# Design Review: Quantum Swarm

**Status:** Initial Proposal (Version 1.0)

**Course:** CS-AI-2025 — Building AI-Powered Applications | Spring 2026

**Team Name:** Vector Visions

**Team Members:** Luka Mikautadze | Rezo Darsavelidze | Giorgi Siradze 

**Team Lead (LMS submitter):** Giorgi Siradze



**Submission Due:** Thursday 2 April 2026 at 23:59

**Total Points:** 10



---

## Section 1: Problem Statement and Real User Need

### 1.1 — Who has this problem?

Small business owners and non-technical founders who need custom, scalable software solutions (like internal management tools or customer-facing apps) but lack the capital to hire a full-scale traditional development agency. These users want long-term, iterative software development but are priced out of the professional agency market and lack the technical expertise to assemble and manage a team of individual freelancers themselves.

---

### 1.2 — What is the problem?

Building high-quality, scalable software requires a coordinated team: architects to plan, designers to build UI, programmers to write code, and QA testers to find bugs. For a small business, orchestrating this is nearly impossible. Hiring a traditional dev agency provides the coordination but is prohibitively expensive. The alternative—hiring individual freelancers via platforms like Upwork—shifts the massive burden of project management onto the non-technical founder. The founder must become a makeshift product manager, translating their business needs into technical tickets, resolving disputes between designers and developers, and verifying code quality. This results in stalled projects, broken codebases, and burned budgets. There is a "missing middle" in the market: centralized, coordinated, long-term software development at a fraction of agency costs.

---

### 1.3 — How do they currently solve it?

Currently, founders either: (1) compromise on their vision by using rigid off-the-shelf no-code tools that do not scale; (2) take out large loans to pay traditional dev agencies; or (3) attempt to manage scattered freelance developers via Jira, Slack, or Upwork, which frequently results in chaotic codebases and project abandonment. 

---

### 1.4 — What is the cost of this problem?

The financial and time costs are severe. A standard MVP from a reputable development agency in 2026 costs between $15,000 and $50,000 and takes 3 to 6 months. Managing freelancers is cheaper on paper (e.g., $30–$50/hour per developer), but the hidden cost of management overhead and rework often doubles the initial estimate. Furthermore, when freelancers leave a project, their "context" and memory of the codebase leave with them, making long-term maintenance incredibly painful. 

---

### 1.5 — Evidence of the problem

To validate this problem, our team conducted a 20-minute interview on 19 March 2026 with a local small business owner who recently attempted to build a custom inventory management system. Key findings: He received agency quotes averaging $18,000, which he could not afford. He then hired two freelance developers. He noted: *"I spent 15 hours a week just trying to explain to the backend guy what the frontend guy needed. When the backend dev quit, the new guy had to rewrite half the code because he didn't understand the previous logic."* He explicitly stated he wished he could just *"talk to one lead person who handles the rest of the team behind closed doors."* This perfectly validates Quantum Swarm's "CEO" chat interface approach.

---

## Section 2: Proposed Solution and AI-Powered Differentiator

### 2.1 — What does your application do?

Quantum Swarm is a multi-agent AI system that simulates an entire centralized software development company. The user interacts exclusively with a chat-based interface acting as the "CEO/Lead Manager" of the agency. The user provides plain-language feature requests or project ideas. Behind the scenes, the CEO delegates tasks to Manager agents, who then assign work to specialized Worker agents (Programmers, Designers, Architects, Bug Hunters). These agents work in a sprint-based approach, utilizing tools (like Docker for code testing) and committing finished work directly to a connected GitHub repository. Crucially, the agents possess long-term memory—they remember how they solved past problems, and managers dynamically assign tasks to specific agents based on their accumulated "experience."

---

### 2.2 — Core features

