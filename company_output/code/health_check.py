import json
from datetime import datetime

class HealthCheck:
    """Standardized health check response for the Task MVP."""
    
    @staticmethod
    def get_status() -> dict:
        """Returns application health status."""
        return {
            "status": "up",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0-MVP",
            "uptime_seconds": 0 # Placeholder for actual uptime logic
        }

    @staticmethod
    def get_response_body() -> str:
        """Returns JSON-formatted health check."""
        return json.dumps(HealthCheck.get_status())
