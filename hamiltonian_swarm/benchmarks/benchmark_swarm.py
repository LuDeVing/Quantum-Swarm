"""
Swarm throughput and latency benchmarks.
"""

from __future__ import annotations
import asyncio
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.swarm.swarm_manager import SwarmManager


async def benchmark_task_throughput(n_tasks: int = 50) -> dict:
    """Measure tasks per second for the orchestrator dispatch pipeline."""
    manager = SwarmManager(n_dims=4)

    for atype in ["task", "task", "search", "memory"]:
        manager.spawn_agent(atype)

    t0 = time.time()
    for i in range(n_tasks):
        await manager.submit_task({
            "task_id": f"bench_{i}",
            "description": f"execute task {i}",
            "subtasks": [{"type": "task", "payload": {"i": i}, "capability": "task", "complexity": 0.1}],
        })
    elapsed = time.time() - t0

    await manager.shutdown()
    return {
        "n_tasks": n_tasks,
        "total_time_s": elapsed,
        "tasks_per_second": n_tasks / elapsed,
    }


if __name__ == "__main__":
    print("\nSwarm Throughput Benchmark")
    print("=" * 40)
    result = asyncio.run(benchmark_task_throughput(50))
    print(f"Tasks: {result['n_tasks']}")
    print(f"Time:  {result['total_time_s']:.3f}s")
    print(f"TPS:   {result['tasks_per_second']:.1f} tasks/sec")
