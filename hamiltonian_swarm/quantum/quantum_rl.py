"""
Quantum-inspired reinforcement learning policy.

Classical policy:  π(a|s) = softmax(W·s)
Quantum policy:    encode s as density matrix ρ = |ψ_s⟩⟨ψ_s|
                   apply parameterized unitary U(θ)
                   measure to get P(a) = Tr(M_a · ρ)

Advantage:
  - Interference between action amplitudes (quantum parallelism simulation)
  - Entangled action correlations (related actions reinforce each other)
  - Natural exploration via quantum randomness

Simulated on classical hardware via density matrix formalism.
"""

from __future__ import annotations
import logging
from typing import List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class QuantumPolicy(nn.Module):
    """
    Quantum-inspired action selection via density matrix formalism.

    Parameters
    ----------
    state_dim : int
        Dimensionality of the state vector.
    n_actions : int
        Number of discrete actions.
    n_circuit_layers : int
        Number of parameterized unitary layers.
    """

    def __init__(
        self,
        state_dim: int,
        n_actions: int,
        n_circuit_layers: int = 2,
    ) -> None:
        super().__init__()
        self.state_dim = state_dim
        self.n_actions = n_actions
        self.n_circuit_layers = n_circuit_layers

        # Parameterized unitary parameters (angles for rotation gates)
        self.theta = nn.Parameter(
            torch.randn(n_circuit_layers, state_dim) * 0.1
        )
        # Measurement operator basis vectors (one per action)
        self.M_basis = nn.Parameter(
            torch.randn(n_actions, state_dim) * 0.1
        )

        logger.info(
            "QuantumPolicy: state_dim=%d, n_actions=%d, layers=%d",
            state_dim, n_actions, n_circuit_layers,
        )

    def encode_state(self, state_vector: torch.Tensor) -> torch.Tensor:
        """
        Convert state vector to density matrix ρ = |ψ⟩⟨ψ|.

        Parameters
        ----------
        state_vector : torch.Tensor
            Shape [state_dim].

        Returns
        -------
        torch.Tensor
            Shape [state_dim, state_dim], complex64.
        """
        psi = F.normalize(state_vector.float(), dim=-1).to(torch.complex64)
        rho = torch.outer(psi, psi.conj())
        return rho

    def apply_unitary(
        self, rho: torch.Tensor, layer_idx: int
    ) -> torch.Tensor:
        """
        Apply parameterized diagonal unitary:
            U = diag(exp(i * theta_layer))
            ρ' = U ρ U†

        Parameters
        ----------
        rho : torch.Tensor
            Density matrix [n, n], complex.
        layer_idx : int

        Returns
        -------
        torch.Tensor
            Evolved density matrix.
        """
        theta = self.theta[layer_idx]
        phase = torch.exp(1j * theta.float()).to(torch.complex64)
        U = torch.diag(phase)
        rho_prime = U @ rho @ U.conj().T
        return rho_prime

    def measure_action(self, rho: torch.Tensor, action_idx: int) -> float:
        """
        Compute P(action) = Tr(M_action · ρ).

        M_action = |m_action⟩⟨m_action| (projector onto action basis vector).

        Parameters
        ----------
        rho : torch.Tensor
            Density matrix [n, n].
        action_idx : int

        Returns
        -------
        float
            Probability of this action.
        """
        m = F.normalize(self.M_basis[action_idx].float(), dim=-1).to(torch.complex64)
        M = torch.outer(m, m.conj())
        return torch.trace(M @ rho).real

    def select_action(self, state: torch.Tensor) -> int:
        """
        Full quantum action selection pipeline.

        1. Encode state as density matrix
        2. Apply all unitary layers
        3. Measure all action probabilities
        4. Sample action from distribution

        Parameters
        ----------
        state : torch.Tensor
            Shape [state_dim].

        Returns
        -------
        int
            Selected action index.
        """
        rho = self.encode_state(state)
        for layer in range(self.n_circuit_layers):
            rho = self.apply_unitary(rho, layer)

        probs = torch.stack(
            [self.measure_action(rho, a) for a in range(self.n_actions)]
        ).float()
        # Ensure valid probability distribution
        probs = probs.clamp(min=0.0)
        prob_sum = probs.sum()
        if prob_sum < 1e-8:
            probs = torch.ones(self.n_actions) / self.n_actions
        else:
            probs = probs / prob_sum

        action = int(torch.multinomial(probs, num_samples=1).item())
        return action

    def action_probabilities(self, state: torch.Tensor) -> torch.Tensor:
        """
        Return full action probability distribution.

        Parameters
        ----------
        state : torch.Tensor

        Returns
        -------
        torch.Tensor
            Shape [n_actions], sums to 1.
        """
        rho = self.encode_state(state)
        for layer in range(self.n_circuit_layers):
            rho = self.apply_unitary(rho, layer)

        probs = torch.stack(
            [self.measure_action(rho, a) for a in range(self.n_actions)]
        ).float().clamp(min=0.0)

        prob_sum = probs.sum()
        return probs / (prob_sum + 1e-8)

    def quantum_advantage_score(
        self,
        classical_probs: torch.Tensor,
        quantum_probs: torch.Tensor,
    ) -> float:
        """
        KL divergence D(quantum || classical) as measure of quantum advantage.

        Larger = quantum policy differs more from classical softmax.
        Not necessarily better, but measures the degree of quantum effect.

        Parameters
        ----------
        classical_probs, quantum_probs : torch.Tensor
            Action probability distributions.

        Returns
        -------
        float
        """
        q = quantum_probs.clamp(min=1e-8)
        p = classical_probs.clamp(min=1e-8)
        kl = torch.sum(q * torch.log(q / p))
        return float(kl.item())

    def update(
        self,
        state: torch.Tensor,
        action: int,
        reward: float,
        lr: float = 1e-3,
    ) -> float:
        """
        Update quantum circuit parameters via REINFORCE policy gradient.

        ∇J(θ) = reward * ∇ log P(action | state)

        Parameters
        ----------
        state : torch.Tensor
        action : int
        reward : float
        lr : float

        Returns
        -------
        float
            Loss value.
        """
        probs = self.action_probabilities(state)
        log_prob = torch.log(probs[action].clamp(min=1e-8))
        loss = -reward * log_prob

        # Manual gradient step
        self.zero_grad()
        loss.backward()
        with torch.no_grad():
            for param in self.parameters():
                if param.grad is not None:
                    param -= lr * param.grad

        return float(loss.item())
