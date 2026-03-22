"""
Agent Genome — the evolvable configuration of an agent.

The genome IS the agent's position in configuration space.
QPSO evolves genomes exactly as it evolves particle positions.

q_genome = [architecture params, hyperparams, behavior params]
p_genome = [mutation velocities for each gene]
"""

from __future__ import annotations
import copy
import logging
import math
import random
from dataclasses import dataclass, field
from typing import List

import numpy as np
import torch

logger = logging.getLogger(__name__)

_ACTIVATIONS = ["tanh", "relu", "gelu", "silu"]
_TOPOLOGIES = ["ring", "star", "mesh", "full"]
_REASONING_STYLES = ["chain_of_thought", "tree_of_thought", "direct", "debate"]


@dataclass
class AgentGenome:
    """
    Evolvable configuration of a swarm agent.

    Numeric genes are encoded as a flat vector for QPSO.
    Categorical genes are encoded as integer indices.

    Parameters are chosen to be measurable and directly affect agent behavior.
    """

    # Architecture genes
    hidden_dim: int = 256
    n_hidden_layers: int = 3
    activation_idx: int = 0               # index into _ACTIVATIONS

    # QPSO genes
    n_particles: int = 30
    alpha_max: float = 1.0
    alpha_min: float = 0.5

    # Agent behavior genes
    memory_decay_rate: float = 0.01
    energy_threshold: float = 0.05
    belief_collapse_threshold: float = 0.8
    task_specialization: List[str] = field(default_factory=lambda: ["general"])

    # Communication genes
    topology_idx: int = 0                 # index into _TOPOLOGIES
    broadcast_frequency: int = 10

    # Prompt genes
    reasoning_style_idx: int = 0         # index into _REASONING_STYLES
    system_prompt_template: str = (
        "You are a helpful agent in a swarm. "
        "Reason carefully before acting."
    )

    # Fitness tracking
    fitness_scores: dict = field(default_factory=dict)
    generation_born: int = 0

    # ── String accessors ───────────────────────────────────────────────

    @property
    def activation(self) -> str:
        return _ACTIVATIONS[self.activation_idx % len(_ACTIVATIONS)]

    @property
    def topology_preference(self) -> str:
        return _TOPOLOGIES[self.topology_idx % len(_TOPOLOGIES)]

    @property
    def reasoning_style(self) -> str:
        return _REASONING_STYLES[self.reasoning_style_idx % len(_REASONING_STYLES)]

    # ── Vector encoding ────────────────────────────────────────────────

    def to_vector(self) -> torch.Tensor:
        """
        Flatten all numeric genes to a 1-D tensor for QPSO.

        Layout:
            [hidden_dim, n_hidden_layers, activation_idx,
             n_particles, alpha_max, alpha_min,
             memory_decay_rate, energy_threshold, belief_collapse_threshold,
             topology_idx, broadcast_frequency, reasoning_style_idx]
        """
        return torch.tensor([
            float(self.hidden_dim),
            float(self.n_hidden_layers),
            float(self.activation_idx),
            float(self.n_particles),
            self.alpha_max,
            self.alpha_min,
            self.memory_decay_rate,
            self.energy_threshold,
            self.belief_collapse_threshold,
            float(self.topology_idx),
            float(self.broadcast_frequency),
            float(self.reasoning_style_idx),
        ], dtype=torch.float32)

    @classmethod
    def from_vector(cls, vector: torch.Tensor) -> "AgentGenome":
        """
        Reconstruct genome from a QPSO position vector.

        Parameters
        ----------
        vector : torch.Tensor
            Shape [12].

        Returns
        -------
        AgentGenome
        """
        v = vector.float().tolist()
        return cls(
            hidden_dim=max(16, int(round(v[0]))),
            n_hidden_layers=max(1, int(round(v[1]))),
            activation_idx=int(round(v[2])) % len(_ACTIVATIONS),
            n_particles=max(5, int(round(v[3]))),
            alpha_max=float(np.clip(v[4], 0.5, 2.0)),
            alpha_min=float(np.clip(v[5], 0.1, 1.0)),
            memory_decay_rate=float(np.clip(v[6], 1e-4, 1.0)),
            energy_threshold=float(np.clip(v[7], 0.001, 0.5)),
            belief_collapse_threshold=float(np.clip(v[8], 0.5, 1.0)),
            topology_idx=int(round(v[9])) % len(_TOPOLOGIES),
            broadcast_frequency=max(1, int(round(v[10]))),
            reasoning_style_idx=int(round(v[11])) % len(_REASONING_STYLES),
        )

    # ── Genetic operators ─────────────────────────────────────────────

    def mutate(self, mutation_rate: float = 0.1) -> "AgentGenome":
        """
        Random Gaussian mutation of each numeric gene with probability mutation_rate.

        Parameters
        ----------
        mutation_rate : float
            Probability each gene is mutated.

        Returns
        -------
        AgentGenome
            New (possibly mutated) genome.
        """
        child = copy.deepcopy(self)
        v = child.to_vector()
        noise_std = torch.tensor([
            32.0, 1.0, 1.0,    # arch
            5.0, 0.1, 0.1,     # qpso
            0.005, 0.01, 0.05, # behavior
            1.0, 2.0, 1.0,     # comm + reasoning
        ])
        mask = (torch.rand(len(v)) < mutation_rate).float()
        noise = torch.randn(len(v)) * noise_std * mask
        v_new = v + noise
        mutated = AgentGenome.from_vector(v_new)
        mutated.generation_born = child.generation_born
        mutated.fitness_scores = {}
        return mutated

    def crossover(self, other: "AgentGenome") -> "AgentGenome":
        """
        Uniform crossover: each gene randomly from self or other.

        Parameters
        ----------
        other : AgentGenome

        Returns
        -------
        AgentGenome
        """
        v_self = self.to_vector()
        v_other = other.to_vector()
        mask = (torch.rand(len(v_self)) > 0.5).float()
        v_child = v_self * mask + v_other * (1.0 - mask)
        child = AgentGenome.from_vector(v_child)
        # Inherit prompt template from the fitter parent
        if self.fitness_scores.get("task_performance", 0) >= other.fitness_scores.get("task_performance", 0):
            child.system_prompt_template = self.system_prompt_template
        else:
            child.system_prompt_template = other.system_prompt_template
        return child

    def __repr__(self) -> str:
        return (
            f"AgentGenome(gen={self.generation_born}, "
            f"hidden={self.hidden_dim}x{self.n_hidden_layers}, "
            f"act={self.activation}, "
            f"particles={self.n_particles}, "
            f"fitness={self.fitness_scores})"
        )
