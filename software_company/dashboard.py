"""Work dashboard for parallel agent coordination."""

from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Dict, List, Optional

from .config import OUTPUT_DIR

logger = logging.getLogger("company")

__all__ = [
    "WorkDashboard",
    "get_dashboard",
    "_dashboard",
    "_dashboard_lock",
]


class WorkDashboard:
    """
    Shared coordination layer for agents working in parallel.
    Tracks domain ownership and routes async messages between agents.
    Persists across sprints so agents remember their domains.
    """
    SAVE_PATH = OUTPUT_DIR / "WORK_DASHBOARD.json"

    def __init__(self):
        self.messages: Dict[str, List] = {}
        self.domains: Dict[str, Dict[str, object]] = {}
        self._sections: Dict[str, Dict[str, str]] = {}  # filename → {section → content}
        self._lock = threading.RLock()
        self._load()

    @staticmethod
    def _parse_file_patterns(file_patterns: str) -> List[str]:
        return [p.strip() for p in (file_patterns or "").split(",") if p.strip()]

    def claim(self, *args, **kwargs) -> str:
        """Register a work domain and file patterns; detects owner and pattern conflicts."""
        if kwargs:
            domain = kwargs["domain"]
            owner = kwargs["owner"]
            description = kwargs.get("description") or ""
            file_patterns = kwargs["file_patterns"]
            sprint = kwargs["sprint"]
        else:
            if len(args) != 5:
                return "CONFLICT: claim() expects (domain, owner, description, file_patterns, sprint)."
            domain, owner, description, file_patterns, sprint = args
        patterns = self._parse_file_patterns(str(file_patterns))
        if not domain or not owner or not patterns:
            return "CONFLICT: domain, owner, and non-empty file_patterns are required."

        with self._lock:
            existing = self.domains.get(domain)
            if existing is not None:
                if existing.get("owner") != owner:
                    return f"CONFLICT: domain '{domain}' is owned by {existing.get('owner')!r}."
                # Same owner: allow update
            else:
                active_files: Dict[str, str] = {}
                for dom_id, info in self.domains.items():
                    if info.get("status") != "active":
                        continue
                    for fn in self._parse_file_patterns(str(info.get("file_patterns", ""))):
                        active_files[fn] = dom_id
                for fn in patterns:
                    other = active_files.get(fn)
                    if other is not None and other != domain:
                        return f"CONFLICT: file pattern '{fn}' overlaps domain '{other}'."

            self.domains[domain] = {
                "owner": owner,
                "description": description,
                "file_patterns": ", ".join(patterns),
                "sprint": int(sprint),
                "status": "active",
            }
            self._save()
        return f"CLAIMED: domain '{domain}' registered for {owner}."

    def get_file_owner(self, filename: str) -> Optional[str]:
        """Return owner agent for this file if an active domain lists it."""
        with self._lock:
            for _dom_id, info in self.domains.items():
                if info.get("status") != "active":
                    continue
                for pat in self._parse_file_patterns(str(info.get("file_patterns", ""))):
                    if pat == filename:
                        return str(info.get("owner"))
            return None

    def write_section(self, filename: str, section: str, owner: str, content: str) -> str:
        """Write a named section of a shared file. Returns error string or empty string on success."""
        with self._lock:
            if filename not in self._sections:
                self._sections[filename] = {}
            existing_owner = None
            for s, c in self._sections[filename].items():
                if s != section and c.strip() and s.startswith(owner + ":"):
                    existing_owner = s
            self._sections[filename][f"{owner}:{section}"] = content
        return ""

    def assemble_shared_file(self, filename: str) -> str:
        """Assemble all sections of a shared file into one string."""
        with self._lock:
            sections = self._sections.get(filename, {})
            if not sections:
                return ""
            return "\n\n".join(content for _, content in sorted(sections.items()))

    def release_sprint(self, sprint: int):
        """Mark domains in this sprint complete and persist."""
        sp = int(sprint)
        with self._lock:
            for _d, info in self.domains.items():
                if int(info.get("sprint", 0)) == sp:
                    info["status"] = "complete"
            self._save()

    def get_status(self) -> str:
        with self._lock:
            parts: List[str] = []
            active_domains = [
                (d, info) for d, info in self.domains.items() if info.get("status") == "active"
            ]
            if active_domains:
                bits = [f"{d} ({info.get('owner')})" for d, info in active_domains]
                parts.append("Active domains: " + ", ".join(bits))
            if self.messages:
                parts.append("Active coordination dashboard.")
            if not parts:
                return "Dashboard: no active coordination or messages."
            return " | ".join(parts)

    def send_message(self, from_agent: str, to_agent: str, message: str, sprint: int) -> str:
        with self._lock:
            self.messages.setdefault(to_agent, []).append(
                {"from": from_agent, "text": message, "sprint": sprint}
            )
            self._save()
            return f"Message queued for {to_agent}. They will receive it in Round 2."

    def get_messages(self, agent_id: str) -> str:
        with self._lock:
            msgs = self.messages.get(agent_id, [])
            if not msgs:
                return "No messages from teammates."
            # Save with the inbox cleared BEFORE returning, so a save failure leaves inbox intact
            self.messages[agent_id] = []
            try:
                self._save()
                del self.messages[agent_id]
            except Exception:
                # Restore on failure so messages are not lost
                self.messages[agent_id] = msgs
                return "\n".join(
                    f"FROM {m['from']} (sprint {m['sprint']}): {m['text']}" for m in msgs
                )
            return "\n".join(
                f"FROM {m['from']} (sprint {m['sprint']}): {m['text']}" for m in msgs
            )

    def peek_messages(self, agent_id: str) -> str:
        """Read messages without clearing the inbox — used for auto-injection into prompts."""
        with self._lock:
            msgs = self.messages.get(agent_id, [])
            if not msgs:
                return ""
            return "\n".join(
                f"FROM {m['from']} (sprint {m['sprint']}): {m['text']}" for m in msgs
            )

    def broadcast(self, from_agent: str, message: str, sprint: int, recipients: List[str]) -> str:
        """Send one message to every agent in `recipients` except the sender.
        Used for breaking-change announcements (API changes, model renames, etc.)."""
        with self._lock:
            sent_to = []
            for agent_id in recipients:
                if agent_id == from_agent:
                    continue
                self.messages.setdefault(agent_id, []).append({
                    "from": from_agent,
                    "text": f"📢 BROADCAST: {message}",
                    "sprint": sprint,
                })
                sent_to.append(agent_id)
            self._save()
        logger.info(f"[Dashboard] {from_agent} broadcast to {len(sent_to)} agents: {message[:80]}")
        return f"Broadcast sent to {len(sent_to)} teammates: {', '.join(sent_to)}"

    def _save(self):
        try:
            self.SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.SAVE_PATH.write_text(
                json.dumps({
                    "messages": self.messages,
                    "domains": self.domains,
                }, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[Dashboard] save failed: {e}")

    def _load(self):
        try:
            if self.SAVE_PATH.exists():
                data = json.loads(self.SAVE_PATH.read_text(encoding="utf-8"))
                self.messages = data.get("messages", {})
                raw_domains = data.get("domains", {})
                self.domains = {str(k): dict(v) for k, v in raw_domains.items()} if raw_domains else {}
                logger.info(f"[Dashboard] loaded coordination dashboard")
        except Exception as e:
            logger.warning(f"[Dashboard] load failed: {e}")


_dashboard: Optional[WorkDashboard] = None
_dashboard_lock = threading.Lock()


def get_dashboard() -> WorkDashboard:
    global _dashboard
    pkg = sys.modules.get("software_company")
    # Package __init__ copies _dashboard by value; tests set sc._dashboard = None to reset.
    if pkg is not None and "_dashboard" in pkg.__dict__ and pkg.__dict__["_dashboard"] is None:
        _dashboard = None
    if _dashboard is None:
        with _dashboard_lock:
            if _dashboard is None:
                _dashboard = WorkDashboard()
    if pkg is not None:
        pkg.__dict__["_dashboard"] = _dashboard
    return _dashboard
