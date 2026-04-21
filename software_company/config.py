"""Global configuration defaults and feature flags."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-preview")
# If set, used for desktop_screenshot vision text and desktop_suggest_click (stronger models = better boxes).
# Example: gemini-2.0-flash or gemini-2.5-pro-preview-05-06 — check current Google AI model IDs.
DESKTOP_VISION_MODEL = (os.environ.get("DESKTOP_VISION_MODEL") or "").strip()
# Second vision pass on a crop around the first guess (slower, often tighter clicks).
DESKTOP_SUGGEST_CLICK_REFINE = os.getenv("DESKTOP_SUGGEST_CLICK_REFINE", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
# Background full-screen PNG buffer for multimodal turns (see desktop_live_snapshot.py).
# 0 = disabled. Example: 1.0 = refresh ~every second while any allowed role runs.
try:
    _live_iv = float((os.getenv("DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC") or "0").strip())
    DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC = _live_iv if _live_iv > 0 else 0.0
except ValueError:
    DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC = 0.0
# Comma-separated role_key values that receive the latest snapshot on each _run_with_tools turn.
DESKTOP_LIVE_SNAPSHOT_ROLES = os.getenv("DESKTOP_LIVE_SNAPSHOT_ROLES", "eng_manager").strip()
OUTPUT_DIR = Path("eng_output")

# Canonical cross-team reference files written by each team's manager
TEAM_CANONICAL_FILES = {
    "Architecture": OUTPUT_DIR / "design" / "architecture_spec.md",
    "Design": OUTPUT_DIR / "design" / "design_spec.md",
    "QA": OUTPUT_DIR / "design" / "qa_findings.md",
}
INTERFERENCE_ALPHA = 0.5
TOKEN_BUDGET = 5_000_000  # hard kill-switch: total tokens (in+out) across all agents
AGILE_MODE = True  # if True, use Anthropic-style task-based collaborative coordination
TEST_GATE_ENABLED = True  # if True, run test suite in the manager fix loop
TEST_GATE_HOOKS: List[str] = []  # if non-empty, run these commands instead of auto-detect
SELF_VERIFY_ENABLED = os.getenv("SELF_VERIFY_ENABLED", "1").strip() not in ("0", "false", "no")
MANAGER_FIX_MAX_ROUNDS = int(os.getenv("MANAGER_FIX_MAX_ROUNDS", "10"))
AGENT_LAUNCH_APPS_ENABLED = os.getenv("AGENT_LAUNCH_APPS_ENABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
AGENT_DESKTOP_CONTROL_ENABLED = os.getenv("AGENT_DESKTOP_CONTROL_ENABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
# When False, GUI integration passes with pytest + start_service only (no desktop_mouse/screenshots).
# Set MANAGER_GUI_DESKTOP_PROOF=0 in CI / headless runs; keep default on for real screen verification.
MANAGER_GUI_DESKTOP_PROOF = os.getenv("MANAGER_GUI_DESKTOP_PROOF", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
# Anthropic computer-use triplet gate: when True (default), GUI integration requires at
# least one complete observe→act→verify triplet (screenshot → action → screenshot).
# Set COMPUTER_USE_REQUIRE_TRIPLET=0 to revert to the old loose 2-screenshot requirement.
COMPUTER_USE_REQUIRE_TRIPLET = os.getenv("COMPUTER_USE_REQUIRE_TRIPLET", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
TEAMMATE_IDLE_HOOKS: List[str] = []
TEAMMATE_IDLE_MAX_RETRIES: int = 3
TASK_CREATED_HOOKS: List[str] = []

HYPOTHESES = ["healthy", "uncertain", "confused"]
ROLE_PRIOR = {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}

STANCES = ["minimal", "robust", "scalable", "pragmatic"]
STANCE_DESC = {
    "minimal": "simplest solution possible, easy to understand and maintain",
    "robust": "defensive, handles edge cases and failures, production-ready",
    "scalable": "designed for growth, extensible, horizontally scalable",
    "pragmatic": "balanced tradeoffs, ships fast, good enough for requirements",
}

# Non-engineering team rounds
MAX_TEAM_ROUNDS = 2  # hard cap for non-engineering teams

# Engineering / sprint caps
MAX_ENG_ROUNDS = 4  # hard cap per sprint to control cost (legacy, kept for reference)
MAX_SPRINTS = 5  # safety cap — CEO should ship before this; prevents runaway cost

# Async task-completion constants
MAX_TASKS_PER_AGENT = 20
MAX_WALL_CLOCK = 600  # seconds — hard timeout for entire engineering phase
MAX_RETRIES_PER_TASK = 10
_AGENT_POLL_INTERVAL = 2  # seconds between task queue polls when blocked
GIT_CMD_TIMEOUT = int(os.getenv("GIT_CMD_TIMEOUT", "120"))

PHASE_IMPLEMENTATION = 1  # Coding individual files
PHASE_INTEGRATION = 2  # Final integration test (manager fix loop)

__all__ = [
    "GEMINI_MODEL",
    "DESKTOP_VISION_MODEL",
    "DESKTOP_SUGGEST_CLICK_REFINE",
    "DESKTOP_LIVE_SNAPSHOT_INTERVAL_SEC",
    "DESKTOP_LIVE_SNAPSHOT_ROLES",
    "OUTPUT_DIR",
    "TEAM_CANONICAL_FILES",
    "INTERFERENCE_ALPHA",
    "TOKEN_BUDGET",
    "AGILE_MODE",
    "TEST_GATE_ENABLED",
    "TEST_GATE_HOOKS",
    "SELF_VERIFY_ENABLED",
    "MANAGER_FIX_MAX_ROUNDS",
    "AGENT_LAUNCH_APPS_ENABLED",
    "AGENT_DESKTOP_CONTROL_ENABLED",
    "MANAGER_GUI_DESKTOP_PROOF",
    "COMPUTER_USE_REQUIRE_TRIPLET",
    "TEAMMATE_IDLE_HOOKS",
    "TEAMMATE_IDLE_MAX_RETRIES",
    "TASK_CREATED_HOOKS",
    "HYPOTHESES",
    "ROLE_PRIOR",
    "STANCES",
    "STANCE_DESC",
    "MAX_TEAM_ROUNDS",
    "MAX_ENG_ROUNDS",
    "MAX_SPRINTS",
    "MAX_TASKS_PER_AGENT",
    "MAX_WALL_CLOCK",
    "MAX_RETRIES_PER_TASK",
    "_AGENT_POLL_INTERVAL",
    "GIT_CMD_TIMEOUT",
    "PHASE_IMPLEMENTATION",
    "PHASE_INTEGRATION",
]
