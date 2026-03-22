"""
Discrete quantum wave function ψ(x).

The wave function is represented as a complex-valued array over a 1D grid.
Physical constraint: ∫|ψ|² dx = 1  (Born normalization).
"""

from __future__ import annotations
import logging
from typing import List, Optional

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class WaveFunction:
    """
    Discrete quantum wave function ψ over a uniform grid.

    Parameters
    ----------
    n_points : int
        Number of grid points.
    dx : float
        Grid spacing (in position units).
    """

    def __init__(self, n_points: int, dx: float = 0.1) -> None:
        self.n_points = n_points
        self.dx = dx
        # Initialize as Gaussian wave packet (real-valued, unnormalized)
        x = torch.linspace(-n_points * dx / 2, n_points * dx / 2, n_points)
        psi_real = torch.exp(-x ** 2 / 2.0)
        self.psi: torch.Tensor = psi_real.to(torch.complex64)
        self.normalize()
        logger.debug("WaveFunction initialized: n_points=%d, dx=%.4f", n_points, dx)

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    def normalize(self) -> None:
        """
        Enforce ∫|ψ|² dx = 1 via numerical integration (trapezoidal).

        Modifies self.psi in-place.
        """
        prob = self.probability_density()
        norm = float((prob * self.dx).sum().item())
        if norm < 1e-30:
            logger.warning("Wave function has near-zero norm; skipping normalization.")
            return
        self.psi = self.psi / (norm ** 0.5)
        # Verification
        prob_after = self.probability_density()
        norm_check = float((prob_after * self.dx).sum().item())
        assert abs(norm_check - 1.0) < 1e-5, f"Normalization failed: integral={norm_check}"

    # ------------------------------------------------------------------
    # Observables
    # ------------------------------------------------------------------

    def probability_density(self) -> torch.Tensor:
        """
        Compute |ψ(x)|².

        Returns
        -------
        torch.Tensor
            Real-valued tensor, shape [n_points].
        """
        return (self.psi.abs() ** 2).real

    def expectation_value(self, observable_matrix: torch.Tensor) -> torch.Tensor:
        """
        Compute ⟨ψ|O|ψ⟩ = ψ† O ψ.

        Parameters
        ----------
        observable_matrix : torch.Tensor
            Hermitian matrix, shape [n_points, n_points], dtype complex.

        Returns
        -------
        torch.Tensor
            Complex scalar expectation value.
        """
        if observable_matrix.dtype != torch.complex64:
            observable_matrix = observable_matrix.to(torch.complex64)
        psi_col = self.psi.unsqueeze(-1)          # [n, 1]
        O_psi = observable_matrix @ psi_col        # [n, 1]
        return (self.psi.conj() @ O_psi.squeeze(-1)) * self.dx

    # ------------------------------------------------------------------
    # State manipulation
    # ------------------------------------------------------------------

    def collapse(self, measurement_outcome: int) -> None:
        """
        Project ψ onto the position eigenstate at index `measurement_outcome`.

        After collapse the wave function is a delta-function at that point.

        Parameters
        ----------
        measurement_outcome : int
            Grid index of the measurement result.
        """
        if not (0 <= measurement_outcome < self.n_points):
            raise ValueError(f"measurement_outcome {measurement_outcome} out of range.")
        new_psi = torch.zeros(self.n_points, dtype=torch.complex64)
        new_psi[measurement_outcome] = 1.0 / (self.dx ** 0.5)
        self.psi = new_psi
        logger.info("Wave function collapsed to position index %d.", measurement_outcome)

    @staticmethod
    def superpose(
        psi_list: List["WaveFunction"],
        coefficients: List[complex],
    ) -> "WaveFunction":
        """
        Create a superposition Σ cᵢ ψᵢ.

        Parameters
        ----------
        psi_list : list of WaveFunction
            Component wave functions (must all have same n_points, dx).
        coefficients : list of complex
            Expansion coefficients cᵢ. Need not be normalized.

        Returns
        -------
        WaveFunction
            New normalized superposition state.
        """
        if len(psi_list) != len(coefficients):
            raise ValueError("psi_list and coefficients must have the same length.")
        n_points = psi_list[0].n_points
        dx = psi_list[0].dx
        result_psi = torch.zeros(n_points, dtype=torch.complex64)
        for psi_i, c_i in zip(psi_list, coefficients):
            result_psi = result_psi + complex(c_i) * psi_i.psi
        new_wf = WaveFunction.__new__(WaveFunction)
        new_wf.n_points = n_points
        new_wf.dx = dx
        new_wf.psi = result_psi
        new_wf.normalize()
        logger.debug("Superposition created from %d states.", len(psi_list))
        return new_wf
