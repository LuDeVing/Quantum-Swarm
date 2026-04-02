# Capstone Design Review

**Course:** CS-AI-2025 — Building AI-Powered Applications | Spring 2026
**Assessment:** Design Review — 10 points
**Due:** Thursday 2 April 2026 at 23:59 Georgia Time
**Submission:** Team repo (see required tree in Lab 3 README) + Google Form (link on Teams)
**Team:** Vector Visions
**Project:** Quantum Swarm
**Repo:** [Quantum Swarm](https://github.com/LuDeVing/Quantum-Swarm)

---

## Section 1 — Problem Statement and Users

**Problem statement (one sentence):**
Small business owners and non-technical founders struggle to build custom software because hiring a traditional dev agency is prohibitively expensive and managing individual freelancers is chaotic, which means they often abandon their projects or settle for unscalable no-code tools.

**Who exactly has this problem:**
Non-technical founders and small business owners who need custom internal tools. We interviewed a local business owner who wanted an inventory management system; he received an unaffordable $18,000 agency quote, subsequently hired two scattered freelancers, and lost 15 hours a week acting as a makeshift product manager to translate requirements between them before the codebase ultimately failed.

**What they do today without your solution:**
They either compromise on their vision by using rigid off-the-shelf software, take out large loans to hire a centralized agency, or attempt to manage freelance developers on Jira/Upwork, which shifts the massive burden of technical project management directly onto them.

**Why AI is the right tool:**
Conventional tools (like Jira or GitHub) only organize *human* labor but do not execute it. Basic LLMs (like ChatGPT) can generate code snippets but cannot orchestrate a multi-step software development lifecycle (planning, coding, testing). A multi-agent AI framework is the only way to provide both the centralized organizational structure of a company *and* the autonomous execution of the labor, utilizing long-term memory to continuously improve on past sprints.

---

## Section 2 — Proposed Solution and Features

**Solution summary (3–5 sentences):**
Quantum Swarm is an AI-powered multi-agent software development agency accessed entirely via a chat interface. Users speak directly to an AI "CEO" who breaks down feature requests and delegates them to specialized AI Worker agents (Programmers, Designers, Bug Hunters). These agents collaborate, write, test, and refine code before pushing it directly to the user's GitHub repository. A long-term memory database tracks how past tasks were solved, allowing the swarm's managers to assign tasks based on accumulated "experience" over time.

**Core features:**

| Feature | AI-powered? | The AI differentiator? |
|---|---|---|
| Chat-based "CEO" Interface | Yes | No |
| Hierarchical Agent Swarm (Planning to Execution) | Yes | Yes |
| Experience-Based Task Routing (Long-Term Memory) | Yes | Yes |
| Automated GitHub PR Integration | No | No |
| Sprint-Based Execution Dashboard | No | No |

**The one feature that would not exist without AI:**
Experience-based task routing, where manager agents assign specific coding tasks to worker agents based on their historical success rates and past context stored in a vector database.

---

## Section 3 — Measurable Success Criteria

| Criterion | How you will measure it | Target |
|---|---|---|
| Code Generation Viability | Calculate the percentage of AI-generated Pull Requests that run locally without fatal console errors during testing. | >75% of PRs compile/run successfully on the first attempt. |
| Agent Orchestration Efficiency | Measure the average number of internal loop iterations between the "Programmer" and "Bug Hunter" agents per task. | Resolve or safely fallback in under 4 internal iterations per task to prevent infinite loops. |

---

## Section 4 — Architecture

**Architecture diagram:**
```
See: docs/design-review/architecture-diagram.png
```
*(Note for the team: Draw the following flow for the PNG: React Frontend -> Spring Boot Backend -> Python AI Microservice (CrewAI). From Python -> Vector DB (Memory), Supabase (Relational DB), and OpenRouter. OpenRouter -> Gemini Pro (CEO) & Gemini Flash (Workers). Finally, Python -> GitHub API).*

**Technology stack:**

| Layer | Technology | Why |
|---|---|---|
| Frontend | React + Tailwind | Fast UI iteration, standard for real-time chat/dashboards. |
| Backend | Spring Boot (Main) + FastAPI (AI Service) | Spring handles secure user state; Python handles AI multi-agent orchestration. |
| Primary AI model | Gemini 1.5 Pro via OpenRouter | Best reasoning capabilities for CEO/Architect planning phases. |
| Secondary model (fallback) | Gemini 1.5 Flash via OpenRouter | High speed and low cost for repetitive Worker tasks. |
| Storage | Supabase Postgres & Pinecone (Vector) | Postgres for user/project state; Pinecone for long-term agent memory context. |
| Hosting | Vercel (Front) + Railway (Back) | Reliable free tiers suitable for capstone deployment. |

**Multimodal capabilities (check all that apply now or planned by Week 8):**

- [x] Text generation
- [ ] Vision / image understanding (Lab 2)
- [ ] Image generation (planned Lab 3 / Week 3)
- [ ] Audio TTS or STT
- [ ] Document / PDF understanding
- [x] Function calling
- [x] RAG

---

## Section 5 — Prompt and Data Flow

```
User action:
  The user types "Add a secure login page to the app" into the React chat interface and clicks send.

Preprocessing:
  The Spring Boot backend attaches the User ID, current GitHub branch status, and previous sprint context, then forwards the payload to the Python AI Microservice.

Prompt construction:
  The Python service constructs a system prompt for the "CEO" agent, injecting its persona rules, the user's raw request, and RAG context (project schema) retrieved from Supabase and Pinecone.

API call:
  OpenRouter routes the call to `google/gemini-1.5-pro` with a low temperature (0.2) for deterministic, structured planning.

Response parsing:
  The model returns a JSON-formatted sprint plan. The Python orchestrator parses this JSON into distinct tasks and triggers the Manager Agent to assign them to Gemini Flash Workers.

Confidence / validation:
  The "Bug Hunter" agent statically analyzes the Programmer agent's code. If the code fails checks 3 times in a row, confidence drops to LOW, the internal loop breaks, and execution halts.

User output:
  If successful, the user sees: "Sprint Complete. A Pull Request for the login page is waiting in GitHub." 
  If validation failed, the fallback UI triggers (described in Section 7).
```

---

## Section 6 — Team Roles and Contract

**Team members and roles:**

| Name | Primary role |
|---|---|
| Luka Mikautadze | AI/Backend Dev & DevOps |
| Rezo Darsavelidze | Frontend UI/UX Integration |
| Giorgi Siradze | Team Lead, Testing & Documentation |

**Team Contract:** Committed to repo root as `TEAM-CONTRACT.md`.

```
Link: https://github.com/ZA-KIU-Classroom/AI-POWERED-SOFTWARE-DEV-SP26/vector-visions/blob/main/TEAM-CONTRACT.md
```

---

## Section 7 — Safety Threats and Fallback UX

### Safety Threats

| Threat | Relevant? | Your mitigation |
|---|---|---|
| Prompt injection — user input hijacks system behaviour | Yes | Strict system boundaries; agents output code strictly to PRs, with zero direct execution access to our backend databases. |
| Hallucination in high-stakes output | Yes | Agents may hallucinate non-existent libraries. Mitigated by Bug Hunter static analysis and mandatory human PR review. |
| Bias affecting specific user groups | N/A | We generate software code, which is structurally immune to demographic bias. |
| Content policy violation | N/A | Software feature requests do not generally trigger safety/NSFW policy violations. |
| Privacy violation via stored model inputs or logs | Yes | Mitigated by using OpenRouter enterprise endpoints ensuring user codebase data is not used for foundational model training. |
| Data exfiltration via model response | Yes | AI could theoretically write code sending data to malicious servers. Mitigated by Human-in-the-loop GitHub merging. |

**Top risk you are most concerned about:**
Our biggest concern is "Infinite Agent Hallucination Loops," where the Bug Hunter and Programmer get stuck endlessly arguing over broken code, burning API credits and stalling the application.

### Fallback UX

The user sees a pause icon in the chat interface followed by a message: "The development team encountered an unresolved dependency issue while building this feature. We have paused work to prevent errors." Below the message, two buttons appear: "Review Partial Code on GitHub" and "Simplify Feature Request." The system does not attempt to hide the failure, but rather frames it as a responsible dev team pausing before breaking the main branch.

---

## Section 8 — Data Governance

| Question | Your answer |
|---|---|
| What user data does your app collect or process? | Feature descriptions, proprietary codebase structures, and chat histories. |
| Where is it stored? (service name, country) | Supabase (Postgres) and Pinecone (Vector), hosted in EU regions. |
| How long is it retained? | Retained indefinitely while the account is active to preserve long-term Agent Memory context. |
| Who has access to it? | Only the authenticated account owner and the backend server. |
| How can a user request deletion? | A "Delete Project" button in user settings cascades and deletes all DB and Vector records immediately. |
| Does your app send user data to third-party AI APIs? Which ones? | Yes. Prompts and code are sent to Google Gemini via OpenRouter. |

---

## Section 9 — IRB-Light Checklist

Check all that apply:

- [ ] My app collects or processes images of real people
- [ ] My app collects or processes audio recordings
- [ ] My app handles personal health information
- [ ] My app handles financial information
- [ ] My app involves users under 18
- [ ] My app processes documents containing personal data

**For each box checked, describe consent flow and data retention:**

```
None of the above apply. (Note: While we process proprietary code and business ideas, we do not process Personally Identifiable Information / PII).
```

---

## Section 10 — Submission Checklist

Complete before Thursday 2 April 23:59.

- [x] All sections above have no `[fill in]` remaining
- [x] `docs/design-review/architecture-diagram.png` committed and readable
- [x] `TEAM-CONTRACT.md` in repo root with all member names
- [x] `.env` is not committed (check `.gitignore`)
- [x] Lab 1 work visible or linked in repo
- [x] Lab 2 proposal and vision call visible in repo
- [ ] `lab-3/generation-strategy.md` committed
- [x] Team repo matches the tree in the Lab 3 README
- [x] Google Form completed by one team member

---

*Design Review for CS-AI-2025 Spring 2026.*
*Questions: zeshan.ahmad@kiu.edu.ge or course forum.*
