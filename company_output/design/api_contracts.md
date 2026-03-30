## TransactionService API Contracts

This document defines the API contracts for the `TransactionService`, which manages transactions in the Personal Finance Tracker.

### Data Structures

```typescript
interface Transaction {
  id: string; // UUID generated client-side
  amount: number;
  category: string;
  description?: string;
  date: string; // ISO 8601 Date
}
```

### Methods

#### `addTransaction(transaction: Transaction): Transaction`

Adds a new transaction.

*   **Request Schema:** `Transaction`
*   **Response Schema:** `Transaction` (the added transaction)
*   **Error Cases:**
    *   Invalid `Transaction` data: Returns an error with a message describing the validation failure.

#### `getTransactions(): Transaction[]`

Gets all transactions.

*   **Response Schema:** `Transaction[]`
*   **Error Cases:**
    *   None.

#### `updateTransaction(id: string, transaction: Transaction): Transaction`

Updates an existing transaction.

*   **Request Schema:** `Transaction`
*   **Response Schema:** `Transaction` (the updated transaction)
*   **Error Cases:**
    *   Transaction with `id` not found: Returns an error with a message indicating that the transaction does not exist.
    *   Invalid `Transaction` data: Returns an error with a message describing the validation failure.

#### `deleteTransaction(id: string): void`

Deletes a transaction.

*   **Error Cases:**
    *   Transaction with `id` not found: Returns an error with a message indicating that the transaction does not exist.

### Input Validation

All `Transaction` data must be validated before being saved. Validation rules:

*   `id`: Must be a valid UUID.
*   `amount`: Must be a number.
*   `category`: Must be a non-empty string.
*   `date`: Must be a valid ISO 8601 date string.

