# Design Review — HamiltonianSwarm: An AI Agent Company

**Course:** CS-AI-2025 — Building AI-Powered Applications | Spring 2026
**Team Lead:** Luka Mikautadze
**Team Members:** Luka Mikautadze, Rezo Darsavelidze, davit mzhavanadze
**Submission Date:** 3/22/2026

---

## Section 1: Problem Statement and Real User Need

**User:** Operations managers and founders at SMBs (5–50 employees) in
knowledge-intensive industries — legal, finance, market research, technical due
diligence — who need coordinated multi-step analysis but cannot afford specialist
teams for each project.

*Example:* A 12-person fintech startup needs a competitive landscape analysis, a
regulatory compliance review, and a technical risk assessment before a Series A
pitch in 48 hours. That normally requires three specialists working in sequence,
which the company cannot staff or schedule on short notice.

**The problem:** Complex analytical work requires a researcher, an analyst, a
validator, and a coordinator working in sequence. SMBs outsource these roles
individually on Upwork/Fiverr and coordinate handoffs by email — which is slow,
error-prone, and expensive.

**Evidence:**
- Upwork (2023): 60% of SMB clients manage 3+ freelancers per project, averaging
  4.2 coordination touchpoints per handoff.
- McKinsey (2023): knowledge workers spend 28% of their workday on coordination,
  not work — costing $800–1,200 in wasted time per 4-person project.
- Deloitte (2024): SMBs in knowledge-intensive sectors run ~18 analytical projects
  per year at $2,400 each — ~$43,200/year.

**Quantified cost:**

| Dimension | Current state |
|---|---|
| Cost per outsourced project (4-person team) | $1,600–$3,200 |
| Coordination overhead per project | ~$306 wasted |
| Average projects/year per SMB | 18 |
| Annual spend | ~$43,200 |
| Median turnaround | 3.1 business days |
| Time-sensitive decisions missed | ~1 in 4 projects |

---

## Section 2: Proposed Solution and AI-Powered Differentiator

**HamiltonianSwarm** is an AI agent company: a system of specialized AI agents
— Researcher, Analyst, Validator, Orchestrator — that runs in parallel, validates
its own coordination, and delivers a multi-perspective report in minutes.

The user submits a task. The Orchestrator decomposes it, assigns sub-tasks to
agents running concurrently, validates every handoff for information consistency,
and returns a structured report with per-claim confidence scores.

**What companies can actually use this for:**

- *Legal firm:* Feed in a 200-page contract. The Search Agent finds relevant case
  law, the Task Agent identifies risk clauses, the Validator flags contradictions
  between jurisdiction sections, and the Memory Agent tracks defined terms across
  the whole document. Output: a risk-ranked clause summary in under 10 minutes.

- *Startup pre-fundraise:* Submit "Analyse the EU payments regulatory landscape
  for a new entrant." Agents run competitor mapping, regulatory barrier extraction,
  and technical risk assessment in parallel. A human analyst team takes 3 days;
  the swarm delivers in minutes.

- *Financial analyst:* "Compare Q3 earnings for the top 5 US banks and flag
  outliers." Agents pull filings, extract key metrics, cross-validate numbers,
  and surface discrepancies — in one run, not one analyst reading five PDFs.

- *Medical researcher:* "Summarise clinical trials for Drug X published 2020–2025
  and identify conflicting efficacy results." The swarm searches, extracts, and
  explicitly surfaces trials where agents disagree — rather than averaging them
  into a false consensus.

**Core features:**

1. **Parallel agent execution** — Search, Task, Memory, and Validator agents run
   concurrently. Tasks that take a human team 3 days sequentially finish in
   minutes. *Benefit: same-day turnaround.*

2. **Energy-validated handoffs** — When an agent passes work to the next, the
   Validator checks Hamiltonian energy conservation: information content before
   and after the handoff must match within 5%. If it doesn't, the handoff is
   rejected and the agent reruns the sub-task. *Benefit: no silent information
   loss or contradiction between sub-tasks.*

3. **Quantum belief states for uncertainty** — Each agent holds competing
   hypotheses in superposition and reports probability-weighted confidence.
   Claims where agents disagree are surfaced explicitly, not silently averaged.
   *Benefit: the user sees what the system is uncertain about.*

