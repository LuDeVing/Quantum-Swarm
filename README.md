# Quantum Swarm — AI Software Company

An autonomous multi-agent system that builds software end-to-end. You give it a product brief. It produces a working, tested codebase.

```bash
python -m software_company "Build a REST API for a todo app with SQLite"
python -m software_company "Brief" --sprints 3
```

Requires `GEMINI_API_KEY` in the environment. Outputs land in `company_output/`.

---

## Demo Video

https://github.com/user-attachments/assets/8be92bd8-9a70-46cb-9c51-01295018720b

## How it works

The system runs like a real company, broken into sprints. Each sprint has four teams that run in sequence:

```
CEO  →  plans the sprint goal
  │
  ├── Architecture team   defines structure, APIs, database schemas
  ├── Design team         UX flows, component specs, visual style
  ├── Engineering team    writes the actual code (8 parallel agents)
  └── QA team             tests, security checks, validation
```

Each team has a **manager** (coordinates, merges work) and **specialist workers** (do the deep work). After every sprint the CEO reviews output and decides whether to continue.

---

## The agent loop

Every agent runs the same cycle:

1. **THINK** — mandatory architecture analysis before writing anything; may call `web_search()` and `recall_memory()` here
2. **DISCOVER** — read existing code, grep the codebase, check past lessons
3. **WRITE** — produce complete, runnable code (no stubs)
4. **VALIDATE** — compile / lint / run tests
5. **FIX** — iterate if validation fails

Engineering agents get isolated git worktrees so all 8 can write in parallel without conflicts. Branches merge into the shared codebase when done.

---

## Memory — three layers

| Layer | Lives | What it stores |
|-------|-------|----------------|
| **Rolling context** | Current sprint only | Last 3 tasks + LLM-summarized history |
| **Vector RAG** | Across sprints (disk) | All written code, searchable by semantic similarity |
| **Graph RAG** | Permanent, grows forever | Domain lessons, causal patterns, expertise |

### Graph RAG — how agents get better over time

After every task, a background LLM call extracts 1–3 concrete lessons and wires them into a **knowledge graph** (NetworkX DiGraph):

```
concept:sqlalchemy ──[appears_in]──► fact:"use async context managers for sessions"
concept:missing_context_manager ──[causes]──► concept:connection_leak
concept:async_context_manager  ──[fixes]──►  concept:connection_leak
```

**Nodes** are concepts (libraries, patterns, error types). **Edges** are causal or structural relationships. **Facts** are lessons attached to relevant concept nodes.

When a new task arrives, retrieval uses **spreading activation** (the same mechanism HippoRAG borrows from neuroscience):

1. Find concept nodes whose names overlap with the query — these are the "seeds"
2. Spread activation outward through edges for 2 hops, decaying by 0.7× per hop
3. Collect fact nodes with the highest accumulated activation
4. Return the top 5 as bullets injected into the agent's prompt

This means querying "database connection pooling" will surface lessons about SQLAlchemy connection leaks — even though those words don't appear in the query — because the graph path `pooling → connection_leak → sqlalchemy` connects them.

All `dev_1`...`dev_8` share one `dev_engineer` graph. Knowledge found by any engineer instantly benefits all of them. Each other role (QA, architect, designer) has its own independent graph.

Memory files live at `company_output/memory/{role}.json` and persist across every run.

---

## Hamiltonian Swarm — agent health monitoring

Every agent carries a **belief state**: a probability vector over three hypotheses about how well it is performing.

| Hypothesis | Default prior |
|-----------|--------------|
| `healthy` | 80% |
| `uncertain` | 15% |
| `confused` | 5% |

After each task, the output is compared against prototype vectors via cosine similarity. This updates the belief via **Bayes' rule** (posterior ∝ prior × likelihood). The result is a single number called **Free Energy (F)**:

- **F ≈ 0** → agent is on-role, behaving as expected
- **F rising** → agent is drifting, output diverging from its role

This is the **Free Energy Principle** from theoretical neuroscience — the brain minimizes the gap between what it predicts and what it observes. Here, agents minimize the gap between expected role behaviour and actual output.

Anomaly detection uses a **z-score over the agent's own history** (not a fixed global threshold), so it adapts to each agent's individual baseline rather than penalizing consistently expressive agents.

### Quantum interference — collective recalibration

At the end of each sprint, all agents' belief states are synchronized through **mean-field quantum interference**:

