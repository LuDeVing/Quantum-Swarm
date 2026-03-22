"""
Robotic path optimization via QPSO.

Problem: Find minimum-energy path from start to goal in a 2D grid with obstacles.

The energy objective encodes:
  - Path length (kinetic energy)
  - Obstacle avoidance penalties (potential energy)
  - Smoothness regularization
"""

from __future__ import annotations
import logging
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("robot_qpso")

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.quantum.qpso import QPSO
from hamiltonian_swarm.quantum.quantum_tunneling import QuantumTunneling


# ──────────────────────────────────────────────────────────────────────
# Path parameterization
# ──────────────────────────────────────────────────────────────────────

START = np.array([0.0, 0.0])
GOAL  = np.array([10.0, 10.0])
N_WAYPOINTS = 8  # intermediate waypoints (x,y pairs = 16 dims)

OBSTACLES = [
    {"center": np.array([3.0, 3.0]), "radius": 1.5},
    {"center": np.array([6.0, 5.0]), "radius": 1.2},
    {"center": np.array([7.0, 8.0]), "radius": 1.0},
    {"center": np.array([2.0, 7.0]), "radius": 0.8},
]


def decode_path(x: np.ndarray) -> np.ndarray:
    """Decode QPSO position vector to waypoint path."""
    waypoints = x.reshape(N_WAYPOINTS, 2)
    path = np.vstack([START, waypoints, GOAL])
    return path


def path_objective(x: np.ndarray) -> float:
    """
    Path cost = total length + obstacle penalties + smoothness regularizer.

    Parameters
    ----------
    x : np.ndarray
        Shape [N_WAYPOINTS * 2] — flattened waypoint coordinates.
    """
    path = decode_path(x)

    # 1. Path length
    diffs = np.diff(path, axis=0)
    length = float(np.sum(np.linalg.norm(diffs, axis=1)))

    # 2. Obstacle penalties
    obs_penalty = 0.0
    for wp in path[1:-1]:  # only intermediate waypoints
        for obs in OBSTACLES:
            dist = np.linalg.norm(wp - obs["center"])
            if dist < obs["radius"] * 2:
                obs_penalty += (obs["radius"] * 2 - dist) ** 2 * 100

    # 3. Smoothness: penalize sharp turns
    smoothness = 0.0
    for i in range(1, len(path) - 1):
        v1 = path[i] - path[i-1]
        v2 = path[i+1] - path[i]
        curvature = np.linalg.norm(v2 - v1)
        smoothness += curvature

    return length + obs_penalty + smoothness * 0.1


if __name__ == "__main__":
    n_dims = N_WAYPOINTS * 2
    lb = np.zeros(n_dims)
    ub = np.full(n_dims, 10.0)

    tunneling = QuantumTunneling()

    logger.info("QPSO robot path optimization: %d dims, %d waypoints", n_dims, N_WAYPOINTS)
    qpso = QPSO(
        n_particles=50,
        n_dims=n_dims,
        bounds=(lb, ub),
        n_iterations=300,
        alpha_max=1.0,
        alpha_min=0.4,
    )
    best_pos, best_val, history = qpso.optimize(path_objective, tunneling=tunneling)

    logger.info("Optimization complete: path cost = %.4f", best_val)

    optimal_path = decode_path(best_pos)

    # Plot
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # Path visualization
    ax = axes[0]
    for obs in OBSTACLES:
        circle = plt.Circle(obs["center"], obs["radius"], color="red", alpha=0.4)
        ax.add_patch(circle)
    ax.plot(optimal_path[:, 0], optimal_path[:, 1], "b-o", lw=2, ms=6, label="Optimal path")
    ax.plot(*START, "g^", ms=12, label="Start")
    ax.plot(*GOAL, "r*", ms=14, label="Goal")
    ax.set_xlim(-0.5, 10.5); ax.set_ylim(-0.5, 10.5)
    ax.set_title(f"Optimal Robot Path (cost={best_val:.2f})")
    ax.legend(); ax.grid(True, alpha=0.3); ax.set_aspect("equal")

    # Convergence
    axes[1].plot(history, "b-", lw=1.5)
    axes[1].set_xlabel("Iteration"); axes[1].set_ylabel("Path cost")
    axes[1].set_title("QPSO Convergence")
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("robot_path_qpso.png", dpi=150, bbox_inches="tight")
    logger.info("Plot saved → robot_path_qpso.png")
