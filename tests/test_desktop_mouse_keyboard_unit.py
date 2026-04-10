"""Smoke tests for desktop_mouse / desktop_keyboard (pyautogui mocked; no real input)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_pyautogui(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    m = MagicMock()
    m.position.return_value = (0, 0)
    m.size.return_value = (1920, 1080)
    monkeypatch.setitem(sys.modules, "pyautogui", m)
    return m


def test_desktop_keyboard_type_writes_text(mock_pyautogui: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_keyboard

    out = desktop_keyboard("type", text="hello")
    assert not out.lstrip().upper().startswith("ERROR")
    mock_pyautogui.write.assert_called_once()
    assert mock_pyautogui.write.call_args[0][0] == "hello"


def test_desktop_keyboard_hotkey(mock_pyautogui: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_keyboard

    out = desktop_keyboard("hotkey", keys="ctrl,c")
    assert not out.lstrip().upper().startswith("ERROR")
    mock_pyautogui.hotkey.assert_called_once_with("ctrl", "c")


def test_desktop_mouse_click(mock_pyautogui: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_mouse

    out = desktop_mouse("click", x=100, y=200)
    assert not out.lstrip().upper().startswith("ERROR")
    mock_pyautogui.click.assert_called_once_with(100, 200, button="left")
