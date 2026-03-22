"""Self-improving evolutionary loop."""
from .genome import AgentGenome
from .fitness_evaluator import FitnessEvaluator, GenerationResult
from .mutation_engine import MutationEngine
from .containment import EvolutionaryContainment
from .evolutionary_loop import QuantumSwarmEvolution
from .generation_logger import GenerationLogger
from .natural_selection import NaturalSelection

__all__ = [
    "AgentGenome",
    "FitnessEvaluator",
    "GenerationResult",
    "MutationEngine",
    "EvolutionaryContainment",
    "QuantumSwarmEvolution",
    "GenerationLogger",
    "NaturalSelection",
]
