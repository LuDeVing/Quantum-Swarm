"""
Natural selection: Pareto-based survival and reproduction.
"""

from __future__ import annotations
import logging
import random
from typing import List, Tuple

logger = logging.getLogger(__name__)


class NaturalSelection:
    """
    Selects survivors and generates offspring based on Pareto dominance + novelty.

    Parameters
    ----------
    elite_fraction : float
        Fraction of population always kept (top Pareto front).
    crossover_rate : float
        Probability of crossover vs cloning.
    """

    def __init__(
        self,
        elite_fraction: float = 0.2,
        crossover_rate: float = 0.7,
    ) -> None:
        self.elite_fraction = elite_fraction
        self.crossover_rate = crossover_rate

    def select_survivors(
        self,
        population: List,
        fitness_scores: List[dict],
        pareto_front_indices: List[int],
        target_size: int,
    ) -> List:
        """
        Keep Pareto front + fill with tournament selection.

        Parameters
        ----------
        population : list of AgentGenome
        fitness_scores : list of dict
        pareto_front_indices : list of int
        target_size : int

        Returns
        -------
        list of AgentGenome
        """
        survivors = [population[i] for i in pareto_front_indices]
        remaining_slots = target_size - len(survivors)

        # Fill remaining via tournament selection
        non_pareto = [i for i in range(len(population)) if i not in pareto_front_indices]
        for _ in range(max(0, remaining_slots)):
            if not non_pareto:
                break
            candidates = random.sample(non_pareto, min(2, len(non_pareto)))
            if len(candidates) == 1:
                winner = candidates[0]
            else:
                t1, t2 = candidates
                winner = t1 if (fitness_scores[t1].get("task_performance", 0) >=
                                fitness_scores[t2].get("task_performance", 0)) else t2
            survivors.append(population[winner])

        return survivors[:target_size]

    def reproduce(
        self,
        survivors: List,
        target_size: int,
        mutation_rate: float = 0.1,
    ) -> List:
        """
        Fill population to target_size via crossover and mutation.

        Parameters
        ----------
        survivors : list of AgentGenome
        target_size : int
        mutation_rate : float

        Returns
        -------
        list of AgentGenome
        """
        offspring = list(survivors)
        while len(offspring) < target_size:
            if len(survivors) >= 2 and random.random() < self.crossover_rate:
                p1, p2 = random.sample(survivors, 2)
                child = p1.crossover(p2)
            else:
                parent = random.choice(survivors)
                child = parent.mutate(mutation_rate)
            offspring.append(child)
        return offspring
