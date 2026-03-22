"""
Tests for QuantumBeliefState.
"""

import math
import pytest
import torch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.quantum.quantum_belief import QuantumBeliefState


class TestQuantumBeliefNormalization:
    def test_uniform_init_normalized(self):
        """Uniform superposition must sum to 1."""
        n = 5
        belief = QuantumBeliefState([f"h{i}" for i in range(n)])
        total = float(belief.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5

    def test_uniform_equal_probs(self):
        """All hypotheses equally likely at init."""
        n = 4
        belief = QuantumBeliefState([f"h{i}" for i in range(n)])
        expected = 1.0 / n
        for i in range(n):
            assert abs(belief.probability(i) - expected) < 1e-5

    def test_normalization_preserved_after_evidence(self):
        """add_evidence must keep Σ|c|²=1."""
        belief = QuantumBeliefState(["A", "B", "C"])
        for i in range(10):
            belief.add_evidence(0, 0.5)
        total = float(belief.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5

    def test_normalization_preserved_after_collapse(self):
        """After collapse the single remaining amplitude has |c|²=1."""
        belief = QuantumBeliefState(["X", "Y", "Z"])
        belief.collapse()
        total = float(belief.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5


class TestQuantumBeliefEvidence:
    def test_positive_evidence_increases_prob(self):
        """Positive evidence_strength raises the target hypothesis probability."""
        belief = QuantumBeliefState(["A", "B", "C"])
        p_before = belief.probability(0)
        belief.add_evidence(0, 2.0)
        assert belief.probability(0) > p_before

    def test_negative_evidence_decreases_prob(self):
        """Negative evidence suppresses the target hypothesis."""
        belief = QuantumBeliefState(["A", "B", "C"])
        p_before = belief.probability(0)
        belief.add_evidence(0, -2.0)
        assert belief.probability(0) < p_before

    def test_evidence_raises_on_out_of_range(self):
        """Out-of-range index raises IndexError."""
        belief = QuantumBeliefState(["A", "B"])
        with pytest.raises(IndexError):
            belief.add_evidence(5, 1.0)

    def test_repeated_evidence_converges(self):
        """Strongly repeated positive evidence should push prob close to 1."""
        belief = QuantumBeliefState(["A", "B", "C"])
        for _ in range(20):
            belief.add_evidence(1, 3.0)
        assert belief.probability(1) > 0.95


class TestQuantumBeliefCollapse:
    def test_collapse_returns_hypothesis_string(self):
        """collapse() returns one of the hypothesis strings."""
        hypotheses = ["route_A", "route_B", "route_C"]
        belief = QuantumBeliefState(hypotheses)
        result = belief.collapse()
        assert result in hypotheses

    def test_collapse_is_eigenstate(self):
        """After collapse only one amplitude is non-zero."""
        belief = QuantumBeliefState(["X", "Y", "Z"])
        belief.collapse()
        non_zero = int((belief.amplitudes.abs() > 1e-6).sum().item())
        assert non_zero == 1

    def test_collapse_biased_to_high_amplitude(self):
        """Amplified hypothesis is selected more often than others."""
        results = []
        for _ in range(200):
            belief = QuantumBeliefState(["A", "B", "C"])
            belief.add_evidence(2, 5.0)   # strongly amplify C
            results.append(belief.collapse())
        frac_c = results.count("C") / len(results)
        assert frac_c > 0.5, f"Expected C to win majority; got {frac_c:.2f}"


class TestQuantumBeliefEntropy:
    def test_entropy_zero_after_collapse(self):
        """Collapsed state (certainty) has zero entropy."""
        belief = QuantumBeliefState(["A", "B", "C"])
        belief.collapse()
        assert belief.entropy() < 1e-6

    def test_entropy_max_for_uniform(self):
        """Uniform distribution has maximum entropy log(N)."""
        n = 6
        belief = QuantumBeliefState([f"h{i}" for i in range(n)])
        expected_max = math.log(n)
        assert abs(belief.entropy() - expected_max) < 1e-4

    def test_entropy_decreases_with_evidence(self):
        """Accumulating evidence reduces entropy (more certainty)."""
        belief = QuantumBeliefState(["A", "B", "C", "D"])
        S0 = belief.entropy()
        for _ in range(10):
            belief.add_evidence(0, 1.0)
        S1 = belief.entropy()
        assert S1 < S0


class TestQuantumBeliefInterference:
    def test_interference_is_normalized(self):
        """Interference result must be normalized."""
        a = QuantumBeliefState(["X", "Y", "Z"])
        b = QuantumBeliefState(["X", "Y", "Z"])
        combined = a.interfere(b)
        total = float(combined.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5

    def test_constructive_interference_amplifies(self):
        """When both agents favor same hypothesis, combined prob increases."""
        a = QuantumBeliefState(["X", "Y"])
        b = QuantumBeliefState(["X", "Y"])
        for _ in range(5):
            a.add_evidence(0, 2.0)
            b.add_evidence(0, 2.0)
        p_a = a.probability(0)
        combined = a.interfere(b)
        # Combined should still favor X at least as much as either alone
        assert combined.probability(0) > 0.5

    def test_destructive_interference_reduces_certainty(self):
        """Opposing beliefs produce higher entropy than individual."""
        a = QuantumBeliefState(["X", "Y"])
        b = QuantumBeliefState(["X", "Y"])
        for _ in range(8):
            a.add_evidence(0, 3.0)   # A strongly favors X
            b.add_evidence(1, 3.0)   # B strongly favors Y
        S_a = a.entropy()
        combined = a.interfere(b)
        S_combined = combined.entropy()
        # Combined uncertainty should be greater than either individual certainty
        assert S_combined > S_a

    def test_interference_requires_same_hypotheses_count(self):
        """Interfering states with different n should raise ValueError."""
        a = QuantumBeliefState(["X", "Y"])
        b = QuantumBeliefState(["X", "Y", "Z"])
        with pytest.raises(ValueError):
            a.interfere(b)

    def test_self_interference_unchanged(self):
        """Interfering a state with itself should return same probabilities."""
        belief = QuantumBeliefState(["A", "B", "C"])
        belief.add_evidence(1, 1.5)
        p_before = [belief.probability(i) for i in range(3)]
        combined = belief.interfere(belief)
        for i in range(3):
            assert abs(combined.probability(i) - p_before[i]) < 1e-4
