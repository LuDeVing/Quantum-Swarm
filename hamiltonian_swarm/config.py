"""
Global hyperparameters and constants for the HamiltonianSwarm framework.
"""

# Hamiltonian parameters
MASS_MATRIX_SCALE: float = 1.0
STIFFNESS_MATRIX_SCALE: float = 1.0
INTEGRATION_DT: float = 0.01
INTEGRATION_STEPS: int = 100
ENERGY_DRIFT_THRESHOLD: float = 0.05
ANOMALY_ZSCORE: float = 3.0
CONSERVATION_LOSS_LAMBDA: float = 0.5

# QPSO parameters
N_PARTICLES: int = 30
N_DIMENSIONS: int = 10
MAX_ITERATIONS: int = 500
ALPHA_MAX: float = 1.0
ALPHA_MIN: float = 0.5
INERTIA_WEIGHT: float = 0.729
C1: float = 1.49445   # cognitive coefficient
C2: float = 1.49445   # social coefficient

# Quantum parameters
HBAR: float = 1.0                  # reduced Planck constant (natural units)
PARTICLE_MASS: float = 1.0
GRID_SIZE: int = 256
GRID_SPACING: float = 0.1
TIME_STEP: float = 0.001

# Swarm parameters
MAX_AGENTS: int = 32
QUEUE_BACKPRESSURE_LIMIT: int = 100
HANDOFF_ENERGY_TOLERANCE: float = 0.05
MEMORY_DECAY_RATE: float = 0.01
MEMORY_FORGET_THRESHOLD: float = 1e-4

# HNN training
HNN_HIDDEN_DIM: int = 256
HNN_HIDDEN_LAYERS: int = 3
HNN_LEARNING_RATE: float = 1e-3
HNN_EPOCHS: int = 1000
HNN_BATCH_SIZE: int = 256
HNN_GRAD_CLIP: float = 1.0

# ── Quantum belief parameters ──────────────────────────────────────────
BELIEF_N_HYPOTHESES: int = 10
BELIEF_COLLAPSE_THRESHOLD: float = 0.8   # collapse when max |c|² > this
BELIEF_ENTROPY_MAX: float = 2.0           # flag if entropy exceeds this

# ── Evolution parameters ───────────────────────────────────────────────
POPULATION_SIZE: int = 20
MAX_GENERATIONS: int = 1000
PARETO_FRONT_SIZE: int = 5
NOVELTY_K_NEIGHBORS: int = 3
MUTATION_RATE: float = 0.1
CROSSOVER_RATE: float = 0.7
CONSERVATION_TOLERANCE: float = 0.05
EMERGENCE_WATCH_GENERATION: int = 20
CHECKPOINT_EVERY_N: int = 10

# ── Information diffusion parameters ──────────────────────────────────
DIFFUSION_HBAR: float = 1.0
DIFFUSION_TIMESTEP: float = 0.1
DIFFUSION_ARRIVAL_THRESHOLD: float = 0.5

# ── QEC parameters ────────────────────────────────────────────────────
QEC_N_COPIES: int = 3
QEC_CORRECTION_THRESHOLD: float = 0.3

# ── Quantum annealing parameters ──────────────────────────────────────
ANNEALING_N_STEPS: int = 1000
ANNEALING_T_START: float = 1.0
ANNEALING_T_END: float = 0.001
ANNEALING_TUNNELING_SCALE: float = 1.0

# ── Market parameters ─────────────────────────────────────────────────
POLYMARKET_API_BASE: str = "https://clob.polymarket.com"
KELLY_FRACTION_MAX: float = 0.25
MIN_EDGE_TO_BET: float = 0.03
PORTFOLIO_MAX_POSITIONS: int = 10
