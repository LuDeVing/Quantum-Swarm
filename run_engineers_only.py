#!/usr/bin/env python3
"""
run_engineers_only.py — Run ONLY the 8 engineering agents with real Gemini calls.

No architecture team, no design team, no QA.
Just the engineering manager + 8 developers building from a task brief.

Usage:
    python run_engineers_only.py
    python run_engineers_only.py "Build a REST API for a notes app with CRUD"

Output goes to: eng_output/code/  and  eng_output/tests/
"""

import sys
import time
import logging
import numpy as np
from pathlib import Path

# ── Override output dir before importing software_company ─────────────────────
# We use a separate folder so we don't pollute company_output/
import os
import shutil
import stat
import software_company as sc

sc.OUTPUT_DIR = Path("eng_output")

# Clear code/ and config/ from prior runs so stale files don't block fresh agents.
# (The hard file-existence guard in write_code_file would otherwise block round-1
#  agents from writing files that were left over from a previous test run.)
def _on_rm_error(func, path, exc_info):
    # Clear the read-only bit and retry
    os.chmod(path, stat.S_IWRITE)
    func(path)

for _subdir in ("code", "config", "tests", "design"):
    _p = sc.OUTPUT_DIR / _subdir
    if _p.exists():
        shutil.rmtree(_p, onexc=_on_rm_error)

sc.OUTPUT_DIR.mkdir(exist_ok=True)
(sc.OUTPUT_DIR / "code").mkdir(exist_ok=True)
(sc.OUTPUT_DIR / "tests").mkdir(exist_ok=True)
(sc.OUTPUT_DIR / "design").mkdir(exist_ok=True)
(sc.OUTPUT_DIR / "config").mkdir(exist_ok=True)

# Also reset the dashboard save path so it writes to eng_output
sc.WorkDashboard.SAVE_PATH = sc.OUTPUT_DIR / "WORK_DASHBOARD.json"
sc._dashboard = None   # force fresh dashboard
sc.reset_contracts()   # force fresh contract registry

# ── Reduce rounds for a quick but meaningful run ─────────────────────────────
sc.MAX_ENG_ROUNDS = 2   # 2 rounds: implement + integrate

from software_company import (
    ENG_WORKERS, ROLES, RollingContext,
    run_engineering_team, token_summary,
    ActiveInferenceState, HYPOTHESES, ROLE_PRIOR,
    extract_stance_probs, STANCES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("eng_sim")


TASK = sys.argv[1] if len(sys.argv) > 1 else (
    "Build a simple notes app backend using plain Python and SQLite. "
    "No frameworks — use only the standard library (http.server, sqlite3, json). "
    "Implement: POST /notes (create), GET /notes (list all), GET /notes/<id> (get one), "
    "DELETE /notes/<id> (delete). Store notes with id, title, content, created_at. "
    "Single file server.py that runs with: python server.py. "
    "Write tests in test_server.py using unittest. "
    "Keep it minimal and completable in 2 rounds."
)


def main():
    print("\n" + "="*60)
    print("  ENGINEERING TEAM — LIVE RUN")
    print(f"  {len(ENG_WORKERS)} developers | {sc.MAX_ENG_ROUNDS} rounds | gemini-2.0-flash")
    print("="*60)
    print(f"\nTASK:\n{TASK}\n")
    print(f"Output → {sc.OUTPUT_DIR.resolve()}/\n")
    print("─"*60)

    rolling_ctxs = {k: RollingContext() for k in ENG_WORKERS + ["eng_manager"]}
    health_states = {
        k: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR)
        for k in ENG_WORKERS + ["eng_manager"]
    }

    t0 = time.time()
    result = run_engineering_team(
        task=TASK,
        rolling_ctxs=rolling_ctxs,
        health_states=health_states,
        sprint_num=1,
    )
    elapsed = time.time() - t0

    # ── Results summary ───────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("  RESULTS")
    print("="*60)
    n_devs = len(ENG_WORKERS)
    stable_threshold = 1.5 * n_devs
    print(f"\nH_swarm:    {result.H_swarm:.3f}  ({'stable' if result.H_swarm < stable_threshold else 'ELEVATED ⚠'})")
    print(f"Confidence: {result.confidence:.0%}")
    print(f"Consensus:  {result.consensus_stance.upper()}")
    print(f"Duration:   {elapsed:.0f}s")
    print(f"Tokens:     {token_summary()}")

    # ── What was written ──────────────────────────────────────────────────────
    print("\n── Files written ──────────────────────────────────────────")
    all_files = list(sc.OUTPUT_DIR.rglob("*"))
    written = [
        f for f in all_files
        if f.is_file()
        and f.name != "WORK_DASHBOARD.json"
        and ".git" not in f.parts
        and "__pycache__" not in f.parts
        and not f.suffix == ".pyc"
    ]
    if written:
        for f in sorted(written):
            rel = str(f.relative_to(sc.OUTPUT_DIR))   # str() required for format spec on Windows
            size = f.stat().st_size
            print(f"  {rel:<45} {size:>6} bytes")
    else:
        print("  (no files written)")

    # ── Manager synthesis ─────────────────────────────────────────────────────
    print("\n── Manager synthesis ──────────────────────────────────────")
    print(result.manager_synthesis[:1200])

    # ── Per-dev health ────────────────────────────────────────────────────────
    print("\n── Developer health ───────────────────────────────────────")
    print(f"  {'Dev':<10} {'F_health':>10}  {'Anomaly':>8}  {'Stance':<12}")
    print(f"  {'─'*46}")
    # Index worker_outputs by role key for fast lookup
    worker_out_by_dev = {w.role: w for w in result.worker_outputs}
    for dev in ENG_WORKERS:
        F  = health_states[dev].free_energy()
        an = "⚠ YES" if health_states[dev].is_anomaly() else "no"
        # Use stance from WorkerOutput (derived from actual agent output, not rolling context)
        wo = worker_out_by_dev.get(dev)
        stance = STANCES[int(np.argmax(wo.stance_probs))] if wo else "unknown"
        print(f"  {dev:<10} {F:>10.3f}  {an:>8}  {stance:<12}")

    print("\n" + "="*60)
    print(f"  Done. Open eng_output/code/ to review the generated code.")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
