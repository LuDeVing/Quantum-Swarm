#!/usr/bin/env python3
"""
software_company.py — Quantum Swarm Software Development Company

A hierarchical AI company that takes a project brief and produces:
  - Architecture document (system design, API spec, data model)
  - Design spec (user flows, UI components, visual style guide)
  - Implementation (code and implementation guide)
  - QA report (tests, security review)
  - CEO executive summary with H_swarm dashboard

Company structure:
  CEO (strategy + synthesis)
    ├── Architecture Manager
    │     System Designer, API Designer, DB Designer
    ├── Design Manager                            ← NEW
    │     UX Researcher, UI Designer, Visual Designer
    ├── Engineering Manager
    │     Backend Developer, Frontend Developer, DevOps Engineer
    └── QA Manager
          Unit Tester, Integration Tester, Security Auditor

Full Quantum Swarm Algorithm:
  ActiveInferenceState     — per-agent health monitoring (perplexity → F)
  interfere_all()          — health-space interference within teams after R1
  Z-score anomaly + reset  — worker reset and retry on R1 anomaly
  interfere_weighted()     — design-stance interference (task-anchored)
  RollingContext           — project memory accumulates across tasks
  H_swarm                  — health signal propagated up the hierarchy

Each agent also has role-specific TOOLS they can call during R1.
Tool results are injected into R2 context (no extra LLM calls — tools
are Python functions executed locally).

Usage:
  python software_company.py
  python software_company.py "Build a real-time chat system with WebSockets"

Output: company_output/
  architecture.md, design_spec.md, implementation.md, qa_report.md,
  ceo_summary.md, results.json
  code/          ← files written by engineers
  tests/         ← files written by QA
  design/        ← files written by designers
"""

from __future__ import annotations

import ast
import json
import logging
import math
import os
import re
import sys
import time
import textwrap
import threading
import yaml
from dataclasses import dataclass, asdict, field
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import hashlib
import pickle

import numpy as np
from dotenv import load_dotenv
import inspect
from google import genai

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("company")

# ── Config ────────────────────────────────────────────────────────────────────
GEMINI_MODEL       = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
OUTPUT_DIR         = Path("company_output")

# Canonical cross-team reference files written by each team's manager
TEAM_CANONICAL_FILES = {
    "Architecture": OUTPUT_DIR / "design" / "architecture_spec.md",
    "Design":       OUTPUT_DIR / "design" / "design_spec.md",
    "QA":           OUTPUT_DIR / "design" / "qa_findings.md",
}
INTERFERENCE_ALPHA = 0.5
TOKEN_BUDGET       = 5_000_000   # hard kill-switch: total tokens (in+out) across all agents
AGILE_MODE         = True        # if True, use Anthropic-style task-based collaborative coordination
TEST_GATE_ENABLED  = True        # if True, run test suite in the manager fix loop
TEST_GATE_HOOKS: List[str] = []  # if non-empty, run these commands instead of auto-detect
                                  # e.g. ["pytest tests/ --tb=short -q", "mypy src/", "eslint src/"]
SELF_VERIFY_ENABLED = os.getenv("SELF_VERIFY_ENABLED", "1").strip() not in ("0", "false", "no")
MANAGER_FIX_MAX_ROUNDS = int(os.getenv("MANAGER_FIX_MAX_ROUNDS", "10"))
# If true, agents may call launch_application() to start arbitrary desktop programs (same user as Python).
AGENT_LAUNCH_APPS_ENABLED = os.getenv("AGENT_LAUNCH_APPS_ENABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
# If true, agents may take full-screen screenshots and control the mouse/keyboard anywhere on screen.
# WARNING: gives agents the same input control as the logged-in user. Only enable in trusted runs.
AGENT_DESKTOP_CONTROL_ENABLED = os.getenv("AGENT_DESKTOP_CONTROL_ENABLED", "0").strip().lower() in (
    "1", "true", "yes", "on",
)
TEAMMATE_IDLE_HOOKS: List[str] = []  # commands to run when an agent finishes all tasks
                                      # non-zero exit logs failure and injects output into context
TEAMMATE_IDLE_MAX_RETRIES: int = 3   # how many times to re-activate an idle agent on hook failure
TASK_CREATED_HOOKS: List[str] = []   # commands to validate a task before it starts
                                      # receives task description via stdin + ENG_TASK_DESCRIPTION env
                                      # non-zero exit rejects the task (calls task_queue.fail())

HYPOTHESES = ["healthy", "uncertain", "confused"]
ROLE_PRIOR = {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}

STANCES = ["minimal", "robust", "scalable", "pragmatic"]
STANCE_DESC = {
    "minimal":   "simplest solution possible, easy to understand and maintain",
    "robust":    "defensive, handles edge cases and failures, production-ready",
    "scalable":  "designed for growth, extensible, horizontally scalable",
    "pragmatic": "balanced tradeoffs, ships fast, good enough for requirements",
}


# ── Tool implementations (pure Python, no LLM) ───────────────────────────────
def _strip_subdir_prefix(filename: str, subdir: str) -> str:
    """Remove leading 'subdir/' prefix from filename if present, to prevent double-nesting."""
    # Normalise to forward slashes so Windows paths like code\foo.py are handled correctly
    filename = filename.replace("\\", "/")
    prefix = subdir + "/"
    while filename.startswith(prefix):
        filename = filename[len(prefix):]
    return filename


def _read_team_files(max_chars: int = 1500) -> str:
    """Read all canonical team spec files and return a combined snippet for injection."""
    parts = []
    labels = {
        "Architecture": "ARCHITECTURE SPEC",
        "Design":       "DESIGN SPEC",
        "QA":           "QA FINDINGS",
    }
    for team, path in TEAM_CANONICAL_FILES.items():
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"─── {labels[team]} ({path.name}) ───\n{content[:max_chars]}")
    if not parts:
        return ""
    return "\n\n".join(parts)


def _write_canonical_file(team_name: str, content: str, append: bool = False) -> None:
    """Write (or append for QA) the manager synthesis to the team's canonical file."""
    path = TEAM_CANONICAL_FILES.get(team_name)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_file_lock(path):
        if append and path.exists():
            existing = path.read_text(encoding="utf-8")
            path.write_text(existing + "\n\n---\n\n" + content, encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
    logger.info(f"[{team_name}] canonical file updated: {path.name}")


_sprint_written_files: set = set()   # filenames written this sprint (cleared each sprint)
_sprint_written_lock = threading.Lock()

def _record_sprint_file(filename: str) -> None:
    with _sprint_written_lock:
        _sprint_written_files.add(filename)

def clear_sprint_files() -> None:
    with _sprint_written_lock:
        _sprint_written_files.clear()

def get_sprint_files() -> list:
    with _sprint_written_lock:
        return sorted(_sprint_written_files)

# Per-file write locks — one Lock per absolute path, created on first access.
# Prevents two agents from writing the same file simultaneously (last-writer-wins race).
_file_write_locks: Dict[str, threading.Lock] = {}
_file_write_locks_meta = threading.Lock()   # guards the dict itself

def _get_file_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _file_write_locks_meta:
        if key not in _file_write_locks:
            _file_write_locks[key] = threading.Lock()
        return _file_write_locks[key]


_STANCE_LINE_RE = re.compile(r'^\s*STANCE:\s*\[?\w+\]?\s*$', re.IGNORECASE)

def _strip_stance(content: str) -> str:
    """Remove trailing STANCE: tag that agents append to their text output.
    Handles both LF and CRLF line endings."""
    lines = content.rstrip().splitlines()
    while lines and _STANCE_LINE_RE.match(lines[-1]):
        lines.pop()
    return '\n'.join(lines) + '\n'

def _tool_write_code_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "code")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        code_dir = _get_code_dir()
        path     = code_dir / filename
        logger.info(f"[write_code_file] writing {filename} → {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        _record_sprint_file(filename)
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to code/{filename}"
    except Exception as e:
        logger.error(f"[write_code_file] FAILED for {filename!r}: {e}", exc_info=True)
        return f"ERROR writing code/{filename}: {e}"


def _bg_index_file(path: Path) -> None:
    try:
        path    = path.resolve()
        wt_root = (OUTPUT_DIR / ".worktrees").resolve()
        if str(path).startswith(str(wt_root)):
            # File is inside a worktree — index it in the owning agent's WorktreeRAG.
            # Parts layout: (.worktrees / <agent_id> / <rest…>)
            parts    = path.relative_to(wt_root).parts
            if len(parts) < 2:
                return
            agent_id = parts[0]
            rel_str  = "/".join(parts[1:])   # forward-slash, relative to worktree root
            logger.info(f"[RAG:bg] worktree file → WorktreeRAG[{agent_id}]: {rel_str}")
            wt_rag   = get_worktree_rag(agent_id)
            if wt_rag is not None:
                wt_rag.index_file(path, rel_str)
            # If the file has already been merged to canonical code/, update global RAG too
            canonical = (OUTPUT_DIR / "code" / Path(*parts[1:])).resolve()
            if canonical.exists():
                logger.info(f"[RAG:bg] also updating global RAG for merged canonical: {rel_str}")
                get_rag().update_file(canonical)
        else:
            rel = str(path).replace("\\", "/")
            logger.info(f"[RAG:bg] non-worktree file → global RAG: {rel}")
            get_rag().update_file(path)
    except Exception as e:
        logger.warning(f"[RAG:bg] index failed for {path.name}: {e}")


def _tool_write_test_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "tests")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        path = OUTPUT_DIR / "tests" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to tests/{filename}"
    except Exception as e:
        logger.error(f"[write_test_file] FAILED for {filename!r}: {e}")
        return f"ERROR writing tests/{filename}: {e}"


def _tool_write_design_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "design")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        path = OUTPUT_DIR / "design" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to design/{filename}"
    except Exception as e:
        logger.error(f"[write_design_file] FAILED for {filename!r}: {e}")
        return f"ERROR writing design/{filename}: {e}"


def _tool_write_config_file(filename: str, content: str) -> str:
    try:
        filename = _strip_subdir_prefix(filename, "config")
        if not filename or any(c in filename for c in ("*", "?", "<", ">", "|")):
            return f"ERROR: invalid filename {filename!r}"
        path = OUTPUT_DIR / "config" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_strip_stance(content), encoding="utf-8")
        threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
        return f"Written {len(content)} chars to config/{filename}"
    except Exception as e:
        logger.error(f"[write_config_file] FAILED for {filename!r}: {e}")
        return f"ERROR writing config/{filename}: {e}"


def _tool_read_file(filename: str) -> str:
    # Check agent's worktree first for code files
    code_dir = _get_code_dir()
    wt_path = (code_dir / _strip_subdir_prefix(filename, "code")).resolve()
    if wt_path.exists():
        return wt_path.read_text(encoding="utf-8")[:2000]

    for subdir in ["code", "tests", "design", "config", ""]:
        p = (OUTPUT_DIR / subdir / filename if subdir else OUTPUT_DIR / filename).resolve()
        if not str(p).startswith(str(OUTPUT_DIR.resolve())):
            return "[ACCESS DENIED: path outside project directory]"
        if p.exists():
            return p.read_text(encoding="utf-8")[:2000]
    return f"[FILE NOT FOUND: {filename}]"


# ── RAG Index ─────────────────────────────────────────────────────────────────

class CodebaseRAG:
    """
    Lightweight RAG over company_output/ code files.
    Chunks files by function/class boundary, embeds with Gemini embedding-001,
    stores as a numpy matrix. Queried with cosine similarity at agent time.
    Index is persisted to disk and rebuilt only when files change.
    """

    EMBED_MODEL  = "gemini-embedding-001"
    # CACHE_PATH must NOT be a class-level attribute — OUTPUT_DIR can be overridden
    # at runtime (e.g. run_engineers_only.py sets sc.OUTPUT_DIR = "eng_output"), and a
    # frozen class attribute would keep pointing at "company_output/rag_index.pkl",
    # loading stale cache from a prior full-company run into an engineers-only run.
    CHUNK_LINES  = 60          # max lines per chunk
    TOP_K        = 5           # chunks returned per query
    SUBDIRS      = ["code", "tests", "design", "config"]
    # Keep this aligned with files the swarm regularly generates.
    # Missing extensions here causes full update() to silently drop files
    # that update_file() may have indexed earlier.
    EXTENSIONS   = {
        ".py", ".ts", ".tsx", ".js", ".jsx",
        ".json", ".yaml", ".yml", ".md",
        ".css", ".html",
    }

    def __init__(self):
        self.chunks:     List[Dict]   = []   # {"file", "text", "hash"}
        self.embeddings: Optional[np.ndarray] = None  # shape (N, D)
        self._lock = threading.RLock()
        self._load_cache()

    # ── public API ────────────────────────────────────────────────────────

    # Serialises full update() and partial update_file() so they never corrupt the index
    _update_lock = threading.Lock()

    def update(self):
        """Scan all output files, embed new/changed chunks, persist cache."""
        with self._update_lock:
            logger.info(f"[RAG:update] starting full scan — OUTPUT_DIR={OUTPUT_DIR.resolve()}")
            new_chunks = self._scan_files()
            if not new_chunks:
                # If repo is empty (or no supported files), clear stale index state.
                logger.warning(f"[RAG:update] scan returned 0 chunks — clearing index")
                with self._lock:
                    self.chunks = []
                    self.embeddings = None
                    self._save_cache()
                return
            unique_files = sorted(set(c["file"] for c in new_chunks))
            logger.info(f"[RAG:update] scan found {len(new_chunks)} chunks from {len(unique_files)} files: {unique_files}")
            with self._lock:
                to_embed = [c for c in new_chunks if not self._already_embedded(c["hash"]) and c.get("text", "").strip()]
            if not to_embed:
                # No new chunks to embed, but still prune stale entries for deleted/renamed files.
                logger.info(f"[RAG:update] all chunks already embedded — pruning stale entries, keeping {len(unique_files)} files")
                with self._lock:
                    existing_by_hash = {c["hash"]: c for c in self.chunks if "vec" in c}
                    self.chunks = [
                        {**c, "vec": existing_by_hash[c["hash"]]["vec"]}
                        for c in new_chunks
                        if c["hash"] in existing_by_hash
                    ]
                    if self.chunks:
                        self.embeddings = np.stack([c["vec"] for c in self.chunks])
                    else:
                        self.embeddings = None
                    self._save_cache()
                return
            logger.info(f"[RAG] embedding {len(to_embed)} new chunks across {len(set(c['file'] for c in to_embed))} files")
            vecs = self._embed_batch([c["text"] for c in to_embed])
            if vecs is None:
                return
            for chunk, vec in zip(to_embed, vecs):
                chunk["vec"] = vec
            with self._lock:
                self.chunks = [c for c in self.chunks if c["hash"] in {n["hash"] for n in new_chunks}]
                existing_new = {c["hash"] for c in to_embed}
                for c in new_chunks:
                    if c["hash"] not in existing_new:
                        old = next((x for x in self.chunks if x["hash"] == c["hash"]), None)
                        if old:
                            c["vec"] = old["vec"]
                self.chunks = [c for c in new_chunks if "vec" in c]
                if self.chunks:
                    self.embeddings = np.stack([c["vec"] for c in self.chunks])
                self._save_cache()
            logger.info(f"[RAG] index updated: {len(self.chunks)} chunks")

    def update_file(self, path: Path) -> None:
        """Embed a single file and replace its chunks in the index. Thread-safe."""
        with self._update_lock:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.warning(f"[RAG:update_file] read failed for {path}: {e}")
                return
            rel = str(path.resolve().relative_to(OUTPUT_DIR.resolve())).replace("\\", "/")
            logger.info(f"[RAG:update_file] indexing {rel}  ({len(text)} chars)")
            new_chunk_texts = self._split_into_chunks(text, path.suffix)
            new_chunks = []
            for chunk_text in new_chunk_texts:
                h = hashlib.md5((rel + chunk_text).encode()).hexdigest()
                new_chunks.append({"file": rel, "text": chunk_text, "hash": h})
            # Only embed chunks not already in the index — check inside lock
            with self._lock:
                to_embed = [c for c in new_chunks if not self._already_embedded(c["hash"]) and c.get("text", "").strip()]
                existing_by_hash = {c["hash"]: c for c in self.chunks if "vec" in c}
            if to_embed:
                vecs = self._embed_batch([c["text"] for c in to_embed])
                if vecs is None:
                    return
                for chunk, vec in zip(to_embed, vecs):
                    chunk["vec"] = vec
            # Fill in existing vecs for unchanged chunks
            for c in new_chunks:
                if "vec" not in c and c["hash"] in existing_by_hash:
                    c["vec"] = existing_by_hash[c["hash"]]["vec"]
            valid_new = [c for c in new_chunks if "vec" in c]
            with self._lock:
                kept = [c for c in self.chunks if c["file"] != rel]
                self.chunks = kept + valid_new
                if self.chunks:
                    self.embeddings = np.stack([c["vec"] for c in self.chunks])
                else:
                    self.embeddings = None
                self._save_cache()
            logger.debug(f"[RAG] indexed {path.name} ({len(valid_new)} chunks)")

    def query(self, query: str, top_k: int = TOP_K) -> str:
        """Return top_k most relevant code chunks for the query."""
        with self._lock:
            if not self.chunks or self.embeddings is None:
                return "[RAG: index is empty — no files indexed yet]"
            # Copy to avoid holding lock during compute
            emb_snapshot = self.embeddings.copy()
            chunks_snapshot = list(self.chunks)
        q_vec = self._embed_one(query)
        if q_vec is None:
            return "[RAG: embedding failed]"
        sims = emb_snapshot @ q_vec / (
            np.linalg.norm(emb_snapshot, axis=1) * np.linalg.norm(q_vec) + 1e-10
        )
        top_idx = np.argsort(sims)[::-1][:top_k]
        parts = []
        for idx in top_idx:
            c = chunks_snapshot[idx]
            parts.append(f"### {c['file']} (similarity={sims[idx]:.2f})\n```\n{c['text'][:600]}\n```")
        return "\n\n".join(parts)

    def manifest(self) -> str:
        """Return a concise file manifest (filename → first 3 lines summary)."""
        if not self.chunks:
            return "[No files indexed yet]"
        seen: Dict[str, str] = {}
        for c in self.chunks:
            fname = c["file"].replace("\\", "/")
            if fname not in seen:
                first_lines = c["text"].strip().split("\n")[:3]
                seen[fname] = " | ".join(l.strip() for l in first_lines if l.strip())[:120]
        lines = [f"- **{fname}**: {summary}" for fname, summary in sorted(seen.items())]
        return "\n".join(lines)

    def list_files(self) -> str:
        """Return sorted list of all indexed files."""
        if not self.chunks:
            return "[No files indexed yet]"
        # Normalise to forward slashes so the model can use paths directly in tool calls
        files = sorted(set(c["file"].replace("\\", "/") for c in self.chunks))
        return "\n".join(files)

    # ── internals ─────────────────────────────────────────────────────────

    def _scan_files(self) -> List[Dict]:
        chunks = []
        scanned_files: List[str] = []
        for subdir in self.SUBDIRS:
            base = OUTPUT_DIR / subdir
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if "node_modules" in path.parts or ".git" in path.parts:
                    continue
                if path.suffix not in self.EXTENSIONS or not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                rel = str(path.resolve().relative_to(OUTPUT_DIR.resolve())).replace("\\", "/")
                scanned_files.append(rel)
                for chunk_text in self._split_into_chunks(text, path.suffix):
                    h = hashlib.md5((rel + chunk_text).encode()).hexdigest()
                    chunks.append({"file": rel, "text": chunk_text, "hash": h})
        logger.debug(
            f"[RAG._scan_files] OUTPUT_DIR={OUTPUT_DIR.resolve()}  "
            f"found {len(scanned_files)} files: {scanned_files}"
        )
        return chunks

    def _split_into_chunks(self, text: str, ext: str) -> List[str]:
        return _rag_split_chunks(text, ext, self.CHUNK_LINES)

    def _already_embedded(self, h: str) -> bool:
        return any(c.get("hash") == h and "vec" in c for c in self.chunks)

    def _embed_batch(self, texts: List[str]) -> Optional[List[np.ndarray]]:
        return _rag_embed_batch(texts)

    def _embed_one(self, text: str) -> Optional[np.ndarray]:
        return _rag_embed_one(text)

    @property
    def cache_path(self) -> Path:
        """Compute cache path at access time so OUTPUT_DIR overrides take effect."""
        return OUTPUT_DIR / "rag_index.pkl"

    def _save_cache(self):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "wb") as f:
                pickle.dump({"chunks": self.chunks}, f)
        except Exception as e:
            logger.warning(f"[RAG] cache save failed: {e}")

    def _load_cache(self):
        try:
            if self.cache_path.exists():
                with open(self.cache_path, "rb") as f:
                    data = pickle.load(f)
                self.chunks = data.get("chunks", [])
                valid = [c for c in self.chunks if "vec" in c]
                if valid:
                    self.embeddings = np.stack([c["vec"] for c in valid])
                    self.chunks = valid
                    logger.info(f"[RAG] loaded {len(self.chunks)} cached chunks from {self.cache_path}")
        except Exception as e:
            logger.warning(f"[RAG] cache load failed: {e}")
            self.chunks = []


# ── Shared RAG utilities (used by both CodebaseRAG and WorktreeRAG) ───────────

_RAG_EMBED_MODEL = CodebaseRAG.EMBED_MODEL
_RAG_CHUNK_LINES = CodebaseRAG.CHUNK_LINES
_RAG_EXTENSIONS  = CodebaseRAG.EXTENSIONS

def _rag_split_chunks(text: str, ext: str, chunk_lines: int = _RAG_CHUNK_LINES) -> List[str]:
    """Split text by function/class boundary (.py) or fixed line window (everything else)."""
    lines = text.split("\n")
    if ext == ".py":
        chunks, buf = [], []
        for line in lines:
            if (line.startswith("def ") or line.startswith("class ")) and buf:
                chunks.append("\n".join(buf))
                buf = []
            buf.append(line)
            if len(buf) >= chunk_lines:
                chunks.append("\n".join(buf))
                buf = []
        if buf:
            chunks.append("\n".join(buf))
        return [c for c in chunks if c.strip()]
    return [
        chunk for chunk in (
            "\n".join(lines[i:i + chunk_lines])
            for i in range(0, len(lines), chunk_lines)
        )
        if chunk.strip()
    ]

def _rag_embed_batch(texts: List[str]) -> Optional[List[np.ndarray]]:
    try:
        client = get_client()
        vecs = []
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            resp = client.models.embed_content(model=_RAG_EMBED_MODEL, contents=batch)
            for emb in resp.embeddings:
                vecs.append(np.array(emb.values, dtype=np.float32))
        return vecs
    except Exception as e:
        logger.warning(f"[RAG] embed_batch failed: {e}")
        return None

def _rag_embed_one(text: str) -> Optional[np.ndarray]:
    result = _rag_embed_batch([text])
    return result[0] if result else None


# ── Global CodebaseRAG singleton ───────────────────────────────────────────────

_rag: Optional[CodebaseRAG] = None
_rag_lock = threading.Lock()

def get_rag() -> CodebaseRAG:
    global _rag
    if _rag is None:
        with _rag_lock:
            if _rag is None:
                logger.info(f"[RAG:init] creating global CodebaseRAG — OUTPUT_DIR={OUTPUT_DIR.resolve()}")
                _rag = CodebaseRAG()
    return _rag


# ── Per-agent WorktreeRAG ──────────────────────────────────────────────────────

class WorktreeRAG:
    """
    Lightweight in-memory RAG for a single agent's git worktree.

    Purpose: let an agent search and list its own in-progress files before they
    are merged to main and picked up by the global CodebaseRAG.  No disk
    persistence — the index is ephemeral and cleared after each merge.

    Paths are stored as forward-slash paths relative to the worktree root so
    they are directly usable as write_code_file / read_file arguments.
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.chunks:    List[Dict]            = []
        self.embeddings: Optional[np.ndarray] = None
        self._lock = threading.RLock()

    # ── public API ────────────────────────────────────────────────────────

    def index_file(self, abs_path: Path, rel_str: str) -> None:
        """Embed a single file and update the in-memory index.

        abs_path  – absolute path to the file inside the worktree.
        rel_str   – forward-slash path relative to worktree root (e.g. 'backend/app/models.py').
        """
        try:
            text = abs_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return
        if not text.strip():
            return

        new_chunks = [
            {"file": rel_str, "text": ct,
             "hash": hashlib.md5((rel_str + ct).encode()).hexdigest()}
            for ct in _rag_split_chunks(text, abs_path.suffix)
        ]
        if not new_chunks:
            return

        with self._lock:
            existing_by_hash = {c["hash"]: c for c in self.chunks if "vec" in c}
            already = {c["hash"] for c in self.chunks if "vec" in c}

        to_embed = [c for c in new_chunks if c["hash"] not in already and c["text"].strip()]
        if to_embed:
            vecs = _rag_embed_batch([c["text"] for c in to_embed])
            if vecs:
                for chunk, vec in zip(to_embed, vecs):
                    chunk["vec"] = vec

        for c in new_chunks:
            if "vec" not in c and c["hash"] in existing_by_hash:
                c["vec"] = existing_by_hash[c["hash"]]["vec"]

        valid = [c for c in new_chunks if "vec" in c]
        with self._lock:
            self.chunks = [c for c in self.chunks if c["file"] != rel_str] + valid
            self.embeddings = np.stack([c["vec"] for c in self.chunks]) if self.chunks else None
        logger.info(f"[WtRAG:{self.agent_id}] indexed {rel_str} ({len(valid)} chunks, total={len(self.chunks)})")

    def query(self, query_str: str, top_k: int = 3) -> str:
        """Return top-k most relevant code chunks from this agent's worktree."""
        with self._lock:
            if not self.chunks or self.embeddings is None:
                return ""
            emb_snap    = self.embeddings.copy()
            chunk_snap  = list(self.chunks)
        q_vec = _rag_embed_one(query_str)
        if q_vec is None:
            return ""
        sims    = emb_snap @ q_vec / (np.linalg.norm(emb_snap, axis=1) * np.linalg.norm(q_vec) + 1e-10)
        top_idx = np.argsort(sims)[::-1][:top_k]
        return "\n\n".join(
            f"### {chunk_snap[i]['file']} (similarity={sims[i]:.2f})\n```\n{chunk_snap[i]['text'][:600]}\n```"
            for i in top_idx
        )

    def list_files(self) -> List[str]:
        """Return sorted list of relative file paths indexed in this worktree."""
        with self._lock:
            return sorted(set(c["file"] for c in self.chunks))

    def clear(self) -> None:
        """Drop all indexed chunks — called after worktree is merged to main."""
        with self._lock:
            n = len(self.chunks)
            self.chunks    = []
            self.embeddings = None
        logger.info(f"[WtRAG:{self.agent_id}] cleared {n} chunks after merge")


# Per-agent WorktreeRAG registry
_worktree_rags: Dict[str, WorktreeRAG] = {}
_worktree_rags_lock = threading.Lock()

def get_worktree_rag(agent_id: str) -> Optional[WorktreeRAG]:
    """Return (creating if needed) the WorktreeRAG for the given agent."""
    if not agent_id:
        return None
    with _worktree_rags_lock:
        if agent_id not in _worktree_rags:
            _worktree_rags[agent_id] = WorktreeRAG(agent_id)
        return _worktree_rags[agent_id]


# ── Interface Contracts ────────────────────────────────────────────────────────

@dataclass
class EndpointContract:
    method: str          # GET, POST, PUT, DELETE
    path: str            # e.g. "/tasks", "/tasks/{task_id}"
    request_model: str   # e.g. "TaskCreate" or "" for no body
    response_model: str  # e.g. "Task", "List[Task]"

@dataclass
class ModelContract:
    name: str            # e.g. "Task"
    fields: str          # e.g. "id: str, title: str, completed: bool"
    file: str            # e.g. "models.py"

@dataclass
class FileContract:
    file: str            # e.g. "routes.py"
    owner: str           # e.g. "dev_2"
    imports_from: List[str]   # files this depends on, e.g. ["models.py"]
    exports: List[str]        # symbols this file must export, e.g. ["create_task", "get_tasks"]
    description: str     # what this file does
    depends_on: List[str] = field(default_factory=list)  # files that must be complete before this one starts

