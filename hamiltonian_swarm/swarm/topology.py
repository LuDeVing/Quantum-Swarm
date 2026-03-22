"""
Swarm topology definitions.

Topologies control how gbest is determined in QPSO:
  - FULLY_CONNECTED : global gbest (all see all)
  - RING            : each particle sees left + right neighbours
  - STAR            : hub-and-spoke (particle 0 is hub)
  - VON_NEUMANN     : 2D grid, each particle sees 4 neighbours

topology_energy() computes the graph Laplacian eigenvalue sum (algebraic
connectivity = Fiedler value), which measures how well-connected the swarm is.
"""

from __future__ import annotations
import logging
import math
from enum import Enum, auto
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)


class TopologyType(Enum):
    FULLY_CONNECTED = auto()
    RING = auto()
    STAR = auto()
    VON_NEUMANN = auto()


class SwarmTopology:
    """
    Swarm topology manager.

    Parameters
    ----------
    n_particles : int
        Number of particles in the swarm.
    topology_type : TopologyType
        Which neighbourhood structure to use.
    """

    def __init__(
        self,
        n_particles: int,
        topology_type: TopologyType = TopologyType.FULLY_CONNECTED,
    ) -> None:
        self.n_particles = n_particles
        self.topology_type = topology_type
        self._adjacency = self._build_adjacency()
        logger.info(
            "SwarmTopology: n=%d, type=%s", n_particles, topology_type.name
        )

    # ------------------------------------------------------------------
    # Adjacency construction
    # ------------------------------------------------------------------

    def _build_adjacency(self) -> np.ndarray:
        n = self.n_particles
        A = np.zeros((n, n), dtype=int)

        if self.topology_type == TopologyType.FULLY_CONNECTED:
            A = np.ones((n, n), dtype=int) - np.eye(n, dtype=int)

        elif self.topology_type == TopologyType.RING:
            for i in range(n):
                A[i, (i - 1) % n] = 1
                A[i, (i + 1) % n] = 1

        elif self.topology_type == TopologyType.STAR:
            # Particle 0 is the hub
            for i in range(1, n):
                A[0, i] = 1
                A[i, 0] = 1

        elif self.topology_type == TopologyType.VON_NEUMANN:
            # Map to 2D grid (round up to nearest square)
            side = math.ceil(math.sqrt(n))
            for i in range(n):
                row, col = divmod(i, side)
                for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    r2, c2 = row + dr, col + dc
                    j = r2 * side + c2
                    if 0 <= r2 < side and 0 <= c2 < side and j < n:
                        A[i, j] = 1

        return A

    # ------------------------------------------------------------------
    # Neighbourhood queries
    # ------------------------------------------------------------------

    def get_neighborhood(self, particle_id: int) -> List[int]:
        """
        Return list of neighbour indices for particle_id (excluding itself).

        Parameters
        ----------
        particle_id : int

        Returns
        -------
        list of int
        """
        return [j for j in range(self.n_particles)
                if self._adjacency[particle_id, j] == 1]

    def compute_local_best(
        self,
        particle_id: int,
        all_pbests: np.ndarray,
        all_pbest_values: np.ndarray,
    ) -> np.ndarray:
        """
        Return the best personal_best among the neighbourhood of particle_id.

        Parameters
        ----------
        particle_id : int
        all_pbests : np.ndarray
            Shape [n_particles, n_dims].
        all_pbest_values : np.ndarray
            Shape [n_particles].

        Returns
        -------
        np.ndarray
            Best position in neighbourhood, shape [n_dims].
        """
        neighbours = self.get_neighborhood(particle_id)
        candidates = [particle_id] + neighbours

        best_idx = candidates[
            int(np.argmin([all_pbest_values[c] for c in candidates]))
        ]
        return all_pbests[best_idx].copy()

    # ------------------------------------------------------------------
    # Graph-theoretic energy
    # ------------------------------------------------------------------

    def topology_energy(self) -> float:
        """
        Compute the sum of graph Laplacian eigenvalues.

        L = D - A  (degree matrix minus adjacency matrix)
        Eigenvalue sum = Tr(L) = sum of degrees.

        The Fiedler value (second-smallest eigenvalue) measures algebraic
        connectivity — larger Fiedler value = better-connected swarm.

        Returns
        -------
        float
            Sum of all Laplacian eigenvalues (= 2 * number of edges for undirected graph).
        """
        A = self._adjacency.astype(float)
        D = np.diag(A.sum(axis=1))
        L = D - A
        eigvals = np.linalg.eigvalsh(L)
        total = float(eigvals.sum())
        fiedler = float(eigvals[1]) if len(eigvals) > 1 else 0.0
        logger.debug(
            "Topology energy: eigenvalue_sum=%.4f, Fiedler=%.4f", total, fiedler
        )
        return total

    def adjacency_matrix(self) -> np.ndarray:
        """Return the adjacency matrix."""
        return self._adjacency.copy()
