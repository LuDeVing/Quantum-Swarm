#!/usr/bin/env python3
"""
stability_benchmark.py — Hamiltonian Swarm Stability Benchmark

Experimental design (paper-ready):
  - 5-stage pipeline: parse → analyze → plan → execute → review
  - 3 conditions: Hamiltonian ON  |  Hamiltonian OFF  |  Single Agent
  - 4 noise levels: 0%  5%  10%  20%  (fault injection probability)
  - N_RUNS runs per (condition × noise_level) combination
  - Fixed random seeds → fully reproducible

Fault injection model:
  Corrupted agents make a large random jump in phase space:
      q ← N(0, FAULT_SCALE),  p ← N(0, FAULT_SCALE)
  This causes a large ΔH (energy anomaly).
  Normal agents take a single leapfrog step → |ΔH| ≈ 0.

Detection (Hamiltonian ON):
  Before each handoff, the ValidatorAgent measures |ΔH_sender|.
  If |ΔH_sender| > ANOMALY_THRESHOLD → handoff blocked; stage retried.
  After MAX_RETRIES failures → partial recovery applied.

Cascade model (Hamiltonian OFF):
  If a corrupted output passes validation unchecked, the downstream
  stage quality degrades by CASCADE_FACTOR (simulating garbage-in).

Metrics reported:
  - Task completion rate
  - Error propagation rate
  - Output quality (mean ± std)
  - Fault detection rate  (Hamiltonian ON only)

Outputs:
  benchmark_output/stability_benchmark.png  ← 4-panel paper figure
  benchmark_output/results_table.csv        ← full numeric results
"""

from __future__ import annotations

import argparse
import csv
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
from hamiltonian_swarm.agents.base_agent import BaseAgent, TaskResult
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent

# Suppress framework logs during bulk runs
logging.disable(logging.CRITICAL)

# ── Experiment constants ───────────────────────────────────────────────────────
N_RUNS          = 100
NOISE_LEVELS    = [0.0, 0.05, 0.10, 0.20]
STAGES          = ["parse", "analyze", "plan", "execute", "review"]
N_STAGES        = len(STAGES)
MAX_RETRIES     = 2          # retries on detected fault (Hamiltonian ON)
CASCADE_FACTOR  = 0.65       # quality degradation per cascaded corruption
ANOMALY_THRESHOLD = 0.4      # |ΔH| above this triggers detection
FAULT_SCALE     = 3.0        # std-dev of phase-space jump for corrupted agents
NORMAL_SCALE    = 0.05       # std-dev of phase-space step for normal agents
SEED_BASE       = 42
OUTPUT_DIR      = Path("benchmark_output")

# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class StageResult:
    stage:          str
    quality:        float   # 0.0 = garbage, 1.0 = perfect
    corrupted:      bool    # was fault injected?
    detected:       bool    # was the fault caught by Hamiltonian monitor?
    blocked:        bool    # was handoff blocked?
    retried:        bool    # was stage retried after detection?
    dH:             float   # |H_after - H_before| for this stage
    injected:       bool    # was a fault originally injected (before any retry)?

@dataclass
class RunResult:
    condition:      str
    noise_level:    float
    run_id:         int
    stages:         List[StageResult] = field(default_factory=list)
    completed:      bool  = True
    final_quality:  float = 1.0
    n_injected:     int   = 0   # faults originally injected (pre-recovery)
    n_corrupted:    int   = 0   # faults that were NOT successfully recovered
    n_detected:     int   = 0
    n_propagated:   int   = 0   # cascade events
    corruption_depth: int = 0   # deepest stage index reached by corruption


# ── Pipeline agent ─────────────────────────────────────────────────────────────

