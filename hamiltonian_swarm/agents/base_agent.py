"""
Abstract base agent with Hamiltonian phase-space state tracking.

Each agent occupies a point in phase space (q, p) representing its
'operational state'. The Hamiltonian H(q, p) measures the agent's
'energy' (computational load + task complexity). Conservation monitoring
detects when an agent's behaviour has drifted from its intended trajectory.
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional

import torch

from ..core.phase_space import PhaseSpaceState
from ..core.hamiltonian import HamiltonianFunction
from ..core.conservation_monitor import ConservationMonitor

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    IDLE = auto()
    RUNNING = auto()
    WAITING = auto()
    TERMINATED = auto()


class AgentDriftException(Exception):
    """Raised when an agent's Hamiltonian energy drifts beyond the stability threshold."""
    pass


@dataclass
class TaskResult:
    """Structured result returned by agent.execute_task()."""
    task_id: str
    agent_id: str
    success: bool
    output: Any
    energy_before: float
    energy_after: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """
    Abstract base class for all swarm agents.

    Every agent maintains a PhaseSpaceState (q, p) representing its position
    in an abstract phase space. The HamiltonianFunction H(q, p) gives the
    agent's energy, and a ConservationMonitor tracks energy drift over time.

    Parameters
    ----------
    n_dims : int
        Dimensionality of the agent's phase space.
    agent_type : str
        Human-readable agent type label.
    mass_scale : float
        Kinetic energy scaling factor.
    stiffness_scale : float
        Potential energy scaling factor.
    drift_threshold : float
        Energy drift fraction that triggers AgentDriftException.
    """

    def __init__(
        self,
        n_dims: int = 4,
        agent_type: str = "base",
        mass_scale: float = 1.0,
        stiffness_scale: float = 1.0,
        drift_threshold: float = 0.05,
    ) -> None:
        self.agent_id: str = str(uuid.uuid4())[:8]
        self.agent_type: str = agent_type
        self.status: AgentStatus = AgentStatus.IDLE
        self.n_dims: int = n_dims

        # Phase-space state initialised near origin with small random momenta
        q0 = torch.randn(n_dims) * 0.1
        p0 = torch.randn(n_dims) * 0.1
        self.phase_state = PhaseSpaceState(q=q0, p=p0, agent_id=self.agent_id)

        # Hamiltonian
        self.hamiltonian = HamiltonianFunction(
            n_dims=n_dims,
            mass_scale=mass_scale,
            stiffness_scale=stiffness_scale,
        )

        # Energy tracking
        self.energy_history: List[float] = []
        self._monitor = ConservationMonitor(
            drift_threshold=drift_threshold,
            reset_callback=self._on_energy_reset,
        )

        # Task queue and memory
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.memory: Dict[str, Any] = {}

        logger.info(
            "Agent created: id=%s, type=%s, n_dims=%d",
            self.agent_id,
            self.agent_type,
            n_dims,
        )

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a task and return a structured TaskResult.

        Must be implemented by every concrete agent subclass.

        Parameters
        ----------
        task : dict
            Task specification with at least keys: 'task_id', 'type', 'payload'.

        Returns
        -------
        TaskResult
        """

    # ------------------------------------------------------------------
    # Phase-space management
    # ------------------------------------------------------------------

    def update_phase_state(self, new_q: torch.Tensor, new_p: torch.Tensor) -> float:
        """
        Update the agent's phase-space coordinates and log the energy.

        Parameters
        ----------
        new_q, new_p : torch.Tensor
            New generalized coordinates and momenta.

        Returns
        -------
        float
            Current Hamiltonian value H(q, p).
        """
        self.phase_state = PhaseSpaceState(
            q=new_q.clone(), p=new_p.clone(), agent_id=self.agent_id
        )
        H = float(self.hamiltonian.total_energy(new_q, new_p).item())
        self.energy_history.append(H)
        self._monitor.record(H)
        logger.debug("Agent %s phase state updated: H=%.6f", self.agent_id, H)
        return H

    def check_stability(self) -> bool:
        """
        Check whether the agent's energy is conserved within tolerance.

        Returns
        -------
        bool
            True if stable.

        Raises
        ------
        AgentDriftException
            If energy drift exceeds the monitor threshold.
        """
        if not self._monitor.is_stable():
            drift = self._monitor.energy_drift_score()
            logger.warning(
                "Agent %s unstable! drift=%.4f", self.agent_id, drift
            )
            raise AgentDriftException(
                f"Agent {self.agent_id} energy drift {drift:.4f} exceeds threshold."
            )
        return True

    def _on_energy_reset(self) -> None:
        """Callback fired by ConservationMonitor when drift exceeds critical level."""
        logger.error(
            "CRITICAL energy drift detected in agent %s — resetting phase state.",
            self.agent_id,
        )
        # Reset to origin with zero energy
        q0 = torch.zeros(self.n_dims)
        p0 = torch.zeros(self.n_dims)
        self.phase_state = PhaseSpaceState(q=q0, p=p0, agent_id=self.agent_id)
        self._monitor.reset()

    # ------------------------------------------------------------------
    # Serialization (for handoffs)
    # ------------------------------------------------------------------

    def serialize_state(self) -> Dict[str, Any]:
        """
        Serialize agent state for handoff or checkpointing.

        Returns
        -------
        dict
            Contains agent_id, agent_type, q, p, energy_history snapshot.
        """
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "q": self.phase_state.q.tolist(),
            "p": self.phase_state.p.tolist(),
            "energy_history": self.energy_history[-10:],
            "status": self.status.name,
            "memory": {k: str(v) for k, v in self.memory.items()},
        }

    def deserialize_state(self, state_dict: Dict[str, Any]) -> None:
        """
        Restore agent state from a serialized dict (e.g., after handoff).

        Parameters
        ----------
        state_dict : dict
            Previously produced by serialize_state().
        """
        q = torch.tensor(state_dict["q"], dtype=torch.float32)
        p = torch.tensor(state_dict["p"], dtype=torch.float32)
        self.phase_state = PhaseSpaceState(q=q, p=p, agent_id=self.agent_id)
        self.energy_history.extend(state_dict.get("energy_history", []))
        self.memory.update(state_dict.get("memory", {}))
        logger.info(
            "Agent %s state restored from handoff (source=%s).",
            self.agent_id,
            state_dict.get("agent_id", "unknown"),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main async loop: dequeue and execute tasks until TERMINATED."""
        self.status = AgentStatus.RUNNING
        logger.info("Agent %s started.", self.agent_id)
        while self.status != AgentStatus.TERMINATED:
            try:
                task = await asyncio.wait_for(self.task_queue.get(), timeout=5.0)
                self.status = AgentStatus.RUNNING
                result = await self.execute_task(task)
                self.task_queue.task_done()
                self.check_stability()
                logger.info(
                    "Agent %s completed task %s: success=%s",
                    self.agent_id,
                    task.get("task_id", "?"),
                    result.success,
                )
            except asyncio.TimeoutError:
                self.status = AgentStatus.IDLE
            except AgentDriftException as e:
                logger.error("AgentDriftException in agent %s: %s", self.agent_id, e)
                raise

    def terminate(self) -> None:
        """Gracefully terminate the agent."""
        self.status = AgentStatus.TERMINATED
        logger.info("Agent %s terminated.", self.agent_id)

    def __repr__(self) -> str:
        return (
            f"{self.agent_type}Agent(id={self.agent_id}, "
            f"status={self.status.name}, "
            f"H={self.energy_history[-1]:.4f if self.energy_history else 'N/A'})"
        )
