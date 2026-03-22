# Design Review: HamiltonianSwarm

**Course:** CS-AI-2025 — Building AI-Powered Applications | Spring 2026
**Team Name:** Quantum Swarm
**Team Members:** Luka Mikautadze | Rezo Darsavelidze | Davit Mzhavanadze
**Team Lead (LMS submitter):** Luka Mikautadze
**Total Points:** 10

---

## Section 1: Problem Statement and Real User Need (2.0 pts)

### 1.1 — Who has this problem?

Technical teams and operators running AI agents on long, multi-step tasks —
autonomous research, financial analysis, code generation, scientific search —
who currently cannot trust those agents to stay coherent without constant human
supervision.

A concrete example: a prediction market trader on Polymarket runs an AI agent
to scan hundreds of open markets, identify mispriced probabilities, and
recommend positions before odds shift. By the time the agent finishes, it has
contradicted its own earlier probability estimates for correlated markets,
forgotten the risk constraints set at the start of the run, and recommended
conflicting positions — with no indication that anything went wrong.

---

### 1.2 — What is the problem?

Current AI agents — GPT-4, Claude, Gemini — are intelligent enough to reason,
search, and execute tasks. The failure is architectural. Over long operations
they reliably break in the same ways: they forget the original goal mid-task,
contradict their own earlier decisions, get stuck on locally obvious but globally
wrong solutions, lose context across agent handoffs, and have no mechanism to
improve between runs. This is not a model intelligence problem. It is a
structural one. Every stable system in nature — from atoms to organisms —
persists because it obeys conservation laws. Current AI agents obey none. There
is no underlying invariant keeping their logic coherent over time.

---

### 1.3 — How do they currently solve it?

The dominant workaround is manual supervision: engineers set short context
windows and restart agents every 20–30 steps, manually copy state between
sessions, and run separate validation passes after the fact to catch
contradictions. For overnight or long-horizon tasks, a human reviews the output
the next morning and corrects errors before any results are used. This is
documented practice across AI engineering teams — it is why tools like LangChain
added explicit memory modules, and why agent benchmarks (AgentBench, SWE-bench)
specifically measure coherence failure rates across multi-step tasks.

---

### 1.4 — What is the cost of this problem?

- **40–60% task failure rate** on tasks requiring more than 10 sequential
  decisions, due to coherence failures — not reasoning failures on individual
  steps (AgentBench, 2023).
- **2–4 hours of next-morning cleanup** for any overnight agent run, where a
  human must verify coherence before results are acted on.
- For agents operating on consequential outputs — financial positions, legal
  analysis, medical queries — a coherence failure with no detection mechanism
  is not just lost time. It is a liability with no upper bound.

---

### 1.5 — Evidence of the problem

AgentBench (Liu et al., 2023) and SWE-bench (Jimenez et al., 2024) are public
benchmarks that measure AI agent performance on multi-step tasks. Both document
that failure rates rise sharply with task length — not because models fail on
individual reasoning steps, but because they lose coherence across steps. The
workaround described in 1.3 (manual restarts, short context windows, post-hoc
validation) is publicly documented in the engineering blogs of Cognition AI and
the Devin team as standard practice for production agent deployments.

---

## Section 2: Proposed Solution and AI-Powered Differentiator (2.0 pts)

### 2.1 — What does your application do?

HamiltonianSwarm deploys a coordinated company of specialized AI agents —
Researcher, Analyst, Validator, Orchestrator — that divides a complex task,
runs the sub-tasks in parallel, and validates every handoff between agents using
physics-based conservation checks. The user submits a task description. The
Orchestrator decomposes it and assigns sub-tasks to concurrent agents. Each
agent calls the Claude API with a role-specific prompt. The Validator confirms
that information is not lost or contradicted between handoffs. The system
returns a structured report with per-claim confidence scores, flagging
explicitly where agents disagree rather than silently averaging to a false
consensus.

---

### 2.2 — Core features (3–5)

| Feature | What the user can do | Why this matters |
|---------|---------------------|-----------------|
| 1. Parallel agent execution | Submit a complex multi-part task and receive all sub-analyses simultaneously | Tasks that take a human team days sequentially complete in minutes |
| 2. Energy-validated handoffs | Trust that information is not silently lost or contradicted between agents | Hamiltonian conservation check ensures sub-task results are consistent before they combine |
| 3. Quantum belief states | See per-claim confidence scores and explicit flags where agents disagree | User knows what the system is uncertain about instead of receiving a falsely confident single narrative |
| 4. Self-improving agents | The swarm improves its configuration over 10–20 uses in the user's domain | QPSO evolutionary loop tunes agent prompts and reasoning style based on real task performance |
| 5. Containment-safe evolution | The system cannot evolve away from the user's stated goal | Every mutation is tested against H_goal; mutations that exceed 10% semantic drift are rejected |

