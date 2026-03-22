"""
Tests for EntanglementRegistry, SharedBeliefState, and QuantumCoalition.
"""

import math
import pytest
import torch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.coordination.entanglement_registry import EntanglementRegistry
from hamiltonian_swarm.quantum.quantum_belief import QuantumBeliefState


def _uniform_psi(n: int) -> torch.Tensor:
    """Uniform complex amplitude vector, normalized."""
    v = torch.ones(n, dtype=torch.complex64)
    return v / v.norm()


def _collapsed_psi(n: int, idx: int) -> torch.Tensor:
    """Unit vector along idx."""
    v = torch.zeros(n, dtype=torch.complex64)
    v[idx] = 1.0 + 0j
    return v


class TestEntanglementRegistry:
    def test_entangle_records_link(self):
        """entangle() creates links in both directions."""
        reg = EntanglementRegistry()
        reg.entangle("a1", "a2", "budget")
        assert any(p == "a2" and v == "budget" for p, v in reg.get_partners("a1"))
        assert any(p == "a1" and v == "budget" for p, v in reg.get_partners("a2"))

    def test_disentangle_removes_link(self):
        """disentangle() removes all links between pair."""
        reg = EntanglementRegistry()
        reg.entangle("a1", "a2", "route")
        reg.disentangle("a1", "a2")
        assert len(reg.get_partners("a1")) == 0
        assert len(reg.get_partners("a2")) == 0

    def test_disentangle_leaves_other_links(self):
        """disentangle(a1,a2) must not remove a1↔a3 links."""
        reg = EntanglementRegistry()
        reg.entangle("a1", "a2", "budget")
        reg.entangle("a1", "a3", "route")
        reg.disentangle("a1", "a2")
        partners_a1 = reg.get_partners("a1")
        assert any(p == "a3" for p, _ in partners_a1)
        assert not any(p == "a2" for p, _ in partners_a1)

    def test_get_partners_empty_for_unknown(self):
        """Unregistered agent returns empty set."""
        reg = EntanglementRegistry()
        assert reg.get_partners("ghost") == set()


class TestBeliefSync:
    def test_sync_identical_beliefs_fidelity_one(self):
        """Two identical states should produce fidelity ≈ 1."""
        reg = EntanglementRegistry()
        psi = _uniform_psi(4)
        f = reg.entanglement_fidelity(psi, psi)
        assert abs(f - 1.0) < 1e-5

    def test_sync_orthogonal_beliefs_fidelity_zero(self):
        """Two orthogonal (contradictory) beliefs → fidelity ≈ 0."""
        reg = EntanglementRegistry()
        psi_a = _collapsed_psi(4, 0)
        psi_b = _collapsed_psi(4, 1)
        f = reg.entanglement_fidelity(psi_a, psi_b)
        assert f < 0.01

    def test_sync_result_is_normalized(self):
        """sync_beliefs must return a normalized state."""
        reg = EntanglementRegistry()
        psi_a = _uniform_psi(5)
        psi_b = _uniform_psi(5)
        psi_b = psi_b * torch.exp(torch.tensor(0.5j))  # phase shift
        psi_shared = reg.sync_beliefs("a1", "a2", psi_a, psi_b)
        norm_sq = float(psi_shared.abs().pow(2).sum().real.item())
        assert abs(norm_sq - 1.0) < 1e-5

    def test_sync_identical_agrees(self):
        """Syncing identical states → shared state = original (same probs)."""
        reg = EntanglementRegistry()
        psi = _collapsed_psi(3, 2)
        psi_shared = reg.sync_beliefs("a", "b", psi, psi)
        # Dominant index should still be 2
        probs = psi_shared.abs().pow(2).real
        assert int(probs.argmax().item()) == 2

    def test_contradictory_beliefs_merged(self):
        """A entirely favors X; B entirely favors Y.
        Merged state must not be dominated by either extreme."""
        reg = EntanglementRegistry()
        n = 4
        psi_a = _collapsed_psi(n, 0)   # certainty X
        psi_b = _collapsed_psi(n, n-1) # certainty Y

        psi_shared = reg.sync_beliefs("a", "b", psi_a, psi_b)
        probs = psi_shared.abs().pow(2).real
        # Neither outcome can dominate with probability > 0.9
        assert float(probs.max().item()) < 0.9


class TestMeasureEntangled:
    def test_measurement_propagates_to_partner(self):
        """Measuring agent a collapses partner b's state on the variable."""
        reg = EntanglementRegistry()
        reg.entangle("a", "b", "budget")
        n = 4
        beliefs = {
            "a": _uniform_psi(n),
            "b": _uniform_psi(n),
        }
        updated = reg.measure_entangled("a", "budget", "outcome_X", beliefs)
        # b's state must now be a unit vector (collapsed)
        b_probs = updated["b"].abs().pow(2).real
        assert abs(float(b_probs.sum().item()) - 1.0) < 1e-5
        assert float(b_probs.max().item()) > 0.99  # fully collapsed

    def test_measurement_no_effect_on_non_partner(self):
        """Measurement of a on 'budget' must not change c (unrelated)."""
        reg = EntanglementRegistry()
        reg.entangle("a", "b", "budget")
        psi_c = _uniform_psi(4)
        beliefs = {
            "a": _uniform_psi(4),
            "b": _uniform_psi(4),
            "c": psi_c.clone(),
        }
        updated = reg.measure_entangled("a", "budget", "X", beliefs)
        # c unchanged
        assert torch.allclose(updated["c"].abs(), psi_c.abs(), atol=1e-6)


class TestFidelityAfterSync:
    def test_fidelity_one_after_full_sync(self):
        """After syncing with itself, fidelity of synced state with original = 1."""
        reg = EntanglementRegistry()
        psi = _uniform_psi(6)
        psi_synced = reg.sync_beliefs("a", "b", psi, psi)
        f = reg.entanglement_fidelity(psi, psi_synced)
        assert abs(f - 1.0) < 1e-5

    def test_fidelity_range(self):
        """Fidelity must always lie in [0, 1]."""
        reg = EntanglementRegistry()
        torch.manual_seed(42)
        for _ in range(10):
            n = 5
            psi_a = torch.randn(n, dtype=torch.complex64)
            psi_b = torch.randn(n, dtype=torch.complex64)
            f = reg.entanglement_fidelity(psi_a, psi_b)
            assert 0.0 <= f <= 1.0 + 1e-6


class TestIndependentEvolutionAfterDisentangle:
    def test_disentangled_beliefs_evolve_independently(self):
        """After disentangle, updating a's belief doesn't affect b."""
        reg = EntanglementRegistry()
        reg.entangle("a", "b", "var")
        reg.disentangle("a", "b")

        n = 4
        beliefs = {
            "a": _uniform_psi(n),
            "b": _uniform_psi(n),
        }
        b_before = beliefs["b"].clone()

        # Measure a — should NOT propagate to b since disentangled
        updated = reg.measure_entangled("a", "var", "X", beliefs)
        assert torch.allclose(updated["b"].abs(), b_before.abs(), atol=1e-6)
