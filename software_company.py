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
from google import genai

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool as lc_tool
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

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
GEMINI_MODEL       = "gemini-3.1-flash-lite-preview"
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
TEST_GATE_ENABLED  = True        # if True, run test suite after every PHASE_INTEGRATION task
TEST_GATE_HOOKS: List[str] = []  # if non-empty, run these commands instead of auto-detect
                                  # e.g. ["pytest tests/ --tb=short -q", "mypy src/", "eslint src/"]
TEAMMATE_IDLE_HOOKS: List[str] = []  # commands to run when an agent finishes all tasks
                                      # non-zero exit logs failure and injects output into context
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


_STANCE_RE = re.compile(r'\n+STANCE:\s*\[?\w+\]?\s*$', re.IGNORECASE)

def _strip_stance(content: str) -> str:
    """Remove trailing STANCE: tag that agents append to their text output."""
    return _STANCE_RE.sub('', content.rstrip()) + '\n'

def _tool_write_code_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "code")
    code_dir = _get_code_dir()
    path     = code_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_file_lock(path):
        path.write_text(_strip_stance(content), encoding="utf-8")
    _record_sprint_file(filename)
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    return f"Written {len(content)} chars to code/{filename}"


def _bg_index_file(path: Path) -> None:
    try:
        # If this file is inside a worktree, resolve it to the canonical code/ path
        # so the RAG index always uses paths relative to OUTPUT_DIR
        path = path.resolve()
        wt_root = (OUTPUT_DIR / ".worktrees").resolve()
        if str(path).startswith(str(wt_root)):
            # .worktrees/<agent_id>/<rest> → OUTPUT_DIR/code/<rest>
            parts = path.relative_to(wt_root).parts  # (agent_id, *rest)
            canonical = (OUTPUT_DIR / "code" / Path(*parts[1:])).resolve()
            if canonical.exists():
                path = canonical
            else:
                return  # file not merged to main yet — skip indexing
        get_rag().update_file(path)
    except Exception as e:
        logger.warning(f"[RAG] background index failed for {path.name}: {e}")


def _tool_write_test_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "tests")
    path     = OUTPUT_DIR / "tests" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_file_lock(path):
        path.write_text(_strip_stance(content), encoding="utf-8")
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    return f"Written {len(content)} chars to tests/{filename}"


def _tool_write_design_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "design")
    path     = OUTPUT_DIR / "design" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_file_lock(path):
        path.write_text(_strip_stance(content), encoding="utf-8")
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    return f"Written {len(content)} chars to design/{filename}"


def _tool_write_config_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "config")
    path     = OUTPUT_DIR / "config" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with _get_file_lock(path):
        path.write_text(_strip_stance(content), encoding="utf-8")
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    return f"Written {len(content)} chars to config/{filename}"


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
    CACHE_PATH   = OUTPUT_DIR / "rag_index.pkl"
    CHUNK_LINES  = 60          # max lines per chunk
    TOP_K        = 5           # chunks returned per query
    SUBDIRS      = ["code", "tests", "design", "config"]
    EXTENSIONS   = {".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".md"}

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
            new_chunks = self._scan_files()
            if not new_chunks:
                return
            with self._lock:
                to_embed = [c for c in new_chunks if not self._already_embedded(c["hash"])]
            if not to_embed:
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
                logger.warning(f"[RAG] update_file read failed for {path}: {e}")
                return
            rel = str(path.relative_to(OUTPUT_DIR))
            new_chunk_texts = self._split_into_chunks(text, path.suffix)
            new_chunks = []
            for chunk_text in new_chunk_texts:
                h = hashlib.md5((rel + chunk_text).encode()).hexdigest()
                new_chunks.append({"file": rel, "text": chunk_text, "hash": h})
            # Only embed chunks not already in the index — check inside lock
            with self._lock:
                to_embed = [c for c in new_chunks if not self._already_embedded(c["hash"])]
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
            if c["file"] not in seen:
                first_lines = c["text"].strip().split("\n")[:3]
                seen[c["file"]] = " | ".join(l.strip() for l in first_lines if l.strip())[:120]
        lines = [f"- **{fname}**: {summary}" for fname, summary in sorted(seen.items())]
        return "\n".join(lines)

    def list_files(self) -> str:
        """Return sorted list of all indexed files."""
        if not self.chunks:
            return "[No files indexed yet]"
        files = sorted(set(c["file"] for c in self.chunks))
        return "\n".join(files)

    # ── internals ─────────────────────────────────────────────────────────

    def _scan_files(self) -> List[Dict]:
        chunks = []
        for subdir in self.SUBDIRS:
            base = OUTPUT_DIR / subdir
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.suffix not in self.EXTENSIONS or not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                rel = str(path.relative_to(OUTPUT_DIR))
                for chunk_text in self._split_into_chunks(text, path.suffix):
                    h = hashlib.md5((rel + chunk_text).encode()).hexdigest()
                    chunks.append({"file": rel, "text": chunk_text, "hash": h})
        return chunks

    def _split_into_chunks(self, text: str, ext: str) -> List[str]:
        """Split by function/class boundaries for .py, by fixed lines otherwise."""
        lines = text.split("\n")
        if ext == ".py":
            chunks, buf = [], []
            for line in lines:
                if (line.startswith("def ") or line.startswith("class ")) and buf:
                    chunks.append("\n".join(buf))
                    buf = []
                buf.append(line)
                if len(buf) >= self.CHUNK_LINES:
                    chunks.append("\n".join(buf))
                    buf = []
            if buf:
                chunks.append("\n".join(buf))
            return [c for c in chunks if c.strip()]
        else:
            return [
                "\n".join(lines[i:i + self.CHUNK_LINES])
                for i in range(0, len(lines), self.CHUNK_LINES)
                if lines[i:i + self.CHUNK_LINES]
            ]

    def _already_embedded(self, h: str) -> bool:
        return any(c.get("hash") == h and "vec" in c for c in self.chunks)

    def _embed_batch(self, texts: List[str]) -> Optional[List[np.ndarray]]:
        try:
            client = get_client()
            vecs = []
            # Gemini embedding API: batch up to 100
            for i in range(0, len(texts), 100):
                batch = texts[i:i + 100]
                resp = client.models.embed_content(
                    model=self.EMBED_MODEL,
                    contents=batch,
                )
                for emb in resp.embeddings:
                    vecs.append(np.array(emb.values, dtype=np.float32))
            return vecs
        except Exception as e:
            logger.warning(f"[RAG] embed_batch failed: {e}")
            return None

    def _embed_one(self, text: str) -> Optional[np.ndarray]:
        result = self._embed_batch([text])
        return result[0] if result else None

    def _save_cache(self):
        try:
            self.CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CACHE_PATH, "wb") as f:
                pickle.dump({"chunks": self.chunks}, f)
        except Exception as e:
            logger.warning(f"[RAG] cache save failed: {e}")

    def _load_cache(self):
        try:
            if self.CACHE_PATH.exists():
                with open(self.CACHE_PATH, "rb") as f:
                    data = pickle.load(f)
                self.chunks = data.get("chunks", [])
                valid = [c for c in self.chunks if "vec" in c]
                if valid:
                    self.embeddings = np.stack([c["vec"] for c in valid])
                    self.chunks = valid
                    logger.info(f"[RAG] loaded {len(self.chunks)} cached chunks")
        except Exception as e:
            logger.warning(f"[RAG] cache load failed: {e}")
            self.chunks = []


