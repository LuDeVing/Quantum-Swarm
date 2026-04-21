#!/usr/bin/env python3
"""Run engineering team for a single project. Called as a subprocess by api_server.py."""
import sys
import json
import logging
from pathlib import Path

if len(sys.argv) < 3:
    print("Usage: project_runner.py <project_id> <goal>", file=sys.stderr)
    sys.exit(1)

project_id = sys.argv[1]
goal = sys.argv[2]
output_dir = Path(f"projects/{project_id}")
output_dir.mkdir(parents=True, exist_ok=True)

# ── Override OUTPUT_DIR in every submodule before any engineering code runs ──
import software_company as sc

sc.OUTPUT_DIR = output_dir
sc.WorkDashboard.SAVE_PATH = output_dir / "WORK_DASHBOARD.json"

import software_company.config as _sc_config
import software_company.tools_impl as _sc_tools
import software_company.agent_loop as _sc_agent_loop
import software_company.dashboard as _sc_dashboard
import software_company.git_worktrees as _sc_gwt
import software_company.rag as _sc_rag
import software_company.task_decomposition as _sc_td
import software_company.engineering as _sc_eng
import software_company.contracts as _sc_contracts
import software_company.planning as _sc_planning

_sc_config.OUTPUT_DIR      = output_dir
_sc_tools.OUTPUT_DIR       = output_dir
_sc_agent_loop.OUTPUT_DIR  = output_dir
_sc_dashboard.OUTPUT_DIR   = output_dir
_sc_gwt.OUTPUT_DIR         = output_dir
_sc_rag.OUTPUT_DIR         = output_dir
_sc_td.OUTPUT_DIR          = output_dir
_sc_eng.OUTPUT_DIR         = output_dir
_sc_contracts.OUTPUT_DIR   = output_dir
_sc_planning.OUTPUT_DIR    = output_dir
_sc_td.TaskTree.SAVE_PATH       = output_dir / "TASK_TREE.json"
_sc_td.ComponentGraph.SAVE_PATH = output_dir / "COMPONENT_GRAPH.json"

from software_company import (
    ENG_WORKERS, RollingContext, run_engineering_team,
    ActiveInferenceState, HYPOTHESES, ROLE_PRIOR,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)

rolling_ctxs = {k: RollingContext() for k in ENG_WORKERS + ["eng_manager"]}
health_states = {
    k: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR)
    for k in ENG_WORKERS + ["eng_manager"]
}

final_status = "Failed"
try:
    run_engineering_team(
        task=goal,
        rolling_ctxs=rolling_ctxs,
        health_states=health_states,
        sprint_num=1,
    )
    final_status = "Completed"
except Exception as exc:
    logging.exception(f"[project_runner] ERROR: {exc}")

# Update project.json status
meta_file = output_dir / "project.json"
if meta_file.exists():
    try:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["status"] = final_status
        meta["runner_pid"] = None
        meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

print(f"[project_runner] done — status={final_status}")
