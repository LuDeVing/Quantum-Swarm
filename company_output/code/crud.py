from typing import List, Optional
from datetime import datetime
from .schemas import Task, TaskCreate

# In-memory database for Task MVP
tasks_db = []
id_counter = 1

def get_tasks() -> List[Task]:
    return [Task(**t) for t in tasks_db]

def get_task(task_id: int) -> Optional[Task]:
    for t in tasks_db:
        if t["id"] == task_id:
            return Task(**t)
    return None

def create_task(task: TaskCreate) -> Task:
    global id_counter
    new_task = {
        "id": id_counter,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "created_at": datetime.now()
    }
    tasks_db.append(new_task)
    id_counter += 1
    return Task(**new_task)

def update_task(task_id: int, task_data: TaskCreate) -> Optional[Task]:
    for t in tasks_db:
        if t["id"] == task_id:
            t.update(task_data.dict())
            return Task(**t)
    return None

def delete_task(task_id: int) -> bool:
    global tasks_db
    for i, t in enumerate(tasks_db):
        if t["id"] == task_id:
            tasks_db.pop(i)
            return True
    return False
