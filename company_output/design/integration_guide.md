## Integration Guide

This guide outlines the integration process for the Personal Finance Tracker application.

### 1. Data Model

The application uses the following data model:

```typescript
interface Transaction {
    id: string; // UUID generated client-side (UUID v4)
    date: string; // ISO 8601 date string (YYYY-MM-DD)
    amount: number; // Non-negative number, stored in cents
    category: string; // User-defined category
    description: string; // User-provided description (max 255 characters)
    type: "income" | "expense"; // Enum to differentiate income vs expense
}
```

### 2. TransactionService API

The application uses the `TransactionService` API to interact with transactions stored in `localStorage`.

```typescript
interface TransactionService {
  addTransaction(transaction: Omit<Transaction, "id">): Transaction;
  getTransaction(id: string): Transaction | null;
  updateTransaction(id: string, updates: Partial<Omit<Transaction, "id">>): Transaction | null;
  deleteTransaction(id: string): boolean;
  getAllTransactions(): Transaction[];
  // Potentially add filterTransactions(filter: TransactionFilter): Transaction[];
}

// Example filter
interface TransactionFilter {
    category?: string;
    type?: "income" | "expense";
    dateRange?: { start: string; end: string }; // ISO 8601 date strings
}
```

### 3. Integration Steps

1.  **Implement the `TransactionService`**: Implement the `TransactionService` interface using the `localStorage` API. Ensure proper error handling and user feedback.
2.  **Data Migration**: Implement the data migration strategy as described in `data_migration_strategy.md`.
3.  **Input Validation**: Implement input validation for all `Transaction` fields. Display clear error messages to the user.
4.  **Error Handling**: Implement error handling for all `localStorage` operations. Display user-friendly error messages.
