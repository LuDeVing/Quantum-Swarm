"""Windows UI Automation helpers for desktop_uia_* tools (optional ``uiautomation`` package)."""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable, Iterator, List, Optional, Tuple

logger = logging.getLogger("company")

UIAUTOMATION_INSTALL_HINT = "pip install uiautomation"

# Control types we treat as actionable for list/click (OpenClaw-style UIA workflow).
_INTERACTIVE_CONTROL_TYPES: frozenset[str] = frozenset(
    {
        "ButtonControl",
        "EditControl",
        "ComboBoxControl",
        "ListItemControl",
        "CheckBoxControl",
        "RadioButtonControl",
        "HyperlinkControl",
        "MenuItemControl",
        "TabItemControl",
        "SpinnerControl",
        "SliderControl",
        "SplitButtonControl",
        "TreeItemControl",
        "DataItemControl",
        "ThumbControl",
        "ScrollBarControl",
    }
)

_DEFAULT_LIST_LIMIT = 60
_MAX_LIST_OUTPUT_CHARS = 12000
_DEFAULT_READ_MAX = 8000
_MAX_TREE_DEPTH = 28


def _import_uia():
    try:
        import uiautomation as auto  # type: ignore[import-untyped]

        return auto
    except ImportError:
        return None


def _iter_descendants(control: Any, max_depth: int, depth: int = 0) -> Iterator[Tuple[Any, int]]:
    if depth > max_depth:
        return
    yield control, depth
    try:
        children = control.GetChildren()
    except Exception:
        return
    if not children:
        return
    for ch in children:
        yield from _iter_descendants(ch, max_depth, depth + 1)


def _safe_cell(s: str) -> str:
    t = (s or "").replace("\r", " ").replace("\n", " ").strip()
    if len(t) > 120:
        t = t[:117] + "..."
    return t


def _rect_str(rect: Any) -> str:
    try:
        return f"({int(rect.left)},{int(rect.top)})-({int(rect.right)},{int(rect.bottom)})"
    except Exception:
        return "(?)"


def _find_window_first(auto_mod: Any, title_substring: str) -> Tuple[Optional[Any], Optional[str]]:
    root = auto_mod.GetRootControl()
    sub = (title_substring or "").strip().lower()
    if not sub:
        return None, "ERROR: title_substring is required"
    for w, _depth in _iter_descendants(root, max_depth=5):
        try:
            if w.ControlTypeName != "WindowControl":
                continue
            nm = (w.Name or "").strip()
            if sub in nm.lower():
                return w, None
        except Exception:
            continue
    return (
        None,
        f"ERROR: no window with title containing {title_substring!r}. "
        "Call desktop_list_windows() then desktop_activate_window().",
    )


def _type_matches(control_type_filter: str, type_name: str) -> bool:
    f = (control_type_filter or "").strip().lower()
    if not f:
        return True
    return f in (type_name or "").lower()


def _name_matches(name_filter: str, name: str) -> bool:
    f = (name_filter or "").strip().lower()
    if not f:
        return True
    return f in (name or "").lower()


def list_elements(
    title_substring: str,
    name_filter: str = "",
    control_type: str = "",
    limit: int = _DEFAULT_LIST_LIMIT,
) -> str:
    """Return a text table of interactive UIA elements under the matched window."""
    if sys.platform != "win32":
        return "ERROR: desktop_uia_* tools are only supported on Windows."
    auto_mod = _import_uia()
    if auto_mod is None:
        return f"ERROR: uiautomation is not installed. Run: {UIAUTOMATION_INSTALL_HINT}"

    win, err = _find_window_first(auto_mod, title_substring)
    if err:
        return err
    try:
        lim = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        lim = _DEFAULT_LIST_LIMIT

    lines: List[str] = []
    header = "#\tType\tName\tRect\tAutomationId"
    lines.append(header)
    n = 0
    for ctrl, _ in _iter_descendants(win, _MAX_TREE_DEPTH):
        try:
            tname = ctrl.ControlTypeName or ""
            if tname not in _INTERACTIVE_CONTROL_TYPES:
                continue
            raw_name = (ctrl.Name or "").strip()
            if not _name_matches(name_filter, raw_name):
                continue
            if not _type_matches(control_type, tname):
                continue
            aid = _safe_cell(getattr(ctrl, "AutomationId", "") or "")
            lines.append(
                f"{n + 1}\t{tname}\t{_safe_cell(raw_name)}\t{_rect_str(ctrl.BoundingRectangle)}\t{aid}"
            )
            n += 1
            if n >= lim:
                break
        except Exception:
            continue

    wtitle = _safe_cell((win.Name or "").strip())
    out = (
        f"UIA elements under window {wtitle!r} "
        f"(showing {n}, limit={lim}, filters name={name_filter!r} type={control_type!r}):\n"
        + "\n".join(lines)
    )
    if len(out) > _MAX_LIST_OUTPUT_CHARS:
        out = out[: _MAX_LIST_OUTPUT_CHARS - 40] + "\n... (truncated)"
    if n == 0:
        out += (
            "\n\nNo matching interactive elements. Try a wider name_filter, empty control_type, "
            "or desktop_screenshot + desktop_suggest_click."
        )
    return out


