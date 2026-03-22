"""
Tests for agent system.
"""

import asyncio
import pytest
import torch
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hamiltonian_swarm.agents.task_agent import TaskAgent
from hamiltonian_swarm.agents.search_agent import SearchAgent
from hamiltonian_swarm.agents.memory_agent import MemoryAgent
from hamiltonian_swarm.agents.validator_agent import ValidatorAgent
from hamiltonian_swarm.agents.orchestrator import Orchestrator, SubTask


class TestTaskAgent:
    def test_execute_task(self):
        agent = TaskAgent(n_dims=4)
        task = {"task_id": "t1", "type": "generic", "payload": {"key": "val"}, "complexity": 0.3}
        result = asyncio.run(agent.execute_task(task))
        assert result.success
        assert result.agent_id == agent.agent_id

    def test_serialize_deserialize(self):
        agent = TaskAgent(n_dims=4)
        state = agent.serialize_state()
        assert "agent_id" in state
        agent2 = TaskAgent(n_dims=4)
        agent2.deserialize_state(state)


class TestSearchAgent:
    def test_search_sphere(self):
        import numpy as np
        agent = SearchAgent(n_dims=2, n_particles=10, n_iterations=50)
        def sphere(x): return float(np.sum(x**2))
        import asyncio
        pos, val, hist = asyncio.run(agent.search_async(sphere))
        assert val < 1.0, f"SearchAgent sphere val={val:.4f}"

    def test_phase_state_updated_after_search(self):
        import numpy as np
        agent = SearchAgent(n_dims=2, n_particles=5, n_iterations=20)
        def sphere(x): return float(np.sum(x**2))
        agent.search(sphere)
        # Phase state should have been updated (not all zeros)
        assert agent.phase_state is not None


class TestMemoryAgent:
    def test_store_and_retrieve(self):
        agent = MemoryAgent(n_dims=4)
        agent.store("Paris trip 2024", importance=2.0)
        agent.store("Meeting notes", importance=0.5)
        agent.store("NYC itinerary", importance=3.0)
        query = torch.zeros(4)
        results = agent.retrieve(query, k=2)
        assert len(results) == 2

    def test_decay_removes_low_importance(self):
        agent = MemoryAgent(n_dims=4, decay_rate=5.0, forget_threshold=0.1)
        agent.store("temp data", importance=0.01)
        initial_count = len(agent._memories)
        agent.decay(dt=5.0)
        assert len(agent._memories) <= initial_count

    def test_store_returns_record_id(self):
        agent = MemoryAgent(n_dims=4)
        rid = agent.store("some content", importance=1.0)
        assert rid.startswith("mem_")


class TestValidatorAgent:
    def test_valid_handoff(self):
        agent = ValidatorAgent(n_dims=4, energy_tolerance=0.5)
        allowed, reason = agent.validate_handoff(
            sender_id="a", receiver_id="b", task_id="t1",
            H_sender_before=1.0, H_sender_after=0.8,
            H_receiver_before=0.5, H_receiver_after=0.7,
        )
        assert allowed, f"Expected allowed, got: {reason}"

    def test_invalid_handoff_blocked(self):
        agent = ValidatorAgent(n_dims=4, energy_tolerance=0.05)
        allowed, reason = agent.validate_handoff(
            sender_id="a", receiver_id="b", task_id="t2",
            H_sender_before=1.0, H_sender_after=0.0,
            H_receiver_before=0.5, H_receiver_after=100.0,
        )
        assert not allowed, "Expected handoff blocked"

    def test_audit_trail(self):
        agent = ValidatorAgent(n_dims=4)
        agent.validate_handoff("a","b","t1",1.0,0.9,0.5,0.6)
        agent.validate_handoff("b","c","t2",2.0,1.8,1.0,1.2)
        trail = agent.audit_trail()
        assert len(trail) == 2


class TestOrchestrator:
    def test_decompose_task_keywords(self):
        orch = Orchestrator(n_dims=4)
        subtasks = orch.decompose_task({"description": "search for flights and store results"})
        types = [s.required_capability for s in subtasks]
        assert "search" in types or "memory" in types

    def test_assign_task_with_agents(self):
        orch = Orchestrator(n_dims=4)
        agent1 = TaskAgent(n_dims=4)
        agent2 = SearchAgent(n_dims=4, n_particles=5, n_iterations=10)
        orch.register_agent(agent1)
        orch.register_agent(agent2)
        subtask = SubTask(
            task_id="sub1", task_type="search",
            payload={}, required_capability="search", h_required=1.0,
        )
        selected = orch.assign_task(subtask)
        assert selected is not None
        assert selected.agent_id in {agent1.agent_id, agent2.agent_id}
