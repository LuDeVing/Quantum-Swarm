"""Role-scoped long-term memory with Graph RAG for all agents.

Architecture (inspired by the HippoRAG / Mem0g / MAGMA literature):

  GRAPH STRUCTURE (NetworkX DiGraph per role)
  ┌──────────────────────────────────────────────────────────────┐
  │  concept:{name}  ──[causes]──►  concept:{name}              │
  │       │                              │                       │
  │  [appears_in]                   [appears_in]                 │
  │       ▼                              ▼                       │
  │   fact:{id}  ◄──[mentions]──  concept:{name}                │
  └──────────────────────────────────────────────────────────────┘

  Node types:
    "concept"  — library, pattern, error type, architectural concept
    "fact"     — a single extracted lesson (sprint, success, lesson text)

  Edge types (concept→concept):
    "causes"       — A causes B (e.g. missing_context_manager → connection_leak)
    "fixes"        — A fixes B
    "related_to"   — general co-occurrence
    "used_with"    — A appears alongside B
  Edge types (concept↔fact):
    "appears_in"   — concept → fact
    "mentions"     — fact → concept

RETRIEVAL (spreading activation, like HippoRAG):
  1. Identify seed concept nodes matching query terms
  2. Spread activation outward through edges (2 hops, 0.7 decay)
  3. Collect fact nodes sorted by activation score
  4. Falls back to keyword scoring when graph has no matching seeds

PERSISTENCE:
  eng_output/memory/{role_key}.json
  Format: {"role": ..., "facts": [...], "graph": <node_link_data>}

ROLE POOLING:
  dev_1..dev_8 share "dev_engineer" — cross-agent learning within a role.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import networkx as nx

logger = logging.getLogger("company")


# ── helpers ───────────────────────────────────────────────────────────────────

def _output_dir() -> Path:
    from .config import OUTPUT_DIR
    return OUTPUT_DIR


def _canon_role(role_key: str) -> str:
    """dev_1..dev_8 share one memory pool; all other roles are independent."""
    if role_key.startswith("dev_"):
        return "dev_engineer"
    return role_key


def _term_set(text: str) -> set:
    """Lowercase word tokens from text, length ≥ 3, minus noise words."""
    _NOISE = {"the", "and", "for", "with", "that", "this", "are", "was",
              "use", "must", "from", "into", "can", "not", "will", "each"}
    return {w for w in re.findall(r"[a-z][a-z0-9_]*", text.lower())
            if len(w) >= 3 and w not in _NOISE}


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class MemoryFact:
    id: str
    sprint: int
    timestamp: str
    task: str            # first 120 chars
    lesson: str          # extracted lesson, target ≤ 40 words
    tags: List[str]      # keyword tags (legacy + graph seed)
    success: bool
    confidence: float


# ── store ─────────────────────────────────────────────────────────────────────

class RoleMemoryStore:
    """
    Persistent Graph RAG memory for one canonical role.

    Internally maintains:
      - self._facts  : List[MemoryFact]  (ordered, for eviction)
      - self._graph  : nx.DiGraph        (concept + fact nodes, typed edges)
    """

    MAX_FACTS = 150

    def __init__(self, canonical_role: str) -> None:
        self.role = canonical_role
        self._path: Optional[Path] = None
        self._facts: List[MemoryFact] = []
        self._graph: nx.DiGraph = nx.DiGraph()
        self._lock = threading.Lock()
        self._loaded = False

    # ── persistence ───────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        if self._path is None:
            mem_dir = _output_dir() / "memory"
            mem_dir.mkdir(parents=True, exist_ok=True)
            self._path = mem_dir / f"{self.role}.json"
        return self._path

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            if self.path.exists():
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    self._facts = [MemoryFact(**f) for f in raw.get("facts", [])]
                    graph_data = raw.get("graph")
                    if graph_data:
                        self._graph = nx.node_link_graph(
                            graph_data, directed=True, multigraph=False
                        )
                    else:
                        # Backward-compat: rebuild graph from flat facts
                        self._graph = nx.DiGraph()
                        for fact in self._facts:
                            self._add_fact_to_graph_locked(fact, fact.tags, [])
                except Exception as e:
                    logger.warning(
                        f"[memory:{self.role}] failed to load ({e}), starting fresh"
                    )
            self._loaded = True

    def _save_locked(self) -> None:
        """Caller must hold self._lock."""
        try:
            graph_data = nx.node_link_data(self._graph, edges="edges")
            payload = {
                "role": self.role,
                "facts": [asdict(f) for f in self._facts],
                "graph": graph_data,
            }
            self.path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"[memory:{self.role}] save failed: {e}")

    # ── graph helpers ─────────────────────────────────────────────────────────

    def _concept_id(self, name: str) -> str:
        return f"concept:{name.lower().strip()}"

    def _fact_id(self, fact_uuid: str) -> str:
        return f"fact:{fact_uuid}"

    def _ensure_concept_locked(self, name: str) -> str:
        """Add concept node if missing; return its node ID."""
        nid = self._concept_id(name)
        if nid not in self._graph:
            self._graph.add_node(nid, type="concept", label=name.lower(), freq=0)
        self._graph.nodes[nid]["freq"] = self._graph.nodes[nid].get("freq", 0) + 1
        return nid

    def _add_fact_to_graph_locked(
        self,
        fact: MemoryFact,
        entities: List[str],
        relations: List[dict],
    ) -> None:
        """Add fact node + concept nodes + edges.  Caller holds self._lock."""
        fid = self._fact_id(fact.id)
        self._graph.add_node(
            fid,
            type="fact",
            lesson=fact.lesson,
            sprint=fact.sprint,
            success=fact.success,
            confidence=fact.confidence,
        )
        # Connect each entity concept ↔ fact
        for entity in entities:
            if not entity.strip():
                continue
            cid = self._ensure_concept_locked(entity)
            self._graph.add_edge(cid, fid, rel="appears_in", weight=1.0)
            self._graph.add_edge(fid, cid, rel="mentions", weight=1.0)

        # Add concept→concept relationship edges
        for rel in relations:
            src_name = str(rel.get("from", "")).strip()
            dst_name = str(rel.get("to", "")).strip()
            rel_type = str(rel.get("rel", "related_to")).strip()
            if not src_name or not dst_name:
                continue
            src_id = self._ensure_concept_locked(src_name)
            dst_id = self._ensure_concept_locked(dst_name)
            # Accumulate weight on repeated observations of the same relation
            if self._graph.has_edge(src_id, dst_id):
                self._graph[src_id][dst_id]["weight"] = (
                    self._graph[src_id][dst_id].get("weight", 1.0) + 0.5
                )
            else:
                self._graph.add_edge(src_id, dst_id, rel=rel_type, weight=1.0)

    # ── writing ───────────────────────────────────────────────────────────────

    def add_fact(
        self,
        lesson: str,
        task: str,
        tags: List[str],
        sprint: int,
        success: bool,
        confidence: float = 0.8,
        entities: Optional[List[str]] = None,
        relations: Optional[List[dict]] = None,
    ) -> None:
        """Add a fact and wire it into the knowledge graph."""
        self._ensure_loaded()
        fact = MemoryFact(
            id=uuid.uuid4().hex[:8],
            sprint=sprint,
            timestamp=datetime.now(timezone.utc).isoformat(),
            task=task[:120],
            lesson=lesson[:250],
            tags=[t.lower().strip() for t in tags if t.strip()],
            success=success,
            confidence=max(0.0, min(1.0, confidence)),
        )
        # Use entities if provided, fall back to tags
        graph_entities = [e for e in (entities or tags) if e.strip()]
        graph_relations = relations or []

        with self._lock:
            self._facts.append(fact)
            self._add_fact_to_graph_locked(fact, graph_entities, graph_relations)
            # Evict: sort by confidence asc, sprint asc → drop oldest least-confident
            if len(self._facts) > self.MAX_FACTS:
                self._facts.sort(key=lambda f: (f.confidence, f.sprint))
                evicted = self._facts[: -self.MAX_FACTS]
                self._facts = self._facts[-self.MAX_FACTS :]
                # Remove evicted fact nodes (leave concept nodes intact)
                for ef in evicted:
                    fid = self._fact_id(ef.id)
                    if fid in self._graph:
                        self._graph.remove_node(fid)
            self._save_locked()
        logger.debug(
            f"[memory:{self.role}] +fact sprint={sprint} "
            f"entities={graph_entities[:3]} rels={len(graph_relations)}"
        )

    # ── retrieval — spreading activation ─────────────────────────────────────

    def query(self, task_description: str, top_k: int = 5) -> str:
        """
        Graph-based retrieval using spreading activation (HippoRAG-style).

        Steps:
          1. Find concept nodes whose label overlaps with query terms (seeds).
          2. Spread activation through edges for 2 hops with 0.7 decay.
          3. Collect fact nodes; rank by activation.
          4. Fall back to keyword scoring when no seeds match (cold start).
        """
        self._ensure_loaded()
        with self._lock:
            g = self._graph
            facts = list(self._facts)

        if not g.nodes or not facts:
            return ""

        query_terms = _term_set(task_description)
        if not query_terms:
            return ""

        # ── Step 1: seed concept nodes ────────────────────────────────────────
        seed_activation: Dict[str, float] = {}
        for nid, data in g.nodes(data=True):
            if data.get("type") != "concept":
                continue
            # Split underscores so "connection_leak" matches query word "leak"
            label_terms = _term_set(data.get("label", "").replace("_", " "))
            overlap = label_terms & query_terms
            if overlap:
                # Seed strength = overlap fraction + log-freq bonus
                strength = len(overlap) / max(len(query_terms), 1)
                freq = data.get("freq", 1)
                strength += min(0.3, freq * 0.05)
                seed_activation[nid] = strength

        # ── Step 2: spreading activation (2 hops, decay 0.7) ─────────────────
        if seed_activation:
            activation: Dict[str, float] = dict(seed_activation)
            DECAY = 0.7
            HOPS  = 2
            for _ in range(HOPS):
                delta: Dict[str, float] = {}
                for node, act in activation.items():
                    for neighbor in g.neighbors(node):
                        w = g[node][neighbor].get("weight", 1.0)
                        delta[neighbor] = delta.get(neighbor, 0.0) + act * DECAY * w
                for node, inc in delta.items():
                    activation[node] = activation.get(node, 0.0) + inc
        else:
            # ── Fallback: keyword scoring (no matching concept seeds) ─────────
            activation = {}
            fact_lookup = {self._fact_id(f.id): f for f in facts}
            for fid, fact in fact_lookup.items():
                if fid not in g:
                    continue
                fact_terms = _term_set(fact.lesson) | _term_set(" ".join(fact.tags))
                word_score = len(fact_terms & query_terms) * 0.5
                if word_score > 0:
                    activation[fid] = word_score + fact.sprint * 0.1

        # ── Step 3: collect and rank fact nodes ───────────────────────────────
        fact_scores: List[Tuple[float, str]] = []
        for nid, act in activation.items():
            if act <= 0:
                continue
            if g.nodes.get(nid, {}).get("type") == "fact":
                fact_scores.append((act, nid))

        if not fact_scores:
            return ""

        fact_scores.sort(reverse=True)
        seen: set = set()
        lines: List[str] = []
        for act, fid in fact_scores:
            if len(lines) >= top_k:
                break
            node_data = g.nodes.get(fid, {})
            lesson = node_data.get("lesson", "")
            if not lesson or lesson in seen:
                continue
            seen.add(lesson)
            status = "ok" if node_data.get("success") else "fail"
            sprint = node_data.get("sprint", 0)
            lines.append(f"- [Sprint {sprint} {status}] {lesson}")

        return "\n".join(lines)

    # ── extraction ────────────────────────────────────────────────────────────

    def extract_and_save(
        self,
        task_description: str,
        output: str,
        sprint: int,
        success: bool,
    ) -> None:
        """
        Background LLM call: extract lessons + entities + relations from a completed task.
        Runs in a daemon thread — all exceptions are caught and logged.
        """
        try:
            import software_company as sc

            role_label = self.role.replace("_", " ")
            prompt = (
                f"You are helping a {role_label} agent build a knowledge graph from experience.\n\n"
                f"Task: {task_description[:200]}\n"
                f"Success: {success}  Sprint: {sprint}\n"
                f"Output excerpt:\n{output[:500]}\n\n"
                "Extract 1-3 concrete, reusable lessons. For each lesson also extract:\n"
                "  - entities: key concepts, library names, patterns, or error types mentioned\n"
                "  - relations: causal/structural links between entities (optional)\n\n"
                "Rules for lessons: ACTIONABLE (DO/AVOID), SPECIFIC (name the library/error), max 35 words.\n\n"
                "Respond with JSON only (no prose, no markdown fences):\n"
                "[\n"
                "  {\n"
                '    "lesson": "Always use async context managers for SQLAlchemy sessions",\n'
                '    "tags": ["sqlalchemy", "async", "database"],\n'
                '    "entities": ["sqlalchemy", "async_context_manager", "connection_leak"],\n'
                '    "relations": [\n'
                '      {"from": "missing_context_manager", "rel": "causes", "to": "connection_leak"},\n'
                '      {"from": "async_context_manager", "rel": "fixes", "to": "connection_leak"}\n'
                "    ],\n"
                '    "confidence": 0.9\n'
                "  }\n"
                "]"
            )
            raw = sc.llm_call(prompt, label=f"memory_extract:{self.role}")
            if not raw or raw.startswith("[ERROR"):
                return
            raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
            raw = re.sub(r"\n?```$", "", raw.strip())
            items = json.loads(raw)
            if not isinstance(items, list):
                return
            saved = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                lesson = str(item.get("lesson", "")).strip()
                if not lesson:
                    continue
                self.add_fact(
                    lesson=lesson,
                    task=task_description,
                    tags=[str(t) for t in item.get("tags", []) if t],
                    sprint=sprint,
                    success=success,
                    confidence=float(item.get("confidence", 0.8)),
                    entities=[str(e) for e in item.get("entities", []) if e],
                    relations=item.get("relations") or [],
                )
                saved += 1
            logger.info(
                f"[memory:{self.role}] sprint={sprint} extracted {saved} lesson(s), "
                f"graph now {self._graph.number_of_nodes()} nodes / "
                f"{self._graph.number_of_edges()} edges"
            )
        except Exception as e:
            logger.debug(
                f"[memory:{self.role}] extract_and_save failed (non-critical): {e}"
            )

    # ── introspection ─────────────────────────────────────────────────────────

    def top_concepts(self, n: int = 10) -> List[Tuple[str, int]]:
        """Top N concept nodes by frequency (expertise hot-spots)."""
        self._ensure_loaded()
        with self._lock:
            concepts = [
                (data.get("label", nid), data.get("freq", 0))
                for nid, data in self._graph.nodes(data=True)
                if data.get("type") == "concept"
            ]
        return sorted(concepts, key=lambda x: x[1], reverse=True)[:n]

    def graph_summary(self) -> str:
        """Human-readable summary of the knowledge graph."""
        self._ensure_loaded()
        with self._lock:
            n_concepts = sum(
                1 for _, d in self._graph.nodes(data=True) if d.get("type") == "concept"
            )
            n_facts = sum(
                1 for _, d in self._graph.nodes(data=True) if d.get("type") == "fact"
            )
            n_edges = self._graph.number_of_edges()
            top = self.top_concepts(5)
        top_str = ", ".join(f"{c}({f})" for c, f in top)
        return (
            f"Graph: {n_concepts} concepts, {n_facts} facts, {n_edges} edges. "
            f"Top expertise: {top_str or 'none yet'}"
        )

    def __len__(self) -> int:
        self._ensure_loaded()
        with self._lock:
            return len(self._facts)


# ── module-level singleton cache ──────────────────────────────────────────────

_stores: Dict[str, RoleMemoryStore] = {}
_stores_lock = threading.Lock()


def get_role_memory(role_key: str) -> RoleMemoryStore:
    """Return (or create) the persistent Graph RAG memory store for this role."""
    key = _canon_role(role_key)
    with _stores_lock:
        if key not in _stores:
            _stores[key] = RoleMemoryStore(key)
        return _stores[key]
