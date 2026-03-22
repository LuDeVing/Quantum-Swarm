from pydantic import BaseModel, Field
from typing import Optional
import uuid


class TaskCreate(BaseModel):
    text: str
    token_budget: int = Field(default=100_000, ge=10_000, le=500_000)


class Claim(BaseModel):
    entity: str
    assertion: str
    confidence: float
    source_type: str  # "agent_inference" | "retrieved_fact"
    verified: bool


class TraceEvent(BaseModel):
    agent: str
    event: str
    energy: Optional[float] = None
    timestamp: Optional[str] = None


class TaskResponse(BaseModel):
    id: str
    status: str
    text: str
    token_budget: int
    tokens_used: int = 0
    claims: list[Claim] = []
    trace: list[TraceEvent] = []


def new_task_id() -> str:
    return str(uuid.uuid4())
