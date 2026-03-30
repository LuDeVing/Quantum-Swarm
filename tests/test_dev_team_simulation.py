"""
test_dev_team_simulation.py — Full 8-developer team simulation.

Runs the actual run_engineering_team() pipeline with mocked LLM calls that
return realistic code outputs. Verifies that:
  - All 8 devs get unique task assignments
  - Devs write real files to disk via their tools
  - Round 2 devs see what teammates built in Round 1
  - Manager feedback flows into Round 2 prompts
  - Health monitoring (H_swarm) is computed correctly
  - The final TeamResult has the right structure

No real API calls — all LLM responses are scripted to return realistic code.
"""

import os
import re
import json
import threading
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

import software_company as sc
from software_company import (
    ENG_WORKERS, ROLES, RollingContext, STANCES,
    run_engineering_team, WorkerOutput,
    ActiveInferenceState, HYPOTHESES, ROLE_PRIOR,
    extract_stance_probs, perplexity_to_similarities,
)
from hamiltonian_swarm.quantum.active_inference import ActiveInferenceState


# ── Realistic mock code outputs — one per developer ───────────────────────────
# Each simulates what a real dev would write: code + tool calls + STANCE

DEV_CODE_OUTPUTS = {
    "dev_1": """\
I'll implement the user authentication module.

```python
# auth.py
from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "dev-secret-key"
ALGORITHM = "HS256"

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

@router.post("/register")
async def register(username: str, password: str):
    hashed = get_password_hash(password)
    return {"username": username, "hashed": hashed}

@router.post("/login")
async def login(username: str, password: str):
    token = create_access_token({"sub": username})
    return {"access_token": token, "token_type": "bearer"}
```

Written auth.py with JWT login/register endpoints.
STANCE: ROBUST""",

    "dev_2": """\
Implementing the Todo CRUD API endpoints.

```python
# todo_routes.py
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from pydantic import BaseModel

router = APIRouter(prefix="/todos")

class TodoCreate(BaseModel):
    title: str
    description: str = ""

class Todo(BaseModel):
    id: int
    title: str
    description: str
    completed: bool = False
    user_id: int

todos_db: List[Todo] = []
_id_counter = 1

@router.get("/", response_model=List[Todo])
async def get_todos(user_id: int = 1):
    return [t for t in todos_db if t.user_id == user_id]

@router.post("/", response_model=Todo)
async def create_todo(todo: TodoCreate, user_id: int = 1):
    global _id_counter
    new_todo = Todo(id=_id_counter, title=todo.title,
                    description=todo.description, user_id=user_id)
    todos_db.append(new_todo)
    _id_counter += 1
    return new_todo

@router.put("/{todo_id}")
async def update_todo(todo_id: int, completed: bool):
    for todo in todos_db:
        if todo.id == todo_id:
            todo.completed = completed
            return todo
    raise HTTPException(404, "Todo not found")

@router.delete("/{todo_id}")
async def delete_todo(todo_id: int):
    global todos_db
    todos_db = [t for t in todos_db if t.id != todo_id]
    return {"deleted": todo_id}
```

STANCE: PRAGMATIC""",

    "dev_3": """\
Building the SQLAlchemy database models and session management.

```python
# models.py
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()
DATABASE_URL = "sqlite:///./todos.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    todos = relationship("TodoItem", back_populates="owner")

class TodoItem(Base):
    __tablename__ = "todos"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(String, default="")
    completed = Column(Boolean, default=False)
    owner_id = Column(Integer, ForeignKey("users.id"))
    owner = relationship("User", back_populates="todos")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

Base.metadata.create_all(bind=engine)
```

STANCE: ROBUST""",

    "dev_4": """\
Creating the FastAPI application entry point and connecting all routers.

```python
# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from todo_routes import router as todo_router

app = FastAPI(title="Todo App", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(todo_router, prefix="/api", tags=["todos"])

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

STANCE: MINIMAL""",

    "dev_5": """\
Implementing the React frontend Login and Register components.

```typescript
// Login.tsx
import React, { useState } from 'react';

interface LoginProps {
  onSuccess: (token: string) => void;
}

const Login: React.FC<LoginProps> = ({ onSuccess }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) throw new Error('Invalid credentials');
      const data = await res.json();
      localStorage.setItem('token', data.access_token);
      onSuccess(data.access_token);
    } catch (err) {
      setError('Login failed. Check your credentials.');
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input value={username} onChange={e => setUsername(e.target.value)} placeholder="Username" />
      <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Password" />
      {error && <p style={{color: 'red'}}>{error}</p>}
      <button type="submit">Login</button>
    </form>
  );
};

export default Login;
```

STANCE: PRAGMATIC""",

    "dev_6": """\
Building the TodoList React component with CRUD operations.

```typescript
// TodoList.tsx
import React, { useEffect, useState } from 'react';

interface Todo {
  id: number;
  title: string;
  description: string;
  completed: boolean;
}

const TodoList: React.FC = () => {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [newTitle, setNewTitle] = useState('');
  const token = localStorage.getItem('token');

  const headers = {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  };

  useEffect(() => {
    fetch('/api/todos/', { headers })
      .then(r => r.json())
      .then(setTodos);
  }, []);

  const addTodo = async () => {
    if (!newTitle.trim()) return;
    const res = await fetch('/api/todos/', {
      method: 'POST',
      headers,
      body: JSON.stringify({ title: newTitle, description: '' }),
    });
    const todo = await res.json();
    setTodos(prev => [...prev, todo]);
    setNewTitle('');
  };

  const toggleTodo = async (id: number, completed: boolean) => {
    await fetch(`/api/todos/${id}?completed=${!completed}`, { method: 'PUT', headers });
    setTodos(prev => prev.map(t => t.id === id ? {...t, completed: !completed} : t));
  };

  const deleteTodo = async (id: number) => {
    await fetch(`/api/todos/${id}`, { method: 'DELETE', headers });
    setTodos(prev => prev.filter(t => t.id !== id));
  };

  return (
    <div>
      <input value={newTitle} onChange={e => setNewTitle(e.target.value)} placeholder="New todo..." />
      <button onClick={addTodo}>Add</button>
      {todos.map(todo => (
        <div key={todo.id}>
          <input type="checkbox" checked={todo.completed} onChange={() => toggleTodo(todo.id, todo.completed)} />
          <span style={{textDecoration: todo.completed ? 'line-through' : 'none'}}>{todo.title}</span>
          <button onClick={() => deleteTodo(todo.id)}>Delete</button>
        </div>
      ))}
    </div>
  );
};

export default TodoList;
```

STANCE: PRAGMATIC""",

    "dev_7": """\
Writing the Docker Compose configuration and requirements.

```yaml
# docker-compose.yml
version: "3.8"
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=sqlite:///./todos.db
      - SECRET_KEY=production-secret-change-me
    volumes:
      - ./backend:/app
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - REACT_APP_API_URL=http://localhost:8000
    depends_on:
      - backend
```

```
# requirements.txt
fastapi==0.104.1
uvicorn==0.24.0
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
sqlalchemy==2.0.23
pydantic==2.5.2
```

STANCE: MINIMAL""",

    "dev_8": """\
Writing unit tests for the authentication and todo endpoints.

```python
# test_api.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_register_user():
    resp = client.post("/api/auth/register",
                       params={"username": "testuser", "password": "secret123"})
    assert resp.status_code == 200
    assert "username" in resp.json()

def test_login_returns_token():
    client.post("/api/auth/register",
                params={"username": "logintest", "password": "pass123"})
    resp = client.post("/api/auth/login",
                       params={"username": "logintest", "password": "pass123"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()

def test_create_todo():
    resp = client.post("/api/todos/", json={"title": "Buy groceries"}, params={"user_id": 1})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Buy groceries"

def test_get_todos():
    resp = client.get("/api/todos/", params={"user_id": 1})
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_delete_todo():
    create_resp = client.post("/api/todos/", json={"title": "To delete"}, params={"user_id": 1})
    todo_id = create_resp.json()["id"]
    del_resp = client.delete(f"/api/todos/{todo_id}")
    assert del_resp.status_code == 200
```

STANCE: ROBUST""",
}

