"""
Tests for Engineering Manager desktop verification helpers.

These mirror how ``agent_loop`` logs tool invocations (``[TOOL: name|ok|fail]``)
and what ``_manager_fix_loop`` requires for ``app_type == "gui"``: at least one
successful ``desktop_mouse`` or ``desktop_keyboard`` call (screenshots alone do not count).

No real desktop, LLM, or full ``run_engineering_team`` run — pure logic only.
"""

from __future__ import annotations

import pytest

import software_company as sc


class TestManagerSawDesktopInteraction:
    """``_manager_saw_desktop_interaction`` — mouse/keyboard success lines only."""

    @pytest.mark.parametrize(
        "lines,expected",
        [
            # Success: exact prefixes used by engineering._manager_saw_desktop_interaction
            ([], False),
            (["[TOOL: desktop_screenshot|ok] {}"], False),
            (["[TOOL: desktop_mouse|ok] {}"], True),
            (["[TOOL: desktop_keyboard|ok] {}"], True),
            (
                [
                    "[TOOL: desktop_screenshot|ok] {}",
                    "[TOOL: desktop_mouse|ok] {'action': 'click'}",
                ],
                True,
            ),
            (
                [
                    "[TOOL: desktop_suggest_click|ok] {'target': 'Submit'}",
                    "[TOOL: desktop_keyboard|ok] {'action': 'type', 'text': 'x'}",
                ],
                True,
            ),
            # suggest_click success does not replace mouse/keyboard for the gate
            (
                [
                    "[TOOL: desktop_screenshot|ok] {}",
                    "[TOOL: desktop_suggest_click|ok] {'target': 'OK'}",
                ],
                False,
            ),
            # Failed desktop calls do not count
            (["[TOOL: desktop_mouse|fail] {}"], False),
            (["[TOOL: desktop_keyboard|fail] {}"], False),
            # Wrong prefix / partial match
            (["desktop_mouse ok"], False),
            (["[TOOL: desktop_mouse] {}"], False),
        ],
    )
    def test_manager_saw_desktop_interaction(self, lines: list[str], expected: bool) -> None:
        assert sc._manager_saw_desktop_interaction(lines) is expected


class TestCountDesktopScreenshots:
    """``_count_desktop_screenshots`` — successful screenshots only."""

    @pytest.mark.parametrize(
        "lines,expected_count",
        [
            ([], 0),
            (["[TOOL: list_files] {}"], 0),
            (["[TOOL: desktop_screenshot|ok] {}"], 1),
            (
                [
                    "[TOOL: desktop_screenshot|ok] {}",
                    "[TOOL: desktop_screenshot|ok] {}",
                    "[TOOL: desktop_screenshot|fail] {}",
                ],
                2,
            ),
        ],
    )
    def test_count(self, lines: list[str], expected_count: int) -> None:
        assert sc._count_desktop_screenshots(lines) == expected_count


class TestManagerSawStartService:
    """``_manager_saw_start_service`` — tracks long-running app boot."""

    def test_yes_when_start_service_logged(self) -> None:
        assert sc._manager_saw_start_service(
            ["[TOOL: start_service] {'name': 'api'}", "[TOOL: read_file] {}"]
        )

    def test_no_without_start_service(self) -> None:
        assert not sc._manager_saw_start_service(["[TOOL: run_shell] {}"])


class TestManagerSawHttpRequest:
    """``_manager_saw_http_request`` — web apps must hit the running server."""

    def test_yes(self) -> None:
        assert sc._manager_saw_http_request(
            ["[TOOL: http_request] {'method': 'GET', 'url': 'http://127.0.0.1:8000/'}"]
        )

    def test_no(self) -> None:
        assert not sc._manager_saw_http_request(["[TOOL: start_service] {}"])
