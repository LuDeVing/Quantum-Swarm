"""
Master evolutionary orchestrator.

Generation cycle:
  1. Deploy population on benchmark tasks → measure fitness
  2. Select survivors (Pareto front + novelty)
  3. Generate offspring via QPSO mutation
  4. Check containment (Hamiltonian conservation)
  5. Propagate best genomes via Schrödinger diffusion (info spread model)
  6. Update quantum belief states with generation results
  7. Log generation + checkpoint best genomes
  8. Repeat
"""

from __future__ import annotations
import copy
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class QuantumSwarmEvolution:
    """
    Full self-improving evolutionary loop.

    Parameters
    ----------
    population_size : int
    benchmark_tasks : list of dict
    core_goal_prompt : str
        Text description of the system's core goal (encoded into H_goal).
    max_generations : int
    conservation_tolerance : float
    checkpoint_dir : str
    """

    def __init__(
        self,
        population_size: int = 20,
        benchmark_tasks: Optional[List[Dict]] = None,
        core_goal_prompt: str = "Be helpful and accurate.",
        max_generations: int = 1000,
        conservation_tolerance: float = 0.05,
        checkpoint_dir: str = "evolution_checkpoints",
    ) -> None:
        from .genome import AgentGenome
        from .fitness_evaluator import FitnessEvaluator
        from .mutation_engine import MutationEngine
        from .containment import EvolutionaryContainment
        from .natural_selection import NaturalSelection
        from .generation_logger import GenerationLogger

        self.population_size = population_size
        self.max_generations = max_generations
        self.core_goal_prompt = core_goal_prompt
        self.checkpoint_dir = checkpoint_dir

        # Initialize population with diverse random genomes
        self.population: List[AgentGenome] = [
            AgentGenome().mutate(mutation_rate=0.5) for _ in range(population_size)
        ]

        # Seed genome for containment baseline
        seed_genome = AgentGenome()
        seed_genome.system_prompt_template = core_goal_prompt

        self.fitness_evaluator = FitnessEvaluator(benchmark_tasks)
        self.mutation_engine = MutationEngine(population_size)
        self.containment = EvolutionaryContainment(seed_genome, conservation_tolerance)
        self.selector = NaturalSelection()
        self.gen_logger = GenerationLogger(log_dir=checkpoint_dir + "/logs")

        self._generation = 0
        self._plateau_count = 0
        self._last_best_fitness = -float("inf")
        self._running = False

        logger.info(
            "QuantumSwarmEvolution ready: pop=%d, max_gen=%d, H_goal=%.4f",
            population_size, max_generations, self.containment.H_goal,
        )

    # ------------------------------------------------------------------
    # Single generation
    # ------------------------------------------------------------------

    def run_generation(self, generation_num: int):
        """Execute one complete generation cycle."""
        from .fitness_evaluator import GenerationResult

        t0 = time.time()

        # 1. Evaluate fitness
        all_scores = []
        for genome in self.population:
            scores = self.fitness_evaluator.evaluate(genome, self.population)
            genome.fitness_scores = scores
            all_scores.append(scores)

        # 2. Pareto front
        pareto = self.fitness_evaluator.pareto_front(all_scores)

        # 3. Select survivors
        survivors = self.selector.select_survivors(
            self.population, all_scores, pareto, self.population_size // 2
        )

        # 4. Generate offspring via QPSO mutation (with containment)
        raw_fitness = [s.get("task_performance", 0.0) for s in all_scores]
        evolved = self.mutation_engine.evolve_generation(
            self.population, raw_fitness, T=self.max_generations
        )

        # 5. Filter through containment
        safe_evolved = []
        violations = 0
        for genome in evolved:
            is_safe, _ = self.containment.enforce(genome)
            if is_safe:
                safe_evolved.append(genome)
            else:
                violations += 1
                # Fall back to direct mutation of a survivor
                if survivors:
                    import random
                    fallback = random.choice(survivors).mutate(0.05)
                    safe_evolved.append(fallback)

        # 6. Merge survivors + safe offspring
        self.population = self.selector.reproduce(
            survivors + safe_evolved, self.population_size
        )

        # 7. Checkpoint
        if generation_num % 10 == 0:
            self.containment.checkpoint_generation(generation_num, self.population)

        # 8. Log
        self.gen_logger.log_generation(
            generation_num, self.population, all_scores, pareto, violations
        )

        # Track best
        best_fit = max(s.get("task_performance", 0) for s in all_scores)
        if best_fit > self._last_best_fitness + 1e-4:
            self._last_best_fitness = best_fit
            self._plateau_count = 0
        else:
            self._plateau_count += 1

        elapsed = time.time() - t0
        logger.info(
            "Generation %d: best_perf=%.4f, pareto=%d, violations=%d, plateau=%d (%.2fs)",
            generation_num, best_fit, len(pareto), violations, self._plateau_count, elapsed,
        )

        return GenerationResult(
            generation=generation_num,
            population_size=len(self.population),
            fitness_scores=all_scores,
            best_genome_idx=int(max(range(len(all_scores)),
                                   key=lambda i: all_scores[i].get("task_performance", 0))),
            pareto_front_indices=pareto,
            mean_fitness={
                k: float(sum(s.get(k, 0) for s in all_scores) / len(all_scores))
                for k in all_scores[0].keys()
            },
            elapsed_seconds=elapsed,
            containment_violations=violations,
        )

    # ------------------------------------------------------------------
    # Stopping conditions
    # ------------------------------------------------------------------

    def should_stop(self) -> Tuple[bool, str]:
        """
        Stopping conditions:
          - Fitness plateaued for 10 generations
          - Max generations reached
          - Human stop signal (_running = False)
        """
        if not self._running:
            return True, "Manual stop."
        if self._generation >= self.max_generations:
            return True, f"Max generations ({self.max_generations}) reached."
        if self._plateau_count >= 10:
            return True, f"Fitness plateaued for 10 generations."
        return False, ""

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, n_generations: Optional[int] = None) -> List:
        """
        Full evolution loop.

        Parameters
        ----------
        n_generations : int, optional
            Override max_generations for this run.

        Returns
        -------
        list of AgentGenome
            Final best population (Pareto front).
        """
        import os
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        max_gen = n_generations or self.max_generations
        self._running = True

        logger.info("Evolution started: max_gen=%d", max_gen)
        while self._generation < max_gen:
            result = self.run_generation(self._generation)
            stop, reason = self.should_stop()
            if stop:
                logger.info("Evolution stopped at generation %d: %s", self._generation, reason)
                break
            self._generation += 1

        self._running = False
        # Return Pareto front
        all_scores = [g.fitness_scores for g in self.population]
        pareto = self.fitness_evaluator.pareto_front(all_scores) if all_scores[0] else list(range(len(self.population)))
        return [self.population[i] for i in pareto]

    def stop(self) -> None:
        """Signal the evolution loop to stop after current generation."""
        self._running = False
