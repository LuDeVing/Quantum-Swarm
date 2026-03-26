# Four Filters — Team Convergence Template

**Team Name:** Quantum Swarm
**Team Members:** Luka Mikautadze | Rezo Darsavelidze | Davit Mzhavanadze

---

## Step 1: Surface All Ideas (5 minutes)

| # | Idea (one sentence) | Proposed by |
|---|---------------------|-------------|
| 1 | Multi-agent AI framework that uses physics equations to keep agents stable and on-task over long runs | Luka |
| 2 | AI agent that scans Polymarket, finds mispriced odds, and recommends positions | Rezo |
| 3 | Research assistant that stays focused on the original question across 50+ reasoning steps | Davit |
| 4 | Code review agent that tracks architectural decisions across a large codebase | Luka |
| 5 | RAG tool for legal/financial document analysis | Rezo |

---

## Step 2: Quick Filter Pass (10 minutes)

| Idea # | Filter 1: Real Problem? | Filter 2: AI Adds Value? | Filter 3: Buildable in 12 weeks? | Filter 4: Team Motivated? | Overall |
|--------|------------------------|--------------------------|----------------------------------|---------------------------|---------|
| 1 | ✓ | ✓ | ? | ✓ | Survivor |
| 2 | ✓ | ✓ | ✓ | ✓ | Survivor |
| 3 | ✓ | ✓ | ✓ | ? | Survivor |
| 4 | ✓ | ✓ | ? | ? | ✗ |
| 5 | ? | ? | ✓ | ✗ | ✗ |

**Ideas that survived:**

```
Idea 1: HamiltonianSwarm physics framework
Idea 2: Polymarket prediction agent
Idea 3: Long-horizon research assistant
```

---

## Step 3: Deep Dive on Survivors (10 minutes)

### Idea 1: HamiltonianSwarm

**Weakest filter:** Filter 3 — Buildable in 12 weeks?

**What would need to be true for this filter to be a clear pass?**

```
The physics math needs to run in normal Python — no special hardware needed,
it's all just equations. If the core is working in week 2, the rest can be
split between team members and built in parallel.
```

**Can this idea be reshaped to address the weakness? How?**

```
Yes — merge ideas 1, 2, and 3. Use Polymarket as the main demo so we always
have something concrete to show, even if the full framework isn't finished.
```

---

### Idea 2: Polymarket prediction agent

**Weakest filter:** Filter 1 — Real Problem?

**What would need to be true for this filter to be a clear pass?**

```
The problem has to be more than "make money on Polymarket." The real issue is
that scanning hundreds of correlated markets at once and staying consistent
across them is genuinely hard — a single prompt can't do it reliably.
```

**Can this idea be reshaped to address the weakness? How?**

```
Frame it as the demo use case for idea 1. Polymarket gives us measurable
results (did the prediction resolve correctly?) which makes the demo strong.
```

---

### Idea 3: Long-horizon research assistant

**Weakest filter:** Filter 4 — Team Motivated?

**What would need to be true for this filter to be a clear pass?**

```
We'd need to actually care about the research domain. We don't, specifically.
But if it's powered by the same framework as idea 1, we care about the
architecture — the use case is just a demo.
```

**Can this idea be reshaped to address the weakness? How?**

```
Absorb it into idea 1 as a secondary demo, behind Polymarket.
```

---

## Step 4: Decision (5 minutes)

**Our chosen project idea:**

```
HamiltonianSwarm — a multi-agent AI framework that uses physics to keep agents
coherent, demonstrated via a Polymarket prediction agent.
```

**Why this idea over the alternatives:**

```
Ideas 2 and 3 alone are just prompt engineering and RAG — nothing technically
new. Idea 1 has a real novel foundation that makes the AI behave differently.
Polymarket as the demo gives us measurable outcomes for Week 12.
```

**The one thing we are most uncertain about:**

```
Whether the energy conservation check will work on real noisy LLM outputs
without triggering false positives constantly. We'll find out in Week 5.
```

---

## Filter Answers for the Chosen Idea

### Filter 1: Problem

**Who specifically has this problem?**

```
Prediction market traders on Polymarket who run AI agents to find mispriced
odds but can't trust them to stay consistent across correlated markets without
manual supervision.
```

**What do they currently do about it?**

```
Manually restart agents every 20-30 steps, review all recommendations by hand,
and only act after checking for contradictions themselves.
```

**What is the cost of the problem not being solved?**

```
By the time they finish reviewing, the mispriced odds have already corrected.
Contradictory positions on correlated markets can also cause direct losses.
```

**Can you reach a real user in the next two weeks?**

```
Yes — Polymarket has a public API. We can test against live markets and measure
accuracy against actual resolutions without needing user interviews.
```

---

### Filter 2: AI

**What does AI specifically do in this product?**

```
- Claude reasons about each market in natural language (impossible with rules)
- Function calling extracts structured probability claims for cross-validation
- Embeddings detect when an agent has drifted off-topic
```

**Which week of the course is most relevant?**

```
Week 6 (Function Calling) for the validator. Week 5 (RAG) for the memory agent.
Week 3 (text generation) for all agent reasoning.
```

**What would the product look like without AI?**

```
A basic filter by volume or price movement — it can't read market descriptions,
reason about correlated events, or weigh conflicting arguments.
```

**Is the AI doing something that was impossible before?**

```
Yes. Scanning hundreds of markets, staying consistent across correlated ones,
and flagging internal contradictions in real time — a human team can do it but
not at market speed.
```

---

### Filter 3: Feasibility

**What APIs does this require?**

```
- AI API key for agent reasoning (via OpenRouter or direct)
- Polymarket CLOB API (public, free) for market data
```

**What is the hardest technical problem?**

```
Calibrating the energy drift threshold so it catches real agent errors without
firing on normal output variation. Can only be solved by testing on real data.
```

**Does anyone on the team know how to solve it?**

```
Luka already built the core physics layer. We'll calibrate the threshold
empirically in weeks 5-6. Fallback: use it as a soft warning, not a hard stop.
```

**What is the MVP?**

```
One Polymarket agent that fetches markets, estimates probabilities with the swarm,
aggregates with QuantumBeliefState, and returns a ranked list with confidence
scores. No evolution, no parallel agents. Already useful on its own.
```

---

### Filter 4: Motivation

**What does the Week 12 demo look like?**

```
Type "find mispriced markets in US politics" into the dashboard. Four agents
spin up on screen. Agent trace shows live energy readings and handoff checks.
Output: ranked positions with confidence scores and disagreement flags.
Bonus: show one market where our estimate beat the odds and it resolved in
our favor.
```

**Who on the team cares about this?**

```
Luka — the physics/math angle. 
Rezo — AI agents and tools design.
Davit — building something that looks compelling and is explainable.
```

**Could this exist beyond the course?**

```
Yes. The framework is already open source at github.com/LuDeVing/Quantum-Swarm.
Polymarket is one application — the same architecture works for research,
trading, and code review.
```

---

## Next Steps

| Action | Owner | Deadline |
|--------|-------|----------|
| Create team GitHub repo | Luka | End of today's lab |
| Complete builder sprint scaffold | Whole team | End of today's lab |
| Draft Design Review Sections 1 and 2 | Rezo | Before next Tuesday |
| Create architecture diagram (Excalidraw) | Davit | Before next Tuesday |
| Complete full Design Review draft | Whole team | Before Thursday 2 April 23:59 |

---

*Internal document — not submitted. Design Review is the submission.*
