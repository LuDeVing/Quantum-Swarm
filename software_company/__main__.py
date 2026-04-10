"""CLI: python -m software_company [brief ...] [--sprints N]"""
from __future__ import annotations


def main() -> None:
    import argparse

    from software_company import DEFAULT_BRIEF, print_dashboard, run_company

    parser = argparse.ArgumentParser(description="Quantum Swarm Software Company")
    parser.add_argument("brief", nargs="*", help="Project brief")
    parser.add_argument("--sprints", type=int, default=5, help="Maximum number of sprints")
    args = parser.parse_args()

    brief = " ".join(args.brief).strip() if args.brief else DEFAULT_BRIEF
    max_sprints = args.sprints

    print(f"\n{'═' * 62}")
    print("  QUANTUM SWARM SOFTWARE COMPANY")
    print(f"{'═' * 62}")
    print(f"  Project : {brief}")
    print(f"  Sprints : {max_sprints}\n")

    sprint_results = run_company(brief, max_sprints=max_sprints)
    for i, result in enumerate(sprint_results, 1):
        print(f"\n── Sprint {i}/{len(sprint_results)} ──")
        print_dashboard(result)


if __name__ == "__main__":
    main()
