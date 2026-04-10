"""Sprint orchestration: `run_company`, kickoff/retro, save outputs, dashboard."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

from .config import *  # noqa: F403
from .llm_client import _call_count, _token_lock, _tokens_in, _tokens_out, token_summary
from .rolling_context import RollingContext
from .team_schemas import ExecutionPlan, ProjectResult, TeamResult
from .roles import ROLES
from .prompts_loaded import _SYSTEM_CEO, _manager_system

from .engineering import (
    MANAGER_ROLES,
    run_executive_meeting,
    run_sprint_planning,
)
from .teams import run_team
from .engineering import run_engineering_team

logger = logging.getLogger("company")


def _llm(*args, **kwargs):
    import software_company as sc

    return sc.llm_call(*args, **kwargs)


# ── Main orchestrator ─────────────────────────────────────────────────────────

TEAM_RUNNERS = {
    "Architecture": lambda task, ctxs, hs, sn=1: run_team(
        "Architecture", "arch_manager",
        ["system_designer", "api_designer", "db_designer"],
        task, ctxs, hs, sn,
    ),
    "Design": lambda task, ctxs, hs, sn=1: run_team(
        "Design", "design_manager",
        ["ux_researcher", "ui_designer", "visual_designer"],
        task, ctxs, hs, sn,
    ),
    "Engineering": lambda task, ctxs, hs, sn=1: run_engineering_team(task, ctxs, hs, sn),
    "QA": lambda task, ctxs, hs, sn=1: run_team(
        "QA", "qa_manager",
        ["unit_tester", "integration_tester", "security_auditor"],
        task, ctxs, hs, sn,
    ),
}


def run_sprint_kickoff(
    brief: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> str:
    """
    CEO + all managers collaboratively define the first sprint goal.
    No CEO monologue — this is a real discussion.
    Returns the agreed Sprint 1 goal as a task string.
    """
    logger.info(f"\n{'═'*55}\nSPRINT KICKOFF: CEO + managers\n{'═'*55}")
    team_names = list(MANAGER_ROLES.keys())

    # CEO opens with vision — not a plan, just the brief and questions
    ceo_open = _llm(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Open the Sprint 1 kickoff meeting. Share your vision for the product and "
        f"ask each manager: what is the single most critical thing your team can "
        f"deliver in Sprint 1 that would give us a working, demonstrable foundation? "
        f"Do NOT dictate the sprint goal — ask for their input.",
        label="ceo_kickoff_open",
        system=_SYSTEM_CEO,
    )
    logger.info(f"CEO opens kickoff: {ceo_open[:100]}...")

    # Round 1: each manager proposes what their team should build in Sprint 1
    def mgr_kickoff_r1(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        out = _llm(
            f"CEO's opening:\n{ceo_open}\n\n"
            f"PROJECT BRIEF:\n{brief}\n\n"
            f"You lead the {team_name} team. What should your team focus on in Sprint 1? "
            f"Be specific: name the concrete deliverables, the acceptance criteria, "
            f"and any dependencies you need from other teams before you can start.",
            label=f"{role_key}_kickoff_r1",
            system=_manager_system(role_key),
        )
        return team_name, out

    r1: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_kickoff_r1, team_names):
            r1[name] = out

    ActiveInferenceState.interfere_all(
        [health_states[MANAGER_ROLES[t]] for t in team_names], alpha=INTERFERENCE_ALPHA
    )

    # Round 2: managers see each other's proposals, negotiate and align
    all_r1 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']}:\n{r1[t]}" for t in team_names)

    def mgr_kickoff_r2(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        out = _llm(
            f"All managers' Sprint 1 proposals:\n{all_r1}\n\n"
            f"Having heard everyone: do you see any conflicts or gaps between proposals? "
            f"Refine your team's Sprint 1 scope to integrate with what the other managers proposed. "
            f"Be concrete about integration points.",
            label=f"{role_key}_kickoff_r2",
            system=_manager_system(role_key),
        )
        return team_name, out

    r2: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_kickoff_r2, team_names):
            r2[name] = out

    # CEO synthesises into a concrete Sprint 1 goal
    all_r2 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']} (refined):\n{r2[t]}" for t in team_names)
    sprint_goal = _llm(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Manager proposals (round 1):\n{all_r1}\n\n"
        f"Manager refinements (round 2):\n{all_r2}\n\n"
        f"Synthesise a concrete Sprint 1 goal that reflects the team's collective judgment. "
        f"Include: what will be built, acceptance criteria for each team, "
        f"integration contracts between teams, and what 'done' looks like at the end of the sprint. "
        f"This is the authoritative sprint goal all teams will execute against.",
        label="ceo_kickoff_goal",
        system=_SYSTEM_CEO,
    )

    for t in team_names:
        rolling_ctxs[MANAGER_ROLES[t]].add("sprint kickoff", r2[t])
    rolling_ctxs["ceo"].add("sprint kickoff", sprint_goal)

    # Save conversation log
    turns = [{"speaker": "CEO — Kickoff Opening", "text": ceo_open}]
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R1)", "text": r1[t]})
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R2)", "text": r2[t]})
    turns.append({"speaker": "CEO — Sprint 1 Goal", "text": sprint_goal})
    _save_conversation("Sprint Kickoff", turns)

    logger.info(f"Sprint 1 goal agreed: {sprint_goal[:120]}...")
    return sprint_goal


def run_sprint_retrospective(
    brief: str,
    sprint_num: int,
    sprint_result: ProjectResult,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> Tuple[str, bool]:
    """
    After a sprint: CEO + all managers review what was built, assess quality,
    and either decide to ship or define the next sprint goal collaboratively.

    Returns (next_sprint_goal_or_empty, should_ship).
    """
    logger.info(f"\n{'═'*55}\nSPRINT {sprint_num} RETROSPECTIVE: CEO + managers\n{'═'*55}")
    team_names = list(MANAGER_ROLES.keys())

    # Build sprint summary for context
    completed = [r for r in [
        sprint_result.architecture, sprint_result.design,
        sprint_result.engineering,  sprint_result.qa,
    ] if r is not None]
    sprint_summary = "\n\n".join(
        f"{t.team} (confidence={t.confidence:.0%}, H={t.H_swarm:.3f}):\n"
        f"{t.manager_synthesis[:400]}"
        for t in completed
    )
    qa_result = sprint_result.qa
    qa_summary = (
        f"QA confidence: {qa_result.confidence:.0%}, H={qa_result.H_swarm:.3f}\n"
        f"{qa_result.manager_synthesis[:300]}"
        if qa_result else "QA did not run this sprint."
    )

    # CEO opens retro
    ceo_retro_open = _llm(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Sprint {sprint_num} has just completed. Here is what was built:\n{sprint_summary}\n\n"
        f"QA Report:\n{qa_summary}\n\n"
        f"Open the sprint retrospective. Ask each manager: "
        f"(1) what did your team deliver vs. what was planned, "
        f"(2) what quality issues or gaps remain, "
        f"(3) what is your recommendation for the next sprint?",
        label=f"ceo_retro_{sprint_num}_open",
        system=_SYSTEM_CEO,
    )
    logger.info(f"CEO opens retro: {ceo_retro_open[:100]}...")

    # Round 1: each manager gives their retrospective assessment
    def mgr_retro_r1(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        team_result = getattr(sprint_result, team_name.lower(), None)
        team_output = (
            f"Your team's output this sprint:\n{team_result.manager_synthesis[:400]}\n"
            f"Confidence: {team_result.confidence:.0%}, H_swarm: {team_result.H_swarm:.3f}"
            if team_result else "Your team did not run this sprint."
        )
        out = _llm(
            f"CEO's retrospective opening:\n{ceo_retro_open}\n\n"
            f"{team_output}\n\n"
            f"Full sprint summary:\n{sprint_summary}\n\n"
            f"Give your honest retrospective: what was delivered, what was missed, "
            f"what technical debt was incurred, and what your team must tackle next sprint. "
            f"Be specific — name actual files, functions, or features.",
            label=f"{role_key}_retro_{sprint_num}_r1",
            system=_manager_system(role_key),
        )
        return team_name, out

    r1: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_retro_r1, team_names):
            r1[name] = out

    ActiveInferenceState.interfere_all(
        [health_states[MANAGER_ROLES[t]] for t in team_names], alpha=INTERFERENCE_ALPHA
    )

    # Round 2: managers propose next sprint scope after hearing each other
    all_r1 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']}:\n{r1[t]}" for t in team_names)

    def mgr_retro_r2(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        out = _llm(
            f"All managers' retrospective assessments:\n{all_r1}\n\n"
            f"Based on what every team reported: propose what YOUR team should build "
            f"in Sprint {sprint_num + 1}. Prioritise what is most critical for quality "
            f"and completeness. Be specific about deliverables and acceptance criteria.",
            label=f"{role_key}_retro_{sprint_num}_r2",
            system=_manager_system(role_key),
        )
        return team_name, out

    r2: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_retro_r2, team_names):
            r2[name] = out

    # CEO decides: ship or define next sprint
    all_r2 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']} (Sprint {sprint_num+1} proposal):\n{r2[t]}" for t in team_names)
    ceo_decision = _llm(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Sprint {sprint_num} summary:\n{sprint_summary}\n\n"
        f"Manager retrospectives:\n{all_r1}\n\n"
        f"Manager Sprint {sprint_num + 1} proposals:\n{all_r2}\n\n"
        f"Overall confidence: {sprint_result.overall_confidence:.0%} | "
        f"H_swarm: {sprint_result.overall_H_swarm:.3f} | "
        f"QA: {qa_summary[:150]}\n\n"
        f"Make the call: is this product ready to ship, or does it need another sprint?\n\n"
        f"If SHIPPING: output exactly 'DECISION: SHIP' followed by your go/no-go rationale.\n"
        f"If CONTINUING: output exactly 'DECISION: SPRINT' followed by the Sprint {sprint_num + 1} "
        f"goal — concrete deliverables, acceptance criteria per team, and integration contracts.",
        label=f"ceo_retro_{sprint_num}_decision",
        system=_SYSTEM_CEO,
    )

    for t in team_names:
        rolling_ctxs[MANAGER_ROLES[t]].add(f"sprint {sprint_num} retro", r2[t])
    rolling_ctxs["ceo"].add(f"sprint {sprint_num} retro", ceo_decision)

    # Save conversation log
    turns = [{"speaker": f"CEO — Sprint {sprint_num} Retrospective Opening", "text": ceo_retro_open}]
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (Retro R1)", "text": r1[t]})
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (Next Sprint Proposal)", "text": r2[t]})
    turns.append({"speaker": f"CEO — Decision", "text": ceo_decision})
    _save_conversation(f"Sprint {sprint_num} Retrospective", turns, sprint_num=sprint_num)

    should_ship = bool(re.search(r"DECISION:\s*SHIP", ceo_decision, re.IGNORECASE))
    logger.info(f"CEO decision: {'SHIP ✓' if should_ship else f'CONTINUE → Sprint {sprint_num+1}'}")
    logger.info(f"  {ceo_decision[:150]}...")

    if should_ship:
        return ceo_decision, True

    # Extract the next sprint goal from the decision text
    m = re.search(r"DECISION:\s*SPRINT\s*(.+)", ceo_decision, re.DOTALL | re.IGNORECASE)
    next_goal = m.group(1).strip() if m else ceo_decision
    return (
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"SPRINT {sprint_num + 1} GOAL (agreed in retrospective):\n{next_goal}\n\n"
        f"COMPLETED IN PREVIOUS SPRINTS:\n{sprint_summary}",
        False,
    )


def _update_rag_and_manifest(sprint_num: int):
    """Re-index all output files into the RAG, then write PROJECT_MANIFEST.md."""
    rag = get_rag()
    rag.update()
    manifest_text = (
        f"# Project Manifest — updated after Sprint {sprint_num}\n\n"
        f"This file lists every source file in the codebase. "
        f"**Read this before writing any new file** to avoid duplicates.\n\n"
        f"## Files\n\n"
        f"{rag.manifest()}\n\n"
        f"## How to use codebase search\n\n"
        f"Call `search_codebase(query)` with a natural language description of what you need "
        f"(e.g. 'authentication token validation', 'WebSocket connection handler', "
        f"'Kanban task model'). It returns the most relevant existing code chunks.\n\n"
        f"Call `list_files()` to see all files.\n\n"
        f"Call `read_file(filename)` to read a specific file before modifying or importing it.\n"
    )
    manifest_path = OUTPUT_DIR / "PROJECT_MANIFEST.md"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    logger.info(f"[RAG] PROJECT_MANIFEST.md updated ({len(rag.chunks)} chunks indexed)")

    # Mark completed domains and write dashboard snapshot
    dash = get_dashboard()
    dash.release_sprint(sprint_num)
    dash_path = OUTPUT_DIR / "WORK_DASHBOARD.md"
    dash_path.write_text(
        f"# Work Dashboard — after Sprint {sprint_num}\n\n"
        + dash.get_status(),
        encoding="utf-8",
    )
    logger.info(f"[Dashboard] WORK_DASHBOARD.md written")


def _run_sprint(
    sprint_brief: str,
    sprint_num: int,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    prev_sprint_summary: str,
) -> ProjectResult:
    """Run a single sprint through the full company pipeline."""
    global _current_sprint_goal
    _current_sprint_goal = sprint_brief   # pin clean goal before context accumulates
    sprint_task = sprint_brief
    if prev_sprint_summary:
        sprint_task += (
            f"\n\nCOMPLETED IN PREVIOUS SPRINTS:\n{prev_sprint_summary}\n\n"
            f"Build on top of the existing work. Do not reimplement what was already done. "
            f"Extend, integrate, and improve."
        )

    plan = run_executive_meeting(sprint_task, rolling_ctxs, health_states)

    results: Dict[str, Optional[TeamResult]] = {
        "Architecture": None, "Design": None, "Engineering": None, "QA": None
    }

    def context_from_results(team_name: str) -> str:
        parts = []
        for other, r in results.items():
            if r is not None and other != team_name:
                parts.append(f"{other} output:\n{r.manager_synthesis[:350]}")
        return "\n\n".join(parts)

    for phase_idx, phase_teams in enumerate(plan.phases, 1):
        valid_teams = [t for t in phase_teams if t in TEAM_RUNNERS]
        if not valid_teams:
            continue
        logger.info(f"\n{'═'*55}\nSPRINT {sprint_num} — PHASE {phase_idx}: {' + '.join(valid_teams)}\n{'═'*55}")

        if len(valid_teams) == 1:
            team = valid_teams[0]
            ctx  = context_from_results(team)
            task = sprint_task if not ctx else f"{sprint_task}\n\nContext from completed teams:\n{ctx}"
            results[team] = TEAM_RUNNERS[team](task, rolling_ctxs, health_states, sprint_num)
        else:
            def _run_team(team_name: str) -> Tuple[str, TeamResult]:
                ctx  = context_from_results(team_name)
                task = sprint_task if not ctx else f"{sprint_task}\n\nContext from completed teams:\n{ctx}"
                return team_name, TEAM_RUNNERS[team_name](task, rolling_ctxs, health_states, sprint_num)

            with ThreadPoolExecutor(max_workers=len(valid_teams)) as ex:
                for team_name, result in ex.map(_run_team, valid_teams):
                    results[team_name] = result

    # ── Update RAG index after all teams have written files ───────────────
    _update_rag_and_manifest(sprint_num)

    ceo_summary = run_ceo_summary(sprint_task, results, plan, rolling_ctxs["ceo"])
    completed   = [r for r in results.values() if r is not None]

    return ProjectResult(
        brief=sprint_brief,
        execution_plan=plan,
        architecture=results.get("Architecture"),
        design=results.get("Design"),
        engineering=results.get("Engineering"),
        qa=results.get("QA"),
        ceo_summary=ceo_summary,
        overall_H_swarm=sum(t.H_swarm for t in completed),
        overall_confidence=sum(t.confidence for t in completed) / max(len(completed), 1),
        duration_s=0.0,  # filled in by run_company
    )


def run_company(brief: str, max_sprints: int = MAX_SPRINTS) -> List[ProjectResult]:
    """
    Run the full company pipeline as collaborative Scrum sprints.

    Sprint goals are NOT planned upfront.
      - Sprint 1 goal is defined collaboratively in a kickoff (CEO + all managers)
      - After each sprint a retrospective (CEO + all managers) reviews quality and
        either declares the product ready to ship OR defines the next sprint goal
      - Sprints continue until the CEO decides to ship — no artificial limit

    Returns a list of ProjectResult, one per sprint.
    """
    _sync_public_config_from_package()
    start = time.time()
    for sub in ["code", "tests", "design", "config"]:
        (OUTPUT_DIR / sub).mkdir(parents=True, exist_ok=True)

    all_roles     = list(ROLES.keys())
    health_states = {r: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR) for r in all_roles}
    rolling_ctxs  = {r: RollingContext() for r in all_roles}

    # ── Sprint 1 goal: CEO + managers kickoff discussion ─────────────────
    sprint_goal    = run_sprint_kickoff(brief, rolling_ctxs, health_states)
    sprint_results: List[ProjectResult] = []
    sprint_num     = 1

    while sprint_num <= max_sprints:
        sprint_start = time.time()
        logger.info(f"\n{'█'*55}\nSPRINT {sprint_num}/{MAX_SPRINTS}\n{'█'*55}")

        result = _run_sprint(
            sprint_goal, sprint_num,
            rolling_ctxs, health_states, prev_sprint_summary="",
        )
        result.duration_s = time.time() - sprint_start
        sprint_results.append(result)
        save_outputs(result, sprint_num=sprint_num)

        # ── Sprint retrospective: CEO + managers review and decide ────────
        next_goal, should_ship = run_sprint_retrospective(
            brief, sprint_num, result, rolling_ctxs, health_states
        )

        if should_ship:
            logger.info(f"\n{'█'*55}\nPRODUCT SHIPPED after {sprint_num} sprint(s)\n{'█'*55}")
            break

        sprint_goal = next_goal
        sprint_num += 1

    if sprint_num > MAX_SPRINTS:
        logger.warning(f"[run_company] hit MAX_SPRINTS={MAX_SPRINTS} — stopping without CEO ship decision")

    logger.info(f"\nTotal duration: {time.time() - start:.0f}s | {token_summary()}")
    return sprint_results


# ── Save outputs ──────────────────────────────────────────────────────────────
def _h_swarm_status(h_swarm: float, n_workers: int) -> str:
    """Return '⚠ elevated' or 'stable' using the same scaled threshold as the run logic."""
    return "⚠ elevated" if h_swarm > 1.5 * n_workers else "stable"


def _team_md(result: TeamResult, brief: str, title: str) -> str:
    n_workers = max(len(result.worker_outputs), 1)
    status    = _h_swarm_status(result.H_swarm, n_workers)
    header = (
        f"# {title}\n\n"
        f"**Project:** {brief}\n\n"
        f"**Consensus Stance:** {result.consensus_stance.upper()} — "
        f"{STANCE_DESC[result.consensus_stance]}\n\n"
        f"**Team Confidence:** {result.confidence:.0%} "
        f"(H_swarm={result.H_swarm:.3f}"
        f"{' ' + status if status == '⚠ elevated' else ''})\n\n"
        f"---\n\n"
    )
    worker_md = "\n\n".join(
        f"### {w.title}\n\n"
        f"*Stance: {w.stance.upper()} | F_health={w.F_health:.3f}"
        f"{'| ⚠ anomaly' if w.anomaly else ''}*\n\n"
        f"{w.output}"
        + (f"\n\n**Tool results:**\n" + "\n".join(w.tool_results) if w.tool_results else "")
        for w in result.worker_outputs
    )
    return (
        header
        + result.manager_synthesis
        + "\n\n---\n\n## Individual Contributions\n\n"
        + worker_md
    )


def _save_conversation(title: str, turns: List[Dict[str, str]], sprint_num: Optional[int] = None) -> None:
    """Append a CEO↔manager conversation to company_output/conversations_sprintN.md."""
    suffix = f"_sprint{sprint_num}" if sprint_num is not None else ""
    path = OUTPUT_DIR / f"conversations{suffix}.md"
    lines = [f"## {title}\n"]
    for turn in turns:
        speaker = turn["speaker"]
        text    = turn["text"].strip()
        lines.append(f"### {speaker}\n\n{text}\n")
    block = "\n---\n".join(lines) + "\n\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)


def save_outputs(result: ProjectResult, sprint_num: Optional[int] = None) -> None:
    suffix = f"_sprint{sprint_num}" if sprint_num is not None else ""
    team_files = [
        (result.architecture, f"architecture{suffix}.md",   "Architecture"),
        (result.design,       f"design_spec{suffix}.md",    "Design Specification"),
        (result.engineering,  f"implementation{suffix}.md", "Implementation"),
        (result.qa,           f"qa_report{suffix}.md",      "QA Report"),
    ]
    for team_result, filename, title in team_files:
        if team_result is not None:
            (OUTPUT_DIR / filename).write_text(
                _team_md(team_result, result.brief, title), encoding="utf-8"
            )

    completed_teams = [
        t for t in [result.architecture, result.design, result.engineering, result.qa]
        if t is not None
    ]
    dashboard_rows = "\n".join(
        f"| {t.team:<13} | {t.H_swarm:.3f} | {t.confidence:.0%} | "
        f"{t.consensus_stance} | {_h_swarm_status(t.H_swarm, max(len(t.worker_outputs), 1))} |"
        for t in completed_teams
    )
    sprint_header = f"Sprint {sprint_num} — " if sprint_num is not None else ""
    (OUTPUT_DIR / f"ceo_summary{suffix}.md").write_text(
        f"# {sprint_header}Executive Summary\n\n"
        f"**Project:** {result.brief}\n\n"
        f"**Overall Confidence:** {result.overall_confidence:.0%} | "
        f"**H_swarm:** {result.overall_H_swarm:.3f} | "
        f"**Duration:** {result.duration_s:.0f}s\n\n"
        f"---\n\n{result.ceo_summary}\n\n---\n\n"
        f"## Execution Plan\n\n"
        f"```\n{result.execution_plan.raw[:600]}\n```\n\n"
        f"## H_swarm Dashboard\n\n"
        f"| Team | H_swarm | Confidence | Stance | Status |\n"
        f"|------|---------|------------|--------|--------|\n"
        f"{dashboard_rows}",
        encoding="utf-8",
    )

    def _serial(obj):
        if isinstance(obj, np.ndarray):  return obj.tolist()
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.integer):  return int(obj)
        raise TypeError(f"Not serializable: {type(obj)}")

    data = asdict(result)
    # Read token counters under lock to avoid torn reads
    with _token_lock:
        _snap_calls = _call_count
        _snap_in    = _tokens_in
        _snap_out   = _tokens_out
    data["token_usage"] = {
        "calls":      _snap_calls,
        "tokens_in":  _snap_in,
        "tokens_out": _snap_out,
        "total":      _snap_in + _snap_out,
        "summary":    token_summary(),
    }
    with open(OUTPUT_DIR / "results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_serial)
    logger.info(f"\nOutputs saved to {OUTPUT_DIR}/")
    logger.info(f"Token usage: {token_summary()}")


# ── Dashboard ─────────────────────────────────────────────────────────────────
def print_dashboard(result: ProjectResult) -> None:
    teams = [t for t in [result.architecture, result.design, result.engineering, result.qa] if t is not None]
    print(f"\n{'═'*62}")
    print(f"  QUANTUM SWARM COMPANY — PROJECT COMPLETE")
    print(f"{'═'*62}")
    print(f"  Project  : {result.brief[:65]}")
    print(f"  Duration : {result.duration_s:.0f}s")
    print(f"  Overall  : {result.overall_confidence:.0%} confidence  |  H_swarm={result.overall_H_swarm:.3f}")
    print(f"{'─'*62}")
    print(f"  Execution plan phases: {len(result.execution_plan.phases)}")
    for i, phase in enumerate(result.execution_plan.phases, 1):
        print(f"    Phase {i}: {', '.join(phase)}")
    print(f"{'─'*62}")
    print(f"  {'Team':<15} {'H_swarm':>8}  {'Confidence':>10}  {'Stance':<12}  Status")
    print(f"  {'─'*15} {'─'*8}  {'─'*10}  {'─'*12}  {'─'*10}")
    for t in teams:
        status = _h_swarm_status(t.H_swarm, max(len(t.worker_outputs), 1))
        print(f"  {t.team:<15} {t.H_swarm:>8.3f}  {t.confidence:>10.0%}  {t.consensus_stance:<12}  {status}")
    print(f"{'─'*62}")
    print(f"  Outputs in {OUTPUT_DIR}/")
    print(f"    architecture.md  design_spec.md  implementation.md")
    print(f"    qa_report.md     ceo_summary.md  results.json")
    print(f"    code/            tests/          design/   config/")
    print(f"{'─'*62}")
    print(f"  Tokens: {token_summary()}")
    print(f"{'═'*62}\n")


# ── Entry point ───────────────────────────────────────────────────────────────
DEFAULT_BRIEF = (
    "Build a REST API for user authentication: "
    "registration, login with JWT tokens, password hashing with bcrypt, "
    "refresh token rotation, rate limiting on login attempts, "
    "and email verification flow."
)

