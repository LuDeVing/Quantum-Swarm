"""
QPSO-powered search and optimization agent.

Wraps QPSO internally and updates its own phase-space state using the
search result as the new position coordinate.
"""

from __future__ import annotations
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import torch

from .base_agent import BaseAgent, TaskResult
from ..quantum.qpso import QPSO
from ..quantum.quantum_tunneling import QuantumTunneling

logger = logging.getLogger(__name__)


class SearchAgent(BaseAgent):
    """
    Optimization agent powered by QPSO.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality.
    n_particles : int
        QPSO swarm size.
    n_iterations : int
        QPSO iterations per search call.
    stagnation_limit : int
        Iterations without improvement before tunneling is triggered.
    """

    def __init__(
        self,
        n_dims: int = 4,
        n_particles: int = 30,
        n_iterations: int = 100,
        stagnation_limit: int = 10,
        **kwargs: Any,
    ) -> None:
        super().__init__(n_dims=n_dims, agent_type="search", **kwargs)
        self.n_particles = n_particles
        self.n_iterations = n_iterations
        self.stagnation_limit = stagnation_limit
        self.tunneling = QuantumTunneling()

        # Track stagnation for tunneling trigger
        self._last_best_value: float = float("inf")
        self._stagnation_counter: int = 0

        logger.info(
            "SearchAgent %s created: n_particles=%d, n_iterations=%d",
            self.agent_id,
            n_particles,
            n_iterations,
        )

    def search(
        self,
        objective_fn: Callable[[np.ndarray], float],
        bounds: Optional[Tuple[np.ndarray, np.ndarray]] = None,
        n_particles: Optional[int] = None,
        n_iterations: Optional[int] = None,
    ) -> Tuple[np.ndarray, float, List[float]]:
        """
        Run QPSO search and update this agent's phase-space state.

        Parameters
        ----------
        objective_fn : callable
            Function to minimize: f(x: np.ndarray) → float.
        bounds : tuple, optional
            (lower_bounds, upper_bounds), each shape [n_dims].
        n_particles : int, optional
            Override default swarm size.
        n_iterations : int, optional
            Override default iterations.

        Returns
        -------
        best_position : np.ndarray
        best_value : float
        convergence_history : list of float
        """
        n_p = n_particles or self.n_particles
        n_it = n_iterations or self.n_iterations

        # Check stagnation, enable tunneling if stuck
        tunneling = None
        if self._stagnation_counter >= self.stagnation_limit:
            logger.info(
                "SearchAgent %s stagnated for %d iterations — activating tunneling.",
                self.agent_id,
                self._stagnation_counter,
            )
            tunneling = self.tunneling

        qpso = QPSO(
            n_particles=n_p,
            n_dims=self.n_dims,
            bounds=bounds,
            n_iterations=n_it,
        )
        best_pos, best_val, history = qpso.optimize(objective_fn, tunneling=tunneling)

        # Update stagnation counter
        if best_val < self._last_best_value - 1e-6:
            self._stagnation_counter = 0
            self._last_best_value = best_val
        else:
            self._stagnation_counter += 1

        # Update phase-space state: use best_pos as q, gradient as p
        n = min(self.n_dims, len(best_pos))
        new_q = torch.zeros(self.n_dims)
        new_q[:n] = torch.tensor(best_pos[:n], dtype=torch.float32)
        new_p = torch.zeros(self.n_dims)
        # Encode search result quality as momentum magnitude
        new_p[:n] = torch.tensor(
            np.gradient(history[-min(n, len(history)):]) * 0.1
            if len(history) >= n else np.zeros(n),
            dtype=torch.float32,
        )
        self.update_phase_state(new_q, new_p)

        logger.info(
            "SearchAgent %s search complete: best_value=%.6f", self.agent_id, best_val
        )
        return best_pos, best_val, history

    async def search_async(
        self,
        objective_fn: Callable[[np.ndarray], float],
        bounds: Optional[Tuple[np.ndarray, np.ndarray]] = None,
        n_particles: Optional[int] = None,
        n_iterations: Optional[int] = None,
    ) -> Tuple[np.ndarray, float, List[float]]:
        """Async wrapper for non-blocking orchestrator use."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.search(objective_fn, bounds, n_particles, n_iterations),
        )

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a search task.

        Task payload must contain:
          - 'objective_fn': callable
          - 'bounds': optional tuple (lb, ub)

        Returns
        -------
        TaskResult with output = {'best_position', 'best_value', 'history'}
        """
        task_id = task.get("task_id", "unknown")
        H_before = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )

        objective_fn = task.get("objective_fn")
        bounds = task.get("bounds", None)

        if objective_fn is None:
            return TaskResult(
                task_id=task_id,
                agent_id=self.agent_id,
                success=False,
                output={"error": "No objective_fn provided."},
                energy_before=H_before,
                energy_after=H_before,
            )

        best_pos, best_val, history = await self.search_async(objective_fn, bounds)

        H_after = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )
        return TaskResult(
            task_id=task_id,
            agent_id=self.agent_id,
            success=True,
            output={
                "best_position": best_pos.tolist(),
                "best_value": best_val,
                "history": history,
            },
            energy_before=H_before,
            energy_after=H_after,
        )