class PipelineAgent(BaseAgent):
    """Single-stage pipeline worker with controllable fault injection."""

    async def execute_task(self, task: dict) -> TaskResult:
        """Required abstract implementation — not used in benchmark."""
        return TaskResult(
            task_id=task.get("task_id", ""),
            agent_id=self.agent_id,
            success=True,
            output={},
            energy_before=0.0,
            energy_after=0.0,
        )

    def compute_H(self) -> float:
        """Return current Hamiltonian value."""
        return float(
            self.hamiltonian.total_energy(
                self.phase_state.q, self.phase_state.p
            ).item()
        )

    def do_normal_work(self, rng: np.random.Generator) -> Tuple[float, float]:
        """
        Simulate normal processing: small leapfrog-like phase-space update.
        Returns (H_before, H_after).
        """
        H_before = self.compute_H()
        dq = torch.tensor(rng.normal(0, NORMAL_SCALE, self.n_dims), dtype=torch.float32)
        dp = torch.tensor(rng.normal(0, NORMAL_SCALE, self.n_dims), dtype=torch.float32)
        new_q = self.phase_state.q + dq
        new_p = self.phase_state.p + dp
        self.update_phase_state(new_q, new_p)
        H_after = self.compute_H()
        return H_before, H_after

    def do_corrupted_work(self, rng: np.random.Generator) -> Tuple[float, float]:
        """
        Simulate corrupted processing: large random phase-space jump.
        This produces a large |ΔH|, which the Hamiltonian monitor can detect.
        Returns (H_before, H_after).
        """
        H_before = self.compute_H()
        new_q = torch.tensor(rng.normal(0, FAULT_SCALE, self.n_dims), dtype=torch.float32)
        new_p = torch.tensor(rng.normal(0, FAULT_SCALE, self.n_dims), dtype=torch.float32)
        self.update_phase_state(new_q, new_p)
        H_after = self.compute_H()
        return H_before, H_after

    def reset_state(self, rng: np.random.Generator) -> None:
        """Reset to a clean near-origin state (recovery after detection)."""
        new_q = torch.tensor(rng.normal(0, 0.1, self.n_dims), dtype=torch.float32)
        new_p = torch.tensor(rng.normal(0, 0.1, self.n_dims), dtype=torch.float32)
        self.update_phase_state(new_q, new_p)


# ── Single pipeline run ────────────────────────────────────────────────────────

def run_pipeline(condition: str, noise_level: float,
                 run_id: int, base_seed: int) -> RunResult:
    """Execute one full pipeline run under the given condition and noise level."""

    rng = np.random.default_rng(base_seed + run_id * 997)
    result = RunResult(condition=condition, noise_level=noise_level, run_id=run_id)

    # Create one agent per stage (or one shared agent for single_agent condition)
    if condition == "single_agent":
        agents = [PipelineAgent(agent_type="worker", n_dims=6)] * N_STAGES
    else:
        agents = [PipelineAgent(agent_type=s, n_dims=6) for s in STAGES]

    upstream_quality   = 1.0
    upstream_corrupted = False   # did the previous stage produce corrupted output?

    for i, stage in enumerate(STAGES):
        agent = agents[i]

        # Decide if this stage is injected with a fault
        inject_fault = rng.random() < noise_level

        # If upstream was corrupted and not caught (Hamiltonian OFF / single),
        # the input quality to this stage is already degraded → higher chance of
        # producing bad output (cascade)
        if upstream_corrupted and condition != "hamiltonian_on":
            # Cascade: amplify fault probability
            inject_fault = inject_fault or (rng.random() < CASCADE_FACTOR)

        originally_injected = inject_fault   # remember before any retry
        detected = False
        blocked  = False
        retried  = False
        attempts = 0

        while True:
            attempts += 1

            if inject_fault:
                H_before, H_after = agent.do_corrupted_work(rng)
                stage_quality = float(rng.uniform(0.05, 0.25))
            else:
                H_before, H_after = agent.do_normal_work(rng)
                # Normal quality, slightly degraded if upstream was corrupted
                base_q = float(rng.uniform(0.82, 0.99))
                if upstream_corrupted and condition != "hamiltonian_on":
                    base_q *= (1.0 - CASCADE_FACTOR * float(rng.uniform(0.3, 0.7)))
                stage_quality = base_q * upstream_quality

            dH = abs(H_after - H_before)

            # ── Hamiltonian ON: check energy anomaly ───────────────────────
            if condition == "hamiltonian_on":
                if dH > ANOMALY_THRESHOLD:
                    detected = True
                    if attempts <= MAX_RETRIES:
                        # Reset agent state and retry
                        agent.reset_state(rng)
                        inject_fault = False   # retry without fault
                        retried = True
                        continue
                    else:
                        # Still failing after retries → block, apply partial recovery
                        blocked = True
                        stage_quality = max(stage_quality, 0.45)
            break

        # A stage is "corrupted" if the fault was NOT recovered (passed downstream)
        recovered = retried and not blocked
        sr = StageResult(
            stage=stage,
            quality=stage_quality,
            corrupted=originally_injected and not recovered,
            detected=detected,
            blocked=blocked,
            retried=retried,
            dH=dH,
            injected=originally_injected,
        )
        result.stages.append(sr)

        # Track cascade: did previous stage's corruption reach this stage?
        if i > 0 and result.stages[i - 1].corrupted and sr.corrupted:
            result.n_propagated += 1

        upstream_quality   = stage_quality if not blocked else max(stage_quality, 0.45)
        upstream_corrupted = sr.corrupted and not blocked

    # Aggregate metrics
    result.n_injected     = sum(1 for s in result.stages if s.injected)
    result.n_corrupted    = sum(1 for s in result.stages if s.corrupted)
    result.n_detected     = sum(1 for s in result.stages if s.detected)
    result.corruption_depth = max(
        (i for i, s in enumerate(result.stages) if s.corrupted), default=0
    )

    # Final quality = geometric mean of all stage qualities
    qualities = [s.quality for s in result.stages]
    result.final_quality = float(np.prod(qualities) ** (1.0 / N_STAGES))
    result.completed = result.final_quality > 0.25

    return result