4. **Self-improving agents** — A background evolutionary loop (QPSO mutation +
   Pareto fitness) improves agent configurations — prompts, reasoning style,
   search depth — based on task performance. *Benefit: the swarm gets better at
   the user's specific domain over 10–20 uses.*

5. **Containment-safe evolution** — Evolution cannot change the semantic goal.
   Every mutation is tested: `|H(mutated) − H_goal| / |H_goal| < 10%`. Mutations
   that fail are rejected. *Benefit: the system cannot evolve away from what the
   user asked for.*

**Why quantum functions specifically:**
Classical optimization gets stuck in local optima and degrades under noise.
Quantum-inspired methods follow laws of nature that have been proven over billions
of years — energy conservation, wave-particle duality, quantum tunneling — which
are mathematically optimal for search and evolution in high-dimensional spaces.

Concretely:
- **QPSO** uses the quantum delta potential to let particles tunnel through
  barriers that trap classical PSO, producing better global search with fewer
  function evaluations.
- **Hamiltonian mechanics** conserves energy exactly, giving us a provable
  invariant to detect when an agent has drifted — something a plain "check the
  output" heuristic cannot provide.
- **Quantum belief states** represent uncertainty natively (superposition of
  hypotheses) rather than forcing a premature binary decision, which is how
  genuine experts actually reason before they have enough evidence.
- **Evolutionary containment via H conservation** means the system cannot improve
  its way out of your goal — the same reason a physical system cannot spontaneously
  violate conservation laws.

**AI capabilities used:**
- **Claude claude-sonnet-4-6** (LLM reasoning): each agent calls the Claude API
  with a role-specific prompt. Open-ended language tasks — interpreting a
  regulatory document, assessing strategic risk — require LLM reasoning;
  deterministic rules cannot do this.
- **Function calling / tool use**: the Validator extracts structured claims
  (entity, assertion, confidence, source) from free-text agent outputs, enabling
  machine-readable contradiction detection.
- **EmbeddingHamiltonianNN**: embeds agent outputs and checks energy drift from
  the goal embedding, detecting semantic drift that is syntactically valid but
  off-target.

**Non-AI comparison:**

| | Human team (non-AI) | HamiltonianSwarm |
|---|---|---|
| Turnaround | 3.1 days | Minutes |
| Cost per project | $1,600–$3,200 | ~$2–5 API cost |
| Availability | Business hours | 24/7 |
| Uncertainty | Single narrative, no confidence | Per-claim confidence scores |
| Handoff errors | ~1 in 5 projects | Validated <5% energy mismatch |
| Improves over time | Requires retraining | Automatic evolutionary loop |

---

## Section 3: Technical Architecture with Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    USER / BROWSER                           │
│          React + Vite  —  hosted on Vercel                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTPS
                            ▼
┌─────────────────────────────────────────────────────────────┐
│               BACKEND  —  FastAPI (Python 3.14)             │
│              hosted Railway  •  POST /tasks                 │
│              GET /tasks/{id}/report                         │
└──────┬──────────────────────────────────┬───────────────────┘
       │                                  │
       ▼                                  ▼
┌─────────────────────┐       ┌───────────────────────────┐
│    SwarmManager     │       │  SQLite  +  Redis         │
│  spawn / submit /   │       │  task store + event queue │
│  monitor health     │       └───────────────────────────┘
└──────┬──────────────┘
       ▼
┌─────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                           │
│            QPSO task assignment  •  health monitor          │
└───┬──────────────┬───────────────┬───────────────┬──────────┘
    ▼              ▼               ▼               ▼
┌────────┐  ┌──────────┐  ┌─────────────┐  ┌────────────┐
│ Search │  │  Task    │  │   Memory    │  │ Validator  │
│ Agent  │  │  Agent   │  │   Agent     │  │  Agent     │
│ (QPSO) │  │ (Claude) │  │  (φ-space)  │  │ (H-audit)  │
└───┬────┘  └────┬─────┘  └──────┬──────┘  └─────┬──────┘
    └────────────┴───────────────┴────────────────┘
                            │
                            ▼  text generation + function calling
                ┌───────────────────────────────┐
                │      Anthropic Claude API     │
                │    model: claude-sonnet-4-6   │
                └───────────────────────────────┘
                            │
                            ▼
                ┌───────────────────────────────┐
                │   HAMILTONIAN / QUANTUM CORE  │
                │   PyTorch 2.1                 │
                │   Conservation Monitor        │
                │   QuantumBeliefState          │
                │   EmbeddingHamiltonianNN      │
                │   EvolutionaryContainment     │
                └───────────────────────────────┘