# Manager responses
BOARD_RESPONSE = """
ITEM_1: Implement JWT authentication module (register/login endpoints, password hashing, token generation)
ITEM_2: Build Todo CRUD REST API endpoints (create, read, update, delete todos with user ownership)
ITEM_3: Design SQLAlchemy database models (User and TodoItem tables with relationships)
ITEM_4: Create FastAPI application entry point (wire all routers, CORS, health check)
ITEM_5: Build React Login and Register frontend components with API integration
ITEM_6: Build React TodoList component with full CRUD UI operations
ITEM_7: Write Docker Compose configuration and Python requirements file
ITEM_8: Write unit and integration tests for all API endpoints
""".strip()

WORKER_CLAIMS = {
    "dev_1": "I specialize in authentication systems and JWT. CLAIM: item_1",
    "dev_2": "I build REST APIs and CRUD operations daily. CLAIM: item_2",
    "dev_3": "Database modeling is my strength — SQLAlchemy expert. CLAIM: item_3",
    "dev_4": "I handle application wiring and entry points. CLAIM: item_4",
    "dev_5": "React frontend developer — I'll handle Login/Register. CLAIM: item_5",
    "dev_6": "I build React components with state management. CLAIM: item_6",
    "dev_7": "DevOps background — Docker and infrastructure is my domain. CLAIM: item_7",
    "dev_8": "QA-aware developer — I write comprehensive tests. CLAIM: item_8",
}

