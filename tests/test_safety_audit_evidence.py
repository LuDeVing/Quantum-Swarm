"""Safety-audit evidence checks for Lab 8."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_episode_log_matches_lab8_schema():
    log = ROOT / "logs" / "episodes.jsonl"
    assert log.exists(), "logs/episodes.jsonl must be committed as audit evidence"

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
    lines = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 100

    for lineno, line in enumerate(lines, 1):
        entry = json.loads(line)
        assert required <= set(entry), f"line {lineno} missing {required - set(entry)}"
        assert entry["event_type"] == "llm_call"


def test_api_security_controls_are_evidenced_in_source():
    src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "HTTPBearer" in src
    assert "invalid_token" in src
    assert "BaseModel" in src and "Field(" in src and "@validator" in src
    assert "mcp_tool_call" in src and "input_hash" in src and "result_status" in src
    assert 'content={"detail": "Internal server error"}' in src


def test_audit_log_has_mcp_tool_call_entries():
    log = ROOT / "logs" / "audit.jsonl"
    assert log.exists(), "logs/audit.jsonl must be committed as MCP audit evidence"
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    tool_entries = [entry for entry in entries if entry.get("event_type") == "mcp_tool_call"]
    assert len(tool_entries) >= 2
    for entry in tool_entries:
        assert {"tool_name", "input_hash", "result_status", "latency_ms"} <= set(entry)


def test_all_content_generation_uses_resilience_wrapper():
    llm_src = (ROOT / "software_company" / "llm_client.py").read_text(encoding="utf-8")
    assert "def generate_content_with_resilience" in llm_src
    assert "future.result(timeout=_LLM_TIMEOUT)" in llm_src
    assert "_BACKOFF_BASE ** attempt" in llm_src
    assert "time.sleep(backoff)" in llm_src

    bypasses = []
    for path in (ROOT / "software_company").glob("*.py"):
        if path.name == "llm_client.py":
            continue
        src = path.read_text(encoding="utf-8")
        if "models.generate_content" in src or "google.generativeai" in src:
            bypasses.append(str(path.relative_to(ROOT)))

    api_src = (ROOT / "api_server.py").read_text(encoding="utf-8")
    if "models.generate_content" in api_src or "google.generativeai" in api_src:
        bypasses.append("api_server.py")

    assert not bypasses, f"LLM calls bypass resilience wrapper: {bypasses}"


def test_readme_and_data_map_expose_all_grading_evidence():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    for marker in [
        "## agent architecture",
        "## model selection decisions",
        "## safety audit evidence",
        "supervisor/worker",
        "agentstate",
        "irreversible action map",
        "mcp/api server security",
        "golden test set",
        "data governance",
    ]:
        assert marker in readme

    data_map = ROOT / "docs" / "data-map.md"
    assert data_map.exists()
    data_map_src = data_map.read_text(encoding="utf-8")
    for marker in ["Stored Data", "Isolation Controls", "PII Controls", "Secret Controls"]:
        assert marker in data_map_src


def test_golden_set_matches_lab8_template_shape():
    golden = json.loads((ROOT / "eval" / "golden_test_set.json").read_text(encoding="utf-8"))
    assert len(golden) == 10
    assert [item["id"] for item in golden] == [f"g{i:03d}" for i in range(1, 11)]
    assert [item["category"] for item in golden] == [
        "factual",
        "factual",
        "reasoning",
        "reasoning",
        "refusal",
        "refusal",
        "edge_case",
        "edge_case",
        "format",
        "format",
    ]
    for item in golden:
        assert item["question"].strip()
        assert item["expected_answer"].strip()
        assert item["pass_criteria"].strip()
        assert item["check"].strip()
