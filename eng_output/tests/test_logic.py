from app.services.task_manager import TaskManager
from app.models.database import init_db
import sys

def test_task_crud():
    init_db()
    
    # Test Create
    task_id = TaskManager.create_task("Test Task", "Test Description")
    print(f"Created task: {task_id}")
    assert task_id > 0
    
    # Test Read
    task = TaskManager.get_task(task_id)
    print(f"Read task: {task}")
    assert task is not None
    assert task["title"] == "Test Task"
    
    # Test Update
    TaskManager.update_task(task_id, "Updated Title", "Updated Description", "completed")
    updated_task = TaskManager.get_task(task_id)
    print(f"Updated task: {updated_task}")
    assert updated_task["title"] == "Updated Title"
    assert updated_task["status"] == "completed"
    
    # Test Get All
    tasks = TaskManager.get_all_tasks()
    print(f"Tasks count: {len(tasks)}")
    assert len(tasks) >= 1
    
    # Test Delete
    success = TaskManager.delete_task(task_id)
    print(f"Deleted task: {success}")
    assert success is True
    assert TaskManager.get_task(task_id) is None
    
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    test_task_crud()
