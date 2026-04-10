#!/usr/bin/env python3
"""
Run the **real** Engineering Manager fix loop (final integration stage) — live LLM + real tools.

This is NOT a unit test: it calls Gemini, may run ``start_service``, ``desktop_screenshot``,
``desktop_mouse``, ``write_code_file``, etc. Use it to verify desktop control and that the
manager actually mutates the project.

Prerequisites
-------------
- ``GEMINI_API_KEY`` in the environment (same as the rest of Quantum Swarm).
- Optional but recommended for **real** GUI screen verification (default):
    ``AGENT_DESKTOP_CONTROL_ENABLED=1`` and ``pip install pyautogui``
- For **reliable** clicks on this smoke Tk window (Windows): ``pip install uiautomation`` then
    ``desktop_uia_click('Manager stage smoke', 'Hello')`` — vision-only ``desktop_suggest_click`` is
    often wrong with *flash-lite* models; use ``DESKTOP_VISION_MODEL`` + a non-lite vision id and/or
    ``DESKTOP_SUGGEST_CLICK_REFINE=1`` if you rely on pixels.
- For **headless / CI-style** GUI projects (pytest only, no mouse):
    ``MANAGER_GUI_DESKTOP_PROOF=0`` — manager passes with ``start_service`` + green tests, no ``desktop_*`` proof.
- Sharper **vision clicks** (optional): ``DESKTOP_VISION_MODEL=<stronger-gemini-vision-id>``;
    second pass: ``DESKTOP_SUGGEST_CLICK_REFINE=1`` (optional ``DESKTOP_SUGGEST_REFINE_MARGIN=160``).
- **Live screen on every manager turn** (optional): ``DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC=1`` —
    buffers a full-screen PNG on that interval and attaches the latest to each ``eng_manager``
    opening message (comma-separated ``DESKTOP_LIVE_SNAPSHOT_ROLES`` to add roles).
- Default chat model is ``gemini-3.1-flash-preview`` (override with ``GEMINI_MODEL``).
- Opt-in guard (prevents accidental spend):
    ``RUN_MANAGER_STAGE_SMOKE=1``

Usage (PowerShell)::

    $env:RUN_MANAGER_STAGE_SMOKE = "1"
    $env:GEMINI_API_KEY = "<your-key>"
    $env:AGENT_DESKTOP_CONTROL_ENABLED = "1"   # for real mouse/keyboard
    python run_manager_stage_smoke.py

    # If HTTP logs still show ``gemini-3.1-flash-lite-preview``, your shell or .env sets GEMINI_MODEL.
    # Fix: ``$env:MANAGER_SMOKE_USE_CONFIG_GEMINI = "1"`` or ``python run_manager_stage_smoke.py --gemini-model gemini-3.1-flash-preview``

Usage (cmd)::

    set RUN_MANAGER_STAGE_SMOKE=1
    set GEMINI_API_KEY=...
    set AGENT_DESKTOP_CONTROL_ENABLED=1
    python run_manager_stage_smoke.py

Output defaults to ``manager_smoke_output/`` (separate from ``eng_output/`` and ``company_output/``).

What to watch in the log
------------------------
- Lines like ``[TOOL: start_service]``, ``[TOOL: desktop_mouse|ok]``, ``[TOOL: write_code_file]``
- ``[ManagerFix]`` summary and whether ``passed`` is True
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock

from dotenv import load_dotenv

# Load repo `.env` first so `GEMINI_API_KEY` matches Cursor/IDE. `override=True` fixes the case
# where a bad or placeholder key is in the shell env and would otherwise win over `.env`.
_REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(_REPO_ROOT / ".env", override=True)
load_dotenv(override=True)

_SMOKE_DEFAULT_GEMINI = "gemini-3.1-flash-preview"


def _consume_smoke_early_argv() -> None:
    """Handle ``--gemini-model <id>`` before ``import software_company`` (so config picks it up)."""
    out: list[str] = [sys.argv[0]]
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--gemini-model" and i + 1 < len(sys.argv):
            os.environ["GEMINI_MODEL"] = sys.argv[i + 1].strip()
            i += 2
            continue
        out.append(sys.argv[i])
        i += 1
    sys.argv[:] = out


_consume_smoke_early_argv()

# Force repo default model for this script only (overrides a stale shell GEMINI_MODEL=e.g. flash-lite).
if os.getenv("MANAGER_SMOKE_USE_CONFIG_GEMINI", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
):
    os.environ["GEMINI_MODEL"] = _SMOKE_DEFAULT_GEMINI
elif not (os.environ.get("GEMINI_MODEL") or "").strip():
    os.environ["GEMINI_MODEL"] = _SMOKE_DEFAULT_GEMINI

# ── Must set output tree before heavy imports use OUTPUT_DIR ─────────────────
if os.environ.get("RUN_MANAGER_STAGE_SMOKE", "").strip().lower() not in (
    "1",
    "true",
    "yes",
    "on",
):
    print(
        "Refusing to run: set RUN_MANAGER_STAGE_SMOKE=1 to confirm you want a live LLM + tool run.",
        file=sys.stderr,
    )
    sys.exit(2)

if not os.environ.get("GEMINI_API_KEY", "").strip():
    print(
        "Refusing to run: GEMINI_API_KEY is not set. Add it to .env in the repo root "
        "(or export it).",
        file=sys.stderr,
    )
    sys.exit(2)

import software_company as sc
import software_company.config as _smoke_cfg


def _resync_gemini_model_modules(model: str) -> None:
    """Submodules keep their own ``GEMINI_MODEL`` binding; align after env/dotenv tweaks."""
    _smoke_cfg.GEMINI_MODEL = model
    sc.GEMINI_MODEL = model
    try:
        import software_company.llm_client as _lc

        _lc.GEMINI_MODEL = model
    except Exception:
        pass
    try:
        import software_company.agent_loop as _al

        _al.GEMINI_MODEL = model
    except Exception:
        pass
    try:
        import software_company.tool_registry as _tr

        _tr.GEMINI_MODEL = model
    except Exception:
        pass
    try:
        import software_company.browser as _br

        _br.GEMINI_MODEL = model
    except Exception:
        pass


_resync_gemini_model_modules(_smoke_cfg.GEMINI_MODEL)


def _resync_desktop_vision_bindings() -> None:
    """Re-read DESKTOP_* from ``os.environ`` and push into config + tool_registry.

    ``from .config import DESKTOP_VISION_MODEL`` keeps a stale copy in submodules unless we
    reassign after ``load_dotenv``. Also surfaces common mistake: vars only in an unsaved editor
    buffer never reach the process environment.
    """
    dvm = (os.environ.get("DESKTOP_VISION_MODEL") or "").strip()
    refine_on = (os.getenv("DESKTOP_SUGGEST_CLICK_REFINE") or "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    _smoke_cfg.DESKTOP_VISION_MODEL = dvm
    _smoke_cfg.DESKTOP_SUGGEST_CLICK_REFINE = refine_on
    try:
        import software_company.tool_registry as _tr

        _tr.DESKTOP_VISION_MODEL = dvm
        _tr.DESKTOP_SUGGEST_CLICK_REFINE = refine_on
    except Exception:
        pass


_resync_desktop_vision_bindings()

# Force Gemini client to use the key from env after `load_dotenv` (singleton may not exist yet).
try:
    import software_company.llm_client as _llm_client

    _llm_client._client = None
except Exception:
    pass

_DEFAULT_OUT = Path("manager_smoke_output")


def _apply_output_dir(out: Path) -> None:
    """Mirror ``run_engineers_only.py``: set package OUTPUT_DIR and refresh submodule bindings."""
    out = out.resolve()
    sc.OUTPUT_DIR = out
    import software_company.config as cfg

    cfg.OUTPUT_DIR = out
    cfg.TEAM_CANONICAL_FILES = {
        "Architecture": out / "design" / "architecture_spec.md",
        "Design": out / "design" / "design_spec.md",
        "QA": out / "design" / "qa_findings.md",
    }
    # Submodules imported ``from .config import OUTPUT_DIR`` — rebind so tools + git use the same tree.
    import software_company.git_worktrees as gw
    import software_company.tools_impl as ti
    import software_company.engineering as eng

    gw.OUTPUT_DIR = out
    ti.OUTPUT_DIR = out
    eng.OUTPUT_DIR = out
    try:
        import software_company.rag as rag

        rag.OUTPUT_DIR = out
    except Exception:
        pass
    from software_company import _monolith as _m

    _m.OUTPUT_DIR = out
    _m.TEAM_CANONICAL_FILES = cfg.TEAM_CANONICAL_FILES


def _on_rm_error(func, path, exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _prepare_output_dir(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for sub in ("code", "tests", "design", "config"):
        p = out / sub
        if p.exists():
            shutil.rmtree(p, onexc=_on_rm_error)
        p.mkdir(parents=True, exist_ok=True)


def _seed_minimal_gui_project(code_dir: Path) -> None:
    """Tiny Tk app + passing pytest so the test gate is green without blocking forever."""
    code_dir.mkdir(parents=True, exist_ok=True)
    (code_dir / "main.py").write_text(
        '''\
"""Minimal Tk window for manager smoke — closes after a few seconds if run directly."""
import tkinter as tk

def main() -> None:
    root = tk.Tk()
    root.title("Manager stage smoke")
    root.geometry("360x220")
    lbl = tk.Label(root, text="Smoke target — manager may click the button", padx=12, pady=12)
    lbl.pack()
    btn = tk.Button(root, text="Hello", width=16)
    btn.pack(pady=12)
    # Auto-close so a blocking ``python main.py`` eventually exits (CI-friendly).
    root.after(120_000, root.destroy)
    root.mainloop()

if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    (code_dir / "app").mkdir(exist_ok=True)
    (code_dir / "app" / "__init__.py").write_text("", encoding="utf-8")
    tests = code_dir / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_smoke.py").write_text(
        "def test_smoke():\n    assert True\n",
        encoding="utf-8",
    )
    (tests / "__init__.py").write_text("", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Live manager fix-loop smoke (LLM + tools).")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUT,
        help=f"Project output root (default: {_DEFAULT_OUT})",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=min(3, int(os.environ.get("MANAGER_FIX_MAX_ROUNDS", "3"))),
        help="max_rounds passed to _manager_fix_loop (default 3 or MANAGER_FIX_MAX_ROUNDS)",
    )
    args = parser.parse_args()

    out: Path = args.output_dir.resolve()
    _apply_output_dir(out)
    try:
        sc.WorkDashboard.SAVE_PATH = out / "WORK_DASHBOARD.json"
        sc._dashboard = None
    except Exception:
        pass

    _prepare_output_dir(out)
    sc.reset_contracts()

    code_dir = out / "code"
    _seed_minimal_gui_project(code_dir)

    reg = sc.get_contracts()
    reg.app_type = "gui"
    reg.build_command = ""
    reg.primary_language = "python"
    reg.entry_point = "main.py"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("manager_smoke")

    # Lazy import after OUTPUT_DIR is patched
    from software_company.engineering import _manager_fix_loop

    task_queue = MagicMock()
    task_queue.get_status.return_value = "(smoke — queue not used)"

    _resync_desktop_vision_bindings()
    log.info("OUTPUT_DIR=%s", out)
    log.info("code_dir=%s", code_dir.resolve())
    log.info("max_rounds=%s  AGENT_DESKTOP_CONTROL_ENABLED=%r", args.rounds, os.environ.get("AGENT_DESKTOP_CONTROL_ENABLED"))
    _dv = getattr(_smoke_cfg, "DESKTOP_VISION_MODEL", "") or ""
    _ref = getattr(_smoke_cfg, "DESKTOP_SUGGEST_CLICK_REFINE", False)
    log.info(
        "GEMINI_MODEL=%r  DESKTOP_VISION_MODEL=%r  DESKTOP_SUGGEST_CLICK_REFINE=%s",
        _smoke_cfg.GEMINI_MODEL,
        _dv,
        _ref,
    )
    if not _dv and "lite" in (_smoke_cfg.GEMINI_MODEL or "").lower():
        log.warning(
            "DESKTOP_VISION_MODEL is empty — desktop_suggest_click uses GEMINI_MODEL (lite). "
            "Add e.g. DESKTOP_VISION_MODEL=gemini-3.1-flash-preview to the saved repo .env file "
            "(Cursor must write the file to disk; unsaved buffer lines are invisible to Python)."
        )
    if "lite" in (_smoke_cfg.GEMINI_MODEL or "").lower() and not (
        os.getenv("MANAGER_SMOKE_USE_CONFIG_GEMINI", "").strip().lower()
        in ("1", "true", "yes", "on")
    ):
        log.warning(
            "Using a *-lite* GEMINI_MODEL — vision/clicks are weaker. Prefer gemini-3.1-flash-preview "
            "or set MANAGER_SMOKE_USE_CONFIG_GEMINI=1 / --gemini-model ..."
        )

    result = _manager_fix_loop(
        code_dir,
        task_queue,
        {},
        max_rounds=args.rounds,
    )

    print()
    print("=" * 60)
    print("MANAGER FIX LOOP RESULT")
    print("=" * 60)
    print(f"  passed:           {result.passed}")
    print(f"  rounds_used:      {result.rounds_used}")
    print(f"  app_run_verified: {result.app_run_verified}")
    print(f"  final_output (first 800 chars):\n{result.final_output[:800]}")
    print()

    # Surface whether anything under code/ changed beyond our seed (rough heuristic)
    tracked = list(code_dir.rglob("*.py"))
    print(f"Python files under code/: {len(tracked)}")
    for p in sorted(tracked)[:40]:
        print(f"  - {p.relative_to(code_dir)}")
    if len(tracked) > 40:
        print(f"  ... and {len(tracked) - 40} more")
    print()
    print("Tip: scroll logs above for [TOOL: write_code_file], [TOOL: desktop_mouse|ok], start_service.")
    if os.environ.get("AGENT_DESKTOP_CONTROL_ENABLED", "").strip().lower() not in ("1", "true", "yes", "on"):
        print("Note: AGENT_DESKTOP_CONTROL_ENABLED was not on — desktop tools may return ERROR.")
    print()

    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
