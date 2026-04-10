"""Per-agent and worktree context (contextvars)."""

from __future__ import annotations

import contextvars as _cv
from typing import Optional

__all__ = [
    "_agent_id_ctx",
    "_sprint_num_ctx",
    "_task_file_ctx",
    "_get_agent_id",
    "_get_sprint_num",
    "_get_task_file",
    "_set_agent_ctx",
    "_set_task_file",
    "_current_sprint_goal",
    "_wt_manager_ctx",
    "_get_worktree_manager",
    "_set_worktree_manager",
]

# Per-thread agent identity — each worker thread sets its own context so parallel
# threads don't overwrite each other's agent ID / sprint number.
# Use contextvars instead of threading.local — ContextVar is propagated through
# asyncio tasks AND through asyncio.to_thread(), which threading.local is NOT.
# This ensures agent identity survives LangGraph's internal async/thread machinery.
_agent_id_ctx: _cv.ContextVar[str] = _cv.ContextVar("agent_id", default="")
_sprint_num_ctx: _cv.ContextVar[int] = _cv.ContextVar("sprint_num", default=1)
_task_file_ctx: _cv.ContextVar[str] = _cv.ContextVar("task_file", default="")


def _get_agent_id() -> str:
    return _agent_id_ctx.get()


def _get_sprint_num() -> int:
    return _sprint_num_ctx.get()


def _get_task_file() -> str:
    return _task_file_ctx.get()


def _set_agent_ctx(agent_id: str, sprint_num: int) -> None:
    _agent_id_ctx.set(agent_id)
    _sprint_num_ctx.set(sprint_num)


def _set_task_file(task_file: str) -> None:
    _task_file_ctx.set(task_file)


# Sprint goal is set once per sprint before any threads start — read-only during execution
_current_sprint_goal: str = ""

# Git worktree manager for the current async/thread context (set during eng runs).
_wt_manager_ctx: _cv.ContextVar[Optional["GitWorktreeManager"]] = _cv.ContextVar(
    "wt_manager", default=None,
)


def _get_worktree_manager() -> Optional["GitWorktreeManager"]:
    return _wt_manager_ctx.get()


def _set_worktree_manager(mgr: Optional["GitWorktreeManager"]) -> None:
    _wt_manager_ctx.set(mgr)