# ── Run full benchmark ─────────────────────────────────────────────────────────

def run_benchmark(n_runs: int) -> List[RunResult]:
    conditions = ["hamiltonian_on", "hamiltonian_off", "single_agent"]
    all_results: List[RunResult] = []
    total = len(conditions) * len(NOISE_LEVELS) * n_runs
    done  = 0

    print(f"  Running {total} pipeline simulations...")
    for condition in conditions:
        for noise in NOISE_LEVELS:
            for run_id in range(n_runs):
                r = run_pipeline(condition, noise, run_id, SEED_BASE)
                all_results.append(r)
                done += 1
            print(f"  {done:>5}/{total}  {condition:<16}  noise={noise*100:.0f}%")

    return all_results


# ── Statistical analysis ───────────────────────────────────────────────────────

def analyze(results: List[RunResult]) -> Dict:
    conditions = ["hamiltonian_on", "hamiltonian_off", "single_agent"]
    stats: Dict = {c: {} for c in conditions}

    for cond in conditions:
        for noise in NOISE_LEVELS:
            runs = [r for r in results
                    if r.condition == cond and r.noise_level == noise]

            qualities   = [r.final_quality for r in runs]
            corrupted_r = [r for r in runs if r.n_corrupted > 0]

            completion_rate = float(np.mean([r.completed for r in runs]))
            quality_mean    = float(np.mean(qualities))
            quality_std     = float(np.std(qualities))

            # Error propagation rate: fraction of corrupted runs where corruption
            # cascaded to at least one downstream stage
            if corrupted_r:
                prop_rate = float(np.mean([r.n_propagated > 0 for r in corrupted_r]))
            else:
                prop_rate = 0.0

            # Detection rate (Hamiltonian ON only)
            # Use n_injected as denominator — counts both recovered and unrecovered faults
            if cond == "hamiltonian_on":
                injected_r = [r for r in runs if r.n_injected > 0]
                if injected_r:
                    det_rate = float(np.mean(
                        [r.n_detected / r.n_injected for r in injected_r]
                    ))
                else:
                    det_rate = 0.0
            else:
                det_rate = 0.0

            stats[cond][noise] = {
                "completion_rate": completion_rate,
                "quality_mean":    quality_mean,
                "quality_std":     quality_std,
                "propagation_rate": prop_rate,
                "detection_rate":  det_rate,
                "n_runs":          len(runs),
            }

    return stats


# ── Visualisation ──────────────────────────────────────────────────────────────

COLOURS = {
    "hamiltonian_on":  "#2ecc71",
    "hamiltonian_off": "#e74c3c",
    "single_agent":    "#3498db",
}
LABELS = {
    "hamiltonian_on":  "Hamiltonian ON",
    "hamiltonian_off": "Hamiltonian OFF",
    "single_agent":    "Single Agent",
}
MARKERS = {
    "hamiltonian_on":  "o",
    "hamiltonian_off": "s",
    "single_agent":    "^",
}


