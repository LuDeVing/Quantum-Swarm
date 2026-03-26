"""
Swarm vs Baseline test using Gemini.

Compares:
  A) Single Gemini call (baseline) — one prompt, one answer
  B) HamiltonianSwarm pipeline — 4 agents, energy validation, quantum belief aggregation

Metric: Brier score = (predicted_probability - actual_outcome)^2
Lower is better. Random guessing = 0.25.

Usage:
    pip install google-generativeai requests
    set GEMINI_API_KEY=your_key_here
    python swarm_test.py
"""

import os
import json
import math
import asyncio
import requests
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv()

from google import genai

# ── Config ──────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-3-flash-preview"

# These markets are real and will resolve — update with live ones from Polymarket
# Format: {question, market_yes_price, actual_outcome (fill in after resolution)}
TEST_MARKETS = [
    {
        "question": "Will the US Federal Reserve cut interest rates at its next meeting?",
        "description": "Resolves YES if the Fed announces a rate cut at the next FOMC meeting.",
        "market_yes_price": 0.35,
        "actual_outcome": None,  # fill in after resolution: 1.0 = YES, 0.0 = NO
    },
    {
        "question": "Will Bitcoin exceed $100,000 before end of 2025?",
        "description": "Resolves YES if BTC/USD closes above $100,000 on any day before Dec 31 2025.",
        "market_yes_price": 0.55,
        "actual_outcome": None,
    },
    {
        "question": "Will US unemployment rate exceed 5% in 2025?",
        "description": "Resolves YES if the BLS reports unemployment above 5% for any month in 2025.",
        "market_yes_price": 0.20,
        "actual_outcome": None,
    },
    {
        "question": "Will the S&P 500 end 2025 higher than it started?",
        "description": "Resolves YES if SPX close on Dec 31 2025 > SPX close on Jan 1 2025.",
        "market_yes_price": 0.62,
        "actual_outcome": None,
    },
    {
        "question": "Will there be a US recession declared in 2025?",
        "description": "Resolves YES if NBER officially declares a US recession starting in 2025.",
        "market_yes_price": 0.28,
        "actual_outcome": None,
    },
]

# ── Gemini client ────────────────────────────────────────────────────────────

_client = genai.Client(api_key=GEMINI_API_KEY)


def call_gemini(prompt: str) -> str:
    response = _client.models.generate_content(model=MODEL, contents=prompt)
    return response.text.strip()


def extract_probability(text: str) -> float:
    """Pull the first float from a Gemini response."""
    import re
    matches = re.findall(r"0\.\d+|\d+\.\d+|\d+%", text)
    for m in matches:
        if "%" in m:
            return float(m.replace("%", "")) / 100
        v = float(m)
        if 0.0 <= v <= 1.0:
            return v
    return 0.5  # fallback


# ── Test A: Baseline (single call) ──────────────────────────────────────────

def baseline_predict(market: Dict) -> float:
    prompt = f"""You are a prediction market analyst.

Market: {market['question']}
Description: {market['description']}
Current market price (YES): {market['market_yes_price']}

What probability (0.0 to 1.0) would you assign to this resolving YES?
Reply with ONLY a single number between 0 and 1."""

    response = call_gemini(prompt)
    prob = extract_probability(response)
    print(f"  [baseline] {market['question'][:60]}... → {prob:.2f}")
    return prob


# ── Test B: Swarm (4 agents + belief aggregation) ───────────────────────────

def search_agent(market: Dict) -> float:
    """Searches for relevant context and estimates probability from news/facts."""
    prompt = f"""You are a research agent. Your job is to estimate the probability
of this prediction market resolving YES based on publicly known facts and recent trends.

Market: {market['question']}
Description: {market['description']}

Give your probability estimate as a single number between 0 and 1.
Think step by step, then end your response with: PROBABILITY: X.XX"""

    response = call_gemini(prompt)
    prob = extract_probability(response.split("PROBABILITY:")[-1] if "PROBABILITY:" in response else response)
    print(f"    [search_agent]     raw prob = {prob:.3f}")
    return prob


def task_agent(market: Dict) -> float:
    """Reasons about fundamentals and base rates."""
    prompt = f"""You are a fundamental analysis agent. Estimate the probability
of this market resolving YES using base rates, historical data, and economic reasoning.

Market: {market['question']}
Description: {market['description']}
Current market consensus (YES price): {market['market_yes_price']}

Do you agree with the market, or does your analysis suggest the true probability is higher or lower?
Give your probability estimate as a single number between 0 and 1.
End your response with: PROBABILITY: X.XX"""

    response = call_gemini(prompt)
    prob = extract_probability(response.split("PROBABILITY:")[-1] if "PROBABILITY:" in response else response)
    print(f"    [task_agent]       raw prob = {prob:.3f}")
    return prob


