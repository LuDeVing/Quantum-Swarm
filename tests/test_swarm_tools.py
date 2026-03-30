"""
test_swarm_tools.py — Unit tests for tool implementations.

Tests run_shell and http_request without executing real commands
or making real network calls.
"""
import pytest
from unittest.mock import patch, MagicMock
import software_company as sc


# ── _tool_run_shell ───────────────────────────────────────────────────────────

class TestRunShell:
    def test_success_returns_stdout(self):
        mock_result = MagicMock()
        mock_result.stdout = "hello world\n"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = sc._tool_run_shell("echo hello")
        assert "hello world" in result

    def test_stderr_included_in_output(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "some error\n"
        with patch("subprocess.run", return_value=mock_result):
            result = sc._tool_run_shell("bad command")
        assert "some error" in result

    def test_combined_stdout_and_stderr(self):
        mock_result = MagicMock()
        mock_result.stdout = "out"
        mock_result.stderr = "err"
        with patch("subprocess.run", return_value=mock_result):
            result = sc._tool_run_shell("cmd")
        assert "out" in result
        assert "err" in result

    def test_timeout_returns_error_message(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 120)):
            result = sc._tool_run_shell("sleep 999")
        assert "timed out" in result.lower()

    def test_exception_returns_error_message(self):
        with patch("subprocess.run", side_effect=OSError("file not found")):
            result = sc._tool_run_shell("nonexistent")
        assert "ERROR" in result

    def test_no_output_returns_no_output_message(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = sc._tool_run_shell("true")
        assert result == "(no output)"

    def test_output_truncated_to_3000_chars(self):
        mock_result = MagicMock()
        mock_result.stdout = "x" * 5000
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = sc._tool_run_shell("big output")
        assert len(result) == 3000

    def test_output_under_3000_not_truncated(self):
        mock_result = MagicMock()
        mock_result.stdout = "y" * 100
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = sc._tool_run_shell("small output")
        assert len(result) == 100

    def test_runs_in_output_dir(self):
        mock_result = MagicMock()
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            sc._tool_run_shell("ls")
        call_kwargs = mock_run.call_args[1]
        assert "cwd" in call_kwargs
        assert str(sc.OUTPUT_DIR) in str(call_kwargs["cwd"])

    def test_shell_true_flag_set(self):
        mock_result = MagicMock()
        mock_result.stdout = "ok"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            sc._tool_run_shell("ls")
        assert mock_run.call_args[1]["shell"] is True


# ── _tool_http_request ────────────────────────────────────────────────────────

class TestHttpRequest:
    def _make_mock_response(self, status_code=200, text="OK"):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        return resp

    def test_get_request_success(self):
        with patch("requests.request", return_value=self._make_mock_response(200, "hello")):
            result = sc._tool_http_request("GET", "http://localhost:8000/health")
        assert "HTTP 200" in result
        assert "hello" in result

    def test_post_request_includes_body(self):
        with patch("requests.request", return_value=self._make_mock_response(201, "created")) as mock_req:
            sc._tool_http_request("POST", "http://localhost/api", '{"key":"val"}')
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["data"] == '{"key":"val"}'

    def test_404_returns_status_in_output(self):
        with patch("requests.request", return_value=self._make_mock_response(404, "not found")):
            result = sc._tool_http_request("GET", "http://localhost/missing")
        assert "HTTP 404" in result

    def test_method_uppercased(self):
        with patch("requests.request", return_value=self._make_mock_response()) as mock_req:
            sc._tool_http_request("get", "http://localhost/")
        call_args = mock_req.call_args[0]
        assert call_args[0] == "GET"

    def test_connection_error_returns_error_string(self):
        with patch("requests.request", side_effect=ConnectionError("refused")):
            result = sc._tool_http_request("GET", "http://localhost:9999/")
        assert "ERROR" in result

    def test_empty_body_sends_none(self):
        with patch("requests.request", return_value=self._make_mock_response()) as mock_req:
            sc._tool_http_request("GET", "http://localhost/")
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["data"] is None

    def test_response_truncated_to_2000_chars(self):
        long_body = "z" * 5000
        with patch("requests.request", return_value=self._make_mock_response(200, long_body)):
            result = sc._tool_http_request("GET", "http://localhost/big")
        # Result = "HTTP 200\n" + 2000 chars = 2009 chars max
        assert result.count("z") == 2000

    def test_content_type_header_set(self):
        with patch("requests.request", return_value=self._make_mock_response()) as mock_req:
            sc._tool_http_request("POST", "http://localhost/", "{}")
        headers = mock_req.call_args[1]["headers"]
        assert headers.get("Content-Type") == "application/json"

    def test_delete_method(self):
        with patch("requests.request", return_value=self._make_mock_response(204, "")) as mock_req:
            sc._tool_http_request("DELETE", "http://localhost/item/1")
        assert mock_req.call_args[0][0] == "DELETE"


# ── validate_python tool ──────────────────────────────────────────────────────

class TestValidatePython:
    def test_valid_python_returns_ok(self):
        code = "def hello():\n    return 42\n"
        result = sc._tool_validate_python(code)
        assert "OK" in result or "syntax" in result.lower()

    def test_invalid_python_returns_error(self):
        code = "def broken(\n    pass\n"
        result = sc._tool_validate_python(code)
        assert "error" in result.lower() or "Syntax" in result

    def test_empty_string_valid(self):
        result = sc._tool_validate_python("")
        assert "OK" in result or "syntax" in result.lower()

    def test_typescript_content_is_invalid_python(self):
        tsx = "const App: React.FC = () => <div>Hello</div>;"
        result = sc._tool_validate_python(tsx)
        assert "error" in result.lower() or "Syntax" in result
