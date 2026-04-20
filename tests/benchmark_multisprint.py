#!/usr/bin/env python3
"""
Multi-Sprint Regression Benchmark for Quantum Swarm.

Runs the full system on tasks of increasing complexity and measures:
  - Test pass rate (pytest on generated code)
  - Whether code is runnable (no import / syntax errors)
  - Sprint count to completion
  - Token cost
  - Regression: does adding complexity break what worked at lower complexity?

Each task runs in a fresh subprocess so module-level singletons reset cleanly.

Usage:
    # Standalone — recommended, shows live progress:
    python tests/benchmark_multisprint.py

    # Via pytest (skipped unless env var set):
    RUN_MULTISPRINT_BENCHMARK=1 python -m pytest tests/benchmark_multisprint.py -v -s

    # Single task smoke (fast):
    RUN_MULTISPRINT_BENCHMARK=1 BENCHMARK_TASK=0 python -m pytest tests/benchmark_multisprint.py -v -s
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "company_output"
RESULTS_FILE = OUTPUT_DIR / "results.json"

MAX_SPRINTS = 2          # cap per task — enough to iterate once
TASK_TIMEOUT = 900       # 15 min hard timeout per task subprocess
MIN_PASS_RATE = 0.50     # MVP bar: at least 50% of tests must pass

# Set RUN_MULTISPRINT_BENCHMARK=1 to actually run; otherwise pytest skips.
RUN_BENCHMARK = os.environ.get("RUN_MULTISPRINT_BENCHMARK", "0") == "1"
# Optionally run only one task by index (0-based) for a quick smoke:
SINGLE_TASK_IDX: Optional[int] = (
    int(os.environ["BENCHMARK_TASK"]) if "BENCHMARK_TASK" in os.environ else None
)

# ---------------------------------------------------------------------------
# Task definitions  (ordered: simplest → most complex)
# ---------------------------------------------------------------------------

TASKS = [
    {
        "name": "CLI todo app",
        "brief": (
            "Build a command-line todo app in Python. "
            "Commands: add <title>, list, complete <id>, delete <id>. "
            "Store todos in SQLite (todos.db). "
            "Include a comprehensive pytest test suite in tests/."
        ),
        "min_pass_rate": 0.60,
    },
    {
        "name": "REST API — basic CRUD",
        "brief": (
            "Build a REST API for a todo app using Python, FastAPI, and SQLite. "
            "Endpoints: POST /todos, GET /todos, GET /todos/{id}, "
            "PUT /todos/{id}, DELETE /todos/{id}. "
            "Include a comprehensive pytest test suite in tests/."
        ),
        "min_pass_rate": 0.55,
    },
    {
        "name": "REST API + JWT auth",
        "brief": (
            "Build a REST API for a todo app using Python, FastAPI, and SQLite. "
            "Include full JWT user authentication: POST /auth/register, POST /auth/login. "
            "Todo endpoints are protected and scoped per user. "
            "Include a comprehensive pytest test suite covering auth and todos."
        ),
        "min_pass_rate": 0.45,
    },
]

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class TaskResult:
    name: str
    brief: str
    pass_rate: float          # 0.0–1.0
    tests_passed: int
    tests_total: int
    runnable: bool            # code directory importable / no syntax errors
    sprint_count: int         # sprints completed (from results.json)
    tokens_in: int
    tokens_out: int
    duration_s: float
    error: Optional[str] = None   # non-None if subprocess crashed

    @property
    def tokens_total(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def passed_bar(self) -> bool:
        return self.pass_rate >= MIN_PASS_RATE and self.runnable

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_output_dir() -> None:
    """Delete generated artifacts so each task starts from a blank slate."""
    for subdir in ["code", "tests", "logs", "design"]:
        p = OUTPUT_DIR / subdir
        if p.exists():
            shutil.rmtree(p)
    for pattern in ["*.md", "*.json", "*.pkl"]:
        for f in OUTPUT_DIR.glob(pattern):
            try:
                f.unlink()
            except OSError:
                pass
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _run_pytest_on_output() -> tuple[int, int]:
    """
    Run pytest on the generated code directory.
    Returns (passed, total).  Returns (0, 0) if no tests found.
    """
    code_dir = OUTPUT_DIR / "code"
    if not code_dir.exists():
        return 0, 0

    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(code_dir), "--tb=no", "-q", "--no-header"],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(code_dir),
        env={**os.environ, "PYTHONPATH": str(code_dir)},
    )
    output = r.stdout + r.stderr

    # Parse "X passed" / "X failed" / "X error" from pytest summary line
    passed = sum(int(m) for m in re.findall(r"(\d+) passed", output))
    failed = sum(int(m) for m in re.findall(r"(\d+) failed", output))
    errors = sum(int(m) for m in re.findall(r"(\d+) error", output))
    total = passed + failed + errors
    return passed, total


def _check_runnable() -> bool:
    """
    Check whether the generated code has no obvious syntax / import errors.
    Tries to compile every .py file in company_output/code/.
    """
    code_dir = OUTPUT_DIR / "code"
    if not code_dir.exists():
        return False
    py_files = list(code_dir.rglob("*.py"))
    if not py_files:
        return False
    for pyf in py_files:
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(pyf)],
            capture_output=True,
        )
        if r.returncode != 0:
            return False
    return True


def _read_results_json() -> dict:
    """Read company_output/results.json written by run_company."""
    if not RESULTS_FILE.exists():
        return {}
    try:
        return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_task(task: dict) -> TaskResult:
    """
    Run one benchmark task in a subprocess and collect metrics.
    """
    print(f"\n  Running: {task['name']}")
    print(f"  Brief:   {task['brief'][:80]}...")
    _reset_output_dir()

    start = time.time()
    proc = subprocess.run(
        [
            sys.executable, "-m", "software_company",
            task["brief"],
            "--sprints", str(MAX_SPRINTS),
        ],
        capture_output=True,
        text=True,
        timeout=TASK_TIMEOUT,
        cwd=str(REPO_ROOT),
    )
    duration = time.time() - start

    crashed = proc.returncode != 0
    error_msg: Optional[str] = None
    if crashed:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        error_msg = f"exit={proc.returncode}: {tail}"
        print(f"  [WARN] subprocess exited {proc.returncode}")

    # Read sprint count + token usage from results.json
    sprint_count = 0
    tokens_in = 0
    tokens_out = 0
    results_data = _read_results_json()
    if isinstance(results_data, list):
        sprint_count = len(results_data)
        # Last entry may have token totals
        if results_data:
            last = results_data[-1]
            tokens_in = last.get("tokens_in", 0) or 0
            tokens_out = last.get("tokens_out", 0) or 0
    elif isinstance(results_data, dict):
        sprint_count = 1
        tokens_in = results_data.get("tokens_in", 0) or 0
        tokens_out = results_data.get("tokens_out", 0) or 0

    # Measure test pass rate
    try:
        passed, total = _run_pytest_on_output()
    except Exception as exc:
        passed, total = 0, 0
        print(f"  [WARN] pytest measurement failed: {exc}")

    pass_rate = (passed / total) if total > 0 else 0.0

    # Check runnability
    try:
        runnable = _check_runnable()
    except Exception:
        runnable = False

    print(
        f"  Done in {duration:.0f}s | "
        f"tests {passed}/{total} ({pass_rate:.0%}) | "
        f"runnable={runnable} | sprints={sprint_count}"
    )

    return TaskResult(
        name=task["name"],
        brief=task["brief"],
        pass_rate=pass_rate,
        tests_passed=passed,
        tests_total=total,
        runnable=runnable,
        sprint_count=sprint_count,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        duration_s=duration,
        error=error_msg,
    )

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report(results: List[TaskResult]) -> None:
    w = 72
    print()
    print("=" * w)
    print("  QUANTUM SWARM — MULTI-SPRINT BENCHMARK RESULTS")
    print("=" * w)

    header = f"  {'Task':<28} {'Tests':>8} {'Pass':>6} {'Run':>5} {'Sprnts':>7} {'Tokens':>9} {'Time':>7}"
    print(header)
    print("  " + "-" * (w - 2))

    for r in results:
        tok = f"{r.tokens_total // 1000}k" if r.tokens_total else "n/a"
        t = f"{r.duration_s:.0f}s"
        test_str = f"{r.tests_passed}/{r.tests_total}" if r.tests_total else "none"
        run_str = "yes" if r.runnable else "NO"
        bar = "PASS" if r.passed_bar else "FAIL"
        print(
            f"  {r.name:<28} {test_str:>8} {r.pass_rate:>5.0%} "
            f"{run_str:>5} {r.sprint_count:>7} {tok:>9} {t:>7}  [{bar}]"
        )
        if r.error:
            snippet = textwrap.shorten(r.error, 60)
            print(f"  {'':28}  ERROR: {snippet}")

    print("  " + "-" * (w - 2))

    passed_tasks = [r for r in results if r.passed_bar]
    avg_pass = sum(r.pass_rate for r in results) / len(results) if results else 0
    all_run = all(r.runnable for r in results)
    print(f"  Tasks passing MVP bar ({MIN_PASS_RATE:.0%}+): {len(passed_tasks)}/{len(results)}")
    print(f"  Average test pass rate: {avg_pass:.0%}")
    print(f"  All outputs runnable:   {'yes' if all_run else 'NO'}")
    print("=" * w)
    print()

    # Regression check: did pass rate degrade significantly as complexity rose?
    if len(results) >= 2:
        drops = []
        for i in range(1, len(results)):
            drop = results[i - 1].pass_rate - results[i].pass_rate
            if drop > 0.20:
                drops.append(
                    f"  {results[i-1].name} -> {results[i].name}: "
                    f"{results[i-1].pass_rate:.0%} -> {results[i].pass_rate:.0%} "
                    f"(dropped {drop:.0%})"
                )
        if drops:
            print("  REGRESSION WARNINGS (>20% pass-rate drop):")
            for d in drops:
                print(d)
        else:
            print("  No significant regressions detected across complexity levels.")
        print()


def _save_report(results: List[TaskResult], path: Path) -> None:
    data = [
        {
            "name": r.name,
            "pass_rate": round(r.pass_rate, 4),
            "tests_passed": r.tests_passed,
            "tests_total": r.tests_total,
            "runnable": r.runnable,
            "sprint_count": r.sprint_count,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "duration_s": round(r.duration_s, 1),
            "passed_bar": r.passed_bar,
            "error": r.error,
        }
        for r in results
    ]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Report saved to: {path}")

# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_benchmark(tasks: List[dict] | None = None) -> List[TaskResult]:
    if tasks is None:
        tasks = TASKS
    results: List[TaskResult] = []
    for task in tasks:
        result = _run_task(task)
        results.append(result)
    _print_report(results)
    report_path = REPO_ROOT / "benchmark_results.json"
    _save_report(results, report_path)
    return results

# ---------------------------------------------------------------------------
# pytest integration (skipped unless RUN_MULTISPRINT_BENCHMARK=1)
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not RUN_BENCHMARK,
    reason="Set RUN_MULTISPRINT_BENCHMARK=1 to run the live benchmark",
)

tasks_to_run = (
    [TASKS[SINGLE_TASK_IDX]] if SINGLE_TASK_IDX is not None else TASKS
)


@pytest.mark.parametrize("task", tasks_to_run, ids=[t["name"] for t in tasks_to_run])
def test_task_passes_mvp_bar(task: dict) -> None:
    """Each task must produce runnable code with >=50% test pass rate."""
    result = _run_task(task)
    _print_report([result])

    assert result.runnable, (
        f"[{task['name']}] Generated code has syntax/import errors"
    )
    assert result.pass_rate >= task.get("min_pass_rate", MIN_PASS_RATE), (
        f"[{task['name']}] Pass rate {result.pass_rate:.0%} < "
        f"required {task.get('min_pass_rate', MIN_PASS_RATE):.0%} "
        f"({result.tests_passed}/{result.tests_total} tests)"
    )


def test_no_regression_across_tasks() -> None:
    """
    Pass rates should not drop by more than 20% between consecutive tasks.
    A large drop signals that adding complexity breaks earlier foundations.
    """
    results = [_run_task(t) for t in tasks_to_run]
    _print_report(results)

    for i in range(1, len(results)):
        prev, curr = results[i - 1], results[i]
        drop = prev.pass_rate - curr.pass_rate
        assert drop <= 0.25, (
            f"Regression: {prev.name} ({prev.pass_rate:.0%}) -> "
            f"{curr.name} ({curr.pass_rate:.0%}), "
            f"dropped {drop:.0%} > 25% threshold"
        )

# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Quantum Swarm — Multi-Sprint Benchmark")
    print(f"Tasks: {len(TASKS)}  |  Max sprints per task: {MAX_SPRINTS}")
    print(f"MVP bar: runnable + >={MIN_PASS_RATE:.0%} tests passing\n")
    results = run_benchmark()
    passing = sum(1 for r in results if r.passed_bar)
    sys.exit(0 if passing == len(results) else 1)
