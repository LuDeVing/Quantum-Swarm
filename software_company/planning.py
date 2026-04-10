"""Blackboard team planning (`run_team_planning`)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple

from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

from .config import INTERFERENCE_ALPHA
from .rolling_context import RollingContext
from .roles import ROLES
from .prompts_loaded import _manager_system, _worker_system

logger = logging.getLogger("company")


def _llm(*args, **kwargs):
    import software_company as sc

    return sc.llm_call(*args, **kwargs)


# ── Team planning: manager + workers discuss and self-assign ─────────────────
def run_team_planning(
    team_name: str,
    manager_role: str,
    worker_roles: List[str],
    brief: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> Dict[str, str]:
    """
    Pull-based blackboard planning: manager posts work items to a shared board,
    workers self-claim in one parallel round, manager resolves conflicts only if needed.
    Research shows 13-57% improvement over push-based assignment.
    Returns {worker_key: sub_task_description}.
    """
    n = len(worker_roles)
    logger.info(f"\n{'─'*55}\nTEAM PLANNING (blackboard): {team_name} ({n} workers)\n{'─'*55}")

    m_info = ROLES[manager_role]

    # ── Step 1: Manager posts work items to blackboard ────────────────────────
    # Agile Update: Allow up to 2x n items, but only as many as actually needed
    board_prompt = (
        f"You are the {m_info['title']}.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Post work items to the team blackboard. Role: {team_name}.\n"
        f"  - POST ONLY AS MANY ITEMS AS NEEDED (between 1 and 100 maximum).\n"
        f"  - Do NOT invent fake tasks for a simple project.\n"
        f"  - Each item must be INDEPENDENT and FILE-ISOLATED.\n"
        f"  - Small enough that a specialist can finish multiple in a sprint\n"
        f"  - Each item must list its files in brackets, e.g. [routes.py, auth.py]\n\n"
        f"CRITICAL RULES:\n"
        f"  1. NO two items should write to the same file\n"
        f"  2. Entry point and shared models are system-managed\n\n"
        f"Format EXACTLY as (one line each):\n"
        f"ITEM_1: <task> [files]\n"
        f"ITEM_2: <task> [files]\n"
        f"... up to ITEM_50 if needed."
    )
    board_output = _llm(board_prompt, label=f"{manager_role}_board_post", system=_manager_system(manager_role))

    # Parse board items — tolerant of ITEM_N:, ITEM N:, N. and N) formats
    items: Dict[str, str] = {}
    item_files: Dict[str, List[str]] = {}  # item_id -> list of files
    # Search for all "ITEM_N" patterns up to 100
    for i in range(1, 101):
        m = re.search(
            rf"(?:ITEM[_ ]{i}|{i}[.):])\s*[:–\-]?\s*(.+)",
            board_output,
            re.IGNORECASE,
        )
        if m:
            text = m.group(1).strip()
            items[f"item_{i}"] = text
            # Extract file list from brackets: [file1.py, file2.js]
            file_match = re.search(r"\[([^\]]+)\]", text)
            if file_match:
                item_files[f"item_{i}"] = [f.strip() for f in file_match.group(1).split(",") if f.strip()]

    # Validate file-isolation: no two items should share files
    file_to_item: Dict[str, str] = {}
    overlaps: List[str] = []
    for iid, files in item_files.items():
        for f in files:
            if f in file_to_item:
                overlaps.append(f"  {f}: claimed by both {file_to_item[f]} and {iid}")
            else:
                file_to_item[f] = iid
    if overlaps:
        logger.warning(f"  {team_name}: file overlap detected in work items:\n" + "\n".join(overlaps))
        logger.warning(f"  The integration enforcer will handle shared files automatically.")

    board_display = "\n".join(f"  [{k}] {v}" for k, v in items.items())
    logger.info(f"  {team_name} blackboard posted {n} items ({len(item_files)} with explicit file lists)")

    # ── Step 2: Workers self-claim in parallel ────────────────────────────────
    def worker_claim(role_key: str) -> Tuple[str, str]:
        idx = worker_roles.index(role_key) + 1
        output = _llm(
            f"You are {ROLES[role_key]['title']} #{idx}.\n"
            f"Expertise: {ROLES[role_key]['expertise']}\n\n"
            f"BLACKBOARD — available work items:\n{board_display}\n\n"
            f"Scan the board and claim ALL items that best match your expertise.\n"
            f"You are encouraged to pick multiple items (up to 3) if they are related.\n"
            f"List them clearly. One sentence reason per claim.\n\n"
            f"End with exactly: CLAIM: item_X, item_Y",
            label=f"{role_key}_claim",
            system=_worker_system(role_key),
        )
        return role_key, output

    claims: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        for role_key, output in ex.map(lambda r: worker_claim(r), worker_roles):
            claims[role_key] = output
            m_claim = re.search(r"CLAIM:\s*([item_\d,\s]+)", output, re.IGNORECASE)
            claimed_str = m_claim.group(1) if m_claim else "UNKNOWN"
            logger.info(f"  [claim] {role_key} → {claimed_str}")

    # Health interference across team
    ActiveInferenceState.interfere_all(
        [health_states[r] for r in worker_roles], alpha=INTERFERENCE_ALPHA
    )

    # ── Step 3: Parse claims; resolve conflicts ──────────────────────────────
    claimed: Dict[str, str] = {}    # item_id → role_key (first valid claimant wins)
    assignments: Dict[str, List[str]] = {r: [] for r in worker_roles}

    for role_key in worker_roles:
        m = re.search(r"CLAIM:\s*([item_\d,\s]+)", claims[role_key], re.IGNORECASE)
        if m:
            iids = [i.strip().lower() for i in m.group(1).split(",") if i.strip()]
            for iid in iids:
                if iid in items and iid not in claimed:
                    claimed[iid] = role_key
                    assignments[role_key].append(iid)

    # Conflict resolution: workers with no tasks get first unclaimed items
    conflict_roles: List[str] = [r for r in worker_roles if not assignments[r]]
    unclaimed_items = [iid for iid in items if iid not in claimed]
    
    for role_key in conflict_roles:
        if unclaimed_items:
            iid = unclaimed_items.pop(0)
            assignments[role_key].append(iid)
            claimed[iid] = role_key

    # ── Step 4: Finalize ─────────────────────────────────────────────────────
    if conflict_roles:
        logger.info(f"  {team_name}: {len(conflict_roles)} worker(s) had no valid claims — assigning pool items")

    logger.info(f"\n  {team_name} blackboard assignments:")
    final_output: Dict[str, str] = {}
    for role_key, iids in assignments.items():
        if iids:
            joined_desc = "\n\n".join(f"Task {i}: {items[i]}" for i in iids)
            final_output[role_key] = joined_desc
            logger.info(f"    {role_key} → {len(iids)} tasks: {', '.join(iids)}")
        else:
            final_output[role_key] = "Assist the team with existing files."
            logger.info(f"    {role_key} → Assist and Review")

    pool_items = {iid: desc for iid, desc in items.items() if iid not in claimed}
    if pool_items:
        logger.info(f"  {team_name}: {len(pool_items)} items left in the general pool.")

    for role_key in worker_roles:
        rolling_ctxs[role_key].add(
            f"{team_name} planning",
            (claims.get(role_key, "") or "")[:400],
        )

    return final_output, pool_items