class InterfaceContractRegistry:
    """
    Holds typed interface contracts generated during sprint planning.
    All agents reference these to ensure shared signatures, import paths,
    and data shapes — eliminating the integration gap.
    """
    def __init__(self):
        self.endpoints: List[EndpointContract] = []
        self.models: List[ModelContract] = []
        self.file_map: Dict[str, FileContract] = {}   # filename -> FileContract
        self.entry_point: str = "main.py"
        self.entry_imports: List[str] = []  # modules the entry point must import
        self.build_command: str = ""      # e.g. "python server.py", "cargo build", "npm run build"
        self.build_file: str = ""         # e.g. "requirements.txt", "Cargo.toml", "package.json"
        self.install_command: str = ""    # e.g. "npm install", "pip install -r requirements.txt"
        self.gitignore_patterns: List[str] = []  # e.g. ["node_modules/", "dist/", "__pycache__/"]
        self.dependencies: List[str] = []  # external deps e.g. ["fastapi", "sqlalchemy"]
        self.init_order: List[str] = []    # ordered module init e.g. ["database", "routes", "server"]
        self._lock = threading.RLock()
        # ── Amendment queue (mid-flight contract changes proposed by agents) ───
        self._pending_amendments: List[Dict] = []  # [{"file", "proposer", "reason", "change", "ts"}]

    def set_from_parsed(self, parsed: Dict) -> None:
        """Populate from parsed LLM output with defensive type-checking."""
        with self._lock:
            # 1. Parse Endpoints Safely
            for ep in parsed.get("endpoints", []):
                if isinstance(ep, dict):
                    self.endpoints.append(EndpointContract(
                        method=ep.get("method", "GET"),
                        path=ep.get("path", "/"),
                        request_model=ep.get("request_model", ""),
                        response_model=ep.get("response_model", ""),
                    ))
            
            # 2. Parse Models Safely
            for m in parsed.get("models", []):
                if isinstance(m, dict):
                    self.models.append(ModelContract(
                        name=m.get("name", ""),
                        fields=m.get("fields", ""),
                        file=m.get("file", "models.py"),
                    ))
            
            # 3. Parse Files Safely
            for f in parsed.get("files", []):
                if isinstance(f, dict):
                    fc = FileContract(
                        file=f.get("file", ""),
                        owner=f.get("owner", ""),
                        imports_from=f.get("imports_from", []),
                        exports=f.get("exports", []),
                        description=f.get("description", ""),
                        depends_on=f.get("depends_on", []),
                    )
                    self.file_map[fc.file] = fc
            
            self.entry_point = parsed.get("entry_point", "server.py")
            self.entry_imports = parsed.get("entry_imports", [])
            self.build_command = parsed.get("build_command", "")
            self.build_file = parsed.get("build_file", "")
            self.install_command = parsed.get("install_command", "")
            self.gitignore_patterns = parsed.get("gitignore_patterns", [])
            self.dependencies = parsed.get("dependencies", [])
            self.init_order = parsed.get("init_order", [])

    def get_contract_for_dev(self, dev_key: str) -> str:
        """Return a prompt-injectable contract summary for a specific developer."""
        with self._lock:
            lines = []
            dev_files = [f for f in self.file_map.values() if f.owner == dev_key]
            if not dev_files and not self.models:
                return ""

            lines.append("═══════════════════════════════════════════════════════")
            lines.append("INTERFACE CONTRACTS (you MUST use these exact signatures)")
            lines.append("═══════════════════════════════════════════════════════")

            if self.models:
                lines.append("\nSHARED DATA MODELS (defined in shared files — import, do NOT redefine):")
                for m in self.models:
                    lines.append(f"  class {m.name}: {m.fields}  (in {m.file})")

            if dev_files:
                lines.append("\nYOUR FILES:")
                for f in dev_files:
                    lines.append(f"  File: {f.file}")
                    lines.append(f"    Description: {f.description}")
                    if f.imports_from:
                        lines.append(f"    Imports from: {', '.join(f.imports_from)}")
                    if f.exports:
                        lines.append(f"    Must export: {', '.join(f.exports)}")

            other_files = [f for f in self.file_map.values() if f.owner != dev_key]
            if other_files:
                lines.append("\nTEAMMATE FILES (import from these, do NOT rewrite them):")
                for f in other_files:
                    lines.append(f"  {f.file} (owner: {f.owner}) — exports: {', '.join(f.exports)}")

            if self.endpoints:
                lines.append("\nAPI ENDPOINTS (all devs must agree on these signatures):")
                for ep in self.endpoints:
                    req = f" (body: {ep.request_model})" if ep.request_model else ""
                    lines.append(f"  {ep.method} {ep.path}{req} -> {ep.response_model}")

            if self.entry_point:
                lines.append(f"\nENTRY POINT: {self.entry_point}")
                if self.entry_imports:
                    lines.append(f"  Must import: {', '.join(self.entry_imports)}")

            lines.append("═══════════════════════════════════════════════════════")
            return "\n".join(lines)

    def get_full_summary(self) -> str:
        """Return a full contract summary for manager review / validation."""
        with self._lock:
            if not self.models and not self.endpoints and not self.file_map:
                return ""
            lines = ["INTERFACE CONTRACTS:"]
            if self.models:
                lines.append("  Models:")
                for m in self.models:
                    lines.append(f"    {m.name}: {m.fields} (in {m.file})")
            if self.endpoints:
                lines.append("  Endpoints:")
                for ep in self.endpoints:
                    req = f" ({ep.request_model})" if ep.request_model else ""
                    lines.append(f"    {ep.method} {ep.path}{req} -> {ep.response_model}")
            if self.file_map:
                lines.append("  File ownership:")
                for fname, fc in sorted(self.file_map.items()):
                    lines.append(f"    {fname} -> {fc.owner}: {fc.description[:60]}")
            return "\n".join(lines)

    def to_dict(self) -> Dict:
        with self._lock:
            return {
                "endpoints": [{"method": e.method, "path": e.path,
                               "request_model": e.request_model,
                               "response_model": e.response_model} for e in self.endpoints],
                "models": [{"name": m.name, "fields": m.fields, "file": m.file} for m in self.models],
                "files": [{"file": f.file, "owner": f.owner,
                           "imports_from": f.imports_from, "exports": f.exports,
                           "description": f.description} for f in self.file_map.values()],
                "entry_point": self.entry_point,
                "entry_imports": self.entry_imports,
            }


_contracts: Optional[InterfaceContractRegistry] = None
_contracts_lock = threading.Lock()

def get_contracts() -> InterfaceContractRegistry:
    global _contracts
    if _contracts is None:
        with _contracts_lock:
            if _contracts is None:
                _contracts = InterfaceContractRegistry()
    return _contracts

def reset_contracts() -> None:
    global _contracts
    with _contracts_lock:
        _contracts = None


    # ── Amendment API ─────────────────────────────────────────────────────

def _registry_request_amendment(file: str, proposer: str, reason: str, proposed_change: str) -> str:
    """Queue a contract amendment request for manager review."""
    reg = get_contracts()
    import time as _t
    with reg._lock:
        reg._pending_amendments.append({
            "file": file,
            "proposer": proposer,
            "reason": reason,
            "change": proposed_change,
            "ts": _t.time(),
        })
    logger.info(f"[Contracts] Amendment queued by {proposer} for '{file}': {reason[:80]}")
    return (
        f"Amendment queued for manager review.\n"
        f"File: {file}\nReason: {reason}\nProposed: {proposed_change}\n"
        f"The manager will review and broadcast any approved changes to the team."
    )


def _registry_process_amendments(sprint: int) -> List[str]:
    """
    Called by the manager monitor. Reviews all pending amendments, applies them
    to the registry, and returns broadcast messages for each approved one.
    For this implementation all amendments are auto-approved (the Lead trusts agents).
    A future version could LLM-gate approvals.
    """
    reg = get_contracts()
    with reg._lock:
        amendments = list(reg._pending_amendments)
        reg._pending_amendments.clear()
    if not amendments:
        return []
    broadcasts = []
    for am in amendments:
        # Apply: update the file description in file_map if it exists
        with reg._lock:
            fc = reg.file_map.get(am["file"])
            if fc:
                fc.description = f"{fc.description} | AMENDED: {am['change'][:120]}" 
        msg = (
            f"CONTRACT AMENDED by {am['proposer']} for '{am['file']}'. "
            f"Reason: {am['reason']}. Change: {am['change']}. "
            f"Update your imports/exports if this affects you."
        )
        broadcasts.append(msg)
        logger.info(f"[Contracts] Amendment applied for '{am['file']}' proposed by {am['proposer']}")
    return broadcasts


# ── Work Dashboard ────────────────────────────────────────────────────────────

class WorkDashboard:
    """
    Shared coordination layer for agents working in parallel.
    Tracks domain ownership and routes async messages between agents.
    Persists across sprints so agents remember their domains.
    """
    SAVE_PATH = OUTPUT_DIR / "WORK_DASHBOARD.json"

    def __init__(self):
        self.messages: Dict[str, List] = {}
        self._sections: Dict[str, Dict[str, str]] = {}  # filename → {section → content}
        self._lock = threading.RLock()
        self._load()

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
        """Mark this sprint as complete."""
        with self._lock:
            self._save()

    def get_status(self) -> str:
        with self._lock:
            if not self.messages:
                return "Dashboard: no active coordination or messages."
            return "Active coordination dashboard."

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


    # ─────────────────────────────────────────────────────────────────────────────

    def _save(self):
        try:
            self.SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.SAVE_PATH.write_text(
                json.dumps({
                    "messages": self.messages,
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
                logger.info(f"[Dashboard] loaded coordination dashboard")
        except Exception as e:
            logger.warning(f"[Dashboard] load failed: {e}")


_dashboard: Optional[WorkDashboard] = None
_dashboard_lock = threading.Lock()

def get_dashboard() -> WorkDashboard:
    global _dashboard
    if _dashboard is None:
        with _dashboard_lock:
            if _dashboard is None:
                _dashboard = WorkDashboard()
    return _dashboard


# ── Browser Pool ──────────────────────────────────────────────────────────────

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
        page = self._session().get("page")
        try:
            import base64
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


# Per-thread agent identity — each worker thread sets its own context so parallel
# threads don't overwrite each other's agent ID / sprint number.
# Use contextvars instead of threading.local — ContextVar is propagated through
# asyncio tasks AND through asyncio.to_thread(), which threading.local is NOT.
# This ensures agent identity survives LangGraph's internal async/thread machinery.
import contextvars as _cv
_agent_id_ctx:   _cv.ContextVar[str] = _cv.ContextVar("agent_id",   default="")
_sprint_num_ctx: _cv.ContextVar[int] = _cv.ContextVar("sprint_num", default=1)
_task_file_ctx:  _cv.ContextVar[str] = _cv.ContextVar("task_file",  default="")

def _get_agent_id()   -> str: return _agent_id_ctx.get()
def _get_sprint_num() -> int: return _sprint_num_ctx.get()
def _get_task_file()  -> str: return _task_file_ctx.get()
def _set_agent_ctx(agent_id: str, sprint_num: int) -> None:
    _agent_id_ctx.set(agent_id)
    _sprint_num_ctx.set(sprint_num)
def _set_task_file(task_file: str) -> None:
    _task_file_ctx.set(task_file)

# Sprint goal is set once per sprint before any threads start — read-only during execution
_current_sprint_goal: str = ""


def _tool_search_codebase(query: str) -> str:
    """Search for relevant code — own in-progress work first, then merged codebase."""
    agent_id = _get_agent_id()
    label    = f"[search_codebase:{agent_id or 'anon'}]"
    parts: List[str] = []

    # Own worktree RAG (freshest, agent-local)
    if agent_id:
        wt_rag = get_worktree_rag(agent_id)
        if wt_rag is not None:
            wt_files = wt_rag.list_files()
            logger.info(f"{label} worktree RAG has {len(wt_files)} files: {wt_files}")
            own = wt_rag.query(query, top_k=3)
            if own:
                parts.append(f"=== Your in-progress work ===\n{own}")
        else:
            logger.info(f"{label} no worktree RAG for agent")

    # Global merged RAG
    global_chunks = len(get_rag().chunks)
    logger.info(f"{label} global RAG has {global_chunks} chunks  query={query!r:.60}")
    global_result = get_rag().query(query)
    if global_result and not global_result.startswith("[RAG:"):
        parts.append(f"=== Merged codebase ===\n{global_result}")

    logger.info(f"{label} returning {len(parts)} result sections")
    return "\n\n".join(parts) if parts else "[No relevant code found]"


def _tool_list_files() -> str:
    """List all source files — merged codebase plus this agent's own in-progress work."""
    agent_id = _get_agent_id()
    label    = f"[list_files:{agent_id or 'anon'}]"

    # ── merged global files ────────────────────────────────────────────────────
    # Global RAG stores paths as "code/<rel>" (relative to OUTPUT_DIR).
    # Strip the leading "code/" so agents see bare paths like "app/models.py"
    # that can be passed directly to write_code_file / read_file.
    raw_global = get_rag().list_files()
    global_rag_paths: set = (
        set(raw_global.split("\n"))
        if raw_global != "[No files indexed yet]"
        else set()
    )
    # Strip "code/" prefix for display; keep raw set for dedup against worktree
    def _strip_code_prefix(p: str) -> str:
        return p[5:] if p.startswith("code/") else p

    lines = [_strip_code_prefix(p) for p in global_rag_paths]

    logger.info(
        f"{label} OUTPUT_DIR={OUTPUT_DIR.resolve()}  "
        f"global RAG has {len(global_rag_paths)} files"
        + (f": {sorted(lines)}" if lines else " (empty)")
    )

    # ── own worktree files not yet merged ──────────────────────────────────────
    # Worktree paths are already relative to the code/ dir (e.g. "app/models.py").
    # The global RAG stores them as "code/app/models.py", so prepend "code/" for
    # the dedup check, then add the bare path if it's genuinely new.
    wt     = _wt_manager_ctx.get()          # type: ignore[attr-defined]
    wt_own: List[str] = []
    if agent_id and wt is not None:
        wt_dir = wt.get_agent_code_dir(agent_id)
        if wt_dir and wt_dir.exists():
            for p in wt_dir.rglob("*"):
                if not p.is_file() or ".git" in p.parts or "node_modules" in p.parts:
                    continue
                if p.suffix not in _RAG_EXTENSIONS:
                    continue
                rel        = str(p.relative_to(wt_dir)).replace("\\", "/")
                global_key = f"code/{rel}"
                if global_key not in global_rag_paths:
                    lines.append(f"{rel} [in-progress]")
                    wt_own.append(rel)
        logger.info(f"{label} worktree dir={wt_dir}  new in-progress files={wt_own}")
    else:
        logger.info(f"{label} no active worktree (agent_id={agent_id!r}, wt={wt})")

    if not lines:
        return "[No files indexed yet]"
    result = "\n".join(sorted(lines))
    logger.info(f"{label} returning {len(lines)} files total:\n{result}")
    return result


def _tool_validate_python(code: str) -> str:
    try:
        ast.parse(code)
        return "Python syntax OK"
    except SyntaxError as e:
        return f"Syntax error: {e}"


def _tool_validate_json(content: str) -> str:
    try:
        json.loads(content)
        return "JSON valid"
    except json.JSONDecodeError as e:
        return f"JSON error: {e}"


def _tool_validate_yaml(content: str) -> str:
    try:
        parsed = yaml.safe_load(content)
        if parsed is None:
            return "YAML warning: file is empty or contains only comments"
        return "YAML valid"
    except yaml.YAMLError as e:
        return f"YAML error: {e}"


def _tool_generate_endpoint_table(endpoints_json: str) -> str:
    """endpoints_json: JSON list of {method, path, description, auth}"""
    try:
        eps = json.loads(endpoints_json)
        rows = ["| Method | Path | Description | Auth |",
                "|--------|------|-------------|------|"]
        for ep in eps:
            rows.append(
                f"| {ep.get('method','GET')} | `{ep.get('path','/')}` "
                f"| {ep.get('description','')} | {ep.get('auth','no')} |"
            )
        return "\n".join(rows)
    except Exception as e:
        return f"[endpoint table error: {e}]"


def _tool_generate_er_diagram(tables_json: str) -> str:
    """tables_json: JSON list of {name, fields:[{name,type,pk,fk}]}"""
    try:
        tables = json.loads(tables_json)
        lines = []
        for t in tables:
            lines.append(f"┌─ {t['name']} {'─'*(20-len(t['name']))}┐")
            for f in t.get("fields", []):
                pk = " PK" if f.get("pk") else ""
                fk = f" → {f['fk']}" if f.get("fk") else ""
                lines.append(f"│  {f['name']:<12} {f['type']:<10}{pk}{fk}")
            lines.append("└" + "─"*22 + "┘")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"[ER diagram error: {e}]"


def _tool_create_ascii_diagram(components_json: str) -> str:
    """components_json: JSON list of {name, connects_to:[names]}"""
    try:
        comps = json.loads(components_json)
        lines = []
        for c in comps:
            name = c["name"]
            conns = c.get("connects_to", [])
            lines.append(f"[{name}]")
            for conn in conns:
                lines.append(f"  └──► [{conn}]")
        return "\n".join(lines)
    except Exception as e:
        return f"[diagram error: {e}]"


def _tool_create_user_flow(steps_json: str) -> str:
    """steps_json: JSON list of {step, action, outcome}"""
    try:
        steps = json.loads(steps_json)
        lines = []
        for i, s in enumerate(steps):
            prefix = "START → " if i == 0 else "      → "
            lines.append(f"{prefix}[{s['step']}]")
            lines.append(f"         Action:  {s.get('action','')}")
            lines.append(f"         Outcome: {s.get('outcome','')}")
            if i < len(steps) - 1:
                lines.append("           |")
        return "\n".join(lines)
    except Exception as e:
        return f"[user flow error: {e}]"


def _tool_create_wireframe(page_name: str, sections_json: str) -> str:
    """sections_json: JSON list of {name, type, content}"""
    try:
        sections = json.loads(sections_json)
        width = 52
        border = "+" + "─" * width + "+"
        lines = [border, f"|  PAGE: {page_name:<{width-9}}|", border]
        for s in sections:
            label = f"  [{s['type'].upper()}] {s['name']}"
            lines.append(f"|{label:<{width}}|")
            if s.get("content"):
                for line in textwrap.wrap(s["content"], width - 4):
                    lines.append(f"|    {line:<{width-4}}|")
            lines.append(f"|{'·'*width}|")
        lines.append(border)
        return "\n".join(lines)
    except Exception as e:
        return f"[wireframe error: {e}]"


def _tool_create_style_guide(guide_json: str) -> str:
    """guide_json: {colors:{name:hex}, fonts:{role:family}, spacing:{name:value}}"""
    try:
        g = json.loads(guide_json)
        lines = ["## Style Guide", ""]
        if "colors" in g:
            lines += ["### Colors", "| Name | Value |", "|------|-------|"]
            for name, val in g["colors"].items():
                lines.append(f"| {name} | `{val}` |")
            lines.append("")
        if "fonts" in g:
            lines += ["### Typography", "| Role | Font |", "|------|------|"]
            for role, fam in g["fonts"].items():
                lines.append(f"| {role} | {fam} |")
            lines.append("")
        if "spacing" in g:
            lines += ["### Spacing Scale", "| Token | Value |", "|-------|-------|"]
            for tok, val in g["spacing"].items():
                lines.append(f"| {tok} | {val} |")
        return "\n".join(lines)
    except Exception as e:
        return f"[style guide error: {e}]"


def _tool_scan_vulnerabilities(code: str) -> str:
    patterns = [
        (r"eval\s*\(",             "HIGH",   "eval() — arbitrary code execution"),
        (r"exec\s*\(",             "HIGH",   "exec() — arbitrary code execution"),
        (r"os\.system\s*\(",       "HIGH",   "os.system() — shell injection risk"),
        (r"subprocess\.call\s*\(", "MEDIUM", "subprocess without shell=False check"),
        (r"password\s*=\s*['\"]",  "HIGH",   "hardcoded password literal"),
        (r"secret\s*=\s*['\"]",    "HIGH",   "hardcoded secret literal"),
        (r"md5\s*\(",               "MEDIUM", "MD5 — weak hash, use SHA-256+"),
        (r"sha1\s*\(",              "MEDIUM", "SHA-1 — weak hash, use SHA-256+"),
        (r"SELECT.+\+",             "HIGH",   "possible SQL injection via string concat"),
        (r"innerHTML\s*=",          "MEDIUM", "innerHTML — potential XSS"),
        (r"document\.write\s*\(",   "MEDIUM", "document.write — potential XSS"),
        (r"verify\s*=\s*False",     "HIGH",   "SSL verification disabled"),
        (r"DEBUG\s*=\s*True",       "MEDIUM", "debug mode enabled in production"),
    ]
    findings = []
    for pattern, severity, desc in patterns:
        matches = re.findall(pattern, code, re.IGNORECASE)
        if matches:
            findings.append(f"[{severity}] {desc} ({len(matches)} occurrence(s))")
    return "\n".join(findings) if findings else "No obvious vulnerabilities detected"


_RUN_SHELL_TIMEOUT = 120   # seconds; raised from 30 so build commands (npm, pip, go) don't get killed

def _tool_run_shell(command: str) -> str:
    """Run a shell command in the output directory and return stdout + stderr (last 3000 chars)."""
    import subprocess
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_RUN_SHELL_TIMEOUT,
            cwd=str(_get_code_dir()),
            encoding="utf-8",
            errors="replace",
        )
        out = (result.stdout or "") + (result.stderr or "")
        out = out[-3000:] if len(out) > 3000 else out
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return (
            f"ERROR: command timed out after {_RUN_SHELL_TIMEOUT}s. "
            "To start a long-running server use start_service(), not run_shell()."
        )
    except Exception as e:
        return f"ERROR: {e}"


# ── Background service registry (start_service / stop_service) ───────────────
_services: Dict[str, object] = {}        # name → subprocess.Popen
_services_ports: Dict[str, int] = {}     # name → port
_services_lock = threading.Lock()

def _extract_port(command: str) -> Optional[int]:
    """Try to extract a port number from a command string."""
    import re
    m = re.search(r'(?:--port|-p|:)\s*(\d{4,5})\b', command)
    if m:
        return int(m.group(1))
    # http.server 8000 / uvicorn app:app --port 8080 style
    m = re.search(r'\b(8\d{3}|9\d{3}|3000|4000|5000)\b', command)
    return int(m.group(1)) if m else None

def _kill_proc_tree(proc) -> None:
    """Kill a process and all its children (cross-platform)."""
    import signal as _signal
    try:
        import psutil
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except Exception:
                pass
        proc.kill()
    except ImportError:
        # psutil not available — fall back to simple kill
        try:
            if sys.platform == "win32":
                import subprocess as _sp
                _sp.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                         stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            else:
                import os, signal as _signal
                os.killpg(os.getpgid(proc.pid), _signal.SIGKILL)
        except Exception:
            proc.kill()
    except Exception:
        proc.kill()


def _tool_start_service(name: str, command: str) -> str:
    """Start a long-running process (server/worker) in the background. Returns startup output."""
    import subprocess, time, queue, threading as _th
    with _services_lock:
        if name in _services and _services[name].poll() is None:
            return f"[{name}] already running (pid={_services[name].pid})"
        # Check port conflict
        port = _extract_port(command)
        if port:
            for svc_name, svc_port in _services_ports.items():
                if svc_port == port and svc_name in _services and _services[svc_name].poll() is None:
                    return (
                        f"PORT CONFLICT: port {port} is already used by service '{svc_name}'. "
                        f"Choose a different port or stop '{svc_name}' first with stop_service('{svc_name}')."
                    )
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(OUTPUT_DIR / "code"),
        )
        time.sleep(2)   # let the process boot
        # Collect early output non-blocking via a drain thread (works on all platforms)
        output_lines: list = []
        q: queue.Queue = queue.Queue()

        def _drain():
            for line in iter(proc.stdout.readline, ""):
                q.put(line.rstrip())

        _th.Thread(target=_drain, daemon=True).start()
        deadline = time.time() + 1.5
        while time.time() < deadline:
            try:
                output_lines.append(q.get_nowait())
            except queue.Empty:
                time.sleep(0.05)
        with _services_lock:
            _services[name] = proc
            if port:
                _services_ports[name] = port   # populate so port-conflict detection works
        status = "running" if proc.poll() is None else f"exited (rc={proc.returncode})"
        early = "\n".join(output_lines[-20:]) if output_lines else "(no output yet)"
        return f"[{name}] started (pid={proc.pid}, port={port}, status={status})\n{early}"
    except Exception as e:
        return f"ERROR starting service '{name}': {e}"


def _tool_stop_service(name: str) -> str:
    """Stop a background service previously started with start_service()."""
    import time
    with _services_lock:
        proc = _services.pop(name, None)
        _services_ports.pop(name, None)
    if proc is None:
        return f"[{name}] not found — either never started or already stopped"
    if proc.poll() is not None:
        return f"[{name}] already exited (rc={proc.returncode})"
    try:
        _kill_proc_tree(proc)
        try:
            rc = proc.wait(timeout=5)
        except Exception:
            rc = proc.returncode
        return f"[{name}] stopped (rc={rc})"
    except Exception as e:
        return f"ERROR stopping service '{name}': {e}"


def _atexit_stop_all_services() -> None:
    """Ensure all tracked background services are killed when the interpreter exits."""
    with _services_lock:
        names = list(_services.keys())
    for name in names:
        try:
            _tool_stop_service(name)
        except Exception:
            pass


import atexit as _atexit
_atexit.register(_atexit_stop_all_services)


def _tool_http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request and return status code + response body (first 2000 chars)."""
    try:
        import requests as _requests
        method = method.upper()
        headers = {"Content-Type": "application/json"}
        resp = _requests.request(
            method, url,
            data=body or None,
            headers=headers,
            timeout=15,
        )
        text = resp.text[:2000]
        return f"HTTP {resp.status_code}\n{text}"
    except Exception as e:
        return f"ERROR: {e}"


def _tool_check_owasp(feature: str) -> str:
    checklist = {
        "auth":        ["A01: Broken Access Control", "A02: Cryptographic Failures",
                        "A07: Identification and Authentication Failures"],
        "api":         ["A01: Broken Access Control", "A03: Injection",
                        "A05: Security Misconfiguration"],
        "input":       ["A03: Injection", "A06: Vulnerable Components"],
        "session":     ["A02: Cryptographic Failures", "A07: Auth Failures"],
        "file_upload": ["A03: Injection", "A04: Insecure Design"],
        "database":    ["A03: Injection", "A02: Cryptographic Failures"],
    }
    feature_lower = feature.lower()
    relevant = []
    for key, risks in checklist.items():
        if key in feature_lower or feature_lower in key:
            relevant.extend(risks)
    if not relevant:
        relevant = ["A01: Broken Access Control", "A03: Injection", "A05: Security Misconfiguration"]
    return "Relevant OWASP Top 10 risks:\n" + "\n".join(f"  • {r}" for r in set(relevant))


# ── Native Anthropic tool registry ───────────────────────────────────────────
# Tools are plain Python functions registered in _TOOL_CALLABLES.
# JSON schemas are generated automatically from signatures + docstrings.

_TOOL_CALLABLES: Dict[str, Callable] = {}


def _register_tool(fn: Callable) -> Callable:
    """Register a Python function as an Anthropic tool (replaces @lc_tool)."""
    _TOOL_CALLABLES[fn.__name__] = fn
    return fn


def _py_type_to_json_schema(annotation) -> dict:
    """Convert a Python type annotation to a JSON Schema property dict."""
    if annotation is inspect.Parameter.empty or annotation is None:
        return {"type": "string"}
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        args = getattr(annotation, "__args__", (None,))
        item_schema = _py_type_to_json_schema(args[0]) if args and args[0] else {}
        return {"type": "array", "items": item_schema}
    if origin is dict:
        return {"type": "object"}
    _SIMPLE: Dict[type, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}
    if annotation in _SIMPLE:
        return {"type": _SIMPLE[annotation]}
    return {"type": "string"}


def _make_anthropic_tool_def(fn: Callable) -> dict:
    """Build a native Anthropic tool definition dict from a function's signature + docstring."""
    try:
        hints = {}
        try:
            hints = {k: v for k, v in fn.__annotations__.items() if k != "return"}
        except Exception:
            pass
        sig = inspect.signature(fn)
        props: Dict[str, dict] = {}
        required: List[str] = []
        for name, param in sig.parameters.items():
            annotation = hints.get(name, inspect.Parameter.empty)
            schema = _py_type_to_json_schema(annotation)
            schema["description"] = name
            props[name] = schema
            if param.default is inspect.Parameter.empty:
                required.append(name)
        return {
            "name": fn.__name__,
            "description": (fn.__doc__ or fn.__name__).strip()[:500],
            "input_schema": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        }
    except Exception as e:
        logger.warning(f"[tool-def] Failed to build schema for {fn.__name__}: {e}")
        return {
            "name": fn.__name__,
            "description": (fn.__doc__ or fn.__name__).strip()[:500],
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }


def get_role_anthropic_tools(role_key: str) -> List[dict]:
    """Return a list of Anthropic tool definition dicts for the given role."""
    names = _ROLE_TOOL_NAMES.get(role_key, [])
    missing = [n for n in names if n not in _TOOL_CALLABLES]
    if missing:
        logger.warning(f"[{role_key}] tools not found in registry (skipped): {missing}")
    return [_make_anthropic_tool_def(_TOOL_CALLABLES[n]) for n in names if n in _TOOL_CALLABLES]


@_register_tool
def run_shell(command: str) -> str:
    """Run a shell command in the project output directory. Use to start services, install deps,
    run tests, or verify the app boots. Returns combined stdout+stderr."""
    return _tool_run_shell(command)

@_register_tool
def http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request to a running service. method: GET/POST/PUT/DELETE.
    body: JSON string for POST/PUT. Returns HTTP status + response body."""
    return _tool_http_request(method, url, body)

@_register_tool
def start_service(name: str, command: str) -> str:
    """Start a long-running background process (server, worker, etc.) and return its startup output.
    name: a label you pick (e.g. 'api', 'frontend') — used to stop it later.
    command: the shell command to launch it (e.g. 'python server.py', 'node index.js').
    Always call stop_service(name) when you're done testing."""
    return _tool_start_service(name, command)

@_register_tool
def stop_service(name: str) -> str:
    """Stop a background service started with start_service(name).
    Always stop services when done — leaving them running blocks ports for teammates."""
    return _tool_stop_service(name)

@_register_tool
def write_code_file(filename: str, content: str) -> str:
    """Write source code to company_output/code/<filename>. Content is the complete file text."""
    return _tool_write_code_file(filename, content)

@_register_tool
def write_file_section(filename: str, section: str, content: str) -> str:
    """Write your code to a specific SECTION of a shared file (like main.py or models.py).
    Use this instead of write_code_file when the file has section-based ownership.
    filename: the shared file path (e.g. 'backend/app/main.py')
    section: section name — use your assigned section or create one with your feature name
    content: the code for JUST this section (not the whole file)"""
    filename = _strip_subdir_prefix(filename, "code")
    agent_id = _get_agent_id()
    dashboard = get_dashboard()

    err = dashboard.write_section(filename, section, agent_id, content)
    if err:
        logger.warning(f"[write_file_section] {agent_id} → {filename}:{section} — {err}")
        return err

    code_dir = _get_code_dir()
    path = code_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    assembled = dashboard.assemble_shared_file(filename)
    path.write_text(assembled, encoding="utf-8")
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    logger.info(f"[write_file_section] {agent_id} wrote section '{section}' in {filename} ({len(content)}c)")
    return (
        f"Written section '{section}' ({len(content)}c) to shared file code/{filename}. "
        f"The assembled file is {len(assembled)}c total."
    )

@_register_tool
def write_test_file(filename: str, content: str) -> str:
    """Write a test file to company_output/tests/<filename>. Content is the complete file text."""
    return _tool_write_test_file(filename, content)

@_register_tool
def write_design_file(filename: str, content: str) -> str:
    """Write a design artifact (markdown, spec) to company_output/design/<filename>."""
    return _tool_write_design_file(filename, content)

@_register_tool
def write_config_file(filename: str, content: str) -> str:
    """Write a config or infra file (Dockerfile, YAML, requirements.txt) to company_output/config/<filename>."""
    return _tool_write_config_file(filename, content)

@_register_tool
def read_file(filename: str) -> str:
    """Read an existing file from any company_output/ subdirectory."""
    return _tool_read_file(filename)

@_register_tool
def list_files() -> str:
    """List all source files currently in the project codebase. Call this before writing any file
    to see what already exists. Returns filenames grouped by subdirectory."""
    return _tool_list_files()

@_register_tool
def search_codebase(query: str) -> str:
    """Semantic search over the entire codebase. Returns the most relevant code chunks for your query.
    Use this to find existing implementations before writing new code — e.g. 'authentication middleware',
    'WebSocket handler', 'database models'. Prevents duplicate implementations."""
    return _tool_search_codebase(query)

@_register_tool
def check_dashboard() -> str:
    """MANDATORY FIRST STEP. See current team messages and coordination status.
    Call this to read any incoming messages from teammates."""
    return get_dashboard().get_status()

@_register_tool
def message_teammate(teammate_role: str, message: str) -> str:
    """Send an async message to a teammate. They receive it in Round 2.
    Use in Round 1 to ask about interfaces, warn about dependencies, or request clarification.
    teammate_role: the role key of the recipient e.g. 'frontend_developer', 'devops_engineer'"""
    return get_dashboard().send_message(
        _get_agent_id(), teammate_role, message, _get_sprint_num()
    )

@_register_tool
def check_messages() -> str:
    """MANDATORY FIRST STEP IN ROUND 2. Read messages sent to you by teammates in Round 1.
    Contains interface questions and compatibility concerns you must address."""
    return get_dashboard().get_messages(_get_agent_id())

@_register_tool
def broadcast_message(message: str) -> str:
    """Shout a message to ALL teammates at once — use this when you make a breaking change
    that affects everyone (e.g. renamed a function, changed a shared model, moved a file).
    Every agent will receive it in their next check_messages() call.
    message: plain text description of the change and what others must update."""
    return get_dashboard().broadcast(
        _get_agent_id(), message, _get_sprint_num(), ENG_WORKERS
    )

@_register_tool
def request_contract_amendment(file: str, reason: str, proposed_change: str) -> str:
    """Request a mid-flight change to the shared Interface Contract.
    Use this when you discover the original contract is wrong or impossible to implement
    (e.g. a dependency is unavailable, the API must change shape, a model needs a new field).
    The Engineering Manager will review and broadcast the approved change to the whole team.
    file: the filename in the contract that needs changing (e.g. 'models.py', 'routes.py')
    reason: why the current contract is wrong or insufficient
    proposed_change: exactly what should change (e.g. 'Add field user_id: int to Note model')"""
    return _registry_request_amendment(
        file=file,
        proposer=_get_agent_id() or "unknown",
        reason=reason,
        proposed_change=proposed_change,
    )

@_register_tool
def open_app(url: str) -> str:
    """Open a browser and navigate to a URL to visually verify your feature.
    Acquires one of 3 browser pool slots (waits if all busy). ALWAYS call close_browser() when done.
    url: full URL e.g. 'http://localhost:3000/login' or 'http://localhost:8000/docs'"""
    return get_browser_pool().acquire(url)

@_register_tool
def browser_action(action: str, selector: str, value: str = "") -> str:
    """Interact with the open browser page and see what is on screen.
    action: 'click' | 'type' | 'navigate' | 'screenshot'
    selector: CSS selector for click/type (e.g. 'button[type=submit]', '#email') or URL for navigate
    value: text to type (only for 'type' action)
    Must call open_app() first."""
    return get_browser_pool().action(action, selector, value)

@_register_tool
def close_browser() -> str:
    """Close the browser and release the pool slot so teammates can use it.
    ALWAYS call this when done — not calling it blocks other agents from getting a browser."""
    return get_browser_pool().release()

@_register_tool
def launch_application(command: str) -> str:
    """Start a desktop program or OS \"open\" command without waiting for it to exit.

    Disabled unless AGENT_LAUNCH_APPS_ENABLED=1 — same shell privileges as your user account.

    *command* uses shell=True. Examples: Windows ``notepad``, ``calc``,
    ``start msedge https://example.com``; macOS ``open -a TextEdit``; Linux ``xdg-open path``.

    Process is detached; stdout/stderr are not captured. The model cannot see the GUI window;
    for web pages use open_app() + browser_action().
    """
    if not AGENT_LAUNCH_APPS_ENABLED:
        return (
            "ERROR: launch_application is disabled. Set AGENT_LAUNCH_APPS_ENABLED=1 in the "
            "environment (e.g. .env). Warning: agents can run any shell command you can."
        )
    cmd = (command or "").strip()
    if not cmd:
        return "ERROR: empty command"
    try:
        import subprocess
        home = str(Path.home())
        if sys.platform == "win32":
            _detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            _newgrp = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=False,
                cwd=home,
                creationflags=_detached | _newgrp,
            )
        else:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                cwd=home,
                start_new_session=True,
            )
        logger.info(f"[launch_application] pid={proc.pid} cmd={cmd[:300]!r}")
        return (
            f"Started detached process pid={proc.pid}. "
            f"No output captured; the agent cannot see the app window. "
            f"For web UIs use open_app + browser_action."
        )
    except Exception as e:
        logger.warning(f"[launch_application] failed: {e}", exc_info=True)
        return f"ERROR: {e}"

