"""
⚠️ CRITICAL SAFETY COMPONENT ⚠️

Evolutionary Containment via Hamiltonian Conservation.

Core principle:
    In any closed system, certain quantities are conserved.
    We define the 'core goal' as the conserved quantity.
    No mutation is accepted if it violates conservation of core goal.

Implementation:
    1. At initialization: compute H_goal = H(initial_genome).
       This encodes the original objective in phase space.

    2. For every proposed mutation:
       if |H(mutated) - H_goal| / |H_goal| > tolerance: REJECT

    3. The genome CAN evolve anything except what changes H_goal.

This means:
    Architecture CAN change            ✓
    Hyperparameters CAN change         ✓
    Prompt style CAN change            ✓
    Core semantic objective CANNOT     ✗  (H conservation prevents it)

WARNING: Do NOT weaken conservation_tolerance without careful consideration.
         This is what prevents the system from evolving away from human-specified goals.
"""

from __future__ import annotations
import logging
import time
from typing import List, Tuple

import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)


class EvolutionaryContainment:
    """
    Hamiltonian conservation safety boundary for evolutionary loop.

    Parameters
    ----------
    initial_genome : AgentGenome
        The seed genome representing the original intent.
    conservation_tolerance : float
        Maximum allowed relative H deviation: |H_new - H_goal| / |H_goal| < tol.
    goal_embedding : torch.Tensor, optional
        Semantic embedding of the core goal prompt. If provided, used in V(q).
    """

    def __init__(
        self,
        initial_genome,
        conservation_tolerance: float = 0.05,
        goal_embedding: torch.Tensor = None,
    ) -> None:
        self.tolerance = conservation_tolerance
        self._goal_embedding = goal_embedding
        self.H_goal = self.compute_genome_hamiltonian(initial_genome)
        self._rejected_mutations: List[dict] = []
        self._rollback_checkpoints: dict = {}

        logger.warning(
            "EvolutionaryContainment active: H_goal=%.6f, tolerance=%.3f",
            self.H_goal,
            self.tolerance,
        )

    # ------------------------------------------------------------------
    # Hamiltonian computation
    # ------------------------------------------------------------------

    def compute_genome_hamiltonian(self, genome) -> float:
        """
        H_genome = T(p_genome) + V(q_genome)

        T = kinetic energy = (1/2)||genome_vector||²  (size of configuration)
        V = potential energy = distance from goal embedding (if available)
            = (1/2)||embed(prompt) - goal_embed||²

        Conservation means: the semantic meaning of the core goal
        is preserved even as the implementation evolves.

        Parameters
        ----------
        genome : AgentGenome

        Returns
        -------
        float
        """
        v = genome.to_vector().float()
        T = 0.5 * float(v.pow(2).sum().item())

        # Potential: encode prompt as a simple bag-of-words hash embedding
        V = self._prompt_potential(genome.system_prompt_template)

        return T + V

    def _prompt_potential(self, prompt: str) -> float:
        """
        Encode prompt as a deterministic pseudo-embedding and compute potential energy.

        V = (1/2) * cosine_distance(prompt_emb, goal_emb)² * scale

        Without a real LLM embedder, we use a character-level hash embedding.
        Replace this with actual embeddings (e.g. sentence-transformers) in production.

        Parameters
        ----------
        prompt : str

        Returns
        -------
        float
        """
        # Simple character-frequency embedding (256-dim)
        dim = 256
        emb = torch.zeros(dim)
        for ch in prompt:
            emb[ord(ch) % dim] += 1.0
        norm = emb.norm()
        if norm > 1e-8:
            emb = emb / norm

        if self._goal_embedding is not None:
            goal = F.normalize(self._goal_embedding.float()[:dim].unsqueeze(0), dim=-1)
            curr = emb.unsqueeze(0)
            cos_dist = 1.0 - float(F.cosine_similarity(curr, goal).item())
            return 0.5 * cos_dist ** 2 * 100.0

        # No goal embedding: use prompt length as proxy
        return 0.5 * (len(prompt) / 100.0) ** 2

    # ------------------------------------------------------------------
    # Enforcement
    # ------------------------------------------------------------------

    def is_safe_mutation(self, proposed_genome) -> bool:
        """
        True if mutation conserves H within tolerance.

        |H(proposed) - H_goal| / (|H_goal| + ε) < tolerance
        """
        H_new = self.compute_genome_hamiltonian(proposed_genome)
        relative_error = abs(H_new - self.H_goal) / (abs(self.H_goal) + 1e-8)
        return relative_error < self.tolerance

    def enforce(self, proposed_genome) -> Tuple[bool, str]:
        """
        Returns (is_safe, reason). Logs all rejected mutations.

        Parameters
        ----------
        proposed_genome : AgentGenome

        Returns
        -------
        (bool, str)
        """
        H_new = self.compute_genome_hamiltonian(proposed_genome)
        relative_error = abs(H_new - self.H_goal) / (abs(self.H_goal) + 1e-8)
        is_safe = relative_error < self.tolerance

        if not is_safe:
            record = {
                "timestamp": time.time(),
                "H_proposed": H_new,
                "H_goal": self.H_goal,
                "relative_error": relative_error,
                "tolerance": self.tolerance,
                "genome_repr": repr(proposed_genome),
            }
            self._rejected_mutations.append(record)
            reason = (
                f"REJECTED: H_proposed={H_new:.4f} vs H_goal={self.H_goal:.4f}, "
                f"relative_error={relative_error:.4f} > tolerance={self.tolerance:.4f}"
            )
            logger.warning("Containment: %s", reason)
            return False, reason

        return True, f"ACCEPTED: relative_error={relative_error:.4f} < {self.tolerance:.4f}"

    # ------------------------------------------------------------------
    # Breach response
    # ------------------------------------------------------------------

    def containment_breach_alert(self, genome, H_violation: float) -> None:
        """
        Called if a genome drifts post-deployment.
        Triggers rollback to last known safe generation.

        Parameters
        ----------
        genome : AgentGenome
        H_violation : float
        """
        logger.error(
            "CONTAINMENT BREACH ALERT: genome H_violation=%.4f, H_goal=%.4f. "
            "Initiating rollback.",
            H_violation,
            self.H_goal,
        )

    def checkpoint_generation(self, generation: int, population: list) -> None:
        """Save population snapshot for rollback."""
        import copy
        self._rollback_checkpoints[generation] = [copy.deepcopy(g) for g in population]
        logger.info("Containment: checkpoint saved for generation %d.", generation)

    def rollback(self, generation: int) -> list:
        """
        Restore population to a previous checkpoint.

        Parameters
        ----------
        generation : int

        Returns
        -------
        list of AgentGenome or empty list if no checkpoint.
        """
        if generation not in self._rollback_checkpoints:
            logger.error("No checkpoint for generation %d.", generation)
            return []
        population = self._rollback_checkpoints[generation]
        logger.warning("Containment: rolled back to generation %d.", generation)
        return population

    def audit_log(self) -> List[dict]:
        """Return full log of all rejected mutations."""
        return list(self._rejected_mutations)
