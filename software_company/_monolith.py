#!/usr/bin/env python3
"""
software_company._monolith — Quantum Swarm Software Development Company (core implementation).

A hierarchical AI company that takes a project brief and produces:
  - Architecture document (system design, API spec, data model)
  - Design spec (user flows, UI components, visual style guide)
  - Implementation (code and implementation guide)
  - QA report (tests, security review)
  - CEO executive summary with H_swarm dashboard

Company structure:
  CEO (strategy + synthesis)
    ├── Architecture Manager
    │     System Designer, API Designer, DB Designer
    ├── Design Manager                            ← NEW
    │     UX Researcher, UI Designer, Visual Designer
    ├── Engineering Manager
    │     Backend Developer, Frontend Developer, DevOps Engineer
    └── QA Manager
          Unit Tester, Integration Tester, Security Auditor

Full Quantum Swarm Algorithm:
  ActiveInferenceState     — per-agent health monitoring (perplexity → F)
  interfere_all()          — health-space interference within teams after R1
  Z-score anomaly + reset  — worker reset and retry on R1 anomaly
  interfere_weighted()     — design-stance interference (task-anchored)
  RollingContext           — project memory accumulates across tasks
  H_swarm                  — health signal propagated up the hierarchy

Each agent also has role-specific TOOLS they can call during R1.
Tool results are injected into R2 context (no extra LLM calls — tools
are Python functions executed locally).

Usage:
  python -m software_company
  python -m software_company "Build a real-time chat system with WebSockets"

(Public API: import ``software_company`` — this module is loaded as ``software_company._monolith``.)

Output: company_output/
  architecture.md, design_spec.md, implementation.md, qa_report.md,
  ceo_summary.md, results.json
  code/          ← files written by engineers
  tests/         ← files written by QA
  design/        ← files written by designers
"""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
import sys
import time
import textwrap
import threading
import contextvars as _cv
import yaml
from dataclasses import dataclass, asdict, field
import subprocess
import shutil as _shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import hashlib
import pickle

import numpy as np
import inspect

# Repo root (parent of the software_company package). Path/sys.path/dotenv are set in package __init__.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent

from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("company")

from .config import *  # noqa: E402,F403

def _sync_public_config_from_package() -> None:
    """Mirror attributes tests/scripts set on ``software_company`` into _monolith + ``config``."""
    pkg = sys.modules.get("software_company")
    if pkg is None:
        return
    pd = pkg.__dict__
    g = globals()
    import software_company.config as _cfg
    if "OUTPUT_DIR" in pd:
        val = pd["OUTPUT_DIR"]
        g["OUTPUT_DIR"] = val
        _cfg.OUTPUT_DIR = val
    if "MAX_ENG_ROUNDS" in pd:
        val = pd["MAX_ENG_ROUNDS"]
        g["MAX_ENG_ROUNDS"] = val
        _cfg.MAX_ENG_ROUNDS = val


from .contracts import *  # noqa: F403
from .state import *  # noqa: F403
from .dashboard import (  # noqa: E402
    WorkDashboard,
    get_dashboard,
    _dashboard,
    _dashboard_lock,
)
from .browser import (  # noqa: E402
    BrowserPool,
    get_browser_pool,
    _browser_pool,
    _browser_pool_lock,
)
from .rag import (  # noqa: E402
    CodebaseRAG,
    WorktreeRAG,
    get_rag,
    get_worktree_rag,
    _RAG_EXTENSIONS,
    _is_ignored_project_path,
    _bg_index_file,
    _bg_rag_refresh_after_tree_change,
)
from .prompts_loaded import *  # noqa: F403
from .llm_client import *  # noqa: F403
from .stance import *  # noqa: F403
from .rolling_context import RollingContext  # noqa: F401
from .team_schemas import *  # noqa: F403


from .git_worktrees import GitWorktreeManager, _get_code_dir, _git_repo_lock  # noqa: F401
from . import tools_impl as _tools_impl

# import * skips leading-underscore names; tests and this module expect _tool_* in namespace.
_g_tools = globals()
for _tk, _tv in _tools_impl.__dict__.items():
    if _tk.startswith("__"):
        continue
    if _tk == "logger":
        continue
    if _tk.startswith("_") or _tk in ("clear_sprint_files", "get_sprint_files"):
        _g_tools[_tk] = _tv
del _g_tools, _tk, _tv

from . import tool_registry as _tool_registry_mod
_gr_tr = globals()
for _rk, _rv in _tool_registry_mod.__dict__.items():
    if _rk.startswith("__"):
        continue
    if _rk == "logger":
        continue
    _gr_tr[_rk] = _rv
del _gr_tr, _rk, _rv

from .roles import (
    ROLES,
    ENG_WORKERS,
    _DOD_CHECKLISTS,
    _ARCH_ROLES,
    _DESIGN_ROLES,
    _QA_ROLES,
    _get_dod,
)

# 8 generic engineering workers — all share the same role definition
for _k in ENG_WORKERS:
    ROLES[_k] = ROLES["software_developer"]
    _ROLE_TOOL_NAMES[_k] = _DEV_TOOL_NAMES

_ROLE_TOOL_NAMES["eng_manager"] = _ENG_MANAGER_TOOL_NAMES

from .agent_loop import _run_fixer, _run_with_tools

# ── Worker / planning / teams / engineering (submodules) ───────────────────
from . import workers as _workers_mod
from . import planning as _planning_mod
from . import teams as _teams_mod
from . import engineering as _engineering_mod

def _merge_submodule(ns: dict, mod) -> None:
    for k, v in mod.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("logger",):
            continue
        ns[k] = v

_mp = globals()
_merge_submodule(_mp, _workers_mod)
_merge_submodule(_mp, _planning_mod)
_merge_submodule(_mp, _teams_mod)
_merge_submodule(_mp, _engineering_mod)
from . import desktop_skill as _desktop_skill_mod

_merge_submodule(_mp, _desktop_skill_mod)
del _mp, _merge_submodule, _workers_mod, _planning_mod, _teams_mod, _engineering_mod, _desktop_skill_mod

# ── Orchestration (run_company, outputs, dashboard) ───────────────────────────
from . import orchestration as _orch_mod

_mo = globals()
for _ok, _ov in _orch_mod.__dict__.items():
    if _ok.startswith("__"):
        continue
    if _ok in ("logger",):
        continue
    _mo[_ok] = _ov
del _mo, _ok, _ov

