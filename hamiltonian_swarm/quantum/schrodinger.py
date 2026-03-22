"""
Schrödinger equation solvers.

Time-Independent:
    H_op ψ = E ψ,   H_op = -(ℏ²/2m) d²/dx² + V(x)
    Solved via finite-difference eigenvalue decomposition.

Time-Dependent (Crank–Nicolson):
    iℏ ∂ψ/∂t = H_op ψ
    (I + iH dt/2ℏ) ψ(t+dt) = (I - iH dt/2ℏ) ψ(t)
"""

from __future__ import annotations
import logging
from typing import Callable, Tuple

import torch

from .wave_function import WaveFunction

logger = logging.getLogger(__name__)


class SchrodingerSolver:
    """
    Finite-difference Schrödinger equation solver.

    Parameters
    ----------
    n_points : int
        Number of spatial grid points.
    dx : float
        Grid spacing.
    hbar : float
        Reduced Planck constant (default 1.0 = natural units).
    mass : float
        Particle mass (default 1.0 = natural units).
    """

    def __init__(
        self,
        n_points: int = 256,
        dx: float = 0.1,
        hbar: float = 1.0,
        mass: float = 1.0,
    ) -> None:
        self.n_points = n_points
        self.dx = dx
        self.hbar = hbar
        self.mass = mass

        # Pre-compute kinetic matrix (second-derivative finite difference)
        # d²/dx² ≈ (ψ_{i+1} - 2ψ_i + ψ_{i-1}) / dx²
        self._T_matrix = self._build_kinetic_matrix()
        logger.debug(
            "SchrodingerSolver ready: n_points=%d, dx=%.4f, hbar=%.3f, mass=%.3f",
            n_points,
            dx,
            hbar,
            mass,
        )

    # ------------------------------------------------------------------
    # Matrix construction
    # ------------------------------------------------------------------

    def _build_kinetic_matrix(self) -> torch.Tensor:
        """
        Build the kinetic energy operator matrix using finite differences.

        T_{ii} = hbar² / (m dx²)
        T_{i,i±1} = -hbar² / (2m dx²)

        Returns
        -------
        torch.Tensor
            Real symmetric tridiagonal matrix, shape [n, n].
        """
        n = self.n_points
        diag_val = self.hbar ** 2 / (self.mass * self.dx ** 2)
        off_val = -self.hbar ** 2 / (2.0 * self.mass * self.dx ** 2)

        T = torch.zeros(n, n)
        idx = torch.arange(n)
        T[idx, idx] = diag_val
        T[idx[:-1], idx[1:]] = off_val
        T[idx[1:], idx[:-1]] = off_val
        return T

    def build_hamiltonian_matrix(
        self, V_fn: Callable[[torch.Tensor], torch.Tensor]
    ) -> torch.Tensor:
        """
        Build the full Hamiltonian matrix H = T + diag(V(x)).

        Parameters
        ----------
        V_fn : callable
            Potential energy function V(x) for a position tensor x.

        Returns
        -------
        torch.Tensor
            Shape [n, n], real-valued.
        """
        x = torch.linspace(
            -self.n_points * self.dx / 2,
            self.n_points * self.dx / 2,
            self.n_points,
        )
        V = V_fn(x)
        H = self._T_matrix.clone()
        H += torch.diag(V)
        return H

    # ------------------------------------------------------------------
    # Time-independent solver (eigenvalue problem)
    # ------------------------------------------------------------------

    def solve_tise(
        self, V_fn: Callable[[torch.Tensor], torch.Tensor], n_states: int = 5
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Solve the Time-Independent Schrödinger Equation H ψ = E ψ.

        Uses torch.linalg.eigh (exploits Hermitian symmetry).

        Parameters
        ----------
        V_fn : callable
            Potential energy V(x).
        n_states : int
            Number of lowest eigenstates to return.

        Returns
        -------
        energies : torch.Tensor
            Shape [n_states], eigenvalues (energy levels).
        eigenstates : torch.Tensor
            Shape [n_states, n_points], normalized eigenvectors.
        """
        H_matrix = self.build_hamiltonian_matrix(V_fn)
        eigvals, eigvecs = torch.linalg.eigh(H_matrix)

        # eigvecs columns are eigenstates; take lowest n_states
        energies = eigvals[:n_states]
        eigenstates = eigvecs[:, :n_states].T  # [n_states, n_points]

        logger.info(
            "TISE solved: ground state E0=%.6f, first excited E1=%.6f",
            float(energies[0].item()),
            float(energies[1].item()) if n_states > 1 else float("nan"),
        )
        return energies, eigenstates

    # ------------------------------------------------------------------
    # Time-dependent solver (Crank–Nicolson)
    # ------------------------------------------------------------------

    def solve_tdse_step(
        self,
        psi: torch.Tensor,
        H_matrix: torch.Tensor,
        dt: float,
    ) -> torch.Tensor:
        """
        Advance the wave function by one time step using Crank–Nicolson.

        Scheme:
            (I + i H dt / 2ℏ) ψ(t+dt) = (I - i H dt / 2ℏ) ψ(t)

        Parameters
        ----------
        psi : torch.Tensor
            Current wave function, shape [n_points], complex.
        H_matrix : torch.Tensor
            Hamiltonian matrix [n, n], real-valued.
        dt : float
            Time step.

        Returns
        -------
        torch.Tensor
            Updated wave function, shape [n_points], complex.
        """
        n = self.n_points
        I = torch.eye(n, dtype=torch.complex64)
        H_c = H_matrix.to(torch.complex64)

        alpha = 1j * dt / (2.0 * self.hbar)
        A = I + alpha * H_c  # left-hand side matrix
        b = (I - alpha * H_c) @ psi.to(torch.complex64)

        psi_new = torch.linalg.solve(A, b)
        return psi_new

    def evolve_tdse(
        self,
        wf: WaveFunction,
        V_fn: Callable[[torch.Tensor], torch.Tensor],
        n_steps: int,
        dt: float,
    ) -> WaveFunction:
        """
        Evolve a WaveFunction for n_steps using TDSE Crank–Nicolson.

        Parameters
        ----------
        wf : WaveFunction
            Initial state.
        V_fn : callable
            Potential energy function.
        n_steps : int
            Number of time steps.
        dt : float
            Time step size.

        Returns
        -------
        WaveFunction
            Final evolved wave function.
        """
        H_matrix = self.build_hamiltonian_matrix(V_fn)
        psi = wf.psi.clone().to(torch.complex64)

        for step in range(n_steps):
            psi = self.solve_tdse_step(psi, H_matrix, dt)
            if step % 100 == 0:
                norm = float((psi.abs() ** 2).sum().item() * wf.dx)
                logger.debug("TDSE step=%d, norm=%.6f", step, norm)

        final_wf = WaveFunction.__new__(WaveFunction)
        final_wf.n_points = wf.n_points
        final_wf.dx = wf.dx
        final_wf.psi = psi
        final_wf.normalize()
        return final_wf
