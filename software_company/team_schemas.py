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
class EngTask:
    """A single unit of engineering work, mapped to one file from the contracts."""
    id: str
    file: str
    description: str
    depends_on: List[str]
    assigned_to: Optional[str] = None
    status: str = "pending"
    retries: int = 0
    primary_owner: Optional[str] = None
    phase: int = PHASE_IMPLEMENTATION
    waiting_for: List[str] = field(default_factory=list)
    component_id: Optional[str] = None
    component_graph_snapshot: Optional[dict] = None
    depth: int = 0  # 0 = leaf (no dependencies), higher = closer to root
