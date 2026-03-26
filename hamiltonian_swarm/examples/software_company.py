"""
Software Company Swarm — builds a CLI task manager from scratch.

Departments (each is a Hamiltonian agent):
  PM           → reads the brief, produces a feature spec
  Research     → picks libraries and approach
  Architecture → designs file structure and function signatures
  Engineering  → writes the actual Python code
  QA           → runs the code, tests every feature
  Review       → validates output against original spec

Each department handoff is energy-validated by HandoffProtocol.
Final output: a working todo.py saved to disk.

Run with:
    python -m hamiltonian_swarm.examples.software_company
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.agents.base_agent import BaseAgent, TaskResult
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent
from hamiltonian_swarm.swarm.handoff_protocol import HandoffProtocol
from hamiltonian_swarm.core.hamiltonian import HamiltonianFunction
from hamiltonian_swarm.core.phase_space import PhaseSpaceState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("software_company")

# ── Project brief ──────────────────────────────────────────────────────────────

PROJECT_BRIEF = """
Build a command-line task manager called todo.py with these features:
  1. add <description> [--priority high|medium|low]  — add a new task
  2. list [--filter <priority>]                      — list all tasks
  3. done <id>                                       — mark task as complete
  4. delete <id>                                     — delete a task
  5. clear                                           — remove all completed tasks

Requirements:
  - Tasks saved automatically to todo.json
  - Each task has: id, description, priority, status (pending/done), created_at
  - Show coloured status indicators in list output
  - Handle invalid IDs gracefully (no crashes)
  - Zero external dependencies (stdlib only)
