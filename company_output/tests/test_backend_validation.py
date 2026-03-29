import pytest
from pydantic import ValidationError
from code.schemas import TaskBase, TaskCreate, Task

def test_task_schema_validation():
    # Happy path
    task_data = {"title": "Test Task", "status": "todo"}
    task = TaskBase(**task_data)
    assert task.title == "Test Task"
    
    # Boundary: Title length 1
    task_short = TaskBase(title="a", status="todo")
    assert len(task_short.title) == 1
    
    # Boundary: Title length 100
    task_long = TaskBase(title="a" * 100, status="todo")
    assert len(task_long.title) == 100

def test_task_schema_validation_errors():
    # Invalid: Title empty
    with pytest.raises(ValidationError):
        TaskBase(title="", status="todo")
    
    # Invalid: Title too long
    with pytest.raises(ValidationError):
        TaskBase(title="a" * 101, status="todo")
    
    # Invalid: Status
    with pytest.raises(ValidationError):
        TaskBase(title="Test", status="invalid_status")

def test_task_full_model_serialization():
    # Simulate DB object
    data = {
        "id": 1,
        "title": "Valid Task",
        "status": "todo",
        "created_at": "2023-10-27T10:00:00Z"
    }
    task = Task(**data)
    assert task.id == 1
    assert task.status == "todo"
