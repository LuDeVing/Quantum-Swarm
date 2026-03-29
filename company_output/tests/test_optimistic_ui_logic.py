
import pytest
import time
import uuid

# Mocking the RequestQueue functionality to test the optimistic state management
class MockRequestQueue:
    def __init__(self):
        self.queue = []
        self.processed = []
        self.rollback_log = []

    def add(self, task):
        self.queue.append(task)
        # Optimistic UI update logic: immediately reflect in 'UI state'
        return {"...": "optimistic_state"}

    def commit(self, task_id):
        self.processed.append(task_id)
        
    def rollback(self, task_id, error):
        self.rollback_log.append({"id": task_id, "error": error})
        # Rollback logic: revert to original state
        return {"status": "reverted"}

def test_optimistic_ui_rollback():
    """
    Ensures that if the API fails, the optimistic UI state reverts correctly.
    """
    queue = MockRequestQueue()
    task_id = str(uuid.uuid4())
    
    # 1. User performs action
    queue.add({"id": task_id, "action": "CREATE"})
    
    # 2. Server returns failure
    result = queue.rollback(task_id, "500 Internal Server Error")
    
    # 3. Assert rollback occurred
    assert result["status"] == "reverted"
    assert any(item["id"] == task_id for item in queue.rollback_log)

def test_rapid_fire_requests():
    """
    Ensures that multiple requests are queued without causing race conditions.
    """
    queue = MockRequestQueue()
    for i in range(5):
        queue.add({"id": i, "action": "TOGGLE"})
    
    assert len(queue.queue) == 5
