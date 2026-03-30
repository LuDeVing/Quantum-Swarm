"""
test_swarm_rolling_context.py — Unit tests for RollingContext.

Tests the project memory accumulation: how agents maintain a rolling
summary of their work across rounds without blowing up context size.
"""
import pytest
from unittest.mock import patch
from software_company import RollingContext


# ── get() — initial empty state ───────────────────────────────────────────────

class TestGetEmpty:
    def test_empty_context_returns_empty_string(self):
        ctx = RollingContext()
        assert ctx.get() == ""

    def test_fresh_context_has_no_summary(self):
        ctx = RollingContext()
        assert ctx.summary == ""
        assert ctx.recent == []


# ── add() — basic appending ───────────────────────────────────────────────────

class TestAdd:
    def test_first_add_appears_in_recent(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("Build auth", "Implemented JWT tokens")
        assert len(ctx.recent) == 1

    def test_add_truncates_task_to_100_chars(self):
        ctx = RollingContext(max_recent=3)
        long_task = "X" * 200
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add(long_task, "output")
        # Entry stored as "Task: {task[:100]}. Output: {output[:250]}"
        assert ctx.recent[0].count("X") == 100

    def test_add_truncates_output_to_250_chars(self):
        ctx = RollingContext(max_recent=3)
        long_output = "Y" * 500
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("task", long_output)
        assert ctx.recent[0].count("Y") == 250

    def test_three_adds_within_max_recent(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("task1", "output1")
            ctx.add("task2", "output2")
            ctx.add("task3", "output3")
        assert len(ctx.recent) == 3


# ── add() — rollover and summarization ───────────────────────────────────────

class TestRollover:
    def test_fourth_add_triggers_llm_summarize(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="running summary") as mock_llm:
            ctx.add("t1", "o1")
            ctx.add("t2", "o2")
            ctx.add("t3", "o3")
            assert mock_llm.call_count == 0  # no summarize yet
            ctx.add("t4", "o4")
            assert mock_llm.call_count == 1  # triggered

    def test_rollover_keeps_max_recent_entries(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            for i in range(5):
                ctx.add(f"task{i}", f"output{i}")
        assert len(ctx.recent) == 3

    def test_rollover_updates_summary(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="the summary"):
            for i in range(4):
                ctx.add(f"task{i}", f"output{i}")
        assert ctx.summary == "the summary"

    def test_rollover_error_response_ignored(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="[ERROR: api failed]"):
            for i in range(4):
                ctx.add(f"task{i}", f"output{i}")
        # Summary should remain empty since response started with [ERROR
        assert ctx.summary == ""

    def test_oldest_entry_removed_on_rollover(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("first_task", "first_output")
            ctx.add("task2", "output2")
            ctx.add("task3", "output3")
            ctx.add("task4", "output4")
        # "first_task" should no longer be in recent
        combined = " ".join(ctx.recent)
        assert "first_task" not in combined


# ── get() — formatting ────────────────────────────────────────────────────────

class TestGetFormatting:
    def test_get_with_only_recent_shows_recent_work_header(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("mytask", "myoutput")
        result = ctx.get()
        assert "RECENT WORK" in result

    def test_get_with_summary_shows_project_history_header(self):
        ctx = RollingContext(max_recent=3)
        ctx.summary = "Some accumulated history"
        result = ctx.get()
        assert "PROJECT HISTORY" in result

    def test_get_ends_with_double_newline(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("task", "output")
        assert ctx.get().endswith("\n\n")

    def test_get_with_summary_and_recent_shows_both(self):
        ctx = RollingContext(max_recent=3)
        ctx.summary = "Prior history"
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("new task", "new output")
        result = ctx.get()
        assert "PROJECT HISTORY" in result
        assert "RECENT WORK" in result

    def test_recent_entries_prefixed_with_dash(self):
        ctx = RollingContext(max_recent=3)
        with patch("software_company.llm_call", return_value="summary"):
            ctx.add("task", "output")
        result = ctx.get()
        assert "- Task:" in result

    def test_max_recent_one_triggers_summarize_on_second_add(self):
        ctx = RollingContext(max_recent=1)
        with patch("software_company.llm_call", return_value="quick summary") as mock_llm:
            ctx.add("task1", "output1")
            assert mock_llm.call_count == 0
            ctx.add("task2", "output2")
            assert mock_llm.call_count == 1
        assert len(ctx.recent) == 1
