"""Native tool registration, Anthropic schemas, and per-role tool name lists."""

from __future__ import annotations

import inspect
import json
import logging
import os
import subprocess
import sys
import threading
from typing import Callable, Dict, List

from .config import (
    AGENT_DESKTOP_CONTROL_ENABLED,
    AGENT_LAUNCH_APPS_ENABLED,
    DESKTOP_SUGGEST_CLICK_REFINE,
    DESKTOP_VISION_MODEL,
    OUTPUT_DIR,
)
from . import desktop_uia as _desktop_uia
from .desktop_skill import DESKTOP_AUTOMATION_TOOL_NAMES
from .contracts import _registry_request_amendment
from .dashboard import get_dashboard
from .browser import get_browser_pool
from .git_worktrees import _get_code_dir
from .llm_client import GEMINI_MODEL, get_client
from .roles import ENG_WORKERS
from .state import _get_agent_id, _get_sprint_num

logger = logging.getLogger("company")

# Windows: align screenshot pixel grid with SendInput / SetCursorPos (HiDPI / scaling).
_desktop_dpi_prep_done = False


def _maybe_windows_desktop_dpi_aware() -> None:
    """Once-per-process best-effort DPI awareness (Windows 8.1+)."""
    global _desktop_dpi_prep_done
    if _desktop_dpi_prep_done or sys.platform != "win32":
        return
    _desktop_dpi_prep_done = True
    if os.getenv("DESKTOP_DISABLE_DPI_AWARE", "").strip().lower() in ("1", "true", "yes", "on"):
        return
    try:
        import ctypes

        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _map_image_coords_to_screen(
    cx: int, cy: int, img_w: int, img_h: int, screen_w: int, screen_h: int
) -> tuple:
    """Map (cx,cy) from screenshot image pixels to PyAutoGUI screen coordinates.

    On scaled displays, ``Image.size`` often differs from ``pyautogui.size()``; the
    vision model labels the image, so we scale to the coordinate space used for clicks.
    Returns ``(sx, sy, did_scale)``."""
    if img_w <= 0 or img_h <= 0 or screen_w <= 0 or screen_h <= 0:
        return cx, cy, False
    if img_w == screen_w and img_h == screen_h:
        sx = max(0, min(screen_w - 1, cx))
        sy = max(0, min(screen_h - 1, cy))
        return sx, sy, False
    sx = int(round(cx * screen_w / img_w))
    sy = int(round(cy * screen_h / img_h))
    sx = max(0, min(screen_w - 1, sx))
    sy = max(0, min(screen_h - 1, sy))
    return sx, sy, True


def _restore_window_if_minimized(win) -> None:
    """``SetForegroundWindow`` alone often leaves a minimized window on the taskbar; restore first."""
    try:
        if getattr(win, "isMinimized", False):
            win.restore()
    except Exception:
        pass


def _activate_window_robust(win) -> None:
    """PyGetWindow ``activate()`` treats SetForegroundWindow==0 as failure; sometimes
    GetLastError is 0 ("success"), producing a bogus exception. Fall back to ctypes."""
    try:
        win.activate()
        return
    except Exception as e:
        msg = str(e)
        bogus = "Error code from Windows: 0" in msg and (
            "success" in msg.lower() or "completed successfully" in msg.lower()
        )
        if bogus:
            logger.info("[desktop_activate_window] ignored PyGetWindow false error (code 0 / success message)")
            return
        if sys.platform == "win32" and hasattr(win, "_hWnd"):
            import ctypes

            hwnd = win._hWnd
            SW_RESTORE = 9
            if ctypes.windll.user32.IsIconic(hwnd):
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return
        raise


# Bind tool impls from tools_impl (star-import skips leading underscores).
from . import tools_impl as _tools_impl

for __k, __v in _tools_impl.__dict__.items():
    if __k.startswith("__"):
        continue
    if __k.startswith("_tool_") or __k in (
        "_strip_subdir_prefix",
        "_subprocess_env_for_project",
        "_bg_index_file",
    ):
        globals()[__k] = __v
del __k, __v, _tools_impl

_TOOL_CALLABLES: Dict[str, Callable] = {}


def _register_tool(fn: Callable) -> Callable:
    """Register a Python function as an Anthropic tool (replaces @lc_tool)."""
    _TOOL_CALLABLES[fn.__name__] = fn
    return fn


def _py_type_to_json_schema(annotation) -> dict:
    """Convert a Python type annotation to a JSON Schema property dict."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return {"type": "string"}
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        args = getattr(annotation, "__args__", (None,))
        item_schema = _py_type_to_json_schema(args[0]) if args and args[0] else {}
        return {"type": "array", "items": item_schema}
    if origin is dict:
        return {"type": "object"}
    _SIMPLE: Dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in _SIMPLE:
        return {"type": _SIMPLE[annotation]}
    return {"type": "string"}


def _make_anthropic_tool_def(fn: Callable) -> dict:
    """Build a native Anthropic tool definition dict from a function's signature + docstring."""
    try:
        hints = {}
        try:
            hints = {k: v for k, v in fn.__annotations__.items() if k != "return"}
        except Exception:
            pass
        sig = inspect.signature(fn)
        props: Dict[str, dict] = {}
        required: List[str] = []
        for name, param in sig.parameters.items():
            annotation = hints.get(name, inspect.Parameter.empty)
            schema = _py_type_to_json_schema(annotation)
            schema["description"] = name
            props[name] = schema
            if param.default is inspect.Parameter.empty:
                required.append(name)
        return {
            "name": fn.__name__,
            "description": (fn.__doc__ or fn.__name__).strip()[:500],
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        }
    except Exception as e:
        logger.warning(f"[tool-def] Failed to build schema for {fn.__name__}: {e}")
        return {
            "name": fn.__name__,
            "description": (fn.__doc__ or fn.__name__).strip()[:500],
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }


