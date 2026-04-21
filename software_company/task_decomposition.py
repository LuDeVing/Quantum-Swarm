"""Recursive task decomposition for the engineering manager.

Before the blackboard phase, the manager decomposes the sprint goal into a tree
of subtasks, drilling down until every leaf is an atomic file-level task that one
developer can implement alone. The resulting tree is saved to TASK_TREE.json and
its ASCII representation is injected into the planning prompt.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .config import OUTPUT_DIR

logger = logging.getLogger("company")

_DEPTH_LABELS = {0: "GOAL", 1: "FEATURE", 2: "COMPONENT", 3: "FILE"}


def _llm(prompt: str, label: str = "") -> str:
    import software_company as sc
    return sc.llm_call(prompt, label=label)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DecomposedTask:
    id: str
    name: str
    description: str
    parent_id: Optional[str]
    depth: int
    is_atomic: bool
    suggested_file: Optional[str]
    complexity: str  # "low" | "medium" | "high"
    children: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "is_atomic": self.is_atomic,
            "suggested_file": self.suggested_file,
            "complexity": self.complexity,
            "children": self.children,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DecomposedTask":
        return cls(
            id=d["id"],
            name=d["name"],
            description=d["description"],
            parent_id=d.get("parent_id"),
            depth=d["depth"],
            is_atomic=d["is_atomic"],
            suggested_file=d.get("suggested_file"),
            complexity=d.get("complexity", "medium"),
            children=d.get("children", []),
        )


class TaskTree:
    MAX_DEPTH = 20  # safety ceiling; manager subdivides until truly atomic
    SAVE_PATH = OUTPUT_DIR / "TASK_TREE.json"

    def __init__(self) -> None:
        self.nodes: Dict[str, DecomposedTask] = {}
        self.root_id: Optional[str] = None
        self.sprint: int = 1
        self.goal: str = ""

    def add_node(self, task: DecomposedTask) -> None:
        self.nodes[task.id] = task
        if task.parent_id is None:
            self.root_id = task.id

    def get_leaf_tasks(self) -> List[DecomposedTask]:
        """Return all atomic leaf nodes (file-level tasks)."""
        return [t for t in self.nodes.values() if t.is_atomic or not t.children]

    def format_tree(self) -> str:
        """Return an ASCII-indented tree for prompt injection."""
        if not self.root_id:
            return ""
        lines: List[str] = []
        self._render_node(self.root_id, lines, indent=0)
        return "\n".join(lines)

    def _render_node(self, node_id: str, lines: List[str], indent: int) -> None:
        node = self.nodes.get(node_id)
        if not node:
            return
        label = _DEPTH_LABELS.get(node.depth, "TASK")
        prefix = "  " * indent
        if node.is_atomic and node.suggested_file:
            lines.append(
                f"{prefix}[{label}] {node.suggested_file} - {node.description}  ({node.complexity})"
            )
        else:
            lines.append(f"{prefix}[{label}] {node.name}: {node.description}")
        for child_id in node.children:
            self._render_node(child_id, lines, indent + 1)

    def save(self) -> None:
        try:
            self.SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "sprint": self.sprint,
                "goal": self.goal,
                "root_id": self.root_id,
                "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            }
            self.SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"TaskTree.save failed: {exc}")

    def load(self) -> None:
        try:
            if not self.SAVE_PATH.exists():
                return
            data = json.loads(self.SAVE_PATH.read_text(encoding="utf-8"))
            self.sprint = data.get("sprint", 1)
            self.goal = data.get("goal", "")
            self.root_id = data.get("root_id")
            self.nodes = {
                nid: DecomposedTask.from_dict(nd)
                for nid, nd in data.get("nodes", {}).items()
            }
        except Exception as exc:
            logger.warning(f"TaskTree.load failed: {exc}")


# ---------------------------------------------------------------------------
# LLM decomposition
# ---------------------------------------------------------------------------

_DECOMPOSE_SYSTEM = (
    "You are a meticulous Engineering Manager building a fully-detailed task tree. "
    "You visit every node and keep subdividing until nothing can be split further. "
    "Respond with JSON only — no markdown fences, no extra text."
)

_DECOMPOSE_PROMPT = """\
You are an Engineering Manager building a task tree for a software sprint.
Your job: visit every node and keep subdividing until NOTHING can be split further.

