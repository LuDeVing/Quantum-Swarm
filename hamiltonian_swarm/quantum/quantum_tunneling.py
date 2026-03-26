"""
Quantum tunneling probability computation.

Uses the WKB (Wentzel–Kramers–Brillouin) approximation for a rectangular barrier:

    T_tunnel = exp(-2γ)
    γ = L * sqrt(2m(V₀ - E)) / ℏ

For E < V₀ (classically forbidden region).
"""

from __future__ import annotations
import logging
import math

import torch

logger = logging.getLogger(__name__)


class QuantumTunneling:
    """
    WKB tunneling probability calculator.

    Parameters
    ----------
    hbar : float
        Reduced Planck constant (natural units = 1.0).
    mass : float
        Particle mass (natural units = 1.0).
    """

    def __init__(self, hbar: float = 1.0, mass: float = 1.0) -> None:
        self.hbar = hbar
        self.mass = mass

    def tunneling_probability(
        self,
        barrier_height: float,
        barrier_width: float,
        particle_energy: float,
    ) -> float:
        """
        Compute WKB tunneling probability through a rectangular barrier.

        Formula:
            γ = L * sqrt(2m(V₀ - E)) / ℏ
            T = exp(-2γ)

        If E >= V₀, classical transmission occurs → return 1.0.

        Parameters
        ----------
        barrier_height : float
            Potential barrier height V₀.
        barrier_width : float
            Barrier width L.
        particle_energy : float
            Particle energy E.

        Returns
        -------
        float
            Tunneling probability in [0, 1].
        """
        if particle_energy >= barrier_height:
            return 1.0  # classically allowed

        delta_V = barrier_height - particle_energy
        gamma = barrier_width * math.sqrt(2.0 * self.mass * delta_V) / self.hbar
        T = math.exp(-2.0 * gamma)
        logger.debug(
            "Tunneling: V₀=%.4f, E=%.4f, L=%.4f → γ=%.4f, T=%.6f",
            barrier_height,
            particle_energy,
            barrier_width,
            gamma,
            T,
        )
        return T

    def should_tunnel(
        self,
        current_value: float,
        local_min_value: float,
        barrier_estimate: float,
        barrier_width: float = 1.0,
        rng: float | None = None,
    ) -> bool:
        """
        Decide stochastically whether a particle should tunnel through a local trap.

        Tunneling occurs if U ~ Uniform(0,1) < T_tunnel.

        Parameters
        ----------
        current_value : float
            Current objective function value (treated as particle energy E).
        local_min_value : float
            Value at the local minimum (barrier floor).
        barrier_estimate : float
            Estimated barrier height above the local minimum.
        barrier_width : float, optional
            Spatial width of the barrier in problem-space units. Defaults to 1.0
            (normalized). Pass the actual search-space extent for more accurate
            WKB tunneling probabilities.
        rng : float, optional
            Pre-supplied random number in [0,1] (for testing). Otherwise drawn uniformly.

        Returns
        -------
        bool
            True if the particle should tunnel.
        """
        V0 = local_min_value + barrier_estimate
        T = self.tunneling_probability(
            barrier_height=V0,
            barrier_width=barrier_width,
            particle_energy=current_value,
        )
        u = rng if rng is not None else float(torch.rand(1).item())
        should = u < T
        if should:
            logger.info(
                "Quantum tunneling triggered! T=%.6f > u=%.6f", T, u
            )
        return should