| Feature | What the user can do | Why this matters |
|---------|---------------------|-----------------|
| 1. "CEO" Chat Interface | Chat with a single point of contact to describe features and request updates. | Abstracts away the complexity of managing a tech team; provides a non-technical entry point. |
| 2. Hierarchical Agent Swarm | Trigger a coordinated team of AI roles (Architect, Designer, Programmer, QA). | Ensures proper software development lifecycles (planning → coding → testing) rather than just dumping raw code. |
| 3. Long-Term Experience Memory | Benefit from a system that learns. Managers assign tasks based on past agent successes. | Solves the "context loss" problem. The AI company gets faster and smarter the longer it works on the user's project. |
| 4. GitHub Integration | Have code automatically committed and pushed to a repository via PRs. | Closes the loop from idea to real, usable output without the user needing to copy-paste code. |
| 5. Sprint-Based Execution | Watch the swarm operate in structured sprints with visual progress updates. | Provides transparency and predictability, mimicking real-world agile methodologies. |

---

### 2.3 — The AI-powered differentiator

The core differentiator is the **Experience-Based Multi-Agent Orchestration with Tool Use**. Standard code-generation tools (like ChatGPT or GitHub Copilot) are single-turn, stateless, and require the user to act as the architect and QA. Quantum Swarm uses specialized LLM personas interacting with *each other* to verify logic before showing it to the user. Furthermore, the inclusion of a Graph/Vector Database for long-term memory allows the Swarm to map *how* tasks were completed. When a new task arrives, the Manager agent queries the database, identifies which Programmer agent has the most relevant "experience," and assigns it accordingly. This self-improving operational hierarchy is fundamentally impossible without advanced AI.

---

### 2.4 — What would the non-AI version look like?

The non-AI version of this application is simply a project management dashboard like Jira combined with a freelance marketplace like Upwork. The user would post a job, interview human developers, assign them tickets on a Kanban board, and manually review their pull requests. It would provide the structure of a company, but zero execution, requiring massive human capital and management time.

---

## Section 3: Technical Architecture 

### 3.1 — Architecture Diagram

