"""Dataclasses for workers, teams, execution plans, and engineering tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .config import PHASE_IMPLEMENTATION

__all__ = [
    "WorkerOutput",
    "TeamResult",
    "ExecutionPlan",
    "ProjectResult",
    "MergeResult",
    "EngTask",
    "AgentState",
    "IRREVERSIBLE_ACTIONS",
]


@dataclass
class WorkerOutput:
    role:         str
    title:        str
    round:        int
    output:       str
    tool_results: List[str]
    stance:       str
    stance_probs: List[float]
    F_health:     float
    anomaly:      bool = False


@dataclass
class TeamResult:
    team:              str
    manager_synthesis: str
    worker_outputs:    List[WorkerOutput]
    H_swarm:           float
    consensus_stance:  str
    confidence:        float
    quality_passed:    bool = True
    quality_summary:   str = ""
    failed_tasks:      int = 0
    total_tasks:       int = 0


@dataclass
class ExecutionPlan:
    raw:          str
    phases:       List[List[str]]
    team_notes:   Dict[str, str]


@dataclass
class ProjectResult:
    brief:              str
    execution_plan:     ExecutionPlan
    architecture:       Optional[TeamResult]
    design:             Optional[TeamResult]
    engineering:        Optional[TeamResult]
    qa:                 Optional[TeamResult]
    ceo_summary:        str
    overall_H_swarm:    float
    overall_confidence: float
    duration_s:         float


@dataclass
class MergeResult:
    """Result of merge_all — tracks conflict resolutions and agents whose branches couldn't be merged."""
    resolutions: List[str] = field(default_factory=list)
    failed_agents: List[str] = field(default_factory=list)


@dataclass
class AgentState:
    """Snapshot of one agent's runtime state — written into every episode log entry."""
    agent_id: str
    role: str
    sprint: int
    task_file: str
    # Hamiltonian health
    belief_healthy: float = 0.80
    belief_uncertain: float = 0.15
    belief_confused: float = 0.05
    free_energy: float = 0.0
    anomaly_detected: bool = False
    # Token accounting
    call_count: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    token_budget_remaining: int = 5_000_000
    # Stance from last output
    last_stance: str = "PRAGMATIC"
    # Fallback guard
    consecutive_fallbacks: int = 0


# Actions that cannot be undone once executed — agents must confirm before running these.
IRREVERSIBLE_ACTIONS: dict[str, str] = {
    "write_code_file":   "Overwrites a file on disk; prior content is lost unless git-tracked.",
    "run_shell":         "Executes arbitrary shell commands; side-effects cannot be rolled back.",
    "git_merge":         "Merges a branch into the shared codebase; may alter history.",
    "message_teammate":  "Broadcasts a message to another agent; cannot be unsent.",
    "delete_project":    "Removes a project directory and all generated artifacts permanently.",
}


@dataclass
class EngTask:
    """A single unit of engineering work, mapped to one file from the contracts."""
    id: str
    file: str
    description: str
    depends_on: List[str]
    assigned_to: Optional[str] = None
    status: str = "pending"
    retries: int = 0
    phase: int = PHASE_IMPLEMENTATION
    waiting_for: List[str] = field(default_factory=list)
    component_id: Optional[str] = None
    component_graph_snapshot: Optional[dict] = None
    depth: int = 0  # 0 = leaf (no dependencies), higher = closer to root
