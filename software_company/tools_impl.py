"""Tool implementations and file/sprint helpers (pure Python, no LLM)."""

from __future__ import annotations

import ast
import atexit as _atexit
import json
import logging
import os
import re
import sys
import textwrap
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from .config import OUTPUT_DIR, TEAM_CANONICAL_FILES
from .contracts import get_contracts
from .git_worktrees import _get_code_dir
from .rag import (
    _bg_index_file,
    _bg_rag_refresh_after_tree_change,
    _is_ignored_project_path,
    _RAG_EXTENSIONS,
    get_rag,
    get_worktree_rag,
)
from .state import _get_agent_id, _get_worktree_manager

logger = logging.getLogger("company")

# ── Tool implementations (pure Python, no LLM) ───────────────────────────────
def _strip_subdir_prefix(filename: str, subdir: str) -> str:
    """Remove leading 'subdir/' segments (repeatable), case-insensitive — avoids code/code/… on disk."""
    filename = filename.replace("\\", "/").strip("/")
    if not filename:
        return ""
    sub_l = subdir.lower()
    parts = filename.split("/")
    while parts and parts[0].lower() == sub_l:
        parts.pop(0)
    return "/".join(parts)


def _read_team_files(max_chars: int = 1500) -> str:
    """Read all canonical team spec files and return a combined snippet for injection."""
    parts = []
    labels = {
        "Architecture": "ARCHITECTURE SPEC",
        "Design":       "DESIGN SPEC",
        "QA":           "QA FINDINGS",
    }
    for team, path in TEAM_CANONICAL_FILES.items():
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"─── {labels[team]} ({path.name}) ───\n{content[:max_chars]}")
    if not parts:
        return ""
    return "\n\n".join(parts)


def _write_canonical_file(team_name: str, content: str, append: bool = False) -> None:
    """Write (or append for QA) the manager synthesis to the team's canonical file."""
    path = TEAM_CANONICAL_FILES.get(team_name)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_file_lock(path):
        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            path.write_text(existing + "\n\n---\n\n" + content, encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
    logger.info(f"[{team_name}] canonical file updated: {path.name}")


_sprint_written_files: set = set()   # filenames written this sprint (cleared each sprint)
_sprint_written_lock = threading.Lock()

def _record_sprint_file(filename: str) -> None:
    with _sprint_written_lock:
        _sprint_written_files.add(filename)

def clear_sprint_files() -> None:
    with _sprint_written_lock:
        _sprint_written_files.clear()

def get_sprint_files() -> list:
    with _sprint_written_lock:
        return sorted(_sprint_written_files)

# Per-file write locks — one Lock per absolute path, created on first access.
# Prevents two agents from writing the same file simultaneously (last-writer-wins race).
_file_write_locks: Dict[str, threading.Lock] = {}
_file_write_locks_meta = threading.Lock()   # guards the dict itself

def _get_file_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _file_write_locks_meta:
        if key not in _file_write_locks:
            _file_write_locks[key] = threading.Lock()
        return _file_write_locks[key]


_STANCE_LINE_RE = re.compile(r'^\s*STANCE:\s*\[?\w+\]?\s*$', re.IGNORECASE)

def _strip_stance(content: str) -> str:
    """Remove trailing STANCE: tag that agents append to their text output.
    Handles both LF and CRLF line endings."""
    lines = content.rstrip().splitlines()
    while lines and _STANCE_LINE_RE.match(lines[-1]):
        lines.pop()
    return '\n'.join(lines) + '\n'


_LLM_EP_PROSE_LINE_RE = re.compile(
    r"^\s*(CHANGES|VALIDATION|NEXT\s+RISK|HANDOFF|STANCE|PERPLEXITY|OUTPUT):\s*",
    re.IGNORECASE,
)


def _strip_llm_summary_lines(content: str) -> str:
    """Drop agent-style summary lines (CHANGES:, VALIDATION:, etc.) from LLM-generated text files."""
    out: List[str] = []
    for line in content.splitlines():
        if _LLM_EP_PROSE_LINE_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _tool_write_code_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "code")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        code_dir = _get_code_dir()
        path     = code_dir / filename
        # Detect file-vs-package conflict: writing foo.py when foo/ dir exists, or vice versa
        stem = path.with_suffix("")  # e.g. src/assets (no .py)
        if path.suffix == ".py" and stem.is_dir():
            return (
                f"ERROR: cannot write {filename!r} — a PACKAGE DIRECTORY '{stem.name}/' already "
                f"exists at that path. Import from the package instead, e.g. "
                f"'from {str(stem).replace('/', '.').replace(chr(92), '.')} import ...' "
                f"or rename one of the two."
            )
        logger.info(f"[write_code_file] writing {filename} → {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        _record_sprint_file(filename)
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to code/{filename}"
    except Exception as e:
        logger.error(f"[write_code_file] FAILED for {filename!r}: {e}", exc_info=True)
        return f"ERROR writing code/{filename}: {e}"


def _tool_write_test_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "tests")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        # Must live under code/tests/ (same tree as write_code_file / run_shell cwd), not OUTPUT_DIR/tests/.
        code_dir = _get_code_dir()
        path = code_dir / "tests" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to tests/{filename}"
    except Exception as e:
        logger.error(f"[write_test_file] FAILED for {filename!r}: {e}")
        return f"ERROR writing tests/{filename}: {e}"


def _tool_write_design_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "design")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        path = OUTPUT_DIR / "design" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to design/{filename}"
    except Exception as e:
        logger.error(f"[write_design_file] FAILED for {filename!r}: {e}")
        return f"ERROR writing design/{filename}: {e}"


def _tool_write_config_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "config")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        path = OUTPUT_DIR / "config" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to config/{filename}"
    except Exception as e:
        logger.error(f"[write_config_file] FAILED for {filename!r}: {e}")
        return f"ERROR writing config/{filename}: {e}"


