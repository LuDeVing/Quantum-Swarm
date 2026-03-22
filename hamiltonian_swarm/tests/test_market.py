"""
Tests for market modules: PolymarketAgent, BeliefAggregator,
ArbitrageDetector, AnnealingOptimizer.
"""

import asyncio
import pytest
import torch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.quantum.quantum_belief import QuantumBeliefState
from hamiltonian_swarm.market.belief_aggregator import BeliefAggregator
from hamiltonian_swarm.market.polymarket_agent import PolymarketAgent
from hamiltonian_swarm.market.arbitrage_detector import ArbitrageDetector
from hamiltonian_swarm.market.annealing_optimizer import AnnealingPortfolioOptimizer


class TestBeliefAggregator:
    def test_aggregate_single_belief(self):
        """Aggregating one belief returns a normalized state."""
        agg = BeliefAggregator(n_outcomes=2)
        b = QuantumBeliefState(["YES", "NO"])
        result = agg.aggregate([b])
        total = float(result.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5

    def test_aggregate_multiple_beliefs_normalized(self):
        """Aggregating multiple beliefs always returns normalized result."""
        agg = BeliefAggregator(n_outcomes=2)
        beliefs = []
        for i in range(5):
            b = QuantumBeliefState(["YES", "NO"])
            b.add_evidence(0, float(i) * 0.5)
            beliefs.append(b)
        result = agg.aggregate(beliefs)
        total = float(result.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5

    def test_weighted_aggregation(self):
        """Higher-weight belief should dominate the aggregate."""
        agg = BeliefAggregator(n_outcomes=2)
        b_yes = QuantumBeliefState(["YES", "NO"])
        for _ in range(10):
            b_yes.add_evidence(0, 2.0)   # strongly YES

        b_no = QuantumBeliefState(["YES", "NO"])
        for _ in range(10):
            b_no.add_evidence(1, 2.0)    # strongly NO

        # Weight b_yes 10x more
        result = agg.aggregate([b_yes, b_no], weights=[10.0, 1.0])
        # YES should dominate
        assert result.probability(0) > 0.5

    def test_consensus_probability_returns_stats(self):
        """consensus_probability returns all required fields."""
        agg = BeliefAggregator(n_outcomes=2)
        beliefs = [QuantumBeliefState(["YES", "NO"]) for _ in range(4)]
        stats = agg.consensus_probability(beliefs, outcome_idx=0)
        for key in ("mean_prob", "std_prob", "min_prob", "max_prob", "consensus_strength"):
            assert key in stats

    def test_consensus_mean_near_half_for_uniform(self):
        """Uniform beliefs → consensus mean ≈ 0.5."""
        agg = BeliefAggregator(n_outcomes=2)
        beliefs = [QuantumBeliefState(["YES", "NO"]) for _ in range(8)]
        stats = agg.consensus_probability(beliefs, 0)
        assert abs(stats["mean_prob"] - 0.5) < 0.05

    def test_aggregate_empty_returns_unknown(self):
        """Empty list returns single 'UNKNOWN' belief."""
        agg = BeliefAggregator(n_outcomes=2)
        result = agg.aggregate([])
        assert "UNKNOWN" in result.hypotheses


class TestPolymarketAgent:
    def test_fetch_markets_returns_list(self):
        """fetch_markets() returns a non-empty list of dicts."""
        agent = PolymarketAgent(n_dims=4)
        markets = agent.fetch_markets()
        assert len(markets) >= 1
        for m in markets:
            assert "market_id" in m
            assert "prices" in m

    def test_build_belief_state(self):
        """build_belief_state creates a QuantumBeliefState with market outcomes."""
        agent = PolymarketAgent(n_dims=4)
        markets = agent.fetch_markets()
        market = markets[0]
        belief = agent.build_belief_state(market)
        # Stored internally
        assert market["market_id"] in agent._market_beliefs

    def test_compute_edge_sign(self):
        """Positive edge when belief prob > market price."""
        agent = PolymarketAgent(n_dims=4)
        b = QuantumBeliefState(["YES", "NO"])
        for _ in range(20):
            b.add_evidence(0, 3.0)   # push YES prob high
        edge = agent.compute_edge(b, market_price=0.1, outcome_idx=0)
        assert edge > 0.0

    def test_kelly_criterion_clips_to_max(self):
        """kelly_criterion never exceeds kelly_max."""
        agent = PolymarketAgent(kelly_max=0.25)
        kelly = agent.kelly_criterion(edge=10.0, odds=0.01)
        assert kelly <= 0.25

    def test_kelly_criterion_zero_for_no_edge(self):
        """Zero edge → zero kelly fraction."""
        agent = PolymarketAgent()
        kelly = agent.kelly_criterion(edge=0.0, odds=1.0)
        assert kelly == 0.0

    def test_kelly_criterion_zero_odds(self):
        """Zero odds → zero kelly fraction (guard against divide-by-zero)."""
        agent = PolymarketAgent()
        kelly = agent.kelly_criterion(edge=0.5, odds=0.0)
        assert kelly == 0.0

    def test_predict_markets_returns_opportunities(self):
        """predict_markets() returns a list (may be empty if no edge)."""
        agent = PolymarketAgent(n_dims=4, min_edge=0.0)  # min_edge=0 → always include
        opportunities = asyncio.run(agent.predict_markets())
        assert isinstance(opportunities, list)

    def test_opportunity_structure(self):
        """Each opportunity dict has required fields."""
        agent = PolymarketAgent(n_dims=4, min_edge=0.0)
        opps = asyncio.run(agent.predict_markets())
        if opps:
            required = {"market_id", "question", "direction", "edge", "kelly_fraction"}
            for opp in opps:
                assert required <= set(opp.keys())

    def test_execute_task_returns_result(self):
        """execute_task() completes and returns a TaskResult."""
        agent = PolymarketAgent(n_dims=4)
        task = {"task_id": "test_market_001"}
        result = asyncio.run(agent.execute_task(task))
        assert result.task_id == "test_market_001"
        assert result.success is True


class TestArbitrageDetector:
    def test_detect_book_arbitrage_no_false_positive(self):
        """Fair prices (summing to 1) should not flag arbitrage."""
        detector = ArbitrageDetector(min_arbitrage_gap=0.05)
        fair_market = {
            "market_id": "m1",
            "outcomes": ["YES", "NO"],
            "prices": {"YES": 0.6, "NO": 0.4},
        }
        arbs = detector.detect_book_arbitrage([fair_market])
        # |0.6+0.4 - 1.0| = 0 < threshold, so no arb should be flagged
        m1_arbs = [a for a in arbs if a["market_id"] == "m1"]
        assert len(m1_arbs) == 0

    def test_detect_book_arbitrage_detects_mispriced(self):
        """Prices summing well below 1 imply arbitrage opportunity."""
        detector = ArbitrageDetector(min_arbitrage_gap=0.05)
        mispriced = {
            "market_id": "m2",
            "outcomes": ["YES", "NO"],
            "prices": {"YES": 0.3, "NO": 0.3},  # sum = 0.6, gap = 0.4 > 0.05
        }
        arbs = detector.detect_book_arbitrage([mispriced])
        m2_arbs = [a for a in arbs if a["market_id"] == "m2"]
        assert len(m2_arbs) >= 1
        assert "arbitrage_gap" in m2_arbs[0]
        assert m2_arbs[0]["arbitrage_gap"] > 0.05

    def test_arbitrage_returns_list(self):
        """detect_book_arbitrage always returns a list."""
        detector = ArbitrageDetector()
        result = detector.detect_book_arbitrage([])
        assert isinstance(result, list)


class TestAnnealingPortfolioOptimizer:
    def test_optimize_returns_dict_with_positions(self):
        """optimize() returns a dict with 'positions' key."""
        optimizer = AnnealingPortfolioOptimizer(budget=1000.0)
        opportunities = [
            {"market_id": "m1", "edge": 0.1, "kelly_fraction": 0.05, "direction": "YES"},
            {"market_id": "m2", "edge": 0.2, "kelly_fraction": 0.15, "direction": "NO"},
            {"market_id": "m3", "edge": 0.05, "kelly_fraction": 0.02, "direction": "YES"},
        ]
        result = optimizer.optimize(opportunities)
        assert "positions" in result
        assert "total_allocated" in result
        assert "expected_return" in result

    def test_allocation_does_not_exceed_budget(self):
        """total_allocated must not exceed budget."""
        optimizer = AnnealingPortfolioOptimizer(budget=1000.0)
        opportunities = [
            {"market_id": f"m{i}", "edge": 0.1 + i * 0.05, "kelly_fraction": 0.1, "direction": "YES"}
            for i in range(5)
        ]
        result = optimizer.optimize(opportunities)
        # total_allocated should not exceed budget
        assert result["total_allocated"] <= 1000.0 + 1.0  # tiny tolerance

    def test_optimize_empty_returns_zero_allocation(self):
        """Empty opportunity list → zero allocation."""
        optimizer = AnnealingPortfolioOptimizer()
        result = optimizer.optimize([])
        assert result["positions"] == []
        assert result["total_allocated"] == 0.0

    def test_positions_have_required_fields(self):
        """Each selected position must have market_id, edge, allocation."""
        optimizer = AnnealingPortfolioOptimizer(budget=1000.0)
        opportunities = [
            {"market_id": "m1", "edge": 0.3, "kelly_fraction": 0.2, "direction": "YES"},
            {"market_id": "m2", "edge": 0.1, "kelly_fraction": 0.05, "direction": "NO"},
        ]
        result = optimizer.optimize(opportunities)
        for pos in result["positions"]:
            assert "market_id" in pos
            assert "edge" in pos
            assert "allocation" in pos
