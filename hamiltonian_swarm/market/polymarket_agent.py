"""
Specialized prediction market agent for Polymarket.

Architecture:
  - QuantumBeliefState: superposition of YES/NO/MAYBE outcomes
  - QPSO: searches for mispriced markets
  - QuantumAnnealing: optimizes portfolio allocation
  - EmbeddingHamiltonianNN: detects when predictions drift from news reality
"""

from __future__ import annotations
import logging
import math
import random
from typing import Any, Dict, List, Optional

import numpy as np
import torch

from ..agents.base_agent import BaseAgent, TaskResult
from ..quantum.quantum_belief import QuantumBeliefState
from ..quantum.quantum_annealing import QuantumAnnealingOptimizer

logger = logging.getLogger(__name__)

_DEFAULT_OUTCOMES = ["YES", "NO", "UNCERTAIN"]


class PolymarketAgent(BaseAgent):
    """
    Prediction market agent using quantum belief states.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality.
    kelly_max : float
        Maximum Kelly fraction per position.
    min_edge : float
        Minimum edge required to consider a position.
    """

    def __init__(
        self,
        n_dims: int = 4,
        kelly_max: float = 0.25,
        min_edge: float = 0.03,
        **kwargs: Any,
    ) -> None:
        super().__init__(n_dims=n_dims, agent_type="polymarket", **kwargs)
        self.kelly_max = kelly_max
        self.min_edge = min_edge
        self._annealer = QuantumAnnealingOptimizer(n_steps=500, T_start=1.0, T_end=0.01)
        self._market_beliefs: Dict[str, QuantumBeliefState] = {}
        logger.info(
            "PolymarketAgent %s: kelly_max=%.2f, min_edge=%.3f",
            self.agent_id, kelly_max, min_edge,
        )

    # ------------------------------------------------------------------
    # Market utilities
    # ------------------------------------------------------------------

    def fetch_markets(self) -> List[Dict]:
        """
        Fetch open prediction markets.

        In a real deployment, calls the Polymarket CLOB API.
        Here returns simulated markets for demonstration.

        Returns
        -------
        list of dict
            Each dict: {market_id, question, outcomes, prices, volume}
        """
        # Simulated markets
        questions = [
            "Will inflation exceed 3% in Q3?",
            "Will the Fed cut rates in September?",
            "Will BTC exceed $100k by year end?",
            "Will the S&P 500 hit all-time high this month?",
            "Will unemployment rise above 5%?",
        ]
        markets = []
        for i, q in enumerate(questions):
            yes_price = round(random.uniform(0.2, 0.8), 2)
            markets.append({
                "market_id": f"market_{i:04d}",
                "question": q,
                "outcomes": ["YES", "NO"],
                "prices": {"YES": yes_price, "NO": round(1.0 - yes_price, 2)},
                "volume": random.randint(1000, 100000),
            })
        logger.debug("Fetched %d simulated markets.", len(markets))
        return markets

    def build_belief_state(self, market: Dict) -> QuantumBeliefState:
        """
        Initialize a quantum belief state over market outcomes.

        Parameters
        ----------
        market : dict

        Returns
        -------
        QuantumBeliefState
        """
        outcomes = market.get("outcomes", ["YES", "NO"])
        belief = QuantumBeliefState(outcomes)
        market_id = market["market_id"]
        self._market_beliefs[market_id] = belief
        return belief

    def update_from_evidence(
        self,
        belief_state: QuantumBeliefState,
        evidence_type: str,
        evidence_strength: float,
        outcome_idx: int = 0,
    ) -> None:
        """
        Update belief amplitude based on evidence.

        Parameters
        ----------
        belief_state : QuantumBeliefState
        evidence_type : str
            e.g. 'news', 'sentiment', 'base_rate', 'correlation'
        evidence_strength : float
            Positive = amplifies outcome_idx, negative = suppresses it.
        outcome_idx : int
            Which outcome the evidence supports.
        """
        logger.debug(
            "Evidence '%s': strength=%.3f → outcome[%d]",
            evidence_type, evidence_strength, outcome_idx,
        )
        belief_state.add_evidence(outcome_idx, evidence_strength)

    def compute_edge(
        self, belief_state: QuantumBeliefState, market_price: float, outcome_idx: int = 0
    ) -> float:
        """
        Edge = P(outcome per belief) - market_price.

        Positive = market underpricing our estimate.

        Parameters
        ----------
        belief_state : QuantumBeliefState
        market_price : float
        outcome_idx : int

        Returns
        -------
        float
        """
        return belief_state.probability(outcome_idx) - market_price

    def kelly_criterion(self, edge: float, odds: float) -> float:
        """
        Optimal bet fraction: f* = edge / odds.
        Clipped to kelly_max to prevent overbetting.

        Parameters
        ----------
        edge : float
        odds : float
            e.g. 1.0 for even-money, 2.0 for 2:1

        Returns
        -------
        float ∈ [0, kelly_max]
        """
        if odds < 1e-8:
            return 0.0
        f_star = edge / odds
        return float(np.clip(f_star, 0.0, self.kelly_max))

    # ------------------------------------------------------------------
    # Full prediction pipeline
    # ------------------------------------------------------------------

    async def predict_markets(self) -> List[Dict]:
        """
        Run full market prediction pipeline.

        Returns
        -------
        list of dict
            Ranked opportunities with edge and Kelly size.
        """
        markets = self.fetch_markets()
        opportunities = []

        for market in markets:
            belief = self.build_belief_state(market)

            # Simulate evidence from 4 sub-agents
            evidence_signals = {
                "news": random.gauss(0, 0.3),
                "sentiment": random.gauss(0, 0.2),
                "base_rate": random.gauss(0, 0.1),
                "correlation": random.gauss(0, 0.15),
            }
            for etype, strength in evidence_signals.items():
                self.update_from_evidence(belief, etype, strength, outcome_idx=0)

            # Compute edge
            yes_price = market["prices"]["YES"]
            edge = self.compute_edge(belief, yes_price, outcome_idx=0)

            if abs(edge) >= self.min_edge:
                direction = 0 if edge > 0 else 1  # YES if positive, NO if negative
                odds = 1.0 / max(market["prices"][market["outcomes"][direction]], 1e-8) - 1.0
                kelly = self.kelly_criterion(abs(edge), max(odds, 0.01))

                opportunities.append({
                    "market_id": market["market_id"],
                    "question": market["question"],
                    "direction": market["outcomes"][direction],
                    "market_price": market["prices"][market["outcomes"][direction]],
                    "belief_prob": belief.probability(direction),
                    "edge": edge,
                    "kelly_fraction": kelly,
                    "belief_entropy": belief.entropy(),
                })

        # Sort by |edge| descending
        opportunities.sort(key=lambda x: abs(x["edge"]), reverse=True)
        logger.info(
            "PolymarketAgent: %d/%d markets have edge > %.2f%%",
            len(opportunities), len(markets), self.min_edge * 100,
        )
        return opportunities

    # ------------------------------------------------------------------
    # Task interface
    # ------------------------------------------------------------------

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        task_id = task.get("task_id", "unknown")
        H_before = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )

        opportunities = await self.predict_markets()

        H_after = self.step_phase_state(dt=0.01)

        return TaskResult(
            task_id=task_id,
            agent_id=self.agent_id,
            success=True,
            output={"opportunities": opportunities, "n_markets_analyzed": len(self.fetch_markets())},
            energy_before=H_before,
            energy_after=H_after,
        )
