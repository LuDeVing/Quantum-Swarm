"""Engineering sprint: executive prep, task queue, manager fix loop, `run_engineering_team`."""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

from .config import *  # noqa: F403
from .contracts import InterfaceContractRegistry, get_contracts
from .dashboard import get_dashboard
from .git_worktrees import GitWorktreeManager
from .rag import _is_ignored_project_path, get_rag, get_worktree_rag
from .rolling_context import RollingContext
from .stance import extract_stance_probs, interfere_weighted, perplexity_to_similarities
from .team_schemas import EngTask, ExecutionPlan, MergeResult, TeamResult, WorkerOutput
from .roles import ENG_WORKERS, ROLES, _get_dod
from .state import (
    _current_sprint_goal,
    _get_sprint_num,
    _set_agent_ctx,
    _set_task_file,
    _set_worktree_manager,
)
from .tools_impl import (
    clear_sprint_files,
    get_sprint_files,
    _normalize_shell_command_for_windows,
    _read_team_files,
    _run_shell_blocks_gui_entrypoint,
    _strip_llm_summary_lines,
    _subprocess_env_for_project,
)
from .prompts_loaded import _SYSTEM_CEO, _manager_system, _worker_system
from .planning import run_team_planning
from .computer_use import (
    CUTripletTracker,
    build_computer_use_loop_section,
    get_screen_dims_hint,
)

logger = logging.getLogger("company")


def _llm(*args, **kwargs):
    import software_company as sc

    return sc.llm_call(*args, **kwargs)


def _run_with_tools_pkg(*args, **kwargs):
    import software_company as sc

    return sc._run_with_tools(*args, **kwargs)


# ── Executive meeting: CEO + all managers plan together ───────────────────────

MANAGER_ROLES = {
    "Architecture": "arch_manager",
    "Design":       "design_manager",
    "Engineering":  "eng_manager",
    "QA":           "qa_manager",
}

TEAM_TASKS_PROMPT = {
    "Architecture": "design the system architecture, API contracts, and data model",
    "Design":       "define UX flows, UI components, and visual style guide",
    "Engineering":  "implement the full software — backend, frontend, and infrastructure",
    "QA":           "test correctness, integration, performance, and security",
}