SPRINT GOAL: {sprint_goal}

CURRENT NODE (depth {depth}):
  Name        : {task_name}
  Description : {task_description}

═══════════════════════════════════════════════════════════════════════════════
 STEP 1 — CAN THIS NODE BE SPLIT FURTHER?
═══════════════════════════════════════════════════════════════════════════════
A node MUST be split (is_atomic: false) if ANY of these are true:
  • It covers more than one source file.
  • It contains multiple distinct responsibilities.
  • You cannot yet write out every single class, method signature, and variable.
  • A developer reading it would still need to make architectural decisions.
  • It has more than ~4 public functions/methods — likely needs splitting.
  • Its name contains words like "system", "module", "engine", "manager",
    "handler", "pipeline", "subsystem", "layer", "component" — almost certainly
    needs further splitting.

A node is truly atomic (is_atomic: true) ONLY when ALL of these hold:
  1. Maps to EXACTLY ONE .py file.
  2. You can list EVERY class with EVERY method including __init__ with ALL typed params.
  3. You can list EVERY module-level function with full typed signature.
  4. You can list EVERY important instance variable and its type.
  5. You can list EVERY project-internal import this file will need.
  6. A developer can open a blank file and implement it with ZERO ambiguity.

═══════════════════════════════════════════════════════════════════════════════
 STEP 2 — HOW TO SPLIT (if not atomic)
═══════════════════════════════════════════════════════════════════════════════
  • Split into 2–8 subtasks, each covering a clearly distinct sub-concern.
  • Each subtask must be narrower and more concrete than its parent.
  • Subtasks will each be visited again and split further if still too broad.
  • Prefer many small focused subtasks over few large vague ones.
  • A real project of moderate complexity has 20–60+ atomic files — do not stop early.
  • When in doubt: SPLIT. You can always stop later; you cannot recover lost detail.

═══════════════════════════════════════════════════════════════════════════════
 STEP 3 — ATOMIC NODE DESCRIPTION (ZERO AMBIGUITY — ALL fields required)
═══════════════════════════════════════════════════════════════════════════════
Write 4–7 sentences covering ALL of:
  (a) File purpose — one sentence on the single responsibility of this file.
  (b) Classes — "Contains class Foo with:
        __init__(self, x: int, y: float) -> None,
        method_a(self, arg: SomeType) -> ReturnType,
        method_b(self) -> list[str],
        property bar: int."
  (c) Module-level functions (if any) — full typed signatures.
  (d) State — "Holds self.position: tuple[int,int], self.active: bool."
  (e) Connections — "Imports Vector2 from physics/vector.py and Config from
        config.py. Consumed by main.py and game_loop.py."
  A developer must be able to implement this file from the description alone.
  If you cannot fill in (b)–(e) completely — the node is NOT yet atomic, split it.

═══════════════════════════════════════════════════════════════════════════════
 OUTPUT — JSON ONLY, no markdown fences, no extra text
