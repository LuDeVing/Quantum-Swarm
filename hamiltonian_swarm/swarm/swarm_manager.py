"""
Swarm lifecycle and topology management.

SwarmManager bootstraps the swarm, manages agent lifecycles, and provides
a unified interface for submitting tasks to the swarm.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional, Type

from ..agents.base_agent import BaseAgent, TaskResult
from ..agents.orchestrator import Orchestrator
from ..agents.task_agent import TaskAgent
from ..agents.search_agent import SearchAgent
from ..agents.memory_agent import MemoryAgent
from ..agents.validator_agent import ValidatorAgent
from .communication_bus import CommunicationBus
from .topology import SwarmTopology, TopologyType
from .handoff_protocol import HandoffProtocol

logger = logging.getLogger(__name__)

_AGENT_REGISTRY: Dict[str, Type[BaseAgent]] = {
    "task": TaskAgent,
    "search": SearchAgent,
    "memory": MemoryAgent,
    "validator": ValidatorAgent,
}


class SwarmManager:
    """
    Top-level swarm lifecycle manager.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality for all agents.
    topology_type : TopologyType
        Swarm neighbourhood topology.
    backpressure_limit : int
        Message bus backpressure threshold.
    """

    def __init__(
        self,
        n_dims: int = 4,
        topology_type: TopologyType = TopologyType.FULLY_CONNECTED,
        backpressure_limit: int = 100,
    ) -> None:
        self.n_dims = n_dims
        self.topology_type = topology_type
        self.bus = CommunicationBus(backpressure_limit=backpressure_limit)
        self.handoff_protocol = HandoffProtocol()
        self.orchestrator = Orchestrator(n_dims=n_dims)
        self.bus.register_agent(self.orchestrator.agent_id)
        self._agents: Dict[str, BaseAgent] = {}
        self._topology: Optional[SwarmTopology] = None
        self._running_tasks: List[asyncio.Task] = []
        logger.info("SwarmManager initialized: n_dims=%d, topology=%s", n_dims, topology_type.name)

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def spawn_agent(
        self,
        agent_type: str = "task",
        n_dims: Optional[int] = None,
        **kwargs: Any,
    ) -> BaseAgent:
        """
        Instantiate and register a new agent.

        Parameters
        ----------
        agent_type : str
            One of 'task', 'search', 'memory', 'validator'.
        n_dims : int, optional
            Override swarm-wide n_dims.

        Returns
        -------
        BaseAgent
        """
        cls = _AGENT_REGISTRY.get(agent_type, TaskAgent)
        agent = cls(n_dims=n_dims or self.n_dims, **kwargs)
        self._agents[agent.agent_id] = agent
        self.orchestrator.register_agent(agent)
        self.bus.register_agent(agent.agent_id)

        # Rebuild topology with new agent count
        n = len(self._agents) + 1  # +1 for orchestrator
        self._topology = SwarmTopology(n, self.topology_type)

        logger.info("Spawned %s agent: %s", agent_type, agent.agent_id)
        return agent

    def terminate_agent(self, agent_id: str) -> None:
        """Gracefully terminate and remove an agent."""
        agent = self._agents.pop(agent_id, None)
        if agent:
            agent.terminate()
            self.orchestrator.unregister_agent(agent_id)
            self.bus.unregister_agent(agent_id)
            logger.info("Terminated agent %s.", agent_id)

    # ------------------------------------------------------------------
    # Task submission
    # ------------------------------------------------------------------

    async def submit_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Submit a high-level task to the orchestrator.

        The orchestrator will decompose and dispatch to agents.

        Parameters
        ----------
        task : dict
            High-level task specification.

        Returns
        -------
        TaskResult
            Orchestrator's result (includes assignment info).
        """
        return await self.orchestrator.execute_task(task)

    # ------------------------------------------------------------------
    # Swarm startup/shutdown
    # ------------------------------------------------------------------

    async def start(self, agent_types: Optional[List[str]] = None) -> None:
        """
        Start the swarm with a default set of agents.

        Parameters
        ----------
        agent_types : list of str, optional
            Agent types to spawn. Defaults to ['task', 'search', 'memory', 'validator'].
        """
        types = agent_types or ["task", "search", "memory", "validator"]
        for atype in types:
            agent = self.spawn_agent(atype)
            task = asyncio.create_task(agent.run(), name=f"agent_{agent.agent_id}")
            self._running_tasks.append(task)

        # Start orchestrator health monitor
        health_task = asyncio.create_task(
            self.orchestrator.monitor_swarm_health(interval=10.0),
            name="health_monitor",
        )
        self._running_tasks.append(health_task)
        logger.info("Swarm started with %d agents.", len(self._agents))

    async def shutdown(self) -> None:
        """Gracefully shut down all agents and cancel background tasks."""
        self.orchestrator.stop_health_monitor()
        for agent_id in list(self._agents.keys()):
            self.terminate_agent(agent_id)
        for task in self._running_tasks:
            task.cancel()
        self._running_tasks.clear()
        logger.info("Swarm shutdown complete.")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return a summary of swarm state."""
        return {
            "n_agents": len(self._agents),
            "agents": [a.serialize_state() for a in self._agents.values()],
            "orchestrator": self.orchestrator.serialize_state(),
            "bus_stats": self.bus.get_stats(),
            "topology_energy": self._topology.topology_energy() if self._topology else None,
            "swarm_energy": self.orchestrator.log_swarm_energy(),
        }