def _tool_read_file(filename: str, offset: int = 1, limit: int = 200) -> str:
    """Read file lines with line numbers. offset: 1-based start line. limit: max lines."""
    MAX_LINES = 500  # hard cap regardless of what caller passes

    def _render(path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return f"[READ ERROR: {e}]"
        all_lines = text.splitlines()
        total = len(all_lines)
        start = max(1, int(offset)) - 1          # convert to 0-based index
        count = min(int(limit), MAX_LINES)
        chunk = all_lines[start: start + count]
        if not chunk:
            return f"[Empty or offset beyond end of file — file has {total} lines]"
        lines_out = [f"{start + i + 1}\t{line}" for i, line in enumerate(chunk)]
        header = f"File: {filename}  (lines {start + 1}–{start + len(chunk)} of {total})"
        suffix = (
            f"\n[{total - start - len(chunk)} more lines — call read_file('{filename}', "
            f"offset={start + len(chunk) + 1}) to continue]"
            if start + len(chunk) < total else ""
        )
        return header + "\n" + "\n".join(lines_out) + suffix

    # Check agent's worktree first for code files
    code_dir = _get_code_dir()
    wt_path = (code_dir / _strip_subdir_prefix(filename, "code")).resolve()
    if wt_path.exists():
        return _render(wt_path)

    out_root = OUTPUT_DIR.resolve()
    candidates: List[Path] = []
    candidates.append((OUTPUT_DIR / "code" / _strip_subdir_prefix(filename, "code")).resolve())
    candidates.append(
        (OUTPUT_DIR / "code" / "tests" / _strip_subdir_prefix(filename, "tests")).resolve()
    )
    candidates.append((OUTPUT_DIR / "tests" / _strip_subdir_prefix(filename, "tests")).resolve())
    for subdir, strip_key in [("design", "design"), ("config", "config")]:
        candidates.append((OUTPUT_DIR / subdir / _strip_subdir_prefix(filename, strip_key)).resolve())
    candidates.append((OUTPUT_DIR / _strip_subdir_prefix(filename, "code")).resolve())

    for p in candidates:
        if not str(p).startswith(str(out_root)):
            return "[ACCESS DENIED: path outside project directory]"
        if p.exists():
            return _render(p)
    return f"[FILE NOT FOUND: {filename}]"


def _dev_tree_path(root: str, relative_path: str) -> Tuple[Optional[Path], Optional[str]]:
    """Resolve a path under code/ (worktree-aware), tests/, config/, or design/. Returns (path, error)."""
    root = (root or "code").strip().lower()
    if root not in ("code", "tests", "config", "design"):
        return None, "ERROR: root must be one of: code, tests, config, design"
    rel = relative_path.replace("\\", "/").strip().strip("/")
    if not rel:
        return None, "ERROR: empty path"
    rel = _strip_subdir_prefix(rel, root)
    if not rel:
        return None, "ERROR: invalid path"
    if any(c in rel for c in ("*", "?", "<", ">", "|")):
        return None, f"ERROR: invalid path {relative_path!r}"
    if ".." in Path(rel).parts:
        return None, "ERROR: path must not contain '..'"
    if ".git" in Path(rel).parts:
        return None, "ERROR: paths under .git are not allowed"
    if root == "code":
        base = _get_code_dir()
    elif root == "tests":
        base = _get_code_dir() / "tests"
    else:
        base = OUTPUT_DIR / root
    try:
        base = base.resolve()
    except OSError as e:
        return None, f"ERROR: {e}"
    path = (base / rel).resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return None, "ERROR: path escapes project directory"
    return path, None


def _tool_create_directory(relative_path: str, root: str = "code") -> str:
    """Create a directory tree (mkdir -p) under the given project root."""
    path, err = _dev_tree_path(root, relative_path)
    if err:
        return err
    assert path is not None
    try:
        path.mkdir(parents=True, exist_ok=True)
        disp = f"{root}/{_strip_subdir_prefix(relative_path.replace('\\', '/'), root)}"
        logger.info(f"[create_directory] {disp} → {path}")
        return f"OK: directory ready at {disp}"
    except OSError as e:
        return f"ERROR: {e}"


def _tool_delete_file(relative_path: str, root: str = "code") -> str:
    """Delete a single file (not a directory)."""
    path, err = _dev_tree_path(root, relative_path)
    if err:
        return err
    assert path is not None
    if not path.exists():
        return f"ERROR: file not found: {path}"
    if path.is_dir():
        return (
            "ERROR: path is a directory — delete files inside first, then remove_empty_directory, "
            "or remove_empty_directory only if the folder is empty"
        )
    try:
        with _get_file_lock(path):
            path.unlink()
        threading.Thread(
            target=_bg_rag_refresh_after_tree_change, daemon=True, name="rag-after-delete"
        ).start()
        logger.info(f"[delete_file] removed {path}")
        rel_disp = _strip_subdir_prefix(relative_path.replace("\\", "/"), root)
        return f"OK: deleted file {root}/{rel_disp}"
    except OSError as e:
        return f"ERROR: {e}"


def _tool_remove_empty_directory(relative_path: str, root: str = "code") -> str:
    """Remove one empty directory (not recursive)."""
    path, err = _dev_tree_path(root, relative_path)
    if err:
        return err
    assert path is not None
    if not path.exists():
        return f"ERROR: path not found: {path}"
    if not path.is_dir():
        return "ERROR: path is not a directory — use delete_file for files"
    try:
        path.rmdir()
        threading.Thread(
            target=_bg_rag_refresh_after_tree_change, daemon=True, name="rag-after-rmdir"
        ).start()
        logger.info(f"[remove_empty_directory] removed {path}")
        return f"OK: removed empty directory {path.name}"
    except OSError as e:
        el = str(e).lower()
        if "not empty" in el or "directory not empty" in el:
            return "ERROR: directory is not empty — delete files inside first"
        return f"ERROR: {e}"

def _tool_search_codebase(query: str) -> str:
    """Search for relevant code — own in-progress work first, then merged codebase."""
    agent_id = _get_agent_id()
    label    = f"[search_codebase:{agent_id or 'anon'}]"
    parts: List[str] = []

    # Own worktree RAG (freshest, agent-local)
    if agent_id:
        wt_rag = get_worktree_rag(agent_id)
        if wt_rag is not None:
            wt_files = wt_rag.list_files()
            logger.info(f"{label} worktree RAG has {len(wt_files)} files: {wt_files}")
            own = wt_rag.query(query, top_k=3)
            if own:
                parts.append(f"=== Your in-progress work ===\n{own}")
        else:
            logger.info(f"{label} no worktree RAG for agent")

    # Global merged RAG
    global_chunks = len(get_rag().chunks)
    logger.info(f"{label} global RAG has {global_chunks} chunks  query={query!r:.60}")
    global_result = get_rag().query(query)
    if global_result and not global_result.startswith("[RAG:"):
        parts.append(f"=== Merged codebase ===\n{global_result}")

    logger.info(f"{label} returning {len(parts)} result sections")
    return "\n\n".join(parts) if parts else "[No relevant code found]"


def _tool_recall_memory(role_key: str, query: str) -> str:
    """Return relevant lessons from this role's long-term memory."""
    try:
        from .long_term_memory import get_role_memory
        store = get_role_memory(role_key)
        result = store.query(query, top_k=8)
        if not result:
            concepts = store.top_concepts(5)
            if concepts:
                concept_str = ", ".join(f"{c}({n})" for c, n in concepts)
                return (
                    f"[No lessons match '{query}'. "
                    f"Top concepts in memory: {concept_str}. "
                    f"Try a broader query or check after more sprints have run.]"
                )
            return f"[No memory yet for this role. Lessons accumulate after each sprint.]"
        count = len(store)
        return f"Long-term memory ({count} facts stored):\n{result}"
    except Exception as e:
        return f"[recall_memory error: {e}]"


def _tool_grep_codebase(pattern: str, glob: str = "", context_lines: int = 0) -> str:
    """Regex search across every file in the project — returns file:line: text matches."""
    import fnmatch

    MAX_MATCHES = 60
    MAX_OUTPUT  = 5000

    if not pattern:
        return "ERROR: pattern is required"
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"ERROR: invalid regex — {e}"

    # Determine which directories to search (agent worktree + merged output)
    code_dir = _get_code_dir()
    search_roots: list[Path] = []
    if code_dir.exists():
        search_roots.append(code_dir)
    fallback = OUTPUT_DIR / "code"
    if fallback.exists() and fallback.resolve() != code_dir.resolve():
        search_roots.append(fallback)

    # Collect candidate files from all roots (deduplicated by resolved path)
    seen_resolved: set[str] = set()
    candidates: list[tuple[Path, str]] = []   # (abs_path, display_path)
    for root in search_roots:
        for fpath in sorted(root.rglob("*")):
            if not fpath.is_file():
                continue
            # Skip binary-ish and noisy files
            if fpath.suffix in {".pyc", ".pyo", ".pkl", ".db", ".sqlite",
                                 ".png", ".jpg", ".jpeg", ".gif", ".ico",
                                 ".zip", ".tar", ".gz", ".whl", ".egg"}:
                continue
            resolved = str(fpath.resolve())
            if resolved in seen_resolved:
                continue
            seen_resolved.add(resolved)
            display = str(fpath.relative_to(root))
            # Apply glob filter if given
            if glob:
                # Support patterns like "*.py" or "**/*.ts"
                if not fnmatch.fnmatch(fpath.name, glob) and not fnmatch.fnmatch(display, glob):
                    continue
            candidates.append((fpath, display))

    if not candidates:
        return f"[No files to search{' matching glob ' + repr(glob) if glob else ''}]"

    lines_out: list[str] = []
    match_count = 0
    truncated = False

    for fpath, display in candidates:
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_lines = text.splitlines()
        file_hits: list[str] = []
        for lineno, line in enumerate(file_lines, 1):
            if rx.search(line):
                if match_count >= MAX_MATCHES:
                    truncated = True
                    break
                match_count += 1
                # Context lines (before)
                if context_lines > 0:
                    for ci in range(max(0, lineno - 1 - context_lines), lineno - 1):
                        file_hits.append(f"  {display}:{ci + 1}: {file_lines[ci]}")
                file_hits.append(f"  {display}:{lineno}: {line}")
                # Context lines (after)
                if context_lines > 0:
                    for ci in range(lineno, min(len(file_lines), lineno + context_lines)):
                        file_hits.append(f"  {display}:{ci + 1}: {file_lines[ci]}")
        if file_hits:
            lines_out.extend(file_hits)
        if truncated:
            break

    if not lines_out:
        return f"[No matches for {pattern!r}{' in ' + repr(glob) if glob else ''}]"

    header = f"Grep results for {pattern!r}{' (' + glob + ')' if glob else ''} — {match_count} match(es):"
    body = "\n".join(lines_out)
    result = header + "\n" + body
    if truncated:
        result += f"\n[Truncated — showing first {MAX_MATCHES} matches. Narrow pattern or add glob filter.]"
    if len(result) > MAX_OUTPUT:
        result = result[:MAX_OUTPUT] + "\n[Output truncated — use a more specific pattern]"
    return result


def _tool_list_files() -> str:
    """List all source files — merged codebase plus this agent's own in-progress work."""
    agent_id = _get_agent_id()
    label    = f"[list_files:{agent_id or 'anon'}]"

    # ── merged global files ────────────────────────────────────────────────────
    # Global RAG stores paths as "code/<rel>" (relative to OUTPUT_DIR).
    # Strip the leading "code/" so agents see bare paths like "app/models.py"
    # that can be passed directly to write_code_file / read_file.
    raw_global = get_rag().list_files()
    global_rag_paths: set = (
        set(raw_global.split("\n"))
        if raw_global != "[No files indexed yet]"
        else set()
    )
    # Strip "code/" prefix for display; keep raw set for dedup against worktree
    def _strip_code_prefix(p: str) -> str:
        return p[5:] if p.startswith("code/") else p

    lines = [_strip_code_prefix(p) for p in global_rag_paths]

    def _norm_list_path(s: str) -> str:
        """Collapse code/foo and foo to the same key (avoids duplicate tests/ paths)."""
        t = s.replace(" [in-progress]", "").strip().replace("\\", "/")
        return t[5:] if t.startswith("code/") else t

    # Dedupe: RAG indexes both OUTPUT_DIR/code/tests/… and OUTPUT_DIR/tests/…
    _seen: Dict[str, str] = {}
    for disp in lines:
        key = _norm_list_path(disp)
        if key not in _seen or ("[in-progress]" in disp and "[in-progress]" not in _seen[key]):
            _seen[key] = disp
    lines = list(_seen.values())

    logger.info(
        f"{label} OUTPUT_DIR={OUTPUT_DIR.resolve()}  "
        f"global RAG has {len(global_rag_paths)} files"
        + (f": {sorted(lines)}" if lines else " (empty)")
    )

    # ── own worktree files not yet merged ──────────────────────────────────────
    # Worktree paths are already relative to the code/ dir (e.g. "app/models.py").
    # The global RAG stores them as "code/app/models.py", so prepend "code/" for
    # the dedup check, then add the bare path if it's genuinely new.
    wt     = _get_worktree_manager()
    wt_own: List[str] = []
    if agent_id and wt is not None:
        wt_dir = wt.get_agent_code_dir(agent_id)
        if wt_dir and wt_dir.exists():
            for p in wt_dir.rglob("*"):
                if not p.is_file() or _is_ignored_project_path(p):
                    continue
                if p.suffix not in _RAG_EXTENSIONS:
                    continue
                rel        = str(p.relative_to(wt_dir)).replace("\\", "/")
                global_key = f"code/{rel}"
                if global_key not in global_rag_paths:
                    lines.append(f"{rel} [in-progress]")
                    wt_own.append(rel)
        logger.info(f"{label} worktree dir={wt_dir}  new in-progress files={wt_own}")
    else:
        logger.info(f"{label} no active worktree (agent_id={agent_id!r}, wt={wt})")

    _seen_final: Dict[str, str] = {}
    for disp in lines:
        key = _norm_list_path(disp)
        if key not in _seen_final or (
            "[in-progress]" in disp and "[in-progress]" not in _seen_final[key]
        ):
            _seen_final[key] = disp
    lines = list(_seen_final.values())

    if not lines:
        return "[No files indexed yet]"
    result = "\n".join(sorted(lines))
    logger.info(f"{label} returning {len(lines)} files total:\n{result}")
    return result


def _tool_validate_python(code: str) -> str:
    try:
        ast.parse(code)
        return "Python syntax OK"
    except SyntaxError as e:
        return f"Syntax error: {e}"


def _tool_validate_json(content: str) -> str:
    try:
        json.loads(content)
        return "JSON valid"
    except json.JSONDecodeError as e:
        return f"JSON error: {e}"


def _tool_validate_yaml(content: str) -> str:
    try:
        parsed = yaml.safe_load(content)
        if parsed is None:
            return "YAML warning: file is empty or contains only comments"
        return "YAML valid"
    except yaml.YAMLError as e:
        return f"YAML error: {e}"


def _tool_generate_endpoint_table(endpoints_json: str) -> str:
    """endpoints_json: JSON list of {method, path, description, auth}"""
    try:
        eps = json.loads(endpoints_json)
        rows = ["| Method | Path | Description | Auth |",
                "|--------|------|-------------|------|"]
        for ep in eps:
            rows.append(
                f"| {ep.get('method','GET')} | `{ep.get('path','/')}` "
                f"| {ep.get('description','')} | {ep.get('auth','no')} |"
            )
        return "\n".join(rows)
    except Exception as e:
        return f"[endpoint table error: {e}]"


def _tool_generate_er_diagram(tables_json: str) -> str:
    """tables_json: JSON list of {name, fields:[{name,type,pk,fk}]}"""
    try:
        tables = json.loads(tables_json)
        lines = []
        for t in tables:
            lines.append(f"┌─ {t['name']} {'─'*(20-len(t['name']))}┐")
            for f in t.get("fields", []):
                pk = " PK" if f.get("pk") else ""
                fk = f" → {f['fk']}" if f.get("fk") else ""
                lines.append(f"│  {f['name']:<12} {f['type']:<10}{pk}{fk}")
            lines.append("└" + "─"*22 + "┘")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"[ER diagram error: {e}]"


def _tool_create_ascii_diagram(components_json: str) -> str:
    """components_json: JSON list of {name, connects_to:[names]}"""
    try:
        comps = json.loads(components_json)
        lines = []
        for c in comps:
            name = c["name"]
            conns = c.get("connects_to", [])
            lines.append(f"[{name}]")
            for conn in conns:
                lines.append(f"  └──► [{conn}]")
        return "\n".join(lines)
    except Exception as e:
        return f"[diagram error: {e}]"


def _tool_create_user_flow(steps_json: str) -> str:
    """steps_json: JSON list of {step, action, outcome}"""
    try:
        steps = json.loads(steps_json)
        lines = []
        for i, s in enumerate(steps):
            prefix = "START → " if i == 0 else "      → "
            lines.append(f"{prefix}[{s['step']}]")
            lines.append(f"         Action:  {s.get('action','')}")
            lines.append(f"         Outcome: {s.get('outcome','')}")
            if i < len(steps) - 1:
                lines.append("           |")
        return "\n".join(lines)
    except Exception as e:
        return f"[user flow error: {e}]"


def _tool_create_wireframe(page_name: str, sections_json: str) -> str:
    """sections_json: JSON list of {name, type, content}"""
    try:
        sections = json.loads(sections_json)
        width = 52
        border = "+" + "─" * width + "+"
        lines = [border, f"|  PAGE: {page_name:<{width-9}}|", border]
        for s in sections:
            label = f"  [{s['type'].upper()}] {s['name']}"
            lines.append(f"|{label:<{width}}|")
            if s.get("content"):
                for line in textwrap.wrap(s["content"], width - 4):
                    lines.append(f"|    {line:<{width-4}}|")
            lines.append(f"|{'·'*width}|")
        lines.append(border)
        return "\n".join(lines)
    except Exception as e:
        return f"[wireframe error: {e}]"


def _tool_create_style_guide(guide_json: str) -> str:
    """guide_json: {colors:{name:hex}, fonts:{role:family}, spacing:{name:value}}"""
    try:
        g = json.loads(guide_json)
        lines = ["## Style Guide", ""]
        if "colors" in g:
            lines += ["### Colors", "| Name | Value |", "|------|-------|"]
            for name, val in g["colors"].items():
                lines.append(f"| {name} | `{val}` |")
            lines.append("")
        if "fonts" in g:
            lines += ["### Typography", "| Role | Font |", "|------|------|"]
            for role, fam in g["fonts"].items():
                lines.append(f"| {role} | {fam} |")
            lines.append("")
        if "spacing" in g:
            lines += ["### Spacing Scale", "| Token | Value |", "|-------|-------|"]
            for tok, val in g["spacing"].items():
                lines.append(f"| {tok} | {val} |")
        return "\n".join(lines)
    except Exception as e:
        return f"[style guide error: {e}]"


def _tool_scan_vulnerabilities(code: str) -> str:
    patterns = [
        (r"eval\s*\(",             "HIGH",   "eval() — arbitrary code execution"),
        (r"exec\s*\(",             "HIGH",   "exec() — arbitrary code execution"),
        (r"os\.system\s*\(",       "HIGH",   "os.system() — shell injection risk"),
        (r"subprocess\.call\s*\(", "MEDIUM", "subprocess without shell=False check"),
        (r"password\s*=\s*['\"]",  "HIGH",   "hardcoded password literal"),
        (r"secret\s*=\s*['\"]",    "HIGH",   "hardcoded secret literal"),
        (r"md5\s*\(",               "MEDIUM", "MD5 — weak hash, use SHA-256+"),
        (r"sha1\s*\(",              "MEDIUM", "SHA-1 — weak hash, use SHA-256+"),
        (r"SELECT.+\+",             "HIGH",   "possible SQL injection via string concat"),
        (r"innerHTML\s*=",          "MEDIUM", "innerHTML — potential XSS"),
        (r"document\.write\s*\(",   "MEDIUM", "document.write — potential XSS"),
        (r"verify\s*=\s*False",     "HIGH",   "SSL verification disabled"),
        (r"DEBUG\s*=\s*True",       "MEDIUM", "debug mode enabled in production"),
    ]
    findings = []
    for pattern, severity, desc in patterns:
        matches = re.findall(pattern, code, re.IGNORECASE)
        if matches:
            findings.append(f"[{severity}] {desc} ({len(matches)} occurrence(s))")
    return "\n".join(findings) if findings else "No obvious vulnerabilities detected"


_RUN_SHELL_TIMEOUT = 120   # seconds; raised from 30 so build commands (npm, pip, go) don't get killed


def _append_run_shell_footer(
    output: str,
    cwd: str,
    *,
    exit_code: Optional[int] = None,
    result: Optional[str] = None,
) -> str:
    """Suffix run_shell output with status and cwd so models don't misread truncated text."""
    body = (output or "").rstrip()
    cwd_disp = str(Path(cwd).resolve())
    if result is not None:
        status = f"run_shell: {result}"
    elif exit_code is not None:
        status = f"run_shell: exit_code={exit_code}"
    else:
        status = "run_shell: status=unknown"
    footer = f"\n---\n{status}\nrun_shell: cwd={cwd_disp}"
    return body + footer


def _append_generic_shell_failure_hints(output: str, exit_code: int) -> str:
    """Language-agnostic hints when a shell command fails (OS/shell level only)."""
    if exit_code == 0:
        return output
    o = output
    low = o.lower()
    extra: List[str] = []
    if any(
        phrase in low
        for phrase in (
            "not recognized",
            "is not recognized",
            "command not found",
            "not found as an internal or external command",
        )
    ):
        extra.append(
            "[hint] The shell could not run a program name in this command — it may be missing "
            "from PATH on this machine, or the name may be wrong. Try the full path to the tool, "
            "or the install path documented for this project."
        )
    extra.append(
        "[hint] Prefer short, single-purpose commands; nested quotes are easy to get wrong in a shell. "
        "Inspect paths or symbols cited in the output with read_file / search_codebase. "
        "For opaque errors, web_search the exact message. Long-running servers belong in "
        "start_service(), not run_shell()."
    )
    return o + "\n\n" + "\n".join(extra)


def _normalize_shell_command_for_windows(command: str) -> str:
    """On Windows, rewrite Unix-style env prefixes to cmd.exe-compatible form.
    e.g. `PYTHONPATH=. python app/main.py`  →  `set PYTHONPATH=.&& python app/main.py`
    Also converts `VAR=val cmd` and `VAR1=a VAR2=b cmd` patterns.
    Only used as a fallback when no bash shell is available.
    """
    import re as _re
    import sys as _sys
    if _sys.platform != "win32":
        return command
    # Match one or more `KEY=VALUE` pairs at the start of the command (before a non-assignment word)
    pattern = _re.compile(r'^((?:[A-Za-z_][A-Za-z0-9_]*=[^\s]*\s+)+)(.*)')
    m = pattern.match(command.strip())
    if not m:
        return command
    env_part = m.group(1).strip()   # e.g. "PYTHONPATH=. FOO=bar"
    rest     = m.group(2).strip()   # the actual command
    sets = " && ".join(f"set {kv}" for kv in env_part.split())
    return f"{sets} && {rest}"


def _find_bash_on_windows() -> str | None:
    """Return path to bash.exe on Windows (Git Bash / WSL), or None if not found."""
    import shutil as _shutil
    # shutil.which checks PATH first — covers most Git for Windows installs
    bash = _shutil.which("bash")
    if bash:
        return bash
    # Common fixed install locations
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]
    import os as _os
    for c in candidates:
        if _os.path.isfile(c):
            return c
    return None


