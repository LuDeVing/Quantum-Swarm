"""
Tests for the **final engineering stage**: the Manager Fix loop (`_manager_fix_loop`).

These tests isolate manager verification (tests/build gate + mandatory tool proof:
``start_service``, GUI desktop tools, ``http_request`` for web) without running
``run_engineering_team``, real LLM calls, or the async dev task queue.

All heavy dependencies are mocked: test gate, build command, ``_run_with_tools``,
git worktrees, and RAG updates.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from software_company.contracts import get_contracts, reset_contracts
from software_company.engineering import (
    ManagerFixResult,
    _manager_fix_collect_errors,
    _manager_fix_loop,
)


def _fresh_registry(app_type: str) -> None:
    reset_contracts()
    reg = get_contracts()
    reg.app_type = app_type
    reg.build_command = ""
    reg.primary_language = "python"
    reg.file_map = {}


def _dummy_task_queue() -> MagicMock:
    q = MagicMock()
    q.get_status.return_value = "(test queue: idle)"
    return q


def _gui_verified_tool_lines() -> list[str]:
    """OpenClaw-style triplet: screenshot → uia_click → uia_read_text (fast, no extra screenshot)."""
    return [
        "[TOOL: start_service] {'name': 'app', 'command': 'python main.py'}",
        "[TOOL: desktop_screenshot|ok] {}",
        "[TOOL: desktop_uia_list_elements|ok] {'title_substring': 'Smoke GUI'}",
        "[TOOL: desktop_uia_click|ok] {'title_substring': 'Smoke GUI', 'name_substring': 'Show'}",
        "[TOOL: desktop_uia_read_text|ok] {'title_substring': 'Smoke GUI'}",
    ]


def _gui_verified_keyboard_tool_lines() -> list[str]:
    """Keyboard triplet: screenshot → keyboard → screenshot (UIA read may not see typed text)."""
    return [
        "[TOOL: start_service] {'name': 'app', 'command': 'python main.py'}",
        "[TOOL: desktop_screenshot|ok] {}",
        "[TOOL: desktop_keyboard|ok] {'action': 'type', 'text': 'smoke'}",
        "[TOOL: desktop_screenshot|ok] {}",
    ]


def _gui_verified_uia_click_tool_lines() -> list[str]:
    """OpenClaw-style UIA triplet: screenshot → uia_click → uia_read_text (Windows UIA path)."""
    return [
        "[TOOL: start_service] {'name': 'app', 'command': 'python main.py'}",
        "[TOOL: desktop_screenshot|ok] {}",
        "[TOOL: desktop_uia_list_elements|ok] {'title_substring': 'App'}",
        "[TOOL: desktop_uia_click|ok] {'title_substring': 'App', 'name_substring': 'OK'}",
        "[TOOL: desktop_uia_read_text|ok] {'title_substring': 'App'}",
    ]


def _gui_suggest_click_only_lines() -> list[str]:
    """Suggest-click alone does not satisfy the mandatory mouse/keyboard proof."""
    return [
        "[TOOL: start_service] {}",
        "[TOOL: desktop_screenshot|ok] {}",
        "[TOOL: desktop_screenshot|ok] {}",
        "[TOOL: desktop_suggest_click|ok] {'target': 'OK'}",
    ]


def _gui_headless_only_start_service_lines() -> list[str]:
    """MANAGER_GUI_DESKTOP_PROOF=0: start_service + green gate, no desktop_*."""
    return [
        "[TOOL: start_service] {'name': 'gui-app', 'command': 'python main.py'}",
    ]


def _web_verified_tool_lines() -> list[str]:
    return [
        "[TOOL: start_service] {'name': 'api', 'command': 'uvicorn main:app'}",
        "[TOOL: http_request] {'method': 'GET', 'url': 'http://127.0.0.1:8000/health'}",
    ]


@pytest.fixture
def code_dir(tmp_path: Path) -> Path:
    d = tmp_path / "code"
    d.mkdir(parents=True, exist_ok=True)
    (d / "main.py").write_text("# stub\n", encoding="utf-8")
    return d


@pytest.fixture
def patch_manager_deps():
    """No git I/O, no RAG scan; manager agent returns scripted tool lines once."""
    wt_inst = MagicMock()
    wt_cls = MagicMock(return_value=wt_inst)
    rag = MagicMock()

    with (
        patch("software_company.engineering.GitWorktreeManager", wt_cls),
        patch("software_company.engineering.get_rag", return_value=rag),
        patch("software_company.engineering._load_agent_test_hints", return_value=""),
    ):
        yield {"wt_cls": wt_cls, "rag": rag}


class TestManagerFixLoopFinalStage:
    """End-to-end behaviour of `_manager_fix_loop` with mocks."""

    def test_gui_passes_after_one_manager_round_with_required_tools(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("gui")

        def run_tools(*_a, **_kw):
            return ("Manager verified GUI.", _gui_verified_tool_lines(), None)

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch("software_company.engineering._run_with_tools_pkg", side_effect=run_tools),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=4,
            )

        assert isinstance(result, ManagerFixResult)
        assert result.passed is True
        assert result.app_run_verified is True
        assert result.rounds_used == 1

    def test_gui_passes_with_desktop_uia_click_instead_of_mouse(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("gui")

        def run_tools(*_a, **_kw):
            return ("Manager verified GUI via UIA.", _gui_verified_uia_click_tool_lines(), None)

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch("software_company.engineering._run_with_tools_pkg", side_effect=run_tools),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=4,
            )

        assert result.passed is True
        assert result.app_run_verified is True
        assert result.rounds_used == 1

    def test_gui_passes_with_desktop_keyboard_typing_instead_of_mouse(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("gui")

        def run_tools(*_a, **_kw):
            return ("Typed in focused field.", _gui_verified_keyboard_tool_lines(), None)

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch("software_company.engineering._run_with_tools_pkg", side_effect=run_tools),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=4,
            )

        assert result.passed is True
        assert result.app_run_verified is True

    def test_gui_headless_passes_with_start_service_only_no_desktop_tools(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("gui")

        def run_tools(*_a, **_kw):
            return ("Headless GUI ok.", _gui_headless_only_start_service_lines(), None)

        with (
            patch("software_company.engineering.MANAGER_GUI_DESKTOP_PROOF", False),
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch("software_company.engineering._run_with_tools_pkg", side_effect=run_tools),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=4,
            )

        assert result.passed is True
        assert result.app_run_verified is True

    def test_gui_fails_when_only_desktop_suggest_click_no_mouse_or_keyboard(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("gui")

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch(
                "software_company.engineering._run_with_tools_pkg",
                return_value=("suggested coords only", _gui_suggest_click_only_lines(), None),
            ),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=2,
            )

        assert result.passed is False
        _out = result.final_output.lower()
        assert (
            "desktop_mouse" in _out
            or "desktop_keyboard" in _out
            or "desktop_uia_click" in _out
        )

    def test_gui_fails_without_desktop_interaction_even_if_tests_green(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("gui")

        # start_service + screenshots only — no desktop_mouse / desktop_keyboard success
        weak_lines = [
            "[TOOL: start_service] {}",
            "[TOOL: desktop_screenshot|ok] {}",
            "[TOOL: desktop_screenshot|ok] {}",
        ]

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch(
                "software_company.engineering._run_with_tools_pkg",
                return_value=("ok", weak_lines, None),
            ),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=2,
            )

        assert result.passed is False
        assert result.app_run_verified is True
        _out = result.final_output.lower()
        assert (
            "desktop_mouse" in _out
            or "desktop_keyboard" in _out
            or "desktop_uia_click" in _out
        )

    def test_web_fails_without_http_request(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("web")

        web_no_http = [
            "[TOOL: start_service] {'name': 'api'}",
        ]

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch(
                "software_company.engineering._run_with_tools_pkg",
                return_value=("ok", web_no_http, None),
            ),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=2,
            )

        assert result.passed is False
        assert "http_request" in result.final_output.lower()

    def test_web_passes_with_start_service_and_http(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("web")

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch(
                "software_company.engineering._run_with_tools_pkg",
                return_value=("ok", _web_verified_tool_lines(), None),
            ),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=4,
            )

        assert result.passed is True
        assert result.app_run_verified is True

    def test_cli_fails_without_start_service(
        self, code_dir: Path, patch_manager_deps: dict
    ) -> None:
        _fresh_registry("cli")

        with (
            patch(
                "software_company.engineering._manager_fix_collect_errors",
                return_value=[],
            ),
            patch(
                "software_company.engineering._run_with_tools_pkg",
                return_value=("ok", ["[TOOL: run_shell] {}"], None),
            ),
        ):
            result = _manager_fix_loop(
                code_dir,
                _dummy_task_queue(),
                {},
                max_rounds=2,
            )

        assert result.passed is False
        assert "start_service" in result.final_output.lower()


class TestManagerFixCollectErrors:
    """`_manager_fix_collect_errors` aggregates test gate + build output."""

    def test_empty_when_gate_passes_and_build_clean(self, tmp_path: Path) -> None:
        _fresh_registry("library")
        reg = get_contracts()
        reg.build_command = ""

        gate = MagicMock()
        gate.skipped = False
        gate.passed = True
        gate.command = "pytest -q"
        gate.output = ""

        with (
            patch("software_company.engineering._run_test_gate", return_value=gate),
            patch("software_company.engineering._run_build_command", return_value=""),
        ):
            errors = _manager_fix_collect_errors(tmp_path, reg)

        assert errors == []

    def test_includes_test_failure_and_build_message(self, tmp_path: Path) -> None:
        _fresh_registry("library")
        reg = get_contracts()
        reg.build_command = "echo fail"

        gate = MagicMock()
        gate.skipped = False
        gate.passed = False
        gate.command = "pytest -q"
        gate.output = "AssertionError: bad"

        with (
            patch("software_company.engineering._run_test_gate", return_value=gate),
            patch(
                "software_company.engineering._run_build_command",
                return_value="BUILD STDERR: missing wheel\n",
            ),
        ):
            errors = _manager_fix_collect_errors(tmp_path, reg)

        assert len(errors) == 2
        assert "AssertionError" in errors[0]
        assert "BUILD" in errors[1] or "wheel" in errors[1]
