"""Git worktree isolation for engineering agents."""

from __future__ import annotations

import logging
import shutil as _shutil
import subprocess
import threading
from pathlib import Path
from typing import List, Optional

from .config import GIT_CMD_TIMEOUT, OUTPUT_DIR
from .contracts import get_contracts
from .state import _get_agent_id, _get_task_file, _get_worktree_manager
from .team_schemas import MergeResult

logger = logging.getLogger("company")

# Serialises all git operations that touch the shared code_dir repo state
# (init, add, commit, worktree add/remove).  Individual agents can still write
# files concurrently; only the git commands themselves need to be serialised.
_git_repo_lock = threading.Lock()


def _get_code_dir() -> Path:
    """Return the active code directory — agent's worktree if active, else shared."""
    # Lazy import: _monolith may still be loading when sibling modules import this file.
    from . import _monolith as _m

    _m._sync_public_config_from_package()
    agent_id = _get_agent_id()
    wt = _get_worktree_manager()
    if wt and agent_id:
        agent_dir = wt.get_agent_code_dir(agent_id)
        if agent_dir and agent_dir.exists():
            return agent_dir
        # Worktree object exists but directory missing — log and fall back
        logger.warning(
            f"[_get_code_dir] worktree dir missing for {agent_id!r} "
            f"(wt root={wt.worktree_root}, exists={wt.worktree_root.exists()}); "
            f"falling back to shared code dir"
        )
    else:
        if not wt:
            logger.debug(f"[_get_code_dir] no worktree manager set (agent={agent_id!r}); using shared code dir")
    return OUTPUT_DIR / "code"


