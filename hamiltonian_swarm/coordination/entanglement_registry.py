"""
Entanglement registry for correlated quantum agent pairs.

When two agents are "entangled" on a shared variable:
  - Their belief states are averaged each sync cycle
  - A measurement (decision) by one propagates to the other
  - They cannot hold contradictory beliefs simultaneously

No quantum hardware required:
  "Entanglement" = shared memory pointer + sync protocol.
  The quantum formalism ensures belief consistency automatically.
"""

from __future__ import annotations
import logging
import math
from typing import Any, Dict, Set, Tuple

import torch

logger = logging.getLogger(__name__)


class EntanglementRegistry:
    """
    Registry of entangled agent pairs with quantum belief synchronization.
    """

    def __init__(self) -> None:
        # agent_id → set of (partner_id, shared_variable)
        self._links: Dict[str, Set[Tuple[str, str]]] = {}
        # shared variable → current belief state amplitudes
        self._shared_vars: Dict[str, torch.Tensor] = {}

    # ------------------------------------------------------------------
    # Link management
    # ------------------------------------------------------------------

    def entangle(
        self,
        agent_a_id: str,
        agent_b_id: str,
        shared_variable: str,
    ) -> None:
        """
        Create an entanglement link on a shared variable.

        Parameters
        ----------
        agent_a_id, agent_b_id : str
        shared_variable : str
            Name of the shared decision variable (e.g. 'budget', 'route').
        """
        for aid, bid in [(agent_a_id, agent_b_id), (agent_b_id, agent_a_id)]:
            self._links.setdefault(aid, set()).add((bid, shared_variable))
        logger.info(
            "Entangled agents %s ↔ %s on variable '%s'.",
            agent_a_id, agent_b_id, shared_variable,
        )

    def disentangle(
        self,
        agent_a_id: str,
        agent_b_id: str,
    ) -> None:
        """
        Remove all entanglement links between two agents.

        Parameters
        ----------
        agent_a_id, agent_b_id : str
        """
        for aid, bid in [(agent_a_id, agent_b_id), (agent_b_id, agent_a_id)]:
            if aid in self._links:
                self._links[aid] = {
                    (p, v) for p, v in self._links[aid] if p != bid
                }
        logger.info("Disentangled agents %s and %s.", agent_a_id, agent_b_id)

    def get_partners(self, agent_id: str) -> Set[Tuple[str, str]]:
        """Return set of (partner_id, variable) pairs for agent_id."""
        return self._links.get(agent_id, set())

    # ------------------------------------------------------------------
    # Belief synchronization
    # ------------------------------------------------------------------

    def sync_beliefs(
        self,
        agent_a_id: str,
        agent_b_id: str,
        psi_a: torch.Tensor,
        psi_b: torch.Tensor,
    ) -> torch.Tensor:
        """
        Merge belief states via quantum superposition:

            ψ_shared = (ψ_A + ψ_B) / √(2 + 2·Re(⟨ψ_A|ψ_B⟩))

        Parameters
        ----------
        agent_a_id, agent_b_id : str
        psi_a, psi_b : torch.Tensor
            Complex amplitude vectors.

        Returns
        -------
        torch.Tensor
            Normalized shared belief state.
        """
        psi_a = psi_a.to(torch.complex64)
        psi_b = psi_b.to(torch.complex64)

        inner = float((psi_a.conj() @ psi_b).real.item())
        denom = math.sqrt(max(2.0 + 2.0 * inner, 1e-12))
        psi_shared = (psi_a + psi_b) / denom

        logger.debug(
            "Belief sync %s↔%s: fidelity=%.4f",
            agent_a_id, agent_b_id,
            self.entanglement_fidelity(psi_a, psi_b),
        )
        return psi_shared

    def measure_entangled(
        self,
        agent_id: str,
        variable: str,
        measurement_result: Any,
        all_agent_beliefs: Dict[str, torch.Tensor],
    ) -> Dict[str, torch.Tensor]:
        """
        Agent collapses its belief on variable.
        Propagates update to all entangled partners.

        Parameters
        ----------
        agent_id : str
        variable : str
        measurement_result : Any
            The outcome of the measurement (collapses all partner beliefs accordingly).
        all_agent_beliefs : dict
            {agent_id: amplitude_tensor}

        Returns
        -------
        dict
            Updated beliefs for all affected agents.
        """
        updated = dict(all_agent_beliefs)
        partners = [p for p, v in self.get_partners(agent_id) if v == variable]

        for partner_id in partners:
            if partner_id in updated:
                # Partner collapses to same measurement outcome
                # Represent as a unit vector at the measured index
                psi = updated[partner_id]
                if len(psi) > 0:
                    n = len(psi)
                    idx = hash(str(measurement_result)) % n
                    new_psi = torch.zeros(n, dtype=torch.complex64)
                    new_psi[idx] = 1.0 + 0j
                    updated[partner_id] = new_psi
                    logger.info(
                        "Entanglement propagation: %s → %s collapsed to outcome index %d.",
                        agent_id, partner_id, idx,
                    )

        return updated

    # ------------------------------------------------------------------
    # Fidelity metric
    # ------------------------------------------------------------------

    def entanglement_fidelity(
        self, psi_a: torch.Tensor, psi_b: torch.Tensor
    ) -> float:
        """
        F = |⟨ψ_A|ψ_B⟩|² ∈ [0, 1].

        1.0 = perfectly synchronized, 0.0 = orthogonal (contradictory).

        Parameters
        ----------
        psi_a, psi_b : torch.Tensor
            Complex amplitude vectors (same length).

        Returns
        -------
        float
        """
        a = psi_a.to(torch.complex64)
        b = psi_b.to(torch.complex64)
        norm_a = a.norm()
        norm_b = b.norm()
        if norm_a < 1e-8 or norm_b < 1e-8:
            return 0.0
        a = a / norm_a
        b = b / norm_b
        return float((a.conj() @ b).abs().pow(2).item())
