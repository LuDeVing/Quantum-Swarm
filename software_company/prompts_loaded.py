"""System prompts loaded from the repo ``prompts/`` directory."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

_REPO_ROOT = Path(__file__).resolve().parent.parent

__all__ = [
    "_REPO_ROOT",
    "_load_prompt",
    "_SYSTEM_WORKER",
    "_SYSTEM_MANAGER",
    "_SYSTEM_CEO",
    "_SYSTEM_AGENT",
    "_SYSTEM_WORKER_ARCHITECT",
    "_SYSTEM_WORKER_DESIGNER",
    "_SYSTEM_WORKER_ENGINEER",
    "_SYSTEM_WORKER_QA",
    "_SYSTEM_MANAGER_ARCH",
    "_SYSTEM_MANAGER_DESIGN",
    "_SYSTEM_MANAGER_ENG",
    "_SYSTEM_MANAGER_QA",
    "_ROLE_SYSTEM_PROMPTS",
    "_worker_system",
    "_manager_system",
]


def _load_prompt(filename: str) -> str:
    p = _REPO_ROOT / "prompts" / filename
    return p.read_text(encoding="utf-8").strip()


_SYSTEM_WORKER           = _load_prompt("worker.txt")
_SYSTEM_MANAGER          = _load_prompt("manager.txt")
_SYSTEM_CEO              = _load_prompt("ceo.txt")
_SYSTEM_AGENT            = _load_prompt("agent.txt")
_SYSTEM_WORKER_ARCHITECT = _load_prompt("worker_architect.txt")
_SYSTEM_WORKER_DESIGNER  = _load_prompt("worker_designer.txt")
_SYSTEM_WORKER_ENGINEER  = _load_prompt("worker_engineer.txt")
_SYSTEM_WORKER_QA        = _load_prompt("worker_qa.txt")
_SYSTEM_MANAGER_ARCH     = _load_prompt("manager_arch.txt")
_SYSTEM_MANAGER_DESIGN   = _load_prompt("manager_design.txt")
_SYSTEM_MANAGER_ENG      = _load_prompt("manager_eng.txt")
_SYSTEM_MANAGER_QA       = _load_prompt("manager_qa.txt")

_ROLE_SYSTEM_PROMPTS: Dict[str, str] = {
    "system_designer": _SYSTEM_WORKER_ARCHITECT,
    "api_designer":    _SYSTEM_WORKER_ARCHITECT,
    "db_designer":     _SYSTEM_WORKER_ARCHITECT,
    "ux_researcher":   _SYSTEM_WORKER_DESIGNER,
    "ui_designer":     _SYSTEM_WORKER_DESIGNER,
    "visual_designer": _SYSTEM_WORKER_DESIGNER,
    "unit_tester":        _SYSTEM_WORKER_QA,
    "integration_tester": _SYSTEM_WORKER_QA,
    "security_auditor":   _SYSTEM_WORKER_QA,
    "arch_manager":   _SYSTEM_MANAGER_ARCH,
    "design_manager": _SYSTEM_MANAGER_DESIGN,
    "eng_manager":    _SYSTEM_MANAGER_ENG,
    "qa_manager":     _SYSTEM_MANAGER_QA,
}


def _worker_system(role_key: str) -> str:
    """Return the role-specific system prompt for a worker, falling back to the generic one."""
    if role_key.startswith("dev_"):
        return _SYSTEM_WORKER_ENGINEER
    return _ROLE_SYSTEM_PROMPTS.get(role_key, _SYSTEM_WORKER)


def _manager_system(role_key: str) -> str:
    """Return the role-specific system prompt for a manager, falling back to the generic one."""
    return _ROLE_SYSTEM_PROMPTS.get(role_key, _SYSTEM_MANAGER)
