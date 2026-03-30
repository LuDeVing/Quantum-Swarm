```typescript
interface Transaction {
    id: string; // UUID generated client-side
    date: string; // ISO 8601 date string (YYYY-MM-DD)
    amount: number;
    category: string;
    description: string;
    type: 'income' | 'expense'; // Enum to differentiate income vs expense
}

interface APIResponse<T> {
    success: boolean;
    data?: T;
    error?: string;
}
```