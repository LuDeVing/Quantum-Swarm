from fastapi import FastAPI, HTTPException
from typing import List
import crud
import schemas

app = FastAPI(title="Quantum Swarm Task API")

@app.get("/tasks", response_model=List[schemas.Task])
def read_tasks():
    return crud.get_tasks()

@app.post("/tasks", response_model=schemas.Task)
def create_task(task: schemas.TaskCreate):
    return crud.create_task(task)

@app.get("/tasks/{task_id}", response_model=schemas.Task)
def read_task(task_id: int):
    db_task = crud.get_task(task_id)
    if db_task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return db_task

@app.put("/tasks/{task_id}", response_model=schemas.Task)
def update_task(task_id: int, task: schemas.TaskCreate):
    db_task = crud.update_task(task_id, task)
    if db_task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return db_task

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    if not crud.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return {"message": "Task deleted"}
