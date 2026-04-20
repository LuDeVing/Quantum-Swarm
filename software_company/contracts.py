"""Typed interface contracts for sprint planning."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("company")

__all__ = [
    "EndpointContract",
    "ModelContract",
    "FileContract",
    "InterfaceContractRegistry",
    "get_contracts",
    "reset_contracts",
    "_registry_request_amendment",
    "_registry_process_amendments",
]


@dataclass
class EndpointContract:
    method: str          # GET, POST, PUT, DELETE
    path: str            # e.g. "/tasks", "/tasks/{task_id}"
    request_model: str   # e.g. "TaskCreate" or "" for no body
    response_model: str  # e.g. "Task", "List[Task]"

@dataclass
class ModelContract:
    name: str            # e.g. "Task"
    fields: str          # e.g. "id: str, title: str, completed: bool"
    file: str            # e.g. "models.py"

@dataclass
class FileContract:
    file: str            # e.g. "routes.py"
    owner: str           # e.g. "dev_2"
    imports_from: List[str]   # files this depends on, e.g. ["models.py"]
    exports: List[str]        # symbols this file must export, e.g. ["create_task", "get_tasks"]
    description: str     # what this file does
    depends_on: List[str] = field(default_factory=list)  # files that must be complete before this one starts

class InterfaceContractRegistry:
    """
    Holds typed interface contracts generated during sprint planning.
    All agents reference these to ensure shared signatures, import paths,
    and data shapes — eliminating the integration gap.
    """
    def __init__(self):
        self.endpoints: List[EndpointContract] = []
        self.models: List[ModelContract] = []
        self.file_map: Dict[str, FileContract] = {}   # filename -> FileContract
        self.entry_point: str = "main.py"
        self.entry_imports: List[str] = []  # modules the entry point must import
        self.build_command: str = ""      # e.g. "python server.py", "cargo build", "npm run build"
        self.build_file: str = ""         # e.g. "requirements.txt", "Cargo.toml", "package.json"
        self.install_command: str = ""    # e.g. "npm install", "pip install -r requirements.txt"
        self.gitignore_patterns: List[str] = []  # e.g. ["node_modules/", "dist/", "__pycache__/"]
        self.dependencies: List[str] = []  # external deps e.g. ["fastapi", "sqlalchemy"]
        self.init_order: List[str] = []    # ordered module init e.g. ["database", "routes", "server"]
        # app_type: "web" | "cli" | "gui" | "script" | "library" | "worker"
        # Drives which verification strategy the manager fix loop uses.
        self.app_type: str = ""
        # primary_language: stack id from contracts (e.g. python, rust, go, javascript, cpp, mixed).
        # Used to avoid forcing PYTHONPATH on non-Python projects.
        self.primary_language: str = ""
        self._lock = threading.RLock()
        # ── Amendment queue (mid-flight contract changes proposed by agents) ───
        self._pending_amendments: List[Dict] = []  # [{"file", "proposer", "reason", "change", "ts"}]

    def set_from_parsed(self, parsed: Dict) -> None:
        """Populate from parsed LLM output with defensive type-checking."""
        with self._lock:
            # 1. Parse Endpoints Safely
            for ep in parsed.get("endpoints", []):
                if isinstance(ep, dict):
                    self.endpoints.append(EndpointContract(
                        method=ep.get("method", "GET"),
                        path=ep.get("path", "/"),
                        request_model=ep.get("request_model", ""),
                        response_model=ep.get("response_model", ""),
                    ))

            # 2. Parse Models Safely
            for m in parsed.get("models", []):
                if isinstance(m, dict):
                    self.models.append(ModelContract(
                        name=m.get("name", ""),
                        fields=m.get("fields", ""),
                        file=m.get("file", "models.py"),
                    ))

            # 3. Parse Files Safely
            for f in parsed.get("files", []):
                if isinstance(f, dict):
                    fc = FileContract(
                        file=f.get("file", ""),
                        owner=f.get("owner", ""),
                        imports_from=f.get("imports_from", []),
                        exports=f.get("exports", []),
                        description=f.get("description", ""),
                        depends_on=f.get("depends_on", []),
                    )
                    self.file_map[fc.file] = fc

            self.entry_point = parsed.get("entry_point", "server.py")
            self.entry_imports = parsed.get("entry_imports", [])
            self.build_command = parsed.get("build_command", "")
            self.build_file = parsed.get("build_file", "")
            self.install_command = parsed.get("install_command", "")
            self.gitignore_patterns = parsed.get("gitignore_patterns", [])
            self.dependencies = parsed.get("dependencies", [])
            self.init_order = parsed.get("init_order", [])
            self.app_type = parsed.get("app_type", "") or self._infer_app_type()
            # Contract LLM sees only the task description, not actual code — re-verify when it says "cli"
            # because GUI apps (pygame, tkinter, etc.) are commonly misclassified.
            if self.app_type in ("cli", "script"):
                _code_inferred = self._infer_app_type()
                if _code_inferred not in ("cli", "script", "library"):
                    self.app_type = _code_inferred
                elif self._file_map_suggests_gui():
                    self.app_type = "gui"
            _pl = parsed.get("primary_language", "")
            if isinstance(_pl, str) and _pl.strip():
                self.primary_language = _pl.strip().lower()
            else:
                self.primary_language = self._infer_primary_language_locked()

    def _infer_primary_language_locked(self) -> str:
        """Infer main stack from build_file / file_map / build_command. Caller must hold self._lock."""
        bf = (self.build_file or "").replace("\\", "/").lower()
        if bf.endswith("cargo.toml") or bf == "cargo.toml":
            return "rust"
        if bf.endswith("go.mod") or bf == "go.mod":
            return "go"
        if bf.endswith("package.json") or bf.endswith("/package.json"):
            return "javascript"
        if bf.endswith("pom.xml") or bf == "pom.xml" or "gradle" in bf:
            return "java"
        if "cmakelists" in bf or bf.endswith(".cmake"):
            return "cpp"
        if bf.endswith("requirements.txt") or bf.endswith("pyproject.toml") or bf.endswith("setup.py"):
            return "python"
        exts = {Path(f).suffix.lower() for f in self.file_map}
        has_py = ".py" in exts
        has_rs = ".rs" in exts
        has_go = ".go" in exts
        has_js = ".js" in exts or ".jsx" in exts
        has_ts = ".ts" in exts or ".tsx" in exts
        has_java = ".java" in exts
        has_cs = ".cs" in exts
        has_cpp = any(
            e in exts for e in (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".h")
        )
        stacks = sum(
            bool(x)
            for x in (
                has_py, has_rs, has_go, has_js or has_ts, has_java, has_cs, has_cpp
            )
        )
        if stacks > 1:
            return "mixed"
        if has_rs:
            return "rust"
        if has_go:
            return "go"
        if has_java:
            return "java"
        if has_cs:
            return "csharp"
        if has_cpp:
            return "cpp"
        if has_ts or has_js:
            return "javascript"
        bc = (self.build_command or "").lower()
        if "cargo" in bc:
            return "rust"
        if "go build" in bc or "go test" in bc or "go run" in bc:
            return "go"
        if "npm " in bc or "node " in bc or "npx " in bc or "yarn " in bc or "pnpm " in bc:
            return "javascript"
        if "mvn" in bc or "gradle" in bc:
            return "java"
        if "dotnet " in bc:
            return "csharp"
        if "cmake " in bc or "clang++" in bc or "g++" in bc:
            return "cpp"
        return "python"

    def _file_map_suggests_gui(self) -> bool:
        """True if contract file paths/descriptions indicate a desktop window UI (caller holds _lock)."""
        _gui_signals = {"tkinter", "pyqt", "pyside", "wxpython", "kivy",
                        "electron", "tauri", "gtk", "wx.", "javafx", "swing",
                        "desktop window", "mainwindow", "gui app", "graphical user"}
        _blob = " ".join(f"{fc.file} {fc.description}" for fc in self.file_map.values()).lower()
        if any(s in _blob for s in _gui_signals):
            return True
        for fc in self.file_map.values():
            name = Path(fc.file or "").name.lower()
            if name == "gui.py" or name.endswith("_gui.py"):
                return True
        return False

    def _infer_app_type(self) -> str:
        """Use LLM to infer app type by reading the actual generated code.
        Falls back to 'cli' only if the LLM call fails."""
        from pathlib import Path
        from .config import OUTPUT_DIR

        # Has HTTP endpoints in contracts → definitely web
        if self.endpoints:
            return "web"

        # Sample the entry point and dependencies file so the LLM can see what was built
        code_dir = OUTPUT_DIR / "code"
        samples: list[str] = []
        for fname in ["main.py", "app.py", "server.py", "index.js",
                      "requirements.txt", "package.json", "Cargo.toml"]:
            f = code_dir / fname
            if f.exists():
                try:
                    samples.append(f"=== {fname} ===\n{f.read_text(encoding='utf-8', errors='replace')[:600]}")
                except OSError:
                    pass
            if len(samples) >= 3:
                break

        if not samples:
            return "cli"

        prompt = (
            "Read the following project files and classify the application type.\n\n"
            + "\n\n".join(samples)
            + "\n\nReply with ONLY one word from this list:\n"
            "  web      — HTTP server or API (FastAPI, Flask, Express, etc.)\n"
            "  gui      — opens a visual window (pygame, tkinter, OpenGL, Qt, Electron, etc.)\n"
            "  cli      — runs in a terminal and exits (argparse, click, shell scripts)\n"
            "  worker   — background daemon or queue processor\n"
            "  library  — importable module with no main loop\n\n"
            "One word only."
        )
        try:
            import software_company as _sc
            result = _sc.llm_call(prompt, label="infer_app_type").strip().lower().split()[0]
            if result in ("web", "gui", "cli", "worker", "library"):
                return result
        except Exception:
            pass
        return "cli"

    def get_contract_for_dev(self, dev_key: str) -> str:
        """Return a prompt-injectable contract summary for a specific developer."""
        with self._lock:
            lines = []
            dev_files = [f for f in self.file_map.values() if f.owner == dev_key]
            if not dev_files and not self.models:
                return ""

            lines.append("═══════════════════════════════════════════════════════")
            lines.append("INTERFACE CONTRACTS (you MUST use these exact signatures)")
            lines.append("═══════════════════════════════════════════════════════")
            _stack = (self.primary_language or "").strip() or self._infer_primary_language_locked()
            lines.append(
                f"\nPRIMARY STACK (language / ecosystem): {_stack} — use that stack's tools "
                f"for validation, tests, and run_shell (not only Python/pytest).\n"
            )

            if self.models:
                lines.append("\nSHARED DATA MODELS (defined in shared files — import, do NOT redefine):")
                for m in self.models:
                    lines.append(f"  class {m.name}: {m.fields}  (in {m.file})")

            if dev_files:
                lines.append("\nYOUR FILES:")
                for f in dev_files:
                    lines.append(f"  File: {f.file}")
                    lines.append(f"    Description: {f.description}")
                    if f.imports_from:
                        lines.append(f"    Imports from: {', '.join(f.imports_from)}")
                    if f.exports:
                        lines.append(f"    Must export: {', '.join(f.exports)}")

            other_files = [f for f in self.file_map.values() if f.owner != dev_key]
            if other_files:
                lines.append("\nTEAMMATE FILES (import from these, do NOT rewrite them):")
                for f in other_files:
                    lines.append(f"  {f.file} (owner: {f.owner}) — exports: {', '.join(f.exports)}")

            if self.endpoints:
                lines.append("\nAPI ENDPOINTS (all devs must agree on these signatures):")
                for ep in self.endpoints:
                    req = f" (body: {ep.request_model})" if ep.request_model else ""
                    lines.append(f"  {ep.method} {ep.path}{req} -> {ep.response_model}")

            if self.entry_point:
                lines.append(f"\nENTRY POINT: {self.entry_point}")
                if self.entry_imports:
                    lines.append(f"  Must import: {', '.join(self.entry_imports)}")

            lines.append("═══════════════════════════════════════════════════════")
            return "\n".join(lines)

    def get_full_summary(self) -> str:
        """Return a full contract summary for manager review / validation."""
        with self._lock:
            if not self.models and not self.endpoints and not self.file_map:
                return ""
            lines = ["INTERFACE CONTRACTS:"]
            if self.models:
                lines.append("  Models:")
                for m in self.models:
                    lines.append(f"    {m.name}: {m.fields} (in {m.file})")
            if self.endpoints:
                lines.append("  Endpoints:")
                for ep in self.endpoints:
                    req = f" ({ep.request_model})" if ep.request_model else ""
                    lines.append(f"    {ep.method} {ep.path}{req} -> {ep.response_model}")
            if self.file_map:
                lines.append("  File ownership:")
                for fname, fc in sorted(self.file_map.items()):
                    lines.append(f"    {fname} -> {fc.owner}: {fc.description[:60]}")
            return "\n".join(lines)

    def to_dict(self) -> Dict:
        with self._lock:
            return {
                "endpoints": [{"method": e.method, "path": e.path,
                               "request_model": e.request_model,
                               "response_model": e.response_model} for e in self.endpoints],
                "models": [{"name": m.name, "fields": m.fields, "file": m.file} for m in self.models],
                "files": [{"file": f.file, "owner": f.owner,
                           "imports_from": f.imports_from, "exports": f.exports,
                           "description": f.description} for f in self.file_map.values()],
                "entry_point": self.entry_point,
                "entry_imports": self.entry_imports,
                "primary_language": self.primary_language,
                "app_type": self.app_type,
            }


_contracts: Optional[InterfaceContractRegistry] = None
_contracts_lock = threading.Lock()

def get_contracts() -> InterfaceContractRegistry:
    global _contracts
    if _contracts is None:
        with _contracts_lock:
            if _contracts is None:
                _contracts = InterfaceContractRegistry()
    return _contracts

def reset_contracts() -> None:
    global _contracts
    with _contracts_lock:
        _contracts = None


# ── Amendment API ─────────────────────────────────────────────────────────────

def _registry_request_amendment(file: str, proposer: str, reason: str, proposed_change: str) -> str:
    """Queue a contract amendment request for manager review."""
    reg = get_contracts()
    with reg._lock:
        reg._pending_amendments.append({
            "file": file,
            "proposer": proposer,
            "reason": reason,
            "change": proposed_change,
            "ts": time.time(),
        })
    logger.info(f"[Contracts] Amendment queued by {proposer} for '{file}': {reason[:80]}")
    return (
        f"Amendment queued for manager review.\n"
        f"File: {file}\nReason: {reason}\nProposed: {proposed_change}\n"
        f"The manager will review and broadcast any approved changes to the team."
    )


def _registry_process_amendments(sprint: int) -> List[str]:
    """
    Called by the manager monitor. Reviews all pending amendments, applies them
    to the registry, and returns broadcast messages for each approved one.
    For this implementation all amendments are auto-approved (the Lead trusts agents).
    A future version could LLM-gate approvals.
    """
    reg = get_contracts()
    with reg._lock:
        amendments = list(reg._pending_amendments)
        reg._pending_amendments.clear()
    if not amendments:
        return []
    broadcasts = []
    for am in amendments:
        # Apply: update the file description in file_map if it exists
        with reg._lock:
            fc = reg.file_map.get(am["file"])
            if fc:
                fc.description = f"{fc.description} | AMENDED: {am['change'][:120]}"
        msg = (
            f"CONTRACT AMENDED by {am['proposer']} for '{am['file']}'. "
            f"Reason: {am['reason']}. Change: {am['change']}. "
            f"Update your imports/exports if this affects you."
        )
        broadcasts.append(msg)
        logger.info(f"[Contracts] Amendment applied for '{am['file']}' proposed by {am['proposer']}")
    return broadcasts
