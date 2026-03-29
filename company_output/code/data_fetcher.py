from typing import List, Dict, Any
from api_client import APIClient

class TaskDataFetcher:
    """
    Business logic layer for fetching task-related data.
    """
    def __init__(self, client: APIClient):
        self.client = client

    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Fetches all tasks from the backend."""
        return await self.client.get('/tasks')

    async def create_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Submits a new task to the backend."""
        return await self.client.post('/tasks', task_data)