def read_text(title_substring: str, max_chars: int = _DEFAULT_READ_MAX) -> str:
    """Flatten non-empty UIA names in the window subtree (fast state check, not OCR)."""
    if sys.platform != "win32":
        return "ERROR: desktop_uia_* tools are only supported on Windows."
    auto_mod = _import_uia()
    if auto_mod is None:
        return f"ERROR: uiautomation is not installed. Run: {UIAUTOMATION_INSTALL_HINT}"

    win, err = _find_window_first(auto_mod, title_substring)
    if err:
        return err
    try:
        cap = max(500, min(50_000, int(max_chars)))
    except (TypeError, ValueError):
        cap = _DEFAULT_READ_MAX

    parts: List[str] = []
    for ctrl, _ in _iter_descendants(win, _MAX_TREE_DEPTH):
        try:
            name = (ctrl.Name or "").strip()
            if name:
                parts.append(name)
        except Exception:
            continue
    text = "\n".join(parts)
    if len(text) > cap:
        text = text[: cap - 20] + "\n... (truncated)"
    wname = _safe_cell((win.Name or "").strip())
    return f"UIA text under {wname!r} ({len(parts)} lines, cap={cap} chars):\n{text}"


def click_named(
    title_substring: str,
    name_substring: str,
    control_type: str = "",
    dpi_prep: Optional[Callable[[], None]] = None,
) -> str:
    """Find a single interactive control by name and click it (UIA Click, with optional DPI prep)."""
    if sys.platform != "win32":
        return "ERROR: desktop_uia_* tools are only supported on Windows."
    auto_mod = _import_uia()
    if auto_mod is None:
        return f"ERROR: uiautomation is not installed. Run: {UIAUTOMATION_INSTALL_HINT}"

    sub = (name_substring or "").strip().lower()
    if not sub:
        return "ERROR: name_substring is required"

    win, err = _find_window_first(auto_mod, title_substring)
    if err:
        return err

    matches: List[Any] = []
    for ctrl, _ in _iter_descendants(win, _MAX_TREE_DEPTH):
        try:
            tname = ctrl.ControlTypeName or ""
            if tname not in _INTERACTIVE_CONTROL_TYPES:
                continue
            raw_name = (ctrl.Name or "").strip()
            if sub not in raw_name.lower():
                continue
            if not _type_matches(control_type, tname):
                continue
            matches.append(ctrl)
        except Exception:
            continue

    if not matches:
        return (
            f"ERROR: no interactive control with name containing {name_substring!r} "
            f"(control_type filter={control_type!r}). "
            "Try desktop_uia_list_elements() or vision-based desktop_suggest_click."
        )
    if len(matches) > 1:
        preview: List[str] = []
        for c in matches[:6]:
            try:
                preview.append(
                    f"{c.ControlTypeName}:{_safe_cell((c.Name or '').strip())} {_rect_str(c.BoundingRectangle)}"
                )
            except Exception:
                preview.append("?")
        return (
            "ERROR: multiple controls match; narrow name_substring or set control_type. "
            "Candidates:\n  - " + "\n  - ".join(preview)
        )

    target = matches[0]
    wname = _safe_cell((win.Name or "").strip())
    cname = _safe_cell((target.Name or "").strip())
    ctype = target.ControlTypeName or "?"
    try:
        if dpi_prep:
            dpi_prep()
        target.Click(simulateMove=True, waitTime=0.12)
        logger.info(f"[desktop_uia_click] window={wname!r} control={ctype!r} name={cname!r}")
        return (
            f"Clicked {ctype} {cname!r} in window {wname!r}. "
            "Call desktop_screenshot() to verify only — do NOT call desktop_suggest_click or "
            "desktop_mouse for this same control unless the screenshot shows the click failed "
            "(redundant vision clicks often miss and undo a good UIA hit)."
        )
    except Exception as e:
        logger.warning(f"[desktop_uia_click] Click failed, trying pyautogui center: {e}", exc_info=True)
        try:
            import pyautogui

            if dpi_prep:
                dpi_prep()
            r = target.BoundingRectangle
            cx = int((r.left + r.right) / 2)
            cy = int((r.top + r.bottom) / 2)
            pyautogui.click(cx, cy)
            logger.info(f"[desktop_uia_click] pyautogui fallback ({cx},{cy})")
            return (
                f"Clicked {ctype} {cname!r} via center ({cx},{cy}) in window {wname!r}. "
                "Call desktop_screenshot() to verify only — avoid desktop_suggest_click for this "
                "same control unless verification shows a miss."
            )
        except ImportError:
            return f"ERROR: UIA Click failed ({e}) and pyautogui is not installed for fallback."
        except Exception as e2:
            return f"ERROR: click failed: {e2}"

