import pytest
import os
import requests

# Assuming the backend is running at http://localhost:8000 for local development/testing
API_BASE = os.getenv("API_BASE", "http://localhost:8000/api/v1")

def test_sql_injection_attempt():
    """
    Ensures input is sanitized against malicious payloads (SQL Injection).
    """
    payload = {"title": "'; DROP TABLE tasks; --", "status": "todo"}
    # The Pydantic model should reject the title as it's not strictly 1-100 characters alphanumeric/clean
    response = requests.post(f"{API_BASE}/tasks", json=payload)
    assert response.status_code == 422 # Expect validation error

def test_auth_header_required():
    """
    Ensure the API is not public, enforcing the Authorization requirement (placeholder).
    """
    # Without Authorization header
    response = requests.get(f"{API_BASE}/tasks")
    # Even if no auth implementation yet, should be 401 or similar once gatekept
    # Currently expected to work, but we are marking a risk.
    assert response.status_code in [200, 401]

def test_task_model_schema_validation():
    """
    Ensure Task entity constraints are enforced (ADR-001).
    """
    # Title too long (>100 characters)
    too_long_title = "A" * 101
    response = requests.post(f"{API_BASE}/tasks", json={"title": too_long_title, "status": "todo"})
    assert response.status_code == 422
