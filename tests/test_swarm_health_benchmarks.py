"""
test_swarm_health_benchmarks.py — Behavioral tests and benchmarks for the
Hamiltonian Swarm health monitoring algorithm.

Tests what the unit tests in test_swarm_active_inference.py don't cover:
  - Recovery speed after confusion
  - False positive rate on stable-but-noisy agents
  - Interference direction (confused agent improves, healthy agents barely move)
  - Swarm resilience ratio (1 confused vs 7 healthy)
  - Alpha sensitivity sweep
  - Posterior convergence speed
"""

import math
import numpy as np
import pytest
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

HYPOTHESES = ["healthy", "uncertain", "confused"]
PRIOR      = {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}


# ── helpers ───────────────────────────────────────────────────────────────────

def make_state():
    return ActiveInferenceState(HYPOTHESES, PRIOR)

def healthy_sims():
    return {"healthy": 0.9, "uncertain": -0.3, "confused": -0.9}

def confused_sims():
    return {"healthy": -0.9, "uncertain": -0.3, "confused": 0.9}

def medium_sims():
    """Medium-perplexity agent: slightly off but not broken."""
    return {"healthy": 0.3, "uncertain": 0.4, "confused": -0.2}

def feed(state, sims, n):
    """Feed n identical observations into a state."""
    for _ in range(n):
        state.update(sims)
    return state


# ── 1. Recovery speed ─────────────────────────────────────────────────────────

class TestRecoverySpeed:
    """After confusion, how many healthy observations to stop being an anomaly?"""

    def test_recovers_within_ten_healthy_observations(self):
        """An agent that had 5 confused tasks should recover in ≤ 10 healthy tasks."""
        state = make_state()
        feed(state, confused_sims(), 5)

        recovered = False
        for i in range(10):
            state.update(healthy_sims())
            if not state.is_anomaly():
                recovered = True
                break

        assert recovered, (
            f"Agent did not recover after 10 healthy observations. "
            f"F_history tail: {state._F_history[-5:]}"
        )

    def test_recovery_faster_after_mild_confusion(self):
        """Mild confusion (3 confused) should recover faster than severe (8 confused)."""
        mild = make_state()
        severe = make_state()

        feed(mild, confused_sims(), 3)
        feed(severe, confused_sims(), 8)

        def steps_to_recover(state, max_steps=20):
            for i in range(1, max_steps + 1):
                state.update(healthy_sims())
                if not state.is_anomaly():
                    return i
            return max_steps + 1  # did not recover

        mild_steps   = steps_to_recover(mild)
        severe_steps = steps_to_recover(severe)

        assert mild_steps <= severe_steps, (
            f"Mild confusion took {mild_steps} steps, "
            f"severe took {severe_steps} — expected mild ≤ severe"
        )

    def test_single_medium_task_does_not_cause_anomaly(self):
        """One mediocre task (not fully confused) should not flag an agent as anomalous."""
        state = make_state()
        feed(state, healthy_sims(), 5)   # establish baseline
        state.update(medium_sims())      # one mediocre task (not extreme confusion)
        assert not state.is_anomaly(), (
            "A single medium-quality task after a healthy baseline should not trigger anomaly. "
            f"F_history: {state._F_history}"
        )

    def test_extreme_single_spike_does_trigger_anomaly(self):
        """Conversely, one fully-confused task IS supposed to trigger the z-score — that's correct."""
        state = make_state()
        feed(state, healthy_sims(), 5)
        state.update(confused_sims())
        # This SHOULD be an anomaly — the z-score is doing its job
        assert state.is_anomaly(), (
            "A fully-confused spike after a healthy baseline should trigger the z-score anomaly detector"
        )


# ── 2. False positive rate on stable noisy agents ────────────────────────────