class GitWorktreeManager:
    """
    Manages Git worktrees so each engineering agent writes to an isolated branch.
    Lifecycle per round: create_worktrees() -> agents work -> commit_all() -> merge_all() -> cleanup()
    """

    def __init__(self, code_dir: Path, agent_ids: List[str]):
        self.code_dir = code_dir.resolve()
        self.agent_ids = agent_ids
        self.worktree_root = self.code_dir.parent / ".worktrees"
        self._initialized = False

    def _git(self, *args: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
        cmd = ["git"] + list(args)
        return subprocess.run(
            cmd,
            cwd=str(cwd or self.code_dir),
            capture_output=True,
            text=True,
            timeout=GIT_CMD_TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )

    def init_repo(self) -> None:
        """Initialize a git repo in code_dir if one doesn't exist, and create an initial commit."""
        if self._initialized:
            return
        with _git_repo_lock:
            if self._initialized:  # double-checked inside the lock
                return
            git_dir = self.code_dir / ".git"
            if not git_dir.exists():
                self.code_dir.mkdir(parents=True, exist_ok=True)
                self._git("init")
                self._git("checkout", "-b", "main")
                gitignore = self.code_dir / ".gitignore"
                if not gitignore.exists():
                    patterns = get_contracts().gitignore_patterns or []
                    content = "\n".join(
                        [".worktrees/", "__pycache__/", "**/__pycache__/", "*.pyc"]
                        + [p for p in patterns if p not in (".worktrees/", "__pycache__/", "**/__pycache__/", "*.pyc")]
                    ) + "\n"
                    gitignore.write_text(content, encoding="utf-8")
                self._git("add", ".")
                self._git("commit", "-m", "initial skeleton", "--allow-empty")
                logger.info("[worktree] initialized git repo in code/")
            else:
                # Patch .gitignore if missing entries for the detected build tool
                gitignore = self.code_dir / ".gitignore"
                existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
                existing_lines = set(existing.splitlines())
                patterns = get_contracts().gitignore_patterns or []
                # Always ignore dependency trees; letting them into git status makes
                # `git add` extremely slow and causes task retries/timeouts on Windows.
                needed_lines = [
                    ".worktrees/",
                    "__pycache__/",
                    "**/__pycache__/",
                    "*.pyc",
                    "node_modules/",
                    "**/node_modules/",
                    "frontend/node_modules/",
                ] + [p for p in patterns if p != ".worktrees/"]
                additions = [l for l in needed_lines if l and l not in existing_lines]
                if additions:
                    with open(gitignore, "a", encoding="utf-8") as f:
                        f.write("\n" + "\n".join(additions) + "\n")
                    for entry in additions:
                        self._git("rm", "-r", "--cached", "--ignore-unmatch", entry.rstrip("/"))
                self._git("add", ".")
                result = self._git("diff", "--cached", "--quiet")
                if result.returncode != 0:
                    self._git("commit", "-m", "pre-round snapshot")
            self._initialized = True

    def create_worktrees(self) -> None:
        """Create an isolated worktree + branch for each agent."""
        self.init_repo()
        with _git_repo_lock:
            self.worktree_root.mkdir(parents=True, exist_ok=True)
            for agent_id in self.agent_ids:
                wt_path = self.worktree_root / agent_id
                # Use forward slashes for git on Windows
                wt_path_str = str(wt_path).replace("\\", "/")
                if wt_path.exists():
                    self._git("worktree", "remove", wt_path_str, "--force")
                    if wt_path.exists():
                        _shutil.rmtree(str(wt_path), ignore_errors=True)
                branch_check = self._git("rev-parse", "--verify", agent_id)
                if branch_check.returncode == 0:
                    self._git("branch", "-D", agent_id)
                result = self._git("worktree", "add", wt_path_str, "-b", agent_id)
                if result.returncode != 0:
                    logger.error(
                        f"[worktree] failed to create worktree for {agent_id}: {result.stderr.strip()}\n"
                        f"  stdout: {result.stdout.strip()}"
                    )
                    raise RuntimeError(f"git worktree add failed for {agent_id}: {result.stderr.strip()}")
                logger.info(f"[worktree] created worktree for {agent_id} at {wt_path}")

    def get_agent_code_dir(self, agent_id: str) -> Optional[Path]:
        """Return the worktree path for an agent, or None if worktrees aren't active."""
        wt_path = self.worktree_root / agent_id
        if wt_path.exists():
            return wt_path
        return None

    def commit_agent(self, agent_id: str) -> bool:
        """Commit all changes in an agent's worktree. Returns True if there was something to commit."""
        wt_path = self.worktree_root / agent_id
        if not wt_path.exists():
            logger.warning(f"[worktree] {agent_id}: worktree path missing at commit time: {wt_path}")
            return False
        # git add/commit within the worktree branch; no lock needed as the worktree
        # branch is exclusive to this agent, but we still serialise to avoid index
        # conflicts on the shared object store.
        with _git_repo_lock:
            # Stage tracked edits quickly.
            self._git("add", "-u", cwd=wt_path)

            # Stage the current task file directly (fast path for normal dev tasks).
            task_file = (_get_task_file() or "").strip().replace("\\", "/")
            if task_file and task_file != "__integration__":
                self._git("add", "--", task_file, cwd=wt_path)
            else:
                # Integration/fallback path: stage only changed paths from porcelain status,
                # while skipping heavy dependency folders.
                st = self._git("status", "--porcelain", cwd=wt_path)
                if st.returncode == 0 and st.stdout:
                    for line in st.stdout.splitlines():
                        if len(line) < 4:
                            continue
                        raw = line[3:].strip()
                        path = raw.split("->")[-1].strip().replace("\\", "/")
                        if not path:
                            continue
                        if "node_modules/" in path or "/.git/" in path or path.startswith(".git/"):
                            continue
                        self._git("add", "--", path, cwd=wt_path)

            diff = self._git("diff", "--cached", "--quiet", cwd=wt_path)
            if diff.returncode == 0:
                logger.info(f"[worktree] {agent_id}: no changes to commit")
                return False
            result = self._git("commit", "-m", f"round work by {agent_id}", cwd=wt_path)
            if result.returncode != 0:
                logger.warning(f"[worktree] {agent_id} commit failed: {result.stderr.strip()}")
                return False
            logger.info(f"[worktree] {agent_id}: committed changes")
            return True

    def merge_all(self) -> MergeResult:
        """Merge all agent branches back into main.
        Returns a MergeResult with conflict resolutions and failed agents."""
        resolutions: List[str] = []
        failed_agents: List[str] = []
        with _git_repo_lock:
            self._git("checkout", "main")
            for agent_id in self.agent_ids:
                result = self._git("merge", agent_id, "--no-edit")
                if result.returncode != 0:
                    conflict_files = self._get_conflict_files()
                    if conflict_files:
                        for cf in conflict_files:
                            resolved = self._resolve_conflict(cf, agent_id)
                            resolutions.append(f"  Resolved conflict in {cf} (agent: {agent_id}): {resolved}")
                        self._git("add", ".")
                        self._git("commit", "-m", f"merged {agent_id} with conflict resolution")
                    else:
                        self._git("merge", "--abort")
                        failed_agents.append(agent_id)
                        logger.warning(f"[worktree] merge of {agent_id} failed (non-conflict): {result.stderr.strip()}")
                else:
                    logger.info(f"[worktree] merged {agent_id} cleanly")
        if resolutions:
            report = "\n".join(resolutions)
            logger.info(f"[worktree] merge conflict resolutions:\n{report}")
        return MergeResult(resolutions=resolutions, failed_agents=failed_agents)

    def _get_conflict_files(self) -> List[str]:
        result = self._git("diff", "--name-only", "--diff-filter=U")
        if result.returncode == 0 and result.stdout.strip():
            return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        return []

    def _resolve_conflict(self, filepath: str, agent_id: str) -> str:
        """Use LLM to resolve a merge conflict."""
        full_path = self.code_dir / filepath
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as e:
            self._git("checkout", "--theirs", filepath)
            return f"read error, took theirs: {e}"

        if "<<<<<<" not in content:
            return "no conflict markers found"

        registry = get_contracts()
        fc = registry.file_map.get(filepath)
        contract_ctx = ""
        if fc:
            contract_ctx = f"Contract: exports={fc.exports}, imports_from={fc.imports_from}, desc={fc.description}"

        try:
            import software_company as _sc

            resolved = _sc.llm_call(
                f"This file has a Git merge conflict. Resolve it by combining both sides correctly.\n\n"
                f"FILE: {filepath}\n"
                f"{contract_ctx}\n\n"
                f"CONFLICTED CONTENT:\n{content[:4000]}\n\n"
                f"Output ONLY the resolved file content. No markdown fences. "
                f"Keep all functionality from both sides. Remove all conflict markers.",
                label=f"resolve_conflict_{filepath}",
            )
            if resolved and "<<<<<<" not in resolved:
                full_path.write_text(resolved.strip() + "\n", encoding="utf-8")
                return "LLM-resolved"
        except Exception as e:
            logger.warning(f"[worktree] LLM conflict resolution failed for {filepath}: {e}")

        self._git("checkout", "--theirs", filepath)
        return "LLM failed, took theirs"

    def cleanup(self) -> None:
        """Remove this manager's worktrees and branches only (not the shared root)."""
        with _git_repo_lock:
            for agent_id in self.agent_ids:
                wt_path = self.worktree_root / agent_id
                wt_path_str = str(wt_path).replace("\\", "/")
                if wt_path.exists():
                    self._git("worktree", "remove", wt_path_str, "--force")
                    if wt_path.exists():
                        _shutil.rmtree(str(wt_path), ignore_errors=True)
                self._git("branch", "-D", agent_id)
            self._git("worktree", "prune")
            # Only remove root if no other worktrees remain
            if self.worktree_root.exists() and not any(self.worktree_root.iterdir()):
                _shutil.rmtree(str(self.worktree_root), ignore_errors=True)
        logger.info(f"[worktree] cleaned up worktrees for {self.agent_ids}")
