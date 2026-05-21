#!/usr/bin/env python
"""
Golden test set evaluator for the Quantum Swarm Lab 8 safety audit.

The golden set is phrased as ten audit questions, but the evaluator is fully
offline and deterministic: it checks committed files, source code, and logs
instead of making live model calls.

Usage:
    python eval/run_eval.py

Writes results to eval/results/results_YYYY-MM-DD.json.
Exit code 0 if >= 7 of 10 pass, 1 otherwise.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
GOLDEN = ROOT / "eval" / "golden_test_set.json"
RESULTS_DIR = ROOT / "eval" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _read_source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _jsonl(rel: str) -> list[dict]:
    path = ROOT / rel
    if not path.exists():
        raise FileNotFoundError(rel)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def check_episode_log_100_entries() -> tuple[bool, str]:
    required = {
        "ts",
        "event_type",
        "model",
        "provider",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "cost_usd",
        "latency_ms",
        "fallback_triggered",
        "error",
    }
    try:
        entries = _jsonl("logs/episodes.jsonl")
    except FileNotFoundError:
        return False, "logs/episodes.jsonl does not exist"
    if len(entries) < 100:
        return False, f"Only {len(entries)} entries; need >= 100"
    for idx, entry in enumerate(entries, 1):
        missing = required - set(entry)
        if missing:
            return False, f"Line {idx} missing required fields: {sorted(missing)}"
        if entry["event_type"] != "llm_call":
            return False, f"Line {idx} has event_type={entry['event_type']!r}"
    return True, f"{len(entries)} entries with full Lab 8 LLM-call schema"


def check_mcp_audit_log_entries() -> tuple[bool, str]:
    required = {"tool_name", "input_hash", "result_status", "latency_ms"}
    try:
        entries = _jsonl("logs/audit.jsonl")
    except FileNotFoundError:
        return False, "logs/audit.jsonl does not exist"
    tool_entries = [entry for entry in entries if entry.get("event_type") == "mcp_tool_call"]
    if len(tool_entries) < 2:
        return False, f"Only {len(tool_entries)} mcp_tool_call entries found"
    for idx, entry in enumerate(tool_entries, 1):
        missing = required - set(entry)
        if missing:
            return False, f"MCP audit entry {idx} missing {sorted(missing)}"
    return True, f"{len(tool_entries)} structured MCP/API tool-call audit entries"


def check_readme_agent_architecture() -> tuple[bool, str]:
    readme = _read_source("README.md").lower()
    markers = [
        "## agent architecture",
        "supervisor/worker",
        "manager agents",
        "specialist workers",
        "react",
        "## model selection decisions",
        "## safety audit evidence",
    ]
    missing = [marker for marker in markers if marker not in readme]
    if missing:
        return False, f"README Agent Architecture section missing: {missing}"
    return True, "README documents Supervisor/Worker plus ReAct architecture"


def check_agent_state_dataclass_fields() -> tuple[bool, str]:
    src = _read_source("software_company/team_schemas.py")
    tree = ast.parse(src)
    required = {
        "agent_id",
        "role",
        "sprint",
        "task_file",
        "belief_healthy",
        "belief_uncertain",
        "belief_confused",
        "free_energy",
        "anomaly_detected",
        "call_count",
        "tokens_in",
        "tokens_out",
        "cache_read_tokens",
        "token_budget_remaining",
        "last_stance",
        "consecutive_fallbacks",
    }
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "AgentState":
            has_dataclass = any(getattr(dec, "id", "") == "dataclass" for dec in node.decorator_list)
            fields = {stmt.target.id for stmt in node.body if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)}
            missing = required - fields
            if not has_dataclass:
                return False, "AgentState exists but is not decorated with @dataclass"
            if missing:
                return False, f"AgentState missing typed fields: {sorted(missing)}"
            return True, f"AgentState dataclass has {len(fields)} typed fields, including all required audit fields"
    return False, "AgentState class not found"


def check_irreversible_actions_guarded() -> tuple[bool, str]:
    src = _read_source("software_company/team_schemas.py")
    readme = _read_source("README.md")
    match = re.search(r"IRREVERSIBLE_ACTIONS:\s*dict\[str,\s*str\]\s*=\s*\{(?P<body>.*?)\n\}", src, re.S)
    if not match:
        return False, "IRREVERSIBLE_ACTIONS map not found"
    actions = re.findall(r'"([^"]+)":', match.group("body"))
    if len(actions) < 4:
        return False, f"Only {len(actions)} irreversible actions found"
    missing_in_readme = [action for action in actions if f"`{action}`" not in readme]
    guard_markers = ["checkpoint", "guard", "required `think`", "owner-id guard", "test gate"]
    if missing_in_readme:
        return False, f"README does not document actions: {missing_in_readme}"
    if not any(marker in readme.lower() for marker in guard_markers):
        return False, "README action map does not mention checkpoints or guards"
    return True, f"{len(actions)} irreversible actions mapped to README guards/checkpoints"


def check_api_security_controls() -> tuple[bool, str]:
    src = _read_source("api_server.py")
    checks = {
        "HTTPBearer auth": "HTTPBearer" in src and "bearer = HTTPBearer" in src,
        "invalid-token rejection": "invalid_token" in src and "WWW-Authenticate" in src,
        "Pydantic validation": "BaseModel" in src and "Field(" in src and "@validator" in src,
        "structured audit logging": "mcp_tool_call" in src and "input_hash" in src and "result_status" in src,
        "sanitized internal errors": 'content={"detail": "Internal server error"}' in src,
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        return False, "Missing controls: " + ", ".join(failed)
    return True, "Bearer auth, Pydantic validation, audit logging, and sanitized errors are present"


def check_all_generate_content_calls_resilient() -> tuple[bool, str]:
    helper_src = _read_source("software_company/llm_client.py")
    if "def generate_content_with_resilience" not in helper_src:
        return False, "generate_content_with_resilience helper is missing"
    if "future.result(timeout=_LLM_TIMEOUT)" not in helper_src:
        return False, "helper does not enforce _LLM_TIMEOUT"
    direct = []
    for path in (ROOT / "software_company").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        if path.name == "llm_client.py":
            continue
        if "models.generate_content" in src or "google.generativeai" in src:
            direct.append(str(path.relative_to(ROOT)))
    api_src = _read_source("api_server.py")
    if "models.generate_content" in api_src or "google.generativeai" in api_src:
        direct.append("api_server.py")
    if direct:
        return False, "Direct content-generation calls bypass wrapper: " + ", ".join(direct)
    return True, "All non-wrapper Gemini content-generation calls use generate_content_with_resilience or llm_call"


def check_llm_retry_backoff_policy() -> tuple[bool, str]:
    src = _read_source("software_company/llm_client.py")
    retries = re.search(r"_LLM_RETRIES\s*=\s*(\d+)", src)
    if not retries or int(retries.group(1)) < 3:
        return False, "_LLM_RETRIES missing or < 3"
    markers = ["_BACKOFF_BASE", "_BACKOFF_BASE ** attempt", "time.sleep(backoff)"]
    missing = [marker for marker in markers if marker not in src]
    if missing:
        return False, f"Backoff markers missing: {missing}"
    return True, f"_LLM_RETRIES={retries.group(1)} with exponential backoff sleep"


def check_cross_user_isolation_and_no_pii() -> tuple[bool, str]:
    tests = _read_source("tests/test_cross_user_isolation.py")
    api_src = _read_source("api_server.py")
    markers = [
        "test_cross_user_access_denied",
        "test_list_projects_filesystem_isolation",
        "test_episode_log_no_pii",
    ]
    missing = [marker for marker in markers if marker not in tests]
    if missing:
        return False, f"Isolation/PII tests missing: {missing}"
    if "owner_id" not in api_src or 'user["id"]' not in api_src:
        return False, "api_server.py owner_id isolation guard not found"
    email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    banned_keys = {"email", "password", "password_hash", "token", "access_token", "refresh_token"}
    for lineno, entry in enumerate(_jsonl("logs/episodes.jsonl"), 1):
        found_keys = banned_keys & set(entry)
        if found_keys:
            return False, f"PII field(s) {sorted(found_keys)} found on episode line {lineno}"
        if email_pattern.search(json.dumps(entry, ensure_ascii=False)):
            return False, f"Email-like value found on episode line {lineno}"
    return True, "Cross-user isolation tests exist and episode log has no email/password/token markers"


def check_data_map_and_env_ignored() -> tuple[bool, str]:
    doc = _read_source("docs/safety-audit.md")
    data_map_path = ROOT / "docs" / "data-map.md"
    if not data_map_path.exists():
        return False, "docs/data-map.md is missing"
    data_map = data_map_path.read_text(encoding="utf-8")
    ignore = _read_source(".gitignore")
    doc_markers = ["Data Retention Policy", "Data Type", "Storage Location", "Deletion Method"]
    data_map_markers = ["Stored Data", "Isolation Controls", "PII Controls", "Secret Controls"]
    ignore_markers = [".env", ".env.*"]
    missing_doc = [marker for marker in doc_markers if marker not in doc]
    if "docs/data-map.md" not in doc:
        missing_doc.append("docs/data-map.md")
    missing_data_map = [marker for marker in data_map_markers if marker not in data_map]
    missing_ignore = [marker for marker in ignore_markers if marker not in ignore]
    if missing_doc or missing_data_map or missing_ignore:
        return False, (
            f"Missing safety-audit markers={missing_doc}, "
            f"data-map markers={missing_data_map}, gitignore markers={missing_ignore}"
        )
    return True, "Standalone data map is documented and .env/.env.* are ignored"


CHECKS = {
    "episode_log_100_entries": check_episode_log_100_entries,
    "mcp_audit_log_entries": check_mcp_audit_log_entries,
    "readme_agent_architecture": check_readme_agent_architecture,
    "agent_state_dataclass_fields": check_agent_state_dataclass_fields,
    "irreversible_actions_guarded": check_irreversible_actions_guarded,
    "api_security_controls": check_api_security_controls,
    "all_generate_content_calls_resilient": check_all_generate_content_calls_resilient,
    "llm_retry_backoff_policy": check_llm_retry_backoff_policy,
    "cross_user_isolation_and_no_pii": check_cross_user_isolation_and_no_pii,
    "data_map_and_env_ignored": check_data_map_and_env_ignored,
}


def main() -> int:
    questions = json.loads(GOLDEN.read_text(encoding="utf-8"))
    results = []
    passed = 0

    for q in questions:
        check_fn = CHECKS.get(q["check"])
        if check_fn is None:
            ok, detail = False, f"No check implementation for {q['check']!r}"
        else:
            try:
                ok, detail = check_fn()
            except Exception as exc:  # keep evaluator output structured for grading
                ok, detail = False, f"Exception: {type(exc).__name__}: {exc}"

        status = "PASS" if ok else "FAIL"
        passed += int(ok)
        print(f"[{status}] {q['id']} ({q['category']}) - {q['question']}")
        print(f"       {detail}")
        results.append({
            "id": q["id"],
            "category": q["category"],
            "type": q.get("type", ""),
            "question": q["question"],
            "expected_answer": q.get("expected_answer", ""),
            "status": status,
            "detail": detail,
            "pass_criteria": q.get("pass_criteria", ""),
        })

    total = len(questions)
    print(f"\nResult: {passed}/{total} passed", end="")
    if passed >= 7:
        print(" [OK] threshold met")
    else:
        print(f" [FAIL] need >= 7, got {passed}")

    out_file = RESULTS_DIR / f"results_{date.today().isoformat()}.json"
    out_file.write_text(
        json.dumps({
            "date": date.today().isoformat(),
            "passed": passed,
            "total": total,
            "threshold": 7,
            "pass_rate": f"{passed / total * 100:.0f}%",
            "results": results,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Results written to {out_file.relative_to(ROOT)}")
    return 0 if passed >= 7 else 1


if __name__ == "__main__":
    sys.exit(main())
