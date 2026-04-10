"""desktop_live_snapshot: role gating and message shape (no real screen)."""

from __future__ import annotations

import pytest


def test_build_message_plain_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "software_company.desktop_live_snapshot.is_enabled_for_role", lambda _rk: False
    )
    from software_company.desktop_live_snapshot import build_user_message_with_live_screen

    out = build_user_message_with_live_screen("hello", "eng_manager")
    assert out == "hello"


def test_roles_allow_eng_manager_default_config() -> None:
    from software_company.desktop_live_snapshot import is_enabled_for_role

    # Default install: interval 0 → never attach
    assert is_enabled_for_role("eng_manager") is False


def test_is_enabled_when_interval_and_desktop_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("software_company.desktop_live_snapshot.AGENT_DESKTOP_CONTROL_ENABLED", True)
    monkeypatch.setattr(
        "software_company.desktop_live_snapshot.DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC", 1.0
    )
    monkeypatch.setattr(
        "software_company.desktop_live_snapshot.DESKTOP_LIVE_SNAPSHOT_ROLES", "eng_manager"
    )
    from software_company.desktop_live_snapshot import is_enabled_for_role

    assert is_enabled_for_role("eng_manager") is True
    assert is_enabled_for_role("dev_1") is False
