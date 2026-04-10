"""Pool of Playwright browser instances for visual app testing."""

from __future__ import annotations

import base64
import logging
import threading
from typing import Dict, Optional

from .config import GEMINI_MODEL
from .state import _get_agent_id

logger = logging.getLogger("company")

__all__ = [
    "BrowserPool",
    "get_browser_pool",
    "_browser_pool",
    "_browser_pool_lock",
]


class BrowserPool:
    """Pool of N Playwright browser instances for visual app testing.
    Agents call open_app() to acquire a slot, interact, then close_browser() to release.

    State is keyed by agent ID (from _get_agent_id()) rather than by thread so that
    LangGraph's asyncio.to_thread() calls — which may use different threads for each
    tool call from the same agent — can still share the same browser session.
    """

    POOL_SIZE   = 3
    TIMEOUT_SEC = 120

    def __init__(self):
        self._semaphore = threading.Semaphore(self.POOL_SIZE)
        # agent_id → {"page": ..., "browser": ..., "playwright": ...}
        self._sessions: Dict[str, Dict] = {}
        self._sessions_lock = threading.Lock()

    def _session(self) -> Dict:
        """Return the session dict for the current agent, creating if absent."""
        agent_id = _get_agent_id() or f"thread-{threading.get_ident()}"
        with self._sessions_lock:
            if agent_id not in self._sessions:
                self._sessions[agent_id] = {"page": None, "browser": None, "playwright": None}
            return self._sessions[agent_id]

    def _clear_session(self) -> None:
        agent_id = _get_agent_id() or f"thread-{threading.get_ident()}"
        with self._sessions_lock:
            self._sessions.pop(agent_id, None)

    def acquire(self, url: str) -> str:
        got = self._semaphore.acquire(timeout=self.TIMEOUT_SEC)
        if not got:
            return "[BROWSER POOL FULL: all 3 slots busy after 120s — try again later]"
        pw = browser = page = None
        try:
            from playwright.sync_api import sync_playwright
            pw      = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page    = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30_000)
            sess = self._session()
            sess["page"]       = page
            sess["browser"]    = browser
            sess["playwright"] = pw
            return self._describe("Page loaded")
        except Exception as e:
            # Clean up any partially initialized resources before releasing slot
            for obj, method in [(page, "close"), (browser, "close"), (pw, "stop")]:
                if obj is not None:
                    try: getattr(obj, method)()
                    except Exception: pass
            self._clear_session()
            self._semaphore.release()
            return f"[BROWSER ERROR: {e}]"

    def action(self, action: str, selector: str, value: str = "") -> str:
        page = self._session().get("page")
        if page is None:
            return "[BROWSER: no open browser — call open_app() first]"
        try:
            act = action.lower().strip()
            if act == "click":
                page.click(selector, timeout=10_000)
                page.wait_for_load_state("networkidle", timeout=15_000)
            elif act == "type":
                page.fill(selector, value, timeout=10_000)
            elif act == "navigate":
                page.goto(selector, wait_until="networkidle", timeout=30_000)
            elif act == "screenshot":
                pass
            else:
                return f"[BROWSER: unknown action '{action}' — use click/type/navigate/screenshot]"
            return self._describe(f"After {action}")
        except Exception as e:
            return f"[BROWSER ACTION ERROR: {e}]"

    def release(self) -> str:
        sess = self._session()
        page = sess.get("page")
        brow = sess.get("browser")
        pw   = sess.get("playwright")
        try:
            if page: page.close()
            if brow: brow.close()
            if pw:   pw.stop()
        except Exception:
            pass
        finally:
            self._clear_session()
            self._semaphore.release()
        return "Browser closed. Pool slot released."

    def _describe(self, context: str) -> str:
        from software_company.llm_client import get_client

        page = self._session().get("page")
        try:
            screenshot_bytes = page.screenshot(full_page=False)
            img_b64          = base64.b64encode(screenshot_bytes).decode()
            resp = get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[{
                    "parts": [
                        {"text": (
                            "Describe what is visible on this web page screenshot. "
                            "Focus on: UI elements, form fields, buttons, text content, "
                            "error messages, success messages, navigation state. "
                            "Be specific and concise. This is for a developer verifying their feature works."
                        )},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    ]
                }],
            )
            return f"[{context}]\nURL: {page.url}\nTitle: {page.title()}\nVisible: {resp.text.strip()}"
        except Exception as e:
            try:
                text = page.inner_text("body")[:1500]
                return f"[{context} — vision unavailable: {e}]\nURL: {page.url}\nPage text: {text}"
            except Exception:
                return f"[{context} — screenshot failed: {e}]"


_browser_pool: Optional[BrowserPool] = None
_browser_pool_lock = threading.Lock()


def get_browser_pool() -> BrowserPool:
    global _browser_pool
    if _browser_pool is None:
        with _browser_pool_lock:
            if _browser_pool is None:
                _browser_pool = BrowserPool()
    return _browser_pool