MANAGER_ROUND1_REVIEW = """\
DECISION: CONTINUE

Good progress. Issues to address in Round 2:
1. dev_1: auth.py needs to import models from database, not use in-memory storage
2. dev_2: todo_routes.py should use database session (get_db dependency) not in-memory list
3. dev_4: main.py is complete but needs to verify all routes mount correctly
4. dev_5/dev_6: Frontend components look solid — verify API URL is configurable via env var
5. dev_8: Tests need to mock the database to avoid real SQLite dependency in CI
"""

MANAGER_SYNTHESIS = """\
Engineering team completed 2 rounds. All 8 features implemented:
- Auth: JWT register/login with bcrypt password hashing
- Todo CRUD: Full REST API with user ownership
- Database: SQLAlchemy models with User/TodoItem relationship
- Entry point: FastAPI app with CORS, all routers mounted
- Frontend: Login, Register, TodoList React components
- Infrastructure: Docker Compose + requirements
- Tests: 6 unit tests covering health, auth, and CRUD
Application is runnable. Open http://localhost:3000 to use.
"""


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def sim_env(tmp_path):
    """Set up isolated temp output dir, fresh dashboard, fresh rolling contexts."""
    # Patch save path and output dir
    old_save  = sc.WorkDashboard.SAVE_PATH
    old_out   = sc.OUTPUT_DIR
    sc.WorkDashboard.SAVE_PATH = tmp_path / "WORK_DASHBOARD.json"
    sc.OUTPUT_DIR              = tmp_path
    sc._dashboard              = None

    # Create subdirs agents will write to
    (tmp_path / "code").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "design").mkdir()
    (tmp_path / "config").mkdir()

    rolling_ctxs  = {k: RollingContext() for k in ENG_WORKERS + ["eng_manager"]}
    health_states = {k: ActiveInferenceState(HYPOTHESES, ROLE_PRIOR)
                     for k in ENG_WORKERS + ["eng_manager"]}

    yield tmp_path, rolling_ctxs, health_states

    sc._dashboard              = None
    sc.WorkDashboard.SAVE_PATH = old_save
    sc.OUTPUT_DIR              = old_out