# Singleton
_rag: Optional[CodebaseRAG] = None
_rag_lock = threading.Lock()

def get_rag() -> CodebaseRAG:
    global _rag
    if _rag is None:
        with _rag_lock:
            if _rag is None:
                _rag = CodebaseRAG()
    return _rag


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
        self.build_command: str = ""   # e.g. "python server.py", "cargo build", "npm run build"
        self.build_file: str = ""      # e.g. "requirements.txt", "Cargo.toml", "package.json"
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
            return "\n\n".join(f"# === {key} ===\n{content}" for key, content in sorted(sections.items()))

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
                model="gemini-2.0-flash",
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

def _get_agent_id()   -> str: return _agent_id_ctx.get()
def _get_sprint_num() -> int: return _sprint_num_ctx.get()
def _set_agent_ctx(agent_id: str, sprint_num: int) -> None:
    _agent_id_ctx.set(agent_id)
    _sprint_num_ctx.set(sprint_num)

# Sprint goal is set once per sprint before any threads start — read-only during execution
_current_sprint_goal: str = ""


def _tool_search_codebase(query: str) -> str:
    """Query the RAG index for relevant code chunks."""
    return get_rag().query(query)


def _tool_list_files() -> str:
    """List all files currently in the codebase index."""
    return get_rag().list_files()


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