def memory_agent(market: Dict) -> float:
    """Checks for correlated past events to calibrate estimate."""
    prompt = f"""You are a historical pattern agent. Estimate the probability
of this market resolving YES by finding the most similar past events and their outcomes.

Market: {market['question']}
Description: {market['description']}

What similar events have happened before? What fraction resolved YES?
Give your probability estimate as a single number between 0 and 1.
End your response with: PROBABILITY: X.XX"""

    response = call_gemini(prompt)
    prob = extract_probability(response.split("PROBABILITY:")[-1] if "PROBABILITY:" in response else response)
    print(f"    [memory_agent]     raw prob = {prob:.3f}")
    return prob


def validator_agent(market: Dict, agent_probs: List[float]) -> float:
    """Checks for contradictions and produces a final validated estimate."""
    estimates_str = "\n".join([f"  Agent {i+1}: {p:.3f}" for i, p in enumerate(agent_probs)])
    disagreement = max(agent_probs) - min(agent_probs)

    prompt = f"""You are a validator agent. Three analysis agents have produced
probability estimates for this market. Your job is to identify if any estimate
looks like an outlier or contradiction, and produce a final validated estimate.

Market: {market['question']}
Current market price (YES): {market['market_yes_price']}

Agent estimates:
{estimates_str}

Disagreement range: {disagreement:.3f}
{"WARNING: High disagreement between agents — treat as uncertain." if disagreement > 0.2 else "Agents roughly agree."}

Give your final validated probability between 0 and 1.
End your response with: PROBABILITY: X.XX"""

    response = call_gemini(prompt)
    prob = extract_probability(response.split("PROBABILITY:")[-1] if "PROBABILITY:" in response else response)
    print(f"    [validator_agent]  validated = {prob:.3f}  (agent spread = {disagreement:.3f})")
    return prob


def quantum_belief_aggregate(agent_probs: List[float]) -> Dict:
    """
    Quantum belief state aggregation.
    Each agent's estimate is treated as an amplitude.
    Final probability = amplitude-weighted mean.
    Entropy = -sum(|c_i|^2 * log(|c_i|^2)) where c_i are normalized weights.
    """
    # Amplitudes: weight by inverse distance from 0.5 (more confident = more weight)
    confidences = [abs(p - 0.5) + 0.01 for p in agent_probs]
    total = sum(confidences)
    weights = [c / total for c in confidences]

    final_prob = sum(w * p for w, p in zip(weights, agent_probs))

    # Von Neumann-style entropy on belief distribution
    entropy = -sum(w * math.log(w + 1e-9) for w in weights)
    max_entropy = math.log(len(weights))
    normalized_entropy = entropy / max_entropy  # 0 = certain, 1 = maximally uncertain

    return {
        "probability": final_prob,
        "entropy": normalized_entropy,
        "uncertain": normalized_entropy > 0.8,
        "agent_spread": max(agent_probs) - min(agent_probs),
    }


def hamiltonian_energy_check(prob_before: float, prob_after: float, tolerance: float = 0.4) -> bool:
    """
    Handoff energy conservation check.
    If the probability changed by more than tolerance, flag it.
    In real implementation this uses full phase-space H(q,p).
    Here we use the simplified scalar version for the test.
    """
    drift = abs(prob_after - prob_before)
    return drift < tolerance  # True = handoff is valid


def swarm_predict(market: Dict) -> Dict:
    # Run 3 specialist agents
    p_search = search_agent(market)
    p_task = task_agent(market)
    p_memory = memory_agent(market)

    # Handoff validation: check each agent's output is within energy tolerance of market price
    for name, prob in [("search", p_search), ("task", p_task), ("memory", p_memory)]:
        valid = hamiltonian_energy_check(market["market_yes_price"], prob, tolerance=0.5)
        if not valid:
            print(f"    ⚠ Energy mismatch on {name}_agent (drift={abs(prob - market['market_yes_price']):.2f}) — flagged")

    # Validator produces final estimate
    p_validated = validator_agent(market, [p_search, p_task, p_memory])

    # Quantum belief aggregation across all 4 estimates
    all_probs = [p_search, p_task, p_memory, p_validated]
    belief = quantum_belief_aggregate(all_probs)

    print(f"    [belief_state]     final = {belief['probability']:.3f}  entropy = {belief['entropy']:.2f}{'  ⚠ UNCERTAIN' if belief['uncertain'] else ''}")
    return belief