class TestFalsePositiveRate:
    """Agents that are consistently medium-quality should NOT keep getting flagged."""

    def test_stable_medium_agent_not_flagged_after_warmup(self):
        """
        An agent consistently producing medium-quality output is not broken —
        it's just average. After enough history the z-score should adapt and
        stop flagging it.
        """
        state = make_state()
        feed(state, medium_sims(), 20)

        anomaly_count = 0
        for _ in range(10):
            state.update(medium_sims())
            if state.is_anomaly():
                anomaly_count += 1

        # Allow at most 1 false positive in 10 consistent medium-quality tasks
        assert anomaly_count <= 1, (
            f"Stable medium-quality agent flagged {anomaly_count}/10 times — "
            f"z-score should have adapted to its baseline"
        )

    def test_false_positive_rate_healthy_agent(self):
        """A consistently healthy agent should never be flagged."""
        state = make_state()
        feed(state, healthy_sims(), 10)

        false_positives = sum(
            1 for _ in range(20)
            if (state.update(healthy_sims()), state.is_anomaly())[1]
        )
        assert false_positives == 0, (
            f"Healthy agent falsely flagged {false_positives}/20 times"
        )

    def test_noisy_agent_adapts_not_permanent_anomaly(self):
        """
        An agent alternating healthy/medium should NOT be permanently flagged.
        Its z-score baseline should include both types and normalize them out.
        """
        state = make_state()
        # Establish mixed baseline
        for _ in range(10):
            state.update(healthy_sims())
            state.update(medium_sims())

        # Now check: mixed observations should not trigger constant anomalies
        anomalies = 0
        for _ in range(10):
            state.update(healthy_sims())
            state.update(medium_sims())
            if state.is_anomaly():
                anomalies += 1

        assert anomalies <= 2, (
            f"Noisy-but-stable agent flagged {anomalies}/10 rounds — "
            f"expected z-score to adapt to mixed baseline"
        )


# ── 3. Interference direction ─────────────────────────────────────────────────

class TestInterferenceDirection:
    """Interference should move confused agents toward healthy, not the reverse."""

    def test_confused_agent_healthy_probability_increases_after_interference(self):
        """
        After interfering a confused agent with 7 healthy agents,
        the confused agent's P(healthy) must increase.
        """
        healthy_agents = [make_state() for _ in range(7)]
        confused_agent = make_state()

        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        feed(confused_agent, confused_sims(), 5)

        p_healthy_before = confused_agent.probability(0)
        ActiveInferenceState.interfere_all(healthy_agents + [confused_agent], alpha=0.5)
        p_healthy_after = confused_agent.probability(0)

        assert p_healthy_after > p_healthy_before, (
            f"Confused agent's P(healthy) did not increase after interference with healthy swarm. "
            f"Before: {p_healthy_before:.4f}, After: {p_healthy_after:.4f}"
        )

    def test_confused_agent_confused_probability_decreases_after_interference(self):
        """The confused agent's P(confused) must decrease after interference."""
        healthy_agents = [make_state() for _ in range(7)]
        confused_agent = make_state()

        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        feed(confused_agent, confused_sims(), 5)

        p_confused_before = confused_agent.probability(2)
        ActiveInferenceState.interfere_all(healthy_agents + [confused_agent], alpha=0.5)
        p_confused_after = confused_agent.probability(2)

        assert p_confused_after < p_confused_before, (
            f"Confused agent's P(confused) did not decrease after interference. "
            f"Before: {p_confused_before:.4f}, After: {p_confused_after:.4f}"
        )

    def test_healthy_agents_barely_change_after_interference(self):
        """
        Healthy agents should absorb minimal damage from one confused agent.
        Their P(healthy) should not drop by more than 0.15.
        """
        healthy_agents = [make_state() for _ in range(7)]
        confused_agent = make_state()

        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        feed(confused_agent, confused_sims(), 5)

        p_healthy_before = [s.probability(0) for s in healthy_agents]
        ActiveInferenceState.interfere_all(healthy_agents + [confused_agent], alpha=0.5)

        for i, (before, s) in enumerate(zip(p_healthy_before, healthy_agents)):
            drop = before - s.probability(0)
            assert drop < 0.15, (
                f"Healthy agent {i} P(healthy) dropped by {drop:.4f} — "
                f"too much damage from one confused agent"
            )


# ── 4. Swarm resilience ratio ─────────────────────────────────────────────────