_BASH_PATH: str | None | bool = False  # False = not yet probed


def _get_bash_path() -> str | None:
    """Cached probe for bash on Windows."""
    global _BASH_PATH
    if _BASH_PATH is False:
        import sys as _sys
        _BASH_PATH = _find_bash_on_windows() if _sys.platform == "win32" else None
    return _BASH_PATH  # type: ignore[return-value]


# Stacks where prepending PYTHONPATH is unnecessary and can confuse native toolchains.
_NON_PYTHONPATH_LANGS = frozenset({
    "rust", "go", "golang", "cpp", "cxx", "c++", "c", "csharp", "cs", "c#",
    "java", "kotlin", "kt", "javascript", "typescript", "js", "ts",
    "ruby", "rb", "php", "swift", "zig", "scala", "haskell", "hs",
    "ocaml", "ml", "nim", "dart", "elixir", "ex", "erlang", "erl",
    "clojure", "clj", "vb", "fsharp", "fs",
})


def _registry_wants_pythonpath() -> bool:
    """True if subprocess env should prepend code_dir to PYTHONPATH (Python or mixed stacks)."""
    reg = get_contracts()
    with reg._lock:
        lang = (reg.primary_language or "").strip().lower()
        if not lang:
            lang = reg._infer_primary_language_locked()
    if lang in ("mixed", "python"):
        return True
    if lang in _NON_PYTHONPATH_LANGS:
        return False
    return True


