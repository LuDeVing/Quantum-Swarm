# Data Map and Governance

This document is the data-governance evidence for the Lab 8 Safety and Evaluation Audit.

## Stored Data

| Data Type | Storage Location | Contains | Retention Period | Deletion Method |
|---|---|---|---|---|
| User accounts | `projects/_users.json` | User id, display name, normalized email, password hash, avatar path | Until account/project data is intentionally wiped | Delete `projects/_users.json` or remove the matching user record |
| Project metadata | `projects/{uuid}/project.json` | Project id, owner id, name, status, timestamps, messages, runner pid | Until project deletion | `DELETE /api/projects/{project_id}` removes the project directory after owner-id authorization |
| Project generated artifacts | `projects/{uuid}/` | Generated app files, dashboard state, task tree, component graph, memory, design hints | Until project cleanup | Delete the project directory or call the project deletion endpoint |
| Shared engineering output | `eng_output/` | Current generated code output, dashboard, task queue, design notes, RAG index | Until manual cleanup or next run overwrite | Delete `eng_output/` |
| Episode log | `logs/episodes.jsonl` | LLM-call metadata: timestamps, model/provider, token counts, cache-read tokens, latency, fallback flag, sanitized error text | Append-only audit evidence; rotate manually | Manual log rotation or deletion after audit retention need expires |
| MCP/API audit log | `logs/audit.jsonl` | Structured API/tool-call records: event type, user id, route/tool name, input hash, result status, status code, latency | Append-only audit evidence; rotate manually | Manual log rotation or deletion after audit retention need expires |
| Vector/RAG index | `eng_output/rag_index.pkl` and project-local `rag_index.pkl` files | Embeddings/index data for generated code retrieval | Persists across runs until output cleanup | Delete the generated output or project directory |
| Long-term role memory | `eng_output/memory/*.json` and project-local `memory/*.json` | Role lessons, graph nodes, graph edges, factual memory extracted from generated outputs | Persists until manual cleanup | Delete the relevant memory JSON files |

## Isolation Controls

User-owned project records include `owner_id`. API routes that list or access projects compare that owner id against the authenticated bearer-token user id. The regression evidence is in `tests/test_cross_user_isolation.py`:

- `test_cross_user_access_denied`
- `test_owner_access_allowed`
- `test_list_projects_filesystem_isolation`
- `test_episode_log_no_pii`

## PII Controls

Episode logs are limited to operational metadata. They must not include email addresses, password material, bearer tokens, or access/refresh tokens. Token-accounting fields such as `input_tokens`, `output_tokens`, and `cache_read_tokens` are allowed and required by the rubric.

PII check:

```bash
py -m pytest tests/test_cross_user_isolation.py::test_episode_log_no_pii -q
```

## Secret Controls

`.gitignore` excludes `.env`, `.env.*`, and `secrets.toml`. The required history check must be run in the actual Git checkout:

```bash
git log --all --full-history -- .env
```

Expected output: empty.
