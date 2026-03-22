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
