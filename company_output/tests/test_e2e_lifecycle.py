import pytest
import os
import requests

# Set the base API URL
BASE_URL = os.getenv("API_URL", "http://localhost:8000")

def test_full_lifecycle():
    """
    Performs full CRUD E2E flow: Create -> Get -> Update -> Delete.
    """
    task_payload = {"title": "Full Cycle Task", "status": "todo"}
    
    # 1. Create
    resp_create = requests.post(f"{BASE_URL}/tasks", json=task_payload)
    assert resp_create.status_code == 201
    task = resp_create.json()
    task_id = task["id"]
    
    # 2. Get
    resp_get = requests.get(f"{BASE_URL}/tasks/{task_id}")
    assert resp_get.status_code == 200
    
    # 3. Update
    resp_update = requests.put(f"{BASE_URL}/tasks/{task_id}", json={"title": "Updated Title", "status": "done"})
    assert resp_update.status_code == 200
    
    # 4. Delete
    resp_delete = requests.delete(f"{BASE_URL}/tasks/{task_id}")
    assert resp_delete.status_code == 204
