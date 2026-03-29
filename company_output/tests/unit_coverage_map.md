# Unit Coverage Map

| Component | Function | Logic Branch Covered | Missing Coverage / Edge Cases |
| :--- | :--- | :--- | :--- |
| `crud.py` | `create_task` | Basic creation, schema validation (via Pydantic) | Database connection timeout, unique title constraint violations |
| `crud.py` | `get_tasks` | Fetch all records | Empty database state, connection pooling exhaustion |
| `crud.py` | `update_task` | Update existing task | ID not found, invalid status transitions (e.g. invalid status string) |
| `crud.py` | `delete_task` | Remove existing task | ID not found |
| `main.py` | `POST /tasks` | Successful creation, 422 for invalid body | Body parsing errors, schema drift (unexpected fields) |
| `main.py` | `PUT /tasks/:id` | Success, 404 for missing ID | Invalid data types in path params |

Note: Coverage is currently focused on the Happy Path and basic Pydantic failures. We lack automated testing for database-level constraint failures and connection-level resilience scenarios.
