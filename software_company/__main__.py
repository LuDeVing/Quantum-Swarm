"""CLI: python -m software_company [brief ...] [--sprints N]"""
from __future__ import annotations


def main() -> None:
    import argparse
    import sys
    from pathlib import Path

    import software_company as sc
    sc.OUTPUT_DIR = Path("eng_output")
    sc.WorkDashboard.SAVE_PATH = sc.OUTPUT_DIR / "WORK_DASHBOARD.json"

    from software_company import ENG_WORKERS, RollingContext, run_engineering_team, ActiveInferenceState, HYPOTHESES, ROLE_PRIOR
    from software_company.engineering import run_sprint_retrospective

    parser = argparse.ArgumentParser(description="Quantum Swarm Engineering Team")
    parser.add_argument("brief", nargs="*", help="Project brief")
    parser.add_argument("-s", "--sprints", type=int, default=1, help="Number of sprints")
    args = parser.parse_args()

    brief = " ".join(args.brief).strip() if args.brief else (
        "Build a simple notes app backend using plain Python and SQLite. "
        "No frameworks. Implement CRUD REST endpoints. Single file server.py."
    )
    num_sprints = max(1, args.sprints)

    eng_output = Path("eng_output")
    eng_output.mkdir(exist_ok=True)
    for sub in ("code", "tests", "design", "config"):
        (eng_output / sub).mkdir(exist_ok=True)

    sc.MAX_ENG_ROUNDS = 2
    sc._dashboard = None
    sc.reset_contracts()

    rolling_ctxs = {k: RollingContext() for k in ENG_WORKERS + ["eng_manager"]}
    health_states = {k: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR) for k in ENG_WORKERS + ["eng_manager"]}

    current_goal = brief
    for sprint_num in range(1, num_sprints + 1):
        print(f"\n{'='*60}\n  SPRINT {sprint_num} / {num_sprints}\n{'='*60}")
        result = run_engineering_team(task=current_goal, rolling_ctxs=rolling_ctxs, health_states=health_states, sprint_num=sprint_num)
        print(f"  H_swarm={result.H_swarm:.3f}  confidence={result.confidence:.0%}  consensus={result.consensus_stance}")
        if sprint_num < num_sprints:
            sc.reset_contracts()
            sc._dashboard = None
            current_goal = run_sprint_retrospective(original_goal=brief, prev_result=result, sprint_num=sprint_num)
            print(f"\n  Sprint {sprint_num+1} goal: {current_goal[:200]}")


if __name__ == "__main__":
    main()
