"""
Loss functions for Hamiltonian Neural Network training.

Total loss:
    L = L_dynamics + λ * L_conservation + μ * L_symplectic

Where:
    L_dynamics    = MSE(dq/dt_pred, dq/dt_true) + MSE(dp/dt_pred, dp/dt_true)
    L_conservation = Var[H(q_t, p_t)] over trajectory (should be zero)
    L_symplectic  = penalty for phase-space volume expansion
"""

from __future__ import annotations
import torch
import torch.nn as nn
from typing import Tuple


def hamiltonian_loss(
    model: nn.Module,
    q: torch.Tensor,
    p: torch.Tensor,
    dqdt_true: torch.Tensor,
    dpdt_true: torch.Tensor,
    lambda_conservation: float = 0.5,
    mu_symplectic: float = 0.1,
) -> Tuple[torch.Tensor, dict]:
    """
    Full Hamiltonian training loss.

    Parameters
    ----------
    model : HamiltonianNN
    q, p : torch.Tensor
        Shape [batch, n_dims].
    dqdt_true, dpdt_true : torch.Tensor
        True derivatives, same shape.
    lambda_conservation : float
        Weight for conservation loss.
    mu_symplectic : float
        Weight for symplectic regularizer.

    Returns
    -------
    total_loss : torch.Tensor
    breakdown : dict
        {'dynamics': float, 'conservation': float, 'symplectic': float}
    """
    q_in = q.requires_grad_(True)
    p_in = p.requires_grad_(True)

    # Predicted Hamiltonian
    H = model(q_in, p_in)  # [batch]

    # Predicted dynamics via autograd
    H_sum = H.sum()
    dH_dq = torch.autograd.grad(H_sum, q_in, create_graph=True, retain_graph=True)[0]
    dH_dp = torch.autograd.grad(H_sum, p_in, create_graph=True, retain_graph=True)[0]

    dqdt_pred = dH_dp
    dpdt_pred = -dH_dq

    # Dynamics loss
    L_dyn = (
        nn.functional.mse_loss(dqdt_pred, dqdt_true)
        + nn.functional.mse_loss(dpdt_pred, dpdt_true)
    )

    # Conservation loss: H should be constant → variance ≈ 0
    L_cons = conservation_loss(H)

    # Symplectic regularizer
    L_symp = symplectic_regularizer(q_in, p_in, dH_dq, dH_dp)

    total = L_dyn + lambda_conservation * L_cons + mu_symplectic * L_symp

    return total, {
        "dynamics": float(L_dyn.item()),
        "conservation": float(L_cons.item()),
        "symplectic": float(L_symp.item()),
        "total": float(total.item()),
    }


def conservation_loss(H: torch.Tensor) -> torch.Tensor:
    """
    Variance of H over a trajectory batch.

    A perfectly conserved Hamiltonian has Var[H] = 0.

    Parameters
    ----------
    H : torch.Tensor
        Shape [batch] — H values over a trajectory.

    Returns
    -------
    torch.Tensor
        Scalar variance.
    """
    return torch.var(H)


def symplectic_regularizer(
    q: torch.Tensor,
    p: torch.Tensor,
    dH_dq: torch.Tensor,
    dH_dp: torch.Tensor,
) -> torch.Tensor:
    """
    Penalize volume expansion in phase space.

    The symplectic condition requires:
        ∂(dq/dt)/∂q + ∂(dp/dt)/∂p = 0   (divergence-free flow)

    This is equivalent to:
        div(f) = ∂dH_dp/∂q - ∂(-dH_dq)/∂p
               = ∂dH_dp/∂q + ∂dH_dq/∂p  ← should be 0

    We approximate by penalizing ||dH_dp||² variance as a soft proxy.

    Parameters
    ----------
    q, p : torch.Tensor
        Phase-space coordinates.
    dH_dq, dH_dp : torch.Tensor
        Gradient tensors.

    Returns
    -------
    torch.Tensor
        Scalar regularization penalty.
    """
    # Soft proxy: penalize large gradient magnitudes (encourages bounded flow)
    return 0.5 * (dH_dq.pow(2).mean() + dH_dp.pow(2).mean())
