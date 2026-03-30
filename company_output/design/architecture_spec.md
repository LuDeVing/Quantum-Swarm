Okay, let's synthesize this into a single, actionable Architecture Decision Record (ADR) for Sprint 2. This ADR will incorporate data encryption, input validation, and a data migration strategy, as well as clearly define the `TransactionService` API.

**Architecture Decision Record: Personal Finance Tracker - Sprint 2**

**1. Introduction**

This document updates the architecture for the Personal Finance Tracker, focusing on secure data persistence in `localStorage` using AES-256 encryption and defining the `TransactionService`. It addresses data migration and input validation requirements for Sprint 2.  It aims to provide a stable, secure, and usable application with reliable data persistence.

**2. Updated Data Model**

The core data structure is the `Transaction` interface, with specific constraints and validation rules implemented.

```typescript
interface Transaction {
    id: string; // UUID generated client-side (UUID v4)
    date: string; // ISO 8601 date string (YYYY-MM-DD)
    amount: number; // Integer representing cents (e.g., $10.50 is 1050).  Non-negative for income, negative for expenses.
    category: string; // User-defined category
    description: string; // User-provided description
}
```

*   **`id`**:  Universally Unique Identifier (UUID) v4, generated client-side.  This avoids potential conflicts and simplifies data management.
*   **`date`**:  ISO 8601 date string (`YYYY-MM-DD`).  Ensures consistent date formatting across different locales.
*   **`amount`**:  Integer representing the transaction amount in cents. This avoids floating-point precision issues. Positive values represent income, negative values represent expenses.
*   **`category`**: User-defined category string.
*   **`description`**: User-provided description string.

**3. TransactionService API Contract**

This section defines the API for interacting with transaction data.  Since this is a front-end only application, the API is implemented as a JavaScript service interacting with `localStorage`.

```typescript
interface TransactionService {
    addTransaction(transaction: Transaction): void;
    getTransactions(): Transaction[];
    getTransaction(id: string): Transaction | undefined;
    updateTransaction(id: string, transaction: Transaction): void;
    deleteTransaction(id: string): void;
    getTransactionsByCategory(category: string): Transaction[];
}
```

**Implementation Details:**

*   **`addTransaction(transaction: Transaction)`**: Adds a new transaction to `localStorage`.  Generates a UUID v4 for the `id` if one is not provided.  Validates the transaction data before saving.
*   **`getTransactions(): Transaction[]`**: Retrieves all transactions from `localStorage`, decrypts the data using AES-256, and returns them as an array of `Transaction` objects.
*   **`getTransaction(id: string): Transaction | undefined`**: Retrieves a specific transaction by its `id` from `localStorage`. Returns `undefined` if the transaction is not found.  Decrypts the data.
*   **`updateTransaction(id: string, transaction: Transaction)`**: Updates an existing transaction in `localStorage`. Validates the transaction data before saving.
*   **`deleteTransaction(id: string): void`**: Deletes a transaction from `localStorage` by its `id`.
*   **`getTransactionsByCategory(category: string): Transaction[]`**: Retrieves transactions filtered by a specific category from `localStorage`.  Decrypts the data.

**4. Data Persistence: LocalStorageService with Encryption**

The `LocalStorageService` is responsible for handling all interactions with `localStorage`, including encryption and decryption.

```typescript
interface LocalStorageService {
    saveData(key: string, data: any): void;
    getData(key: string): any | null;
    removeData(key: string): void;
}
```

*   **Encryption**: All data stored in `localStorage` will be encrypted using AES-256 encryption with a randomly generated key stored securely using the Web Crypto API. A new key should be generated on initial load if no key exists.  Engineering should use a well-vetted library like `crypto-js` or a native Web Crypto API implementation.
*   **`saveData(key: string, data: any)`**: Serializes the `data` to JSON, encrypts it using AES-256, and saves it to `localStorage` under the specified `key`.
*   **`getData(key: string)`**: Retrieves the encrypted data from `localStorage` using the specified `key`, decrypts it using AES-256, and parses it from JSON. Returns `null` if the key does not exist.
*   **`removeData(key: string)`**: Removes the data associated with the specified `key` from `localStorage`.

**Implementation Notes:**

*   The `TransactionService` will use the `LocalStorageService` to persist data.
*   The `localStorage` key for transaction data will be `"transactions"`.
*   Consider using a library like `crypto-js` or the Web Crypto API for AES-256 encryption.

