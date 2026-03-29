import pytest
from fastapi.testclient import TestClient
from code.main import app

client = TestClient(app)

def test_create_task_invalid_data_returns_422():
    # Test empty title (min_length=1)
    response = client.post("/tasks", json={"title": "", "status": "todo"})
    assert response.status_code == 422
    
    # Test title too long (max_length=100)
    response = client.post("/tasks", json={"title": "a" * 101, "status": "todo"})
    assert response.status_code == 422
    
    # Test invalid status
    response = client.post("/tasks", json={"title": "Valid title", "status": "invalid_status"})
    assert response.status_code == 422

def test_update_non_existent_task_returns_404():
    response = client.put("/tasks/99999", json={"title": "Does not exist", "status": "todo"})
    assert response.status_code == 404

def test_get_non_existent_task_returns_404():
    response = client.get("/tasks/99999")
    assert response.status_code == 404

def test_delete_non_existent_task_returns_404():
    response = client.delete("/tasks/99999")
    assert response.status_code == 404

def test_malformed_json_returns_422():
    # Sending string instead of object
    response = client.post("/tasks", content="not a json", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
