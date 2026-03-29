import httpx
import logging
from typing import Any, Dict, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class APIClient:
    """
    A resilient API client for interacting with the task management backend.
    """
    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def get(self, endpoint: str) -> Dict[str, Any]:
        """Performs a GET request to the specified endpoint."""
        try:
            response = await self.client.get(endpoint)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

    async def post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Performs a POST request to the specified endpoint."""
        try:
            response = await self.client.post(endpoint, json=data)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

    async def close(self):
        """Closes the underlying HTTP client."""
        await self.client.aclose()
