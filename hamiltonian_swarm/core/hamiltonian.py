"""
Hamiltonian energy functions and Hamilton's equations of motion.

The Hamiltonian H(q, p) = T(p) + V(q) governs the dynamics of a system:

    dq/dt =  ∂H/∂p
    dp/dt = -∂H/∂q

Two symplectic integrators are provided:
  - Symplectic Euler (1st order, volume-preserving)
  - Störmer–Verlet / Leapfrog (2nd order, time-reversible and symplectic)
"""

from __future__ import annotations
import logging
from typing import List, Optional

import torch
import torch.nn as nn

from .phase_space import PhaseSpaceState

logger = logging.getLogger(__name__)


class HamiltonianFunction:
    """
    Implements the Hamiltonian H(q, p) = T(p) + V(q).

    Kinetic energy:
        T(p) = (1/2) p^T M^{-1} p

    Potential energy (quadratic / spring):
        V(q) = (1/2) q^T K q

    Parameters
    ----------
    n_dims : int
        Dimensionality of the phase space (each of q and p).
    mass_scale : float
        Scalar multiplier for the identity mass matrix M = mass_scale * I.
    stiffness_scale : float
        Scalar multiplier for the identity stiffness matrix K = stiffness_scale * I.
    """

    def __init__(
        self,
        n_dims: int,
        mass_scale: float = 1.0,
        stiffness_scale: float = 1.0,
    ) -> None:
        self.n_dims = n_dims
        # Mass matrix M and its inverse (diagonal → simple reciprocal)
        self.M_inv = torch.eye(n_dims) / mass_scale
        # Stiffness matrix K
        self.K = torch.eye(n_dims) * stiffness_scale
        logger.debug(
            "HamiltonianFunction created: n_dims=%d, mass_scale=%.3f, stiffness_scale=%.3f",
            n_dims,
            mass_scale,
            stiffness_scale,
        )

    # ------------------------------------------------------------------
    # Energy components
    # ------------------------------------------------------------------

    def kinetic_energy(
        self, p: torch.Tensor, M: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Compute kinetic energy T(p) = (1/2) p^T M^{-1} p.

        Parameters
        ----------
        p : torch.Tensor
            Momentum vector, shape [n_dims].
        M : torch.Tensor, optional
            Mass matrix [n_dims, n_dims]. Defaults to self.M_inv^{-1}.

        Returns
        -------
        torch.Tensor
            Scalar kinetic energy.
        """
        M_inv = self.M_inv if M is None else torch.linalg.inv(M)
        return 0.5 * p @ M_inv @ p

    def potential_energy(
        self, q: torch.Tensor, K: Optional[torch.Tensor] = None
    ) -> torch.Tensor:
        """
        Compute potential energy V(q) = (1/2) q^T K q.

        Parameters
        ----------
        q : torch.Tensor
            Position vector, shape [n_dims].
        K : torch.Tensor, optional
            Stiffness matrix [n_dims, n_dims]. Defaults to self.K.

        Returns
        -------
        torch.Tensor
            Scalar potential energy.
        """
        K_mat = self.K if K is None else K
        return 0.5 * q @ K_mat @ q

    def total_energy(self, q: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """
        Compute total Hamiltonian H(q, p) = T(p) + V(q).

        Parameters
        ----------
        q, p : torch.Tensor
            Phase-space coordinates, shape [n_dims].

        Returns
        -------
        torch.Tensor
            Scalar total energy.
        """
        return self.kinetic_energy(p) + self.potential_energy(q)

    # ------------------------------------------------------------------
    # Gradients via autograd
    # ------------------------------------------------------------------

    def dH_dq(self, q: torch.Tensor) -> torch.Tensor:
        """
        Compute ∂H/∂q = K q  (gradient of potential w.r.t. q).

        Uses torch.autograd.grad for generality, allowing subclasses to
        override potential_energy with non-quadratic forms.

        Parameters
        ----------
        q : torch.Tensor
            Position vector, shape [n_dims]. Must have requires_grad=True.

        Returns
        -------
        torch.Tensor
            Gradient ∂H/∂q, shape [n_dims].
        """
        q_ = q.detach().requires_grad_(True)
        V = self.potential_energy(q_)
        (grad,) = torch.autograd.grad(V, q_, create_graph=False)
        return grad

    def dH_dp(self, p: torch.Tensor) -> torch.Tensor:
        """
        Compute ∂H/∂p = M^{-1} p  (gradient of kinetic energy w.r.t. p).

        Parameters
        ----------
        p : torch.Tensor
            Momentum vector, shape [n_dims]. Must have requires_grad=True.

        Returns
        -------
        torch.Tensor
            Gradient ∂H/∂p, shape [n_dims].
        """
        p_ = p.detach().requires_grad_(True)
        T = self.kinetic_energy(p_)
        (grad,) = torch.autograd.grad(T, p_, create_graph=False)
        return grad

    # ------------------------------------------------------------------
    # Symplectic integrators
    # ------------------------------------------------------------------

    def integrate_symplectic_euler(
        self,
        state: PhaseSpaceState,
        dt: float,
        n_steps: int,
    ) -> List[PhaseSpaceState]:
        """
        Integrate Hamilton's equations using the Symplectic Euler method.

        Scheme (1st order, volume-preserving):
            q_{n+1} = q_n + dt * (∂H/∂p)|_{p_n}
            p_{n+1} = p_n - dt * (∂H/∂q)|_{q_{n+1}}

        Parameters
        ----------
        state : PhaseSpaceState
            Initial condition.
        dt : float
            Time step.
        n_steps : int
            Number of integration steps.

        Returns
        -------
        list of PhaseSpaceState
            Trajectory including initial state.
        """
        trajectory: List[PhaseSpaceState] = [state.clone()]
        q = state.q.clone().float()
        p = state.p.clone().float()

        for step in range(n_steps):
            dq_dt = self.dH_dp(p)
            q_new = q + dt * dq_dt
            dp_dt = self.dH_dq(q_new)
            p_new = p - dt * dp_dt

            q, p = q_new, p_new
            new_state = PhaseSpaceState(
                q=q.clone(), p=p.clone(), agent_id=state.agent_id
            )
            trajectory.append(new_state)

            if step % 100 == 0:
                H = float(self.total_energy(q, p).item())
                logger.debug("SymplecticEuler step=%d, H=%.6f", step, H)

        return trajectory

    def integrate_leapfrog(
        self,
        state: PhaseSpaceState,
        dt: float,
        n_steps: int,
    ) -> List[PhaseSpaceState]:
        """
        Integrate Hamilton's equations using the Störmer–Verlet (Leapfrog) method.

        Scheme (2nd order, time-reversible, symplectic):
            p_{n+1/2} = p_n - (dt/2) * (∂H/∂q)|_{q_n}
            q_{n+1}   = q_n + dt * (∂H/∂p)|_{p_{n+1/2}}
            p_{n+1}   = p_{n+1/2} - (dt/2) * (∂H/∂q)|_{q_{n+1}}

        Parameters
        ----------
        state : PhaseSpaceState
            Initial condition.
        dt : float
            Time step.
        n_steps : int
            Number of integration steps.

        Returns
        -------
        list of PhaseSpaceState
            Trajectory including initial state.
        """
        trajectory: List[PhaseSpaceState] = [state.clone()]
        q = state.q.clone().float()
        p = state.p.clone().float()

        for step in range(n_steps):
            # Half-step momentum
            p_half = p - (dt / 2.0) * self.dH_dq(q)
            # Full-step position
            q_new = q + dt * self.dH_dp(p_half)
            # Half-step momentum update
            p_new = p_half - (dt / 2.0) * self.dH_dq(q_new)

            q, p = q_new, p_new
            new_state = PhaseSpaceState(
                q=q.clone(), p=p.clone(), agent_id=state.agent_id
            )
            trajectory.append(new_state)

            if step % 100 == 0:
                H = float(self.total_energy(q, p).item())
                logger.debug("Leapfrog step=%d, H=%.6f", step, H)

        return trajectory
