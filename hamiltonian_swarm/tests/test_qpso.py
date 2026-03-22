"""
Tests for QPSO optimizer and quantum tunneling.
"""

import pytest
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.quantum.qpso import QPSO
from hamiltonian_swarm.quantum.quantum_tunneling import QuantumTunneling


# ──────────────────────────────────────────────────────────────────────
# Benchmark functions
# ──────────────────────────────────────────────────────────────────────

def sphere(x):
    return float(np.sum(x**2))

def rastrigin(x):
    n = len(x)
    return float(10 * n + np.sum(x**2 - 10 * np.cos(2 * np.pi * x)))

def rosenbrock(x):
    return float(np.sum(100 * (x[1:] - x[:-1]**2)**2 + (1 - x[:-1])**2))

def ackley(x):
    n = len(x)
    a, b, c = 20, 0.2, 2 * np.pi
    sum1 = np.sum(x**2)
    sum2 = np.sum(np.cos(c * x))
    return float(-a * np.exp(-b * np.sqrt(sum1/n)) - np.exp(sum2/n) + a + np.e)


# ──────────────────────────────────────────────────────────────────────
# QPSO tests
# ──────────────────────────────────────────────────────────────────────

class TestQPSO:
    def _make_qpso(self, n_dims=5, n_iter=300):
        lb = np.full(n_dims, -5.0)
        ub = np.full(n_dims, 5.0)
        return QPSO(
            n_particles=40,
            n_dims=n_dims,
            bounds=(lb, ub),
            n_iterations=n_iter,
        )

    def test_sphere_global_minimum(self):
        """QPSO should find sphere minimum (0) within 0.1 tolerance."""
        qpso = self._make_qpso(n_dims=5, n_iter=200)
        _, best_val, _ = qpso.optimize(sphere)
        assert best_val < 0.1, f"Sphere: best_val={best_val:.4f} > 0.1"

    def test_rastrigin_near_minimum(self):
        """QPSO should find Rastrigin minimum (0) within 1.0 for 5D."""
        qpso = self._make_qpso(n_dims=5, n_iter=400)
        _, best_val, _ = qpso.optimize(rastrigin)
        assert best_val < 1.0, f"Rastrigin: best_val={best_val:.4f}"

    def test_ackley_global_minimum(self):
        """QPSO should find Ackley minimum (0) within 0.5 for 5D."""
        lb = np.full(5, -32.0); ub = np.full(5, 32.0)
        qpso = QPSO(n_particles=40, n_dims=5, bounds=(lb, ub), n_iterations=400)
        _, best_val, _ = qpso.optimize(ackley)
        assert best_val < 0.5, f"Ackley: best_val={best_val:.4f}"

    def test_convergence_history_monotone(self):
        """Convergence history must be non-increasing (gbest can only improve)."""
        qpso = self._make_qpso(n_dims=3, n_iter=100)
        _, _, history = qpso.optimize(sphere)
        for i in range(1, len(history)):
            assert history[i] <= history[i-1] + 1e-10, \
                f"Convergence non-monotone at step {i}: {history[i-1]:.6f} → {history[i]:.6f}"

    def test_ring_topology(self):
        """Ring topology QPSO should still converge on sphere."""
        qpso = QPSO(
            n_particles=20, n_dims=3,
            bounds=(np.full(3, -5.0), np.full(3, 5.0)),
            n_iterations=200,
            topology="ring",
        )
        _, best_val, _ = qpso.optimize(sphere)
        assert best_val < 0.5, f"Ring QPSO sphere: {best_val:.4f}"


# ──────────────────────────────────────────────────────────────────────
# Tunneling tests
# ──────────────────────────────────────────────────────────────────────

class TestQuantumTunneling:
    def setup_method(self):
        self.tun = QuantumTunneling(hbar=1.0, mass=1.0)

    def test_classical_transmission(self):
        """Particle above barrier → T = 1.0."""
        T = self.tun.tunneling_probability(
            barrier_height=1.0, barrier_width=1.0, particle_energy=2.0
        )
        assert T == 1.0

    def test_below_barrier_less_than_one(self):
        """Particle below barrier → T ∈ (0, 1)."""
        T = self.tun.tunneling_probability(
            barrier_height=5.0, barrier_width=1.0, particle_energy=1.0
        )
        assert 0.0 < T < 1.0, f"Expected T ∈ (0,1), got {T}"

    def test_monotone_decreasing_width(self):
        """Tunneling probability decreases monotonically with barrier width."""
        V0, E = 2.0, 0.5
        probs = [
            self.tun.tunneling_probability(V0, L, E)
            for L in [0.1, 0.5, 1.0, 2.0, 5.0]
        ]
        for i in range(1, len(probs)):
            assert probs[i] < probs[i-1], \
                f"T not decreasing: {probs[i-1]:.6f} → {probs[i]:.6f}"

    def test_analytic_value(self):
        """Check T against known analytic: T = exp(-2 * L * sqrt(2m(V-E)) / hbar)."""
        import math
        V0, L, E, m, hbar = 2.0, 1.0, 0.5, 1.0, 1.0
        expected = math.exp(-2 * L * math.sqrt(2 * m * (V0 - E)) / hbar)
        computed = self.tun.tunneling_probability(V0, L, E)
        assert abs(computed - expected) < 1e-10, f"Analytic mismatch: {computed} vs {expected}"

    def test_should_tunnel_deterministic(self):
        """With rng=0 (< any T>0) tunneling should always occur for weak barriers."""
        result = self.tun.should_tunnel(
            current_value=0.5,
            local_min_value=0.5,
            barrier_estimate=0.001,  # tiny barrier → T near 1
            rng=0.0001,              # very small u
        )
        assert result is True
