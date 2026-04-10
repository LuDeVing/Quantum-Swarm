"""
test_swarm_pure_functions.py — Zero-mock tests for pure math/logic functions.

Tests:
  - perplexity_to_similarities
  - extract_stance_probs
  - consistency_weight
  - interfere_weighted
  - token_summary cost calculation
"""
import math
import numpy as np
import pytest
import software_company as sc
import software_company.llm_client as _llm_counters


# ── perplexity_to_similarities ────────────────────────────────────────────────

class TestPerplexityToSimilarities:
    def test_returns_three_keys(self):
        result = sc.perplexity_to_similarities(2.0)
        assert set(result.keys()) == {"healthy", "uncertain", "confused"}

    def test_low_perplexity_yields_healthy(self):
        # perplexity=1.5 → very confident → healthy should be highest
        result = sc.perplexity_to_similarities(1.5)
        assert result["healthy"] > result["uncertain"]
        assert result["healthy"] > result["confused"]

    def test_high_perplexity_yields_confused(self):
        # perplexity=30.0 → max confusion → confused should be highest
        result = sc.perplexity_to_similarities(30.0)
        assert result["confused"] >= result["healthy"]

    def test_perplexity_one_zero_edge(self):
        # log(max(1.0, 1.0)) = 0 → confusion=0
        # healthy  = 1 - 2*0 = 1.0
        # uncertain = 1 - 2*|0 - 0.5| = 1 - 1 = 0.0
        # confused  = clamp(2*0 - 1) = 0.0
        result = sc.perplexity_to_similarities(1.0)
        assert math.isclose(result["healthy"],   1.0, abs_tol=1e-9)
        assert math.isclose(result["uncertain"], 0.0, abs_tol=1e-9)
        assert math.isclose(result["confused"],  0.0, abs_tol=1e-9)

    def test_perplexity_below_one_clamped_to_one(self):
        # max(perplexity, 1.0) clamps to 1.0
        result_below = sc.perplexity_to_similarities(0.1)
        result_one   = sc.perplexity_to_similarities(1.0)
        assert result_below == result_one

    def test_perplexity_30_confusion_is_one(self):
        result = sc.perplexity_to_similarities(30.0)
        # confusion = log(30)/log(30) = 1.0 → confused = 2*1-1 = 1.0
        assert math.isclose(result["confused"], 1.0, abs_tol=1e-9)

    def test_perplexity_100_clamped_at_30(self):
        # min(..., 1.0) clamps confusion to 1.0 regardless of perplexity > 30
        result_30  = sc.perplexity_to_similarities(30.0)
        result_100 = sc.perplexity_to_similarities(100.0)
        assert result_30 == result_100

    def test_midpoint_perplexity_uncertain_peaks(self):
        # At confusion=0.5, uncertain = 1 - 2*|0.5 - 0.5| = 1.0
        # confusion = 0.5 when log(p)/log(30) = 0.5 → p = 30^0.5 ≈ 5.477
        p = 30 ** 0.5
        result = sc.perplexity_to_similarities(p)
        assert math.isclose(result["uncertain"], 1.0, abs_tol=1e-9)


# ── extract_stance_probs ──────────────────────────────────────────────────────

class TestExtractStanceProbs:
    def test_returns_array_length_four(self):
        probs = sc.extract_stance_probs("some output")
        assert len(probs) == 4

    def test_sums_to_one(self):
        probs = sc.extract_stance_probs("simple minimal basic")
        assert math.isclose(probs.sum(), 1.0, abs_tol=1e-9)

    def test_empty_string_uniform_with_pseudocounts(self):
        # All 0 keyword counts + 0.5 pseudocount → equal probability
        probs = sc.extract_stance_probs("")
        assert math.isclose(probs[0], probs[1], abs_tol=1e-9)
        assert math.isclose(probs[1], probs[2], abs_tol=1e-9)

    def test_minimal_keywords_boost_minimal_stance(self):
        text = "simple minimal basic lean lightweight easy small straightforward"
        probs = sc.extract_stance_probs(text)
        # Index 0 = minimal
        assert probs[0] == probs.max()

    def test_robust_keywords_boost_robust_stance(self):
        text = "robust reliable error handling fallback resilient defensive retry fault"
        probs = sc.extract_stance_probs(text)
        # Index 1 = robust
        assert probs[1] == probs.max()

    def test_scalable_keywords_boost_scalable_stance(self):
        text = "scalable extensible modular distributed horizontal growth microservice queue"
        probs = sc.extract_stance_probs(text)
        # Index 2 = scalable
        assert probs[2] == probs.max()

    def test_pragmatic_keywords_boost_pragmatic_stance(self):
        text = "pragmatic practical tradeoff balance reasonable sufficient good enough ship"
        probs = sc.extract_stance_probs(text)
        # Index 3 = pragmatic
        assert probs[3] == probs.max()

    def test_case_insensitive(self):
        lower = sc.extract_stance_probs("simple")
        upper = sc.extract_stance_probs("SIMPLE")
        np.testing.assert_array_almost_equal(lower, upper)

    def test_all_probs_between_zero_and_one(self):
        probs = sc.extract_stance_probs("robust scalable minimal pragmatic")
        assert all(0.0 <= p <= 1.0 for p in probs)


# ── consistency_weight ────────────────────────────────────────────────────────

