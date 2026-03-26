"""
SwarmBench Test — Gemini agents on the 5 swarm tasks.

Runs SwarmBench (arxiv 2505.04364) using Gemini 2.0 Flash via its
OpenAI-compatible endpoint, then compares against published baselines.

SwarmBench tasks (2D grid, agents see only a local view):
  Pursuit        — cooperatively chase a moving target
  Foraging       — collect scattered resources
  Flocking       — align movement with neighbours
  Synchronization— reach shared state without global view
  Transport      — push an object to a goal cooperatively

Published avg scores (SwarmBench paper, Table 1):
  o4-mini         : 0.61
  GPT-4o          : 0.52
  gemini-2.0-flash: 0.49   ← our baseline to beat
  deepseek-v3     : 0.48
  random agent    : 0.21

Requirements:
  - YuLan-SwarmIntell/ must be cloned next to this file (already done)
  - pip install openai colorama numpy   (standard packages)

Usage:
  python swarmbench_test.py
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_DIR = Path(__file__).parent / "YuLan-SwarmIntell"
LOG_DIR  = str(REPO_DIR / "swarmbench_logs")

if not REPO_DIR.exists():
    print("ERROR: YuLan-SwarmIntell/ not found. Clone it first:")
    print("  git clone https://github.com/RUC-GSAI/YuLan-SwarmIntell.git")
    sys.exit(1)

# Must add repo root to sys.path — it uses local imports (util, framework, swarmbench)
sys.path.insert(0, str(REPO_DIR))
os.chdir(REPO_DIR)   # also change cwd so relative paths inside the repo work

# ── Config ────────────────────────────────────────────────────────────────────

GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY", "")
MODEL           = "gemini-3-flash-preview"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

TASKS      = ["Pursuit", "Foraging", "Flocking", "Synchronization", "Transport"]
SEEDS      = [42, 123, 7]   # 3 seeds → avg score ± std
NUM_AGENTS = 6              # paper uses 10; 6 keeps cost low
MAX_ROUND  = 50             # paper uses 100; 50 keeps cost low
GRID_W     = 10
GRID_H     = 10
VIEW_SIZE  = 5

# Published baselines (avg over all tasks, from paper Table 1)
PUBLISHED = {
    "o4-mini":          0.61,
    "GPT-4o":           0.52,
    "gemini-2.0-flash": 0.49,
    "deepseek-v3":      0.48,
    "random-agent":     0.21,
}


# ── Run experiments ───────────────────────────────────────────────────────────

def run():
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    from swarmbench import SwarmFramework

    n = 1
    for task in TASKS:
        for seed in SEEDS:
            SwarmFramework.submit(
                f"exp_{n}_{task}_s{seed}",
                SwarmFramework.model_config(MODEL, GEMINI_API_KEY, GEMINI_BASE_URL),
                task,
                log_dir=LOG_DIR,
                num_agents=NUM_AGENTS,
                max_round=MAX_ROUND,
                width=GRID_W,
                height=GRID_H,
                seed=seed,
                view_size=VIEW_SIZE,
            )
            n += 1

    total = len(TASKS) * len(SEEDS)
    print(f"  Running {total} experiments ({len(TASKS)} tasks × {len(SEEDS)} seeds)...")
    print(f"  Agents: {NUM_AGENTS}  |  Rounds: {MAX_ROUND}  |  Grid: {GRID_W}×{GRID_H}")
    print(f"  Logs → {LOG_DIR}\n")

    SwarmFramework.run_all(max_parallel=2)


# ── Parse scores ──────────────────────────────────────────────────────────────

def parse_scores() -> dict:
    """
    Read game logs and return scores per task.
    Score is stored in the final round's game_log entry under key 'score'.
    Meta log maps timestamp → {task, model, ...}.
    """
    meta_path = Path(LOG_DIR) / "meta_log.json"
    if not meta_path.exists():
        print(f"  No meta_log.json found in {LOG_DIR}")
        return {}

    with open(meta_path) as f:
        meta = json.load(f)

    scores_by_task = defaultdict(list)

    for timestamp, info in meta.items():
        task = info.get("task")
        if not task:
            continue
        game_log_path = Path(LOG_DIR) / f"game_log_{timestamp}.json"
        if not game_log_path.exists():
            continue
        try:
            with open(game_log_path) as f:
                steps = json.load(f)
            final_score = steps[-1].get("score") if steps else None
            if isinstance(final_score, (int, float)):
                scores_by_task[task].append(float(final_score))
                print(f"    {task} seed {info.get('seed','?')}: {final_score:.3f}")
        except Exception as e:
            print(f"    Warning: could not parse {game_log_path.name}: {e}")

    return dict(scores_by_task)


# ── Display results ───────────────────────────────────────────────────────────

def display(scores_by_task: dict):
    def avg(lst): return sum(lst) / len(lst) if lst else None
    def std(lst):
        if not lst: return None
        m = avg(lst)
        return (sum((x-m)**2 for x in lst) / len(lst)) ** 0.5

    task_avgs = {t: avg(scores_by_task.get(t, [])) for t in TASKS}
    valid     = [v for v in task_avgs.values() if v is not None]
    overall   = avg(valid)

    print(f"\n{'='*65}")
    print(f"  RESULTS")
    print(f"  Model:   {MODEL}")
    print(f"  Config:  {NUM_AGENTS} agents  |  {MAX_ROUND} rounds  |  {len(SEEDS)} seeds")
    print(f"{'='*65}")
    print(f"\n  Per-task (avg ± std over {len(SEEDS)} seeds):")
    print(f"  {'Task':<20} {'Avg':>7} {'Std':>7} {'N':>4}")
    print(f"  {'-'*42}")
    for task in TASKS:
        data = scores_by_task.get(task, [])
        a = avg(data)
        s = std(data)
        if a is not None:
            print(f"  {task:<20} {a:>7.3f} {s:>7.3f} {len(data):>4}")
        else:
            print(f"  {task:<20} {'N/A':>7}")

    print(f"\n  {'OVERALL':<20} {f'{overall:.3f}' if overall else 'N/A':>7}")

    print(f"\n  Published baselines (all tasks, SwarmBench paper):")
    print(f"  {'Model':<25} {'Avg Score':>10}")
    print(f"  {'-'*37}")
    for model_name, score in sorted(PUBLISHED.items(), key=lambda x: -x[1]):
        marker = "  ← published us" if model_name == MODEL else ""
        print(f"  {model_name:<25} {score:>10.2f}{marker}")

    if overall is not None:
        pub = PUBLISHED.get(MODEL, 0.49)
        diff = overall - pub
        print(f"\n  Our score: {overall:.3f}  |  Published {MODEL}: {pub:.2f}  |  diff: {diff:+.3f}")
        if diff > 0.02:
            print("  The swarm coordination is helping above the published baseline.")
        elif diff < -0.02:
            print("  Below published baseline — coordination overhead on small grids.")
        else:
            print("  On par with published baseline.")

    # Show LLM trace log
    trace_log = Path(LOG_DIR) / "llm_trace.log"
    if trace_log.exists():
        lines = trace_log.read_text(encoding="utf-8").splitlines()
        print(f"\n{'='*65}")
        print(f"  LLM TRACE  (last 60 lines of {len(lines)} total — full log: {trace_log})")
        print(f"{'='*65}")
        for line in lines[-60:]:
            print(f"  {line}")

    # Also run the repo's own score_agg.py for full breakdown
    print(f"\n  Running repo score_agg.py for full breakdown...")
    try:
        result = subprocess.run(
            [sys.executable, "analysis/score_agg.py", "--log-dir", LOG_DIR],
            capture_output=True, text=True, cwd=str(REPO_DIR)
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr[:500])
    except Exception as e:
        print(f"  (score_agg.py failed: {e})")

    # Save
    out = {
        "model": MODEL,
        "num_agents": NUM_AGENTS,
        "max_round": MAX_ROUND,
        "seeds": SEEDS,
        "scores_by_task": {t: scores_by_task.get(t, []) for t in TASKS},
        "task_averages": task_avgs,
        "overall_average": overall,
        "published_baselines": PUBLISHED,
    }
    out_path = Path(__file__).parent / "swarmbench_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n  Results saved to swarmbench_results.json")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*65}")
    print(f"  SwarmBench  |  {MODEL}  |  Gemini OpenAI-compat API")
    print(f"{'='*65}")
    print(f"  Tasks:    {', '.join(TASKS)}")
    print(f"  Settings: {NUM_AGENTS} agents, {MAX_ROUND} rounds, {len(SEEDS)} seeds")
    print(f"  Beat:     gemini-2.0-flash published = 0.49")
    print(f"{'='*65}\n")

    run()

    print("\n  Parsing scores...")
    scores = parse_scores()
    display(scores)


if __name__ == "__main__":
    main()
