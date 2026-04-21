#!/usr/bin/env python3
"""Quick smoke test for task tree generation only. No engineering agents."""

import sys
import time
from pathlib import Path

import software_company as sc

_OUT = Path("eng_output")
sc.OUTPUT_DIR = _OUT
sc.WorkDashboard.SAVE_PATH = _OUT / "WORK_DASHBOARD.json"
_OUT.mkdir(exist_ok=True)

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

_sc_config.OUTPUT_DIR           = _OUT
_sc_tools.OUTPUT_DIR            = _OUT
_sc_agent_loop.OUTPUT_DIR       = _OUT
_sc_dashboard.OUTPUT_DIR        = _OUT
_sc_gwt.OUTPUT_DIR              = _OUT
_sc_rag.OUTPUT_DIR              = _OUT
_sc_td.OUTPUT_DIR               = _OUT
_sc_eng.OUTPUT_DIR              = _OUT
_sc_contracts.OUTPUT_DIR        = _OUT
_sc_planning.OUTPUT_DIR         = _OUT
_sc_td.TaskTree.SAVE_PATH       = _OUT / "TASK_TREE.json"
_sc_td.ComponentGraph.SAVE_PATH = _OUT / "COMPONENT_GRAPH.json"

from software_company.task_decomposition import run_recursive_decomposition

GOAL = (
    sys.argv[1] if len(sys.argv) > 1
    else "Build a 2D space shooter game in pygame with player movement, enemy waves, bullets, scoring, and a main menu screen."
)

print(f"\n{'='*60}")
print(f"  TASK TREE SMOKE TEST")
print(f"{'='*60}")
print(f"  Goal: {GOAL[:100]}")
print(f"{'='*60}\n")

t0 = time.time()
tree = run_recursive_decomposition(GOAL, sprint_num=1)
elapsed = time.time() - t0

leaves = tree.get_leaf_tasks()

print(f"\n{'='*60}")
print(f"  RESULT")
print(f"{'='*60}")
print(f"  Total nodes : {len(tree.nodes)}")
print(f"  Leaf tasks  : {len(leaves)}")
print(f"  Max depth   : {max(n.depth for n in tree.nodes.values()) if tree.nodes else 0}")
print(f"  Time        : {elapsed:.1f}s")
print(f"\n  FULL TREE:")
print(tree.format_tree())
print(f"\n  LEAF TASKS (what engineers will implement):")
for i, leaf in enumerate(sorted(leaves, key=lambda l: l.suggested_file or ""), 1):
    print(f"\n  [{i}] {leaf.suggested_file or '(no file)'}  [{leaf.complexity}]")
    print(f"       {leaf.description[:200]}")
print(f"\n{'='*60}\n")