def get_role_anthropic_tools(role_key: str) -> List[dict]:
    """Return a list of Anthropic tool definition dicts for the given role."""
    names = _ROLE_TOOL_NAMES.get(role_key, [])
    missing = [n for n in names if n not in _TOOL_CALLABLES]
    if missing:
        logger.warning(f"[{role_key}] tools not found in registry (skipped): {missing}")
    return [_make_anthropic_tool_def(_TOOL_CALLABLES[n]) for n in names if n in _TOOL_CALLABLES]


@_register_tool
def think(thought: str) -> str:
    """Record your architectural reasoning BEFORE writing any code.
    Call this once at the start of a task to think through:
      1. Best design pattern / structure for this file
      2. What makes this code excellent, not just functional
      3. Integration risks with teammate code
      4. Quality improvements beyond the minimum spec
    Use web_search() DURING this phase to research unfamiliar patterns, best practices,
    or library APIs before committing to a design. Has no side effects — purely structures
    your thinking. Returns the thought so you can confirm it was recorded.
    Required before the first write_code_file call."""
    _agent = _get_agent_id() or "unknown"
    logger.info(f"[think:{_agent}] {thought[:120]}")
    return f"Architectural analysis recorded ({len(thought)} chars). Proceed to implementation."


@_register_tool
def run_shell(command: str) -> str:
    """Run a shell command in the project output directory. Use to start services, install deps,
    run tests, or verify the app boots. Returns combined stdout+stderr."""
    return _tool_run_shell(command)


@_register_tool
def http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request to a running service. method: GET/POST/PUT/DELETE.
    body: JSON string for POST/PUT. Returns HTTP status + response body."""
    return _tool_http_request(method, url, body)

@_register_tool
def download_url(url: str, dest_path: str) -> str:
    """Download a file from a public https URL into code/<dest_path> (e.g. assets/textures/grass.png).
    For textures and small binaries; use write_code_file for source. Respects AGENT_DOWNLOAD_MAX_BYTES."""
    return _tool_download_url(url, dest_path)

@_register_tool
def web_search(query: str, focus: str = "") -> str:
    """Search the web for official docs, CLI syntax, install steps, or test commands when the project
    stack is unfamiliar — instead of guessing language-specific commands. Call before run_shell when unsure.
    query: what to look up (e.g. 'deno run typescript', 'gradle test single class').
    focus: optional hint (e.g. 'windows', 'install', 'ci')."""
    return _tool_web_search(query, focus)

@_register_tool
def start_service(name: str, command: str) -> str:
    """Start a long-running background process (server, worker, etc.) and return its startup output.
    name: a label you pick (e.g. 'api', 'frontend') — used to stop it later.
    command: the shell command to launch it (e.g. 'python server.py', 'node index.js').
    Always call stop_service(name) when you're done testing."""
    return _tool_start_service(name, command)

@_register_tool
def stop_service(name: str) -> str:
    """Stop a background service started with start_service(name).
    Always stop services when done — leaving them running blocks ports for teammates."""
    return _tool_stop_service(name)

@_register_tool
def write_code_file(filename: str, content: str) -> str:
    """Write source code to company_output/code/<filename>. Content is the complete file text."""
    return _tool_write_code_file(filename, content)

@_register_tool
def write_file_section(filename: str, section: str, content: str) -> str:
    """Write your code to a specific SECTION of a shared file (like main.py or models.py).
    Use this instead of write_code_file when the file has section-based ownership.
    filename: the shared file path (e.g. 'backend/app/main.py')
    section: section name — use your assigned section or create one with your feature name
    content: the code for JUST this section (not the whole file)"""
    filename = _strip_subdir_prefix(filename, "code")
    agent_id = _get_agent_id()
    dashboard = get_dashboard()

    err = dashboard.write_section(filename, section, agent_id, content)
    if err:
        logger.warning(f"[write_file_section] {agent_id} → {filename}:{section} — {err}")
        return err

    code_dir = _get_code_dir()
    path = code_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    assembled = dashboard.assemble_shared_file(filename)
    path.write_text(assembled, encoding="utf-8")
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    logger.info(f"[write_file_section] {agent_id} wrote section '{section}' in {filename} ({len(content)}c)")
    return (
        f"Written section '{section}' ({len(content)}c) to shared file code/{filename}. "
        f"The assembled file is {len(assembled)}c total."
    )

@_register_tool
def write_test_file(filename: str, content: str) -> str:
    """Write a test file to company_output/tests/<filename>. Content is the complete file text."""
    return _tool_write_test_file(filename, content)

@_register_tool
def write_design_file(filename: str, content: str) -> str:
    """Write a design artifact (markdown, spec) to company_output/design/<filename>."""
    return _tool_write_design_file(filename, content)

@_register_tool
def write_config_file(filename: str, content: str) -> str:
    """Write a config or infra file (Dockerfile, YAML, requirements.txt) to company_output/config/<filename>."""
    return _tool_write_config_file(filename, content)

@_register_tool
def read_file(filename: str, offset: int = 1, limit: int = 200) -> str:
    """Read a file with line numbers. Returns lines in 'lineno: content' format.
    filename: path relative to the project root (e.g. 'app/models.py', 'tests/test_auth.py').
    offset: 1-based line number to start reading from (default 1 = beginning of file).
    limit: max number of lines to return (default 200, max 500).
    When a file is too large to read at once, use offset to read the next window:
      read_file('app/models.py', offset=201) — reads lines 201-400.
    The response footer tells you how many lines remain and what offset to use next."""
    return _tool_read_file(filename, offset, limit)

@_register_tool
def create_directory(relative_path: str, root: str = "code") -> str:
    """Create a folder (and parent folders) under the project. root: code, tests, config, or design."""
    return _tool_create_directory(relative_path, root)

@_register_tool
def delete_file(relative_path: str, root: str = "code") -> str:
    """Delete one file under the project (not a directory). root: code, tests, config, or design."""
    return _tool_delete_file(relative_path, root)

@_register_tool
def remove_empty_directory(relative_path: str, root: str = "code") -> str:
    """Remove one empty directory. Delete files inside first if needed."""
    return _tool_remove_empty_directory(relative_path, root)

@_register_tool
def list_files() -> str:
    """List all source files currently in the project codebase. Call this before writing any file
    to see what already exists. Returns filenames grouped by subdirectory."""
    return _tool_list_files()