```

**→ Redraw in Excalidraw/draw.io before PDF submission.**

**Stack:**

| Layer | Technology | Justification |
|---|---|---|
| Frontend | React + Vite | Async component model fits live agent-trace polling; Vite keeps dev iteration fast |
| Frontend hosting | Vercel | Zero-config Git deploy; edge CDN for fast dashboard load |
| Backend | FastAPI (Python 3.14) | asyncio-native matches multi-agent concurrency; Python required for hamiltonian_swarm library |
| Backend hosting | Railway | One-command deploy with persistent SQLite volumes; no AWS overhead for course scale |
| Queue | Redis | pub/sub for agent completion events; avoids polling on the API layer |
| Storage | SQLite | Task records + agent logs fit in a single file; no separate DB server needed |
| AI model | Claude claude-sonnet-4-6 | Cleaner tool-use interface than GPT-4o for structured claim extraction; $3/$15 per MTok |
| ML framework | PyTorch 2.1 | Required for autograd Hamiltonian gradients and EmbeddingHamiltonianNN |

**Data flow — core feature (task → report):**

1. User submits task text via React → `POST /tasks`
2. FastAPI writes `PENDING` record to SQLite, publishes to Redis
3. SwarmManager receives event, calls `submit_task()` → Orchestrator
4. Orchestrator runs `decompose_task()` via QPSO, spawns 4 agents concurrently
5. Each agent calls Claude claude-sonnet-4-6 with role-specific prompt; function
   calling extracts structured claims (entity, assertion, confidence, source)
6. ConservationMonitor checks energy after each update; drift >5% triggers
   AgentStateQEC correction
7. HandoffProtocol validates `|ΔH_sender + ΔH_receiver| ≈ 0` between agents;
   failing handoffs trigger agent re-run
8. QuantumBeliefState aggregates claims; entropy >0.8 nats → "conflicting
   evidence" label
9. Results written to SQLite; Redis completion event published
10. React polls `GET /tasks/{id}/report`; renders structured report with
    confidence scores and agent trace

---

## Section 4: Risk and Failure Mode Analysis

### FM1 — Hallucination cascade (AI-specific, High impact)

One agent produces a fabricated claim. Downstream agents treat it as fact, building
further analysis on top of it. Unlike single-agent hallucination, the cascade looks
credible because multiple agents appear to agree.

**Mitigations:**
- Function-calling extraction requires every claim to carry `source_type:
  agent_inference | retrieved_fact`. A chain of `agent_inference` with no
  `retrieved_fact` ancestor is labelled `UNVERIFIED` in the report.
- QuantumBeliefState entropy check: entropy > 0.8 nats on a claim triggers a
  "conflicting evidence" flag before consensus is declared.
- A handoff that fabricates information registers as energy mismatch >5% and is
  rejected; the sending agent reruns the sub-task.

### FM2 — Agent goal drift (AI-specific, High impact)

The evolutionary loop produces faster agents that silently omit nuance, optimising
for speed over accuracy and drifting from the user's stated objective over time.

**Mitigations:**
- EvolutionaryContainment encodes the core goal as `H_goal`. Every mutation is
  tested: `|H(mutated) − H_goal| / |H_goal| < 0.10`. Failures are rejected and
  logged to a dashboard-visible audit trail.
- Containment runs every generation, not only at startup.

### FM3 — Coordination deadlock (Infrastructure, Medium impact)

Two agents wait on each other, or one crashes mid-task, leaving status `RUNNING`
indefinitely.

**Mitigations:**
- ConservationMonitor: no energy update in >30 s fires `reset_callback`, signalling
  the SwarmManager that the agent is stalled.
- Hard 5-minute task timeout; timed-out tasks are marked `FAILED` and partial
  output is returned.
- AgentStateQEC restores a stalled agent from a 3-copy checkpoint without full
  restart, preserving work already done.

### FM4 — API cost overrun (Business, Medium impact)

A complex task with many agent iterations hits $50+ in Claude API costs in a
single run.

**Mitigations:**
- `max_tokens_budget` required at task submission (default: 100k tokens ≈ $0.60).
  SwarmManager tracks usage via SDK `usage` field and blocks new calls at limit.
- Dashboard shows real-time token counter; 80% consumed triggers a warning with
  extend/conclude options.

---

## Section 5: Team Roles and Week-by-Week Plan

| Member | Role | Owns |
|---|---|---|
| [A — Lead] | Product & Backend | FastAPI, SwarmManager, Redis, SQLite, API design |
| [B] | AI & Agent Logic | Claude API, agent prompts, function-calling extraction, QuantumBeliefState |
| [C] | Physics & Safety | Hamiltonian core, EvolutionaryContainment, ConservationMonitor, AgentStateQEC |
| [D] | Frontend | React dashboard, task form, agent trace view, report rendering, Vercel deploy |

| Week | Dates | Deliverables | Owner | Risk |
|---|---|---|---|---|
| 2 | Mar 23–29 | Repo, FastAPI skeleton, React boilerplate, Claude API call confirmed | A, D | Low |
| 3 | Mar 30–Apr 5 | SwarmManager + Orchestrator wired to FastAPI; single-agent end-to-end | A, B | Medium |
| **4** | **Apr 6–12** | **🟦 DESIGN REVIEW due Apr 2** | All | — |
| 5 | Apr 13–19 | All 4 agents running in parallel; handoff protocol; Redis pub/sub | A, B, C | **High** — first full integration; async bugs expected |
| 6 | Apr 20–26 | Conservation monitor live; energy logged; stall detection working | C | Medium |
| 7 | Apr 27–May 3 | QuantumBeliefState in outputs; confidence scores in report; function-calling extraction | B, C | Medium |
| 8 | May 4–10 | React: live agent trace, token counter, confidence display; 3 real end-to-end task tests | D, A | Medium |
| 9 | May 11–17 | Evolutionary loop running; containment violations logged; 10-generation test passing | C | **High** — compute-heavy; may need async offload |
| 10 | May 18–24 | Token budget enforcement; error handling; internal team end-to-end test | All | Medium |
| **11** | **May 25–31** | **🟥 SAFETY AUDIT** — containment log reviewed; failure modes tested adversarially | C, A | High |
| **12** | **Jun 1–7** | **🟧 PEER REVIEW PRESENTATION** — live demo + 3 pre-recorded fallback runs | All | Medium |

**High-risk weeks:**
- **Week 5:** First time all agents run together. Integration bugs (async ordering,
  Redis race conditions, false-positive handoff rejections) are expected. Friday is
  kept clear for debugging.
- **Week 9:** Evolutionary loop under production API latency. Fallback: run
  asynchronously offline if per-request latency is unacceptable.

---

## Section 6: IRB-Light Checklist

| # | Question | Answer | Explanation |
|---|---|---|---|
| 1 | Collects PII? | **Yes** | Task text may contain names, business details, or financial data typed by the user |
| 2 | Stores user data beyond session? | **Yes** | Task text and agent outputs stored in SQLite for report retrieval |
| 3 | Shares data with third parties? | **Yes** | Task prompts sent to Anthropic Claude API; Anthropic's API terms prohibit using API data for training |
| 4 | Targets minors? | **No** | Business operators (18+) only; no age gate needed for prototype |
| 5 | Decisions with material impact? | **Yes** | Reports may inform financial or legal decisions; a hallucination could influence real business action |
| 6 | Human subjects research? | **No** | No surveys, interviews, or behavioral tracking |

**Data handling (required because Q1, Q2, Q3, Q5 are Yes):**
- First-use consent screen states: task text is stored and sent to the Anthropic
  API; outputs are AI-generated and must be independently verified before acting.
- No accounts or emails collected. Tasks identified by client-generated UUID.
  Users can delete via `DELETE /tasks/{id}`.
- Every report page shows: *"AI-generated. Verify before acting."*

---