1. Convert each agent's probability vector to quantum amplitudes: `a = sqrt(p)` (Born rule)
2. Average all agents' amplitudes together (mean field)
3. Normalize and convert back to probabilities: `p = a²`
4. Blend each agent's individual state with the shared result at α = 0.5:
   `p_new = 0.5 × p_individual + 0.5 × p_shared`

The practical effect: if most agents are healthy but one is confused, interference pulls the confused agent toward the healthy mean — a soft recalibration that preserves individual identity while correcting outliers.

The word *quantum* refers to using the mathematical formalism of quantum mechanics (amplitudes, Born rule, superposition) as a coordination primitive — not literal quantum hardware.

---

## Tools available to every agent

| Tool | What it does |
|------|-------------|
| `think(thought)` | Log architecture analysis before writing — mandatory |
| `recall_memory(query)` | Spreading-activation search of the Graph RAG |
| `grep_codebase(pattern, glob)` | Exact regex search across project files |
| `search_codebase(query)` | Semantic / vector search across project files |
| `read_file(filename, offset, limit)` | Paginated read with line numbers |
| `web_search(query)` | Search the web for docs and best practices |
| `write_code_file(filename, content)` | The only way to ship code |
| `run_shell(command)` | Run tests, compilers, build tools |
| `validate_python / json / yaml` | Syntax checking |
| `message_teammate(role, message)` | Coordinate with another agent |

---

## Key file layout

```
software_company/
  orchestration.py      sprint runner — CEO, teams, retro
  engineering.py        engineering team: task queue, parallel builds, test gate
  workers.py            non-engineering workers (arch, design, QA)
  long_term_memory.py   Graph RAG per role (NetworkX + JSON persistence)
  rag.py                vector RAG for codebase search (Gemini embeddings + pickle)
  tool_registry.py      all agent tools defined and registered here
  rolling_context.py    in-sprint rolling summary

hamiltonian_swarm/quantum/
  active_inference.py   belief state, free energy, quantum interference
  ...                   other physics-inspired modules

prompts/
  worker_engineer.txt   system prompt for engineering agents
  worker_architect.txt  system prompt for architecture agents
  worker_designer.txt   system prompt for design agents
  worker_qa.txt         system prompt for QA agents

company_output/         all generated artifacts (created at runtime)
  code/                 the software being built
  memory/               Graph RAG files — one per role, persist forever
  design/               architecture spec, design spec, QA findings
  rag_index.pkl         vector search index
```

---

## Agent Architecture

### Pattern: Supervisor/Worker with ReAct agents

Quantum Swarm uses a **Supervisor/Worker** pattern: manager agents plan, assign, and review work while specialist workers execute bounded tasks. Each manager and worker uses a **ReAct** inner loop: it reasons (THINK) before each action, then acts with a registered tool, then observes the result and repeats. This keeps coordination centralized while forcing grounded decisions before file writes, shell commands, and other side-effecting actions.

```
THINK → tool_call → observe → THINK → tool_call → ... → write_code_file
```

The loop runs for up to `MANAGER_FIX_MAX_ROUNDS` (default 10) before the manager escalates.

### AgentState — per-agent runtime snapshot

Every agent's live state is tracked in an `AgentState` dataclass (defined in `software_company/team_schemas.py`):

```python
@dataclass
class AgentState:
    agent_id: str           # e.g. "dev_3", "qa_manager"
    role: str               # matches ROLES dict key
    sprint: int             # 1-based sprint number
    task_file: str          # file the agent is currently writing
    # Hamiltonian health
    belief_healthy: float   # posterior P(healthy)  — starts at 0.80
    belief_uncertain: float # posterior P(uncertain) — starts at 0.15
    belief_confused: float  # posterior P(confused)  — starts at 0.05
    free_energy: float      # KL divergence from expected role behaviour
    anomaly_detected: bool  # True when z-score > 2Ïƒ over agent's own history
    # Token accounting
    call_count: int
    tokens_in: int
    tokens_out: int
    cache_read_tokens: int
    token_budget_remaining: int  # hard stop at 5 M tokens
    # Quality self-report
    last_stance: str             # MINIMAL | ROBUST | SCALABLE | PRAGMATIC
    consecutive_fallbacks: int   # LLM errors in a row; triggers circuit-break at 3
```

### Irreversible action map

