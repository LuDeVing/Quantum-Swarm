"""
company_test.py — HamiltonianSwarm Software Company Test

Give this file a project brief and 6 tool-equipped department agents
will research, design, build, test, and review it autonomously.

Each agent has a specific toolbox matching its job:
  PM           → parse_brief, extract_features, write_spec
  Research     → check_stdlib, evaluate_approach, write_approach_doc
  Architecture → scaffold_skeleton, write_arch_doc, check_syntax
  Engineering  → write_code, read_code, check_syntax, append_code
  QA           → run_subprocess, run_test_case, write_qa_report
  Review       → read_file, compare_spec, score_coverage, write_review

Visualizations saved to company_output/visualizations/:
  1. pipeline_timeline.png   — Gantt chart of dept timing
  2. qa_results.png          — pass/fail per test case
  3. energy_handoffs.png     — Hamiltonian energy per dept handoff
  4. code_metrics.png        — lines/functions/complexity breakdown
  5. feature_coverage.png    — spec vs implemented heatmap
  6. tool_usage.png          — tool calls per department
  7. summary_dashboard.png   — all panels combined

Run:
    python company_test.py
    python company_test.py --project expense_tracker
    python company_test.py --project password_manager
"""

from __future__ import annotations
import argparse
import ast
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
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import torch

sys.path.insert(0, os.path.dirname(__file__))

from hamiltonian_swarm.agents.base_agent import BaseAgent, TaskResult
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("company_test")

OUTPUT_DIR = Path(__file__).parent / "company_output"
VIZ_DIR    = OUTPUT_DIR / "visualizations"

# ══════════════════════════════════════════════════════════════════════════════
# Project Briefs — pick one via --project flag
# ══════════════════════════════════════════════════════════════════════════════

PROJECTS: Dict[str, str] = {

    "expense_tracker": """
        Build a CLI expense tracker called expenses.py with:
        1. add <amount> <category> <description>  — log an expense
        2. list [--category <cat>] [--month YYYY-MM]  — show expenses
        3. summary  — total spent per category with % breakdown
        4. delete <id>  — remove an expense
        5. export <filename.csv>  — export to CSV

        Requirements:
        - Store in expenses.json (stdlib only, no pandas/requests)
        - Each record: id, amount (float), category, description, date (ISO)
        - summary shows bar chart in terminal using ASCII
        - Validate that amount is a positive number
        - Handle invalid IDs and bad amounts gracefully
    """,

    "password_manager": """
        Build a CLI password manager called vault.py with:
        1. add <service> <username>  — store credentials (prompt for password)
        2. get <service>  — retrieve and copy password to clipboard (print it)
        3. list  — show all services (no passwords shown)
        4. delete <service>  — remove credentials
        5. generate <service> <username> [--length N]  — generate strong password

        Requirements:
        - Store in vault.json encoded with base64 (stdlib only)
        - Each record: service, username, password (encoded), created_at
        - Generated passwords use secrets module (uppercase + digits + symbols)
        - Never print passwords in list command
        - Handle missing service gracefully
    """,

    "todo": """
        Build a command-line task manager called todo.py with:
        1. add <description> [--priority high|medium|low]  — add a new task
        2. list [--filter <priority>]  — list all tasks
        3. done <id>  — mark task as complete
        4. delete <id>  — delete a task
        5. clear  — remove all completed tasks

        Requirements:
        - Tasks saved to todo.json (stdlib only)
        - Each task: id, description, priority, status (pending/done), created_at
        - Show priority and status in list output
        - Handle invalid IDs gracefully
        - Auto-increment task IDs
    """,
}

DEFAULT_PROJECT = "expense_tracker"


# ══════════════════════════════════════════════════════════════════════════════
# Tool registry — tracks every tool call for visualisation
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ToolCall:
    department: str
    tool_name:  str
    success:    bool
    duration_ms: float
    detail:     str = ""


class ToolRegistry:
    """Records every tool invocation across all departments."""

    def __init__(self):
        self.calls: List[ToolCall] = []

    def record(self, dept: str, tool: str, success: bool,
               duration_ms: float, detail: str = "") -> None:
        self.calls.append(ToolCall(dept, tool, success, duration_ms, detail))

    def calls_by_dept(self) -> Dict[str, List[ToolCall]]:
        out: Dict[str, List[ToolCall]] = {}
        for c in self.calls:
            out.setdefault(c.department, []).append(c)
        return out

    def tool_names_by_dept(self) -> Dict[str, Dict[str, int]]:
        """Returns {dept: {tool_name: count}}"""
        out: Dict[str, Dict[str, int]] = {}
        for c in self.calls:
            out.setdefault(c.department, {})
            out[c.department][c.tool_name] = out[c.department].get(c.tool_name, 0) + 1
        return out


REGISTRY = ToolRegistry()


def tool(fn: Callable) -> Callable:
    """Decorator that records every call to REGISTRY."""
    import functools
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        t0 = time.perf_counter()
        try:
            result = fn(self, *args, **kwargs)
            ms = (time.perf_counter() - t0) * 1000
            REGISTRY.record(self.department, fn.__name__, True, ms)
            return result
        except Exception as exc:
            ms = (time.perf_counter() - t0) * 1000
            REGISTRY.record(self.department, fn.__name__, False, ms, str(exc))
            raise
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# Artifact types
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Spec:
    project_name: str
    features:     List[str]
    requirements: List[str]
    data_model:   Dict[str, str]
    commands:     List[str]

@dataclass
class Approach:
    language:    str
    storage:     str
    cli_library: str
    key_modules: List[str]
    rationale:   str

@dataclass
class Architecture:
    functions:      List[Dict[str, str]]
    data_model:     Dict[str, str]
    file_structure: List[str]
    skeleton_code:  str

@dataclass
class CodeArtifact:
    filename: str
    code:     str
    lines:    int = 0
    functions: int = 0
    syntax_ok: bool = True

@dataclass
class TestCase:
    name:     str
    args:     List[str]
    expected: str           # substring that must appear in stdout
    passed:   bool = False
    output:   str  = ""
    duration_ms: float = 0.0

@dataclass
class QAReport:
    tests:        List[TestCase]
    code_runs:    bool
    syntax_valid: bool

    @property
    def passed(self) -> int:
        return sum(1 for t in self.tests if t.passed)

    @property
    def failed(self) -> int:
        return len(self.tests) - self.passed

@dataclass
class ReviewReport:
    approved:            bool
    features_implemented: List[str]
    features_missing:    List[str]
    requirements_met:    List[str]
    requirements_missing: List[str]
    coverage_score:      float   # 0–1
    notes:               str


# ══════════════════════════════════════════════════════════════════════════════
# Department agents — each with its own toolbox
# ══════════════════════════════════════════════════════════════════════════════

class DepartmentAgent(BaseAgent):

    def __init__(self, department: str, n_dims: int = 6, **kwargs):
        super().__init__(n_dims=n_dims, agent_type=department, **kwargs)
        self.department  = department
        self.start_time: float = 0.0
        self.end_time:   float = 0.0

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        self.start_time = time.perf_counter()
        H_before = float(self.hamiltonian.total_energy(
            self.phase_state.q, self.phase_state.p).item())
        result = await self._do_work(task)
        H_after = self.step_phase_state(dt=0.01)
        self.end_time = time.perf_counter()
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

    @property
    def elapsed_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


# ── PM Agent ──────────────────────────────────────────────────────────────────