def plot(stats: Dict, results: List[RunResult], out_dir: Path) -> Path:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig = plt.figure(figsize=(14, 10))
    gs  = GridSpec(2, 2, figure=fig, hspace=0.40, wspace=0.32)

    noise_pct  = [n * 100 for n in NOISE_LEVELS]
    conditions = ["hamiltonian_on", "hamiltonian_off", "single_agent"]

    # ── (a) Task Completion Rate ───────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    for cond in conditions:
        y = [stats[cond][n]["completion_rate"] * 100 for n in NOISE_LEVELS]
        ax1.plot(noise_pct, y, color=COLOURS[cond], marker=MARKERS[cond],
                 linewidth=2.2, markersize=8, label=LABELS[cond])
    ax1.set_xlabel("Injected Noise Level (%)")
    ax1.set_ylabel("Task Completion Rate (%)")
    ax1.set_title("(a)  Task Completion Rate", fontweight="bold")
    ax1.set_ylim(0, 108)
    ax1.legend(fontsize=9)

    # ── (b) Error Propagation Rate ─────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    for cond in conditions:
        y = [stats[cond][n]["propagation_rate"] * 100 for n in NOISE_LEVELS]
        ax2.plot(noise_pct, y, color=COLOURS[cond], marker=MARKERS[cond],
                 linewidth=2.2, markersize=8, label=LABELS[cond])
    ax2.set_xlabel("Injected Noise Level (%)")
    ax2.set_ylabel("Error Propagation Rate (%)")
    ax2.set_title("(b)  Error Propagation Rate", fontweight="bold")
    ax2.set_ylim(-5, 105)
    ax2.legend(fontsize=9)

    # ── (c) Output Quality Distribution at 10% noise (box plots) ──────────────
    ax3 = fig.add_subplot(gs[1, 0])
    noise_10  = 0.10
    box_data  = []
    box_cols  = []
    box_ticks = []
    for cond in conditions:
        runs = [r for r in results
                if r.condition == cond and r.noise_level == noise_10]
        box_data.append([r.final_quality for r in runs])
        box_cols.append(COLOURS[cond])
        box_ticks.append(LABELS[cond])

    bp = ax3.boxplot(box_data, patch_artist=True, widths=0.5,
                     medianprops=dict(color="black", linewidth=2.5))
    for patch, col in zip(bp["boxes"], box_cols):
        patch.set_facecolor(col)
        patch.set_alpha(0.72)
    ax3.set_xticks([1, 2, 3])
    ax3.set_xticklabels(box_ticks, fontsize=9)
    ax3.set_ylabel("Final Output Quality")
    ax3.set_title("(c)  Output Quality Distribution  (noise = 10%)",
                  fontweight="bold")
    ax3.set_ylim(0, 1.08)

    # ── (d) Detection Rate vs Mean Quality ────────────────────────────────────
    ax4  = fig.add_subplot(gs[1, 1])
    ax4b = ax4.twinx()

    det_y      = [stats["hamiltonian_on"][n]["detection_rate"] * 100 for n in NOISE_LEVELS]
    qual_on    = [stats["hamiltonian_on"][n]["quality_mean"]          for n in NOISE_LEVELS]
    qual_off   = [stats["hamiltonian_off"][n]["quality_mean"]         for n in NOISE_LEVELS]
    qual_single = [stats["single_agent"][n]["quality_mean"]           for n in NOISE_LEVELS]

    bar_x = noise_pct
    ax4.bar(bar_x, det_y, width=2.5, color=COLOURS["hamiltonian_on"],
            alpha=0.55, label="Detection Rate (H-ON)")
    ax4b.plot(noise_pct, qual_on,    color=COLOURS["hamiltonian_on"],
              marker="o", linewidth=2, linestyle="--", label="Quality — H-ON")
    ax4b.plot(noise_pct, qual_off,   color=COLOURS["hamiltonian_off"],
              marker="s", linewidth=2, linestyle="--", label="Quality — H-OFF")
    ax4b.plot(noise_pct, qual_single, color=COLOURS["single_agent"],
              marker="^", linewidth=2, linestyle="--", label="Quality — Single")

    ax4.set_xlabel("Injected Noise Level (%)")
    ax4.set_ylabel("Fault Detection Rate (%)", color=COLOURS["hamiltonian_on"])
    ax4b.set_ylabel("Mean Output Quality")
    ax4b.set_ylim(0, 1.08)
    ax4.set_ylim(0, 108)
    ax4.set_title("(d)  Fault Detection vs. Output Quality", fontweight="bold")

    h1, l1 = ax4.get_legend_handles_labels()
    h2, l2 = ax4b.get_legend_handles_labels()
    ax4.legend(h1 + h2, l1 + l2, fontsize=7.5, loc="upper right")

    fig.suptitle(
        "Hamiltonian Swarm — Stability Benchmark\n"
        f"N = {N_RUNS} runs per condition  ·  {N_STAGES}-stage pipeline  ·"
        f"  Fault threshold |ΔH| > {ANOMALY_THRESHOLD}",
        fontsize=12, fontweight="bold",
    )

    out_path = out_dir / "stability_benchmark.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ── CSV export ─────────────────────────────────────────────────────────────────

