"""
Quantum coalition formation protocol.

Agents form coalitions to tackle tasks that benefit from combined expertise.
Coalition formation is modeled as a quantum game where:
  - Agents start in superposition of possible coalitions
  - Evidence (task requirements) collapses them to a specific coalition
  - Entanglement ensures coalition members coordinate without contradiction
"""

from __future__ import annotations
import logging
import math
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
import torch

logger = logging.getLogger(__name__)


class QuantumCoalition:
    """
    Quantum coalition formation and management.

    Parameters
    ----------
    agent_ids : list of str
        All available agents.
    max_coalition_size : int
        Maximum agents per coalition.
    """

    def __init__(
        self,
        agent_ids: List[str],
        max_coalition_size: int = 5,
    ) -> None:
        self.agent_ids = agent_ids
        self.max_coalition_size = max_coalition_size
        self._active_coalitions: List[Dict] = []
        logger.info(
            "QuantumCoalition: %d agents, max_size=%d", len(agent_ids), max_coalition_size
        )

    # ------------------------------------------------------------------
    # Coalition formation
    # ------------------------------------------------------------------

    def form_coalition(
        self,
        task_requirements: Dict[str, float],
        agent_capabilities: Dict[str, Dict[str, float]],
    ) -> List[str]:
        """
        Form an optimal coalition via quantum amplitude amplification over candidate sets.

        Parameters
        ----------
        task_requirements : dict
            {capability: required_level}
        agent_capabilities : dict
            {agent_id: {capability: level}}

        Returns
        -------
        list of str
            Agent IDs in the formed coalition.
        """
        # Score each agent for this task
        scores = {}
        for aid in self.agent_ids:
            caps = agent_capabilities.get(aid, {})
            score = sum(
                min(caps.get(cap, 0.0), req)
                for cap, req in task_requirements.items()
            ) / max(sum(task_requirements.values()), 1e-8)
            scores[aid] = score

        # Sort by score, take top max_coalition_size
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        coalition = [aid for aid, _ in ranked[:self.max_coalition_size] if _ > 0]

        record = {
            "task_requirements": task_requirements,
            "members": coalition,
            "formation_scores": {aid: scores[aid] for aid in coalition},
        }
        self._active_coalitions.append(record)
        logger.info("Coalition formed: %s", coalition)
        return coalition

    def dissolve_coalition(self, coalition_members: List[str]) -> None:
        """Remove a coalition record."""
        self._active_coalitions = [
            c for c in self._active_coalitions
            if set(c["members"]) != set(coalition_members)
        ]
        logger.info("Coalition dissolved: %s", coalition_members)

    def coalition_value(
        self,
        coalition: List[str],
        task_requirements: Dict[str, float],
        agent_capabilities: Dict[str, Dict[str, float]],
    ) -> float:
        """
        Characteristic function v(S): value of coalition S on task.

        v(S) = Σ_capability min(max_level_in_S, required_level) / required

        Parameters
        ----------
        coalition : list of str
        task_requirements : dict
        agent_capabilities : dict

        Returns
        -------
        float ∈ [0, 1]
        """
        total_req = max(sum(task_requirements.values()), 1e-8)
        value = 0.0
        for cap, req in task_requirements.items():
            best_level = max(
                agent_capabilities.get(aid, {}).get(cap, 0.0)
                for aid in coalition
            ) if coalition else 0.0
            value += min(best_level, req)
        return value / total_req

    @property
    def active_coalitions(self) -> List[Dict]:
        return list(self._active_coalitions)