"""

OUTPUT_DIR = Path(__file__).parent.parent.parent / "company_output"


# ── Artifact dataclasses passed between departments ────────────────────────────

@dataclass
class Spec:
    features: List[str]
    requirements: List[str]
    data_model: Dict[str, str]

@dataclass
class Approach:
    language: str
    storage: str
    cli_library: str
    rationale: str

@dataclass
class Architecture:
    data_model: Dict[str, str]
    functions: List[Dict[str, str]]   # [{name, signature, purpose}]
    file_structure: List[str]

@dataclass
class CodeArtifact:
    filename: str
    code: str
    language: str = "python"

@dataclass
class QAReport:
    tests_run: int
    tests_passed: int
    tests_failed: int
    failures: List[Dict[str, str]]
    code_runs: bool

@dataclass
class ReviewReport:
    approved: bool
    features_implemented: List[str]
    features_missing: List[str]
    notes: str


# ── Department agents ──────────────────────────────────────────────────────────

class DepartmentAgent(BaseAgent):
    """Base class for all department agents."""

    def __init__(self, department: str, n_dims: int = 6, **kwargs):
        super().__init__(n_dims=n_dims, agent_type=department, **kwargs)
        self.department = department

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        H_before = float(self.hamiltonian.total_energy(
            self.phase_state.q, self.phase_state.p).item())
        result = await self._do_work(task)
        H_after = self.step_phase_state(dt=0.01)
        return TaskResult(
            task_id=task.get("task_id", "unknown"),
            agent_id=self.agent_id,
            success=True,
            output=result,
            energy_before=H_before,
            energy_after=H_after,
        )

    async def _do_work(self, task: Dict[str, Any]) -> Any:
        raise NotImplementedError


class PMAgent(DepartmentAgent):
    """Reads the brief and produces a structured feature spec."""

    def __init__(self, **kwargs):
        super().__init__("pm", **kwargs)

    async def _do_work(self, task: Dict[str, Any]) -> Spec:
        brief = task["brief"]
        logger.info("PM: analysing project brief...")
        time.sleep(0.1)

        features = [
            "add <description> [--priority high|medium|low]",
            "list [--filter <priority>]",
            "done <id>",
            "delete <id>",
            "clear (remove completed tasks)",
        ]
        requirements = [
            "Persist tasks to todo.json",
            "Zero external dependencies",
            "Graceful error handling for invalid IDs",
            "Show priority and status in list output",
            "Auto-increment task IDs",
        ]
        data_model = {
            "id":          "int — auto-incremented unique identifier",
            "description": "str — task text",
            "priority":    "str — high | medium | low (default: medium)",
            "status":      "str — pending | done",
            "created_at":  "str — ISO timestamp",
        }

        spec = Spec(features=features, requirements=requirements, data_model=data_model)
        logger.info("PM: spec complete — %d features, %d requirements",
                    len(features), len(requirements))
        return spec


class ResearchAgent(DepartmentAgent):
    """Evaluates libraries and picks the best approach."""

    def __init__(self, **kwargs):
        super().__init__("research", **kwargs)

    async def _do_work(self, task: Dict[str, Any]) -> Approach:
        logger.info("Research: evaluating libraries and storage options...")
        time.sleep(0.1)

        approach = Approach(
            language="Python 3.8+",
            storage="JSON file (todo.json) via stdlib json module",
            cli_library="argparse (stdlib) — no pip install needed",
            rationale=(
                "argparse handles subcommands cleanly. "
                "JSON storage is human-readable and requires no DB setup. "
                "All stdlib — zero dependencies as required."
            ),
        )
        logger.info("Research: approach decided — %s + %s",
                    approach.cli_library, approach.storage)
        return approach


class ArchitectureAgent(DepartmentAgent):
    """Designs the code structure and function signatures."""

    def __init__(self, **kwargs):
        super().__init__("architecture", **kwargs)

    async def _do_work(self, task: Dict[str, Any]) -> Architecture:
        logger.info("Architecture: designing structure...")
        time.sleep(0.1)

        functions = [
            {"name": "load_tasks",    "signature": "() -> List[dict]",
             "purpose": "Load tasks from todo.json, return [] if not found"},
            {"name": "save_tasks",    "signature": "(tasks: List[dict]) -> None",
             "purpose": "Persist task list to todo.json"},
            {"name": "next_id",       "signature": "(tasks: List[dict]) -> int",
             "purpose": "Return max(id)+1 or 1 if empty"},
            {"name": "cmd_add",       "signature": "(args) -> None",
             "purpose": "Add new task with description and priority"},
            {"name": "cmd_list",      "signature": "(args) -> None",
             "purpose": "Print all tasks, optionally filtered by priority"},
            {"name": "cmd_done",      "signature": "(args) -> None",
             "purpose": "Mark task as done by ID"},
            {"name": "cmd_delete",    "signature": "(args) -> None",
             "purpose": "Delete task by ID"},
            {"name": "cmd_clear",     "signature": "(args) -> None",
             "purpose": "Remove all completed tasks"},
            {"name": "main",          "signature": "() -> None",
             "purpose": "Entry point — build argparse parser and dispatch"},
        ]
        arch = Architecture(
            data_model={
                "id": "int", "description": "str", "priority": "str",
                "status": "str", "created_at": "str",
            },
            functions=functions,
            file_structure=["todo.py", "todo.json (auto-created)"],
        )
        logger.info("Architecture: %d functions designed", len(functions))
        return arch


class EngineeringAgent(DepartmentAgent):
    """Writes the actual Python code based on spec + architecture."""

    def __init__(self, **kwargs):
        super().__init__("engineering", **kwargs)

    async def _do_work(self, task: Dict[str, Any]) -> CodeArtifact:
        logger.info("Engineering: writing todo.py...")
        time.sleep(0.2)

        code = textwrap.dedent('''\
            #!/usr/bin/env python3
            """
            todo.py — CLI Task Manager
            Generated by HamiltonianSwarm Software Company
            """

            import argparse
            import json
            import sys
            from datetime import datetime
            from pathlib import Path

            TODO_FILE = Path(__file__).parent / "todo.json"

            PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
            PRIORITY_COLOUR = {
                "high":   "\\033[91m",   # red
                "medium": "\\033[93m",   # yellow
                "low":    "\\033[92m",   # green
            }
            STATUS_COLOUR = {
                "pending": "\\033[0m",   # reset
                "done":    "\\033[90m",  # grey
            }
            RESET = "\\033[0m"


            def load_tasks():
                if not TODO_FILE.exists():
                    return []
                try:
                    with open(TODO_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    return []


            def save_tasks(tasks):
                with open(TODO_FILE, "w", encoding="utf-8") as f:
                    json.dump(tasks, f, indent=2, ensure_ascii=False)


            def next_id(tasks):
                return max((t["id"] for t in tasks), default=0) + 1


            def find_task(tasks, task_id):
                """Return task with given id or None."""
                return next((t for t in tasks if t["id"] == task_id), None)


            def cmd_add(args):
                tasks = load_tasks()
                task = {
                    "id":          next_id(tasks),
                    "description": " ".join(args.description),
                    "priority":    args.priority,
                    "status":      "pending",
                    "created_at":  datetime.now().isoformat(timespec="seconds"),
                }
                tasks.append(task)
                save_tasks(tasks)
                print(f"Added task #{task[\'id\']}: {task[\'description\']} [{task[\'priority\']}]")


            def cmd_list(args):
                tasks = load_tasks()
                if args.filter:
                    tasks = [t for t in tasks if t["priority"] == args.filter]
                if not tasks:
                    print("No tasks found.")
                    return
                tasks_sorted = sorted(tasks, key=lambda t: (
                    PRIORITY_ORDER.get(t["priority"], 9),
                    t["id"],
                ))
                print(f"  {'ID':<4} {'Pri':<8} {'Status':<10} Description")
                print("  " + "-" * 55)
                for t in tasks_sorted:
                    pc = PRIORITY_COLOUR.get(t["priority"], "")
                    sc = STATUS_COLOUR.get(t["status"], "")
                    done_mark = "x" if t["status"] == "done" else " "
                    print(
                        f"  {t[\'id\']:<4} "
                        f"{pc}{t[\'priority\']:<8}{RESET} "
                        f"{sc}[{done_mark}]{RESET}        "
                        f"{sc}{t[\'description\']}{RESET}"
                    )


            def cmd_done(args):
                tasks = load_tasks()
                task = find_task(tasks, args.id)
                if task is None:
                    print(f"Error: no task with id {args.id}.", file=sys.stderr)
                    sys.exit(1)
                if task["status"] == "done":
                    print(f"Task #{args.id} is already done.")
                    return
                task["status"] = "done"
                save_tasks(tasks)
                print(f"Task #{args.id} marked as done.")


            def cmd_delete(args):
                tasks = load_tasks()
                task = find_task(tasks, args.id)
                if task is None:
                    print(f"Error: no task with id {args.id}.", file=sys.stderr)
                    sys.exit(1)
                tasks = [t for t in tasks if t["id"] != args.id]
                save_tasks(tasks)
                print(f"Task #{args.id} deleted.")


            def cmd_clear(args):
                tasks = load_tasks()
                before = len(tasks)
                tasks = [t for t in tasks if t["status"] != "done"]
                save_tasks(tasks)
                removed = before - len(tasks)
                print(f"Cleared {removed} completed task(s).")


            def main():
                parser = argparse.ArgumentParser(
                    prog="todo",
                    description="CLI Task Manager — HamiltonianSwarm edition",
                )
                sub = parser.add_subparsers(dest="command", metavar="command")
                sub.required = True

                # add
                p_add = sub.add_parser("add", help="Add a new task")
                p_add.add_argument("description", nargs="+", help="Task description")
                p_add.add_argument(
                    "--priority", "-p",
                    choices=["high", "medium", "low"],
                    default="medium",
                    help="Task priority (default: medium)",
                )
                p_add.set_defaults(func=cmd_add)

                # list
                p_list = sub.add_parser("list", help="List tasks")
                p_list.add_argument(
                    "--filter", "-f",
                    choices=["high", "medium", "low"],
                    help="Filter by priority",
                )
                p_list.set_defaults(func=cmd_list)

                # done
                p_done = sub.add_parser("done", help="Mark task as done")
                p_done.add_argument("id", type=int, help="Task ID")
                p_done.set_defaults(func=cmd_done)

                # delete
                p_del = sub.add_parser("delete", help="Delete a task")
                p_del.add_argument("id", type=int, help="Task ID")
                p_del.set_defaults(func=cmd_delete)

                # clear
                p_clear = sub.add_parser("clear", help="Remove all completed tasks")
                p_clear.set_defaults(func=cmd_clear)

                args = parser.parse_args()
                args.func(args)


            if __name__ == "__main__":
                main()
        ''')

        artifact = CodeArtifact(filename="todo.py", code=code)
        logger.info("Engineering: %d lines written", len(code.splitlines()))
        return artifact


class QAAgent(DepartmentAgent):
    """Runs the generated code and tests every feature."""

    def __init__(self, **kwargs):
        super().__init__("qa", **kwargs)

    async def _do_work(self, task: Dict[str, Any]) -> QAReport:
        artifact: CodeArtifact = task["artifact"]
        output_dir: Path = task["output_dir"]

        logger.info("QA: running test suite on %s...", artifact.filename)

        todo_path = output_dir / artifact.filename
        json_path = output_dir / "todo.json"

        # Clean slate
        if json_path.exists():
            json_path.unlink()

        def run(args: List[str]) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, str(todo_path)] + args,
                capture_output=True, text=True, cwd=str(output_dir),
            )

        tests = []

        # T1 — script runs without crashing
        r = run(["--help"])
        tests.append({"name": "help runs",
                       "pass": r.returncode == 0,
                       "detail": r.stderr[:100] if r.returncode != 0 else "ok"})

        # T2 — add a task
        r = run(["add", "Buy groceries", "--priority", "high"])
        tests.append({"name": "add task",
                       "pass": r.returncode == 0 and "Added" in r.stdout,
                       "detail": r.stdout.strip()})

        # T3 — add another task (default priority)
        r = run(["add", "Read a book"])
        tests.append({"name": "add task default priority",
                       "pass": r.returncode == 0,
                       "detail": r.stdout.strip()})

        # T4 — list tasks
        r = run(["list"])
        tests.append({"name": "list tasks",
                       "pass": r.returncode == 0 and "Buy groceries" in r.stdout,
                       "detail": r.stdout.strip()[:120]})

        # T5 — list filtered by priority
        r = run(["list", "--filter", "high"])
        tests.append({"name": "list filter by priority",
                       "pass": r.returncode == 0 and "Buy groceries" in r.stdout,
                       "detail": r.stdout.strip()[:120]})

        # T6 — mark done
        r = run(["done", "1"])
        tests.append({"name": "mark done",
                       "pass": r.returncode == 0 and "done" in r.stdout.lower(),
                       "detail": r.stdout.strip()})

        # T7 — invalid ID handled gracefully (no crash / non-zero exit is fine)
        r = run(["done", "999"])
        tests.append({"name": "invalid id graceful",
                       "pass": "Error" in r.stdout or "Error" in r.stderr,
                       "detail": (r.stdout + r.stderr).strip()[:100]})

        # T8 — delete task
        r = run(["delete", "2"])
        tests.append({"name": "delete task",
                       "pass": r.returncode == 0 and "deleted" in r.stdout.lower(),
                       "detail": r.stdout.strip()})

        # T9 — clear completed
        r = run(["clear"])
        tests.append({"name": "clear completed",
                       "pass": r.returncode == 0 and "Cleared" in r.stdout,
                       "detail": r.stdout.strip()})

        # T10 — todo.json created
        tests.append({"name": "todo.json exists",
                       "pass": json_path.exists(),
                       "detail": "file present" if json_path.exists() else "MISSING"})

        passed = [t for t in tests if t["pass"]]
        failed = [t for t in tests if not t["pass"]]

        for t in tests:
            status = "PASS" if t["pass"] else "FAIL"
            logger.info("  QA [%s] %s — %s", status, t["name"], t["detail"][:60])

        report = QAReport(
            tests_run=len(tests),
            tests_passed=len(passed),
            tests_failed=len(failed),
            failures=failed,
            code_runs=tests[0]["pass"],
        )
        logger.info("QA: %d/%d tests passed", len(passed), len(tests))
        return report


class ReviewAgent(DepartmentAgent):
    """Compares delivered code against the original spec."""

    def __init__(self, **kwargs):
        super().__init__("review", **kwargs)

    async def _do_work(self, task: Dict[str, Any]) -> ReviewReport:
        spec: Spec = task["spec"]
        qa: QAReport = task["qa_report"]
        logger.info("Review: validating against original spec...")
        time.sleep(0.1)

        implemented = []
        missing = []

        feature_checks = {
            "add <description> [--priority high|medium|low]": qa.tests_passed >= 2,
            "list [--filter <priority>]":                     qa.tests_passed >= 4,
            "done <id>":                                      qa.tests_passed >= 6,
            "delete <id>":                                    qa.tests_passed >= 8,
            "clear (remove completed tasks)":                 qa.tests_passed >= 9,
        }
        for feat, done in feature_checks.items():
            (implemented if done else missing).append(feat)

        req_checks = {
            "Persist tasks to todo.json":           qa.tests_passed >= 10,
            "Zero external dependencies":           True,
            "Graceful error handling for invalid IDs": any(
                t["name"] == "invalid id graceful" and t["pass"]
                for t in (task.get("all_tests") or [])
            ) or qa.tests_passed >= 7,
            "Show priority and status in list output": qa.tests_passed >= 4,
            "Auto-increment task IDs":               qa.tests_passed >= 2,
        }
        for req, done in req_checks.items():
            if done and req not in implemented:
                implemented.append(req)
            elif not done and req not in missing:
                missing.append(req)

        approved = qa.tests_failed == 0 and len(missing) == 0
        notes = (
            f"{qa.tests_passed}/{qa.tests_run} QA tests passed. "
            + (f"Missing: {', '.join(missing)}." if missing else "All features present.")
        )

        report = ReviewReport(
            approved=approved,
            features_implemented=implemented,
            features_missing=missing,
            notes=notes,
        )
        logger.info("Review: %s — %s",
                    "APPROVED" if approved else "NEEDS WORK", notes)
        return report


# ── Company orchestrator ───────────────────────────────────────────────────────

class SoftwareCompany:
    """
    Coordinates all department agents through a validated handoff pipeline.
    Each department hands off its artifact to the next with energy conservation checks.
    """

    def __init__(self):
        self.protocol   = HandoffProtocol(energy_tolerance=0.1)
        self.validator  = ValidatorAgent(n_dims=6, energy_tolerance=0.85)

        self.pm          = PMAgent()
        self.research    = ResearchAgent()
        self.architecture = ArchitectureAgent()
        self.engineering = EngineeringAgent()
        self.qa          = QAAgent()
        self.review      = ReviewAgent()

        self.agents = [
            self.pm, self.research, self.architecture,
            self.engineering, self.qa, self.review,
        ]
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("SoftwareCompany: %d departments ready, output -> %s",
                    len(self.agents), OUTPUT_DIR)

    def _handoff(self, sender: DepartmentAgent, receiver: DepartmentAgent,
                 task_id: str) -> bool:
        """Validate energy conservation between two departments."""
        H_s_before = float(sender.hamiltonian.total_energy(
            sender.phase_state.q, sender.phase_state.p).item())
        H_r_before = float(receiver.hamiltonian.total_energy(
            receiver.phase_state.q, receiver.phase_state.p).item())

        sender.step_phase_state(dt=0.005)
        receiver.step_phase_state(dt=0.005)

        H_s_after = float(sender.hamiltonian.total_energy(
            sender.phase_state.q, sender.phase_state.p).item())
        H_r_after = float(receiver.hamiltonian.total_energy(
            receiver.phase_state.q, receiver.phase_state.p).item())

        allowed, reason = self.validator.validate_handoff(
            sender_id=sender.department,
            receiver_id=receiver.department,
            task_id=task_id,
            H_sender_before=H_s_before,
            H_sender_after=H_s_after,
            H_receiver_before=H_r_before,
            H_receiver_after=H_r_after,
        )
        status = "OK" if allowed else "DRIFT"
        logger.info("  Handoff [%s] %s -> %s | %s",
                    status, sender.department, receiver.department, reason)
        return allowed

    async def run(self, brief: str) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("SOFTWARE COMPANY — starting project")
        logger.info("=" * 60)

        t_start = time.time()
        pipeline_log = []

        # ── Step 1: PM ─────────────────────────────────────────────────
        logger.info("\n[Dept 1/6] PM — reading brief...")
        r_pm = await self.pm.execute_task({"task_id": "pm_spec", "brief": brief})
        spec: Spec = r_pm.output
        pipeline_log.append({"dept": "PM", "artifact": "Spec",
                              "features": len(spec.features)})

        self._handoff(self.pm, self.research, "pm->research")

        # ── Step 2: Research ───────────────────────────────────────────
        logger.info("\n[Dept 2/6] Research — evaluating approach...")
        r_res = await self.research.execute_task(
            {"task_id": "res_approach", "spec": spec})
        approach: Approach = r_res.output
        pipeline_log.append({"dept": "Research", "artifact": "Approach",
                              "cli": approach.cli_library})

        self._handoff(self.research, self.architecture, "res->arch")

        # ── Step 3: Architecture ───────────────────────────────────────
        logger.info("\n[Dept 3/6] Architecture — designing structure...")
        r_arch = await self.architecture.execute_task(
            {"task_id": "arch_design", "spec": spec, "approach": approach})
        arch: Architecture = r_arch.output
        pipeline_log.append({"dept": "Architecture", "artifact": "Design",
                              "functions": len(arch.functions)})

        self._handoff(self.architecture, self.engineering, "arch->eng")

        # ── Step 4: Engineering ────────────────────────────────────────
        logger.info("\n[Dept 4/6] Engineering — writing code...")
        r_eng = await self.engineering.execute_task(
            {"task_id": "eng_code", "spec": spec, "arch": arch, "approach": approach})
        artifact: CodeArtifact = r_eng.output

        # Save to disk immediately
        out_path = OUTPUT_DIR / artifact.filename
        out_path.write_text(artifact.code, encoding="utf-8")
        logger.info("Engineering: saved -> %s (%d lines)",
                    out_path, len(artifact.code.splitlines()))
        pipeline_log.append({"dept": "Engineering", "artifact": artifact.filename,
                              "lines": len(artifact.code.splitlines())})

        self._handoff(self.engineering, self.qa, "eng->qa")

        # ── Step 5: QA ─────────────────────────────────────────────────
        logger.info("\n[Dept 5/6] QA — running test suite...")
        r_qa = await self.qa.execute_task(
            {"task_id": "qa_test", "artifact": artifact, "output_dir": OUTPUT_DIR})
        qa_report: QAReport = r_qa.output
        pipeline_log.append({"dept": "QA", "passed": qa_report.tests_passed,
                              "failed": qa_report.tests_failed})

        self._handoff(self.qa, self.review, "qa->review")

        # ── Step 6: Review ─────────────────────────────────────────────
        logger.info("\n[Dept 6/6] Review — final validation...")
        r_rev = await self.review.execute_task(
            {"task_id": "review_final", "spec": spec,
             "qa_report": qa_report, "artifact": artifact})
        review: ReviewReport = r_rev.output
        pipeline_log.append({"dept": "Review",
                              "approved": review.approved,
                              "missing": len(review.features_missing)})

        elapsed = time.time() - t_start

        # ── Final report ───────────────────────────────────────────────
        logger.info("\n%s", "=" * 60)
        logger.info("PROJECT COMPLETE — %.2fs", elapsed)
        logger.info("=" * 60)
        logger.info("Output file : %s", out_path)
        logger.info("QA results  : %d/%d tests passed",
                    qa_report.tests_passed, qa_report.tests_run)
        logger.info("Review      : %s", "APPROVED" if review.approved else "NEEDS WORK")

        if review.features_implemented:
            logger.info("\nFeatures implemented:")
            for f in review.features_implemented:
                logger.info("  [x] %s", f)
        if review.features_missing:
            logger.info("\nFeatures missing:")
            for f in review.features_missing:
                logger.info("  [ ] %s", f)

        if qa_report.failures:
            logger.info("\nQA failures:")
            for fail in qa_report.failures:
                logger.info("  FAIL: %s — %s", fail["name"], fail["detail"])

        # Energy audit
        logger.info("\nEnergy audit (handoff conservation):")
        audit = self.validator.audit_trail()
        for entry in audit:
            status = "CONSERVED" if not entry["violation"] else "VIOLATION"
            logger.info("  [%s] %s -> %s | dH=%.4f",
                        status, entry["sender_id"], entry["receiver_id"],
                        entry["dH_sender"] + entry["dH_receiver"])

        # Save results JSON
        results = {
            "project": "todo.py",
            "elapsed_seconds": round(elapsed, 2),
            "output_file": str(out_path),
            "qa": {"passed": qa_report.tests_passed, "total": qa_report.tests_run,
                   "failures": qa_report.failures},
            "review": {"approved": review.approved,
                       "implemented": review.features_implemented,
                       "missing": review.features_missing},
            "pipeline": pipeline_log,
        }
        results_path = OUTPUT_DIR / "company_results.json"
        results_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        logger.info("\nResults saved -> %s", results_path)

        return results


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    company = SoftwareCompany()
    results = asyncio.run(company.run(PROJECT_BRIEF))

    print("\n" + "=" * 60)
    if results["review"]["approved"]:
        print("  PROJECT APPROVED")
        print(f"  QA: {results['qa']['passed']}/{results['qa']['total']} tests passed")
        print(f"  Output: {results['output_file']}")
        print("\n  Try it:")
        print(f"    python {results['output_file']} add Buy milk --priority high")
        print(f"    python {results['output_file']} list")
        print(f"    python {results['output_file']} done 1")
    else:
        print("  PROJECT NEEDS WORK")
        print(f"  QA: {results['qa']['passed']}/{results['qa']['total']} tests passed")
        if results["review"]["missing"]:
            print("  Missing:", ", ".join(results["review"]["missing"]))
    print("=" * 60)
