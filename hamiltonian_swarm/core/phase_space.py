"""
Phase space (q, p) state representation for Hamiltonian mechanics.

In Hamiltonian mechanics, the state of a system is fully described by
generalized coordinates q and conjugate momenta p, forming a 2n-dimensional
phase space.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import torch

logger = logging.getLogger(__name__)


@dataclass
class PhaseSpaceState:
    """
    Represents a point in phase space (q, p).

    Attributes
    ----------
    q : torch.Tensor
        Generalized coordinates, shape [n_dims].
    p : torch.Tensor
        Conjugate momenta, shape [n_dims].
    timestamp : float
        Unix timestamp of state creation.
    agent_id : str
        Identifier of the owning agent.
    """

    q: torch.Tensor
    p: torch.Tensor
    timestamp: float = field(default_factory=time.time)
    agent_id: str = "unknown"

    def __post_init__(self) -> None:
        if self.q.shape != self.p.shape:
            raise ValueError(
                f"q and p must have the same shape, got {self.q.shape} vs {self.p.shape}"
            )
        logger.debug(
            "PhaseSpaceState created for agent=%s, n_dims=%d",
            self.agent_id,
            self.q.shape[0],
        )

    # ------------------------------------------------------------------
    # Tensor conversion
    # ------------------------------------------------------------------

    def to_tensor(self) -> torch.Tensor:
        """
        Convert (q, p) to a flat PyTorch tensor.

        Returns
        -------
        torch.Tensor
            Shape [2 * n_dims], float32.
        """
        return torch.cat([self.q, self.p], dim=0)

    @classmethod
    def from_tensor(
        cls, tensor: torch.Tensor, agent_id: str = "unknown"
    ) -> "PhaseSpaceState":
        """
        Reconstruct a PhaseSpaceState from a flat tensor.

        Parameters
        ----------
        tensor : torch.Tensor
            Shape [2 * n_dims].
        agent_id : str
            Agent identifier.

        Returns
        -------
        PhaseSpaceState
        """
        if tensor.ndim != 1 or tensor.shape[0] % 2 != 0:
            raise ValueError(
                f"Expected 1-D tensor with even length, got shape {tensor.shape}"
            )
        n = tensor.shape[0] // 2
        return cls(q=tensor[:n].clone(), p=tensor[n:].clone(), agent_id=agent_id)

    # ------------------------------------------------------------------
    # Energy / geometry
    # ------------------------------------------------------------------

    def energy_norm(self) -> float:
        """
        Compute the L2 norm of the combined (q, p) state vector.

        Returns
        -------
        float
            ||[q, p]||_2
        """
        return float(torch.norm(self.to_tensor()).item())

    @staticmethod
    def symplectic_area(trajectory: List["PhaseSpaceState"]) -> float:
        """
        Compute the symplectic area ∫ p · dq along a trajectory using
        trapezoidal integration.

        The symplectic 2-form ω = dq ∧ dp is preserved by Hamiltonian flow.
        The area ∫ p dq is a related invariant for 1-D systems.

        Parameters
        ----------
        trajectory : list of PhaseSpaceState
            Ordered sequence of phase-space states.

        Returns
        -------
        float
            Approximate ∫ p · dq.
        """
        if len(trajectory) < 2:
            return 0.0

        total = 0.0
        for i in range(len(trajectory) - 1):
            q_i = trajectory[i].q.numpy()
            q_j = trajectory[i + 1].q.numpy()
            p_i = trajectory[i].p.numpy()
            p_j = trajectory[i + 1].p.numpy()
            dq = q_j - q_i
            # Trapezoidal: (p_i + p_j) / 2 · dq
            total += float(np.dot((p_i + p_j) / 2.0, dq))

        return total

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def clone(self) -> "PhaseSpaceState":
        """Return a deep copy."""
        return PhaseSpaceState(
            q=self.q.clone(),
            p=self.p.clone(),
            timestamp=self.timestamp,
            agent_id=self.agent_id,
        )

    def __repr__(self) -> str:
        return (
            f"PhaseSpaceState(agent={self.agent_id}, "
            f"n_dims={self.q.shape[0]}, "
            f"||q||={float(self.q.norm()):.4f}, "
            f"||p||={float(self.p.norm()):.4f})"
        )
