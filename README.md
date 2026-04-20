# Quantum Swarm — AI Software Company

An autonomous multi-agent system that builds software end-to-end. You give it a product brief. It produces a working, tested codebase.

```bash
python -m software_company "Build a REST API for a todo app with SQLite"
python -m software_company "Brief" --sprints 3
```

Requires `GEMINI_API_KEY` in the environment. Outputs land in `company_output/`.

---

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

All `dev_1`..`dev_8` share one `dev_engineer` graph. Knowledge found by any engineer instantly benefits all of them. Each other role (QA, architect, designer) has its own independent graph.

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

## Running tests

```bash
python -m pytest tests/ -v

# Manager smoke test — live LLM + desktop tools
RUN_MANAGER_STAGE_SMOKE=1 AGENT_DESKTOP_CONTROL_ENABLED=1 python run_manager_stage_smoke.py
```