def _subprocess_env_for_project(code_dir: Path) -> Dict[str, str]:
    """Environment for child processes: copy os.environ; inject the active venv into PATH
    so agents use the same python/pip that runs this process, not the system Python."""
    import sys as _sys
    cwd_s = str(Path(code_dir).resolve())
    env: Dict[str, str] = dict(os.environ)

    # Inject the active venv's Scripts/bin dir so `pip` and `python` resolve correctly.
    # sys.executable is e.g. C:\project\.venv\Scripts\python.exe — its parent is Scripts/.
    venv_bin = Path(_sys.executable).parent
    if venv_bin.exists():
        sep = os.pathsep
        current_path = env.get("PATH", "")
        venv_bin_s = str(venv_bin)
        if venv_bin_s not in current_path:
            env["PATH"] = venv_bin_s + sep + current_path
        # Also set VIRTUAL_ENV so pip knows it's inside a venv
        env["VIRTUAL_ENV"] = str(venv_bin.parent)
        env.pop("PYTHONHOME", None)  # PYTHONHOME confuses venv Python

    if not _registry_wants_pythonpath():
        return env
    sep = os.pathsep
    existing = env.get("PYTHONPATH", "").strip()
    if existing:
        parts = [p for p in existing.split(sep) if p]
        if cwd_s not in parts:
            env["PYTHONPATH"] = cwd_s + sep + existing
    else:
        env["PYTHONPATH"] = cwd_s
    return env


