
import pytest
from fastapi.testclient import TestClient
from code.main import app

client = TestClient(app)

def test_root_path_not_exists():
    response = client.get("/")
    assert response.status_code == 404

def test_delete_nonexistent_task():
    response = client.delete("/tasks/999")
    assert response.status_code == 404

def test_put_nonexistent_task():
    response = client.put("/tasks/999", json={"title": "Updated", "status": "done"})
    assert response.status_code == 404
