# HamiltonianSwarm

A physics-informed multi-agent AI framework combining Hamiltonian mechanics,
Hamiltonian Neural Networks (HNN), and Quantum-Behaved Particle Swarm Optimization (QPSO).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR                             │
│   QPSO-based agent assignment • Swarm health monitoring      │
└───────────┬─────────────┬──────────────┬────────────────────┘
            │             │              │
     ┌──────▼───┐  ┌──────▼───┐  ┌──────▼───┐  ┌────────────┐
     │ Search   │  │  Task    │  │  Memory  │  │ Validator  │
     │  Agent   │  │  Agent   │  │  Agent   │  │  Agent     │
     │ (QPSO)   │  │          │  │ (φ-space)│  │ (H-audit)  │
     └──────────┘  └──────────┘  └──────────┘  └────────────┘
            │
     ┌──────▼────────────────────────────────────────────┐
     │              QUANTUM ENGINE                        │
     │  QPSO • Wave Functions • Schrödinger Solver        │
     │  Quantum Tunneling • State Registry                │
     └──────────────────────────────────────────────────┘
            │
     ┌──────▼────────────────────────────────────────────┐
     │           HAMILTONIAN CORE                         │
     │  H(q,p) = T(p)+V(q) • Leapfrog/Symplectic Euler   │
     │  HNN • Conservation Monitor • Phase Space          │
     └──────────────────────────────────────────────────┘
```

---

## Formula Reference

### Hamiltonian Mechanics

| Symbol | Formula | Meaning |
|--------|---------|---------|
| H | T(p) + V(q) | Total energy |
| T(p) | ½ p^T M⁻¹ p | Kinetic energy |
| V(q) | ½ q^T K q | Potential energy (quadratic) |
| dq/dt | ∂H/∂p | Hamilton's equation |
| dp/dt | -∂H/∂q | Hamilton's equation |

**Leapfrog (Störmer–Verlet):**
```
p_{n+1/2} = p_n - (dt/2) ∂H/∂q |_{q_n}
q_{n+1}   = q_n + dt ∂H/∂p |_{p_{n+1/2}}
p_{n+1}   = p_{n+1/2} - (dt/2) ∂H/∂q |_{q_{n+1}}
```

### QPSO Core Update

```
φ ~ U(0,1)
p_i = φ·pbest_i + (1-φ)·gbest          (local attractor)
mbest = (1/N) Σ pbest_i(t)             (mean best)
u ~ U(0,1)
x_i(t+1) = p_i ± α|mbest - x_i|·ln(1/u)
α(t) = α_max - (α_max - α_min)·t/T     (annealing)
```

### Quantum Tunneling (WKB)

```
γ = L·√(2m(V₀-E)) / ℏ
T = exp(-2γ)
```

### HNN Loss

```
L = MSE(dq/dt_pred, dq/dt_true)
  + MSE(dp/dt_pred, dp/dt_true)
  + λ·Var[H(q_t, p_t)]
  + μ·(‖∂H/∂q‖² + ‖∂H/∂p‖²)/2
```

---

## Quickstart

### Installation

```bash
cd hamiltonian_swarm
pip install -r requirements.txt
```

### Run tests

```bash
pytest tests/ -v
```

### Travel planner demo

```bash
python -m hamiltonian_swarm.examples.travel_planning_swarm
```

### Robot path optimization

```bash
python -m hamiltonian_swarm.examples.robot_motion_qpso
```

### Train an HNN

```python
from hamiltonian_swarm.training.hnn_trainer import HNNTrainer
from hamiltonian_swarm.training.dataset_generator import generate_harmonic_oscillator, PhaseSpaceDataset

q, p, dqdt, dpdt = generate_harmonic_oscillator(n_trajectories=200)
dataset = PhaseSpaceDataset(q, p, dqdt, dpdt)

trainer = HNNTrainer(n_dims=1, epochs=100)
history = trainer.train(dataset=dataset)
```

### Use QPSO directly

```python
import numpy as np
from hamiltonian_swarm.quantum.qpso import QPSO

def sphere(x): return float(np.sum(x**2))

qpso = QPSO(n_particles=30, n_dims=10, n_iterations=500)
best_pos, best_val, history = qpso.optimize(sphere)
print(f"Global minimum: {best_val:.6f}")
```

### Build a swarm

```python
import asyncio
from hamiltonian_swarm.swarm.swarm_manager import SwarmManager

async def main():
    manager = SwarmManager(n_dims=4)
    manager.spawn_agent("search")
    manager.spawn_agent("task")
    manager.spawn_agent("memory")

    result = await manager.submit_task({
        "description": "search for optimal parameters and store results"
    })
    print(result)
    await manager.shutdown()

asyncio.run(main())
```

---

## Module Overview

| Module | Purpose |
|--------|---------|
| `core/hamiltonian.py` | H(q,p) functions, leapfrog & symplectic Euler integrators |
| `core/hamiltonian_nn.py` | Neural network that learns H from trajectory data |
| `core/conservation_monitor.py` | Sliding-window energy drift detector |
| `core/phase_space.py` | (q, p) state dataclass with symplectic geometry |
| `quantum/qpso.py` | Full QPSO with quantum delta potential, annealing, topologies |
| `quantum/schrodinger.py` | TISE eigenvalue solver + TDSE Crank–Nicolson |
| `quantum/wave_function.py` | Complex ψ(x) with normalization, collapse, superposition |
| `quantum/quantum_tunneling.py` | WKB tunneling probability for local optima escape |
| `quantum/quantum_state.py` | Multi-particle registry, entanglement, Von Neumann entropy |
| `agents/base_agent.py` | Abstract agent with phase-space state and drift detection |
| `agents/orchestrator.py` | Task decomposition, QPSO assignment, health monitoring |
| `agents/search_agent.py` | QPSO-powered optimization agent |
| `agents/memory_agent.py` | Phase-space encoded associative memory with decay |
| `agents/validator_agent.py` | Handoff energy conservation auditor |
| `swarm/handoff_protocol.py` | Symplectic state transfer between agents |
| `swarm/communication_bus.py` | Energy-tagged async message bus |
| `swarm/topology.py` | Ring/star/grid/fully-connected neighbourhood graphs |
| `training/hnn_trainer.py` | Adam + cosine annealing training loop for HNN |
| `training/dataset_generator.py` | SHO, pendulum, double-well, Hénon–Heiles datasets |
| `benchmarks/` | QPSO vs GD, stability, and swarm throughput benchmarks |
| `examples/` | Travel planner, stock HNN, robot path optimization |

---

## Configuration (`config.py`)

All hyperparameters are centralized in `config.py`. Key settings:

```python
INTEGRATION_DT = 0.01          # Leapfrog timestep
ENERGY_DRIFT_THRESHOLD = 0.05  # 5% drift triggers instability
N_PARTICLES = 30               # QPSO swarm size
MAX_ITERATIONS = 500           # QPSO iterations
ALPHA_MAX, ALPHA_MIN = 1.0, 0.5  # Contraction-expansion bounds
HNN_HIDDEN_DIM = 256           # HNN network width
HNN_EPOCHS = 1000              # Training epochs
```

---

## Citation / Inspiration

- **HNN**: Greydanus et al., "Hamiltonian Neural Networks" (NeurIPS 2019)
- **QPSO**: Sun et al., "Particle Swarm Optimization with Particles Having Quantum Behavior" (2004)
- **WKB Tunneling**: Wentzel–Kramers–Brillouin approximation (quantum mechanics)
- **Störmer–Verlet**: Leapfrog integration for symplectic Hamiltonian systems
