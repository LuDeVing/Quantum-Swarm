"""
Energy-tagged message bus for inter-agent communication.

Every message carries an energy_tag = H(sender.q, sender.p).
Backpressure is applied when an agent's queue exceeds QUEUE_BACKPRESSURE_LIMIT.
"""

from __future__ import annotations
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """An energy-tagged inter-agent message."""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    sender_id: str = ""
    receiver_id: str = ""          # empty string = broadcast
    content: Any = None
    energy_tag: float = 0.0        # H(sender.q, sender.p) at send time
    timestamp: float = field(default_factory=time.time)
    message_type: str = "generic"


class CommunicationBus:
    """
    Asynchronous message bus with energy tagging and backpressure.

    Parameters
    ----------
    backpressure_limit : int
        Maximum messages per agent queue before senders are slowed.
    backpressure_delay : float
        Sleep duration (seconds) imposed on sender when receiver is saturated.
    """

    def __init__(
        self,
        backpressure_limit: int = 100,
        backpressure_delay: float = 0.01,
    ) -> None:
        self.backpressure_limit = backpressure_limit
        self.backpressure_delay = backpressure_delay
        self._queues: Dict[str, asyncio.Queue] = {}
        self._broadcast_subscribers: List[str] = []
        self._stats: Dict[str, int] = defaultdict(int)
        self._energy_broadcasts: List[Dict[str, Any]] = []
        logger.info(
            "CommunicationBus initialized: backpressure_limit=%d", backpressure_limit
        )

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str) -> None:
        """Register an agent to receive messages."""
        if agent_id not in self._queues:
            self._queues[agent_id] = asyncio.Queue()
            self._broadcast_subscribers.append(agent_id)
            logger.debug("Bus: registered agent %s.", agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the bus."""
        self._queues.pop(agent_id, None)
        if agent_id in self._broadcast_subscribers:
            self._broadcast_subscribers.remove(agent_id)

    # ------------------------------------------------------------------
    # Send / Receive
    # ------------------------------------------------------------------

    async def send(self, message: Message) -> None:
        """
        Publish a message. Applies backpressure if receiver queue is full.

        The sender's 'communication cost' is modelled by the energy_tag:
        high-energy senders consume more bandwidth.

        Parameters
        ----------
        message : Message
        """
        receiver_id = message.receiver_id

        if receiver_id == "" or receiver_id == "broadcast":
            # Broadcast to all registered agents except sender
            for aid in self._broadcast_subscribers:
                if aid != message.sender_id:
                    await self._deliver(aid, message)
        else:
            await self._deliver(receiver_id, message)

        self._stats[f"sent_from_{message.sender_id}"] += 1
        logger.debug(
            "Bus: message %s sent from %s to %s (energy=%.4f).",
            message.message_id,
            message.sender_id,
            message.receiver_id or "BROADCAST",
            message.energy_tag,
        )

    async def _deliver(self, agent_id: str, message: Message) -> None:
        """Deliver a message with backpressure handling."""
        if agent_id not in self._queues:
            logger.warning("Bus: unknown receiver %s — message dropped.", agent_id)
            return

        queue = self._queues[agent_id]
        # Backpressure: wait if queue is saturated
        while queue.qsize() >= self.backpressure_limit:
            logger.warning(
                "Bus: backpressure applied — agent %s queue full (%d).",
                agent_id,
                queue.qsize(),
            )
            await asyncio.sleep(self.backpressure_delay)

        await queue.put(message)
        self._stats[f"received_by_{agent_id}"] += 1

    async def receive(self, agent_id: str, timeout: float = 1.0) -> Optional[Message]:
        """
        Dequeue one message for agent_id.

        Parameters
        ----------
        agent_id : str
        timeout : float
            Seconds to wait before returning None.

        Returns
        -------
        Message or None
        """
        if agent_id not in self._queues:
            return None
        try:
            msg = await asyncio.wait_for(self._queues[agent_id].get(), timeout=timeout)
            self._queues[agent_id].task_done()
            return msg
        except asyncio.TimeoutError:
            return None

    # ------------------------------------------------------------------
    # Energy broadcasting
    # ------------------------------------------------------------------

    async def broadcast_energy(self, agent_id: str, H_value: float) -> None:
        """
        Publish an energy reading to all energy monitors.

        Parameters
        ----------
        agent_id : str
        H_value : float
            Current Hamiltonian value.
        """
        record = {
            "agent_id": agent_id,
            "H_value": H_value,
            "timestamp": time.time(),
        }
        self._energy_broadcasts.append(record)
        energy_msg = Message(
            sender_id=agent_id,
            receiver_id="broadcast",
            content=record,
            energy_tag=H_value,
            message_type="energy_broadcast",
        )
        await self.send(energy_msg)
        logger.debug("Bus: energy broadcast from %s: H=%.6f", agent_id, H_value)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Return communication statistics."""
        return {
            "registered_agents": list(self._queues.keys()),
            "message_counts": dict(self._stats),
            "energy_broadcasts": len(self._energy_broadcasts),
            "queue_sizes": {aid: q.qsize() for aid, q in self._queues.items()},
        }
