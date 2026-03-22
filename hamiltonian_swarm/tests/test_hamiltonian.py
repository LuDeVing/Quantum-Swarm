"""
Tests for Hamiltonian mechanics core.

Verifies:
  1. Leapfrog energy conservation over 1000 steps (|ΔH/H| < 1e-4)
  2. Gradient correctness via finite differences
  3. Symplectic structure: det(Jacobian) ≈ 1
"""

import pytest
import torch
import numpy as np

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.core.phase_space import PhaseSpaceState
from hamiltonian_swarm.core.hamiltonian import HamiltonianFunction


@pytest.fixture
def ham():
    return HamiltonianFunction(n_dims=2, mass_scale=1.0, stiffness_scale=1.0)


@pytest.fixture
def init_state():
    q = torch.tensor([1.0, 0.5])
    p = torch.tensor([0.3, -0.7])
    return PhaseSpaceState(q=q, p=p, agent_id="test")


# ──────────────────────────────────────────────────────────────────────
# 1. Energy conservation
# ──────────────────────────────────────────────────────────────────────

class TestEnergyConservation:
    def test_leapfrog_conservation_1000_steps(self, ham, init_state):
        """Leapfrog should conserve energy with |ΔH/H| < 1e-4 over 1000 steps."""
        trajectory = ham.integrate_leapfrog(init_state, dt=0.01, n_steps=1000)
        H0 = float(ham.total_energy(trajectory[0].q, trajectory[0].p).item())
        H_values = [float(ham.total_energy(s.q, s.p).item()) for s in trajectory]
        max_drift = max(abs(H - H0) for H in H_values) / (abs(H0) + 1e-12)
        assert max_drift < 1e-4, f"Leapfrog energy drift {max_drift:.2e} exceeds 1e-4"

    def test_symplectic_euler_bounded(self, ham, init_state):
        """Symplectic Euler energy should remain bounded (no exponential growth)."""
        trajectory = ham.integrate_symplectic_euler(init_state, dt=0.01, n_steps=500)
        H0 = float(ham.total_energy(trajectory[0].q, trajectory[0].p).item())
        H_final = float(ham.total_energy(trajectory[-1].q, trajectory[-1].p).item())
        # Should not blow up — allow 5x growth as conservative bound
        assert abs(H_final) < abs(H0) * 5.0 + 0.1, f"Symplectic Euler diverged: H={H_final:.4f}"


# ──────────────────────────────────────────────────────────────────────
# 2. Gradient correctness (finite difference check)
# ──────────────────────────────────────────────────────────────────────

class TestGradients:
    def test_dH_dq_finite_difference(self, ham):
        """∂H/∂q from autograd should match finite-difference approximation."""
        q = torch.tensor([0.5, -1.2])
        p = torch.tensor([0.3, 0.8])
        eps = 1e-4

        grad_autograd = ham.dH_dq(q)

        grad_fd = torch.zeros_like(q)
        for i in range(len(q)):
            q_plus = q.clone(); q_plus[i] += eps
            q_minus = q.clone(); q_minus[i] -= eps
            V_plus = float(ham.potential_energy(q_plus).item())
            V_minus = float(ham.potential_energy(q_minus).item())
            grad_fd[i] = (V_plus - V_minus) / (2 * eps)

        assert torch.allclose(grad_autograd, grad_fd, atol=1e-3), \
            f"dH/dq mismatch: autograd={grad_autograd}, fd={grad_fd}"

    def test_dH_dp_finite_difference(self, ham):
        """∂H/∂p from autograd should match finite-difference approximation."""
        q = torch.tensor([1.0, 0.2])
        p = torch.tensor([-0.5, 1.1])
        eps = 1e-4

        grad_autograd = ham.dH_dp(p)

        grad_fd = torch.zeros_like(p)
        for i in range(len(p)):
            p_plus = p.clone(); p_plus[i] += eps
            p_minus = p.clone(); p_minus[i] -= eps
            T_plus = float(ham.kinetic_energy(p_plus).item())
            T_minus = float(ham.kinetic_energy(p_minus).item())
            grad_fd[i] = (T_plus - T_minus) / (2 * eps)

        assert torch.allclose(grad_autograd, grad_fd, atol=1e-3), \
            f"dH/dp mismatch: autograd={grad_autograd}, fd={grad_fd}"


# ──────────────────────────────────────────────────────────────────────
# 3. Symplectic structure
# ──────────────────────────────────────────────────────────────────────

class TestSymplecticStructure:
    def test_leapfrog_jacobian_determinant(self, ham):
        """
        For a linear Hamiltonian, det(Jacobian of leapfrog map) should be ≈ 1.

        We numerically estimate the Jacobian via finite differences on the map
        (q0, p0) → (q1, p1) for one leapfrog step.
        """
        n = 2
        eps = 1e-4
        q0 = torch.tensor([0.3, 0.7])
        p0 = torch.tensor([-0.4, 0.6])

        def leapfrog_map(q, p):
            state = PhaseSpaceState(q=q.clone(), p=p.clone())
            traj = ham.integrate_leapfrog(state, dt=0.05, n_steps=1)
            return traj[-1].q, traj[-1].p

        # Build Jacobian columns via finite differences on full (q,p) vector
        x0 = torch.cat([q0, p0])
        J = torch.zeros(2*n, 2*n)
        for i in range(2*n):
            x_plus = x0.clone(); x_plus[i] += eps
            x_minus = x0.clone(); x_minus[i] -= eps
            q_p, p_p = leapfrog_map(x_plus[:n], x_plus[n:])
            q_m, p_m = leapfrog_map(x_minus[:n], x_minus[n:])
            f_plus = torch.cat([q_p, p_p])
            f_minus = torch.cat([q_m, p_m])
            J[:, i] = (f_plus - f_minus) / (2 * eps)

        det = float(torch.linalg.det(J).item())
        assert abs(det - 1.0) < 0.01, f"Leapfrog Jacobian det={det:.6f}, expected 1.0"


# ──────────────────────────────────────────────────────────────────────
# 4. PhaseSpaceState
# ──────────────────────────────────────────────────────────────────────

class TestPhaseSpaceState:
    def test_to_from_tensor_roundtrip(self):
        q = torch.tensor([1.0, 2.0, 3.0])
        p = torch.tensor([4.0, 5.0, 6.0])
        state = PhaseSpaceState(q=q, p=p)
        tensor = state.to_tensor()
        restored = PhaseSpaceState.from_tensor(tensor)
        assert torch.allclose(restored.q, q)
        assert torch.allclose(restored.p, p)

    def test_energy_norm(self):
        q = torch.tensor([3.0, 4.0])
        p = torch.tensor([0.0, 0.0])
        state = PhaseSpaceState(q=q, p=p)
        assert abs(state.energy_norm() - 5.0) < 1e-5

    def test_symplectic_area_circle(self):
        """For a circle trajectory (SHO), ∫p dq = -π A² (area of ellipse)."""
        n = 500
        t = np.linspace(0, 2 * np.pi, n, endpoint=False)
        A = 1.0
        states = [
            PhaseSpaceState(
                q=torch.tensor([A * np.cos(ti)]),
                p=torch.tensor([-A * np.sin(ti)]),
            )
            for ti in t
        ]
        area = PhaseSpaceState.symplectic_area(states)
        # Expected: -π (for unit circle traversed clockwise)
        assert abs(abs(area) - np.pi * A**2) < 0.1, f"Symplectic area={area:.4f}"