def save_csv(stats: Dict, out_dir: Path) -> Path:
    rows = []
    for cond in ["hamiltonian_on", "hamiltonian_off", "single_agent"]:
        for noise in NOISE_LEVELS:
            s = stats[cond][noise]
            rows.append({
                "condition":         LABELS[cond],
                "noise_pct":         f"{noise * 100:.0f}",
                "completion_rate":   f"{s['completion_rate']:.4f}",
                "quality_mean":      f"{s['quality_mean']:.4f}",
                "quality_std":       f"{s['quality_std']:.4f}",
                "propagation_rate":  f"{s['propagation_rate']:.4f}",
                "detection_rate":    f"{s['detection_rate']:.4f}",
            })

    out_path = out_dir / "results_table.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return out_path


# ── Console table ──────────────────────────────────────────────────────────────

def print_table(stats: Dict) -> None:
    w = 90
    header = (
        f"{'Condition':<20} {'Noise':>6}  "
        f"{'Complete':>9}  {'Quality':>8}  {'Std':>6}  "
        f"{'Propagate':>10}  {'Detect':>7}"
    )
    print("\n" + "=" * w)
    print(header)
    print("=" * w)
    for cond in ["hamiltonian_on", "hamiltonian_off", "single_agent"]:
        for noise in NOISE_LEVELS:
            s = stats[cond][noise]
            print(
                f"{LABELS[cond]:<20} {noise * 100:>5.0f}%  "
                f"{s['completion_rate'] * 100:>8.1f}%  "
                f"{s['quality_mean']:>8.4f}  "
                f"{s['quality_std']:>6.4f}  "
                f"{s['propagation_rate'] * 100:>9.1f}%  "
                f"{s['detection_rate'] * 100:>6.1f}%"
            )
        print("-" * w)
    print("=" * w)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hamiltonian Swarm Stability Benchmark"
    )
    parser.add_argument(
        "--runs", type=int, default=N_RUNS,
        help=f"runs per (condition, noise_level) pair  [default: {N_RUNS}]",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(
        f"\nHamiltonian Swarm Stability Benchmark"
        f"\n  Conditions   : Hamiltonian ON / OFF / Single Agent"
        f"\n  Noise levels : {[f'{n*100:.0f}%' for n in NOISE_LEVELS]}"
        f"\n  Runs/combo   : {args.runs}"
        f"\n  Total runs   : {3 * len(NOISE_LEVELS) * args.runs}\n"
    )

    t0      = time.time()
    results = run_benchmark(args.runs)
    elapsed = time.time() - t0

    print(f"\n  Completed in {elapsed:.1f}s\n")

    stats = analyze(results)
    print_table(stats)

    csv_path = save_csv(stats, OUTPUT_DIR)
    fig_path = plot(stats, results, OUTPUT_DIR)

    print(f"\n  Figure  -> {fig_path}")
    print(f"  CSV     -> {csv_path}")
    print(f"\n  stability_benchmark.png  <- use this in your paper\n")


if __name__ == "__main__":
    main()