def _tool_run_shell(command: str) -> str:
    """Run a shell command in the output directory and return stdout + stderr (last 3000 chars)."""
    import subprocess
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(_get_code_dir()),
        )
        out = result.stdout + result.stderr
        out = out[-3000:] if len(out) > 3000 else out
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return (
            "ERROR: command timed out after 30s. "
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


# ── LangChain tool definitions (native function calling — no regex parsing) ───
# Tools accept native Python types; Gemini passes structured JSON args automatically.

@lc_tool
def run_shell(command: str) -> str:
    """Run a shell command in the project output directory. Use to start services, install deps,
    run tests, or verify the app boots. Returns combined stdout+stderr."""
    return _tool_run_shell(command)

@lc_tool
def http_request(method: str, url: str, body: str = "") -> str:
    """Make an HTTP request to a running service. method: GET/POST/PUT/DELETE.
    body: JSON string for POST/PUT. Returns HTTP status + response body."""
    return _tool_http_request(method, url, body)

@lc_tool
def start_service(name: str, command: str) -> str:
    """Start a long-running background process (server, worker, etc.) and return its startup output.
    name: a label you pick (e.g. 'api', 'frontend') — used to stop it later.
    command: the shell command to launch it (e.g. 'python server.py', 'node index.js').
    Always call stop_service(name) when you're done testing."""
    return _tool_start_service(name, command)

@lc_tool
def stop_service(name: str) -> str:
    """Stop a background service started with start_service(name).
    Always stop services when done — leaving them running blocks ports for teammates."""
    return _tool_stop_service(name)

@lc_tool
def write_code_file(filename: str, content: str) -> str:
    """Write source code to company_output/code/<filename>. Content is the complete file text."""
    return _tool_write_code_file(filename, content)

@lc_tool
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
    with _get_file_lock(path):
        # Assemble INSIDE the lock so the read+write is atomic.
        # When this agent acquires the lock, it re-reads all sections including
        # any written by other agents while this one was waiting.
        assembled = dashboard.assemble_shared_file(filename)
        path.write_text(assembled, encoding="utf-8")
    threading.Thread(target=_bg_index_file, args=(path,), daemon=True, name=f"rag-{filename}").start()
    logger.info(f"[write_file_section] {agent_id} wrote section '{section}' in {filename} ({len(content)}c)")
    return (
        f"Written section '{section}' ({len(content)}c) to shared file code/{filename}. "
        f"The assembled file is {len(assembled)}c total."
    )

@lc_tool
def write_test_file(filename: str, content: str) -> str:
    """Write a test file to company_output/tests/<filename>. Content is the complete file text."""
    return _tool_write_test_file(filename, content)

@lc_tool
def write_design_file(filename: str, content: str) -> str:
    """Write a design artifact (markdown, spec) to company_output/design/<filename>."""
    return _tool_write_design_file(filename, content)

@lc_tool
def write_config_file(filename: str, content: str) -> str:
    """Write a config or infra file (Dockerfile, YAML, requirements.txt) to company_output/config/<filename>."""
    return _tool_write_config_file(filename, content)

@lc_tool
def read_file(filename: str) -> str:
    """Read an existing file from any company_output/ subdirectory."""
    return _tool_read_file(filename)

@lc_tool
def list_files() -> str:
    """List all source files currently in the project codebase. Call this before writing any file
    to see what already exists. Returns filenames grouped by subdirectory."""
    return _tool_list_files()

@lc_tool
def search_codebase(query: str) -> str:
    """Semantic search over the entire codebase. Returns the most relevant code chunks for your query.
    Use this to find existing implementations before writing new code — e.g. 'authentication middleware',
    'WebSocket handler', 'database models'. Prevents duplicate implementations."""
    return _tool_search_codebase(query)

@lc_tool
def check_dashboard() -> str:
    """MANDATORY FIRST STEP. See current team messages and coordination status.
    Call this to read any incoming messages from teammates."""
    return get_dashboard().get_status()


@lc_tool
def message_teammate(teammate_role: str, message: str) -> str:
    """Send an async message to a teammate. They receive it in Round 2.
    Use in Round 1 to ask about interfaces, warn about dependencies, or request clarification.
    teammate_role: the role key of the recipient e.g. 'frontend_developer', 'devops_engineer'"""
    return get_dashboard().send_message(
        _get_agent_id(), teammate_role, message, _get_sprint_num()
    )

@lc_tool
def check_messages() -> str:
    """MANDATORY FIRST STEP IN ROUND 2. Read messages sent to you by teammates in Round 1.
    Contains interface questions and compatibility concerns you must address."""
    return get_dashboard().get_messages(_get_agent_id())

@lc_tool
def broadcast_message(message: str) -> str:
    """Shout a message to ALL teammates at once — use this when you make a breaking change
    that affects everyone (e.g. renamed a function, changed a shared model, moved a file).
    Every agent will receive it in their next check_messages() call.
    message: plain text description of the change and what others must update."""
    return get_dashboard().broadcast(
        _get_agent_id(), message, _get_sprint_num(), ENG_WORKERS
    )

@lc_tool
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

@lc_tool
def open_app(url: str) -> str:
    """Open a browser and navigate to a URL to visually verify your feature.
    Acquires one of 3 browser pool slots (waits if all busy). ALWAYS call close_browser() when done.
    url: full URL e.g. 'http://localhost:3000/login' or 'http://localhost:8000/docs'"""
    return get_browser_pool().acquire(url)

@lc_tool
def browser_action(action: str, selector: str, value: str = "") -> str:
    """Interact with the open browser page and see what is on screen.
    action: 'click' | 'type' | 'navigate' | 'screenshot'
    selector: CSS selector for click/type (e.g. 'button[type=submit]', '#email') or URL for navigate
    value: text to type (only for 'type' action)
    Must call open_app() first."""
    return get_browser_pool().action(action, selector, value)

@lc_tool
def close_browser() -> str:
    """Close the browser and release the pool slot so teammates can use it.
    ALWAYS call this when done — not calling it blocks other agents from getting a browser."""
    return get_browser_pool().release()

@lc_tool
def validate_python(code: str) -> str:
    """Check Python code for syntax errors. Returns 'Python syntax OK' or a description of the error."""
    return _tool_validate_python(code)

@lc_tool
def validate_json(content: str) -> str:
    """Validate a JSON string. Returns 'JSON valid' or error details."""
    return _tool_validate_json(content)

@lc_tool
def validate_yaml(content: str) -> str:
    """Validate a YAML string (Dockerfile, CI config, etc.). Returns 'YAML valid' or error details."""
    return _tool_validate_yaml(content)

@lc_tool
def generate_endpoint_table(endpoints: List[Dict]) -> str:
    """Generate a markdown table of API endpoints. Each endpoint needs: method, path, description, auth."""
    return _tool_generate_endpoint_table(json.dumps(endpoints))

@lc_tool
def generate_er_diagram(tables: List[Dict]) -> str:
    """Generate an ASCII ER diagram. Each table needs: name, fields (list of {name, type, pk, fk})."""
    return _tool_generate_er_diagram(json.dumps(tables))

@lc_tool
def create_ascii_diagram(components: List[Dict]) -> str:
    """Generate an ASCII component diagram. Each component needs: name, connects_to (list of names)."""
    return _tool_create_ascii_diagram(json.dumps(components))

@lc_tool
def create_user_flow(steps: List[Dict]) -> str:
    """Generate an ASCII user flow diagram. Each step needs: step (label), action, outcome."""
    return _tool_create_user_flow(json.dumps(steps))

@lc_tool
def create_wireframe(page_name: str, sections: List[Dict]) -> str:
    """Generate an ASCII wireframe for a UI page. Each section needs: name, type, content."""
    return _tool_create_wireframe(page_name, json.dumps(sections))

@lc_tool
def create_style_guide(colors: Dict, fonts: Dict, spacing: Dict) -> str:
    """Generate a formatted style guide. colors/fonts/spacing are dicts of token→value."""
    return _tool_create_style_guide(json.dumps({"colors": colors, "fonts": fonts, "spacing": spacing}))

@lc_tool
def scan_vulnerabilities(code: str) -> str:
    """Scan code for common security vulnerabilities (OWASP patterns). Returns severity-labelled findings."""
    return _tool_scan_vulnerabilities(code)

@lc_tool
def check_owasp(feature: str) -> str:
    """Get relevant OWASP Top 10 risks for a feature. Feature: auth, api, input, session, file_upload, database."""
    return _tool_check_owasp(feature)


# ── Role → tool mapping (LangChain tool objects) ─────────────────────────────
_LC_TOOLS_BY_NAME: Dict[str, object] = {
    t.name: t for t in [
        write_code_file, write_file_section, write_test_file, write_design_file, write_config_file,
        read_file, list_files, search_codebase,
        run_shell, http_request, start_service, stop_service,
        check_dashboard, message_teammate, check_messages,
        broadcast_message, request_contract_amendment,
        open_app, browser_action, close_browser,
        validate_python, validate_json, validate_yaml,
        generate_endpoint_table, generate_er_diagram, create_ascii_diagram,
        create_user_flow, create_wireframe, create_style_guide,
        scan_vulnerabilities, check_owasp,
    ]
}

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
                           "open_app", "browser_action", "close_browser"] + _DASHBOARD_RO_TOOLS,
    "integration_tester": ["write_test_file", "validate_python", "validate_json", "run_shell",
                           "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser"] + _DASHBOARD_RO_TOOLS,
    "security_auditor":   ["write_test_file", "scan_vulnerabilities", "check_owasp", "run_shell",
                           "start_service", "stop_service", "http_request",
                           "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser"] + _DASHBOARD_RO_TOOLS,
}
_DEV_TOOL_NAMES = ["write_code_file", "write_file_section", "write_test_file",
                   "validate_python", "validate_json",
                   "validate_yaml", "write_config_file", "read_file", "run_shell",
                   "list_files", "search_codebase", "start_service", "stop_service",
                   "http_request", "open_app", "browser_action", "close_browser"] + _DASHBOARD_TOOLS

