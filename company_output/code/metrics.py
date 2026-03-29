import time
from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class MetricsRegistry:
    """Simple in-memory metrics registry for the Task MVP."""
    _data: Dict[str, int] = field(default_factory=dict)
    
    def increment(self, metric_name: str):
        """Increments a counter."""
        self._data[metric_name] = self._data.get(metric_name, 0) + 1
        
    def get_metrics(self) -> Dict[str, int]:
        """Returns current snapshot of metrics."""
        return self._data

# Global instance for the application
registry = MetricsRegistry()

def record_request(endpoint: str):
    """Utility to record incoming requests."""
    registry.increment(f"http_requests_total_{endpoint}")