[User's Browser (React UI)]
       |
       | HTTPS / WebSocket (Feature request text, e.g., "Build a login page")
       v
[Primary Backend — Spring Boot (Java)]
       |                         |
       | JSON task payload       | User ID, Project State
       v                         v
[AI Microservice — Python] <---> [Supabase Postgres DB]
(CrewAI / Agent Orchestrator)    (Stores user projects, chat history)
       |            |
       |            | Queries Agent "Experience" context
       |            v
       |    [Vector DB] (Long-Term Agent Memory)
       |
       | Prompts + Context
       v
[OpenRouter API Gateway] 
       |
       | Routes requests based on agent persona
       +--------------------+
       |                    |
       v                    v
[Gemini Pro]         [Gemini Flash]
(CEO / Planner)      (Workers / Coders)
       |
       | Code generation output mapped back to Microservice
       v
[GitHub API]
(Pushes committed code as Pull Requests)

---

### 3.2 — Technology Stack

| Layer | Technology | Why this choice |
|-------|-----------|-----------------|
| Frontend | React | Industry standard; excellent for building dynamic, real-time chat and dashboard interfaces. |
| Main Backend | Spring Boot (Java) | Robust enterprise framework for handling user authentication, project state, and API routing. |
| AI Backend / Microservice | Python (FastAPI/Flask) | Essential for AI. Python has the best ecosystem for multi-agent frameworks, vector search, and LLM SDKs. |
| Agent Framework | CrewAI (or LangGraph) | Purpose-built for creating role-based AI agents (CEO, Manager, Worker) that collaborate to achieve a goal. |
| AI Models | Gemini Pro & Flash | Gemini Pro for complex reasoning (Architect/CEO), Flash for high-speed, lower-cost tasks (Workers). |
| Memory / Database | Neo4j (Graph) or Vector DB | Allows agents to store relational data about "how" tasks were solved, enabling experience-based routing. |
| Tooling / Output | GitHub API & Docker | GitHub for storing output; Docker for isolated, sandboxed environments where agents can safely test code. |

---

### 3.3 — Core Data Flow

1. User types a request in the React frontend: *"Add a secure login page to my application."*
2. React sends the prompt via WebSocket to the Spring Boot backend, which logs the request and forwards it to the Python Agent Microservice.
3. The **CEO Agent** (powered by Gemini Pro) analyzes the request and breaks it down into a sprint plan.
4. The CEO hands the plan to the **Department Managers**. 
5. The **Manager Agents** query the Long-Term Memory database to check which Programmer and Designer agents have "experience" with authentication flows.
6. Tasks are assigned. The **Designer Agent** drafts the UI structure. The **Programmer Agent** writes the React/Spring code.
7. The Programmer utilizes a secure Docker Sandbox tool to attempt compiling/testing the code.
8. If errors occur, the **Bug Hunter Agent** detects them, and loops back to the Programmer until it passes.
9. Once approved by the Manager, the AI microservice uses the GitHub API to push a Pull Request to the user's repository.
10. The Python service saves the successful workflow to the Memory Database (increasing the agents' experience).
11. The Spring backend notifies the React frontend, and the CEO Agent messages the user: *"Sprint complete. The login page code has been pushed to GitHub."*

---

## Section 4: Risk and Failure Mode Analysis 

### Risk 1: Infinite Agent Conversation Loops

**What happens when this occurs:**
The Programmer agent writes code, the Bug Hunter agent finds an error, the Programmer tries to fix it but creates a new error, and they get stuck in an endless loop arguing with each other. This consumes massive amounts of API tokens and stalls the sprint.
**Likelihood:** High (very common in multi-agent autonomous systems).
**Impact on user:** High (costs spike, no progress made, system looks broken).
**Mitigation strategy:**
Implement strict `max_iterations` limits within the agent framework. If an error is not resolved within 3 iterations, the Manager agent will halt the loop, commit the closest working code, and notify the user via the CEO chat that manual intervention is required on a specific bug.

### Risk 2: Malicious Code Execution during Tool Use

**What happens when this occurs:**
The Programmer agent hallucinates or maliciously generates code that attempts to access our host server's file system or environment variables when it is instructed to "test" the code.
**Likelihood:** Low-Medium (LLMs can write destructive bash commands if prompted poorly).
**Impact on user/system:** High (Security breach or server crash).
**Mitigation strategy:**
All agent-driven code execution and testing will occur strictly inside isolated, ephemeral Docker containers (or secure sandbox APIs like E2B) with no network access to our internal databases. Containers will be instantly destroyed after the test.

### Risk 3: Hallucinated Output Overwriting Working Code

**What happens when this occurs:**
The Swarm decides to refactor an existing working feature while building a new one, breaking the entire project for the user.
**Likelihood:** Medium.
**Impact on user:** High (loss of trust, broken application).
**Mitigation strategy:**
Agents will never have permission to force-push to the `main` branch. The final output of a sprint will strictly be a GitHub Pull Request (PR). The user maintains the ultimate human-in-the-loop authority to merge the code.

---

## Section 5: Team Roles and Week-by-Week Plan 

### 5.1 — Team Roles

| Team Member | Primary Role | Secondary Role | What they own |
|-------------|-------------|----------------|---------------|
| Luka M. | AI/Backend Dev | DevOps | Python Agent microservice, Framework integration, Memory DB logic, Docker sandboxing. |
| Rezo D. | Frontend Dev | API Integrations| React architecture, Chat UI, Sprint visualization, connecting front to Spring. |
| Giorgi S. | UI/UX & Prompts | Product/Domain | Interface design, defining agent personas/prompts, system architecture planning. |

*Note: The Spring Boot intermediate layer will be a shared effort depending on bandwidth.*

---

### 5.2 — Week-by-Week Plan

| Week | Dates | What we will build / complete | Who leads | Risk level |
|------|-------|-------------------------------|-----------|------------|
| 2 | 20 Mar | Setup React, Spring Boot, and Python base repos. Draft Design Review. | Whole team | Low |
| 3 | 27 Mar | Implement basic chat interface. Python service calls Gemini API. | Rezo + Luka | Low |
| 4 | 3 Apr | **Design Review due**. Setup basic CrewAI/LangGraph framework (CEO to 1 Worker). | Luka + Giorgi | High |
| 5 | 10 Apr | Connect Python Agent service to Spring Boot backend via REST. | Luka + Rezo | Medium |
| 6 | 17 Apr | Implement Agent specialized roles (Designer, Programmer) and Docker sandbox. | Luka + Giorgi | High |
| 7 | 24 Apr | Build GitHub API integration for pushing Pull Requests. | Rezo + Luka | Medium |
| 8 | 1 May | Implement the Long-Term Memory (Experience) database for routing. | Luka + Giorgi | High |
| 9 | 8 May | Midterm week — integration testing and UI polishing. | — | Low |
| 10 | 15 May | Finalize Sprint visualization on frontend. Refine agent prompts. | Rezo + Giorgi | Medium |
| 11 | 22 May | **Safety Audit** — security check on Docker containers, prompt injection testing. | Whole team | High |
| 12 | 29 May | **Peer Review Presentation** — live demo rehearsal with a sample repository. | Whole team | High |

---

### 5.3 — Honest Assessment

The hardest phase of this project will be Weeks 6 through 8. Building a single chatbot is straightforward, but orchestrating a multi-agent swarm where LLMs must communicate with *each other* (Manager to Programmer to QA) is notoriously unstable. Our biggest technical risk is "Agent Drifting"—where the Bug Hunter and the Programmer get stuck in an infinite loop of writing code, finding a bug, and rewriting it incorrectly. If we discover in Week 6 that our chosen framework (CrewAI/LangGraph) is too difficult to stabilize, our fallback plan is to reduce the swarm hierarchy from a full team down to just two agents: a "CEO" for planning and a single "Universal Developer" for execution. 

A secondary major risk is the Docker Sandbox integration. Allowing AI to autonomously execute and test code on a server is a significant security and DevOps hurdle. If this proves too complex or resource-heavy for a student environment, we will pivot to a "dry-run" approach: the agents will write the code and push it straight to GitHub via PR, but the human user will be responsible for pulling and testing the code locally.

Finally, maintaining a dual-backend architecture (Spring Boot for user state + Python for AI execution) adds significant complexity to our data flow. We are aware that this is an extremely ambitious project. We have front-loaded the core chat and API connections to Week 3 to ensure that if the advanced features (like long-term memory) fail, we still have a working, demonstrable minimum viable product for Demo Day.


---

## Section 6: IRB-Light Checklist 

| Question | Answer | If yes: explain |
|----------|--------|-----------------|
| 1. Does your app collect images of real people? | No | — |
| 2. Does your app process photographs of faces? | No | — |
| 3. Does your app handle sensitive documents? | Yes | The app processes proprietary business ideas, intellectual property, and private code bases. |
| 4. Does your app store user-uploaded data? | Yes | Chat histories, generated code, and project states are stored in our databases. |
| 5. If storing data: for how long and where? | PostgreSQL | Data is stored for the lifetime of the user's account to enable the system's long-term memory functions. |
| 6. Do users need to give informed consent? | Yes | Users must consent to their code and ideas being processed by AI models. |

**Consent and data handling approach:**
Since target users are startups and businesses, protecting their Intellectual Property (IP) is critical. During onboarding, the application will display a Terms of Service explicitly stating that: (1) System prompts and code are processed by Google Gemini; (2) We utilize enterprise API endpoints that guarantee user data is *not* used to train Google's foundational models; (3) Sandbox environments are ephemeral and purged immediately; (4) Only the user's private Agent Memory Database retains their architectural choices. This ensures users feel secure submitting their proprietary startup ideas to our Swarm.

---

*Design Review for CS-AI-2025 Spring 2026.*