# Per-agent spin detection: tracks (command, output_hash) for the last N shell calls
_shell_spin_tracker: Dict[str, List[int]] = {}   # agent_id → [hash1, hash2, ...]
_shell_spin_lock = threading.Lock()
_SPIN_WINDOW = 4    # how many consecutive identical (cmd+output) to consider a spin
_SPIN_MAX    = 3    # how many times to allow before injecting a hint


def _check_shell_spin(agent: str, command: str, output: str) -> bool:
    """Return True if this agent is in a spin loop (same cmd+output repeated ≥ _SPIN_MAX times)."""
    key = hash((command.strip(), output.strip()[:500]))
    with _shell_spin_lock:
        history = _shell_spin_tracker.setdefault(agent, [])
        history.append(key)
        if len(history) > _SPIN_WINDOW:
            history.pop(0)
        # Spin = all entries in the window are identical
        return len(history) >= _SPIN_MAX and len(set(history)) == 1


def _reset_shell_spin(agent: str) -> None:
    """Reset spin tracker when the agent makes progress (different output)."""
    with _shell_spin_lock:
        _shell_spin_tracker.pop(agent, None)


def _run_shell_segment_blocks_gui(seg: str) -> Optional[str]:
    """If a single shell segment would start a blocking GUI main, return error text."""
    import re
    c = (seg or "").strip()
    if not c:
        return None
    low = c.lower()
    safe_markers = (
        "--help", "-h ", " -h", "--version", " -v", "-c ", " -c ", "py_compile",
        "pytest", "unittest", "__integration__", "pip ", "npm ", "docker build",
        "flake8", "mypy", "black ", "ruff ", "echo ", "type ", "dir ", "ls ",
        "chmod ", "git ", "curl ", "wget ", "tasklist", "findstr",
        "cargo ", "rustc ", "go ", "clang", "gcc ", "g++ ", "make ", "cmake ",
        "dotnet ", "mvn ", "gradle ", "bundle ", "rspec ",
    )
    # -m is only safe for known non-GUI modules; do NOT blanket-allow it
    # because `python -m src.engine` / `python -m app` starts a blocking GUI loop
    _SAFE_M_MODULES = (
        "pytest", "unittest", "py_compile", "pip", "venv", "ensurepip",
        "compileall", "flake8", "mypy", "black", "ruff", "isort",
        "coverage", "http.server", "json.tool", "pydoc",
    )
    _m_match = re.search(r"\bpython\w*\s+-m\s+(\S+)", low)
    if _m_match:
        mod = _m_match.group(1).split(".")[0]
        if not any(mod == s or mod.startswith(s) for s in _SAFE_M_MODULES):
            return (
                f"ERROR: run_shell cannot run 'python -m {_m_match.group(1)}' — "
                "it may start a blocking event loop. "
                "Use start_service() to launch it in the background instead.\n\n"
                "Use instead:\n"
                "  start_service('app', 'python -m " + _m_match.group(1) + "')\n"
                "  then desktop_list_windows() / desktop_activate_window()."
            )
    if any(m in low for m in safe_markers):
        return None
    if re.search(r"(?:^|[\s;|&])-h(?:\s|$)", low) or re.search(
        r"(?:^|[\s;|&])--help(?:\s|$)", low
    ):
        return None
    m = re.search(
        r"(?:^|[;&|]\s*)(?:pythonw?\d?|py(?:thon)?3?)\s+([\w./\\-]+\.py)\b",
        c,
        re.IGNORECASE,
    )
    if not m:
        return None
    raw = m.group(1).replace("\\", "/")
    base = raw.split("/")[-1].lower()
    entry_like = {"main.py", "run.py", "app.py", "gui.py", "__main__.py"}
    if not (base.endswith("_gui.py") or base in entry_like):
        return None
    return (
        "ERROR: run_shell cannot run the full GUI entrypoint — it starts an event loop and "
        f"blocks until you close the window (then times out after {_RUN_SHELL_TIMEOUT}s), "
        "freezing this agent thread.\n\n"
        "Use instead:\n"
        "  • Smoke-check without UI: run_shell('python run.py --help') or unit tests / "
        "python -c \"import tkinter; print('ok')\"\n"
        "  • Real GUI session (manager / integration with desktop tools): "
        "start_service('gui', 'python run.py'), then desktop_list_windows() / desktop_activate_window() if needed; "
        "on Windows prefer desktop_uia_list_elements / desktop_uia_click when UIA names exist, else "
        "desktop_screenshot(), desktop_suggest_click('control name'), desktop_mouse('click', x, y), "
        "desktop_keyboard() as needed; then stop_service('gui').\n"
    )


def _run_shell_blocks_gui_entrypoint(command: str) -> Optional[str]:
    """Block GUI main on any command *segment* — a safe tail must not exempt a GUI head
    (e.g. ``python main.py &`` + ``python -c ...`` on the next line)."""
    import re
    c = (command or "").strip()
    if not c:
        return None
    # Flatten: newlines, && (cmd), & (Windows/cmd chain)
    segments: List[str] = []
    for raw_line in re.split(r"[\r\n]+", c):
        line = raw_line.strip()
        if not line:
            continue
        for chunk in re.split(r"\s*&&\s*", line):
            chunk = chunk.strip()
            if not chunk:
                continue
            for seg in re.split(r"\s*&\s*", chunk):
                s = seg.strip()
                if s:
                    segments.append(s)
    for seg in segments:
        hit = _run_shell_segment_blocks_gui(seg)
        if hit:
            return hit
    return None