def run_executive_meeting(
    brief: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> ExecutionPlan:
    """
    CEO + all 4 managers meet together.
    Round 1: each manager independently assesses their team's readiness and dependencies.
    Round 2: each manager sees all other managers' positions, may negotiate.
    CEO final: synthesises into an execution plan with phases and wait decisions.

    Returns (ExecutionPlan, {team: task_description}).
    """
    logger.info(f"\n{'═'*55}\nEXECUTIVE MEETING: CEO + all managers\n{'═'*55}")

    team_names = list(MANAGER_ROLES.keys())

    # ── Round 1: CEO opens, managers respond independently ────────────────
    ceo_opening = _llm(
        f"You are the CEO of a software company.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Open the executive meeting. Briefly state:\n"
        f"1. The project goal and key constraints\n"
        f"2. The four team workstreams (Architecture, Design, Engineering, QA)\n"
        f"3. Ask each manager to assess: can they start immediately, or do they "
        f"need to wait for another team? What are their dependencies?\n\n"
        f"Keep it concise — 150 words max.",
        label="ceo_opening",
        system=_SYSTEM_CEO,
    )
    logger.info(f"\nCEO opens meeting: {ceo_opening[:120]}...")

    def manager_r1(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        output = _llm(
            f"You are the {ROLES[role_key]['title']}.\n\n"
            f"CEO's opening:\n{ceo_opening}\n\n"
            f"Your team's responsibility: {TEAM_TASKS_PROMPT[team_name]}\n\n"
            f"Respond to the CEO. State:\n"
            f"1. Can your team START IMMEDIATELY or do you need to WAIT for another team?\n"
            f"2. If waiting: which team and what specific output do you need?\n"
            f"3. Can you do any partial work while waiting? What?\n"
            f"4. What does your team need from others to do their best work?\n\n"
            f"Be direct and specific. 100 words max.",
            label=f"{role_key}_r1",
            system=_manager_system(role_key),
        )
        return team_name, output

    r1: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for team_name, output in ex.map(lambda t: manager_r1(t), team_names):
            r1[team_name] = output

    # Health interference across managers
    ActiveInferenceState.interfere_all(
        [health_states[MANAGER_ROLES[t]] for t in team_names], alpha=INTERFERENCE_ALPHA
    )

    # ── Round 2: managers see all positions, negotiate ────────────────────
    all_r1 = "\n\n".join(
        f"{ROLES[MANAGER_ROLES[t]]['title']}:\n{r1[t]}" for t in team_names
    )

    def manager_r2(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        output = _llm(
            f"You are the {ROLES[role_key]['title']}.\n\n"
            f"All managers have responded:\n{all_r1}\n\n"
            f"Your team: {TEAM_TASKS_PROMPT[team_name]}\n\n"
            f"After hearing everyone:\n"
            f"1. Confirm or update your start decision (START NOW / WAIT FOR X)\n"
            f"2. If you can start partial work in parallel, what specifically?\n"
            f"3. Any concerns or blockers to flag to the CEO?\n\n"
            f"50 words max.",
            label=f"{role_key}_r2",
            system=_manager_system(role_key),
        )
        return team_name, output

    r2: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for team_name, output in ex.map(lambda t: manager_r2(t), team_names):
            r2[team_name] = output

    # ── CEO synthesises execution plan ────────────────────────────────────
    all_r2 = "\n\n".join(
        f"{ROLES[MANAGER_ROLES[t]]['title']} (final):\n{r2[t]}" for t in team_names
    )
    plan_output = _llm(
        f"You are the CEO.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Meeting summary:\n{all_r1}\n\nFinal positions:\n{all_r2}\n\n"
        f"Produce the execution plan. Your job is ONLY to decide the order and dependencies — "
        f"each team will figure out internally what to build and who does what.\n\n"
        f"Format EXACTLY as:\n\n"
        f"PHASE_1: <comma-separated team names that start immediately>\n"
        f"PHASE_2: <teams that start after Phase 1 completes>\n"
        f"PHASE_3: <teams that start after Phase 2 completes>\n"
        f"PHASE_4: <teams that start after Phase 3 completes>\n\n"
        f"(Only include phases that are needed. Skip empty phases.)\n\n"
        f"NOTES: <why this ordering — what each waiting team needs from the phase before it>",
        label="ceo_plan",
        system=_SYSTEM_CEO,
    )

    # Parse phases
    phases: List[List[str]] = []
    for i in range(1, 5):
        m = re.search(rf"PHASE_{i}:\s*(.+)", plan_output, re.IGNORECASE)
        if m:
            teams_in_phase = [t.strip() for t in m.group(1).split(",")]
            # Normalise to canonical names matching TEAM_RUNNERS keys
            canonical = {"Architecture", "Design", "Engineering", "QA"}
            normalised = [
                next((c for c in canonical if c.lower() in t.lower()), t.strip().capitalize())
                for t in teams_in_phase
            ]
            phases.append(normalised)

    if not phases:  # fallback
        phases = [["Architecture"], ["Design"], ["Engineering"], ["QA"]]

    notes_m = re.search(r"NOTES:\s*(.+)", plan_output, re.DOTALL | re.IGNORECASE)
    notes_text = notes_m.group(1).strip() if notes_m else ""

    # Log the plan
    logger.info(f"\nEXECUTION PLAN:")
    for i, phase in enumerate(phases, 1):
        logger.info(f"  Phase {i}: {' + '.join(phase)}")
    logger.info(f"  Notes: {notes_text[:120]}")

    full_transcript = (
        f"CEO opening:\n{ceo_opening}\n\n"
        f"Manager round 1:\n{all_r1}\n\n"
        f"Manager round 2:\n{all_r2}\n\n"
        f"CEO plan:\n{plan_output}"
    )

    # Update rolling contexts
    for team_name, role_key in MANAGER_ROLES.items():
        rolling_ctxs[role_key].add("executive meeting", r2[team_name])

    # Save conversation log
    turns = [{"speaker": "CEO", "text": ceo_opening}]
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R1)", "text": r1[t]})
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R2)", "text": r2[t]})
    turns.append({"speaker": "CEO — Execution Plan", "text": plan_output})
    # Local import avoids circular import: orchestration imports this module at load time.
    from .orchestration import _save_conversation as _save_exec_meeting_conv

    _save_exec_meeting_conv("Executive Meeting", turns)

    return ExecutionPlan(
        raw=full_transcript,
        phases=phases,
        team_notes={"all": notes_text},
    )


# ── Sprint planning: engineering manager + devs discuss together ──────────────

def _generate_contracts(
    task: str,
    dev_assignments: Dict[str, str],
    pool: Dict[str, str] = None,
) -> None:
    """
    After sprint planning assigns work items, ask the manager to generate
    typed interface contracts that all agents must follow.
    """
    logger.info(f"\n{'─'*55}\nCONTRACT GENERATION: Engineering\n{'─'*55}")

    assignment_list = "\n".join(
        f"  {dev}: owns {desc}" for dev, desc in dev_assignments.items()
    )
    if pool:
        pool_list = "\n".join(f"  [Pool] {iid}: {desc}" for iid, desc in pool.items())
        assignment_list += f"\n\nUNASSIGNED BACKLOG POOL:\n{pool_list}"
    
    # Inject Architect's intended structure if available
    struct_ctx = ""
    struct_path = OUTPUT_DIR / "design" / "project_structure.md"
    if struct_path.exists():
        struct_ctx = f"\n\nARCHITECT'S PROJECT STRUCTURE (MANDATORY FILE PATHS):\n{struct_path.read_text(encoding='utf-8')[:3000]}"

    if AGILE_MODE:
        contract_prompt = (
            f"You are the Engineering Manager.\n\n"
            f"PROJECT:\n{task[:600]}\n\n"
            f"DEV ASSIGNMENTS:\n{assignment_list}\n"
            f"{struct_ctx}\n\n"
            f"Currently we are in AGILE MODE. Do NOT generate rigid typed signatures or exact data models. "
            f"Instead, generate a Collaborative Task List that maps files to owners and gives high-level feature descriptions. "
            f"The developers will use broadcasting and messaging to agree on the exact interfaces as they build them.\n\n"
            f"Output EXACTLY this JSON structure (no markdown fences, just raw JSON):\n"
            f'{{\n'
            f'  "primary_language": "python",\n'
            f'  "build_command": "python server.py",\n'
            f'  "build_file": "requirements.txt",\n'
            f'  "dependencies": ["sqlite3"],\n'
            f'  "init_order": [],\n'
            f'  "models": [],\n'
            f'  "endpoints": [],\n'
            f'  "files": [\n'
            f'    {{"file": "models.py", "owner": "dev_1", "imports_from": [], '
            f'"exports": [], "depends_on": [], "description": "Collaborative data models — define as needed and broadcast changes"}},\n'
            f'    {{"file": "routes.py", "owner": "dev_2", "imports_from": ["models.py"], '
            f'"exports": [], "depends_on": ["models.py"], "description": "API routes — negotiate signatures with frontend"}}\n'
            f'  ],\n'
            f'  "entry_point": "server.py",\n'
            f'  "entry_imports": []\n'
            f'}}\n\n'
            f"RULES:\n"
            f"- Set 'primary_language' to the project's main stack: python, rust, go, javascript, typescript, "
            f"java, csharp, cpp, kotlin, ruby, php, mixed, etc. The orchestrator uses this for env and verification.\n"
            f"- Every dev must own at least one file\n"
            f"- Use 'files' to define ownership and 'description' to give the collaborative goal\n"
            f"- The entry point file is SYSTEM-MANAGED — set its owner to 'system'\n"
            f"- 'depends_on' should only be used for high-level file ordering\n"
        )
    else:
        contract_prompt = (
            f"You are the Engineering Manager.\n\n"
            f"PROJECT:\n{task[:600]}\n\n"
            f"DEV ASSIGNMENTS:\n{assignment_list}\n"
            f"{struct_ctx}\n\n"
            f"Generate typed interface contracts so all developers use identical "
            f"signatures, import paths, and data models. This prevents integration failures.\n\n"
            f"Output EXACTLY this JSON structure (no markdown fences, just raw JSON):\n"
            f'{{\n'
            f'  "primary_language": "python",\n'
            f'  "build_command": "python server.py",\n'
            f'  "build_file": "requirements.txt",\n'
            f'  "dependencies": ["sqlite3"],\n'
            f'  "init_order": ["database", "routes", "server"],\n'
            f'  "models": [\n'
            f'    {{"name": "ModelName", "fields": "field1: type, field2: type", "file": "models.py"}}\n'
            f'  ],\n'
            f'  "endpoints": [\n'
            f'    {{"method": "POST", "path": "/items", "request_model": "ItemCreate", "response_model": "Item"}}\n'
            f'  ],\n'
            f'  "files": [\n'
            f'    {{"file": "models.py", "owner": "dev_1", "imports_from": [], '
            f'"exports": ["Item"], "depends_on": [], "description": "data models"}},\n'
            f'    {{"file": "routes.py", "owner": "dev_2", "imports_from": ["models.py"], '
            f'"exports": ["create_item"], "depends_on": ["models.py"], "description": "API routes"}}\n'
            f'  ],\n'
            f'  "entry_point": "server.py",\n'
            f'  "entry_imports": ["routes", "database"],\n'
            f'  "app_type": "web"\n'
            f'}}\n\n'
            f"RULES:\n"
            f"- Set 'primary_language' to the project's main stack (python, rust, go, javascript, typescript, "
            f"java, csharp, cpp, kotlin, mixed, …). Use 'mixed' if several languages are first-class.\n"
            f"- Every dev must own at least one file\n"
            f"- Shared models/types go in ONE file that everyone imports from\n"
            f"- The entry point file is SYSTEM-MANAGED — set its owner to 'system'\n"
            f"  (The entry point will be auto-generated to wire all modules together)\n"
            f"- NO two devs should own the same file — split into separate modules instead\n"
            f"- Include ALL files needed for a working application\n"
            f"- 'depends_on' MUST list files that must be complete before this file can be written.\n"
            f"  Files with no dependencies have 'depends_on': []. The entry point depends on ALL other files.\n"
            f"  Test files depend on the files they test.\n"
            f"- 'exports' MUST list the exact symbol names other files need to import from this file\n"
            f"- 'build_command' is the shell command to run the app or run tests\n"
            f"- 'build_file' is the config file that lists dependencies (e.g. 'requirements.txt', 'Cargo.toml',\n"
            f"  'package.json', 'go.mod'). Leave empty if not applicable.\n"
            f"- 'install_command' is the shell command to install dependencies before building\n"
            f"  (e.g. 'npm install', 'pip install -r requirements.txt', 'cargo fetch', 'go mod download').\n"
            f"  Leave empty if no install step is needed.\n"
            f"- 'gitignore_patterns' is a list of patterns for .gitignore based on the build system\n"
            f"  (e.g. ['node_modules/', 'dist/', 'package-lock.json'] for Node,\n"
            f"  ['__pycache__/', '*.pyc', 'dist/', 'build/'] for Python,\n"
            f"  ['target/'] for Rust). Always include build artifacts and dependency directories.\n"
            f"- 'dependencies' lists external libraries needed (e.g. ['fastapi', 'sqlalchemy'])\n"
            f"- 'init_order' lists modules in the order they should be initialized (if ordering matters)\n"
            f"- 'app_type' MUST be one of: 'web' (HTTP server/API), 'cli' (command-line tool that runs and exits),\n"
            f"  'gui' (desktop window app), 'script' (one-shot script, no stdin loop), 'worker' (background daemon),\n"
            f"  'library' (no runnable entry point — only importable modules).\n"
            f"  Choose based on the PROJECT description. This controls how the manager verifies the app.\n"
            f"  CRITICAL: Any desktop UI (tkinter, PyQt, wxPython, Electron window, JavaFX, etc.) MUST use "
            f"app_type 'gui' — never 'cli' or 'script'. The manager verifies with pytest + start_service; "
            f"real desktop_mouse/screenshots are required only when MANAGER_GUI_DESKTOP_PROOF is on (default).\n"
        )

    contract_output = _llm(
        contract_prompt,
        label="eng_contracts",
        system=_manager_system("eng_manager"),
    )

    # Parse JSON from the output — tolerant of markdown fences
    json_text = contract_output.strip()
    if "```" in json_text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", json_text, re.DOTALL)
        if m:
            json_text = m.group(1).strip()

    try:
        parsed = json.loads(json_text)
        registry = get_contracts()
        registry.set_from_parsed(parsed)
        logger.info(
            f"  Contracts generated: {len(registry.models)} models, "
            f"{len(registry.endpoints)} endpoints, {len(registry.file_map)} files"
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"  Contract parsing failed ({e}) — continuing without typed contracts")


def run_sprint_planning(
    task: str,
    health_states: Dict[str, ActiveInferenceState],
    rolling_ctxs: Dict[str, RollingContext],
) -> Tuple[Dict[str, str], Dict[str, str], Optional[Any]]:
    """
    Engineering sprint planning: assign work items via blackboard,
    then generate typed interface contracts for all agents.
    Returns (dev_assignments, pool, component_graph).
    """
    from .task_decomposition import run_recursive_decomposition, run_component_graph_generation

    sprint_num = _get_sprint_num()
    logger.info(f"  [eng] Recursively decomposing sprint goal (sprint {sprint_num})...")
    tree = run_recursive_decomposition(task, sprint_num)
    tree_text = tree.format_tree()
    leaf_count = len(tree.get_leaf_tasks())
    logger.info(f"  [eng] Decomposition complete — {leaf_count} atomic tasks identified")

    # ComponentGraph: single LLM call for typed dependency graph
    component_graph = None
    try:
        logger.info(f"  [eng] Generating ComponentGraph (sprint {sprint_num})...")
        component_graph = run_component_graph_generation(task, sprint_num)
        if not component_graph or len(component_graph.nodes) < 2:
            component_graph = None
            logger.info("  [eng] ComponentGraph skipped (< 2 nodes) — TaskTree fallback")
        else:
            logger.info(f"  [eng] ComponentGraph ready — {len(component_graph.nodes)} components")
    except Exception as exc:
        logger.warning(f"  [eng] ComponentGraph failed ({exc}) — TaskTree fallback")
        component_graph = None

    enriched_task = (
        task
        + "\n\n\u2500\u2500\u2500 PRE-DECOMPOSED TASK TREE \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        + tree_text
        + "\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        "The tree above shows the full file breakdown. Write blackboard items that align\n"
        "with these atomic files so developers can claim and implement them directly."
    )

    dev_assignments, pool = run_team_planning(
        "Engineering", "eng_manager", ENG_WORKERS, enriched_task, rolling_ctxs, health_states
    )

    # Generate typed contracts so agents share exact signatures
    _generate_contracts(enriched_task, dev_assignments, pool)

    return dev_assignments, pool, component_graph


def run_ceo_summary(
    brief: str,
    results: Dict[str, Optional[TeamResult]],
    plan: ExecutionPlan,
    ctx: RollingContext,
) -> str:
    team_text = "\n\n".join(
        f"{name} (confidence {t.confidence:.0%}, H={t.H_swarm:.3f}):\n{t.manager_synthesis[:500]}"
        for name, t in results.items() if t is not None
    )
    plan_text = ""
    if plan:
        phase_lines = "\n".join(
            f"  Phase {i}: {' + '.join(teams)}"
            for i, teams in enumerate(plan.phases, 1)
        )
        notes = plan.team_notes.get("all", "")
        plan_text = (
            f"Phases:\n{phase_lines}\n"
            + (f"Notes: {notes[:300]}" if notes else "")
        )
    summary = _llm(
        f"You are the CEO.\n\nPROJECT: {brief}\n\n"
        + (f"EXECUTION PLAN:\n{plan_text}\n\n" if plan_text else "")
        + f"TEAM RESULTS:\n{team_text}\n\n"
        f"Write an executive summary:\n"
        f"1. Project Overview\n2. Key Architecture Decisions\n3. Design Highlights\n"
        f"4. Implementation Highlights\n5. Quality & Risk Assessment\n6. Next Steps\n\n"
        f"Flag any elevated H_swarm teams. Be concise and actionable.",
        label="ceo_summary",
        system=_SYSTEM_CEO,
    )
    ctx.add(brief, summary)
    return summary


# ── Engineering team: sprint planning → parallel build → synthesize ──────────


@dataclass
class SprintBlocker:
    """A dependency blocker recorded during the integration phase for cross-sprint planning."""
    agent: str
    task_file: str
    blocker_description: str
    waiting_for_files: List[str]
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            import datetime
            self.timestamp = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# Thread-safe sprint-blocker registry (cleared at the start of each engineering sprint)
_sprint_blockers: List[SprintBlocker] = []
_sprint_blockers_lock = threading.Lock()


def _record_sprint_blocker(blocker: SprintBlocker) -> None:
    with _sprint_blockers_lock:
        _sprint_blockers.append(blocker)
    logger.warning(
        f"[Blocker] {blocker.agent} blocked on {blocker.task_file!r}: {blocker.blocker_description[:120]}"
    )


def _get_sprint_blockers() -> List[SprintBlocker]:
    with _sprint_blockers_lock:
        return list(_sprint_blockers)


def _clear_sprint_blockers() -> None:
    with _sprint_blockers_lock:
        _sprint_blockers.clear()


def _looks_like_dependency_error(output: str) -> bool:
    """Heuristic: does the error output look like a missing-dependency / not-yet-written file?"""
    lowered = output.lower()
    dependency_signals = [
        "modulenotfounderror",
        "cannot import name",
        "importerror",
        "no module named",
        "no such file or directory",
        "enoent",
        "cannot find module",
        "module not found",
        "failed to resolve",
        "not yet implemented",
        "connection refused",
        "address already in use",  # service not ready yet
    ]
    return any(sig in lowered for sig in dependency_signals)


class EngTaskQueue:
    """
    Thread-safe shared task queue for async engineering dispatch.
    Tasks with unmet dependencies stay blocked until prerequisites complete.
    """

    def __init__(
        self,
        registry: InterfaceContractRegistry,
        dev_assignments: Dict[str, str],
        pool_tasks: Dict[str, str] = None,
        component_graph: Optional[Any] = None,
    ):
        self._lock = threading.RLock()
        self.tasks: Dict[str, EngTask] = {}
        self._completed_tasks: set = set()
        pool_tasks = pool_tasks or {}
        self._component_graph = component_graph

        def _is_valid_fname(fname: str) -> bool:
            """Reject wildcard/glob paths the LLM sometimes generates (e.g. migrations/versions/*)."""
            return not any(c in fname for c in ("*", "?", "<", ">", "|"))

        # ── ComponentGraph path ────────────────────────────────────────────
        if component_graph and len(component_graph.nodes) >= 2:
            try:
                import json as _json
                _graph_snapshot = _json.loads(
                    component_graph.SAVE_PATH.read_text(encoding="utf-8")
                ) if component_graph.SAVE_PATH.exists() else None

                for cid in component_graph.topological_order:
                    comp = component_graph.nodes.get(cid)
                    if not comp or not comp.file_path:
                        continue
                    tid = f"task_comp_{cid}_p1"
                    dep_ids = [
                        f"task_comp_{dep}_p1"
                        for dep in comp.depends_on
                        if dep in component_graph.nodes
                    ]
                    # Build description including public interface
                    pi = comp.public_interface
                    iface_lines = []
                    if pi.get("classes"):
                        iface_lines.append("Classes: " + ", ".join(pi["classes"]))
                    if pi.get("functions"):
                        iface_lines.append("Functions:\n  " + "\n  ".join(pi["functions"]))
                    if pi.get("constants"):
                        iface_lines.append("Constants: " + ", ".join(pi["constants"]))
                    iface_text = ("\n".join(iface_lines)) if iface_lines else "none specified"
                    description = (
                        f"PHASE 1: Implement {comp.name} ({comp.file_path})\n"
                        f"{comp.description}\n\n"
                        f"REQUIRED PUBLIC INTERFACE:\n{iface_text}"
                    )
                    self.tasks[tid] = EngTask(
                        id=tid,
                        file=comp.file_path,
                        description=description,
                        depends_on=dep_ids,
                        status="pending" if not dep_ids else "blocked",
                        phase=PHASE_IMPLEMENTATION,
                        component_id=cid,
                        component_graph_snapshot=_graph_snapshot,
                        depth=comp.depth,
                    )

                logger.info(
                    f"[TaskQueue] ComponentGraph mode: {len(self.tasks)} tasks from "
                    f"{len(component_graph.nodes)} components (topological order)"
                )
            except Exception as _cg_err:
                logger.warning(f"[TaskQueue] ComponentGraph task build failed ({_cg_err}) — falling back")
                self.tasks.clear()
        # ── End ComponentGraph path ────────────────────────────────────────

        file_to_task_id = {}
        for fname, fc in registry.file_map.items():
            if fname == registry.entry_point:
                continue
            if not _is_valid_fname(fname):
                logger.warning(f"[TaskQueue] skipping invalid filename in contracts: {fname!r}")
                continue
            tid = f"task_{fname.replace('/', '_').replace('.', '_')}"
            file_to_task_id[fname] = tid

        # Phase 1: Implementation (Drafting)  — skipped when ComponentGraph already populated tasks
        if not any(t.phase == PHASE_IMPLEMENTATION for t in self.tasks.values()):
            for fname, fc in registry.file_map.items():
                if fname == registry.entry_point:
                    continue
                if not _is_valid_fname(fname):
                    continue
                tid = f"task_{fname.replace('/', '_').replace('.', '_')}_p1"
                dep_ids = [
                    f"task_{d.replace('/', '_').replace('.', '_')}_p1" for d in fc.depends_on
                    if d in file_to_task_id
                ]
                desc = f"PHASE 1: Implementation and local drafting for {fname}"
                for dk, assignment in dev_assignments.items():
                    if fname in assignment:
                        desc = f"PHASE 1: {assignment}"
                        break

                self.tasks[tid] = EngTask(
                    id=tid, file=fname, description=desc,
                    depends_on=dep_ids, status="pending" if not dep_ids else "blocked",
                    phase=PHASE_IMPLEMENTATION
                )

        # No typed contracts → derive per-file tasks from blackboard text so the queue is not
        # only __integration__ (which would let a single dev claim integration immediately).
        if not any(t.phase == PHASE_IMPLEMENTATION for t in self.tasks.values()):
            seen_files: set = set()
            for assign_blob in list(dev_assignments.values()) + list(pool_tasks.values()):
                for m in re.finditer(r"\[([^\]]+)\]", assign_blob):
                    for part in m.group(1).split(","):
                        fn = part.strip()
                        if not fn or not _is_valid_fname(fn) or fn in seen_files:
                            continue
                        seen_files.add(fn)
                        tid = f"task_{fn.replace('/', '_').replace('.', '_')}_p1"
                        if tid in self.tasks:
                            continue
                        self.tasks[tid] = EngTask(
                            id=tid,
                            file=fn,
                            description=f"PHASE 1 (no contracts): {assign_blob[:280]}",
                            depends_on=[],
                            status="pending",
                            phase=PHASE_IMPLEMENTATION,
                        )

        integ_tid = "task_integration_test"
        self.tasks[integ_tid] = EngTask(
            id=integ_tid, file="__integration__",
            description="Final integration: final build check and smoke tests",
            depends_on=list(self.tasks.keys()),
            status="blocked", # Always last
            phase=PHASE_INTEGRATION
        )

        # Any files NOT covered by dev assignments (pool tasks)
        for iid, pool_desc in pool_tasks.items():
            # Try to extract file if it's there
            file_match = re.search(r"\[([^\]]+)\]", pool_desc)
            if file_match:
                p_files = [f.strip() for f in file_match.group(1).split(",") if f.strip()]
                for pf in p_files:
                    if pf in file_to_task_id:
                        # Existing file is now part of an unassigned Pool Task
                        tid = file_to_task_id[pf] + "_p1"
                        if tid in self.tasks:
                            self.tasks[tid].description = f"POOL TASK: {pool_desc}"

        n_pending = sum(1 for t in self.tasks.values() if t.status == "pending")
        n_blocked = sum(1 for t in self.tasks.values() if t.status == "blocked")
        logger.info(f"[TaskQueue] initialized {len(self.tasks)} tasks ({n_pending} pending, {n_blocked} blocked) + final integration.")
        self._load()   # crash recovery: reload persisted state if available
        # After reload, dependencies that were already satisfied in the persisted state
        # must be re-evaluated — without this, Phase 2 tasks stay blocked forever on restart.
        self._unblock_dependents()
        self._persist()

    # _PERSIST_PATH must NOT be a class attribute — OUTPUT_DIR may be overridden at
    # runtime. A frozen class attr would always point at company_output/task_queue_state.json
    # and load stale task states from a prior full-company run into an engineers-only run.
    @property
    def _persist_path(self) -> Path:
        return OUTPUT_DIR / "task_queue_state.json"

    def _persist(self) -> None:
        """Serialize queue state to disk after every mutation."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "tasks": {
                    tid: {
                        "id": t.id, "file": t.file, "description": t.description,
                        "depends_on": t.depends_on, "assigned_to": t.assigned_to,
                        "status": t.status, "retries": t.retries,
                        "primary_owner": t.primary_owner, "phase": t.phase,
                        "waiting_for": t.waiting_for,
                    }
                    for tid, t in self.tasks.items()
                },
                "completed_tasks": list(self._completed_tasks),
            }
            self._persist_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[TaskQueue] persist failed: {e}")

    def _load(self) -> None:
        """Reload queue state from disk if available (crash recovery)."""
        if not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for tid, td in data.get("tasks", {}).items():
                if tid in self.tasks:
                    t = self.tasks[tid]
                    t.status      = td.get("status", t.status)
                    t.assigned_to = td.get("assigned_to", t.assigned_to)
                    t.retries     = td.get("retries", t.retries)
                    t.waiting_for = td.get("waiting_for", [])
            self._completed_tasks = set(data.get("completed_tasks", []))
            logger.info(f"[TaskQueue] crash-recovery: reloaded state from {self._persist_path.name}")
        except Exception as e:
            logger.warning(f"[TaskQueue] load failed: {e}")

    def claim_next(self, dev_key: str) -> Optional[EngTask]:
        """Claim the next available pending task — leaf components (depth=0) first."""
        with self._lock:
            pending = [t for t in self.tasks.values() if t.status == "pending"]
            if not pending:
                return None
            pending.sort(key=lambda t: (t.depth, t.id))
            task = pending[0]
            task.status = "in_progress"
            task.assigned_to = dev_key
            logger.info(f"[TaskQueue] {dev_key} claimed '{task.id}' (depth={task.depth}, {task.file})")
            self._persist()
            return task

    def complete(self, task_id: str) -> None:
        """Mark a task completed and unblock dependents.
        No-op if the task is already in a terminal state (completed/failed)."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                if task.status in ("completed", "failed"):
                    logger.debug(f"[TaskQueue] complete('{task_id}') ignored — already {task.status}")
                    return
                task.status = "completed"
                self._completed_tasks.add(task_id)
                logger.info(f"[TaskQueue] task '{task_id}' COMPLETED")
                self._unblock_dependents()
                self._persist()

    def get_retries(self, task_id: str) -> int:
        """Return retry count for a task, thread-safely."""
        with self._lock:
            task = self.tasks.get(task_id)
            return task.retries if task else MAX_RETRIES_PER_TASK

    def fail(self, task_id: str) -> None:
        """Mark a task failed. It may be retried by another agent."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.retries += 1
                if task.retries < MAX_RETRIES_PER_TASK:
                    task.status = "pending"
                    task.assigned_to = None
                    logger.warning(f"[TaskQueue] task '{task_id}' failed — requeueing (retry {task.retries})")
                else:
                    task.status = "failed"
                    self._completed_tasks.add(task_id)
                    logger.error(f"[TaskQueue] task '{task_id}' FAILED permanently after {task.retries} retries")
                    self._unblock_dependents()
                self._persist()

    def _unblock_dependents(self) -> None:
        """Move blocked/waiting tasks to pending if all their dependencies are satisfied."""
        for t in self.tasks.values():
            if t.status in ("blocked", "waiting"):
                deps_met = all(d in self._completed_tasks for d in t.depends_on)
                if t.status == "waiting":
                    # Also check that the specific files this task is waiting for are now done
                    wait_met = all(
                        any(ct.file == wf and ct.status == "completed" for ct in self.tasks.values())
                        for wf in (t.waiting_for or [])
                    )
                    if deps_met and wait_met:
                        t.status = "pending"
                        t.waiting_for = []
                        logger.info(f"[TaskQueue] wait-unblocked task '{t.id}' ({t.file}) — dependencies arrived")
                elif deps_met:
                    t.status = "pending"
                    logger.info(f"[TaskQueue] unblocked task '{t.id}' ({t.file})")

    def set_waiting(self, task_id: str, waiting_for_files: List[str]) -> None:
        """Put a task into 'waiting' state until specific dependency files complete."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.status = "waiting"
                task.waiting_for = list(waiting_for_files)
                self._persist()
                logger.info(
                    f"[TaskQueue] task '{task_id}' is WAITING for: {waiting_for_files}"
                )

    def requeue_after_wait(self, task_id: str) -> None:
        """Re-queue a task after it was woken from WAITING — does NOT increment retries."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.status = "pending"
                task.assigned_to = None
                task.waiting_for = []
                self._persist()
                logger.info(f"[TaskQueue] task '{task_id}' requeued after wait (retries unchanged at {task.retries})")

    def is_deadlocked(self) -> bool:
        """Return True when active tasks are stalled — nothing can make progress.
        Covers: all-waiting, all-blocked, or mixed blocked+waiting with no pending/in_progress."""
        with self._lock:
            active = [t for t in self.tasks.values() if t.status not in ("completed", "failed")]
            if not active:
                return False
            if any(t.status in ("pending", "in_progress") for t in active):
                return False
            return all(t.status in ("blocked", "waiting") for t in active)

    def get_waiting_tasks(self) -> List["EngTask"]:
        with self._lock:
            return [t for t in self.tasks.values() if t.status == "waiting"]

    def all_done(self) -> bool:
        with self._lock:
            return all(t.status in ("completed", "failed") for t in self.tasks.values())

    def has_work_available(self) -> bool:
        """True if there are pending tasks or in-progress tasks that might unblock others."""
        with self._lock:
            return any(t.status in ("pending", "in_progress", "blocked", "waiting") for t in self.tasks.values())

    def get_status(self) -> str:
        with self._lock:
            counts: Dict[str, int] = {}
            for t in self.tasks.values():
                counts[t.status] = counts.get(t.status, 0) + 1
            lines = [f"Tasks: {len(self.tasks)} total"]
            for status in ("pending", "blocked", "waiting", "in_progress", "completed", "failed"):
                if counts.get(status):
                    lines.append(f"  {status}: {counts[status]}")
            in_prog = [t for t in self.tasks.values() if t.status == "in_progress"]
            if in_prog:
                lines.append("  Active:")
                for t in in_prog:
                    lines.append(f"    {t.assigned_to} → {t.file}")
            waiting = [t for t in self.tasks.values() if t.status == "waiting"]
            if waiting:
                lines.append("  Waiting:")
                for t in waiting:
                    lines.append(f"    {t.assigned_to} → {t.file} (needs: {t.waiting_for})")
            return "\n".join(lines)

    def get_completed_files(self) -> List[str]:
        """Return filenames of completed tasks (for peer context)."""
        with self._lock:
            return [t.file for t in self.tasks.values() if t.status == "completed" and t.file != "__integration__"]

    def force_fail_remaining(self) -> None:
        """Mark all non-terminal tasks as failed (used by wall-clock timeout)."""
        with self._lock:
            for t in self.tasks.values():
                if t.status in ("pending", "blocked", "in_progress", "waiting"):
                    t.status = "failed"
            self._completed_tasks.update(t.id for t in self.tasks.values() if t.status == "failed")
            self._persist()

    def cancel_all(self) -> None:
        """Immediately cancel all pending/blocked/in-progress/waiting tasks.
        Used by the token budget kill-switch to stop the swarm cleanly."""
        with self._lock:
            for t in self.tasks.values():
                if t.status not in ("completed", "failed"):
                    t.status = "failed"
            self._completed_tasks.update(t.id for t in self.tasks.values())
            self._persist()
        logger.critical("[TaskQueue] ALL TASKS CANCELLED — token budget kill-switch triggered")


def emit_skeleton(dev_assignments: Dict[str, str], sprint_num: int = 1) -> None:
    """
    Write skeleton/stub files based on interface contracts before Round 1.
    Pre-populates dashboard domain claims so agents don't fight over files.
    Entry point is registered as a SHARED file (system-managed).
    Agents fill in the stubs rather than inventing their own file structure.
    """
    registry = get_contracts()
    if not registry.file_map and not registry.models:
        logger.info("[skeleton] No contracts available — skipping skeleton generation")
        return

    logger.info(f"\n{'─'*55}\nSKELETON GENERATION\n{'─'*55}")
    code_dir = OUTPUT_DIR / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    dashboard = get_dashboard()
    files_written = 0


    # ── Write shared model stubs ─────────────────────────────────────────────
    model_files_seen: set = set()
    for model in registry.models:
        model_file = code_dir / model.file
        if model_file.exists() and model.file in model_files_seen:
            continue
        model_files_seen.add(model.file)
        model_file.parent.mkdir(parents=True, exist_ok=True)
        fields_lines = []
        for field_str in model.fields.split(","):
            field_str = field_str.strip()
            if field_str:
                fields_lines.append(f"    {field_str}")
        fields_block = "\n".join(fields_lines) if fields_lines else "    pass"
        stub = (
            f"# AUTO-GENERATED SKELETON — implement the bodies\n"
            f"# Owner: system\n\n"
            f"class {model.name}:\n"
            f"{fields_block}\n"
        )
        if model_file.exists():
            existing = model_file.read_text(encoding="utf-8")
            model_file.write_text(existing + "\n\n" + stub, encoding="utf-8")
        else:
            model_file.write_text(stub, encoding="utf-8")
        files_written += 1
        logger.info(f"  [skeleton] wrote model stub: {model.file}")

    # ── Write generic file stubs ─────────────────────────────────────────────
    _EXT_COMMENTS = {
        ".py": ("#", ""),    ".go": ("//", ""),    ".rs": ("//", ""),
        ".js": ("//", ""),   ".ts": ("//", ""),    ".jsx": ("//", ""),
        ".tsx": ("//", ""),  ".java": ("//", ""),  ".c": ("//", ""),
        ".cpp": ("//", ""),  ".rb": ("#", ""),     ".lua": ("--", ""),
    }

    for fname, fc in registry.file_map.items():
        if fname == registry.entry_point:
            continue

        # Skip wildcard/glob paths that the LLM sometimes generates (e.g. "migrations/versions/*")
        # — these are not valid file paths on any OS.
        if any(c in fname for c in ("*", "?", "<", ">", "|")):
            logger.warning(f"  [skeleton] skipping invalid filename (contains wildcard/illegal char): {fname!r}")
            continue

        file_path = code_dir / fname
        if file_path.exists():
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)

        ext = Path(fname).suffix
        comment_prefix, _ = _EXT_COMMENTS.get(ext, ("#", ""))

        stub = (
            f"{comment_prefix} AUTO-GENERATED SKELETON — {fc.description}\n"
            f"{comment_prefix} Owner: {fc.owner}\n"
            f"{comment_prefix} Exports: {', '.join(fc.exports)}\n"
            f"{comment_prefix} Imports from: {', '.join(fc.imports_from) if fc.imports_from else 'none'}\n"
            f"{comment_prefix} TODO: implement this file\n"
        )

        file_path.write_text(stub, encoding="utf-8")
        files_written += 1
        logger.info(f"  [skeleton] wrote stub: {fname} (owner: {fc.owner})")


    logger.info(f"  [skeleton] {files_written} stub files written")






def enforce_integration() -> str:
    """
    Lightweight integration enforcer:
      1. Creates missing __init__.py files for Python packages
      2. Assembles shared files from their sections
      3. Uses LLM to generate the entry point that wires all modules
      4. Uses LLM to generate build config files if needed
      5. Runs the build command and returns errors for the agents to fix
    """
    code_dir = OUTPUT_DIR / "code"
    if not code_dir.exists():
        return ""

    registry = get_contracts()
    fixes: List[str] = []

    # 1. Create missing __init__.py for any dir with .py files
    for dirpath in code_dir.rglob("*"):
        if dirpath.is_dir() and any(dirpath.glob("*.py")):
            init = dirpath / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
                fixes.append(f"Created {init.relative_to(code_dir)}")


    # 3. LLM-generate entry point
    if registry.entry_point and registry.file_map:
        ep_result = _generate_entry_point_via_llm(registry, code_dir)
        if ep_result:
            fixes.append(f"LLM-generated entry point '{registry.entry_point}'")

    # 4. LLM-generate build config
    if registry.build_file:
        bf_result = _emit_build_scaffold_via_llm(registry, code_dir)
        if bf_result:
            fixes.append(f"LLM-generated build config '{registry.build_file}'")

    if fixes:
        report = "INTEGRATION ENFORCER — auto-fixes applied:\n" + "\n".join(f"  + {f}" for f in fixes)
        logger.info(f"\n{report}")
        return report
    return ""


_SERVER_CMD_PATTERNS = [
    "uvicorn ", "gunicorn ", "flask run", "python server", "python app",
    "python main", "python -m uvicorn", "python -m flask", "python -m http.server",
    "npm start", "npm run dev", "npm run start", "node server", "node index",
    "node app", "daphne ", "hypercorn ", "php artisan serve", "rails server",
    "rails s", "django", "manage.py runserver",
]


def _is_server_command(cmd: str) -> bool:
    """Detect build_command that is actually a long-running server start."""
    lowered = cmd.lower().strip()
    return any(lowered.startswith(p) or p in lowered for p in _SERVER_CMD_PATTERNS)


def _run_build_command(registry: InterfaceContractRegistry) -> str:
    """Run the build command and return its output (empty if success).
    Skips commands that look like long-running server starts — those are
    tested via start_service/http_request in the manager fix loop instead."""
    if not registry.build_command:
        return ""
    if _is_server_command(registry.build_command):
        logger.info(
            f"[build] skipping server-style build_command '{registry.build_command}' "
            f"— app boot is verified via start_service() instead"
        )
        return ""
    _norm_build = _normalize_shell_command_for_windows(registry.build_command)
    if _run_shell_blocks_gui_entrypoint(_norm_build):
        logger.info(
            f"[build] skipping GUI entrypoint build_command {registry.build_command!r} "
            f"— would block; verify via start_service / desktop tools instead"
        )
        return ""
    code_dir = OUTPUT_DIR / "code"
    if not code_dir.exists():
        return ""
    try:
        result = subprocess.run(
            registry.build_command, shell=True, cwd=str(code_dir),
            env=_subprocess_env_for_project(code_dir),
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            out = ((result.stdout or "")[-2000:] + "\n" + (result.stderr or "")[-2000:]).strip()
            return f"BUILD FAILED (exit {result.returncode}):\n{out}"
    except subprocess.TimeoutExpired:
        return "BUILD TIMEOUT: command took longer than 60s"
    except Exception as e:
        return f"BUILD ERROR: {e}"
    return ""


@dataclass
class TestGateResult:
    passed:  bool    # True if tests exited 0, or no test suite found
    skipped: bool    # True if no test files were detected
    output:  str     # raw stdout+stderr trimmed to 4000 chars
    command: str     # command that ran (empty if skipped)


def _resolve_cmake_tool(name: str) -> Optional[str]:
    """Resolve ``cmake`` or ``ctest`` (PATH or typical Windows Kitware install under Program Files)."""
    import shutil

    w = shutil.which(name)
    if w:
        return w
    if sys.platform == "win32":
        roots: List[str] = []
        for pf in ("ProgramFiles", "ProgramFiles(x86)"):
            r = os.environ.get(pf)
            if r:
                roots.append(r)
        # Fallback if env is stripped (rare in subprocess sandboxes)
        roots.extend(["C:\\Program Files", "C:\\Program Files (x86)"])
        seen: set = set()
        for root in roots:
            if root in seen:
                continue
            seen.add(root)
            p = Path(root) / "CMake" / "bin" / f"{name}.exe"
            if p.is_file():
                return str(p)
    return None


def _cmake_build_is_msvc_multi_config(code_dir: Path) -> bool:
    """True if build/ looks like a Visual Studio multi-config generator (needs --config Release)."""
    b = code_dir / "build"
    if not b.is_dir():
        return False
    if sys.platform != "win32":
        return False
    if any(b.glob("*.sln")):
        return True
    cache = b / "CMakeCache.txt"
    if cache.exists():
        try:
            txt = cache.read_text(encoding="utf-8", errors="ignore")
            if "Visual Studio" in txt and "Ninja" not in txt:
                return True
        except OSError:
            pass
    return False


def _cmake_test_gate_command(code_dir: Path) -> Optional[str]:
    """Build cmake+ctest shell command with resolved executables; None if cmake missing."""
    cmake = _resolve_cmake_tool("cmake")
    if not cmake:
        return None
    ctest = _resolve_cmake_tool("ctest")
    if not ctest:
        alt = Path(cmake).parent / ("ctest.exe" if sys.platform == "win32" else "ctest")
        if alt.is_file():
            ctest = str(alt)
    if not ctest:
        return None

    def _q(p: str) -> str:
        return f'"{p}"' if " " in p else p

    qc, qt = _q(cmake), _q(ctest)
    if _cmake_build_is_msvc_multi_config(code_dir):
        return (
            f"{qc} --build build --config Release && "
            f"{qt} --test-dir build -C Release --output-on-failure"
        )
    return f"{qc} --build build && {qt} --test-dir build --output-on-failure"


def _run_test_gate(code_dir: Path) -> TestGateResult:
    """
    Run the project's test suite.
    If TEST_GATE_HOOKS is non-empty, run each hook command in sequence — the gate
    fails on the first non-zero exit.  When empty, fall back to auto-detection
    (pytest or npm).
    Returns TestGateResult. Never raises — all failures are captured in .output.
    Called by the manager fix loop and by self-verification.
    """
    # ── Configurable hooks path ───────────────────────────────────────────
    if TEST_GATE_HOOKS:
        combined_output: List[str] = []
        for hook_cmd in TEST_GATE_HOOKS:
            try:
                result = subprocess.run(
                    hook_cmd, shell=True, capture_output=True, text=True,
                    timeout=60, cwd=str(code_dir),
                    env=_subprocess_env_for_project(code_dir),
                    encoding="utf-8", errors="replace",
                )
                raw = ((result.stdout or "") + (result.stderr or ""))[-4000:]
                combined_output.append(f"[hook: {hook_cmd}]\n{raw}")
                if result.returncode != 0:
                    return TestGateResult(
                        passed=False, skipped=False,
                        output="\n".join(combined_output),
                        command=hook_cmd,
                    )
            except subprocess.TimeoutExpired:
                combined_output.append(f"[hook: {hook_cmd}] TIMEOUT after 60s")
                return TestGateResult(
                    passed=False, skipped=False,
                    output="\n".join(combined_output),
                    command=hook_cmd,
                )
            except Exception as e:
                combined_output.append(f"[hook: {hook_cmd}] ERROR: {e}")
                return TestGateResult(
                    passed=False, skipped=False,
                    output="\n".join(combined_output),
                    command=hook_cmd,
                )
        return TestGateResult(
            passed=True, skipped=False,
            output="\n".join(combined_output),
            command="; ".join(TEST_GATE_HOOKS),
        )

    # ── Auto-detect path (language-agnostic) ─────────────────────────────
    tests_dir = code_dir / "tests"

    def _has_test_files(*globs: str) -> bool:
        for d in (tests_dir, code_dir):
            if d.exists():
                for g in globs:
                    for p in d.rglob(g):
                        if "node_modules" not in p.parts and ".git" not in p.parts:
                            return True
        return False

    def _has_file(*names: str) -> bool:
        return any((code_dir / n).exists() for n in names)

    def _makefile_has_test() -> bool:
        mf = code_dir / "Makefile"
        if not mf.exists():
            return False
        try:
            return "test" in mf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False

    # Detection order: most-specific first
    # Use `python -m pytest` so it works regardless of whether `pytest` is on
    # the system PATH (common on Windows where the Scripts/ directory may be absent).
    if _has_test_files("test_*.py", "*_test.py", "*_tests.py", "tests_*.py"):
        # Important: run from cwd=code_dir with RELATIVE targets, because OUTPUT_DIR
        # can be relative (e.g., "eng_output") and absolute-looking relative paths
        # like "eng_output\\code\\tests" become invalid from inside code_dir.
        _pyexe = f'"{sys.executable}"'  # quote for paths with spaces (e.g. "Quantum Swarm")
        if tests_dir.exists():
            cmd = f"{_pyexe} -m pytest tests --tb=short -q"
        else:
            cmd = f"{_pyexe} -m pytest . --tb=short -q"
    elif _has_file("Cargo.toml"):
        cmd = "cargo test"
    elif _has_file("go.mod"):
        cmd = "go test ./..."
    elif _has_file("pom.xml"):
        cmd = "mvn test -q"
    elif _has_file("build.gradle", "build.gradle.kts"):
        cmd = "gradle test"
    elif any(code_dir.glob("*.csproj")) or any(code_dir.glob("*.sln")):
        cmd = "dotnet test"
    elif _has_file("CMakeLists.txt"):
        cmd = _cmake_test_gate_command(code_dir)
        if not cmd:
            return TestGateResult(
                passed=False,
                skipped=False,
                output=(
                    "cmake not found on PATH and not under Program Files\\CMake\\bin. "
                    "Install CMake or add it to PATH so the test gate can run "
                    "`cmake --build build` and `ctest`."
                ),
                command="(cmake not found)",
            )
    elif _makefile_has_test():
        cmd = "make test"
    elif _has_test_files("*.spec.ts", "*.spec.js", "*.test.ts", "*.test.js") or _has_file("package.json"):
        cmd = "npm test --if-present"
    elif _has_test_files("*_spec.rb", "*_test.rb"):
        cmd = "bundle exec rspec"
    else:
        return TestGateResult(passed=True, skipped=True, output="", command="")

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=120, cwd=str(code_dir),
            env=_subprocess_env_for_project(code_dir),
            encoding="utf-8", errors="replace",
        )
        raw = ((result.stdout or "") + (result.stderr or ""))[-4000:]
        return TestGateResult(passed=(result.returncode == 0), skipped=False,
                              output=raw, command=cmd)
    except subprocess.TimeoutExpired:
        return TestGateResult(passed=False, skipped=False, command=cmd,
                              output="TEST GATE TIMEOUT: suite did not finish within 120s.")
    except Exception as e:
        return TestGateResult(passed=False, skipped=False, command=cmd,
                              output=f"TEST GATE ERROR: {e}")


# ── Per-file self-verification (runs after each agent merges) ────────────────

@dataclass
class SelfVerifyResult:
    passed: bool
    output: str
    is_own_fault: bool  # True → agent's merge introduced the failure

def _run_self_verify(code_dir: Path, eng_task: "EngTask") -> SelfVerifyResult:
    """Run lightweight per-file verification after an agent's merge.

    Checks (when applicable):
      - Python: import smoke + matching pytest file
      - JS/TS: node --check / tsc
      - Rust/Go: ``cargo check`` / ``go vet`` when manifest present
      - Dockerfile / YAML / JSON: syntax validation
    Returns SelfVerifyResult; fault attribution is done by the caller.
    """
    fpath = code_dir / eng_task.file
    if not fpath.exists():
        return SelfVerifyResult(passed=True, output="(file does not exist — skip)", is_own_fault=False)

    checks: List[str] = []
    suffix = fpath.suffix.lower()
    _pyexe = f'"{sys.executable}"'  # quote for paths with spaces (e.g. "Quantum Swarm")

    if suffix == ".py":
        # Syntax parse always (avoids flaky package import before app/__init__.py exists).
        checks.append(
            f"{_pyexe} -c "
            f"\"import ast, pathlib; ast.parse(pathlib.Path(r'{fpath}').read_text(encoding='utf-8'))\""
        )
        rel_slash = eng_task.file.replace("\\", "/")
        if "/" not in rel_slash:
            mod_path = rel_slash
            if mod_path.endswith(".py"):
                mod_path = mod_path[:-3]
            checks.append(f"{_pyexe} -c \"import {mod_path}\"")
        _test_candidates = [
            code_dir / "tests" / f"test_{fpath.name}",
            code_dir / "tests" / f"{fpath.stem}_test.py",
            fpath.parent / f"test_{fpath.name}",
        ]
        for tc in _test_candidates:
            if tc.exists():
                checks.append(f"{_pyexe} -m pytest {str(tc)} -x -q --tb=short")
                break
    elif suffix in (".js", ".mjs", ".cjs"):
        checks.append(f"node --check {str(fpath)}")
    elif suffix in (".ts", ".tsx"):
        npx = "npx.cmd" if sys.platform == "win32" else "npx"
        checks.append(f"{npx} tsc --noEmit {str(fpath)} 2>&1 || true")
    elif suffix == ".rs" and (code_dir / "Cargo.toml").exists():
        checks.append("cargo check -q")
    elif suffix == ".go" and (code_dir / "go.mod").exists():
        checks.append("go vet ./...")
    elif suffix in (".json",):
        checks.append(f"{_pyexe} -c \"import json, pathlib; json.loads(pathlib.Path(r'{fpath}').read_text())\"")
    elif suffix in (".yml", ".yaml"):
        checks.append(f"{_pyexe} -c \"import yaml, pathlib; yaml.safe_load(pathlib.Path(r'{fpath}').read_text())\"")
    elif fpath.name == "Dockerfile":
        checks.append(f"{_pyexe} -c \"p=open(r'{fpath}').read(); assert 'FROM' in p, 'no FROM in Dockerfile'\"")

    if not checks:
        return SelfVerifyResult(passed=True, output="(no applicable checks)", is_own_fault=False)

    all_output: List[str] = []
    for cmd in checks:
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(code_dir),
                env=_subprocess_env_for_project(code_dir),
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            combined = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
            all_output.append(f"$ {cmd}\n{combined}")
            if proc.returncode != 0:
                return SelfVerifyResult(
                    passed=False,
                    output="\n".join(all_output),
                    is_own_fault=False,  # caller will attribute
                )
        except subprocess.TimeoutExpired:
            all_output.append(f"$ {cmd}\nTIMEOUT (30s)")
            return SelfVerifyResult(passed=False, output="\n".join(all_output), is_own_fault=False)
        except Exception as e:
            all_output.append(f"$ {cmd}\nERROR: {e}")

    return SelfVerifyResult(passed=True, output="\n".join(all_output), is_own_fault=False)


def _run_self_verify_with_attribution(
    code_dir: Path, eng_task: "EngTask", pre_merge_result: SelfVerifyResult
) -> SelfVerifyResult:
    """Run verification after merge and compare with pre-merge to attribute fault."""
    post = _run_self_verify(code_dir, eng_task)
    if post.passed:
        return post
    if not pre_merge_result.passed:
        return SelfVerifyResult(passed=False, output=post.output, is_own_fault=False)
    return SelfVerifyResult(passed=False, output=post.output, is_own_fault=True)


def _generate_entry_point_via_llm(
    registry: InterfaceContractRegistry, code_dir: Path
) -> bool:
    """Use LLM to generate the entry point file that wires all modules together."""
    file_summaries = []
    for fname, fc in registry.file_map.items():
        if fname == registry.entry_point:
            continue
        fpath = code_dir / fname
        source_preview = ""
        if fpath.exists():
            try:
                source_preview = fpath.read_text(encoding="utf-8")[:500]
            except Exception:
                pass
        file_summaries.append(
            f"  {fname} (exports: {fc.exports}, imports_from: {fc.imports_from}):\n"
            f"    {fc.description}\n"
            f"    Preview: {source_preview[:200]}..."
        )

    prompt = (
        f"Generate the entry point file '{registry.entry_point}' that wires together all modules.\n\n"
        f"MODULES:\n" + "\n".join(file_summaries) + "\n\n"
        f"ENTRY IMPORTS NEEDED: {registry.entry_imports}\n"
        f"DEPENDENCIES: {registry.dependencies}\n\n"
        f"REQUIREMENTS:\n"
        f"  - Import and wire ALL modules listed above\n"
        f"  - The app must be runnable with: {registry.build_command or 'appropriate command'}\n"
        f"  - Output ONLY the file content, no markdown fences\n"
        f"  - Do NOT append CHANGES:, VALIDATION:, STANCE:, HANDOFF:, or any prose summary — executable source only\n"
        f"  - Make it production-ready with error handling\n"
        "\nINTEGRATION RULES:\n"
        "  - The entry point will be AUTO-GENERATED — do NOT create it yourself\n"
        "  - Your file MUST export exactly the symbols listed in your contract's 'exports'\n"
        "  - Import from files listed in your contract's 'imports_from'\n"
        "  - Do NOT invent new file names — use the exact paths from the contract\n"
    )
    try:
        source = _llm(prompt, label="generate_entry_point")
        if source and "```" in source:
            m = re.search(r"```\w*\n(.*?)```", source, re.DOTALL)
            if m:
                source = m.group(1)
        if source and source.strip():
            body = source.strip()
            if str(registry.entry_point).endswith(".py"):
                body = _strip_llm_summary_lines(body)
                try:
                    ast.parse(body)
                except SyntaxError as se:
                    logger.warning(
                        f"[generate_entry_point] Python still invalid after prose strip: {se}"
                    )
            ep_path = code_dir / registry.entry_point
            ep_path.parent.mkdir(parents=True, exist_ok=True)
            ep_path.write_text(body.rstrip() + "\n", encoding="utf-8")
            return True
    except Exception as e:
        logger.warning(f"  LLM entry-point generation failed: {e}")
    return False


def _emit_build_scaffold_via_llm(
    registry: InterfaceContractRegistry, code_dir: Path
) -> bool:
    """Use LLM to generate build configuration files (package.json, requirements.txt, etc.)."""
    bf_path = code_dir / registry.build_file
    if bf_path.exists():
        # Skip only if it's real content — not a skeleton stub
        raw = bf_path.read_text(encoding="utf-8", errors="ignore").lstrip()
        if raw and not raw.startswith("#") and not raw.startswith("# AUTO-GENERATED"):
            return False
        # Fall through: file is a skeleton comment — overwrite with real content

    existing_files = []
    for p in code_dir.rglob("*"):
        if "node_modules" in p.parts or ".git" in p.parts:
            continue
        if p.is_file() and not p.name.startswith("."):
            existing_files.append(str(p.relative_to(code_dir)))

    prompt = (
        f"Generate the build configuration file '{registry.build_file}'.\n\n"
        f"PROJECT FILES: {existing_files[:50]}\n"
        f"DEPENDENCIES: {registry.dependencies}\n"
        f"BUILD COMMAND: {registry.build_command}\n\n"
        f"Output ONLY the file content, no markdown fences.\n"
        f"Do NOT append CHANGES:, VALIDATION:, STANCE:, HANDOFF:, or any prose summary.\n"
    )
    if str(registry.build_file).endswith("requirements.txt"):
        prompt += (
            "\nPYTHON REQUIREMENTS.TXT RULES:\n"
            "  - For pygame, PyOpenGL, or other C-extension packages: prefer flexible pins "
            "(e.g. pygame>=2.5.0) over == pins that force sdist builds.\n"
            "  - When a package often has no wheel for brand-new CPython (e.g. pygame on Windows), "
            "use PEP 508 environment markers so pip does not try to compile from source on those "
            "interpreters — e.g. `pygame>=2.5.0; python_version < \"3.14\"` plus a # comment telling "
            "developers to use a 3.11–3.12 venv for full deps.\n"
            "  - Add a short # comment at the top if native wheels matter: on Windows, "
            "Python 3.11 or 3.12 (64-bit) usually gets pre-built wheels; very new Python "
            "versions may lack wheels and pip will try to compile (often fails without MSYS2).\n"
        )
    is_json = registry.build_file.endswith(".json")
    for attempt in range(3):
        try:
            source = _llm(prompt, label="generate_build_config")
            if source and "```" in source:
                m = re.search(r"```\w*\n(.*?)```", source, re.DOTALL)
                if m:
                    source = m.group(1)
            if not source or not source.strip():
                continue
            content = _strip_llm_summary_lines(source.strip())
            # Validate JSON files before writing
            if is_json:
                # Robustly extract just the outermost {...} block — ignore trailing text
                _start = content.find('{')
                _end = content.rfind('}')
                if _start != -1 and _end != -1 and _end > _start:
                    content = content[_start:_end + 1]
                try:
                    json.loads(content)
                except json.JSONDecodeError as je:
                    logger.warning(f"  LLM build-config attempt {attempt+1}: invalid JSON — {je}")
                    prompt += f"\n\nPREVIOUS ATTEMPT WAS INVALID JSON: {je}\nOutput ONLY valid JSON, no comments, no markdown."
                    continue
            bf_path.parent.mkdir(parents=True, exist_ok=True)
            bf_path.write_text(content.rstrip() + "\n", encoding="utf-8")
            return True
        except Exception as e:
            logger.warning(f"  LLM build-config generation failed: {e}")
    return False






def _setup_project(code_dir: Path) -> None:
    """
    Manager-run project setup: generate build config and install dependencies
    once before any engineering agent starts. This ensures package.json,
    node_modules, etc. exist from the start so agents never race to create them.
    """
    registry = get_contracts()
    if not registry.build_file:
        return

    logger.info(f"[Setup] Manager setting up project ({registry.build_file})...")

    # Generate build config if missing or a skeleton stub
    bf_path = code_dir / registry.build_file
    is_stub = (
        bf_path.exists() and
        bf_path.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("#")
    )
    if not bf_path.exists() or is_stub:
        _emit_build_scaffold_via_llm(registry, code_dir)

    # Install dependencies if build config now exists
    bf_path = code_dir / registry.build_file  # re-check after potential generation
    if not bf_path.exists():
        logger.warning("[Setup] build config still missing after generation — skipping install")
        return

    install_cmd = registry.install_command
    if not install_cmd:
        return

    logger.info(f"[Setup] running '{install_cmd}'...")
    try:
        result = subprocess.run(
            install_cmd, shell=True, cwd=str(code_dir),
            env=_subprocess_env_for_project(code_dir),
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            logger.info(f"[Setup] '{install_cmd}' succeeded")
        else:
            out = ((result.stdout or "") + (result.stderr or ""))[-1000:]
            logger.warning(f"[Setup] '{install_cmd}' failed:\n{out}")
    except subprocess.TimeoutExpired:
        logger.warning(f"[Setup] '{install_cmd}' timed out after 180s")
    except Exception as e:
        logger.warning(f"[Setup] '{install_cmd}' error: {e}")




@dataclass
class ManagerFixResult:
    passed: bool
    rounds_used: int
    final_output: str
    app_run_verified: bool = False


def _manager_fix_collect_errors(code_dir: Path, registry: "InterfaceContractRegistry") -> List[str]:
    """Run test gate + build; return a list of error strings (empty if all green)."""
    errors: List[str] = []
    gate = _run_test_gate(code_dir)
    if gate.skipped:
        logger.info("[ManagerFix] test gate skipped (no tests detected)")
    elif gate.passed:
        logger.info(f"[ManagerFix] test gate passed: {gate.command}")
    else:
        errors.append(f"TEST FAILURE ({gate.command}):\n{gate.output}")
    build_out = _run_build_command(registry)
    if build_out:
        errors.append(build_out)
    return errors


def _manager_saw_start_service(tool_results: List[str]) -> bool:
    return any(tr.startswith("[TOOL: start_service]") for tr in (tool_results or []))


def _manager_saw_desktop_interaction(tool_results: List[str]) -> bool:
    """True if mouse, keyboard, or UIA click ran successfully (tool returned non-ERROR text).
    Screenshot-only does not count; failed desktop_* calls do not count."""
    trs = tool_results or []
    return any(
        tr.startswith("[TOOL: desktop_mouse|ok]")
        or tr.startswith("[TOOL: desktop_keyboard|ok]")
        or tr.startswith("[TOOL: desktop_uia_click|ok]")
        for tr in trs
    )


def _count_desktop_screenshots(tool_results: List[str]) -> int:
    """Count successful screenshots only (disabled desktop / pyautogui → ERROR → not counted)."""
    return sum(1 for tr in (tool_results or []) if tr.startswith("[TOOL: desktop_screenshot|ok]"))


def _manager_saw_http_request(tool_results: List[str]) -> bool:
    return any(tr.startswith("[TOOL: http_request]") for tr in (tool_results or []))


def _load_agent_test_hints() -> str:
    """Load the agent-contributed test hints from design/agent_test_hints.md."""
    hints_path = OUTPUT_DIR / "design" / "agent_test_hints.md"
    if not hints_path.exists():
        return ""
    try:
        content = hints_path.read_text(encoding="utf-8").strip()
        return content[:3000] if content else ""
    except Exception:
        return ""


def _write_sprint_blockers_report() -> Optional[Path]:
    """Persist all recorded sprint blockers to design/sprint_blockers.md.
    Returns the path written (or None if there were no blockers)."""
    blockers = _get_sprint_blockers()
    if not blockers:
        return None
    report_path = OUTPUT_DIR / "design" / "sprint_blockers.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    import datetime
    lines = [
        "# Sprint Blocker Report",
        f"_Generated: {datetime.datetime.utcnow().isoformat(timespec='seconds')}Z_",
        "",
        "These blockers were detected during the integration phase. They should be",
        "reviewed in the next sprint planning session / manager/CEO sync.",
        "",
    ]
    for i, b in enumerate(blockers, 1):
        lines += [
            f"## Blocker {i}: `{b.task_file}`",
            f"- **Agent**: {b.agent}",
            f"- **Timestamp**: {b.timestamp}",
            f"- **Waiting for**: {', '.join(b.waiting_for_files) or 'unknown'}",
            f"- **Description**: {b.blocker_description}",
            "",
        ]
    lines += [
        "---",
        f"_Total blockers this sprint: {len(blockers)}_",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"[SprintBlockers] wrote {len(blockers)} blocker(s) to {report_path}")
    return report_path


def _manager_fix_loop(
    code_dir: Path,
    task_queue: "EngTaskQueue",
    rolling_ctxs: Dict[str, "RollingContext"],
    max_rounds: int = MANAGER_FIX_MAX_ROUNDS,
) -> ManagerFixResult:
    """Run tests/build repeatedly; manager must boot the app and prove it responds.

    Success requires: (1) test gate + build green, (2) ``start_service()`` at least once,
    (3) for ``app_type=='web'``, at least one ``http_request()`` toward the running server,
    (4) for ``app_type=='gui'`` when ``MANAGER_GUI_DESKTOP_PROOF`` is true (default), a successful
    ``desktop_mouse``, ``desktop_keyboard``, or ``desktop_uia_click`` plus two ``desktop_screenshot()``
    calls; when ``MANAGER_GUI_DESKTOP_PROOF=0`` (headless/CI),
    ``start_service`` plus a green test gate is enough — no real desktop control required.
    """
    registry = get_contracts()
    _set_agent_ctx("eng_manager", _get_sprint_num())
    # ── Computer-use triplet tracker (replaces 4 separate booleans) ──────
    _cu = CUTripletTracker()
    manager_ran_start_service = False
    manager_ran_http_request = False
    last_error_block = ""
    build_cmd_hint = registry.build_command or ""
    app_type = registry.app_type or registry._infer_app_type()
    # Contract LLM commonly labels GUI apps (pygame, tkinter, etc.) as "cli".
    # Re-infer from actual code when app_type is "cli" to avoid sending --help to a blocking window.
    if app_type in ("cli", "script"):
        _re_inferred = registry._infer_app_type()
        if _re_inferred != app_type:
            logger.info(f"[ManagerFix] app_type upgraded {app_type!r} -> {_re_inferred!r} via code inspection")
            app_type = _re_inferred
    # Every app type with a visible interface requires desktop proof.
    # cli/library are exempt (they have no window to screenshot).
    _desktop_proof_required = (
        app_type in ("gui",) and MANAGER_GUI_DESKTOP_PROOF
    )
    # Every app type must produce functional proof:
    #   gui    → launch + screenshot triplet
    #   web    → launch + http_request
    #   cli    → run and produce non-empty meaningful output
    #   worker → launch + confirm process is running
    _functional_proof_required = app_type not in ("library",)
    logger.info(
        f"[ManagerFix] app_type={app_type!r}  "
        f"gui_desktop_proof_required={_desktop_proof_required}  "
        f"functional_proof_required={_functional_proof_required}  "
        f"computer_use_triplet_required={COMPUTER_USE_REQUIRE_TRIPLET}"
    )

    # All runnable app types need start_service or an explicit run
    _needs_start_service = app_type in ("web", "worker", "gui")

    # Load the team's test hints once at the start of the fix loop
    _agent_test_hints = _load_agent_test_hints()
    _hints_section = (
        f"\n\nAGENT TEST CHECKLIST (each item should say what the feature is, where to find it, "
        f"and how to test it — see design/agent_test_hints.md):\n"
        f"{_agent_test_hints}\n"
        if _agent_test_hints
        else ""
    )

    _gui_desktop_env_warn = ""
    if _desktop_proof_required:
        _has_pyautogui = True
        try:
            import pyautogui as _pa  # noqa: F401
        except ImportError:
            _has_pyautogui = False
        if not AGENT_DESKTOP_CONTROL_ENABLED or not _has_pyautogui:
            _gui_desktop_env_warn = (
                "\nGUI VERIFICATION PREREQUISITES (required or integration cannot pass):\n"
                "  - Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the environment (e.g. .env).\n"
                "  - Install pyautogui: pip install pyautogui\n"
                "  - Optional: DESKTOP_VISION_MODEL=<Gemini vision id> for sharper suggest_click; "
                "DESKTOP_SUGGEST_CLICK_REFINE=1 for a second crop pass (slower).\n"
                "  - Optional (Windows): pip install uiautomation for desktop_uia_list_elements / "
                "desktop_uia_read_text / desktop_uia_click (structured UI before pixel/vision).\n"
                "  - Only successful desktop_* tool results count: if a call returns a line starting "
                "with ERROR, fix the environment and call the tool again until it succeeds.\n"
            )
    elif app_type == "gui":
        _gui_desktop_env_warn = (
            "\nGUI HEADLESS MODE: MANAGER_GUI_DESKTOP_PROOF is off — integration passes with "
            "start_service() and a green test gate only. Desktop tools are optional.\n"
        )

    for round_num in range(1, max_rounds + 1):
        logger.info(f"[ManagerFix] round {round_num}/{max_rounds} — running verification…")

        errors = _manager_fix_collect_errors(code_dir, registry)
        if errors:
            last_error_block = "\n\n".join(errors)[-4000:]

        tests_build_ok = not errors
        # ── Triplet-aware GUI gate ──────────────────────────────────────
        if _desktop_proof_required:
            if COMPUTER_USE_REQUIRE_TRIPLET:
                _desktop_ok = _cu.has_at_least_one_triplet()
            else:
                # Legacy mode: any action + 2 screenshots
                _desktop_ok = _cu.actions >= 1 and _cu.screenshots >= 2
        else:
            _desktop_ok = True
        _web_ok = (app_type != "web") or manager_ran_http_request
        if tests_build_ok and manager_ran_start_service and _desktop_ok and _web_ok:
            logger.info(
                f"[ManagerFix] ALL GREEN + app verified after "
                f"{round_num - 1} manager round(s)"
            )
            return ManagerFixResult(
                passed=True,
                rounds_used=max(0, round_num - 1),
                final_output="All tests and build passed; manager ran mandatory app verification.",
                app_run_verified=True,
            )

        # Build file listing for the manager
        file_list: List[str] = []
        try:
            for p in sorted(code_dir.rglob("*")):
                if p.is_file() and not _is_ignored_project_path(p):
                    file_list.append(str(p.relative_to(code_dir)).replace("\\", "/"))
        except Exception:
            pass
        files_section = "\n".join(file_list[:200]) if file_list else "(unable to list files)"

        _gui_cumulative = ""
        if app_type == "gui":
            _cu_section = build_computer_use_loop_section(_cu, _desktop_proof_required)
            if _desktop_proof_required:
                _triplet_gate_note = (
                    "(triplet gate: COMPUTER_USE_REQUIRE_TRIPLET=1)"
                    if COMPUTER_USE_REQUIRE_TRIPLET
                    else "(legacy gate: 2 screenshots + 1 action required)"
                )
                _gui_cumulative = (
                    f"{_cu_section}"
                    f"  Gate mode: {_triplet_gate_note}\n"
                    f"  start_service recorded: {'yes' if manager_ran_start_service else 'no'}\n"
                    f"  Never use run_shell with `python main.py &` on Windows (times out); "
                    f"GUI runs via start_service / launch_application only.\n\n"
                )
            else:
                _gui_cumulative = (
                    f"── GUI verification (headless / test-gate mode) ──\n"
                    f"  MANAGER_GUI_DESKTOP_PROOF=0 — real desktop mouse/screenshots are NOT required.\n"
                    f"  start_service recorded: {'yes' if manager_ran_start_service else 'no'}\n"
                    f"  Requirement: call start_service with the GUI entry command; pytest must stay green.\n"
                    f"  Prefer automated tests that exercise widgets or a short-lived GUI smoke in-process.\n\n"
                )

        if errors:
            error_block = "\n\n".join(errors)[-4000:]
            logger.warning(f"[ManagerFix] round {round_num} errors:\n{error_block[:500]}")
            _gui_extra = (
                (
                    "GUI-SPECIFIC REQUIREMENT — OpenClaw-style UIA-first (applies even during error rounds):\n"
                    f"  {get_screen_dims_hint()}\n"
                    "  - desktop_list_windows() → desktop_activate_window('title') to restore focus.\n"
                    "  - STEP 1: desktop_screenshot() one baseline.\n"
                    "  - STEP 2 LOCATE (fast — no vision): desktop_uia_list_elements('Win Title') → exact names.\n"
                    "    Only fall back to desktop_suggest_click if UIA returns nothing.\n"
                    "  - STEP 3 ACT (accurate): desktop_uia_click('Win Title', 'Name') preferred;\n"
                    "    desktop_mouse/keyboard as pixel fallback.\n"
                    "  - STEP 4 VERIFY (fast): desktop_uia_read_text('Win Title') to confirm change;\n"
                    "    desktop_screenshot() only if UIA cannot read the result.\n"
                    "  - ERROR-prefixed tool returns do NOT satisfy the loop gate.\n"
                    if _desktop_proof_required
                    else (
                        "GUI-SPECIFIC (headless mode — fix tests first):\n"
                        "  - Fix failing pytest output above; use read_file / write_code_file.\n"
                        "  - start_service('gui', '<run command>') still records that the app boots.\n"
                        "  - Add or tighten tests that validate GUI logic without requiring desktop_* tools.\n"
                    )
                )
                if app_type == "gui" else ""
            )
            _web_extra = (
                "WEB-SPECIFIC REQUIREMENT (applies even during error rounds):\n"
                "  - After start_service(), call http_request('GET', ...) against a real URL on that server.\n"
                "  - Integration is not complete until at least one HTTP request succeeds.\n"
                if app_type == "web" else ""
            )
            prompt = (
                f"You are the Engineering Manager. The full codebase has been assembled by "
                f"your team, but verification is failing.\n\n"
                f"ERRORS (round {round_num}/{max_rounds}):\n"
                f"```\n{error_block}\n```\n\n"
                f"PROJECT FILES:\n{files_section}\n\n"
                f"TASK QUEUE STATUS:\n{task_queue.get_status()}\n\n"
                f"YOUR JOB: Diagnose and fix the errors.\n"
                f"  1. Use read_file() to inspect the relevant files.\n"
                f"  2. Use write_code_file() to fix the code.\n"
                f"  3. Use run_shell() to re-run specific commands if needed.\n"
                f"  3b. Use web_search() when the failure involves an unfamiliar stack or CLI you are guessing.\n"
                f"  4. Focus on the FIRST error — fixing it often resolves cascading failures.\n"
                f"NON-NEGOTIABLE: Before integration is complete you MUST run the real application "
                f"at least once (method depends on app_type='{app_type}' — see mandatory boot "
                f"instructions you will receive once tests are green).\n"
                f"{_gui_cumulative}"
                f"{_gui_extra}"
                f"{_web_extra}"
                f"{_gui_desktop_env_warn}"
                f"Do NOT just describe what to do — actually make the changes with tools.\n"
            )
        else:
            _verb = {
                "web": "WEB SERVER BOOT",
                "worker": "WORKER BOOT",
                "gui": "GUI LAUNCH",
                "cli": "CLI RUN",
                "script": "SCRIPT RUN",
                "library": "IMPORT CHECK",
            }.get(app_type, "APPLICATION RUN")
            logger.warning(
                f"[ManagerFix] round {round_num} — tests/build green but mandatory "
                f"{_verb} not done yet"
            )
            # Build app-type-specific instructions
            if _needs_start_service:
                _run_instructions = (
                    f"REQUIRED (use tools, not prose only):\n"
                    f"  1. list_files() / read_file() entry + manifest to find the run command.\n"
                    f"     web_search() if the framework's boot command is unclear.\n"
                    f"  2. start_service('app', '<run command>') — starts server in background.\n"
                    f"     If it returns 'CRASHED immediately', read the traceback and fix the file.\n"
                    f"  3. http_request('GET', 'http://localhost:<port>/health') — confirm response.\n"
                    f"  4. Verify EACH item in the test checklist with http_request().\n"
                    f"  5. stop_service('app') when done.\n"
                )
            elif app_type == "gui":
                if _desktop_proof_required:
                    _run_instructions = (
                        f"REQUIRED — OpenClaw-style UIA-first verification (use tools, not prose):\n"
                        f"  {get_screen_dims_hint()}\n"
                        f"  1. read_file() to identify the entry point and run command.\n"
                        f"  2. launch_application('<run command>') — opens the GUI window.\n"
                        f"  3. desktop_list_windows() then desktop_activate_window('title substring').\n"
                        f"  4. start_service('<name>', '<run command>') — records boot for the orchestrator.\n"
                        f"  --- COMPUTER-USE LOOP (OpenClaw: UIA first, vision as fallback) ---\n"
                        f"  5. OBSERVE:  desktop_screenshot() — one baseline screenshot.\n"
                        f"  6. LOCATE (fast path — no vision API call):\n"
                        f"       desktop_uia_list_elements('Window Title') → read exact control names.\n"
                        f"       Only if UIA returns nothing: desktop_suggest_click('<description>').\n"
                        f"  7. ACT (preferred — accurate, instant):\n"
                        f"       desktop_uia_click('Window Title', 'Control Name') — click by name.\n"
                        f"       Fallback: desktop_mouse('click', x, y) or desktop_keyboard().\n"
                        f"  8. VERIFY (fast path — no screenshot needed when UIA can read state):\n"
                        f"       desktop_uia_read_text('Window Title') — confirm label/field changed.\n"
                        f"       Fallback: desktop_screenshot() — only if UIA cannot read the result.\n"
                        f"  -------------------------------------------------------\n"
                        f"  Repeat steps 5-8 for each checklist item. One complete loop is the minimum.\n"
                        f"  FORBIDDEN as GUI proof: run_shell(tasklist), pip freeze, python -c tkinter only.\n"
                        f"  If the app is frozen or not responding: close_application(<pid>) then fix and re-launch.\n"
                    )
                else:
                    _run_instructions = (
                        f"REQUIRED (headless GUI mode — MANAGER_GUI_DESKTOP_PROOF=0):\n"
                        f"  1. read_file() to identify the entry point and run command.\n"
                        f"  2. start_service('gui', '<run command>') — records boot (same command as real GUI).\n"
                        f"  3. Rely on pytest: add tests under tests/ that import widgets, build windows off-screen, or\n"
                        f"     run short smokes; run_shell('pytest ...') if you need a one-off check.\n"
                        f"  4. Do NOT spend rounds on desktop_screenshot / desktop_mouse unless debugging locally.\n"
                        f"  5. launch_application() is optional here; focus on green test gate + start_service.\n"
                    )
            elif app_type in ("cli", "script"):
                _pl = (registry.primary_language or "").strip() or "python"
                _run_instructions = (
                    f"REQUIRED (use tools, not prose only):\n"
                    f"  Contract primary_language: {_pl!r} — use the real interpreter/build for this repo.\n"
                    f"  1. read_file() to find the entry point and expected arguments.\n"
                    f"  2. run_shell() a safe smoke (often --help or equivalent). If unsure of the CLI, web_search first.\n"
                    f"  3. run_shell() the real run command from the contract / README — exercise main functionality.\n"
                    f"     Exit code 0 = success. Any non-zero or traceback = failure to fix.\n"
                    f"  4. Verify EACH checklist item by running the CLI with relevant arguments.\n"
                    f"  NOTE: also call start_service('<name>', '<same run command>') so the orchestrator "
                    f"records that you ran it (short-lived exit is fine).\n"
                )
            else:  # library
                _pl = (registry.primary_language or "").strip() or "python"
                _run_instructions = (
                    f"REQUIRED (use tools, not prose only):\n"
                    f"  Contract primary_language: {_pl!r}.\n"
                    f"  1. run_shell() an import/compile check appropriate for this stack "
                    f"(read pyproject/Cargo.toml/go.mod/etc.; web_search if unsure).\n"
                    f"  2. run_shell() the project's test command from the repo (README, Makefile, CI).\n"
                    f"  3. Verify EACH checklist item is importable and callable.\n"
                    f"  NOTE: call start_service with a short exiting check command so the orchestrator "
                    f"records verification.\n"
                )

            _mgr_session_note = "You have NOT yet completed mandatory application verification in this manager session.\n\n"
            if app_type == "gui" and _desktop_proof_required and (
                manager_ran_start_service or _cu.screenshots > 0 or _cu.actions > 0
            ):
                _mgr_session_note = (
                    "Some verification tools already ran in a prior round — read the computer-use status block below. "
                    "Complete only what is missing (usually the ACT → VERIFY steps or a second screenshot after an action). "
                    "Do not repeat environment audit commands (pip freeze, tasklist, tkinter -c) — they do not satisfy the loop gate.\n\n"
                )
            elif app_type == "gui" and (not _desktop_proof_required) and manager_ran_start_service:
                _mgr_session_note = (
                    "start_service already ran — if the loop continues, focus on any remaining test failures or "
                    "contract checklist items; desktop tools are not required for pass in this mode.\n\n"
                )
            prompt = (
                f"You are the Engineering Manager — MANDATORY {_verb} "
                f"(round {round_num}/{max_rounds}).\n\n"
                f"app_type: {app_type!r} — use the appropriate verification method below.\n"
                f"Automated tests currently pass (or there is no failing gate).\n"
                f"{_gui_cumulative}"
                f"{_mgr_session_note}"
                f"Contract build_command hint: {build_cmd_hint!r}\n\n"
                f"{_run_instructions}"
                f"{_gui_desktop_env_warn}"
                f"{_hints_section}\n"
                f"PROJECT FILES:\n{files_section}\n\n"
                f"TASK QUEUE STATUS:\n{task_queue.get_status()}\n"
            )

        output, tool_results, _ = _run_with_tools_pkg(
            prompt, "eng_manager", f"mgr_fix_r{round_num}", retry_count=0
        )
        if _manager_saw_start_service(tool_results):
            manager_ran_start_service = True
        if _manager_saw_http_request(tool_results):
            manager_ran_http_request = True
        # Update computer-use triplet tracker
        _cu.update_from_tool_results(tool_results)
        logger.info(
            f"[ManagerFix] round {round_num} — manager used {len(tool_results)} tool calls, "
            f"output {len(output)}c, app_verified={manager_ran_start_service}, "
            f"http_verified={manager_ran_http_request}, "
            f"cu_triplets={_cu.completed_triplets}, cu_screenshots={_cu.screenshots}, cu_actions={_cu.actions}"
        )

        try:
            wt = GitWorktreeManager(code_dir, ["eng_manager"])
            wt.create_worktrees()
            wt.commit_agent("eng_manager")
            # merge_all() already takes _git_repo_lock internally.
            _mr = wt.merge_all()
            if _mr.failed_agents:
                logger.warning(f"[ManagerFix] merge failed for agents: {_mr.failed_agents}")
            wt.cleanup()
        except Exception as e:
            logger.warning(f"[ManagerFix] commit/merge after round {round_num} failed: {e}")

        try:
            get_rag().update()
        except Exception:
            pass

    # Exhausted rounds — final check
    errors = _manager_fix_collect_errors(code_dir, registry)
    tests_build_ok = not errors
    if errors:
        last_error_block = "\n\n".join(errors)[-4000:]
    # Triplet-aware final gate
    if _desktop_proof_required:
        if COMPUTER_USE_REQUIRE_TRIPLET:
            _desktop_ok = _cu.has_at_least_one_triplet()
        else:
            _desktop_ok = _cu.actions >= 1 and _cu.screenshots >= 2
    else:
        _desktop_ok = True
    _web_ok = (app_type != "web") or manager_ran_http_request
    if tests_build_ok and manager_ran_start_service and _desktop_ok and _web_ok:
        logger.info("[ManagerFix] green + start_service after final round")
        return ManagerFixResult(
            passed=True,
            rounds_used=max_rounds,
            final_output="Tests/build passed; manager invoked start_service.",
            app_run_verified=True,
        )
    if tests_build_ok and not manager_ran_start_service:
        msg = (
            f"Tests/build passed but the Engineering Manager never called start_service() "
            f"within {max_rounds} round(s). Integration requires booting the app at least once."
        )
        logger.warning(f"[ManagerFix] {msg}")
        return ManagerFixResult(
            passed=False,
            rounds_used=max_rounds,
            final_output=msg,
            app_run_verified=False,
        )
    if (
        tests_build_ok
        and manager_ran_start_service
        and app_type == "gui"
        and _desktop_proof_required
        and not _desktop_ok
    ):
        msg = (
            "Tests/build passed and start_service was used, but GUI verification is incomplete: "
            "the computer-use loop requires at least one complete observe\u2192act\u2192verify triplet. "
            "OpenClaw-style (fast): desktop_screenshot \u2192 desktop_uia_click \u2192 desktop_uia_read_text. "
            "Pixel fallback: desktop_screenshot \u2192 desktop_mouse / desktop_keyboard \u2192 desktop_screenshot. "
            f"Current counters: {_cu.status_line()}. "
            "If tools returned ERROR, set AGENT_DESKTOP_CONTROL_ENABLED=1, pip install pyautogui, and on Windows "
            "pip install uiautomation for desktop_uia_click / desktop_uia_read_text; then retry. "
            "For CI/headless runs only, set MANAGER_GUI_DESKTOP_PROOF=0 or COMPUTER_USE_REQUIRE_TRIPLET=0."
        )
        logger.warning(f"[ManagerFix] {msg}")
        return ManagerFixResult(
            passed=False,
            rounds_used=max_rounds,
            final_output=msg,
            app_run_verified=True,
        )
    if tests_build_ok and manager_ran_start_service and app_type == "web" and not _web_ok:
        msg = (
            "Tests/build passed and start_service was used, but web verification is incomplete: "
            "the manager must call http_request() at least once against the running server."
        )
        logger.warning(f"[ManagerFix] {msg}")
        return ManagerFixResult(
            passed=False,
            rounds_used=max_rounds,
            final_output=msg,
            app_run_verified=True,
        )
    logger.warning(f"[ManagerFix] FAILED after {max_rounds} rounds — returning last errors")
    return ManagerFixResult(
        passed=False,
        rounds_used=max_rounds,
        final_output=(
            f"Manager fix loop exhausted {max_rounds} rounds.\n"
            f"{last_error_block[:2000]}"
        ),
        app_run_verified=manager_ran_start_service,
    )


def run_sprint_retrospective(
    original_goal: str,
    prev_result: "TeamResult",
    sprint_num: int,
) -> str:
    """
    Manager agent reviews the current codebase after sprint_num and returns
    an enriched goal for sprint_num+1: bug fixes + missing features + improvements.
    Uses tools (list_files, read_file, run_shell, web_search) to inspect actual code.
    """
    from .agent_loop import _run_with_tools

    _set_agent_ctx("eng_manager", sprint_num)
    logger.info(f"\n{'='*56}\n  SPRINT {sprint_num} RETROSPECTIVE\n{'='*56}")

    prompt = (
        f"You are the Engineering Manager running a sprint {sprint_num} retrospective.\n\n"
        f"ORIGINAL GOAL:\n{original_goal[:600]}\n\n"
        f"SPRINT {sprint_num} SYNTHESIS:\n{prev_result.manager_synthesis[:800]}\n\n"
        f"YOUR JOB: Define the goal for sprint {sprint_num + 1}.\n\n"
        f"STEPS (use your tools):\n"
        f"  1. list_files() — see every file in the codebase.\n"
        f"  2. read_file() on key files — understand what was ACTUALLY implemented vs what was promised.\n"
        f"  3. run_shell('python -m py_compile <file>') — spot syntax errors in critical files.\n"
        f"  4. web_search() if you want to research better approaches or missing features.\n"
        f"  5. Identify ALL of:\n"
        f"       - Bugs and incomplete implementations from sprint {sprint_num}\n"
        f"       - Features from the original goal that are missing or broken\n"
        f"       - Quality/robustness improvements (error handling, edge cases)\n"
        f"       - New features that would meaningfully advance the project\n\n"
        f"OUTPUT FORMAT (required):\n"
        f"Write a detailed sprint {sprint_num + 1} goal. Be specific: name the exact files\n"
        f"to change, the exact bugs to fix, and the exact features to add or improve.\n"
        f"Do NOT just restate the original goal — describe what to BUILD ON top of what exists.\n\n"
        f"End your response with this exact marker followed by the goal text:\n"
        f"SPRINT {sprint_num + 1} GOAL:\n<detailed goal here>"
    )

    final_text, _, _ = _run_with_tools(
        prompt=prompt,
        role_key="eng_manager",
        label=f"retrospective_s{sprint_num}",
    )

    marker = f"SPRINT {sprint_num + 1} GOAL:"
    if marker in final_text:
        new_goal = final_text.split(marker, 1)[1].strip()
    else:
        new_goal = final_text.strip() or original_goal

    logger.info(f"[Retrospective] Sprint {sprint_num + 1} goal ({len(new_goal)}c): {new_goal[:120]}...")
    return new_goal


def run_engineering_team(
    task: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    sprint_num: int = 1,
) -> TeamResult:
    """
    Async task-completion engineering team.
    Agents self-claim tasks from a shared queue, work in isolated Git worktrees,
    merge on completion, and pull the next task. No fixed rounds.
    """
    from . import _monolith as _mono

    _mono._sync_public_config_from_package()
    n = len(ENG_WORKERS)
    logger.info(f"\n{'─'*55}\nTEAM: ENGINEERING ({n} devs, async mode)\n{'─'*55}")
    clear_sprint_files()   # reset file tracking for this sprint

    dev_assignments, pool, component_graph = run_sprint_planning(task, health_states, rolling_ctxs)
    emit_skeleton(dev_assignments, sprint_num)

    code_dir = OUTPUT_DIR / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    _skeleton_wt = GitWorktreeManager(code_dir, [])
    _skeleton_wt.init_repo()
    logger.info("[Engineering] git repo initialized with skeleton commit")

    # Index skeleton stubs NOW so list_files() returns real results when agents start.
    # Without this, the RAG index is empty at t=0 and agents enter a discovery loop.
    get_rag().update()
    logger.info(f"[Engineering] RAG pre-indexed {len(get_rag().chunks)} skeleton chunks")

    _setup_project(code_dir)

    task_queue = EngTaskQueue(get_contracts(), dev_assignments, pool, component_graph=component_graph)
    built: Dict[str, WorkerOutput] = {}
    _tasks_completed_by: Dict[str, int] = {d: 0 for d in ENG_WORKERS}
    _merge_lock = threading.Lock()
    _built_lock = threading.Lock()  # guards built + _tasks_completed_by

    # ── build_feature: adapted for task-based work ────────────────────────

    def build_feature(dev_key: str, eng_task: EngTask, retry_count: int = 0) -> WorkerOutput:
        _set_agent_ctx(dev_key, sprint_num)
        _set_task_file(eng_task.file)
        dashboard_status = get_dashboard().get_status()
        task_num = _tasks_completed_by[dev_key] + 1
        logger.info(f"[{dev_key}] ▶ Task START — {eng_task.file}: {eng_task.description[:60]}")

        completed_files = task_queue.get_completed_files()
        peer_context = ""
        if completed_files:
            previews = []
            for cf in completed_files[:6]:
                fpath = code_dir / cf
                if fpath.exists():
                    try:
                        src = fpath.read_text(encoding="utf-8")[:300]
                        previews.append(f"  {cf}:\n    {src[:200]}...")
                    except Exception:
                        pass
            if previews:
                peer_context = "\nCOMPLETED FILES IN CODEBASE (already merged):\n" + "\n".join(previews) + "\n"

        messages_section = ""
        try:
            pending = get_dashboard().peek_messages(dev_key)
            if pending:
                messages_section = f"\nMESSAGES FROM TEAMMATES (read carefully):\n{pending}\n"
        except Exception:
            pass

        if AGILE_MODE:
            integration_rules = (
                "\nAGILE COLLABORATION RULES (Targeted Communication):\n"
                "  - NO TRIVIAL BROADCASTS: Do NOT broadcast small progress updates.\n"
                "  - TARGETED MESSAGES: If you need something from a specific teammate, use message_teammate().\n"
                "  - BREAKING BROADCASTS: ONLY use broadcast_message() for team-wide structural changes\n"
                "    (e.g. changing an API port, a shared data model, or a global config constant).\n"
                "  - Use search_codebase() to find teammates' work without asking them for status updates.\n"
                "  - Dashboard contents are already injected into your prompt — no need to poll.\n"
            )
        else:
            integration_rules = (
                "\nINTEGRATION RULES:\n"
                "  - The entry point will be AUTO-GENERATED — do NOT create it yourself\n"
                "  - Your file MUST export exactly the symbols listed in your contract's 'exports'\n"
                "  - Import from files listed in your contract's 'imports_from'\n"
                "  - Do NOT invent new file names — use the exact paths from the contract\n"
            )

        is_integration_specialist = (eng_task.file == "__integration__")
        _contracts_for_task = get_contracts()
        build_cmd = _contracts_for_task.build_command
        _int_app_type = _contracts_for_task.app_type or _contracts_for_task._infer_app_type()

        if is_integration_specialist:
            build_errors = ""
            if build_cmd:
                _norm_build = _normalize_shell_command_for_windows(build_cmd)
                if _run_shell_blocks_gui_entrypoint(_norm_build):
                    build_errors = (
                        f"\nPRE-FLIGHT SKIPPED: build_command {build_cmd!r} would start a blocking GUI "
                        f"main loop — use pytest / --help / compile checks instead.\n"
                    )
                    logger.info(f"[{dev_key}] skipped pre-flight (blocking GUI build_command)")
                else:
                    try:
                        logger.info(f"[{dev_key}] running pre-flight '{build_cmd}' (timeout=30s)...")
                        result = subprocess.run(
                            build_cmd, shell=True, cwd=str(code_dir),
                            env=_subprocess_env_for_project(code_dir),
                            capture_output=True, text=True, timeout=30,
                            encoding="utf-8", errors="replace",
                        )
                        if result.returncode != 0:
                            build_errors = f"\nBUILD ERRORS (from running '{build_cmd}'):\n{(result.stdout or '')[-2000:]}\n{(result.stderr or '')[-2000:]}\n"
                        logger.info(f"[{dev_key}] pre-flight done (rc={result.returncode})")
                    except Exception as e:
                        build_errors = f"\nBUILD FAILED: {e}\n"
                        logger.info(f"[{dev_key}] pre-flight failed: {e}")

            _gui_integ = ""
            if _int_app_type == "gui":
                _gui_integ = (
                    "GUI PROJECT: Never use run_shell() to start the full app (main.py / run.py / Tk or Qt "
                    "main loop). That blocks until the window closes and will freeze or time out this agent.\n"
                    "Use run_shell only for commands that exit on their own: pytest, linters, "
                    "python -m py_compile, or python <entry> --help. The manager verifies the GUI via "
                    "start_service + tests; full desktop_mouse/screenshot proof runs only when "
                    "MANAGER_GUI_DESKTOP_PROOF is enabled (omit or set 0 in headless/CI).\n\n"
                )
            task_instruction = (
                f"INTEGRATION TEST — all code merged.\n"
                f"{build_errors}"
                f"{_gui_integ}"
                f"Verify with run_shell using only non-blocking commands (tests, --help, compile checks). "
                f"Contract build_command hint: {(build_cmd or 'none')!r} — if it would launch a long-running "
                f"GUI or server, do not run it via run_shell here; rely on tests and code fixes instead.\n"
                f"Use write_code_file (not write_config_file) for manifests like requirements.txt.\n"
            )
        else:
            _build_hint = (
                f"  3. Before completing, try running '{build_cmd}' using run_shell.\n"
                f"  4. If it fails because of something obvious, fix it. If it's a team-wide issue, broadcast it.\n"
            ) if build_cmd else (
                "  3. Verify your file is syntactically correct (e.g. validate_python if applicable).\n"
            )
            _leaf_note = (
                "\nSTART HERE: This is a leaf component — no project dependencies. "
                "Implement it fully on its own without importing from other project files.\n"
                if eng_task.depth == 0 and eng_task.component_id
                else ""
            )
            task_instruction = (
                f"TASK: Implement '{eng_task.file}'\n"
                f"{_leaf_note}"
                f"Description: {eng_task.description}\n\n"
                f"STEPS:\n"
                f"  1. list_files() and read_file() to see existing code from teammates\n"
                f"  2. write_code_file('{eng_task.file}', <YOUR COMPLETE CODE>)\n"
                f"     — Make sure imports match what your teammates exported\n"
                f"     — Follow the interfaces/contracts exactly\n"
                f"{_build_hint}"
                f"\nIMPORTANT: After you write your file, the system will automatically\n"
                f"verify that it integrates correctly (syntax, imports, tests). If your\n"
                f"code breaks something, you will be asked to fix it. Write carefully.\n"
            )


        # ── ComponentGraph context injection ──────────────────────────────
        component_graph_section = ""
        if eng_task.component_id and eng_task.component_graph_snapshot:
            try:
                from .task_decomposition import ComponentGraph as _CG
                _cg = _CG()
                _cg.sprint = eng_task.component_graph_snapshot.get("sprint", 1)
                _cg.goal = eng_task.component_graph_snapshot.get("goal", "")
                from .task_decomposition import Component as _Comp
                _cg.nodes = {
                    cid: _Comp.from_dict(cd)
                    for cid, cd in eng_task.component_graph_snapshot.get("nodes", {}).items()
                }
                _cg.topological_order = eng_task.component_graph_snapshot.get(
                    "topological_order", list(_cg.nodes.keys())
                )
                _this_comp = _cg.nodes.get(eng_task.component_id)
                if _this_comp:
                    _completed = task_queue.get_completed_files()
                    dep_lines = []
                    for dep_id in _this_comp.depends_on:
                        dep_comp = _cg.nodes.get(dep_id)
                        if dep_comp:
                            _done = dep_comp.file_path in _completed
                            dep_lines.append(
                                f"    [{dep_comp.name}] {dep_comp.file_path} "
                                f"{'[DONE]' if _done else '[PENDING]'}"
                            )
                    consumer_lines = [
                        f"    [{_cg.nodes[c].name}] {_cg.nodes[c].file_path}"
                        for c in _this_comp.consumers if c in _cg.nodes
                    ]
                    pi = _this_comp.public_interface
                    pi_classes = ", ".join(pi.get("classes", [])) or "none"
                    pi_fns = "\n      ".join(pi.get("functions", [])) or "none"
                    pi_consts = ", ".join(pi.get("constants", [])) or "none"
                    _position = (
                        "LEAF COMPONENT — no dependencies, implement from scratch independently."
                        if not _this_comp.depends_on
                        else f"INTERMEDIATE COMPONENT (depth={_this_comp.depth}) — your dependencies must be built before you."
                        if _this_comp.consumers
                        else f"ROOT COMPONENT (depth={_this_comp.depth}) — top of the graph; all other components serve you."
                    )
                    component_graph_section = (
                        f"\n╔══ COMPONENT GRAPH CONTEXT ═══════════════════════════╗\n"
                        f"║  {_position}\n"
                        f"║  Implementing: {_this_comp.name} ({_this_comp.file_path})\n"
                        + (f"  CONSUMERS (will call YOUR code):\n" + "\n".join(consumer_lines) + "\n" if consumer_lines else "  CONSUMERS: none — this is a leaf component\n")
                        + f"  YOUR DEPENDENCIES:\n"
                        + ("\n".join(dep_lines) + "\n" if dep_lines else "    None — implement independently.\n")
                        + f"  YOUR REQUIRED PUBLIC INTERFACE:\n"
                        + f"    Classes: {pi_classes}\n"
                        + f"    Functions:\n      {pi_fns}\n"
                        + f"    Constants: {pi_consts}\n"
                        + f"  FULL GRAPH:\n{_cg.format_ascii(max_lines=20)}\n"
                        + f"╚══════════════════════════════════════════════════════╝\n"
                    )
            except Exception as _cg_err:
                logger.warning(f"[{dev_key}] ComponentGraph injection failed: {_cg_err}")
        # ── End ComponentGraph context ─────────────────────────────────────

        team_files = _read_team_files()
        team_files_section = (
            f"\n\n─── TEAM SPECIFICATIONS (read before writing any code) ───\n{team_files}\n"
            f"────────────────────────────────────────────────────────\n"
        ) if team_files else ""

        contract_section = ""
        contract_text = get_contracts().get_contract_for_dev(dev_key)
        if contract_text:
            contract_section = f"\n{contract_text}\n"

        goal_anchor = ""
        if _current_sprint_goal:
            goal_anchor = (
                f"╔══════════════════════════════════════════════════════╗\n"
                f"║  SPRINT GOAL (your north star — never lose sight of this)\n"
                f"║  {_current_sprint_goal[:200]}\n"
                f"╚══════════════════════════════════════════════════════╝\n\n"
            )

        dod_checklist = _get_dod(dev_key)

        queue_status = task_queue.get_status()

        prompt = (
            f"You are dev_{dev_key.split('_')[1]}. "
            f"Your task: write file '{eng_task.file}'.\n\n"
            f"{task_instruction}\n\n"
            f"PROJECT: {task[:300]}\n\n"
        )
        # Add contract if available (concise)
        if contract_section:
            prompt += f"YOUR CONTRACT:{contract_section}\n"
        # Add component graph context (typed interface + dependency map)
        if component_graph_section:
            prompt += component_graph_section
        # Add peer context (what's already built)
        if peer_context:
            prompt += f"{peer_context}\n"
        # Add messages from teammates
        if messages_section:
            prompt += f"{messages_section}\n"
        # Long-term memory — lessons learned from past sprints (role-scoped)
        from .long_term_memory import get_role_memory as _get_role_memory
        _ltm = _get_role_memory(dev_key).query(eng_task.description, top_k=5)
        if _ltm:
            prompt += (
                "\n─── DOMAIN EXPERTISE FROM PAST SPRINTS ─────────────────────────\n"
                + _ltm +
                "\n─────────────────────────────────────────────────────────────────\n"
            )
        # Rolling context from previous tasks
        _rolling = rolling_ctxs[dev_key].get()
        if _rolling and len(_rolling.strip()) > 20:
            prompt += f"\nPREVIOUS WORK:\n{_rolling[:600]}\n"
        if retry_count > 0:
            # Inject existing file content so the model already has context
            # and doesn't need to call list_files / read_file (removing those
            # tools caused Gemini AFC to silently reject the unknown calls,
            # burning all 25 rounds with 0 Python invocations).
            _existing_content = ""
            _target_path = code_dir / eng_task.file
            if _target_path.exists():
                try:
                    _existing_content = _target_path.read_text(encoding="utf-8", errors="replace")[:2000]
                except Exception:
                    pass
            _file_context = (
                f"\nCURRENT FILE CONTENT ({eng_task.file}):\n```\n{_existing_content}\n```\n"
                if _existing_content
                else f"\n(File {eng_task.file} does not exist yet — create it from scratch.)\n"
            )
            prompt += (
                f"\n{'='*60}\n"
                f"RETRY {retry_count} — WRITE IS REQUIRED\n"
                f"{'='*60}\n"
                f"Your previous attempt did NOT call write_code_file.\n"
                f"All tools are still available — do NOT loop on list_files.\n"
                f"{_file_context}"
                f"ACTION REQUIRED: Call write_code_file('{eng_task.file}', <complete code>) NOW.\n"
                f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]\n"
            )
            logger.info(
                f"[{dev_key}] retry {retry_count} — full toolset kept, "
                f"injecting {'existing' if _existing_content else 'empty'} file content into prompt"
            )
        else:
            prompt += (
                f"\n─── THINKING PHASE (required before writing) ───────────────\n"
                f"Call think(thought) FIRST with your ARCHITECTURE ANALYSIS (4-8 sentences):\n"
                f"  a) Best design pattern / structure for '{eng_task.file}'\n"
                f"  b) What makes this code excellent — not just functional\n"
                f"  c) Integration risks with teammate code\n"
                f"  d) Quality improvements beyond the minimum spec\n"
                f"─────────────────────────────────────────────────────────────\n"
                f"THEN call write_code_file('{eng_task.file}', <complete code>).\n"
                f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
            )
        logger.info(f"[{dev_key}] prompt built ({len(prompt)}c) — handing off to ReAct agent")
        output, tool_results, perplexity = _run_with_tools_pkg(
            prompt, dev_key, f"{dev_key}_t{task_num}", retry_count=retry_count
        )
        sims    = perplexity_to_similarities(perplexity)
        F       = health_states[dev_key].update(sims)
        anomaly = health_states[dev_key].is_anomaly()
        logger.info(
            f"[{dev_key}] health update — perplexity={perplexity:.2f}  F_health={F:.3f}  "
            f"anomaly={'YES ⚠' if anomaly else 'no'}  tools_used={len(tool_results)}"
        )
        if anomaly and task_num == 1:
            logger.warning(f"[{dev_key}] ANOMALY F={F:.3f} — invoking fixer agent")
            health_states[dev_key].reset()
            output  = _run_fixer(dev_key, eng_task.description, output, F)
            sims    = perplexity_to_similarities(5.0)
            F       = health_states[dev_key].update(sims)
            anomaly = health_states[dev_key].is_anomaly()
        elif anomaly:
            logger.warning(f"[{dev_key}] ANOMALY F={F:.3f} — resetting health state")
            health_states[dev_key].reset()
        m      = re.search(r"STANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)", output, re.IGNORECASE)
        stance = m.group(1).lower() if m else "pragmatic"
        logger.info(
            f"[{dev_key}] ✔ Task DONE — {eng_task.file}  stance={stance.upper()}  "
            f"output={len(output)}c  F={F:.3f}"
        )
        rolling_ctxs[dev_key].add(eng_task.description, output)
        # Background lesson extraction — never blocks the pipeline
        threading.Thread(
            target=_get_role_memory(dev_key).extract_and_save,
            args=(eng_task.description, output, sprint_num, not anomaly),
            daemon=True,
        ).start()
        return WorkerOutput(
            role=dev_key, title=f"Software Developer — {eng_task.description[:40]}",
            round=task_num, output=output, tool_results=tool_results,
            stance=stance, stance_probs=extract_stance_probs(output).tolist(),
            F_health=F, anomaly=anomaly,
        )

    # ── Task-completion broadcast + test-hint writer ──────────────────────

    def _broadcast_task_completion(
        dev_key: str,
        eng_task: "EngTask",
        code_dir: Path,
        sprint_num: int,
        task_queue: "EngTaskQueue",
    ) -> None:
        """After a task completes:
        1. Broadcast a short 'what I implemented' message so teammates who were
           waiting on this file can retry their integration.
        2. Append a structured test-hint to design/agent_test_hints.md so the
           engineering manager has a concrete checklist to verify during the fix loop.
        """
        registry = get_contracts()
        file_entry = registry.file_map.get(eng_task.file, {})
        exports = file_entry.get("exports", []) if isinstance(file_entry, dict) else []

        # --- Structured hint: feature + where to find + how to test (manager checklist) ---
        hint_prompt = (
            f"You are {dev_key}. You just finished '{eng_task.file}'.\n"
            f"Task: {eng_task.description[:500]}\n"
            f"Exports: {exports}\n\n"
            "Write a short checklist block (max ~600 chars) the engineering manager can follow "
            "on the running application. Use exactly these three lines, no preamble:\n"
            "FEATURE: <what behavior or capability shipped>\n"
            "FIND: <how to locate it: window title, button label, URL path, menu, CLI command, etc.>\n"
            "TEST: <exact observable steps: HTTP method+path, clicks, keys, or pytest name>\n"
            "Use real strings from the task/code (titles, routes, flags). Do not invent product names."
        )
        try:
            hint_sentence = _llm(hint_prompt, label=f"{dev_key}_test_hint").strip()
            if len(hint_sentence) > 800:
                hint_sentence = hint_sentence[:797] + "..."
        except Exception:
            hint_sentence = (
                f"FEATURE: code in {eng_task.file}\n"
                f"FIND: run the app entry from the contract/README\n"
                f"TEST: exercise the behavior described in the task and confirm it matches."
            )

        # --- Append hint to design/agent_test_hints.md ---
        hints_path = OUTPUT_DIR / "design" / "agent_test_hints.md"
        hints_path.parent.mkdir(parents=True, exist_ok=True)
        with _sprint_blockers_lock:  # reuse a handy lock; the file is small
            with open(hints_path, "a", encoding="utf-8") as _hf:
                _hf.write(f"### [{dev_key}] `{eng_task.file}`\n{hint_sentence}\n\n")
        logger.info(f"[{dev_key}] test hint recorded: {hint_sentence[:100]}")

        # --- Broadcast to teammates so waiting agents are triggered ---
        completion_msg = (
            f"COMPLETED: {dev_key} finished '{eng_task.file}'. "
            f"Exports: {exports or '(see file)'}. "
            f"Test hint: {hint_sentence}"
        )
        try:
            get_dashboard().broadcast(dev_key, completion_msg, sprint_num, ENG_WORKERS)
        except Exception as e:
            logger.warning(f"[{dev_key}] completion broadcast failed (non-fatal): {e}")

        # --- Trigger waiting tasks that listed this file as a dependency ---
        _any_unblocked = False
        with task_queue._lock:
            for t in task_queue.tasks.values():
                if t.status == "waiting" and eng_task.file in (t.waiting_for or []):
                    t.waiting_for = [f for f in t.waiting_for if f != eng_task.file]
                    if not t.waiting_for:
                        t.status = "pending"
                        _any_unblocked = True
                        logger.info(
                            f"[TaskQueue] '{t.id}' unblocked from waiting — "
                            f"'{eng_task.file}' is now complete"
                        )
            if _any_unblocked:
                task_queue._persist()

    # ── Agent worker loop ─────────────────────────────────────────────────

    def _agent_worker_loop(dev_key: str) -> None:
        """Long-running worker: pull task → worktree → build → merge → repeat.
        Outer loop retries if a TeammateIdle hook fails (up to TEAMMATE_IDLE_MAX_RETRIES)."""
        _idle_retries = 0
        while True:  # outer idle-hook retry loop
            while task_queue.has_work_available():
                with _built_lock:
                    _agent_task_count = _tasks_completed_by[dev_key]
                if _agent_task_count >= MAX_TASKS_PER_AGENT:
                    logger.info(f"[{dev_key}] hit MAX_TASKS_PER_AGENT={MAX_TASKS_PER_AGENT} — stopping")
                    break

                eng_task = task_queue.claim_next(dev_key)
                if eng_task is None:
                    if task_queue.all_done():
                        break
                    import time as _time
                    _time.sleep(_AGENT_POLL_INTERVAL)
                    continue

                # ── TaskCreated hook: pre-task validator ──────────────────
                if TASK_CREATED_HOOKS:
                    _task_rejected = False
                    _hook_outputs: List[str] = []
                    _task_env = {
                        **_subprocess_env_for_project(code_dir),
                        "ENG_TASK_DESCRIPTION": eng_task.description,
                    }
                    for _hook_cmd in TASK_CREATED_HOOKS:
                        try:
                            _hook_proc = subprocess.run(
                                _hook_cmd, shell=True, capture_output=True, text=True,
                                timeout=30, cwd=str(code_dir), env=_task_env,
                                input=eng_task.description,
                                encoding="utf-8", errors="replace",
                            )
                            _hook_out = ((_hook_proc.stdout or "") + (_hook_proc.stderr or ""))[-1000:]
                            _hook_outputs.append(f"[task-hook: {_hook_cmd}]\n{_hook_out}")
                            if _hook_proc.returncode != 0:
                                _task_rejected = True
                                break
                        except Exception as _hook_e:
                            _hook_outputs.append(f"[task-hook: {_hook_cmd}] ERROR: {_hook_e}")
                            _task_rejected = True
                            break
                    if _task_rejected:
                        _rejection_msg = "\n".join(_hook_outputs)
                        logger.warning(
                            f"[{dev_key}] TASK REJECTED by pre-task hook: {eng_task.id}\n"
                            f"{_rejection_msg[:300]}"
                        )
                        task_queue.fail(eng_task.id)
                        continue
                # ─────────────────────────────────────────────────────────

                # Pre-generate build config before integration task starts
                if eng_task.file == "__integration__":
                    registry = get_contracts()
                    if registry.build_file:
                        _emit_build_scaffold_via_llm(registry, code_dir)

                wt = GitWorktreeManager(code_dir, [dev_key])
                try:
                    wt.create_worktrees()
                    _set_worktree_manager(wt)

                    _retries_before = task_queue.get_retries(eng_task.id)
                    result = build_feature(dev_key, eng_task, retry_count=_retries_before)
                    with _built_lock:
                        built[dev_key] = result

                    # If agent still produced no write tool call, requeue and retry
                    # with a narrowed toolset (write-only) on the next attempt.
                    if eng_task.file != "__integration__":
                        _wrote = any(
                            ("write_code_file" in tr) or ("write_file_section" in tr)
                            for tr in (result.tool_results or [])
                        )
                        if not _wrote:
                            retries_used = _retries_before
                            logger.warning(
                                f"[{dev_key}] no write tool call for '{eng_task.file}' "
                                f"(retry {retries_used + 1}/{MAX_RETRIES_PER_TASK}) — "
                                f"will inject file content into next prompt"
                            )
                            rolling_ctxs[dev_key].add(
                                f"FAILED: no write_code_file call for '{eng_task.file}'",
                                f"Your previous attempt did NOT call write_code_file() for '{eng_task.file}'. "
                                f"The task is automatically failed until you do. "
                                f"REQUIRED: Call write_code_file('{eng_task.file}', <full file content>) "
                                f"as your FIRST tool call this attempt. "
                                f"Do NOT use run_shell with printf/echo/cat — those are invisible to the "
                                f"project tracking system and will count as zero writes. "
                                f"write_code_file() is the ONLY tool that saves a file to the project."
                            )
                            task_queue.fail(eng_task.id)
                            continue

                    # ── Pre-merge self-verify baseline (for fault attribution) ──
                    _pre_merge_verify = None
                    if (
                        SELF_VERIFY_ENABLED
                        and eng_task.file != "__integration__"
                    ):
                        _pre_merge_verify = _run_self_verify(code_dir, eng_task)
                        logger.debug(
                            f"[{dev_key}] pre-merge verify for '{eng_task.file}': "
                            f"passed={_pre_merge_verify.passed}"
                        )

                    committed = wt.commit_agent(dev_key)
                    with _merge_lock:
                        merge_result = wt.merge_all()
                        if merge_result.resolutions:
                            logger.info(f"[{dev_key}] merge resolutions:\n" + "\n".join(merge_result.resolutions))
                        if dev_key in merge_result.failed_agents:
                            logger.error(
                                f"[{dev_key}] OWN BRANCH FAILED TO MERGE for '{eng_task.file}' — retrying"
                            )
                            task_queue.fail(eng_task.id)
                            continue

                    # Worktree content is now in main — clear in-memory worktree RAG.
                    _wt_rag = get_worktree_rag(dev_key)
                    if _wt_rag is not None:
                        _wt_rag.clear()

                    # ── Empty-output guard: if agent wrote nothing, retry ──
                    if not committed and eng_task.file != "__integration__":
                        target = code_dir / eng_task.file
                        file_missing = not target.exists()
                        file_is_stub = (
                            target.exists() and
                            target.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("# AUTO-GENERATED SKELETON")
                        )
                        if file_missing or file_is_stub:
                            retries_used = task_queue.get_retries(eng_task.id)
                            if retries_used < MAX_RETRIES_PER_TASK:
                                logger.warning(
                                    f"[{dev_key}] agent wrote nothing for '{eng_task.file}' "
                                    f"(retry {retries_used + 1}/{MAX_RETRIES_PER_TASK})"
                                )
                                rolling_ctxs[dev_key].add(
                                    f"EMPTY OUTPUT — {eng_task.file}",
                                    f"You were assigned '{eng_task.file}' but wrote nothing. "
                                    f"Use write_code_file to actually write the file content."
                                )
                                task_queue.fail(eng_task.id)
                                continue
                            else:
                                logger.warning(
                                    f"[{dev_key}] agent wrote nothing for '{eng_task.file}' "
                                    f"but retries exhausted — accepting to avoid deadlock"
                                )

                    # ── Self-verify after merge (per-file) ─────────────────
                    if (
                        SELF_VERIFY_ENABLED
                        and eng_task.file != "__integration__"
                        and _pre_merge_verify is not None
                    ):
                        sv = _run_self_verify_with_attribution(
                            code_dir, eng_task, _pre_merge_verify
                        )
                        if not sv.passed:
                            if sv.is_own_fault:
                                retries_used = task_queue.get_retries(eng_task.id)
                                if retries_used < MAX_RETRIES_PER_TASK:
                                    logger.warning(
                                        f"[{dev_key}] SELF-VERIFY FAILED (own fault) for "
                                        f"'{eng_task.file}' — retry {retries_used + 1}/"
                                        f"{MAX_RETRIES_PER_TASK}\n{sv.output[:500]}"
                                    )
                                    rolling_ctxs[dev_key].add(
                                        f"SELF-VERIFY FAILED — {eng_task.file}",
                                        f"Your code broke verification after merge.\n"
                                        f"Error output:\n{sv.output}\n\n"
                                        f"Fix the errors in '{eng_task.file}' using write_code_file."
                                    )
                                    task_queue.fail(eng_task.id)
                                    continue
                                else:
                                    logger.warning(
                                        f"[{dev_key}] SELF-VERIFY FAILED (own fault) but "
                                        f"retries exhausted — accepting '{eng_task.id}'"
                                    )
                            else:
                                # Not own fault — check if it looks like a missing dependency
                                if _looks_like_dependency_error(sv.output):
                                    # depends_on stores task IDs — find which are incomplete
                                    _incomplete_dep_ids = [
                                        dep_id for dep_id in eng_task.depends_on
                                        if dep_id not in task_queue._completed_tasks
                                    ]
                                    # Convert task IDs → file paths for waiting_for
                                    _incomplete_files = [
                                        task_queue.tasks[dep_id].file
                                        for dep_id in _incomplete_dep_ids
                                        if dep_id in task_queue.tasks
                                    ]
                                    if not _incomplete_files:
                                        # No unresolved teammate deps — likely env/setup issue, not
                                        # teammate-integration readiness. Complete with warning.
                                        logger.info(
                                            f"[{dev_key}] dependency-like verify error for '{eng_task.file}' "
                                            f"but no unresolved file dependencies were found; "
                                            f"completing with warning instead of WAIT"
                                        )
                                        rolling_ctxs[dev_key].add(
                                            f"VERIFY WARNING — {eng_task.file}",
                                            f"Verification looked dependency-related, but no pending "
                                            f"teammate file dependency was detected.\n"
                                            f"Error output:\n{sv.output[:500]}"
                                        )
                                        # Fall through to task completion below
                                    elif task_queue.get_retries(eng_task.id) < MAX_RETRIES_PER_TASK:
                                        logger.info(
                                            f"[{dev_key}] SELF-VERIFY FAILED (dependency not ready) for "
                                            f"'{eng_task.file}' — entering WAIT for: {_incomplete_files}"
                                        )
                                        rolling_ctxs[dev_key].add(
                                            f"WAITING — {eng_task.file}",
                                            f"Verification failed because a dependency is not yet ready.\n"
                                            f"Error:\n{sv.output[:400]}\n\n"
                                            f"Waiting for: {_incomplete_files}\n"
                                            f"You will be automatically re-activated when those files complete."
                                        )
                                        task_queue.set_waiting(eng_task.id, _incomplete_files)
                                        # Sleep until a teammate wakes us (check every poll interval)
                                        import time as _wait_time
                                        _wait_deadline = _wait_time.time() + MAX_WALL_CLOCK
                                        while task_queue.tasks[eng_task.id].status == "waiting":
                                            if _wait_time.time() > _wait_deadline:
                                                logger.warning(
                                                    f"[{dev_key}] wait-deadline exceeded for "
                                                    f"'{eng_task.id}' — giving up"
                                                )
                                                task_queue.fail(eng_task.id)
                                                break
                                            _wait_time.sleep(_AGENT_POLL_INTERVAL * 3)
                                        # After wake-up, loop back to retry the task
                                        if task_queue.tasks[eng_task.id].status == "pending":
                                            logger.info(
                                                f"[{dev_key}] woken from wait for '{eng_task.id}' — retrying"
                                            )
                                            task_queue.requeue_after_wait(eng_task.id)
                                        continue
                                    else:
                                        logger.warning(
                                            f"[{dev_key}] SELF-VERIFY FAILED (dependency) but "
                                            f"retries exhausted — accepting '{eng_task.id}'"
                                        )
                                else:
                                    logger.info(
                                        f"[{dev_key}] SELF-VERIFY FAILED (pre-existing) for "
                                        f"'{eng_task.file}' — completing with warning"
                                    )

                    # ── Sync config/ → code/ ──────────────────────────────
                    if eng_task.file == "__integration__":
                        config_dir = OUTPUT_DIR / "config"
                        if config_dir.exists():
                            for cf in config_dir.iterdir():
                                if cf.is_file():
                                    dest = code_dir / cf.name
                                    dest_is_stub = dest.exists() and dest.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("#")
                                    if not dest.exists() or dest_is_stub:
                                        _shutil.copy2(str(cf), str(dest))
                                        logger.info(f"[{dev_key}] synced config/{cf.name} → code/{cf.name}")

                    # ── Pre-gate: install deps if needed ──────────────────
                    if eng_task.file == "__integration__":
                        _install_cmd = get_contracts().install_command
                        _build_file_path = code_dir / (get_contracts().build_file or "")
                        if _install_cmd and _build_file_path.exists():
                            logger.info(f"[{dev_key}] running '{_install_cmd}' before test gate...")
                            try:
                                subprocess.run(
                                    _install_cmd, shell=True, cwd=str(code_dir),
                                    env=_subprocess_env_for_project(code_dir),
                                    capture_output=True, text=True, timeout=180,
                                    encoding="utf-8", errors="replace",
                                )
                            except Exception as e:
                                logger.warning(f"[{dev_key}] '{_install_cmd}' failed: {e}")

                    # ── Complete the task ──────────────────────────────────
                    task_queue.complete(eng_task.id)
                    with _built_lock:
                        _tasks_completed_by[dev_key] += 1
                    # ─────────────────────────────────────────────────────

                    # ── Broadcast completion + write test hint ─────────────
                    if eng_task.file != "__integration__":
                        _broadcast_task_completion(
                            dev_key, eng_task, code_dir, sprint_num, task_queue
                        )
                    # ─────────────────────────────────────────────────────

                    try:
                        get_rag().update()
                    except Exception as e:
                        logger.warning(f"[{dev_key}] incremental RAG update failed: {e}")

                except Exception as exc:
                    # Detect interpreter shutdown — don't requeue, just abort cleanly.
                    _is_shutdown = (
                        isinstance(exc, RuntimeError)
                        and "interpreter shutdown" in str(exc)
                    ) or isinstance(exc, (KeyboardInterrupt, SystemExit))
                    if _is_shutdown:
                        logger.warning(f"[{dev_key}] interpreter shutting down — aborting task loop")
                        return
                    logger.error(f"[{dev_key}] task {eng_task.id} crashed: {exc}", exc_info=True)
                    task_queue.fail(eng_task.id)
                    with _built_lock:
                        built[dev_key] = WorkerOutput(
                            role=dev_key, title=f"Software Developer (error)",
                            round=_tasks_completed_by[dev_key] + 1,
                            output=f"[task crashed: {exc}]",
                            tool_results=[], stance="pragmatic",
                            stance_probs=[0.1, 0.1, 0.1, 0.7],
                            F_health=9.9, anomaly=True,
                        )
                finally:
                    wt.cleanup()
                    _set_worktree_manager(None)

                ActiveInferenceState.interfere_all(
                    [health_states[d] for d in ENG_WORKERS], alpha=INTERFERENCE_ALPHA
                )

            # ── TeammateIdle hook with retry loop ─────────────────────────
            if not TEAMMATE_IDLE_HOOKS or _idle_retries >= TEAMMATE_IDLE_MAX_RETRIES:
                break  # no hooks configured, or retries exhausted — agent done
            _idle_outputs: List[str] = []
            _idle_all_passed = True
            for _idle_cmd in TEAMMATE_IDLE_HOOKS:
                try:
                    _idle_proc = subprocess.run(
                        _idle_cmd, shell=True, capture_output=True, text=True,
                        timeout=60, cwd=str(code_dir),
                        env=_subprocess_env_for_project(code_dir),
                        encoding="utf-8", errors="replace",
                    )
                    _idle_out = ((_idle_proc.stdout or "") + (_idle_proc.stderr or ""))[-2000:]
                    _idle_outputs.append(f"[idle-hook: {_idle_cmd}]\n{_idle_out}")
                    if _idle_proc.returncode != 0:
                        _idle_all_passed = False
                        break
                except Exception as _idle_e:
                    _idle_outputs.append(f"[idle-hook: {_idle_cmd}] ERROR: {_idle_e}")
                    _idle_all_passed = False
                    break
            _idle_combined = "\n".join(_idle_outputs)
            if _idle_all_passed:
                logger.info(f"[{dev_key}] TEAMMATE IDLE HOOK passed — agent done")
                break  # exit outer loop cleanly
            _idle_retries += 1
            logger.warning(
                f"[{dev_key}] TEAMMATE IDLE HOOK FAILED "
                f"(retry {_idle_retries}/{TEAMMATE_IDLE_MAX_RETRIES}) — re-activating agent\n"
                f"{_idle_combined[:300]}"
            )
            rolling_ctxs[dev_key].add(
                f"TEAMMATE IDLE HOOK FAILED (attempt {_idle_retries})", _idle_combined
            )
            # continues outer while True → agent re-enters task loop
            # ─────────────────────────────────────────────────────────────

    # ── Manager monitor ───────────────────────────────────────────────────

    def _manager_monitor() -> None:
        """Periodic progress check — logs status and intervenes if swarm health is elevated."""
        import time as _time
        check_interval = 15
        _phase_1_synced = False
        while task_queue.has_work_available():
            _time.sleep(check_interval)
            
            # ── Sync Step (Between Phase 1 and Phase 2) ──────────────────
            phase_1_done = all(
                t.status in ("completed", "failed")
                for t in task_queue.tasks.values() if t.phase == PHASE_IMPLEMENTATION
            )
            if phase_1_done and not _phase_1_synced:
                logger.info("\n[Manager Monitor] PHASE 1 COMPLETE — Synchronizing codebase for Phase 2 Integration...")
                # Always unblock Phase 2 tasks — even if RAG fails
                try:
                    with task_queue._lock:
                        task_queue._unblock_dependents()
                    _phase_1_synced = True
                    logger.info("[Manager Monitor] PHASE 2 (Integration) RELEASED.\n")
                except Exception as e:
                    logger.error(f"[Manager Monitor] Failed to unblock Phase 2 tasks: {e}")
                    _phase_1_synced = True  # don't retry — avoid infinite loop
                # Re-index the RAG separately so integrators can 'see' all Phase 1 code
                try:
                    get_rag().update()
                    logger.info("[Manager Monitor] codebase indexed for Phase 2.\n")
                except Exception as e:
                    logger.warning(f"[Manager Monitor] RAG sync failed (non-fatal): {e}")

            if task_queue.all_done():
                break

            # ── Deadlock detection ────────────────────────────────────────
            if task_queue.is_deadlocked():
                with task_queue._lock:
                    _stalled = [t for t in task_queue.tasks.values()
                                if t.status in ("blocked", "waiting")]
                logger.critical(
                    f"[Manager Monitor] DEADLOCK DETECTED — "
                    f"{len(_stalled)} remaining tasks are stalled (blocked/waiting)"
                )
                for _wt in _stalled:
                    blocker = SprintBlocker(
                        agent=_wt.assigned_to or "unknown",
                        task_file=_wt.file,
                        blocker_description=(
                            f"Deadlock: task '{_wt.file}' is {_wt.status}"
                            + (f" for {_wt.waiting_for}" if _wt.waiting_for else "")
                            + ". No other agent is making progress."
                        ),
                        waiting_for_files=list(_wt.waiting_for),
                    )
                    _record_sprint_blocker(blocker)
                    if _wt.assigned_to:
                        get_dashboard().send_message(
                            "eng_manager", _wt.assigned_to,
                            f"DEADLOCK DETECTED: your task '{_wt.file}' is {_wt.status} "
                            f"and no progress is being made. "
                            f"This has been recorded as a sprint blocker for the next planning session.",
                            sprint_num,
                        )
                with task_queue._lock:
                    for _wt in _stalled:
                        _wt.status = "failed"
                        task_queue._completed_tasks.add(_wt.id)
                    task_queue._persist()
                break  # deadlock — stop monitoring

            H_swarm = sum(health_states[d].free_energy() for d in ENG_WORKERS)
            stable_threshold = 1.5 * n
            status = task_queue.get_status()
            logger.info(
                f"\n[Manager Monitor] H_swarm={H_swarm:.3f}  "
                f"({'stable' if H_swarm < stable_threshold else 'ELEVATED ⚠'})\n{status}"
            )

            if H_swarm > stable_threshold * 1.5:
                failed_tasks = [t for t in task_queue.tasks.values() if t.status == "failed"]
                if failed_tasks:
                    logger.warning(
                        f"[Manager Monitor] swarm health critical — "
                        f"{len(failed_tasks)} failed tasks, sending guidance"
                    )
                    for ft in failed_tasks:
                        if ft.assigned_to:
                            if AGILE_MODE:
                                msg = (
                                    f"Task '{ft.file}' failed. In AGILE MODE, you must negotiate interfaces. "
                                    f"Have you broadcasted your changes? Did you read your teammates' files? "
                                    f"Communicate more and retry."
                                )
                            else:
                                msg = (
                                    f"Task '{ft.file}' failed. Check imports and dependencies. "
                                    f"Read the architecture spec before retrying."
                                )
                            get_dashboard().send_message("eng_manager", ft.assigned_to, msg, sprint_num)

            # ── Check token budget kill-switch ───────────────────────────
            with _token_lock:
                current_tokens_used = _tokens_in + _tokens_out
            if current_tokens_used > TOKEN_BUDGET:
                logger.critical(f"[Manager Monitor] KILL SWITCH TRIPPED: {current_tokens_used:,} tokens > {TOKEN_BUDGET:,} budget")
                task_queue.cancel_all()
                break

            # ── Process pending amendments ───────────────────────────────
            amendment_broadcasts = _registry_process_amendments(sprint_num)
            for msg in amendment_broadcasts:
                get_dashboard().broadcast("eng_manager", msg, sprint_num, ENG_WORKERS)

    # ── Launch all agents + monitor ───────────────────────────────────────

    import time as _eng_time
    start_time = _eng_time.time()

    with ThreadPoolExecutor(max_workers=n + 1) as ex:
        agent_futures = {
            ex.submit(_agent_worker_loop, dev): dev for dev in ENG_WORKERS
        }
        monitor_future = ex.submit(_manager_monitor)

        while not task_queue.all_done():
            elapsed = _eng_time.time() - start_time
            if elapsed > MAX_WALL_CLOCK:
                logger.warning(
                    f"[Engineering] hit MAX_WALL_CLOCK={MAX_WALL_CLOCK}s — "
                    f"forcing completion after {elapsed:.0f}s"
                )
                task_queue.force_fail_remaining()
                break
            all_agents_exited = all(f.done() for f in agent_futures)
            if all_agents_exited and not task_queue.all_done():
                logger.warning("[Engineering] all agents exited but tasks remain — forcing completion")
                task_queue.force_fail_remaining()
                break
            _eng_time.sleep(3)

        try:
            for fut in as_completed(list(agent_futures.keys()), timeout=60):
                dev = agent_futures.get(fut, "unknown")
                try:
                    fut.result()
                except Exception as exc:
                    logger.error(f"[{dev}] worker loop error: {exc}", exc_info=True)
        except TimeoutError:
            logger.warning("[Engineering] timeout waiting for agent threads to finish")

    elapsed = _eng_time.time() - start_time
    logger.info(f"\n[Engineering] async phase completed in {elapsed:.1f}s")
    logger.info(f"[Engineering] final queue status:\n{task_queue.get_status()}")

    # ── Final enforcement + build ─────────────────────────────────────────
    final_enforce = enforce_integration()
    if final_enforce:
        logger.info(f"\n[FINAL ENFORCEMENT]\n{final_enforce}")

    # ── Manager fix-until-green loop ──────────────────────────────────────
    fix_result = _manager_fix_loop(code_dir, task_queue, rolling_ctxs)
    if fix_result.passed:
        logger.info(
            f"[Engineering] Manager fix loop PASSED in {fix_result.rounds_used} round(s) "
            f"(app_run_verified={fix_result.app_run_verified})"
        )
    else:
        logger.warning(
            f"[Engineering] Manager fix loop FAILED after {fix_result.rounds_used} rounds\n"
            f"{fix_result.final_output[:500]}"
        )

    # ── Persist sprint blockers report ────────────────────────────────────
    _blockers_report_path = _write_sprint_blockers_report()
    if _blockers_report_path:
        logger.warning(
            f"[Engineering] {len(_get_sprint_blockers())} sprint blocker(s) recorded — "
            f"see {_blockers_report_path} for next sprint planning"
        )
    _clear_sprint_blockers()  # reset for potential next sprint

    # ── Health + consensus ────────────────────────────────────────────────
    ActiveInferenceState.interfere_all(
        [health_states[d] for d in ENG_WORKERS], alpha=INTERFERENCE_ALPHA
    )
    H_swarm     = sum(health_states[d].free_energy() for d in ENG_WORKERS)
    mean_stance = np.mean([
        np.array(built[d].stance_probs) for d in ENG_WORKERS if d in built
    ] or [np.array([0.25, 0.25, 0.25, 0.25])], axis=0)
    consensus   = STANCES[int(mean_stance.argmax())]

    # ── Dev summary table ─────────────────────────────────────────────────
    logger.info(f"\n  ── Final dev summary ──────────────────────────")
    logger.info(f"  {'Dev':<10} {'Tasks':>6} {'F_health':>10}  {'Anomaly':>8}  {'Stance':<12}")
    logger.info(f"  {'─'*56}")
    for _dev in ENG_WORKERS:
        if _dev in built:
            _w = built[_dev]
            logger.info(
                f"  {_dev:<10} {_tasks_completed_by[_dev]:>6} {_w.F_health:>10.3f}  "
                f"{'⚠ YES' if _w.anomaly else 'no':>8}  {_w.stance.upper():<12}"
            )
        else:
            logger.info(f"  {_dev:<10} {_tasks_completed_by[_dev]:>6}      —         —  —")

    # ── Final manager synthesis ───────────────────────────────────────────
    feature_summaries = "\n\n".join(
        f"=== Dev {dev.split('_')[1]} — {dev_assignments[dev]} "
        f"(tasks: {_tasks_completed_by[dev]}) ===\n{built[dev].output[:700]}"
        for dev in ENG_WORKERS if dev in built
    )
    _fix_status = (
        f"Manager fix loop: PASSED in {fix_result.rounds_used} round(s); "
        f"app boot via start_service verified={fix_result.app_run_verified}"
        if fix_result.passed
        else (
            f"Manager fix loop: FAILED after {fix_result.rounds_used} rounds; "
            f"app_run_verified={fix_result.app_run_verified}\n"
            f"{fix_result.final_output[:300]}"
        )
    )
    synthesis = _llm(
        f"You are the {ROLES['eng_manager']['title']}.\n\n"
        f"Your team completed tasks asynchronously ({elapsed:.0f}s elapsed).\n\n"
        f"TASK QUEUE FINAL STATUS:\n{task_queue.get_status()}\n\n"
        f"MANAGER FIX LOOP:\n{_fix_status}\n\n"
        f"FINAL OUTPUTS:\n{feature_summaries}\n\n"
        f"H_swarm={H_swarm:.3f}\n\n"
        f"Synthesize into a single coherent implementation guide:\n"
        f"1. How the features connect and integrate\n"
        f"2. Shared dependencies and interfaces\n"
        f"3. Any remaining gaps or failed tasks\n"
        f"4. Final runnable project structure and start command",
        label="eng_manager_synthesis",
        system=_manager_system("eng_manager"),
    )
    rolling_ctxs["eng_manager"].add(task, synthesis)

    return TeamResult(
        team="Engineering",
        manager_synthesis=synthesis,
        worker_outputs=[built[d] for d in ENG_WORKERS if d in built],
        H_swarm=H_swarm,
        consensus_stance=consensus,
        confidence=max(0.0, 1.0 - H_swarm / (1.5 * n)),
    )



