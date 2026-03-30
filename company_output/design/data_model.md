## Transaction Data Model

This document defines the data model for a transaction in the Personal Finance Tracker.

### Fields

| Field | Type | Nullable | Constraints | Description |
|---|---|---|---|---| 
| id | string | false | UUID | Unique identifier for the transaction. |
| amount | number | false |  | The amount of the transaction. Positive for income, negative for expense. |
| category | string | false |  | The category of the transaction (e.g., "Food", "Salary"). |
| description | string | true |  | A description of the transaction. |
| date | string | false | ISO 8601 Date | The date of the transaction. |

### Example

```json
{
  "id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
  "amount": -50.00,
  "category": "Food",
  "description": "Lunch at a restaurant",
  "date": "2024-07-24"
}
```
