#!/usr/bin/env python3
"""
FastAPI server for Quantum Swarm frontend.
Runs on port 3001, serves /api/* endpoints matching frontend/src/services/api.js.
"""
from __future__ import annotations

import json
import logging
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import psutil
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field, validator

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("QUANTUM_SWARM_SECRET_KEY", "quantum-swarm-dev-secret-do-not-use-in-prod")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72
PROJECTS_DIR = Path("projects")
USERS_FILE = PROJECTS_DIR / "_users.json"
GENERAL_CHAT_FILE = PROJECTS_DIR / "_general_chat.json"

PROJECTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Structured audit logging
# ---------------------------------------------------------------------------
AUDIT_LOG_DIR = Path("logs")
AUDIT_LOG_DIR.mkdir(exist_ok=True)
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit.jsonl"
_audit_logger = logging.getLogger("audit")

def _audit(event: str, user_id: str, detail: dict | None = None) -> None:
    """Append one structured JSON line to the audit log â€” never raises."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": event,
            "event": event,
            "user_id": user_id,
            **(detail or {}),
        }
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:
        pass


pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

app = FastAPI(title="Quantum Swarm API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _request_audit_middleware(request: Request, call_next):
    """Log every request/response pair; sanitise exceptions before they reach the client."""
    t0 = time.monotonic()
    tool_name = f"{request.method} {request.url.path}"
    audit_input = f"{tool_name}?{request.url.query}".encode("utf-8")
    input_hash = hashlib.sha256(audit_input).hexdigest()[:16]
    try:
        response = await call_next(request)
        latency_ms = int((time.monotonic() - t0) * 1000)
        _audit("mcp_tool_call", user_id="-", detail={
            "tool_name": tool_name,
            "input_hash": input_hash,
            "result_status": "ok" if response.status_code < 400 else "error",
            "status": response.status_code,
            "latency_ms": latency_ms,
        })
        return response
    except Exception as exc:
        # Return a sanitised error â€” never leak internal tracebacks to callers.
        _audit("mcp_tool_call", user_id="-", detail={
            "tool_name": tool_name,
            "input_hash": input_hash,
            "result_status": "error",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "error_type": type(exc).__name__,
        })
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

# ---------------------------------------------------------------------------
# Helpers â€” users
# ---------------------------------------------------------------------------

def _load_users() -> list[dict]:
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    return []


def _save_users(users: list[dict]) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def _find_user(email: str) -> Optional[dict]:
    return next((u for u in _load_users() if u["email"] == email), None)


def _find_user_by_id(uid: str) -> Optional[dict]:
    return next((u for u in _load_users() if u["id"] == uid), None)


def _make_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


GUEST_USER = {"id": "guest", "name": "Guest", "email": "", "avatar": ""}

def _current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> dict:
    if not creds:
        return GUEST_USER
    uid = _decode_token(creds.credentials)
    if not uid:
        _audit("auth_rejected", user_id="", detail={"reason": "invalid_token"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = _find_user_by_id(uid)
    if not user:
        _audit("auth_rejected", user_id=uid, detail={"reason": "unknown_user"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"], "avatar": u.get("avatar", "")}

# ---------------------------------------------------------------------------
# Helpers â€” projects
# ---------------------------------------------------------------------------

def _project_dir(pid: str) -> Path:
    return PROJECTS_DIR / pid


def _project_file(pid: str) -> Path:
    return _project_dir(pid) / "project.json"


def _load_project(pid: str) -> dict:
    pf = _project_file(pid)
    if not pf.exists():
        raise HTTPException(404, "Project not found")
    return json.loads(pf.read_text(encoding="utf-8"))


def _save_project(meta: dict) -> None:
    pf = _project_file(meta["id"])
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_runner_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _project_status(meta: dict) -> str:
    """Return a truthful live status for the project runner."""
    stored = meta.get("status", "Planning")
    if stored == "Completed":
        tasks = _read_queue_tasks(meta["id"])
        if any(task.get("status") == "failed" for task in tasks):
            return "Failed"
    if stored == "In Progress" and not _is_runner_alive(meta.get("runner_pid")):
        result_file = _project_dir(meta["id"]) / "run_result.json"
        if result_file.exists():
            try:
                return json.loads(result_file.read_text(encoding="utf-8")).get("status", "Failed")
            except Exception:
                pass
        return "Failed"
    return stored


def _authorize_project(meta: dict, user: dict) -> None:
    """Allow owners and legacy unowned projects; guest only owns guest projects."""
    owner = meta.get("owner_id")
    if owner and owner != user["id"]:
        raise HTTPException(403, "Forbidden")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def _read_queue_tasks(pid: str) -> list[dict]:
    data = _read_json(_project_dir(pid) / "task_queue_state.json", {})
    tasks = data.get("tasks", {})
    return list(tasks.values()) if isinstance(tasks, dict) else tasks


def _project_summary(meta: dict) -> dict:
    pid = meta["id"]
    tasks = _read_queue_tasks(pid)
    total = len(tasks)
    done = sum(1 for task in tasks if task.get("status") == "completed")
    failed = sum(1 for task in tasks if task.get("status") == "failed")
    blocked = sum(1 for task in tasks if task.get("status") in ("blocked", "waiting"))
    active_agents = len({
        task.get("assigned_to")
        for task in tasks
        if task.get("assigned_to") and task.get("status") == "in_progress"
    })
    result = _read_json(_project_dir(pid) / "run_result.json", {})
    quality = None
    if total:
        quality = max(0, round(((done - failed) / total) * 100))
    messages = meta.get("messages", [])
    return {
        "id": pid,
        "name": meta["name"],
        "status": _project_status(meta),
        "date": meta["date"],
        "lastMessage": messages[-1]["text"] if messages else "",
        "done": done,
        "total": total,
        "progress": round(done / total * 100) if total else 0,
        "failed": failed,
        "blocked": blocked,
        "activeAgents": active_agents,
        "quality": quality,
        "qualityPassed": result.get("quality_passed"),
        "summary": result.get("quality_summary") or meta.get("last_run_summary", ""),
    }


def _read_task_counts(pid: str) -> tuple[int, int]:
    """Return (done, total) from task_queue_state.json."""
    queue_file = _project_dir(pid) / "task_queue_state.json"
    if queue_file.exists():
        try:
            data = json.loads(queue_file.read_text(encoding="utf-8"))
            tasks = data.get("tasks", {})
            if isinstance(tasks, dict):
                tasks = list(tasks.values())
            total = len(tasks)
            done = sum(1 for t in tasks if t.get("status") == "completed")
            return done, total
        except Exception:
            pass
    return 0, 0


def _summarize_progress(pid: str) -> str:
    done, total = _read_task_counts(pid)
    if total > 0:
        pct = int(done / total * 100)
        return f"Progress: {done}/{total} tasks complete ({pct}%). Still working..."
    log = _project_dir(pid) / "run.log"
    if log.exists():
        try:
            tail = log.read_text(encoding="utf-8", errors="replace")[-600:]
            last_line = tail.strip().splitlines()[-1] if tail.strip() else "(starting)"
            return f"Running... Latest: {last_line}"
        except Exception:
            pass
    return "Starting up..."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%-I:%M %p")
    except Exception:
        return ""


def _make_message(text: str, sender: str) -> dict:
    now = _now_iso()
    return {"id": str(uuid.uuid4()), "text": text, "sender": sender, "time": _fmt_time(now), "createdAt": now}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)

    @validator("email")
    def _login_email_has_basic_shape(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("invalid email address")
        return value

class RegisterBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)

    @validator("name", "email")
    def _strip_text(cls, value: str) -> str:
        return value.strip()

    @validator("email")
    def _register_email_has_basic_shape(cls, value: str) -> str:
        value = value.lower()
        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("invalid email address")
        return value

class GoogleBody(BaseModel):
    idToken: str = Field(..., min_length=8, max_length=4096)

class GithubBody(BaseModel):
    code: str = Field(..., min_length=4, max_length=512)

class CreateProjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)

class UpdateProjectBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    status: Optional[str] = Field(default=None, min_length=1, max_length=40)

class SendMessageBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)

class VerificationRunBody(BaseModel):
    kind: str = Field(..., pattern="^(test|run)$")

# ---------------------------------------------------------------------------
# AUTH routes
# ---------------------------------------------------------------------------

@app.post("/api/auth/register")
def auth_register(body: RegisterBody):
    users = _load_users()
    if any(u["email"] == body.email for u in users):
        _audit("register_failed", user_id="", detail={"reason": "duplicate_email"})
        raise HTTPException(400, "Email already registered")
    uid = str(uuid.uuid4())
    user = {
        "id": uid,
        "name": body.name,
        "email": body.email,
        "password_hash": pwd_ctx.hash(body.password),
        "avatar": f"https://api.dicebear.com/7.x/initials/svg?seed={body.name}",
    }
    users.append(user)
    _save_users(users)
    token = _make_token(uid)
    _audit("register_ok", user_id=uid)
    return {"user": _public_user(user), "token": token}


@app.post("/api/auth/login")
def auth_login(body: LoginBody):
    user = _find_user(body.email)
    if not user or not pwd_ctx.verify(body.password, user.get("password_hash", "")):
        _audit("login_failed", user_id="", detail={"reason": "bad_credentials"})
        raise HTTPException(401, "Invalid email or password")
    token = _make_token(user["id"])
    _audit("login_ok", user_id=user["id"])
    return {"user": _public_user(user), "token": token}


@app.post("/api/auth/google")
def auth_google(body: GoogleBody):
    """Stub â€” creates/returns a placeholder user for the Google token."""
    stub_email = f"google_{body.idToken[:8]}@stub.local"
    user = _find_user(stub_email)
    if not user:
        uid = str(uuid.uuid4())
        user = {"id": uid, "name": "Google User", "email": stub_email,
                "password_hash": "", "avatar": ""}
        users = _load_users()
        users.append(user)
        _save_users(users)
    token = _make_token(user["id"])
    return {"user": _public_user(user), "token": token}


@app.post("/api/auth/github")
def auth_github(body: GithubBody):
    """Stub â€” creates/returns a placeholder user for the GitHub code."""
    stub_email = f"github_{body.code[:8]}@stub.local"
    user = _find_user(stub_email)
    if not user:
        uid = str(uuid.uuid4())
        user = {"id": uid, "name": "GitHub User", "email": stub_email,
                "password_hash": "", "avatar": ""}
        users = _load_users()
        users.append(user)
        _save_users(users)
    token = _make_token(user["id"])
    return {"user": _public_user(user), "token": token}


@app.get("/api/auth/me")
def auth_me(user: dict = Depends(_current_user)):
    return {"user": _public_user(user)}


@app.post("/api/auth/logout")
def auth_logout():
    return {"success": True}


@app.get("/api/auth/{provider}/redirect")
def auth_redirect(provider: str):
    return {"message": f"{provider} OAuth not configured in dev mode"}

# ---------------------------------------------------------------------------
# PROJECTS routes
# ---------------------------------------------------------------------------

@app.get("/api/projects")
def list_projects(user: dict = Depends(_current_user)):
    projects = []
    for pdir in PROJECTS_DIR.iterdir():
        pf = pdir / "project.json"
        if not pf.exists():
            continue
        try:
            meta = json.loads(pf.read_text(encoding="utf-8"))
            owner = meta.get("owner_id")
            if owner and owner != user["id"]:
                continue
            # Refresh live status
            live = _project_status(meta)
            if live != meta.get("status"):
                meta["status"] = live
                _save_project(meta)
            projects.append(_project_summary(meta))
        except Exception:
            continue
    projects.sort(key=lambda p: p["date"], reverse=True)
    return {"projects": projects}


@app.get("/api/portfolio")
def get_portfolio(user: dict = Depends(_current_user)):
    """Aggregate project, agent, blocker, and artifact data for the control center."""
    projects = list_projects(user)["projects"]
    all_tasks: list[dict] = []
    artifacts: list[dict] = []

    for project in projects:
        pid = project["id"]
        tasks = _read_queue_tasks(pid)
        for task in tasks:
            all_tasks.append({**task, "projectId": pid, "projectName": project["name"]})

        component_graph = _read_json(_project_dir(pid) / "COMPONENT_GRAPH.json", {})
        nodes = component_graph.get("nodes", {})
        node_values = list(nodes.values()) if isinstance(nodes, dict) else nodes
        for node in node_values[:20]:
            file_path = node.get("file_path") or node.get("suggested_file")
            if not file_path:
                continue
            resolved = _project_dir(pid) / "code" / file_path
            artifacts.append({
                "id": f"{pid}:{file_path}",
                "projectId": pid,
                "projectName": project["name"],
                "name": file_path,
                "type": Path(file_path).suffix.lstrip(".") or "file",
                "status": "ready" if resolved.exists() else "planned",
                "createdBy": node.get("owner") or node.get("assigned_to") or "swarm",
            })

    agent_keys = [f"dev_{i}" for i in range(1, 9)]
    agents = []
    for key in agent_keys:
        assigned = [task for task in all_tasks if task.get("assigned_to") == key]
        working = next((task for task in assigned if task.get("status") == "in_progress"), None)
        agents.append({
            "key": key,
            "name": f"Engineer {key.split('_')[-1]}",
            "status": "working" if working else ("done" if assigned else "idle"),
            "currentTask": working.get("file") if working else None,
            "tasksDone": sum(1 for task in assigned if task.get("status") == "completed"),
            "tasksFailed": sum(1 for task in assigned if task.get("status") == "failed"),
        })

    blockers = [
        {
            "id": task.get("id", ""),
            "projectId": task["projectId"],
            "projectName": task["projectName"],
            "file": task.get("file", "Unknown task"),
            "status": task.get("status", "blocked"),
            "agent": task.get("assigned_to"),
        }
        for task in all_tasks
        if task.get("status") in ("failed", "blocked", "waiting")
    ]
    completed = sum(1 for task in all_tasks if task.get("status") == "completed")
    quality = round(completed / len(all_tasks) * 100) if all_tasks else None

    return {
        "projects": projects,
        "agents": agents,
        "artifacts": artifacts[:50],
        "blockers": blockers[:20],
        "summary": {
            "projects": len(projects),
            "activeProjects": sum(1 for project in projects if project["status"] == "In Progress"),
            "agentsWorking": sum(1 for agent in agents if agent["status"] == "working"),
            "tasks": len(all_tasks),
            "completedTasks": completed,
            "blockers": len(blockers),
            "quality": quality,
        },
    }


@app.post("/api/projects", status_code=201)
def create_project(body: CreateProjectBody, user: dict = Depends(_current_user)):
    pid = str(uuid.uuid4())
    now = _now_iso()
    meta = {
        "id": pid,
        "name": body.name,
        "status": "Planning",
        "date": now,
        "owner_id": user["id"],
        "messages": [],
        "runner_pid": None,
    }
    _save_project(meta)
    return {"project": {"id": pid, "name": body.name, "status": "Planning", "date": now}}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    shutil.rmtree(_project_dir(project_id), ignore_errors=True)
    return {"success": True}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, body: UpdateProjectBody, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    if body.name is not None:
        meta["name"] = body.name
    if body.status is not None:
        meta["status"] = body.status
    _save_project(meta)
    return {"project": {"id": meta["id"], "name": meta["name"], "status": meta["status"], "date": meta["date"]}}

# ---------------------------------------------------------------------------
# PROJECT MESSAGES routes
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/messages")
def get_project_messages(project_id: str, page: int = 1, limit: int = 50,
                         user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    msgs = meta.get("messages", [])
    start = (page - 1) * limit
    return {"messages": msgs[start: start + limit]}


@app.post("/api/projects/{project_id}/messages")
def send_project_message(project_id: str, body: SendMessageBody,
                         user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)

    user_msg = _make_message(body.text, "user")
    meta.setdefault("messages", []).append(user_msg)

    live_status = _project_status(meta)
    meta["status"] = live_status

    if live_status == "Planning":
        # First substantive message â†’ kick off engineering run
        meta["status"] = "In Progress"
        log_path = _project_dir(project_id) / "run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "project_runner.py", project_id, body.text],
            stdout=open(str(log_path), "w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            cwd=str(Path.cwd()),
        )
        meta["runner_pid"] = proc.pid
        ai_text = (
            f"Got it! I'm spinning up your engineering team to build \"{body.text}\". "
            "Send another message to check progress."
        )
    elif live_status == "In Progress":
        ai_text = _summarize_progress(project_id)
    else:
        # Completed or Failed â€” summarize what was built
        cg = _project_dir(project_id) / "COMPONENT_GRAPH.json"
        if cg.exists():
            try:
                data = json.loads(cg.read_text(encoding="utf-8"))
                nodes = list(data.get("nodes", {}).values())
                file_list = ", ".join(n.get("file_path", "") for n in nodes[:8] if n.get("file_path"))
                ai_text = f"Your project is complete! Files built: {file_list or 'see projects/{project_id}/code/'}."
            except Exception:
                ai_text = f"Your project is {live_status}. Check projects/{project_id}/code/ for the output."
        else:
            ai_text = f"Your project is {live_status}. Check projects/{project_id}/code/ for the output."

    ai_msg = _make_message(ai_text, "ai")
    meta["messages"].append(ai_msg)
    _save_project(meta)

    return {"userMessage": user_msg, "aiReply": ai_msg}

# ---------------------------------------------------------------------------
# DASHBOARD endpoint â€” task tree + agent health
# ---------------------------------------------------------------------------

def _workflow_steps(meta: dict, tasks: list[dict], quality: dict, pdir: Path) -> list[dict]:
    status = _project_status(meta)
    has_tree = (pdir / "TASK_TREE.json").exists()
    has_code = (pdir / "code").exists() and any((pdir / "code").rglob("*"))
    tests = quality.get("verification", {}).get("test") or {}
    run = quality.get("verification", {}).get("run") or {}
    failed = status in ("Failed", "Stopped")
    specs = [
        ("brief", "Brief", bool(meta.get("messages"))),
        ("plan", "Plan", has_tree),
        ("build", "Build", has_code and bool(tasks)),
        ("test", "Test", bool(tests) or bool(quality)),
        ("run", "Run", bool(run) or bool(quality.get("quality_passed"))),
        ("deliver", "Deliver", status == "Completed"),
    ]
    first_incomplete = next((key for key, _, complete in specs if not complete), "deliver")
    steps = []
    for key, label, complete in specs:
        step_status = "complete" if complete else "pending"
        if failed and key == first_incomplete:
            step_status = "failed"
        elif not failed and status == "In Progress" and key == first_incomplete:
            step_status = "active"
        steps.append({"key": key, "label": label, "status": step_status})
    return steps


def _canonical_tree(pdir: Path, tasks: list[dict]) -> dict:
    raw_tree = _read_json(pdir / "TASK_TREE.json", {})
    raw_nodes = raw_tree.get("nodes", {})
    raw_values = list(raw_nodes.values()) if isinstance(raw_nodes, dict) else raw_nodes
    descriptions = {
        node.get("suggested_file"): node
        for node in raw_values
        if node.get("suggested_file")
    }
    root_id = raw_tree.get("root_id") or "project-root"
    root = next((node for node in raw_values if node.get("id") == root_id), {})
    nodes = [{
        "id": root_id,
        "name": root.get("name") or "Project goal",
        "description": root.get("description") or raw_tree.get("goal", ""),
        "parentId": None,
        "depth": 0,
        "file": None,
        "status": "completed" if tasks else "pending",
        "agent": None,
        "complexity": root.get("complexity", "high"),
        "dependsOn": [],
        "retries": 0,
    }]
    edges = []
    task_ids = {task.get("id") for task in tasks}
    for task in tasks:
        planned = descriptions.get(task.get("file"), {})
        file_path = pdir / "code" / task.get("file", "")
        task_status = task.get("status", "pending")
        if file_path.is_file():
            preview = file_path.read_text(encoding="utf-8", errors="replace")[:4000].lower()
            if "auto-generated skeleton" in preview or "todo: implement this file" in preview:
                task_status = "needs_review"
        nodes.append({
            "id": task.get("id"),
            "name": planned.get("name") or Path(task.get("file") or task.get("id", "")).name,
            "description": planned.get("description") or task.get("description", ""),
            "parentId": root_id,
            "depth": 1,
            "file": None if task.get("file") == "__integration__" else task.get("file"),
            "status": task_status,
            "agent": task.get("assigned_to"),
            "complexity": planned.get("complexity", "medium"),
            "dependsOn": task.get("depends_on", []),
            "retries": task.get("retries", 0),
        })
        edges.append({"from": root_id, "to": task.get("id"), "type": "hierarchy"})
        edges.extend(
            {"from": dep, "to": task.get("id"), "type": "dependency"}
            for dep in task.get("depends_on", [])
            if dep in task_ids
        )
    return {"rootId": root_id, "goal": raw_tree.get("goal", ""), "nodes": nodes, "edges": edges}


def _meaningful_events(pdir: Path, tasks: list[dict]) -> list[dict]:
    events = []
    log_path = pdir / "run.log"
    patterns = [
        ("plan", "Plan created", re.compile(r"(TASK_TREE|component graph|initialized .*tasks)", re.I)),
        ("assignment", "Agent assigned", re.compile(r"(claimed|assigned)", re.I)),
        ("file", "File generated", re.compile(r"(writing |Created )", re.I)),
        ("fix", "Fix applied", re.compile(r"(ManagerFix|auto-fixes applied|requeueing)", re.I)),
        ("test", "Tests executed", re.compile(r"(test gate|passed in|pytest)", re.I)),
        ("verification", "Verification", re.compile(r"(ALL GREEN|verified|done . status)", re.I)),
    ]
    if log_path.exists():
        for index, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
            for event_type, title, pattern in patterns:
                if pattern.search(line):
                    events.append({
                        "id": f"log-{index}",
                        "type": event_type,
                        "title": title,
                        "detail": line[-500:],
                        "timestamp": line[:8] if re.match(r"\d\d:\d\d:\d\d", line) else "",
                    })
                    break
    stored = pdir / "events.jsonl"
    if stored.exists():
        for line in stored.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events[-120:]


def _approved_verification_commands(pdir: Path) -> dict:
    code_dir = pdir / "code"
    commands = {}
    if (code_dir / "tests").exists():
        commands["test"] = {
            "label": "Run test suite",
            "argv": [sys.executable, "-m", "pytest", "-q"],
            "display": "python -m pytest -q",
        }
    entry = code_dir / "src" / "main.py"
    if entry.exists():
        commands["run"] = {
            "label": "Run application proof",
            "argv": [sys.executable, "src/main.py", "10", "+", "5"],
            "display": "python src/main.py 10 + 5",
        }
    elif (code_dir / "main.py").exists():
        commands["run"] = {
            "label": "Run application",
            "argv": [sys.executable, "main.py"],
            "display": "python main.py",
        }
    return commands


def _verification_state(pdir: Path) -> dict:
    state = _read_json(pdir / "verification.json", {})
    return {"commands": {
        key: {"label": value["label"], "display": value["display"]}
        for key, value in _approved_verification_commands(pdir).items()
    }, **state}


def _append_event(pdir: Path, event: dict) -> None:
    with open(pdir / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


@app.get("/api/projects/{project_id}/dashboard")
def get_project_dashboard(project_id: str, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    pdir = _project_dir(project_id)

    # --- task tree nodes (name, depth, complexity) ---
    tree_nodes: dict = {}
    tree_file = pdir / "TASK_TREE.json"
    if tree_file.exists():
        try:
            tree_nodes = json.loads(tree_file.read_text(encoding="utf-8")).get("nodes", {})
        except Exception:
            pass

    # --- task queue statuses (status, assigned_to, file) ---
    queue_tasks: dict = {}
    queue_file = pdir / "task_queue_state.json"
    if queue_file.exists():
        try:
            queue_tasks = json.loads(queue_file.read_text(encoding="utf-8")).get("tasks", {})
        except Exception:
            pass

    # Merge: queue tasks are the leaf work items; annotate with tree name if available
    tasks_out = []
    for t in queue_tasks.values():
        tasks_out.append({
            "id": t.get("id", ""),
            "file": t.get("file", ""),
            "status": t.get("status", "pending"),
            "assigned_to": t.get("assigned_to"),
            "depends_on": t.get("depends_on", []),
            "retries": t.get("retries", 0),
        })

    # If no queue yet but tree exists, show tree atomic nodes as pending
    if not tasks_out and tree_nodes:
        for n in tree_nodes.values():
            if n.get("is_atomic"):
                tasks_out.append({
                    "id": n["id"],
                    "file": n.get("suggested_file", ""),
                    "status": "pending",
                    "assigned_to": None,
                    "depends_on": [],
                    "retries": 0,
                })

    # --- agent health: derive from queue tasks ---
    ENG_DEV_KEYS = [f"dev_{i}" for i in range(1, 9)]
    agents_out = []
    for dev in ENG_DEV_KEYS:
        working = next((t for t in tasks_out if t.get("assigned_to") == dev and t["status"] == "in_progress"), None)
        done_count = sum(1 for t in tasks_out if t.get("assigned_to") == dev and t["status"] == "completed")
        agents_out.append({
            "key": dev,
            "status": "working" if working else ("done" if done_count > 0 else "idle"),
            "current_file": working["file"] if working else None,
            "tasks_done": done_count,
        })

    done = sum(1 for t in tasks_out if t["status"] == "completed")
    total = len(tasks_out)
    quality = _read_json(pdir / "run_result.json", {})
    quality["verification"] = _verification_state(pdir)

    return {
        "tasks": tasks_out,
        "agents": agents_out,
        "done": done,
        "total": total,
        "status": _project_status(meta),
        "quality": quality,
        "workflow": _workflow_steps(meta, tasks_out, quality, pdir),
        "tree": _canonical_tree(pdir, tasks_out),
        "events": _meaningful_events(pdir, tasks_out),
    }


@app.get("/api/projects/{project_id}/artifacts")
def get_project_artifacts(project_id: str, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    code_dir = _project_dir(project_id) / "code"
    artifacts = []
    if code_dir.exists():
        for path in code_dir.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                preview = path.read_text(encoding="utf-8", errors="replace")[:4000].lower()
                artifact_status = "needs_review" if (
                    "auto-generated skeleton" in preview or "todo: implement this file" in preview
                ) else "ready"
                artifacts.append({
                    "name": path.relative_to(code_dir).as_posix(),
                    "type": path.suffix.lstrip(".") or "file",
                    "size": path.stat().st_size,
                    "status": artifact_status,
                })
    return {"artifacts": artifacts[:250]}


@app.get("/api/projects/{project_id}/artifacts/content")
def get_project_artifact_content(project_id: str, path: str,
                                 user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    code_dir = (_project_dir(project_id) / "code").resolve()
    target = (code_dir / path).resolve()
    try:
        target.relative_to(code_dir)
    except ValueError:
        raise HTTPException(400, "Invalid artifact path")
    if not target.is_file():
        raise HTTPException(404, "Artifact not found")
    if target.stat().st_size > 500_000:
        raise HTTPException(413, "Artifact is too large to preview")
    return {
        "path": target.relative_to(code_dir).as_posix(),
        "content": target.read_text(encoding="utf-8", errors="replace"),
        "language": target.suffix.lstrip(".") or "text",
    }


@app.get("/api/projects/{project_id}/verification")
def get_project_verification(project_id: str, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    return _verification_state(_project_dir(project_id))


@app.post("/api/projects/{project_id}/verification/run")
def run_project_verification(project_id: str, body: VerificationRunBody,
                             user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    pdir = _project_dir(project_id)
    code_dir = pdir / "code"
    command = _approved_verification_commands(pdir).get(body.kind)
    if not command:
        raise HTTPException(400, f"No approved {body.kind} command detected")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command["argv"],
            cwd=code_dir,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = (completed.stdout + completed.stderr)[-20_000:]
        result = {
            "kind": body.kind,
            "command": command["display"],
            "exitCode": completed.returncode,
            "passed": completed.returncode == 0,
            "output": output,
            "durationMs": round((time.monotonic() - started) * 1000),
            "timestamp": _now_iso(),
        }
    except subprocess.TimeoutExpired as exc:
        result = {
            "kind": body.kind,
            "command": command["display"],
            "exitCode": None,
            "passed": False,
            "output": f"Command timed out after 30 seconds.\n{exc.stdout or ''}{exc.stderr or ''}",
            "durationMs": 30_000,
            "timestamp": _now_iso(),
        }
    state = _read_json(pdir / "verification.json", {})
    state[body.kind] = result
    (pdir / "verification.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    _append_event(pdir, {
        "id": str(uuid.uuid4()),
        "type": "test" if body.kind == "test" else "verification",
        "title": "Tests passed" if body.kind == "test" and result["passed"] else (
            "Application run verified" if result["passed"] else f"{body.kind.title()} failed"
        ),
        "detail": f'{result["command"]} exited with {result["exitCode"]}',
        "timestamp": result["timestamp"],
    })
    return result


@app.get("/api/projects/{project_id}/logs")
def get_project_logs(project_id: str, limit: int = 300,
                     user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)
    log_path = _project_dir(project_id) / "run.log"
    lines = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-min(limit, 1000):]
    return {"lines": lines, "status": _project_status(meta)}


# ---------------------------------------------------------------------------
# STOP endpoint â€” kill running engineering subprocess
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/stop")
def stop_project(project_id: str, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    _authorize_project(meta, user)

    pid = meta.get("runner_pid")
    killed = False
    if pid and _is_runner_alive(pid):
        try:
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            proc.kill()
            killed = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    meta["status"] = "Stopped"
    meta["runner_pid"] = None
    stop_msg = _make_message("â›” Project stopped by user.", "ai")
    meta.setdefault("messages", []).append(stop_msg)
    _save_project(meta)

    return {"success": True, "killed": killed, "aiReply": stop_msg}


# ---------------------------------------------------------------------------
# PROGRESS polling endpoint
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/progress")
def get_project_progress(project_id: str, user: dict = Depends(_current_user)):
    """Lightweight poll endpoint â€” returns latest task counts + last log line."""
    meta = _load_project(project_id)
    _authorize_project(meta, user)

    live_status = _project_status(meta)
    if live_status != meta.get("status"):
        meta["status"] = live_status
        _save_project(meta)

    done, total = _read_task_counts(project_id)
    last_line = ""

    log = _project_dir(project_id) / "run.log"
    if log.exists():
        try:
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
            lines = [l.strip() for l in tail.splitlines() if l.strip()]
            if lines:
                last_line = lines[-1]
        except Exception:
            pass

    return {
        "status": live_status,
        "done": done,
        "total": total,
        "last_line": last_line,
    }


# ---------------------------------------------------------------------------
# GENERAL CHAT routes
# ---------------------------------------------------------------------------

def _load_general_chat() -> list[dict]:
    if GENERAL_CHAT_FILE.exists():
        return json.loads(GENERAL_CHAT_FILE.read_text(encoding="utf-8"))
    return []


def _save_general_chat(msgs: list[dict]) -> None:
    GENERAL_CHAT_FILE.write_text(json.dumps(msgs, indent=2, ensure_ascii=False), encoding="utf-8")


@app.get("/api/chat/messages")
def get_general_messages(page: int = 1, limit: int = 50,
                         user: dict = Depends(_current_user)):
    msgs = _load_general_chat()
    start = (page - 1) * limit
    return {"messages": msgs[start: start + limit]}


@app.post("/api/chat/messages")
def send_general_message(body: SendMessageBody, user: dict = Depends(_current_user)):
    msgs = _load_general_chat()
    user_msg = _make_message(body.text, "user")
    msgs.append(user_msg)

    # Simple LLM reply via google-generativeai (same model the engineering system uses)
    ai_text = _general_chat_reply(body.text, msgs[-10:])
    ai_msg = _make_message(ai_text, "ai")
    msgs.append(ai_msg)
    _save_general_chat(msgs)
    return {"userMessage": user_msg, "aiReply": ai_msg}


def _general_chat_reply(text: str, history: list[dict]) -> str:
    try:
        import os
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            return "I'm here! (Set GEMINI_API_KEY env var to enable real AI replies.)"
        os.environ.setdefault("GEMINI_API_KEY", api_key)
        from software_company.llm_client import llm_call
        conversation = "\n".join(
            f"{'User' if m['sender'] == 'user' else 'Assistant'}: {m['text']}"
            for m in history
        )
        return llm_call(
            f"You are a helpful AI assistant for a software project management tool.\n\n"
            f"Conversation:\n{conversation}\n\nAssistant:"
            "\n\nReply concisely and do not include internal errors or tracebacks.",
            label="api_general_chat",
            system="",
        )
    except Exception as exc:
        _audit("chat_llm_unavailable", user_id="-", detail={"reason": type(exc).__name__})
        return "(AI unavailable. Please try again later.)"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=3001, reload=False)