def _dev_run_shell_blocks_app(command: str) -> Optional[str]:
    """For dev_* agents: block any command that runs the full application.
    Developers must only run unit tests or syntax checks — the manager runs the app."""
    import re
    c = (command or "").strip().lower()
    # Allow: pytest, unittest, py_compile, validate, pip, flake8, mypy, ls, git, etc.
    _ALLOWED_PATTERNS = (
        "pytest", "unittest", "py_compile", "pip ", "pip3 ",
        "flake8", "mypy", "black ", "ruff ", "isort ",
        "validate", "ls ", "ls\n", "dir ", "find ", "cat ",
        "git ", "echo ", "python --version", "python3 --version",
        "python -m pytest", "python3 -m pytest",
        "python -m unittest", "python3 -m unittest",
        "python -m py_compile", "python3 -m py_compile",
        "python -c \"import", "python3 -c \"import",
        "python -c 'import", "python3 -c 'import",
        "import tkinter", "import pygame", "import PyQt",
    )
    if any(p in c for p in _ALLOWED_PATTERNS):
        return None
    # Block: python <anything>.py  or  python3 <anything>.py  (that isn't a test file)
    m = re.search(r"python\w*\s+([\w./\\-]+\.py)\b", c)
    if m:
        script = m.group(1).replace("\\", "/").split("/")[-1]
        if not (script.startswith("test_") or script.endswith("_test.py")):
            return (
                f"ERROR: developers must not run the full application ({script}). "
                "Your job is to write and unit-test YOUR file only. "
                "The manager runs the full app after all files are merged.\n"
                "Allowed: python -m pytest tests/test_your_file.py\n"
                "         python -m py_compile your_file.py\n"
                "         python -c \"import your_module; ...\" (import-only checks)"
            )
    return None


def _tool_run_shell(command: str) -> str:
    """Run a shell command in the output directory and return stdout + stderr (last 3000 chars)."""
    import subprocess
    agent = _get_agent_id() or "unknown_agent"
    cwd = _get_code_dir()
    if not (command or "").strip():
        return "ERROR: run_shell requires a non-empty command."
    bash = _get_bash_path()
    if not bash:
        command = _normalize_shell_command_for_windows(command)
    # Dev agents must not run the full application
    if (agent or "").startswith("dev_"):
        _dev_block = _dev_run_shell_blocks_app(command)
        if _dev_block:
            logger.warning(f"[run_shell:{agent}] blocked app-run by developer: {command[:80]!r}")
            return _dev_block
    _block = _run_shell_blocks_gui_entrypoint(command)
    if _block:
        logger.warning(f"[run_shell:{agent}] blocked GUI-blocking command: {command[:120]!r}")
        return _block
    logger.info(f"[run_shell:{agent}] ▶ {command} (cwd={cwd})")
    try:
        _env = _subprocess_env_for_project(Path(cwd))
        if bash:
            cmd_args = [bash, "-c", command]
            result = subprocess.run(
                cmd_args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=_RUN_SHELL_TIMEOUT,
                cwd=str(cwd),
                env=_env,
                encoding="utf-8",
                errors="replace",
            )
        else:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_RUN_SHELL_TIMEOUT,
                cwd=str(cwd),
                env=_env,
                encoding="utf-8",
                errors="replace",
            )
        out = (result.stdout or "") + (result.stderr or "")
        preview = out[-500:] if len(out) > 500 else out
        logger.info(
            f"[run_shell:{agent}] exit={result.returncode} output_preview=\n"
            f"{preview if preview else '(no output)'}"
        )
        out = out[-3000:] if len(out) > 3000 else out
        final_out = out or "(no output)"
        if result.returncode != 0:
            final_out = _append_generic_shell_failure_hints(final_out, result.returncode)
        if result.returncode != 0 and _check_shell_spin(agent, command, final_out):
            logger.warning(
                f"[run_shell:{agent}] SPIN DETECTED — same failing command repeated "
                f"{_SPIN_MAX}+ times. Injecting hint to try a different approach."
            )
            return _append_run_shell_footer(
                final_out + "\n\n"
                "[SPIN GUARD] You have run this exact command multiple times with the same "
                "failure. Running it again will not help. Read the actual source files involved, "
                "understand the root cause, fix the code, then re-run.",
                cwd,
                exit_code=result.returncode,
            )
        if result.returncode == 0:
            _reset_shell_spin(agent)
        return _append_run_shell_footer(final_out, cwd, exit_code=result.returncode)
    except subprocess.TimeoutExpired:
        logger.warning(f"[run_shell:{agent}] TIMEOUT after {_RUN_SHELL_TIMEOUT}s: {command}")
        return _append_run_shell_footer(
            f"ERROR: command timed out after {_RUN_SHELL_TIMEOUT}s. "
            "To start a long-running server use start_service(), not run_shell().",
            cwd,
            result="timeout",
        )
    except Exception as e:
        logger.warning(f"[run_shell:{agent}] ERROR: {e}")
        return _append_run_shell_footer(f"ERROR: {e}", cwd, result="subprocess_error")


# ── Background service registry (start_service / stop_service) ───────────────
_services: Dict[str, object] = {}        # name → subprocess.Popen
_services_ports: Dict[str, int] = {}     # name → port
_services_lock = threading.Lock()

def _extract_port(command: str) -> Optional[int]:
    """Try to extract a port number from a command string."""
    import re
    m = re.search(r'(?:--port|-p|:)\s*(\d{4,5})\b', command)
    if m:
        return int(m.group(1))
    # http.server 8000 / uvicorn app:app --port 8080 style
    m = re.search(r'\b(8\d{3}|9\d{3}|3000|4000|5000)\b', command)
    return int(m.group(1)) if m else None

def _kill_proc_tree(proc) -> None:
    """Kill a process and all its children (cross-platform)."""
    import signal as _signal
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except Exception:
                pass
        proc.kill()
    except ImportError:
        # psutil not available — fall back to simple kill
        try:
            if sys.platform == "win32":
                import subprocess as _sp
                _sp.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                         stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            else:
                import os, signal as _signal
                os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
        except Exception:
            proc.kill()
    except Exception:
        proc.kill()


def _wait_for_port(port: int, timeout: float = 6.0) -> bool:
    """Poll until localhost:port accepts a TCP connection or timeout expires."""
    import socket, time as _t
    deadline = _t.time() + timeout
    while _t.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            _t.sleep(0.3)
    return False