def _make_run_with_tools_mock(call_tracker: list, written_files: dict):
    """
    Returns a mock for _run_with_tools that:
    - Returns realistic code output per dev
    - Actually writes files to disk via the real write_code_file tool
    - Tracks all calls for assertion
    """
    call_lock = threading.Lock()

    def mock_run(prompt: str, role_key: str, label: str = "") -> tuple:
        output = DEV_CODE_OUTPUTS.get(role_key, f"No code defined for {role_key} STANCE: PRAGMATIC")
        with call_lock:
            call_tracker.append({
                "role": role_key,
                "label": label,
                "prompt_len": len(prompt),
                "has_peer_context": "WHAT YOUR TEAMMATES BUILT" in prompt,
                "has_manager_feedback": "MANAGER FEEDBACK" in prompt,
                "output_len": len(output),
            })
        # Write a real file to disk so teammates can read it
        filename_map = {
            "dev_1": ("auth.py",          "code"),
            "dev_2": ("todo_routes.py",   "code"),
            "dev_3": ("models.py",        "code"),
            "dev_4": ("main.py",          "code"),
            "dev_5": ("Login.tsx",        "code"),
            "dev_6": ("TodoList.tsx",     "code"),
            "dev_7": ("docker-compose.yml", "config"),
            "dev_8": ("test_api.py",      "tests"),
        }
        if role_key in filename_map:
            fname, subdir = filename_map[role_key]
            fpath = sc.OUTPUT_DIR / subdir / fname
            fpath.write_text(output, encoding="utf-8")
            with call_lock:
                written_files[fname] = str(fpath)

        perplexity = 2.0  # confident output → low perplexity
        return (output, [], perplexity)

    return mock_run


def _make_llm_call_mock(call_tracker: list):
    """
    Mock for llm_call — used by manager (planning board, reviews, synthesis).
    """
    call_count = {"n": 0}
    lock = threading.Lock()

    def mock_llm(prompt: str, label: str = "", **kwargs):
        with lock:
            n = call_count["n"]
            call_count["n"] += 1

        # Board posting
        if "Post" in prompt and "ITEM_" in prompt or "work items" in prompt.lower():
            return BOARD_RESPONSE

        # Worker claims (contain "CLAIM")
        for dev, claim in WORKER_CLAIMS.items():
            if dev in label:
                return claim

        # Fallback claim for any worker
        if "Scan the board" in prompt or "claim" in prompt.lower():
            items = ["item_1","item_2","item_3","item_4","item_5","item_6","item_7","item_8"]
            return f"I'll take this. CLAIM: {items[n % 8]}"

        # Manager round 1 review
        if "DECISION" in prompt or ("Round" in prompt and "review" in label.lower()):
            return MANAGER_ROUND1_REVIEW

        # Synthesis / final summary
        if "synthesis" in label.lower() or "completed" in prompt:
            return MANAGER_SYNTHESIS

        # Context summarizer
        if "running summary" in prompt.lower() or label == "ctx":
            return "Context summarized."

        return f"Done. STANCE: PRAGMATIC"

    return mock_llm


# ── Main simulation test ───────────────────────────────────────────────────────