═══════════════════════════════════════════════════════════════════════════════
{{"subtasks": [
  {{
    "name": "ShortClearLabel",
    "description": "ATOMIC: full zero-ambiguity description per Step 3. NON-ATOMIC: what this sub-concern covers and why it needs further splitting.",
    "is_atomic": true,
    "suggested_file": "src/subdir/filename.py",
    "complexity": "low|medium|high"
  }}
]}}
"""


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


def _call_decompose(
    sprint_goal: str,
    task_name: str,
    task_description: str,
    depth: int,
    label: str,
) -> List[dict]:
    """Call the LLM to decompose one task. Returns list of subtask dicts."""
    prompt = _DECOMPOSE_PROMPT.format(
        sprint_goal=sprint_goal[:300],
        task_name=task_name,
        task_description=task_description[:200],
        depth=depth,
    )
    raw = _llm(prompt, label=label)

    # Strip markdown fences if model added them anyway
    raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())

    try:
        parsed = json.loads(raw)
        subtasks = parsed.get("subtasks", parsed) if isinstance(parsed, dict) else parsed
        if not isinstance(subtasks, list):
            return []
        result = []
        for s in subtasks:
            if not isinstance(s, dict) or "name" not in s:
                continue
            result.append({
                "name": str(s.get("name", "task")),
                "description": str(s.get("description", "")),
                "is_atomic": bool(s.get("is_atomic", False)),
                "suggested_file": s.get("suggested_file") or None,
                "complexity": str(s.get("complexity", "medium")),
            })
        return result
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Decompose parse error [{label}]: {exc} — raw: {raw[:200]}")
        return []


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_recursive_decomposition(goal: str, sprint_num: int = 1) -> TaskTree:
    """
    Recursively decompose the sprint goal into a tree of atomic leaf tasks.

    Uses BFS. All nodes at the same depth are decomposed in parallel via
    ThreadPoolExecutor so total latency is O(depth) LLM round trips.

    Returns a TaskTree whose leaf nodes each represent one source file.
    """
    tree = TaskTree()
    tree.sprint = sprint_num
    tree.goal = goal

    root = DecomposedTask(
        id=_new_id(),
        name="Sprint Goal",
        description=goal[:200],
        parent_id=None,
        depth=0,
        is_atomic=False,
        suggested_file=None,
        complexity="high",
    )
    tree.add_node(root)

    # BFS level by level so each level can be parallelised
    current_level = [root.id]

    while current_level:
        # Collect nodes at this level that still need decomposition
        to_decompose = [
            tree.nodes[nid]
            for nid in current_level
            if not tree.nodes[nid].is_atomic
            and tree.nodes[nid].depth < TaskTree.MAX_DEPTH
        ]

        if not to_decompose:
            break

        next_level: List[str] = []

        # Decompose all nodes at this level in parallel
        with ThreadPoolExecutor(max_workers=min(len(to_decompose), 8)) as pool:
            futures = {
                pool.submit(
                    _call_decompose,
                    goal,
                    node.name,
                    node.description,
                    node.depth,
                    f"decompose_d{node.depth}_{node.id}",
                ): node
                for node in to_decompose
            }
            for fut in as_completed(futures):
                node = futures[fut]
                try:
                    subtask_dicts = fut.result()
                except Exception as exc:
                    logger.warning(f"Decompose future error for {node.id}: {exc}")
                    subtask_dicts = []

                # Stop recursion if LLM can't divide further
                if len(subtask_dicts) <= 1:
                    node.is_atomic = True
                    if subtask_dicts:
                        node.suggested_file = subtask_dicts[0].get("suggested_file")
                    continue

                child_depth = node.depth + 1
                for sd in subtask_dicts:
                    # Only force atomic at the hard safety ceiling
                    is_atomic = sd["is_atomic"] or child_depth >= TaskTree.MAX_DEPTH
                    child = DecomposedTask(
                        id=_new_id(),
                        name=sd["name"],
                        description=sd["description"],
                        parent_id=node.id,
                        depth=child_depth,
                        is_atomic=is_atomic,
                        suggested_file=sd.get("suggested_file"),
                        complexity=sd.get("complexity", "medium"),
                    )
                    tree.add_node(child)
                    node.children.append(child.id)
                    if not is_atomic:
                        next_level.append(child.id)

        current_level = next_level

    tree.save()
    leaf_count = len(tree.get_leaf_tasks())
    logger.info(
        f"TaskTree: {len(tree.nodes)} nodes, {leaf_count} leaf tasks\n"
        f"\n{'='*56}\n"
        f"  TASK DECOMPOSITION TREE\n"
        f"{'='*56}\n"
        f"{tree.format_tree()}\n"
        f"{'='*56}"
    )
    return tree


# ---------------------------------------------------------------------------
# ComponentGraph — typed dependency graph for structured task assignment
# ---------------------------------------------------------------------------

@dataclass
class Component:
    """One source file / one developer unit with an explicit public interface."""
    id: str
    name: str
    file_path: str
    description: str
    public_interface: Dict[str, List[str]]  # {"classes": [], "functions": [], "constants": []}
    depends_on: List[str]   # Component IDs
    consumers: List[str]    # populated by build_consumer_index()
    complexity: str         # "low" | "medium" | "high"
    depth: int              # longest dependency path length (assigned_depths)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "file_path": self.file_path,
            "description": self.description,
            "public_interface": self.public_interface,
            "depends_on": self.depends_on,
            "consumers": self.consumers,
            "complexity": self.complexity,
            "depth": self.depth,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Component":
        return cls(
            id=d["id"],
            name=d["name"],
            file_path=d["file_path"],
            description=d.get("description", ""),
            public_interface=d.get("public_interface", {"classes": [], "functions": [], "constants": []}),
            depends_on=d.get("depends_on", []),
            consumers=d.get("consumers", []),
            complexity=d.get("complexity", "medium"),
            depth=d.get("depth", 0),
        )


class ComponentGraph:
    SAVE_PATH = OUTPUT_DIR / "COMPONENT_GRAPH.json"

    def __init__(self) -> None:
        self.nodes: Dict[str, Component] = {}
        self.topological_order: List[str] = []
        self.sprint: int = 1
        self.goal: str = ""

    def build_consumer_index(self) -> None:
        """Reverse-populate .consumers from depends_on edges."""
        for comp in self.nodes.values():
            comp.consumers = []
        for comp in self.nodes.values():
            for dep_id in comp.depends_on:
                if dep_id in self.nodes:
                    self.nodes[dep_id].consumers.append(comp.id)

    def topological_sort(self) -> None:
        """Kahn's algorithm; fallback to list(nodes) on cycle."""
        in_degree: Dict[str, int] = {cid: 0 for cid in self.nodes}
        for comp in self.nodes.values():
            for dep in comp.depends_on:
                if dep in in_degree:
                    in_degree[comp.id] = in_degree[comp.id] + 1

        queue = [cid for cid, deg in in_degree.items() if deg == 0]
        order: List[str] = []
        while queue:
            cid = queue.pop(0)
            order.append(cid)
            for consumer_id in self.nodes[cid].consumers:
                in_degree[consumer_id] -= 1
                if in_degree[consumer_id] == 0:
                    queue.append(consumer_id)

        if len(order) == len(self.nodes):
            self.topological_order = order
        else:
            logger.warning("ComponentGraph: cycle detected — using fallback ordering")
            self.topological_order = list(self.nodes.keys())

    def assign_depths(self) -> None:
        """Longest dependency path per node (leaf = 0)."""
        depths: Dict[str, int] = {}

        def _depth(cid: str) -> int:
            if cid in depths:
                return depths[cid]
            comp = self.nodes.get(cid)
            if not comp or not comp.depends_on:
                depths[cid] = 0
                return 0
            d = 1 + max(_depth(dep) for dep in comp.depends_on if dep in self.nodes)
            depths[cid] = d
            return d

        for cid in self.nodes:
            _depth(cid)
        for cid, d in depths.items():
            self.nodes[cid].depth = d

    def format_ascii(self, max_lines: int = 30) -> str:
        """Compact ASCII view for prompt injection."""
        lines: List[str] = []
        for cid in self.topological_order:
            comp = self.nodes.get(cid)
            if not comp:
                continue
            fns = comp.public_interface.get("functions", [])
            fn_preview = ", ".join(fns[:2]) + ("…" if len(fns) > 2 else "")
            dep_names = [self.nodes[d].name for d in comp.depends_on if d in self.nodes]
            consumer_names = [self.nodes[c].name for c in comp.consumers if c in self.nodes]
            dep_str = f" <- [{', '.join(dep_names)}]" if dep_names else ""
            con_str = f" -> [{', '.join(consumer_names)}]" if consumer_names else ""
            lines.append(f"  [{comp.name}] {comp.file_path}{dep_str}{con_str}")
            if fn_preview:
                lines.append(f"      exposes: {fn_preview}")
            if len(lines) >= max_lines:
                lines.append("  ...")
                break
        return "\n".join(lines)

    def save(self) -> None:
        try:
            self.SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "sprint": self.sprint,
                "goal": self.goal,
                "nodes": {cid: c.to_dict() for cid, c in self.nodes.items()},
                "topological_order": self.topological_order,
            }
            self.SAVE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning(f"ComponentGraph.save failed: {exc}")

    @classmethod
    def load(cls) -> "ComponentGraph":
        g = cls()
        try:
            if cls.SAVE_PATH.exists():
                data = json.loads(cls.SAVE_PATH.read_text(encoding="utf-8"))
                g.sprint = data.get("sprint", 1)
                g.goal = data.get("goal", "")
                g.nodes = {cid: Component.from_dict(cd) for cid, cd in data.get("nodes", {}).items()}
                g.topological_order = data.get("topological_order", list(g.nodes.keys()))
        except Exception as exc:
            logger.warning(f"ComponentGraph.load failed: {exc}")
        return g


