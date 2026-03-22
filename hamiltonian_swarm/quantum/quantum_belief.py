"""
Quantum Belief State for agents.

An agent holds multiple hypotheses simultaneously before committing:

    ψ_agent = Σ cᵢ |hypothesis_i⟩

Each hypothesis is a possible interpretation of the task.
|cᵢ|² = probability the agent assigns to hypothesis i.

The agent "collapses" to one hypothesis when it must act.
After acting, amplitudes are updated (Bayesian-quantum update).
"""

from __future__ import annotations
import logging
import math
from typing import List, Optional

import torch
import numpy as np

logger = logging.getLogger(__name__)


class QuantumBeliefState:
    """
    Quantum superposition of agent hypotheses.

    Parameters
    ----------
    hypotheses : list of str
        Candidate interpretations or task framings.
    """

    def __init__(self, hypotheses: List[str]) -> None:
        if not hypotheses:
            raise ValueError("At least one hypothesis required.")
        self.hypotheses = hypotheses
        n = len(hypotheses)
        # Uniform superposition: cᵢ = 1/√N
        self.amplitudes: torch.Tensor = torch.full(
            (n,), 1.0 / math.sqrt(n), dtype=torch.complex64
        )
        logger.debug(
            "QuantumBeliefState created: %d hypotheses, uniform init.", n
        )

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize(self) -> None:
        """Enforce Σ|cᵢ|² = 1."""
        norm = float(self.amplitudes.abs().pow(2).sum().sqrt().item())
        if norm < 1e-12:
            n = len(self.hypotheses)
            self.amplitudes = torch.full(
                (n,), 1.0 / math.sqrt(n), dtype=torch.complex64
            )
            return
        self.amplitudes = self.amplitudes / norm
        # Verify
        total = float(self.amplitudes.abs().pow(2).sum().item())
        assert abs(total - 1.0) < 1e-5, f"Normalization failed: Σ|c|²={total}"

    # ------------------------------------------------------------------
    # Probability
    # ------------------------------------------------------------------

    def probability(self, i: int) -> float:
        """Return |cᵢ|²."""
        return float(self.amplitudes[i].abs().pow(2).item())

    def probabilities(self) -> torch.Tensor:
        """Return all |cᵢ|² as a real tensor."""
        return self.amplitudes.abs().pow(2).real

    # ------------------------------------------------------------------
    # Evidence update
    # ------------------------------------------------------------------

    def add_evidence(self, hypothesis_idx: int, evidence_strength: float) -> None:
        """
        Update amplitude based on new evidence:
            cᵢ → cᵢ * exp(evidence_strength)
            then renormalize.

        Positive evidence_strength amplifies hypothesis i.
        Negative evidence_strength suppresses it.

        Parameters
        ----------
        hypothesis_idx : int
        evidence_strength : float
        """
        if not (0 <= hypothesis_idx < len(self.hypotheses)):
            raise IndexError(f"hypothesis_idx {hypothesis_idx} out of range.")
        scale = math.exp(evidence_strength)
        new_amps = self.amplitudes.clone()
        new_amps[hypothesis_idx] = new_amps[hypothesis_idx] * scale
        self.amplitudes = new_amps
        self.normalize()
        logger.debug(
            "Evidence update: hypothesis=%d, strength=%.3f, new_prob=%.4f",
            hypothesis_idx, evidence_strength, self.probability(hypothesis_idx),
        )

    # ------------------------------------------------------------------
    # Collapse (measurement)
    # ------------------------------------------------------------------

    def collapse(self) -> str:
        """
        Sample one hypothesis weighted by |cᵢ|², then collapse to it.

        Returns
        -------
        str
            The selected hypothesis text.
        """
        probs = self.probabilities().numpy().astype(float)
        probs = probs / probs.sum()
        idx = int(np.random.choice(len(self.hypotheses), p=probs))
        selected = self.hypotheses[idx]
        # Collapse amplitudes to eigenstate |idx⟩
        new_amps = torch.zeros_like(self.amplitudes)
        new_amps[idx] = 1.0 + 0j
        self.amplitudes = new_amps
        logger.info("Belief collapsed → hypothesis[%d]: '%s'", idx, selected[:80])
        return selected

    # ------------------------------------------------------------------
    # Entropy
    # ------------------------------------------------------------------

    def entropy(self) -> float:
        """
        S = -Σ |cᵢ|² log|cᵢ|²  (belief uncertainty measure).

        Returns
        -------
        float
            0 = certain (collapsed), log(N) = maximally uncertain.
        """
        probs = self.probabilities()
        probs = probs.clamp(min=1e-12)
        return float(-torch.sum(probs * torch.log(probs)).item())

    # ------------------------------------------------------------------
    # Interference
    # ------------------------------------------------------------------

    def interfere(self, other: "QuantumBeliefState") -> "QuantumBeliefState":
        """
        Combine two agents' beliefs via amplitude addition:
            ψ_combined = (ψ_A + ψ_B) / √2

        Hypotheses must match. Use when two agents share the same problem.

        Parameters
        ----------
        other : QuantumBeliefState

        Returns
        -------
        QuantumBeliefState
            New combined belief state.
        """
        if len(self.hypotheses) != len(other.hypotheses):
            raise ValueError("Cannot interfere belief states with different hypothesis counts.")
        combined_amps = (self.amplitudes + other.amplitudes) / math.sqrt(2)
        result = QuantumBeliefState(self.hypotheses.copy())
        result.amplitudes = combined_amps
        result.normalize()
        logger.debug("Belief states interfered: combined entropy=%.4f", result.entropy())
        return result

    def __repr__(self) -> str:
        top_idx = int(self.probabilities().argmax().item())
        return (
            f"QuantumBeliefState(n={len(self.hypotheses)}, "
            f"top='{self.hypotheses[top_idx][:40]}' "
            f"P={self.probability(top_idx):.3f}, "
            f"S={self.entropy():.3f})"
        )
