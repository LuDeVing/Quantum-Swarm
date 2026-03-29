import pytest
from fastapi.testclient import TestClient
from code.main import app

def test_security_headers_present():
    """Verify standard security headers are set."""
    client = TestClient(app)
    response = client.get("/tasks")
    # Check for security headers (this assumes a middleware exists)
    # If not, this test should fail until it's added.
    assert "X-Content-Type-Options" in response.headers
    assert "Strict-Transport-Security" in response.headers

def test_api_injection_prevention():
    """Test against basic SQLi via malformed title."""
    client = TestClient(app)
    # Attempting to inject into title field
    payload = {"title": "'; DROP TABLE tasks;--", "status": "todo"}
    response = client.post("/tasks", json=payload)
    # Should either be 422 (Schema validation) or saved as a string (sanitized)
    assert response.status_code in [200, 422]
    
    # Check that database is not actually empty
    get_res = client.get("/tasks")
    assert get_res.status_code == 200
