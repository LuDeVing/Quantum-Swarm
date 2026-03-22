"""
Multi-particle quantum state registry.

Tracks N quantum particles with position, momentum, personal best, and
entanglement state. Provides quantum information metrics such as
Von Neumann entropy and coherence.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)


@dataclass
class QuantumParticle:
    """Single quantum particle record."""
    particle_id: int
    position: np.ndarray
    momentum: np.ndarray
    personal_best: np.ndarray
    personal_best_value: float = float("inf")
    entangled_with: Set[int] = field(default_factory=set)
    measurement_count: int = 0
    collapsed_position: Optional[np.ndarray] = None


class QuantumStateRegistry:
    """
    Registry for a swarm of quantum particles.

    Parameters
    ----------
    n_particles : int
        Number of particles.
    n_dims : int
        Phase-space dimensionality per particle.
    """

    def __init__(self, n_particles: int, n_dims: int) -> None:
        self.n_particles = n_particles
        self.n_dims = n_dims
        self.particles: Dict[int, QuantumParticle] = {}
        self._init_particles()
        logger.info(
            "QuantumStateRegistry initialized: n_particles=%d, n_dims=%d",
            n_particles,
            n_dims,
        )

    def _init_particles(self) -> None:
        for i in range(self.n_particles):
            pos = np.random.randn(self.n_dims)
            mom = np.random.randn(self.n_dims)
            self.particles[i] = QuantumParticle(
                particle_id=i,
                position=pos,
                momentum=mom,
                personal_best=pos.copy(),
            )

    # ------------------------------------------------------------------
    # Entanglement
    # ------------------------------------------------------------------

    def entangle(self, particle_i: int, particle_j: int) -> None:
        """
        Mark particles i and j as entangled.

        When entangled, their local attractors are averaged during updates,
        correlating their quantum evolution.

        Parameters
        ----------
        particle_i, particle_j : int
            Particle indices to entangle.
        """
        self.particles[particle_i].entangled_with.add(particle_j)
        self.particles[particle_j].entangled_with.add(particle_i)
        logger.info("Particles %d and %d are now entangled.", particle_i, particle_j)

    def get_entangled_attractor(self, particle_id: int) -> np.ndarray:
        """
        Return averaged personal_best among particle and its entangled partners.

        Parameters
        ----------
        particle_id : int

        Returns
        -------
        np.ndarray
            Averaged attractor position.
        """
        p = self.particles[particle_id]
        positions = [p.personal_best]
        for j in p.entangled_with:
            positions.append(self.particles[j].personal_best)
        return np.mean(positions, axis=0)

    # ------------------------------------------------------------------
    # Measurement
    # ------------------------------------------------------------------

    def measure_particle(self, particle_id: int) -> np.ndarray:
        """
        Collapse particle to a definite position (measurement).

        The collapsed position is drawn from a Gaussian centered on
        the current position with spread proportional to |momentum|.

        Parameters
        ----------
        particle_id : int

        Returns
        -------
        np.ndarray
            Measured (collapsed) position.
        """
        p = self.particles[particle_id]
        spread = np.linalg.norm(p.momentum) + 1e-8
        collapsed = p.position + np.random.randn(self.n_dims) * spread * 0.1
        p.collapsed_position = collapsed
        p.measurement_count += 1
        logger.info(
            "Particle %d measured (count=%d): pos=%s",
            particle_id,
            p.measurement_count,
            np.round(collapsed, 4),
        )
        return collapsed

    # ------------------------------------------------------------------
    # Quantum information metrics
    # ------------------------------------------------------------------

    def build_density_matrix(self) -> np.ndarray:
        """
        Build a simplified density matrix ρ of size [n_particles, n_particles].

        ρ_{ij} = ⟨x_i | x_j⟩ / ||x_i|| ||x_j||  (normalized inner product)

        This approximates the off-diagonal coherence structure.

        Returns
        -------
        np.ndarray
            Shape [n_particles, n_particles], complex.
        """
        positions = np.stack(
            [self.particles[i].position for i in range(self.n_particles)]
        )
        norms = np.linalg.norm(positions, axis=1, keepdims=True) + 1e-12
        normalized = positions / norms

        rho = normalized @ normalized.T  # real inner products
        # Make complex for generality
        return rho.astype(complex)

    def compute_von_neumann_entropy(
        self, density_matrix: Optional[np.ndarray] = None
    ) -> float:
        """
        Compute Von Neumann entropy S = -Tr(ρ log ρ).

        Uses eigenvalue decomposition: S = -Σ λ_i log(λ_i) for λ_i > 0.

        Parameters
        ----------
        density_matrix : np.ndarray, optional
            If None, builds from current particle positions.

        Returns
        -------
        float
            Entropy value ≥ 0.
        """
        if density_matrix is None:
            density_matrix = self.build_density_matrix()

        # Eigenvalues of the density matrix
        eigvals = np.linalg.eigvalsh(density_matrix.real)
        eigvals = np.clip(eigvals, 1e-15, None)
        eigvals /= eigvals.sum()  # normalize to form valid prob. distribution

        entropy = float(-np.sum(eigvals * np.log(eigvals)))
        logger.debug("Von Neumann entropy: S=%.6f", entropy)
        return entropy

    def coherence_metric(self) -> float:
        """
        Measure quantum coherence as the mean magnitude of off-diagonal elements
        of the density matrix.

        Returns
        -------
        float
            Coherence value. 0 = fully decoherent (diagonal ρ), >0 = coherent.
        """
        rho = self.build_density_matrix()
        n = rho.shape[0]
        off_diag = rho - np.diag(np.diag(rho))
        coherence = float(np.abs(off_diag).mean())
        logger.debug("Coherence metric: %.6f", coherence)
        return coherence

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def update_particle(
        self,
        particle_id: int,
        new_position: np.ndarray,
        new_value: float,
    ) -> None:
        """Update particle position and personal best."""
        p = self.particles[particle_id]
        p.position = new_position.copy()
        p.momentum = new_position - p.personal_best  # Δ as pseudo-momentum
        if new_value < p.personal_best_value:
            p.personal_best = new_position.copy()
            p.personal_best_value = new_value