def _tool_start_service(name: str, command: str) -> str:
    """Start a long-running process (server/worker) in the background.
    Returns a startup summary including early output, port readiness, and any crash details."""
    import subprocess, time, queue, threading as _th
    bash = _get_bash_path()
    if not bash:
        command = _normalize_shell_command_for_windows(command)

    with _services_lock:
        existing = _services.get(name)
        if existing is not None and existing.poll() is None:
            return f"[{name}] already running (pid={existing.pid}) — call stop_service('{name}') first if you want to restart it"
        # Check port conflict
        port = _extract_port(command)
        if port:
            for svc_name, svc_port in _services_ports.items():
                if svc_port == port and svc_name in _services and _services[svc_name].poll() is None:
                    return (
                        f"PORT CONFLICT: port {port} is already used by service '{svc_name}'. "
                        f"Stop it first with stop_service('{svc_name}') or choose a different port."
                    )
    try:
        _svc_root = OUTPUT_DIR / "code"
        _svc_env = _subprocess_env_for_project(_svc_root)
        _popen_cmd = [bash, "-c", command] if bash else command
        proc = subprocess.Popen(
            _popen_cmd,
            shell=not bash,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(_svc_root),
            env=_svc_env,
            encoding="utf-8",
            errors="replace",
        )

        # Start drain thread immediately so we capture crash output even on fast exits
        output_lines: list = []
        q: queue.Queue = queue.Queue()

        def _drain():
            for line in iter(proc.stdout.readline, ""):
                q.put(line.rstrip())

        _th.Thread(target=_drain, daemon=True).start()

        # Give the process up to 4 seconds to either crash or start accepting connections
        boot_deadline = time.time() + 4.0
        while time.time() < boot_deadline:
            try:
                output_lines.append(q.get(timeout=0.1))
            except queue.Empty:
                pass
            if proc.poll() is not None:
                break   # process already exited — collect remaining output

        # Drain any remaining buffered lines
        flush_deadline = time.time() + 0.5
        while time.time() < flush_deadline:
            try:
                output_lines.append(q.get_nowait())
            except queue.Empty:
                break

        with _services_lock:
            _services[name] = proc
            if port:
                _services_ports[name] = port

        rc = proc.poll()
        early = "\n".join(output_lines[-30:]) if output_lines else "(no output captured)"

        if rc is not None:
            # Process crashed — return full diagnostics so manager knows exactly why
            return (
                f"[{name}] CRASHED immediately (exit rc={rc}) — the app cannot start.\n"
                f"Command: {command}\n"
                f"Output:\n{early}\n\n"
                f"ACTION REQUIRED: Read the error above, fix the import/config issue in the "
                f"relevant source file(s) with write_code_file(), then call start_service() again."
            )

        # Process is running — check if the port is actually accepting connections
        port_ready = False
        if port:
            port_ready = _wait_for_port(port, timeout=5.0)
            # Collect any additional startup lines while waiting
            for _ in range(20):
                try:
                    output_lines.append(q.get_nowait())
                except queue.Empty:
                    break

        early = "\n".join(output_lines[-30:]) if output_lines else "(no output yet)"
        port_status = ""
        if port:
            port_status = (
                f"\nPort {port}: {'✓ accepting connections' if port_ready else '⚠ not yet responding (app may still be starting)'}"
            )

        return (
            f"[{name}] started (pid={proc.pid}){port_status}\n"
            f"Startup output:\n{early}"
        )
    except Exception as e:
        return f"ERROR starting service '{name}': {e}"


def _tool_stop_service(name: str) -> str:
    """Stop a background service previously started with start_service()."""
    import time
    with _services_lock:
        proc = _services.pop(name, None)
        _services_ports.pop(name, None)
    if proc is None:
        return f"[{name}] not found — either never started or already stopped"
    if proc.poll() is not None:
        return f"[{name}] already exited (rc={proc.returncode})"
    try:
        _kill_proc_tree(proc)
        try:
            rc = proc.wait(timeout=5)
        except Exception:
            rc = proc.returncode
        return f"[{name}] stopped (rc={rc})"
    except Exception as e:
        return f"ERROR stopping service '{name}': {e}"


def _atexit_stop_all_services() -> None:
    """Ensure all tracked background services are killed when the interpreter exits."""
    with _services_lock:
        names = list(_services.keys())
    for name in names:
        try:
            _tool_stop_service(name)
        except Exception:
            pass


import atexit as _atexit
_atexit.register(_atexit_stop_all_services)