# Engineering manager gets full file access + service tools for integration pass
_ENG_MANAGER_TOOL_NAMES = [
    "read_file", "list_files", "search_codebase",
    "write_code_file", "write_config_file",
    "validate_python", "validate_json", "validate_yaml",
    "run_shell", "start_service", "stop_service", "http_request",
] + _DASHBOARD_RO_TOOLS


def get_role_lc_tools(role_key: str) -> List:
    """Return list of LangChain tool objects for this role."""
    names = _ROLE_TOOL_NAMES.get(role_key, [])
    missing = [n for n in names if n not in _LC_TOOLS_BY_NAME]
    if missing:
        logger.warning(f"[{role_key}] tools not found in registry (skipped): {missing}")
    return [_LC_TOOLS_BY_NAME[n] for n in names if n in _LC_TOOLS_BY_NAME]


# ── LangGraph worker: runs prompt through ReAct agent, tools called natively ──
def _run_with_tools(
    prompt: str,
    role_key: str,
    label: str,
) -> Tuple[str, List[str], float]:
    """
    Run a prompt through a LangGraph ReAct agent with this role's tools.
    Returns (final_text, tool_result_strings, perplexity_estimate).
    Tool calls use native Gemini function calling — no regex, no 0-char files.
    """
    agent = _get_lc_agent(role_key)
    logger.info(f"[{label}] ── ReAct agent invoked (role={role_key}, prompt={len(prompt)}c, recursion_limit=16)")

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 16},
        )
    except Exception as e:
        logger.error(f"[{label}] agent error: {e}")
        return f"[ERROR: {e}]\nSTANCE: PRAGMATIC", [], 10.0

    messages = result.get("messages", [])
    ai_turns   = sum(1 for m in messages if isinstance(m, AIMessage))
    tool_turns = sum(1 for m in messages if isinstance(m, ToolMessage))
    logger.info(f"[{label}] agent finished — {len(messages)} messages ({ai_turns} AI turns, {tool_turns} tool calls)")

    # Collect tool results from ToolMessages
    tool_results: List[str] = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_results.append(f"[TOOL: {msg.name}] {msg.content}")
            logger.info(f"  Tool {msg.name}: {str(msg.content)[:80]}")

    # Final AI response: last AIMessage WITHOUT pending tool_calls (the summary turn)
    final_ai = next(
        (m for m in reversed(messages)
         if isinstance(m, AIMessage) and not getattr(m, "tool_calls", [])),
        None,
    )
    # Normalize: multimodal content may be a list of dicts; join string parts only
    if final_ai is not None:
        raw_content = final_ai.content
        if isinstance(raw_content, str):
            text = raw_content
        elif isinstance(raw_content, list):
            text = "".join(p if isinstance(p, str) else p.get("text", "") for p in raw_content)
        else:
            text = ""
    else:
        text = ""

    # Token accounting: LangChain's Gemini integration stores usage on the AIMessage
    # object itself as `usage_metadata` (not inside response_metadata).
    global _tokens_in, _tokens_out, _call_count
    for msg in messages:
        if isinstance(msg, AIMessage):
            usage = getattr(msg, "usage_metadata", None) or {}
            t_in  = usage.get("input_tokens", 0) or 0
            t_out = usage.get("output_tokens", 0) or 0
            with _token_lock:
                _call_count += 1
                _tokens_in  += t_in
                _tokens_out += t_out

    # Fallback: if the agent produced no meaningful summary, ask the LLM directly
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

    # Perplexity: when fallback was used the original AIMessage is stale — use length heuristic
    if used_fallback:
        perplexity = max(1.5, 10.0 - min(len(text) / 500, 1.0) * 7.0)
    else:
        perplexity = _perplexity_from_lc(final_ai)
    logger.info(f"[{label}] perplexity={perplexity:.2f}  final_text={len(text)}c")
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


