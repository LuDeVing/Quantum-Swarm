#!/usr/bin/env python3
"""
run_engineers_only.py — Run ONLY the 8 engineering agents with real Gemini calls.

No architecture team, no design team, no QA.
Just the engineering manager + 8 developers building from a task brief.

Usage:
    python run_engineers_only.py
    python run_engineers_only.py "Build a REST API for a notes app with CRUD"
    python run_engineers_only.py "Build a pygame shooter" --sprints 3
    python run_engineers_only.py -f prompts/engineers_only_full_task_template.txt
    python run_engineers_only.py -f prompts/task.txt --sprints 2

Output goes to: eng_output/code/  and  eng_output/tests/
"""

import sys
import time
import logging
import argparse
import shutil
import stat
import os
import numpy as np
from pathlib import Path

# ── Override output dir before importing software_company ─────────────────────
import software_company as sc

sc.OUTPUT_DIR = Path("eng_output")
sc.WorkDashboard.SAVE_PATH = sc.OUTPUT_DIR / "WORK_DASHBOARD.json"

from software_company import (
    ENG_WORKERS, RollingContext, run_engineering_team,
    token_summary, ActiveInferenceState, HYPOTHESES, ROLE_PRIOR,
    extract_stance_probs, STANCES,
)
from software_company.engineering import run_sprint_retrospective

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eng_sim")

_DEFAULT_TASK = (
    "Build a simple notes app backend using plain Python and SQLite. "
    "No frameworks — use only the standard library (http.server, sqlite3, json). "
    "Implement: POST /notes (create), GET /notes (list all), GET /notes/<id> (get one), "
    "DELETE /notes/<id> (delete). Store notes with id, title, content, created_at. "
    "Single file server.py that runs with: python server.py. "
    "Write tests in test_server.py using unittest. "
    "Keep it minimal and completable in 2 rounds."
)

_ON_RM_ERROR = lambda func, path, exc: (os.chmod(path, stat.S_IWRITE), func(path))


def _wipe_output_dir() -> None:
    """Remove all subdirs so stale files don't block fresh agents."""
    for subdir in ("code", "config", "tests", "design"):
        p = sc.OUTPUT_DIR / subdir
        if p.exists():
            shutil.rmtree(p, onexc=_ON_RM_ERROR)
    sc.OUTPUT_DIR.mkdir(exist_ok=True)
    for subdir in ("code", "tests", "design", "config"):
        (sc.OUTPUT_DIR / subdir).mkdir(exist_ok=True)


def _reset_between_sprints() -> None:
    """Reset planning state between sprints. Keep code/ so engineers build on prior work."""
    sc.reset_contracts()
    sc._dashboard = None

    # Remove stale planning artifacts (will be regenerated for new goal)
    for fname in ("task_queue_state.json", "TASK_TREE.json", "COMPONENT_GRAPH.json"):
        p = sc.OUTPUT_DIR / fname
        if p.exists():
            p.unlink()

    # Clear design/ and config/ — re-planned each sprint; code/ stays intact
    for subdir in ("design", "config"):
        d = sc.OUTPUT_DIR / subdir
        if d.exists():
            shutil.rmtree(d, onexc=_ON_RM_ERROR)
        d.mkdir(exist_ok=True)


