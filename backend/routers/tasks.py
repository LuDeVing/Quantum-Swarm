import json
from fastapi import APIRouter, HTTPException

from backend.db import get_db
from backend.models.task import TaskCreate, TaskResponse, new_task_id

router = APIRouter()


@router.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(body: TaskCreate):
    task_id = new_task_id()
    async with await get_db() as db:
        await db.execute(
            "INSERT INTO tasks (id, text, token_budget) VALUES (?, ?, ?)",
            (task_id, body.text, body.token_budget),
        )
        await db.commit()

    # TODO: dispatch to SwarmManager here
    # await swarm_manager.submit_task(task_id, body.text, body.token_budget)

    return TaskResponse(
        id=task_id,
        status="PENDING",
        text=body.text,
        token_budget=body.token_budget,
    )


@router.get("/tasks/{task_id}/report", response_model=TaskResponse)
async def get_report(task_id: str):
    async with await get_db() as db:
        db.row_factory = lambda c, r: dict(zip([d[0] for d in c.description], r))
        async with db.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskResponse(
        id=row["id"],
        status=row["status"],
        text=row["text"],
        token_budget=row["token_budget"],
        tokens_used=row["tokens_used"] or 0,
        claims=json.loads(row["claims"] or "[]"),
        trace=json.loads(row["trace"] or "[]"),
    )


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str):
    async with await get_db() as db:
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()
