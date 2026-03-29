import pytest
import requests
import os

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

def test_crud_flow():
    """
    Integration test verifying the full CRUD flow for the Task entity.
    This fulfills the requirement of contract validation.
    """
    # 1. Create a task
    response = requests.post(f"{BACKEND_URL}/tasks", json={"title": "Contract Test Task", "status": "todo"})
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    task = response.json()
    task_id = task["id"]

    # 2. Get task
    response = requests.get(f"{BACKEND_URL}/tasks/{task_id}")
    assert response.status_code == 200

    # 3. Update task
    response = requests.put(f"{BACKEND_URL}/tasks/{task_id}", json={"title": "Updated Title", "status": "done"})
    assert response.status_code == 200
    assert response.json()["status"] == "done"

    # 4. Delete task
    response = requests.delete(f"{BACKEND_URL}/tasks/{task_id}")
    assert response.status_code == 200

def test_invalid_input_fails():
    """Verify that malformed data triggers error states."""
    response = requests.post(f"{BACKEND_URL}/tasks", json={"title": ""}) # Min length violation
    assert response.status_code == 422 # FastAPI validation error
