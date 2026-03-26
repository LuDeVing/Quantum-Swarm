"""
Master orchestrator (conductor) agent.

Responsibilities:
  - Decompose high-level tasks into subtasks
  - Assign subtasks to agents via QPSO-based fitness optimization
  - Monitor swarm health and trigger rebalancing
  - Log total swarm energy H_total = Σ H_i(q_i, p_i)
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import torch

from .base_agent import BaseAgent, AgentDriftException, TaskResult
from ..quantum.qpso import QPSO
from ..coordination.shared_belief_state import SharedBeliefState

logger = logging.getLogger(__name__)


@dataclass
class SubTask:
    """A decomposed subtask with metadata."""
    task_id: str
    task_type: str
    payload: Dict[str, Any]
    required_capability: str = "general"
    h_required: float = 1.0          # Expected Hamiltonian energy for this task
    complexity: float = 0.5
    assigned_agent_id: Optional[str] = None
    status: str = "pending"          # pending | assigned | complete | failed
    result: Optional[TaskResult] = None


class Orchestrator(BaseAgent):
    """
    Master orchestrator that coordinates all swarm agents.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality of the orchestrator itself.
    capability_weights : dict, optional
        Mapping from agent_type to capability score for fitness.
    """

    def __init__(
        self,
        n_dims: int = 8,
        capability_weights: Optional[Dict[str, float]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(n_dims=n_dims, agent_type="orchestrator", **kwargs)
        self._agents: Dict[str, BaseAgent] = {}
        self._subtask_history: List[SubTask] = []
        self.capability_weights = capability_weights or {
            "search": 1.0,
            "task": 0.8,
            "memory": 0.7,
            "validator": 0.6,
        }
        self._health_monitor_running = False
        logger.info("Orchestrator %s initialized.", self.agent_id)

    # ------------------------------------------------------------------
    # Agent registry
    # ------------------------------------------------------------------

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent with the orchestrator."""
        self._agents[agent.agent_id] = agent
        logger.info(
            "Orchestrator: registered agent %s (type=%s).",
            agent.agent_id,
            agent.agent_type,
        )

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the registry."""
        self._agents.pop(agent_id, None)
        logger.info("Orchestrator: unregistered agent %s.", agent_id)

    # ------------------------------------------------------------------
    # Task decomposition
    # ------------------------------------------------------------------

    def decompose_task(self, high_level_task: Dict[str, Any]) -> List[SubTask]:
        """
        Decompose a high-level task description into concrete SubTasks.

        Uses a rule-based engine based on task type keywords.
        Each subtask gets a unique task_id and is tagged with required_capability.

        Parameters
        ----------
        high_level_task : dict
            Must contain 'description' (str) and optionally 'subtasks' (list).

        Returns
        -------
        list of SubTask
        """
        description = str(high_level_task.get("description", ""))
        explicit_subtasks = high_level_task.get("subtasks", [])

        if explicit_subtasks:
            subtasks = [
                SubTask(
                    task_id=str(uuid.uuid4())[:8],
                    task_type=st.get("type", "generic"),
                    payload=st.get("payload", {}),
                    required_capability=st.get("capability", "general"),
                    h_required=float(st.get("h_required", 1.0)),
                    complexity=float(st.get("complexity", 0.5)),
                )
                for st in explicit_subtasks
            ]
        else:
            # Rule-based decomposition from description keywords
            subtasks = []
            keywords_to_capabilities = {
                "search": "search",
                "find": "search",
                "optimize": "search",
                "remember": "memory",
                "store": "memory",
                "recall": "memory",
                "validate": "validator",
                "check": "validator",
                "plan": "task",
                "execute": "task",
            }
            for keyword, capability in keywords_to_capabilities.items():
                if keyword.lower() in description.lower():
                    subtasks.append(
                        SubTask(
                            task_id=str(uuid.uuid4())[:8],
                            task_type=capability,
                            payload={"description": description, "keyword": keyword},
                            required_capability=capability,
                            h_required=1.0,
                            complexity=0.5,
                        )
                    )
            # Always include a generic task if nothing matched
            if not subtasks:
                subtasks.append(
                    SubTask(
                        task_id=str(uuid.uuid4())[:8],
                        task_type="generic",
                        payload={"description": description},
                        required_capability="task",
                        h_required=1.0,
                    )
                )

        logger.info(
            "Orchestrator decomposed task into %d subtasks.", len(subtasks)
        )
        self._subtask_history.extend(subtasks)
        return subtasks

    # ------------------------------------------------------------------
    # QPSO-based agent assignment
    # ------------------------------------------------------------------

    def _capability_match(self, agent: BaseAgent, subtask: SubTask) -> float:
        """Score how well an agent matches a subtask's required capability."""
        return self.capability_weights.get(
            agent.agent_type, 0.5
        ) if agent.agent_type == subtask.required_capability else 0.3

    def _current_load(self, agent: BaseAgent) -> float:
        """Normalize current task queue size to [0, 1]."""
        return min(agent.task_queue.qsize() / 10.0, 1.0)

    def _energy_compatibility(self, agent: BaseAgent, subtask: SubTask) -> float:
        """Score energy compatibility: how close agent's H is to required H."""
        H_agent = float(
            agent.hamiltonian.total_energy(
                agent.phase_state.q, agent.phase_state.p
            ).item()
        )
        return 1.0 / (1.0 + abs(H_agent - subtask.h_required))

    def assign_task(
        self,
        subtask: SubTask,
        w1: float = 1.0,
        w2: float = 0.5,
        w3: float = 0.3,
    ) -> Optional[BaseAgent]:
        """
        Select the best agent for a subtask using QPSO over a fitness function.

        Fitness:
            f(agent, task) = w1 * capability_match
                           - w2 * current_load
                           + w3 * energy_compatibility

        If fewer than 2 agents are registered, falls back to greedy selection.

        Parameters
        ----------
        subtask : SubTask
        w1, w2, w3 : float
            Weighting coefficients for fitness components.

        Returns
        -------
        BaseAgent or None
        """
        agents = list(self._agents.values())
        if not agents:
            logger.error("No agents registered with orchestrator.")
            return None

        if len(agents) == 1:
            selected = agents[0]
            subtask.assigned_agent_id = selected.agent_id
            return selected

        # Adapt w3 based on total swarm energy:
        # high H_total → swarm is chaotic → prefer stable agents (raise w3)
        H_total = self.log_swarm_energy()
        H_per_agent = H_total / max(len(agents), 1)
        w3_adaptive = w3 * (1.0 + min(H_per_agent, 2.0))

        # Build fitness function over agent indices
        agent_list = agents

        def fitness(x: np.ndarray) -> float:
            # Map continuous x[0] to nearest agent index
            idx = int(np.clip(round(x[0] * (len(agent_list) - 1)), 0, len(agent_list) - 1))
            agent = agent_list[idx]
            cap = self._capability_match(agent, subtask)
            load = self._current_load(agent)
            energy_compat = self._energy_compatibility(agent, subtask)
            # Negative because QPSO minimizes
            return -(w1 * cap - w2 * load + w3_adaptive * energy_compat)

        qpso = QPSO(
            n_particles=min(10, len(agent_list) * 2),
            n_dims=1,
            bounds=(np.array([0.0]), np.array([1.0])),
            n_iterations=50,
        )
        best_x, _, _ = qpso.optimize(fitness)
        best_idx = int(np.clip(round(best_x[0] * (len(agent_list) - 1)), 0, len(agent_list) - 1))
        selected = agent_list[best_idx]
        subtask.assigned_agent_id = selected.agent_id

        logger.info(
            "Orchestrator assigned subtask %s to agent %s (type=%s) via QPSO.",
            subtask.task_id,
            selected.agent_id,
            selected.agent_type,
        )
        return selected

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    async def monitor_swarm_health(self, interval: float = 5.0) -> None:
        """
        Async loop that checks all agent energy_drift_scores.

        Triggers rebalancing if any agent is unstable.

        Parameters
        ----------
        interval : float
            Check interval in seconds.
        """
        self._health_monitor_running = True
        while self._health_monitor_running:
            await asyncio.sleep(interval)
            unstable_agents = []
            for agent_id, agent in self._agents.items():
                try:
                    agent.check_stability()
                except AgentDriftException as e:
                    unstable_agents.append(agent_id)
                    logger.warning(
                        "Swarm health: agent %s is unstable — %s", agent_id, e
                    )

            if unstable_agents:
                await self.trigger_rebalance(unstable_agents)

            self.log_swarm_energy()

    async def trigger_rebalance(self, unstable_agent_ids: List[str]) -> None:
        """
        Redistribute tasks from unstable agents to stable ones.

        Parameters
        ----------
        unstable_agent_ids : list of str
            Agents that are energy-unstable.
        """
        stable_agents = [
            a for aid, a in self._agents.items()
            if aid not in unstable_agent_ids
        ]
        if not stable_agents:
            logger.error("No stable agents available for rebalancing!")
            return

        for agent_id in unstable_agent_ids:
            agent = self._agents.get(agent_id)
            if agent is None:
                continue
            # Drain the unstable agent's queue into stable agents
            tasks_moved = 0
            while not agent.task_queue.empty():
                try:
                    task = agent.task_queue.get_nowait()
                    target = stable_agents[tasks_moved % len(stable_agents)]
                    await target.task_queue.put(task)
                    tasks_moved += 1
                except asyncio.QueueEmpty:
                    break
            logger.info(
                "Rebalanced %d tasks from unstable agent %s.", tasks_moved, agent_id
            )

    def log_swarm_energy(self) -> float:
        """
        Compute total swarm energy H_total = Σ H_i(q_i, p_i).

        Returns
        -------
        float
            Sum of all agent Hamiltonian values.
        """
        H_total = 0.0
        for agent in self._agents.values():
            H_i = float(
                agent.hamiltonian.total_energy(
                    agent.phase_state.q, agent.phase_state.p
                ).item()
            )
            H_total += H_i

        H_self = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )
        H_total += H_self

        logger.info(
            "Swarm energy: H_total=%.4f, n_agents=%d", H_total, len(self._agents)
        )
        return H_total

    def stop_health_monitor(self) -> None:
        """Stop the health monitoring loop."""
        self._health_monitor_running = False

    def _qpso_sync_agents(self) -> None:
        """Pull all agent phase-space positions toward the swarm global best.

        Implements the QPSO position update rule directly:
            local_attractor = φ·q + (1-φ)·q_gbest
            q_new = local_attractor ± β·|q_mbest - q|·log(1/u)

        The global best agent is the one whose energy has drifted least
        from its initial value (most stable = most reliable belief).
        """
        agents = [a for a in self._agents.values() if a.energy_history]
        if len(agents) < 2:
            return

        gbest_agent = min(
            agents,
            key=lambda a: abs(a.energy_history[-1] - a.energy_history[0]),
        )
        gbest_q = gbest_agent.phase_state.q
        mbest_q = torch.stack([a.phase_state.q for a in agents]).mean(dim=0)

        beta = 0.5
        for agent in agents:
            if agent.agent_id == gbest_agent.agent_id:
                continue
            phi  = torch.rand(agent.n_dims)
            u    = torch.rand(agent.n_dims).clamp(min=1e-8)
            sign = torch.sign(torch.rand(agent.n_dims) - 0.5)
            local_attractor = phi * agent.phase_state.q + (1.0 - phi) * gbest_q
            delta = beta * (mbest_q - agent.phase_state.q).abs() * torch.log(1.0 / u)
            q_new = local_attractor + sign * delta
            agent.update_phase_state(q_new, agent.phase_state.p)

        logger.debug(
            "QPSO sync complete: gbest_agent=%s, %d agents updated.",
            gbest_agent.agent_id,
            len(agents) - 1,
        )

    # ------------------------------------------------------------------
    # Task interface
    # ------------------------------------------------------------------

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute an orchestration task: decompose and dispatch subtasks.

        Parameters
        ----------
        task : dict
            High-level task description.

        Returns
        -------
        TaskResult
        """
        task_id = task.get("task_id", str(uuid.uuid4())[:8])
        H_before = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )

        # Initialise shared belief state for this task
        hypotheses = task.get("hypotheses", ["success", "failure"])
        shared_belief = SharedBeliefState(
            hypotheses=hypotheses,
            agent_ids=list(self._agents.keys()),
        )

        subtasks = self.decompose_task(task)
        results = []

        for subtask in subtasks:
            agent = self.assign_task(subtask)
            if agent is not None:
                await agent.task_queue.put(
                    {
                        "task_id": subtask.task_id,
                        "type": subtask.task_type,
                        "payload": subtask.payload,
                        "complexity": subtask.complexity,
                        "hypotheses": hypotheses,
                        "_shared_belief": shared_belief,
                    }
                )
                results.append(
                    {
                        "subtask_id": subtask.task_id,
                        "assigned_to": agent.agent_id,
                        "type": subtask.task_type,
                    }
                )

        # Sync all agent positions toward swarm global best via QPSO update
        self._qpso_sync_agents()

        H_after = self.step_phase_state(dt=0.01)

        # Collapse shared belief to a single answer
        final_answer = shared_belief.collapse()

        return TaskResult(
            task_id=task_id,
            agent_id=self.agent_id,
            success=True,
            output={
                "subtasks_dispatched": len(results),
                "assignments": results,
                "final_answer": final_answer,
                "belief_entropy": shared_belief.entropy(),
            },
            energy_before=H_before,
            energy_after=H_after,
        )