@_register_tool
def search_codebase(query: str) -> str:
    """Semantic search over the entire codebase. Returns the most relevant code chunks for your query.
    Use this to find existing implementations before writing new code — e.g. 'authentication middleware',
    'WebSocket handler', 'database models'. Prevents duplicate implementations."""
    return _tool_search_codebase(query)

@_register_tool
def recall_memory(query: str) -> str:
    """Search your role's long-term memory for lessons learned in past sprints.
    query: topic or task description — e.g. 'SQLAlchemy async session', 'React useState hook'.
    Returns bullet list of specific lessons other agents in your role have accumulated.
    Use during THINK phase BEFORE web_search when the question concerns patterns this team has
    already encountered. Also use when stuck — past failure modes are stored here."""
    agent_id = _get_agent_id() or "unknown"
    return _tool_recall_memory(agent_id, query)

@_register_tool
def grep_codebase(pattern: str, glob: str = "", context_lines: int = 0) -> str:
    """Exact regex search across every project file — returns file:line: text, like grep -rn.
    pattern: Python regex (or plain string) to search for, e.g. 'def authenticate', 'TODO', 'import os'.
    glob: optional file-name filter, e.g. '*.py', '*.ts', '*.go' — leave blank to search all files.
    context_lines: lines of context to show before/after each match (like grep -C N), default 0.
    Use this to locate a specific function, class, import, or string when you know what to look for.
    Prefer search_codebase for open-ended semantic discovery; prefer grep_codebase for exact matches."""
    return _tool_grep_codebase(pattern, glob, context_lines)

@_register_tool
def check_dashboard() -> str:
    """MANDATORY FIRST STEP. See current team messages and coordination status.
    Call this to read any incoming messages from teammates."""
    return get_dashboard().get_status()

@_register_tool
def message_teammate(teammate_role: str, message: str) -> str:
    """Send an async message to a teammate. They receive it in Round 2.
    Use in Round 1 to ask about interfaces, warn about dependencies, or request clarification.
    teammate_role: the role key of the recipient e.g. 'frontend_developer', 'devops_engineer'"""
    return get_dashboard().send_message(
        _get_agent_id(), teammate_role, message, _get_sprint_num()
    )

@_register_tool
def check_messages() -> str:
    """MANDATORY FIRST STEP IN ROUND 2. Read messages sent to you by teammates in Round 1.
    Contains interface questions and compatibility concerns you must address."""
    return get_dashboard().get_messages(_get_agent_id())

@_register_tool
def broadcast_message(message: str) -> str:
    """Shout a message to ALL teammates at once — use this when you make a breaking change
    that affects everyone (e.g. renamed a function, changed a shared model, moved a file).
    Every agent will receive it in their next check_messages() call.
    message: plain text description of the change and what others must update."""
    return get_dashboard().broadcast(
        _get_agent_id(), message, _get_sprint_num(), ENG_WORKERS
    )

@_register_tool
def request_contract_amendment(file: str, reason: str, proposed_change: str) -> str:
    """Request a mid-flight change to the shared Interface Contract.
    Use this when you discover the original contract is wrong or impossible to implement
    (e.g. a dependency is unavailable, the API must change shape, a model needs a new field).
    The Engineering Manager will review and broadcast the approved change to the whole team.
    file: the filename in the contract that needs changing (e.g. 'models.py', 'routes.py')
    reason: why the current contract is wrong or insufficient
    proposed_change: exactly what should change (e.g. 'Add field user_id: int to Note model')"""
    return _registry_request_amendment(
        file=file,
        proposer=_get_agent_id() or "unknown",
        reason=reason,
        proposed_change=proposed_change,
    )

@_register_tool
def open_app(url: str) -> str:
    """Open a browser and navigate to a URL to visually verify your feature.
    Acquires one of 3 browser pool slots (waits if all busy). ALWAYS call close_browser() when done.
    url: full URL e.g. 'http://localhost:3000/login' or 'http://localhost:8000/docs'"""
    return get_browser_pool().acquire(url)

@_register_tool
def browser_action(action: str, selector: str, value: str = "") -> str:
    """Interact with the open browser page and see what is on screen.
    action: 'click' | 'type' | 'navigate' | 'screenshot'
    selector: CSS selector for click/type (e.g. 'button[type=submit]', '#email') or URL for navigate
    value: text to type (only for 'type' action)
    Must call open_app() first."""
    return get_browser_pool().action(action, selector, value)

@_register_tool
def close_browser() -> str:
    """Close the browser and release the pool slot so teammates can use it.
    ALWAYS call this when done — not calling it blocks other agents from getting a browser."""
    return get_browser_pool().release()