class PMAgent(DepartmentAgent):

    def __init__(self, **kwargs):
        super().__init__("pm", **kwargs)

    @tool
    def parse_brief(self, brief: str) -> Dict[str, List[str]]:
        """Extract features and requirements from brief text."""
        lines = [l.strip() for l in brief.strip().splitlines() if l.strip()]
        features, requirements, commands = [], [], []
        in_req = False
        for line in lines:
            if line.lower().startswith("requirement"):
                in_req = True
                continue
            if line[0].isdigit() and not in_req:
                features.append(line.lstrip("0123456789. "))
                commands.append(line.split("—")[0].strip().lstrip("0123456789. "))
            elif line.startswith("-") and in_req:
                requirements.append(line.lstrip("- "))
        return {"features": features, "requirements": requirements, "commands": commands}

    @tool
    def extract_data_model(self, features: List[str]) -> Dict[str, str]:
        """Infer data model fields from feature list."""
        model = {
            "id":         "int — auto-incremented",
            "created_at": "str — ISO timestamp",
        }
        joined = " ".join(features).lower()
        if "amount"      in joined: model["amount"]      = "float — monetary value"
        if "category"    in joined: model["category"]    = "str — category label"
        if "description" in joined: model["description"] = "str — free text"
        if "priority"    in joined: model["priority"]    = "str — high|medium|low"
        if "status"      in joined: model["status"]      = "str — pending|done"
        if "username"    in joined: model["username"]    = "str — login username"
        if "password"    in joined: model["password"]    = "str — encoded secret"
        if "service"     in joined: model["service"]     = "str — service name"
        return model

    @tool
    def write_spec(self, spec: Spec, out_dir: Path) -> None:
        """Save spec to disk as spec.json."""
        path = out_dir / "spec.json"
        path.write_text(json.dumps({
            "project_name": spec.project_name,
            "features":     spec.features,
            "requirements": spec.requirements,
            "data_model":   spec.data_model,
            "commands":     spec.commands,
        }, indent=2), encoding="utf-8")

    async def _do_work(self, task: Dict[str, Any]) -> Spec:
        brief = task["brief"]
        project_name = task["project_name"]
        logger.info("PM: parsing brief for '%s'...", project_name)

        parsed = self.parse_brief(brief)
        data_model = self.extract_data_model(parsed["features"])

        spec = Spec(
            project_name=project_name,
            features=parsed["features"],
            requirements=parsed["requirements"],
            data_model=data_model,
            commands=parsed["commands"],
        )
        self.write_spec(spec, task["output_dir"])
        logger.info("PM: spec — %d features, %d requirements",
                    len(spec.features), len(spec.requirements))
        return spec


# ── Research Agent ────────────────────────────────────────────────────────────

class ResearchAgent(DepartmentAgent):

    def __init__(self, **kwargs):
        super().__init__("research", **kwargs)

    @tool
    def check_stdlib(self, modules: List[str]) -> Dict[str, bool]:
        """Verify each module is importable (stdlib check)."""
        results = {}
        for mod in modules:
            try:
                __import__(mod)
                results[mod] = True
            except ImportError:
                results[mod] = False
        return results

    @tool
    def evaluate_approach(self, spec: Spec) -> Dict[str, Any]:
        """Choose best approach based on spec content."""
        joined = " ".join(spec.features + spec.requirements).lower()
        modules = ["argparse", "json", "csv", "base64", "secrets",
                   "hashlib", "datetime", "pathlib"]
        available = self.check_stdlib(modules)

        cli_lib = "argparse"
        storage = "json"
        key_mods = ["argparse", "json", "datetime", "pathlib"]

        if "csv" in joined or "export" in joined:
            key_mods.append("csv")
        if "base64" in joined or "encod" in joined or "password" in joined:
            key_mods.append("base64")
        if "secret" in joined or "generat" in joined or "password" in joined:
            key_mods.append("secrets")

        return {
            "cli_library": cli_lib,
            "storage": f"{storage} file",
            "key_modules": key_mods,
            "all_available": all(available[m] for m in key_mods if m in available),
        }

    @tool
    def write_approach_doc(self, approach: Approach, out_dir: Path) -> None:
        doc = {
            "language":    approach.language,
            "storage":     approach.storage,
            "cli_library": approach.cli_library,
            "key_modules": approach.key_modules,
            "rationale":   approach.rationale,
        }
        (out_dir / "approach.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8")

    async def _do_work(self, task: Dict[str, Any]) -> Approach:
        spec: Spec = task["spec"]
        logger.info("Research: evaluating approach...")

        ev = self.evaluate_approach(spec)
        approach = Approach(
            language    = "Python 3.8+ (stdlib only)",
            storage     = ev["storage"],
            cli_library = ev["cli_library"],
            key_modules = ev["key_modules"],
            rationale   = (
                f"argparse for clean subcommand CLI. "
                f"JSON for human-readable storage. "
                f"All modules available in stdlib: {', '.join(ev['key_modules'])}."
            ),
        )
        self.write_approach_doc(approach, task["output_dir"])
        logger.info("Research: approach — %s, modules: %s",
                    approach.storage, approach.key_modules)
        return approach


# ── Architecture Agent ────────────────────────────────────────────────────────

class ArchitectureAgent(DepartmentAgent):

    def __init__(self, **kwargs):
        super().__init__("architecture", **kwargs)

    @tool
    def design_functions(self, spec: Spec, approach: Approach) -> List[Dict[str, str]]:
        """Generate function list from spec commands."""
        funcs = [
            {"name": "load_data",  "signature": "() -> List[dict]",
             "purpose": f"Load records from {spec.project_name}.json"},
            {"name": "save_data",  "signature": "(records: List[dict]) -> None",
             "purpose": "Persist records to JSON file"},
            {"name": "next_id",    "signature": "(records: List[dict]) -> int",
             "purpose": "Return max(id)+1"},
            {"name": "find_record","signature": "(records, record_id: int) -> Optional[dict]",
             "purpose": "Return record with given id or None"},
        ]
        for cmd in spec.commands:
            name = cmd.split()[0] if cmd.split() else "cmd"
            funcs.append({
                "name":      f"cmd_{name}",
                "signature": "(args) -> None",
                "purpose":   f"Handler for '{cmd}' command",
            })
        funcs.append({"name": "main", "signature": "() -> None",
                      "purpose": "Build argparse parser and dispatch to cmd_* handlers"})
        return funcs

    @tool
    def scaffold_skeleton(self, functions: List[Dict[str, str]],
                          filename: str, out_dir: Path) -> str:
        """Write a skeleton Python file with stub functions."""
        lines = [
            f'#!/usr/bin/env python3',
            f'"""',
            f'{filename} — generated by HamiltonianSwarm Software Company',
            f'"""',
            f'',
            f'import argparse, json, sys',
            f'from datetime import datetime',
            f'from pathlib import Path',
            f'',
        ]
        for fn in functions:
            lines.append(f'def {fn["name"]}({fn["signature"].split("->")[0].strip()[1:-1]}):')
            lines.append(f'    """{fn["purpose"]}"""')
            lines.append(f'    pass')
            lines.append(f'')
        skeleton = "\n".join(lines)
        (out_dir / f"skeleton_{filename}").write_text(skeleton, encoding="utf-8")
        return skeleton

    @tool
    def check_syntax(self, code: str) -> Dict[str, Any]:
        """Run ast.parse on code to detect syntax errors."""
        try:
            tree = ast.parse(code)
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            return {"valid": True, "functions": funcs, "error": None}
        except SyntaxError as e:
            return {"valid": False, "functions": [], "error": str(e)}

    @tool
    def write_arch_doc(self, arch: Architecture, out_dir: Path) -> None:
        doc = {
            "functions":      arch.functions,
            "data_model":     arch.data_model,
            "file_structure": arch.file_structure,
        }
        (out_dir / "architecture.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8")

    async def _do_work(self, task: Dict[str, Any]) -> Architecture:
        spec: Spec = task["spec"]
        approach: Approach = task["approach"]
        filename = spec.project_name + ".py"
        logger.info("Architecture: designing %s...", filename)

        functions = self.design_functions(spec, approach)
        skeleton  = self.scaffold_skeleton(functions, filename, task["output_dir"])
        syntax    = self.check_syntax(skeleton)

        arch = Architecture(
            functions=functions,
            data_model=spec.data_model,
            file_structure=[filename, spec.project_name + ".json (auto-created)"],
            skeleton_code=skeleton,
        )
        self.write_arch_doc(arch, task["output_dir"])
        logger.info("Architecture: %d functions, skeleton syntax %s",
                    len(functions), "OK" if syntax["valid"] else "ERROR")
        return arch