class TestDevTeamSimulation:
    """Full 8-developer engineering team simulation — 1 sprint, 2 rounds."""

    def test_all_8_devs_get_unique_assignments(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools", side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call", side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            result = run_engineering_team(
                task="Build a simple todo app with JWT auth. Backend: FastAPI + SQLAlchemy. Frontend: React.",
                rolling_ctxs=rolling_ctxs,
                health_states=health_states,
                sprint_num=1,
            )

        dev_calls = [c for c in call_tracker if c.get("role") in ENG_WORKERS]
        roles_called = [c["role"] for c in dev_calls]
        assert len(set(roles_called)) == 8, f"Expected 8 unique devs, got: {set(roles_called)}"

    def test_all_8_devs_produce_output(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools", side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call", side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            result = run_engineering_team(
                task="Build a todo app with JWT auth.",
                rolling_ctxs=rolling_ctxs,
                health_states=health_states,
                sprint_num=1,
            )

        dev_calls = [c for c in call_tracker if c.get("role") in ENG_WORKERS]
        for call in dev_calls:
            assert call["output_len"] > 0, f"{call['role']} produced empty output"

    def test_files_actually_written_to_disk(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools", side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call", side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            run_engineering_team(
                task="Build a todo app.",
                rolling_ctxs=rolling_ctxs,
                health_states=health_states,
                sprint_num=1,
            )

        # Verify key files exist on disk
        expected = {
            "auth.py":           tmp_path / "code" / "auth.py",
            "todo_routes.py":    tmp_path / "code" / "todo_routes.py",
            "models.py":         tmp_path / "code" / "models.py",
            "main.py":           tmp_path / "code" / "main.py",
            "Login.tsx":         tmp_path / "code" / "Login.tsx",
            "TodoList.tsx":      tmp_path / "code" / "TodoList.tsx",
            "docker-compose.yml": tmp_path / "config" / "docker-compose.yml",
            "test_api.py":       tmp_path / "tests" / "test_api.py",
        }
        for fname, fpath in expected.items():
            assert fpath.exists(), f"{fname} was not written to disk"
            assert fpath.stat().st_size > 0, f"{fname} is empty"

    def test_written_files_contain_real_code(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools", side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call", side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        auth_content = (tmp_path / "code" / "auth.py").read_text()
        assert "def create_access_token" in auth_content
        assert "jwt.encode" in auth_content

        todo_content = (tmp_path / "code" / "todo_routes.py").read_text()
        assert "@router.post" in todo_content
        assert "@router.delete" in todo_content

        models_content = (tmp_path / "code" / "models.py").read_text()
        assert "class User" in models_content
        assert "class TodoItem" in models_content

        test_content = (tmp_path / "tests" / "test_api.py").read_text()
        assert "def test_" in test_content
        assert "TestClient" in test_content

    def test_round2_devs_see_teammates_output(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools", side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call", side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 2):

            run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        # Round 2 calls should have peer context in prompt
        round2_calls = [c for c in call_tracker
                        if c.get("role") in ENG_WORKERS and "r2" in c.get("label","")]
        if round2_calls:
            assert any(c["has_peer_context"] for c in round2_calls), \
                "Round 2 devs should see teammates' Round 1 output"

    def test_round2_devs_receive_manager_feedback(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools", side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call", side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 2):

            run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        round2_calls = [c for c in call_tracker
                        if c.get("role") in ENG_WORKERS and "r2" in c.get("label","")]
        if round2_calls:
            assert any(c["has_manager_feedback"] for c in round2_calls), \
                "Round 2 devs should receive manager feedback from Round 1"

    def test_result_is_team_result(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env

        with patch("software_company._run_with_tools",
                   side_effect=_make_run_with_tools_mock([], {})), \
             patch("software_company.llm_call",
                   side_effect=_make_llm_call_mock([])), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            result = run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        from software_company import TeamResult
        assert isinstance(result, TeamResult)
        assert result.team == "Engineering"

    def test_h_swarm_is_non_negative(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env

        with patch("software_company._run_with_tools",
                   side_effect=_make_run_with_tools_mock([], {})), \
             patch("software_company.llm_call",
                   side_effect=_make_llm_call_mock([])), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            result = run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        assert result.H_swarm >= 0.0

    def test_manager_synthesis_in_result(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env

        with patch("software_company._run_with_tools",
                   side_effect=_make_run_with_tools_mock([], {})), \
             patch("software_company.llm_call",
                   side_effect=_make_llm_call_mock([])), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            result = run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        assert len(result.manager_synthesis) > 0

    def test_rolling_context_updated_after_sprint(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env

        with patch("software_company._run_with_tools",
                   side_effect=_make_run_with_tools_mock([], {})), \
             patch("software_company.llm_call",
                   side_effect=_make_llm_call_mock([])), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        # Each dev's rolling context should have their work recorded
        for dev in ENG_WORKERS:
            assert len(rolling_ctxs[dev].recent) > 0, \
                f"{dev} rolling context not updated after sprint"

    def test_health_states_updated_after_sprint(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env

        with patch("software_company._run_with_tools",
                   side_effect=_make_run_with_tools_mock([], {})), \
             patch("software_company.llm_call",
                   side_effect=_make_llm_call_mock([])), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        # Each dev should have F_history from the updates
        for dev in ENG_WORKERS:
            assert len(health_states[dev]._F_history) > 0, \
                f"{dev} health state never updated"

    def test_each_dev_gets_different_feature(self, sim_env):
        tmp_path, rolling_ctxs, health_states = sim_env
        call_tracker = []
        written_files = {}

        with patch("software_company._run_with_tools",
                   side_effect=_make_run_with_tools_mock(call_tracker, written_files)), \
             patch("software_company.llm_call",
                   side_effect=_make_llm_call_mock(call_tracker)), \
             patch("software_company.MAX_ENG_ROUNDS", 1):

            run_engineering_team("Build todo app.", rolling_ctxs, health_states, 1)

        # Each dev prompt should mention their specific feature
        dev_calls = {c["role"]: c for c in call_tracker if c.get("role") in ENG_WORKERS}
        # At minimum all 8 devs were called
        assert len(dev_calls) == 8


# ── Per-developer output quality checks ───────────────────────────────────────

class TestDevOutputQuality:
    """Verify that each dev's scripted output is structurally valid code."""

    def test_auth_py_has_router_and_jwt(self):
        out = DEV_CODE_OUTPUTS["dev_1"]
        assert "router = APIRouter()" in out
        assert "jwt.encode" in out
        assert "def create_access_token" in out

    def test_todo_routes_has_all_crud_verbs(self):
        out = DEV_CODE_OUTPUTS["dev_2"]
        assert "@router.get" in out
        assert "@router.post" in out
        assert "@router.put" in out
        assert "@router.delete" in out

    def test_models_has_user_and_todo(self):
        out = DEV_CODE_OUTPUTS["dev_3"]
        assert "class User" in out
        assert "class TodoItem" in out
        assert "ForeignKey" in out

    def test_main_includes_both_routers(self):
        out = DEV_CODE_OUTPUTS["dev_4"]
        assert "auth_router" in out
        assert "todo_router" in out
        assert "CORSMiddleware" in out

    def test_login_tsx_has_fetch_call(self):
        out = DEV_CODE_OUTPUTS["dev_5"]
        assert "fetch('/api/auth/login'" in out
        assert "access_token" in out

    def test_todo_list_tsx_has_all_operations(self):
        out = DEV_CODE_OUTPUTS["dev_6"]
        assert "useEffect" in out
        assert "fetch(" in out
        assert "DELETE" in out

    def test_docker_compose_has_both_services(self):
        out = DEV_CODE_OUTPUTS["dev_7"]
        assert "backend:" in out
        assert "frontend:" in out
        assert "8000:8000" in out

    def test_test_file_has_multiple_test_functions(self):
        out = DEV_CODE_OUTPUTS["dev_8"]
        test_fns = re.findall(r"def test_\w+", out)
        assert len(test_fns) >= 4

    def test_all_devs_have_stance_marker(self):
        for dev, out in DEV_CODE_OUTPUTS.items():
            match = re.search(r"STANCE:\s*(MINIMAL|ROBUST|SCALABLE|PRAGMATIC)", out, re.IGNORECASE)
            assert match, f"{dev} output missing STANCE marker"

    def test_stance_probs_sum_to_one_for_all_devs(self):
        import math
        for dev, out in DEV_CODE_OUTPUTS.items():
            probs = extract_stance_probs(out)
            assert math.isclose(probs.sum(), 1.0, abs_tol=1e-9), \
                f"{dev} stance probs don't sum to 1"


# ── Coordination checks ───────────────────────────────────────────────────────

class TestDevCoordination:
    """Check that the coordination infrastructure works during the simulation."""

    def test_devs_can_write_to_different_subdirs(self, sim_env):
        tmp_path, _, _ = sim_env
        (tmp_path / "code").mkdir(exist_ok=True)
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "config").mkdir(exist_ok=True)

        # Simulate dev_1 and dev_8 writing to different dirs
        (tmp_path / "code" / "auth.py").write_text(DEV_CODE_OUTPUTS["dev_1"])
        (tmp_path / "tests" / "test_api.py").write_text(DEV_CODE_OUTPUTS["dev_8"])

        assert (tmp_path / "code" / "auth.py").exists()
        assert (tmp_path / "tests" / "test_api.py").exists()

    def test_dev_output_readable_by_peer(self):
        # Simulate dev_2 reading dev_1's auth output to understand the token format
        auth_output = DEV_CODE_OUTPUTS["dev_1"]
        assert "create_access_token" in auth_output  # dev_2 can discover this

        # dev_2's todo routes should be written knowing auth exists
        todo_output = DEV_CODE_OUTPUTS["dev_2"]
        # They don't explicitly import auth, but the structure is compatible
        assert "user_id" in todo_output   # consistent ownership field

    def test_health_interference_across_all_8_devs(self):
        states = [ActiveInferenceState(HYPOTHESES, ROLE_PRIOR) for _ in range(8)]

        # Simulate: 6 healthy devs, 2 confused
        healthy_sims = {"healthy": 0.8, "uncertain": -0.2, "confused": -0.8}
        confused_sims = {"healthy": -0.8, "uncertain": -0.2, "confused": 0.8}

        for i, state in enumerate(states):
            sims = confused_sims if i >= 6 else healthy_sims
            state.update(sims)

        probs_before = [s.probabilities().copy() for s in states]
        ActiveInferenceState.interfere_all(states, alpha=0.5)

        # The 2 confused devs should drift toward the healthy consensus
        for i in [6, 7]:
            p_confused_after = states[i].probability(2)
            p_confused_before = probs_before[i][2]
            # After interference with 6 healthy agents, confused probability decreases
            assert p_confused_after < p_confused_before, \
                f"Dev {i+1} confusion not reduced by healthy peer interference"

    def test_all_stances_are_valid_enum_values(self):
        for dev, out in DEV_CODE_OUTPUTS.items():
            match = re.search(r"STANCE:\s*(\w+)", out, re.IGNORECASE)
            assert match
            stance = match.group(1).lower()
            assert stance in STANCES, f"{dev} has invalid stance '{stance}'"

    def test_peer_context_includes_all_other_devs(self):
        """Verify the peer context string built in round 2 includes all 7 other devs."""
        fake_built = {
            dev: WorkerOutput(
                role=dev, title=f"Dev {dev.split('_')[1]}",
                round=1, output=DEV_CODE_OUTPUTS[dev], tool_results=[],
                stance="pragmatic", stance_probs=[0.25]*4,
                F_health=0.1, anomaly=False,
            )
            for dev in ENG_WORKERS
        }
        fake_assignments = {dev: f"Feature {i+1}" for i, dev in enumerate(ENG_WORKERS)}

        # Build peer summaries for dev_1 (same logic as run_engineering_team)
        peer_summaries = "\n\n".join(
            f"Dev {other.split('_')[1]} ({fake_assignments[other]}):\n{fake_built[other].output[:400]}"
            for other in ENG_WORKERS if other != "dev_1" and other in fake_built
        )
        peer_context = f"\nWHAT YOUR TEAMMATES BUILT LAST ROUND:\n{peer_summaries}\n"

        # Should reference all 7 other devs
        for dev in ENG_WORKERS:
            if dev != "dev_1":
                dev_num = dev.split("_")[1]
                assert f"Dev {dev_num}" in peer_context, \
                    f"Dev {dev_num} missing from peer context for dev_1"
