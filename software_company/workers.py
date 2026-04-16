"""Single-worker execution (`run_worker`)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import numpy as np
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

from .config import OUTPUT_DIR
from .dashboard import get_dashboard
from .rolling_context import RollingContext
from .stance import extract_stance_probs, perplexity_to_similarities
from .state import _current_sprint_goal, _set_agent_ctx
from .team_schemas import WorkerOutput
from .roles import ROLES, _get_dod
from .tool_registry import get_role_lc_tools
from .prompts_loaded import _worker_system

logger = logging.getLogger("company")

# ── Worker execution ──────────────────────────────────────────────────────────
def run_worker(
    role_key: str,
    task: str,
    peer_outputs: List[str],
    peer_tool_results: List[str],
    health_state: ActiveInferenceState,
    rolling_ctx: RollingContext,
    round_num: int,
    sprint_num: int = 1,
) -> WorkerOutput:
    import software_company as sc

    _set_agent_ctx(role_key, sprint_num)

    role      = ROLES[role_key]
    ctx_text  = rolling_ctx.get()
    has_tools = bool(get_role_lc_tools(role_key))

    # ── Goal anchor: pin original sprint goal at the top of every prompt ──
    goal_anchor = ""
    if _current_sprint_goal:
        goal_anchor = (
            f"╔══════════════════════════════════════════════════════╗\n"
            f"║  SPRINT GOAL (your north star — never lose sight of this)\n"
            f"║  {_current_sprint_goal[:200]}\n"
            f"╚══════════════════════════════════════════════════════╝\n\n"
        )

    # Inject manifest for roles that write or read files
    manifest_snippet = ""
    manifest_path = OUTPUT_DIR / "PROJECT_MANIFEST.md"
    struct_path   = OUTPUT_DIR / "design" / "project_structure.md"

    if has_tools:
        # 1. Project Structure (Architect's Intent)
        if struct_path.exists():
            manifest_snippet += (
                "\n\n─── ARCHITECT'S PROJECT STRUCTURE (design/project_structure.md) ───\n"
                + struct_path.read_text(encoding="utf-8")[:3000]
                + "\n───────────────────────────────────────────────────────────────\n"
                "IMPORTANT: You MUST follow this directory tree. Create only these files.\n"
            )

        # 2. Existing files (Actual status)
        if manifest_path.exists():
            manifest_snippet += (
                "\n\n─── CODEBASE INDEX (PROJECT_MANIFEST.md) ───\n"
                + manifest_path.read_text(encoding="utf-8")[:2000]
                + "\n────────────────────────────────────────────\n"
                "IMPORTANT: Before writing any file, call list_files() and search_codebase() "
                "to check what already exists. Do NOT reimplement existing code — extend it.\n"
            )

    dashboard_snippet = ""
    messages_snippet = ""
    if has_tools:
        dashboard_snippet = (
            "\n\n─── WORK DASHBOARD (Sprint " + str(sprint_num) + ") ───\n"
            + get_dashboard().get_status()
            + "\n────────────────────────────────\n"
        )
        try:
            pending = get_dashboard().peek_messages(role_key)
            if pending:
                messages_snippet = f"\nMESSAGES FROM TEAMMATES (read carefully):\n{pending}\n"
        except Exception:
            pass

    dod_checklist = _get_dod(role_key)

    # Long-term memory — lessons from past sprints for this role
    from .long_term_memory import get_role_memory as _get_role_memory
    _ltm = _get_role_memory(role_key).query(task, top_k=4)
    ltm_section = (
        "\n─── DOMAIN EXPERTISE FROM PAST SPRINTS ─────────────────────────\n"
        + _ltm +
        "\n─────────────────────────────────────────────────────────────────\n"
    ) if _ltm else ""

    # Coordination instructions — mirror engineering's mandatory tool-use steps
    coord_instructions = ""
    if has_tools:
        if round_num == 1:
            coord_instructions = (
                "\nMANDATORY FIRST STEPS (do these before producing any work):\n"
                "  1. call check_dashboard() — check messages from teammates\n"
                "  2. call check_messages() — read any messages from teammates or other teams\n"
                "  3. If you need info from another role, call message_teammate(role, question)\n\n"
            )
        else:
            coord_instructions = (
                "\nMANDATORY FIRST STEPS (do these before revising any work):\n"
                "  1. call check_messages() — read ALL messages before changing anything\n"
                "  2. Address every teammate message in your revised output\n\n"
            )

    if round_num == 1:
        prompt = (
            f"{goal_anchor}"
            f"You are a {role['title']} at a software company.\n"
            f"Expertise: {role['expertise']}\n"
            f"Responsibility: {role['responsibility']}\n\n"
            f"{ltm_section}"
            f"{ctx_text}"
            f"{manifest_snippet}"
            f"{dashboard_snippet}"
            f"{messages_snippet}"
            f"{coord_instructions}"
            f"PROJECT TASK:\n{task}\n\n"
            f"Produce your best work product. Be specific, technical, and complete.\n"
            f"Include actual code, schemas, diagrams, or specs where relevant.\n\n"
            f"{dod_checklist}\n\n"
            f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )
    else:
        peer_text = "\n\n---\n".join(
            f"Colleague output:\n{p[:600]}" for p in peer_outputs
        )
        tool_text = (
            "\nTOOL RESULTS FROM PREVIOUS ROUND:\n" + "\n".join(peer_tool_results[:10]) + "\n"
            if peer_tool_results else ""
        )
        feedback_text = (
            f"\nMANAGER FEEDBACK (Round {round_num - 1}):\n{peer_outputs[-1]}\n"
            f"Address every point above.\n"
            if peer_outputs and peer_outputs[-1].startswith("[MANAGER]") else ""
        )
        prompt = (
            f"{goal_anchor}"
            f"You are a {role['title']} at a software company.\n"
            f"Expertise: {role['expertise']}\n\n"
            f"{ltm_section}"
            f"{ctx_text}"
            f"{manifest_snippet}"
            f"{dashboard_snippet}"
            f"{messages_snippet}"
            f"{coord_instructions}"
            f"PROJECT TASK:\n{task}\n\n"
            f"ROUND {round_num} — You have seen what your colleagues produced last round.\n"
            f"COLLEAGUE OUTPUTS:\n{peer_text}\n"
            f"{tool_text}"
            f"{feedback_text}"
            f"Discuss conflicts with your colleagues, fill gaps, and improve your contribution. "
            f"Do not repeat what others have already done — build on it or fix it.\n\n"
            f"{dod_checklist}\n\n"
            f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )

    label = f"{role_key}_R{round_num}"
    if has_tools:
        output, tool_results, perplexity = sc._run_with_tools(prompt, role_key, label)
    else:
        output, perplexity = sc.llm_call(
            prompt, label=label, get_logprobs=True, system=_worker_system(role_key)
        )
        tool_results = []

    sims    = perplexity_to_similarities(perplexity)
    F       = health_state.update(sims)
    anomaly = health_state.is_anomaly()

    if anomaly and round_num == 1:
        logger.warning(f"[{role_key}] ANOMALY F={F:.3f} — invoking fixer agent")
        health_state.reset()
        # Fixer agent: surgical patch of the uncertain output (not a full retry)
        output = sc._run_fixer(role_key, task, output, F)
        sims    = perplexity_to_similarities(5.0)   # moderate uncertainty after fix
        F       = health_state.update(sims)
        anomaly = health_state.is_anomaly()  # reflect actual post-fix state

    m      = re.search(r"STANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)", output, re.IGNORECASE)
    stance = m.group(1).lower() if m else "pragmatic"

    # Background lesson extraction — never blocks
    import threading as _threading
    _threading.Thread(
        target=_get_role_memory(role_key).extract_and_save,
        args=(task, output, sprint_num, not anomaly),
        daemon=True,
    ).start()

    return WorkerOutput(
        role=role_key,
        title=role["title"],
        round=round_num,
        output=output,
        tool_results=tool_results,
        stance=stance,
        stance_probs=extract_stance_probs(output).tolist(),
        F_health=F,
        anomaly=anomaly,
    )



