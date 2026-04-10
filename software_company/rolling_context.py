"""Rolling project memory across tasks."""

from __future__ import annotations

import threading
from typing import List

from .prompts_loaded import _SYSTEM_WORKER

__all__ = ["RollingContext"]


class RollingContext:
    def __init__(self, max_recent: int = 3) -> None:
        self.summary    = ""
        self.recent:    List[str] = []
        self.max_recent = max_recent
        self._lock      = threading.Lock()

    def add(self, task: str, output: str) -> None:
        entry = f"Task: {task[:100]}. Output: {output[:250]}"
        with self._lock:
            self.recent.append(entry)
            should_summarise = len(self.recent) > self.max_recent
            old = self.recent.pop(0) if should_summarise else None
            current_summary = self.summary
        if should_summarise and old is not None:
            prompt = (
                "Maintain a concise running summary of a software engineer's work.\n\n"
                f"Current summary:\n{current_summary or '(none)'}\n\n"
                f"New entry:\n{old}\n\n"
                "Update summary. Max 80 words. Preserve decisions made, patterns used, issues found. "
                "Reply with ONLY the updated summary."
            )
            import software_company as sc

            result = sc.llm_call(prompt, label="ctx", system=_SYSTEM_WORKER)
            if not result.startswith("[ERROR"):
                with self._lock:
                    self.summary = result

    def get(self) -> str:
        with self._lock:
            summary = self.summary
            recent  = list(self.recent)
        if not summary and not recent:
            return ""
        parts = []
        if summary:
            parts.append(f"PROJECT HISTORY:\n{summary}")
        if recent:
            parts.append("RECENT WORK:\n" + "\n".join(f"- {e}" for e in recent))
        return "\n".join(parts) + "\n\n"
