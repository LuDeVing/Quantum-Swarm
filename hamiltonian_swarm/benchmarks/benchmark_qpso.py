"""
QPSO vs classical PSO vs Gradient Descent benchmark on standard functions.

Run:
    python -m hamiltonian_swarm.benchmarks.benchmark_qpso
"""

from __future__ import annotations
import time
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.quantum.qpso import QPSO


# ──────────────────────────────────────────────────────────────────────
# Benchmark functions (minimization, global min = 0)
# ──────────────────────────────────────────────────────────────────────

BENCHMARKS = {
    "Sphere":      lambda x: float(np.sum(x**2)),
    "Rastrigin":   lambda x: float(10*len(x) + np.sum(x**2 - 10*np.cos(2*np.pi*x))),
    "Rosenbrock":  lambda x: float(np.sum(100*(x[1:]-x[:-1]**2)**2 + (1-x[:-1])**2)),
    "Ackley":      lambda x: float(-20*np.exp(-0.2*np.sqrt(np.mean(x**2)))
                                   - np.exp(np.mean(np.cos(2*np.pi*x))) + 20 + np.e),
}


def run_qpso(fn, n_dims=10, n_runs=5):
    results = []
    for _ in range(n_runs):
        lb = np.full(n_dims, -5.0)
        ub = np.full(n_dims, 5.0)
        qpso = QPSO(n_particles=30, n_dims=n_dims, bounds=(lb, ub), n_iterations=500)
        t0 = time.time()
        _, best, _ = qpso.optimize(fn)
        elapsed = time.time() - t0
        results.append((best, elapsed))
    return results


def gradient_descent(fn, n_dims=10, lr=0.01, steps=5000):
    """Simple gradient descent baseline using finite differences."""
    x = np.random.uniform(-5.0, 5.0, n_dims)
    eps = 1e-5
    t0 = time.time()
    for _ in range(steps):
        grad = np.array([(fn(x + eps*np.eye(n_dims)[i]) - fn(x - eps*np.eye(n_dims)[i]))
                         / (2*eps) for i in range(n_dims)])
        x = x - lr * grad
    return float(fn(x)), time.time() - t0


if __name__ == "__main__":
    N = 10
    print(f"\n{'='*60}")
    print(f"QPSO vs Gradient Descent  |  n_dims={N}")
    print(f"{'='*60}")
    print(f"{'Function':<14} | {'QPSO best':>12} | {'GD best':>12} | {'QPSO time':>10}")
    print(f"{'-'*60}")

    for name, fn in BENCHMARKS.items():
        qpso_results = run_qpso(fn, n_dims=N, n_runs=3)
        qpso_best = np.mean([r[0] for r in qpso_results])
        qpso_time = np.mean([r[1] for r in qpso_results])
        gd_val, gd_time = gradient_descent(fn, n_dims=N)
        print(f"{name:<14} | {qpso_best:>12.6f} | {gd_val:>12.6f} | {qpso_time:>9.2f}s")
    print(f"{'='*60}\n")
