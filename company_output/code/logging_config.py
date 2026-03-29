import logging
import sys
from pathlib import Path

def setup_logging(name: str = "quantum_swarm_task_app"):
    """Configures centralized logging for the application."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Standard format for structured logging (JSON-ready later)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Console output for local dev / cloud logs
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    
    if not logger.handlers:
        logger.addHandler(handler)
        
    return logger
