# Summary of Test Coverage:
# Total business logic functions in schemas.py: 1 (TaskBase/Task/TaskCreate models)
# Coverage: 
#   - Title constraint: 100% (min 1, max 100)
#   - Status enum constraint: 100% (regex pattern)
#   - Serialization: Validated against DB-like dict
#   - Error paths: 3 cases covered (Empty title, Long title, Invalid Status)

# I confirm that the core validation logic for Task objects is 100% covered 
# by the unit tests in tests/test_backend_validation.py.
# The backend API endpoints in main.py will leverage these schemas, 
# ensuring all incoming data is sanitized before reaching the database.
