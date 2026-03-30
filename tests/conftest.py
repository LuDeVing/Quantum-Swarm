"""
conftest.py — Shared fixtures for Quantum Swarm tests.

Import strategy: software_company.py calls load_dotenv() and imports heavy
dependencies at module level. We patch those before import using sys.modules
so tests never need a real API key or network connection.
"""
import sys
import types
import os
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

# ── Stub out heavy dependencies before software_company imports them ──────────
# This must run before any test file imports from software_company.

def _make_genai_stub():
    """Minimal google.genai stub."""
    genai = types.ModuleType("google.genai")
    genai.Client = MagicMock()
    google = types.ModuleType("google")
    google.genai = genai
    return google, genai

def _make_langchain_stubs():
    lc_google = types.ModuleType("langchain_google_genai")
    lc_google.ChatGoogleGenerativeAI = MagicMock()
    lc_core = types.ModuleType("langchain_core")
    lc_tools = types.ModuleType("langchain_core.tools")
    def _tool_decorator(f):
        f.name = f.__name__              # mimic LangChain @tool which sets .name
        return f
    lc_tools.tool = _tool_decorator
    lc_messages = types.ModuleType("langchain_core.messages")
    for cls in ["HumanMessage", "AIMessage", "ToolMessage", "SystemMessage"]:
        setattr(lc_messages, cls, MagicMock)
    lc_core.tools = lc_tools
    lc_core.messages = lc_messages
    lg = types.ModuleType("langgraph")
    lg_pre = types.ModuleType("langgraph.prebuilt")
    lg_pre.create_react_agent = MagicMock()
    lg.prebuilt = lg_pre
    return lc_google, lc_core, lc_tools, lc_messages, lg, lg_pre

# Inject stubs
google, genai_mod = _make_genai_stub()
sys.modules.setdefault("google", google)
sys.modules.setdefault("google.genai", genai_mod)
lc_google, lc_core, lc_tools_mod, lc_messages_mod, lg, lg_pre = _make_langchain_stubs()
sys.modules.setdefault("langchain_google_genai", lc_google)
sys.modules.setdefault("langchain_core", lc_core)
sys.modules.setdefault("langchain_core.tools", lc_tools_mod)
sys.modules.setdefault("langchain_core.messages", lc_messages_mod)
sys.modules.setdefault("langgraph", lg)
sys.modules.setdefault("langgraph.prebuilt", lg_pre)

# Ensure GEMINI_API_KEY exists so get_client() doesn't raise KeyError
os.environ.setdefault("GEMINI_API_KEY", "test-key-does-not-matter")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def fresh_dashboard(tmp_path):
    """WorkDashboard with patched SAVE_PATH so no real file I/O leaks."""
    import software_company as sc
    save_path = tmp_path / "WORK_DASHBOARD.json"
    # Patch both the class-level constant and the singleton
    old_save_path = sc.WorkDashboard.SAVE_PATH
    sc.WorkDashboard.SAVE_PATH = save_path
    sc._dashboard = None
    dash = sc.get_dashboard()
    yield dash
    sc._dashboard = None
    sc.WorkDashboard.SAVE_PATH = old_save_path


@pytest.fixture()
def mock_llm_call():
    """Patch llm_call to return a configurable string."""
    with patch("software_company.llm_call", return_value="mock response STANCE: PRAGMATIC") as m:
        yield m


@pytest.fixture()
def healthy_state():
    """A fresh ActiveInferenceState with default priors."""
    from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState
    hypotheses = ["healthy", "uncertain", "confused"]
    prior = {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}
    return ActiveInferenceState(hypotheses, prior)


@pytest.fixture()
def rolling_ctx(mock_llm_call):
    """RollingContext with llm_call mocked."""
    from software_company import RollingContext
    return RollingContext(max_recent=3)


@pytest.fixture()
def three_states():
    """Three fresh health states for interference tests."""
    from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState
    hypotheses = ["healthy", "uncertain", "confused"]
    prior = {"healthy": 0.8, "uncertain": 0.15, "confused": 0.05}
    return [ActiveInferenceState(hypotheses, prior) for _ in range(3)]
