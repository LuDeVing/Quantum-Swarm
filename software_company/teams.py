"""Multi-round team execution (`run_team`)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import numpy as np
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

from .config import MAX_TEAM_ROUNDS, OUTPUT_DIR, STANCES
from .dashboard import get_dashboard
from .rolling_context import RollingContext
from .stance import consistency_weight, extract_stance_probs, interfere_weighted
from .team_schemas import TeamResult, WorkerOutput
from .roles import ROLES
from .prompts_loaded import _manager_system

from .planning import run_team_planning
from .workers import run_worker

logger = logging.getLogger("company")


def _llm(*args, **kwargs):
    import software_company as sc

    return sc.llm_call(*args, **kwargs)


# ── Team execution ────────────────────────────────────────────────────────────

def run_team(
    team_name: str,
    manager_role: str,
    worker_roles: List[str],
    task: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    sprint_num: int = 1,
) -> TeamResult:
    logger.info(f"\n{'─'*55}\nTEAM: {team_name.upper()}\n{'─'*55}")

    # ── Team planning: manager + workers decide who does what ─────────────
    worker_tasks, _ = run_team_planning(
        team_name, manager_role, worker_roles, task, rolling_ctxs, health_states
    )

    def make_worker_task(role: str) -> str:
        return (
            f"PROJECT BRIEF:\n{task}\n\n"
            f"YOUR SPECIFIC ASSIGNMENT:\n{worker_tasks[role]}\n\n"
            f"What your teammates are working on:\n"
            + "\n".join(
                f"  {r}: {worker_tasks[r]}" for r in worker_roles if r != role
            )
        )

    # ── Iterative rounds with manager review after each ───────────────────
    current: Dict[str, WorkerOutput] = {}
    manager_feedback: str = ""
    round_num = 1

    while round_num <= MAX_TEAM_ROUNDS:
        logger.info(f"\n{'─'*55}\n{team_name} Round {round_num}/{MAX_TEAM_ROUNDS}\n{'─'*55}")

        all_tool_results = [res for r in worker_roles for res in current[r].tool_results] if current else []

        def run_one(role: str, rnd: int = round_num, feedback: str = manager_feedback) -> WorkerOutput:
            # Peer outputs = everyone else's last output + manager feedback appended
            peers = [current[o].output for o in worker_roles if o != role] if current else []
            if feedback:
                peers = peers + [f"[MANAGER] {feedback}"]
            return run_worker(
                role, make_worker_task(role),
                peers, all_tool_results,
                health_states[role], rolling_ctxs[role], rnd, sprint_num,
            )

        with ThreadPoolExecutor(max_workers=len(worker_roles)) as ex:
            futures = {ex.submit(run_one, role): role for role in worker_roles}
            for fut in as_completed(futures):
                role = futures[fut]
                try:
                    current[role] = fut.result()
                except Exception as exc:
                    logger.error(f"[{role}] worker crashed: {exc}", exc_info=True)
                    current[role] = WorkerOutput(
                        role=role, title=ROLES.get(role, {}).get("title", role),
                        round=round_num, output=f"[worker crashed: {exc}]",
                        tool_results=[], stance="pragmatic",
                        stance_probs=[0.1, 0.1, 0.1, 0.7],
                        F_health=9.9, anomaly=True,
                    )

        # ── Health + stance interference ──────────────────────────────────
        ActiveInferenceState.interfere_all(
            [health_states[r] for r in worker_roles], alpha=INTERFERENCE_ALPHA
        )
        stance_probs = [np.array(current[r].stance_probs) for r in worker_roles]
        weights      = np.array([consistency_weight(current[r].output) for r in worker_roles])
        weights      = weights / (weights.sum() + 1e-10)
        updated      = interfere_weighted(stance_probs, weights.tolist(), alpha=INTERFERENCE_ALPHA)
        for i, role in enumerate(worker_roles):
            current[role].stance_probs = updated[i].tolist()

        # Use post-interference free energy (not stale WorkerOutput values)
        H_swarm     = sum(health_states[r].free_energy() for r in worker_roles)
        n_workers   = len(worker_roles)
        stable_thr  = 1.5 * n_workers
        mean_stance = np.mean([np.array(current[r].stance_probs) for r in worker_roles], axis=0)
        consensus   = STANCES[int(mean_stance.argmax())]
        logger.info(
            f"{team_name} R{round_num}: H_swarm={H_swarm:.3f}  consensus={consensus.upper()}  "
            f"({'stable' if H_swarm < stable_thr else 'ELEVATED ⚠'})"
        )

        # ── Manager reviews round, decides CONTINUE or DONE ───────────────
        summaries = "\n\n".join(
            f"=== {current[r].title} (F={current[r].F_health:.3f}{'⚠' if current[r].anomaly else ''}) ===\n"
            f"{current[r].output[:600]}"
            for r in worker_roles
        )
        team_specific_review = ""
        if team_name == "Architecture":
            team_specific_review = (
                "4. Does the spec include dependency waves (Wave 0 / Wave 1 / Wave 2)?\n"
                "5. Does every file have an explicit depends_on list?\n"
                "6. Are build_command, build_file, and dependencies specified?\n"
                "   (Engineering CANNOT dispatch agents without waves and depends_on)\n"
            )
        elif team_name == "QA":
            team_specific_review = (
                "4. Did testers run the build_command first before testing?\n"
                "5. Were tests executed in wave order (foundation → core → UI)?\n"
                "6. Is the GO/NO-GO backed by actual test output, not claims?\n"
            )
        elif team_name == "Design":
            team_specific_review = (
                "4. Do component names match what Engineering uses in their file names?\n"
                "5. Did designers check the dashboard for Engineering's claimed domains?\n"
            )

        manager_review = _llm(
            f"You are the {ROLES[manager_role]['title']}.\n\n"
            f"TASK: {task[:300]}\n\n"
            f"ROUND {round_num} TEAM OUTPUTS:\n{summaries}\n\n"
            f"H_swarm={H_swarm:.3f}\n\n"
            f"Review what the team produced this round:\n"
            f"1. Are there conflicts or overlaps between team members' work?\n"
            f"2. Are there gaps — things nobody addressed?\n"
            f"3. Is the work coherent and integrated as a whole?\n"
            f"{team_specific_review}\n"
            f"If the team's output is complete and coherent: respond with DECISION: DONE\n"
            f"Otherwise: respond with DECISION: CONTINUE\n"
            f"Then give specific, numbered feedback for each team member on what to fix or improve next round.",
            label=f"{manager_role}_r{round_num}_review",
            system=_manager_system(manager_role),
        )
        rolling_ctxs[manager_role].add(task, manager_review)
        logger.info(f"[{manager_role}] Round {round_num} review: {manager_review[:120]}...")

        if "DECISION: DONE" in manager_review or round_num >= MAX_TEAM_ROUNDS:
            if round_num >= MAX_TEAM_ROUNDS:
                logger.warning(f"[{team_name}] hit MAX_TEAM_ROUNDS={MAX_TEAM_ROUNDS} — stopping")
            break

        manager_feedback = manager_review
        round_num += 1

    # ── Integration pass (Engineering team only) ─────────────────────────
    # Manager reads the actual written files, boots the app, patches broken glue.
    if team_name == "Engineering":
        logger.info(f"\n{'─'*55}\n{team_name} INTEGRATION PASS — manager fixing glue code\n{'─'*55}")
        sprint_files = get_sprint_files()

        # Find existing files that import from or are imported by sprint files
        # so the manager knows what else may be broken by the new changes
        affected_files: set = set()
        code_dir = _get_code_dir()
        sprint_stems = {Path(f).stem for f in sprint_files}  # e.g. {"auth", "models"}
        all_code_files = list(code_dir.rglob("*.py")) + list(code_dir.rglob("*.ts")) + \
                         list(code_dir.rglob("*.tsx")) + list(code_dir.rglob("*.js"))
        for existing in all_code_files:
            rel = existing.relative_to(code_dir).as_posix()
            if rel in sprint_files:
                continue   # already in new files list
            try:
                src = existing.read_text(encoding="utf-8", errors="ignore")
                if any(stem in src for stem in sprint_stems):
                    affected_files.add(rel)
            except Exception:
                pass

        files_list = "\n".join(f"  - {f}" for f in sprint_files) if sprint_files else "  (none recorded)"
        affected_list = "\n".join(f"  - {f}" for f in sorted(affected_files)) if affected_files else "  (none)"

        integration_output, integration_tool_results, _ = _run_with_tools(
            f"You are the {ROLES[manager_role]['title']}.\n\n"
            f"TASK:\n{task}\n\n"
            f"Your team just finished {round_num} round(s) of development. "
            f"Your job now is INTEGRATION — make the codebase actually run as one app.\n\n"
            f"NEW FILES (written this sprint):\n{files_list}\n\n"
            f"AFFECTED FILES (existing files that import from the new files — may be broken):\n{affected_list}\n\n"
            f"STEP 1 — Understand the codebase\n"
            f"  list_files() to see everything written.\n"
            f"  read_file() the entry point and any config files (requirements.txt, package.json,\n"
            f"  docker-compose.yml, Makefile, etc.) to understand exactly how this app is started.\n"
            f"  Determine: what is the boot command? what port does it run on? what is the health endpoint?\n"
            f"  web_search() if you need confirmation for an unfamiliar framework or CLI.\n\n"
            f"STEP 2 — Audit and fix\n"
            f"  read_file() every file in the NEW FILES and AFFECTED FILES lists.\n"
            f"  search_codebase() for import mismatches, wrong function names, missing symbols.\n"
            f"  write_code_file() to patch anything broken.\n"
            f"  Check that all required scaffold files exist (e.g. for React: public/index.html,\n"
            f"  src/index.js — write them if missing).\n"
            f"  validate_python() on every Python file you touch.\n\n"
            f"STEP 3 — THIS STEP IS MANDATORY. Boot the app and verify it responds.\n"
            f"  Using what you learned in Step 1:\n"
            f"    start_service('app', '<the actual boot command you found>')\n"
            f"    http_request('GET', '<the actual health or root URL you found>')\n"
            f"    run_shell(the project's test command) if tests exist — web_search if the stack is unfamiliar\n"
            f"    stop_service('app')\n"
            f"  Do NOT use placeholder commands. Use the real boot command from the codebase.\n"
            f"  Do NOT declare INTEGRATION: DONE without showing actual HTTP response output.\n"
            f"  If the boot fails, read the error, fix the file, and retry.\n\n"
            f"Fix everything. Do not summarize problems — solve them.\n"
            f"End with: INTEGRATION: DONE (paste the actual HTTP response) "
            f"or INTEGRATION: PARTIAL (list exactly what failed and why).",
            manager_role,
            label=f"{manager_role}_integration",
        )
        rolling_ctxs[manager_role].add(task, integration_output)
        logger.info(f"[{manager_role}] integration pass: {integration_output[:150]}...")
    else:
        integration_output = ""

    # ── Final manager synthesis ───────────────────────────────────────────
    summaries = "\n\n".join(
        f"=== {current[r].title} (stance={current[r].stance.upper()}, F={current[r].F_health:.3f}"
        f"{'⚠' if current[r].anomaly else ''}) ===\n{current[r].output[:900]}"
        for r in worker_roles
    )
    integration_section = (
        f"\n\nINTEGRATION PASS OUTPUT:\n{integration_output[:800]}"
        if integration_output else ""
    )
    synthesis = _llm(
        f"You are the {ROLES[manager_role]['title']}.\n\n"
        f"TASK: {task}\n\n"
        f"TEAM OUTPUTS (after {round_num} round(s)):\n{summaries}"
        f"{integration_section}\n\n"
        f"Consensus stance: {consensus.upper()} — {STANCE_DESC[consensus]}\n"
        f"H_swarm={H_swarm:.3f} "
        f"({'stable' if H_swarm < stable_thr else 'elevated — flag risky decisions'})\n\n"
        f"Synthesize the best elements into a single coherent, complete deliverable. "
        f"Resolve any remaining conflicts. Be thorough and specific.",
        label=f"{manager_role}_synthesis",
        system=_manager_system(manager_role),
    )

    for role in worker_roles:
        rolling_ctxs[role].add(task, current[role].output)
    rolling_ctxs[manager_role].add(task, synthesis)

    # Write canonical file so other teams can reference this team's output
    # QA appends (findings accumulate), others overwrite (latest spec wins)
    _write_canonical_file(team_name, synthesis, append=(team_name == "QA"))

    # Post-interference free energy for final H_swarm
    H_swarm     = sum(health_states[r].free_energy() for r in worker_roles)
    mean_stance = np.mean([np.array(current[r].stance_probs) for r in worker_roles], axis=0)
    consensus   = STANCES[int(mean_stance.argmax())]

    return TeamResult(
        team=team_name,
        manager_synthesis=synthesis,
        worker_outputs=[current[r] for r in worker_roles],   # deterministic order
        H_swarm=H_swarm,
        consensus_stance=consensus,
        confidence=max(0.0, 1.0 - H_swarm / (1.5 * n_workers)),  # mean-based, consistent with eng team
    )



