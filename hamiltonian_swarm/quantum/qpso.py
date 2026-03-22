"""
Quantum-Behaved Particle Swarm Optimization (QPSO).

QPSO replaces velocity with a quantum potential well, giving particles
the ability to sample the entire search space and escape local optima.

Core quantum update:
    φ  ~ Uniform(0, 1)
    p_i = φ * pbest_i + (1 - φ) * gbest          (local attractor)
    mbest = (1/N) Σ pbest_i(t)                     (mean best)
    u  ~ Uniform(0, 1)
    x_i(t+1) = p_i ± α * |mbest - x_i| * ln(1/u)  (quantum jump)
    Sign: + if rand() > 0.5, else -

Contraction-expansion coefficient annealing:
    α(t) = α_max - (α_max - α_min) * t / T
"""

from __future__ import annotations
import asyncio
import logging
from typing import Callable, List, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)


class QPSO:
    """
    Quantum-Behaved Particle Swarm Optimizer.

    Parameters
    ----------
    n_particles : int
        Swarm size.
    n_dims : int
        Search space dimensionality.
    bounds : tuple of (lower, upper) arrays
        Each array has shape [n_dims]. Defines search bounds per dimension.
    n_iterations : int
        Maximum number of iterations.
    alpha_max : float
        Maximum contraction-expansion coefficient.
    alpha_min : float
        Minimum contraction-expansion coefficient.
    topology : str
        Neighbourhood topology: 'global' (default), 'ring', 'star'.
    """

    def __init__(
        self,
        n_particles: int = 30,
        n_dims: int = 10,
        bounds: Optional[Tuple[np.ndarray, np.ndarray]] = None,
        n_iterations: int = 500,
        alpha_max: float = 1.0,
        alpha_min: float = 0.5,
        topology: str = "global",
    ) -> None:
        self.n_particles = n_particles
        self.n_dims = n_dims
        self.n_iterations = n_iterations
        self.alpha_max = alpha_max
        self.alpha_min = alpha_min
        self.topology = topology

        if bounds is None:
            lb = np.full(n_dims, -10.0)
            ub = np.full(n_dims, 10.0)
            self.bounds = (lb, ub)
        else:
            self.bounds = bounds

        self.lb = np.array(self.bounds[0], dtype=np.float64)
        self.ub = np.array(self.bounds[1], dtype=np.float64)

        # State (initialized on first optimize call)
        self.positions: np.ndarray = np.empty(0)
        self.pbest: np.ndarray = np.empty(0)
        self.pbest_values: np.ndarray = np.empty(0)
        self.gbest: np.ndarray = np.empty(0)
        self.gbest_value: float = float("inf")

        # History
        self.convergence_history: List[float] = []
        self.diversity_history: List[float] = []
        self.mbest_history: List[np.ndarray] = []

        logger.info(
            "QPSO initialized: n_particles=%d, n_dims=%d, n_iter=%d, topology=%s",
            n_particles,
            n_dims,
            n_iterations,
            topology,
        )

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize_particles(self) -> None:
        """Uniformly initialize all particles within bounds."""
        self.positions = self.lb + np.random.rand(self.n_particles, self.n_dims) * (
            self.ub - self.lb
        )
        self.pbest = self.positions.copy()
        self.pbest_values = np.full(self.n_particles, float("inf"))
        self.gbest = self.positions[0].copy()
        self.gbest_value = float("inf")
        logger.debug("Particles initialized within bounds.")

    # ------------------------------------------------------------------
    # MBest
    # ------------------------------------------------------------------

    def update_mbest(self) -> np.ndarray:
        """
        Compute Mean Best Position (MBest):
            mbest(t) = (1/N) Σ pbest_i(t)

        Returns
        -------
        np.ndarray
            Shape [n_dims].
        """
        return self.pbest.mean(axis=0)

    # ------------------------------------------------------------------
    # Particle update
    # ------------------------------------------------------------------

    def _alpha(self, t: int) -> float:
        """
        Linearly annealed contraction-expansion coefficient:
            α(t) = α_max - (α_max - α_min) * t / T
        """
        return self.alpha_max - (self.alpha_max - self.alpha_min) * t / self.n_iterations

    def _get_local_best(self, i: int) -> np.ndarray:
        """Return the local best position for particle i given topology."""
        if self.topology == "global":
            return self.gbest
        elif self.topology == "ring":
            left = (i - 1) % self.n_particles
            right = (i + 1) % self.n_particles
            candidates = [i, left, right]
            best_idx = candidates[
                int(np.argmin([self.pbest_values[c] for c in candidates]))
            ]
            return self.pbest[best_idx]
        elif self.topology == "star":
            # Particle 0 is the hub
            hub_val = self.pbest_values[0]
            own_val = self.pbest_values[i]
            return self.pbest[0] if hub_val < own_val else self.pbest[i]
        else:
            return self.gbest

    def update_particle(self, i: int, t: int) -> None:
        """
        Apply quantum position update to particle i at iteration t.

        Quantum update equations:
            φ  ~ U(0,1)
            p_i = φ * pbest_i + (1 - φ) * lbest
            u  ~ U(0,1)
            sign = +1 if rand() > 0.5 else -1
            x_i = p_i + sign * α * |mbest - x_i| * ln(1/u)

        Parameters
        ----------
        i : int
            Particle index.
        t : int
            Current iteration.
        """
        alpha = self._alpha(t)
        lbest = self._get_local_best(i)
        mbest = self.update_mbest()

        phi = np.random.rand(self.n_dims)
        local_attractor = phi * self.pbest[i] + (1.0 - phi) * lbest

        u = np.random.rand(self.n_dims)
        u = np.clip(u, 1e-300, 1.0)  # avoid log(0)
        sign = np.where(np.random.rand(self.n_dims) > 0.5, 1.0, -1.0)

        delta = alpha * np.abs(mbest - self.positions[i]) * np.log(1.0 / u)
        self.positions[i] = local_attractor + sign * delta

        # Clip to bounds
        self.positions[i] = np.clip(self.positions[i], self.lb, self.ub)

    # ------------------------------------------------------------------
    # Main optimize loop
    # ------------------------------------------------------------------

    def optimize(
        self,
        objective_fn: Callable[[np.ndarray], float],
        tunneling=None,
    ) -> Tuple[np.ndarray, float, List[float]]:
        """
        Run QPSO optimization.

        Parameters
        ----------
        objective_fn : callable
            f(x: np.ndarray) → float, to be minimized.
        tunneling : QuantumTunneling, optional
            If provided, applies tunneling escape for stuck particles.

        Returns
        -------
        best_position : np.ndarray
            Shape [n_dims].
        best_value : float
            Objective function value at best_position.
        convergence_history : list of float
            gbest value at each iteration.
        """
        self.initialize_particles()
        self.convergence_history = []
        self.diversity_history = []
        self.mbest_history = []

        # Evaluate initial positions
        for i in range(self.n_particles):
            val = objective_fn(self.positions[i])
            self.pbest_values[i] = val
            if val < self.gbest_value:
                self.gbest_value = val
                self.gbest = self.positions[i].copy()

        stagnation_counter = np.zeros(self.n_particles, dtype=int)

        for t in range(self.n_iterations):
            mbest = self.update_mbest()
            self.mbest_history.append(mbest.copy())

            for i in range(self.n_particles):
                self.update_particle(i, t)
                val = objective_fn(self.positions[i])

                # Tunneling escape from local optima
                if tunneling is not None and stagnation_counter[i] > 10:
                    if tunneling.should_tunnel(
                        current_value=val,
                        local_min_value=self.pbest_values[i],
                        barrier_estimate=abs(self.gbest_value - self.pbest_values[i]) + 1e-6,
                    ):
                        # Random perturbation = tunneling jump
                        self.positions[i] = self.lb + np.random.rand(self.n_dims) * (
                            self.ub - self.lb
                        )
                        val = objective_fn(self.positions[i])
                        stagnation_counter[i] = 0
                        logger.info("Particle %d tunneled at iteration %d.", i, t)

                if val < self.pbest_values[i]:
                    self.pbest_values[i] = val
                    self.pbest[i] = self.positions[i].copy()
                    stagnation_counter[i] = 0
                else:
                    stagnation_counter[i] += 1

                if val < self.gbest_value:
                    self.gbest_value = val
                    self.gbest = self.positions[i].copy()

            self.convergence_history.append(self.gbest_value)

            # Diversity: mean pairwise spread
            diversity = float(np.std(self.positions, axis=0).mean())
            self.diversity_history.append(diversity)

            if t % 50 == 0:
                logger.info(
                    "QPSO iter=%d/%d, gbest=%.6f, diversity=%.4f, alpha=%.4f",
                    t,
                    self.n_iterations,
                    self.gbest_value,
                    diversity,
                    self._alpha(t),
                )

        logger.info(
            "QPSO complete: best_value=%.6f after %d iterations.",
            self.gbest_value,
            self.n_iterations,
        )
        return self.gbest.copy(), self.gbest_value, self.convergence_history

    async def optimize_async(
        self,
        objective_fn: Callable[[np.ndarray], float],
        tunneling=None,
    ) -> Tuple[np.ndarray, float, List[float]]:
        """
        Async wrapper around optimize() for non-blocking agent use.

        Runs the synchronous optimize in a thread pool executor.
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self.optimize(objective_fn, tunneling)
        )
        return result