def _perplexity_from_lc(msg: Optional[AIMessage]) -> float:
    """Estimate perplexity via verbal confidence elicitation, falling back to content heuristic."""
    if msg is None:
        return 8.0
    content = msg.content if isinstance(msg.content, str) else ""
    if not content or len(content) < 10:
        return 8.0
    # Ask the model to self-rate its confidence in a single token (A/B/C/D)
    try:
        elicit_prompt = (
            f"You just produced this response:\n\"\"\"\n{content[:800]}\n\"\"\"\n\n"
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
            score = _CONFIDENCE_MAP[letter]
            logger.info(f"  confidence self-rating: {letter.upper()} → perplexity={score:.1f}")
            return score
        logger.info(f"  confidence self-rating: unrecognised reply '{reply.strip()[:10]}' — falling back to content heuristic")
    except Exception as exc:
        logger.debug(f"  confidence elicitation failed: {exc}")
    return _perplexity_from_content(content)


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

# ── LLM / agent cache (avoid rebuilding on every call) ───────────────────────
_lc_llm: Optional["ChatGoogleGenerativeAI"] = None
_agent_cache: Dict[str, object] = {}
_agent_cache_lock = threading.Lock()  # guards lazy init of _lc_llm and _agent_cache

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


def _get_lc_agent(role_key: str):
    """Return (or create and cache) a LangGraph ReAct agent for this role."""
    global _lc_llm
    if role_key not in _agent_cache:
        with _agent_cache_lock:
            if role_key not in _agent_cache:   # double-checked
                if _lc_llm is None:
                    _lc_llm = ChatGoogleGenerativeAI(
                        model=GEMINI_MODEL,
                        google_api_key=os.environ["GEMINI_API_KEY"],
                    )
                tools = get_role_lc_tools(role_key)
                combined_prompt = _worker_system(role_key) + "\n\n" + _SYSTEM_AGENT
                _agent_cache[role_key] = create_react_agent(
                    _lc_llm, tools, prompt=combined_prompt
                )
    return _agent_cache[role_key]


def get_client() -> genai.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def token_summary() -> str:
    with _token_lock:
        calls = _call_count
        t_in  = _tokens_in
        t_out = _tokens_out
    total = t_in + t_out
    # Gemini 3.1 Flash-Lite: $0.25 / 1M input, $1.50 / 1M output
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
    try:
        cfg: Dict = {}
        if system:
            cfg["system_instruction"] = system
        r = get_client().models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            **({"config": cfg} if cfg else {}),
        )
        text = (r.text or "").strip()

        # Track tokens
        u = getattr(r, "usage_metadata", None)
        t_in  = getattr(u, "prompt_token_count",     0) or 0
        t_out = getattr(u, "candidates_token_count", 0) or 0
        global _tokens_in, _tokens_out, _call_count
        with _token_lock:
            _tokens_in  += t_in
            _tokens_out += t_out
            _call_count += 1

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
        logger.error(f"LLM_ERROR [{label}]: {e}")
        fallback = f"[ERROR: {e}]\nSTANCE: PRAGMATIC"
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
        f"  {dev}: {desc}" for dev, desc in dev_assignments.items()
    )
    if pool:
        pool_list = "\n".join(f"  [Pool] {iid}: {desc}" for iid, desc in pool.items())
        assignment_list += f"\n\nUNASSIGNED BACKLOG POOL:\n{pool_list}"

    assignment_list = "\n".join(f"  {d}: owns {a}" for d, a in dev_assignments.items())
    
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
            f"- 'build_command' is the shell command to run the app or run tests (e.g. 'python server.py',\n"
            f"  'cargo build', 'npm run build', 'go build ./...')\n"
            f"- 'build_file' is the config file that lists dependencies (e.g. 'requirements.txt', 'Cargo.toml',\n"
            f"  'package.json', 'go.mod'). Leave empty if not applicable.\n"
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
MAX_TASKS_PER_AGENT = 4
MAX_WALL_CLOCK      = 300   # seconds — hard timeout for entire engineering phase
MAX_RETRIES_PER_TASK = 2
_AGENT_POLL_INTERVAL = 2    # seconds between task queue polls when blocked

