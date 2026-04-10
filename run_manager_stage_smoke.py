#!/usr/bin/env python3
"""
Run the **real** Engineering Manager fix loop (final integration stage) — live LLM + real tools.

This is NOT a unit test: it calls Gemini, may run ``start_service``, ``desktop_screenshot``,
``desktop_mouse``, ``write_code_file``, etc. Use it to verify desktop control and that the
manager actually mutates the project.

Prerequisites
-------------
- ``GEMINI_API_KEY`` in the environment (same as the rest of Quantum Swarm).
- Optional but recommended for GUI verification:
    ``AGENT_DESKTOP_CONTROL_ENABLED=1`` and ``pip install pyautogui``
- Opt-in guard (prevents accidental spend):
    ``RUN_MANAGER_STAGE_SMOKE=1``

Usage (PowerShell)::

    $env:RUN_MANAGER_STAGE_SMOKE = "1"
    $env:GEMINI_API_KEY = "<your-key>"
    $env:AGENT_DESKTOP_CONTROL_ENABLED = "1"   # for real mouse/keyboard
    python run_manager_stage_smoke.py

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

    log.info("OUTPUT_DIR=%s", out)
    log.info("code_dir=%s", code_dir.resolve())
    log.info("max_rounds=%s  AGENT_DESKTOP_CONTROL_ENABLED=%r", args.rounds, os.environ.get("AGENT_DESKTOP_CONTROL_ENABLED"))

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
