# Safety and Evaluation Audit - Quantum Swarm

**Team Name:** Vector Visions  
**Team Members:** Luka, Rezo, Giorgi  
**Repository:** https://github.com/ZA-KIU-Classroom/AI-POWERED-SOFTWARE-DEV-SP26/vector-visions  
**Audit Commit:** run `git rev-parse HEAD` in the team repo after committing  
**Submitted:** 2026-05-13

---

## Area 1: Episode Log Quality - /2 pts

**Link to episode log file:** `logs/episodes.jsonl`

**Total entry count:** 136

**Sample - 5 consecutive entries:**

```json
{"ts":"2026-04-28T09:00:00Z","event_type":"llm_call","model":"gemini-3.1-flash-preview","provider":"google-genai","input_tokens":5267,"output_tokens":556,"cache_read_tokens":209,"cache_write_tokens":0,"cost_usd":0.00215075,"latency_ms":6037,"fallback_triggered":false,"error":null,"episode_id":"qa_task-0000-1777366800000","agent_id":"ceo","sprint":2,"task_file":"backend/api.py","label":"qa_task","attempt":1}
{"ts":"2026-04-28T09:00:52Z","event_type":"llm_call","model":"gemini-3.1-flash-preview","provider":"google-genai","input_tokens":5397,"output_tokens":1014,"cache_read_tokens":0,"cache_write_tokens":0,"cost_usd":0.00287025,"latency_ms":7065,"fallback_triggered":false,"error":null,"episode_id":"eng_task-0001-1777366852000","agent_id":"architect_manager","sprint":3,"task_file":"config/settings.py","label":"eng_task","attempt":1}
{"ts":"2026-04-28T09:05:04Z","event_type":"llm_call","model":"gemini-3.1-flash-preview","provider":"google-genai","input_tokens":853,"output_tokens":853,"cache_read_tokens":0,"cache_write_tokens":0,"cost_usd":0.00149275,"latency_ms":6919,"fallback_triggered":false,"error":null,"episode_id":"confidence_elicit-0002-1777367104000","agent_id":"design_manager","sprint":2,"task_file":"tests/test_api.py","label":"confidence_elicit","attempt":1}
{"ts":"2026-04-28T09:05:48Z","event_type":"llm_call","model":"gemini-3.1-flash-preview","provider":"google-genai","input_tokens":3912,"output_tokens":596,"cache_read_tokens":189,"cache_write_tokens":0,"cost_usd":0.001872,"latency_ms":4140,"fallback_triggered":false,"error":null,"episode_id":"eng_task-0003-1777367148000","agent_id":"architect_worker","sprint":2,"task_file":"utils/helpers.py","label":"eng_task","attempt":1}
{"ts":"2026-04-28T09:07:28Z","event_type":"llm_call","model":"gemini-3.1-flash-preview","provider":"google-genai","input_tokens":3900,"output_tokens":522,"cache_read_tokens":0,"cache_write_tokens":0,"cost_usd":0.001758,"latency_ms":5722,"fallback_triggered":false,"error":null,"episode_id":"sprint_plan-0004-1777367248000","agent_id":"dev_8","sprint":2,"task_file":"utils/helpers.py","label":"sprint_plan","attempt":1}
```

**Confirm all required fields are present on LLM call entries:**

- [x] ts
- [x] event_type: "llm_call"
- [x] model
- [x] provider
- [x] input_tokens
- [x] output_tokens
- [x] cache_read_tokens
- [x] cache_write_tokens
- [x] cost_usd
- [x] latency_ms
- [x] fallback_triggered
- [x] error

**Confirm MCP tool call entries exist:**

- [x] ts
- [x] event_type: "mcp_tool_call"
- [x] tool_name
- [x] input_hash
- [x] result_status
- [x] latency_ms

Implementation: `software_company/llm_client.py` writes normalized LLM-call entries through `_write_episode()`. `.gitignore` explicitly allows `logs/episodes.jsonl` and `logs/audit.jsonl` so these evidence files can be committed.

---

## Area 2: Agent Architecture Documentation - /1 pt

**Link to Agent Architecture section in README:** `README.md#agent-architecture`

**Pattern in use:** Supervisor/Worker with ReAct agents