**5. Data Migration Strategy**

This section describes the strategy for migrating data if the data model changes in the future. Since we are using `localStorage`, migrations will be handled client-side.

**Scenario: Adding a New Field to the `Transaction` Interface**

1.  **Version Check:** When the application loads, check for a version number in `localStorage` (e.g., `"dataVersion": "1"`).
2.  **Migration Logic:** If the current application version is higher than the version in `localStorage`, execute the necessary migration logic.  For example:

```typescript
function migrateData(transactions: any[], oldVersion: string, newVersion: string): Transaction[] {
    let migratedTransactions: Transaction[] = [];

    if (oldVersion === "1" && newVersion === "2") {
        // Example: Adding a "notes" field
        migratedTransactions = transactions.map(transaction => ({
            ...transaction,
            notes: "" // Default value for the new field
        }));
    }
    //Add more migrations as needed.

    return migratedTransactions;
}
```

3.  **Update Data:** After migration, update the `"transactions"` data in `localStorage` with the migrated data.
4.  **Update Version:** Update the `"dataVersion"` in `localStorage` to the current version.

**Important Considerations:**

*   Provide default values for new fields to avoid data loss.
*   Test migrations thoroughly to ensure data integrity.
*   Implement migrations in a way that is backwards-compatible (i.e., the application should still function if a migration fails).
*   For more complex migrations, consider using a more robust data migration tool or library.

**6. Input Validation**

Robust input validation is crucial for data integrity and preventing errors.

*   **Amount:** Must be a number, and should be validated on input using a number type. Must be converted to an Integer *before* being stored (representing cents). Should handle `parseInt()` errors robustly.
*   **Date:** Must be a valid ISO 8601 date string (`YYYY-MM-DD`). Use a date picker component to ensure correct formatting. Or use a RegEx.
*   **Category:**  Implement input length restrictions.
*   **Description:** Implement input length restrictions.

**7. Error Handling**

*   Implement a standardized error alert component (as defined by the Design team) to display error messages to the user.
*   Catch and handle potential errors during data encryption/decryption. Display a user-friendly error message if encryption/decryption fails.  Consider prompting the user to reset the data (with a warning that all data will be lost).
*   Handle errors during `localStorage` access (e.g., if `localStorage` is full).

**8. Security Considerations**

*   **Data Encryption:**  AES-256 encryption of all data stored in `localStorage`.
*   **Input Validation:**  Prevent malicious input from being stored.
*   **Dependency Scanning:**  Regularly scan dependencies for known vulnerabilities.
*   **Avoid Storing Sensitive Information:**  This application should not store any highly sensitive information (e.g., passwords, credit card numbers).

**9. Risks and Mitigation**

*   **Data Loss:**  Although we are implementing encryption and validation, there is always a risk of data loss due to browser errors, user error, or other unforeseen circumstances.  Provide a clear warning to the user that data is stored locally and may be lost.  Consider implementing a simple export/import feature in the future to allow users to back up their data.
*   **localStorage Limitations:**  `localStorage` has limited storage capacity (typically 5-10MB).  This application is not suitable for storing large amounts of data.  Consider implementing pagination or other techniques to limit the amount of data stored in `localStorage`.

**10. Integration Contract (for Engineering)**

1.  **Implement `TransactionService`:** Implement the `TransactionService` interface, using the `LocalStorageService` for data persistence.
2.  **Implement `LocalStorageService`:** Implement the `LocalStorageService` interface, including AES-256 encryption and decryption.
3.  **Implement Data Migration:** Implement the data migration strategy to handle future data model changes.
4.  **Implement Input Validation:**  Implement robust input validation to prevent invalid data from being stored.
5.  **Implement Error Handling:** Implement the standardized error alert component and handle potential errors during data encryption/decryption and `localStorage` access.
6.  **Address QA Findings:**  Address all security and accessibility issues identified by QA.

**11. Acceptance Criteria (Architecture)**

*   Data model includes all necessary fields with types and constraints.
*   API contracts for `TransactionService` and `LocalStorageService` are clearly defined and documented.
*   Data migrations strategy is defined.
*   Data model is suitable for `localStorage` use with encryption.
*   The use of AES-256 encryption is documented with justification for chosen method (library or web crypto api).
*   This ADR is updated in the case of new learnings or discoveries during implementation.

This ADR provides a comprehensive architectural blueprint for Sprint 2, ensuring a stable, secure, and usable personal finance tracker with reliable data persistence.