_GRAPH_AGENT_PROMPT = """\
You are a senior Engineering Manager. Build a COMPREHENSIVE, DETAILED component dependency \
graph for this sprint goal.

SPRINT GOAL: {goal}

METHOD — top-down recursive expansion:
1. Start from the sprint goal. Identify every top-level source file needed.
2. For EACH file ask: "What does this file import from THIS project?" Add those as dependencies.
3. Repeat step 2 for every new file until you reach true leaf files (no internal imports).
4. If two files share a dependency, that dependency is ONE node (DAG, not tree).
5. Use web_search() to verify library APIs, typical module layouts, class designs, or anything
   you are unsure about before writing interface signatures.

MANDATORY COMPLETENESS RULES — violating these will trigger rejection:
- MINIMUM 12 components, ideally 15-25. Cover every file that will actually be written.
- ALWAYS include: a constants/config file, all data model files (dataclasses/TypedDicts),
  all manager/controller classes, all utility helpers, the main entry point.
- Each description: 2-4 sentences. Explain what the class/module DOES, what STATE it holds,
  and what ROLE it plays in the overall system. Never less than 30 words.
- public_interface MUST list EVERY public method/function:
    - Full typed signature: name(self, param: type = default) -> ReturnType
    - Include __init__ with every parameter and its default
    - Include @property getters as "property name: type"
    - Include class-level constants or Enum values
    - Include module-level functions (not just class methods)
  No stub like "..." or vague "update() -> None". Every method must be fully specified.
- depends_on: list every component this file imports from. Be exhaustive — if it uses a
  helper or a data model, that edge must exist.

Output ONLY valid JSON (no fences):
{{"components": [
  {{
    "id": "comp_XXXX",
    "name": "ShortName",
    "file_path": "src/module.py",
    "description": "2-4 sentences describing state, role, and behavior of this component.",
    "public_interface": {{
      "classes": ["ClassName"],
      "functions": [
        "ClassName.__init__(self, param1: type, param2: type = default) -> None",
        "ClassName.method_name(self, arg: type) -> ReturnType",
        "ClassName.property_name: type",
        "module_level_function(arg: type) -> ReturnType"
      ],
      "constants": ["CONSTANT_NAME: type = value"]
    }},
    "depends_on": ["comp_YYYY", "comp_ZZZZ"],
    "complexity": "low|medium|high"
  }}
]}}
"""

