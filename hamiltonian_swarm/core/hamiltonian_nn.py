"""
Hamiltonian Neural Network (HNN).

The HNN learns a scalar Hamiltonian H_θ(q, p) from trajectory data such that
the derived dynamics match observations:

    dq/dt =  ∂H_θ/∂p
    dp/dt = -∂H_θ/∂q

Loss = MSE(predicted dq/dt, true dq/dt)
     + MSE(predicted dp/dt, true dp/dt)
     + λ * Var[H_θ(q_t, p_t)]   ← conservation regulariser
"""

from __future__ import annotations
import logging
from typing import List, Tuple

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


class HamiltonianNN(nn.Module):
    """
    Hamiltonian Neural Network.

    Architecture:
        Input  : [q, p]  →  shape [2 * n_dims]
        Hidden : MLP, depth=n_layers, width=hidden_dim, Tanh activations
        Output : scalar H_θ(q, p)

    Parameters
    ----------
    n_dims : int
        Dimensionality of each of q and p.
    hidden_dim : int
        Width of each hidden layer.
    n_layers : int
        Number of hidden layers.
    """

    def __init__(
        self,
        n_dims: int,
        hidden_dim: int = 256,
        n_layers: int = 3,
    ) -> None:
        super().__init__()
        self.n_dims = n_dims
        input_dim = 2 * n_dims

        layers: List[nn.Module] = []
        in_features = input_dim
        for _ in range(n_layers):
            layers.append(nn.Linear(in_features, hidden_dim))
            layers.append(nn.Tanh())
            in_features = hidden_dim
        layers.append(nn.Linear(hidden_dim, 1))

        self.net = nn.Sequential(*layers)
        logger.info(
            "HamiltonianNN created: n_dims=%d, hidden_dim=%d, n_layers=%d",
            n_dims,
            hidden_dim,
            n_layers,
        )

    # ------------------------------------------------------------------
    # Forward pass
    # ------------------------------------------------------------------

    def forward(self, q: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """
        Compute predicted Hamiltonian H_θ(q, p).

        Parameters
        ----------
        q : torch.Tensor
            Positions, shape [batch, n_dims] or [n_dims].
        p : torch.Tensor
            Momenta, shape [batch, n_dims] or [n_dims].

        Returns
        -------
        torch.Tensor
            Scalar (or batch of scalars) H_θ values.
        """
        x = torch.cat([q, p], dim=-1)
        return self.net(x).squeeze(-1)

    # ------------------------------------------------------------------
    # Dynamics via autograd
    # ------------------------------------------------------------------

    def time_derivative(
        self, q: torch.Tensor, p: torch.Tensor
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Compute equations of motion:
            dq/dt =  ∂H_θ/∂p
            dp/dt = -∂H_θ/∂q

        Parameters
        ----------
        q : torch.Tensor
            Positions, shape [batch, n_dims] or [n_dims].
        p : torch.Tensor
            Momenta, same shape as q.

        Returns
        -------
        dq_dt : torch.Tensor
        dp_dt : torch.Tensor
        """
        q_ = q.detach().requires_grad_(True)
        p_ = p.detach().requires_grad_(True)

        H = self.forward(q_, p_)
        H_sum = H.sum()  # sum over batch for autograd

        dH_dq = torch.autograd.grad(H_sum, q_, create_graph=True, retain_graph=True)[0]
        dH_dp = torch.autograd.grad(H_sum, p_, create_graph=True, retain_graph=True)[0]

        dq_dt = dH_dp
        dp_dt = -dH_dq

        return dq_dt, dp_dt

    # ------------------------------------------------------------------
    # Conservation metric
    # ------------------------------------------------------------------

    def energy_error(
        self, q_traj: torch.Tensor, p_traj: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute mean absolute energy drift over a trajectory:
            mean |H(q_t, p_t) - H(q_0, p_0)|

        Parameters
        ----------
        q_traj : torch.Tensor
            Shape [T, n_dims].
        p_traj : torch.Tensor
            Shape [T, n_dims].

        Returns
        -------
        torch.Tensor
            Scalar energy error.
        """
        with torch.no_grad():
            H_traj = self.forward(q_traj, p_traj)
            H0 = H_traj[0]
            return (H_traj - H0).abs().mean()
