"""Anthropic-style computer-use loop support for the Engineering Manager agent.

Public API used by engineering.py
──────────────────────────────────
  get_screen_dims()                  → (w, h) — pyautogui or live-snapshot dims
  get_screen_dims_hint()             → human-readable string for prompt injection
  build_computer_use_loop_section()  → structured observe→act→verify block
  CUTripletTracker                   → tracks screenshot→action→screenshot triplets
  zoom_region_impl(x1,y1,x2,y2)     → crops PNG, calls vision, returns description

The module is intentionally dependency-light: all heavy imports (pyautogui, PIL,
google.genai) are deferred to call time so the rest of the package still imports
cleanly in environments without a display.
"""

from __future__ import annotations

import base64
import io
import logging
import threading
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger("company")

# ──────────────────────────────────────────────────────────────────────────────
# Screen dimension helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_screen_dims() -> Tuple[int, int]:
    """Return (width, height) of the primary screen.

    Resolution order:
      1. Live-snapshot buffer dims  (already captured by background thread)
      2. pyautogui.size()           (ground truth; deferred import)
      3. (0, 0)                     (no desktop available)
    """
    # 1. Try the live-snapshot buffer first (zero-cost if already running)
    try:
        from .desktop_live_snapshot import _dims, _png  # noqa: PLC0415
        if _png is not None and _dims[0] > 0:
            return _dims
    except Exception:
        pass

    # 2. Fall back to pyautogui
    try:
        import pyautogui  # noqa: PLC0415
        return tuple(pyautogui.size())  # type: ignore[return-value]
    except Exception:
        pass

    return (0, 0)


def get_screen_dims_hint() -> str:
    """Return a compact prompt string with display canvas dimensions.

    Example: "DISPLAY CANVAS: display_width_px=1920  display_height_px=1080"
    """
    w, h = get_screen_dims()
    if w > 0 and h > 0:
        return f"DISPLAY CANVAS: display_width_px={w}  display_height_px={h}"
    return "DISPLAY CANVAS: unknown (call desktop_screenshot() to get dimensions)"


