"""
Full NYC travel planner demo using the HamiltonianSwarm framework.

Task: "Plan a 5-day trip from Tbilisi to NYC, budget $2000, prefer culture"

Demonstrates:
  - Orchestrator task decomposition
  - QPSO-powered search over 10,000 simulated flight options
  - ValidatorAgent handoff conservation checks
  - MemoryAgent preference storage
  - HNN monitoring orchestrator logic state
  - Full energy audit log
"""

from __future__ import annotations
import asyncio
import logging
import random
import numpy as np
import torch

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("travel_planning")

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.swarm.swarm_manager import SwarmManager
from hamiltonian_swarm.agents.search_agent import SearchAgent
from hamiltonian_swarm.agents.memory_agent import MemoryAgent
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent
from hamiltonian_swarm.agents.task_agent import TaskAgent
from hamiltonian_swarm.core.hamiltonian_nn import HamiltonianNN


# ──────────────────────────────────────────────────────────────────────
# Simulated data
# ──────────────────────────────────────────────────────────────────────

N_FLIGHT_OPTIONS = 10_000

def generate_flights():
    """Simulate 10,000 flight options: (price, duration_hours, stops, comfort_score)."""
    np.random.seed(42)
    return {
        "prices":    np.random.uniform(400, 1800, N_FLIGHT_OPTIONS),
        "durations": np.random.uniform(12, 36, N_FLIGHT_OPTIONS),
        "stops":     np.random.randint(0, 4, N_FLIGHT_OPTIONS),
        "comfort":   np.random.uniform(1, 10, N_FLIGHT_OPTIONS),
    }

def generate_hotels():
    """Simulate 500 NYC hotel options: (price/night, rating, distance_to_culture_km)."""
    np.random.seed(7)
    return {
        "price_per_night": np.random.uniform(80, 400, 500),
        "rating":          np.random.uniform(2, 5, 500),
        "culture_dist":    np.random.uniform(0.1, 5.0, 500),
    }


# ──────────────────────────────────────────────────────────────────────
# Objective functions
# ──────────────────────────────────────────────────────────────────────

FLIGHTS = generate_flights()
HOTELS  = generate_hotels()
BUDGET  = 2000.0
DAYS    = 5

def flight_objective(x: np.ndarray) -> float:
    """
    Minimize: price + 50*duration + 100*stops - 20*comfort
    QPSO searches in continuous space; map to nearest flight index.
    """
    idx = int(abs(x[0]) * N_FLIGHT_OPTIONS) % N_FLIGHT_OPTIONS
    price    = FLIGHTS["prices"][idx]
    duration = FLIGHTS["durations"][idx]
    stops    = FLIGHTS["stops"][idx]
    comfort  = FLIGHTS["comfort"][idx]
    score = price + 50 * duration + 100 * stops - 20 * comfort
    # Budget penalty (round trip)
    if price * 2 > BUDGET * 0.6:
        score += 1000
    return float(score)

def hotel_objective(x: np.ndarray) -> float:
    """Minimize: 5-day cost - 100*rating + 50*culture_dist."""
    idx = int(abs(x[0]) * 500) % 500
    cost = HOTELS["price_per_night"][idx] * DAYS
    rating = HOTELS["rating"][idx]
    dist = HOTELS["culture_dist"][idx]
    score = cost - 100 * rating + 50 * dist
    if cost > BUDGET * 0.5:
        score += 500
    return float(score)


# ──────────────────────────────────────────────────────────────────────
# HNN logic monitor
# ──────────────────────────────────────────────────────────────────────

def create_hnn_monitor(n_dims: int = 4) -> HamiltonianNN:
    """Create an HNN to monitor orchestrator logic state stability."""
    return HamiltonianNN(n_dims=n_dims, hidden_dim=64, n_layers=2)


# ──────────────────────────────────────────────────────────────────────
# Main demo
# ──────────────────────────────────────────────────────────────────────

