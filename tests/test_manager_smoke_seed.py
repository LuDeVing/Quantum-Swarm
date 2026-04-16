"""Smoke seed layout: wx Entry + Show + OpenClaw-style UIA checklist (no LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from manager_smoke_seed import seed_minimal_gui_project, write_smoke_agent_test_hints


def test_smoke_seed_has_entry_show_and_hints(tmp_path: Path) -> None:
    code = tmp_path / "code"
    seed_minimal_gui_project(code)
    main_py = (code / "main.py").read_text(encoding="utf-8")
    # wx app — native Win32 controls
    assert "wx.TextCtrl" in main_py
    assert "wx.Button" in main_py
    assert "_on_show" in main_py
    assert "Smoke GUI" in main_py
    assert 'name="Entry"' in main_py
    assert 'name="Show"' in main_py

    write_smoke_agent_test_hints(tmp_path)
    hints = (tmp_path / "design" / "agent_test_hints.md").read_text(encoding="utf-8")
    assert "FEATURE" in hints
    assert "Show" in hints
    # Must reference the OpenClaw UIA tools (no vision needed for wx apps)
    assert "desktop_uia_list_elements" in hints
    assert "desktop_uia_click" in hints
    assert "desktop_uia_read_text" in hints
    # Must NOT instruct agent to fall back to pixel/vision for locate/verify
    assert "Snapshot" in hints or "SNAPSHOT" in hints
