"""
Task handoff protocol that conserves phase-space state via symplectic transformation.

When Agent A hands a task to Agent B:
1. Serialize Agent A's PhaseSpaceState
2. Apply a symplectic rotation:
       q_B = R * q_A
       p_B = R^{-T} * p_A   (contragredient transform preserves symplectic form)
3. Verify H_A(q_A, p_A) ≈ H_B(q_B, p_B)
4. If mismatch > tolerance: inject correction impulse to p_B
5. Log full handoff event
"""

from __future__ import annotations
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import torch

from ..core.phase_space import PhaseSpaceState
from ..core.hamiltonian import HamiltonianFunction

logger = logging.getLogger(__name__)


@dataclass
class HandoffEvent:
    """Record of a single handoff."""
    handoff_id: str
    sender_id: str
    receiver_id: str
    task_id: str
    H_sender_before: float
    H_receiver_after: float
    energy_mismatch: float
    correction_applied: bool
    timestamp: float


class HandoffProtocol:
    """
    Symplectic handoff protocol for inter-agent task transfer.

    Parameters
    ----------
    energy_tolerance : float
        Relative energy mismatch tolerance (5% = 0.05).
    """

    def __init__(self, energy_tolerance: float = 0.05) -> None:
        self.energy_tolerance = energy_tolerance
        self._log: list[HandoffEvent] = []
        logger.info("HandoffProtocol initialized: tolerance=%.3f", energy_tolerance)

    # ------------------------------------------------------------------
    # Symplectic transform
    # ------------------------------------------------------------------

    def _random_rotation(self, n: int) -> torch.Tensor:
        """Generate a random orthogonal matrix via QR decomposition."""
        A = torch.randn(n, n)
        Q, _ = torch.linalg.qr(A)
        # Ensure det(Q) = +1
        if torch.linalg.det(Q) < 0:
            Q[:, 0] = -Q[:, 0]
        return Q

    def apply_symplectic_transform(
        self,
        state: PhaseSpaceState,
        R: Optional[torch.Tensor] = None,
    ) -> PhaseSpaceState:
        """
        Apply a symplectic transformation to a PhaseSpaceState.

        Transformation:
            q_new = R * q
            p_new = R^{-T} * p   (= R * p for orthogonal R)

        For orthogonal R: R^{-T} = R, so the symplectic form dp ∧ dq is preserved.

        Parameters
        ----------
        state : PhaseSpaceState
        R : torch.Tensor, optional
            Orthogonal rotation matrix [n, n]. Generated randomly if None.

        Returns
        -------
        PhaseSpaceState
            Transformed state.
        """
        n = state.q.shape[0]
        if R is None:
            R = self._random_rotation(n)

        R = R.float()
        q_new = R @ state.q.float()
        # Contragredient: for orthogonal R, R^{-T} = R
        p_new = R @ state.p.float()

        return PhaseSpaceState(q=q_new, p=p_new, agent_id=state.agent_id)

    # ------------------------------------------------------------------
    # Main handoff
    # ------------------------------------------------------------------

    def execute_handoff(
        self,
        sender_state: PhaseSpaceState,
        sender_hamiltonian: HamiltonianFunction,
        receiver_agent_id: str,
        receiver_hamiltonian: HamiltonianFunction,
        task_id: str,
    ) -> Tuple[PhaseSpaceState, HandoffEvent]:
        """
        Execute a symplectic handoff from sender to receiver.

        Steps:
            1. Compute sender energy H_A
            2. Apply symplectic rotation to state
            3. Compute receiver energy H_B
            4. If |H_A - H_B|/H_A > tolerance, inject correction impulse to p_B
            5. Log event

        Parameters
        ----------
        sender_state : PhaseSpaceState
        sender_hamiltonian : HamiltonianFunction
        receiver_agent_id : str
        receiver_hamiltonian : HamiltonianFunction
        task_id : str

        Returns
        -------
        new_state : PhaseSpaceState
            State as it should be loaded by the receiver.
        event : HandoffEvent
        """
        H_A = float(
            sender_hamiltonian.total_energy(sender_state.q, sender_state.p).item()
        )

        # Apply symplectic transform
        new_state = self.apply_symplectic_transform(sender_state)
        new_state.agent_id = receiver_agent_id

        # Compute receiver energy
        H_B = float(
            receiver_hamiltonian.total_energy(new_state.q, new_state.p).item()
        )

        # Mismatch check
        mismatch = abs(H_A - H_B) / (abs(H_A) + 1e-8)
        correction_applied = False

        if mismatch > self.energy_tolerance:
            logger.warning(
                "Handoff energy mismatch %.4f > %.4f — injecting correction impulse.",
                mismatch,
                self.energy_tolerance,
            )
            # Correction: scale p to restore energy
            # H ≈ 0.5 * ||p||² → scale factor = sqrt(H_A / H_B)
            if H_B > 1e-8:
                scale = (abs(H_A) / abs(H_B)) ** 0.5
                new_state = PhaseSpaceState(
                    q=new_state.q,
                    p=new_state.p * scale,
                    agent_id=receiver_agent_id,
                )
            else:
                # H_B near zero: add impulse
                impulse = torch.randn_like(new_state.p) * (abs(H_A) ** 0.5)
                new_state = PhaseSpaceState(
                    q=new_state.q,
                    p=new_state.p + impulse,
                    agent_id=receiver_agent_id,
                )
            H_B = float(
                receiver_hamiltonian.total_energy(new_state.q, new_state.p).item()
            )
            mismatch = abs(H_A - H_B) / (abs(H_A) + 1e-8)
            correction_applied = True

        event = HandoffEvent(
            handoff_id=str(uuid.uuid4())[:8],
            sender_id=sender_state.agent_id,
            receiver_id=receiver_agent_id,
            task_id=task_id,
            H_sender_before=H_A,
            H_receiver_after=H_B,
            energy_mismatch=mismatch,
            correction_applied=correction_applied,
            timestamp=time.time(),
        )
        self._log.append(event)

        logger.info(
            "Handoff %s: %s→%s, H_A=%.4f, H_B=%.4f, mismatch=%.4f, corrected=%s",
            event.handoff_id,
            sender_state.agent_id,
            receiver_agent_id,
            H_A,
            H_B,
            mismatch,
            correction_applied,
        )
        return new_state, event

    def get_log(self) -> list[dict[str, Any]]:
        """Return all handoff events as dicts."""
        return [
            {
                "handoff_id": e.handoff_id,
                "sender_id": e.sender_id,
                "receiver_id": e.receiver_id,
                "task_id": e.task_id,
                "H_sender_before": e.H_sender_before,
                "H_receiver_after": e.H_receiver_after,
                "energy_mismatch": e.energy_mismatch,
                "correction_applied": e.correction_applied,
                "timestamp": e.timestamp,
            }
            for e in self._log
        ]
