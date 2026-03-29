"""
Lindblad Master Equation for agent role coherence.

Models agent beliefs as an open quantum system — a density matrix ρ that
can represent both pure states (coherent, on-task agent) and mixed states
(drifted, decohered agent).

Equation of motion:
    dρ/dt = -i[H, ρ]  +  Σₖ γₖ(LₖρLₖ† - ½{Lₖ†Lₖ, ρ})
              coherent       dissipative (drift + restoration)

Key metric — purity Tr(ρ²):
    1.0  = pure state, agent fully coherent on its role
    0.33 = maximally mixed, agent has completely lost role coherence
    < 0.5 → anomaly detected, role reinforcement triggered
"""

from __future__ import annotations

import logging
import math
from typing import Dict, List

import torch

from hamiltonian_swarm.core.information_entropy import InformationEntropy

logger = logging.getLogger(__name__)


class LindBladBeliefState:
    """
    Agent belief state as a density matrix ρ evolved under the Lindblad equation.

    Basis states
    ------------
    0 = healthy   (E=0, ground state — agent is on-task, coherent)
    1 = uncertain (E=1, intermediate)
    2 = confused  (E=2, excited state — agent has drifted from role)

    Parameters
    ----------
    hypotheses : list of str
        Must be ["healthy", "uncertain", "confused"] in that order.
    energy_levels : torch.Tensor
        Energy eigenvalues, shape [3]. Default [0., 1., 2.].
    gamma_restore : float
        Lindblad restoring rate — strength of pull back toward healthy ground state.
    gamma_noise : float
        Lindblad noise rate — rate of context-driven drift toward confused state.
    """

    def __init__(
        self,
        hypotheses: List[str],
        energy_levels: torch.Tensor,
        gamma_restore: float = 0.3,
        gamma_noise: float = 0.05,
    ) -> None:
        self.hypotheses = hypotheses
        self.n = len(hypotheses)
        self.gamma_restore = gamma_restore
        self.gamma_noise = gamma_noise

        # Hamiltonian: diagonal with energy levels
        self._H = torch.diag(energy_levels.to(torch.complex128))

        # Lindblad operators (complex128 for numerical stability)
        # L_restore: |healthy⟩⟨confused| — confused → healthy
        L_restore = torch.zeros(self.n, self.n, dtype=torch.complex128)
        L_restore[0, 2] = 1.0

        # L_partial: |healthy⟩⟨uncertain| — uncertain → healthy
        L_partial = torch.zeros(self.n, self.n, dtype=torch.complex128)
        L_partial[0, 1] = 1.0

        # L_noise: |confused⟩⟨healthy| — healthy → confused (context drift)
        L_noise = torch.zeros(self.n, self.n, dtype=torch.complex128)
        L_noise[2, 0] = 1.0

        self._lindblad_ops = [
            (L_restore, gamma_restore),
            (L_partial,  gamma_restore / 2.0),
            (L_noise,    gamma_noise),
        ]

        # Initial state: uniform mixture ρ = I/3 — agent starts with no prior.
        # The first measurement (belief report) determines the state.
        # Lindblad restoring force then drives clean agents toward |healthy⟩⟨healthy|.
        self.rho = torch.eye(self.n, dtype=torch.complex128) / self.n

        logger.debug(
            "LindBladBeliefState created: n=%d, gamma_restore=%.3f, gamma_noise=%.3f",
            self.n, gamma_restore, gamma_noise,
        )

    # ------------------------------------------------------------------
    # Core update methods
    # ------------------------------------------------------------------

    def apply_measurement(self, similarities: Dict[str, float]) -> None:
        """
        Bayesian-quantum update from cosine similarities to basis state prototypes.

        Builds a diagonal measurement operator M = diag(sim_healthy, sim_uncertain, sim_confused)
        and applies: ρ → M ρ M† / Tr(M ρ M†)

        Parameters
        ----------
        similarities : dict
            Keys must match self.hypotheses. Values are cosine similarities in [-1, 1].
            Shifted to [0, 1] internally so all weights are non-negative.
        """
        # Shift cosine similarities from [-1,1] to [0,1] to keep M positive
        vals = torch.tensor(
            [max(0.0, (similarities[h] + 1.0) / 2.0) for h in self.hypotheses],
            dtype=torch.complex128,
        )
        # Avoid degenerate all-zero measurement
        if vals.abs().max() < 1e-8:
            return

        M = torch.diag(vals)
        rho_new = M @ self.rho @ M.conj().T
        trace = rho_new.trace().real.item()
        if trace < 1e-10:
            return   # measurement gave zero probability — skip update
        self.rho = rho_new / trace
        self._enforce_valid()

    def evolve(self, dt: float = 1.0) -> None:
        """
        Advance density matrix by one Lindblad step (first-order Euler).

        dρ = [-i(Hρ - ρH) + Σₖ γₖ(LₖρLₖ† - ½(Lₖ†LₖρQ + ρLₖ†Lₖ))] dt
        """
        # Coherent part: -i[H, ρ]
        drho = -1j * (self._H @ self.rho - self.rho @ self._H) * dt

        # Dissipative part
        for L, gamma in self._lindblad_ops:
            Ld = L.conj().T
            LdL = Ld @ L
            drho = drho + gamma * (
                L @ self.rho @ Ld
                - 0.5 * (LdL @ self.rho + self.rho @ LdL)
            ) * dt

        self.rho = self.rho + drho
        self._enforce_valid()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def purity(self) -> float:
        """Tr(ρ²) ∈ [1/n, 1.0]. 1.0 = pure/coherent. 1/n = maximally mixed/drifted."""
        return float((self.rho @ self.rho).trace().real.item())

    def expectation_H(self) -> float:
        """⟨H⟩ = Tr(ρH) ∈ [0, max(E)]. Higher = more confused/energetic."""
        return float((self.rho @ self._H).trace().real.item())

    def entropy(self) -> float:
        """Von Neumann entropy S(ρ) = -Tr(ρ log ρ). 0 = pure. log(n) = maximally mixed."""
        return InformationEntropy.von_neumann_entropy(self.rho)

    def probability(self, i: int) -> float:
        """Population of basis state i — diagonal element ρ[i,i]."""
        return float(self.rho[i, i].real.item())

    def probabilities(self) -> torch.Tensor:
        """Real diagonal of ρ — population vector summing to 1."""
        return self.rho.diagonal().real.float()

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset to uniform ρ = I/n — next measurement will re-establish state."""
        self.rho = torch.eye(self.n, dtype=torch.complex128) / self.n
        logger.debug("LindBladBeliefState reset to uniform I/n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enforce_valid(self) -> None:
        """
        Project ρ back to the set of valid density matrices:
        1. Hermitian:            ρ = (ρ + ρ†) / 2
        2. Positive semi-definite: clamp eigenvalues ≥ 0 via eigendecomposition
        3. Trace = 1:            ρ = ρ / Tr(ρ)
        """
        # 1. Hermitianise
        self.rho = (self.rho + self.rho.conj().T) / 2.0

        # 2. Positive semi-definite: decompose, clamp, reconstruct
        eigvals, eigvecs = torch.linalg.eigh(self.rho)
        eigvals = eigvals.real.clamp(min=0.0).to(torch.complex128)
        self.rho = eigvecs @ torch.diag(eigvals) @ eigvecs.conj().T

        # 3. Normalise trace
        trace = self.rho.trace().real.item()
        if trace > 1e-10:
            self.rho = self.rho / trace
        else:
            # Fallback: reset to uniform mixed state
            self.rho = torch.eye(self.n, dtype=torch.complex128) / self.n

    def __repr__(self) -> str:
        return (
            f"LindBladBeliefState("
            f"purity={self.purity():.3f}, "
            f"⟨H⟩={self.expectation_H():.3f}, "
            f"S={self.entropy():.3f}, "
            f"healthy={self.probability(0):.2f}, "
            f"confused={self.probability(2):.2f})"
        )
