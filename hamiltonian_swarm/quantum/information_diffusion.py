"""
Schrödinger equation on agent communication graph.

Models how information spreads through the swarm:

    iℏ ∂ψ/∂t = L ψ

Where:
    ψ(i, t) = probability amplitude that agent i has received the information
    L = graph Laplacian of the agent communication topology

Solution:
    ψ(t) = exp(-i L t / ℏ) ψ(0)

This is the correct placement because:
- ψ(i,t) is measurable: P(agent i has info) = |ψ(i,t)|²
- L is measurable: it IS the actual communication adjacency
- Predicts when all agents know about a critical event
"""

from __future__ import annotations
import logging
from typing import List, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)

try:
    from ..quantum.qpso import QPSO
    _HAS_QPSO = True
except ImportError:
    _HAS_QPSO = False


class InformationDiffusion:
    """
    Quantum information diffusion on a swarm communication graph.

    Parameters
    ----------
    adjacency_matrix : torch.Tensor
        Shape [n_agents, n_agents], symmetric binary matrix.
    hbar : float
        Reduced Planck constant (default 1.0).
    """

    def __init__(
        self,
        adjacency_matrix: torch.Tensor,
        hbar: float = 1.0,
    ) -> None:
        self.adjacency = adjacency_matrix.float()
        self.n_agents = adjacency_matrix.shape[0]
        self.hbar = hbar
        self.L = self.build_laplacian(adjacency_matrix)
        logger.info(
            "InformationDiffusion: n_agents=%d, hbar=%.2f", self.n_agents, hbar
        )

    # ------------------------------------------------------------------
    # Graph Laplacian
    # ------------------------------------------------------------------

    def build_laplacian(self, adjacency_matrix: torch.Tensor) -> torch.Tensor:
        """
        L = D - A, where D is the degree matrix and A is the adjacency matrix.

        Parameters
        ----------
        adjacency_matrix : torch.Tensor
            Shape [n, n].

        Returns
        -------
        torch.Tensor
            Graph Laplacian [n, n], real-valued.
        """
        A = adjacency_matrix.float()
        degrees = A.sum(dim=1)
        D = torch.diag(degrees)
        L = D - A
        return L

    # ------------------------------------------------------------------
    # Propagation
    # ------------------------------------------------------------------

    def propagate(
        self,
        initial_state: torch.Tensor,
        t: float,
    ) -> torch.Tensor:
        """
        Compute ψ(t) = exp(-i L t / ℏ) ψ(0).

        Uses torch.matrix_exp on the complex Laplacian.

        Parameters
        ----------
        initial_state : torch.Tensor
            Initial amplitude distribution, shape [n_agents]. Complex or real.
        t : float
            Propagation time.

        Returns
        -------
        torch.Tensor
            ψ(t), shape [n_agents], complex64.
        """
        psi0 = initial_state.to(torch.complex64)
        L_c = self.L.to(torch.complex64)
        U = torch.matrix_exp(-1j * L_c * t / self.hbar)
        psi_t = U @ psi0
        return psi_t

    def probability_at_time(
        self, initial_state: torch.Tensor, t: float
    ) -> torch.Tensor:
        """
        Return |ψ(t)|² — probability each agent has the information.

        Parameters
        ----------
        initial_state : torch.Tensor
        t : float

        Returns
        -------
        torch.Tensor
            Real probabilities, shape [n_agents].
        """
        psi_t = self.propagate(initial_state, t)
        return psi_t.abs().pow(2).real

    # ------------------------------------------------------------------
    # Arrival times
    # ------------------------------------------------------------------

    def information_arrival_time(
        self,
        source_agent: int,
        target_agent: int,
        threshold: float = 0.5,
        t_max: float = 20.0,
        dt: float = 0.05,
    ) -> float:
        """
        Time for |ψ(target, t)|² to exceed threshold.

        Parameters
        ----------
        source_agent : int
            Index of the agent that originates the information.
        target_agent : int
        threshold : float
        t_max : float
        dt : float

        Returns
        -------
        float
            Arrival time, or t_max if never reached.
        """
        psi0 = torch.zeros(self.n_agents, dtype=torch.complex64)
        psi0[source_agent] = 1.0 + 0j

        t = 0.0
        while t <= t_max:
            probs = self.probability_at_time(psi0, t)
            if float(probs[target_agent].item()) > threshold:
                return t
            t += dt
        return t_max

    def diffusion_bottlenecks(
        self,
        threshold: float = 0.5,
        t_max: float = 20.0,
        dt: float = 0.1,
    ) -> List[int]:
        """
        Find agents where information arrives slowest (bottlenecks).

        Averages arrival time over all possible source agents.

        Returns
        -------
        list of int
            Agent indices sorted by slowest arrival (worst first).
        """
        mean_arrivals = []
        for target in range(self.n_agents):
            total = 0.0
            for source in range(self.n_agents):
                if source == target:
                    continue
                total += self.information_arrival_time(source, target, threshold, t_max, dt)
            mean_arrivals.append(total / max(self.n_agents - 1, 1))

        sorted_indices = sorted(range(self.n_agents), key=lambda i: mean_arrivals[i], reverse=True)
        logger.info("Diffusion bottlenecks (worst first): %s", sorted_indices[:5])
        return sorted_indices

    # ------------------------------------------------------------------
    # Topology optimization
    # ------------------------------------------------------------------

    def optimize_topology(self, n_edges_to_add: int) -> List[Tuple[int, int]]:
        """
        Use QPSO to find which edges to add to maximize information diffusion speed.

        Fitness = mean information arrival time across all pairs (minimize).

        Parameters
        ----------
        n_edges_to_add : int

        Returns
        -------
        list of (int, int)
            Recommended edges to add.
        """
        if not _HAS_QPSO:
            logger.warning("QPSO not available — returning empty edge list.")
            return []

        n = self.n_agents
        n_possible = n * (n - 1) // 2
        n_add = min(n_edges_to_add, n_possible)

        # Encode edge selection as n_possible binary variables (continuous relaxation)
        def fitness(x: np.ndarray) -> float:
            # Threshold to binary
            selected = x > 0.5
            adj = self.adjacency.clone()
            k = 0
            for i in range(n):
                for j in range(i + 1, n):
                    if selected[k] and adj[i, j] == 0:
                        adj[i, j] = 1.0
                        adj[j, i] = 1.0
                    k += 1
            tmp = InformationDiffusion(adj, self.hbar)
            total = 0.0
            count = 0
            for src in range(n):
                for tgt in range(n):
                    if src != tgt:
                        total += tmp.information_arrival_time(src, tgt, t_max=10.0, dt=0.2)
                        count += 1
            return total / max(count, 1)

        lb = np.zeros(n_possible)
        ub = np.ones(n_possible)
        qpso = QPSO(n_particles=20, n_dims=n_possible, bounds=(lb, ub), n_iterations=50)
        best_x, _, _ = qpso.optimize(fitness)

        # Extract top n_add edges
        selected = best_x > 0.5
        edges = []
        k = 0
        for i in range(n):
            for j in range(i + 1, n):
                if selected[k] and self.adjacency[i, j] == 0:
                    edges.append((i, j))
                k += 1

        logger.info("Topology optimizer recommends adding %d edges: %s", len(edges), edges[:5])
        return edges[:n_add]
