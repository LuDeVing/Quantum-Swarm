import pytest
import httpx
import os
import uuid

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

@pytest.mark.asyncio
async def test_full_crud_lifecycle_persistence():
    """
    Verify full CRUD lifecycle: Create, Read, Update, Delete.
    Ensures persistent state works across requests using the actual API endpoints.
    """
    async with httpx.AsyncClient(base_url=BACKEND_URL) as client:
        # 1. Create
        task_data = {
            "title": f"Integration Test Task {uuid.uuid4()}",
            "description": "Integration test description",
            "status": "todo"
        }
        create_resp = await client.post("/tasks", json=task_data)
        assert create_resp.status_code == 200
        created_task = create_resp.json()
        task_id = created_task["id"]
        assert created_task["title"] == task_data["title"]

        # 2. Read
        read_resp = await client.get(f"/tasks/{task_id}")
        assert read_resp.status_code == 200
        assert read_resp.json()["id"] == task_id

        # 3. Update
        update_data = {
            "title": "Updated Task",
            "status": "in_progress"
        }
        update_resp = await client.put(f"/tasks/{task_id}", json=update_data)
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "in_progress"

        # 4. Delete
        delete_resp = await client.delete(f"/tasks/{task_id}")
        assert delete_resp.status_code == 200

        # Verify deletion
        get_after_delete = await client.get(f"/tasks/{task_id}")
        assert get_after_delete.status_code == 404

@pytest.mark.asyncio
async def test_update_non_existent_task_returns_404():
    """Verify that updating a non-existent task returns 404."""
    async with httpx.AsyncClient(base_url=BACKEND_URL) as client:
        update_data = {"title": "Ghost Task", "status": "done"}
        resp = await client.put("/tasks/999999", json=update_data)
        assert resp.status_code == 404

@pytest.mark.asyncio
async def test_invalid_status_transition_returns_422():
    """Verify that invalid status transitions are rejected by validation."""
    async with httpx.AsyncClient(base_url=BACKEND_URL) as client:
        task_data = {
            "title": "Invalid Status Task",
            "status": "invalid_status"
        }
        resp = await client.post("/tasks", json=task_data)
        assert resp.status_code == 422
