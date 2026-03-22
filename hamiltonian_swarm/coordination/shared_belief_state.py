"""
Shared quantum belief state across entangled agents.
"""

from __future__ import annotations
import logging
import math
from typing import Dict, List

import torch

logger = logging.getLogger(__name__)


class SharedBeliefState:
    """
    Maintains a shared quantum belief state for a group of entangled agents.

    All agents in the group see the same belief state after synchronization.
    Individual observations update the shared state for all members.

    Parameters
    ----------
    hypotheses : list of str
    agent_ids : list of str
    """

    def __init__(
        self, hypotheses: List[str], agent_ids: List[str]
    ) -> None:
        self.hypotheses = hypotheses
        self.agent_ids = set(agent_ids)
        n = len(hypotheses)
        # Uniform shared superposition
        self._shared_amplitudes = torch.full(
            (n,), 1.0 / math.sqrt(n), dtype=torch.complex64
        )
        logger.info(
            "SharedBeliefState: %d hypotheses, %d agents.",
            n, len(agent_ids),
        )

    def update(self, evidence_idx: int, strength: float) -> None:
        """
        Any agent in the group can update the shared belief.

        Parameters
        ----------
        evidence_idx : int
        strength : float
            Positive = amplify, negative = suppress.
        """
        scale = math.exp(strength)
        new_amps = self._shared_amplitudes.clone()
        new_amps[evidence_idx] = new_amps[evidence_idx] * scale
        norm = float(new_amps.abs().pow(2).sum().sqrt().item())
        if norm > 1e-8:
            new_amps = new_amps / norm
        self._shared_amplitudes = new_amps

    def probabilities(self) -> torch.Tensor:
        """Return |cᵢ|² for all hypotheses."""
        return self._shared_amplitudes.abs().pow(2).real

    def collapse(self) -> str:
        """Sample and collapse to one hypothesis."""
        import numpy as np
        probs = self.probabilities().numpy().astype(float)
        probs = probs / probs.sum()
        idx = int(np.random.choice(len(self.hypotheses), p=probs))
        new_amps = torch.zeros_like(self._shared_amplitudes)
        new_amps[idx] = 1.0 + 0j
        self._shared_amplitudes = new_amps
        return self.hypotheses[idx]

    def entropy(self) -> float:
        """Shared belief uncertainty S = -Σ|cᵢ|² log|cᵢ|²."""
        p = self.probabilities().clamp(min=1e-12)
        return float(-torch.sum(p * torch.log(p)).item())

    def add_agent(self, agent_id: str) -> None:
        """Add a new agent to the shared belief group."""
        self.agent_ids.add(agent_id)

    def remove_agent(self, agent_id: str) -> None:
        """Remove an agent from the group."""
        self.agent_ids.discard(agent_id)