These tools require the agent to have completed a THINK step immediately before calling them. The manager fix loop will not retry past 10 rounds when any of these fails.

| Tool | Why it is irreversible | Checkpoint / guard |
|------|------------------------|--------------------|
| `write_code_file` | Overwrites a file on disk; prior content is lost unless git-tracked | Required `THINK`; file ownership tracked in `WORK_DASHBOARD.json`; test gate runs after integration |
| `run_shell` | Executes arbitrary shell commands; side-effects cannot be rolled back | Required `THINK`; command timeout in `tools_impl.py`; shell output is captured for review |
| `git_merge` | Merges a branch into the shared codebase; may alter history | Manager-only merge path; branch/worktree isolation before integration |
| `message_teammate` | Broadcasts to another agent; cannot be unsent | Required `THINK`; messages are append-only in dashboard state |
| `delete_project` | Removes a project directory and all generated artifacts permanently | API owner-id guard; bearer token validation; route-level audit log |

---

## Model Selection Decisions

| Call Location | Current Model | Reason | Alternative Considered |
|---|---|---|---|
| `software_company/llm_client.py::llm_call` | `GEMINI_MODEL`, default `gemini-3.1-flash-preview` | Main coding, planning, manager review, and fallback-summary paths need one consistent model behind shared timeout/backoff logging | Stronger Gemini model for quality, rejected for capstone cost control |
| `api_server.py::_general_chat_reply` | `GEMINI_MODEL` through `llm_call()` | Keeps frontend chat under the same timeout, exponential backoff, fallback logging, and sanitized-error policy as all other content-generation calls | Separate direct `gemini-2.0-flash` call, rejected because direct calls bypass resilience controls |
| `software_company/agent_loop.py::_run_with_tools` | `GEMINI_MODEL` through `generate_content_with_resilience()` | Tool-using ReAct turns need Gemini function-calling while still enforcing the shared timeout/retry policy | Direct SDK `models.generate_content`, rejected because it skipped the shared resilience wrapper |
| Browser and desktop vision helpers | `DESKTOP_VISION_MODEL` override, falling back to `GEMINI_MODEL` | Screenshot/click localization may need a stronger vision-capable model depending on local UI conditions | Fixed hard-coded vision model, rejected because grading machines and displays vary |
| RAG embeddings | `_RAG_EMBED_MODEL` | Embedding calls are not natural-language generation and are isolated to codebase retrieval | Reusing the chat model, rejected because generation models are not optimized for embeddings |

---

## Safety Audit Evidence

The Lab 8 capstone evidence is committed under [docs/safety-audit.md](docs/safety-audit.md), with the data inventory split out into [docs/data-map.md](docs/data-map.md). The audit can be re-run locally with:

```bash
py eval/run_eval.py
py -m pytest tests/test_safety_audit_evidence.py tests/test_cross_user_isolation.py -q
```

Current local verification:

| Rubric Area | Evidence | Status |
|---|---|---|
| Episode log quality | `logs/episodes.jsonl` has 136 LLM-call entries with `cache_read_tokens`, `latency_ms`, `fallback_triggered`, and the full Lab 8 schema | Pass |
| Agent architecture documentation | This README has the Supervisor/Worker pattern, `AgentState` dataclass fields, irreversible action map, checkpoints/guards, and model-selection table | Pass |
| MCP/API server security | `api_server.py` implements bearer-token auth, Pydantic validation, structured JSONL audit logging, and sanitized internal-error responses | Pass |
| Resilience patterns | `software_company/llm_client.py` wraps all Gemini content-generation calls with `_LLM_TIMEOUT`, `_LLM_RETRIES = 3`, and exponential backoff | Pass |
| Golden test set and evaluation | `eval/golden_test_set.json`, `eval/run_eval.py`, and `eval/results/results_2026-05-21.json` show 10/10 passing | Pass |
| Data governance | `tests/test_cross_user_isolation.py`, `docs/data-map.md`, `.gitignore`, and log PII checks cover owner isolation, data retention, PII-free logs, and `.env` exclusion | Pass |

The most recent full local test run passed: `383 passed, 12 skipped`.

---

## Running tests

```bash
python -m pytest tests/ -v

# Manager smoke test — live LLM + desktop tools
RUN_MANAGER_STAGE_SMOKE=1 AGENT_DESKTOP_CONTROL_ENABLED=1 python run_manager_stage_smoke.py
```