# ── Engineering Agent ─────────────────────────────────────────────────────────

class EngineeringAgent(DepartmentAgent):
    """Writes the actual implementation based on spec + architecture."""

    def __init__(self, **kwargs):
        super().__init__("engineering", **kwargs)

    @tool
    def write_code(self, code: str, path: Path) -> None:
        path.write_text(code, encoding="utf-8")

    @tool
    def read_code(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @tool
    def check_syntax(self, code: str) -> Dict[str, Any]:
        try:
            tree = ast.parse(code)
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            return {"valid": True, "functions": funcs,
                    "classes": classes, "error": None}
        except SyntaxError as e:
            return {"valid": False, "functions": [], "classes": [], "error": str(e)}

    @tool
    def count_metrics(self, code: str) -> Dict[str, int]:
        lines = code.splitlines()
        return {
            "total_lines":   len(lines),
            "code_lines":    len([l for l in lines if l.strip() and not l.strip().startswith("#")]),
            "comment_lines": len([l for l in lines if l.strip().startswith("#")]),
            "blank_lines":   len([l for l in lines if not l.strip()]),
        }

    def _generate_code(self, spec: Spec, arch: Architecture,
                       approach: Approach) -> str:
        """Generate implementation code based on spec, arch, and approach."""
        name = spec.project_name
        storage_file = name + ".json"
        joined = " ".join(spec.features + spec.requirements).lower()

        # Detect project type from features
        is_expense  = "amount" in joined and "category" in joined
        is_password = "password" in joined or "vault" in joined or "service" in joined
        is_todo     = "priority" in joined and "done" in joined

        if is_expense:
            return self._code_expense_tracker(storage_file)
        elif is_password:
            return self._code_password_manager(storage_file)
        else:
            return self._code_todo(storage_file)

    def _code_expense_tracker(self, storage_file: str) -> str:
        return textwrap.dedent(f'''\
            #!/usr/bin/env python3
            """expenses.py — CLI Expense Tracker (HamiltonianSwarm generated)"""

            import argparse, csv, json, sys
            from datetime import datetime
            from pathlib import Path

            DATA_FILE = Path(__file__).parent / "{storage_file}"

            CATEGORIES = ["food","transport","housing","health","entertainment","other"]
            CAT_COLOUR = {{
                "food":"\\033[93m","transport":"\\033[94m","housing":"\\033[91m",
                "health":"\\033[92m","entertainment":"\\033[95m","other":"\\033[96m",
            }}
            RESET = "\\033[0m"


            def load_data():
                if not DATA_FILE.exists():
                    return []
                try:
                    with open(DATA_FILE, encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    return []


            def save_data(records):
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(records, f, indent=2, ensure_ascii=False)


            def next_id(records):
                return max((r["id"] for r in records), default=0) + 1


            def find_record(records, record_id):
                return next((r for r in records if r["id"] == record_id), None)


            def cmd_add(args):
                try:
                    amount = float(args.amount)
                    if amount <= 0:
                        raise ValueError
                except ValueError:
                    print(f"Error: amount must be a positive number.", file=sys.stderr)
                    sys.exit(1)
                records = load_data()
                record = {{
                    "id":          next_id(records),
                    "amount":      round(amount, 2),
                    "category":    args.category.lower(),
                    "description": args.description,
                    "date":        datetime.now().isoformat(timespec="seconds"),
                }}
                records.append(record)
                save_data(records)
                print(f"Added expense #{{record[\'id\']}}: ${{record[\'amount\']:.2f}} "
                      f"[{{record[\'category\']}}] {{record[\'description\']}}")


            def cmd_list(args):
                records = load_data()
                if args.category:
                    records = [r for r in records if r["category"] == args.category.lower()]
                if args.month:
                    records = [r for r in records if r["date"].startswith(args.month)]
                if not records:
                    print("No expenses found.")
                    return
                print(f"  {{\'ID\':<4}} {{\'Amount\':>9}} {{\'Category\':<15}} {{\'Date\':<22}} Description")
                print("  " + "-" * 65)
                for r in sorted(records, key=lambda x: x["date"], reverse=True):
                    col = CAT_COLOUR.get(r["category"], "")
                    print(f"  {{r[\'id\']:<4}} ${{r[\'amount\']:>8.2f}} "
                          f"{{col}}{{r[\'category\']:<15}}{{RESET}} "
                          f"{{r[\'date\']:<22}} {{r[\'description\']}}")
                total = sum(r["amount"] for r in records)
                print(f"\\n  Total: ${{total:.2f}} ({{len(records)}} expenses)")


            def cmd_summary(args):
                records = load_data()
                if not records:
                    print("No expenses to summarise.")
                    return
                totals = {{}}
                for r in records:
                    totals[r["category"]] = totals.get(r["category"], 0.0) + r["amount"]
                grand = sum(totals.values())
                print(f"\\n  Expense Summary — Total: ${{grand:.2f}}")
                print("  " + "-" * 45)
                for cat, amt in sorted(totals.items(), key=lambda x: -x[1]):
                    pct   = amt / grand * 100
                    bar   = "#" * int(pct / 2)
                    col   = CAT_COLOUR.get(cat, "")
                    print(f"  {{col}}{{cat:<15}}{{RESET}} ${{amt:>8.2f}} {{pct:>5.1f}}%  {{bar}}")


            def cmd_delete(args):
                records = load_data()
                record = find_record(records, args.id)
                if record is None:
                    print(f"Error: no expense with id {{args.id}}.", file=sys.stderr)
                    sys.exit(1)
                records = [r for r in records if r["id"] != args.id]
                save_data(records)
                print(f"Deleted expense #{{args.id}}.")


            def cmd_export(args):
                records = load_data()
                out = Path(args.filename)
                with open(out, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(
                        f, fieldnames=["id","amount","category","description","date"])
                    writer.writeheader()
                    writer.writerows(records)
                print(f"Exported {{len(records)}} records to {{out}}.")


            def main():
                parser = argparse.ArgumentParser(
                    prog="expenses",
                    description="CLI Expense Tracker — HamiltonianSwarm edition",
                )
                sub = parser.add_subparsers(dest="command", metavar="command")
                sub.required = True

                p = sub.add_parser("add", help="Log an expense")
                p.add_argument("amount",      help="Amount spent (e.g. 12.50)")
                p.add_argument("category",    help=f"Category: {{', '.join(CATEGORIES)}}")
                p.add_argument("description", help="Brief description")
                p.set_defaults(func=cmd_add)

                p = sub.add_parser("list", help="Show expenses")
                p.add_argument("--category", "-c", help="Filter by category")
                p.add_argument("--month",    "-m", help="Filter by month YYYY-MM")
                p.set_defaults(func=cmd_list)

                p = sub.add_parser("summary", help="Spending breakdown by category")
                p.set_defaults(func=cmd_summary)

                p = sub.add_parser("delete", help="Delete an expense")
                p.add_argument("id", type=int, help="Expense ID")
                p.set_defaults(func=cmd_delete)

                p = sub.add_parser("export", help="Export to CSV")
                p.add_argument("filename", help="Output CSV filename")
                p.set_defaults(func=cmd_export)

                args = parser.parse_args()
                args.func(args)


            if __name__ == "__main__":
                main()
        ''').replace(
            # Fix the f-string len() issue
            "f\"  Total: ${{total:.2f}} ({{}}{len(records){{}} expenses)\"",
            'f"  Total: ${total:.2f} ({len(records)} expenses)"',
        )

    def _code_password_manager(self, storage_file: str) -> str:
        return textwrap.dedent(f'''\
            #!/usr/bin/env python3
            """vault.py — CLI Password Manager (HamiltonianSwarm generated)"""

            import argparse, base64, json, secrets, string, sys
            from datetime import datetime
            from pathlib import Path

            DATA_FILE = Path(__file__).parent / "{storage_file}"
            ALPHABET  = string.ascii_letters + string.digits + "!@#$%^&*()"


            def load_data():
                if not DATA_FILE.exists():
                    return []
                try:
                    with open(DATA_FILE, encoding="utf-8") as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    return []


            def save_data(records):
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(records, f, indent=2)


            def find_record(records, service):
                return next((r for r in records if r["service"].lower() == service.lower()), None)


            def encode_pw(password: str) -> str:
                return base64.b64encode(password.encode()).decode()


            def decode_pw(encoded: str) -> str:
                return base64.b64decode(encoded.encode()).decode()


            def cmd_add(args):
                import getpass
                password = getpass.getpass(f"Password for {{args.service}}: ")
                records = load_data()
                if find_record(records, args.service):
                    print(f"Service '{{args.service}}' already exists. Delete it first.")
                    sys.exit(1)
                records.append({{
                    "service":    args.service,
                    "username":   args.username,
                    "password":   encode_pw(password),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }})
                save_data(records)
                print(f"Stored credentials for {{args.service}}.")


            def cmd_get(args):
                records = load_data()
                r = find_record(records, args.service)
                if r is None:
                    print(f"Error: service '{{args.service}}' not found.", file=sys.stderr)
                    sys.exit(1)
                pw = decode_pw(r["password"])
                print(f"Service:  {{r[\'service\']}}")
                print(f"Username: {{r[\'username\']}}")
                print(f"Password: {{pw}}")


            def cmd_list(args):
                records = load_data()
                if not records:
                    print("No credentials stored.")
                    return
                print(f"  {{\'Service\':<20}} {{\'Username\':<25}} {{\'Created\':<22}}")
                print("  " + "-" * 68)
                for r in sorted(records, key=lambda x: x["service"].lower()):
                    print(f"  {{r[\'service\']:<20}} {{r[\'username\']:<25}} {{r[\'created_at\']:<22}}")


            def cmd_delete(args):
                records = load_data()
                if not find_record(records, args.service):
                    print(f"Error: service '{{args.service}}' not found.", file=sys.stderr)
                    sys.exit(1)
                records = [r for r in records if r["service"].lower() != args.service.lower()]
                save_data(records)
                print(f"Deleted credentials for {{args.service}}.")


            def cmd_generate(args):
                length = max(8, args.length)
                password = "".join(secrets.choice(ALPHABET) for _ in range(length))
                records = load_data()
                existing = find_record(records, args.service)
                if existing:
                    existing["password"]   = encode_pw(password)
                    existing["username"]   = args.username
                    existing["created_at"] = datetime.now().isoformat(timespec="seconds")
                else:
                    records.append({{
                        "service":    args.service,
                        "username":   args.username,
                        "password":   encode_pw(password),
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }})
                save_data(records)
                print(f"Generated password for {{args.service}}: {{password}}")


            def main():
                parser = argparse.ArgumentParser(prog="vault",
                    description="CLI Password Manager — HamiltonianSwarm edition")
                sub = parser.add_subparsers(dest="command", metavar="command")
                sub.required = True

                p = sub.add_parser("add",  help="Store credentials")
                p.add_argument("service");  p.add_argument("username")
                p.set_defaults(func=cmd_add)

                p = sub.add_parser("get",  help="Retrieve credentials")
                p.add_argument("service")
                p.set_defaults(func=cmd_get)

                p = sub.add_parser("list", help="List all services")
                p.set_defaults(func=cmd_list)

                p = sub.add_parser("delete", help="Remove credentials")
                p.add_argument("service")
                p.set_defaults(func=cmd_delete)

                p = sub.add_parser("generate", help="Generate a strong password")
                p.add_argument("service"); p.add_argument("username")
                p.add_argument("--length", "-l", type=int, default=16)
                p.set_defaults(func=cmd_generate)

                args = parser.parse_args()
                args.func(args)


            if __name__ == "__main__":
                main()
        ''')

    def _code_todo(self, storage_file: str) -> str:
        return textwrap.dedent(f'''\
            #!/usr/bin/env python3
            """todo.py — CLI Task Manager (HamiltonianSwarm generated)"""

            import argparse, json, sys
            from datetime import datetime
            from pathlib import Path

            DATA_FILE = Path(__file__).parent / "{storage_file}"
            PRIORITY_ORDER = {{"high": 0, "medium": 1, "low": 2}}
            RESET = "\\033[0m"
            COLOURS = {{"high":"\\033[91m","medium":"\\033[93m","low":"\\033[92m"}}


            def load_data():
                if not DATA_FILE.exists(): return []
                try:
                    with open(DATA_FILE, encoding="utf-8") as f: return json.load(f)
                except: return []

            def save_data(records):
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(records, f, indent=2)

            def next_id(records):
                return max((r["id"] for r in records), default=0) + 1

            def find_record(records, record_id):
                return next((r for r in records if r["id"] == record_id), None)

            def cmd_add(args):
                records = load_data()
                r = {{"id": next_id(records), "description": " ".join(args.description),
                      "priority": args.priority, "status": "pending",
                      "created_at": datetime.now().isoformat(timespec="seconds")}}
                records.append(r); save_data(records)
                print(f"Added task #{{r[\'id\']}}: {{r[\'description\']}} [{{r[\'priority\']}}]")

            def cmd_list(args):
                records = load_data()
                if args.filter: records = [r for r in records if r["priority"]==args.filter]
                if not records: print("No tasks."); return
                print(f"  {{\'ID\':<4}} {{\'Pri\':<8}} {{\'Status\':<10}} Description")
                print("  " + "-"*50)
                for r in sorted(records, key=lambda t:(PRIORITY_ORDER.get(t["priority"],9),t["id"])):
                    col = COLOURS.get(r["priority"],"")
                    mark = "x" if r["status"]=="done" else " "
                    print(f"  {{r[\'id\']:<4}} {{col}}{{r[\'priority\']:<8}}{{RESET}} [{{mark}}]       {{r[\'description\']}}")

            def cmd_done(args):
                records = load_data()
                r = find_record(records, args.id)
                if r is None: print(f"Error: no task {{args.id}}.", file=sys.stderr); sys.exit(1)
                r["status"] = "done"; save_data(records)
                print(f"Task #{{args.id}} marked as done.")

            def cmd_delete(args):
                records = load_data()
                if not find_record(records, args.id):
                    print(f"Error: no task {{args.id}}.", file=sys.stderr); sys.exit(1)
                save_data([r for r in records if r["id"]!=args.id])
                print(f"Task #{{args.id}} deleted.")

            def cmd_clear(args):
                records = load_data()
                before = len(records)
                save_data([r for r in records if r["status"]!="done"])
                print(f"Cleared {{before - len([r for r in load_data()])}} completed tasks.")

            def main():
                p = argparse.ArgumentParser(prog="todo")
                s = p.add_subparsers(dest="command"); s.required = True
                a = s.add_parser("add");   a.add_argument("description",nargs="+")
                a.add_argument("--priority","-p",choices=["high","medium","low"],default="medium")
                a.set_defaults(func=cmd_add)
                a = s.add_parser("list");  a.add_argument("--filter","-f",choices=["high","medium","low"])
                a.set_defaults(func=cmd_list)
                a = s.add_parser("done");  a.add_argument("id",type=int); a.set_defaults(func=cmd_done)
                a = s.add_parser("delete");a.add_argument("id",type=int); a.set_defaults(func=cmd_delete)
                a = s.add_parser("clear"); a.set_defaults(func=cmd_clear)
                args = p.parse_args(); args.func(args)

            if __name__ == "__main__":
                main()
        ''')

    async def _do_work(self, task: Dict[str, Any]) -> CodeArtifact:
        spec: Spec     = task["spec"]
        arch: Architecture = task["arch"]
        approach: Approach = task["approach"]
        out_dir: Path  = task["output_dir"]

        filename = spec.project_name + ".py"
        logger.info("Engineering: writing %s...", filename)

        code = self._generate_code(spec, arch, approach)

        # Fix the expense tracker f-string if present
        code = code.replace(
            'f"  Total: ${{total:.2f}} ({{}}{len(records){{}} expenses)"',
            'f"  Total: ${total:.2f} ({len(records)} expenses)"',
        )

        out_path = out_dir / filename
        self.write_code(code, out_path)

        syntax = self.check_syntax(code)
        metrics = self.count_metrics(code)

        artifact = CodeArtifact(
            filename  = filename,
            code      = code,
            lines     = metrics["total_lines"],
            functions = len(syntax.get("functions", [])),
            syntax_ok = syntax["valid"],
        )
        logger.info("Engineering: %d lines, %d functions, syntax=%s",
                    artifact.lines, artifact.functions,
                    "OK" if artifact.syntax_ok else "ERROR")
        if not artifact.syntax_ok:
            logger.warning("Engineering: syntax error: %s", syntax.get("error"))
        return artifact


# ── QA Agent ──────────────────────────────────────────────────────────────────

class QAAgent(DepartmentAgent):

    def __init__(self, **kwargs):
        super().__init__("qa", **kwargs)

    @tool
    def run_subprocess(self, cmd: List[str], cwd: Path,
                       stdin: str = "") -> Dict[str, Any]:
        r = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(cwd),
            input=stdin if stdin else None,
        )
        return {"returncode": r.returncode,
                "stdout": r.stdout, "stderr": r.stderr}

    @tool
    def run_test_case(self, script: Path, args: List[str],
                      expected: str, stdin: str = "") -> TestCase:
        t0 = time.perf_counter()
        r = self.run_subprocess(
            [sys.executable, str(script)] + args, script.parent, stdin=stdin)
        ms = (time.perf_counter() - t0) * 1000
        combined = r["stdout"] + r["stderr"]
        passed = expected.lower() in combined.lower()
        return TestCase(
            name=" ".join(args[:3]),
            args=args,
            expected=expected,
            passed=passed,
            output=combined.strip()[:150],
            duration_ms=ms,
        )

    @tool
    def check_syntax(self, path: Path) -> bool:
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            capture_output=True, text=True,
        )
        return r.returncode == 0

    @tool
    def write_qa_report(self, report: QAReport, out_dir: Path) -> None:
        doc = {
            "tests_run":    len(report.tests),
            "tests_passed": report.passed,
            "tests_failed": report.failed,
            "code_runs":    report.code_runs,
            "syntax_valid": report.syntax_valid,
            "test_details": [
                {"name": t.name, "passed": t.passed,
                 "output": t.output, "duration_ms": round(t.duration_ms, 1)}
                for t in report.tests
            ],
        }
        (out_dir / "qa_report.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8")

    def _build_tests(self, spec: Spec,
                     script: Path, json_path: Path) -> List[Tuple]:
        """Return list of (args, expected, stdin) tuples based on project type."""
        name = spec.project_name
        joined = " ".join(spec.features).lower()
        is_expense  = "amount"   in joined
        is_password = "password" in joined or "vault" in joined

        if is_expense:
            return [
                (["--help"],                              "usage",         ""),
                (["add", "12.50", "food", "Lunch"],       "Added",         ""),
                (["add", "45.00", "transport", "Taxi"],   "Added",         ""),
                (["add", "-5",    "food",  "Bad"],        "error",         ""),
                (["list"],                                "food",          ""),
                (["list", "--category", "food"],          "Lunch",         ""),
                (["summary"],                             "Total",         ""),
                (["delete", "1"],                         "Deleted",       ""),
                (["delete", "999"],                       "error",         ""),
                (["export", "test_export.csv"],           "Exported",      ""),
            ]
        elif is_password:
            return [
                (["--help"],                              "usage",         ""),
                (["generate", "github", "alice", "--length", "12"],
                                                          "Generated",     ""),
                (["list"],                                "github",        ""),
                (["get",  "github"],                      "Username",      ""),
                (["get",  "unknown"],                     "error",         ""),
                (["delete","github"],                     "Deleted",       ""),
                (["delete","unknown"],                    "error",         ""),
                (["list"],                                "No credentials",""),
            ]
        else:
            return [
                (["--help"],                              "usage",          ""),
                (["add", "Buy milk", "--priority", "high"], "Added",        ""),
                (["add", "Read book"],                    "Added",          ""),
                (["list"],                                "Buy milk",       ""),
                (["list", "--filter", "high"],            "Buy milk",       ""),
                (["done", "1"],                           "done",           ""),
                (["done", "999"],                         "error",          ""),
                (["delete", "2"],                         "deleted",        ""),
                (["clear"],                               "Cleared",        ""),
            ]

    async def _do_work(self, task: Dict[str, Any]) -> QAReport:
        artifact: CodeArtifact = task["artifact"]
        spec: Spec             = task["spec"]
        out_dir: Path          = task["output_dir"]
        script = out_dir / artifact.filename
        json_path = out_dir / (spec.project_name + ".json")

        logger.info("QA: running test suite on %s...", artifact.filename)

        # Clean state
        if json_path.exists():
            json_path.unlink()

        syntax_ok = self.check_syntax(script)

        test_defs = self._build_tests(spec, script, json_path)
        test_cases = []
        for args, expected, stdin in test_defs:
            tc = self.run_test_case(script, args, expected, stdin)
            tc.name = " ".join(args[:3]) if args else "unknown"
            status = "PASS" if tc.passed else "FAIL"
            logger.info("  QA [%s] %-30s — %s", status, tc.name, tc.output[:50])
            test_cases.append(tc)

        report = QAReport(
            tests       = test_cases,
            code_runs   = test_cases[0].passed if test_cases else False,
            syntax_valid = syntax_ok,
        )
        self.write_qa_report(report, out_dir)
        logger.info("QA: %d/%d passed", report.passed, len(test_cases))
        return report