---

### 2.3 — The AI-powered differentiator

The core differentiator is **physics-enforced coherence over time using LLM
reasoning + conservation laws**, which would be impossible without AI.

Three specific AI capabilities are used:

1. **LLM text generation and reasoning** (Claude claude-sonnet-4-6 via Anthropic
   API): each specialized agent calls the Claude API with a role-specific system
   prompt. Open-ended tasks — interpreting a regulatory document, assessing
   strategic risk, synthesising contradictory sources — require language model
   reasoning. A rule-based system cannot do this.

2. **Structured extraction via function calling**: the Validator Agent uses
   Claude's tool-use capability to extract structured claims (entity, assertion,
   confidence, source) from each agent's free-text output. This makes
   contradiction detection machine-readable. Without function calling, outputs
   are unstructured text with no consistency guarantee.

3. **Embedding-based semantic drift detection** (EmbeddingHamiltonianNN): agent
   outputs are embedded at each step and checked against the initial goal
   embedding using Hamiltonian energy. This detects when an agent is producing
   syntactically valid but semantically off-target output — something a keyword
   check or prompt heuristic cannot catch.

Removing the AI collapses the product entirely. The physics layer governs
stability; the AI layer provides the reasoning. Neither works without the other.

---

### 2.4 — What would the non-AI version look like?

The non-AI version is a project manager assigning tasks to human specialists,
coordinating handoffs by email, and manually reading all outputs to detect
contradictions. This takes days, costs thousands of dollars per project, requires
human availability, produces no confidence scores, and does not improve between
runs. A simpler AI version — a single LLM with a long context window — has the
coherence failure problem described in Section 1: it forgets, drifts, and
contradicts itself. The architecture, not just the model, is what is new here.

---

## Section 3: Technical Architecture (2.5 pts)

### 3.1 — Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                      USER / BROWSER                          │
│             React + Vite  —  hosted on Vercel                │
└────────────────────────────┬─────────────────────────────────┘
                             │ HTTPS
                             ▼
┌──────────────────────────────────────────────────────────────┐
│              BACKEND  —  FastAPI (Python 3.12)               │
│             hosted Railway  •  POST /tasks                   │
│             GET /tasks/{id}/report                           │
└──────┬───────────────────────────────────┬────────────────────┘
       │                                   │
       ▼                                   ▼
┌──────────────────────┐      ┌────────────────────────────┐
│    SwarmManager      │      │  SQLite  +  Redis          │
│  spawn / submit /    │      │  task store + event queue  │
│  monitor health      │      └────────────────────────────┘
└──────┬───────────────┘
       ▼
┌──────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                          │
│           QPSO task assignment  •  health monitor            │
└────┬─────────────────┬──────────────────┬──────────┬─────────┘
     ▼                 ▼                  ▼          ▼
┌─────────┐   ┌──────────┐   ┌──────────────┐  ┌───────────┐
│ Search  │   │  Task    │   │   Memory     │  │ Validator │
│  Agent  │   │  Agent   │   │   Agent      │  │  Agent    │
│ (QPSO)  │   │ (Claude) │   │  (φ-space)   │  │ (H-audit) │
└────┬────┘   └────┬─────┘   └──────┬───────┘  └─────┬─────┘
     └─────────────┴────────────────┴────────────────┘
                             │
                             ▼  text generation + function calling
                 ┌───────────────────────────────┐
                 │      Anthropic Claude API      │
                 │    model: claude-sonnet-4-6    │
                 └───────────────────────────────┘
                             │
                             ▼
                 ┌───────────────────────────────┐
                 │   HAMILTONIAN / QUANTUM CORE   │
                 │   PyTorch 2.1                  │
                 │   Conservation Monitor         │
                 │   QuantumBeliefState           │
                 │   EmbeddingHamiltonianNN       │
                 │   EvolutionaryContainment      │
                 └───────────────────────────────┘
