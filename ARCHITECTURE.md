# Quantum Swarm — Deep Architecture Reference

This document explains in full detail how every part of the system works: the sprint lifecycle, agent execution, memory layers, health monitoring, and the physics-inspired coordination mechanisms.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Sprint Lifecycle](#2-sprint-lifecycle)
3. [Team Structure](#3-team-structure)
4. [The Agent Loop](#4-the-agent-loop)
5. [Engineering Team — Parallel Execution](#5-engineering-team--parallel-execution)
6. [Interface Contracts](#6-interface-contracts)
7. [Memory Architecture](#7-memory-architecture)
8. [Graph RAG — Long-Term Memory](#8-graph-rag--long-term-memory)
9. [Hamiltonian Swarm — Health Monitoring](#9-hamiltonian-swarm--health-monitoring)
10. [Stance System](#10-stance-system)
11. [Manager Fix Loop](#11-manager-fix-loop)
12. [Tool Registry](#12-tool-registry)
13. [Configuration Reference](#13-configuration-reference)
14. [File Layout](#14-file-layout)

---

## 1. System Overview

Quantum Swarm is a hierarchical multi-agent pipeline that converts a one-line product brief into a working, tested codebase — autonomously, without human guidance between steps.

The top-level entrypoint is:

```bash
python -m software_company "Build a REST API for a todo app"
```

Internally, this calls `run_company(brief)` in `orchestration.py`, which drives a loop of up to `MAX_SPRINTS` sprints. Each sprint produces concrete artifacts (code, tests, design specs, architecture docs), and at the end of every sprint the CEO and all managers collectively decide whether the product is ready to ship or whether another sprint is needed.

The system is **not a chatbot**. Agents do not produce prose replies. They produce files, test results, API contracts, and architecture diagrams. The LLM is the reasoning engine; the pipeline is the machine that acts on its outputs.

```
brief
  │
  └─► run_company()
        ├── sprint kickoff (CEO + 4 managers negotiate goal)
        ├── for each sprint:
        │     ├── Architecture team  →  architecture_spec.md, API contracts
        │     ├── Design team        →  design_spec.md, wireframes
        │     ├── Engineering team   →  code/ (8 agents, parallel git worktrees)
        │     └── QA team            →  tests, security audit, qa_findings.md
        └── sprint retrospective (ship or plan next sprint)
```

---

## 2. Sprint Lifecycle

### 2.1 Sprint Kickoff

Before the first sprint, the CEO and all four managers hold a kickoff meeting. This is not the CEO dictating a plan — it is a real multi-round negotiation:

**Round 1** — CEO opens with the brief and asks each manager what their team should focus on. All four managers respond simultaneously (ThreadPoolExecutor with 4 workers). Each manager names concrete deliverables, acceptance criteria, and dependencies from other teams.

**Round 2** — Each manager reads all other managers' proposals and refines their own scope to resolve conflicts and integration gaps. Again, all four run in parallel.

**Synthesis** — The CEO reads all proposals and refinements and writes a single authoritative Sprint Goal: what will be built, acceptance criteria per team, integration contracts, and the definition of "done."

This Sprint Goal is pinned at the top of every agent's prompt for the entire sprint as a "north star" box so no agent loses sight of the goal.

### 2.2 Team Execution Order

Within each sprint, teams run **sequentially** — each team's output feeds into the next:

```
Architecture  →  Design  →  Engineering  →  QA
```

This ordering is deliberate: engineers cannot write code before they have an architecture spec, and QA cannot write meaningful tests before the code exists.

### 2.3 Sprint Retrospective

After each sprint, the CEO and all managers review what was built:

1. Each manager summarizes their team's deliverables and identifies gaps.
2. The CEO reads all summaries and makes a binary decision: **SHIP** or **CONTINUE**.
3. If continuing, the CEO + managers negotiate the next sprint's goal using the same two-round process.

The retrospective result is saved to `company_output/engineering_sprint{N}.md`, `architecture_sprint{N}.md`, etc. for audit.

---

## 3. Team Structure

### Roles

Every role has a fixed identity, a system prompt loaded from `prompts/`, and a tool whitelist.

| Role Key | Title | Team |
|----------|-------|------|
| `ceo` | Chief Executive Officer | Orchestration |
| `arch_manager` | Architecture Manager | Architecture |
| `system_designer` | Systems Architecture Specialist | Architecture |
| `api_designer` | API Design Specialist | Architecture |
| `db_designer` | Database Design Specialist | Architecture |
| `design_manager` | Design Manager | Design |
| `ux_researcher` | UX Research Specialist | Design |
| `ui_designer` | UI Design Specialist | Design |
| `visual_designer` | Visual Design Specialist | Design |
| `eng_manager` | Engineering Manager | Engineering |
| `dev_1`..`dev_8` | Software Developer | Engineering |
| `qa_manager` | QA Manager | QA |
| `unit_tester` | Unit Testing Specialist | QA |
| `integration_tester` | Integration Testing Specialist | QA |
| `security_auditor` | Security Audit Specialist | QA |

### How teams run

Non-engineering teams use `run_team()` in `teams.py`:

1. **Round 1** — all workers run in parallel. Each reads the Sprint Goal, existing specs, and peer outputs, then produces their deliverable.
2. **Round 2** — workers read each other's Round 1 outputs and integrate or resolve conflicts.
3. The manager reads all worker outputs and writes a merged, coherent spec.

Engineering uses a completely different model (see §5).

---

## 4. The Agent Loop

Every agent — whether architect, designer, QA, or engineer — operates inside a **ReAct loop** (Reason + Act). The loop is driven by `_run_with_tools()` in `_monolith.py`, which calls the Gemini API with a tool-use prompt and interprets function call responses.

The maximum number of rounds per agent is bounded by `MAX_RETRIES_PER_TASK`. If an agent calls no write tools in a round, the system detects it and injects a mandatory write reminder before the next round, narrowing the available tools to force a write.

### The required execution order (enforced by the prompt)

```
0. THINK         Call think(thought) — mandatory architecture analysis
                 May call web_search() and recall_memory() here
1. DISCOVER      read_file, grep_codebase, search_codebase, list_files
2. WRITE         write_code_file (the only action that counts)
3. VALIDATE      validate_python / run_shell with pytest/cargo/etc.
4. FIX           if validation fails, edit and revalidate
```

`think()` is a no-op tool (returns immediately, no LLM call) that logs the architectural reasoning to the console. It is listed first in every tool call sequence as a forcing function — the model cannot skip it because the system prompt says it is required before the first write.

### Stance tagging

Every agent must end its response with:

```
STANCE: [MINIMAL|ROBUST|SCALABLE|PRAGMATIC]
```

This tag is parsed to a 4-dimensional probability vector and used in the health monitoring system (see §9). It also appears in logs so you can see at a glance whether the sprint is trending toward over-engineering or under-engineering.

---

## 5. Engineering Team — Parallel Execution

Engineering is the most complex team because 8 agents run simultaneously, each working on a different file, and their work must integrate at the end.

### 5.1 Sprint Planning

Before any code is written, the engineering manager runs `run_sprint_planning()`:

1. An LLM call analyzes the architecture spec and produces a `FileContract` for every file that needs to be written — describing its purpose, what it imports, what it exports, and what files must exist before it can start.
2. Contracts are stored in the global `InterfaceContractRegistry` (see §6).
3. The task queue is populated from the contracts and their `depends_on` graph.

### 5.2 Task Queue

`EngTaskQueue` is a dependency-aware work queue:

- Tasks have states: `pending`, `blocked`, `in_progress`, `completed`, `failed`
- A task is only available for pickup when all entries in its `depends_on` list are `completed`
- When a task completes, the queue finds all tasks that were waiting on it and unblocks them
- State is checkpointed to `company_output/task_queue_state.json` after every mutation so the queue survives crashes

Each of the 8 `dev_*` agents runs in its own thread. Each thread calls `claim_next_available()`, executes the task, calls `complete()` or `fail()`, and immediately picks up the next available task. Agents keep working until the queue is empty or the wall-clock limit is hit.

### 5.3 Git Worktrees

Each developer writes into an **isolated git worktree** at `company_output/code/.worktrees/dev_N/`. This means all 8 developers can write to the same logical file system in parallel without merge conflicts — each has their own directory tree, their own branch.

When a developer finishes a task:
1. Their worktree branch is merged into `main` using `git merge --squash`
2. The merged files are immediately indexed into the shared RAG so other agents can `search_codebase()` and find the new code
3. A broadcast message is sent to all teammates: "COMPLETED: dev_2 finished `auth/models.py`. Exports: User, Token, hash_password"
4. Any tasks that were blocked on this file are automatically unblocked

### 5.4 Self-Verification

After writing code, each agent runs `_self_verify_file()`:
- If the file is Python: `python -m py_compile` to check syntax
- If tests exist: `python -m pytest tests/ --tb=short -q`
- If Rust: `cargo check`
- Etc.

If verification fails, the error is injected back into the agent's prompt and it gets another attempt (up to `MAX_RETRIES_PER_TASK`).

### 5.5 Test Gate

After all tasks complete, the engineering manager runs `_run_test_gate()` on the merged codebase. This is a final integration test — it detects the project's test framework automatically:

| Condition | Command |
|-----------|---------|
| `test_*.py` files exist | `python -m pytest tests/ --tb=short -q` |
| `Cargo.toml` exists | `cargo test` |
| `go.mod` exists | `go test ./...` |
| `pom.xml` exists | `mvn test -q` |
| `build.gradle` exists | `gradle test` |
| `*.csproj` / `*.sln` exists | `dotnet test` |
| `CMakeLists.txt` exists | `cmake --build build && ctest` |
| `package.json` with test script | `npm test` |

If the gate fails, the engineering manager enters the fix loop (see §11).

---

## 6. Interface Contracts

Contracts are the mechanism that prevents integration failures when 8 agents work in parallel on different files.

### FileContract

```python
@dataclass
class FileContract:
    file: str              # "routes/auth.py"
    owner: str             # "dev_2"
    imports_from: List[str]  # ["models.py", "database.py"]
    exports: List[str]       # ["login", "register", "get_current_user"]
    description: str         # what this file does
    depends_on: List[str]    # files that must be complete first
```

Every agent receives their contract in the prompt. They know exactly what symbols they must export, what files they can import from, and what their file is for — without needing to coordinate with other agents.

### EndpointContract and ModelContract

Beyond file contracts, the registry also holds API-level contracts:

```python
@dataclass
class EndpointContract:
    method: str        # "POST"
    path: str          # "/auth/login"
    request_model: str # "LoginRequest"
    response_model: str # "TokenResponse"

@dataclass
class ModelContract:
    name: str    # "User"
    fields: str  # "id: str, email: str, hashed_password: str"
    file: str    # "models.py"
```

These contracts are generated by the engineering manager's LLM call during sprint planning and are referenced by every agent. If an agent wants to change a contract (e.g., add a field to a model), they call `request_contract_amendment()` which logs the request for the manager to approve. If they change a public interface without requesting an amendment, the system will detect the mismatch during the test gate.

---

## 7. Memory Architecture

Agents have three completely independent memory layers that operate at different timescales.

### 7.1 Rolling Context (in-sprint, ephemeral)

`RollingContext` maintains a sliding window of the last 3 completed tasks plus a running summary. When the window fills, the oldest entry is summarized by a small LLM call and merged into the `summary` field:

```
Prompt injection:
  PROJECT HISTORY:
  Agent implemented auth middleware (SQLAlchemy session scope issue resolved)
  and user registration endpoint with email validation.

  RECENT WORK:
  - Task: implement login endpoint. Output: JWT token generation, bcrypt...
  - Task: implement token refresh. Output: sliding expiration window...
```

Rolling context is **in-memory only**. It resets at the start of every sprint. Its purpose is to prevent an agent from forgetting what it just did three tasks ago within the same sprint.

### 7.2 Vector RAG (cross-sprint, disk-persisted)

`CodebaseRAG` in `rag.py` maintains a vector index of all written code files. Every file is chunked (max 60 lines, splitting at function/class boundaries in a language-aware way for Python, Rust, Go, C/C++, Java, C#, Kotlin, TypeScript), embedded using `gemini-embedding-001`, and stored as a numpy array in `rag_index.pkl`.

When an agent calls `search_codebase("SQLAlchemy session management")`, the query is embedded and cosine similarity is computed against all stored chunks. The top-K most similar chunks are returned as formatted code snippets.

The RAG index persists across runs. Agents writing on Sprint 5 can find code written on Sprint 1 through semantic search.

Each agent also has an ephemeral `WorktreeRAG` — a separate in-memory index of only their own in-progress files. When `search_codebase()` is called, the agent's own worktree is searched first (freshest context), then the global merged index.

### 7.3 Graph RAG (permanent, growing)

See §8 for full detail. This is the long-term memory layer where agents accumulate expertise across all sprints.

---

## 8. Graph RAG — Long-Term Memory

### 8.1 Why a graph, not a flat list

A flat vector store retrieves by similarity to the query text. If an agent asks about "connection pooling" and the stored lesson says "use async context managers for SQLAlchemy", standard retrieval misses it because the words don't overlap.

A knowledge graph can answer this: `connection_pool → related_to → connection_leak → fixed_by → async_context_manager`. The query "connection pooling" activates the `connection_pool` node, activation spreads along edges, and the fact attached to `async_context_manager` gets retrieved — even with zero word overlap to the original query.

### 8.2 Graph structure

The graph is a **NetworkX directed graph** (`nx.DiGraph`) stored per canonical role at `company_output/memory/{role}.json`.

**Node types:**

| Type | ID format | Attributes |
|------|-----------|------------|
| `concept` | `concept:sqlalchemy` | `label`, `freq` (how often mentioned) |
| `fact` | `fact:a3f9b2c1` | `lesson` (text), `sprint`, `success`, `confidence` |

**Edge types:**

| Type | Direction | Meaning |
|------|-----------|---------|
| `causes` | concept → concept | A causes B (e.g. missing context → connection leak) |
| `fixes` | concept → concept | A is the fix for B |
| `related_to` | concept → concept | General association |
| `used_with` | concept → concept | A appears alongside B |
| `appears_in` | concept → fact | This concept is mentioned in this lesson |
| `mentions` | fact → concept | This lesson mentions this concept |

### 8.3 Extraction pipeline

After every completed task, a **background daemon thread** runs the extraction:

```python
threading.Thread(
    target=get_role_memory(dev_key).extract_and_save,
    args=(task_description, output, sprint_num, not anomaly),
    daemon=True,
).start()
```

The extraction prompt asks the LLM for 1–3 lessons in structured JSON:

```json
[{
  "lesson": "Always use async context managers for SQLAlchemy sessions",
  "tags": ["sqlalchemy", "async", "database"],
  "entities": ["sqlalchemy", "async_context_manager", "connection_leak"],
  "relations": [
    {"from": "missing_context_manager", "rel": "causes", "to": "connection_leak"},
    {"from": "async_context_manager", "rel": "fixes", "to": "connection_leak"}
  ],
  "confidence": 0.9
}]
```

Each extracted lesson becomes a `fact` node. Each entity becomes a `concept` node (created if it doesn't exist, frequency incremented if it does). Relationship entries become directed edges between concept nodes.

This runs in the background so it **never adds latency to the main pipeline**.

### 8.4 Spreading activation retrieval

When an agent is about to start a task, the query runs through spreading activation (inspired by HippoRAG and the hippocampal indexing theory of human memory):

**Step 1 — Seed identification.** Extract word tokens from the task description. For every `concept` node in the graph, split its label on underscores and check for token overlap with the query. Matching concepts become seeds with initial activation proportional to the overlap fraction plus a small log-frequency bonus.

**Step 2 — Activation spreading.** Iterate for 2 hops. In each hop, every activated node passes a fraction of its activation to its graph neighbors, weighted by the edge's accumulated weight and a fixed decay of 0.7:

```
activation[neighbor] += activation[node] × 0.7 × edge_weight
```

After 2 hops, concept nodes connected to the seeds (even with no direct word match) have accumulated activation from multiple paths.

**Step 3 — Fact collection.** Filter for `fact` nodes with activation > 0. Rank descending. Return the top-5 lesson texts.

**Fallback.** If no concept seeds are found (cold start, or query terms have no concept node matches), the system falls back to keyword scoring against stored lesson text and tags directly.

### 8.5 Role pooling

`dev_1` through `dev_8` all map to the canonical role `"dev_engineer"` and share one graph. Any lesson extracted from `dev_3`'s task is immediately available to `dev_7`'s next task. Cross-agent learning within a role is automatic.

All other roles (unit_tester, security_auditor, system_designer, etc.) have independent graphs.

### 8.6 Eviction

The graph is capped at 150 facts per role. When the limit is exceeded, facts are sorted by (confidence ascending, sprint ascending) and the oldest, least-confident facts are evicted. Their `fact` nodes are removed from the graph; `concept` nodes are **never** removed (they represent accumulated domain knowledge, and removing them would break multi-hop paths for other facts).

### 8.7 Memory growth over time

After Sprint 1, the `dev_engineer` graph might have 8 facts and 15 concept nodes. After Sprint 10, it might have 80 facts and 120 concept nodes with dense causal connections. `graph_summary()` shows the current state:

```
Graph: 47 concepts, 63 facts, 189 edges.
Top expertise: sqlalchemy(12), fastapi(9), async(8), pytest(7), jwt(6)
```

The `top_concepts()` output is the system's representation of what a role has become expert in.

---

## 9. Hamiltonian Swarm — Health Monitoring

### 9.1 The belief state

Every agent carries an `ActiveInferenceState` — a probability vector over three hypotheses:

```
healthy    prior = 0.80   (agent is on-role, outputs are coherent)
uncertain  prior = 0.15   (output is off-pattern, may need guidance)
confused   prior = 0.05   (something is wrong)
```

The prior is the baseline expectation for a functioning agent. The posterior is updated after every task.

### 9.2 Free Energy (the health signal)

After each task, the agent's output is evaluated. The LLM's **perplexity** (a measure of how surprised the model was by its own output — low perplexity = confident and coherent, high perplexity = uncertain and meandering) is converted to similarity scores for each hypothesis:

```python
confusion = log(perplexity) / log(30)  # normalized 0–1

similarities = {
    "healthy":   max(0, 1 - 2 × confusion),
    "uncertain": max(0, 1 - 2 × |confusion - 0.5|),
    "confused":  max(0, 2 × confusion - 1),
}
```

These similarities are used as likelihoods in a Bayesian update:

```
posterior ∝ prior × likelihood
```

The result is the new probability vector over {healthy, uncertain, confused}.

**Free Energy** is then computed as the KL divergence between the posterior and the prior:

```
F = KL(posterior || prior) = Σ posterior[i] × log(posterior[i] / prior[i])
```

This is directly from Karl Friston's Free Energy Principle (neuroscience). The interpretation: F = 0 means the agent's current state matches its expected role behavior exactly. F rising means the agent is behaving in an unexpected way — it is "surprised" by its own outputs relative to its role.

### 9.3 Anomaly detection

```python
def is_anomaly(self) -> bool:
    F_last = self._F_history[-1]
    if len(history) >= 5:
        z = (F_last - mean(history[:-1])) / std(history[:-1])
        return z > 2.0       # more than 2 std devs above own baseline
    else:
        return F_last > -log(prior_healthy / 2)   # cold-start fallback
```

The z-score uses the **agent's own history** as the reference distribution. An agent that consistently produces high-perplexity output (e.g., because it writes very long, verbose responses) will not be flagged — only a sudden deviation from its own baseline triggers an anomaly.

When an anomaly is detected on the first task of a sprint, a separate **fixer agent** is invoked with the original task, the anomalous output, and the F value. The fixer rewrites the output. If an anomaly occurs on later tasks, the health state is reset to the prior without invoking the fixer.

### 9.4 Quantum interference — collective calibration

At the end of sprint planning and after team execution, all agents' belief states are synchronized through mean-field quantum interference. This is the "Hamiltonian Swarm" mechanism.

**Why quantum amplitudes?** Probability vectors are non-negative and sum to 1. If you average probabilities directly, you get a simple mean. But quantum amplitudes (square roots of probabilities) encode phase information — the Born rule `p = |amplitude|²` preserves constructive and destructive interference, meaning agents with strongly aligned belief states reinforce each other, while agents with contradictory states partially cancel. This produces a more nuanced collective mean than simple probability averaging.

**The procedure:**

```python
# 1. Convert each agent's probabilities to quantum amplitudes (Born rule)
amplitudes[i] = sqrt(probs[i])

# 2. Mean-field average of all amplitudes
combined = mean(amplitudes)
combined = combined / ||combined||   # normalize

# 3. Convert back to probabilities
shared = combined²
shared = shared / sum(shared)

# 4. Blend each agent toward the shared state
probs_new[i] = (1 - alpha) × probs_old[i] + alpha × shared
```

With the default `alpha = 0.5`:
- Agents retain 50% of their individual state (identity preserved)
- 50% of each agent's state is pulled toward the swarm mean (collective recalibration)

**The practical effect:** If 7 agents are healthy and 1 is confused after a sprint, the confused agent's posterior shifts toward the healthy mean — its `confused` probability drops, `healthy` rises. On the next task, its prior is effectively recalibrated, making it less likely to be flagged as anomalous just because it had one bad task.

---

## 10. Stance System

Every agent tags its output with a **stance** — its self-reported quality philosophy for that task:

| Stance | Meaning |
|--------|---------|
| `MINIMAL` | Simplest possible implementation |
| `ROBUST` | Defensive, heavy error handling, retry logic |
| `SCALABLE` | Designed for growth, modular, distributed-ready |
| `PRAGMATIC` | Practical balance — default |

The stance is extracted from the output text (regex on `STANCE: MINIMAL/ROBUST/SCALABLE/PRAGMATIC`), converted to a 4-vector, and stored in the `WorkerOutput`. The engineering manager reads all stance vectors to understand if the sprint is trending toward over-engineering (too many SCALABLE) or under-engineering (too many MINIMAL).

Stance vectors are also used in `interfere_weighted()` — a weighted version of quantum interference that blends belief states using the stance probabilities as weights, giving more influence to agents that expressed higher confidence in their stance.

---

## 11. Manager Fix Loop

After the engineering test gate runs, if it fails the engineering manager enters a fix loop with up to `MANAGER_FIX_MAX_ROUNDS = 10` rounds.

In each round:
1. The manager reads the test failure output.
2. The manager looks at the test hints file (`design/agent_test_hints.md`) written by each engineer after completing their task — these are structured FEATURE/FIND/TEST checklists.
3. The manager calls tools to diagnose: `read_file`, `grep_codebase`, `run_shell`, and for GUI apps: `desktop_uia_list_elements`, `desktop_uia_click`, `desktop_uia_read_text`.
4. The manager writes fixes using `write_code_file`.
5. The test gate re-runs.

### GUI verification (OpenClaw-style UIA)

For desktop GUI applications, the manager uses Windows UI Automation (UIA) through an **OpenClaw-style** protocol:

```
(1) desktop_uia_list_elements('Window Title')   → LOCATE: enumerate all controls by name
(2) desktop_uia_click('Window Title', 'Button') → ACT: click by name, no pixel coordinates
(3) desktop_uia_read_text('Window Title')       → VERIFY: read result text without screenshot
```

This is faster and more reliable than pixel-coordinate clicking: UIA exposes the actual Win32 control tree, so the manager finds "ButtonControl named 'Submit'" directly rather than trying to locate a pixel position from a screenshot.

A `CUTripletTracker` enforces that every GUI test must include at least one complete `observe → act → verify` triplet before the integration pass is accepted. The valid triplet patterns are:

- `screenshot → (uia_click | mouse | keyboard) → (screenshot | uia_read_text)`
- `uia_list_elements → uia_click → uia_read_text` (the preferred UIA-only path)

---

## 12. Tool Registry

All agent tools are registered in `tool_registry.py` using the `@_register_tool` decorator. Every registered function is automatically exposed to the LLM as a callable tool via the Gemini function-calling API.

Tools are grouped by role. Each role has a whitelist of tool names; the LLM can only call tools on that whitelist.

### Discovery tools (read-only)
- `list_files()` — all project files
- `read_file(filename, offset, limit)` — paginated read with line numbers
- `grep_codebase(pattern, glob, context_lines)` — exact regex search, file:line: format
- `search_codebase(query)` — semantic vector search
- `recall_memory(query)` — Graph RAG spreading activation query
- `web_search(query, focus)` — DuckDuckGo (primary) / Brave (if API key set)

### Write tools (engineering only)
- `write_code_file(filename, content)` — write to `company_output/code/`
- `write_file_section(filename, section, content)` — overwrite one section of a shared file
- `write_test_file(filename, content)` — write to `company_output/code/tests/`
- `write_config_file(filename, content)` — write to `company_output/config/`
- `create_directory(path, root)` — mkdir -p
- `delete_file(path, root)` — remove a file
- `download_url(url, dest_path)` — fetch a binary asset

### Validation tools
- `validate_python(code)` — AST parse check
- `validate_json(content)` — JSON parse check
- `validate_yaml(content)` — YAML parse check

### Execution tools
- `run_shell(command)` — runs in `company_output/code/`
- `start_service(name, command)` — background daemon
- `stop_service(name)` — kill a daemon
- `http_request(method, url, body)` — HTTP call for API testing

### Cognitive tools
- `think(thought)` — no-op, logs reasoning (required before first write)

### Design tools
- `write_design_file(filename, content)` — write to `company_output/design/`
- `create_ascii_diagram(name, content)` — architecture diagram
- `generate_endpoint_table(...)` — API endpoint documentation
- `generate_er_diagram(...)` — database ER diagram
- `create_wireframe(...)` — UI wireframe
- `create_user_flow(...)` — UX flow diagram
- `create_style_guide(...)` — visual design spec

### Desktop control tools (manager only)
- `desktop_screenshot()` — full-screen screenshot with Gemini vision description
- `desktop_uia_list_elements(window)` — enumerate Win32 UIA control tree
- `desktop_uia_click(window, element)` — click a UIA control by name
- `desktop_uia_read_text(window)` — read all text from a UIA window
- `desktop_mouse(action, x, y)` — pixel-precise mouse control
- `desktop_keyboard(action, text, keys)` — type text or hotkeys

### Coordination tools
- `check_dashboard()` — read team dashboard (required first step)
- `check_messages()` — read direct messages
- `message_teammate(role, message)` — send a direct message
- `broadcast_message(message)` — team-wide announcement
- `request_contract_amendment(file, reason, change)` — propose a contract change

---

## 13. Configuration Reference

All configuration lives in `software_company/config.py` and can be overridden via environment variables or at runtime before calling `run_company()`.

| Variable | Default | Meaning |
|----------|---------|---------|
| `OUTPUT_DIR` | `company_output/` | Root for all generated artifacts |
| `GEMINI_MODEL` | `gemini-3.1-flash-preview` | LLM model for all agents |
| `MAX_SPRINTS` | `5` | Maximum sprints before forced stop |
| `MAX_TASKS_PER_AGENT` | `20` | Max tasks one engineer can claim per sprint |
| `MAX_WALL_CLOCK` | `600` | Seconds before engineering phase is force-stopped |
| `MAX_RETRIES_PER_TASK` | `10` | Retry budget per engineer per task |
| `TOKEN_BUDGET` | `5_000_000` | Hard stop for the entire run |
| `TEST_GATE_ENABLED` | `True` | Whether to run the test gate |
| `TEST_GATE_HOOKS` | `[]` | Custom test commands; if set, overrides auto-detect |
| `MANAGER_FIX_MAX_ROUNDS` | `10` | Fix loop rounds before giving up |
| `SELF_VERIFY_ENABLED` | `True` | Whether agents self-verify after writing |
| `AGILE_MODE` | `True` | Relaxed coordination (targeted messages, no rigid contracts) |
| `INTERFERENCE_ALPHA` | `0.5` | Blend weight for quantum interference |
| `COMPUTER_USE_REQUIRE_TRIPLET` | `True` | Require observe→act→verify for GUI pass |
| `AGENT_WEB_SEARCH_ENABLED` | `1` | Enable `web_search()` tool |
| `AGENT_WEB_SEARCH_MAX_RESULTS` | `5` | Results per web search call |
| `BRAVE_API_KEY` | — | Optional; enables Brave Search as fallback |
| `AGENT_DESKTOP_CONTROL_ENABLED` | `0` | Enable desktop mouse/keyboard tools |
| `MANAGER_GUI_DESKTOP_PROOF` | `1` | Require live GUI proof during fix loop |

---

## 14. File Layout

```
Quantum Swarm/
│
├── software_company/               Main package
│   ├── __init__.py                 Public API: run_company(), llm_call()
│   ├── _monolith.py                ReAct tool loop, LLM call infrastructure
│   ├── orchestration.py            Sprint lifecycle: kickoff, teams, retro
│   ├── engineering.py              Engineering team: task queue, worktrees, build_feature
│   ├── workers.py                  Non-engineering workers: run_worker()
│   ├── teams.py                    Team runner: manager + parallel workers
│   ├── planning.py                 Sprint planning: contract generation
│   ├── tool_registry.py            All agent tools (@_register_tool), role tool lists
│   ├── tools_impl.py               Tool implementations (pure Python, no LLM)
│   ├── long_term_memory.py         Graph RAG: NetworkX DiGraph per role
│   ├── rag.py                      Vector RAG: Gemini embeddings + numpy + pickle
│   ├── rolling_context.py          Short-term memory: sliding summary window
│   ├── contracts.py                InterfaceContractRegistry, FileContract, etc.
│   ├── dashboard.py                WorkDashboard: messaging + domain ownership
│   ├── computer_use.py             CUTripletTracker, GUI verification logic
│   ├── git_worktrees.py            GitWorktreeManager: per-agent isolated branches
│   ├── stance.py                   Stance parsing, weighted interference
│   ├── state.py                    ContextVar agent identity (thread-local)
│   ├── roles.py                    ROLES dict, ENG_WORKERS list, DoD per role
│   ├── config.py                   All configuration constants
│   ├── llm_client.py               Gemini client singleton, token accounting
│   ├── prompts_loaded.py           System prompts loaded from prompts/*.txt
│   └── team_schemas.py             Dataclasses: WorkerOutput, TeamResult, EngTask, etc.
│
├── hamiltonian_swarm/
│   └── quantum/
│       ├── active_inference.py     Belief state, Free Energy, quantum interference
│       ├── amplitude_amplification.py
│       ├── information_diffusion.py
│       ├── lindblad.py
│       ├── qpso.py                 Quantum Particle Swarm Optimization
│       ├── quantum_annealing.py
│       ├── quantum_belief.py
│       ├── quantum_error_correction.py
│       ├── quantum_rl.py
│       ├── quantum_state.py
│       ├── quantum_tunneling.py
│       ├── schrodinger.py
│       └── wave_function.py
│
├── prompts/
│   ├── worker_engineer.txt         System prompt for dev_1..dev_8
│   ├── worker_architect.txt        System prompt for arch team workers
│   ├── worker_designer.txt         System prompt for design team workers
│   ├── worker_qa.txt               System prompt for QA team workers
│   ├── manager_eng.txt             Engineering manager prompt
│   ├── manager_arch.txt            Architecture manager prompt
│   ├── manager_design.txt          Design manager prompt
│   ├── manager_qa.txt              QA manager prompt
│   ├── ceo.txt                     CEO orchestrator prompt
│   └── docker_delivery.txt         Docker requirements (injected when applicable)
│
├── tests/                          Test suite (252 tests, 0 external calls)
│
└── company_output/                 Generated at runtime
    ├── code/                       The software being built
    │   ├── .worktrees/             Per-agent isolated git branches
    │   │   ├── dev_1/
    │   │   └── ...
    │   └── tests/
    ├── memory/                     Graph RAG files — persist across all runs
    │   ├── dev_engineer.json
    │   ├── unit_tester.json
    │   └── ...
    ├── design/
    │   ├── architecture_spec.md
    │   ├── design_spec.md
    │   ├── project_structure.md
    │   └── agent_test_hints.md     FEATURE/FIND/TEST checklists from engineers
    ├── WORK_DASHBOARD.json         Team messaging and domain ownership
    ├── task_queue_state.json       Engineering task queue (crash recovery)
    ├── rag_index.pkl               Vector embeddings cache
    └── PROJECT_MANIFEST.md         File index for quick agent orientation
```

---

## How it all fits together — end-to-end flow

```
run_company(brief)
│
├── Sprint Kickoff
│     CEO opens meeting → 4 managers propose (parallel) →
│     managers refine after seeing each other (parallel) →
│     CEO synthesizes Sprint Goal
│
├── Sprint N
│   ├── Architecture team
│   │     3 workers (parallel) → manager merges → architecture_spec.md
│   │
│   ├── Design team
│   │     3 workers (parallel) → manager merges → design_spec.md
│   │
│   ├── Engineering team
│   │     run_sprint_planning() → FileContracts → EngTaskQueue
│   │     8 dev agents (parallel threads):
│   │       claim task → build_feature() → self-verify →
│   │       merge to main → RAG re-index → broadcast → claim next task
│   │     manager fix loop (up to 10 rounds) if test gate fails
│   │
│   └── QA team
│         3 workers (parallel) → manager merges → qa_findings.md
│
├── Sprint Retrospective
│     managers summarize → CEO decides SHIP or CONTINUE
│
└── repeat or return ProjectResult
```

After every `build_feature()` call:
- Health state updated (perplexity → Free Energy → anomaly detection)
- Rolling context updated (task + output → sliding summary)
- Background thread: Graph RAG extraction (lesson + entities + relations → graph)

After every sprint planning round:
- Quantum interference across all agents in the team
- Belief states blended toward swarm mean
```