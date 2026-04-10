"""Quantum Swarm software company — implementation split across submodules; public API re-exported here."""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

load_dotenv()

# Re-export everything defined in _monolith (including leading-underscore names used by tests/patches).
from . import _monolith as _monolith_mod

_pkg = globals()
for _key, _val in _monolith_mod.__dict__.items():
    if _key.startswith("__"):
        continue
    _pkg[_key] = _val


def _install_wrapped_callable(attr: str) -> None:
    """So unittest.patch('software_company.llm_call', ...) affects _monolith call sites."""
    _orig = _monolith_mod.__dict__.get(attr)
    if _orig is None or not callable(_orig):
        return

    def wrapper(*args, **kwargs):
        cur = sys.modules["software_company"].__dict__.get(attr, _orig)
        if cur is wrapper:
            return _orig(*args, **kwargs)
        return cur(*args, **kwargs)

    wrapper.__name__ = getattr(_orig, "__name__", attr)
    wrapper.__qualname__ = getattr(_orig, "__qualname__", attr)
    wrapper.__doc__ = getattr(_orig, "__doc__", None)
    _pkg[attr] = wrapper
    setattr(_monolith_mod, attr, wrapper)


for _wrap_name in ("llm_call", "_run_with_tools", "_run_fixer"):
    _install_wrapped_callable(_wrap_name)

del _pkg, _wrap_name, _install_wrapped_callable, _key, _val