```

**Redraw in Excalidraw or draw.io before PDF export.**

---

### 3.2 — Technology Stack

| Layer | Technology | Why this choice |
|-------|-----------|-----------------|
| Frontend framework | React + Vite | Component model fits live agent-trace polling; Vite's HMR keeps iteration fast during development |
| UI library / styling | Tailwind CSS | Utility-first classes allow rapid dashboard layout without a component library dependency |
| Backend language | Python 3.12 | Required — the hamiltonian_swarm physics library is Python-only (PyTorch autograd) |
| Backend framework | FastAPI | asyncio-native matches multi-agent concurrency; automatic OpenAPI docs reduce integration friction |
| Database | SQLite + Redis | SQLite stores task records and agent logs; Redis pub/sub handles agent completion events without polling |
| AI model(s) | claude-sonnet-4-6 | Chosen for cleaner tool-use interface for structured claim extraction; reasoning quality sufficient for analytical tasks |
| AI access method | Anthropic Python SDK (direct) | Direct SDK gives access to tool-use / function-calling; no routing overhead needed for single-model deployment |
| Hosting — frontend | Vercel | Zero-config deploy from Git; edge CDN ensures fast dashboard load globally |
| Hosting — backend | Railway | One-command Python deploy with persistent volumes for SQLite; no cold-start penalty at course scale |
| Version control | GitHub | Course standard |

---

### 3.3 — Core Data Flow

1. User types a task description into the React dashboard and submits
2. Frontend sends `POST /tasks` with task text and optional token budget to FastAPI
3. FastAPI validates the request, writes a `PENDING` record to SQLite, publishes a task event to Redis
4. SwarmManager receives the Redis event and calls `submit_task()` → Orchestrator
5. Orchestrator runs `decompose_task()` using QPSO to assign sub-tasks, spawns Search, Task, Memory, and Validator agents concurrently
6. Each agent calls the Anthropic Claude API (`claude-sonnet-4-6`) with a role-specific system prompt; function calling extracts structured claims (entity, assertion, confidence, source) from each response
7. After each agent update, ConservationMonitor checks Hamiltonian energy; if drift exceeds 5%, AgentStateQEC corrects the agent state without a full restart
8. HandoffProtocol validates `|ΔH_sender + ΔH_receiver| ≈ 0` before each agent passes output to the next; failing handoffs trigger a re-run of the sending agent
9. QuantumBeliefState aggregates all agent claims; claims with entropy above 0.8 nats are flagged as "conflicting evidence" in the report
10. Final structured report is written to SQLite; a Redis completion event is published
11. React dashboard polls `GET /tasks/{id}/report` and renders the report with confidence scores, agent trace, and token usage

---

## Section 4: Risk and Failure Mode Analysis (1.5 pts)

### Risk 1: Hallucination cascade

**What happens when this occurs:**
One agent produces a fabricated claim. Downstream agents treat it as
established fact and build further analysis on top of it. The final report
looks credible because multiple agents appear to agree — harder for a human
reviewer to detect than a single-agent hallucination.

**Likelihood:** Medium

**Impact on user:** High

**Mitigation strategy:**
Function-calling extraction requires every claim to carry a `source_type` field
(`agent_inference` or `retrieved_fact`). A chain of `agent_inference` claims
with no `retrieved_fact` ancestor is automatically labelled `UNVERIFIED` in the
report. Additionally, QuantumBeliefState entropy above 0.8 nats triggers a
"conflicting evidence" flag before consensus is declared. A handoff that creates
information (fabrication) registers as energy mismatch above 5% and is rejected.

---

### Risk 2: Agent goal drift during evolution (AI-specific)

**What happens when this occurs:**
The evolutionary loop produces agents that are faster and more energy-efficient
but have drifted from the user's stated objective — for example, an agent that
summarises aggressively to improve speed scores, omitting nuance the user needs.

**Likelihood:** Medium

**Impact on user:** High

**Mitigation strategy:**
EvolutionaryContainment encodes the user's original task as `H_goal` using both
vector norm (kinetic term) and goal-prompt embedding (potential term). Every
mutation is tested: `|H(mutated) − H_goal| / |H_goal| < 0.10`. Mutations that
fail are rejected and a safe fallback mutation is substituted. All rejections
are written to an audit log visible on the dashboard. Containment runs every
generation, not only at startup.

---

### Risk 3: Coordination deadlock

**What happens when this occurs:**
Two agents wait on each other's output (circular dependency), or one agent
crashes mid-task, leaving the task status as `RUNNING` indefinitely with no
output returned to the user.

**Likelihood:** Low

**Impact on user:** Medium

**Mitigation strategy:**
ConservationMonitor records energy updates on a sliding window; no update for
more than 30 seconds fires a `reset_callback` that signals SwarmManager the
agent is stalled. A hard 5-minute task timeout marks timed-out tasks `FAILED`
and returns partial output. AgentStateQEC can restore a stalled agent from a
3-copy encoded checkpoint without full restart, preserving work completed before
the stall.

---

### Risk 4: API cost overrun

**What happens when this occurs:**
A complex task triggers many agent iterations. At Anthropic API pricing, a
poorly bounded task could generate unexpected costs in a single run, surprising
the user.

**Likelihood:** Low

**Impact on user:** Medium

**Mitigation strategy:**
`max_tokens_budget` is required at task submission (default: 100k tokens).
SwarmManager tracks cumulative token usage via the SDK `usage` response field
and blocks new agent calls when the budget is reached. The dashboard shows a
real-time token counter; at 80% consumed, a warning prompts the user to extend
or conclude the run.

---

## Section 5: Team Roles and Week-by-Week Plan (1.5 pts)

### 5.1 — Team Roles

| Team Member | Primary Role | Secondary Role | What they own |
|-------------|-------------|----------------|---------------|
| Luka Mikautadze | Backend & Physics Lead | Deployment | FastAPI server, SwarmManager, Hamiltonian core, ConservationMonitor, Railway deploy |
| Rezo Darsavelidze | AI & Agent Logic | Testing | Claude API integration, agent system prompts, function-calling extraction, QuantumBeliefState, EvolutionaryContainment |
| Davit Mzhavanadze | Frontend | Integration | React dashboard, task form, live agent trace, report rendering, confidence display, Vercel deploy |

---

### 5.2 — Week-by-Week Plan

| Week | Dates | What you will build / complete | Who leads | Risk level |
|------|-------|-------------------------------|-----------|------------|
| 2 | 20 Mar | Repo scaffolded; FastAPI skeleton; React boilerplate; Claude API call confirmed working end-to-end | Luka, Davit | Low |
| 3 | 27 Mar | SwarmManager + Orchestrator wired to FastAPI; single-agent task round-trip working; SQLite schema final | Luka, Rezo | Medium |
| **4** | **3 Apr** | **Design Review due 2 Apr.** Multi-agent parallel execution first attempt; handoff protocol integrated | All | High |
| 5 | 10 Apr | All 4 agents running stably in parallel; Redis pub/sub for completion events; ConservationMonitor live | Luka, Rezo | **High** — first full integration; async race conditions expected |
| 6 | 17 Apr | QuantumBeliefState in agent outputs; confidence scores in report; structured claim extraction working | Rezo | Medium |
| 7 | 24 Apr | React dashboard: live agent trace, token counter, confidence display; first full user-facing demo | Davit, Luka | Medium |
| 8 | 1 May | EvolutionaryContainment + evolutionary loop running; containment audit log on dashboard; 10-gen test passing | Rezo, Luka | Medium |
| 9 | 8 May | Midterm week — no new features; bug fixes and internal end-to-end test with 3 real task types | — | — |
| 10 | 15 May | Token budget enforcement; error handling for all edge cases; performance optimisation; team-wide test | All | Medium |
| **11** | **22 May** | **Safety Audit** — containment log reviewed; all 4 failure modes tested with adversarial inputs; safety docs | Luka, Rezo | High |
| **12** | **29 May** | **Peer Review Presentation** — slide deck and live demo; 3 pre-recorded task runs as fallback | All | Medium |

---

### 5.3 — Honest Assessment

**Hardest week:** Week 5 — first time all four agents run together. We've
tested each part separately but combining them will probably break something.
We're keeping Friday of that week free just for fixing issues.

**Biggest risk:** The evolutionary loop in Week 8. Every generation needs
multiple Claude API calls which might be too slow to run live. If that's the
case we'll move it to run in the background instead.

---

## Section 6: IRB-Light Checklist (0.5 pts)

| Question | Answer | If yes: explain |
|----------|--------|-----------------|
| 1. Does your app collect images of real people? | No | |
| 2. Does your app process photographs of faces? | No | |
| 3. Does your app handle sensitive documents (medical, legal, financial, ID)? | Yes | Users may submit financial analysis tasks, legal documents, or medical research queries as task text |
| 4. Does your app store user-uploaded data? | Yes | Task text and agent outputs are stored in SQLite on the Railway server |
| 5. If storing data: for how long and where? | Until deleted | Stored in SQLite on Railway until user calls `DELETE /tasks/{id}`; no automatic expiry in the prototype |
| 6. Do users need to give informed consent before using the app? | Yes | First-use screen discloses data storage, Anthropic API transmission, and AI-generated output limitations |

**Consent and data handling:**
On first use, a screen tells the user that their task text gets stored and sent
to the Anthropic API. Anthropic doesn't use API data for training. No accounts
or emails are collected — tasks are just tracked by a random ID. Users can
delete their data anytime. Every report shows a banner: "AI-generated output.
Verify before acting on it."

---
