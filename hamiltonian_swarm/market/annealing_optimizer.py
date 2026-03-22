"""
Quantum annealing portfolio optimizer for prediction markets.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List

from ..quantum.quantum_annealing import QuantumAnnealingOptimizer

logger = logging.getLogger(__name__)


class AnnealingPortfolioOptimizer:
    """
    Wraps QuantumAnnealingOptimizer for prediction market portfolio construction.

    Parameters
    ----------
    budget : float
        Total bankroll to allocate.
    max_positions : int
        Maximum number of simultaneous positions.
    kelly_max : float
        Maximum Kelly fraction per position.
    """

    def __init__(
        self,
        budget: float = 1000.0,
        max_positions: int = 10,
        kelly_max: float = 0.25,
    ) -> None:
        self.budget = budget
        self.max_positions = max_positions
        self.kelly_max = kelly_max
        self._optimizer = QuantumAnnealingOptimizer(n_steps=500)
        logger.info(
            "AnnealingPortfolioOptimizer: budget=%.2f, max_pos=%d",
            budget, max_positions,
        )

    def optimize(self, opportunities: List[Dict]) -> Dict[str, Any]:
        """
        Select and size optimal portfolio from opportunities.

        Parameters
        ----------
        opportunities : list of dict
            Each: {'market_id', 'edge', 'kelly_fraction', 'market_price', 'direction'}

        Returns
        -------
        dict
            {'positions': list, 'total_allocated': float, 'expected_return': float}
        """
        if not opportunities:
            return {"positions": [], "total_allocated": 0.0, "expected_return": 0.0}

        # Limit to max_positions
        candidates = opportunities[:self.max_positions]

        # Build position costs and returns for QUBO
        import numpy as np
        returns = np.array([abs(c["edge"]) for c in candidates])
        costs = np.array([c.get("kelly_fraction", 0.05) * self.budget for c in candidates])

        result = self._optimizer.optimize_portfolio(
            [
                {
                    "name": c["market_id"],
                    "expected_return": returns[i],
                    "cost": costs[i],
                }
                for i, c in enumerate(candidates)
            ],
            budget=self.budget,
        )

        selected_indices = [i for i, x in enumerate(result["binary_vector"]) if x == 1]
        positions = []
        for idx in selected_indices:
            c = candidates[idx]
            allocation = costs[idx]
            positions.append({
                "market_id": c["market_id"],
                "direction": c.get("direction", "YES"),
                "edge": c["edge"],
                "allocation": allocation,
                "kelly_fraction": c.get("kelly_fraction", 0.0),
            })

        total_allocated = sum(p["allocation"] for p in positions)
        expected_return = sum(abs(p["edge"]) * p["allocation"] for p in positions)

        logger.info(
            "Portfolio: %d positions, allocated=%.2f/%.2f, E[return]=%.4f",
            len(positions), total_allocated, self.budget, expected_return,
        )
        return {
            "positions": positions,
            "total_allocated": total_allocated,
            "expected_return": expected_return,
        }
