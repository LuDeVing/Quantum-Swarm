"""
Example: Polymarket Prediction Pipeline Demo

Demonstrates the full market prediction system:
  - PolymarketAgent: quantum belief-based prediction per market
  - BeliefAggregator: multi-agent consensus via quantum interference
  - ArbitrageDetector: QPSO-powered mispricing detection
  - AnnealingPortfolioOptimizer: optimal Kelly-sized portfolio construction

Run with:
    python -m hamiltonian_swarm.examples.polymarket_prediction
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("polymarket_demo")


async def run_multi_agent_prediction(n_agents: int = 5) -> None:
    """
    Run multi-agent market prediction with quantum belief aggregation.

    Parameters
    ----------
    n_agents : int
        Number of independent PolymarketAgents to run.
    """
    from hamiltonian_swarm.market.polymarket_agent import PolymarketAgent
    from hamiltonian_swarm.market.belief_aggregator import BeliefAggregator
    from hamiltonian_swarm.market.arbitrage_detector import ArbitrageDetector
    from hamiltonian_swarm.market.annealing_optimizer import AnnealingPortfolioOptimizer
    from hamiltonian_swarm.quantum.quantum_belief import QuantumBeliefState

    logger.info("=" * 60)
    logger.info("Polymarket Multi-Agent Prediction Demo")
    logger.info("Agents: %d", n_agents)
    logger.info("=" * 60)

    # ── Step 1: Create a swarm of market prediction agents ────────────
    agents = [
        PolymarketAgent(
            n_dims=4,
            kelly_max=0.25,
            min_edge=0.0,  # include all markets for demo
            agent_id=f"poly_agent_{i:02d}",
        )
        for i in range(n_agents)
    ]
    logger.info("Created %d PolymarketAgents", len(agents))

    # ── Step 2: Each agent independently predicts markets ─────────────
    all_agent_opportunities = []
    for agent in agents:
        opps = await agent.predict_markets()
        all_agent_opportunities.append(opps)
        logger.info(
            "Agent %s: found %d opportunities",
            agent.agent_id, len(opps),
        )

    # ── Step 3: Fetch shared market list ──────────────────────────────
    markets = agents[0].fetch_markets()
    logger.info("\n%d markets fetched:", len(markets))
    for m in markets:
        yes_p = m["prices"]["YES"]
        no_p = m["prices"]["NO"]
        logger.info(
            "  [%s]  YES=%.2f  NO=%.2f  vol=%d  '%s'",
            m["market_id"], yes_p, no_p, m["volume"], m["question"][:50],
        )

    # ── Step 4: Aggregate beliefs per market via quantum interference ──
    aggregator = BeliefAggregator(n_outcomes=2)
    market_consensus = {}

    for market in markets:
        mid = market["market_id"]
        market_beliefs = []
        for agent in agents:
            b = agent.build_belief_state(market)
            # Inject a bit of random evidence to differentiate agents
            import random
            for _ in range(3):
                b.add_evidence(0, random.gauss(0, 0.5))
            market_beliefs.append(b)

        # Aggregate all agents' beliefs
        consensus = aggregator.aggregate(market_beliefs)
        stats = aggregator.consensus_probability(market_beliefs, outcome_idx=0)
        market_consensus[mid] = {
            "belief_state": consensus,
            "stats": stats,
            "market": market,
        }

        logger.info(
            "\n[%s] '%s'",
            mid, market["question"][:60],
        )
        logger.info(
            "  Market price YES=%.2f  |  Consensus YES prob=%.3f ± %.3f",
            market["prices"]["YES"],
            stats["mean_prob"],
            stats["std_prob"],
        )
        logger.info(
            "  Consensus strength: %.3f  |  Entropy: %.4f",
            stats["consensus_strength"],
            consensus.entropy(),
        )

    # ── Step 5: Arbitrage detection ───────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("Arbitrage Detection:")

    detector = ArbitrageDetector(min_arbitrage_gap=0.03)

    # Book arbitrage check
    book_arbs = detector.detect_book_arbitrage(markets)
    if book_arbs:
        logger.info("  Book arbitrage found:")
        for arb in book_arbs:
            logger.info(
                "  [%s] price_sum=%.4f, gap=%.4f, profit=%.2f%%",
                arb["market_id"], arb["price_sum"],
                arb["arbitrage_gap"], arb["expected_profit_pct"],
            )
    else:
        logger.info("  No pure book arbitrage detected.")

    # Directional opportunities from quantum consensus
    belief_probs = {
        mid: float(v["belief_state"].probability(0))
        for mid, v in market_consensus.items()
    }
    directional_opps = detector.qpso_market_search(markets, belief_probs)
    if directional_opps:
        logger.info("  Directional opportunities (belief vs market):")
        for opp in directional_opps[:5]:
            logger.info(
                "  [%s] %s — belief=%.3f, market=%.3f, edge=%.3f",
                opp["market_id"], opp["direction"],
                opp["belief_p"], opp["market_p"], opp["edge"],
            )
    else:
        logger.info("  No directional opportunities above threshold.")

    # ── Step 6: Portfolio optimization via quantum annealing ──────────
    logger.info("\n" + "─" * 50)
    logger.info("Portfolio Optimization (Quantum Annealing):")

    # Combine all opportunities from all agents
    combined_opps = []
    for agent_opps in all_agent_opportunities:
        for opp in agent_opps:
            combined_opps.append(opp)
    combined_opps.sort(key=lambda x: abs(x["edge"]), reverse=True)
    # Deduplicate by market_id (keep highest-edge entry)
    seen = set()
    unique_opps = []
    for opp in combined_opps:
        if opp["market_id"] not in seen:
            seen.add(opp["market_id"])
            unique_opps.append(opp)

    portfolio_optimizer = AnnealingPortfolioOptimizer(
        budget=10_000.0,
        max_positions=5,
        kelly_max=0.25,
    )

    portfolio = portfolio_optimizer.optimize(unique_opps)

    logger.info(
        "  Selected %d positions | Allocated: $%.2f / $%.2f | E[return]: %.4f",
        len(portfolio["positions"]),
        portfolio["total_allocated"],
        portfolio_optimizer.budget,
        portfolio["expected_return"],
    )
    if portfolio["positions"]:
        logger.info("  Positions:")
        for pos in portfolio["positions"]:
            logger.info(
                "    [%s] %s — edge=%.3f, allocation=$%.2f (kelly=%.3f)",
                pos["market_id"], pos.get("direction", "?"),
                pos["edge"], pos["allocation"], pos.get("kelly_fraction", 0),
            )

    # ── Step 7: Execute tasks via agent interface ──────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("Executing tasks via agent interface:")
    for i, agent in enumerate(agents[:2]):
        task = {"task_id": f"market_scan_{i:03d}"}
        result = await agent.execute_task(task)
        logger.info(
            "  Agent %s: success=%s, energy_before=%.4f, energy_after=%.4f, "
            "n_markets=%d",
            agent.agent_id, result.success,
            result.energy_before, result.energy_after,
            result.output.get("n_markets_analyzed", 0),
        )

    logger.info("\n" + "=" * 60)
    logger.info("Polymarket prediction demo complete.")


def run_belief_evolution_demo() -> None:
    """
    Show how a single agent's quantum belief evolves as evidence arrives.
    """
    from hamiltonian_swarm.quantum.quantum_belief import QuantumBeliefState

    logger.info("=" * 60)
    logger.info("Quantum Belief Evolution Demo (single market)")
    logger.info("=" * 60)

    hypotheses = [
        "Fed cuts rates → YES",
        "Fed holds rates → NO",
        "Data dependent → UNCERTAIN",
    ]
    belief = QuantumBeliefState(hypotheses)
    logger.info("Initial state: %s", belief)

    evidence_stream = [
        ("strong_inflation_print", -0.8, 0),  # suppresses YES
        ("labor_market_weak",      +1.2, 0),  # amplifies YES
        ("Fed_hawkish_speech",     -0.5, 0),  # suppresses YES
        ("Fed_dovish_hint",        +0.9, 0),  # amplifies YES
        ("CPI_lower_than_expected", +1.5, 0), # strongly amplifies YES
    ]

    for etype, strength, idx in evidence_stream:
        belief.add_evidence(idx, strength)
        logger.info(
            "  Evidence '%s' (%.1f) → YES_prob=%.3f, NO_prob=%.3f, H=%.4f",
            etype, strength,
            belief.probability(0), belief.probability(1),
            belief.entropy(),
        )

    # Collapse
    decision = belief.collapse()
    logger.info("\nCollapsed decision: '%s'", decision)
    logger.info("Post-collapse entropy: %.6f (should be ~0)", belief.entropy())


if __name__ == "__main__":
    # Step 1: Show single-agent belief dynamics
    run_belief_evolution_demo()
    print()

    # Step 2: Run full multi-agent prediction pipeline
    asyncio.run(run_multi_agent_prediction(n_agents=5))