_GRAPH_VALIDATOR_SYSTEM = (
    "You are a strict senior architect validating a component dependency graph. "
    "Respond with JSON only — no markdown fences, no extra text."
)

_GRAPH_VALIDATOR_PROMPT = """\
Validate this component dependency graph for the sprint goal below. \
Be STRICT — flag every gap, vagueness, or missing piece.

SPRINT GOAL: {goal}

COMPONENT GRAPH:
{graph_ascii}

FULL COMPONENT JSON:
{components_json}

Check ALL of the following and flag EVERY violation:
1. MISSING COMPONENTS: data models, helpers, managers, constants, config, utilities,
   event systems, renderers, loaders — anything a developer would need to write that is
   not already in the graph.
2. INCOMPLETE INTERFACES: any method missing typed params, return types, or defaults;
   __init__ not listed; properties missing; module-level functions absent.
3. MISSING DEPENDENCY EDGES: if component A calls something from component B, the edge
   A.depends_on must include B's id. Flag every missing edge.
4. VAGUE DESCRIPTIONS: any description under 30 words or that doesn't explain state/role.
5. COVERAGE GAPS: aspects of the sprint goal not covered by any component.

Return JSON — no other text:
{{
  "issues": [
    {{
      "type": "missing_component|incomplete_interface|missing_dependency|vague_description|coverage_gap",
      "component_id": "comp_XXXX or null",
      "description": "specific, actionable description of what is wrong",
      "suggested_name": "SuggestedName (for missing_component only)",
      "suggested_file": "src/file.py (for missing_component only)"
    }}
  ],
  "verdict": "approved|needs_revision"
}}
"""