@_register_tool
def desktop_screenshot() -> str:
    """Take a full-screen screenshot and return a Gemini vision description of what is visible.
    Call before and after desktop_mouse/desktop_keyboard actions to verify the result.
    Returns: resolution, cursor position, and a natural-language description of the screen.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1 in the environment."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment (e.g. .env). Warning: agents will be able to see and control your screen."
        )
    try:
        import pyautogui
        import base64, io
        screen_w, screen_h = pyautogui.size()
        cx, cy = pyautogui.position()
        img = pyautogui.screenshot()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        try:
            resp = get_client().models.generate_content(
                model=GEMINI_MODEL,
                contents=[{
                    "parts": [
                        {"text": (
                            "Describe what is visible on this screenshot in detail: "
                            "list all open windows, visible text, UI elements, and their positions. "
                            "If you see an application, name it. Be specific and concise."
                        )},
                        {"inline_data": {"mime_type": "image/png", "data": img_b64}},
                    ]
                }],
            )
            vision = resp.text.strip()
        except Exception as e:
            vision = f"(vision unavailable: {e})"
        return (
            f"Screen: {screen_w}x{screen_h}  Cursor: ({cx},{cy})\n"
            f"Visible: {vision}"
        )
    except ImportError:
        return (
            "ERROR: pyautogui is not installed. Run: pip install pyautogui\n"
            "Linux may also need: sudo apt-get install python3-xlib python3-tk"
        )
    except Exception as e:
        logger.warning(f"[desktop_screenshot] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_mouse(
    action: str,
    x: int = -1,
    y: int = -1,
    button: str = "left",
    clicks: int = 1,
    scroll_direction: str = "down",
) -> str:
    """Control the mouse anywhere on screen.
    action: 'move' | 'click' | 'double_click' | 'right_click' | 'scroll'
    x, y: screen coordinates in pixels from the top-left corner (-1 = current cursor position)
    button: 'left' | 'right' | 'middle'  (for click actions)
    clicks: number of scroll ticks  (only for 'scroll')
    scroll_direction: 'up' | 'down'  (only for 'scroll')
    Call desktop_screenshot() afterwards to see what changed.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow mouse control."
        )
    try:
        import pyautogui, time
        pyautogui.FAILSAFE = True   # move to corner to abort
        act = (action or "").strip().lower()
        # Resolve coordinates — -1 means stay at current position
        cur_x, cur_y = pyautogui.position()
        tx = cur_x if x < 0 else x
        ty = cur_y if y < 0 else y

        if act == "move":
            pyautogui.moveTo(tx, ty, duration=0.2)
        elif act == "click":
            pyautogui.click(tx, ty, button=button)
        elif act == "double_click":
            pyautogui.doubleClick(tx, ty)
        elif act == "right_click":
            pyautogui.rightClick(tx, ty)
        elif act == "scroll":
            pyautogui.moveTo(tx, ty, duration=0.1)
            amount = clicks if scroll_direction == "up" else -clicks
            pyautogui.scroll(amount)
        else:
            return f"ERROR: unknown action {action!r}. Use: move | click | double_click | right_click | scroll"

        time.sleep(0.35)   # give OS time to render
        nx, ny = pyautogui.position()
        logger.info(f"[desktop_mouse] {act} at ({tx},{ty}) button={button}")
        return f"Done: {act} at ({tx},{ty}). Cursor now at ({nx},{ny}). Call desktop_screenshot() to see the result."
    except ImportError:
        return "ERROR: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as e:
        logger.warning(f"[desktop_mouse] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def desktop_keyboard(action: str, text: str = "", keys: str = "") -> str:
    """Type text or press keyboard shortcuts on the currently focused window.
    action: 'type' | 'hotkey' | 'press'
      'type'   → types text character by character (use for filling in fields)
      'hotkey' → holds keys simultaneously, e.g. keys='ctrl,c' for copy, 'ctrl,z' for undo
      'press'  → taps one or more keys sequentially, e.g. keys='enter' or keys='tab,tab,enter'
    text: the string to type  (only for 'type')
    keys: comma-separated key names  (for 'hotkey' and 'press')
    Key names: enter, tab, space, backspace, delete, escape, up, down, left, right,
               f1..f12, ctrl, alt, shift, win, a..z, 0..9, etc.
    Call desktop_screenshot() first to confirm focus on the right field.
    Requires AGENT_DESKTOP_CONTROL_ENABLED=1."""
    if not AGENT_DESKTOP_CONTROL_ENABLED:
        return (
            "ERROR: desktop control is disabled. Set AGENT_DESKTOP_CONTROL_ENABLED=1 in the "
            "environment to allow keyboard control."
        )
    try:
        import pyautogui, time
        act = (action or "").strip().lower()
        if act == "type":
            if not text:
                return "ERROR: 'text' is required for action='type'"
            pyautogui.write(text, interval=0.03)
            time.sleep(0.1)
            logger.info(f"[desktop_keyboard] type {len(text)} chars")
            return f"Typed {len(text)} characters. Call desktop_screenshot() to verify."
        elif act == "hotkey":
            if not keys:
                return "ERROR: 'keys' is required for action='hotkey' (e.g. 'ctrl,c')"
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
            pyautogui.hotkey(*key_list)
            time.sleep(0.2)
            logger.info(f"[desktop_keyboard] hotkey {key_list}")
            return f"Pressed hotkey: {'+'.join(key_list)}. Call desktop_screenshot() to verify."
        elif act == "press":
            if not keys:
                return "ERROR: 'keys' is required for action='press' (e.g. 'enter' or 'tab,tab,enter')"
            key_list = [k.strip() for k in keys.split(",") if k.strip()]
            for k in key_list:
                pyautogui.press(k)
                time.sleep(0.05)
            logger.info(f"[desktop_keyboard] press {key_list}")
            return f"Pressed key(s): {', '.join(key_list)}. Call desktop_screenshot() to verify."
        else:
            return f"ERROR: unknown action {action!r}. Use: type | hotkey | press"
    except ImportError:
        return "ERROR: pyautogui is not installed. Run: pip install pyautogui"
    except Exception as e:
        logger.warning(f"[desktop_keyboard] failed: {e}", exc_info=True)
        return f"ERROR: {e}"


@_register_tool
def validate_python(code: str) -> str:
    """Check Python code for syntax errors. Returns 'Python syntax OK' or a description of the error."""
    return _tool_validate_python(code)

@_register_tool
def validate_json(content: str) -> str:
    """Validate a JSON string. Returns 'JSON valid' or error details."""
    return _tool_validate_json(content)

@_register_tool
def validate_yaml(content: str) -> str:
    """Validate a YAML string (Dockerfile, CI config, etc.). Returns 'YAML valid' or error details."""
    return _tool_validate_yaml(content)

@_register_tool
def generate_endpoint_table(endpoints: List[Dict]) -> str:
    """Generate a markdown table of API endpoints. Each endpoint needs: method, path, description, auth."""
    return _tool_generate_endpoint_table(json.dumps(endpoints))

@_register_tool
def generate_er_diagram(tables: List[Dict]) -> str:
    """Generate an ASCII ER diagram. Each table needs: name, fields (list of {name, type, pk, fk})."""
    return _tool_generate_er_diagram(json.dumps(tables))

@_register_tool
def create_ascii_diagram(components: List[Dict]) -> str:
    """Generate an ASCII component diagram. Each component needs: name, connects_to (list of names)."""
    return _tool_create_ascii_diagram(json.dumps(components))

@_register_tool
def create_user_flow(steps: List[Dict]) -> str:
    """Generate an ASCII user flow diagram. Each step needs: step (label), action, outcome."""
    return _tool_create_user_flow(json.dumps(steps))

@_register_tool
def create_wireframe(page_name: str, sections: List[Dict]) -> str:
    """Generate an ASCII wireframe for a UI page. Each section needs: name, type, content."""
    return _tool_create_wireframe(page_name, json.dumps(sections))

@_register_tool
def create_style_guide(colors: Dict, fonts: Dict, spacing: Dict) -> str:
    """Generate a formatted style guide. colors/fonts/spacing are dicts of token→value."""
    return _tool_create_style_guide(json.dumps({"colors": colors, "fonts": fonts, "spacing": spacing}))

@_register_tool
def scan_vulnerabilities(code: str) -> str:
    """Scan code for common security vulnerabilities (OWASP patterns). Returns severity-labelled findings."""
    return _tool_scan_vulnerabilities(code)

@_register_tool
def check_owasp(feature: str) -> str:
    """Get relevant OWASP Top 10 risks for a feature. Feature: auth, api, input, session, file_upload, database."""
    return _tool_check_owasp(feature)

# Dashboard tools available to all roles that write or review work
_DASHBOARD_TOOLS    = ["check_dashboard", "message_teammate", "check_messages",
                       "broadcast_message", "request_contract_amendment"]
_DASHBOARD_RO_TOOLS = ["check_dashboard", "message_teammate", "check_messages"]  # read-only for QA/arch

_ROLE_TOOL_NAMES: Dict[str, List[str]] = {
    "system_designer":    ["create_ascii_diagram", "write_design_file", "read_file",
                           "list_files", "search_codebase"] + _DASHBOARD_RO_TOOLS,
    "api_designer":       ["generate_endpoint_table", "validate_yaml", "write_design_file",
                           "read_file", "list_files", "search_codebase"] + _DASHBOARD_RO_TOOLS,
    "db_designer":        ["generate_er_diagram", "write_design_file", "read_file",
                           "list_files", "search_codebase"] + _DASHBOARD_RO_TOOLS,
    "ux_researcher":      ["create_user_flow", "write_design_file", "read_file",
                           "list_files", "search_codebase"] + _DASHBOARD_RO_TOOLS,
    "ui_designer":        ["create_wireframe", "write_design_file", "read_file",
                           "list_files", "search_codebase"] + _DASHBOARD_RO_TOOLS,
    "visual_designer":    ["create_style_guide", "write_design_file", "read_file",
                           "list_files", "search_codebase"] + _DASHBOARD_RO_TOOLS,
    "unit_tester":        ["write_test_file", "validate_python", "scan_vulnerabilities",
                           "run_shell", "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser", "launch_application",
                           "desktop_screenshot", "desktop_mouse", "desktop_keyboard"] + _DASHBOARD_RO_TOOLS,
    "integration_tester": ["write_test_file", "validate_python", "validate_json", "run_shell",
                           "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser", "launch_application",
                           "desktop_screenshot", "desktop_mouse", "desktop_keyboard"] + _DASHBOARD_RO_TOOLS,
    "security_auditor":   ["write_test_file", "scan_vulnerabilities", "check_owasp", "run_shell",
                           "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser", "launch_application",
                           "desktop_screenshot", "desktop_mouse", "desktop_keyboard"] + _DASHBOARD_RO_TOOLS,
}
_DEV_TOOL_NAMES = ["write_code_file", "write_file_section", "write_test_file",
                   "validate_python", "validate_json",
                   "validate_yaml", "write_config_file", "read_file", "run_shell",
                   "list_files", "search_codebase", "start_service", "stop_service",
                   "http_request", "open_app", "browser_action", "close_browser", "launch_application",
                   "desktop_screenshot", "desktop_mouse", "desktop_keyboard",
                   # Full dashboard / messaging suite — Gemini SDK raises KeyError
                   # if the model tries to call a function that isn't in the tool list,
                   # so all known tools must be registered even if prompts de-emphasise them.
                   "check_dashboard", "check_messages",
                   "message_teammate", "broadcast_message", "request_contract_amendment"]

# Subset used on retries after a no-write round — read/browse/poll tools stripped
# so the model has no choice but to write.
_DEV_WRITE_ONLY_TOOL_NAMES = [
    "write_code_file", "write_file_section", "write_test_file",
    "write_config_file", "validate_python", "validate_json", "validate_yaml",
    "run_shell", "start_service", "stop_service",
]

def _dev_tools_for_attempt(role_key: str, retry_count: int) -> List[str]:
    """Return the appropriate tool list for a dev agent.
    Always returns the full toolset — narrowing to write-only caused the model to
    attempt calling list_files anyway; Gemini AFC rejects those unknown function
    calls silently, burning all 25 rounds with 0 Python invocations.
    Instead, retries inject file content directly into the prompt so the model
    already has context and doesn't need to call list_files.
    """
    if not role_key.startswith("dev_"):
        return _ROLE_TOOL_NAMES.get(role_key, [])
    return _DEV_TOOL_NAMES

# Engineering manager gets full file access + service tools for integration pass
_ENG_MANAGER_TOOL_NAMES = [
    "read_file", "list_files", "search_codebase",
    "write_code_file", "write_config_file",
    "validate_python", "validate_json", "validate_yaml",
    "run_shell", "start_service", "stop_service", "http_request", "launch_application",
    "desktop_screenshot", "desktop_mouse", "desktop_keyboard",
] + _DASHBOARD_RO_TOOLS


def get_role_lc_tools(role_key: str) -> List[dict]:
    """Return list of Anthropic tool definition dicts for this role (alias for get_role_anthropic_tools)."""
    return get_role_anthropic_tools(role_key)


# ── Gemini native function-calling agentic loop ───────────────────────────────
def _run_with_tools(
    prompt: str,
    role_key: str,
    label: str,
    retry_count: int = 0,
) -> Tuple[str, List[str], float]:
    """
    Run a prompt through Gemini's native automatic function-calling chat session.
    System instruction is pinned once in chat config and never re-injected.
    Conversation history is maintained as structured Content objects by the SDK —
    no string concatenation, no JSON parsing, no regex.
    Returns (final_text, tool_result_strings, perplexity_estimate).
    """
    from google.genai import types as _gtypes
    import concurrent.futures as _cf

    _AGENT_TIMEOUT = 240
    _MAX_AGENT_RETRIES = 3
    _MAX_TOOL_CALLS = 24 if role_key.startswith("dev_") else 100

    # Thread-safe invocation log shared between the wrapper closures and _run_loop.
    _tool_invocations: List[str] = []
    _tool_inv_lock = threading.Lock()

    def _run_loop() -> Tuple[str, List[str]]:
        names    = _dev_tools_for_attempt(role_key, retry_count)
        tool_fns = [_TOOL_CALLABLES[n] for n in names if n in _TOOL_CALLABLES]
        system   = _worker_system(role_key) + "\n\n" + _SYSTEM_AGENT

        # Wrap each tool callable so we can count and log actual invocations.
        # AFC resolves tool calls internally — the final response has no
        # function_call parts, so response-inspection always reports 0.
        _consec_list_files = [0]   # mutable so inner closure can mutate it

        def _make_counted(fn):
            import typing as _typing_mod

            def _wrapper(*args, **kwargs):
                arg_repr = str(kwargs or args)[:200]
                # Registered tools have names like "list_files", "write_code_file" (no _tool_ prefix)
                is_list = fn.__name__ == "list_files"
                with _tool_inv_lock:
                    if is_list:
                        _consec_list_files[0] += 1
                        run_n = _consec_list_files[0]
                    else:
                        _consec_list_files[0] = 0
                        run_n = 0
                if is_list:
                    logger.warning(
                        f"  [{label}] list_files called (consecutive #{run_n})"
                    )
                try:
                    result = fn(*args, **kwargs)
                    entry = f"[TOOL: {fn.__name__}] {arg_repr}"
                    with _tool_inv_lock:
                        _tool_invocations.append(entry)
                    if is_list:
                        logger.info(
                            f"  [{label}] list_files result →\n{result}"
                        )
                    else:
                        logger.info(f"  [{label}] tool {fn.__name__}: {arg_repr[:80]}")
                    return result
                except Exception as _tool_err:
                    entry = f"[TOOL ERROR: {fn.__name__}] {arg_repr} → {_tool_err}"
                    with _tool_inv_lock:
                        _tool_invocations.append(entry)
                    logger.error(f"  [{label}] tool {fn.__name__} RAISED: {_tool_err}")
                    raise

            # Copy identity attributes manually.
            # IMPORTANT: do NOT use functools.wraps() or set __wrapped__ = fn.
            # `from __future__ import annotations` (PEP 563) makes all
            # annotations in this module strings.  In Python 3.14 inspect.signature()
            # no longer evaluates those strings, so they stay as e.g. `'str'`.
            # The Gemini AFC code calls isinstance(value, param.annotation) which
            # then fails with "isinstance() arg 2 must be a type" because 'str'
            # is a string, not a type.  Setting __wrapped__ would cause
            # inspect.signature() to follow it and hit the same problem.
            # Instead we build an explicit __signature__ with fully-evaluated
            # type objects sourced from typing.get_type_hints().
            _wrapper.__name__ = fn.__name__
            _wrapper.__qualname__ = fn.__qualname__
            _wrapper.__doc__ = fn.__doc__
            _wrapper.__module__ = fn.__module__

            try:
                raw_sig = inspect.signature(fn, follow_wrapped=False)
                try:
                    hints = _typing_mod.get_type_hints(fn)
                except Exception:
                    hints = {}
                new_params = []
                for pname, param in raw_sig.parameters.items():
                    if pname in hints:
                        param = param.replace(annotation=hints[pname])
                    new_params.append(param)
                ret_ann = hints.get("return", inspect.Parameter.empty)
                _wrapper.__signature__ = raw_sig.replace(
                    parameters=new_params, return_annotation=ret_ann
                )
            except Exception as _sig_err:
                logger.warning(f"[_make_counted] could not build signature for {fn.__name__}: {_sig_err}")

            return _wrapper

        counted_fns = [_make_counted(fn) for fn in tool_fns]

        cfg_kwargs: dict = dict(
            system_instruction=system,
            max_output_tokens=8096,
        )
        if counted_fns:
            cfg_kwargs["tools"] = counted_fns
            cfg_kwargs["automatic_function_calling"] = _gtypes.AutomaticFunctionCallingConfig(
                maximum_remote_calls=_MAX_TOOL_CALLS + 1,
            )

        chat = get_client().chats.create(
            model=GEMINI_MODEL,
            config=_gtypes.GenerateContentConfig(**cfg_kwargs),
        )

        r = chat.send_message(prompt)
        _track_tokens(r)

        final_text = (getattr(r, "text", "") or "").strip()

        with _tool_inv_lock:
            collected = list(_tool_invocations)

        logger.info(f"[{label}] agent finished — {len(collected)} tool invocations")
        return final_text, collected

    last_err = ""
    text = ""
    tool_results: List[str] = []
    logger.info(f"[{label}] ── Gemini native function-calling loop (role={role_key}, prompt={len(prompt)}c)")

    # Capture the calling thread's ContextVars (agent_id, worktree_manager, sprint_num)
    # so tool functions invoked by Gemini AFC inside the inner thread see the right values.
    _ctx = _cv.copy_context()

    for _attempt in range(1, _MAX_AGENT_RETRIES + 1):
        _ex = _cf.ThreadPoolExecutor(max_workers=1)
        try:
            _fut = _ex.submit(_ctx.run, _run_loop)
            try:
                text, tool_results = _fut.result(timeout=_AGENT_TIMEOUT)
                break
            except _cf.TimeoutError:
                last_err = f"agent timed out after {_AGENT_TIMEOUT}s"
                logger.warning(f"[{label}] {last_err} (attempt {_attempt}/{_MAX_AGENT_RETRIES})")
                _fut.cancel()
            except Exception as e:
                last_err = str(e)
                logger.warning(f"[{label}] agent error: {e} (attempt {_attempt}/{_MAX_AGENT_RETRIES})")
                # Exponential backoff for rate-limit (429) errors
                if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
                    _backoff = 5 * (2 ** (_attempt - 1))   # 5s, 10s, 20s …
                    logger.info(f"[{label}] rate-limited — waiting {_backoff}s before retry")
                    import time as _time
                    _time.sleep(_backoff)
        finally:
            _ex.shutdown(wait=False)
    else:
        logger.error(f"[{label}] all {_MAX_AGENT_RETRIES} attempts failed — {last_err}")
        return f"[ERROR: {last_err}]\nSTANCE: PRAGMATIC", [], 10.0

    # Fallback: if agent produced no meaningful summary, synthesise from tool outputs
    used_fallback = False
    if len(text) < 150 and tool_results:
        tool_summary = "\n".join(tool_results[:6])
        fallback_prompt = (
            f"You just used these tools:\n{tool_summary}\n\n"
            "Write a detailed technical summary of what was built, key decisions, "
            "and integration notes. End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )
        text = llm_call(fallback_prompt, label=f"{label}_summary", get_logprobs=False, system=_SYSTEM_AGENT)
        used_fallback = True
        logger.info(f"[{label}] fallback summary triggered ({len(text)}c)")

    logger.info(
        f"[{label}] ({len(text)}c | tools={len(tool_results)}) "
        f"[total: {token_summary()}]: {text[:80]}{'...' if len(text) > 80 else ''}"
    )

    perplexity = (
        max(1.5, 10.0 - min(len(text) / 500, 1.0) * 7.0)
        if used_fallback
        else _perplexity_from_content(text)
    )
    logger.info(f"[{label}] perplexity={perplexity:.2f}  final_text={len(text)}c")

    # ── Save agent trace to markdown ──────────────────────────────────────
    try:
        import datetime as _dt
        logs_dir = OUTPUT_DIR / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        md_path = logs_dir / f"{label}.md"
        lines = [
            f"# Agent Trace: `{label}`\n",
            f"**Role:** {role_key}  \n**Time:** {_dt.datetime.now().strftime('%H:%M:%S')}\n\n",
        ]
        for tr in tool_results:
            lines.append(f"**Tool:** {tr[:400]}\n\n")
        if text.strip():
            lines.append(f"---\n## Summary\n{text.strip()}\n")
        md_path.write_text("".join(lines), encoding="utf-8")
    except Exception:
        pass  # never let logging break the agent

    return text, tool_results, perplexity


_CONFIDENCE_MAP = {
    "a": 1.5,   # Very confident
    "b": 2.5,   # Confident
    "c": 5.0,   # Uncertain
    "d": 8.0,   # Very uncertain
}

def _perplexity_from_content(text: str) -> float:
    """Content-based perplexity heuristic — fallback when verbal elicitation fails."""
    if not text or len(text) < 10:
        return 8.0
    if text.lower().startswith("[error"):
        return 10.0
    score = 2.0
    hedges = ["might", "could", "perhaps", "unclear", "i think",
              "probably", "not sure", "may need", "i believe", "it seems",
              "possibly", "i'm not", "hard to say"]
    hedge_count = sum(text.lower().count(h) for h in hedges)
    score += min(hedge_count * 0.4, 3.0)
    if "STANCE:" not in text:
        score += 2.0
    words = text.lower().split()
    if words:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.4:
            score += 2.0
    if len(text) < 200:
        score += 1.5
    return min(score, 10.0)




# ── Role definitions ──────────────────────────────────────────────────────────
ROLES: Dict[str, Dict[str, str]] = {
    "ceo": {
        "title":          "Chief Executive Officer",
        "expertise":      "software strategy, project decomposition, cross-team coordination",
        "responsibility": "break project into workstreams, synthesize team outputs into final deliverable",
    },
    # Architecture
    "arch_manager": {
        "title":          "Architecture Manager",
        "expertise":      "software architecture, system design, technical leadership",
        "responsibility": "lead architecture team, synthesize design into a coherent system specification",
    },
    "system_designer": {
        "title":          "System Designer",
        "expertise":      "distributed systems, component design, data flow, system boundaries, scalability patterns",
        "responsibility": "design overall system components, their interactions, and data flow — produce component diagram",
    },
    "api_designer": {
        "title":          "API Designer",
        "expertise":      "REST, GraphQL, OpenAPI spec, API versioning, auth flows, rate limiting",
        "responsibility": "design all API endpoints, request/response schemas, authentication and authorization flows",
    },
    "db_designer": {
        "title":          "Database Designer",
        "expertise":      "data modeling, SQL/NoSQL, indexing strategies, migrations, query optimization",
        "responsibility": "design data models, schemas, relationships, indexes, and migration strategy",
    },
    # Design
    "design_manager": {
        "title":          "Design Manager",
        "expertise":      "product design, UX leadership, design systems, design handoff",
        "responsibility": "lead design team, synthesize research and visuals into a complete design specification",
    },
    "ux_researcher": {
        "title":          "UX Researcher",
        "expertise":      "user research, personas, user flows, information architecture, usability testing",
        "responsibility": "define user personas, map complete user flows, identify UX requirements and pain points",
    },
    "ui_designer": {
        "title":          "UI Designer",
        "expertise":      "interface design, component systems, accessibility (WCAG), responsive design, interaction patterns",
        "responsibility": "design UI components, screen layouts, interaction states, accessibility requirements",
    },
    "visual_designer": {
        "title":          "Visual Designer",
        "expertise":      "visual design, typography, color theory, brand identity, design tokens, icon systems",
        "responsibility": "define complete visual style guide: colors, typography, spacing, icons, animation tokens",
    },
    # Engineering
    "eng_manager": {
        "title":          "Engineering Manager",
        "expertise":      "software engineering, code quality, technical execution, delivery",
        "responsibility": "lead engineering team, synthesize worker code into a coherent, runnable implementation",
    },
    "software_developer": {
        "title":          "Software Developer",
        "expertise":      "full-stack development, Python, JavaScript/TypeScript, SQL, REST APIs, Docker, CI/CD, cloud",
        "responsibility":  "implement any engineering task: backend logic, frontend components, APIs, infra config, or tooling — write actual working code",
    },
    # QA
    "qa_manager": {
        "title":          "QA Manager",
        "expertise":      "quality assurance, testing strategy, risk assessment, release criteria",
        "responsibility": "lead QA team, synthesize quality report with explicit go/no-go recommendation",
    },
    "unit_tester": {
        "title":          "Unit Test Engineer",
        "expertise":      "pytest, jest, vitest, mocking, coverage analysis, TDD, property-based testing",
        "responsibility": "write comprehensive unit tests for all core functions, edge cases, and error paths",
    },
    "integration_tester": {
        "title":          "Integration Test Engineer",
        "expertise":      "API testing, end-to-end testing, contract testing, load testing, Postman/k6",
        "responsibility": "write integration and E2E test scenarios, API contract tests, performance test plan",
    },
    "security_auditor": {
        "title":          "Security Auditor",
        "expertise":      "OWASP Top 10, penetration testing, threat modeling, secure coding, compliance",
        "responsibility": "threat model the system, identify vulnerabilities, provide mitigation recommendations",
    },
}

# 8 generic engineering workers — all share the same role definition
ENG_WORKERS = [f"dev_{i}" for i in range(1, 9)]
for _k in ENG_WORKERS:
    ROLES[_k] = ROLES["software_developer"]
    _ROLE_TOOL_NAMES[_k] = _DEV_TOOL_NAMES

_ROLE_TOOL_NAMES["eng_manager"] = _ENG_MANAGER_TOOL_NAMES


# ── Definition of Done checklists (one per role category) ─────────────────────
# Each worker self-verifies before submitting. If any item is FAIL, they fix it
# in the same response. Research shows self-DoD catches issues before manager review.

_DOD_CHECKLISTS: Dict[str, str] = {
    "engineering": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Every function is fully implemented — no TODOs, no stubs\n"
        "  [ ] All new modules are imported/registered in the running app\n"
        "  [ ] Error handling and input validation are written\n"
        "  [ ] No hardcoded secrets or magic numbers\n"
        "  [ ] Verified it runs: paste actual shell output or explain why impossible\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
    "architecture": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Every data structure has exact field names, types, and nullability\n"
        "  [ ] Every API endpoint has method, path, auth, request + response schema\n"
        "  [ ] No vague types (object/array/any) — all fields are concrete\n"
        "  [ ] Integration order is specified (what must be built before what)\n"
        "  [ ] Output written to design/architecture_spec.md\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
    "design": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Every component has exact px, hex, and ms values — no vague descriptions\n"
        "  [ ] All states are covered: default, loading, error, empty, success\n"
        "  [ ] Every user flow has a defined end state — no dead ends\n"
        "  [ ] Accessibility: all interactive elements are keyboard-navigable\n"
        "  [ ] Output written to design/design_spec.md\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
    "qa": (
        "DEFINITION OF DONE — verify every item before submitting:\n"
        "  [ ] Tests are deterministic — no random data, no time-dependent assertions\n"
        "  [ ] Happy path, error path, and at least one edge case are covered\n"
        "  [ ] Auth is tested: unauthenticated request is rejected\n"
        "  [ ] Real output is shown — actual pytest/browser results, not claims\n"
        "  [ ] All new findings written to design/qa_findings.md with SEVERITY/FILE/DESCRIPTION\n"
        "Mark each as PASS or FAIL. Fix any FAIL before ending your response."
    ),
}

_ARCH_ROLES  = {"system_designer", "api_designer", "db_designer"}
_DESIGN_ROLES = {"ux_researcher", "ui_designer", "visual_designer"}
_QA_ROLES    = {"unit_tester", "integration_tester", "security_auditor"}


def _get_dod(role_key: str) -> str:
    """Return the Definition of Done checklist for this role."""
    if role_key in _ARCH_ROLES:
        return _DOD_CHECKLISTS["architecture"]
    if role_key in _DESIGN_ROLES:
        return _DOD_CHECKLISTS["design"]
    if role_key in _QA_ROLES:
        return _DOD_CHECKLISTS["qa"]
    # All dev_N and software_developer
    return _DOD_CHECKLISTS["engineering"]


# ── Data classes ──────────────────────────────────────────────────────────────
@dataclass
class WorkerOutput:
    role:         str
    title:        str
    round:        int
    output:       str
    tool_results: List[str]
    stance:       str
    stance_probs: List[float]
    F_health:     float
    anomaly:      bool = False


@dataclass
class TeamResult:
    team:              str
    manager_synthesis: str
    worker_outputs:    List[WorkerOutput]
    H_swarm:           float
    consensus_stance:  str
    confidence:        float


@dataclass
class ExecutionPlan:
    raw:          str                    # full meeting transcript
    phases:       List[List[str]]        # [[teams to run in parallel], [next batch], ...]
    team_notes:   Dict[str, str]         # team → special instruction from meeting


@dataclass
class ProjectResult:
    brief:              str
    execution_plan:     ExecutionPlan
    architecture:       Optional[TeamResult]
    design:             Optional[TeamResult]
    engineering:        Optional[TeamResult]
    qa:                 Optional[TeamResult]
    ceo_summary:        str
    overall_H_swarm:    float
    overall_confidence: float
    duration_s:         float


# ── Gemini client ─────────────────────────────────────────────────────────────
_client: Optional[genai.Client] = None
_client_lock = threading.Lock()

# ── Token tracking ────────────────────────────────────────────────────────────
_tokens_in:  int = 0
_tokens_out: int = 0
_call_count: int = 0
_token_lock = threading.Lock()   # guards all three counters against concurrent +=


def _track_tokens(response_or_usage) -> None:
    """Thread-safe accumulation of token counters from Anthropic/Gemini responses."""
    usage = response_or_usage
    # Gemini SDK response: usage lives under response.usage_metadata
    if hasattr(response_or_usage, "usage_metadata"):
        usage = getattr(response_or_usage, "usage_metadata")
    in_tokens = (
        getattr(usage, "input_tokens", None)
        or getattr(usage, "prompt_token_count", None)
        or 0
    )
    out_tokens = (
        getattr(usage, "output_tokens", None)
        or getattr(usage, "candidates_token_count", None)
        or 0
    )
    global _tokens_in, _tokens_out, _call_count
    with _token_lock:
        _tokens_in  += int(in_tokens or 0)
        _tokens_out += int(out_tokens or 0)
        _call_count += 1

# ── System prompts (loaded from prompts/ directory) ───────────────────────────
def _load_prompt(filename: str) -> str:
    p = Path(__file__).parent / "prompts" / filename
    return p.read_text(encoding="utf-8").strip()

_SYSTEM_WORKER           = _load_prompt("worker.txt")
_SYSTEM_MANAGER          = _load_prompt("manager.txt")
_SYSTEM_CEO              = _load_prompt("ceo.txt")
_SYSTEM_AGENT            = _load_prompt("agent.txt")
# Role-specific prompts
_SYSTEM_WORKER_ARCHITECT = _load_prompt("worker_architect.txt")
_SYSTEM_WORKER_DESIGNER  = _load_prompt("worker_designer.txt")
_SYSTEM_WORKER_ENGINEER  = _load_prompt("worker_engineer.txt")
_SYSTEM_WORKER_QA        = _load_prompt("worker_qa.txt")
_SYSTEM_MANAGER_ARCH     = _load_prompt("manager_arch.txt")
_SYSTEM_MANAGER_DESIGN   = _load_prompt("manager_design.txt")
_SYSTEM_MANAGER_ENG      = _load_prompt("manager_eng.txt")
_SYSTEM_MANAGER_QA       = _load_prompt("manager_qa.txt")

# Map role keys to their specific system prompts
_ROLE_SYSTEM_PROMPTS: Dict[str, str] = {
    # Architecture workers
    "system_designer": _SYSTEM_WORKER_ARCHITECT,
    "api_designer":    _SYSTEM_WORKER_ARCHITECT,
    "db_designer":     _SYSTEM_WORKER_ARCHITECT,
    # Design workers
    "ux_researcher":   _SYSTEM_WORKER_DESIGNER,
    "ui_designer":     _SYSTEM_WORKER_DESIGNER,
    "visual_designer": _SYSTEM_WORKER_DESIGNER,
    # QA workers
    "unit_tester":        _SYSTEM_WORKER_QA,
    "integration_tester": _SYSTEM_WORKER_QA,
    "security_auditor":   _SYSTEM_WORKER_QA,
    # Managers
    "arch_manager":   _SYSTEM_MANAGER_ARCH,
    "design_manager": _SYSTEM_MANAGER_DESIGN,
    "eng_manager":    _SYSTEM_MANAGER_ENG,
    "qa_manager":     _SYSTEM_MANAGER_QA,
}

def _worker_system(role_key: str) -> str:
    """Return the role-specific system prompt for a worker, falling back to the generic one."""
    # Engineering devs (dev_1 … dev_8) use the engineer prompt
    if role_key.startswith("dev_"):
        return _SYSTEM_WORKER_ENGINEER
    return _ROLE_SYSTEM_PROMPTS.get(role_key, _SYSTEM_WORKER)

def _manager_system(role_key: str) -> str:
    """Return the role-specific system prompt for a manager, falling back to the generic one."""
    return _ROLE_SYSTEM_PROMPTS.get(role_key, _SYSTEM_MANAGER)




def get_client() -> genai.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = genai.Client(
                    api_key=os.environ["GEMINI_API_KEY"],
                    http_options={"api_version": "v1beta"},
                )
    return _client


def token_summary() -> str:
    with _token_lock:
        calls = _call_count
        t_in  = _tokens_in
        t_out = _tokens_out
    total = t_in + t_out
    # gemini-3.1-flash-lite-preview: $0.25/1M input, $1.50/1M output
    cost = (t_in * 0.25 + t_out * 1.50) / 1_000_000
    return (
        f"calls={calls}  "
        f"in={t_in:,}  out={t_out:,}  total={total:,}  "
        f"~${cost:.4f}"
    )



def llm_call(
    prompt: str,
    label: str = "",
    get_logprobs: bool = False,
    system: str = _SYSTEM_WORKER,
):
    import concurrent.futures as _cf
    _LLM_TIMEOUT = 60
    _LLM_RETRIES = 3

    def _do_call():
        from google.genai import types as _gtypes
        cfg = _gtypes.GenerateContentConfig(
            max_output_tokens=8096,
            **({"system_instruction": system} if system else {}),
        )
        return get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=cfg,
        )

    last_err: str = ""
    for _attempt in range(1, _LLM_RETRIES + 1):
        try:
            _llm_ex = _cf.ThreadPoolExecutor(max_workers=1)
            _llm_fut = _llm_ex.submit(_do_call)
            try:
                r = _llm_fut.result(timeout=_LLM_TIMEOUT)
                _llm_ex.shutdown(wait=False)
            except _cf.TimeoutError:
                _llm_ex.shutdown(wait=False)
                last_err = f"timed out after {_LLM_TIMEOUT}s"
                logger.warning(f"LLM_TIMEOUT [{label}] attempt {_attempt}/{_LLM_RETRIES} — retrying...")
                continue

            text = (getattr(r, "text", "") or "").strip()

            _track_tokens(r)
            u = getattr(r, "usage_metadata", None)
            t_in  = getattr(u, "prompt_token_count", 0) or 0
            t_out = getattr(u, "candidates_token_count", 0) or 0

            tag = f"[{label}] " if label else ""
            logger.info(
                f"{tag}({len(text)}c | in={t_in} out={t_out}) "
                f"[total: {token_summary()}]: "
                f"{text[:80]}{'...' if len(text) > 80 else ''}"
            )
            if get_logprobs:
                perplexity = _perplexity_from_content(text)
                try:
                    elicit_prompt = (
                        f"You just produced this response:\n\"\"\"\n{text[:800]}\n\"\"\"\n\n"
                        "Rate your confidence in this response:\n"
                        "A) Very confident — output is complete, correct, and well-reasoned\n"
                        "B) Confident — minor gaps possible but core is solid\n"
                        "C) Uncertain — notable gaps or assumptions made\n"
                        "D) Very uncertain — significant issues or missing information\n\n"
                        "Reply with only the letter A, B, C, or D."
                    )
                    reply = llm_call(elicit_prompt, label="", get_logprobs=False, system="")
                    letter = reply.strip().upper()[:1].lower()
                    if letter in _CONFIDENCE_MAP:
                        perplexity = _CONFIDENCE_MAP[letter]
                except Exception:
                    pass
                return text, perplexity
            return text
        except Exception as e:
            last_err = str(e)
            logger.warning(f"LLM_ERROR [{label}] attempt {_attempt}/{_LLM_RETRIES}: {e}")

    logger.error(f"LLM_ERROR [{label}]: all {_LLM_RETRIES} attempts failed — {last_err}")
    fallback = f"[ERROR: {last_err}]\nSTANCE: PRAGMATIC"
    return (fallback, 10.0) if get_logprobs else fallback


def perplexity_to_similarities(perplexity: float) -> dict:
    confusion = min(math.log(max(perplexity, 1.0)) / math.log(30.0), 1.0)
    return {
        "healthy":   max(0.0, min(1.0, 1.0 - 2.0 * confusion)),
        "uncertain": max(0.0, min(1.0, 1.0 - 2.0 * abs(confusion - 0.5))),
        "confused":  max(0.0, min(1.0, 2.0 * confusion - 1.0)),
    }


def interfere_weighted(
    beliefs: List[np.ndarray],
    weights: List[float],
    alpha: float = 0.5,
) -> List[np.ndarray]:
    w = np.array(weights, dtype=float)
    w = w / w.sum()
    amps     = [np.sqrt(np.clip(b, 1e-10, 1.0)) for b in beliefs]
    combined = sum(wi * a for wi, a in zip(w, amps))
    norm     = float(np.linalg.norm(combined))
    if norm < 1e-10:
        return beliefs
    combined = (combined / norm) ** 2
    combined /= combined.sum()
    return [(1.0 - alpha) * b + alpha * combined for b in beliefs]


# ── Rolling context ───────────────────────────────────────────────────────────
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
            result = llm_call(prompt, label="ctx", system=_SYSTEM_WORKER)
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


# ── Stance extraction + consistency weight ────────────────────────────────────
def extract_stance_probs(output: str) -> np.ndarray:
    # Prefer explicit STANCE: tag if present (e.g. "STANCE: ROBUST")
    tag_match = re.search(r"\bSTANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)\b", output, re.IGNORECASE)
    if tag_match:
        tag = tag_match.group(1).upper()
        idx = {"MINIMAL": 0, "ROBUST": 1, "SCALABLE": 2, "PRAGMATIC": 3}.get(tag, 3)
        scores = np.full(4, 0.5)
        scores[idx] = 4.0
        return scores / scores.sum()
    text = output.lower()
    scores = np.array([
        sum(1 for w in ["simple", "minimal", "straightforward", "basic",
                         "lean", "lightweight", "easy", "small"] if w in text),
        sum(1 for w in ["robust", "reliable", "error handling", "fallback",
                         "resilient", "defensive", "retry", "fault"] if w in text),
        sum(1 for w in ["scalable", "extensible", "modular", "distributed",
                         "horizontal", "growth", "microservice", "queue"] if w in text),
        sum(1 for w in ["pragmatic", "practical", "tradeoff", "balance",
                         "reasonable", "sufficient", "good enough", "ship"] if w in text),
    ], dtype=float)
    scores += 0.5
    return scores / scores.sum()


def consistency_weight(output: str) -> float:
    length_score = min(len(output) / 2000, 1.0)
    logic_words  = sum(1 for w in ["because", "therefore", "however", "thus", "since",
                                    "which means", "as a result", "consequently"] if w in output.lower())
    tech_words   = sum(1 for w in ["function", "class", "endpoint", "schema", "service",
                                    "interface", "module", "database", "api", "test",
                                    "component", "route", "model", "controller"] if w in output.lower())
    return 0.4 * length_score + 0.3 * min(logic_words / 5, 1.0) + 0.3 * min(tech_words / 10, 1.0)


# ── Worker execution ──────────────────────────────────────────────────────────
def _run_fixer(role_key: str, task: str, failed_output: str, F_score: float) -> str:
    """
    Fixer agent: reads a failed/uncertain output and makes surgical corrections.
    Returns a patched output. Used instead of full retry on anomaly.
    Per research: raises success 43→89.5 vs. restart, cuts recovery time 50%.
    """
    role = ROLES[role_key]
    fix_prompt = (
        f"You are a senior {role['title']} reviewing a colleague's uncertain work.\n\n"
        f"ORIGINAL TASK:\n{task[:400]}\n\n"
        f"UNCERTAIN OUTPUT (uncertainty score={F_score:.3f}):\n{failed_output[:1200]}\n\n"
        f"This output scored high on uncertainty. Diagnose exactly what is wrong:\n"
        f"1. Identify the specific parts that are vague, incomplete, or contradictory.\n"
        f"2. Rewrite only those parts with decisive, concrete replacements.\n"
        f"3. Keep everything that is already correct — do not rewrite for the sake of it.\n\n"
        f"Output the complete corrected version. Be decisive and specific.\n"
        f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
    )
    fixed = llm_call(fix_prompt, label=f"{role_key}_fixer", get_logprobs=False, system=_worker_system(role_key))
    if not fixed.strip():
        logger.warning(f"[{role_key}] fixer returned empty — keeping original output")
        return failed_output
    logger.info(f"[{role_key}] fixer applied — output patched ({len(fixed)}c)")
    return fixed


def run_worker(
    role_key: str,
    task: str,
    peer_outputs: List[str],
    peer_tool_results: List[str],
    health_state: ActiveInferenceState,
    rolling_ctx: RollingContext,
    round_num: int,
    sprint_num: int = 1,
) -> WorkerOutput:
    _set_agent_ctx(role_key, sprint_num)

    role      = ROLES[role_key]
    ctx_text  = rolling_ctx.get()
    has_tools = bool(get_role_lc_tools(role_key))

    # ── Goal anchor: pin original sprint goal at the top of every prompt ──
    goal_anchor = ""
    if _current_sprint_goal:
        goal_anchor = (
            f"╔══════════════════════════════════════════════════════╗\n"
            f"║  SPRINT GOAL (your north star — never lose sight of this)\n"
            f"║  {_current_sprint_goal[:200]}\n"
            f"╚══════════════════════════════════════════════════════╝\n\n"
        )

    # Inject manifest for roles that write or read files
    manifest_snippet = ""
    manifest_path = OUTPUT_DIR / "PROJECT_MANIFEST.md"
    struct_path   = OUTPUT_DIR / "design" / "project_structure.md"

    if has_tools:
        # 1. Project Structure (Architect's Intent)
        if struct_path.exists():
            manifest_snippet += (
                "\n\n─── ARCHITECT'S PROJECT STRUCTURE (design/project_structure.md) ───\n"
                + struct_path.read_text(encoding="utf-8")[:3000]
                + "\n───────────────────────────────────────────────────────────────\n"
                "IMPORTANT: You MUST follow this directory tree. Create only these files.\n"
            )

        # 2. Existing files (Actual status)
        if manifest_path.exists():
            manifest_snippet += (
                "\n\n─── CODEBASE INDEX (PROJECT_MANIFEST.md) ───\n"
                + manifest_path.read_text(encoding="utf-8")[:2000]
                + "\n────────────────────────────────────────────\n"
                "IMPORTANT: Before writing any file, call list_files() and search_codebase() "
                "to check what already exists. Do NOT reimplement existing code — extend it.\n"
            )

    dashboard_snippet = ""
    messages_snippet = ""
    if has_tools:
        dashboard_snippet = (
            "\n\n─── WORK DASHBOARD (Sprint " + str(sprint_num) + ") ───\n"
            + get_dashboard().get_status()
            + "\n────────────────────────────────\n"
        )
        try:
            pending = get_dashboard().peek_messages(role_key)
            if pending:
                messages_snippet = f"\nMESSAGES FROM TEAMMATES (read carefully):\n{pending}\n"
        except Exception:
            pass

    dod_checklist = _get_dod(role_key)

    # Coordination instructions — mirror engineering's mandatory tool-use steps
    coord_instructions = ""
    if has_tools:
        if round_num == 1:
            coord_instructions = (
                "\nMANDATORY FIRST STEPS (do these before producing any work):\n"
                "  1. call check_dashboard() — check messages from teammates\n"
                "  2. call check_messages() — read any messages from teammates or other teams\n"
                "  3. If you need info from another role, call message_teammate(role, question)\n\n"
            )
        else:
            coord_instructions = (
                "\nMANDATORY FIRST STEPS (do these before revising any work):\n"
                "  1. call check_messages() — read ALL messages before changing anything\n"
                "  2. Address every teammate message in your revised output\n\n"
            )

    if round_num == 1:
        prompt = (
            f"{goal_anchor}"
            f"You are a {role['title']} at a software company.\n"
            f"Expertise: {role['expertise']}\n"
            f"Responsibility: {role['responsibility']}\n\n"
            f"{ctx_text}"
            f"{manifest_snippet}"
            f"{dashboard_snippet}"
            f"{messages_snippet}"
            f"{coord_instructions}"
            f"PROJECT TASK:\n{task}\n\n"
            f"Produce your best work product. Be specific, technical, and complete.\n"
            f"Include actual code, schemas, diagrams, or specs where relevant.\n\n"
            f"{dod_checklist}\n\n"
            f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )
    else:
        peer_text = "\n\n---\n".join(
            f"Colleague output:\n{p[:600]}" for p in peer_outputs
        )
        tool_text = (
            "\nTOOL RESULTS FROM PREVIOUS ROUND:\n" + "\n".join(peer_tool_results[:10]) + "\n"
            if peer_tool_results else ""
        )
        feedback_text = (
            f"\nMANAGER FEEDBACK (Round {round_num - 1}):\n{peer_outputs[-1]}\n"
            f"Address every point above.\n"
            if peer_outputs and peer_outputs[-1].startswith("[MANAGER]") else ""
        )
        prompt = (
            f"{goal_anchor}"
            f"You are a {role['title']} at a software company.\n"
            f"Expertise: {role['expertise']}\n\n"
            f"{ctx_text}"
            f"{manifest_snippet}"
            f"{dashboard_snippet}"
            f"{messages_snippet}"
            f"{coord_instructions}"
            f"PROJECT TASK:\n{task}\n\n"
            f"ROUND {round_num} — You have seen what your colleagues produced last round.\n"
            f"COLLEAGUE OUTPUTS:\n{peer_text}\n"
            f"{tool_text}"
            f"{feedback_text}"
            f"Discuss conflicts with your colleagues, fill gaps, and improve your contribution. "
            f"Do not repeat what others have already done — build on it or fix it.\n\n"
            f"{dod_checklist}\n\n"
            f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )

    label = f"{role_key}_R{round_num}"
    if has_tools:
        output, tool_results, perplexity = _run_with_tools(prompt, role_key, label)
    else:
        output, perplexity = llm_call(prompt, label=label, get_logprobs=True, system=_worker_system(role_key))
        tool_results = []

    sims    = perplexity_to_similarities(perplexity)
    F       = health_state.update(sims)
    anomaly = health_state.is_anomaly()

    if anomaly and round_num == 1:
        logger.warning(f"[{role_key}] ANOMALY F={F:.3f} — invoking fixer agent")
        health_state.reset()
        # Fixer agent: surgical patch of the uncertain output (not a full retry)
        output  = _run_fixer(role_key, task, output, F)
        sims    = perplexity_to_similarities(5.0)   # moderate uncertainty after fix
        F       = health_state.update(sims)
        anomaly = health_state.is_anomaly()  # reflect actual post-fix state

    m      = re.search(r"STANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)", output, re.IGNORECASE)
    stance = m.group(1).lower() if m else "pragmatic"

    return WorkerOutput(
        role=role_key,
        title=role["title"],
        round=round_num,
        output=output,
        tool_results=tool_results,
        stance=stance,
        stance_probs=extract_stance_probs(output).tolist(),
        F_health=F,
        anomaly=anomaly,
    )


# ── Team planning: manager + workers discuss and self-assign ─────────────────
def run_team_planning(
    team_name: str,
    manager_role: str,
    worker_roles: List[str],
    brief: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> Dict[str, str]:
    """
    Pull-based blackboard planning: manager posts work items to a shared board,
    workers self-claim in one parallel round, manager resolves conflicts only if needed.
    Research shows 13-57% improvement over push-based assignment.
    Returns {worker_key: sub_task_description}.
    """
    n = len(worker_roles)
    logger.info(f"\n{'─'*55}\nTEAM PLANNING (blackboard): {team_name} ({n} workers)\n{'─'*55}")

    m_info = ROLES[manager_role]

    # ── Step 1: Manager posts work items to blackboard ────────────────────────
    # Agile Update: Allow up to 2x n items, but only as many as actually needed
    board_prompt = (
        f"You are the {m_info['title']}.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Post work items to the team blackboard. Role: {team_name}.\n"
        f"  - POST ONLY AS MANY ITEMS AS NEEDED (between 1 and 100 maximum).\n"
        f"  - Do NOT invent fake tasks for a simple project.\n"
        f"  - Each item must be INDEPENDENT and FILE-ISOLATED.\n"
        f"  - Small enough that a specialist can finish multiple in a sprint\n"
        f"  - Each item must list its files in brackets, e.g. [routes.py, auth.py]\n\n"
        f"CRITICAL RULES:\n"
        f"  1. NO two items should write to the same file\n"
        f"  2. Entry point and shared models are system-managed\n\n"
        f"Format EXACTLY as (one line each):\n"
        f"ITEM_1: <task> [files]\n"
        f"ITEM_2: <task> [files]\n"
        f"... up to ITEM_50 if needed."
    )
    board_output = llm_call(board_prompt, label=f"{manager_role}_board_post",
                             system=_manager_system(manager_role))

    # Parse board items — tolerant of ITEM_N:, ITEM N:, N. and N) formats
    items: Dict[str, str] = {}
    item_files: Dict[str, List[str]] = {}  # item_id -> list of files
    # Search for all "ITEM_N" patterns up to 100
    for i in range(1, 101):
        m = re.search(
            rf"(?:ITEM[_ ]{i}|{i}[.):])\s*[:–\-]?\s*(.+)",
            board_output,
            re.IGNORECASE,
        )
        if m:
            text = m.group(1).strip()
            items[f"item_{i}"] = text
            # Extract file list from brackets: [file1.py, file2.js]
            file_match = re.search(r"\[([^\]]+)\]", text)
            if file_match:
                item_files[f"item_{i}"] = [f.strip() for f in file_match.group(1).split(",") if f.strip()]

    # Validate file-isolation: no two items should share files
    file_to_item: Dict[str, str] = {}
    overlaps: List[str] = []
    for iid, files in item_files.items():
        for f in files:
            if f in file_to_item:
                overlaps.append(f"  {f}: claimed by both {file_to_item[f]} and {iid}")
            else:
                file_to_item[f] = iid
    if overlaps:
        logger.warning(f"  {team_name}: file overlap detected in work items:\n" + "\n".join(overlaps))
        logger.warning(f"  The integration enforcer will handle shared files automatically.")

    board_display = "\n".join(f"  [{k}] {v}" for k, v in items.items())
    logger.info(f"  {team_name} blackboard posted {n} items ({len(item_files)} with explicit file lists)")

    # ── Step 2: Workers self-claim in parallel ────────────────────────────────
    def worker_claim(role_key: str) -> Tuple[str, str]:
        idx = worker_roles.index(role_key) + 1
        output = llm_call(
            f"You are {ROLES[role_key]['title']} #{idx}.\n"
            f"Expertise: {ROLES[role_key]['expertise']}\n\n"
            f"BLACKBOARD — available work items:\n{board_display}\n\n"
            f"Scan the board and claim ALL items that best match your expertise.\n"
            f"You are encouraged to pick multiple items (up to 3) if they are related.\n"
            f"List them clearly. One sentence reason per claim.\n\n"
            f"End with exactly: CLAIM: item_X, item_Y",
            label=f"{role_key}_claim",
            system=_worker_system(role_key),
        )
        return role_key, output

    claims: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        for role_key, output in ex.map(lambda r: worker_claim(r), worker_roles):
            claims[role_key] = output
            m_claim = re.search(r"CLAIM:\s*([item_\d,\s]+)", output, re.IGNORECASE)
            claimed_str = m_claim.group(1) if m_claim else "UNKNOWN"
            logger.info(f"  [claim] {role_key} → {claimed_str}")

    # Health interference across team
    ActiveInferenceState.interfere_all(
        [health_states[r] for r in worker_roles], alpha=INTERFERENCE_ALPHA
    )

    # ── Step 3: Parse claims; resolve conflicts ──────────────────────────────
    claimed: Dict[str, str] = {}    # item_id → role_key (first valid claimant wins)
    assignments: Dict[str, List[str]] = {r: [] for r in worker_roles}

    for role_key in worker_roles:
        m = re.search(r"CLAIM:\s*([item_\d,\s]+)", claims[role_key], re.IGNORECASE)
        if m:
            iids = [i.strip().lower() for i in m.group(1).split(",") if i.strip()]
            for iid in iids:
                if iid in items and iid not in claimed:
                    claimed[iid] = role_key
                    assignments[role_key].append(iid)

    # Conflict resolution: workers with no tasks get first unclaimed items
    conflict_roles: List[str] = [r for r in worker_roles if not assignments[r]]
    unclaimed_items = [iid for iid in items if iid not in claimed]
    
    for role_key in conflict_roles:
        if unclaimed_items:
            iid = unclaimed_items.pop(0)
            assignments[role_key].append(iid)
            claimed[iid] = role_key

    # ── Step 4: Finalize ─────────────────────────────────────────────────────
    if conflict_roles:
        logger.info(f"  {team_name}: {len(conflict_roles)} worker(s) had no valid claims — assigning pool items")

    logger.info(f"\n  {team_name} blackboard assignments:")
    final_output: Dict[str, str] = {}
    for role_key, iids in assignments.items():
        if iids:
            joined_desc = "\n\n".join(f"Task {i}: {items[i]}" for i in iids)
            final_output[role_key] = joined_desc
            logger.info(f"    {role_key} → {len(iids)} tasks: {', '.join(iids)}")
        else:
            final_output[role_key] = "Assist the team with existing files."
            logger.info(f"    {role_key} → Assist and Review")

    pool_items = {iid: desc for iid, desc in items.items() if iid not in claimed}
    if pool_items:
        logger.info(f"  {team_name}: {len(pool_items)} items left in the general pool.")

    return final_output, pool_items


# ── Team execution ────────────────────────────────────────────────────────────
MAX_TEAM_ROUNDS = 2  # hard cap for non-engineering teams


def run_team(
    team_name: str,
    manager_role: str,
    worker_roles: List[str],
    task: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    sprint_num: int = 1,
) -> TeamResult:
    logger.info(f"\n{'─'*55}\nTEAM: {team_name.upper()}\n{'─'*55}")

    # ── Team planning: manager + workers decide who does what ─────────────
    worker_tasks, _ = run_team_planning(
        team_name, manager_role, worker_roles, task, rolling_ctxs, health_states
    )

    def make_worker_task(role: str) -> str:
        return (
            f"PROJECT BRIEF:\n{task}\n\n"
            f"YOUR SPECIFIC ASSIGNMENT:\n{worker_tasks[role]}\n\n"
            f"What your teammates are working on:\n"
            + "\n".join(
                f"  {r}: {worker_tasks[r]}" for r in worker_roles if r != role
            )
        )

    # ── Iterative rounds with manager review after each ───────────────────
    current: Dict[str, WorkerOutput] = {}
    manager_feedback: str = ""
    round_num = 1

    while round_num <= MAX_TEAM_ROUNDS:
        logger.info(f"\n{'─'*55}\n{team_name} Round {round_num}/{MAX_TEAM_ROUNDS}\n{'─'*55}")

        all_tool_results = [res for r in worker_roles for res in current[r].tool_results] if current else []

        def run_one(role: str, rnd: int = round_num, feedback: str = manager_feedback) -> WorkerOutput:
            # Peer outputs = everyone else's last output + manager feedback appended
            peers = [current[o].output for o in worker_roles if o != role] if current else []
            if feedback:
                peers = peers + [f"[MANAGER] {feedback}"]
            return run_worker(
                role, make_worker_task(role),
                peers, all_tool_results,
                health_states[role], rolling_ctxs[role], rnd, sprint_num,
            )

        with ThreadPoolExecutor(max_workers=len(worker_roles)) as ex:
            futures = {ex.submit(run_one, role): role for role in worker_roles}
            for fut in as_completed(futures):
                role = futures[fut]
                try:
                    current[role] = fut.result()
                except Exception as exc:
                    logger.error(f"[{role}] worker crashed: {exc}", exc_info=True)
                    current[role] = WorkerOutput(
                        role=role, title=ROLES.get(role, {}).get("title", role),
                        round=round_num, output=f"[worker crashed: {exc}]",
                        tool_results=[], stance="pragmatic",
                        stance_probs=[0.1, 0.1, 0.1, 0.7],
                        F_health=9.9, anomaly=True,
                    )

        # ── Health + stance interference ──────────────────────────────────
        ActiveInferenceState.interfere_all(
            [health_states[r] for r in worker_roles], alpha=INTERFERENCE_ALPHA
        )
        stance_probs = [np.array(current[r].stance_probs) for r in worker_roles]
        weights      = np.array([consistency_weight(current[r].output) for r in worker_roles])
        weights      = weights / (weights.sum() + 1e-10)
        updated      = interfere_weighted(stance_probs, weights.tolist(), alpha=INTERFERENCE_ALPHA)
        for i, role in enumerate(worker_roles):
            current[role].stance_probs = updated[i].tolist()

        # Use post-interference free energy (not stale WorkerOutput values)
        H_swarm     = sum(health_states[r].free_energy() for r in worker_roles)
        n_workers   = len(worker_roles)
        stable_thr  = 1.5 * n_workers
        mean_stance = np.mean([np.array(current[r].stance_probs) for r in worker_roles], axis=0)
        consensus   = STANCES[int(mean_stance.argmax())]
        logger.info(
            f"{team_name} R{round_num}: H_swarm={H_swarm:.3f}  consensus={consensus.upper()}  "
            f"({'stable' if H_swarm < stable_thr else 'ELEVATED ⚠'})"
        )

        # ── Manager reviews round, decides CONTINUE or DONE ───────────────
        summaries = "\n\n".join(
            f"=== {current[r].title} (F={current[r].F_health:.3f}{'⚠' if current[r].anomaly else ''}) ===\n"
            f"{current[r].output[:600]}"
            for r in worker_roles
        )
        team_specific_review = ""
        if team_name == "Architecture":
            team_specific_review = (
                "4. Does the spec include dependency waves (Wave 0 / Wave 1 / Wave 2)?\n"
                "5. Does every file have an explicit depends_on list?\n"
                "6. Are build_command, build_file, and dependencies specified?\n"
                "   (Engineering CANNOT dispatch agents without waves and depends_on)\n"
            )
        elif team_name == "QA":
            team_specific_review = (
                "4. Did testers run the build_command first before testing?\n"
                "5. Were tests executed in wave order (foundation → core → UI)?\n"
                "6. Is the GO/NO-GO backed by actual test output, not claims?\n"
            )
        elif team_name == "Design":
            team_specific_review = (
                "4. Do component names match what Engineering uses in their file names?\n"
                "5. Did designers check the dashboard for Engineering's claimed domains?\n"
            )

        manager_review = llm_call(
            f"You are the {ROLES[manager_role]['title']}.\n\n"
            f"TASK: {task[:300]}\n\n"
            f"ROUND {round_num} TEAM OUTPUTS:\n{summaries}\n\n"
            f"H_swarm={H_swarm:.3f}\n\n"
            f"Review what the team produced this round:\n"
            f"1. Are there conflicts or overlaps between team members' work?\n"
            f"2. Are there gaps — things nobody addressed?\n"
            f"3. Is the work coherent and integrated as a whole?\n"
            f"{team_specific_review}\n"
            f"If the team's output is complete and coherent: respond with DECISION: DONE\n"
            f"Otherwise: respond with DECISION: CONTINUE\n"
            f"Then give specific, numbered feedback for each team member on what to fix or improve next round.",
            label=f"{manager_role}_r{round_num}_review",
            system=_manager_system(manager_role),
        )
        rolling_ctxs[manager_role].add(task, manager_review)
        logger.info(f"[{manager_role}] Round {round_num} review: {manager_review[:120]}...")

        if "DECISION: DONE" in manager_review or round_num >= MAX_TEAM_ROUNDS:
            if round_num >= MAX_TEAM_ROUNDS:
                logger.warning(f"[{team_name}] hit MAX_TEAM_ROUNDS={MAX_TEAM_ROUNDS} — stopping")
            break

        manager_feedback = manager_review
        round_num += 1

    # ── Integration pass (Engineering team only) ─────────────────────────
    # Manager reads the actual written files, boots the app, patches broken glue.
    if team_name == "Engineering":
        logger.info(f"\n{'─'*55}\n{team_name} INTEGRATION PASS — manager fixing glue code\n{'─'*55}")
        sprint_files = get_sprint_files()

        # Find existing files that import from or are imported by sprint files
        # so the manager knows what else may be broken by the new changes
        affected_files: set = set()
        code_dir = _get_code_dir()
        sprint_stems = {Path(f).stem for f in sprint_files}  # e.g. {"auth", "models"}
        all_code_files = list(code_dir.rglob("*.py")) + list(code_dir.rglob("*.ts")) + \
                         list(code_dir.rglob("*.tsx")) + list(code_dir.rglob("*.js"))
        for existing in all_code_files:
            rel = existing.relative_to(code_dir).as_posix()
            if rel in sprint_files:
                continue   # already in new files list
            try:
                src = existing.read_text(encoding="utf-8", errors="ignore")
                if any(stem in src for stem in sprint_stems):
                    affected_files.add(rel)
            except Exception:
                pass

        files_list = "\n".join(f"  - {f}" for f in sprint_files) if sprint_files else "  (none recorded)"
        affected_list = "\n".join(f"  - {f}" for f in sorted(affected_files)) if affected_files else "  (none)"

        integration_output, integration_tool_results, _ = _run_with_tools(
            f"You are the {ROLES[manager_role]['title']}.\n\n"
            f"TASK:\n{task}\n\n"
            f"Your team just finished {round_num} round(s) of development. "
            f"Your job now is INTEGRATION — make the codebase actually run as one app.\n\n"
            f"NEW FILES (written this sprint):\n{files_list}\n\n"
            f"AFFECTED FILES (existing files that import from the new files — may be broken):\n{affected_list}\n\n"
            f"STEP 1 — Understand the codebase\n"
            f"  list_files() to see everything written.\n"
            f"  read_file() the entry point and any config files (requirements.txt, package.json,\n"
            f"  docker-compose.yml, Makefile, etc.) to understand exactly how this app is started.\n"
            f"  Determine: what is the boot command? what port does it run on? what is the health endpoint?\n\n"
            f"STEP 2 — Audit and fix\n"
            f"  read_file() every file in the NEW FILES and AFFECTED FILES lists.\n"
            f"  search_codebase() for import mismatches, wrong function names, missing symbols.\n"
            f"  write_code_file() to patch anything broken.\n"
            f"  Check that all required scaffold files exist (e.g. for React: public/index.html,\n"
            f"  src/index.js — write them if missing).\n"
            f"  validate_python() on every Python file you touch.\n\n"
            f"STEP 3 — THIS STEP IS MANDATORY. Boot the app and verify it responds.\n"
            f"  Using what you learned in Step 1:\n"
            f"    start_service('app', '<the actual boot command you found>')\n"
            f"    http_request('GET', '<the actual health or root URL you found>')\n"
            f"    run_shell('pytest') or run_shell('npm test') if test files exist\n"
            f"    stop_service('app')\n"
            f"  Do NOT use placeholder commands. Use the real boot command from the codebase.\n"
            f"  Do NOT declare INTEGRATION: DONE without showing actual HTTP response output.\n"
            f"  If the boot fails, read the error, fix the file, and retry.\n\n"
            f"Fix everything. Do not summarize problems — solve them.\n"
            f"End with: INTEGRATION: DONE (paste the actual HTTP response) "
            f"or INTEGRATION: PARTIAL (list exactly what failed and why).",
            manager_role,
            label=f"{manager_role}_integration",
        )
        rolling_ctxs[manager_role].add(task, integration_output)
        logger.info(f"[{manager_role}] integration pass: {integration_output[:150]}...")
    else:
        integration_output = ""

    # ── Final manager synthesis ───────────────────────────────────────────
    summaries = "\n\n".join(
        f"=== {current[r].title} (stance={current[r].stance.upper()}, F={current[r].F_health:.3f}"
        f"{'⚠' if current[r].anomaly else ''}) ===\n{current[r].output[:900]}"
        for r in worker_roles
    )
    integration_section = (
        f"\n\nINTEGRATION PASS OUTPUT:\n{integration_output[:800]}"
        if integration_output else ""
    )
    synthesis = llm_call(
        f"You are the {ROLES[manager_role]['title']}.\n\n"
        f"TASK: {task}\n\n"
        f"TEAM OUTPUTS (after {round_num} round(s)):\n{summaries}"
        f"{integration_section}\n\n"
        f"Consensus stance: {consensus.upper()} — {STANCE_DESC[consensus]}\n"
        f"H_swarm={H_swarm:.3f} "
        f"({'stable' if H_swarm < stable_thr else 'elevated — flag risky decisions'})\n\n"
        f"Synthesize the best elements into a single coherent, complete deliverable. "
        f"Resolve any remaining conflicts. Be thorough and specific.",
        label=f"{manager_role}_synthesis",
        system=_manager_system(manager_role),
    )

    for role in worker_roles:
        rolling_ctxs[role].add(task, current[role].output)
    rolling_ctxs[manager_role].add(task, synthesis)

    # Write canonical file so other teams can reference this team's output
    # QA appends (findings accumulate), others overwrite (latest spec wins)
    _write_canonical_file(team_name, synthesis, append=(team_name == "QA"))

    # Post-interference free energy for final H_swarm
    H_swarm     = sum(health_states[r].free_energy() for r in worker_roles)
    mean_stance = np.mean([np.array(current[r].stance_probs) for r in worker_roles], axis=0)
    consensus   = STANCES[int(mean_stance.argmax())]

    return TeamResult(
        team=team_name,
        manager_synthesis=synthesis,
        worker_outputs=[current[r] for r in worker_roles],   # deterministic order
        H_swarm=H_swarm,
        consensus_stance=consensus,
        confidence=max(0.0, 1.0 - H_swarm / (1.5 * n_workers)),  # mean-based, consistent with eng team
    )


# ── Executive meeting: CEO + all managers plan together ───────────────────────

MANAGER_ROLES = {
    "Architecture": "arch_manager",
    "Design":       "design_manager",
    "Engineering":  "eng_manager",
    "QA":           "qa_manager",
}

TEAM_TASKS_PROMPT = {
    "Architecture": "design the system architecture, API contracts, and data model",
    "Design":       "define UX flows, UI components, and visual style guide",
    "Engineering":  "implement the full software — backend, frontend, and infrastructure",
    "QA":           "test correctness, integration, performance, and security",
}


def run_executive_meeting(
    brief: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> ExecutionPlan:
    """
    CEO + all 4 managers meet together.
    Round 1: each manager independently assesses their team's readiness and dependencies.
    Round 2: each manager sees all other managers' positions, may negotiate.
    CEO final: synthesises into an execution plan with phases and wait decisions.

    Returns (ExecutionPlan, {team: task_description}).
    """
    logger.info(f"\n{'═'*55}\nEXECUTIVE MEETING: CEO + all managers\n{'═'*55}")

    team_names = list(MANAGER_ROLES.keys())

    # ── Round 1: CEO opens, managers respond independently ────────────────
    ceo_opening = llm_call(
        f"You are the CEO of a software company.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Open the executive meeting. Briefly state:\n"
        f"1. The project goal and key constraints\n"
        f"2. The four team workstreams (Architecture, Design, Engineering, QA)\n"
        f"3. Ask each manager to assess: can they start immediately, or do they "
        f"need to wait for another team? What are their dependencies?\n\n"
        f"Keep it concise — 150 words max.",
        label="ceo_opening",
        system=_SYSTEM_CEO,
    )
    logger.info(f"\nCEO opens meeting: {ceo_opening[:120]}...")

    def manager_r1(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        output = llm_call(
            f"You are the {ROLES[role_key]['title']}.\n\n"
            f"CEO's opening:\n{ceo_opening}\n\n"
            f"Your team's responsibility: {TEAM_TASKS_PROMPT[team_name]}\n\n"
            f"Respond to the CEO. State:\n"
            f"1. Can your team START IMMEDIATELY or do you need to WAIT for another team?\n"
            f"2. If waiting: which team and what specific output do you need?\n"
            f"3. Can you do any partial work while waiting? What?\n"
            f"4. What does your team need from others to do their best work?\n\n"
            f"Be direct and specific. 100 words max.",
            label=f"{role_key}_r1",
            system=_manager_system(role_key),
        )
        return team_name, output

    r1: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for team_name, output in ex.map(lambda t: manager_r1(t), team_names):
            r1[team_name] = output

    # Health interference across managers
    ActiveInferenceState.interfere_all(
        [health_states[MANAGER_ROLES[t]] for t in team_names], alpha=INTERFERENCE_ALPHA
    )

    # ── Round 2: managers see all positions, negotiate ────────────────────
    all_r1 = "\n\n".join(
        f"{ROLES[MANAGER_ROLES[t]]['title']}:\n{r1[t]}" for t in team_names
    )

    def manager_r2(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        output = llm_call(
            f"You are the {ROLES[role_key]['title']}.\n\n"
            f"All managers have responded:\n{all_r1}\n\n"
            f"Your team: {TEAM_TASKS_PROMPT[team_name]}\n\n"
            f"After hearing everyone:\n"
            f"1. Confirm or update your start decision (START NOW / WAIT FOR X)\n"
            f"2. If you can start partial work in parallel, what specifically?\n"
            f"3. Any concerns or blockers to flag to the CEO?\n\n"
            f"50 words max.",
            label=f"{role_key}_r2",
            system=_manager_system(role_key),
        )
        return team_name, output

    r2: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for team_name, output in ex.map(lambda t: manager_r2(t), team_names):
            r2[team_name] = output

    # ── CEO synthesises execution plan ────────────────────────────────────
    all_r2 = "\n\n".join(
        f"{ROLES[MANAGER_ROLES[t]]['title']} (final):\n{r2[t]}" for t in team_names
    )
    plan_output = llm_call(
        f"You are the CEO.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Meeting summary:\n{all_r1}\n\nFinal positions:\n{all_r2}\n\n"
        f"Produce the execution plan. Your job is ONLY to decide the order and dependencies — "
        f"each team will figure out internally what to build and who does what.\n\n"
        f"Format EXACTLY as:\n\n"
        f"PHASE_1: <comma-separated team names that start immediately>\n"
        f"PHASE_2: <teams that start after Phase 1 completes>\n"
        f"PHASE_3: <teams that start after Phase 2 completes>\n"
        f"PHASE_4: <teams that start after Phase 3 completes>\n\n"
        f"(Only include phases that are needed. Skip empty phases.)\n\n"
        f"NOTES: <why this ordering — what each waiting team needs from the phase before it>",
        label="ceo_plan",
        system=_SYSTEM_CEO,
    )

    # Parse phases
    phases: List[List[str]] = []
    for i in range(1, 5):
        m = re.search(rf"PHASE_{i}:\s*(.+)", plan_output, re.IGNORECASE)
        if m:
            teams_in_phase = [t.strip() for t in m.group(1).split(",")]
            # Normalise to canonical names matching TEAM_RUNNERS keys
            canonical = {"Architecture", "Design", "Engineering", "QA"}
            normalised = [
                next((c for c in canonical if c.lower() in t.lower()), t.strip().capitalize())
                for t in teams_in_phase
            ]
            phases.append(normalised)

    if not phases:  # fallback
        phases = [["Architecture"], ["Design"], ["Engineering"], ["QA"]]

    notes_m = re.search(r"NOTES:\s*(.+)", plan_output, re.DOTALL | re.IGNORECASE)
    notes_text = notes_m.group(1).strip() if notes_m else ""

    # Log the plan
    logger.info(f"\nEXECUTION PLAN:")
    for i, phase in enumerate(phases, 1):
        logger.info(f"  Phase {i}: {' + '.join(phase)}")
    logger.info(f"  Notes: {notes_text[:120]}")

    full_transcript = (
        f"CEO opening:\n{ceo_opening}\n\n"
        f"Manager round 1:\n{all_r1}\n\n"
        f"Manager round 2:\n{all_r2}\n\n"
        f"CEO plan:\n{plan_output}"
    )

    # Update rolling contexts
    for team_name, role_key in MANAGER_ROLES.items():
        rolling_ctxs[role_key].add("executive meeting", r2[team_name])

    # Save conversation log
    turns = [{"speaker": "CEO", "text": ceo_opening}]
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R1)", "text": r1[t]})
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R2)", "text": r2[t]})
    turns.append({"speaker": "CEO — Execution Plan", "text": plan_output})
    _save_conversation("Executive Meeting", turns)

    return ExecutionPlan(
        raw=full_transcript,
        phases=phases,
        team_notes={"all": notes_text},
    )


# ── Sprint planning: engineering manager + devs discuss together ──────────────

def _generate_contracts(
    task: str,
    dev_assignments: Dict[str, str],
    pool: Dict[str, str] = None,
) -> None:
    """
    After sprint planning assigns work items, ask the manager to generate
    typed interface contracts that all agents must follow.
    """
    logger.info(f"\n{'─'*55}\nCONTRACT GENERATION: Engineering\n{'─'*55}")

    assignment_list = "\n".join(
        f"  {dev}: owns {desc}" for dev, desc in dev_assignments.items()
    )
    if pool:
        pool_list = "\n".join(f"  [Pool] {iid}: {desc}" for iid, desc in pool.items())
        assignment_list += f"\n\nUNASSIGNED BACKLOG POOL:\n{pool_list}"
    
    # Inject Architect's intended structure if available
    struct_ctx = ""
    struct_path = OUTPUT_DIR / "design" / "project_structure.md"
    if struct_path.exists():
        struct_ctx = f"\n\nARCHITECT'S PROJECT STRUCTURE (MANDATORY FILE PATHS):\n{struct_path.read_text(encoding='utf-8')[:3000]}"

    if AGILE_MODE:
        contract_prompt = (
            f"You are the Engineering Manager.\n\n"
            f"PROJECT:\n{task[:600]}\n\n"
            f"DEV ASSIGNMENTS:\n{assignment_list}\n"
            f"{struct_ctx}\n\n"
            f"Currently we are in AGILE MODE. Do NOT generate rigid typed signatures or exact data models. "
            f"Instead, generate a Collaborative Task List that maps files to owners and gives high-level feature descriptions. "
            f"The developers will use broadcasting and messaging to agree on the exact interfaces as they build them.\n\n"
            f"Output EXACTLY this JSON structure (no markdown fences, just raw JSON):\n"
            f'{{\n'
            f'  "build_command": "python server.py",\n'
            f'  "build_file": "requirements.txt",\n'
            f'  "dependencies": ["sqlite3"],\n'
            f'  "init_order": [],\n'
            f'  "models": [],\n'
            f'  "endpoints": [],\n'
            f'  "files": [\n'
            f'    {{"file": "models.py", "owner": "dev_1", "imports_from": [], '
            f'"exports": [], "depends_on": [], "description": "Collaborative data models — define as needed and broadcast changes"}},\n'
            f'    {{"file": "routes.py", "owner": "dev_2", "imports_from": ["models.py"], '
            f'"exports": [], "depends_on": ["models.py"], "description": "API routes — negotiate signatures with frontend"}}\n'
            f'  ],\n'
            f'  "entry_point": "server.py",\n'
            f'  "entry_imports": []\n'
            f'}}\n\n'
            f"RULES:\n"
            f"- Every dev must own at least one file\n"
            f"- Use 'files' to define ownership and 'description' to give the collaborative goal\n"
            f"- The entry point file is SYSTEM-MANAGED — set its owner to 'system'\n"
            f"- 'depends_on' should only be used for high-level file ordering\n"
        )
    else:
        contract_prompt = (
            f"You are the Engineering Manager.\n\n"
            f"PROJECT:\n{task[:600]}\n\n"
            f"DEV ASSIGNMENTS:\n{assignment_list}\n"
            f"{struct_ctx}\n\n"
            f"Generate typed interface contracts so all developers use identical "
            f"signatures, import paths, and data models. This prevents integration failures.\n\n"
            f"Output EXACTLY this JSON structure (no markdown fences, just raw JSON):\n"
            f'{{\n'
            f'  "build_command": "python server.py",\n'
            f'  "build_file": "requirements.txt",\n'
            f'  "dependencies": ["sqlite3"],\n'
            f'  "init_order": ["database", "routes", "server"],\n'
            f'  "models": [\n'
            f'    {{"name": "ModelName", "fields": "field1: type, field2: type", "file": "models.py"}}\n'
            f'  ],\n'
            f'  "endpoints": [\n'
            f'    {{"method": "POST", "path": "/items", "request_model": "ItemCreate", "response_model": "Item"}}\n'
            f'  ],\n'
            f'  "files": [\n'
            f'    {{"file": "models.py", "owner": "dev_1", "imports_from": [], '
            f'"exports": ["Item"], "depends_on": [], "description": "data models"}},\n'
            f'    {{"file": "routes.py", "owner": "dev_2", "imports_from": ["models.py"], '
            f'"exports": ["create_item"], "depends_on": ["models.py"], "description": "API routes"}}\n'
            f'  ],\n'
            f'  "entry_point": "server.py",\n'
            f'  "entry_imports": ["routes", "database"]\n'
            f'}}\n\n'
            f"RULES:\n"
            f"- Every dev must own at least one file\n"
            f"- Shared models/types go in ONE file that everyone imports from\n"
            f"- The entry point file is SYSTEM-MANAGED — set its owner to 'system'\n"
            f"  (The entry point will be auto-generated to wire all modules together)\n"
            f"- NO two devs should own the same file — split into separate modules instead\n"
            f"- Include ALL files needed for a working application\n"
            f"- 'depends_on' MUST list files that must be complete before this file can be written.\n"
            f"  Files with no dependencies have 'depends_on': []. The entry point depends on ALL other files.\n"
            f"  Test files depend on the files they test.\n"
            f"- 'exports' MUST list the exact symbol names other files need to import from this file\n"
            f"- 'build_command' is the shell command to run the app or run tests\n"
            f"- 'build_file' is the config file that lists dependencies (e.g. 'requirements.txt', 'Cargo.toml',\n"
            f"  'package.json', 'go.mod'). Leave empty if not applicable.\n"
            f"- 'install_command' is the shell command to install dependencies before building\n"
            f"  (e.g. 'npm install', 'pip install -r requirements.txt', 'cargo fetch', 'go mod download').\n"
            f"  Leave empty if no install step is needed.\n"
            f"- 'gitignore_patterns' is a list of patterns for .gitignore based on the build system\n"
            f"  (e.g. ['node_modules/', 'dist/', 'package-lock.json'] for Node,\n"
            f"  ['__pycache__/', '*.pyc', 'dist/', 'build/'] for Python,\n"
            f"  ['target/'] for Rust). Always include build artifacts and dependency directories.\n"
            f"- 'dependencies' lists external libraries needed (e.g. ['fastapi', 'sqlalchemy'])\n"
            f"- 'init_order' lists modules in the order they should be initialized (if ordering matters)\n"
        )

    contract_output = llm_call(
        contract_prompt,
        label="eng_contracts",
        system=_manager_system("eng_manager"),
    )

    # Parse JSON from the output — tolerant of markdown fences
    json_text = contract_output.strip()
    if "```" in json_text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", json_text, re.DOTALL)
        if m:
            json_text = m.group(1).strip()

    try:
        parsed = json.loads(json_text)
        registry = get_contracts()
        registry.set_from_parsed(parsed)
        logger.info(
            f"  Contracts generated: {len(registry.models)} models, "
            f"{len(registry.endpoints)} endpoints, {len(registry.file_map)} files"
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"  Contract parsing failed ({e}) — continuing without typed contracts")


def run_sprint_planning(
    task: str,
    health_states: Dict[str, ActiveInferenceState],
    rolling_ctxs: Dict[str, RollingContext],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Engineering sprint planning: assign work items via blackboard,
    then generate typed interface contracts for all agents.
    """
    dev_assignments, pool = run_team_planning(
        "Engineering", "eng_manager", ENG_WORKERS, task, rolling_ctxs, health_states
    )

    # Generate typed contracts so agents share exact signatures
    _generate_contracts(task, dev_assignments, pool)

    return dev_assignments, pool


def run_ceo_summary(
    brief: str,
    results: Dict[str, Optional[TeamResult]],
    plan: ExecutionPlan,
    ctx: RollingContext,
) -> str:
    team_text = "\n\n".join(
        f"{name} (confidence {t.confidence:.0%}, H={t.H_swarm:.3f}):\n{t.manager_synthesis[:500]}"
        for name, t in results.items() if t is not None
    )
    plan_text = ""
    if plan:
        phase_lines = "\n".join(
            f"  Phase {i}: {' + '.join(teams)}"
            for i, teams in enumerate(plan.phases, 1)
        )
        notes = plan.team_notes.get("all", "")
        plan_text = (
            f"Phases:\n{phase_lines}\n"
            + (f"Notes: {notes[:300]}" if notes else "")
        )
    summary = llm_call(
        f"You are the CEO.\n\nPROJECT: {brief}\n\n"
        + (f"EXECUTION PLAN:\n{plan_text}\n\n" if plan_text else "")
        + f"TEAM RESULTS:\n{team_text}\n\n"
        f"Write an executive summary:\n"
        f"1. Project Overview\n2. Key Architecture Decisions\n3. Design Highlights\n"
        f"4. Implementation Highlights\n5. Quality & Risk Assessment\n6. Next Steps\n\n"
        f"Flag any elevated H_swarm teams. Be concise and actionable.",
        label="ceo_summary",
        system=_SYSTEM_CEO,
    )
    ctx.add(brief, summary)
    return summary


# ── Engineering team: sprint planning → parallel build → synthesize ──────────

MAX_ENG_ROUNDS = 4   # hard cap per sprint to control cost (legacy, kept for reference)
MAX_SPRINTS    = 5   # safety cap — CEO should ship before this; prevents runaway cost

# ── Async task-completion constants ───────────────────────────────────────────
MAX_TASKS_PER_AGENT = 20
MAX_WALL_CLOCK      = 600   # seconds — hard timeout for entire engineering phase
MAX_RETRIES_PER_TASK = 10
_AGENT_POLL_INTERVAL = 2    # seconds between task queue polls when blocked

# Phase constants (integration task still uses PHASE_INTEGRATION as a marker)
PHASE_IMPLEMENTATION = 1   # Coding individual files
PHASE_INTEGRATION    = 2   # Final integration test (manager fix loop)


@dataclass
class EngTask:
    """A single unit of engineering work, mapped to one file from the contracts."""
    id: str
    file: str
    description: str
    depends_on: List[str]
    assigned_to: Optional[str] = None
    status: str = "pending"       # pending | blocked | in_progress | completed | failed
    retries: int = 0
    primary_owner: Optional[str] = None  # legacy field; ownership is no longer used for claiming
    phase: int = PHASE_IMPLEMENTATION


class EngTaskQueue:
    """
    Thread-safe shared task queue for async engineering dispatch.
    Tasks with unmet dependencies stay blocked until prerequisites complete.
    """

    def __init__(
        self,
        registry: InterfaceContractRegistry,
        dev_assignments: Dict[str, str],
        pool_tasks: Dict[str, str] = None,
    ):
        self._lock = threading.RLock()
        self.tasks: Dict[str, EngTask] = {}
        self._completed_tasks: set = set()
        pool_tasks = pool_tasks or {}

        def _is_valid_fname(fname: str) -> bool:
            """Reject wildcard/glob paths the LLM sometimes generates (e.g. migrations/versions/*)."""
            return not any(c in fname for c in ("*", "?", "<", ">", "|"))

        file_to_task_id = {}
        for fname, fc in registry.file_map.items():
            if fname == registry.entry_point:
                continue
            if not _is_valid_fname(fname):
                logger.warning(f"[TaskQueue] skipping invalid filename in contracts: {fname!r}")
                continue
            tid = f"task_{fname.replace('/', '_').replace('.', '_')}"
            file_to_task_id[fname] = tid

        # Phase 1: Implementation (Drafting)
        for fname, fc in registry.file_map.items():
            if fname == registry.entry_point:
                continue
            if not _is_valid_fname(fname):
                continue
            tid = f"task_{fname.replace('/', '_').replace('.', '_')}_p1"
            dep_ids = [
                f"task_{d.replace('/', '_').replace('.', '_')}_p1" for d in fc.depends_on
                if d in file_to_task_id
            ]
            desc = f"PHASE 1: Implementation and local drafting for {fname}"
            for dk, assignment in dev_assignments.items():
                if fname in assignment:
                    desc = f"PHASE 1: {assignment}"
                    break

            self.tasks[tid] = EngTask(
                id=tid, file=fname, description=desc,
                depends_on=dep_ids, status="pending" if not dep_ids else "blocked",
                phase=PHASE_IMPLEMENTATION
            )

        integ_tid = "task_integration_test"
        self.tasks[integ_tid] = EngTask(
            id=integ_tid, file="__integration__",
            description="Final integration: final build check and smoke tests",
            depends_on=list(self.tasks.keys()),
            status="blocked", # Always last
            phase=PHASE_INTEGRATION
        )

        # Any files NOT covered by dev assignments (pool tasks)
        for iid, pool_desc in pool_tasks.items():
            # Try to extract file if it's there
            file_match = re.search(r"\[([^\]]+)\]", pool_desc)
            if file_match:
                p_files = [f.strip() for f in file_match.group(1).split(",") if f.strip()]
                for pf in p_files:
                    if pf in file_to_task_id:
                        # Existing file is now part of an unassigned Pool Task
                        tid = file_to_task_id[pf] + "_p1"
                        if tid in self.tasks:
                            self.tasks[tid].description = f"POOL TASK: {pool_desc}"

        n_pending = sum(1 for t in self.tasks.values() if t.status == "pending")
        n_blocked = sum(1 for t in self.tasks.values() if t.status == "blocked")
        logger.info(f"[TaskQueue] initialized {len(self.tasks)} tasks ({n_pending} pending, {n_blocked} blocked) + final integration.")
        self._load()   # crash recovery: reload persisted state if available
        # After reload, dependencies that were already satisfied in the persisted state
        # must be re-evaluated — without this, Phase 2 tasks stay blocked forever on restart.
        self._unblock_dependents()
        self._persist()

    # _PERSIST_PATH must NOT be a class attribute — OUTPUT_DIR may be overridden at
    # runtime. A frozen class attr would always point at company_output/task_queue_state.json
    # and load stale task states from a prior full-company run into an engineers-only run.
    @property
    def _persist_path(self) -> Path:
        return OUTPUT_DIR / "task_queue_state.json"

    def _persist(self) -> None:
        """Serialize queue state to disk after every mutation."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "tasks": {
                    tid: {
                        "id": t.id, "file": t.file, "description": t.description,
                        "depends_on": t.depends_on, "assigned_to": t.assigned_to,
                        "status": t.status, "retries": t.retries,
                        "primary_owner": t.primary_owner, "phase": t.phase,
                    }
                    for tid, t in self.tasks.items()
                },
                "completed_tasks": list(self._completed_tasks),
            }
            self._persist_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[TaskQueue] persist failed: {e}")

    def _load(self) -> None:
        """Reload queue state from disk if available (crash recovery)."""
        if not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for tid, td in data.get("tasks", {}).items():
                if tid in self.tasks:
                    t = self.tasks[tid]
                    t.status      = td.get("status", t.status)
                    t.assigned_to = td.get("assigned_to", t.assigned_to)
                    t.retries     = td.get("retries", t.retries)
            self._completed_tasks = set(data.get("completed_tasks", []))
            logger.info(f"[TaskQueue] crash-recovery: reloaded state from {self._persist_path.name}")
        except Exception as e:
            logger.warning(f"[TaskQueue] load failed: {e}")

    def claim_next(self, dev_key: str) -> Optional[EngTask]:
        """Claim the next available pending task from the shared pool."""
        with self._lock:
            for t in self.tasks.values():
                if t.status != "pending":
                    continue
                t.status = "in_progress"
                t.assigned_to = dev_key
                logger.info(f"[TaskQueue] {dev_key} claimed task '{t.id}' ({t.file})")
                self._persist()
                return t
            return None

    def complete(self, task_id: str) -> None:
        """Mark a task completed and unblock dependents."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.status = "completed"
                self._completed_tasks.add(task_id)
                logger.info(f"[TaskQueue] task '{task_id}' COMPLETED")
                self._unblock_dependents()
                self._persist()

    def get_retries(self, task_id: str) -> int:
        """Return retry count for a task, thread-safely."""
        with self._lock:
            task = self.tasks.get(task_id)
            return task.retries if task else MAX_RETRIES_PER_TASK

    def fail(self, task_id: str) -> None:
        """Mark a task failed. It may be retried by another agent."""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                task.retries += 1
                if task.retries < MAX_RETRIES_PER_TASK:
                    task.status = "pending"
                    task.assigned_to = None
                    logger.warning(f"[TaskQueue] task '{task_id}' failed — requeueing (retry {task.retries})")
                else:
                    task.status = "failed"
                    self._completed_tasks.add(task_id)
                    logger.error(f"[TaskQueue] task '{task_id}' FAILED permanently after {task.retries} retries")
                    self._unblock_dependents()
                self._persist()

    def _unblock_dependents(self) -> None:
        """Move blocked tasks to pending if all their dependencies are satisfied."""
        for t in self.tasks.values():
            if t.status == "blocked":
                deps_met = all(d in self._completed_tasks for d in t.depends_on)
                if deps_met:
                    t.status = "pending"
                    logger.info(f"[TaskQueue] unblocked task '{t.id}' ({t.file})")

    def all_done(self) -> bool:
        with self._lock:
            return all(t.status in ("completed", "failed") for t in self.tasks.values())

    def has_work_available(self) -> bool:
        """True if there are pending tasks or in-progress tasks that might unblock others."""
        with self._lock:
            return any(t.status in ("pending", "in_progress", "blocked") for t in self.tasks.values())

    def get_status(self) -> str:
        with self._lock:
            counts = {"pending": 0, "blocked": 0, "in_progress": 0, "completed": 0, "failed": 0}
            for t in self.tasks.values():
                counts[t.status] = counts.get(t.status, 0) + 1
            lines = [f"Tasks: {len(self.tasks)} total"]
            for status, count in counts.items():
                if count:
                    lines.append(f"  {status}: {count}")
            in_prog = [t for t in self.tasks.values() if t.status == "in_progress"]
            if in_prog:
                lines.append("  Active:")
                for t in in_prog:
                    lines.append(f"    {t.assigned_to} → {t.file}")
            return "\n".join(lines)

    def get_completed_files(self) -> List[str]:
        """Return filenames of completed tasks (for peer context)."""
        with self._lock:
            return [t.file for t in self.tasks.values() if t.status == "completed" and t.file != "__integration__"]

    def force_fail_remaining(self) -> None:
        """Mark all non-terminal tasks as failed (used by wall-clock timeout)."""
        with self._lock:
            for t in self.tasks.values():
                if t.status in ("pending", "blocked", "in_progress"):
                    t.status = "failed"
            self._completed_tasks.update(t.id for t in self.tasks.values() if t.status == "failed")

    def cancel_all(self) -> None:
        """Immediately cancel all pending/blocked/in-progress tasks.
        Used by the token budget kill-switch to stop the swarm cleanly."""
        with self._lock:
            for t in self.tasks.values():
                if t.status not in ("completed", "failed"):
                    t.status = "failed"
            self._completed_tasks.update(t.id for t in self.tasks.values())
        logger.critical("[TaskQueue] ALL TASKS CANCELLED — token budget kill-switch triggered")


def emit_skeleton(dev_assignments: Dict[str, str], sprint_num: int = 1) -> None:
    """
    Write skeleton/stub files based on interface contracts before Round 1.
    Pre-populates dashboard domain claims so agents don't fight over files.
    Entry point is registered as a SHARED file (system-managed).
    Agents fill in the stubs rather than inventing their own file structure.
    """
    registry = get_contracts()
    if not registry.file_map and not registry.models:
        logger.info("[skeleton] No contracts available — skipping skeleton generation")
        return

    logger.info(f"\n{'─'*55}\nSKELETON GENERATION\n{'─'*55}")
    code_dir = OUTPUT_DIR / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    dashboard = get_dashboard()
    files_written = 0


    # ── Write shared model stubs ─────────────────────────────────────────────
    model_files_seen: set = set()
    for model in registry.models:
        model_file = code_dir / model.file
        if model_file.exists() and model.file in model_files_seen:
            continue
        model_files_seen.add(model.file)
        model_file.parent.mkdir(parents=True, exist_ok=True)
        fields_lines = []
        for field_str in model.fields.split(","):
            field_str = field_str.strip()
            if field_str:
                fields_lines.append(f"    {field_str}")
        fields_block = "\n".join(fields_lines) if fields_lines else "    pass"
        stub = (
            f"# AUTO-GENERATED SKELETON — implement the bodies\n"
            f"# Owner: system\n\n"
            f"class {model.name}:\n"
            f"{fields_block}\n"
        )
        if model_file.exists():
            existing = model_file.read_text(encoding="utf-8")
            model_file.write_text(existing + "\n\n" + stub, encoding="utf-8")
        else:
            model_file.write_text(stub, encoding="utf-8")
        files_written += 1
        logger.info(f"  [skeleton] wrote model stub: {model.file}")

    # ── Write generic file stubs ─────────────────────────────────────────────
    _EXT_COMMENTS = {
        ".py": ("#", ""),    ".go": ("//", ""),    ".rs": ("//", ""),
        ".js": ("//", ""),   ".ts": ("//", ""),    ".jsx": ("//", ""),
        ".tsx": ("//", ""),  ".java": ("//", ""),  ".c": ("//", ""),
        ".cpp": ("//", ""),  ".rb": ("#", ""),     ".lua": ("--", ""),
    }

    for fname, fc in registry.file_map.items():
        if fname == registry.entry_point:
            continue

        # Skip wildcard/glob paths that the LLM sometimes generates (e.g. "migrations/versions/*")
        # — these are not valid file paths on any OS.
        if any(c in fname for c in ("*", "?", "<", ">", "|")):
            logger.warning(f"  [skeleton] skipping invalid filename (contains wildcard/illegal char): {fname!r}")
            continue

        file_path = code_dir / fname
        if file_path.exists():
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)

        ext = Path(fname).suffix
        comment_prefix, _ = _EXT_COMMENTS.get(ext, ("#", ""))

        stub = (
            f"{comment_prefix} AUTO-GENERATED SKELETON — {fc.description}\n"
            f"{comment_prefix} Owner: {fc.owner}\n"
            f"{comment_prefix} Exports: {', '.join(fc.exports)}\n"
            f"{comment_prefix} Imports from: {', '.join(fc.imports_from) if fc.imports_from else 'none'}\n"
            f"{comment_prefix} TODO: implement this file\n"
        )

        file_path.write_text(stub, encoding="utf-8")
        files_written += 1
        logger.info(f"  [skeleton] wrote stub: {fname} (owner: {fc.owner})")


    logger.info(f"  [skeleton] {files_written} stub files written")






def enforce_integration() -> str:
    """
    Lightweight integration enforcer:
      1. Creates missing __init__.py files for Python packages
      2. Assembles shared files from their sections
      3. Uses LLM to generate the entry point that wires all modules
      4. Uses LLM to generate build config files if needed
      5. Runs the build command and returns errors for the agents to fix
    """
    code_dir = OUTPUT_DIR / "code"
    if not code_dir.exists():
        return ""

    registry = get_contracts()
    fixes: List[str] = []

    # 1. Create missing __init__.py for any dir with .py files
    for dirpath in code_dir.rglob("*"):
        if dirpath.is_dir() and any(dirpath.glob("*.py")):
            init = dirpath / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
                fixes.append(f"Created {init.relative_to(code_dir)}")


    # 3. LLM-generate entry point
    if registry.entry_point and registry.file_map:
        ep_result = _generate_entry_point_via_llm(registry, code_dir)
        if ep_result:
            fixes.append(f"LLM-generated entry point '{registry.entry_point}'")

    # 4. LLM-generate build config
    if registry.build_file:
        bf_result = _emit_build_scaffold_via_llm(registry, code_dir)
        if bf_result:
            fixes.append(f"LLM-generated build config '{registry.build_file}'")

    if fixes:
        report = "INTEGRATION ENFORCER — auto-fixes applied:\n" + "\n".join(f"  + {f}" for f in fixes)
        logger.info(f"\n{report}")
        return report
    return ""


def _run_build_command(registry: InterfaceContractRegistry) -> str:
    """Run the build command and return its output (empty if success)."""
    if not registry.build_command:
        return ""
    code_dir = OUTPUT_DIR / "code"
    if not code_dir.exists():
        return ""
    try:
        result = subprocess.run(
            registry.build_command, shell=True, cwd=str(code_dir),
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            out = ((result.stdout or "")[-2000:] + "\n" + (result.stderr or "")[-2000:]).strip()
            return f"BUILD FAILED (exit {result.returncode}):\n{out}"
    except subprocess.TimeoutExpired:
        return "BUILD TIMEOUT: command took longer than 60s"
    except Exception as e:
        return f"BUILD ERROR: {e}"
    return ""


@dataclass
class TestGateResult:
    passed:  bool    # True if tests exited 0, or no test suite found
    skipped: bool    # True if no test files were detected
    output:  str     # raw stdout+stderr trimmed to 4000 chars
    command: str     # command that ran (empty if skipped)


def _run_test_gate(code_dir: Path) -> TestGateResult:
    """
    Run the project's test suite.
    If TEST_GATE_HOOKS is non-empty, run each hook command in sequence — the gate
    fails on the first non-zero exit.  When empty, fall back to auto-detection
    (pytest or npm).
    Returns TestGateResult. Never raises — all failures are captured in .output.
    Called by the manager fix loop and by self-verification.
    """
    # ── Configurable hooks path ───────────────────────────────────────────
    if TEST_GATE_HOOKS:
        combined_output: List[str] = []
        for hook_cmd in TEST_GATE_HOOKS:
            try:
                result = subprocess.run(
                    hook_cmd, shell=True, capture_output=True, text=True,
                    timeout=60, cwd=str(code_dir),
                    encoding="utf-8", errors="replace",
                )
                raw = ((result.stdout or "") + (result.stderr or ""))[-4000:]
                combined_output.append(f"[hook: {hook_cmd}]\n{raw}")
                if result.returncode != 0:
                    return TestGateResult(
                        passed=False, skipped=False,
                        output="\n".join(combined_output),
                        command=hook_cmd,
                    )
            except subprocess.TimeoutExpired:
                combined_output.append(f"[hook: {hook_cmd}] TIMEOUT after 60s")
                return TestGateResult(
                    passed=False, skipped=False,
                    output="\n".join(combined_output),
                    command=hook_cmd,
                )
            except Exception as e:
                combined_output.append(f"[hook: {hook_cmd}] ERROR: {e}")
                return TestGateResult(
                    passed=False, skipped=False,
                    output="\n".join(combined_output),
                    command=hook_cmd,
                )
        return TestGateResult(
            passed=True, skipped=False,
            output="\n".join(combined_output),
            command="; ".join(TEST_GATE_HOOKS),
        )

    # ── Auto-detect path (language-agnostic) ─────────────────────────────
    tests_dir = code_dir / "tests"

    def _has_test_files(*globs: str) -> bool:
        for d in (tests_dir, code_dir):
            if d.exists():
                for g in globs:
                    for p in d.rglob(g):
                        if "node_modules" not in p.parts and ".git" not in p.parts:
                            return True
        return False

    def _has_file(*names: str) -> bool:
        return any((code_dir / n).exists() for n in names)

    def _makefile_has_test() -> bool:
        mf = code_dir / "Makefile"
        if not mf.exists():
            return False
        try:
            return "test" in mf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False

    # Detection order: most-specific first
    # Use `python -m pytest` so it works regardless of whether `pytest` is on
    # the system PATH (common on Windows where the Scripts/ directory may be absent).
    if _has_test_files("test_*.py", "*_test.py"):
        cmd = f"{sys.executable} -m pytest {str(tests_dir)} --tb=short -q"
    elif _has_file("Cargo.toml"):
        cmd = "cargo test"
    elif _has_file("go.mod"):
        cmd = "go test ./..."
    elif _has_file("pom.xml"):
        cmd = "mvn test -q"
    elif _has_file("build.gradle", "build.gradle.kts"):
        cmd = "gradle test"
    elif _has_file("*.csproj") or any(code_dir.glob("*.sln")):
        cmd = "dotnet test"
    elif _has_file("CMakeLists.txt"):
        cmd = "cmake --build build/ && ctest --test-dir build/ --output-on-failure"
    elif _makefile_has_test():
        cmd = "make test"
    elif _has_test_files("*.spec.ts", "*.spec.js", "*.test.ts", "*.test.js") or _has_file("package.json"):
        cmd = "npm test --if-present"
    elif _has_test_files("*_spec.rb", "*_test.rb"):
        cmd = "bundle exec rspec"
    else:
        return TestGateResult(passed=True, skipped=True, output="", command="")

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=120, cwd=str(code_dir),
            encoding="utf-8", errors="replace",
        )
        raw = ((result.stdout or "") + (result.stderr or ""))[-4000:]
        return TestGateResult(passed=(result.returncode == 0), skipped=False,
                              output=raw, command=cmd)
    except subprocess.TimeoutExpired:
        return TestGateResult(passed=False, skipped=False, command=cmd,
                              output="TEST GATE TIMEOUT: suite did not finish within 120s.")
    except Exception as e:
        return TestGateResult(passed=False, skipped=False, command=cmd,
                              output=f"TEST GATE ERROR: {e}")


# ── Per-file self-verification (runs after each agent merges) ────────────────

@dataclass
class SelfVerifyResult:
    passed: bool
    output: str
    is_own_fault: bool  # True → agent's merge introduced the failure

def _run_self_verify(code_dir: Path, eng_task: "EngTask") -> SelfVerifyResult:
    """Run lightweight per-file verification after an agent's merge.

    Checks:
      - Python: ``python -c "import <module>"`` + matching test file
      - JS/TS: ``node --check <file>``
      - Dockerfile / YAML / JSON: syntax validation
    Returns SelfVerifyResult; fault attribution is done by the caller.
    """
    fpath = code_dir / eng_task.file
    if not fpath.exists():
        return SelfVerifyResult(passed=True, output="(file does not exist — skip)", is_own_fault=False)

    checks: List[str] = []
    suffix = fpath.suffix.lower()

    if suffix == ".py":
        mod_path = eng_task.file.replace("/", ".").replace("\\", ".")
        if mod_path.endswith(".py"):
            mod_path = mod_path[:-3]
        checks.append(f"{sys.executable} -c \"import {mod_path}\"")
        _test_candidates = [
            code_dir / "tests" / f"test_{fpath.name}",
            code_dir / "tests" / f"{fpath.stem}_test.py",
            fpath.parent / f"test_{fpath.name}",
        ]
        for tc in _test_candidates:
            if tc.exists():
                checks.append(f"{sys.executable} -m pytest {str(tc)} -x -q --tb=short")
                break
    elif suffix in (".js", ".mjs", ".cjs"):
        checks.append(f"node --check {str(fpath)}")
    elif suffix in (".ts", ".tsx"):
        npx = "npx.cmd" if sys.platform == "win32" else "npx"
        checks.append(f"{npx} tsc --noEmit {str(fpath)} 2>&1 || true")
    elif suffix in (".json",):
        checks.append(f"{sys.executable} -c \"import json, pathlib; json.loads(pathlib.Path(r'{fpath}').read_text())\"")
    elif suffix in (".yml", ".yaml"):
        checks.append(f"{sys.executable} -c \"import yaml, pathlib; yaml.safe_load(pathlib.Path(r'{fpath}').read_text())\"")
    elif fpath.name == "Dockerfile":
        checks.append(f"{sys.executable} -c \"p=open(r'{fpath}').read(); assert 'FROM' in p, 'no FROM in Dockerfile'\"")

    if not checks:
        return SelfVerifyResult(passed=True, output="(no applicable checks)", is_own_fault=False)

    all_output: List[str] = []
    for cmd in checks:
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(code_dir),
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            combined = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
            all_output.append(f"$ {cmd}\n{combined}")
            if proc.returncode != 0:
                return SelfVerifyResult(
                    passed=False,
                    output="\n".join(all_output),
                    is_own_fault=False,  # caller will attribute
                )
        except subprocess.TimeoutExpired:
            all_output.append(f"$ {cmd}\nTIMEOUT (30s)")
            return SelfVerifyResult(passed=False, output="\n".join(all_output), is_own_fault=False)
        except Exception as e:
            all_output.append(f"$ {cmd}\nERROR: {e}")

    return SelfVerifyResult(passed=True, output="\n".join(all_output), is_own_fault=False)


def _run_self_verify_with_attribution(
    code_dir: Path, eng_task: "EngTask", pre_merge_result: SelfVerifyResult
) -> SelfVerifyResult:
    """Run verification after merge and compare with pre-merge to attribute fault."""
    post = _run_self_verify(code_dir, eng_task)
    if post.passed:
        return post
    if not pre_merge_result.passed:
        return SelfVerifyResult(passed=False, output=post.output, is_own_fault=False)
    return SelfVerifyResult(passed=False, output=post.output, is_own_fault=True)


# ── Git Worktree isolation for engineering agents ─────────────────────────────

import shutil as _shutil

# Serialises all git operations that touch the shared code_dir repo state
# (init, add, commit, worktree add/remove).  Individual agents can still write
# files concurrently; only the git commands themselves need to be serialised.
_git_repo_lock = threading.Lock()

_wt_manager_ctx: _cv.ContextVar[Optional["GitWorktreeManager"]] = _cv.ContextVar(
    "wt_manager", default=None,
)

def _get_worktree_manager() -> Optional["GitWorktreeManager"]:
    return _wt_manager_ctx.get()

def _set_worktree_manager(mgr: Optional["GitWorktreeManager"]) -> None:
    _wt_manager_ctx.set(mgr)

def _get_code_dir() -> Path:
    """Return the active code directory — agent's worktree if active, else shared."""
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
            cmd, cwd=str(cwd or self.code_dir),
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )

    def init_repo(self) -> None:
        """Initialize a git repo in code_dir if one doesn't exist, and create an initial commit."""
        if self._initialized:
            return
        with _git_repo_lock:
            if self._initialized:   # double-checked inside the lock
                return
            git_dir = self.code_dir / ".git"
            if not git_dir.exists():
                self.code_dir.mkdir(parents=True, exist_ok=True)
                self._git("init")
                self._git("checkout", "-b", "main")
                gitignore = self.code_dir / ".gitignore"
                if not gitignore.exists():
                    patterns = get_contracts().gitignore_patterns or []
                    content = "\n".join([".worktrees/"] + [p for p in patterns if p != ".worktrees/"]) + "\n"
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
                needed_lines = [".worktrees/"] + [p for p in patterns if p != ".worktrees/"]
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
                    raise RuntimeError(
                        f"git worktree add failed for {agent_id}: {result.stderr.strip()}"
                    )
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
            self._git("add", ".", cwd=wt_path)
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

    def merge_all(self) -> List[str]:
        """Merge all agent branches back into main. Returns list of conflict resolutions."""
        resolutions: List[str] = []
        with _git_repo_lock:
            # Always land on main before merging so we never accidentally merge
            # into a detached HEAD or a stale agent branch.
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
                        logger.warning(f"[worktree] merge of {agent_id} failed (non-conflict): {result.stderr.strip()}")
                else:
                    logger.info(f"[worktree] merged {agent_id} cleanly")
        if resolutions:
            report = "\n".join(resolutions)
            logger.info(f"[worktree] merge conflict resolutions:\n{report}")
        return resolutions

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
            resolved = llm_call(
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


def _generate_entry_point_via_llm(
    registry: InterfaceContractRegistry, code_dir: Path
) -> bool:
    """Use LLM to generate the entry point file that wires all modules together."""
    file_summaries = []
    for fname, fc in registry.file_map.items():
        if fname == registry.entry_point:
            continue
        fpath = code_dir / fname
        source_preview = ""
        if fpath.exists():
            try:
                source_preview = fpath.read_text(encoding="utf-8")[:500]
            except Exception:
                pass
        file_summaries.append(
            f"  {fname} (exports: {fc.exports}, imports_from: {fc.imports_from}):\n"
            f"    {fc.description}\n"
            f"    Preview: {source_preview[:200]}..."
        )

    prompt = (
        f"Generate the entry point file '{registry.entry_point}' that wires together all modules.\n\n"
        f"MODULES:\n" + "\n".join(file_summaries) + "\n\n"
        f"ENTRY IMPORTS NEEDED: {registry.entry_imports}\n"
        f"DEPENDENCIES: {registry.dependencies}\n\n"
        f"REQUIREMENTS:\n"
        f"  - Import and wire ALL modules listed above\n"
        f"  - The app must be runnable with: {registry.build_command or 'appropriate command'}\n"
        f"  - Output ONLY the file content, no markdown fences\n"
        f"  - Make it production-ready with error handling\n"
        "\nINTEGRATION RULES:\n"
        "  - The entry point will be AUTO-GENERATED — do NOT create it yourself\n"
        "  - Your file MUST export exactly the symbols listed in your contract's 'exports'\n"
        "  - Import from files listed in your contract's 'imports_from'\n"
        "  - Do NOT invent new file names — use the exact paths from the contract\n"
    )
    try:
        source = llm_call(prompt, label="generate_entry_point")
        if source and "```" in source:
            m = re.search(r"```\w*\n(.*?)```", source, re.DOTALL)
            if m:
                source = m.group(1)
        if source and source.strip():
            ep_path = code_dir / registry.entry_point
            ep_path.parent.mkdir(parents=True, exist_ok=True)
            ep_path.write_text(source.strip() + "\n", encoding="utf-8")
            return True
    except Exception as e:
        logger.warning(f"  LLM entry-point generation failed: {e}")
    return False


def _emit_build_scaffold_via_llm(
    registry: InterfaceContractRegistry, code_dir: Path
) -> bool:
    """Use LLM to generate build configuration files (package.json, requirements.txt, etc.)."""
    bf_path = code_dir / registry.build_file
    if bf_path.exists():
        # Skip only if it's real content — not a skeleton stub
        raw = bf_path.read_text(encoding="utf-8", errors="ignore").lstrip()
        if raw and not raw.startswith("#") and not raw.startswith("# AUTO-GENERATED"):
            return False
        # Fall through: file is a skeleton comment — overwrite with real content

    existing_files = []
    for p in code_dir.rglob("*"):
        if "node_modules" in p.parts or ".git" in p.parts:
            continue
        if p.is_file() and not p.name.startswith("."):
            existing_files.append(str(p.relative_to(code_dir)))

    prompt = (
        f"Generate the build configuration file '{registry.build_file}'.\n\n"
        f"PROJECT FILES: {existing_files[:50]}\n"
        f"DEPENDENCIES: {registry.dependencies}\n"
        f"BUILD COMMAND: {registry.build_command}\n\n"
        f"Output ONLY the file content, no markdown fences.\n"
    )
    is_json = registry.build_file.endswith(".json")
    for attempt in range(3):
        try:
            source = llm_call(prompt, label="generate_build_config")
            if source and "```" in source:
                m = re.search(r"```\w*\n(.*?)```", source, re.DOTALL)
                if m:
                    source = m.group(1)
            if not source or not source.strip():
                continue
            content = source.strip()
            # Validate JSON files before writing
            if is_json:
                # Robustly extract just the outermost {...} block — ignore trailing text
                _start = content.find('{')
                _end = content.rfind('}')
                if _start != -1 and _end != -1 and _end > _start:
                    content = content[_start:_end + 1]
                try:
                    json.loads(content)
                except json.JSONDecodeError as je:
                    logger.warning(f"  LLM build-config attempt {attempt+1}: invalid JSON — {je}")
                    prompt += f"\n\nPREVIOUS ATTEMPT WAS INVALID JSON: {je}\nOutput ONLY valid JSON, no comments, no markdown."
                    continue
            bf_path.parent.mkdir(parents=True, exist_ok=True)
            bf_path.write_text(content + "\n", encoding="utf-8")
            return True
        except Exception as e:
            logger.warning(f"  LLM build-config generation failed: {e}")
    return False






def _setup_project(code_dir: Path) -> None:
    """
    Manager-run project setup: generate build config and install dependencies
    once before any engineering agent starts. This ensures package.json,
    node_modules, etc. exist from the start so agents never race to create them.
    """
    registry = get_contracts()
    if not registry.build_file:
        return

    logger.info(f"[Setup] Manager setting up project ({registry.build_file})...")

    # Generate build config if missing or a skeleton stub
    bf_path = code_dir / registry.build_file
    is_stub = (
        bf_path.exists() and
        bf_path.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("#")
    )
    if not bf_path.exists() or is_stub:
        _emit_build_scaffold_via_llm(registry, code_dir)

    # Install dependencies if build config now exists
    bf_path = code_dir / registry.build_file  # re-check after potential generation
    if not bf_path.exists():
        logger.warning("[Setup] build config still missing after generation — skipping install")
        return

    install_cmd = registry.install_command
    if not install_cmd:
        return

    logger.info(f"[Setup] running '{install_cmd}'...")
    try:
        result = subprocess.run(
            install_cmd, shell=True, cwd=str(code_dir),
            capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            logger.info(f"[Setup] '{install_cmd}' succeeded")
        else:
            out = ((result.stdout or "") + (result.stderr or ""))[-1000:]
            logger.warning(f"[Setup] '{install_cmd}' failed:\n{out}")
    except subprocess.TimeoutExpired:
        logger.warning(f"[Setup] '{install_cmd}' timed out after 180s")
    except Exception as e:
        logger.warning(f"[Setup] '{install_cmd}' error: {e}")




@dataclass
class ManagerFixResult:
    passed: bool
    rounds_used: int
    final_output: str
    app_run_verified: bool = False


def _manager_fix_collect_errors(code_dir: Path, registry: "InterfaceContractRegistry") -> List[str]:
    """Run test gate + build; return a list of error strings (empty if all green)."""
    errors: List[str] = []
    gate = _run_test_gate(code_dir)
    if gate.skipped:
        logger.info("[ManagerFix] test gate skipped (no tests detected)")
    elif gate.passed:
        logger.info(f"[ManagerFix] test gate passed: {gate.command}")
    else:
        errors.append(f"TEST FAILURE ({gate.command}):\n{gate.output}")
    build_out = _run_build_command(registry)
    if build_out:
        errors.append(build_out)
    return errors


def _manager_saw_start_service(tool_results: List[str]) -> bool:
    return any(tr.startswith("[TOOL: start_service]") for tr in (tool_results or []))


def _manager_fix_loop(
    code_dir: Path,
    task_queue: "EngTaskQueue",
    rolling_ctxs: Dict[str, "RollingContext"],
    max_rounds: int = MANAGER_FIX_MAX_ROUNDS,
) -> ManagerFixResult:
    """Run tests/build repeatedly; manager must also invoke ``start_service()`` at least once.

    Success requires: (1) test gate + build green, and (2) at least one ``start_service`` tool
    call in this session (integration manager actually booted the app).
    """
    registry = get_contracts()
    _set_agent_ctx("eng_manager", _get_sprint_num())
    manager_ran_start_service = False
    last_error_block = ""
    build_cmd_hint = registry.build_command or ""

    for round_num in range(1, max_rounds + 1):
        logger.info(f"[ManagerFix] round {round_num}/{max_rounds} — running verification…")

        errors = _manager_fix_collect_errors(code_dir, registry)
        if errors:
            last_error_block = "\n\n".join(errors)[-4000:]

        tests_build_ok = not errors
        if tests_build_ok and manager_ran_start_service:
            logger.info(
                f"[ManagerFix] ALL GREEN + start_service verified after "
                f"{round_num - 1} manager round(s)"
            )
            return ManagerFixResult(
                passed=True,
                rounds_used=max(0, round_num - 1),
                final_output="All tests and build passed; manager invoked start_service at least once.",
                app_run_verified=True,
            )

        # Build file listing for the manager
        file_list: List[str] = []
        try:
            for p in sorted(code_dir.rglob("*")):
                if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts:
                    file_list.append(str(p.relative_to(code_dir)).replace("\\", "/"))
        except Exception:
            pass
        files_section = "\n".join(file_list[:200]) if file_list else "(unable to list files)"

        if errors:
            error_block = "\n\n".join(errors)[-4000:]
            logger.warning(f"[ManagerFix] round {round_num} errors:\n{error_block[:500]}")
            prompt = (
                f"You are the Engineering Manager. The full codebase has been assembled by "
                f"your team, but verification is failing.\n\n"
                f"ERRORS (round {round_num}/{max_rounds}):\n"
                f"```\n{error_block}\n```\n\n"
                f"PROJECT FILES:\n{files_section}\n\n"
                f"TASK QUEUE STATUS:\n{task_queue.get_status()}\n\n"
                f"YOUR JOB: Diagnose and fix the errors.\n"
                f"  1. Use read_file() to inspect the relevant files.\n"
                f"  2. Use write_code_file() to fix the code.\n"
                f"  3. Use run_shell() to re-run specific commands if needed.\n"
                f"  4. Focus on the FIRST error — fixing it often resolves cascading failures.\n"
                f"NON-NEGOTIABLE: Before integration is complete you MUST run the real application "
                f"at least once using start_service(), then http_request() against localhost, "
                f"then stop_service(). Do not skip this even if tests later pass.\n"
                f"Do NOT just describe what to do — actually make the changes with tools.\n"
            )
        else:
            logger.warning(
                f"[ManagerFix] round {round_num} — tests/build green but start_service not "
                f"invoked yet; forcing mandatory app boot"
            )
            prompt = (
                f"You are the Engineering Manager — MANDATORY APPLICATION BOOT "
                f"(round {round_num}/{max_rounds}).\n\n"
                f"Automated tests and the build command currently pass (or there is no failing gate).\n"
                f"You have NOT yet called start_service() in this manager session. "
                f"The integration phase is incomplete until you boot the app at least once.\n\n"
                f"Contract build_command hint: {build_cmd_hint!r}\n\n"
                f"REQUIRED (use tools, not prose only):\n"
                f"  1. list_files() / read_file() as needed to find how to run "
                f"(docker compose, npm start, uvicorn, python -m, etc.).\n"
                f"  2. start_service(name, command, port) — use a short name like 'app' or 'api'.\n"
                f"  3. http_request('GET', 'http://localhost:<port>/...') to confirm a response "
                f"(root, /health, /docs, or similar).\n"
                f"  4. stop_service(name) when done.\n\n"
                f"PROJECT FILES:\n{files_section}\n\n"
                f"TASK QUEUE STATUS:\n{task_queue.get_status()}\n"
            )

        output, tool_results, _ = _run_with_tools(
            prompt, "eng_manager", f"mgr_fix_r{round_num}", retry_count=0
        )
        if _manager_saw_start_service(tool_results):
            manager_ran_start_service = True
        logger.info(
            f"[ManagerFix] round {round_num} — manager used {len(tool_results)} tool calls, "
            f"output {len(output)}c, start_service_seen={manager_ran_start_service}"
        )

        try:
            wt = GitWorktreeManager(code_dir, ["eng_manager"])
            wt.create_worktrees()
            wt.commit_agent("eng_manager")
            with _git_repo_lock:
                wt.merge_all()
            wt.cleanup()
        except Exception as e:
            logger.warning(f"[ManagerFix] commit/merge after round {round_num} failed: {e}")

        try:
            get_rag().update()
        except Exception:
            pass

    # Exhausted rounds — final check
    errors = _manager_fix_collect_errors(code_dir, registry)
    tests_build_ok = not errors
    if errors:
        last_error_block = "\n\n".join(errors)[-4000:]
    if tests_build_ok and manager_ran_start_service:
        logger.info("[ManagerFix] green + start_service after final round")
        return ManagerFixResult(
            passed=True,
            rounds_used=max_rounds,
            final_output="Tests/build passed; manager invoked start_service.",
            app_run_verified=True,
        )
    if tests_build_ok and not manager_ran_start_service:
        msg = (
            f"Tests/build passed but the Engineering Manager never called start_service() "
            f"within {max_rounds} round(s). Integration requires booting the app at least once."
        )
        logger.warning(f"[ManagerFix] {msg}")
        return ManagerFixResult(
            passed=False,
            rounds_used=max_rounds,
            final_output=msg,
            app_run_verified=False,
        )
    logger.warning(f"[ManagerFix] FAILED after {max_rounds} rounds — returning last errors")
    return ManagerFixResult(
        passed=False,
        rounds_used=max_rounds,
        final_output=(
            f"Manager fix loop exhausted {max_rounds} rounds.\n"
            f"{last_error_block[:2000]}"
        ),
        app_run_verified=manager_ran_start_service,
    )


def run_engineering_team(
    task: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    sprint_num: int = 1,
) -> TeamResult:
    """
    Async task-completion engineering team.
    Agents self-claim tasks from a shared queue, work in isolated Git worktrees,
    merge on completion, and pull the next task. No fixed rounds.
    """
    n = len(ENG_WORKERS)
    logger.info(f"\n{'─'*55}\nTEAM: ENGINEERING ({n} devs, async mode)\n{'─'*55}")
    clear_sprint_files()   # reset file tracking for this sprint

    dev_assignments, pool = run_sprint_planning(task, health_states, rolling_ctxs)
    emit_skeleton(dev_assignments, sprint_num)

    code_dir = OUTPUT_DIR / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    _skeleton_wt = GitWorktreeManager(code_dir, [])
    _skeleton_wt.init_repo()
    logger.info("[Engineering] git repo initialized with skeleton commit")

    # Index skeleton stubs NOW so list_files() returns real results when agents start.
    # Without this, the RAG index is empty at t=0 and agents enter a discovery loop.
    get_rag().update()
    logger.info(f"[Engineering] RAG pre-indexed {len(get_rag().chunks)} skeleton chunks")

    _setup_project(code_dir)

    task_queue = EngTaskQueue(get_contracts(), dev_assignments, pool)
    built: Dict[str, WorkerOutput] = {}
    _tasks_completed_by: Dict[str, int] = {d: 0 for d in ENG_WORKERS}
    _merge_lock = threading.Lock()
    _built_lock = threading.Lock()  # guards built + _tasks_completed_by

    # ── build_feature: adapted for task-based work ────────────────────────

    def build_feature(dev_key: str, eng_task: EngTask, retry_count: int = 0) -> WorkerOutput:
        _set_agent_ctx(dev_key, sprint_num)
        _set_task_file(eng_task.file)
        dashboard_status = get_dashboard().get_status()
        task_num = _tasks_completed_by[dev_key] + 1
        logger.info(f"[{dev_key}] ▶ Task START — {eng_task.file}: {eng_task.description[:60]}")

        completed_files = task_queue.get_completed_files()
        peer_context = ""
        if completed_files:
            previews = []
            for cf in completed_files[:6]:
                fpath = code_dir / cf
                if fpath.exists():
                    try:
                        src = fpath.read_text(encoding="utf-8")[:300]
                        previews.append(f"  {cf}:\n    {src[:200]}...")
                    except Exception:
                        pass
            if previews:
                peer_context = "\nCOMPLETED FILES IN CODEBASE (already merged):\n" + "\n".join(previews) + "\n"

        messages_section = ""
        try:
            pending = get_dashboard().peek_messages(dev_key)
            if pending:
                messages_section = f"\nMESSAGES FROM TEAMMATES (read carefully):\n{pending}\n"
        except Exception:
            pass

        if AGILE_MODE:
            integration_rules = (
                "\nAGILE COLLABORATION RULES (Targeted Communication):\n"
                "  - NO TRIVIAL BROADCASTS: Do NOT broadcast small progress updates.\n"
                "  - TARGETED MESSAGES: If you need something from a specific teammate, use message_teammate().\n"
                "  - BREAKING BROADCASTS: ONLY use broadcast_message() for team-wide structural changes\n"
                "    (e.g. changing an API port, a shared data model, or a global config constant).\n"
                "  - Use search_codebase() to find teammates' work without asking them for status updates.\n"
                "  - Dashboard contents are already injected into your prompt — no need to poll.\n"
            )
        else:
            integration_rules = (
                "\nINTEGRATION RULES:\n"
                "  - The entry point will be AUTO-GENERATED — do NOT create it yourself\n"
                "  - Your file MUST export exactly the symbols listed in your contract's 'exports'\n"
                "  - Import from files listed in your contract's 'imports_from'\n"
                "  - Do NOT invent new file names — use the exact paths from the contract\n"
            )

        is_integration_specialist = (eng_task.file == "__integration__")
        build_cmd = get_contracts().build_command

        if is_integration_specialist:
            build_errors = ""
            if build_cmd:
                try:
                    logger.info(f"[{dev_key}] running pre-flight '{build_cmd}' (timeout=30s)...")
                    result = subprocess.run(
                        build_cmd, shell=True, cwd=str(code_dir),
                        capture_output=True, text=True, timeout=30,
                        encoding="utf-8", errors="replace",
                    )
                    if result.returncode != 0:
                        build_errors = f"\nBUILD ERRORS (from running '{build_cmd}'):\n{(result.stdout or '')[-2000:]}\n{(result.stderr or '')[-2000:]}\n"
                    logger.info(f"[{dev_key}] pre-flight done (rc={result.returncode})")
                except Exception as e:
                    build_errors = f"\nBUILD FAILED: {e}\n"
                    logger.info(f"[{dev_key}] pre-flight failed: {e}")

            task_instruction = (
                f"INTEGRATION TEST — all code merged.\n"
                f"{build_errors}"
                f"Run '{build_cmd or 'the build command'}' with run_shell. Fix any errors with write_code_file.\n"
                f"Use write_code_file (not write_config_file) for manifests like requirements.txt.\n"
            )
        else:
            _build_hint = (
                f"  3. Before completing, try running '{build_cmd}' using run_shell.\n"
                f"  4. If it fails because of something obvious, fix it. If it's a team-wide issue, broadcast it.\n"
            ) if build_cmd else (
                "  3. Verify your file is syntactically correct (e.g. validate_python if applicable).\n"
            )
            task_instruction = (
                f"TASK: Implement '{eng_task.file}'\n"
                f"Description: {eng_task.description}\n\n"
                f"STEPS:\n"
                f"  1. list_files() and read_file() to see existing code from teammates\n"
                f"  2. write_code_file('{eng_task.file}', <YOUR COMPLETE CODE>)\n"
                f"     — Make sure imports match what your teammates exported\n"
                f"     — Follow the interfaces/contracts exactly\n"
                f"{_build_hint}"
                f"\nIMPORTANT: After you write your file, the system will automatically\n"
                f"verify that it integrates correctly (syntax, imports, tests). If your\n"
                f"code breaks something, you will be asked to fix it. Write carefully.\n"
            )


        team_files = _read_team_files()
        team_files_section = (
            f"\n\n─── TEAM SPECIFICATIONS (read before writing any code) ───\n{team_files}\n"
            f"────────────────────────────────────────────────────────\n"
        ) if team_files else ""

        contract_section = ""
        contract_text = get_contracts().get_contract_for_dev(dev_key)
        if contract_text:
            contract_section = f"\n{contract_text}\n"

        goal_anchor = ""
        if _current_sprint_goal:
            goal_anchor = (
                f"╔══════════════════════════════════════════════════════╗\n"
                f"║  SPRINT GOAL (your north star — never lose sight of this)\n"
                f"║  {_current_sprint_goal[:200]}\n"
                f"╚══════════════════════════════════════════════════════╝\n\n"
            )

        dod_checklist = _get_dod(dev_key)

        queue_status = task_queue.get_status()

        prompt = (
            f"You are dev_{dev_key.split('_')[1]}. "
            f"Your task: write file '{eng_task.file}'.\n\n"
            f"{task_instruction}\n\n"
            f"PROJECT: {task[:300]}\n\n"
        )
        # Add contract if available (concise)
        if contract_section:
            prompt += f"YOUR CONTRACT:{contract_section}\n"
        # Add peer context (what's already built)
        if peer_context:
            prompt += f"{peer_context}\n"
        # Add messages from teammates
        if messages_section:
            prompt += f"{messages_section}\n"
        # Rolling context from previous tasks
        _rolling = rolling_ctxs[dev_key].get()
        if _rolling and len(_rolling.strip()) > 20:
            prompt += f"\nPREVIOUS WORK:\n{_rolling[:600]}\n"
        if retry_count > 0:
            # Inject existing file content so the model already has context
            # and doesn't need to call list_files / read_file (removing those
            # tools caused Gemini AFC to silently reject the unknown calls,
            # burning all 25 rounds with 0 Python invocations).
            _existing_content = ""
            _target_path = code_dir / eng_task.file
            if _target_path.exists():
                try:
                    _existing_content = _target_path.read_text(encoding="utf-8", errors="replace")[:2000]
                except Exception:
                    pass
            _file_context = (
                f"\nCURRENT FILE CONTENT ({eng_task.file}):\n```\n{_existing_content}\n```\n"
                if _existing_content
                else f"\n(File {eng_task.file} does not exist yet — create it from scratch.)\n"
            )
            prompt += (
                f"\n{'='*60}\n"
                f"RETRY {retry_count} — WRITE IS REQUIRED\n"
                f"{'='*60}\n"
                f"Your previous attempt did NOT call write_code_file.\n"
                f"All tools are still available — do NOT loop on list_files.\n"
                f"{_file_context}"
                f"ACTION REQUIRED: Call write_code_file('{eng_task.file}', <complete code>) NOW.\n"
                f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]\n"
            )
            logger.info(
                f"[{dev_key}] retry {retry_count} — full toolset kept, "
                f"injecting {'existing' if _existing_content else 'empty'} file content into prompt"
            )
        else:
            prompt += (
                f"\nREMINDER: You MUST call write_code_file('{eng_task.file}', <code>) "
                f"with complete working code. Prose-only = failure.\n"
                f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
            )
        logger.info(f"[{dev_key}] prompt built ({len(prompt)}c) — handing off to ReAct agent")
        output, tool_results, perplexity = _run_with_tools(
            prompt, dev_key, f"{dev_key}_t{task_num}", retry_count=retry_count
        )
        sims    = perplexity_to_similarities(perplexity)
        F       = health_states[dev_key].update(sims)
        anomaly = health_states[dev_key].is_anomaly()
        logger.info(
            f"[{dev_key}] health update — perplexity={perplexity:.2f}  F_health={F:.3f}  "
            f"anomaly={'YES ⚠' if anomaly else 'no'}  tools_used={len(tool_results)}"
        )
        if anomaly and task_num == 1:
            logger.warning(f"[{dev_key}] ANOMALY F={F:.3f} — invoking fixer agent")
            health_states[dev_key].reset()
            output  = _run_fixer(dev_key, eng_task.description, output, F)
            sims    = perplexity_to_similarities(5.0)
            F       = health_states[dev_key].update(sims)
            anomaly = health_states[dev_key].is_anomaly()
        elif anomaly:
            logger.warning(f"[{dev_key}] ANOMALY F={F:.3f} — resetting health state")
            health_states[dev_key].reset()
        m      = re.search(r"STANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)", output, re.IGNORECASE)
        stance = m.group(1).lower() if m else "pragmatic"
        logger.info(
            f"[{dev_key}] ✔ Task DONE — {eng_task.file}  stance={stance.upper()}  "
            f"output={len(output)}c  F={F:.3f}"
        )
        rolling_ctxs[dev_key].add(eng_task.description, output)
        return WorkerOutput(
            role=dev_key, title=f"Software Developer — {eng_task.description[:40]}",
            round=task_num, output=output, tool_results=tool_results,
            stance=stance, stance_probs=extract_stance_probs(output).tolist(),
            F_health=F, anomaly=anomaly,
        )

    # ── Agent worker loop ─────────────────────────────────────────────────

    def _agent_worker_loop(dev_key: str) -> None:
        """Long-running worker: pull task → worktree → build → merge → repeat.
        Outer loop retries if a TeammateIdle hook fails (up to TEAMMATE_IDLE_MAX_RETRIES)."""
        _idle_retries = 0
        while True:  # outer idle-hook retry loop
            while task_queue.has_work_available():
                with _built_lock:
                    _agent_task_count = _tasks_completed_by[dev_key]
                if _agent_task_count >= MAX_TASKS_PER_AGENT:
                    logger.info(f"[{dev_key}] hit MAX_TASKS_PER_AGENT={MAX_TASKS_PER_AGENT} — stopping")
                    break

                eng_task = task_queue.claim_next(dev_key)
                if eng_task is None:
                    if task_queue.all_done():
                        break
                    import time as _time
                    _time.sleep(_AGENT_POLL_INTERVAL)
                    continue

                # ── TaskCreated hook: pre-task validator ──────────────────
                if TASK_CREATED_HOOKS:
                    _task_rejected = False
                    _hook_outputs: List[str] = []
                    _task_env = {**os.environ, "ENG_TASK_DESCRIPTION": eng_task.description}
                    for _hook_cmd in TASK_CREATED_HOOKS:
                        try:
                            _hook_proc = subprocess.run(
                                _hook_cmd, shell=True, capture_output=True, text=True,
                                timeout=30, cwd=str(code_dir), env=_task_env,
                                input=eng_task.description,
                                encoding="utf-8", errors="replace",
                            )
                            _hook_out = ((_hook_proc.stdout or "") + (_hook_proc.stderr or ""))[-1000:]
                            _hook_outputs.append(f"[task-hook: {_hook_cmd}]\n{_hook_out}")
                            if _hook_proc.returncode != 0:
                                _task_rejected = True
                                break
                        except Exception as _hook_e:
                            _hook_outputs.append(f"[task-hook: {_hook_cmd}] ERROR: {_hook_e}")
                            _task_rejected = True
                            break
                    if _task_rejected:
                        _rejection_msg = "\n".join(_hook_outputs)
                        logger.warning(
                            f"[{dev_key}] TASK REJECTED by pre-task hook: {eng_task.id}\n"
                            f"{_rejection_msg[:300]}"
                        )
                        task_queue.fail(eng_task.id)
                        continue
                # ─────────────────────────────────────────────────────────

                # Pre-generate build config before integration task starts
                if eng_task.file == "__integration__":
                    registry = get_contracts()
                    if registry.build_file:
                        _emit_build_scaffold_via_llm(registry, code_dir)

                wt = GitWorktreeManager(code_dir, [dev_key])
                try:
                    wt.create_worktrees()
                    _set_worktree_manager(wt)

                    _retries_before = task_queue.get_retries(eng_task.id)
                    result = build_feature(dev_key, eng_task, retry_count=_retries_before)
                    with _built_lock:
                        built[dev_key] = result

                    # If agent still produced no write tool call, requeue and retry
                    # with a narrowed toolset (write-only) on the next attempt.
                    if eng_task.file != "__integration__":
                        _wrote = any(
                            ("write_code_file" in tr) or ("write_file_section" in tr)
                            for tr in (result.tool_results or [])
                        )
                        if not _wrote:
                            retries_used = _retries_before
                            logger.warning(
                                f"[{dev_key}] no write tool call for '{eng_task.file}' "
                                f"(retry {retries_used + 1}/{MAX_RETRIES_PER_TASK}) — "
                                f"will inject file content into next prompt"
                            )
                            rolling_ctxs[dev_key].add(
                                f"FAILED: no write_code_file call for '{eng_task.file}'",
                                f"Your previous attempt did NOT call write_code_file() for '{eng_task.file}'. "
                                f"The task is automatically failed until you do. "
                                f"REQUIRED: Call write_code_file('{eng_task.file}', <full file content>) "
                                f"as your FIRST tool call this attempt. "
                                f"Do NOT use run_shell with printf/echo/cat — those are invisible to the "
                                f"project tracking system and will count as zero writes. "
                                f"write_code_file() is the ONLY tool that saves a file to the project."
                            )
                            task_queue.fail(eng_task.id)
                            continue

                    # ── Pre-merge self-verify baseline (for fault attribution) ──
                    _pre_merge_verify = None
                    if (
                        SELF_VERIFY_ENABLED
                        and eng_task.file != "__integration__"
                    ):
                        _pre_merge_verify = _run_self_verify(code_dir, eng_task)
                        logger.debug(
                            f"[{dev_key}] pre-merge verify for '{eng_task.file}': "
                            f"passed={_pre_merge_verify.passed}"
                        )

                    committed = wt.commit_agent(dev_key)
                    with _merge_lock:
                        resolutions = wt.merge_all()
                        if resolutions:
                            logger.info(f"[{dev_key}] merge resolutions:\n" + "\n".join(resolutions))

                    # Worktree content is now in main — clear in-memory worktree RAG.
                    _wt_rag = get_worktree_rag(dev_key)
                    if _wt_rag is not None:
                        _wt_rag.clear()

                    # ── Empty-output guard: if agent wrote nothing, retry ──
                    if not committed and eng_task.file != "__integration__":
                        target = code_dir / eng_task.file
                        file_missing = not target.exists()
                        file_is_stub = (
                            target.exists() and
                            target.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("# AUTO-GENERATED SKELETON")
                        )
                        if file_missing or file_is_stub:
                            retries_used = task_queue.get_retries(eng_task.id)
                            if retries_used < MAX_RETRIES_PER_TASK:
                                logger.warning(
                                    f"[{dev_key}] agent wrote nothing for '{eng_task.file}' "
                                    f"(retry {retries_used + 1}/{MAX_RETRIES_PER_TASK})"
                                )
                                rolling_ctxs[dev_key].add(
                                    f"EMPTY OUTPUT — {eng_task.file}",
                                    f"You were assigned '{eng_task.file}' but wrote nothing. "
                                    f"Use write_code_file to actually write the file content."
                                )
                                task_queue.fail(eng_task.id)
                                continue
                            else:
                                logger.warning(
                                    f"[{dev_key}] agent wrote nothing for '{eng_task.file}' "
                                    f"but retries exhausted — accepting to avoid deadlock"
                                )

                    # ── Self-verify after merge (per-file) ─────────────────
                    if (
                        SELF_VERIFY_ENABLED
                        and eng_task.file != "__integration__"
                        and _pre_merge_verify is not None
                    ):
                        sv = _run_self_verify_with_attribution(
                            code_dir, eng_task, _pre_merge_verify
                        )
                        if not sv.passed:
                            if sv.is_own_fault:
                                retries_used = task_queue.get_retries(eng_task.id)
                                if retries_used < MAX_RETRIES_PER_TASK:
                                    logger.warning(
                                        f"[{dev_key}] SELF-VERIFY FAILED (own fault) for "
                                        f"'{eng_task.file}' — retry {retries_used + 1}/"
                                        f"{MAX_RETRIES_PER_TASK}\n{sv.output[:500]}"
                                    )
                                    rolling_ctxs[dev_key].add(
                                        f"SELF-VERIFY FAILED — {eng_task.file}",
                                        f"Your code broke verification after merge.\n"
                                        f"Error output:\n{sv.output}\n\n"
                                        f"Fix the errors in '{eng_task.file}' using write_code_file."
                                    )
                                    task_queue.fail(eng_task.id)
                                    continue
                                else:
                                    logger.warning(
                                        f"[{dev_key}] SELF-VERIFY FAILED (own fault) but "
                                        f"retries exhausted — accepting '{eng_task.id}'"
                                    )
                            else:
                                logger.info(
                                    f"[{dev_key}] SELF-VERIFY FAILED (pre-existing) for "
                                    f"'{eng_task.file}' — completing with warning"
                                )

                    # ── Sync config/ → code/ ──────────────────────────────
                    if eng_task.file == "__integration__":
                        config_dir = OUTPUT_DIR / "config"
                        if config_dir.exists():
                            for cf in config_dir.iterdir():
                                if cf.is_file():
                                    dest = code_dir / cf.name
                                    dest_is_stub = dest.exists() and dest.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("#")
                                    if not dest.exists() or dest_is_stub:
                                        _shutil.copy2(str(cf), str(dest))
                                        logger.info(f"[{dev_key}] synced config/{cf.name} → code/{cf.name}")

                    # ── Pre-gate: install deps if needed ──────────────────
                    if eng_task.file == "__integration__":
                        _install_cmd = get_contracts().install_command
                        _build_file_path = code_dir / (get_contracts().build_file or "")
                        if _install_cmd and _build_file_path.exists():
                            logger.info(f"[{dev_key}] running '{_install_cmd}' before test gate...")
                            try:
                                subprocess.run(
                                    _install_cmd, shell=True, cwd=str(code_dir),
                                    capture_output=True, text=True, timeout=180,
                                    encoding="utf-8", errors="replace",
                                )
                            except Exception as e:
                                logger.warning(f"[{dev_key}] '{_install_cmd}' failed: {e}")

                    # ── Complete the task ──────────────────────────────────
                    task_queue.complete(eng_task.id)
                    with _built_lock:
                        _tasks_completed_by[dev_key] += 1
                    # ─────────────────────────────────────────────────────

                    try:
                        get_rag().update()
                    except Exception as e:
                        logger.warning(f"[{dev_key}] incremental RAG update failed: {e}")

                except Exception as exc:
                    # Detect interpreter shutdown — don't requeue, just abort cleanly.
                    _is_shutdown = (
                        isinstance(exc, RuntimeError)
                        and "interpreter shutdown" in str(exc)
                    ) or isinstance(exc, (KeyboardInterrupt, SystemExit))
                    if _is_shutdown:
                        logger.warning(f"[{dev_key}] interpreter shutting down — aborting task loop")
                        return
                    logger.error(f"[{dev_key}] task {eng_task.id} crashed: {exc}", exc_info=True)
                    task_queue.fail(eng_task.id)
                    with _built_lock:
                        built[dev_key] = WorkerOutput(
                            role=dev_key, title=f"Software Developer (error)",
                            round=_tasks_completed_by[dev_key] + 1,
                            output=f"[task crashed: {exc}]",
                            tool_results=[], stance="pragmatic",
                            stance_probs=[0.1, 0.1, 0.1, 0.7],
                            F_health=9.9, anomaly=True,
                        )
                finally:
                    wt.cleanup()
                    _set_worktree_manager(None)

                ActiveInferenceState.interfere_all(
                    [health_states[d] for d in ENG_WORKERS], alpha=INTERFERENCE_ALPHA
                )

            # ── TeammateIdle hook with retry loop ─────────────────────────
            if not TEAMMATE_IDLE_HOOKS or _idle_retries >= TEAMMATE_IDLE_MAX_RETRIES:
                break  # no hooks configured, or retries exhausted — agent done
            _idle_outputs: List[str] = []
            _idle_all_passed = True
            for _idle_cmd in TEAMMATE_IDLE_HOOKS:
                try:
                    _idle_proc = subprocess.run(
                        _idle_cmd, shell=True, capture_output=True, text=True,
                        timeout=60, cwd=str(code_dir),
                        encoding="utf-8", errors="replace",
                    )
                    _idle_out = ((_idle_proc.stdout or "") + (_idle_proc.stderr or ""))[-2000:]
                    _idle_outputs.append(f"[idle-hook: {_idle_cmd}]\n{_idle_out}")
                    if _idle_proc.returncode != 0:
                        _idle_all_passed = False
                        break
                except Exception as _idle_e:
                    _idle_outputs.append(f"[idle-hook: {_idle_cmd}] ERROR: {_idle_e}")
                    _idle_all_passed = False
                    break
            _idle_combined = "\n".join(_idle_outputs)
            if _idle_all_passed:
                logger.info(f"[{dev_key}] TEAMMATE IDLE HOOK passed — agent done")
                break  # exit outer loop cleanly
            _idle_retries += 1
            logger.warning(
                f"[{dev_key}] TEAMMATE IDLE HOOK FAILED "
                f"(retry {_idle_retries}/{TEAMMATE_IDLE_MAX_RETRIES}) — re-activating agent\n"
                f"{_idle_combined[:300]}"
            )
            rolling_ctxs[dev_key].add(
                f"TEAMMATE IDLE HOOK FAILED (attempt {_idle_retries})", _idle_combined
            )
            # continues outer while True → agent re-enters task loop
            # ─────────────────────────────────────────────────────────────

    # ── Manager monitor ───────────────────────────────────────────────────

    def _manager_monitor() -> None:
        """Periodic progress check — logs status and intervenes if swarm health is elevated."""
        import time as _time
        check_interval = 15
        _phase_1_synced = False
        while task_queue.has_work_available():
            _time.sleep(check_interval)
            
            # ── Sync Step (Between Phase 1 and Phase 2) ──────────────────
            phase_1_done = all(
                t.status in ("completed", "failed")
                for t in task_queue.tasks.values() if t.phase == PHASE_IMPLEMENTATION
            )
            if phase_1_done and not _phase_1_synced:
                logger.info("\n[Manager Monitor] PHASE 1 COMPLETE — Synchronizing codebase for Phase 2 Integration...")
                # Always unblock Phase 2 tasks — even if RAG fails
                try:
                    with task_queue._lock:
                        task_queue._unblock_dependents()
                    _phase_1_synced = True
                    logger.info("[Manager Monitor] PHASE 2 (Integration) RELEASED.\n")
                except Exception as e:
                    logger.error(f"[Manager Monitor] Failed to unblock Phase 2 tasks: {e}")
                    _phase_1_synced = True  # don't retry — avoid infinite loop
                # Re-index the RAG separately so integrators can 'see' all Phase 1 code
                try:
                    get_rag().update()
                    logger.info("[Manager Monitor] codebase indexed for Phase 2.\n")
                except Exception as e:
                    logger.warning(f"[Manager Monitor] RAG sync failed (non-fatal): {e}")

            if task_queue.all_done():
                break

            H_swarm = sum(health_states[d].free_energy() for d in ENG_WORKERS)
            stable_threshold = 1.5 * n
            status = task_queue.get_status()
            logger.info(
                f"\n[Manager Monitor] H_swarm={H_swarm:.3f}  "
                f"({'stable' if H_swarm < stable_threshold else 'ELEVATED ⚠'})\n{status}"
            )

            if H_swarm > stable_threshold * 1.5:
                failed_tasks = [t for t in task_queue.tasks.values() if t.status == "failed"]
                if failed_tasks:
                    logger.warning(
                        f"[Manager Monitor] swarm health critical — "
                        f"{len(failed_tasks)} failed tasks, sending guidance"
                    )
                    for ft in failed_tasks:
                        if ft.assigned_to:
                            if AGILE_MODE:
                                msg = (
                                    f"Task '{ft.file}' failed. In AGILE MODE, you must negotiate interfaces. "
                                    f"Have you broadcasted your changes? Did you read your teammates' files? "
                                    f"Communicate more and retry."
                                )
                            else:
                                msg = (
                                    f"Task '{ft.file}' failed. Check imports and dependencies. "
                                    f"Read the architecture spec before retrying."
                                )
                            get_dashboard().send_message("eng_manager", ft.assigned_to, msg, sprint_num)

            # ── Check token budget kill-switch ───────────────────────────
            with _token_lock:
                current_tokens_used = _tokens_in + _tokens_out
            if current_tokens_used > TOKEN_BUDGET:
                logger.critical(f"[Manager Monitor] KILL SWITCH TRIPPED: {current_tokens_used:,} tokens > {TOKEN_BUDGET:,} budget")
                task_queue.cancel_all()
                break

            # ── Process pending amendments ───────────────────────────────
            amendment_broadcasts = _registry_process_amendments(sprint_num)
            for msg in amendment_broadcasts:
                get_dashboard().broadcast("eng_manager", msg, sprint_num, ENG_WORKERS)

    # ── Launch all agents + monitor ───────────────────────────────────────

    import time as _eng_time
    start_time = _eng_time.time()

    with ThreadPoolExecutor(max_workers=n + 1) as ex:
        agent_futures = {
            ex.submit(_agent_worker_loop, dev): dev for dev in ENG_WORKERS
        }
        monitor_future = ex.submit(_manager_monitor)

        while not task_queue.all_done():
            elapsed = _eng_time.time() - start_time
            if elapsed > MAX_WALL_CLOCK:
                logger.warning(
                    f"[Engineering] hit MAX_WALL_CLOCK={MAX_WALL_CLOCK}s — "
                    f"forcing completion after {elapsed:.0f}s"
                )
                task_queue.force_fail_remaining()
                break
            all_agents_exited = all(f.done() for f in agent_futures)
            if all_agents_exited and not task_queue.all_done():
                logger.warning("[Engineering] all agents exited but tasks remain — forcing completion")
                task_queue.force_fail_remaining()
                break
            _eng_time.sleep(3)

        try:
            for fut in as_completed(list(agent_futures.keys()), timeout=60):
                dev = agent_futures.get(fut, "unknown")
                try:
                    fut.result()
                except Exception as exc:
                    logger.error(f"[{dev}] worker loop error: {exc}", exc_info=True)
        except TimeoutError:
            logger.warning("[Engineering] timeout waiting for agent threads to finish")

    elapsed = _eng_time.time() - start_time
    logger.info(f"\n[Engineering] async phase completed in {elapsed:.1f}s")
    logger.info(f"[Engineering] final queue status:\n{task_queue.get_status()}")

    # ── Final enforcement + build ─────────────────────────────────────────
    final_enforce = enforce_integration()
    if final_enforce:
        logger.info(f"\n[FINAL ENFORCEMENT]\n{final_enforce}")

    # ── Manager fix-until-green loop ──────────────────────────────────────
    fix_result = _manager_fix_loop(code_dir, task_queue, rolling_ctxs)
    if fix_result.passed:
        logger.info(
            f"[Engineering] Manager fix loop PASSED in {fix_result.rounds_used} round(s) "
            f"(app_run_verified={fix_result.app_run_verified})"
        )
    else:
        logger.warning(
            f"[Engineering] Manager fix loop FAILED after {fix_result.rounds_used} rounds\n"
            f"{fix_result.final_output[:500]}"
        )

    # ── Health + consensus ────────────────────────────────────────────────
    ActiveInferenceState.interfere_all(
        [health_states[d] for d in ENG_WORKERS], alpha=INTERFERENCE_ALPHA
    )
    H_swarm     = sum(health_states[d].free_energy() for d in ENG_WORKERS)
    mean_stance = np.mean([
        np.array(built[d].stance_probs) for d in ENG_WORKERS if d in built
    ] or [np.array([0.25, 0.25, 0.25, 0.25])], axis=0)
    consensus   = STANCES[int(mean_stance.argmax())]

    # ── Dev summary table ─────────────────────────────────────────────────
    logger.info(f"\n  ── Final dev summary ──────────────────────────")
    logger.info(f"  {'Dev':<10} {'Tasks':>6} {'F_health':>10}  {'Anomaly':>8}  {'Stance':<12}")
    logger.info(f"  {'─'*56}")
    for _dev in ENG_WORKERS:
        if _dev in built:
            _w = built[_dev]
            logger.info(
                f"  {_dev:<10} {_tasks_completed_by[_dev]:>6} {_w.F_health:>10.3f}  "
                f"{'⚠ YES' if _w.anomaly else 'no':>8}  {_w.stance.upper():<12}"
            )
        else:
            logger.info(f"  {_dev:<10} {_tasks_completed_by[_dev]:>6}      —         —  —")

    # ── Final manager synthesis ───────────────────────────────────────────
    feature_summaries = "\n\n".join(
        f"=== Dev {dev.split('_')[1]} — {dev_assignments[dev]} "
        f"(tasks: {_tasks_completed_by[dev]}) ===\n{built[dev].output[:700]}"
        for dev in ENG_WORKERS if dev in built
    )
    _fix_status = (
        f"Manager fix loop: PASSED in {fix_result.rounds_used} round(s); "
        f"app boot via start_service verified={fix_result.app_run_verified}"
        if fix_result.passed
        else (
            f"Manager fix loop: FAILED after {fix_result.rounds_used} rounds; "
            f"app_run_verified={fix_result.app_run_verified}\n"
            f"{fix_result.final_output[:300]}"
        )
    )
    synthesis = llm_call(
        f"You are the {ROLES['eng_manager']['title']}.\n\n"
        f"Your team completed tasks asynchronously ({elapsed:.0f}s elapsed).\n\n"
        f"TASK QUEUE FINAL STATUS:\n{task_queue.get_status()}\n\n"
        f"MANAGER FIX LOOP:\n{_fix_status}\n\n"
        f"FINAL OUTPUTS:\n{feature_summaries}\n\n"
        f"H_swarm={H_swarm:.3f}\n\n"
        f"Synthesize into a single coherent implementation guide:\n"
        f"1. How the features connect and integrate\n"
        f"2. Shared dependencies and interfaces\n"
        f"3. Any remaining gaps or failed tasks\n"
        f"4. Final runnable project structure and start command",
        label="eng_manager_synthesis",
        system=_manager_system("eng_manager"),
    )
    rolling_ctxs["eng_manager"].add(task, synthesis)

    return TeamResult(
        team="Engineering",
        manager_synthesis=synthesis,
        worker_outputs=[built[d] for d in ENG_WORKERS if d in built],
        H_swarm=H_swarm,
        consensus_stance=consensus,
        confidence=max(0.0, 1.0 - H_swarm / (1.5 * n)),
    )


# ── Main orchestrator ─────────────────────────────────────────────────────────

TEAM_RUNNERS = {
    "Architecture": lambda task, ctxs, hs, sn=1: run_team(
        "Architecture", "arch_manager",
        ["system_designer", "api_designer", "db_designer"],
        task, ctxs, hs, sn,
    ),
    "Design": lambda task, ctxs, hs, sn=1: run_team(
        "Design", "design_manager",
        ["ux_researcher", "ui_designer", "visual_designer"],
        task, ctxs, hs, sn,
    ),
    "Engineering": lambda task, ctxs, hs, sn=1: run_engineering_team(task, ctxs, hs, sn),
    "QA": lambda task, ctxs, hs, sn=1: run_team(
        "QA", "qa_manager",
        ["unit_tester", "integration_tester", "security_auditor"],
        task, ctxs, hs, sn,
    ),
}


def run_sprint_kickoff(
    brief: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> str:
    """
    CEO + all managers collaboratively define the first sprint goal.
    No CEO monologue — this is a real discussion.
    Returns the agreed Sprint 1 goal as a task string.
    """
    logger.info(f"\n{'═'*55}\nSPRINT KICKOFF: CEO + managers\n{'═'*55}")
    team_names = list(MANAGER_ROLES.keys())

    # CEO opens with vision — not a plan, just the brief and questions
    ceo_open = llm_call(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Open the Sprint 1 kickoff meeting. Share your vision for the product and "
        f"ask each manager: what is the single most critical thing your team can "
        f"deliver in Sprint 1 that would give us a working, demonstrable foundation? "
        f"Do NOT dictate the sprint goal — ask for their input.",
        label="ceo_kickoff_open",
        system=_SYSTEM_CEO,
    )
    logger.info(f"CEO opens kickoff: {ceo_open[:100]}...")

    # Round 1: each manager proposes what their team should build in Sprint 1
    def mgr_kickoff_r1(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        out = llm_call(
            f"CEO's opening:\n{ceo_open}\n\n"
            f"PROJECT BRIEF:\n{brief}\n\n"
            f"You lead the {team_name} team. What should your team focus on in Sprint 1? "
            f"Be specific: name the concrete deliverables, the acceptance criteria, "
            f"and any dependencies you need from other teams before you can start.",
            label=f"{role_key}_kickoff_r1",
            system=_manager_system(role_key),
        )
        return team_name, out

    r1: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_kickoff_r1, team_names):
            r1[name] = out

    ActiveInferenceState.interfere_all(
        [health_states[MANAGER_ROLES[t]] for t in team_names], alpha=INTERFERENCE_ALPHA
    )

    # Round 2: managers see each other's proposals, negotiate and align
    all_r1 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']}:\n{r1[t]}" for t in team_names)

    def mgr_kickoff_r2(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        out = llm_call(
            f"All managers' Sprint 1 proposals:\n{all_r1}\n\n"
            f"Having heard everyone: do you see any conflicts or gaps between proposals? "
            f"Refine your team's Sprint 1 scope to integrate with what the other managers proposed. "
            f"Be concrete about integration points.",
            label=f"{role_key}_kickoff_r2",
            system=_manager_system(role_key),
        )
        return team_name, out

    r2: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_kickoff_r2, team_names):
            r2[name] = out

    # CEO synthesises into a concrete Sprint 1 goal
    all_r2 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']} (refined):\n{r2[t]}" for t in team_names)
    sprint_goal = llm_call(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Manager proposals (round 1):\n{all_r1}\n\n"
        f"Manager refinements (round 2):\n{all_r2}\n\n"
        f"Synthesise a concrete Sprint 1 goal that reflects the team's collective judgment. "
        f"Include: what will be built, acceptance criteria for each team, "
        f"integration contracts between teams, and what 'done' looks like at the end of the sprint. "
        f"This is the authoritative sprint goal all teams will execute against.",
        label="ceo_kickoff_goal",
        system=_SYSTEM_CEO,
    )

    for t in team_names:
        rolling_ctxs[MANAGER_ROLES[t]].add("sprint kickoff", r2[t])
    rolling_ctxs["ceo"].add("sprint kickoff", sprint_goal)

    # Save conversation log
    turns = [{"speaker": "CEO — Kickoff Opening", "text": ceo_open}]
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R1)", "text": r1[t]})
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (R2)", "text": r2[t]})
    turns.append({"speaker": "CEO — Sprint 1 Goal", "text": sprint_goal})
    _save_conversation("Sprint Kickoff", turns)

    logger.info(f"Sprint 1 goal agreed: {sprint_goal[:120]}...")
    return sprint_goal


def run_sprint_retrospective(
    brief: str,
    sprint_num: int,
    sprint_result: ProjectResult,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
) -> Tuple[str, bool]:
    """
    After a sprint: CEO + all managers review what was built, assess quality,
    and either decide to ship or define the next sprint goal collaboratively.

    Returns (next_sprint_goal_or_empty, should_ship).
    """
    logger.info(f"\n{'═'*55}\nSPRINT {sprint_num} RETROSPECTIVE: CEO + managers\n{'═'*55}")
    team_names = list(MANAGER_ROLES.keys())

    # Build sprint summary for context
    completed = [r for r in [
        sprint_result.architecture, sprint_result.design,
        sprint_result.engineering,  sprint_result.qa,
    ] if r is not None]
    sprint_summary = "\n\n".join(
        f"{t.team} (confidence={t.confidence:.0%}, H={t.H_swarm:.3f}):\n"
        f"{t.manager_synthesis[:400]}"
        for t in completed
    )
    qa_result = sprint_result.qa
    qa_summary = (
        f"QA confidence: {qa_result.confidence:.0%}, H={qa_result.H_swarm:.3f}\n"
        f"{qa_result.manager_synthesis[:300]}"
        if qa_result else "QA did not run this sprint."
    )

    # CEO opens retro
    ceo_retro_open = llm_call(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Sprint {sprint_num} has just completed. Here is what was built:\n{sprint_summary}\n\n"
        f"QA Report:\n{qa_summary}\n\n"
        f"Open the sprint retrospective. Ask each manager: "
        f"(1) what did your team deliver vs. what was planned, "
        f"(2) what quality issues or gaps remain, "
        f"(3) what is your recommendation for the next sprint?",
        label=f"ceo_retro_{sprint_num}_open",
        system=_SYSTEM_CEO,
    )
    logger.info(f"CEO opens retro: {ceo_retro_open[:100]}...")

    # Round 1: each manager gives their retrospective assessment
    def mgr_retro_r1(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        team_result = getattr(sprint_result, team_name.lower(), None)
        team_output = (
            f"Your team's output this sprint:\n{team_result.manager_synthesis[:400]}\n"
            f"Confidence: {team_result.confidence:.0%}, H_swarm: {team_result.H_swarm:.3f}"
            if team_result else "Your team did not run this sprint."
        )
        out = llm_call(
            f"CEO's retrospective opening:\n{ceo_retro_open}\n\n"
            f"{team_output}\n\n"
            f"Full sprint summary:\n{sprint_summary}\n\n"
            f"Give your honest retrospective: what was delivered, what was missed, "
            f"what technical debt was incurred, and what your team must tackle next sprint. "
            f"Be specific — name actual files, functions, or features.",
            label=f"{role_key}_retro_{sprint_num}_r1",
            system=_manager_system(role_key),
        )
        return team_name, out

    r1: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_retro_r1, team_names):
            r1[name] = out

    ActiveInferenceState.interfere_all(
        [health_states[MANAGER_ROLES[t]] for t in team_names], alpha=INTERFERENCE_ALPHA
    )

    # Round 2: managers propose next sprint scope after hearing each other
    all_r1 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']}:\n{r1[t]}" for t in team_names)

    def mgr_retro_r2(team_name: str) -> Tuple[str, str]:
        role_key = MANAGER_ROLES[team_name]
        out = llm_call(
            f"All managers' retrospective assessments:\n{all_r1}\n\n"
            f"Based on what every team reported: propose what YOUR team should build "
            f"in Sprint {sprint_num + 1}. Prioritise what is most critical for quality "
            f"and completeness. Be specific about deliverables and acceptance criteria.",
            label=f"{role_key}_retro_{sprint_num}_r2",
            system=_manager_system(role_key),
        )
        return team_name, out

    r2: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for name, out in ex.map(mgr_retro_r2, team_names):
            r2[name] = out

    # CEO decides: ship or define next sprint
    all_r2 = "\n\n".join(f"{ROLES[MANAGER_ROLES[t]]['title']} (Sprint {sprint_num+1} proposal):\n{r2[t]}" for t in team_names)
    ceo_decision = llm_call(
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Sprint {sprint_num} summary:\n{sprint_summary}\n\n"
        f"Manager retrospectives:\n{all_r1}\n\n"
        f"Manager Sprint {sprint_num + 1} proposals:\n{all_r2}\n\n"
        f"Overall confidence: {sprint_result.overall_confidence:.0%} | "
        f"H_swarm: {sprint_result.overall_H_swarm:.3f} | "
        f"QA: {qa_summary[:150]}\n\n"
        f"Make the call: is this product ready to ship, or does it need another sprint?\n\n"
        f"If SHIPPING: output exactly 'DECISION: SHIP' followed by your go/no-go rationale.\n"
        f"If CONTINUING: output exactly 'DECISION: SPRINT' followed by the Sprint {sprint_num + 1} "
        f"goal — concrete deliverables, acceptance criteria per team, and integration contracts.",
        label=f"ceo_retro_{sprint_num}_decision",
        system=_SYSTEM_CEO,
    )

    for t in team_names:
        rolling_ctxs[MANAGER_ROLES[t]].add(f"sprint {sprint_num} retro", r2[t])
    rolling_ctxs["ceo"].add(f"sprint {sprint_num} retro", ceo_decision)

    # Save conversation log
    turns = [{"speaker": f"CEO — Sprint {sprint_num} Retrospective Opening", "text": ceo_retro_open}]
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (Retro R1)", "text": r1[t]})
    for t in team_names:
        turns.append({"speaker": f"{ROLES[MANAGER_ROLES[t]]['title']} (Next Sprint Proposal)", "text": r2[t]})
    turns.append({"speaker": f"CEO — Decision", "text": ceo_decision})
    _save_conversation(f"Sprint {sprint_num} Retrospective", turns, sprint_num=sprint_num)

    should_ship = bool(re.search(r"DECISION:\s*SHIP", ceo_decision, re.IGNORECASE))
    logger.info(f"CEO decision: {'SHIP ✓' if should_ship else f'CONTINUE → Sprint {sprint_num+1}'}")
    logger.info(f"  {ceo_decision[:150]}...")

    if should_ship:
        return ceo_decision, True

    # Extract the next sprint goal from the decision text
    m = re.search(r"DECISION:\s*SPRINT\s*(.+)", ceo_decision, re.DOTALL | re.IGNORECASE)
    next_goal = m.group(1).strip() if m else ceo_decision
    return (
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"SPRINT {sprint_num + 1} GOAL (agreed in retrospective):\n{next_goal}\n\n"
        f"COMPLETED IN PREVIOUS SPRINTS:\n{sprint_summary}",
        False,
    )


def _update_rag_and_manifest(sprint_num: int):
    """Re-index all output files into the RAG, then write PROJECT_MANIFEST.md."""
    rag = get_rag()
    rag.update()
    manifest_text = (
        f"# Project Manifest — updated after Sprint {sprint_num}\n\n"
        f"This file lists every source file in the codebase. "
        f"**Read this before writing any new file** to avoid duplicates.\n\n"
        f"## Files\n\n"
        f"{rag.manifest()}\n\n"
        f"## How to use codebase search\n\n"
        f"Call `search_codebase(query)` with a natural language description of what you need "
        f"(e.g. 'authentication token validation', 'WebSocket connection handler', "
        f"'Kanban task model'). It returns the most relevant existing code chunks.\n\n"
        f"Call `list_files()` to see all files.\n\n"
        f"Call `read_file(filename)` to read a specific file before modifying or importing it.\n"
    )
    manifest_path = OUTPUT_DIR / "PROJECT_MANIFEST.md"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    logger.info(f"[RAG] PROJECT_MANIFEST.md updated ({len(rag.chunks)} chunks indexed)")

    # Mark completed domains and write dashboard snapshot
    dash = get_dashboard()
    dash.release_sprint(sprint_num)
    dash_path = OUTPUT_DIR / "WORK_DASHBOARD.md"
    dash_path.write_text(
        f"# Work Dashboard — after Sprint {sprint_num}\n\n"
        + dash.get_status(),
        encoding="utf-8",
    )
    logger.info(f"[Dashboard] WORK_DASHBOARD.md written")


def _run_sprint(
    sprint_brief: str,
    sprint_num: int,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    prev_sprint_summary: str,
) -> ProjectResult:
    """Run a single sprint through the full company pipeline."""
    global _current_sprint_goal
    _current_sprint_goal = sprint_brief   # pin clean goal before context accumulates
    sprint_task = sprint_brief
    if prev_sprint_summary:
        sprint_task += (
            f"\n\nCOMPLETED IN PREVIOUS SPRINTS:\n{prev_sprint_summary}\n\n"
            f"Build on top of the existing work. Do not reimplement what was already done. "
            f"Extend, integrate, and improve."
        )

    plan = run_executive_meeting(sprint_task, rolling_ctxs, health_states)

    results: Dict[str, Optional[TeamResult]] = {
        "Architecture": None, "Design": None, "Engineering": None, "QA": None
    }

    def context_from_results(team_name: str) -> str:
        parts = []
        for other, r in results.items():
            if r is not None and other != team_name:
                parts.append(f"{other} output:\n{r.manager_synthesis[:350]}")
        return "\n\n".join(parts)

    for phase_idx, phase_teams in enumerate(plan.phases, 1):
        valid_teams = [t for t in phase_teams if t in TEAM_RUNNERS]
        if not valid_teams:
            continue
        logger.info(f"\n{'═'*55}\nSPRINT {sprint_num} — PHASE {phase_idx}: {' + '.join(valid_teams)}\n{'═'*55}")

        if len(valid_teams) == 1:
            team = valid_teams[0]
            ctx  = context_from_results(team)
            task = sprint_task if not ctx else f"{sprint_task}\n\nContext from completed teams:\n{ctx}"
            results[team] = TEAM_RUNNERS[team](task, rolling_ctxs, health_states, sprint_num)
        else:
            def _run_team(team_name: str) -> Tuple[str, TeamResult]:
                ctx  = context_from_results(team_name)
                task = sprint_task if not ctx else f"{sprint_task}\n\nContext from completed teams:\n{ctx}"
                return team_name, TEAM_RUNNERS[team_name](task, rolling_ctxs, health_states, sprint_num)

            with ThreadPoolExecutor(max_workers=len(valid_teams)) as ex:
                for team_name, result in ex.map(_run_team, valid_teams):
                    results[team_name] = result

    # ── Update RAG index after all teams have written files ───────────────
    _update_rag_and_manifest(sprint_num)

    ceo_summary = run_ceo_summary(sprint_task, results, plan, rolling_ctxs["ceo"])
    completed   = [r for r in results.values() if r is not None]

    return ProjectResult(
        brief=sprint_brief,
        execution_plan=plan,
        architecture=results.get("Architecture"),
        design=results.get("Design"),
        engineering=results.get("Engineering"),
        qa=results.get("QA"),
        ceo_summary=ceo_summary,
        overall_H_swarm=sum(t.H_swarm for t in completed),
        overall_confidence=sum(t.confidence for t in completed) / max(len(completed), 1),
        duration_s=0.0,  # filled in by run_company
    )


def run_company(brief: str, max_sprints: int = MAX_SPRINTS) -> List[ProjectResult]:
    """
    Run the full company pipeline as collaborative Scrum sprints.

    Sprint goals are NOT planned upfront.
      - Sprint 1 goal is defined collaboratively in a kickoff (CEO + all managers)
      - After each sprint a retrospective (CEO + all managers) reviews quality and
        either declares the product ready to ship OR defines the next sprint goal
      - Sprints continue until the CEO decides to ship — no artificial limit

    Returns a list of ProjectResult, one per sprint.
    """
    start = time.time()
    for sub in ["code", "tests", "design", "config"]:
        (OUTPUT_DIR / sub).mkdir(parents=True, exist_ok=True)

    all_roles     = list(ROLES.keys())
    health_states = {r: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR) for r in all_roles}
    rolling_ctxs  = {r: RollingContext() for r in all_roles}

    # ── Sprint 1 goal: CEO + managers kickoff discussion ─────────────────
    sprint_goal    = run_sprint_kickoff(brief, rolling_ctxs, health_states)
    sprint_results: List[ProjectResult] = []
    sprint_num     = 1

    while sprint_num <= max_sprints:
        sprint_start = time.time()
        logger.info(f"\n{'█'*55}\nSPRINT {sprint_num}/{MAX_SPRINTS}\n{'█'*55}")

        result = _run_sprint(
            sprint_goal, sprint_num,
            rolling_ctxs, health_states, prev_sprint_summary="",
        )
        result.duration_s = time.time() - sprint_start
        sprint_results.append(result)
        save_outputs(result, sprint_num=sprint_num)

        # ── Sprint retrospective: CEO + managers review and decide ────────
        next_goal, should_ship = run_sprint_retrospective(
            brief, sprint_num, result, rolling_ctxs, health_states
        )

        if should_ship:
            logger.info(f"\n{'█'*55}\nPRODUCT SHIPPED after {sprint_num} sprint(s)\n{'█'*55}")
            break

        sprint_goal = next_goal
        sprint_num += 1

    if sprint_num > MAX_SPRINTS:
        logger.warning(f"[run_company] hit MAX_SPRINTS={MAX_SPRINTS} — stopping without CEO ship decision")

    logger.info(f"\nTotal duration: {time.time() - start:.0f}s | {token_summary()}")
    return sprint_results


# ── Save outputs ──────────────────────────────────────────────────────────────
def _h_swarm_status(h_swarm: float, n_workers: int) -> str:
    """Return '⚠ elevated' or 'stable' using the same scaled threshold as the run logic."""
    return "⚠ elevated" if h_swarm > 1.5 * n_workers else "stable"


def _team_md(result: TeamResult, brief: str, title: str) -> str:
    n_workers = max(len(result.worker_outputs), 1)
    status    = _h_swarm_status(result.H_swarm, n_workers)
    header = (
        f"# {title}\n\n"
        f"**Project:** {brief}\n\n"
        f"**Consensus Stance:** {result.consensus_stance.upper()} — "
        f"{STANCE_DESC[result.consensus_stance]}\n\n"
        f"**Team Confidence:** {result.confidence:.0%} "
        f"(H_swarm={result.H_swarm:.3f}"
        f"{' ' + status if status == '⚠ elevated' else ''})\n\n"
        f"---\n\n"
    )
    worker_md = "\n\n".join(
        f"### {w.title}\n\n"
        f"*Stance: {w.stance.upper()} | F_health={w.F_health:.3f}"
        f"{'| ⚠ anomaly' if w.anomaly else ''}*\n\n"
        f"{w.output}"
        + (f"\n\n**Tool results:**\n" + "\n".join(w.tool_results) if w.tool_results else "")
        for w in result.worker_outputs
    )
    return (
        header
        + result.manager_synthesis
        + "\n\n---\n\n## Individual Contributions\n\n"
        + worker_md
    )


def _save_conversation(title: str, turns: List[Dict[str, str]], sprint_num: Optional[int] = None) -> None:
    """Append a CEO↔manager conversation to company_output/conversations_sprintN.md."""
    suffix = f"_sprint{sprint_num}" if sprint_num is not None else ""
    path = OUTPUT_DIR / f"conversations{suffix}.md"
    lines = [f"## {title}\n"]
    for turn in turns:
        speaker = turn["speaker"]
        text    = turn["text"].strip()
        lines.append(f"### {speaker}\n\n{text}\n")
    block = "\n---\n".join(lines) + "\n\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)


def save_outputs(result: ProjectResult, sprint_num: Optional[int] = None) -> None:
    suffix = f"_sprint{sprint_num}" if sprint_num is not None else ""
    team_files = [
        (result.architecture, f"architecture{suffix}.md",   "Architecture"),
        (result.design,       f"design_spec{suffix}.md",    "Design Specification"),
        (result.engineering,  f"implementation{suffix}.md", "Implementation"),
        (result.qa,           f"qa_report{suffix}.md",      "QA Report"),
    ]
    for team_result, filename, title in team_files:
        if team_result is not None:
            (OUTPUT_DIR / filename).write_text(
                _team_md(team_result, result.brief, title), encoding="utf-8"
            )

    completed_teams = [
        t for t in [result.architecture, result.design, result.engineering, result.qa]
        if t is not None
    ]
    dashboard_rows = "\n".join(
        f"| {t.team:<13} | {t.H_swarm:.3f} | {t.confidence:.0%} | "
        f"{t.consensus_stance} | {_h_swarm_status(t.H_swarm, max(len(t.worker_outputs), 1))} |"
        for t in completed_teams
    )
    sprint_header = f"Sprint {sprint_num} — " if sprint_num is not None else ""
    (OUTPUT_DIR / f"ceo_summary{suffix}.md").write_text(
        f"# {sprint_header}Executive Summary\n\n"
        f"**Project:** {result.brief}\n\n"
        f"**Overall Confidence:** {result.overall_confidence:.0%} | "
        f"**H_swarm:** {result.overall_H_swarm:.3f} | "
        f"**Duration:** {result.duration_s:.0f}s\n\n"
        f"---\n\n{result.ceo_summary}\n\n---\n\n"
        f"## Execution Plan\n\n"
        f"```\n{result.execution_plan.raw[:600]}\n```\n\n"
        f"## H_swarm Dashboard\n\n"
        f"| Team | H_swarm | Confidence | Stance | Status |\n"
        f"|------|---------|------------|--------|--------|\n"
        f"{dashboard_rows}",
        encoding="utf-8",
    )

    def _serial(obj):
        if isinstance(obj, np.ndarray):  return obj.tolist()
        if isinstance(obj, np.floating): return float(obj)
        if isinstance(obj, np.integer):  return int(obj)
        raise TypeError(f"Not serializable: {type(obj)}")

    data = asdict(result)
    # Read token counters under lock to avoid torn reads
    with _token_lock:
        _snap_calls = _call_count
        _snap_in    = _tokens_in
        _snap_out   = _tokens_out
    data["token_usage"] = {
        "calls":      _snap_calls,
        "tokens_in":  _snap_in,
        "tokens_out": _snap_out,
        "total":      _snap_in + _snap_out,
        "summary":    token_summary(),
    }
    with open(OUTPUT_DIR / "results.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_serial)
    logger.info(f"\nOutputs saved to {OUTPUT_DIR}/")
    logger.info(f"Token usage: {token_summary()}")


# ── Dashboard ─────────────────────────────────────────────────────────────────
def print_dashboard(result: ProjectResult) -> None:
    teams = [t for t in [result.architecture, result.design, result.engineering, result.qa] if t is not None]
    print(f"\n{'═'*62}")
    print(f"  QUANTUM SWARM COMPANY — PROJECT COMPLETE")
    print(f"{'═'*62}")
    print(f"  Project  : {result.brief[:65]}")
    print(f"  Duration : {result.duration_s:.0f}s")
    print(f"  Overall  : {result.overall_confidence:.0%} confidence  |  H_swarm={result.overall_H_swarm:.3f}")
    print(f"{'─'*62}")
    print(f"  Execution plan phases: {len(result.execution_plan.phases)}")
    for i, phase in enumerate(result.execution_plan.phases, 1):
        print(f"    Phase {i}: {', '.join(phase)}")
    print(f"{'─'*62}")
    print(f"  {'Team':<15} {'H_swarm':>8}  {'Confidence':>10}  {'Stance':<12}  Status")
    print(f"  {'─'*15} {'─'*8}  {'─'*10}  {'─'*12}  {'─'*10}")
    for t in teams:
        status = _h_swarm_status(t.H_swarm, max(len(t.worker_outputs), 1))
        print(f"  {t.team:<15} {t.H_swarm:>8.3f}  {t.confidence:>10.0%}  {t.consensus_stance:<12}  {status}")
    print(f"{'─'*62}")
    print(f"  Outputs in {OUTPUT_DIR}/")
    print(f"    architecture.md  design_spec.md  implementation.md")
    print(f"    qa_report.md     ceo_summary.md  results.json")
    print(f"    code/            tests/          design/   config/")
    print(f"{'─'*62}")
    print(f"  Tokens: {token_summary()}")
    print(f"{'═'*62}\n")


# ── Entry point ───────────────────────────────────────────────────────────────
DEFAULT_BRIEF = (
    "Build a REST API for user authentication: "
    "registration, login with JWT tokens, password hashing with bcrypt, "
    "refresh token rotation, rate limiting on login attempts, "
    "and email verification flow."
)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Quantum Swarm Software Company")
    parser.add_argument("brief", nargs="*", help="Project brief")
    parser.add_argument("--sprints", type=int, default=5, help="Maximum number of sprints")
    args = parser.parse_args()

    brief = " ".join(args.brief).strip() if args.brief else DEFAULT_BRIEF
    MAX_SPRINTS = args.sprints

    print(f"\n{'═' * 62}")
    print(f"  QUANTUM SWARM SOFTWARE COMPANY")
    print(f"{'═' * 62}")
    print(f"  Project : {brief}")
    print(f"  Sprints : {MAX_SPRINTS}\n")

    sprint_results = run_company(brief, max_sprints=MAX_SPRINTS)
    for i, result in enumerate(sprint_results, 1):
        print(f"\n── Sprint {i}/{len(sprint_results)} ──")
        print_dashboard(result)
