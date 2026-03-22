"""
Hamiltonian-based logic validator agent.

Validates task handoffs by checking energy conservation:
    ΔH_sender + ΔH_receiver ≈ 0

Maintains a Swarm Energy Tensor tracking all inter-agent energy transfers.
"""

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

import torch

from .base_agent import BaseAgent, TaskResult

logger = logging.getLogger(__name__)


class EnergyTransactionLog:
    """Record of a single inter-agent energy transaction."""
    __slots__ = ("sender_id", "receiver_id", "task_id", "dH_sender", "dH_receiver", "violation", "timestamp")

    def __init__(
        self,
        sender_id: str,
        receiver_id: str,
        task_id: str,
        dH_sender: float,
        dH_receiver: float,
        violation: bool,
        timestamp: float,
    ) -> None:
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.task_id = task_id
        self.dH_sender = dH_sender
        self.dH_receiver = dH_receiver
        self.violation = violation
        self.timestamp = timestamp


class ValidatorAgent(BaseAgent):
    """
    Swarm-wide Hamiltonian conservation validator.

    Validates each task handoff and maintains an audit trail of all
    energy transactions.

    Parameters
    ----------
    n_dims : int
        Phase-space dimensionality.
    energy_tolerance : float
        Maximum allowed |ΔH_sender + ΔH_receiver| / max(|ΔH_sender|, 1e-8)
        before a handoff is blocked.
    """

    def __init__(
        self,
        n_dims: int = 4,
        energy_tolerance: float = 0.05,
        **kwargs: Any,
    ) -> None:
        super().__init__(n_dims=n_dims, agent_type="validator", **kwargs)
        self.energy_tolerance = energy_tolerance
        self._transaction_log: List[EnergyTransactionLog] = []
        # Swarm Energy Tensor: agent_id → {agent_id: cumulative_transfer}
        self._swarm_tensor: Dict[str, Dict[str, float]] = {}
        logger.info(
            "ValidatorAgent %s created: tolerance=%.3f", self.agent_id, energy_tolerance
        )

    # ------------------------------------------------------------------
    # Handoff validation
    # ------------------------------------------------------------------

    def validate_handoff(
        self,
        sender_id: str,
        receiver_id: str,
        task_id: str,
        H_sender_before: float,
        H_sender_after: float,
        H_receiver_before: float,
        H_receiver_after: float,
    ) -> Tuple[bool, str]:
        """
        Validate that energy is conserved during a task handoff.

        Conservation criterion:
            |ΔH_sender + ΔH_receiver| / max(|ΔH_sender|, ε) < tolerance

        Parameters
        ----------
        sender_id, receiver_id : str
            Agent identifiers.
        task_id : str
            Task being transferred.
        H_*_before, H_*_after : float
            Agent Hamiltonian values before and after handoff.

        Returns
        -------
        allowed : bool
            Whether the handoff is allowed.
        reason : str
            Human-readable validation result.
        """
        import time

        dH_sender = H_sender_after - H_sender_before
        dH_receiver = H_receiver_after - H_receiver_before
        conservation_error = abs(dH_sender + dH_receiver)
        scale = max(abs(dH_sender), 1e-8)
        relative_error = conservation_error / scale

        violation = relative_error > self.energy_tolerance
        allowed = not violation

        # Update Swarm Energy Tensor
        if sender_id not in self._swarm_tensor:
            self._swarm_tensor[sender_id] = {}
        self._swarm_tensor[sender_id][receiver_id] = (
            self._swarm_tensor[sender_id].get(receiver_id, 0.0) + abs(dH_sender)
        )

        # Log transaction
        log_entry = EnergyTransactionLog(
            sender_id=sender_id,
            receiver_id=receiver_id,
            task_id=task_id,
            dH_sender=dH_sender,
            dH_receiver=dH_receiver,
            violation=violation,
            timestamp=time.time(),
        )
        self._transaction_log.append(log_entry)

        if violation:
            reason = (
                f"BLOCKED: conservation violation {relative_error:.4f} > "
                f"{self.energy_tolerance:.4f} "
                f"(ΔH_sender={dH_sender:.4f}, ΔH_receiver={dH_receiver:.4f})"
            )
            logger.warning("ValidatorAgent: %s", reason)
        else:
            reason = (
                f"ALLOWED: conservation error {relative_error:.4f} "
                f"(ΔH_sender={dH_sender:.4f}, ΔH_receiver={dH_receiver:.4f})"
            )
            logger.info("ValidatorAgent: %s", reason)

        return allowed, reason

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def audit_trail(self) -> List[Dict[str, Any]]:
        """
        Return the full energy transaction log.

        Returns
        -------
        list of dict
            Each entry describes one handoff validation event.
        """
        return [
            {
                "sender_id": e.sender_id,
                "receiver_id": e.receiver_id,
                "task_id": e.task_id,
                "dH_sender": e.dH_sender,
                "dH_receiver": e.dH_receiver,
                "violation": e.violation,
                "timestamp": e.timestamp,
            }
            for e in self._transaction_log
        ]

    def swarm_energy_tensor(self) -> Dict[str, Dict[str, float]]:
        """Return the swarm energy transfer tensor."""
        return self._swarm_tensor

    # ------------------------------------------------------------------
    # Task interface
    # ------------------------------------------------------------------

    async def execute_task(self, task: Dict[str, Any]) -> TaskResult:
        """
        Execute a validation task.

        Task payload for 'validate_handoff':
            sender_id, receiver_id, task_id,
            H_sender_before, H_sender_after,
            H_receiver_before, H_receiver_after

        Returns
        -------
        TaskResult with output = {'allowed': bool, 'reason': str}
        """
        task_id = task.get("task_id", "unknown")
        task_type = task.get("type", "validate_handoff")
        payload = task.get("payload", {})
        H_before = float(
            self.hamiltonian.total_energy(self.phase_state.q, self.phase_state.p).item()
        )

        if task_type == "validate_handoff":
            allowed, reason = self.validate_handoff(
                sender_id=payload.get("sender_id", ""),
                receiver_id=payload.get("receiver_id", ""),
                task_id=payload.get("task_id", task_id),
                H_sender_before=float(payload.get("H_sender_before", 0.0)),
                H_sender_after=float(payload.get("H_sender_after", 0.0)),
                H_receiver_before=float(payload.get("H_receiver_before", 0.0)),
                H_receiver_after=float(payload.get("H_receiver_after", 0.0)),
            )
            output = {"allowed": allowed, "reason": reason}
        elif task_type == "audit":
            output = {"audit_trail": self.audit_trail()}
        else:
            output = {"error": f"Unknown task type: {task_type}"}

        dq = torch.randn(self.n_dims) * 0.01
        dp = torch.randn(self.n_dims) * 0.005
        H_after = self.update_phase_state(
            self.phase_state.q + dq, self.phase_state.p + dp
        )

        return TaskResult(
            task_id=task_id,
            agent_id=self.agent_id,
            success=True,
            output=output,
            energy_before=H_before,
            energy_after=H_after,
        )
