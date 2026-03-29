
import pytest
from unittest.mock import AsyncMock, patch
from code.src.services.requestQueue import RequestQueue

@pytest.fixture
def queue():
    return RequestQueue()

@pytest.mark.asyncio
async def test_request_queue_retry_logic_on_failure(queue):
    """
    Edge Case: Verify queue stops processing and preserves state on backend failure.
    """
    with patch('code.src.services.requestQueue.RequestQueue.syncWithBackend', new_callable=AsyncMock) as mock_sync:
        mock_sync.side_effect = Exception("Network Error")
        
        await queue.add({'action': 'add', 'data': {'title': 'Fail Task'}})
        
        # Queue should have 1 item left (the one that failed)
        assert len(queue.queue) == 1
        assert mock_sync.call_count == 1

@pytest.mark.asyncio
async def test_request_queue_handles_malformed_payload(queue):
    """
    Edge Case: Verify system handles malformed data without crashing the queue.
    """
    # Assuming the syncWithBackend throws or rejects bad input
    with patch('code.src.services.requestQueue.RequestQueue.syncWithBackend', new_callable=AsyncMock) as mock_sync:
        mock_sync.side_effect = ValueError("Invalid Payload")
        
        await queue.add({'action': 'add', 'data': {}}) # Missing title
        
        assert len(queue.queue) == 1
        assert mock_sync.call_count == 1

@pytest.mark.asyncio
async def test_race_condition_protection(queue):
    """
    Race Condition Protection: Ensure multiple simultaneous additions are queued 
    rather than causing overlapping execution.
    """
    with patch('code.src.services.requestQueue.RequestQueue.syncWithBackend', new_callable=AsyncMock) as mock_sync:
        mock_sync.return_value = None
        
        # Fire two requests quickly
        await queue.add({'action': 'add', 'data': {'title': 'Task 1'}})
        await queue.add({'action': 'add', 'data': {'title': 'Task 2'}})
        
        assert mock_sync.call_count == 2
        assert len(queue.queue) == 0
