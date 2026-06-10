import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server


@pytest.fixture()
def client(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(api_server, "PROJECTS_DIR", projects)
    monkeypatch.setattr(api_server, "USERS_FILE", projects / "_users.json")
    monkeypatch.setattr(api_server, "GENERAL_CHAT_FILE", projects / "_general_chat.json")
    project = projects / "demo"
    code = project / "code"
    (code / "src").mkdir(parents=True)
    (code / "tests").mkdir()
    (project / "project.json").write_text(json.dumps({
        "id": "demo", "name": "Demo", "owner_id": "guest", "status": "Completed",
        "date": "2026-01-01T00:00:00+00:00", "messages": [{"text": "build it"}],
    }), encoding="utf-8")
    (project / "task_queue_state.json").write_text(json.dumps({"tasks": {
        "main": {"id": "main", "file": "src/main.py", "status": "completed", "depends_on": []}
    }}), encoding="utf-8")
    (project / "TASK_TREE.json").write_text(json.dumps({
        "root_id": "root", "goal": "Demo", "nodes": {
            "root": {"id": "root", "name": "Goal", "description": "Demo", "complexity": "high"}
        }
    }), encoding="utf-8")
    (code / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (code / "tests" / "test_ok.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
    return TestClient(api_server.app)


def test_dashboard_contains_visual_journey(client):
    data = client.get("/api/projects/demo/dashboard").json()
    assert [step["key"] for step in data["workflow"]] == ["brief", "plan", "build", "test", "run", "deliver"]
    assert data["tree"]["nodes"][1]["file"] == "src/main.py"
    assert data["tree"]["edges"][0]["type"] == "hierarchy"


def test_artifact_content_is_contained(client):
    response = client.get("/api/projects/demo/artifacts/content", params={"path": "src/main.py"})
    assert response.status_code == 200
    assert "print" in response.json()["content"]
    assert client.get("/api/projects/demo/artifacts/content", params={"path": "../../api_server.py"}).status_code == 400


def test_skeleton_files_are_flagged_for_review(client):
    project = api_server.PROJECTS_DIR / "demo"
    (project / "code" / "src" / "main.py").write_text("# AUTO-GENERATED SKELETON\n# TODO: implement this file\n", encoding="utf-8")
    dashboard = client.get("/api/projects/demo/dashboard").json()
    artifacts = client.get("/api/projects/demo/artifacts").json()
    assert dashboard["tree"]["nodes"][1]["status"] == "needs_review"
    assert next(item for item in artifacts["artifacts"] if item["name"] == "src/main.py")["status"] == "needs_review"


def test_approved_verification_commands_run(client):
    test_result = client.post("/api/projects/demo/verification/run", json={"kind": "test"})
    run_result = client.post("/api/projects/demo/verification/run", json={"kind": "run"})
    assert test_result.json()["passed"] is True
    assert run_result.json()["passed"] is True