@_register_tool
def launch_application(command: str) -> str:
    """Start a desktop program or OS \"open\" command without waiting for it to exit.

    Disabled unless AGENT_LAUNCH_APPS_ENABLED=1 — same shell privileges as your user account.

    *command* uses shell=True. Examples: Windows ``notepad``, ``calc``,
    ``start msedge https://example.com``; macOS ``open -a TextEdit``; Linux ``xdg-open path``.

    Process is detached; stdout/stderr are not captured. The model cannot see the GUI window;
    for web pages use open_app() + browser_action().
    """
    if not AGENT_LAUNCH_APPS_ENABLED:
        return (
            "ERROR: launch_application is disabled. Set AGENT_LAUNCH_APPS_ENABLED=1 in the "
            "environment (e.g. .env). Warning: agents can run any shell command you can."
        )
    cmd = (command or "").strip()
    if not cmd:
        return "ERROR: empty command"
    try:
        import subprocess
        # Run from merged product tree so `python main.py` / relative paths resolve.
        launch_root = OUTPUT_DIR / "code"
        launch_root.mkdir(parents=True, exist_ok=True)
        launch_cwd = str(launch_root.resolve())
        launch_env = _subprocess_env_for_project(launch_root)
        if sys.platform == "win32":
            _detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            _newgrp = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=False,
                cwd=launch_cwd,
                env=launch_env,
                creationflags=_detached | _newgrp,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                cwd=launch_cwd,
                env=launch_env,
                start_new_session=True,
            )
        logger.info(f"[launch_application] pid={proc.pid} cmd={cmd[:300]!r}")
        return (
            f"Started detached process pid={proc.pid}. "
            f"No output captured; the agent cannot see the app window. "
            f"For web UIs use open_app + browser_action."
        )
    except Exception as e:
        logger.warning(f"[launch_application] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_list_windows(limit: int = 40) -> str:
    """List top-level windows with non-empty titles and approximate screen bounds.

    Use before ``desktop_activate_window`` when the target app is not focused.
    Typical flow: ``desktop_list_windows`` → ``desktop_activate_window`` →
    ``desktop_screenshot`` → ``desktop_suggest_click`` → ``desktop_mouse`` / ``desktop_keyboard``.
    Rows may include ``[minimized]`` — those windows are not usable for screenshots until activated.

    ``limit``: maximum number of rows (clamped 1–200).
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow window listing."
        )
    try:
        lim = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        lim = 40
    try:
        import pygetwindow as gw
    except ImportError:
        return (
            "ERROR: PyGetWindow is not installed. Run: pip install PyGetWindow\n"
            "(Desktop window tools require it; Linux support may be limited.)"
        )
    try:
        rows: List[tuple] = []
        for w in gw.getAllWindows():
            try:
                title = (w.title or "").strip()
                if not title:
                    continue
                mini = bool(getattr(w, "isMinimized", False))
                rows.append((title, w.left, w.top, w.width, w.height, mini))
            except Exception:
                continue
        if not rows:
            return (
                "No titled windows returned. On some platforms PyGetWindow returns little or nothing; "
                "try desktop_screenshot() to see the screen instead."
            )
        lines: List[str] = []
        for i, (title, left, top, width, height, mini) in enumerate(rows[:lim], start=1):
            tag = "  [minimized]" if mini else ""
            lines.append(f"{i}. {title!r}  rect=({left}, {top}, {width}x{height}){tag}")
        n = len(lines)
        return (
            f"Windows (showing {n} of {len(rows)}, limit={lim}):\n"
            + "\n".join(lines)
            + "\n\nMinimized windows do not appear in full-screen captures — call "
            "desktop_activate_window first to restore and focus.\n"
            "Next: desktop_activate_window('unique substring of title') then desktop_screenshot()."
        )
    except Exception as e:
        logger.warning(f"[desktop_list_windows] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_activate_window(title_substring: str) -> str:
    """Bring the first window whose title contains ``title_substring`` to the foreground.

    On Windows, **restores from minimized** first so the window is visible for screenshots and clicks.
    Match is case-insensitive. If multiple match, the first enumeration order wins —
    use a longer substring from ``desktop_list_windows`` if needed.
    Flow: list → activate → screenshot → suggest_click → mouse/keyboard.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow window activation."
        )
    sub = (title_substring or "").strip()
    if not sub:
        return "ERROR: 'title_substring' is required (see desktop_list_windows for titles)"
    try:
        import time

        import pygetwindow as gw
    except ImportError:
        return (
            "ERROR: PyGetWindow is not installed. Run: pip install PyGetWindow\n"
            "(Desktop window tools require it; Linux support may be limited.)"
        )
    try:
        sub_l = sub.lower()
        candidates: List = []
        for w in gw.getAllWindows():
            try:
                title = (w.title or "").strip()
                if sub_l in title.lower():
                    candidates.append(w)
            except Exception:
                continue
        if not candidates:
            return (
                f"ERROR: no window with title containing {sub!r}. "
                "Call desktop_list_windows() and pick an exact substring."
            )
        win = candidates[0]
        _maybe_windows_desktop_dpi_aware()
        _restore_window_if_minimized(win)
        _activate_window_robust(win)
        time.sleep(0.12)
        logger.info(f"[desktop_activate_window] activated {win.title!r}")
        return (
            f"Activated window: {win.title!r} (restored if it was minimized). "
            "Next: desktop_screenshot() then desktop_suggest_click / desktop_mouse / desktop_keyboard."
        )
    except Exception as e:
        logger.warning(f"[desktop_activate_window] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_uia_list_elements(
    title_substring: str,
    name_filter: str = "",
    control_type: str = "",
    limit: int = 60,
) -> str:
    """Windows only. List interactive UI Automation elements under the first window whose title
    contains ``title_substring`` (same matching style as ``desktop_activate_window``).
    OpenClaw-style workflow: after focusing the app, use this before pixel/vision clicks when
    controls expose names. Columns: index, ControlType, Name, screen rect, AutomationId.
    ``name_filter``: optional substring (case-insensitive) matched against control Name.
    ``control_type``: optional substring matched against ControlTypeName (e.g. ``Button``, ``Edit``).
    ``limit``: max rows (1–200). Requires AGENT_DESKTOP_CONTROL_ENABLED=1 and ``pip install uiautomation``."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow UIA tools."
        )
    return _desktop_uia.list_elements(title_substring, name_filter, control_type, limit)


@_register_tool
def desktop_uia_read_text(title_substring: str, max_chars: int = 8000) -> str:
    """Windows only. Collect non-empty UIA ``Name`` values under the matched window (no OCR).
    Use to verify dialogs or forms when automation names are exposed. Caps output length with
    ``max_chars``. Requires AGENT_DESKTOP_CONTROL_ENABLED=1 and ``pip install uiautomation``."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow UIA tools."
        )
    return _desktop_uia.read_text(title_substring, max_chars)


