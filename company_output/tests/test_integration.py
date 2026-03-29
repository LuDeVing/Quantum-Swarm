
import pytest
from httpx import AsyncClient

BACKEND_URL = "http://backend:8000"

@pytest.mark.asyncio
async def test_api_contract_post_task():
    async with AsyncClient(base_url=BACKEND_URL) as client:
        # Test valid creation
        resp = await client.post("/tasks", json={"title": "Test Task"})
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] == "Test Task"
        assert "created_at" in data

@pytest.mark.asyncio
async def test_api_contract_invalid_payload():
    async with AsyncClient(base_url=BACKEND_URL) as client:
        # Empty title (violates 1-100 constraint)
        resp = await client.post("/tasks", json={"title": ""})
        assert resp.status_code == 422
