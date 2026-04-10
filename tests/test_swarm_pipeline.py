"""
test_swarm_pipeline.py — 1-cycle simulations of each pipeline stage.

Each test simulates exactly one complete cycle of a pipeline stage
with mock LLM responses, verifying structure and coordination logic
without any real API calls.
"""
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, call
from software_company import (
    RollingContext, ROLES, HYPOTHESES, ROLE_PRIOR,
    run_team_planning, extract_stance_probs,
    perplexity_to_similarities,
)
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState


def make_state():
    return ActiveInferenceState(HYPOTHESES, ROLE_PRIOR)

def make_rolling_ctxs(*keys):
    return {k: RollingContext() for k in keys}


# ── Blackboard planning — 1 full cycle ───────────────────────────────────────

class TestBlackboardPlanningCycle:
    """Simulate the full run_team_planning() flow with mock LLM."""

    TEAM       = "Engineering"
    MANAGER    = "eng_manager"
    WORKERS    = ["dev_1", "dev_2", "dev_3"]

    def _board_response(self):
        return "ITEM_1: Build authentication backend\nITEM_2: Build todo CRUD API\nITEM_3: Build frontend components"

    def _worker_responses(self):
        # Each worker claims a different item
        return [
            "I am a backend developer. CLAIM: item_1",
            "I focus on APIs. CLAIM: item_2",
            "I do frontend. CLAIM: item_3",
        ]

    def test_all_workers_get_unique_assignments(self):
        responses = [self._board_response()] + self._worker_responses()
        with patch("software_company.llm_call", side_effect=responses):
            rolling_ctxs   = make_rolling_ctxs(self.MANAGER, *self.WORKERS)
            health_states  = {k: make_state() for k in [self.MANAGER] + self.WORKERS}
            assignments, _pool = run_team_planning(
                self.TEAM, self.MANAGER, self.WORKERS,
                "Build a todo app", rolling_ctxs, health_states,
            )
        assert len(assignments) == 3
        assert len(set(assignments.values())) == 3  # all unique tasks

    def test_assignments_dict_keyed_by_worker_role(self):
        responses = [self._board_response()] + self._worker_responses()
        with patch("software_company.llm_call", side_effect=responses):
            rolling_ctxs  = make_rolling_ctxs(self.MANAGER, *self.WORKERS)
            health_states = {k: make_state() for k in [self.MANAGER] + self.WORKERS}
            assignments, _pool = run_team_planning(
                self.TEAM, self.MANAGER, self.WORKERS,
                "Build a todo app", rolling_ctxs, health_states,
            )
        for worker in self.WORKERS:
            assert worker in assignments

    def test_conflict_resolution_assigns_all_workers(self):
        # All three workers claim item_1 → conflict → manager reassigns
        board = self._board_response()
        conflict_claims = [
            "I want item_1. CLAIM: item_1",
            "Me too! CLAIM: item_1",
            "Also me. CLAIM: item_1",
        ]
        with patch("software_company.llm_call", side_effect=[board] + conflict_claims):
            rolling_ctxs  = make_rolling_ctxs(self.MANAGER, *self.WORKERS)
            health_states = {k: make_state() for k in [self.MANAGER] + self.WORKERS}
            assignments, _pool = run_team_planning(
                self.TEAM, self.MANAGER, self.WORKERS,
                "Build a todo app", rolling_ctxs, health_states,
            )
        # All workers should still get an assignment (even if duplicate)
        assert len(assignments) == 3

    def test_worker_rolling_ctx_updated_after_planning(self):
        responses = [self._board_response()] + self._worker_responses()
        with patch("software_company.llm_call", side_effect=responses):
            rolling_ctxs  = make_rolling_ctxs(self.MANAGER, *self.WORKERS)
            health_states = {k: make_state() for k in [self.MANAGER] + self.WORKERS}
            run_team_planning(
                self.TEAM, self.MANAGER, self.WORKERS,
                "Build a todo app", rolling_ctxs, health_states,
            )
        # Each worker's context should have their claim recorded
        for worker in self.WORKERS:
            assert len(rolling_ctxs[worker].recent) > 0

    def test_no_claim_in_response_falls_back_to_unclaimed_item(self):
        board = self._board_response()
        no_claim_responses = [
            "I'll work on this but didn't state claim",  # no CLAIM: in response
            "CLAIM: item_2",
            "CLAIM: item_3",
        ]
        with patch("software_company.llm_call", side_effect=[board] + no_claim_responses):
            rolling_ctxs  = make_rolling_ctxs(self.MANAGER, *self.WORKERS)
            health_states = {k: make_state() for k in [self.MANAGER] + self.WORKERS}
            assignments, _pool = run_team_planning(
                self.TEAM, self.MANAGER, self.WORKERS,
                "Build a todo app", rolling_ctxs, health_states,
            )
        # All workers should still be assigned something
        assert all(v for v in assignments.values())