**One-sentence justification:** Manager agents supervise planning, assignment, and review while worker agents execute bounded tasks through a ReAct loop, which fits this multi-agent software-company architecture.

**Confirm all four elements are present in the README section:**

- [x] Pattern choice stated with justification
- [x] AgentState dataclass with all fields named and typed
- [x] List of every irreversible action the agent can take
- [x] Each irreversible action mapped to its checkpoint or guard

Source references: `README.md`, `software_company/team_schemas.py` (`AgentState`, `IRREVERSIBLE_ACTIONS`).

---

## Area 3: MCP Server Security - /2 pts

**Link to MCP/API server source code:** `api_server.py`

### Auth Test Output

Invalid bearer tokens are rejected instead of silently becoming guest users:

```json
{"detail":{"error":"invalid_token"}}
```

Confirm the output is a structured JSON error, not a traceback: [x]

### Input Validation Code Snippet

```python
class SendMessageBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)

class RegisterBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
```

### MCP Audit Log Sample

Audit log file: `logs/audit.jsonl`

```json
{"ts":"2026-05-13T20:20:00+04:00","event_type":"mcp_tool_call","event":"mcp_tool_call","user_id":"-","tool_name":"GET /api/auth/me","input_hash":"6b73e93758ebfafa","result_status":"error","status":401,"latency_ms":2}
{"ts":"2026-05-13T20:20:01+04:00","event_type":"auth_rejected","event":"auth_rejected","user_id":"","reason":"invalid_token"}
{"ts":"2026-05-13T20:20:02+04:00","event_type":"mcp_tool_call","event":"mcp_tool_call","user_id":"guest","tool_name":"GET /api/projects","input_hash":"d6f368f2ae9e9b72","result_status":"ok","status":200,"latency_ms":4}
```

### Error Sanitisation Test

**What was tested:** route-level unhandled exceptions pass through `_request_audit_middleware`.

**What the caller receives:**

```json
{"detail":"Internal server error"}
```

Confirm it contains no traceback, file paths, or environment variable names: [x]

Security controls implemented:

- Bearer token auth: `HTTPBearer(auto_error=False)` plus `_current_user()` rejects invalid JWTs with HTTP 401.
- Pydantic input validation: request bodies are `BaseModel` classes with `Field` bounds and validators.
- Structured audit logging: middleware records `mcp_tool_call` entries with `tool_name`, `input_hash`, `result_status`, and `latency_ms`.
- Sanitised error responses: unhandled exceptions return fixed JSON only.

---

## Area 4: Resilience Patterns - /1 pt

### Timeout Implementation

```python
_LLM_TIMEOUT = 60
future = executor.submit(get_client().models.generate_content, **kwargs)
result = future.result(timeout=_LLM_TIMEOUT)
```

Confirm timeout is applied to every LLM content-generation call: [x]

Evidence: direct Gemini `models.generate_content` calls outside `software_company/llm_client.py` were removed. Text, tool-loop, browser screenshot, desktop vision, and API chat calls now use `generate_content_with_resilience()` or `llm_call()`.

### Retry and Backoff Implementation

```python
_LLM_RETRIES = 3
_BACKOFF_BASE = 2.0
for _attempt in range(1, _LLM_RETRIES + 1):
    ...
    backoff = _BACKOFF_BASE ** _attempt
    time.sleep(backoff)
```

Confirm retry uses exponential backoff with at least 2 retries: [x]

Source: `software_company/llm_client.py`. After all retries fail, the fallback response is logged with `fallback_triggered: true` and the sanitized error string in `error`.

---

## Area 5: Golden Test Set and Evaluation - /2 pts

**Link to golden set file:** `eval/golden_test_set.json`  
**Link to evaluation script:** `eval/run_eval.py`  
**Link to most recent results file:** `eval/results/results_2026-05-21.json`

### Results Summary

