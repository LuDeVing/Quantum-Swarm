import pytest
from fastapi.testclient import TestClient
from code.main import app
from code.schemas import TaskCreate

client = TestClient(app)

def test_api_schema_validation_on_post():
    """Verify that POST /tasks enforces schema constraints."""
    # Invalid: too short title
    response = client.post("/tasks", json={"title": "", "status": "todo"})
    assert response.status_code == 422

    # Invalid: invalid status
    response = client.post("/tasks", json={"title": "Test Task", "status": "invalid"})
    assert response.status_code == 422

def test_api_integration_crud_flow():
    """Test the full lifecycle of a task via the API."""
    # Create
    response = client.post("/tasks", json={"title": "Integration Task", "status": "todo"})
    assert response.status_code == 200
    task_id = response.json()["id"]

    # Read
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Integration Task"

    # Update
    response = client.put(f"/tasks/{task_id}", json={"title": "Updated Task", "status": "done"})
    assert response.status_code == 200
    assert response.json()["title"] == "Updated Task"
    assert response.json()["status"] == "done"

    # Delete
    response = client.delete(f"/tasks/{task_id}")
    assert response.status_code == 200

    # Verify Gone
    response = client.get(f"/tasks/{task_id}")
    assert response.status_code == 404