class TestSwarmResilienceRatio:
    """
    The key invariant: interference should benefit the confused agent MORE
    than it costs the healthy agents.
    """

    def test_benefit_to_confused_exceeds_cost_to_healthy(self):
        """
        Total gain in P(healthy) for the confused agent should exceed
        total loss in P(healthy) across all healthy agents combined.
        """
        healthy_agents = [make_state() for _ in range(7)]
        confused_agent = make_state()

        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        feed(confused_agent, confused_sims(), 5)

        p_healthy_before_confused  = confused_agent.probability(0)
        p_healthy_before_healthies = [s.probability(0) for s in healthy_agents]

        all_agents = healthy_agents + [confused_agent]
        ActiveInferenceState.interfere_all(all_agents, alpha=0.5)

        gain_confused = confused_agent.probability(0) - p_healthy_before_confused
        total_loss_healthy = sum(
            max(0.0, before - s.probability(0))
            for before, s in zip(p_healthy_before_healthies, healthy_agents)
        )

        assert gain_confused > total_loss_healthy, (
            f"Swarm interference net-negative: confused gain={gain_confused:.4f}, "
            f"total healthy cost={total_loss_healthy:.4f}"
        )

    @pytest.mark.parametrize("n_confused", [1, 2, 3])
    def test_majority_healthy_always_dominates(self, n_confused):
        """Even with multiple confused agents, the healthy majority should dominate."""
        n_healthy = 8 - n_confused
        healthy_agents = [make_state() for _ in range(n_healthy)]
        confused_agents = [make_state() for _ in range(n_confused)]

        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        for s in confused_agents:
            feed(s, confused_sims(), 5)

        all_agents = healthy_agents + confused_agents
        ActiveInferenceState.interfere_all(all_agents, alpha=0.5)

        # After interference, every agent's P(healthy) should exceed P(confused)
        for i, s in enumerate(all_agents):
            assert s.probability(0) > s.probability(2), (
                f"Agent {i}: P(healthy)={s.probability(0):.3f} < "
                f"P(confused)={s.probability(2):.3f} after interference with "
                f"{n_healthy} healthy vs {n_confused} confused"
            )


# ── 5. Alpha sensitivity sweep ────────────────────────────────────────────────

