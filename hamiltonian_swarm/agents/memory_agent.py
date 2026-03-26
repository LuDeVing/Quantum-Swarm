"""
Long-term memory agent using phase-space encoding.

Memories are stored as particles in a potential well: important memories
have high kinetic energy (|p| magnitude) and persist longer under decay.
Low-energy memories are garbage collected ('forgotten').

Storage:  (q_memory, p_memory, content, timestamp)
Retrieval: k-nearest in q-space (Euclidean distance)
Decay:    p(t+dt) = p(t) * exp(-γ * dt)
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import torch
import numpy as np

from .base_agent import BaseAgent, TaskResult

logger = logging.getLogger(__name__)


@dataclass
class MemoryRecord:
    """A single stored memory."""
    q: torch.Tensor        # Position in memory space
    p: torch.Tensor        # Momentum (encodes importance)
    content: Any
    timestamp: float
    record_id: str


class MemoryAgent(BaseAgent):
    """
    Agent that manages long-term associative memory via phase-space encoding.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality (memory embedding size).
    decay_rate : float
        γ: momentum decay rate. p(t+dt) = p(t) * exp(-γ * dt).
    forget_threshold : float
        Memories with |p| < forget_threshold are garbage collected.
    max_memories : int
        Maximum number of memories to retain.
    """

    def __init__(
        self,
        n_dims: int = 8,
        decay_rate: float = 0.01,
        forget_threshold: float = 1e-4,
        max_memories: int = 10000,
        **kwargs: Any,
    ) -> None:
        super().__init__(n_dims=n_dims, agent_type="memory", **kwargs)
        self.decay_rate = decay_rate
        self.forget_threshold = forget_threshold
        self.max_memories = max_memories
        self._memories: List[MemoryRecord] = []
        self._record_counter = 0
        logger.info(
            "MemoryAgent %s created: n_dims=%d, decay_rate=%.4f",
            self.agent_id,
            n_dims,
            decay_rate,
        )

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    def store(self, content: Any, importance: float = 1.0) -> str:
        """
        Store content as a memory particle.

        The memory is encoded as:
          q ~ random position in memory embedding space
          |p| = importance  (high importance = high persistence)

        Parameters
        ----------
        content : Any
            The information to store.
        importance : float
            Importance weight. Larger values → slower decay → longer retention.

        Returns
        -------
        str
            Record ID of the stored memory.
        """
        self._gc_if_needed()

        q = torch.randn(self.n_dims)
        # Normalize q to unit sphere, then perturb with content hash
        q = q / (q.norm() + 1e-8)
        content_hash = hash(str(content)) % 10000 / 10000.0
        q = q + torch.randn(self.n_dims) * content_hash * 0.1

        # Set |p| = importance
        p_dir = torch.randn(self.n_dims)
        p_dir = p_dir / (p_dir.norm() + 1e-8)
        p = p_dir * importance

        record_id = f"mem_{self._record_counter:06d}"
        self._record_counter += 1

        record = MemoryRecord(
            q=q, p=p, content=content, timestamp=time.time(), record_id=record_id
        )
        self._memories.append(record)

        logger.debug(
            "Memory stored: id=%s, importance=%.4f, total_memories=%d",
            record_id,
            importance,
            len(self._memories),
        )
        return record_id

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query_q: torch.Tensor, k: int = 5) -> List[MemoryRecord]:
        """
        Retrieve k nearest memories by Euclidean distance in q-space.

        Parameters
        ----------
        query_q : torch.Tensor
            Query position, shape [n_dims].
        k : int
            Number of memories to return.

        Returns
        -------
        list of MemoryRecord
            Sorted by ascending distance (closest first).
        """
        if not self._memories:
            return []

        # Compute distances
        distances = []
        for mem in self._memories:
            d = float(torch.dist(query_q, mem.q).item())
            distances.append((d, mem))

        distances.sort(key=lambda x: x[0])
        k_nearest = [mem for _, mem in distances[:k]]

        logger.debug(
            "Memory retrieval: query returned %d memories (top dist=%.4f)",
            len(k_nearest),
            distances[0][0] if distances else float("nan"),
        )
        return k_nearest

    # ------------------------------------------------------------------
    # Decay
    # ------------------------------------------------------------------

    def decay(self, dt: float) -> int:
        """
        Apply momentum decay to all memories:
            p(t+dt) = p(t) * exp(-γ * dt)

        Memories with |p| < forget_threshold are removed.

        Parameters
        ----------
        dt : float
            Elapsed time since last decay call.

        Returns
        -------
        int
            Number of memories forgotten.
        """
        decay_factor = float(np.exp(-self.decay_rate * dt))
        forgotten = 0
        surviving = []
        for mem in self._memories:
            mem.p = mem.p * decay_factor
            if float(mem.p.norm().item()) >= self.forget_threshold:
                surviving.append(mem)
            else:
                forgotten += 1

        self._memories = surviving
        if forgotten > 0:
            logger.info(
                "MemoryAgent %s: %d memories forgotten after decay (dt=%.2f).",
                self.agent_id,
                forgotten,
                dt,
            )
        return forgotten

    # ------------------------------------------------------------------
    # Garbage collection
    # ------------------------------------------------------------------

    def _gc_if_needed(self) -> None:
        """Remove memories exceeding capacity, starting with lowest |p|."""
        if len(self._memories) >= self.max_memories:
            self._memories.sort(key=lambda m: float(m.p.norm().item()), reverse=True)
            removed = len(self._memories) - self.max_memories + 1
            self._memories = self._memories[:self.max_memories]
            logger.debug("GC: removed %d low-energy memories.", removed)

    # ------------------------------------------------------------------
    # Task interface
    # ------------------------------------------------------------------

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a memory task.

        Task types:
          - 'store': {'content': ..., 'importance': float}
          - 'retrieve': {'query_q': list or tensor, 'k': int}
          - 'decay': {'dt': float}

        Returns
        -------
        TaskResult
        """
        task_id = task.get("task_id", "unknown")
        task_type = task.get("type", "store")
        H_before = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )

        output: Dict[str, Any] = {}

        if task_type == "store":
            content = task.get("payload", {}).get("content", "")
            importance = float(task.get("payload", {}).get("importance", 1.0))
            record_id = self.store(content, importance)
            output = {"record_id": record_id, "n_memories": len(self._memories)}

        elif task_type == "retrieve":
            raw_q = task.get("payload", {}).get("query_q", [0.0] * self.n_dims)
            k = int(task.get("payload", {}).get("k", 5))
            query_q = torch.tensor(raw_q, dtype=torch.float32)
            records = self.retrieve(query_q, k)
            output = {
                "results": [
                    {"record_id": r.record_id, "content": str(r.content), "timestamp": r.timestamp}
                    for r in records
                ]
            }

        elif task_type == "decay":
            dt = float(task.get("payload", {}).get("dt", 1.0))
            forgotten = self.decay(dt)
            output = {"forgotten": forgotten, "remaining": len(self._memories)}

        else:
            output = {"error": f"Unknown task type: {task_type}"}

        H_after = self.step_phase_state(dt=0.01)

        return TaskResult(
            task_id=task_id,
            agent_id=self.agent_id,
            success=True,
            output=output,
            energy_before=H_before,
            energy_after=H_after,
        )