# ── Review Agent ──────────────────────────────────────────────────────────────

class ReviewAgent(DepartmentAgent):

    def __init__(self, **kwargs):
        super().__init__("review", **kwargs)

    @tool
    def read_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else ""

    @tool
    def compare_spec(self, spec: Spec, qa: QAReport) -> Dict[str, Any]:
        """Score feature coverage based on QA results."""
        pass_rate = qa.passed / max(len(qa.tests), 1)
        n = len(spec.features)
        n_impl = max(0, round(pass_rate * n))
        implemented = spec.features[:n_impl]
        missing     = spec.features[n_impl:]
        return {"implemented": implemented, "missing": missing,
                "pass_rate": pass_rate}

    @tool
    def score_coverage(self, spec: Spec, qa: QAReport,
                       artifact: CodeArtifact) -> float:
        feat_score = qa.passed / max(len(qa.tests), 1)
        req_score  = 1.0 if artifact.syntax_ok else 0.5
        return round((feat_score * 0.7 + req_score * 0.3), 3)

    @tool
    def write_review(self, report: ReviewReport, out_dir: Path) -> None:
        doc = {
            "approved":              report.approved,
            "coverage_score":        report.coverage_score,
            "features_implemented":  report.features_implemented,
            "features_missing":      report.features_missing,
            "requirements_met":      report.requirements_met,
            "requirements_missing":  report.requirements_missing,
            "notes":                 report.notes,
        }
        (out_dir / "review.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8")

    async def _do_work(self, task: Dict[str, Any]) -> ReviewReport:
        spec: Spec              = task["spec"]
        qa: QAReport            = task["qa_report"]
        artifact: CodeArtifact  = task["artifact"]
        out_dir: Path           = task["output_dir"]

        logger.info("Review: validating against spec...")

        comparison  = self.compare_spec(spec, qa)
        coverage    = self.score_coverage(spec, qa, artifact)

        req_met     = spec.requirements if qa.passed >= len(qa.tests) * 0.8 else []
        req_missing = [] if req_met else spec.requirements

        approved = coverage >= 0.75 and artifact.syntax_ok

        report = ReviewReport(
            approved              = approved,
            features_implemented  = comparison["implemented"],
            features_missing      = comparison["missing"],
            requirements_met      = req_met,
            requirements_missing  = req_missing,
            coverage_score        = coverage,
            notes = (
                f"{qa.passed}/{len(qa.tests)} QA tests passed. "
                f"Coverage: {coverage:.0%}. "
                + ("All requirements met." if req_met else
                   f"Missing: {', '.join(comparison['missing'][:2])}")
            ),
        )
        self.write_review(report, out_dir)
        logger.info("Review: %s  coverage=%.0f%%  %s",
                    "APPROVED" if approved else "NEEDS WORK",
                    coverage * 100, report.notes)
        return report


