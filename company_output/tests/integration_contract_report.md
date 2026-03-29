# integration_contract_report.md

# API Integration & Contract Verification Report

## 1. Executive Summary
This report defines the current state of the API integration between the Fastify backend and the React frontend. The contract is currently enforced by Pydantic on the backend (schemas.py) and TypeScript interfaces in the frontend (taskStore.ts).

## 2. API Contract Specification (Source of Truth)
| Endpoint | Method | Expected Code | Request/Response Mapping |
| :--- | :--- | :--- | :--- |
| `/tasks` | POST | 201 | {title: str} -> {id: int, title: str, status: str, created_at: str} |
| `/tasks` | GET | 200 | N/A -> List[{id: int, title: str, status: str, created_at: str}] |
| `/tasks/:id` | PUT | 200 | {status: str} -> {id: int, status: str} |
| `/tasks/:id` | DELETE | 204 | N/A -> N/A |

## 3. Integration Status
- **Backend (main.py/schemas.py):** Implemented using Pydantic V2. Validated against the requirement (1-100 chars, specific statuses).
- **Frontend (src/hooks/useTaskMutation.ts):** Implemented using an optimistic approach with `requestQueue.ts`.
- **Race Condition Testing:** I have implemented a suite in `tests/test_performance_and_race.py` that bombards the `/tasks` endpoint to ensure the backend serializes concurrent requests correctly without database lock errors.

## 4. Identified Gaps (Critical)
1. **Schema Mismatch:** The backend uses `int` for `id` (schemas.py), but the CEO's brief requires `UUID`. **This must be refactored before deployment.**
2. **Status Inconsistency:** Backend uses `todo|in_progress|done`, while frontend `taskStore.ts` uses `pending|synced`. This will cause UI synchronization failures.
3. **Database Migration:** No automated migration script (like alembic) is visible in the codebase to sync `models.py` with the physical DB.

## 5. Stance
STANCE: [PRAGMATIC]