# Phase constants for Two-Phase Sprints
PHASE_IMPLEMENTATION = 1   # Coding individual files
PHASE_INTEGRATION    = 2   # Wiring, Docker, Infrastructure, Final Integration


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
    primary_owner: Optional[str] = None  # dev originally assigned to this file
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

        file_to_task_id = {}
        for fname, fc in registry.file_map.items():
            if fname == registry.entry_point:
                continue
            tid = f"task_{fname.replace('/', '_').replace('.', '_')}"
            file_to_task_id[fname] = tid

        # Phase 1: Implementation (Drafting)
        for fname, fc in registry.file_map.items():
            if fname == registry.entry_point:
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
                primary_owner=fc.owner if fc.owner != "system" else None,
                phase=PHASE_IMPLEMENTATION
            )

        # Phase 2: Collaborative Integration (Wiring Specialist)
        # These tasks depend on ALL Phase 1 tasks being completed and merged.
        p1_task_ids = [t.id for t in self.tasks.values() if t.phase == PHASE_IMPLEMENTATION]
        
        for fname, fc in registry.file_map.items():
            if fname == registry.entry_point:
                continue
            tid = f"task_{fname.replace('/', '_').replace('.', '_')}_p2"
            desc = f"PHASE 2: Collaborative Integration and Wiring for {fname}. " \
                   f"Fix imports and ensure it works with the merged codebase."
            
            self.tasks[tid] = EngTask(
                id=tid, file=fname, description=desc,
                depends_on=p1_task_ids, status="blocked",
                primary_owner=fc.owner if fc.owner != "system" else None,
                phase=PHASE_INTEGRATION
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
                            self.tasks[tid].primary_owner = None # No one owns it

        n_pending = sum(1 for t in self.tasks.values() if t.status == "pending")
        n_blocked = sum(1 for t in self.tasks.values() if t.status == "blocked")
        logger.info(f"[TaskQueue] initialized {len(self.tasks)} tasks ({n_pending} pending, {n_blocked} blocked) in two phases.")
        self._load()   # crash recovery: reload persisted state if available
        self._persist()

    _PERSIST_PATH = OUTPUT_DIR / "task_queue_state.json"

    def _persist(self) -> None:
        """Serialize queue state to disk after every mutation."""
        try:
            self._PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
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
            self._PERSIST_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[TaskQueue] persist failed: {e}")

    def _load(self) -> None:
        """Reload queue state from disk if available (crash recovery)."""
        if not self._PERSIST_PATH.exists():
            return
        try:
            data = json.loads(self._PERSIST_PATH.read_text(encoding="utf-8"))
            for tid, td in data.get("tasks", {}).items():
                if tid in self.tasks:
                    t = self.tasks[tid]
                    t.status      = td.get("status", t.status)
                    t.assigned_to = td.get("assigned_to", t.assigned_to)
                    t.retries     = td.get("retries", t.retries)
            self._completed_tasks = set(data.get("completed_tasks", []))
            logger.info(f"[TaskQueue] crash-recovery: reloaded state from {self._PERSIST_PATH.name}")
        except Exception as e:
            logger.warning(f"[TaskQueue] load failed: {e}")

    def claim_next(self, dev_key: str) -> Optional[EngTask]:
        """Claim the next available pending task. Prefers tasks assigned to this dev."""
        with self._lock:
            preferred = None
            fallback = None
            for t in self.tasks.values():
                if t.status != "pending":
                    continue
                if t.primary_owner == dev_key and preferred is None:
                    preferred = t
                elif fallback is None:
                    fallback = t
            chosen = preferred or fallback
            if chosen:
                chosen.status = "in_progress"
                chosen.assigned_to = dev_key
                logger.info(f"[TaskQueue] {dev_key} claimed task '{chosen.id}' ({chosen.file})")
                self._persist()
            return chosen

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
        phase_1_all_done = all(
            t.status in ("completed", "failed")
            for t in self.tasks.values() if t.phase == PHASE_IMPLEMENTATION
        )

        for t in self.tasks.values():
            if t.status == "blocked":
                # Regular dependencies check
                deps_met = all(d in self._completed_tasks for d in t.depends_on)
                
                # Phase 2 gate: Only release if Phase 1 is fully completed
                phase_gate_ok = True
                if t.phase == PHASE_INTEGRATION:
                    phase_gate_ok = phase_1_all_done

                if deps_met and phase_gate_ok:
                    t.status = "pending"
                    logger.info(f"[TaskQueue] unblocked task '{t.id}' ({t.file}) [PHASE {t.phase}]")

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
        )
        if result.returncode != 0:
            out = (result.stdout[-2000:] + "\n" + result.stderr[-2000:]).strip()
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
    Called only for PHASE_INTEGRATION tasks when TEST_GATE_ENABLED is True.
    """
    # ── Configurable hooks path ───────────────────────────────────────────
    if TEST_GATE_HOOKS:
        combined_output: List[str] = []
        for hook_cmd in TEST_GATE_HOOKS:
            try:
                result = subprocess.run(
                    hook_cmd, shell=True, capture_output=True, text=True,
                    timeout=60, cwd=str(code_dir),
                )
                raw = (result.stdout + result.stderr)[-4000:]
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
                    if any(d.rglob(g)):
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
    if _has_test_files("test_*.py", "*_test.py"):
        cmd = f"pytest {str(tests_dir)} --tb=short -q"
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
        )
        raw = (result.stdout + result.stderr)[-4000:]
        return TestGateResult(passed=(result.returncode == 0), skipped=False,
                              output=raw, command=cmd)
    except subprocess.TimeoutExpired:
        return TestGateResult(passed=False, skipped=False, command=cmd,
                              output="TEST GATE TIMEOUT: suite did not finish within 120s.")
    except Exception as e:
        return TestGateResult(passed=False, skipped=False, command=cmd,
                              output=f"TEST GATE ERROR: {e}")


# ── Git Worktree isolation for engineering agents ─────────────────────────────

import shutil as _shutil

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
        )

    def init_repo(self) -> None:
        """Initialize a git repo in code_dir if one doesn't exist, and create an initial commit."""
        if self._initialized:
            return
        git_dir = self.code_dir / ".git"
        if not git_dir.exists():
            self.code_dir.mkdir(parents=True, exist_ok=True)
            self._git("init")
            self._git("checkout", "-b", "main")
            gitignore = self.code_dir / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("__pycache__/\n*.pyc\n.worktrees/\n", encoding="utf-8")
            self._git("add", ".")
            self._git("commit", "-m", "initial skeleton", "--allow-empty")
            logger.info("[worktree] initialized git repo in code/")
        else:
            self._git("add", ".")
            result = self._git("diff", "--cached", "--quiet")
            if result.returncode != 0:
                self._git("commit", "-m", "pre-round snapshot")
        self._initialized = True

    def create_worktrees(self) -> None:
        """Create an isolated worktree + branch for each agent."""
        self.init_repo()
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        for agent_id in self.agent_ids:
            wt_path = self.worktree_root / agent_id
            if wt_path.exists():
                self._git("worktree", "remove", str(wt_path), "--force")
                if wt_path.exists():
                    _shutil.rmtree(str(wt_path), ignore_errors=True)
            branch_check = self._git("rev-parse", "--verify", agent_id)
            if branch_check.returncode == 0:
                self._git("branch", "-D", agent_id)
            result = self._git("worktree", "add", str(wt_path), "-b", agent_id)
            if result.returncode != 0:
                logger.error(f"[worktree] failed to create worktree for {agent_id}: {result.stderr}")
            else:
                logger.info(f"[worktree] created worktree for {agent_id}")

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
            return False
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
        for agent_id in self.agent_ids:
            wt_path = self.worktree_root / agent_id
            if wt_path.exists():
                self._git("worktree", "remove", str(wt_path), "--force")
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
        return False

    existing_files = []
    for p in code_dir.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            existing_files.append(str(p.relative_to(code_dir)))

    prompt = (
        f"Generate the build configuration file '{registry.build_file}'.\n\n"
        f"PROJECT FILES: {existing_files[:50]}\n"
        f"DEPENDENCIES: {registry.dependencies}\n"
        f"BUILD COMMAND: {registry.build_command}\n\n"
        f"  1. call check_dashboard() — check for messages from teammates\n"
        f"  2. call check_messages() — read every message before finalizing\n\n"
        f"Output ONLY the file content, no markdown fences.\n"
    )
    try:
        source = llm_call(prompt, label="generate_build_config")
        if source and "```" in source:
            m = re.search(r"```\w*\n(.*?)```", source, re.DOTALL)
            if m:
                source = m.group(1)
        if source and source.strip():
            bf_path.parent.mkdir(parents=True, exist_ok=True)
            bf_path.write_text(source.strip() + "\n", encoding="utf-8")
            return True
    except Exception as e:
        logger.warning(f"  LLM build-config generation failed: {e}")
    return False






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

    task_queue = EngTaskQueue(get_contracts(), dev_assignments, pool)
    built: Dict[str, WorkerOutput] = {}
    _tasks_completed_by: Dict[str, int] = {d: 0 for d in ENG_WORKERS}
    _merge_lock = threading.Lock()

    # ── build_feature: adapted for task-based work ────────────────────────

    def build_feature(dev_key: str, eng_task: EngTask) -> WorkerOutput:
        _set_agent_ctx(dev_key, sprint_num)
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
                "  - Check your dashboard and messages EVERY TURN to see what's actually relevant to you.\n"
                "  - Use search_codebase() to see your teammates' work; avoid asking them for status updates.\n"
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
        is_phase_2 = (eng_task.phase == PHASE_INTEGRATION)
        build_cmd = get_contracts().build_command

        if is_integration_specialist:
            build_errors = ""
            if build_cmd:
                try:
                    result = subprocess.run(
                        build_cmd, shell=True, cwd=str(code_dir),
                        capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode != 0:
                        build_errors = f"\nPHASE 1 BUILD ERRORS (from running '{build_cmd}'):\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}\n"
                except Exception as e:
                    build_errors = f"\nPHASE 1 BUILD FAILED: {e}\n"

            task_instruction = (
                f"FINAL INTEGRATION TEST — all components are merged.\n"
                f"{build_errors}"
                f"\nYOUR MISSION: Run '{build_cmd}' and perform a final smoke test.\n"
                f"  1. If any final issues persist, FIX them using the run_shell tool.\n"
                f"  2. Do NOT finish this task until '{build_cmd}' returns a success code.\n\n"
                f"{integration_rules}"
            )
        elif is_phase_2:
             task_instruction = (
                f"PHASE 2: COLLABORATIVE INTEGRATION for file '{eng_task.file}'\n"
                f"Description: {eng_task.description}\n\n"
                f"YOUR MISSION: Now that ALL code is merged, fix the wiring for YOUR file ONLY.\n"
                f"  1. Use search_codebase() to see how your teammates implemented their parts.\n"
                f"  2. Identify if YOUR file ('{eng_task.file}') uses the correct filenames/symbols from others.\n"
                f"  3. MANDATORY: Run '{build_cmd}' herself using the run_shell tool.\n"
                f"  4. READ the error log carefully. THE 'STAY IN YOUR LANE' RULE:\n"
                f"     - If the error is in YOUR FILE ('{eng_task.file}'), fix it and retry.\n"
                f"     - If the error is in a DIFFERENT file, DO NOT touch it. Just exit.\n"
                f"  5. Do NOT finish until YOUR file's role in the build is confirmed.\n\n"
                f"{integration_rules}"
            )
        else:
            task_instruction = (
                f"PHASE 1: IMPLEMENTATION for file '{eng_task.file}'\n"
                f"Description: {eng_task.description}\n\n"
                f"  1. call check_dashboard() and check_messages() before starting.\n"
                f"  2. Follow the project goal. You have creative freedom in Agile Mode.\n\n"
                f"  --- INTEGRATION CHECK ---\n"
                f"  3. Before completing, try running '{build_cmd}' herself using run_shell.\n"
                f"  4. If it fails because of something obvious, fix it. If it's a team-wide issue, broadcast it.\n"
                f"  5. Use broadcast_message() for any shared interface changes.\n"
                f"{integration_rules}"
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
            f"{goal_anchor}"
            f"You are Software Developer #{dev_key.split('_')[1]}.\n"
            f"Expertise: {ROLES[dev_key]['expertise']}\n\n"
            f"{rolling_ctxs[dev_key].get()}"
            f"PROJECT CONTEXT:\n{task[:400]}\n\n"
            f"TASK QUEUE STATUS:\n{queue_status}\n\n"
            f"Your teammates are working on:\n"
            + "\n".join(
                f"  Dev {other.split('_')[1]}: {dev_assignments[other]}"
                for other in ENG_WORKERS if other != dev_key
            )
            + f"\n\nWORK DASHBOARD:\n{dashboard_status}\n"
            + contract_section
            + team_files_section
            + peer_context
            + messages_section
            + f"\n{task_instruction}\n"
            f"Write actual, working code. Implement exactly what the architecture and design specs say. "
            f"Fix any bugs listed in QA findings. Run your code with run_shell to verify it works.\n\n"
            f"{dod_checklist}\n\n"
            f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )
        logger.info(f"[{dev_key}] prompt built ({len(prompt)}c) — handing off to ReAct agent")
        output, tool_results, perplexity = _run_with_tools(prompt, dev_key, f"{dev_key}_t{task_num}")
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
        """Long-running worker: pull task → worktree → build → merge → repeat."""
        while task_queue.has_work_available():
            if _tasks_completed_by[dev_key] >= MAX_TASKS_PER_AGENT:
                logger.info(f"[{dev_key}] hit MAX_TASKS_PER_AGENT={MAX_TASKS_PER_AGENT} — stopping")
                break

            eng_task = task_queue.claim_next(dev_key)
            if eng_task is None:
                if task_queue.all_done():
                    break
                import time as _time
                _time.sleep(_AGENT_POLL_INTERVAL)
                continue

            # ── TaskCreated hook: pre-task validator ──────────────────────
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
                        )
                        _hook_out = (_hook_proc.stdout + _hook_proc.stderr)[-1000:]
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
            # ─────────────────────────────────────────────────────────────

            wt = GitWorktreeManager(code_dir, [dev_key])
            try:
                wt.create_worktrees()
                _set_worktree_manager(wt)

                result = build_feature(dev_key, eng_task)
                built[dev_key] = result

                wt.commit_agent(dev_key)
                with _merge_lock:
                    resolutions = wt.merge_all()
                    if resolutions:
                        logger.info(f"[{dev_key}] merge resolutions:\n" + "\n".join(resolutions))

                # ── Test Gate (Anthropic-style hard mechanical gate) ──────
                if TEST_GATE_ENABLED and eng_task.phase == PHASE_INTEGRATION:
                    gate = _run_test_gate(OUTPUT_DIR / "code")
                    if gate.skipped:
                        logger.info(f"[{dev_key}] TEST GATE skipped — no test files detected")
                        task_queue.complete(eng_task.id)
                        _tasks_completed_by[dev_key] += 1
                    elif gate.passed:
                        logger.info(f"[{dev_key}] TEST GATE passed — '{gate.command}'")
                        task_queue.complete(eng_task.id)
                        _tasks_completed_by[dev_key] += 1
                    else:
                        eng_task_obj = task_queue.tasks.get(eng_task.id)
                        retries_used = eng_task_obj.retries if eng_task_obj else MAX_RETRIES_PER_TASK
                        if retries_used < MAX_RETRIES_PER_TASK:
                            logger.warning(
                                f"[{dev_key}] TEST GATE FAILED "
                                f"(retry {retries_used + 1}/{MAX_RETRIES_PER_TASK}) "
                                f"— '{gate.command}'\n{gate.output[:500]}"
                            )
                            rolling_ctxs[dev_key].add(
                                f"TEST GATE FAILED — {eng_task.file}",
                                f"Command: {gate.command}\nOutput:\n{gate.output}"
                            )
                            task_queue.fail(eng_task.id)
                            # _tasks_completed_by NOT incremented — retry doesn't count
                        else:
                            logger.warning(
                                f"[{dev_key}] TEST GATE FAILED but retries exhausted "
                                f"— accepting '{eng_task.id}' to avoid deadlock"
                            )
                            task_queue.complete(eng_task.id)
                            _tasks_completed_by[dev_key] += 1
                else:
                    task_queue.complete(eng_task.id)
                    _tasks_completed_by[dev_key] += 1
                # ─────────────────────────────────────────────────────────

                # Incremental RAG Update: Index the newly merged file so others can find it
                try:
                    get_rag().update()
                except Exception as e:
                    logger.warning(f"[{dev_key}] incremental RAG update failed: {e}")

            except Exception as exc:
                logger.error(f"[{dev_key}] task {eng_task.id} crashed: {exc}", exc_info=True)
                task_queue.fail(eng_task.id)
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

        # ── TeammateIdle hook: runs after agent exhausts all tasks ────────
        if TEAMMATE_IDLE_HOOKS:
            _idle_outputs: List[str] = []
            _idle_all_passed = True
            for _idle_cmd in TEAMMATE_IDLE_HOOKS:
                try:
                    _idle_proc = subprocess.run(
                        _idle_cmd, shell=True, capture_output=True, text=True,
                        timeout=60, cwd=str(code_dir),
                    )
                    _idle_out = (_idle_proc.stdout + _idle_proc.stderr)[-2000:]
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
                logger.info(f"[{dev_key}] TEAMMATE IDLE HOOK passed")
            else:
                logger.warning(f"[{dev_key}] TEAMMATE IDLE HOOK FAILED\n{_idle_combined[:300]}")
                rolling_ctxs[dev_key].add("TEAMMATE IDLE HOOK FAILED", _idle_combined)
        # ─────────────────────────────────────────────────────────────────

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
                try:
                    # Re-index the RAG so Integrators can 'see' all Phase 1 code
                    get_rag().update()
                    # Release the Integration tasks
                    task_queue._unblock_dependents()
                    _phase_1_synced = True
                    logger.info("[Manager Monitor] codebase indexed. PHASE 2 (Integration) RELEASED.\n")
                except Exception as e:
                    logger.error(f"[Manager Monitor] Sync failed: {e}")

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
    final_build = _run_build_command(get_contracts())
    if final_build:
        logger.info(f"\n[POST-ENFORCEMENT BUILD]\n{final_build}")
    else:
        logger.info("  Post-enforcement build: SUCCESS ✓")

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
    synthesis = llm_call(
        f"You are the {ROLES['eng_manager']['title']}.\n\n"
        f"Your team completed tasks asynchronously ({elapsed:.0f}s elapsed).\n\n"
        f"TASK QUEUE FINAL STATUS:\n{task_queue.get_status()}\n\n"
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
