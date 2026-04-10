"""Background desktop PNG buffer + attach latest frame to selected agent turns.

When ``DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC`` > 0 and ``AGENT_DESKTOP_CONTROL_ENABLED``,
a daemon thread periodically captures the screen. Each **outer** ``_run_with_tools``
invocation for roles listed in ``DESKTOP_LIVE_SNAPSHOT_ROLES`` prepends that PNG to the
first ``chat.send_message`` (Gemini sees text + image).

Note: Gemini AFC performs additional internal turns after the first message; those
steps do not automatically re-attach the image. The buffer stays fresh for the **next**
round's opening message, and the model can still call ``desktop_screenshot()`` anytime.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from typing import Any, List, Optional, Tuple, Union

from .config import (
    AGENT_DESKTOP_CONTROL_ENABLED,
    DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC,
    DESKTOP_LIVE_SNAPSHOT_ROLES,
)

logger = logging.getLogger("company")

_lock = threading.Lock()
_png: Optional[bytes] = None
_dims: Tuple[int, int] = (0, 0)
_mono_ts: float = 0.0
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _roles_allow(role_key: str) -> bool:
    raw = (DESKTOP_LIVE_SNAPSHOT_ROLES or "eng_manager").strip()
    if not raw:
        return False
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    return role_key in allowed


def is_enabled_for_role(role_key: str) -> bool:
    return (
        AGENT_DESKTOP_CONTROL_ENABLED
        and DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC > 0
        and _roles_allow(role_key)
    )


def ensure_background_capture_running() -> None:
    global _thread
    if DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC <= 0 or not AGENT_DESKTOP_CONTROL_ENABLED:
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    t = threading.Thread(target=_bg_loop, name="desktop_live_snapshot", daemon=True)
    _thread = t
    t.start()
    logger.info(
        f"[desktop_live_snapshot] background capture every {DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC}s"
    )


def _bg_loop() -> None:
    interval = max(0.25, min(float(DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC), 3600.0))
    while not _stop.is_set():
        t0 = time.monotonic()
        try:
            _capture_once()
        except Exception as e:
            logger.debug(f"[desktop_live_snapshot] capture failed: {e}")
        elapsed = time.monotonic() - t0
        sleep_for = max(0.05, interval - elapsed)
        if _stop.wait(sleep_for):
            break


def _capture_once() -> None:
    global _png, _dims, _mono_ts
    from . import tool_registry as tr

    tr._maybe_windows_desktop_dpi_aware()
    import pyautogui

    img = pyautogui.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    w, h = img.size
    with _lock:
        _png = data
        _dims = (w, h)
        _mono_ts = time.monotonic()


def get_latest_png_bytes() -> Optional[bytes]:
    """Return newest buffered PNG; synchronously capture once if empty."""
    with _lock:
        if _png is not None:
            return _png
    try:
        _capture_once()
    except Exception:
        return None
    with _lock:
        return _png


def snapshot_age_sec() -> float:
    with _lock:
        if _png is None:
            return -1.0
        return max(0.0, time.monotonic() - _mono_ts)


def build_user_message_with_live_screen(
    prompt: str, role_key: str
) -> Union[str, List[Any]]:
    """Return a string or [text, image Part] for ``chat.send_message``."""
    if not is_enabled_for_role(role_key):
        return prompt
    ensure_background_capture_running()
    png = get_latest_png_bytes()
    if not png:
        return prompt
    from google.genai import types as _gtypes

    age = snapshot_age_sec()
    age_note = f"~{age:.1f}s old" if age >= 0 else "just captured"
    prefix = (
        f"[Live desktop: full-screen PNG attached, buffer refreshes every "
        f"{DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC}s; this frame is {age_note}. "
        f"Treat it as the current screen unless a tool shows otherwise.]\n\n"
    )
    return [
        prefix + prompt,
        _gtypes.Part.from_bytes(data=png, mime_type="image/png"),
    ]
