"""
Embedding-space Hamiltonian monitor.

Correct placement of HNN: monitoring semantic drift in embedding space.

q = agent's current output embedding vector (e.g. 1536-dim)
p = velocity of embedding = current_embedding - previous_embedding
H = "semantic energy" — how far the agent has drifted from its goal embedding

Conservation law:
    H should stay near H_0 (initial goal embedding energy).
    H increase → agent drifting away from original goal (semantic drift).
    Sudden H drop → collapsed to degenerate state (looping/repetition).
"""

from __future__ import annotations
import logging
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class EmbeddingHamiltonianNN(nn.Module):
    """
    Hamiltonian Neural Network operating in embedding space.

    Architecture:
        Input : [q_emb, p_emb] — concatenated current + velocity embeddings
        Hidden: MLP with Tanh activations
        Output: scalar semantic energy H_θ(q, p)

    Parameters
    ----------
    emb_dim : int
        Dimensionality of the embedding (e.g. 1536 for OpenAI, 768 for BERT).
    hidden_dim : int
        Width of hidden layers.
    n_layers : int
        Number of hidden layers.
    """

    def __init__(
        self,
        emb_dim: int = 64,
        hidden_dim: int = 128,
        n_layers: int = 2,
    ) -> None:
        super().__init__()
        self.emb_dim = emb_dim
        self._prev_embedding: Optional[torch.Tensor] = None
        self._goal_embedding: Optional[torch.Tensor] = None
        self._H0: Optional[float] = None

        layers: list[nn.Module] = []
        in_features = emb_dim * 2
        for _ in range(n_layers):
            layers.extend([nn.Linear(in_features, hidden_dim), nn.Tanh()])
            in_features = hidden_dim
        layers.append(nn.Linear(hidden_dim, 1))
        self.net = nn.Sequential(*layers)

        logger.info(
            "EmbeddingHamiltonianNN: emb_dim=%d, hidden=%d, layers=%d",
            emb_dim, hidden_dim, n_layers,
        )

    def set_goal(self, goal_embedding: torch.Tensor) -> None:
        """
        Register the goal embedding and compute H_0 (conserved baseline).

        Parameters
        ----------
        goal_embedding : torch.Tensor
            Shape [emb_dim]. Represents the agent's target semantic state.
        """
        self._goal_embedding = goal_embedding.float().detach()
        p_zero = torch.zeros_like(goal_embedding)
        with torch.no_grad():
            self._H0 = float(self.forward(goal_embedding, p_zero).item())
        logger.info("Goal embedding set. H_0 = %.6f", self._H0)

    def forward(self, q: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
        """
        Compute semantic energy H_θ(q, p).

        Parameters
        ----------
        q : torch.Tensor
            Current embedding, shape [emb_dim] or [batch, emb_dim].
        p : torch.Tensor
            Embedding velocity, same shape as q.

        Returns
        -------
        torch.Tensor
            Scalar energy (or batch of scalars).
        """
        x = torch.cat([q, p], dim=-1)
        return self.net(x).squeeze(-1)

    def embedding_velocity(
        self, current_emb: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute p = emb(t) - emb(t-1), the direction of semantic movement.

        On the first call, returns a zero vector.

        Parameters
        ----------
        current_emb : torch.Tensor
            Shape [emb_dim].

        Returns
        -------
        torch.Tensor
            Velocity vector, shape [emb_dim].
        """
        current_emb = current_emb.float()
        if self._prev_embedding is None:
            self._prev_embedding = current_emb.clone()
            return torch.zeros_like(current_emb)
        velocity = current_emb - self._prev_embedding
        self._prev_embedding = current_emb.clone()
        return velocity

    def semantic_drift_score(
        self, current_emb: torch.Tensor, goal_emb: Optional[torch.Tensor] = None
    ) -> float:
        """
        Cosine distance between current embedding and goal embedding.

        Distance ∈ [0, 2]. 0 = identical direction, 2 = opposite.

        Parameters
        ----------
        current_emb : torch.Tensor
            Shape [emb_dim].
        goal_emb : torch.Tensor, optional
            Defaults to self._goal_embedding if set.

        Returns
        -------
        float
        """
        goal = goal_emb if goal_emb is not None else self._goal_embedding
        if goal is None:
            return 0.0
        cos_sim = F.cosine_similarity(
            current_emb.float().unsqueeze(0),
            goal.float().unsqueeze(0),
        )
        return float(1.0 - cos_sim.item())

    def is_drifting(
        self,
        current_emb: torch.Tensor,
        threshold: float = 0.15,
    ) -> bool:
        """
        True if semantic drift score exceeds threshold.

        Parameters
        ----------
        current_emb : torch.Tensor
        threshold : float
            Default 0.15 (cosine distance).

        Returns
        -------
        bool
        """
        score = self.semantic_drift_score(current_emb)
        if score > threshold:
            logger.warning(
                "Semantic drift detected: score=%.4f > threshold=%.4f",
                score, threshold,
            )
        return score > threshold

    def energy_drift(self, current_emb: torch.Tensor) -> float:
        """
        Compute |H(current) - H_0| / |H_0| as a relative drift measure.

        Returns
        -------
        float
            Relative energy drift. 0 = no drift.
        """
        if self._H0 is None:
            return 0.0
        p = self.embedding_velocity(current_emb)
        with torch.no_grad():
            H_current = float(self.forward(current_emb.float(), p).item())
        drift = abs(H_current - self._H0) / (abs(self._H0) + 1e-8)
        logger.debug("Embedding H drift: %.4f", drift)
        return drift