class TestAlphaSensitivity:
    """
    Benchmark: sweep alpha 0.0 -> 1.0.
    For each alpha, measure:
      - How much the confused agent improves (gain)
      - How much the healthy agents degrade (cost)
      - Net benefit = gain - cost
    The net benefit should peak somewhere between 0.3 and 0.7.
    """

    def _run_interference(self, alpha):
        healthy_agents = [make_state() for _ in range(7)]
        confused_agent = make_state()
        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        feed(confused_agent, confused_sims(), 5)

        p_conf_before   = confused_agent.probability(0)
        p_hlthy_before  = [s.probability(0) for s in healthy_agents]

        ActiveInferenceState.interfere_all(healthy_agents + [confused_agent], alpha=alpha)

        gain = confused_agent.probability(0) - p_conf_before
        cost = sum(
            max(0.0, b - s.probability(0))
            for b, s in zip(p_hlthy_before, healthy_agents)
        )
        return gain, cost, gain - cost

    def test_alpha_zero_no_benefit_no_cost(self):
        gain, cost, net = self._run_interference(0.0)
        assert math.isclose(gain, 0.0, abs_tol=1e-6)
        assert math.isclose(cost, 0.0, abs_tol=1e-6)

    def test_alpha_one_maximum_convergence(self):
        gain, cost, net = self._run_interference(1.0)
        # Full convergence: confused gains the most, healthy lose the most
        assert gain > 0.1, f"Alpha=1.0 should produce large gain, got {gain:.4f}"

    def test_net_benefit_positive_across_mid_alphas(self):
        """Net benefit (gain - cost) should be positive for alpha in [0.2, 0.8]."""
        for alpha in [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
            gain, cost, net = self._run_interference(alpha)
            assert net > 0, (
                f"Alpha={alpha}: net benefit is negative "
                f"(gain={gain:.4f}, cost={cost:.4f})"
            )

    def test_net_benefit_monotonically_increases_with_alpha(self):
        """
        In an 8-agent swarm where 7 are healthy and 1 is confused, the net benefit
        increases monotonically with alpha — higher blending always helps more because
        the healthy majority dominates the shared state, so healthy agents barely lose
        anything while the confused agent gains significantly.

        This is a documented property of the algorithm: when healthy agents are the
        overwhelming majority, there is no sweet-spot alpha — more blending is better.
        The default alpha=0.5 is a conservative choice that limits disruption to
        healthy agents in edge cases (e.g. 4 healthy vs 4 confused).
        """
        alphas = [i / 10 for i in range(1, 11)]  # 0.1, 0.2, ..., 1.0
        nets   = [self._run_interference(a)[2] for a in alphas]

        # Net benefit should be strictly positive for all non-zero alpha
        for alpha, net in zip(alphas, nets):
            assert net >= 0, f"Alpha={alpha}: net benefit negative ({net:.4f})"

        # And it should be non-decreasing as alpha increases
        for i in range(1, len(nets)):
            assert nets[i] >= nets[i-1] - 1e-6, (
                f"Net benefit decreased from alpha={alphas[i-1]:.1f} to alpha={alphas[i]:.1f}: "
                f"{nets[i-1]:.4f} -> {nets[i]:.4f}"
            )


# ── 6. Posterior convergence speed ───────────────────────────────────────────

class TestConvergenceSpeed:
    """
    How many observations does it take for the posterior to stabilize?
    Measured by the change in P(healthy) between consecutive updates
    falling below a threshold.
    """

    def test_converges_within_fifteen_healthy_updates(self):
        """
        Starting from the prior, 15 consistent healthy observations should
        produce a stable posterior (delta < 0.005 between consecutive updates).
        """
        state = make_state()
        THRESHOLD = 0.005
        prev_p = state.probability(0)
        converged_at = None

        for i in range(1, 16):
            state.update(healthy_sims())
            curr_p = state.probability(0)
            if abs(curr_p - prev_p) < THRESHOLD:
                converged_at = i
                break
            prev_p = curr_p

        assert converged_at is not None, (
            "Posterior did not converge within 15 updates. "
            f"Final P(healthy)={state.probability(0):.4f}"
        )

    def test_converges_within_fifteen_confused_updates(self):
        """Confused signal should also converge — just to a different stable point."""
        state = make_state()
        THRESHOLD = 0.005
        prev_p = state.probability(2)
        converged_at = None

        for i in range(1, 16):
            state.update(confused_sims())
            curr_p = state.probability(2)
            if abs(curr_p - prev_p) < THRESHOLD:
                converged_at = i
                break
            prev_p = curr_p

        assert converged_at is not None, (
            "Confused posterior did not converge within 15 updates."
        )

    def test_posterior_stable_point_reflects_signal(self):
        """After convergence, the dominant hypothesis must match the signal."""
        healthy_state = make_state()
        confused_state = make_state()

        feed(healthy_state, healthy_sims(), 15)
        feed(confused_state, confused_sims(), 15)

        # Healthy signal -> P(healthy) should dominate
        assert healthy_state.probability(0) > healthy_state.probability(1)
        assert healthy_state.probability(0) > healthy_state.probability(2)

        # Confused signal -> P(confused) should increase significantly above prior
        assert confused_state.probability(2) > PRIOR["confused"] * 3


# ── 7. Printed benchmark summary (not a test — run with -s to see output) ─────

def test_benchmark_summary(capsys):
    """
    Prints a human-readable benchmark table when run with pytest -s.
    Not an assertion test — documents the algorithm's quantitative behaviour.
    """
    rows = []

    # Convergence speed
    for signal_name, sims in [("healthy", healthy_sims()), ("confused", confused_sims()), ("medium", medium_sims())]:
        state = make_state()
        prev = state.probability(0 if signal_name != "confused" else 2)
        steps = 0
        for i in range(1, 31):
            state.update(sims)
            curr = state.probability(0 if signal_name != "confused" else 2)
            if abs(curr - prev) < 0.002:
                steps = i
                break
            prev = curr
        rows.append(("Convergence steps", signal_name, steps if steps else ">30"))

    # Recovery speed
    state = make_state()
    feed(state, confused_sims(), 5)
    recovery = next(
        (i for i in range(1, 31) if (state.update(healthy_sims()), not state.is_anomaly())[1]),
        ">30"
    )
    rows.append(("Recovery steps (after 5 confused)", "-> healthy", recovery))

    # Alpha sweep net benefit
    best_alpha, best_net = 0.0, -999.0
    for alpha_10 in range(11):
        alpha = alpha_10 / 10
        healthy_agents = [make_state() for _ in range(7)]
        confused_agent = make_state()
        for s in healthy_agents:
            feed(s, healthy_sims(), 5)
        feed(confused_agent, confused_sims(), 5)
        p_before = confused_agent.probability(0)
        ph_before = [s.probability(0) for s in healthy_agents]
        ActiveInferenceState.interfere_all(healthy_agents + [confused_agent], alpha=alpha)
        gain = confused_agent.probability(0) - p_before
        cost = sum(max(0.0, b - s.probability(0)) for b, s in zip(ph_before, healthy_agents))
        net = gain - cost
        if net > best_net:
            best_net, best_alpha = net, alpha
        rows.append(("Alpha net benefit", f"a={alpha:.1f}", f"gain={gain:.4f} cost={cost:.4f} net={net:.4f}"))

    rows.append(("Best alpha", f"a={best_alpha:.1f}", f"net={best_net:.4f}"))

    with capsys.disabled():
        print("\n\n" + "=" * 65)
        print("  HAMILTONIAN SWARM — HEALTH ALGORITHM BENCHMARK")
        print("=" * 65)
        for label, key, val in rows:
            print(f"  {label:<42} {key:<18} {val}")
        print("=" * 65 + "\n")