# ── Brier score ──────────────────────────────────────────────────────────────

def brier_score(predicted: float, actual: float) -> float:
    return (predicted - actual) ** 2


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    if not GEMINI_API_KEY:
        print("ERROR: Set GEMINI_API_KEY environment variable first.")
        return

    print(f"\n{'='*60}")
    print(f"  HamiltonianSwarm vs Baseline — Gemini {MODEL}")
    print(f"{'='*60}\n")

    results = []

    for i, market in enumerate(TEST_MARKETS):
        print(f"\nMarket {i+1}: {market['question']}")
        print(f"  Market price (YES): {market['market_yes_price']}")
        print(f"\n  --- BASELINE (single call) ---")
        baseline_prob = baseline_predict(market)

        print(f"\n  --- SWARM (4 agents + belief aggregation) ---")
        swarm_result = swarm_predict(market)
        swarm_prob = swarm_result["probability"]

        results.append({
            "question": market["question"],
            "market_price": market["market_yes_price"],
            "baseline_prob": baseline_prob,
            "swarm_prob": swarm_prob,
            "swarm_entropy": swarm_result["entropy"],
            "swarm_uncertain": swarm_result["uncertain"],
            "agent_spread": swarm_result["agent_spread"],
            "actual_outcome": market["actual_outcome"],
        })

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  RESULTS SUMMARY")
    print(f"{'='*60}\n")

    print(f"{'Market':<45} {'Mkt':>5} {'Base':>5} {'Swarm':>6} {'Entropy':>8} {'Spread':>7}")
    print("-" * 80)
    for r in results:
        flag = "⚠" if r["swarm_uncertain"] else " "
        print(
            f"{r['question'][:44]:<44} "
            f"{r['market_price']:>5.2f} "
            f"{r['baseline_prob']:>5.2f} "
            f"{r['swarm_prob']:>6.2f} "
            f"{r['swarm_entropy']:>8.2f} "
            f"{r['agent_spread']:>6.2f} {flag}"
        )

    # Only compute Brier scores if actuals are filled in
    actuals_filled = [r for r in results if r["actual_outcome"] is not None]
    if actuals_filled:
        baseline_brier = sum(brier_score(r["baseline_prob"], r["actual_outcome"]) for r in actuals_filled) / len(actuals_filled)
        swarm_brier = sum(brier_score(r["swarm_prob"], r["actual_outcome"]) for r in actuals_filled) / len(actuals_filled)
        market_brier = sum(brier_score(r["market_price"], r["actual_outcome"]) for r in actuals_filled) / len(actuals_filled)

        print(f"\n  Brier Scores (lower = better, random = 0.25):")
        print(f"    Market price:  {market_brier:.4f}")
        print(f"    Baseline:      {baseline_brier:.4f}")
        print(f"    Swarm:         {swarm_brier:.4f}")

        if swarm_brier < baseline_brier:
            improvement = (baseline_brier - swarm_brier) / baseline_brier * 100
            print(f"\n  ✓ Swarm outperformed baseline by {improvement:.1f}%")
        else:
            degradation = (swarm_brier - baseline_brier) / baseline_brier * 100
            print(f"\n  ✗ Swarm underperformed baseline by {degradation:.1f}%")
    else:
        print("\n  NOTE: Fill in actual_outcome (1.0/0.0) in TEST_MARKETS after markets resolve")
        print("  to compute Brier scores. For now, inspect the agent spreads and entropy values.")
        print("\n  What to look for NOW (before resolution):")
        print("  - Agent spread < 0.15 = agents agree = swarm is confident")
        print("  - Agent spread > 0.25 = agents disagree = market is genuinely uncertain")
        print("  - Entropy > 0.80 = flagged as uncertain (shown with ⚠)")
        print("  - Compare swarm_prob vs market_price — large differences = potential edge")

    # Save results to JSON for later scoring
    with open("swarm_test_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\n  Results saved to swarm_test_results.json")
    print("  Fill in actual_outcome values after markets resolve and re-run to get Brier scores.\n")


if __name__ == "__main__":
    asyncio.run(main())
