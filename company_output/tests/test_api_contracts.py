
import pytest
from fastapi.testclient import TestClient
from code.main import app

client = TestClient(app)

def test_create_task_validation():
    # Test valid task creation
    response = client.post("/tasks", json={"title": "Test Task", "status": "todo"})
    assert response.status_code == 200
    
    # Test invalid title length (empty)
    response = client.post("/tasks", json={"title": "", "status": "todo"})
    assert response.status_code == 422
    
    # Test invalid title length (>100)
    response = client.post("/tasks", json={"title": "a" * 101, "status": "todo"})
    assert response.status_code == 422

def test_invalid_status_enum():
    response = client.post("/tasks", json={"title": "Task", "status": "invalid"})
    assert response.status_code == 422

def test_read_nonexistent_task():
    response = client.get("/tasks/999")
    assert response.status_code == 404