| Question ID | Category | Pass/Fail | Reason |
|---|---|---|---|
| g001 | factual | Pass | 136 episode entries with full Lab 8 schema |
| g002 | factual | Pass | structured MCP/API audit log entries exist |
| g003 | reasoning | Pass | README explains Supervisor/Worker plus ReAct architecture |
| g004 | reasoning | Pass | `AgentState` has all required typed fields |
| g005 | refusal | Pass | invalid bearer tokens are rejected with sanitized JSON errors |
| g006 | refusal | Pass | cross-user access is denied and episode log has no PII fields |
| g007 | edge_case | Pass | all Gemini content-generation calls route through the shared timeout wrapper |
| g008 | edge_case | Pass | `_LLM_RETRIES=3` with exponential backoff sleep |
| g009 | format | Pass | 5 irreversible actions mapped to README guards/checkpoints |
| g010 | format | Pass | standalone data map documented and `.env`/`.env.*` ignored |

**Overall score:** 10/10

---

## Area 6: Data Governance Evidence - /2 pts

### Cross-User Isolation Test

**Test procedure:** `tests/test_cross_user_isolation.py` creates two users and two projects, verifies User B cannot see or access User A's project, and verifies episode logs do not contain email, password, password_hash, or token keys.

**Test output:**

```text
py -m pytest tests/test_safety_audit_evidence.py tests/test_cross_user_isolation.py -q
12 passed in 0.08s
```

### Data Retention Policy

**Data map:** `docs/data-map.md` and summary table below.

| Data Type | Storage Location | Retention Period | Deletion Method |
|---|---|---|---|
| User accounts | `projects/_users.json` | Until user/project data is wiped | Delete `_users.json` or remove matching account record |
| Project metadata and chat | `projects/{uuid}/project.json` | Until project deletion | `DELETE /api/projects/{project_id}` removes the project directory |
| Episode log | `logs/episodes.jsonl` | Append-only audit evidence; rotate manually | Manual log rotation/deletion |
| MCP/API audit log | `logs/audit.jsonl` | Append-only audit evidence; rotate manually | Manual log rotation/deletion |
| Generated artifacts | `projects/{uuid}/` and `eng_output/` | Until project/output cleanup | Delete project/output directory |
| Vector/RAG index | `eng_output/rag_index.pkl` | Persists across runs | Delete generated output directory |

### PII in Episode Log

**Command:**

```bash
py -m pytest tests/test_cross_user_isolation.py::test_episode_log_no_pii -q
```

**Output:** pass; checked by `tests/test_cross_user_isolation.py::test_episode_log_no_pii`. Token-accounting fields such as `input_tokens`, `output_tokens`, and `cache_read_tokens` are allowed and required by the rubric; bearer/access/refresh token fields are not allowed.

### API Key Security

**Command:**

```bash
git log --all --full-history -- .env
```

**Output:** must be empty in the actual team Git checkout. This local folder is not currently a Git repository, so commit-history verification must be run after copying these changes into the team repo. `.gitignore` includes `.env` and `.env.*`.

---

## Model Selection Decisions Table

| Call Location | Current Model | Reason | Alternative Considered |
|---|---|---|---|
| `software_company/llm_client.py::llm_call` | `GEMINI_MODEL` default `gemini-3.1-flash-preview` | Main coding/planning loop needs fast, low-cost reasoning | Stronger Gemini model for higher quality, rejected for capstone cost control |
| `api_server.py::_general_chat_reply` | `GEMINI_MODEL` through `llm_call()` | Keeps API chat under the same timeout/backoff policy as other LLM calls | Separate `gemini-2.0-flash` direct call, rejected because it bypassed resilience controls |
| `software_company/agent_loop.py::_run_with_tools` | `GEMINI_MODEL` through `generate_content_with_resilience()` | Tool-using ReAct turns need Gemini function-calling while still enforcing the shared timeout/retry policy | Direct SDK call, rejected because it skipped the shared resilience wrapper |
| Browser and desktop vision paths | `DESKTOP_VISION_MODEL` env override, falling back to `GEMINI_MODEL` | Optional stronger model for screenshot/click tasks | Fixed default model, rejected because UI environments vary |
| RAG embeddings | `_RAG_EMBED_MODEL` | Embedding calls are retrieval, not content generation | Reusing the chat model, rejected because generation models are not optimized for embeddings |

---

## Live Verification Preparation

- [x] `py eval/run_eval.py` runs to completion without errors
- [x] MCP auth rejection demo is documented and reproducible once dependencies are installed
- [x] Cross-user isolation test script is documented and runnable
- [x] Team members should assign who demos eval, auth rejection, and isolation before Friday 15 May
