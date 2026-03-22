"""
Von Neumann entropy and related information-theoretic measures
for agent state analysis.

S(ρ) = -Tr(ρ log ρ) = -Σ λᵢ log λᵢ

Applied to:
- Agent belief state density matrix
- Swarm state collective uncertainty
- Phase-space distribution entropy
"""

from __future__ import annotations
import logging
import math
from typing import Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)


class InformationEntropy:
    """
    Von Neumann entropy and coherence measures for agent states.

    Parameters
    ----------
    n_agents : int
        Number of agents to track.
    """

    def __init__(self, n_agents: int) -> None:
        self.n_agents = n_agents
        logger.debug("InformationEntropy tracker: n_agents=%d", n_agents)

    # ------------------------------------------------------------------
    # Density matrix utilities
    # ------------------------------------------------------------------

    @staticmethod
    def build_density_matrix(state_vector: torch.Tensor) -> torch.Tensor:
        """
        Build density matrix ρ = |ψ⟩⟨ψ| from a (normalized) state vector.

        Parameters
        ----------
        state_vector : torch.Tensor
            Complex or real, shape [n].

        Returns
        -------
        torch.Tensor
            Shape [n, n], complex64.
        """
        psi = state_vector.to(torch.complex64)
        norm = psi.norm()
        if norm > 1e-8:
            psi = psi / norm
        rho = torch.outer(psi, psi.conj())
        return rho

    @staticmethod
    def von_neumann_entropy(rho: torch.Tensor) -> float:
        """
        S(ρ) = -Tr(ρ log ρ) = -Σ λᵢ log λᵢ  for λᵢ > 0.

        Parameters
        ----------
        rho : torch.Tensor
            Density matrix [n, n], Hermitian, trace = 1.

        Returns
        -------
        float
            Entropy ≥ 0. 0 = pure state. log(n) = maximally mixed.
        """
        eigvals = torch.linalg.eigvalsh(rho.real).clamp(min=1e-15)
        eigvals = eigvals / eigvals.sum()
        S = float(-torch.sum(eigvals * torch.log(eigvals)).item())
        return S

    @staticmethod
    def classical_entropy(probs: torch.Tensor) -> float:
        """
        Shannon entropy H = -Σ pᵢ log pᵢ.

        Parameters
        ----------
        probs : torch.Tensor
            Probability vector summing to 1, shape [n].

        Returns
        -------
        float
        """
        p = probs.float().clamp(min=1e-15)
        p = p / p.sum()
        return float(-torch.sum(p * torch.log(p)).item())

    @staticmethod
    def relative_entropy(rho: torch.Tensor, sigma: torch.Tensor) -> float:
        """
        Quantum relative entropy (KL divergence):
        S(ρ||σ) = Tr(ρ (log ρ - log σ))

        Approximated via eigendecomposition.

        Parameters
        ----------
        rho, sigma : torch.Tensor
            Density matrices [n, n].

        Returns
        -------
        float
            Relative entropy ≥ 0.
        """
        eig_rho = torch.linalg.eigvalsh(rho.real).clamp(min=1e-15)
        eig_sig = torch.linalg.eigvalsh(sigma.real).clamp(min=1e-15)
        eig_rho = eig_rho / eig_rho.sum()
        eig_sig = eig_sig / eig_sig.sum()
        # Approximate using aligned eigenvalues
        return float(torch.sum(eig_rho * (torch.log(eig_rho) - torch.log(eig_sig))).item())

    # ------------------------------------------------------------------
    # Swarm-level measures
    # ------------------------------------------------------------------

    def swarm_entropy(self, agent_state_vectors: list[torch.Tensor]) -> float:
        """
        Mean Von Neumann entropy across all agents.

        Parameters
        ----------
        agent_state_vectors : list of torch.Tensor
            Each shape [n_dims], representing agent phase-space state.

        Returns
        -------
        float
        """
        entropies = []
        for sv in agent_state_vectors:
            rho = self.build_density_matrix(sv)
            entropies.append(self.von_neumann_entropy(rho))
        return float(np.mean(entropies)) if entropies else 0.0

    def mutual_information(
        self,
        rho_ab: torch.Tensor,
        rho_a: torch.Tensor,
        rho_b: torch.Tensor,
    ) -> float:
        """
        Quantum mutual information:
        I(A:B) = S(A) + S(B) - S(AB)

        Parameters
        ----------
        rho_ab : torch.Tensor
            Joint density matrix [n*m, n*m].
        rho_a, rho_b : torch.Tensor
            Marginal density matrices [n, n] and [m, m].

        Returns
        -------
        float
        """
        S_ab = self.von_neumann_entropy(rho_ab)
        S_a = self.von_neumann_entropy(rho_a)
        S_b = self.von_neumann_entropy(rho_b)
        return max(0.0, S_a + S_b - S_ab)
