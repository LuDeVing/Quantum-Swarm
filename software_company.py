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
from dataclasses import dataclass, asdict
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
    if append and path.exists():
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing + "\n\n---\n\n" + content, encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")
    logger.info(f"[{team_name}] canonical file updated: {path.name}")


def _tool_write_code_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "code")
    owner = get_dashboard().get_file_owner(filename)
    if owner and owner != _get_agent_id():
        return (
            f"BLOCKED: '{filename}' belongs to {owner} — they claimed this file. "
            f"Call message_teammate('{owner}', '...') to coordinate, "
            f"or claim a different domain for your work."
        )
    path = OUTPUT_DIR / "code" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    # Embed in background so agents can search mid-sprint without blocking writes
    threading.Thread(
        target=lambda p: _bg_index_file(p),
        args=(path,),
        daemon=True,
        name=f"rag-{filename}",
    ).start()
    return f"Written {len(content)} chars to code/{filename}"


def _bg_index_file(path: Path) -> None:
    try:
        get_rag().update_file(path)
    except Exception as e:
        logger.warning(f"[RAG] background index failed for {path.name}: {e}")


def _tool_write_test_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "tests")
    path = OUTPUT_DIR / "tests" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to tests/{filename}"


def _tool_write_design_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "design")
    path = OUTPUT_DIR / "design" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to design/{filename}"


def _tool_write_config_file(filename: str, content: str) -> str:
    filename = _strip_subdir_prefix(filename, "config")
    path = OUTPUT_DIR / "config" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Written {len(content)} chars to config/{filename}"


def _tool_read_file(filename: str) -> str:
    for subdir in ["code", "tests", "design", "config", ""]:
        p = (OUTPUT_DIR / subdir / filename if subdir else OUTPUT_DIR / filename).resolve()
        # Prevent path traversal outside the output directory
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

    def update(self):
        """Scan all output files, embed new/changed chunks, persist cache."""
        new_chunks = self._scan_files()
        if not new_chunks:
            return
        to_embed = [c for c in new_chunks if not self._already_embedded(c["hash"])]
        if not to_embed:
            return
        logger.info(f"[RAG] embedding {len(to_embed)} new chunks across {len(set(c['file'] for c in to_embed))} files")
        vecs = self._embed_batch([c["text"] for c in to_embed])
        if vecs is None:
            return
        for chunk, vec in zip(to_embed, vecs):
            chunk["vec"] = vec
        self.chunks = [c for c in self.chunks if c["hash"] in {n["hash"] for n in new_chunks}]
        existing_new = {c["hash"] for c in to_embed}
        for c in new_chunks:
            if c["hash"] not in existing_new:
                # keep existing vec
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
        # Only embed chunks not already in the index
        to_embed = [c for c in new_chunks if not self._already_embedded(c["hash"])]
        if to_embed:
            vecs = self._embed_batch([c["text"] for c in to_embed])
            if vecs is None:
                return
            for chunk, vec in zip(to_embed, vecs):
                chunk["vec"] = vec
        # Fill in existing vecs for unchanged chunks
        with self._lock:
            existing_by_hash = {c["hash"]: c for c in self.chunks if "vec" in c}
        for c in new_chunks:
            if "vec" not in c and c["hash"] in existing_by_hash:
                c["vec"] = existing_by_hash[c["hash"]]["vec"]
        valid_new = [c for c in new_chunks if "vec" in c]
        with self._lock:
            # Remove old chunks for this file, add new ones
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


# ── Work Dashboard ────────────────────────────────────────────────────────────

