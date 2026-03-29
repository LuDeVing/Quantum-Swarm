import logging
import asyncio
from typing import Any, Callable, TypeVar, ParamSpec

T = TypeVar("T")
P = ParamSpec("P")

logger = logging.getLogger(__name__)

class ResilienceWrapper:
    """
    Implements simple circuit-breaker and retry logic for API calls.
    """
    def __init__(self, retries: int = 3, backoff: float = 0.5):
        self.retries = retries
        self.backoff = backoff
        self.failure_count = 0
        self.max_failures = 5
        self.is_open = False

    async def execute(self, func: Callable[P, Any], *args: P.args, **kwargs: P.kwargs) -> Any:
        if self.is_open:
            raise Exception("Circuit breaker is OPEN. Failing fast.")

        for attempt in range(self.retries):
            try:
                result = await func(*args, **kwargs)
                self.failure_count = 0
                return result
            except Exception as e:
                self.failure_count += 1
                if self.failure_count >= self.max_failures:
                    self.is_open = True
                    logger.critical("Circuit breaker tripped!")
                
                if attempt == self.retries - 1:
                    raise e
                
                wait = self.backoff * (2 ** attempt)
                logger.warning(f"Request failed, retrying in {wait}s... (attempt {attempt + 1})")
                await asyncio.sleep(wait)
