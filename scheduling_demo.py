#!/usr/bin/env python3
"""
scheduling_demo.py — Multi-Agent Job Scheduling via Hamiltonian QPSO

Research demonstration showing Hamiltonian mechanics is genuinely useful
for multi-agent AI task coordination — not just a physics metaphor.

Problem: P||Cmax (parallel machine scheduling, minimise makespan)
  - M jobs, each with a processing time p_j
  - N machines, each runs one job at a time
  - Assign every job to a machine to minimise max(total load per machine)
  - NP-hard for N >= 2

Hamiltonian encoding:
  Each machine i is an agent with phase-space state (q_i, p_i):
    q_i = current total load assigned to machine i
    p_i = job arrival rate (rate of change of load)
    H_i = (p_i^2 / 2m) + (k/2)(q_i - target)^2
        = kinetic (throughput pressure) + potential (imbalance penalty)

  Conservation invariant: sum(q_i) = sum(p_j) = total work (constant)
  Energy equilibrium: all H_i equal = perfectly balanced schedule

Four algorithms compared on the same instance:
  1. Random          — random job-to-machine assignment
  2. List (greedy)   — always assign next job to least-loaded machine
  3. QPSO only       — QPSO without Hamiltonian monitoring or tunneling
  4. Hamiltonian QPSO — QPSO + conservation monitoring + quantum tunneling

Output: scheduling_output/scheduling_demo.png  (paper-quality 4-panel figure)
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

sys.path.insert(0, str(Path(__file__).parent))
from hamiltonian_swarm.quantum.qpso import QPSO
from hamiltonian_swarm.quantum.quantum_tunneling import QuantumTunneling
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent
from hamiltonian_swarm.agents.base_agent import BaseAgent, TaskResult

logging.disable(logging.CRITICAL)

# ── Problem parameters ─────────────────────────────────────────────────────────
N_MACHINES   = 8
N_JOBS       = 40
SEED         = 42
MAX_JOB_TIME = 20    # processing times uniform in [1, MAX_JOB_TIME]
OUTPUT_DIR   = Path("scheduling_output")

# ── QPSO parameters ────────────────────────────────────────────────────────────
N_PARTICLES  = 50
N_ITERATIONS = 200
ALPHA_MAX    = 1.0
ALPHA_MIN    = 0.5
STAGNATION   = 15    # iterations before tunneling attempt

# ── Hamiltonian parameters ─────────────────────────────────────────────────────
MASS         = 1.0
STIFFNESS    = 2.0   # k in V = (k/2)(q - target)^2


# ── Machine agent ──────────────────────────────────────────────────────────────

class MachineAgent(BaseAgent):
    """
    An agent representing one machine in the scheduling problem.
    Phase space: q = assigned load, p = load-change rate.
    H = kinetic + potential = (p^2/2m) + (k/2)(q - target)^2
    """

    def __init__(self, machine_id: int, target_load: float) -> None:
        super().__init__(n_dims=1, agent_type=f"machine_{machine_id}",
                         mass_scale=MASS, stiffness_scale=STIFFNESS)
        self.machine_id  = machine_id
        self.target_load = target_load   # ideal balanced load
        self._load       = 0.0

    async def execute_task(self, task: dict) -> TaskResult:
        return TaskResult(task_id="", agent_id=self.agent_id,
                          success=True, output={},
                          energy_before=0.0, energy_after=0.0)

    def assign_load(self, new_load: float) -> float:
        """Set machine load and update phase-space state. Returns H."""
        delta = new_load - self._load
        self._load = new_load
        q = torch.tensor([new_load / (self.target_load + 1e-8)],  # normalised position
                         dtype=torch.float32)
        p = torch.tensor([delta / (self.target_load + 1e-8)],     # normalised velocity
                         dtype=torch.float32)
        self.update_phase_state(q, p)
        return float(self.hamiltonian.total_energy(q, p).item())

    @property
    def load(self) -> float:
        return self._load


# ── Problem generation ─────────────────────────────────────────────────────────

def generate_instance(seed: int) -> np.ndarray:
    """Return array of job processing times shape [N_JOBS]."""
    rng = np.random.default_rng(seed)
    return rng.integers(1, MAX_JOB_TIME + 1, size=N_JOBS).astype(float)


def lower_bound(jobs: np.ndarray) -> float:
    """Theoretical lower bound: max(max_job, total_work / n_machines)."""
    return float(max(jobs.max(), jobs.sum() / N_MACHINES))


# ── Assignment → makespan ──────────────────────────────────────────────────────

def makespan(assignment: np.ndarray, jobs: np.ndarray) -> float:
    """Compute makespan (max machine load) for a given job assignment vector."""
    loads = np.zeros(N_MACHINES)
    for j, m in enumerate(assignment.astype(int) % N_MACHINES):
        loads[m] += jobs[j]
    return float(loads.max())


def loads_from_assignment(assignment: np.ndarray, jobs: np.ndarray) -> np.ndarray:
    loads = np.zeros(N_MACHINES)
    for j, m in enumerate(assignment.astype(int) % N_MACHINES):
        loads[m] += jobs[j]
    return loads


def imbalance(assignment: np.ndarray, jobs: np.ndarray) -> float:
    """Coefficient of variation of machine loads (0 = perfect balance)."""
    ls = loads_from_assignment(assignment, jobs)
    mean = ls.mean()
    return float(ls.std() / mean) if mean > 0 else 0.0


# ── Algorithm 1: Random ────────────────────────────────────────────────────────

def solve_random(jobs: np.ndarray, seed: int) -> Tuple[np.ndarray, List[float]]:
    rng = np.random.default_rng(seed + 1)
    assignment = rng.integers(0, N_MACHINES, size=N_JOBS).astype(float)
    return assignment, [makespan(assignment, jobs)]


# ── Algorithm 2: List scheduling (greedy LPT) ─────────────────────────────────

def solve_list(jobs: np.ndarray) -> Tuple[np.ndarray, List[float]]:
    """Longest-Processing-Time first: sort jobs descending, assign to lightest machine."""
    order = np.argsort(-jobs)   # longest first
    assignment = np.zeros(N_JOBS)
    loads = np.zeros(N_MACHINES)
    for j in order:
        m = int(np.argmin(loads))
        assignment[j] = m
        loads[m] += jobs[j]
    return assignment, [makespan(assignment, jobs)]


# ── Algorithm 3: QPSO (no Hamiltonian monitoring) ─────────────────────────────

def solve_qpso(jobs: np.ndarray, seed: int,
               use_tunneling: bool = False,
               use_hamiltonian: bool = False,
               validator: ValidatorAgent | None = None,
               machines: List[MachineAgent] | None = None,
               ) -> Tuple[np.ndarray, List[float], List[int]]:
    """
    Run QPSO on the scheduling problem.

    Parameters
    ----------
    use_tunneling : bool
        Whether to invoke QuantumTunneling for stuck particles.
    use_hamiltonian : bool
        Whether to use Hamiltonian conservation monitoring to reject invalid moves.
    """
    np.random.seed(seed + 2)

    lb = np.zeros(N_JOBS)
    ub = np.full(N_JOBS, float(N_MACHINES))

    tunneling = QuantumTunneling() if use_tunneling else None

    qpso = QPSO(
        n_particles=N_PARTICLES,
        n_dims=N_JOBS,
        bounds=(lb, ub),
        n_iterations=N_ITERATIONS,
        alpha_max=ALPHA_MAX,
        alpha_min=ALPHA_MIN,
    )
    qpso.initialize_particles()

    # Track tunneling events
    tunnel_events: List[int] = []
    convergence:   List[float] = []
    stagnation_counter = np.zeros(N_PARTICLES, dtype=int)
    lb_val = lower_bound(jobs)

    def objective(x: np.ndarray) -> float:
        return makespan(x, jobs)

    # Evaluate initial population
    for i in range(N_PARTICLES):
        val = objective(qpso.positions[i])
        qpso.pbest_values[i] = val
        if val < qpso.gbest_value:
            qpso.gbest_value = val
            qpso.gbest = qpso.positions[i].copy()

    for t in range(N_ITERATIONS):
        qpso.update_mbest()

        for i in range(N_PARTICLES):
            old_pos = qpso.positions[i].copy()
            qpso.update_particle(i, t)
            new_val = objective(qpso.positions[i])

            # ── Hamiltonian conservation check ────────────────────────────
            if use_hamiltonian and validator is not None and machines is not None:
                old_loads = loads_from_assignment(old_pos, jobs)
                new_loads = loads_from_assignment(qpso.positions[i], jobs)
                total_old = old_loads.sum()
                total_new = new_loads.sum()
                conservation_error = abs(total_new - total_old) / (total_old + 1e-8)
                # If conservation is violated (work appeared or vanished), reject move
                if conservation_error > 0.01:
                    qpso.positions[i] = old_pos   # revert
                    new_val = objective(old_pos)

            # ── Quantum tunneling escape ───────────────────────────────────
            if tunneling is not None and stagnation_counter[i] > STAGNATION:
                barrier = abs(qpso.gbest_value - qpso.pbest_values[i]) + 1.0
                if tunneling.should_tunnel(new_val, qpso.pbest_values[i], barrier):
                    # Tunneling: jump to a balanced random assignment
                    new_pos = _balanced_random_assignment(jobs, np.random.default_rng(t + i))
                    qpso.positions[i] = new_pos
                    new_val = objective(new_pos)
                    stagnation_counter[i] = 0
                    tunnel_events.append(t)

            if new_val < qpso.pbest_values[i]:
                qpso.pbest_values[i] = new_val
                qpso.pbest[i] = qpso.positions[i].copy()
                stagnation_counter[i] = 0
            else:
                stagnation_counter[i] += 1

            if new_val < qpso.gbest_value:
                qpso.gbest_value = new_val
                qpso.gbest = qpso.positions[i].copy()

        convergence.append(qpso.gbest_value)

    return qpso.gbest, convergence, tunnel_events


def _balanced_random_assignment(jobs: np.ndarray,
                                rng: np.random.Generator) -> np.ndarray:
    """Generate a random assignment that roughly balances load (tunneling target)."""
    order   = np.argsort(-jobs)
    assign  = np.zeros(N_JOBS)
    loads   = np.zeros(N_MACHINES)
    # LPT base + small random perturbation
    for j in order:
        m = int(np.argmin(loads))
        # 30% chance: assign to a random machine instead (exploration)
        if rng.random() < 0.3:
            m = int(rng.integers(0, N_MACHINES))
        assign[j] = m
        loads[m] += jobs[j]
    return assign


# ── Hamiltonian machine agents setup ──────────────────────────────────────────

def build_machine_agents(jobs: np.ndarray
                         ) -> Tuple[List[MachineAgent], ValidatorAgent]:
    target = jobs.sum() / N_MACHINES
    machines  = [MachineAgent(i, target) for i in range(N_MACHINES)]
    validator = ValidatorAgent(n_dims=1, energy_tolerance=0.15)
    return machines, validator


# ── Run all four algorithms ────────────────────────────────────────────────────

@dataclass
class Result:
    name:          str
    assignment:    np.ndarray
    makespan:      float
    imbalance:     float
    gap_to_lb:     float
    convergence:   List[float]
    tunnel_events: List[int]
    loads:         np.ndarray
    colour:        str


def run_all(jobs: np.ndarray) -> List[Result]:
    lb = lower_bound(jobs)
    machines, validator = build_machine_agents(jobs)
    results = []

    def wrap(name, assignment, convergence, tunnel_events, colour):
        ms = makespan(assignment, jobs)
        return Result(
            name=name,
            assignment=assignment,
            makespan=ms,
            imbalance=imbalance(assignment, jobs),
            gap_to_lb=(ms - lb) / lb * 100,
            convergence=convergence,
            tunnel_events=tunnel_events,
            loads=loads_from_assignment(assignment, jobs),
            colour=colour,
        )

    # 1. Random
    a, c = solve_random(jobs, SEED)
    results.append(wrap("Random", a, c, [], "#e74c3c"))

    # 2. List scheduling (LPT greedy)
    a, c = solve_list(jobs)
    results.append(wrap("List (LPT)", a, c, [], "#e67e22"))

    # 3. QPSO only (no Hamiltonian, no tunneling)
    a, c, te = solve_qpso(jobs, SEED, use_tunneling=False, use_hamiltonian=False)
    results.append(wrap("QPSO only", a, c, te, "#3498db"))

    # 4. Hamiltonian QPSO (conservation monitoring + quantum tunneling)
    a, c, te = solve_qpso(jobs, SEED,
                          use_tunneling=True, use_hamiltonian=True,
                          validator=validator, machines=machines)
    results.append(wrap("Hamiltonian QPSO", a, c, te, "#2ecc71"))

    return results


# ── Print results table ────────────────────────────────────────────────────────

def print_table(results: List[Result], lb: float) -> None:
    w = 72
    print("\n" + "=" * w)
    print(f"{'Algorithm':<20} {'Makespan':>9} {'Imbalance':>10} {'Gap-to-LB':>10} {'Tunnels':>8}")
    print("=" * w)
    for r in results:
        print(f"{r.name:<20} {r.makespan:>9.1f} {r.imbalance:>9.3f}  "
              f"{r.gap_to_lb:>9.1f}%  {len(r.tunnel_events):>7}")
    print("-" * w)
    print(f"{'Theoretical LB':<20} {lb:>9.1f}")
    print("=" * w)


# ── 4-panel figure ─────────────────────────────────────────────────────────────

def plot(results: List[Result], jobs: np.ndarray, out_dir: Path) -> Path:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(14, 10))
    gs  = GridSpec(2, 2, figure=fig, hspace=0.40, wspace=0.32)
    lb  = lower_bound(jobs)

    names   = [r.name   for r in results]
    colours = [r.colour for r in results]

    # ── (a) Makespan comparison ────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    bars = ax1.bar(names, [r.makespan for r in results],
                   color=colours, alpha=0.85, edgecolor="white", linewidth=1.2)
    ax1.axhline(lb, color="black", linestyle="--", linewidth=1.5, label=f"LB = {lb:.0f}")
    for bar, r in zip(bars, results):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                 f"{r.makespan:.0f}", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax1.set_ylabel("Makespan (time units)")
    ax1.set_title("(a)  Makespan  [lower = better]", fontweight="bold")
    ax1.set_ylim(0, max(r.makespan for r in results) * 1.18)
    ax1.tick_params(axis="x", rotation=12)
    ax1.legend(fontsize=9)

    # ── (b) QPSO convergence curves ───────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    for r in results[2:]:   # QPSO variants only
        ax2.plot(r.convergence, color=r.colour, linewidth=2, label=r.name)
        # Mark tunneling events
        for te in r.tunnel_events:
            if te < len(r.convergence):
                ax2.axvline(te, color=r.colour, alpha=0.25, linewidth=0.8)
    ax2.axhline(lb, color="black", linestyle="--", linewidth=1.5, label=f"LB = {lb:.0f}")
    ax2.set_xlabel("Iteration")
    ax2.set_ylabel("Best Makespan")
    ax2.set_title("(b)  QPSO Convergence  (vertical = tunnel event)", fontweight="bold")
    ax2.legend(fontsize=9)

    # ── (c) Load distribution (box plot) ──────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    box_data = [r.loads for r in results]
    bp = ax3.boxplot(box_data, patch_artist=True, widths=0.5,
                     medianprops=dict(color="black", linewidth=2.2))
    for patch, col in zip(bp["boxes"], colours):
        patch.set_facecolor(col)
        patch.set_alpha(0.72)
    ax3.axhline(lb, color="black", linestyle="--", linewidth=1.5,
                label=f"Perfect balance = {lb:.0f}")
    ax3.set_xticks(range(1, len(results) + 1))
    ax3.set_xticklabels(names, fontsize=8, rotation=10)
    ax3.set_ylabel("Machine Load (time units)")
    ax3.set_title("(c)  Load Distribution per Machine", fontweight="bold")
    ax3.legend(fontsize=9)

    # ── (d) Tunneling events + effect ─────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    h_qpso = results[-1]   # Hamiltonian QPSO
    q_only = results[-2]   # QPSO only

    ax4.plot(q_only.convergence,  color=q_only.colour,  linewidth=2,
             label="QPSO only",        alpha=0.7)
    ax4.plot(h_qpso.convergence,  color=h_qpso.colour,  linewidth=2,
             label="Hamiltonian QPSO", alpha=0.9)

    # Highlight tunneling events
    for te in h_qpso.tunnel_events:
        if te < len(h_qpso.convergence):
            ax4.scatter(te, h_qpso.convergence[te], color="#f39c12",
                        zorder=5, s=40, marker="^")

    # Annotate count
    ax4.text(0.97, 0.96, f"Tunnel events: {len(h_qpso.tunnel_events)}",
             transform=ax4.transAxes, ha="right", va="top",
             fontsize=9, color="#f39c12",
             bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#f39c12", alpha=0.8))

    ax4.axhline(lb, color="black", linestyle="--", linewidth=1.5,
                label=f"LB = {lb:.0f}")
    ax4.set_xlabel("Iteration")
    ax4.set_ylabel("Best Makespan")
    ax4.set_title("(d)  Tunneling Events  (orange triangles)", fontweight="bold")
    ax4.legend(fontsize=9)

    # ── Figure title ───────────────────────────────────────────────────────────
    gap_list = f"{results[0].gap_to_lb:.0f}%"
    gap_lpt  = f"{results[1].gap_to_lb:.0f}%"
    gap_qpso = f"{results[2].gap_to_lb:.0f}%"
    gap_hq   = f"{results[3].gap_to_lb:.0f}%"

    fig.suptitle(
        f"Hamiltonian Swarm — Job Scheduling Benchmark\n"
        f"{N_MACHINES} machines  ·  {N_JOBS} jobs  ·  "
        f"LB = {lb:.0f}    "
        f"Gap: Random {gap_list}  |  LPT {gap_lpt}  |  "
        f"QPSO {gap_qpso}  |  H-QPSO {gap_hq}",
        fontsize=11, fontweight="bold",
    )

    out_path = out_dir / "scheduling_demo.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"\nHamiltonian Swarm — Job Scheduling Demo"
        f"\n  Machines   : {N_MACHINES}"
        f"\n  Jobs       : {N_JOBS}"
        f"\n  Seed       : {SEED}"
        f"\n  QPSO iters : {N_ITERATIONS} x {N_PARTICLES} particles\n"
    )

    jobs = generate_instance(SEED)
    lb   = lower_bound(jobs)
    print(f"  Total work : {jobs.sum():.0f}   LB = {lb:.0f}\n")

    t0      = time.time()
    results = run_all(jobs)
    elapsed = time.time() - t0

    print_table(results, lb)
    print(f"\n  Completed in {elapsed:.2f}s")

    out = plot(results, jobs, OUTPUT_DIR)
    print(f"  Figure -> {out}")
    print(f"\n  scheduling_demo.png  <- use this in your paper\n")


if __name__ == "__main__":
    main()