class TestConsistencyWeight:
    def test_empty_string_returns_zero_ish(self):
        # length=0, no logic/tech words → 0.4*0 + 0.3*0 + 0.3*0 = 0
        w = sc.consistency_weight("")
        assert math.isclose(w, 0.0, abs_tol=1e-9)

    def test_return_value_between_zero_and_one(self):
        w = sc.consistency_weight("some text")
        assert 0.0 <= w <= 1.0

    def test_long_output_maxes_length_score(self):
        # 2000+ chars → length_score = 1.0
        long_text = "a " * 1100  # > 2000 chars
        w_long  = sc.consistency_weight(long_text)
        w_short = sc.consistency_weight("a")
        assert w_long > w_short

    def test_logic_words_increase_weight(self):
        base = sc.consistency_weight("text " * 100)
        with_logic = sc.consistency_weight(
            "text " * 100 + " because therefore however thus since"
        )
        assert with_logic > base

    def test_tech_words_increase_weight(self):
        base = sc.consistency_weight("text " * 100)
        with_tech = sc.consistency_weight(
            "text " * 100 + " function class endpoint schema service"
        )
        assert with_tech > base

    def test_weight_formula_coefficients(self):
        # Construct a string with max scores in all three components
        long_text  = "a " * 1100                    # length_score = 1.0
        logic_text = " because therefore however thus since " * 5  # ≥5 hits
        tech_text  = " function class endpoint schema service interface module database api test " * 3
        full = long_text + logic_text + tech_text
        w = sc.consistency_weight(full)
        # Should be close to 0.4*1 + 0.3*1 + 0.3*1 = 1.0
        assert w > 0.9


# ── interfere_weighted ────────────────────────────────────────────────────────

class TestInterfereWeighted:
    def _uniform_belief(self):
        return np.array([1/3, 1/3, 1/3])

    def test_alpha_zero_returns_original_beliefs(self):
        beliefs = [np.array([0.7, 0.2, 0.1]), np.array([0.1, 0.8, 0.1])]
        weights = [0.5, 0.5]
        result  = sc.interfere_weighted(beliefs, weights, alpha=0.0)
        np.testing.assert_array_almost_equal(result[0], beliefs[0])
        np.testing.assert_array_almost_equal(result[1], beliefs[1])

    def test_alpha_one_all_agents_converge(self):
        beliefs = [np.array([0.9, 0.05, 0.05]), np.array([0.05, 0.05, 0.9])]
        weights = [0.5, 0.5]
        result  = sc.interfere_weighted(beliefs, weights, alpha=1.0)
        np.testing.assert_array_almost_equal(result[0], result[1], decimal=5)

    def test_output_sums_to_one(self):
        beliefs = [np.array([0.6, 0.3, 0.1]), np.array([0.2, 0.5, 0.3])]
        weights = [0.4, 0.6]
        result  = sc.interfere_weighted(beliefs, weights, alpha=0.5)
        for r in result:
            assert math.isclose(r.sum(), 1.0, abs_tol=1e-9)

    def test_all_values_non_negative(self):
        beliefs = [np.array([0.8, 0.1, 0.1]), np.array([0.1, 0.1, 0.8])]
        result  = sc.interfere_weighted(beliefs, [0.5, 0.5], alpha=0.5)
        for r in result:
            assert all(v >= 0 for v in r)

    def test_identical_beliefs_unchanged(self):
        b = np.array([0.7, 0.2, 0.1])
        beliefs = [b.copy(), b.copy(), b.copy()]
        result  = sc.interfere_weighted(beliefs, [1/3]*3, alpha=0.5)
        for r in result:
            np.testing.assert_array_almost_equal(r, b)

    def test_unequal_weights_bias_toward_heavier(self):
        # Agent 0: confident healthy. Agent 1: confused. Weight 0 >> weight 1.
        beliefs = [np.array([0.9, 0.05, 0.05]), np.array([0.05, 0.05, 0.9])]
        weights = [0.9, 0.1]
        result  = sc.interfere_weighted(beliefs, weights, alpha=1.0)
        # Both should be biased toward agent 0 (healthy)
        assert result[0][0] > result[0][2]
        assert result[1][0] > result[1][2]

    def test_three_agents(self):
        beliefs = [
            np.array([0.8, 0.1, 0.1]),
            np.array([0.1, 0.8, 0.1]),
            np.array([0.1, 0.1, 0.8]),
        ]
        result = sc.interfere_weighted(beliefs, [1/3]*3, alpha=0.5)
        assert len(result) == 3
        for r in result:
            assert math.isclose(r.sum(), 1.0, abs_tol=1e-9)


# ── token_summary cost calculation ────────────────────────────────────────────

class TestTokenSummary:
    def _reset_counters(self):
        _llm_counters._tokens_in = 0
        _llm_counters._tokens_out = 0
        _llm_counters._call_count = 0

    def test_zero_tokens_zero_cost(self):
        self._reset_counters()
        summary = sc.token_summary()
        assert "~$0.0000" in summary

    def test_known_cost_calculation(self):
        # 1M input tokens at $0.25/1M (see token_summary in implementation)
        self._reset_counters()
        _llm_counters._tokens_in = 1_000_000
        _llm_counters._tokens_out = 0
        summary = sc.token_summary()
        assert "~$0.2500" in summary

    def test_output_tokens_cost_more(self):
        # 1M output at $1.50/1M
        self._reset_counters()
        _llm_counters._tokens_in = 0
        _llm_counters._tokens_out = 1_000_000
        summary = sc.token_summary()
        assert "~$1.5000" in summary

    def test_summary_includes_call_count(self):
        self._reset_counters()
        _llm_counters._call_count = 42
        summary = sc.token_summary()
        assert "calls=42" in summary

    def test_summary_includes_totals(self):
        self._reset_counters()
        _llm_counters._tokens_in = 500
        _llm_counters._tokens_out = 300
        summary = sc.token_summary()
        assert "in=500" in summary
        assert "out=300" in summary
        assert "total=800" in summary

    def teardown_method(self):
        _llm_counters._tokens_in = 0
        _llm_counters._tokens_out = 0
        _llm_counters._call_count = 0
