"""Tests for desktop_skill bundle and desktop_list_windows / desktop_activate_window."""

from __future__ import annotations

import sys
import types

import pytest

from software_company.desktop_skill import (
    DESKTOP_AUTOMATION_TOOL_NAMES,
    DESKTOP_TOOLS_OK_FAIL,
    merge_role_tools_with_desktop,
)


def test_desktop_automation_tool_names_order() -> None:
    assert DESKTOP_AUTOMATION_TOOL_NAMES[:2] == (
        "desktop_list_windows",
        "desktop_activate_window",
    )
    assert DESKTOP_AUTOMATION_TOOL_NAMES[2:5] == (
        "desktop_uia_list_elements",
        "desktop_uia_read_text",
        "desktop_uia_click",
    )
    assert "desktop_screenshot" in DESKTOP_AUTOMATION_TOOL_NAMES
    assert DESKTOP_TOOLS_OK_FAIL == frozenset(DESKTOP_AUTOMATION_TOOL_NAMES)


def test_merge_role_tools_with_desktop_dedupes_and_order() -> None:
    base = ["read_file", "desktop_mouse", "list_files"]
    out = merge_role_tools_with_desktop(base)
    assert out[0] == "read_file"
    assert out[1] == "desktop_mouse"  # kept from base, not duplicated from bundle
    assert out.count("desktop_mouse") == 1
    # Bundle appends missing desktop tools in canonical order
    for name in DESKTOP_AUTOMATION_TOOL_NAMES:
        assert name in out
    assert out.index("read_file") < out.index("desktop_list_windows")


def test_merge_empty_base() -> None:
    assert merge_role_tools_with_desktop([]) == list(DESKTOP_AUTOMATION_TOOL_NAMES)


def test_software_company_reexports_desktop_skill() -> None:
    import software_company as sc

    assert hasattr(sc, "merge_role_tools_with_desktop")
    assert sc.DESKTOP_AUTOMATION_TOOL_NAMES == DESKTOP_AUTOMATION_TOOL_NAMES


@pytest.fixture
def fake_pygetwindow(monkeypatch: pytest.MonkeyPatch):
    """Inject a minimal pygetwindow-like module."""

    class Win:
        __slots__ = ("title", "left", "top", "width", "height", "_activated", "_minimized")

        def __init__(
            self,
            title: str,
            left: int = 0,
            top: int = 0,
            width: int = 100,
            height: int = 80,
            minimized: bool = False,
        ):
            self.title = title
            self.left = left
            self.top = top
            self.width = width
            self.height = height
            self._activated = False
            self._minimized = minimized

        @property
        def isMinimized(self) -> bool:
            return self._minimized

        def restore(self) -> None:
            self._minimized = False

        def activate(self) -> None:
            self._activated = True

    wins = [
        Win(""),
        Win("Calculator", minimized=True),
        Win("My Test App — v1", 10, 20, 640, 480),
    ]

    mod = types.ModuleType("pygetwindow")

    def get_all():
        return list(wins)

    mod.getAllWindows = get_all  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pygetwindow", mod)
    return wins


def test_desktop_list_windows_success(fake_pygetwindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_list_windows

    text = desktop_list_windows(limit=10)
    assert not text.upper().startswith("ERROR")
    assert "Calculator" in text
    assert "[minimized]" in text
    assert "My Test App" in text
    assert "rect=" in text


def test_desktop_activate_window_success(fake_pygetwindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_activate_window

    out = desktop_activate_window("test app")
    assert not out.upper().startswith("ERROR")
    assert "My Test App" in out
    assert fake_pygetwindow[2]._activated is True


def test_desktop_activate_window_restores_minimized_first(
    fake_pygetwindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_activate_window

    out = desktop_activate_window("Calculator")
    assert not out.upper().startswith("ERROR")
    assert fake_pygetwindow[1]._minimized is False
    assert fake_pygetwindow[1]._activated is True


def test_desktop_activate_window_no_match(fake_pygetwindow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    from software_company.tool_registry import desktop_activate_window

    out = desktop_activate_window("xyznonexistent")
    assert out.upper().startswith("ERROR")


def test_desktop_list_windows_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", True)
    monkeypatch.setitem(sys.modules, "pygetwindow", None)
    from software_company.tool_registry import desktop_list_windows

    out = desktop_list_windows()
    assert "ERROR" in out.upper()
    assert "PyGetWindow" in out or "pygetwindow" in out.lower()
