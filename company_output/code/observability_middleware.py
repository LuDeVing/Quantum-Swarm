import time
import logging
from fastapi import Request, FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
import json
import sys

# Configure structured logging to stdout for observability
logger = logging.getLogger("quantum_swarm_logger")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
# Simplified JSON-like structure for logs
formatter = logging.Formatter('{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Process the request
        response = await call_next(request)
        
        process_time = time.time() - start_time
        
        # Log request details
        log_data = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration": f"{process_time:.4f}s"
        }
        logger.info(f"Request: {json.dumps(log_data)}")
        
        return response

def add_observability(app: FastAPI):
    app.add_middleware(ObservabilityMiddleware)
    
    # Health check route
    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "task-api"}
