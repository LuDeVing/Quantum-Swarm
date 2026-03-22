"""
Energy drift detection benchmarks.

Measures how quickly the ConservationMonitor detects injected anomalies.
"""

from __future__ import annotations
import time
import random
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.core.conservation_monitor import ConservationMonitor


def benchmark_detection_latency(n_runs: int = 20) -> dict:
    """Measure mean steps until anomaly detection after a spike injection."""
    latencies = []

    for _ in range(n_runs):
        monitor = ConservationMonitor(z_score_threshold=2.5)
        # Burn in with stable signal
        for _ in range(50):
            monitor.record(1.0 + random.gauss(0, 0.001))

        # Inject spike and measure detection step
        for step in range(1, 20):
            monitor.record(100.0)  # clear spike
            if monitor.detect_anomaly():
                latencies.append(step)
                break

    return {
        "mean_latency_steps": sum(latencies) / len(latencies) if latencies else float("nan"),
        "detection_rate": len(latencies) / n_runs,
        "n_runs": n_runs,
    }


def benchmark_drift_threshold(n_points: int = 500) -> dict:
    """Measure drift score evolution for linear energy growth."""
    monitor = ConservationMonitor(window_size=100)
    drift_scores = []
    for i in range(n_points):
        monitor.record(1.0 + i * 0.01)
        drift_scores.append(monitor.energy_drift_score())
    return {
        "final_drift_score": drift_scores[-1],
        "stable_fraction": sum(1 for d in drift_scores if d < 0.05) / n_points,
    }


if __name__ == "__main__":
    print("\nConservationMonitor Benchmarks")
    print("=" * 40)

    res = benchmark_detection_latency()
    print(f"Detection latency: {res['mean_latency_steps']:.1f} steps "
          f"(detection rate: {res['detection_rate']:.0%})")

    res2 = benchmark_drift_threshold()
    print(f"Drift benchmark: final_score={res2['final_drift_score']:.4f}, "
          f"stable_fraction={res2['stable_fraction']:.2%}")
