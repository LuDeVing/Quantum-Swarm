"""
Quantum Annealing for combinatorial portfolio optimization.

Annealing schedule:
    H(s) = (1 - s) * H_transverse + s * H_problem
    s: 0 → 1  (quantum regime → classical regime)

H_transverse = -Σ σ_x_i  (quantum tunneling, allows barrier crossing)
H_problem    = QUBO matrix (classical objective)

Advantage over classical simulated annealing:
    quantum tunneling allows crossing energy barriers that
    thermal fluctuations cannot overcome.
"""

from __future__ import annotations
import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)


class QuantumAnnealingOptimizer:
    """
    Simulated quantum annealing for QUBO problems.

    Parameters
    ----------
    n_steps : int
        Number of annealing steps.
    T_start : float
        Initial temperature.
    T_end : float
        Final temperature.
    tunneling_scale : float
        Controls quantum tunneling strength.
    """

    def __init__(
        self,
        n_steps: int = 1000,
        T_start: float = 1.0,
        T_end: float = 0.001,
        tunneling_scale: float = 1.0,
    ) -> None:
        self.n_steps = n_steps
        self.T_start = T_start
        self.T_end = T_end
        self.tunneling_scale = tunneling_scale
        self._energy_history: List[float] = []

    # ------------------------------------------------------------------
    # QUBO construction
    # ------------------------------------------------------------------

    def build_qubo_matrix(
        self,
        returns: np.ndarray,
        costs: np.ndarray,
        budget: float,
        penalty_lambda: float = 10.0,
    ) -> torch.Tensor:
        """
        Build QUBO matrix for binary portfolio selection.

        Objective: minimize -Σ rᵢ xᵢ + λ(Σ cᵢ xᵢ - B)²

        Parameters
        ----------
        returns : np.ndarray
            Expected returns for each asset, shape [n].
        costs : np.ndarray
            Cost per asset, shape [n].
        budget : float
            Total budget B.
        penalty_lambda : float
            Budget constraint penalty weight.

        Returns
        -------
        torch.Tensor
            QUBO matrix Q shape [n, n].
        """
        n = len(returns)
        Q = torch.zeros(n, n)

        # Linear terms (diagonal): -return + penalty * (cost²  - 2*cost*budget)
        for i in range(n):
            Q[i, i] = -returns[i] + penalty_lambda * (costs[i]**2 - 2 * costs[i] * budget)

        # Quadratic terms (off-diagonal): penalty * 2 * cost_i * cost_j
        for i in range(n):
            for j in range(i + 1, n):
                Q[i, j] = penalty_lambda * 2 * costs[i] * costs[j]
                Q[j, i] = Q[i, j]

        return Q

    # ------------------------------------------------------------------
    # Hamiltonians
    # ------------------------------------------------------------------

    def transverse_field_hamiltonian(self, n_variables: int) -> torch.Tensor:
        """
        H_T = -Σ σ_x_i as a 2^n × 2^n matrix.

        For large n, approximated as -n * I (mean-field).
        Full construction only for n ≤ 10.

        Parameters
        ----------
        n_variables : int

        Returns
        -------
        torch.Tensor
            Approximate transverse field [n, n] (mean-field diagonal form).
        """
        # Mean-field approximation: H_T ≈ -n_variables * I
        return -n_variables * torch.eye(n_variables)

    def qubo_energy(self, x: np.ndarray, Q: torch.Tensor) -> float:
        """
        Compute QUBO energy x^T Q x.

        Parameters
        ----------
        x : np.ndarray
            Binary vector {0,1}^n.
        Q : torch.Tensor

        Returns
        -------
        float
        """
        x_t = torch.tensor(x, dtype=torch.float32)
        return float((x_t @ Q @ x_t).item())

    # ------------------------------------------------------------------
    # Tunneling rate
    # ------------------------------------------------------------------

    def tunneling_rate(self, s: float, barrier_height: float) -> float:
        """
        Γ_tunnel = exp(-barrier_height / ((1 - s) * tunneling_scale + 1e-8))

        High at s≈0 (quantum regime), low at s≈1 (classical regime).

        Parameters
        ----------
        s : float
            Annealing progress ∈ [0, 1].
        barrier_height : float

        Returns
        -------
        float
        """
        quantum_strength = (1.0 - s) * self.tunneling_scale
        return math.exp(-barrier_height / (quantum_strength + 1e-8))

    # ------------------------------------------------------------------
    # Main annealing loop
    # ------------------------------------------------------------------

    def anneal(
        self,
        qubo_matrix: torch.Tensor,
        x_init: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, float]:
        """
        Run quantum annealing schedule.

        For each step:
            1. Compute current temperature T(s)
            2. Propose a flip (Metropolis-Hastings)
            3. Accept with probability that includes quantum tunneling:
               P_accept = exp(-ΔE / T) + Γ_tunnel

        Parameters
        ----------
        qubo_matrix : torch.Tensor
            Shape [n, n].
        x_init : np.ndarray, optional
            Initial binary vector. Random if None.

        Returns
        -------
        best_x : np.ndarray
            Best binary vector found.
        best_energy : float
        """
        n = qubo_matrix.shape[0]
        x = x_init if x_init is not None else np.random.randint(0, 2, n)
        x = x.copy().astype(float)

        current_energy = self.qubo_energy(x, qubo_matrix)
        best_x = x.copy()
        best_energy = current_energy
        self._energy_history = [current_energy]

        schedule = np.linspace(0.0, 1.0, self.n_steps)
        T_schedule = np.exp(
            np.linspace(math.log(self.T_start), math.log(self.T_end), self.n_steps)
        )

        for step, (s, T) in enumerate(zip(schedule, T_schedule)):
            # Propose random bit flip
            flip_idx = np.random.randint(n)
            x_new = x.copy()
            x_new[flip_idx] = 1.0 - x_new[flip_idx]

            new_energy = self.qubo_energy(x_new, qubo_matrix)
            delta_E = new_energy - current_energy

            # Metropolis acceptance + quantum tunneling boost
            if delta_E < 0:
                accept = True
            else:
                thermal_prob = math.exp(-delta_E / (T + 1e-8))
                tunnel_prob = self.tunneling_rate(s, abs(delta_E))
                accept = np.random.rand() < min(thermal_prob + tunnel_prob, 1.0)

            if accept:
                x = x_new
                current_energy = new_energy
                if current_energy < best_energy:
                    best_energy = current_energy
                    best_x = x.copy()

            self._energy_history.append(current_energy)

            if step % 100 == 0:
                logger.debug(
                    "Annealing step %d/%d: s=%.3f, T=%.4f, E=%.4f, best=%.4f",
                    step, self.n_steps, s, T, current_energy, best_energy,
                )

        logger.info(
            "Annealing complete: best_energy=%.4f, selected=%d assets.",
            best_energy, int(best_x.sum()),
        )
        return best_x.astype(int), best_energy

    # ------------------------------------------------------------------
    # Portfolio optimization
    # ------------------------------------------------------------------

    def optimize_portfolio(
        self,
        market_positions: List[Dict],
        budget: float = 1000.0,
        penalty_lambda: float = 10.0,
    ) -> Dict:
        """
        Full portfolio optimization pipeline.

        Parameters
        ----------
        market_positions : list of dict
            Each dict: {'name': str, 'expected_return': float, 'cost': float}.
        budget : float
        penalty_lambda : float

        Returns
        -------
        dict
            {'selected': list of dicts, 'total_cost': float, 'expected_return': float}
        """
        if not market_positions:
            return {"selected": [], "total_cost": 0.0, "expected_return": 0.0}

        returns = np.array([p["expected_return"] for p in market_positions])
        costs = np.array([p["cost"] for p in market_positions])

        Q = self.build_qubo_matrix(returns, costs, budget, penalty_lambda)
        best_x, best_energy = self.anneal(Q)

        selected = [market_positions[i] for i in range(len(market_positions)) if best_x[i] == 1]
        total_cost = sum(p["cost"] for p in selected)
        total_return = sum(p["expected_return"] for p in selected)

        logger.info(
            "Portfolio: %d/%d positions selected, cost=%.2f, return=%.4f",
            len(selected), len(market_positions), total_cost, total_return,
        )
        return {
            "selected": selected,
            "total_cost": total_cost,
            "expected_return": total_return,
            "qubo_energy": best_energy,
            "binary_vector": best_x.tolist(),
        }
