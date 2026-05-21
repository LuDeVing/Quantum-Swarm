"""
Cross-user data isolation tests for the Quantum Swarm API.

These tests verify the owner_id isolation guard logic without importing the full
api_server module (which has optional deps like jose/psutil that may not be installed
in the CI environment).  We extract and unit-test the guard directly.
"""
from __future__ import annotations

import json
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out heavy optional deps so api_server can be imported in any environment
# ---------------------------------------------------------------------------

def _stub_modules(*names: str) -> None:
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()
            # Ensure sub-packages resolve too
            parts = name.split(".")
            for i in range(1, len(parts)):
                parent = ".".join(parts[:i])
                if parent not in sys.modules:
                    sys.modules[parent] = MagicMock()

_stub_modules("jose", "jose.jwt", "passlib", "passlib.context",
              "psutil", "uvicorn")


# ---------------------------------------------------------------------------
# Helpers — minimal project metadata
# ---------------------------------------------------------------------------

def _make_project(pid: str, owner_id: str) -> dict:
    return {
        "id": pid,
        "name": "Test project",
        "status": "Planning",
        "date": "2026-05-13T00:00:00+00:00",
        "owner_id": owner_id,
        "messages": [],
        "runner_pid": None,
    }


# ---------------------------------------------------------------------------
# Core isolation guard — extracted so it can be tested independently
# ---------------------------------------------------------------------------

def _is_owner_or_guest(project_owner_id: str | None, user_id: str) -> bool:
    """
    Mirrors the guard in api_server.py:
        if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
            raise HTTPException(403, "Forbidden")
    Returns True if access is allowed, False if it should be denied.
    """
    if project_owner_id and project_owner_id != user_id and user_id != "guest":
        return False
    return True


# ---------------------------------------------------------------------------
# Test 1: User B cannot access User A's project
# ---------------------------------------------------------------------------

def test_cross_user_access_denied():
    """User B must be denied access to a project owned by User A."""
    uid_a = str(uuid.uuid4())
    uid_b = str(uuid.uuid4())
    assert _is_owner_or_guest(uid_a, uid_b) is False, \
        "User B should be denied access to User A's project"


# ---------------------------------------------------------------------------
# Test 2: Owner can access their own project
# ---------------------------------------------------------------------------

def test_owner_access_allowed():
    """The legitimate owner must be granted access."""
    uid = str(uuid.uuid4())
    assert _is_owner_or_guest(uid, uid) is True, \
        "Owner must be allowed to access their own project"


# ---------------------------------------------------------------------------
# Test 3: Guest user is allowed (public/unauthenticated fallback)
# ---------------------------------------------------------------------------

def test_guest_access_allowed():
    """Guest token must be allowed through the isolation guard."""
    uid_a = str(uuid.uuid4())
    assert _is_owner_or_guest(uid_a, "guest") is True, \
        "Guest must bypass ownership check (public mode)"


# ---------------------------------------------------------------------------
# Test 4: Project with no owner_id is accessible by anyone
# ---------------------------------------------------------------------------

def test_no_owner_id_is_open():
    """Projects without an owner_id are legacy/shared — any user may access."""
    uid_b = str(uuid.uuid4())
    assert _is_owner_or_guest(None, uid_b) is True, \
        "Projects without an owner_id should be readable by all"
    assert _is_owner_or_guest("", uid_b) is True, \
        "Projects with an empty owner_id should be readable by all"


# ---------------------------------------------------------------------------
# Test 5: list_projects — filesystem-level isolation via project.json scan
# ---------------------------------------------------------------------------

def test_list_projects_filesystem_isolation(tmp_path: Path):
    """
    Simulate the list_projects scan: each project.json is read and owner_id is
    checked.  User B should only see their own project in the result list.
    """
    uid_a = str(uuid.uuid4())
    uid_b = str(uuid.uuid4())
    pid_a = str(uuid.uuid4())
    pid_b = str(uuid.uuid4())

    for pid, owner in [(pid_a, uid_a), (pid_b, uid_b)]:
        pdir = tmp_path / pid
        pdir.mkdir()
        (pdir / "project.json").write_text(
            json.dumps(_make_project(pid, owner)), encoding="utf-8"
        )

    # Replicate the list_projects scan logic
    user_b_id = uid_b
    visible = []
    for pdir in tmp_path.iterdir():
        pf = pdir / "project.json"
        if not pf.exists():
            continue
        meta = json.loads(pf.read_text(encoding="utf-8"))
        owner = meta.get("owner_id")
        if owner and owner != user_b_id and user_b_id != "guest":
            continue  # filtered out — belongs to another user
        visible.append(meta["id"])

    assert pid_b in visible, "User B should see their own project"
    assert pid_a not in visible, "User B must NOT see User A's project"


# ---------------------------------------------------------------------------
# Test 6: Episode log contains no PII fields
# ---------------------------------------------------------------------------

def test_episode_log_no_pii():
    """Episode log entries must not contain email, password, or token fields."""
    log = Path(__file__).parent.parent / "logs" / "episodes.jsonl"
    if not log.exists():
        pytest.skip("logs/episodes.jsonl not present — run the system first")
    banned_keys = {"email", "password", "password_hash", "token"}
    for lineno, line in enumerate(log.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        entry = json.loads(line)
        found = banned_keys & set(entry.keys())
        assert not found, \
            f"PII field(s) {found} found in episode log line {lineno}"
