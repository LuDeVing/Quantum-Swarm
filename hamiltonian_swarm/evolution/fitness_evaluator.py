"""
Multi-objective fitness evaluator for agent genomes.

Objectives:
  1. task_performance   — success rate on benchmark tasks
  2. energy_efficiency  — quality per token used
  3. stability          — 1 / (1 + mean_drift_score)
  4. speed              — 1 / mean_task_completion_time
  5. cooperation        — information successfully shared
  6. novelty            — genetic distance from population mean

No single scalar — Pareto-front multi-objective optimization.
"""

from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)


@dataclass
class GenerationResult:
    """Result of one complete generation."""
    generation: int
    population_size: int
    fitness_scores: List[Dict[str, float]]
    best_genome_idx: int
    pareto_front_indices: List[int]
    mean_fitness: Dict[str, float]
    elapsed_seconds: float
    containment_violations: int = 0


class FitnessEvaluator:
    """
    Multi-objective fitness evaluation for agent genomes.

    Parameters
    ----------
    benchmark_tasks : list of dict
        Task specifications used to evaluate agents.
    novelty_k : int
        Number of nearest neighbours for novelty score.
    """

    def __init__(
        self,
        benchmark_tasks: Optional[List[Dict]] = None,
        novelty_k: int = 3,
    ) -> None:
        self.benchmark_tasks = benchmark_tasks or self._default_benchmarks()
        self.novelty_k = novelty_k
        logger.info(
            "FitnessEvaluator: %d benchmarks, novelty_k=%d",
            len(self.benchmark_tasks), novelty_k,
        )

    def _default_benchmarks(self) -> List[Dict]:
        return [
            {"task_id": "bench_1", "type": "task", "payload": {"complexity": 0.3}, "complexity": 0.3},
            {"task_id": "bench_2", "type": "task", "payload": {"complexity": 0.7}, "complexity": 0.7},
            {"task_id": "bench_3", "type": "task", "payload": {"complexity": 0.5}, "complexity": 0.5},
        ]

    # ------------------------------------------------------------------
    # Individual evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        genome,  # AgentGenome
        population: Optional[List] = None,
    ) -> Dict[str, float]:
        """
        Evaluate all objectives for a genome.

        Parameters
        ----------
        genome : AgentGenome
        population : list of AgentGenome, optional
            Needed for novelty score.

        Returns
        -------
        dict
            {'task_performance': float, 'energy_efficiency': float,
             'stability': float, 'speed': float,
             'cooperation': float, 'novelty': float}
        """
        scores = {}

        # 1. Task performance: simulate based on genome's hidden_dim and n_layers
        # In a real system this would run the agent; here we use a proxy model
        capacity = math.log(1 + genome.hidden_dim * genome.n_hidden_layers) / 10.0
        scores["task_performance"] = float(np.clip(capacity + np.random.randn() * 0.05, 0, 1))

        # 2. Energy efficiency: penalize large architectures
        size_penalty = genome.hidden_dim * genome.n_hidden_layers / (256 * 3)
        scores["energy_efficiency"] = float(np.clip(1.0 - size_penalty * 0.3 + np.random.randn() * 0.02, 0, 1))

        # 3. Stability: based on energy_threshold (tighter = more stable)
        scores["stability"] = float(1.0 / (1.0 + genome.energy_threshold * 10))

        # 4. Speed: inversely proportional to architecture size
        scores["speed"] = float(np.clip(1.0 / (1.0 + size_penalty) + np.random.randn() * 0.02, 0, 1))

        # 5. Cooperation: broadcast frequency bonus
        scores["cooperation"] = float(np.clip(
            math.log(1 + genome.broadcast_frequency) / math.log(20) + np.random.randn() * 0.02,
            0, 1
        ))

        # 6. Novelty: distance from population mean in genome space
        if population and len(population) > 1:
            scores["novelty"] = self.novelty_score(genome, population)
        else:
            scores["novelty"] = 0.5

        # 7. Quantum fitness: QPSO convergence speed + belief collapse efficiency
        scores["quantum"] = self.quantum_fitness(genome)

        return scores

    # ------------------------------------------------------------------
    # Pareto dominance
    # ------------------------------------------------------------------

    def pareto_dominates(
        self,
        scores_a: Dict[str, float],
        scores_b: Dict[str, float],
    ) -> bool:
        """
        True if A Pareto-dominates B:
        A is at least as good as B on all objectives and strictly better on one.
        """
        keys = list(scores_a.keys())
        at_least_equal = all(scores_a[k] >= scores_b[k] for k in keys)
        strictly_better = any(scores_a[k] > scores_b[k] for k in keys)
        return at_least_equal and strictly_better

    def pareto_front(
        self, population_scores: List[Dict[str, float]]
    ) -> List[int]:
        """
        Return indices of non-dominated genomes (Pareto front).

        Parameters
        ----------
        population_scores : list of dict

        Returns
        -------
        list of int
        """
        n = len(population_scores)
        is_dominated = [False] * n
        for i in range(n):
            for j in range(n):
                if i != j and self.pareto_dominates(population_scores[j], population_scores[i]):
                    is_dominated[i] = True
                    break
        return [i for i in range(n) if not is_dominated[i]]

    # ------------------------------------------------------------------
    # Novelty
    # ------------------------------------------------------------------

    def novelty_score(
        self, genome, population: List
    ) -> float:
        """
        Distance to k nearest neighbours in genome vector space.

        Parameters
        ----------
        genome : AgentGenome
        population : list of AgentGenome

        Returns
        -------
        float
            Mean distance to k-NN. Higher = more novel.
        """
        if len(population) < 2:
            return 0.5
        v_self = genome.to_vector()
        distances = []
        for other in population:
            if other is genome:
                continue
            v_other = other.to_vector()
            distances.append(float(torch.dist(v_self, v_other).item()))
        distances.sort()
        k = min(self.novelty_k, len(distances))
        novelty = float(np.mean(distances[:k]))
        # Normalize to roughly [0, 1]
        return float(np.tanh(novelty / 100.0))

    # ------------------------------------------------------------------
    # Quantum fitness
    # ------------------------------------------------------------------

    def quantum_fitness(self, genome) -> float:
        """
        Fitness contribution from quantum components:
        - QPSO convergence speed (alpha range)
        - Belief state collapse threshold efficiency
        - Tunneling potential (alpha_max - alpha_min)

        Returns
        -------
        float ∈ [0, 1]
        """
        qpso_score = (genome.alpha_max - genome.alpha_min) / 1.0
        belief_score = 1.0 - genome.belief_collapse_threshold
        return float(np.clip((qpso_score + belief_score) / 2.0, 0, 1))


# Needed for genome.evaluate() proxy
import math
