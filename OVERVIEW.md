# Quantum Swarm — How It Works

You give it an idea. It builds the software.

---

## The Big Picture

Quantum Swarm is an AI-powered software company that runs entirely on its own. You type a one-line description of what you want built, and a team of AI agents — each with a specific job — works together to design, code, test, and ship it.

Think of it like hiring a full software team, except every person on the team is an AI, they never sleep, and they work in parallel.

---

## The Company Structure

The system is organized exactly like a real company:

**CEO** sits at the top. Before work starts, the CEO runs a meeting with all the managers to agree on what gets built in this round. The CEO also reviews the work at the end and decides if it's ready to ship or needs another round.

**Four teams** do the actual work, in order:

| Team | What they produce |
|------|------------------|
| **Architecture** | The blueprint — how the system is structured, what the API looks like, how the database is designed |
| **Design** | The user experience — what screens look like, how users move through the app, colors and spacing |
| **Engineering** | The actual code — 8 developers writing files simultaneously |
| **QA** | Tests and security checks — making sure nothing is broken |

Each team has a **manager** who coordinates the workers and merges their output into one clean document.

---

## A Round of Work (Called a "Sprint")

Everything happens in rounds called sprints. Here's what one sprint looks like:

### 1. The Kickoff Meeting
The CEO gathers all four managers. They don't just rubber-stamp a plan — they actually negotiate:
- Round 1: each manager proposes what their team should build
- Round 2: managers read each other's proposals and adjust to avoid conflicts
- CEO reads everything and writes the final agreed goal

This goal gets pinned at the top of every agent's work so nobody loses sight of it.