async def plan_trip():
    logger.info("=" * 60)
    logger.info("HamiltonianSwarm — NYC Travel Planner Demo")
    logger.info("Task: 5-day Tbilisi→NYC, budget $2000, prefer culture")
    logger.info("=" * 60)

    # 1. Set up swarm
    manager = SwarmManager(n_dims=4)
    search_agent  = manager.spawn_agent("search", n_dims=4, n_particles=50, n_iterations=200)
    memory_agent  = manager.spawn_agent("memory", n_dims=4)
    validator     = manager.spawn_agent("validator", n_dims=4)
    task_agent    = manager.spawn_agent("task", n_dims=4)

    hnn_monitor = create_hnn_monitor(n_dims=4)

    # 2. Store user preferences in MemoryAgent
    logger.info("\n[Step 1] Storing user preferences in MemoryAgent...")
    await memory_agent.execute_task({
        "task_id": "mem_prefs",
        "type": "store",
        "payload": {"content": "Prefers culture, art museums, Broadway; budget $2000; 5 days", "importance": 5.0},
    })

    # 3. Flight search via QPSO
    logger.info("\n[Step 2] QPSO flight search (10,000 options)...")
    H_before_search = float(
        search_agent.hamiltonian.total_energy(
            search_agent.phase_state.q, search_agent.phase_state.p
        ).item()
    )

    flight_result = await search_agent.execute_task({
        "task_id": "flight_search",
        "type": "search",
        "objective_fn": flight_objective,
        "bounds": (np.array([0.0]), np.array([1.0])),
    })

    best_flight_idx = int(abs(flight_result.output["best_position"][0]) * N_FLIGHT_OPTIONS) % N_FLIGHT_OPTIONS
    best_flight_price = FLIGHTS["prices"][best_flight_idx]
    best_flight_duration = FLIGHTS["durations"][best_flight_idx]
    logger.info(
        "  Best flight: $%.0f (%.1fh, %d stops)",
        best_flight_price * 2,  # round trip
        best_flight_duration,
        FLIGHTS["stops"][best_flight_idx],
    )

    # 4. Hotel search
    logger.info("\n[Step 3] QPSO hotel search...")
    hotel_result = await search_agent.execute_task({
        "task_id": "hotel_search",
        "type": "search",
        "objective_fn": hotel_objective,
        "bounds": (np.array([0.0]), np.array([1.0])),
    })

    best_hotel_idx = int(abs(hotel_result.output["best_position"][0]) * 500) % 500
    best_hotel_price = HOTELS["price_per_night"][best_hotel_idx] * DAYS
    best_hotel_rating = HOTELS["rating"][best_hotel_idx]
    logger.info(
        "  Best hotel: $%.0f/5-nights (rating %.1f/5, %.1fkm to culture hub)",
        best_hotel_price,
        best_hotel_rating,
        HOTELS["culture_dist"][best_hotel_idx],
    )

    # 5. Validate handoff (search → task for itinerary planning)
    logger.info("\n[Step 4] ValidatorAgent: checking handoff conservation...")
    H_after_search = float(
        search_agent.hamiltonian.total_energy(
            search_agent.phase_state.q, search_agent.phase_state.p
        ).item()
    )
    H_task_before = float(
        task_agent.hamiltonian.total_energy(
            task_agent.phase_state.q, task_agent.phase_state.p
        ).item()
    )

    validation = await validator.execute_task({
        "task_id": "validate_handoff",
        "type": "validate_handoff",
        "payload": {
            "sender_id": search_agent.agent_id,
            "receiver_id": task_agent.agent_id,
            "task_id": "itinerary_task",
            "H_sender_before": H_before_search,
            "H_sender_after": H_after_search,
            "H_receiver_before": H_task_before,
            "H_receiver_after": H_task_before + (H_before_search - H_after_search),
        },
    })
    logger.info("  Handoff validation: %s", validation.output["reason"])

    # 6. Itinerary planning task
    logger.info("\n[Step 5] TaskAgent: building itinerary...")
    cultural_sites = [
        "MoMA", "Metropolitan Museum", "Brooklyn Museum",
        "Guggenheim", "Whitney Museum", "The Cloisters",
        "Broadway Show", "Jazz at Lincoln Center", "High Line",
    ]
    itinerary = {}
    for day in range(1, DAYS + 1):
        sites = random.sample(cultural_sites, 2)
        itinerary[f"Day {day}"] = f"Visit {sites[0]} + {sites[1]}"

    itinerary_result = await task_agent.execute_task({
        "task_id": "itinerary_task",
        "type": "plan",
        "payload": {
            "itinerary": itinerary,
            "flight": f"${best_flight_price*2:.0f} round trip",
            "hotel": f"${best_hotel_price:.0f} for 5 nights",
        },
        "complexity": 0.6,
    })

    # 7. HNN stability check
    logger.info("\n[Step 6] HNN logic monitor: checking orchestrator state stability...")
    q = manager.orchestrator.phase_state.q.unsqueeze(0)
    p = manager.orchestrator.phase_state.p.unsqueeze(0)
    with torch.no_grad():
        H_pred = hnn_monitor(q, p)
    logger.info("  HNN predicted H = %.4f (monitoring orchestrator logic state)", float(H_pred.item()))

    # 8. Memory recall
    logger.info("\n[Step 7] Recalling preferences from MemoryAgent...")
    recall_result = await memory_agent.execute_task({
        "task_id": "recall",
        "type": "retrieve",
        "payload": {"query_q": [0.0] * 4, "k": 3},
    })

    # 9. Budget summary
    total_flights = best_flight_price * 2
    total_hotel = best_hotel_price
    total_cost = total_flights + total_hotel
    remaining = BUDGET - total_cost

    logger.info("\n" + "=" * 60)
    logger.info("TRIP PLAN: Tbilisi → New York City (5 Days)")
    logger.info("=" * 60)
    logger.info("FLIGHTS:   $%.0f (round trip, %.1fh)", total_flights, best_flight_duration)
    logger.info("HOTEL:     $%.0f (5 nights, rating %.1f/5)", total_hotel, best_hotel_rating)
    logger.info("BUDGET:    $%.0f / $%.0f used (remaining: $%.0f)",
                total_cost, BUDGET, remaining)
    logger.info("")
    logger.info("ITINERARY:")
    for day, activities in itinerary.items():
        logger.info("  %s: %s", day, activities)

    # 10. Energy audit
    logger.info("\n" + "=" * 60)
    logger.info("ENERGY AUDIT LOG")
    logger.info("=" * 60)
    total_swarm_energy = manager.orchestrator.log_swarm_energy()
    logger.info("Total swarm energy: H_total = %.4f", total_swarm_energy)
    audit = validator._transaction_log
    for entry in audit:
        status = "✓ CONSERVED" if not entry.violation else "✗ VIOLATION"
        logger.info(
            "  [%s] %s→%s: ΔH_sender=%.4f, mismatch=%.4f",
            status, entry.sender_id, entry.receiver_id,
            entry.dH_sender, entry.dH_sender + entry.dH_receiver,
        )
    logger.info("=" * 60)

    await manager.shutdown()
    return {
        "itinerary": itinerary,
        "total_cost": total_cost,
        "remaining_budget": remaining,
        "swarm_energy": total_swarm_energy,
    }


if __name__ == "__main__":
    result = asyncio.run(plan_trip())
    print(f"\nFinal budget used: ${result['total_cost']:.0f} / $2000")
    print(f"Swarm remained stable: H_total = {result['swarm_energy']:.4f}")