@_register_tool
def desktop_uia_click(
    title_substring: str,
    name_substring: str,
    control_type: str = "",
) -> str:
    """Windows only. Click the single interactive control whose Name contains ``name_substring``
    (case-insensitive). Scope to the first matching top-level window (``title_substring``).
    Optional ``control_type`` substring disambiguates (e.g. ``Button``). Uses UIA ``Click`` with
    pyautogui center fallback. If 0 or multiple matches, returns ERROR — narrow strings or call
    ``desktop_uia_list_elements`` first. Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow UIA tools."
        )
    return _desktop_uia.click_named(
        title_substring,
        name_substring,
        control_type,
        dpi_prep=_maybe_windows_desktop_dpi_aware,
    )


@_register_tool
def desktop_screenshot() -> str:
    """Take a full-screen screenshot and return a Gemini vision description of what is visible.
    Minimized windows are not shown — call desktop_activate_window(title) first to restore them.
    Call before and after desktop_mouse/desktop_keyboard actions to verify the result.
    For click targets use desktop_suggest_click('description') first — it captures the screen
    and returns coordinates matched to the current layout.
    Returns: resolution, cursor position, and a natural-language description of the screen.
    Uses ``DESKTOP_VISION_MODEL`` when set, else ``GEMINI_MODEL``.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1 in the environment."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment (e.g. .env). Warning: agents will be able to see and control your screen."
        )
    try:
        import pyautogui
        import base64, io

        _maybe_windows_desktop_dpi_aware()
        screen_w, screen_h = pyautogui.size()
        cx, cy = pyautogui.position()
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        try:
            resp = get_client().models.generate_content(
                model=_desktop_vision_model(),
                contents=[{
                    "parts": [
                        {"text": (
                            "Describe what is visible on this screenshot in detail: "
                            "list all open windows, visible text, UI elements, and their positions. "
                            "If you see an application, name it. Be specific and concise."
                        )},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    ]
                }],
            )
            vision = resp.text.strip()
        except Exception as e:
            vision = f"(vision unavailable: {e})"
        iw, ih = img.size
        cap_note = ""
        if iw != screen_w or ih != screen_h:
            cap_note = f"  capture={iw}x{ih} (use desktop_suggest_click for scaled clicks)\n"
        return (
            f"Screen: {screen_w}x{screen_h}  "
            f"display_width_px={screen_w}  display_height_px={screen_h}  "
            f"Cursor: ({cx},{cy})\n"
            f"{cap_note}"
            f"Visible: {vision}"
        )
    except ImportError:
        return (
            "ERROR: pyautogui is not installed. Run: pip install pyautogui\n"
            "Linux may also need: sudo apt-get install python3-xlib python3-tk"
        )
    except Exception as e:
        logger.warning(f"[desktop_screenshot] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_mouse(
    action: str,
    x: int = -1,
    y: int = -1,
    button: str = "left",
    clicks: int = 1,
    scroll_direction: str = "down",
) -> str:
    """Control the mouse anywhere on screen.
    action: 'move' | 'click' | 'double_click' | 'right_click' | 'scroll'
    x, y: screen coordinates in pixels from the top-left corner (-1 = current cursor position)
    button: 'left' | 'right' | 'middle'  (for click actions)
    clicks: number of scroll ticks  (only for 'scroll')
    scroll_direction: 'up' | 'down'  (only for 'scroll')
    Call desktop_screenshot() afterwards to see what changed.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow mouse control."
        )
    try:
        import pyautogui, time

        _maybe_windows_desktop_dpi_aware()
        pyautogui.FAILSAFE = True   # move to corner to abort
        pyautogui.MINIMUM_DURATION = 0
        pyautogui.PAUSE = 0.02
        act = (action or "").strip().lower()
        # Resolve coordinates — -1 means stay at current position
        cur_x, cur_y = pyautogui.position()
        tx = cur_x if x < 0 else x
        ty = cur_y if y < 0 else y

        if act == "move":
            pyautogui.moveTo(tx, ty, duration=0.05)
        elif act == "click":
            pyautogui.click(tx, ty, button=button)
        elif act == "double_click":
            pyautogui.doubleClick(tx, ty)
        elif act == "right_click":
            pyautogui.rightClick(tx, ty)
        elif act == "scroll":
            pyautogui.moveTo(tx, ty, duration=0.05)
            amount = clicks if scroll_direction == "up" else -clicks
            pyautogui.scroll(amount)
        else:
            return f"ERROR: unknown action {action!r}. Use: move | click | double_click | right_click | scroll"

        time.sleep(0.12)
        nx, ny = pyautogui.position()
        logger.info(f"[desktop_mouse] {act} at ({tx},{ty}) button={button}")
        return f"Done: {act} at ({tx},{ty}). Cursor now at ({nx},{ny}). Call desktop_screenshot() to see the result."
    except ImportError:
        return "ERROR: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as e:
        logger.warning(f"[desktop_mouse] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_keyboard(action: str, text: str = "", keys: str = "") -> str:
    """Type text or press keyboard shortcuts on the currently focused window.
    action: 'type' | 'hotkey' | 'press'
      'type'   → types text character by character (use for filling in fields)
      'hotkey' → holds keys simultaneously, e.g. keys='ctrl,c' for copy, 'ctrl,z' for undo
      'press'  → taps one or more keys sequentially, e.g. keys='enter' or keys='tab,tab,enter'
    text: the string to type  (only for 'type')
    keys: comma-separated key names  (for 'hotkey' and 'press')
    Key names: enter, tab, space, backspace, delete, escape, up, down, left, right,
               f1..f12, ctrl, alt, shift, win, a..z, 0..9, etc.
    Call desktop_screenshot() first to confirm focus on the right field.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow keyboard control."
        )
    try:
        import pyautogui, time

        _maybe_windows_desktop_dpi_aware()
        pyautogui.PAUSE = 0.02
        act = (action or "").strip().lower()
        if act == "type":
            if not text:
                return "ERROR: 'text' is required for action='type'"
            pyautogui.write(text, interval=0.02)
            time.sleep(0.05)
            logger.info(f"[desktop_keyboard] type {len(text)} chars")
            return f"Typed {len(text)} characters. Call desktop_screenshot() to verify."
        elif act == "hotkey":
            if not keys:
                return "ERROR: 'keys' is required for action='hotkey' (e.g. 'ctrl,c')"
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
            pyautogui.hotkey(*key_list)
            time.sleep(0.08)
            logger.info(f"[desktop_keyboard] hotkey {key_list}")
            return f"Pressed hotkey: {'+'.join(key_list)}. Call desktop_screenshot() to verify."
        elif act == "press":
            if not keys:
                return "ERROR: 'keys' is required for action='press' (e.g. 'enter' or 'tab,tab,enter')"
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
            for k in key_list:
                pyautogui.press(k)
                time.sleep(0.03)
            logger.info(f"[desktop_keyboard] press {key_list}")
            return f"Pressed key(s): {', '.join(key_list)}. Call desktop_screenshot() to verify."
        else:
            return f"ERROR: unknown action {action!r}. Use: type | hotkey | press"
    except ImportError:
        return "ERROR: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as e:
        logger.warning(f"[desktop_keyboard] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


def _desktop_vision_model() -> str:
    """Model id for screen understanding; override with DESKTOP_VISION_MODEL for sharper clicks."""
    return (DESKTOP_VISION_MODEL or "").strip() or GEMINI_MODEL


def _parse_click_coords_json(raw: str) -> tuple:
    """Parse vision JSON: bbox (preferred) or x/y; nulls with reason."""
    import re

    t = (raw or "").strip()
    if "```" in t:
        for part in t.split("```"):
            part = part.strip()
            if part.lower().startswith("json"):
                part = part[4:].lstrip()
            if part.startswith("{"):
                t = part
                break
    m = re.search(r"\{[\s\S]*\}", t)
    if not m:
        return None, None, "no JSON object in model response"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, None, f"invalid JSON: {e}"

    el = str(obj.get("element") or "").strip()
    bbox = obj.get("bbox")
    if bbox is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            x1, y1, x2, y2 = (int(round(float(bbox[i]))) for i in range(4))
            if x1 > x2:
                x1, x2 = x2, x1
            if y1 > y2:
                y1, y2 = y2, y1
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            note = el or "bbox"
            return cx, cy, note
        except (TypeError, ValueError):
            pass

    x, y = obj.get("x"), obj.get("y")
    if x is None or y is None:
        reason = obj.get("reason") or el or "target not found"
        return None, None, str(reason)
    try:
        return int(round(float(x))), int(round(float(y))), el
    except (TypeError, ValueError):
        return None, None, "x/y not numeric"


@_register_tool
def desktop_suggest_click(target: str) -> str:
    """Find where to click on the *current* screen for a described UI control.

    Captures a fresh screenshot and asks the vision model for pixel coordinates in
    **image** space (top-left of the PNG, x right, y down). Values are mapped to
    **screen** coordinates for ``desktop_mouse`` when capture size differs from
    ``pyautogui.size()`` (Windows display scaling).

    ``target``: short phrase, e.g. "OK button", "Run menu", "text field labeled Name".

    Vision quality: set ``DESKTOP_VISION_MODEL`` to a stronger Gemini vision model than
    ``GEMINI_MODEL`` if clicks are imprecise. Optional ``DESKTOP_SUGGEST_CLICK_REFINE=1``
    runs a second vision pass on a crop around the first guess (slower, often tighter).

    Does not move the mouse. On failure returns ERROR: ... (e.g. target not visible).
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow screen capture."
        )
    tgt = (target or "").strip()
    if not tgt:
        return "ERROR: 'target' is required (what to click, e.g. 'Submit button')"
    try:
        import base64
        import io

        import pyautogui

        _maybe_windows_desktop_dpi_aware()
        screen_w, screen_h = pyautogui.size()
        img = pyautogui.screenshot()
        w, h = img.size
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        vision_model = _desktop_vision_model()
        prompt = (
            f"You are localizing a UI control for mouse input. Screenshot size {w}x{h} pixels "
            f"(width × height, origin top-left, x right, y down).\n"
            f"Target to click: {tgt!r}.\n\n"
            "Rules:\n"
            "- Put the click on the **actual interactive widget** (button rectangle, link, checkbox), "
            "not on static instructional text above/beside it.\n"
            "- For a **labeled button** (e.g. visible label text on the button face): bbox must wrap only the "
            "**raised/flat button chrome** that receives the click, not the whole window and not a "
            "separate caption line above the button. The center (x,y) must land **on the button face**.\n"
            "- Prefer a **tight** box; oversized boxes produce wrong centers.\n\n"
            "Reply with ONLY one JSON object, no markdown, no code fences. Prefer a tight axis-aligned "
            "bounding box in **image pixel coordinates**:\n"
            '  "bbox": [x1, y1, x2, y2]  — corners of the smallest rectangle that fully contains the '
            "clickable control (button face, not whole window).\n"
            '  "element": short label of what you boxed\n'
            "If you cannot box it reliably, omit bbox and instead give:\n"
            '  "x": <int>, "y": <int>  — center of the clickable area\n'
            "Do not guess: if the target is not visible, use "
            '"x": null, "y": null, "bbox": null, "reason": "why not visible".'
        )
        try:
            resp = get_client().models.generate_content(
                model=vision_model,
                contents=[{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    ],
                }],
            )
            raw = (getattr(resp, "text", None) or "").strip()
        except Exception as e:
            return f"ERROR: vision request failed: {e}"
        ix, iy, note = _parse_click_coords_json(raw)
        if ix is None or iy is None:
            return f"ERROR: could not locate click target ({note}). Raw: {raw[:500]!r}"
        ix = max(0, min(w - 1, ix))
        iy = max(0, min(h - 1, iy))

        if DESKTOP_SUGGEST_CLICK_REFINE:
            try:
                margin = int((os.getenv("DESKTOP_SUGGEST_REFINE_MARGIN") or "160").strip() or "160")
            except ValueError:
                margin = 160
            margin = max(48, min(margin, min(w, h) // 2))
            left = max(0, ix - margin)
            top = max(0, iy - margin)
            right = min(w, ix + margin)
            bottom = min(h, iy + margin)
            if right - left >= 32 and bottom - top >= 32:
                crop = img.crop((left, top, right, bottom))
                cw, ch = crop.size
                cbuf = io.BytesIO()
                crop.save(cbuf, format="PNG")
                crop_b64 = base64.b64encode(cbuf.getvalue()).decode()
                rprompt = (
                    f"Cropped region {cw}x{ch} pixels from a larger screenshot. "
                    f"In the full image this crop's top-left was at ({left},{top}).\n"
                    f"Find the best single click point for: {tgt!r}.\n"
                    "Reply ONLY JSON: {\"x\": <int>, \"y\": <int>} relative to THIS crop "
                    "(0,0 = top-left of crop). Center of the button/control. "
                    "If not visible here: {\"x\": null, \"y\": null, \"reason\": \"...\"}."
                )
                try:
                    rresp = get_client().models.generate_content(
                        model=vision_model,
                        contents=[{
                            "parts": [
                                {"text": rprompt},
                                {"inline_data": {"mime_type": "image/png", "data": crop_b64}},
                            ],
                        }],
                    )
                    rraw = (getattr(rresp, "text", None) or "").strip()
                    rx, ry, _ = _parse_click_coords_json(rraw)
                    if rx is not None and ry is not None:
                        nix = max(0, min(w - 1, left + rx))
                        niy = max(0, min(h - 1, top + ry))
                        logger.info(
                            f"[desktop_suggest_click] refine crop=({left},{top})-({right},{bottom}) "
                            f"local=({rx},{ry}) -> image=({nix},{niy}) was=({ix},{iy})"
                        )
                        ix, iy = nix, niy
                except Exception as _ref_e:
                    logger.warning(f"[desktop_suggest_click] refine pass failed: {_ref_e}")
        sx, sy, scaled = _map_image_coords_to_screen(ix, iy, w, h, screen_w, screen_h)
        scale_hint = ""
        if scaled:
            scale_hint = f" (image {w}x{h} → screen {screen_w}x{screen_h}: mapped {ix},{iy} → {sx},{sy})"
        logger.info(
            f"[desktop_suggest_click] model={vision_model!r} target={tgt!r} image=({ix},{iy}) "
            f"screen=({sx},{sy}) scaled={scaled} note={note!r}"
        )
        _lite = "lite" in (vision_model or "").lower()
        _retry = (
            " After desktop_mouse + desktop_screenshot: if the click clearly missed (cursor wrong, "
            "button not pressed), call desktop_suggest_click again with a **narrower** target "
            "(e.g. exact button label only) or use desktop_uia_click on Windows if the control has "
            "a UIA name — retry up to 2–3 times; one bad vision box is common."
        )
        _model_hint = ""
        if _lite:
            _model_hint = (
                " Vision is using a *lite* model — clicks are often imprecise; set DESKTOP_VISION_MODEL "
                "to a stronger Gemini vision id, and/or DESKTOP_SUGGEST_CLICK_REFINE=1 for a second crop pass."
            )
        return (
            f"Suggested click for {tgt!r}: use screen coordinates ({sx}, {sy}) for desktop_mouse"
            + (f" — {note}" if note else "")
            + f".{scale_hint} (vision_model={vision_model})"
            f" Next: desktop_mouse('click', {sx}, {sy}).{_retry}{_model_hint}"
        )
    except ImportError:
        return "ERROR: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as e:
        logger.warning(f"[desktop_suggest_click] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_zoom_region(x1: int, y1: int, x2: int, y2: int, hint: str = "") -> str:
    """Zoom into a rectangular screen region for detailed inspection before clicking.

    Captures the current screen, crops the region [x1,y1] → [x2,y2] (screen pixel
    coords), sends the crop to the vision model, and returns a detailed description
    of every UI element visible inside that area.

    Use this as STEP 2 of the computer-use loop when you cannot reliably identify a
    click target from the full-screen screenshot — 'zoom in, then click'.

    x1, y1: top-left corner of the region (screen coordinates)
    x2, y2: bottom-right corner of the region (screen coordinates)
    hint:   optional description of what you are looking for (e.g. 'Submit button')

    If the vision model identifies a single best click target, CLICK_AT_CROP
    coordinates are translated back to full-screen (sx, sy) for desktop_mouse.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    from .computer_use import zoom_region_impl  # deferred to avoid circular import
    return zoom_region_impl(x1, y1, x2, y2, hint=hint)


@_register_tool
def validate_python(code: str) -> str:
    """Check Python code for syntax errors. Returns 'Python syntax OK' or a description of the error."""
    return _tool_validate_python(code)

@_register_tool
def validate_json(content: str) -> str:
    """Validate a JSON string. Returns 'JSON valid' or error details."""
    return _tool_validate_json(content)

@_register_tool
def validate_yaml(content: str) -> str:
    """Validate a YAML string (Dockerfile, CI config, etc.). Returns 'YAML valid' or error details."""
    return _tool_validate_yaml(content)

@_register_tool
def generate_endpoint_table(endpoints: List[Dict]) -> str:
    """Generate a markdown table of API endpoints. Each endpoint needs: method, path, description, auth."""
    return _tool_generate_endpoint_table(json.dumps(endpoints))

@_register_tool
def generate_er_diagram(tables: List[Dict]) -> str:
    """Generate an ASCII ER diagram. Each table needs: name, fields (list of {name, type, pk, fk})."""
    return _tool_generate_er_diagram(json.dumps(tables))

@_register_tool
def create_ascii_diagram(components: List[Dict]) -> str:
    """Generate an ASCII component diagram. Each component needs: name, connects_to (list of names)."""
    return _tool_create_ascii_diagram(json.dumps(components))

@_register_tool
def create_user_flow(steps: List[Dict]) -> str:
    """Generate an ASCII user flow diagram. Each step needs: step (label), action, outcome."""
    return _tool_create_user_flow(json.dumps(steps))

@_register_tool
def create_wireframe(page_name: str, sections: List[Dict]) -> str:
    """Generate an ASCII wireframe for a UI page. Each section needs: name, type, content."""
    return _tool_create_wireframe(page_name, json.dumps(sections))

@_register_tool
def create_style_guide(colors: Dict, fonts: Dict, spacing: Dict) -> str:
    """Generate a formatted style guide. colors/fonts/spacing are dicts of token→value."""
    return _tool_create_style_guide(json.dumps({"colors": colors, "fonts": fonts, "spacing": spacing}))

@_register_tool
def scan_vulnerabilities(code: str) -> str:
    """Scan code for common security vulnerabilities (OWASP patterns). Returns severity-labelled findings."""
    return _tool_scan_vulnerabilities(code)

@_register_tool
def check_owasp(feature: str) -> str:
    """Get relevant OWASP Top 10 risks for a feature. Feature: auth, api, input, session, file_upload, database."""
    return _tool_check_owasp(feature)

# Same mapping as _TOOL_CALLABLES — tests and external code expect this name.
_LC_TOOLS_BY_NAME: Dict[str, Callable] = _TOOL_CALLABLES

# Dashboard tools available to all roles that write or review work
_DASHBOARD_TOOLS    = ["check_dashboard", "message_teammate", "check_messages",
                       "broadcast_message", "request_contract_amendment"]
_DASHBOARD_RO_TOOLS = ["check_dashboard", "message_teammate", "check_messages"]  # read-only for QA/arch

_ROLE_TOOL_NAMES: Dict[str, List[str]] = {
    "system_designer":    ["create_ascii_diagram", "write_design_file", "read_file",
                           "list_files", "search_codebase", "grep_codebase", "web_search",
                           "recall_memory"] + _DASHBOARD_RO_TOOLS,
    "api_designer":       ["generate_endpoint_table", "validate_yaml", "write_design_file",
                           "read_file", "list_files", "search_codebase", "grep_codebase", "web_search",
                           "recall_memory"] + _DASHBOARD_RO_TOOLS,
    "db_designer":        ["generate_er_diagram", "write_design_file", "read_file",
                           "list_files", "search_codebase", "grep_codebase", "web_search",
                           "recall_memory"] + _DASHBOARD_RO_TOOLS,
    "ux_researcher":      ["create_user_flow", "write_design_file", "read_file",
                           "list_files", "search_codebase", "grep_codebase", "web_search",
                           "recall_memory"] + _DASHBOARD_RO_TOOLS,
    "ui_designer":        ["create_wireframe", "write_design_file", "read_file",
                           "list_files", "search_codebase", "grep_codebase", "web_search",
                           "recall_memory"] + _DASHBOARD_RO_TOOLS,
    "visual_designer":    ["create_style_guide", "write_design_file", "read_file",
                           "list_files", "search_codebase", "grep_codebase", "web_search",
                           "recall_memory"] + _DASHBOARD_RO_TOOLS,
    "unit_tester":        ["write_test_file", "validate_python", "scan_vulnerabilities",
                           "web_search", "run_shell", "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase", "grep_codebase", "recall_memory",
                           "open_app", "browser_action", "close_browser", "launch_application",
                           *DESKTOP_AUTOMATION_TOOL_NAMES,
                           ] + _DASHBOARD_RO_TOOLS,
    "integration_tester": ["write_test_file", "validate_python", "validate_json", "web_search",
                           "run_shell", "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase", "grep_codebase", "recall_memory",
                           "open_app", "browser_action", "close_browser", "launch_application",
                           *DESKTOP_AUTOMATION_TOOL_NAMES,
                           ] + _DASHBOARD_RO_TOOLS,
    "security_auditor":   ["write_test_file", "scan_vulnerabilities", "check_owasp", "web_search",
                           "run_shell", "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase", "grep_codebase", "recall_memory",
                           "open_app", "browser_action", "close_browser", "launch_application",
                           *DESKTOP_AUTOMATION_TOOL_NAMES,
                           ] + _DASHBOARD_RO_TOOLS,
}
_DEV_TOOL_NAMES = ["think",
                   "write_code_file", "write_file_section", "write_test_file",
                   "validate_python", "validate_json",
                   "validate_yaml", "write_config_file", "read_file",
                   "create_directory", "delete_file", "remove_empty_directory",
                   "run_shell",
                   "list_files", "search_codebase", "grep_codebase", "recall_memory",
                   "start_service", "stop_service",
                   "http_request", "download_url", "web_search",
                   "open_app", "browser_action", "close_browser", "launch_application",
                   *DESKTOP_AUTOMATION_TOOL_NAMES,
                   # Full dashboard / messaging suite — Gemini SDK raises KeyError
                   # if the model tries to call a function that isn't in the tool list,
                   # so all known tools must be registered even if prompts de-emphasise them.
                   "check_dashboard", "check_messages",
                   "message_teammate", "broadcast_message", "request_contract_amendment"]

# Subset used on retries after a no-write round — read/browse/poll tools stripped
# so the model has no choice but to write.
_DEV_WRITE_ONLY_TOOL_NAMES = [
    "write_code_file", "write_file_section", "write_test_file",
    "write_config_file", "validate_python", "validate_json", "validate_yaml",
    "create_directory", "delete_file", "remove_empty_directory",
    "run_shell", "start_service", "stop_service", "download_url", "web_search",
]

def _dev_tools_for_attempt(role_key: str, retry_count: int) -> List[str]:
    """Return the appropriate tool list for a dev agent.
    Always returns the full toolset — narrowing to write-only caused the model to
    attempt calling list_files anyway; Gemini AFC rejects those unknown function
    calls silently, burning all 25 rounds with 0 Python invocations.
    Instead, retries inject file content directly into the prompt so the model
    already has context and doesn't need to call list_files.
    """
    if not role_key.startswith("dev_"):
        return _ROLE_TOOL_NAMES.get(role_key, [])
    return _DEV_TOOL_NAMES

# Engineering manager gets full file access + service tools for integration pass
_ENG_MANAGER_TOOL_NAMES = [
    "read_file", "list_files", "search_codebase", "grep_codebase", "recall_memory",
    "write_code_file", "write_config_file",
    "create_directory", "delete_file", "remove_empty_directory",
    "validate_python", "validate_json", "validate_yaml",
    "run_shell", "start_service", "stop_service", "http_request", "download_url", "web_search",
    "launch_application",
    *DESKTOP_AUTOMATION_TOOL_NAMES,
] + _DASHBOARD_RO_TOOLS


def get_role_lc_tools(role_key: str) -> List[dict]:
    """Return list of Anthropic tool definition dicts for this role (alias for get_role_anthropic_tools)."""
    return get_role_anthropic_tools(role_key)
