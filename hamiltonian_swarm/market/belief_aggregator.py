"""
Combine multiple agent beliefs into a single market prediction.

Uses quantum interference: beliefs that agree constructively interfere
(amplitudes add), beliefs that disagree destructively interfere (cancel).
"""

from __future__ import annotations
import logging
import math
from typing import Dict, List

import torch

from ..quantum.quantum_belief import QuantumBeliefState

logger = logging.getLogger(__name__)


class BeliefAggregator:
    """
    Aggregate beliefs from multiple agents via quantum interference.

    Parameters
    ----------
    n_outcomes : int
        Number of possible outcomes (e.g. 2 for YES/NO).
    """

    def __init__(self, n_outcomes: int = 2) -> None:
        self.n_outcomes = n_outcomes

    def aggregate(
        self,
        beliefs: List[QuantumBeliefState],
        weights: List[float] = None,
    ) -> QuantumBeliefState:
        """
        Aggregate multiple belief states via weighted amplitude sum.

        ψ_agg = Σ wᵢ ψᵢ / ||Σ wᵢ ψᵢ||

        Parameters
        ----------
        beliefs : list of QuantumBeliefState
        weights : list of float, optional
            Agent credibility weights. Defaults to uniform.

        Returns
        -------
        QuantumBeliefState
        """
        if not beliefs:
            return QuantumBeliefState(["UNKNOWN"])

        if weights is None:
            weights = [1.0] * len(beliefs)

        w_total = sum(weights)
        combined_amps = torch.zeros(self.n_outcomes, dtype=torch.complex64)

        for belief, w in zip(beliefs, weights):
            if len(belief.amplitudes) == self.n_outcomes:
                combined_amps = combined_amps + (w / w_total) * belief.amplitudes

        # Create aggregated belief
        outcomes = beliefs[0].hypotheses[:self.n_outcomes]
        result = QuantumBeliefState(outcomes)
        result.amplitudes = combined_amps
        result.normalize()

        logger.debug(
            "Aggregated %d beliefs: entropy=%.4f, top_prob=%.4f",
            len(beliefs),
            result.entropy(),
            float(result.probabilities().max().item()),
        )
        return result

    def consensus_probability(
        self, beliefs: List[QuantumBeliefState], outcome_idx: int = 0
    ) -> Dict[str, float]:
        """
        Compute consensus probability and uncertainty for an outcome.

        Parameters
        ----------
        beliefs : list of QuantumBeliefState
        outcome_idx : int

        Returns
        -------
        dict: {'mean_prob', 'std_prob', 'min_prob', 'max_prob', 'consensus_strength'}
        """
        probs = [b.probability(outcome_idx) for b in beliefs]
        import numpy as np
        return {
            "mean_prob": float(np.mean(probs)),
            "std_prob": float(np.std(probs)),
            "min_prob": float(np.min(probs)),
            "max_prob": float(np.max(probs)),
            "consensus_strength": float(1.0 - np.std(probs)),  # 1=full consensus
        }