def _print_sprint_summary(sprint_num: int, result, elapsed: float, health_states: dict) -> None:
    n_devs = len(ENG_WORKERS)
    stable_threshold = 1.5 * n_devs
    print(f"\n{'='*60}")
    print(f"  SPRINT {sprint_num} RESULTS")
    print(f"{'='*60}")
    print(f"  H_swarm:    {result.H_swarm:.3f}  ({'stable' if result.H_swarm < stable_threshold else 'ELEVATED'})")
    print(f"  Confidence: {result.confidence:.0%}")
    print(f"  Consensus:  {result.consensus_stance.upper()}")
    print(f"  Duration:   {elapsed:.0f}s")
    print(f"  Tokens:     {token_summary()}")

    print(f"\n  Files written:")
    written = sorted(
        f for f in sc.OUTPUT_DIR.rglob("*")
        if f.is_file()
        and f.name != "WORK_DASHBOARD.json"
        and ".git" not in f.parts
        and "__pycache__" not in f.parts
        and f.suffix != ".pyc"
    )
    for f in written:
        rel = str(f.relative_to(sc.OUTPUT_DIR))
        print(f"    {rel:<45} {f.stat().st_size:>6} bytes")

    print(f"\n  Manager synthesis:")
    print(f"  {result.manager_synthesis[:600].replace(chr(10), chr(10)+'  ')}")

    print(f"\n  Developer health:")
    print(f"  {'Dev':<10} {'F_health':>10}  {'Anomaly':>8}  {'Stance':<12}")
    print(f"  {'─'*46}")
    worker_by_dev = {w.role: w for w in result.worker_outputs}
    for dev in ENG_WORKERS:
        F = health_states[dev].free_energy()
        an = "YES" if health_states[dev].is_anomaly() else "no"
        wo = worker_by_dev.get(dev)
        stance = STANCES[int(np.argmax(wo.stance_probs))] if wo else "unknown"
        print(f"  {dev:<10} {F:>10.3f}  {an:>8}  {stance:<12}")


def main():
    parser = argparse.ArgumentParser(
        description="Run the engineering team for N sprints.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("task", nargs="?", default=None,
                        help="Task description (inline string)")
    parser.add_argument("-f", "--file", metavar="PATH",
                        help="Read task from a file instead")
    parser.add_argument("-s", "--sprints", type=int, default=1, metavar="N",
                        help="Number of sprints to run (default: 1)")
    args = parser.parse_args()

    # Resolve task
    if args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"ERROR: task file not found: {path}", file=sys.stderr)
            sys.exit(2)
        original_goal = path.read_text(encoding="utf-8").strip()
    elif args.task:
        original_goal = args.task.strip()
    else:
        original_goal = _DEFAULT_TASK

    num_sprints = max(1, args.sprints)
    sc.MAX_ENG_ROUNDS = 2

    # Initial wipe (fresh start)
    _wipe_output_dir()
    sc._dashboard = None
    sc.reset_contracts()

    print(f"\n{'='*60}")
    print(f"  ENGINEERING TEAM — {num_sprints} SPRINT{'S' if num_sprints > 1 else ''}")
    print(f"  {len(ENG_WORKERS)} developers | {sc.MAX_ENG_ROUNDS} rounds/sprint")
    print(f"{'='*60}")
    print(f"\nORIGINAL GOAL:\n{original_goal}\n")
    print(f"Output -> {sc.OUTPUT_DIR.resolve()}/\n{'─'*60}")

    # Shared across all sprints — team memory accumulates
    rolling_ctxs = {k: RollingContext() for k in ENG_WORKERS + ["eng_manager"]}
    health_states = {
        k: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR)
        for k in ENG_WORKERS + ["eng_manager"]
    }

    current_goal = original_goal
    total_start = time.time()

    for sprint_num in range(1, num_sprints + 1):
        print(f"\n{'='*60}")
        print(f"  SPRINT {sprint_num} / {num_sprints}")
        print(f"  GOAL: {current_goal[:120]}{'...' if len(current_goal) > 120 else ''}")
        print(f"{'='*60}\n")

        t0 = time.time()
        result = run_engineering_team(
            task=current_goal,
            rolling_ctxs=rolling_ctxs,
            health_states=health_states,
            sprint_num=sprint_num,
        )
        elapsed = time.time() - t0

        _print_sprint_summary(sprint_num, result, elapsed, health_states)

        if sprint_num < num_sprints:
            print(f"\n{'─'*60}")
            print(f"  Retrospective: manager reviewing sprint {sprint_num} output...")
            print(f"{'─'*60}")
            _reset_between_sprints()
            current_goal = run_sprint_retrospective(
                original_goal=original_goal,
                prev_result=result,
                sprint_num=sprint_num,
            )
            print(f"\n  SPRINT {sprint_num + 1} GOAL:\n  {current_goal[:400]}\n")

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  ALL {num_sprints} SPRINT{'S' if num_sprints > 1 else ''} COMPLETE")
    print(f"  Total time: {total_elapsed:.0f}s  |  Tokens: {token_summary()}")
    print(f"  Code: {sc.OUTPUT_DIR.resolve()}/code/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