### 2. Teams Work in Sequence
Architecture goes first (you can't design a UI before you know what the app does). Design goes second. Engineering goes third (they read the architecture and design specs). QA goes last (they need code to test).

### 3. Review and Decision
At the end, the CEO and managers review what was built. If it's good enough to ship, done. If not, they plan the next sprint and do it all again — up to five times.

---

## How the Engineers Work

This is where it gets interesting. All 8 AI developers work **at the same time**, each on a different file, without stepping on each other.

Before anyone writes a single line of code, the engineering manager produces a plan that says: "dev_1, you write the login endpoint. It needs to import from models.py, and it must export these three functions. Don't start until models.py is done." Every developer gets a contract like this.

Each developer works in their own isolated copy of the codebase (a git branch), writes their file, runs the tests, and then merges back into the shared version. As soon as a file is merged, all the other developers can see it and use it.

When all files are done, the system runs the full test suite automatically. If tests fail, the engineering manager gets a list of what broke and spends up to 10 rounds fixing it.

---

## Memory — How Agents Get Smarter Over Time

Agents have three types of memory, each working at a different timescale.

### Short-Term (lasts one sprint)
A sliding window of the last few tasks the agent completed. Like a human's short-term working memory — enough to not repeat yourself within a session, but gone when the sprint ends.

### Code Search (persists forever)
Every file ever written gets indexed and is searchable by meaning. An agent writing a database layer in Sprint 5 can search "authentication session handling" and find relevant code written back in Sprint 1, even if the exact words don't match.

### Long-Term Knowledge Graph (the good stuff)
After every task, the system extracts lessons and builds a **knowledge graph** — a web of connected concepts.

Here's a simple example of what that graph looks like:

```
"missing context manager" ──causes──► "connection leak"
"async context manager"   ──fixes───► "connection leak"
"connection leak"          ──linked──► lesson: "always wrap SQLAlchemy in async with"
```

When an agent is about to work on something database-related, the system activates the relevant concept nodes in this graph, follows the connections outward, and surfaces the most useful lessons — even if the query words don't exactly match the stored lesson.

This is called **spreading activation** — the same way human memory works. You think of "Paris" and "Eiffel Tower" comes to mind without needing to explicitly search for it.

All 8 developers share the same knowledge graph, so anything one of them learns benefits everyone immediately. Each role (QA, architect, designer, etc.) has its own separate graph.

After many sprints, the graph becomes a living record of what the team knows — what caused bugs, what fixed them, which libraries caused the most trouble, which patterns worked best.

---

## Agent Health Monitoring (The Hamiltonian Swarm)

The system continuously monitors whether each agent is working well or struggling.

### How it works

Every agent has a "health state" — essentially a confidence score about how well it's performing. After each task, the system checks: was the output coherent and on-task, or was it meandering and confused?

This gets turned into a single number called **Free Energy**. The name comes from theoretical neuroscience (the Free Energy Principle, by Karl Friston) — the same math used to model how brains work. The core idea: a healthy agent's output should match what's expected from its role. The bigger the gap between expectation and reality, the higher the Free Energy, and the more likely something is wrong.

- **Free Energy near zero** → agent is on-track
- **Free Energy rising** → agent is drifting or confused

If an agent's Free Energy spikes significantly above its own recent average, it's flagged as an anomaly and a "fixer" agent steps in to review and redo the work.

### The swarm effect

At the end of each sprint, all agents' health states are blended together. If most agents are working well but one is struggling, the struggling agent gets pulled toward the healthy average. It's like a team recalibration — no single agent's bad day permanently derails its performance.

The blending uses **quantum amplitudes** (the math of quantum mechanics) rather than simple averaging. Square roots of probabilities are averaged and then squared back. This produces a more nuanced merge — agents with similar states reinforce each other more strongly, while outliers are gently corrected rather than overwritten.

---

## What Every Agent Can Do

Every agent has access to a set of tools depending on their role. Here are the most important ones available to everyone:

| Tool | What it does |
|------|-------------|
| **think** | Write out your reasoning before doing anything (required) |
| **recall_memory** | Search past lessons from the knowledge graph |
| **read_file** | Read any project file, with line numbers and pagination |
| **grep_codebase** | Search for an exact word or pattern across all files |
| **search_codebase** | Search by meaning (finds "authentication" even if you search "login security") |
| **web_search** | Look up documentation, APIs, best practices online |
| **write_code_file** | Write code (the only way to actually ship something) |
| **run_shell** | Run tests, compile code, check for errors |
| **message_teammate** | Send a direct message to another agent |

Before writing anything, agents must call `think()` first — a forced pause where they plan their approach, consider what could go wrong, and decide what quality bar to aim for. They can also use `web_search` and `recall_memory` during this thinking phase to do real research before committing to an approach.

---

## The Stance System

Every agent ends their work with a self-declared stance:

- **MINIMAL** — I kept it as simple as possible
- **ROBUST** — I added solid error handling and edge case coverage
- **SCALABLE** — I designed it to grow
- **PRAGMATIC** — I made practical tradeoffs

This isn't just a label. The stances feed into the health monitoring — if every agent is declaring SCALABLE on a simple CRUD app, that's a signal the team might be over-engineering.

---

## Testing GUI Apps

When the software being built has a graphical interface, the engineering manager can actually open it, click around, and verify it works — using real Windows accessibility tools (not screenshots and pixel-guessing).

The process:
1. List all the buttons, text fields, and controls in the window by name
2. Click a button by name (e.g., click the "Submit" button)
3. Read what changed in the window to verify it worked

This is faster and more reliable than taking screenshots and asking an AI to guess where things are.

---

## Where Everything Lives

```
company_output/          Everything the system creates
  code/                  The actual software being built
  memory/                The knowledge graphs (persist forever, grow with every sprint)
  design/                Architecture docs, design specs, test checklists
  
prompts/                 The instructions each type of agent follows
software_company/        The engine that runs the whole system
hamiltonian_swarm/       The health monitoring and swarm coordination math
```

---

## In One Sentence

Quantum Swarm is an AI team that designs, codes, and tests software — getting smarter after every sprint by building a shared knowledge graph of lessons learned, while continuously monitoring its own health to catch and correct struggling agents before they cause problems.