# ──────────────────────────────────────────────────────────────────────────────
# Triplet tracker: screenshot → action → screenshot
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CUTripletTracker:
    """Track completed observe→act→verify triplets across manager fix rounds.

    A triplet is: (screenshot_ok) → (action_ok) → (screenshot_ok).
    Attributes are updated by ``_manager_fix_loop`` after each tool-results list.
    """
    screenshots: int = 0          # cumulative successful desktop_screenshot calls
    actions: int = 0              # cumulative successful action calls (mouse/kb/uia)
    completed_triplets: int = 0   # full screenshot→action→screenshot sequences

    # Internal state for incomplete-triplet tracking
    _last_event: str = field(default="", repr=False)   # "screenshot" | "action" | ""

    def update_from_tool_results(self, tool_results: List[str]) -> None:
        """Process a batch of tool-result strings and advance triplet state."""
        for tr in tool_results:
            if tr.startswith("[TOOL: desktop_screenshot|ok]"):
                self.screenshots += 1
                if self._last_event == "action":
                    # screenshot AFTER an action → triplet complete
                    self.completed_triplets += 1
                    self._last_event = "screenshot"
                else:
                    self._last_event = "screenshot"
            elif tr.startswith("[TOOL: desktop_uia_read_text|ok]"):
                # OpenClaw-style: UIA text read counts as verify step — no screenshot needed
                if self._last_event == "action":
                    self.completed_triplets += 1
                    self._last_event = "screenshot"  # treat as verified state
            elif (
                tr.startswith("[TOOL: desktop_mouse|ok]")
                or tr.startswith("[TOOL: desktop_keyboard|ok]")
                or tr.startswith("[TOOL: desktop_uia_click|ok]")
            ):
                self.actions += 1
                if self._last_event == "screenshot":
                    self._last_event = "action"
                # else: action without prior screenshot — still counts but no triplet yet

    def has_at_least_one_triplet(self) -> bool:
        return self.completed_triplets >= 1

    def status_line(self) -> str:
        return (
            f"screenshot_calls={self.screenshots}  "
            f"action_calls={self.actions}  "
            f"completed_triplets={self.completed_triplets}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Computer-use loop prompt builder
# ──────────────────────────────────────────────────────────────────────────────

def build_computer_use_loop_section(
    tracker: CUTripletTracker,
    desktop_proof_required: bool = True,
) -> str:
    """Return the structured computer-use loop instruction block for the manager prompt.

    Follows Anthropic's documented computer-use protocol exactly:
      1. App creates environment + tells model screen size (display_width_px / display_height_px)
      2. Model receives goal + screenshot
      3. Model returns a tool call (screenshot / click / type / scroll / zoom)
      4. App executes the action
      5. App captures new state and sends back — loop repeats

    This function formats that protocol as an unambiguous checklist the Gemini
    manager can follow step by step.
    """
    dims_hint = get_screen_dims_hint()
    triplet_status = tracker.status_line()

    if not desktop_proof_required:
        return (
            f"── Computer-Use Context ──\n"
            f"  {dims_hint}\n"
            f"  GUI HEADLESS MODE: desktop mouse/screenshot proof not required.\n"
            f"  Call start_service() to record boot; rely on pytest for GUI logic.\n\n"
        )

    triplet_note = (
        "✔ At least one full triplet recorded — keep verifying checklist items."
        if tracker.has_at_least_one_triplet()
        else "✗ No complete triplet yet — you MUST complete at least one full loop."
    )

    return (
        f"── COMPUTER-USE LOOP PROTOCOL (OpenClaw-style: UIA first) ──────────────\n"
        f"  {dims_hint}\n"
        f"  Current loop status: {triplet_status}\n"
        f"  Triplet goal:        {triplet_note}\n\n"
        f"  REQUIRED SEQUENCE (repeat for each UI interaction):\n"
        f"    STEP 1 — OBSERVE:  desktop_screenshot()              ← baseline only\n"
        f"    STEP 2 — LOCATE (UIA first — fast, no vision API):\n"
        f"               FAST:   desktop_uia_list_elements('Window Title')  ← exact names\n"
        f"               SLOW fallback only: desktop_suggest_click('<target>') ← if UIA empty\n"
        f"               ZOOM fallback: desktop_zoom_region(x1,y1,x2,y2)    ← unclear area\n"
        f"    STEP 3 — ACT (use name from step 2):\n"
        f"               FAST:   desktop_uia_click('Win Title', 'Control Name')  ← preferred\n"
        f"               SLOW fallback: desktop_mouse / desktop_keyboard          ← pixel based\n"
        f"    STEP 4 — VERIFY (no screenshot needed if UIA can read state):\n"
        f"               FAST:   desktop_uia_read_text('Win Title')   ← read result text\n"
        f"               SLOW fallback: desktop_screenshot()          ← only if UIA cannot read\n\n"
        f"  RULES:\n"
        f"    • Try desktop_uia_list_elements BEFORE any screenshot/suggest_click — it is\n"
        f"      instant and never makes a vision API call. Skip it only if it returns empty.\n"
        f"    • desktop_uia_click by name is perfectly accurate. desktop_mouse with pixel\n"
        f"      coordinates from suggest_click is a slow, error-prone fallback.\n"
        f"    • desktop_uia_read_text completes the verify step — no screenshot required.\n"
        f"    • desktop_list_windows → desktop_activate_window first if window is not focused.\n"
        f"    • Screenshot-only rounds do NOT satisfy integration — an action is required.\n"
        f"    • ERROR-prefixed tool returns do NOT count as successful calls.\n"
        f"────────────────────────────────────────────────────────────────────────\n\n"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Zoom-region implementation (called by the tool_registry shim)
# ──────────────────────────────────────────────────────────────────────────────

def zoom_region_impl(
    x1: int, y1: int, x2: int, y2: int,
    hint: str = "",
    vision_model: str = "",
) -> str:
    """Crop [x1,y1→x2,y2] from the current screen and ask the vision model to
    describe it in detail.  Returns the description plus scaled-coordinate hints.

    This is the Anthropic 'zoom into region' step — use it when a screen area
    is too small or dense to locate a click target reliably.

    Args:
        x1, y1: top-left corner of the region (screen pixel coords)
        x2, y2: bottom-right corner of the region (screen pixel coords)
        hint:   optional text describing what you are looking for in the crop
        vision_model: override DESKTOP_VISION_MODEL; empty = use default
    """
    # Delayed imports so the module loads cleanly without a display
    try:
        import pyautogui  # noqa: PLC0415
    except ImportError:
        return "ERROR: pyautogui is not installed. Run: pip install pyautogui"

    try:
        from .config import AGENT_DESKTOP_CONTROL_ENABLED  # noqa: PLC0415
        if not AGENT_DESKTOP_CONTROL_ENABLED:
            return (
                "ERROR: desktop control is disabled. "
                "Set AGENT_DESKTOP_CONTROL_ENABLED=1 to use desktop_zoom_region."
            )
    except Exception:
        pass

    try:
        from .tool_registry import _desktop_vision_model, _maybe_windows_desktop_dpi_aware  # noqa: PLC0415
        from .llm_client import get_client  # noqa: PLC0415

        _maybe_windows_desktop_dpi_aware()
        screen_w, screen_h = pyautogui.size()

        # Clamp coords to screen bounds
        rx1 = max(0, min(x1, x2, screen_w - 1))
        ry1 = max(0, min(y1, y2, screen_h - 1))
        rx2 = min(screen_w, max(x1, x2))
        ry2 = min(screen_h, max(y1, y2))

        if rx2 - rx1 < 8 or ry2 - ry1 < 8:
            return (
                f"ERROR: zoom region ({rx1},{ry1})→({rx2},{ry2}) is too small "
                f"(minimum 8×8 pixels). Widen the region."
            )

        img = pyautogui.screenshot()
        crop = img.crop((rx1, ry1, rx2, ry2))
        cw, ch = crop.size

        buf = io.BytesIO()
        crop.save(buf, format="PNG")
        crop_b64 = base64.b64encode(buf.getvalue()).decode()

        model = vision_model or _desktop_vision_model()
        hint_part = f" Looking for: {hint!r}." if hint else ""
        prompt_text = (
            f"You are inspecting a zoomed crop ({cw}×{ch} px) taken from a "
            f"{screen_w}×{screen_h} screen. The crop's top-left in the full image "
            f"is ({rx1},{ry1}).{hint_part}\n\n"
            "Describe every UI element visible: labels, buttons, input fields, "
            "icons, text, and their approximate positions within this crop.\n"
            "If you can identify the best single click target, also output: "
            "CLICK_AT_CROP: x=<int> y=<int>  (coordinates within crop, 0,0=top-left)."
        )

        try:
            resp = get_client().models.generate_content(
                model=model,
                contents=[{
                    "parts": [
                        {"text": prompt_text},
                        {"inline_data": {"mime_type": "image/png", "data": crop_b64}},
                    ],
                }],
            )
            description = (getattr(resp, "text", None) or "").strip()
        except Exception as ve:
            description = f"(vision call failed: {ve})"

        logger.info(
            f"[desktop_zoom_region] ({rx1},{ry1})-({rx2},{ry2}) crop={cw}x{ch} "
            f"model={model!r} hint={hint!r}"
        )

        # Parse CLICK_AT_CROP if present and translate back to screen coords
        import re  # noqa: PLC0415
        click_hint = ""
        m = re.search(r"CLICK_AT_CROP:\s*x=(\d+)\s*y=(\d+)", description, re.IGNORECASE)
        if m:
            cx_crop = int(m.group(1))
            cy_crop = int(m.group(2))
            sx = rx1 + cx_crop
            sy = ry1 + cy_crop
            click_hint = (
                f"\nSuggested screen click: desktop_mouse('click', {sx}, {sy})  "
                f"(crop ({cx_crop},{cy_crop}) → screen ({sx},{sy}))"
            )

        return (
            f"Zoom region ({rx1},{ry1})→({rx2},{ry2}) — crop {cw}×{ch}px on "
            f"{screen_w}×{screen_h} screen:\n"
            f"{description}"
            f"{click_hint}"
        )

    except Exception as e:
        logger.warning(f"[desktop_zoom_region] failed: {e}", exc_info=True)
        return f"ERROR: {e}"