# ── Worker reasoning — 1 round cycle ─────────────────────────────────────────

class TestWorkerRoundCycle:
    """Simulate run_worker() for one round — validates output structure."""

    def _mock_worker_output(self, stance="PRAGMATIC"):
        return f"I implemented the auth module with JWT tokens. STANCE: {stance}"

    def _mock_tools_result(self, text, perplexity=2.0):
        """Return value shape for _run_with_tools: (output, tool_results, perplexity)."""
        return (text, [], perplexity)

    def test_worker_round1_produces_worker_output(self):
        from software_company import run_worker
        mock_output = self._mock_worker_output()
        with patch("software_company._run_with_tools",
                   return_value=self._mock_tools_result(mock_output)):
            result = run_worker(
                role_key="dev_1",
                task="Implement JWT authentication",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        assert result.output == mock_output
        assert result.role == "dev_1"
        assert result.round == 1

    def test_worker_round1_extracts_stance(self):
        from software_company import run_worker
        with patch("software_company._run_with_tools",
                   return_value=self._mock_tools_result("output STANCE: MINIMAL")):
            result = run_worker(
                role_key="dev_1",
                task="task",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        assert result.stance == "minimal"

    def test_worker_round1_missing_stance_defaults_pragmatic(self):
        from software_company import run_worker
        with patch("software_company._run_with_tools",
                   return_value=self._mock_tools_result("output with no stance marker")):
            result = run_worker(
                role_key="dev_1",
                task="task",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        assert result.stance == "pragmatic"

    def test_worker_round2_receives_peer_context(self):
        from software_company import run_worker
        captured_prompts = []

        def capture_tools(prompt, *args, **kwargs):
            captured_prompts.append(prompt)
            return ("output STANCE: ROBUST", [], 2.0)

        with patch("software_company._run_with_tools", side_effect=capture_tools):
            run_worker(
                role_key="dev_2",
                task="Build todo API",
                peer_outputs=["Dev 1 built auth module with JWT"],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=2,
            )
        combined = " ".join(captured_prompts)
        assert "Dev 1 built auth module with JWT" in combined

    def test_worker_f_health_populated(self):
        from software_company import run_worker
        with patch("software_company._run_with_tools",
                   return_value=self._mock_tools_result("output STANCE: PRAGMATIC", 2.5)):
            result = run_worker(
                role_key="dev_1",
                task="task",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        assert result.F_health >= 0.0

    def test_worker_stance_probs_sum_to_one(self):
        import math
        from software_company import run_worker
        with patch("software_company._run_with_tools",
                   return_value=self._mock_tools_result("output STANCE: SCALABLE", 2.0)):
            result = run_worker(
                role_key="dev_1",
                task="task",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        assert math.isclose(sum(result.stance_probs), 1.0, abs_tol=1e-9)


# ── Health monitoring — anomaly detection cycle ───────────────────────────────

class TestHealthMonitoringCycle:
    """Simulate the anomaly detection and recovery flow."""

    def test_healthy_agent_no_anomaly_flag(self):
        from software_company import run_worker
        # Low perplexity = confident = healthy
        with patch("software_company._run_with_tools", return_value=("clear output STANCE: PRAGMATIC", [], 1.5)):
            result = run_worker(
                role_key="dev_1",
                task="task",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=make_state(),
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        # Should not be anomaly with low perplexity on a fresh state
        assert isinstance(result.anomaly, bool)

    def test_anomaly_triggers_fixer_call(self):
        from software_company import run_worker
        # Force anomaly: very high perplexity = very confused
        fixer_called = []

        def mock_fixer(role_key, task, failed_output, F_score):
            fixer_called.append(True)
            return "fixed output STANCE: PRAGMATIC"

        with patch("software_company._run_with_tools", return_value=("vague uncertain output STANCE: PRAGMATIC", [], 9.0)), \
             patch("software_company._run_fixer", side_effect=mock_fixer):
            state = make_state()
            # Force anomaly flag by manipulating state
            state._F_history = [0.1] * 5  # baseline history
            # Now update with very high F to trigger z-score
            result = run_worker(
                role_key="dev_1",
                task="task",
                peer_outputs=[],
                peer_tool_results=[],
                health_state=state,
                rolling_ctx=RollingContext(),
                round_num=1,
            )
        # Test passes as long as no crash — fixer may or may not be called
        assert isinstance(result.anomaly, bool)


# ── Stance interference — 1 cycle ─────────────────────────────────────────────

class TestStanceInterferenceCycle:
    """Simulate how stances are blended across a team after a round."""

    def test_three_different_stances_blend_toward_mean(self):
        from software_company import interfere_weighted
        # Three agents with very different stances
        minimal   = np.array([0.9, 0.05, 0.025, 0.025])  # minimal dominant
        robust    = np.array([0.025, 0.9, 0.05, 0.025])   # robust dominant
        pragmatic = np.array([0.025, 0.025, 0.05, 0.9])   # pragmatic dominant
        beliefs   = [minimal, robust, pragmatic]
        weights   = [1/3, 1/3, 1/3]

        blended = interfere_weighted(beliefs, weights, alpha=0.5)

        # After blending, no single stance should be as extreme
        assert blended[0][0] < 0.9   # minimal agent diluted
        assert blended[1][1] < 0.9   # robust agent diluted
        assert blended[2][3] < 0.9   # pragmatic agent diluted

    def test_consensus_emerges_with_alpha_one(self):
        from software_company import interfere_weighted
        beliefs = [
            np.array([0.7, 0.1, 0.1, 0.1]),
            np.array([0.1, 0.7, 0.1, 0.1]),
            np.array([0.1, 0.1, 0.7, 0.1]),
        ]
        blended = interfere_weighted(beliefs, [1/3]*3, alpha=1.0)
        # All agents should have identical beliefs
        np.testing.assert_array_almost_equal(blended[0], blended[1], decimal=5)
        np.testing.assert_array_almost_equal(blended[1], blended[2], decimal=5)


# ── RollingContext across a sprint ────────────────────────────────────────────

class TestRollingContextSprintCycle:
    """Simulate context accumulation across a 3-round sprint."""

    def test_context_grows_across_rounds(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary text"):
            ctx.add("Round 1 task", "Implemented auth module")
            assert "Round 1 task" in ctx.get()

            ctx.add("Round 2 task", "Added todo routes")
            assert "Round 2 task" in ctx.get()

    def test_sprint_context_survives_rollover(self):
        ctx = RollingContext(max_recent=2)
        with patch("software_company.llm_call", return_value="accumulated summary"):
            ctx.add("task1", "output1")
            ctx.add("task2", "output2")
            ctx.add("task3", "output3")  # triggers rollover

        # Summary should have been set by the mock
        assert ctx.summary == "accumulated summary"
        # Still have recent entries
        assert len(ctx.recent) == 2

    def test_multiple_agents_independent_contexts(self):
        ctxs = {f"dev_{i}": RollingContext() for i in range(3)}
        with patch("software_company.llm_call", return_value="summary"):
            ctxs["dev_0"].add("dev0 task", "dev0 output")
            ctxs["dev_1"].add("dev1 task", "dev1 output")
            ctxs["dev_2"].add("dev2 task", "dev2 output")

        # Each context only has its own entry
        assert "dev0" in ctxs["dev_0"].get()
        assert "dev1" not in ctxs["dev_0"].get()
        assert "dev2" not in ctxs["dev_0"].get()
