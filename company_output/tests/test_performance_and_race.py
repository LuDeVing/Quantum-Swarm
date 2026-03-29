
import httpx
import pytest
import asyncio
import os

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

@pytest.mark.asyncio
async def test_race_condition_create_task():
    """
    Test rapid-fire task creation to ensure database stability and atomic increments.
    """
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(10):
            tasks.append(client.post(f"{BACKEND_URL}/tasks", json={"title": f"Task {i}"}))
        
        responses = await asyncio.gather(*tasks)
        
        # Ensure all tasks created successfully
        for resp in responses:
            assert resp.status_code == 201
            
        # Verify total count
        get_resp = await client.get(f"{BACKEND_URL}/tasks")
        assert get_resp.status_code == 200
        assert len(get_resp.json()) == 10