_GRAPH_FIXER_SYSTEM = (
    "You are a senior Engineering Manager fixing a component dependency graph. "
    "Respond with JSON only — no markdown fences, no extra text."
)

_GRAPH_FIXER_PROMPT = """\
Fix ALL issues in this component dependency graph. Return the complete improved graph.

SPRINT GOAL: {goal}

CURRENT GRAPH JSON:
{graph_json}

VALIDATOR ISSUES TO FIX:
{issues}

Instructions:
- Add every missing component listed in the issues.
- Complete every incomplete interface (add missing methods, types, defaults).
- Add all missing dependency edges.
- Expand every vague description to 2-4 sentences covering state, role, and behavior.
- Keep all existing components — do NOT remove anything.
- Assign new components fresh IDs in the format "comp_XXXX".
- Ensure no circular dependencies.

Output the COMPLETE corrected graph JSON (same format, all components):
{{"components": [...]}}
"""


def _parse_components_json(raw: str) -> list:
    """Extract and parse the components list from raw LLM text."""
    raw = raw.strip()
    json_start = raw.find("{")
    json_end = raw.rfind("}") + 1
    if json_start != -1 and json_end > json_start:
        raw = raw[json_start:json_end]
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    parsed = json.loads(raw)
    components = parsed.get("components", [])
    if not isinstance(components, list):
        return []
    return components


def _build_graph_from_components(components_raw: list, goal: str, sprint_num: int) -> Optional[ComponentGraph]:
    """Turn a raw components list into a fully-built ComponentGraph."""
    graph = ComponentGraph()
    graph.sprint = sprint_num
    graph.goal = goal
    for cr in components_raw:
        if not isinstance(cr, dict) or "id" not in cr:
            continue
        pi = cr.get("public_interface", {})
        if not isinstance(pi, dict):
            pi = {}
        comp = Component(
            id=str(cr["id"]),
            name=str(cr.get("name", cr["id"])),
            file_path=str(cr.get("file_path", "")),
            description=str(cr.get("description", "")),
            public_interface={
                "classes": list(pi.get("classes", [])),
                "functions": list(pi.get("functions", [])),
                "constants": list(pi.get("constants", [])),
            },
            depends_on=[str(d) for d in cr.get("depends_on", [])],
            consumers=[],
            complexity=str(cr.get("complexity", "medium")),
            depth=0,
        )
        graph.nodes[comp.id] = comp
    if len(graph.nodes) < 2:
        return None
    graph.build_consumer_index()
    graph.topological_sort()
    graph.assign_depths()
    return graph


