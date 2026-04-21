#!/usr/bin/env python3
"""
FastAPI server for Quantum Swarm frontend.
Runs on port 3001, serves /api/* endpoints matching frontend/src/services/api.js.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import psutil
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY = "quantum-swarm-dev-secret-do-not-use-in-prod"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 72
PROJECTS_DIR = Path("projects")
USERS_FILE = PROJECTS_DIR / "_users.json"
GENERAL_CHAT_FILE = PROJECTS_DIR / "_general_chat.json"

PROJECTS_DIR.mkdir(exist_ok=True)

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

# ---------------------------------------------------------------------------
# Helpers — users
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
        return GUEST_USER
    user = _find_user_by_id(uid)
    return user if user else GUEST_USER


def _public_user(u: dict) -> dict:
    return {"id": u["id"], "name": u["name"], "email": u["email"], "avatar": u.get("avatar", "")}

# ---------------------------------------------------------------------------
# Helpers — projects
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
    """Recalculate live status — marks Completed if runner finished."""
    stored = meta.get("status", "Planning")
    if stored == "In Progress" and not _is_runner_alive(meta.get("runner_pid")):
        # Runner exited — check for explicit status written by project_runner.py
        return meta.get("status", "Completed")
    return stored


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
    email: str
    password: str

class RegisterBody(BaseModel):
    name: str
    email: str
    password: str

class GoogleBody(BaseModel):
    idToken: str

class GithubBody(BaseModel):
    code: str

class CreateProjectBody(BaseModel):
    name: str

class UpdateProjectBody(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None

class SendMessageBody(BaseModel):
    text: str

# ---------------------------------------------------------------------------
# AUTH routes
# ---------------------------------------------------------------------------

@app.post("/api/auth/register")
def auth_register(body: RegisterBody):
    users = _load_users()
    if any(u["email"] == body.email for u in users):
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
    return {"user": _public_user(user), "token": token}


@app.post("/api/auth/login")
def auth_login(body: LoginBody):
    user = _find_user(body.email)
    if not user or not pwd_ctx.verify(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid email or password")
    token = _make_token(user["id"])
    return {"user": _public_user(user), "token": token}


@app.post("/api/auth/google")
def auth_google(body: GoogleBody):
    """Stub — creates/returns a placeholder user for the Google token."""
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
    """Stub — creates/returns a placeholder user for the GitHub code."""
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
            if owner and owner != user["id"] and user["id"] != "guest":
                continue
            # Refresh live status
            live = _project_status(meta)
            if live != meta.get("status"):
                meta["status"] = live
                _save_project(meta)
            msgs = meta.get("messages", [])
            last_msg = msgs[-1]["text"] if msgs else ""
            projects.append({
                "id": meta["id"],
                "name": meta["name"],
                "status": meta["status"],
                "date": meta["date"],
                "lastMessage": last_msg,
            })
        except Exception:
            continue
    projects.sort(key=lambda p: p["date"], reverse=True)
    return {"projects": projects}


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
    if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
        raise HTTPException(403, "Forbidden")
    shutil.rmtree(_project_dir(project_id), ignore_errors=True)
    return {"success": True}


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, body: UpdateProjectBody, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
        raise HTTPException(403, "Forbidden")
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
    if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
        raise HTTPException(403, "Forbidden")
    msgs = meta.get("messages", [])
    start = (page - 1) * limit
    return {"messages": msgs[start: start + limit]}


@app.post("/api/projects/{project_id}/messages")
def send_project_message(project_id: str, body: SendMessageBody,
                         user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
        raise HTTPException(403, "Forbidden")

    user_msg = _make_message(body.text, "user")
    meta.setdefault("messages", []).append(user_msg)

    live_status = _project_status(meta)
    meta["status"] = live_status

    if live_status == "Planning":
        # First substantive message → kick off engineering run
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
        # Completed or Failed — summarize what was built
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
# DASHBOARD endpoint — task tree + agent health
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/dashboard")
def get_project_dashboard(project_id: str, user: dict = Depends(_current_user)):
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

    return {
        "tasks": tasks_out,
        "agents": agents_out,
        "done": done,
        "total": total,
    }


# ---------------------------------------------------------------------------
# STOP endpoint — kill running engineering subprocess
# ---------------------------------------------------------------------------

@app.post("/api/projects/{project_id}/stop")
def stop_project(project_id: str, user: dict = Depends(_current_user)):
    meta = _load_project(project_id)
    if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
        raise HTTPException(403, "Forbidden")

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
    stop_msg = _make_message("⛔ Project stopped by user.", "ai")
    meta.setdefault("messages", []).append(stop_msg)
    _save_project(meta)

    return {"success": True, "killed": killed, "aiReply": stop_msg}


# ---------------------------------------------------------------------------
# PROGRESS polling endpoint
# ---------------------------------------------------------------------------

@app.get("/api/projects/{project_id}/progress")
def get_project_progress(project_id: str, user: dict = Depends(_current_user)):
    """Lightweight poll endpoint — returns latest task counts + last log line."""
    meta = _load_project(project_id)
    if meta.get("owner_id") and meta["owner_id"] != user["id"] and user["id"] != "guest":
        raise HTTPException(403, "Forbidden")

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
        import google.generativeai as genai
        import os
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not api_key:
            return "I'm here! (Set GEMINI_API_KEY env var to enable real AI replies.)"
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        conversation = "\n".join(
            f"{'User' if m['sender'] == 'user' else 'Assistant'}: {m['text']}"
            for m in history
        )
        resp = model.generate_content(
            f"You are a helpful AI assistant for a software project management tool.\n\n"
            f"Conversation:\n{conversation}\n\nAssistant:"
        )
        return resp.text.strip()
    except Exception as exc:
        return f"(AI unavailable: {exc})"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("api_server:app", host="0.0.0.0", port=3001, reload=False)
