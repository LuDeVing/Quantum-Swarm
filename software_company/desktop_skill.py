"""Reusable desktop automation skill — tool name bundle and merge helper.

All desktop tools share ``AGENT_DESKTOP_CONTROL_ENABLED`` and optional deps
(``pyautogui``, ``PyGetWindow``) as implemented in ``tool_registry``.

On Windows, ``tool_registry`` enables per-monitor DPI awareness once per process
(unless ``DESKTOP_DISABLE_DPI_AWARE=1``) and maps vision click coordinates from
screenshot pixel size to ``pyautogui.size()`` when they differ (scaled displays).

To give any role desktop automation without copying tool name lists::

    from software_company.desktop_skill import merge_role_tools_with_desktop

    _ROLE_TOOL_NAMES["my_role"] = merge_role_tools_with_desktop(
        ["read_file", "list_files", ...]
    )

Or assign ``list(base) + list(DESKTOP_AUTOMATION_TOOL_NAMES)`` if you prefer;
``merge_role_tools_with_desktop`` deduplicates while preserving order (base first).

Recommended agent flow: ``desktop_list_windows`` → ``desktop_activate_window`` →
(on Windows, prefer) ``desktop_uia_list_elements`` / ``desktop_uia_read_text`` →
``desktop_uia_click`` when names are reliable → else ``desktop_screenshot`` →
``desktop_suggest_click`` → ``desktop_mouse`` / ``desktop_keyboard``.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence

# Single source of truth for "this role has the desktop skill" (order = tool registration order).
DESKTOP_AUTOMATION_TOOL_NAMES: tuple[str, ...] = (
    "desktop_list_windows",
    "desktop_activate_window",
    "desktop_uia_list_elements",
    "desktop_uia_read_text",
    "desktop_uia_click",
    "desktop_screenshot",
    "desktop_suggest_click",
    "desktop_mouse",
    "desktop_keyboard",
)

# Tools whose return value may be ERROR:-prefixed; agent_loop tags |ok|/|fail|.
DESKTOP_TOOLS_OK_FAIL: frozenset[str] = frozenset(DESKTOP_AUTOMATION_TOOL_NAMES)


def merge_role_tools_with_desktop(base: Sequence[str]) -> List[str]:
    """Return ``base`` plus any desktop skill tools not already present; order preserved."""
    seen: set[str] = set()
    out: List[str] = []
    for name in base:
        if name not in seen:
            seen.add(name)
            out.append(name)
    for name in DESKTOP_AUTOMATION_TOOL_NAMES:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def extend_tools_with_desktop(names: Iterable[str]) -> List[str]:
    """Alias for merge with a generic iterable (consumed once into a list first)."""
    return merge_role_tools_with_desktop(list(names))