class WorkDashboard:
    """
    Shared coordination layer for agents working in parallel.
    Tracks domain ownership and routes async messages between agents.
    Persists across sprints so agents remember their domains.
    """
    SAVE_PATH = OUTPUT_DIR / "WORK_DASHBOARD.json"

    def __init__(self):
        self.domains:  Dict[str, Dict] = {}
        self.messages: Dict[str, List] = {}
        self._lock = threading.RLock()
        self._load()

    def claim(self, domain: str, owner: str, description: str, file_patterns: str, sprint: int) -> str:
        with self._lock:
            existing = self.domains.get(domain)
            if existing and existing["owner"] != owner and existing["status"] == "active":
                return (
                    f"CONFLICT: '{domain}' is owned by {existing['owner']} "
                    f"(sprint {existing['sprint']}). Their work: {existing['description'][:100]}. "
                    f"Use a different domain name or message them to coordinate."
                )
            self.domains[domain] = {
                "owner": owner, "description": description,
                "file_patterns": file_patterns, "sprint": sprint, "status": "active",
            }
            self._save()
            return f"CLAIMED: '{domain}' registered. You own files matching: {file_patterns}"

    def get_file_owner(self, filename: str) -> Optional[str]:
        """Return the owner of a filename if it matches any active domain's file_patterns."""
        with self._lock:
            for d in self.domains.values():
                if d["status"] != "active":
                    continue
                patterns = [p.strip() for p in d["file_patterns"].split(",")]
                for pat in patterns:
                    # Simple glob-style match: exact name or wildcard prefix
                    if pat == filename or (pat.startswith("*") and filename.endswith(pat[1:])):
                        return d["owner"]
        return None

    def release_sprint(self, sprint: int):
        """Mark all active domains from this sprint as complete."""
        with self._lock:
            for d in self.domains.values():
                if d.get("sprint") == sprint and d.get("status") == "active":
                    d["status"] = "complete"
            self._save()

    def get_status(self) -> str:
        with self._lock:
            if not self.domains:
                return "Dashboard is empty — no domains claimed yet this project."
            lines = ["| Domain | Owner | Files | Status | Sprint |",
                     "|--------|-------|-------|--------|--------|"]
            for name, d in sorted(self.domains.items()):
                lines.append(
                    f"| {name} | {d['owner']} | {d['file_patterns'][:40]} "
                    f"| {d['status']} | {d['sprint']} |"
                )
            return "\n".join(lines)

    def send_message(self, from_agent: str, to_agent: str, message: str, sprint: int) -> str:
        with self._lock:
            self.messages.setdefault(to_agent, []).append(
                {"from": from_agent, "text": message, "sprint": sprint}
            )
            self._save()
            return f"Message queued for {to_agent}. They will receive it in Round 2."

    def get_messages(self, agent_id: str) -> str:
        with self._lock:
            msgs = self.messages.pop(agent_id, [])
            self._save()
            if not msgs:
                return "No messages from teammates."
            return "\n".join(
                f"FROM {m['from']} (sprint {m['sprint']}): {m['text']}" for m in msgs
            )

    def _save(self):
        try:
            self.SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.SAVE_PATH.write_text(
                json.dumps({"domains": self.domains, "messages": self.messages}, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[Dashboard] save failed: {e}")

    def _load(self):
        try:
            if self.SAVE_PATH.exists():
                data = json.loads(self.SAVE_PATH.read_text(encoding="utf-8"))
                self.domains  = data.get("domains", {})
                self.messages = data.get("messages", {})
                logger.info(f"[Dashboard] loaded {len(self.domains)} domains")
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
    Agents call open_app() to acquire a slot, interact, then close_browser() to release."""

    POOL_SIZE   = 3
    TIMEOUT_SEC = 120

    def __init__(self):
        self._semaphore = threading.Semaphore(self.POOL_SIZE)
        self._local     = threading.local()   # per-thread: .page, .browser, .playwright

    def acquire(self, url: str) -> str:
        got = self._semaphore.acquire(timeout=self.TIMEOUT_SEC)
        if not got:
            return "[BROWSER POOL FULL: all 3 slots busy after 120s — try again later]"
        try:
            from playwright.sync_api import sync_playwright
            pw      = sync_playwright().start()
            browser = pw.chromium.launch(headless=True)
            page    = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30_000)
            self._local.page       = page
            self._local.browser    = browser
            self._local.playwright = pw
            return self._describe("Page loaded")
        except Exception as e:
            self._semaphore.release()
            self._local.page = None
            return f"[BROWSER ERROR: {e}]"

    def action(self, action: str, selector: str, value: str = "") -> str:
        page = getattr(self._local, "page", None)
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
        page = getattr(self._local, "page",       None)
        brow = getattr(self._local, "browser",    None)
        pw   = getattr(self._local, "playwright", None)
        try:
            if page: page.close()
            if brow: brow.close()
            if pw:   pw.stop()
        except Exception:
            pass
        finally:
            self._local.page       = None
            self._local.browser    = None
            self._local.playwright = None
            self._semaphore.release()
        return "Browser closed. Pool slot released."

    def _describe(self, context: str) -> str:
        page = self._local.page
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
_thread_ctx = threading.local()   # .agent_id: str, .sprint_num: int

def _get_agent_id()   -> str: return getattr(_thread_ctx, "agent_id",   "")
def _get_sprint_num() -> int: return getattr(_thread_ctx, "sprint_num", 1)
def _set_agent_ctx(agent_id: str, sprint_num: int) -> None:
    _thread_ctx.agent_id   = agent_id
    _thread_ctx.sprint_num = sprint_num

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
        yaml.safe_load(content)
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
            timeout=120,
            cwd=str(OUTPUT_DIR),
        )
        out = result.stdout + result.stderr
        out = out[-3000:] if len(out) > 3000 else out
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120s"
    except Exception as e:
        return f"ERROR: {e}"


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
def write_code_file(filename: str, content: str) -> str:
    """Write source code to company_output/code/<filename>. Content is the complete file text."""
    return _tool_write_code_file(filename, content)

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
    """MANDATORY FIRST STEP. See who owns which domains and files across the whole team.
    Call this before claiming any domain or writing any file. Shows current sprint state."""
    return get_dashboard().get_status()

@lc_tool
def claim_domain(domain_name: str, description: str, file_patterns: str) -> str:
    """MANDATORY before writing files. Register your work domain to prevent conflicts.
    domain_name: short identifier e.g. 'backend_auth', 'frontend_kanban', 'docker_infra'
    description: what you are building
    file_patterns: comma-separated files you will write e.g. 'auth.py, auth_routes.py'
    Returns CLAIMED (proceed) or CONFLICT (coordinate with the owner first)."""
    return get_dashboard().claim(
        domain_name, _get_agent_id(), description, file_patterns, _get_sprint_num()
    )

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
        write_code_file, write_test_file, write_design_file, write_config_file,
        read_file, list_files, search_codebase,
        check_dashboard, claim_domain, message_teammate, check_messages,
        open_app, browser_action, close_browser,
        validate_python, validate_json, validate_yaml,
        generate_endpoint_table, generate_er_diagram, create_ascii_diagram,
        create_user_flow, create_wireframe, create_style_guide,
        scan_vulnerabilities, check_owasp,
    ]
}

# Dashboard tools available to all roles that write or review work
_DASHBOARD_TOOLS    = ["check_dashboard", "claim_domain", "message_teammate", "check_messages"]
_DASHBOARD_RO_TOOLS = ["check_dashboard", "message_teammate", "check_messages"]  # read-only for QA/arch

_ROLE_TOOL_NAMES: Dict[str, List[str]] = {
    "system_designer":    ["create_ascii_diagram"] + _DASHBOARD_RO_TOOLS,
    "api_designer":       ["generate_endpoint_table", "validate_yaml"] + _DASHBOARD_RO_TOOLS,
    "db_designer":        ["generate_er_diagram"] + _DASHBOARD_RO_TOOLS,
    "ux_researcher":      ["create_user_flow", "write_design_file"] + _DASHBOARD_RO_TOOLS,
    "ui_designer":        ["create_wireframe", "write_design_file"] + _DASHBOARD_RO_TOOLS,
    "visual_designer":    ["create_style_guide", "write_design_file"] + _DASHBOARD_RO_TOOLS,
    "unit_tester":        ["write_test_file", "validate_python", "scan_vulnerabilities",
                           "run_shell", "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser"] + _DASHBOARD_RO_TOOLS,
    "integration_tester": ["write_test_file", "validate_json", "run_shell", "http_request",
                           "read_file", "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser"] + _DASHBOARD_RO_TOOLS,
    "security_auditor":   ["scan_vulnerabilities", "check_owasp", "run_shell", "http_request",
                           "list_files", "search_codebase",
                           "open_app", "browser_action", "close_browser"] + _DASHBOARD_RO_TOOLS,
}
_DEV_TOOL_NAMES = ["write_code_file", "validate_python", "validate_json",
                   "validate_yaml", "write_config_file", "read_file", "run_shell",
                   "list_files", "search_codebase",
                   "open_app", "browser_action", "close_browser"] + _DASHBOARD_TOOLS


def get_role_lc_tools(role_key: str) -> List:
    """Return list of LangChain tool objects for this role."""
    names = _ROLE_TOOL_NAMES.get(role_key, [])
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

    try:
        result = agent.invoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 16},
        )
    except Exception as e:
        logger.error(f"[{label}] agent error: {e}")
        return f"[ERROR: {e}]\nSTANCE: PRAGMATIC", [], 10.0

    messages = result.get("messages", [])

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
    text = final_ai.content if final_ai and isinstance(final_ai.content, str) else ""

    # Token accounting: LangChain's Gemini integration stores usage on the AIMessage
    # object itself as `usage_metadata` (not inside response_metadata).
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
    if len(text) < 150 and tool_results:
        tool_summary = "\n".join(tool_results[:6])
        fallback_prompt = (
            f"You just used these tools:\n{tool_summary}\n\n"
            "Write a detailed technical summary of what was built, key decisions, "
            "and integration notes. End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
        )
        text = llm_call(fallback_prompt, label=f"{label}_summary", get_logprobs=False, system=_SYSTEM_AGENT)
        logger.info(f"[{label}] fallback summary triggered ({len(text)}c)")

    logger.info(
        f"[{label}] ({len(text)}c | tools={len(tool_results)}) "
        f"[total: {token_summary()}]: {text[:80]}{'...' if len(text) > 80 else ''}"
    )

    # Perplexity estimate: try logprobs from metadata, else length-based heuristic
    perplexity = _perplexity_from_lc(final_ai)
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
            return _CONFIDENCE_MAP[letter]
    except Exception:
        pass
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
    total = _tokens_in + _tokens_out
    # Gemini 3.1 Flash-Lite pricing: $0.25/1M in, $1.50/1M out
    cost = (_tokens_in * 0.25 + _tokens_out * 1.50) / 1_000_000
    return (
        f"calls={_call_count}  "
        f"in={_tokens_in:,}  out={_tokens_out:,}  total={total:,}  "
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
        "healthy":   1.0 - 2.0 * confusion,
        "uncertain": 1.0 - 2.0 * abs(confusion - 0.5),
        "confused":  2.0 * confusion - 1.0,
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

    def add(self, task: str, output: str) -> None:
        entry = f"Task: {task[:100]}. Output: {output[:250]}"
        self.recent.append(entry)
        if len(self.recent) > self.max_recent:
            old = self.recent.pop(0)
            prompt = (
                "Maintain a concise running summary of a software engineer's work.\n\n"
                f"Current summary:\n{self.summary or '(none)'}\n\n"
                f"New entry:\n{old}\n\n"
                "Update summary. Max 80 words. Preserve decisions made, patterns used, issues found. "
                "Reply with ONLY the updated summary."
            )
            result = llm_call(prompt, label="ctx", system=_SYSTEM_WORKER)
            if not result.startswith("[ERROR"):
                self.summary = result

    def get(self) -> str:
        if not self.summary and not self.recent:
            return ""
        parts = []
        if self.summary:
            parts.append(f"PROJECT HISTORY:\n{self.summary}")
        if self.recent:
            parts.append("RECENT WORK:\n" + "\n".join(f"- {e}" for e in self.recent))
        return "\n".join(parts) + "\n\n"


# ── Stance extraction + consistency weight ────────────────────────────────────
def extract_stance_probs(output: str) -> np.ndarray:
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
    if has_tools and manifest_path.exists():
        manifest_snippet = (
            "\n\n─── CODEBASE INDEX (PROJECT_MANIFEST.md) ───\n"
            + manifest_path.read_text(encoding="utf-8")[:2000]
            + "\n────────────────────────────────────────────\n"
            "IMPORTANT: Before writing any file, call list_files() and search_codebase() "
            "to check what already exists. Do NOT reimplement existing code — extend it.\n"
        )

    dashboard_snippet = ""
    if has_tools:
        dashboard_snippet = (
            "\n\n─── WORK DASHBOARD (Sprint " + str(sprint_num) + ") ───\n"
            + get_dashboard().get_status()
            + "\n────────────────────────────────\n"
        )

    dod_checklist = _get_dod(role_key)

    if round_num == 1:
        prompt = (
            f"{goal_anchor}"
            f"You are a {role['title']} at a software company.\n"
            f"Expertise: {role['expertise']}\n"
            f"Responsibility: {role['responsibility']}\n\n"
            f"{ctx_text}"
            f"{manifest_snippet}"
            f"{dashboard_snippet}"
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
    board_prompt = (
        f"You are the {m_info['title']}.\n\n"
        f"PROJECT BRIEF:\n{brief}\n\n"
        f"Post {n} work items to the team blackboard. Each item must be:\n"
        f"  - Independent (no blocking dependencies on other items)\n"
        f"  - Sized for one person in one sprint\n"
        f"  - Clear enough that a specialist can self-assign without asking questions\n\n"
        f"Format EXACTLY as (one line each):\n"
        + "\n".join(f"ITEM_{i+1}: <concise task description>" for i in range(n))
    )
    board_output = llm_call(board_prompt, label=f"{manager_role}_board_post",
                             system=_manager_system(manager_role))

    # Parse board items
    items: Dict[str, str] = {}
    for i in range(1, n + 1):
        m = re.search(rf"ITEM_{i}:\s*(.+)", board_output)
        items[f"item_{i}"] = m.group(1).strip() if m else f"Work item {i}"
    board_display = "\n".join(f"  [{k}] {v}" for k, v in items.items())
    logger.info(f"  {team_name} blackboard posted {n} items")

    # ── Step 2: Workers self-claim in parallel ────────────────────────────────
    def worker_claim(role_key: str) -> Tuple[str, str]:
        idx = worker_roles.index(role_key) + 1
        output = llm_call(
            f"You are {ROLES[role_key]['title']} #{idx}.\n"
            f"Expertise: {ROLES[role_key]['expertise']}\n\n"
            f"BLACKBOARD — available work items:\n{board_display}\n\n"
            f"Scan the board and claim the item that best matches your expertise.\n"
            f"State in one sentence why you are the best fit.\n"
            f"If two items fit equally, pick the one with the lower number.\n\n"
            f"End with exactly: CLAIM: item_N",
            label=f"{role_key}_claim",
            system=_worker_system(role_key),
        )
        return role_key, output

    claims: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=n) as ex:
        for role_key, output in ex.map(lambda r: worker_claim(r), worker_roles):
            claims[role_key] = output

    # Health interference across team
    ActiveInferenceState.interfere_all(
        [health_states[r] for r in worker_roles], alpha=INTERFERENCE_ALPHA
    )

    # ── Step 3: Parse claims; resolve conflicts without extra LLM round ───────
    claimed: Dict[str, str] = {}    # item_id → role_key (first valid claimant wins)
    assignments: Dict[str, str] = {}

    for role_key in worker_roles:
        m = re.search(r"CLAIM:\s*(item_\d+)", claims[role_key], re.IGNORECASE)
        if m:
            iid = m.group(1).lower()
            if iid not in claimed:
                claimed[iid] = role_key
                assignments[role_key] = iid

    # Conflict resolution: workers who lost their claim get next unclaimed item
    conflict_roles: List[str] = []
    unclaimed_items = [iid for iid in items if iid not in claimed]
    for role_key in worker_roles:
        if role_key not in assignments:
            conflict_roles.append(role_key)   # this worker lost their original claim
            if unclaimed_items:
                iid = unclaimed_items.pop(0)
                assignments[role_key] = iid
                claimed[iid] = role_key
            else:
                # All items taken — give a duplicate of the last item (shouldn't happen with n==n)
                assignments[role_key] = list(items.keys())[-1] if items else f"item_{worker_roles.index(role_key) + 1}"

    # ── Step 4: Only log/record if there were actual conflicts ───────────────
    if conflict_roles:
        logger.info(f"  {team_name}: {len(conflict_roles)} conflict(s) — manager arbitrates")
        conflict_summary = "\n".join(
            f"  {ROLES[r]['title']}: {claims[r][-120:]}" for r in conflict_roles
        )
        final_board = "\n".join(f"  ASSIGNED {ROLES[assignments[r]]['title']}: {items[assignments[r]]}"
                                 for r in worker_roles)
        rolling_ctxs[manager_role].add("blackboard arbitration",
                                        f"Resolved conflicts:\n{conflict_summary}\n\nFinal board:\n{final_board}")

    logger.info(f"\n  {team_name} blackboard assignments:")
    for role_key, iid in assignments.items():
        logger.info(f"    {role_key} → {items.get(iid, iid)[:60]}")

    for role_key in worker_roles:
        rolling_ctxs[role_key].add("blackboard claim", claims[role_key])

    return {role_key: items.get(iid, iid) for role_key, iid in assignments.items()}


# ── Team execution ────────────────────────────────────────────────────────────
MAX_TEAM_ROUNDS = 4  # hard cap for non-engineering teams


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
    worker_tasks = run_team_planning(
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
                current[futures[fut]] = fut.result()

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

        H_swarm     = sum(current[r].F_health for r in worker_roles)
        mean_stance = np.mean([np.array(current[r].stance_probs) for r in worker_roles], axis=0)
        consensus   = STANCES[int(mean_stance.argmax())]
        logger.info(
            f"{team_name} R{round_num}: H_swarm={H_swarm:.3f}  consensus={consensus.upper()}  "
            f"({'stable' if H_swarm < 1.5 else 'ELEVATED ⚠'})"
        )

        # ── Manager reviews round, decides CONTINUE or DONE ───────────────
        summaries = "\n\n".join(
            f"=== {current[r].title} (F={current[r].F_health:.3f}{'⚠' if current[r].anomaly else ''}) ===\n"
            f"{current[r].output[:600]}"
            for r in worker_roles
        )
        manager_review = llm_call(
            f"You are the {ROLES[manager_role]['title']}.\n\n"
            f"TASK: {task[:300]}\n\n"
            f"ROUND {round_num} TEAM OUTPUTS:\n{summaries}\n\n"
            f"H_swarm={H_swarm:.3f}\n\n"
            f"Review what the team produced this round:\n"
            f"1. Are there conflicts or overlaps between team members' work?\n"
            f"2. Are there gaps — things nobody addressed?\n"
            f"3. Is the work coherent and integrated as a whole?\n\n"
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

    # ── Final manager synthesis ───────────────────────────────────────────
    summaries = "\n\n".join(
        f"=== {current[r].title} (stance={current[r].stance.upper()}, F={current[r].F_health:.3f}"
        f"{'⚠' if current[r].anomaly else ''}) ===\n{current[r].output[:900]}"
        for r in worker_roles
    )
    synthesis = llm_call(
        f"You are the {ROLES[manager_role]['title']}.\n\n"
        f"TASK: {task}\n\n"
        f"TEAM OUTPUTS (after {round_num} round(s)):\n{summaries}\n\n"
        f"Consensus stance: {consensus.upper()} — {STANCE_DESC[consensus]}\n"
        f"H_swarm={H_swarm:.3f} "
        f"({'stable' if H_swarm < 1.5 else 'elevated — flag risky decisions'})\n\n"
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

    H_swarm     = sum(current[r].F_health for r in worker_roles)
    mean_stance = np.mean([np.array(current[r].stance_probs) for r in worker_roles], axis=0)
    consensus   = STANCES[int(mean_stance.argmax())]

    return TeamResult(
        team=team_name,
        manager_synthesis=synthesis,
        worker_outputs=list(current.values()),
        H_swarm=H_swarm,
        consensus_stance=consensus,
        confidence=max(0.0, 1.0 - H_swarm / (3.0 * len(worker_roles))),
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

def run_sprint_planning(
    task: str,
    health_states: Dict[str, ActiveInferenceState],
    rolling_ctxs: Dict[str, RollingContext],
) -> Dict[str, str]:
    """Delegates to run_team_planning — Engineering uses the same flow as all other teams."""
    return run_team_planning(
        "Engineering", "eng_manager", ENG_WORKERS, task, rolling_ctxs, health_states
    )


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
    return llm_call(
        f"You are the CEO.\n\nPROJECT: {brief}\n\n{team_text}\n\n"
        f"Write an executive summary:\n"
        f"1. Project Overview\n2. Key Architecture Decisions\n3. Design Highlights\n"
        f"4. Implementation Highlights\n5. Quality & Risk Assessment\n6. Next Steps\n\n"
        f"Flag any elevated H_swarm teams. Be concise and actionable.",
        label="ceo_summary",
        system=_SYSTEM_CEO,
    )


# ── Engineering team: sprint planning → parallel build → synthesize ──────────

MAX_ENG_ROUNDS = 5   # hard cap per sprint to control cost
MAX_SPRINTS    = 6   # safety cap — CEO should ship before this; prevents runaway cost


def run_engineering_team(
    task: str,
    rolling_ctxs: Dict[str, RollingContext],
    health_states: Dict[str, ActiveInferenceState],
    sprint_num: int = 1,
) -> TeamResult:
    n = len(ENG_WORKERS)
    logger.info(f"\n{'─'*55}\nTEAM: ENGINEERING ({n} devs)\n{'─'*55}")

    # ── Sprint planning: manager + devs discuss together ─────────────────
    dev_assignments = run_sprint_planning(task, health_states, rolling_ctxs)

    # ── Iterative development rounds ──────────────────────────────────────
    # Each round: all devs build in parallel, manager reviews, decides
    # CONTINUE (with feedback) or DONE. Repeats up to MAX_ENG_ROUNDS.
    manager_feedback: str = ""   # injected into each subsequent round
    built: Dict[str, WorkerOutput] = {}
    round_num = 1

    while round_num <= MAX_ENG_ROUNDS:
        logger.info(f"\n{'─'*55}\nEngineering Round {round_num}/{MAX_ENG_ROUNDS}\n{'─'*55}")

        def build_feature(dev_key: str, rnd: int = round_num, feedback: str = manager_feedback) -> WorkerOutput:
            _set_agent_ctx(dev_key, sprint_num)
            feature_desc     = dev_assignments[dev_key]
            dashboard_status = get_dashboard().get_status()

            # What teammates built last round (empty on round 1)
            peer_context = ""
            if built:
                peer_summaries = "\n\n".join(
                    f"Dev {other.split('_')[1]} ({dev_assignments[other]}):\n{built[other].output[:400]}"
                    for other in ENG_WORKERS if other != dev_key and other in built
                )
                peer_context = f"\nWHAT YOUR TEAMMATES BUILT LAST ROUND:\n{peer_summaries}\n"

            feedback_section = (
                f"\nMANAGER FEEDBACK FROM ROUND {rnd - 1}:\n{feedback}\n"
                f"Address every point above before marking your work done.\n"
            ) if feedback else ""

            round_instruction = (
                "This is your first round. Implement your feature completely."
                if rnd == 1 else
                f"This is round {rnd}. Read the manager feedback and peer outputs above. "
                f"Fix integration issues, resolve conflicts, and run the app to verify it boots."
            )

            team_files = _read_team_files()
            team_files_section = (
                f"\n\n─── TEAM SPECIFICATIONS (read before writing any code) ───\n{team_files}\n"
                f"────────────────────────────────────────────────────────\n"
            ) if team_files else ""

            goal_anchor = ""
            if _current_sprint_goal:
                goal_anchor = (
                    f"╔══════════════════════════════════════════════════════╗\n"
                    f"║  SPRINT GOAL (your north star — never lose sight of this)\n"
                    f"║  {_current_sprint_goal[:200]}\n"
                    f"╚══════════════════════════════════════════════════════╝\n\n"
                )

            dod_checklist = _get_dod(dev_key)

            prompt = (
                f"{goal_anchor}"
                f"You are Software Developer #{dev_key.split('_')[1]}.\n"
                f"Expertise: {ROLES[dev_key]['expertise']}\n\n"
                f"{rolling_ctxs[dev_key].get()}"
                f"PROJECT CONTEXT:\n{task[:400]}\n\n"
                f"YOUR FEATURE: {feature_desc}\n\n"
                f"Your teammates are working on:\n"
                + "\n".join(
                    f"  Dev {other.split('_')[1]}: {dev_assignments[other]}"
                    for other in ENG_WORKERS if other != dev_key
                )
                + f"\n\nWORK DASHBOARD:\n{dashboard_status}\n"
                + team_files_section
                + peer_context
                + feedback_section
                + f"\n{round_instruction}\n"
                f"Write actual, working code. Implement exactly what the architecture and design specs say. "
                f"Fix any bugs listed in QA findings. Run your code with run_shell to verify it works.\n\n"
                f"{dod_checklist}\n\n"
                f"End with: STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]"
            )
            output, tool_results, perplexity = _run_with_tools(prompt, dev_key, f"{dev_key}_r{rnd}")
            sims    = perplexity_to_similarities(perplexity)
            F       = health_states[dev_key].update(sims)
            anomaly = health_states[dev_key].is_anomaly()
            if anomaly and rnd == 1:
                logger.warning(f"[{dev_key}] ANOMALY F={F:.3f} — invoking fixer agent")
                health_states[dev_key].reset()
                output  = _run_fixer(dev_key, feature_desc, output, F)
                sims    = perplexity_to_similarities(5.0)
                F       = health_states[dev_key].update(sims)
                anomaly = health_states[dev_key].is_anomaly()
            elif anomaly:
                logger.warning(f"[{dev_key}] ANOMALY F={F:.3f} — resetting")
                health_states[dev_key].reset()
            m      = re.search(r"STANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)", output, re.IGNORECASE)
            stance = m.group(1).lower() if m else "pragmatic"
            rolling_ctxs[dev_key].add(feature_desc, output)
            return WorkerOutput(
                role=dev_key, title=f"Software Developer — {feature_desc[:40]}",
                round=rnd, output=output, tool_results=tool_results,
                stance=stance, stance_probs=extract_stance_probs(output).tolist(),
                F_health=F, anomaly=anomaly,
            )

        with ThreadPoolExecutor(max_workers=n) as ex:
            futures = {ex.submit(build_feature, dev): dev for dev in ENG_WORKERS}
            for fut in as_completed(futures):
                built[futures[fut]] = fut.result()

        # ── Health interference ───────────────────────────────────────────
        ActiveInferenceState.interfere_all(
            [health_states[d] for d in ENG_WORKERS], alpha=INTERFERENCE_ALPHA
        )

        H_swarm     = sum(built[d].F_health for d in ENG_WORKERS)
        mean_stance = np.mean([np.array(built[d].stance_probs) for d in ENG_WORKERS], axis=0)
        consensus   = STANCES[int(mean_stance.argmax())]
        logger.info(
            f"Engineering R{round_num}: H_swarm={H_swarm:.3f}  consensus={consensus.upper()}  "
            f"({'stable' if H_swarm < 1.5 else 'ELEVATED ⚠'})"
        )

        # ── Manager reviews round, decides CONTINUE or DONE ───────────────
        feature_summaries = "\n\n".join(
            f"=== Dev {dev.split('_')[1]} — {dev_assignments[dev]} ===\n{built[dev].output[:600]}"
            for dev in ENG_WORKERS
        )
        team_files = _read_team_files()
        team_files_section = f"\n\nTEAM SPECIFICATIONS:\n{team_files}\n" if team_files else ""
        manager_review = llm_call(
            f"You are the {ROLES['eng_manager']['title']}.\n\n"
            f"SPRINT TASK:\n{task[:300]}\n"
            + team_files_section +
            f"\nROUND {round_num} DEV OUTPUTS:\n{feature_summaries}\n\n"
            f"H_swarm={H_swarm:.3f} ({'stable' if H_swarm < 1.5 else 'elevated'})\n\n"
            f"Review what the team built against the architecture spec, design spec, and QA findings above.\n"
            f"Ask yourself:\n"
            f"1. Is there a working entry point (main.py / docker-compose.yml)?\n"
            f"2. Are all features integrated and consistent with the architecture spec?\n"
            f"3. Does the implementation match the design spec?\n"
            f"4. Are the bugs and gaps listed in QA findings addressed?\n"
            f"5. Did any dev actually run the app and confirm it boots?\n\n"
            f"If everything is integrated and the app is runnable: respond with DECISION: DONE\n"
            f"Otherwise: respond with DECISION: CONTINUE\n"
            f"Then list specific, numbered actions each dev must take next round. "
            f"Reference the spec files — tell devs exactly what to implement or fix.",
            label=f"eng_manager_r{round_num}_review",
            system=_manager_system("eng_manager"),
        )
        rolling_ctxs["eng_manager"].add(task, manager_review)
        logger.info(f"[eng_manager] Round {round_num} review: {manager_review[:120]}...")

        if "DECISION: DONE" in manager_review or round_num >= MAX_ENG_ROUNDS:
            if round_num >= MAX_ENG_ROUNDS:
                logger.warning(f"[Engineering] hit MAX_ENG_ROUNDS={MAX_ENG_ROUNDS} — stopping")
            break

        manager_feedback = manager_review
        round_num += 1

    # ── Final manager synthesis ───────────────────────────────────────────
    feature_summaries = "\n\n".join(
        f"=== Dev {dev.split('_')[1]} — {dev_assignments[dev]} ===\n{built[dev].output[:700]}"
        for dev in ENG_WORKERS
    )
    synthesis = llm_call(
        f"You are the {ROLES['eng_manager']['title']}.\n\n"
        f"Your team completed {round_num} round(s) of development.\n\n"
        f"FINAL OUTPUTS:\n{feature_summaries}\n\n"
        f"H_swarm={H_swarm:.3f}\n\n"
        f"Synthesize into a single coherent implementation guide:\n"
        f"1. How the features connect and integrate\n"
        f"2. Shared dependencies and interfaces\n"
        f"3. Integration order\n"
        f"4. Any remaining gaps\n"
        f"5. Final runnable project structure and start command",
        label="eng_manager_synthesis",
        system=_manager_system("eng_manager"),
    )
    rolling_ctxs["eng_manager"].add(task, synthesis)

    H_swarm     = sum(built[d].F_health for d in ENG_WORKERS)
    mean_stance = np.mean([np.array(built[d].stance_probs) for d in ENG_WORKERS], axis=0)
    consensus   = STANCES[int(mean_stance.argmax())]

    return TeamResult(
        team="Engineering",
        manager_synthesis=synthesis,
        worker_outputs=list(built.values()),
        H_swarm=H_swarm,
        consensus_stance=consensus,
        confidence=max(0.0, 1.0 - H_swarm / (3.0 * n)),
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


def run_company(brief: str) -> List[ProjectResult]:
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

    while sprint_num <= MAX_SPRINTS:
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
def _team_md(result: TeamResult, brief: str, title: str) -> str:
    header = (
        f"# {title}\n\n"
        f"**Project:** {brief}\n\n"
        f"**Consensus Stance:** {result.consensus_stance.upper()} — "
        f"{STANCE_DESC[result.consensus_stance]}\n\n"
        f"**Team Confidence:** {result.confidence:.0%} "
        f"(H_swarm={result.H_swarm:.3f}"
        f"{' ⚠ elevated' if result.H_swarm > 1.5 else ''})\n\n"
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
        f"{t.consensus_stance} | {'⚠ elevated' if t.H_swarm > 1.5 else 'stable'} |"
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
    data["token_usage"] = {
        "calls":      _call_count,
        "tokens_in":  _tokens_in,
        "tokens_out": _tokens_out,
        "total":      _tokens_in + _tokens_out,
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
        status = "⚠ elevated" if t.H_swarm > 1.5 else "stable"
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
    brief = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else DEFAULT_BRIEF

    print(f"\n{'═'*62}")
    print(f"  QUANTUM SWARM SOFTWARE COMPANY")
    print(f"{'═'*62}")
    print(f"  Project : {brief}")
    print(f"  Sprints : until CEO ships\n")

    sprint_results = run_company(brief)
    for i, result in enumerate(sprint_results, 1):
        print(f"\n── Sprint {i}/{len(sprint_results)} ──")
        print_dashboard(result)
