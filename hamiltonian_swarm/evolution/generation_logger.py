"""
Generation logger — records every generation's genome + fitness.
"""

from __future__ import annotations
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class GenerationLogger:
    """
    Logs generation data to disk and in memory.

    Parameters
    ----------
    log_dir : str
        Directory to write JSON generation logs.
    """

    def __init__(self, log_dir: str = "evolution_logs") -> None:
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._in_memory: List[Dict[str, Any]] = []
        logger.info("GenerationLogger: log_dir=%s", log_dir)

    def log_generation(
        self,
        generation: int,
        population: List,          # list of AgentGenome
        fitness_scores: List[Dict[str, float]],
        pareto_front: List[int],
        containment_violations: int = 0,
        extra: Optional[Dict] = None,
    ) -> None:
        """
        Record one generation to memory and disk.

        Parameters
        ----------
        generation : int
        population : list of AgentGenome
        fitness_scores : list of dict
        pareto_front : list of int
        containment_violations : int
        extra : dict, optional
        """
        record = {
            "generation": generation,
            "timestamp": time.time(),
            "population_size": len(population),
            "pareto_front_size": len(pareto_front),
            "containment_violations": containment_violations,
            "genomes": [repr(g) for g in population],
            "fitness_scores": fitness_scores,
            "pareto_front_indices": pareto_front,
            "best_fitness": {
                k: max(s.get(k, 0) for s in fitness_scores)
                for k in (fitness_scores[0].keys() if fitness_scores else [])
            },
        }
        if extra:
            record.update(extra)
        self._in_memory.append(record)

        path = os.path.join(self.log_dir, f"gen_{generation:05d}.json")
        try:
            with open(path, "w") as f:
                json.dump(record, f, indent=2, default=str)
        except Exception as e:
            logger.warning("GenerationLogger: failed to write %s: %s", path, e)

        logger.info(
            "Gen %d logged: pop=%d, pareto=%d, violations=%d",
            generation, len(population), len(pareto_front), containment_violations,
        )

    def summary(self) -> Dict[str, Any]:
        """Return summary statistics across all logged generations."""
        if not self._in_memory:
            return {}
        return {
            "total_generations": len(self._in_memory),
            "total_violations": sum(r["containment_violations"] for r in self._in_memory),
            "final_pareto_size": self._in_memory[-1]["pareto_front_size"],
        }

    def get_generation(self, generation: int) -> Optional[Dict]:
        """Retrieve a specific generation record from memory."""
        for r in self._in_memory:
            if r["generation"] == generation:
                return r
        return None
