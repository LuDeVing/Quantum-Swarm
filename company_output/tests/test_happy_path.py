
import pytest
from fastapi.testclient import TestClient
from code.main import app

client = TestClient(app)

def test_happy_path_task_lifecycle():
    # 1. Create
    create_response = client.post("/tasks", json={"title": "Lifecycle Task", "status": "todo"})
    assert create_response.status_code == 200
    task_id = create_response.json()["id"]

    # 2. Get
    get_response = client.get(f"/tasks/{task_id}")
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "Lifecycle Task"

    # 3. Update
    put_response = client.put(f"/tasks/{task_id}", json={"title": "Updated Task", "status": "done"})
    assert put_response.status_code == 200
    assert put_response.json()["status"] == "done"

    # 4. Delete
    delete_response = client.delete(f"/tasks/{task_id}")
    assert delete_response.status_code == 200
    
    # 5. Verify gone
    assert client.get(f"/tasks/{task_id}").status_code == 404