def run_component_graph_generation(goal: str, sprint_num: int = 1) -> Optional[ComponentGraph]:
    """
    Agent-driven top-down ComponentGraph generation with a validate→fix loop.

    Phase 1: Manager agent builds the graph (top-down, can web_search).
    Phase 2: Validator LLM checks for missing components, incomplete interfaces,
             missing edges, vague descriptions.
    Phase 3: If issues found, Fixer LLM corrects the graph. Repeat up to 2 rounds.
    Returns None on any failure so the existing contract path kicks in.
    """
    _MAX_VALIDATION_ROUNDS = 2

    try:
        from .agent_loop import _run_with_tools

        # ── Phase 1: Agent builds initial graph ───────────────────────────
        prompt = _GRAPH_AGENT_PROMPT.format(goal=goal[:500])
        logger.info(f"[ComponentGraph] Phase 1: agent building graph for sprint {sprint_num}...")
        final_text, _, _ = _run_with_tools(
            prompt=prompt,
            role_key="eng_manager",
            label=f"comp_graph_agent_s{sprint_num}",
        )

        components_raw = _parse_components_json(final_text)
        if len(components_raw) < 2:
            logger.warning("ComponentGraph agent: < 2 components returned — skipping")
            return None

        # ── Phase 2+3: Validate → Fix loop ────────────────────────────────
        current_components = components_raw
        for _round in range(1, _MAX_VALIDATION_ROUNDS + 1):
            graph = _build_graph_from_components(current_components, goal, sprint_num)
            if not graph:
                logger.warning(f"ComponentGraph: failed to build graph on round {_round}")
                break

            # Validate
            validator_prompt = _GRAPH_VALIDATOR_PROMPT.format(
                goal=goal[:400],
                graph_ascii=graph.format_ascii(max_lines=60),
                components_json=json.dumps({"components": current_components}, indent=2)[:8000],
            )
            logger.info(f"[ComponentGraph] Phase 2 round {_round}: validating {len(graph.nodes)} components...")
            val_raw = _llm(validator_prompt, label=f"comp_graph_validator_s{sprint_num}_r{_round}")

            # Parse validator output
            try:
                val_json_start = val_raw.find("{")
                val_json_end = val_raw.rfind("}") + 1
                val_parsed = json.loads(val_raw[val_json_start:val_json_end]) if val_json_start != -1 else {}
            except Exception:
                val_parsed = {}

            issues = val_parsed.get("issues", [])
            verdict = val_parsed.get("verdict", "approved")
            logger.info(f"[ComponentGraph] Validator verdict: {verdict} ({len(issues)} issues)")

            if verdict == "approved" or not issues:
                logger.info(f"[ComponentGraph] Graph approved after round {_round}")
                break

            if _round == _MAX_VALIDATION_ROUNDS:
                logger.info(f"[ComponentGraph] Max validation rounds reached — using current graph")
                break

            # Fix
            issues_text = "\n".join(
                f"- [{i['type']}] {i.get('component_id', '')} — {i['description']}"
                for i in issues
            )
            fixer_prompt = _GRAPH_FIXER_PROMPT.format(
                goal=goal[:400],
                graph_json=json.dumps({"components": current_components}, indent=2)[:8000],
                issues=issues_text,
            )
            logger.info(f"[ComponentGraph] Phase 3 round {_round}: fixing {len(issues)} issues...")
            fix_raw = _llm(fixer_prompt, label=f"comp_graph_fixer_s{sprint_num}_r{_round}")
            fixed_components = _parse_components_json(fix_raw)
            if len(fixed_components) >= len(current_components):
                current_components = fixed_components
                logger.info(f"[ComponentGraph] Fixed graph: {len(fixed_components)} components")
            else:
                logger.warning(f"[ComponentGraph] Fixer returned fewer components — keeping current")

        # Build final graph
        graph = _build_graph_from_components(current_components, goal, sprint_num)
        if not graph:
            return None

        graph.save()
        logger.info(
            f"ComponentGraph FINAL: {len(graph.nodes)} components\n"
            f"{'='*56}\n"
            f"  COMPONENT GRAPH\n"
            f"{'='*56}\n"
            f"{graph.format_ascii()}\n"
            f"{'='*56}"
        )
        return graph

    except Exception as exc:
        logger.warning(f"ComponentGraph generation failed ({exc}) — skipping")
        return None