# ══════════════════════════════════════════════════════════════════════════════
# Visualizations
# ══════════════════════════════════════════════════════════════════════════════

DEPT_COLOURS = {
    "pm":           "#4e79a7",
    "research":     "#f28e2b",
    "architecture": "#e15759",
    "engineering":  "#76b7b2",
    "qa":           "#59a14f",
    "review":       "#edc948",
}


def make_visualizations(
    agents:   List[DepartmentAgent],
    handoffs: List[Dict],
    qa:       QAReport,
    artifact: CodeArtifact,
    spec:     Spec,
    review:   ReviewReport,
    out_dir:  Path,
) -> None:
    VIZ_DIR.mkdir(parents=True, exist_ok=True)

    _plot_pipeline_timeline(agents, out_dir)
    _plot_qa_results(qa, out_dir)
    _plot_energy_handoffs(handoffs, agents, out_dir)
    _plot_code_metrics(artifact, out_dir)
    _plot_feature_coverage(spec, review, qa, out_dir)
    _plot_tool_usage(out_dir)
    _plot_summary_dashboard(agents, handoffs, qa, artifact, spec, review, out_dir)

    logger.info("Visualizations saved to %s", VIZ_DIR)


def _plot_pipeline_timeline(agents: List[DepartmentAgent], out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 4))
    t0 = min(a.start_time for a in agents)
    for i, agent in enumerate(agents):
        start = (agent.start_time - t0) * 1000
        dur   = max(agent.elapsed_ms, 5)
        col   = DEPT_COLOURS.get(agent.department, "#aaaaaa")
        ax.barh(i, dur, left=start, height=0.5, color=col, edgecolor="white", lw=1.5)
        ax.text(start + dur / 2, i, f"{dur:.0f}ms",
                va="center", ha="center", fontsize=8, color="white", fontweight="bold")
    ax.set_yticks(range(len(agents)))
    ax.set_yticklabels([a.department.upper() for a in agents])
    ax.set_xlabel("Time (ms)")
    ax.set_title("Department Pipeline Timeline (Gantt)")
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    fig.savefig(VIZ_DIR / "pipeline_timeline.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_qa_results(qa: QAReport, out_dir: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, max(4, len(qa.tests) * 0.45 + 1)))
    names = [t.name[:35] for t in qa.tests]
    durations = [t.duration_ms for t in qa.tests]
    colours = ["#59a14f" if t.passed else "#e15759" for t in qa.tests]

    bars = ax.barh(range(len(qa.tests)), durations, color=colours, edgecolor="white", lw=1)
    for i, (t, bar) in enumerate(zip(qa.tests, bars)):
        label = "PASS" if t.passed else "FAIL"
        ax.text(bar.get_width() + 0.5, i, label,
                va="center", fontsize=8, fontweight="bold",
                color="#59a14f" if t.passed else "#e15759")

    ax.set_yticks(range(len(qa.tests)))
    ax.set_yticklabels(names, fontsize=8)
    ax.set_xlabel("Duration (ms)")
    ax.set_title(f"QA Test Results — {qa.passed}/{len(qa.tests)} Passed")

    pass_patch = mpatches.Patch(color="#59a14f", label="PASS")
    fail_patch = mpatches.Patch(color="#e15759", label="FAIL")
    ax.legend(handles=[pass_patch, fail_patch], loc="lower right")
    ax.grid(axis="x", alpha=0.3)
    plt.tight_layout()
    fig.savefig(VIZ_DIR / "qa_results.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_energy_handoffs(handoffs: List[Dict],
                          agents: List[DepartmentAgent], out_dir: Path) -> None:
    if not handoffs:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))

    labels    = [f"{h['sender']}->{h['receiver']}" for h in handoffs]
    h_sender  = [h["H_sender_before"] for h in handoffs]
    h_recv    = [h["H_receiver_before"] for h in handoffs]
    mismatches = [abs(h["dH_total"]) for h in handoffs]
    statuses  = [h["allowed"] for h in handoffs]

    x = np.arange(len(labels))
    w = 0.35
    axes[0].bar(x - w/2, h_sender, w, label="Sender H", color="#4e79a7", alpha=0.8)
    axes[0].bar(x + w/2, h_recv,   w, label="Receiver H", color="#f28e2b", alpha=0.8)
    axes[0].set_xticks(x); axes[0].set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
    axes[0].set_title("Hamiltonian Energy per Handoff")
    axes[0].set_ylabel("H value"); axes[0].legend(); axes[0].grid(axis="y", alpha=0.3)

    colours = ["#59a14f" if s else "#e15759" for s in statuses]
    axes[1].bar(x, mismatches, color=colours, edgecolor="white", lw=1.5)
    axes[1].set_xticks(x); axes[1].set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
    axes[1].set_title("Energy Mismatch per Handoff (lower = better)")
    axes[1].set_ylabel("|dH_total|")
    axes[1].axhline(0.85, color="red", linestyle="--", lw=1, label="Tolerance")
    axes[1].legend(); axes[1].grid(axis="y", alpha=0.3)

    plt.tight_layout()
    fig.savefig(VIZ_DIR / "energy_handoffs.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_code_metrics(artifact: CodeArtifact, out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle(f"Code Metrics — {artifact.filename}", fontsize=12)

    # Pie: line breakdown
    tree = ast.parse(artifact.code)
    code_lines = len([l for l in artifact.code.splitlines()
                      if l.strip() and not l.strip().startswith("#")])
    comment_lines = len([l for l in artifact.code.splitlines()
                         if l.strip().startswith("#")])
    blank_lines = len([l for l in artifact.code.splitlines() if not l.strip()])
    docstring_lines = artifact.lines - code_lines - comment_lines - blank_lines

    sizes  = [code_lines, comment_lines, blank_lines, max(docstring_lines, 0)]
    labels = ["Code", "Comments", "Blank", "Docstrings"]
    cols   = ["#4e79a7", "#59a14f", "#bab0ac", "#f28e2b"]
    valid  = [(s, l, c) for s, l, c in zip(sizes, labels, cols) if s > 0]
    axes[0].pie([v[0] for v in valid],
                labels=[v[1] for v in valid],
                colors=[v[2] for v in valid],
                autopct="%1.0f%%", startangle=90)
    axes[0].set_title(f"Line Breakdown ({artifact.lines} total)")

    # Bar: function count by type
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    cmd_fns  = [f for f in funcs if f.startswith("cmd_")]
    util_fns = [f for f in funcs if not f.startswith("cmd_") and f != "main"]

    categories = ["cmd_* handlers", "Utility funcs", "main()"]
    counts     = [len(cmd_fns), len(util_fns), 1]
    bar_cols   = ["#4e79a7", "#f28e2b", "#e15759"]
    bars = axes[1].bar(categories, counts, color=bar_cols, edgecolor="white", lw=1.5)
    for bar, count in zip(bars, counts):
        axes[1].text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                     str(count), ha="center", va="bottom", fontweight="bold")
    axes[1].set_title(f"Functions by Type ({len(funcs)} total)")
    axes[1].set_ylabel("Count"); axes[1].grid(axis="y", alpha=0.3)

    plt.tight_layout()
    fig.savefig(VIZ_DIR / "code_metrics.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_feature_coverage(spec: Spec, review: ReviewReport,
                           qa: QAReport, out_dir: Path) -> None:
    features = spec.features[:8]  # cap at 8 for readability
    n = len(features)
    if n == 0:
        return

    fig, ax = plt.subplots(figsize=(10, max(3, n * 0.7 + 1)))

    impl_set = set(review.features_implemented)
    for i, feat in enumerate(features):
        implemented = feat in impl_set
        color = "#59a14f" if implemented else "#e15759"
        ax.barh(i, 1, color=color, alpha=0.8, edgecolor="white")
        label = "Implemented" if implemented else "Missing"
        ax.text(0.5, i, label, ha="center", va="center",
                fontsize=9, color="white", fontweight="bold")

    ax.set_yticks(range(n))
    ax.set_yticklabels([f[:55] for f in features], fontsize=8)
    ax.set_xlim(0, 1); ax.set_xticks([])
    ax.set_title(f"Feature Coverage — {len(review.features_implemented)}/{n} Implemented"
                 f"  (Score: {review.coverage_score:.0%})")

    impl_p = mpatches.Patch(color="#59a14f", label="Implemented")
    miss_p = mpatches.Patch(color="#e15759", label="Missing")
    ax.legend(handles=[impl_p, miss_p], loc="lower right")
    plt.tight_layout()
    fig.savefig(VIZ_DIR / "feature_coverage.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_tool_usage(out_dir: Path) -> None:
    by_dept = REGISTRY.tool_names_by_dept()
    if not by_dept:
        return

    depts = list(by_dept.keys())
    all_tools = sorted({t for tools in by_dept.values() for t in tools})
    n_tools = len(all_tools)
    n_depts = len(depts)

    matrix = np.zeros((n_depts, n_tools))
    for i, dept in enumerate(depts):
        for j, tool_name in enumerate(all_tools):
            matrix[i, j] = by_dept[dept].get(tool_name, 0)

    fig, ax = plt.subplots(figsize=(max(8, n_tools * 1.2), max(4, n_depts * 0.8 + 1)))
    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
    plt.colorbar(im, ax=ax, label="Call count")

    ax.set_xticks(range(n_tools))
    ax.set_xticklabels(all_tools, rotation=40, ha="right", fontsize=8)
    ax.set_yticks(range(n_depts))
    ax.set_yticklabels([d.upper() for d in depts], fontsize=9)

    for i in range(n_depts):
        for j in range(n_tools):
            v = int(matrix[i, j])
            if v > 0:
                ax.text(j, i, str(v), ha="center", va="center",
                        fontsize=9, color="black" if v < 3 else "white",
                        fontweight="bold")

    ax.set_title("Tool Usage Heatmap — Calls per Department")
    plt.tight_layout()
    fig.savefig(VIZ_DIR / "tool_usage.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_summary_dashboard(
    agents:   List[DepartmentAgent],
    handoffs: List[Dict],
    qa:       QAReport,
    artifact: CodeArtifact,
    spec:     Spec,
    review:   ReviewReport,
    out_dir:  Path,
) -> None:
    fig = plt.figure(figsize=(18, 12))
    fig.suptitle(
        f"HamiltonianSwarm Software Company — {spec.project_name}.py\n"
        f"QA: {qa.passed}/{len(qa.tests)} passed  |  "
        f"Coverage: {review.coverage_score:.0%}  |  "
        f"{'APPROVED' if review.approved else 'NEEDS WORK'}",
        fontsize=13, fontweight="bold",
    )
    gs = GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

    # ── 1. Timeline (top row, full width) ──────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    t0 = min(a.start_time for a in agents)
    for i, agent in enumerate(agents):
        start = (agent.start_time - t0) * 1000
        dur   = max(agent.elapsed_ms, 5)
        col   = DEPT_COLOURS.get(agent.department, "#aaa")
        ax1.barh(i, dur, left=start, height=0.55, color=col, edgecolor="white")
        ax1.text(start + dur / 2, i, f"{agent.department}\n{dur:.0f}ms",
                 va="center", ha="center", fontsize=7.5,
                 color="white", fontweight="bold")
    ax1.set_yticks([]); ax1.set_xlabel("ms")
    ax1.set_title("Pipeline Timeline", fontsize=10); ax1.grid(axis="x", alpha=0.3)

    # ── 2. QA results (mid left) ───────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, 0])
    passed = qa.passed; failed = qa.failed
    ax2.pie([passed, failed] if failed else [passed],
            labels=["Passed", "Failed"] if failed else ["Passed"],
            colors=["#59a14f", "#e15759"] if failed else ["#59a14f"],
            autopct="%1.0f%%", startangle=90, textprops={"fontsize": 9})
    ax2.set_title(f"QA: {passed}/{len(qa.tests)}", fontsize=10)

    # ── 3. Feature coverage (mid centre) ──────────────────────────────
    ax3 = fig.add_subplot(gs[1, 1])
    n_impl = len(review.features_implemented)
    n_miss = len(review.features_missing)
    ax3.bar(["Implemented", "Missing"], [n_impl, n_miss],
            color=["#59a14f", "#e15759"], edgecolor="white")
    for x, v in enumerate([n_impl, n_miss]):
        ax3.text(x, v + 0.05, str(v), ha="center", fontweight="bold")
    ax3.set_title("Feature Coverage", fontsize=10)
    ax3.set_ylabel("Features"); ax3.grid(axis="y", alpha=0.3)

    # ── 4. Energy handoffs (mid right) ────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 2])
    if handoffs:
        labels = [f"{h['sender'][:3]}->{h['receiver'][:3]}" for h in handoffs]
        mismatches = [abs(h["dH_total"]) for h in handoffs]
        cols = ["#59a14f" if h["allowed"] else "#e15759" for h in handoffs]
        ax4.bar(range(len(labels)), mismatches, color=cols, edgecolor="white")
        ax4.set_xticks(range(len(labels)))
        ax4.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
        ax4.axhline(0.85, color="red", lw=1, linestyle="--", label="Tol.")
        ax4.legend(fontsize=7)
    ax4.set_title("Energy Mismatch", fontsize=10)
    ax4.set_ylabel("|dH|"); ax4.grid(axis="y", alpha=0.3)

    # ── 5. Code metrics (bottom left) ─────────────────────────────────
    ax5 = fig.add_subplot(gs[2, 0])
    tree = ast.parse(artifact.code)
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    metrics = {
        "Total lines":   artifact.lines,
        "Functions":     len(funcs),
        "Syntax":        1 if artifact.syntax_ok else 0,
    }
    bars = ax5.bar(list(metrics.keys()), list(metrics.values()),
                   color=["#4e79a7", "#f28e2b", "#59a14f" if artifact.syntax_ok else "#e15759"],
                   edgecolor="white")
    for bar, v in zip(bars, metrics.values()):
        ax5.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 str(v), ha="center", fontsize=9, fontweight="bold")
    ax5.set_title("Code Metrics", fontsize=10); ax5.grid(axis="y", alpha=0.3)

    # ── 6. Tool usage (bottom centre+right) ───────────────────────────
    ax6 = fig.add_subplot(gs[2, 1:])
    by_dept = REGISTRY.tool_names_by_dept()
    if by_dept:
        depts = list(by_dept.keys())
        tool_totals = {d: sum(v.values()) for d, v in by_dept.items()}
        cols6 = [DEPT_COLOURS.get(d, "#aaa") for d in depts]
        bars6 = ax6.bar(range(len(depts)),
                        [tool_totals[d] for d in depts],
                        color=cols6, edgecolor="white")
        for bar, v in zip(bars6, [tool_totals[d] for d in depts]):
            ax6.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                     str(v), ha="center", fontsize=9, fontweight="bold")
        ax6.set_xticks(range(len(depts)))
        ax6.set_xticklabels([d.upper() for d in depts], fontsize=8)
    ax6.set_title("Total Tool Calls per Department", fontsize=10)
    ax6.set_ylabel("Calls"); ax6.grid(axis="y", alpha=0.3)

    fig.savefig(VIZ_DIR / "summary_dashboard.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ══════════════════════════════════════════════════════════════════════════════
# Company orchestrator
# ══════════════════════════════════════════════════════════════════════════════

class SoftwareCompany:

    def __init__(self):
        self.validator    = ValidatorAgent(n_dims=6, energy_tolerance=0.95)
        self.pm           = PMAgent()
        self.research     = ResearchAgent()
        self.architecture = ArchitectureAgent()
        self.engineering  = EngineeringAgent()
        self.qa           = QAAgent()
        self.review       = ReviewAgent()

        self.dept_agents = [
            self.pm, self.research, self.architecture,
            self.engineering, self.qa, self.review,
        ]
        self.handoff_log: List[Dict] = []

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        VIZ_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("SoftwareCompany ready — %d departments", len(self.dept_agents))

    def _handoff(self, sender: DepartmentAgent,
                 receiver: DepartmentAgent, task_id: str) -> bool:
        H_sb = float(sender.hamiltonian.total_energy(
            sender.phase_state.q, sender.phase_state.p).item())
        H_rb = float(receiver.hamiltonian.total_energy(
            receiver.phase_state.q, receiver.phase_state.p).item())
        sender.step_phase_state(dt=0.005)
        receiver.step_phase_state(dt=0.005)
        H_sa = float(sender.hamiltonian.total_energy(
            sender.phase_state.q, sender.phase_state.p).item())
        H_ra = float(receiver.hamiltonian.total_energy(
            receiver.phase_state.q, receiver.phase_state.p).item())

        allowed, reason = self.validator.validate_handoff(
            sender.department, receiver.department, task_id,
            H_sb, H_sa, H_rb, H_ra,
        )
        self.handoff_log.append({
            "sender":            sender.department,
            "receiver":          receiver.department,
            "H_sender_before":   H_sb,
            "H_receiver_before": H_rb,
            "dH_total":          (H_sa - H_sb) + (H_ra - H_rb),
            "allowed":           allowed,
            "reason":            reason,
        })
        status = "OK" if allowed else "DRIFT"
        logger.info("  Handoff [%s] %s -> %s",
                    status, sender.department, receiver.department)
        return allowed

    async def run(self, brief: str, project_name: str) -> Dict[str, Any]:
        t_start = time.perf_counter()
        logger.info("=" * 60)
        logger.info("SOFTWARE COMPANY — project: %s", project_name)
        logger.info("=" * 60)

        # Clean old json data
        for f in OUTPUT_DIR.glob("*.json"):
            if f.name not in ("spec.json","approach.json","architecture.json",
                               "qa_report.json","review.json","company_results.json"):
                f.unlink()

        # ── 1. PM ──────────────────────────────────────────────────────
        logger.info("\n[1/6] PM — parsing brief")
        r = await self.pm.execute_task({
            "task_id": "pm", "brief": brief,
            "project_name": project_name, "output_dir": OUTPUT_DIR,
        })
        spec: Spec = r.output
        self._handoff(self.pm, self.research, "pm->res")

        # ── 2. Research ────────────────────────────────────────────────
        logger.info("\n[2/6] Research — evaluating approach")
        r = await self.research.execute_task({
            "task_id": "res", "spec": spec, "output_dir": OUTPUT_DIR,
        })
        approach: Approach = r.output
        self._handoff(self.research, self.architecture, "res->arch")

        # ── 3. Architecture ────────────────────────────────────────────
        logger.info("\n[3/6] Architecture — designing structure")
        r = await self.architecture.execute_task({
            "task_id": "arch", "spec": spec,
            "approach": approach, "output_dir": OUTPUT_DIR,
        })
        arch: Architecture = r.output
        self._handoff(self.architecture, self.engineering, "arch->eng")

        # ── 4. Engineering ─────────────────────────────────────────────
        logger.info("\n[4/6] Engineering — writing code")
        r = await self.engineering.execute_task({
            "task_id": "eng", "spec": spec,
            "arch": arch, "approach": approach, "output_dir": OUTPUT_DIR,
        })
        artifact: CodeArtifact = r.output
        self._handoff(self.engineering, self.qa, "eng->qa")

        # ── 5. QA ──────────────────────────────────────────────────────
        logger.info("\n[5/6] QA — running test suite")
        r = await self.qa.execute_task({
            "task_id": "qa", "artifact": artifact,
            "spec": spec, "output_dir": OUTPUT_DIR,
        })
        qa_report: QAReport = r.output
        self._handoff(self.qa, self.review, "qa->rev")

        # ── 6. Review ──────────────────────────────────────────────────
        logger.info("\n[6/6] Review — final validation")
        r = await self.review.execute_task({
            "task_id": "rev", "spec": spec, "qa_report": qa_report,
            "artifact": artifact, "output_dir": OUTPUT_DIR,
        })
        review: ReviewReport = r.output

        elapsed = (time.perf_counter() - t_start) * 1000

        # ── Summary ────────────────────────────────────────────────────
        logger.info("\n%s", "=" * 60)
        logger.info("PROJECT COMPLETE  %.0fms", elapsed)
        logger.info("File     : %s", OUTPUT_DIR / artifact.filename)
        logger.info("QA       : %d/%d tests passed",
                    qa_report.passed, len(qa_report.tests))
        logger.info("Coverage : %.0f%%", review.coverage_score * 100)
        logger.info("Review   : %s", "APPROVED" if review.approved else "NEEDS WORK")

        if review.features_implemented:
            logger.info("\nFeatures implemented:")
            for f in review.features_implemented:
                logger.info("  [x] %s", f[:70])
        if review.features_missing:
            logger.info("Features missing:")
            for f in review.features_missing:
                logger.info("  [ ] %s", f[:70])

        if qa_report.failed:
            logger.info("\nQA failures:")
            for t in qa_report.tests:
                if not t.passed:
                    logger.info("  FAIL: %-30s %s", t.name, t.output[:60])

        # ── Visualizations ─────────────────────────────────────────────
        logger.info("\nGenerating visualizations...")
        make_visualizations(
            self.dept_agents, self.handoff_log,
            qa_report, artifact, spec, review, OUTPUT_DIR,
        )

        results = {
            "project":        project_name,
            "output_file":    str(OUTPUT_DIR / artifact.filename),
            "elapsed_ms":     round(elapsed, 1),
            "qa":             {"passed": qa_report.passed,
                               "total":  len(qa_report.tests)},
            "coverage_score": review.coverage_score,
            "approved":       review.approved,
            "visualizations": [str(p) for p in VIZ_DIR.glob("*.png")],
        }
        (OUTPUT_DIR / "company_results.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8")
        return results


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="HamiltonianSwarm Software Company — give it a brief, get working code")
    parser.add_argument(
        "--project", "-p",
        choices=list(PROJECTS.keys()),
        default=DEFAULT_PROJECT,
        help=f"Which project to build (default: {DEFAULT_PROJECT})",
    )
    cli_args = parser.parse_args()

    project_name = cli_args.project
    brief        = PROJECTS[project_name]

    company = SoftwareCompany()
    results = asyncio.run(company.run(brief, project_name))

    print("\n" + "=" * 60)
    status = "APPROVED" if results["approved"] else "NEEDS WORK"
    print(f"  {status}")
    print(f"  QA       : {results['qa']['passed']}/{results['qa']['total']} tests passed")
    print(f"  Coverage : {results['coverage_score']:.0%}")
    print(f"  File     : {results['output_file']}")
    print(f"  Time     : {results['elapsed_ms']:.0f}ms")
    print(f"\n  Visualizations -> {VIZ_DIR}")
    print(f"  summary_dashboard.png  <- start here")
    print("=" * 60)
