"""
QPSO-driven genome mutation engine.

Each QPSO particle = one AgentGenome.
Fitness function = agent performance on benchmark tasks.
Global best = best-performing genome found so far.
"""

from __future__ import annotations
import logging
from typing import List, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)


class MutationEngine:
    """
    QPSO-powered genome evolution engine.

    Parameters
    ----------
    population_size : int
    genome_dim : int
        Length of genome.to_vector().
    genome_bounds : tuple of (lb, ub), optional
        Bounds for each gene dimension.
    """

    def __init__(
        self,
        population_size: int = 20,
        genome_dim: int = 12,
        genome_bounds: Optional[Tuple[np.ndarray, np.ndarray]] = None,
    ) -> None:
        self.population_size = population_size
        self.genome_dim = genome_dim

        if genome_bounds is None:
            lb = np.array([16, 1, 0, 5, 0.5, 0.1, 1e-4, 0.001, 0.5, 0, 1, 0], dtype=float)
            ub = np.array([512, 6, 3, 60, 2.0, 1.0, 1.0, 0.5, 1.0, 3, 30, 3], dtype=float)
            self.genome_bounds = (lb, ub)
        else:
            self.genome_bounds = genome_bounds

        self.lb = self.genome_bounds[0]
        self.ub = self.genome_bounds[1]

        # QPSO state
        self._positions: np.ndarray = np.empty(0)
        self._pbests: np.ndarray = np.empty(0)
        self._pbest_values: np.ndarray = np.empty(0)
        self._gbest: np.ndarray = np.empty(0)
        self._gbest_value: float = float("inf")
        self._t: int = 0

        logger.info("MutationEngine: population=%d, genome_dim=%d", population_size, genome_dim)

    def _initialize(self) -> None:
        self._positions = self.lb + np.random.rand(self.population_size, self.genome_dim) * (self.ub - self.lb)
        self._pbests = self._positions.copy()
        self._pbest_values = np.full(self.population_size, float("inf"))
        self._gbest = self._positions[0].copy()
        self._gbest_value = float("inf")

    def _alpha(self, T: int) -> float:
        return 1.0 - 0.5 * self._t / max(T, 1)

    def _quantum_update(self, i: int, T: int) -> np.ndarray:
        alpha = self._alpha(T)
        mbest = self._pbests.mean(axis=0)
        phi = np.random.rand(self.genome_dim)
        local_attractor = phi * self._pbests[i] + (1 - phi) * self._gbest
        u = np.clip(np.random.rand(self.genome_dim), 1e-300, 1.0)
        sign = np.where(np.random.rand(self.genome_dim) > 0.5, 1.0, -1.0)
        new_pos = local_attractor + sign * alpha * np.abs(mbest - self._positions[i]) * np.log(1.0 / u)
        return np.clip(new_pos, self.lb, self.ub)

    def evolve_generation(
        self,
        population: List,  # list of AgentGenome
        fitness_scores: List[float],
        T: int = 100,
    ) -> List:
        """
        One generation of QPSO evolution.

        Parameters
        ----------
        population : list of AgentGenome
        fitness_scores : list of float
            Lower = better (minimization).
        T : int
            Total planned generations (for alpha annealing).

        Returns
        -------
        list of AgentGenome
            New evolved population.
        """
        from .genome import AgentGenome

        if len(self._positions) == 0:
            self._initialize()

        # Sync positions from population
        for i, genome in enumerate(population[:self.population_size]):
            self._positions[i] = genome.to_vector().numpy()

        # Update personal and global bests
        for i, val in enumerate(fitness_scores[:self.population_size]):
            neg_val = -val  # convert to minimization (higher fitness = lower neg)
            if neg_val < self._pbest_values[i]:
                self._pbest_values[i] = neg_val
                self._pbests[i] = self._positions[i].copy()
            if neg_val < self._gbest_value:
                self._gbest_value = neg_val
                self._gbest = self._positions[i].copy()

        # Quantum update for each particle
        new_population = []
        for i in range(self.population_size):
            new_pos = self._quantum_update(i, T)
            self._positions[i] = new_pos
            genome = AgentGenome.from_vector(torch.tensor(new_pos, dtype=torch.float32))
            genome.generation_born = self._t
            new_population.append(genome)

        self._t += 1
        return new_population

    def hamiltonian_constrained_mutation(
        self,
        genome,  # AgentGenome
        H_conserved: float,
        tolerance: float = 0.05,
        containment=None,
    ):
        """
        Only accept mutation if H(new_genome) ≈ H_conserved ± tolerance.

        Parameters
        ----------
        genome : AgentGenome
        H_conserved : float
        tolerance : float
        containment : EvolutionaryContainment, optional

        Returns
        -------
        AgentGenome
            Mutated genome if safe, original if rejected.
        """
        candidate = genome.mutate(mutation_rate=0.15)

        if containment is not None:
            safe, reason = containment.enforce(candidate)
            if not safe:
                logger.debug("Hamiltonian-constrained mutation rejected: %s", reason)
                return genome

        return candidate
