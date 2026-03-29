import pytest
import httpx
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

BASE_URL = os.getenv("API_URL", "http://backend:8000")

@pytest.mark.asyncio
async def test_rapid_fire_task_creation():
    """
    Stress test for race conditions:
    Fire multiple simultaneous requests to verify atomicity and unique ID generation.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, headers={"Authorization": "Bearer stress-test"}) as client:
        tasks = [client.post("/api/v1/tasks", json={"title": f"Task {i}", "status": "todo"}) for i in range(10)]
        results = await asyncio.gather(*tasks)
        
        ids = set()
        for r in results:
            assert r.status_code == 201
            data = r.json()
            ids.add(data["id"])
        
        # Verify 10 unique tasks created
        assert len(ids) == 10
