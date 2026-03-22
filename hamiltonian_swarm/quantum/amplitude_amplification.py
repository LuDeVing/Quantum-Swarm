"""
Grover-inspired Amplitude Amplification for memory retrieval.

Classical retrieval: O(N) — check every memory.
Amplitude amplification: O(√N) — quadratic speedup.

Algorithm:
1. Uniform superposition over all N memory indices
2. Oracle: flip amplitude sign for memories matching query
3. Diffusion: invert amplitudes about mean (Grover diffusion operator)
4. Repeat π/4 * √N times
5. Measure: highest-amplitude index is returned
"""

from __future__ import annotations
import logging
import math
from typing import List, Optional

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class AmplitudeAmplificationSearch:
    """
    Grover amplitude amplification adapted for classical memory retrieval.

    Parameters
    ----------
    similarity_threshold : float
        Cosine similarity above which a memory is considered a match for the oracle.
    """

    def __init__(self, similarity_threshold: float = 0.7) -> None:
        self.similarity_threshold = similarity_threshold
        logger.debug(
            "AmplitudeAmplificationSearch: threshold=%.2f", similarity_threshold
        )

    # ------------------------------------------------------------------
    # State preparation
    # ------------------------------------------------------------------

    def initialize_superposition(self, n_memories: int) -> torch.Tensor:
        """
        ψ = (1/√N) Σ |i⟩ — uniform superposition over all memory indices.

        Parameters
        ----------
        n_memories : int

        Returns
        -------
        torch.Tensor
            Shape [n_memories], dtype complex64, uniform amplitude 1/√N.
        """
        amp = 1.0 / math.sqrt(n_memories)
        return torch.full((n_memories,), amp, dtype=torch.complex64)

    # ------------------------------------------------------------------
    # Oracle
    # ------------------------------------------------------------------

    def oracle(
        self,
        amplitudes: torch.Tensor,
        query_embedding: torch.Tensor,
        memory_embeddings: torch.Tensor,
    ) -> torch.Tensor:
        """
        Flip amplitude sign for memories that match the query.

        Match criterion: cosine_similarity(memory_emb, query_emb) > threshold.

        Parameters
        ----------
        amplitudes : torch.Tensor
            Shape [N], complex.
        query_embedding : torch.Tensor
            Shape [emb_dim].
        memory_embeddings : torch.Tensor
            Shape [N, emb_dim].

        Returns
        -------
        torch.Tensor
            Updated amplitudes with sign flips for matching memories.
        """
        q_norm = F.normalize(query_embedding.float().unsqueeze(0), dim=-1)
        m_norm = F.normalize(memory_embeddings.float(), dim=-1)
        similarities = (m_norm @ q_norm.T).squeeze(-1)  # [N]

        mask = (similarities > self.similarity_threshold).to(torch.complex64)
        # Flip sign: oracle = I - 2|good⟩⟨good|
        flipped = amplitudes * (1.0 - 2.0 * mask)
        n_marked = int(mask.real.sum().item())
        logger.debug("Oracle marked %d / %d memories.", n_marked, len(amplitudes))
        return flipped

    # ------------------------------------------------------------------
    # Diffusion operator
    # ------------------------------------------------------------------

    def diffusion_operator(self, amplitudes: torch.Tensor) -> torch.Tensor:
        """
        Grover diffusion operator: D = 2|ψ⟩⟨ψ| - I.

        In amplitude form:
            amplitudes → 2 * mean(amplitudes) - amplitudes

        This inverts amplitudes about their mean, amplifying marked states.

        Parameters
        ----------
        amplitudes : torch.Tensor
            Shape [N], complex.

        Returns
        -------
        torch.Tensor
            Diffused amplitudes.
        """
        mean_amp = amplitudes.mean()
        return 2.0 * mean_amp - amplitudes

    # ------------------------------------------------------------------
    # Full search
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: torch.Tensor,
        memory_embeddings: torch.Tensor,
        n_iterations: Optional[int] = None,
    ) -> int:
        """
        Run amplitude amplification and return index of best-matching memory.

        Parameters
        ----------
        query_embedding : torch.Tensor
            Shape [emb_dim].
        memory_embeddings : torch.Tensor
            Shape [N, emb_dim].
        n_iterations : int, optional
            Defaults to π/4 * √N (optimal Grover iterations).

        Returns
        -------
        int
            Index of the retrieved memory.
        """
        N = memory_embeddings.shape[0]
        if N == 0:
            raise ValueError("No memories to search.")
        if N == 1:
            return 0

        opt_iters = max(1, int(math.pi / 4 * math.sqrt(N)))
        n_iters = n_iterations if n_iterations is not None else opt_iters

        amplitudes = self.initialize_superposition(N)

        for iteration in range(n_iters):
            amplitudes = self.oracle(amplitudes, query_embedding, memory_embeddings)
            amplitudes = self.diffusion_operator(amplitudes)

        # Measure: index with highest probability
        probs = amplitudes.abs().pow(2).real
        best_idx = int(probs.argmax().item())

        logger.debug(
            "AmplitudeAmplification: N=%d, iters=%d, best_idx=%d, prob=%.4f",
            N, n_iters, best_idx, float(probs[best_idx].item()),
        )
        return best_idx

    def search_top_k(
        self,
        query_embedding: torch.Tensor,
        memory_embeddings: torch.Tensor,
        k: int = 5,
        n_iterations: Optional[int] = None,
    ) -> List[int]:
        """
        Return indices of top-k memories by amplitude probability after amplification.

        Parameters
        ----------
        query_embedding : torch.Tensor
        memory_embeddings : torch.Tensor
            Shape [N, emb_dim].
        k : int
        n_iterations : int, optional

        Returns
        -------
        list of int
        """
        N = memory_embeddings.shape[0]
        if N == 0:
            return []
        k = min(k, N)

        opt_iters = max(1, int(math.pi / 4 * math.sqrt(N)))
        n_iters = n_iterations if n_iterations is not None else opt_iters

        amplitudes = self.initialize_superposition(N)
        for _ in range(n_iters):
            amplitudes = self.oracle(amplitudes, query_embedding, memory_embeddings)
            amplitudes = self.diffusion_operator(amplitudes)

        probs = amplitudes.abs().pow(2).real
        top_k = torch.topk(probs, k).indices.tolist()
        return top_k

    def speedup_ratio(self, n_memories: int) -> float:
        """
        Theoretical speedup: N / √N = √N.

        Parameters
        ----------
        n_memories : int

        Returns
        -------
        float
        """
        return math.sqrt(n_memories)
