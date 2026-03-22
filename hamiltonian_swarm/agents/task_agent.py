"""
Generic task-execution agent.

Handles arbitrary payload tasks and updates its phase-space state
proportionally to task complexity.
"""

from __future__ import annotations
import logging
from typing import Any, Dict

import torch

from .base_agent import BaseAgent, TaskResult

logger = logging.getLogger(__name__)


class TaskAgent(BaseAgent):
    """
    A general-purpose agent that executes structured tasks.

    The agent encodes task complexity as phase-space momentum magnitude.
    """

    def __init__(self, n_dims: int = 4, **kwargs: Any) -> None:
        super().__init__(n_dims=n_dims, agent_type="task", **kwargs)

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a generic task payload.

        The 'complexity' key (float 0-1) scales how much the agent's
        phase-space momentum changes during execution.

        Parameters
        ----------
        task : dict
            Keys: 'task_id', 'type', 'payload', 'complexity' (optional, default 0.5).

        Returns
        -------
        TaskResult
        """
        task_id = task.get("task_id", "unknown")
        complexity = float(task.get("complexity", 0.5))
        payload = task.get("payload", {})

        H_before = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )

        # Simulate work: nudge phase state proportional to complexity
        dq = torch.randn(self.n_dims) * complexity * 0.1
        dp = torch.randn(self.n_dims) * complexity * 0.2
        new_q = self.phase_state.q + dq
        new_p = self.phase_state.p + dp
        H_after = self.update_phase_state(new_q, new_p)

        result_output = {"processed": True, "payload_keys": list(payload.keys())}
        logger.info(
            "TaskAgent %s executed task %s: complexity=%.2f, ΔH=%.4f",
            self.agent_id,
            task_id,
            complexity,
            H_after - H_before,
        )

        return TaskResult(
            task_id=task_id,
            agent_id=self.agent_id,
            success=True,
            output=result_output,
            energy_before=H_before,
            energy_after=H_after,
        )
