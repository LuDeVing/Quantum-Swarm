"""Codebase and per-worktree RAG indexing over project output."""

from __future__ import annotations

import hashlib
import logging
import pickle
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import OUTPUT_DIR

logger = logging.getLogger("company")

__all__ = [
    "CodebaseRAG",
    "WorktreeRAG",
    "get_rag",
    "get_worktree_rag",
    "_RAG_EMBED_MODEL",
    "_RAG_CHUNK_LINES",
    "_RAG_EXTENSIONS",
    "_is_ignored_project_path",
    "_bg_index_file",
    "_bg_rag_refresh_after_tree_change",
]


def _is_ignored_project_path(path: Path) -> bool:
    """Dependency trees, VCS metadata, and bytecode dirs — exclude from RAG and file walks."""
    parts = path.parts
    return (
        "node_modules" in parts
        or ".git" in parts
        or "__pycache__" in parts
        or "target" in parts  # Rust
        or "vendor" in parts  # Go / vendored trees
        or ".gradle" in parts
    )


class CodebaseRAG:
    """
    Lightweight RAG over eng_output/ code files.
    Chunks files by function/class boundary, embeds with Gemini embedding model
    (gemini-embedding-001), stores as a numpy matrix. Queried with cosine
    similarity at agent time. Index is persisted to disk and rebuilt only when
    files change.
    """

    EMBED_MODEL = "gemini-embedding-001"
    # CACHE_PATH must NOT be a class-level attribute — OUTPUT_DIR can be overridden
    # at runtime (e.g. run_engineers_only.py sets sc.OUTPUT_DIR = "eng_output"), and a
    # frozen class attribute would keep pointing at "eng_output/rag_index.pkl",
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
        # Native / JVM / other stacks (keep aligned with _rag_split_chunks)
        ".rs", ".go",
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
        ".cs", ".java", ".kt", ".kts", ".swift", ".scala",
        ".rb", ".php", ".ex", ".exs", ".erl", ".hs", ".ml", ".clj",
        ".toml",  # Cargo, Poetry, etc. (usually small in SUBDIRS)
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
                if _is_ignored_project_path(path):
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

def _rag_split_at_starts(
    lines: List[str], starts: Tuple[str, ...], chunk_lines: int, lstrip: bool = True
) -> List[str]:
    """Accumulate lines; flush when a new top-level construct begins (prefix match)."""
    chunks, buf = [], []
    for line in lines:
        head = line.lstrip() if lstrip else line
        if any(head.startswith(s) for s in starts) and buf:
            chunks.append("\n".join(buf))
            buf = []
        buf.append(line)
        if len(buf) >= chunk_lines:
            chunks.append("\n".join(buf))
            buf = []
    if buf:
        chunks.append("\n".join(buf))
    return [c for c in chunks if c.strip()]


def _rag_split_chunks(text: str, ext: str, chunk_lines: int = _RAG_CHUNK_LINES) -> List[str]:
    """Split text by definition boundaries where we know them; else fixed line windows."""
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
    if ext == ".rs":
        return _rag_split_at_starts(
            lines,
            (
                "fn ", "pub fn ", "pub async fn ", "pub(crate) fn ", "pub(super) fn ",
                "impl ", "trait ", "mod ", "pub mod ", "struct ", "enum ",
            ),
            chunk_lines,
        )
    if ext == ".go":
        return _rag_split_at_starts(
            lines, ("func ", "type ", "const ", "var "), chunk_lines
        )
    if ext in (".java", ".cs", ".kt", ".kts"):
        return _rag_split_at_starts(
            lines,
            ("class ", "interface ", "record ", "enum ", "namespace ", "public class "),
            chunk_lines,
        )
    if ext in (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h", ".c"):
        return _rag_split_at_starts(
            lines,
            ("class ", "struct ", "namespace ", "template ", "void ", "static ", "inline "),
            chunk_lines,
        )
    return [
        chunk for chunk in (
            "\n".join(lines[i:i + chunk_lines])
            for i in range(0, len(lines), chunk_lines)
        )
        if chunk.strip()
    ]

def _rag_embed_batch(texts: List[str]) -> Optional[List[np.ndarray]]:
    try:
        from software_company.llm_client import get_client

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

def _bg_rag_refresh_after_tree_change() -> None:
    try:
        get_rag().update()
    except Exception as e:
        logger.warning(f"[RAG] refresh after tree change failed: {e}")

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
