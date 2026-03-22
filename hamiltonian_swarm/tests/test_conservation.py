"""
Tests for energy conservation monitor and handoff protocol.
"""

import pytest
import torch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.core.conservation_monitor import ConservationMonitor
from hamiltonian_swarm.core.hamiltonian import HamiltonianFunction
from hamiltonian_swarm.core.phase_space import PhaseSpaceState
from hamiltonian_swarm.swarm.handoff_protocol import HandoffProtocol
from hamiltonian_swarm.agents.base_agent import AgentDriftException


class TestConservationMonitor:
    def test_stable_signal(self):
        """Constant energy → monitor reports stable."""
        monitor = ConservationMonitor(drift_threshold=0.05)
        for _ in range(50):
            monitor.record(1.0)
        assert monitor.is_stable()

    def test_drift_detection(self):
        """Large variation → monitor detects instability."""
        monitor = ConservationMonitor(drift_threshold=0.05)
        for i in range(50):
            monitor.record(1.0 + i * 0.5)  # linear growth
        assert not monitor.is_stable()

    def test_spike_anomaly_detection(self):
        """Isolated large spike → anomaly detected."""
        monitor = ConservationMonitor(z_score_threshold=2.0)
        for _ in range(50):
            monitor.record(1.0)
        monitor.record(100.0)  # huge spike
        assert monitor.total_anomalies >= 1

    def test_reset_callback_fired(self):
        """reset_callback fires when drift exceeds threshold."""
        called = []
        monitor = ConservationMonitor(
            drift_threshold=0.01,
            reset_callback=lambda: called.append(True),
        )
        for i in range(30):
            monitor.record(1.0 + i * 1.0)  # severe drift
        assert len(called) > 0, "reset_callback was never fired"

    def test_energy_drift_score_zero_for_constant(self):
        """Drift score should be 0 for constant energy."""
        monitor = ConservationMonitor()
        for _ in range(20):
            monitor.record(3.14)
        assert monitor.energy_drift_score() < 1e-10


class TestHandoffProtocol:
    def test_energy_conserved_within_tolerance(self):
        """Handoff protocol should produce energy mismatch < 0.1 after correction."""
        protocol = HandoffProtocol(energy_tolerance=0.05)
        ham_a = HamiltonianFunction(n_dims=3)
        ham_b = HamiltonianFunction(n_dims=3)
        state = PhaseSpaceState(
            q=torch.tensor([1.0, 0.5, -0.3]),
            p=torch.tensor([0.2, -0.1, 0.8]),
            agent_id="agent_a",
        )
        new_state, event = protocol.execute_handoff(
            sender_state=state,
            sender_hamiltonian=ham_a,
            receiver_agent_id="agent_b",
            receiver_hamiltonian=ham_b,
            task_id="test_task",
        )
        assert event.energy_mismatch < 0.1, \
            f"Energy mismatch {event.energy_mismatch:.4f} too large after correction"

    def test_handoff_logged(self):
        """Handoff events are logged."""
        protocol = HandoffProtocol()
        ham = HamiltonianFunction(n_dims=2)
        state = PhaseSpaceState(
            q=torch.tensor([0.5, 0.5]),
            p=torch.tensor([0.5, 0.5]),
            agent_id="a",
        )
        protocol.execute_handoff(state, ham, "b", ham, "task1")
        protocol.execute_handoff(state, ham, "c", ham, "task2")
        log = protocol.get_log()
        assert len(log) == 2

    def test_symplectic_transform_preserves_norm(self):
        """Orthogonal R: ||R q|| = ||q|| (norm preserved)."""
        protocol = HandoffProtocol()
        n = 4
        R = protocol._random_rotation(n)
        v = torch.randn(n)
        assert abs(float((R @ v).norm().item()) - float(v.norm().item())) < 1e-5


class TestAgentDrift:
    def test_agent_drift_exception_raised(self):
        """Agent with severe energy spikes should raise AgentDriftException."""
        from hamiltonian_swarm.core.conservation_monitor import ConservationMonitor
        from hamiltonian_swarm.core.hamiltonian import HamiltonianFunction
        # Build a monitor with tight threshold and NO reset callback
        monitor = ConservationMonitor(drift_threshold=0.01, reset_callback=None)
        ham = HamiltonianFunction(n_dims=2)
        # Feed strongly varying energies to trigger drift
        for i in range(50):
            H = float(ham.total_energy(
                torch.randn(2) * (1 + i * 0.5),
                torch.randn(2) * (1 + i * 0.5),
            ).item())
            monitor.record(H)
        # After feeding large variations the drift score should exceed threshold
        drift = monitor.energy_drift_score()
        assert drift > 0.01, f"Expected drift > 0.01, got {drift:.4f}"
        assert not monitor.is_stable(), "Monitor should be unstable after large energy swings"
        # Confirm AgentDriftException is raised by a real agent
        with pytest.raises(AgentDriftException):
            from hamiltonian_swarm.agents.task_agent import TaskAgent
            agent = TaskAgent(n_dims=2, drift_threshold=0.001)
            # Disable the reset callback so it doesn't suppress the drift
            agent._monitor.reset_callback = None
            for i in range(60):
                q = torch.randn(2) * (1 + i * 0.5)
                p = torch.randn(2) * (1 + i * 0.5)
                agent.update_phase_state(q, p)
            agent.check_stability()
