import pytest
import asyncio
from httpx import AsyncClient

@pytest.fixture
async def client():
    # Placeholder for application client setup
    # In a real setup, this would import the FastAPI app
    # from src.main import app
    pass

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
