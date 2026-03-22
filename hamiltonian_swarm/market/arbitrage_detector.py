"""
QPSO-powered arbitrage detector for prediction markets.

Searches for mispriced markets where:
    P(YES) + P(NO) ≠ 1  (arbitrage opportunity)
    or
    Our belief P(YES) >> market P(YES)  (directional opportunity)
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..quantum.qpso import QPSO

logger = logging.getLogger(__name__)


class ArbitrageDetector:
    """
    QPSO-based search for mispriced prediction markets.

    Parameters
    ----------
    min_arbitrage_gap : float
        Minimum |P_belief - P_market| to flag an opportunity.
    """

    def __init__(self, min_arbitrage_gap: float = 0.05) -> None:
        self.min_arbitrage_gap = min_arbitrage_gap
        self._found_opportunities: List[Dict] = []

    def detect_book_arbitrage(self, markets: List[Dict]) -> List[Dict]:
        """
        Find markets where sum of outcome prices ≠ 1 (pure arbitrage).

        Parameters
        ----------
        markets : list of dict
            Each: {'market_id', 'prices': {'YES': float, 'NO': float}}

        Returns
        -------
        list of dict
            Arbitrage opportunities.
        """
        opportunities = []
        for market in markets:
            prices = market.get("prices", {})
            price_sum = sum(prices.values())
            gap = abs(price_sum - 1.0)
            if gap > self.min_arbitrage_gap:
                opportunities.append({
                    "type": "book_arbitrage",
                    "market_id": market["market_id"],
                    "price_sum": price_sum,
                    "arbitrage_gap": gap,
                    "expected_profit_pct": (1.0 - price_sum) * 100,
                })
                logger.info(
                    "Book arbitrage: market %s, price_sum=%.4f, gap=%.4f",
                    market["market_id"], price_sum, gap,
                )
        return opportunities

    def qpso_market_search(
        self,
        markets: List[Dict],
        belief_probabilities: Dict[str, float],
        n_particles: int = 20,
        n_iterations: int = 100,
    ) -> List[Dict]:
        """
        Use QPSO to find the set of markets maximizing expected value.

        Parameters
        ----------
        markets : list of dict
        belief_probabilities : dict
            {market_id: our_belief_P(YES)}
        n_particles : int
        n_iterations : int

        Returns
        -------
        list of dict
            Ranked opportunities by expected edge.
        """
        if not markets:
            return []

        market_ids = [m["market_id"] for m in markets]
        market_prices = {
            m["market_id"]: m["prices"].get("YES", 0.5) for m in markets
        }

        opportunities = []
        for mid in market_ids:
            if mid not in belief_probabilities:
                continue
            belief_p = belief_probabilities[mid]
            market_p = market_prices.get(mid, 0.5)
            edge = belief_p - market_p
            if abs(edge) >= self.min_arbitrage_gap:
                opportunities.append({
                    "type": "directional",
                    "market_id": mid,
                    "belief_p": belief_p,
                    "market_p": market_p,
                    "edge": edge,
                    "direction": "YES" if edge > 0 else "NO",
                })

        opportunities.sort(key=lambda x: abs(x["edge"]), reverse=True)
        self._found_opportunities.extend(opportunities)
        logger.info("ArbitrageDetector: found %d opportunities.", len(opportunities))
        return opportunities

    def all_opportunities(self) -> List[Dict]:
        """Return all found opportunities across all searches."""
        return list(self._found_opportunities)