def _tool_http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request and return status code + response body (first 2000 chars)."""
    try:
        import requests as _requests
        method = method.upper()
        headers = {"Content-Type": "application/json"}
        resp = _requests.request(
            method, url,
            data=body or None,
            headers=headers,
            timeout=15,
        )
        text = resp.text[:2000]
        return f"HTTP {resp.status_code}\n{text}"
    except Exception as e:
        return f"ERROR: {e}"


# ── download_url (HTTPS assets: textures, small binaries) ─────────────────────
# Env: AGENT_DOWNLOAD_ENABLED (default on), AGENT_DOWNLOAD_MAX_BYTES (default 10MiB),
#      AGENT_DOWNLOAD_ALLOW_HTTP=1 to permit http:// URLs.
# Web search: AGENT_WEB_SEARCH_ENABLED (default on), AGENT_WEB_SEARCH_MAX_RESULTS (1–20, default 5).
# Optional: BRAVE_API_KEY or BRAVE_SEARCH_API_KEY for Brave Search API fallback.

_DOWNLOAD_BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".ico", ".bin", ".zip",
    ".gz", ".tar", ".7z", ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".mp3", ".ogg",
})
_DOWNLOAD_MAX_REDIRECTS = 5
_DOWNLOAD_CHUNK = 65536
_DOWNLOAD_UA = "QuantumSwarm-download_url/1.0"
_WEBSEARCH_UA = "QuantumSwarm-web_search/1.0"


def _agent_download_enabled() -> bool:
    v = os.getenv("AGENT_DOWNLOAD_ENABLED", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _agent_download_max_bytes() -> int:
    try:
        return max(1024, int(os.getenv("AGENT_DOWNLOAD_MAX_BYTES", str(10 * 1024 * 1024))))
    except ValueError:
        return 10 * 1024 * 1024


def _agent_download_allow_http() -> bool:
    v = os.getenv("AGENT_DOWNLOAD_ALLOW_HTTP", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _download_ip_blocked(ip: "ipaddress._BaseAddress") -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
        return True
    if ip.version == 4:
        if ip.is_reserved or int(ip) == 0:
            return True
    if ip.version == 6:
        if ip.is_reserved or ip.is_unspecified:
            return True
    return False


def _download_validate_host(host: str) -> Optional[str]:
    """Return None if host resolves only to allowed addresses; else error string."""
    import ipaddress
    import socket

    if not host or host.strip() != host:
        return "ERROR: invalid host"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None:
        return "ERROR: URL host resolves to a disallowed address" if _download_ip_blocked(addr) else None

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        return f"ERROR: cannot resolve host: {e}"
    seen: set = set()
    for _fam, _typ, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        try:
            a = ipaddress.ip_address(ip_str)
        except ValueError:
            return "ERROR: invalid resolved address"
        if _download_ip_blocked(a):
            return "ERROR: URL host resolves to a disallowed address (private/loopback/link-local)"
    if not seen:
        return "ERROR: host resolved to no addresses"
    return None


def _download_validate_url(url: str) -> Optional[str]:
    """Return None if URL is acceptable for fetch, else error string."""
    from urllib.parse import urlparse

    try:
        p = urlparse(url)
    except Exception as e:
        return f"ERROR: invalid URL: {e}"
    if p.scheme not in ("https", "http"):
        return f"ERROR: scheme {p.scheme!r} not allowed (only http/https)"
    if p.scheme == "http" and not _agent_download_allow_http():
        return "ERROR: only https allowed (set AGENT_DOWNLOAD_ALLOW_HTTP=1 for http)"
    if not p.hostname:
        return "ERROR: URL missing host"
    if p.username is not None or p.password is not None:
        return "ERROR: URL must not contain credentials"
    return _download_validate_host(p.hostname)


def _download_should_skip_rag(path: Path, content_type: str) -> bool:
    if path.suffix.lower() in _DOWNLOAD_BINARY_SUFFIXES:
        return True
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct.startswith("image/") or ct.startswith("font/"):
        return True
    if ct in ("application/octet-stream", "application/font-woff", "application/font-sfnt"):
        return True
    return False


def _tool_download_url(url: str, dest_path: str) -> str:
    """Download bytes from a public URL into code/<dest_path>. HTTPS only unless AGENT_DOWNLOAD_ALLOW_HTTP=1.
    Use for textures, small data files — not for source code (use write_code_file)."""
    import hashlib
    from urllib.parse import urljoin, urlparse

    import requests as _requests

    if not _agent_download_enabled():
        return "ERROR: download_url disabled (AGENT_DOWNLOAD_ENABLED=0)"

    url = (url or "").strip()
    if not url:
        return "ERROR: empty url"

    rel = _strip_subdir_prefix((dest_path or "").strip(), "code")
    if not rel or any(c in rel for c in ("*", "?", "<", ">", "|")):
        return f"ERROR: invalid dest_path {dest_path!r}"
    if ".." in Path(rel).parts:
        return "ERROR: dest_path must not contain '..'"

    code_dir = _get_code_dir().resolve()
    path = (code_dir / rel).resolve()
    try:
        path.relative_to(code_dir)
    except ValueError:
        return "ERROR: dest_path escapes code directory"

    err = _download_validate_url(url)
    if err:
        return err

    max_bytes = _agent_download_max_bytes()
    headers = {"User-Agent": _DOWNLOAD_UA, "Accept": "*/*"}
    current = url
    resp = None

    try:
        for _redirect_i in range(_DOWNLOAD_MAX_REDIRECTS + 1):
            v_err = _download_validate_url(current)
            if v_err:
                return v_err
            r = _requests.get(
                current,
                stream=True,
                timeout=30,
                allow_redirects=False,
                headers=headers,
            )
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                r.close()
                if not loc:
                    return "ERROR: redirect without Location header"
                current = urljoin(current, loc)
                continue
            resp = r
            break
        else:
            return f"ERROR: too many redirects (max {_DOWNLOAD_MAX_REDIRECTS})"

        if resp is None:
            return "ERROR: no response"

        if resp.status_code != 200:
            body_preview = (resp.text or "")[:200]
            resp.close()
            return f"ERROR: HTTP {resp.status_code} {body_preview!r}"

        cl = resp.headers.get("Content-Length")
        if cl is not None:
            try:
                if int(cl) > max_bytes:
                    resp.close()
                    return f"ERROR: Content-Length {cl} exceeds max {max_bytes}"
            except ValueError:
                pass

        ctype = resp.headers.get("Content-Type", "")

        h = hashlib.sha256()
        total = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as out:
            for chunk in resp.iter_content(chunk_size=_DOWNLOAD_CHUNK):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    resp.close()
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return f"ERROR: response exceeds max_bytes={max_bytes}"
                h.update(chunk)
                out.write(chunk)
        resp.close()

        digest = h.hexdigest()[:16]
        _record_sprint_file(rel)
        if not _download_should_skip_rag(path, ctype):
            threading.Thread(
                target=_bg_index_file, args=(path,), daemon=True, name=f"rag-dl-{path.name}"
            ).start()

        logger.info(f"[download_url] saved {total} bytes → code/{rel} (sha256~{digest})")
        return (
            f"Saved {total} bytes to code/{rel}\n"
            f"URL: {current}\nContent-Type: {ctype or '(none)'}\nsha256-prefix: {digest}"
        )
    except Exception as e:
        logger.warning(f"[download_url] failed: {e}")
        try:
            if path.exists():
                path.unlink(missing_ok=True)
        except OSError:
            pass
        return f"ERROR: {e}"


def _agent_web_search_enabled() -> bool:
    v = os.getenv("AGENT_WEB_SEARCH_ENABLED", "1").strip().lower()
    return v not in ("0", "false", "no")


def _agent_web_search_max_results() -> int:
    try:
        return max(1, min(20, int(os.getenv("AGENT_WEB_SEARCH_MAX_RESULTS", "5"))))
    except ValueError:
        return 5


def _ddg_instant_answer_fallback(query: str) -> str:
    """Lightweight DuckDuckGo instant-answer JSON (no extra deps). Often sparse for CLI queries."""
    import requests as _rq

    try:
        r = _rq.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1"},
            timeout=20,
            headers={"User-Agent": _WEBSEARCH_UA},
        )
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        logger.warning(f"[web_search] DDG instant answer failed: {e}")
        return ""

    parts: List[str] = []
    if d.get("AbstractText"):
        parts.append(f"Abstract: {d['AbstractText']}")
    if d.get("Answer"):
        parts.append(f"Answer: {d['Answer']}")
    for t in d.get("RelatedTopics", [])[:10]:
        if isinstance(t, dict) and t.get("Text"):
            parts.append(f"- {t['Text']}")
        elif isinstance(t, dict) and "Topics" in t:
            for sub in t.get("Topics", [])[:4]:
                if isinstance(sub, dict) and sub.get("Text"):
                    parts.append(f"- {sub['Text']}")
    return "\n".join(parts)


def _brave_web_search(query: str, max_n: int) -> Optional[str]:
    key = (os.getenv("BRAVE_API_KEY") or os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
    if not key:
        return None
    import requests as _rq

    try:
        r = _rq.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_n},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            timeout=25,
        )
        if r.status_code != 200:
            logger.warning(f"[web_search] Brave HTTP {r.status_code}")
            return None
        data = r.json()
        web = data.get("web", {}).get("results", [])
        lines: List[str] = []
        for i, it in enumerate(web[:max_n], 1):
            title = it.get("title", "")
            url = it.get("url", "")
            desc = (it.get("description", "") or "")[:500]
            lines.append(f"{i}. {title}\n   {url}\n   {desc}")
        if lines:
            return "Web search (Brave):\n" + "\n".join(lines)
    except Exception as e:
        logger.warning(f"[web_search] Brave failed: {e}")
    return None


def _ddgs_text_search(query: str, max_n: int) -> Optional[str]:
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return None
    lines: List[str] = []
    try:
        ddgs = DDGS()
        iterable = ddgs.text(query, max_results=max_n)
        for i, item in enumerate(iterable, 1):
            if i > max_n:
                break
            if isinstance(item, dict):
                title = item.get("title", "")
                href = item.get("href", "") or item.get("link", "")
                body = (item.get("body", "") or item.get("snippet", ""))[:450]
            else:
                title = str(item)
                href = ""
                body = ""
            lines.append(f"{i}. {title}\n   {href}\n   {body}")
    except Exception as e:
        logger.warning(f"[web_search] ddgs failed: {e}")
        return None
    if lines:
        return "Web search results (verify commands before run_shell):\n" + "\n".join(lines)
    return None


def _tool_web_search(query: str, focus: str = "") -> str:
    if not _agent_web_search_enabled():
        return "ERROR: web_search disabled (set AGENT_WEB_SEARCH_ENABLED=1)"
    q = (query or "").strip()
    focus = (focus or "").strip()
    if focus:
        q = f"{q} {focus}".strip()
    if not q:
        return "ERROR: empty query"
    if len(q) > 800:
        return "ERROR: query too long (max 800 characters)"
    max_n = _agent_web_search_max_results()

    out = _ddgs_text_search(q, max_n)
    if out:
        return out
    out = _brave_web_search(q, max_n)
    if out:
        return out
    ia = _ddg_instant_answer_fallback(q)
    if ia.strip():
        return "Web search (instant answer — may be brief):\n" + ia.strip()
    return (
        "No useful web results for this query. Try shorter keywords, official docs site name, "
        "or read_file on README / package manifest in the repo."
    )


def _tool_check_owasp(feature: str) -> str:
    checklist = {
        "auth":        ["A01: Broken Access Control", "A02: Cryptographic Failures",
                        "A07: Identification and Authentication Failures"],
        "api":         ["A01: Broken Access Control", "A03: Injection",
                        "A05: Security Misconfiguration"],
        "input":       ["A03: Injection", "A06: Vulnerable Components"],
        "session":     ["A02: Cryptographic Failures", "A07: Auth Failures"],
        "file_upload": ["A03: Injection", "A04: Insecure Design"],
        "database":    ["A03: Injection", "A02: Cryptographic Failures"],
    }
    feature_lower = feature.lower()
    relevant = []
    for key, risks in checklist.items():
        if key in feature_lower or feature_lower in key:
            relevant.extend(risks)
    if not relevant:
        relevant = ["A01: Broken Access Control", "A03: Injection", "A05: Security Misconfiguration"]
    return "Relevant OWASP Top 10 risks:\n" + "\n".join(f"  • {r}" for r in set(relevant))
