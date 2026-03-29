import pytest
import httpx
import os

# Base URLs configured for service-to-service communication in Docker Compose
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

@pytest.mark.asyncio
async def test_api_tasks_crud_flow():
    """
    Integration test verifying the full CRUD flow for the Task entity.
    Strictly adheres to the API Contract in ADR-001.
    """
    async with httpx.AsyncClient(base_url=BACKEND_URL, headers={"Authorization": "Bearer test-token"}) as client:
        # 1. Create a task
        response = await client.post("/api/v1/tasks", json={"title": "Test Task"})
        assert response.status_code == 201
        task = response.json()
        assert "id" in task
        assert task["title"] == "Test Task"
        task_id = task["id"]

        # 2. Get tasks
        response = await client.get("/api/v1/tasks")
        assert response.status_code == 200
        tasks = response.json()
        assert isinstance(tasks, list)
        assert any(t["id"] == task_id for t in tasks)

        # 3. Update task
        response = await client.put(f"/api/v1/tasks/{task_id}", json={"status": "COMPLETED"})
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"

        # 4. Delete task
        response = await client.delete(f"/api/v1/tasks/{task_id}")
        assert response.status_code == 204
