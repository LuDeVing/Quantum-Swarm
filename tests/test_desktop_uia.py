"""Unit tests for Windows UIA desktop helpers (mocked tree; no real UI Automation)."""

from __future__ import annotations

import types
from typing import List

import pytest

import software_company.desktop_uia as desktop_uia


def _fake_uia_module() -> tuple[types.SimpleNamespace, object, List[object]]:
    """Minimal control tree: Desktop → Window → Pane → two buttons."""

    class R:
        __slots__ = ("left", "top", "right", "bottom")

        def __init__(self, l: int = 0, t: int = 0, r: int = 100, b: int = 40) -> None:
            self.left, self.top, self.right, self.bottom = l, t, r, b

    class FC:
        __slots__ = ("ControlTypeName", "Name", "AutomationId", "BoundingRectangle", "_ch", "clicked")

        def __init__(
            self,
            ctype: str,
            name: str,
            children: List["FC"] | None = None,
            aid: str = "",
        ) -> None:
            self.ControlTypeName = ctype
            self.Name = name
            self.AutomationId = aid
            self.BoundingRectangle = R(10, 10, 110, 50)
            self._ch = list(children or [])
            self.clicked = False

        def GetChildren(self) -> List["FC"]:
            return self._ch

        def Click(self, simulateMove: bool = True, waitTime: float = 0.5) -> None:
            self.clicked = True

    btn_a = FC("ButtonControl", "OK")
    btn_b = FC("ButtonControl", "Also OK")
    pane = FC("PaneControl", "", [btn_a, btn_b])
    win = FC("WindowControl", "My Unit Test App", [pane])
    root = FC("PaneControl", "Desktop 1", [win])
    mod = types.SimpleNamespace()
    mod.GetRootControl = lambda: root
    return mod, win, [btn_a, btn_b]


@pytest.fixture
def win32_uia(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(desktop_uia.sys, "platform", "win32")
    fake_mod, win, buttons = _fake_uia_module()
    monkeypatch.setattr(desktop_uia, "_import_uia", lambda: fake_mod)
    return {"win": win, "buttons": buttons}


def test_list_elements_returns_table(win32_uia: dict) -> None:
    out = desktop_uia.list_elements("Unit Test")
    assert "UIA elements" in out
    assert "ButtonControl" in out
    assert "OK" in out
    assert "Also OK" in out


def test_list_elements_name_filter(win32_uia: dict) -> None:
    out = desktop_uia.list_elements("Unit Test", name_filter="Also")
    assert "Also OK" in out
    assert out.count("ButtonControl") == 1


def test_read_text_flattens_names(win32_uia: dict) -> None:
    out = desktop_uia.read_text("Unit Test", max_chars=5000)
    assert "My Unit Test App" in out
    assert "OK" in out


def test_click_named_success(win32_uia: dict) -> None:
    out = desktop_uia.click_named("Unit Test", "Submit", control_type="", dpi_prep=None)
    assert "ERROR: no interactive" in out

    out2 = desktop_uia.click_named("Unit Test", "Also", dpi_prep=None)
    assert "Clicked" in out2
    assert win32_uia["buttons"][1].clicked is True


def test_click_named_ambiguous(win32_uia: dict) -> None:
    out = desktop_uia.click_named("Unit Test", "OK", dpi_prep=None)
    assert "ERROR: multiple controls match" in out


def test_non_windows_returns_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop_uia.sys, "platform", "linux")
    assert desktop_uia.list_elements("x").startswith("ERROR:")
    assert desktop_uia.read_text("x").startswith("ERROR:")
    assert desktop_uia.click_named("a", "b").startswith("ERROR:")


def test_import_uia_none_shows_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop_uia.sys, "platform", "win32")
    monkeypatch.setattr(desktop_uia, "_import_uia", lambda: None)
    assert "uiautomation" in desktop_uia.list_elements("w").lower()


def test_manager_saw_desktop_interaction_counts_uia() -> None:
    import software_company as sc

    assert sc._manager_saw_desktop_interaction(
        ["[TOOL: desktop_uia_click|ok] {}", "[TOOL: desktop_screenshot|ok] {}"]
    )


def test_tool_registry_uia_respects_desktop_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.tool_registry.AGENT_DESKTOP_CONTROL_ENABLED", False)
    from software_company.tool_registry import desktop_uia_list_elements

    assert "disabled" in desktop_uia_list_elements("t").lower()
