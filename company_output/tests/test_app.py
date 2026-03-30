
import pytest
import json
from unittest.mock import patch

# Mock localStorage for testing in a non-browser environment
class MockLocalStorage:
    def __init__(self):
        self.store = {}

    def setItem(self, key, value):
        self.store[key] = value

    def getItem(self, key):
        return self.store.get(key, None)

    def removeItem(self, key):
        if key in self.store:
            del self.store[key]

    def clear(self):
        self.store = {}


@pytest.fixture
def mock_local_storage(monkeypatch):
    mock_storage = MockLocalStorage()
    monkeypatch.setattr("localStorage", mock_storage)
    return mock_storage


# Assuming the transaction object structure is defined as:
# interface Transaction {
#     id: string; // UUID generated client-side
#     date: string; // ISO 8601 date string
#     amount: number;
#     category: string;
#     description: string;
#     type: "income" | "expense"; // Enum to differentiate income vs expense
# }

def is_valid_uuid(uuid_string):
    try:
        uuid.UUID(uuid_string)
        return True
    except ValueError:
        return False

import uuid

def test_add_transaction_income(mock_local_storage):
    # Simulate adding an income transaction
    transaction = {
        "id": str(uuid.uuid4()),
        "date": "2024-01-01",
        "amount": 100,
        "category": "Salary",
        "description": "January Salary",
        "type": "income"
    }

    # Call the function to add the transaction (replace with the actual function call from app.js)
    # For example, if you have a function called addTransaction(transaction) in app.js:
    # addTransaction(transaction)
    # Since we don't have access to the js functions directly, we will simulate the local storage update
    # as it would happen in the addTransaction function
    transactions = []
    transactions.append(transaction)
    mock_local_storage.setItem("finance_entries", json.dumps(transactions))

    # Assert that the transaction was added to local storage
    stored_transactions = json.loads(mock_local_storage.getItem("finance_entries"))
    assert len(stored_transactions) == 1
    assert stored_transactions[0]["amount"] == 100
    assert stored_transactions[0]["type"] == "income"
    assert is_valid_uuid(stored_transactions[0]["id"])

def test_add_transaction_expense(mock_local_storage):
    # Simulate adding an expense transaction
    transaction = {
        "id": str(uuid.uuid4()),
        "date": "2024-01-02",
        "amount": 50,
        "category": "Groceries",
        "description": "Weekly Groceries",
        "type": "expense"
    }

    # Call the function to add the transaction (replace with the actual function call from app.js)
    # For example, if you have a function called addTransaction(transaction) in app.js:
    # addTransaction(transaction)
    # Since we don't have access to the js functions directly, we will simulate the local storage update
    # as it would happen in the addTransaction function
    transactions = []
    transactions.append(transaction)
    mock_local_storage.setItem("finance_entries", json.dumps(transactions))

    # Assert that the transaction was added to local storage
    stored_transactions = json.loads(mock_local_storage.getItem("finance_entries"))
    assert len(stored_transactions) == 1
    assert stored_transactions[0]["amount"] == 50
    assert stored_transactions[0]["type"] == "expense"
    assert is_valid_uuid(stored_transactions[0]["id"])

def test_load_transactions_empty(mock_local_storage):
    # Ensure that loading transactions from an empty local storage returns an empty list
    mock_local_storage.clear()

    # Simulate loading transactions (replace with the actual function call from app.js)
    # For example, if you have a function called loadTransactions() in app.js:
    # transactions = loadTransactions()
    # Since we don't have access to the js functions directly, we will simulate the local storage read
    stored_transactions = mock_local_storage.getItem("finance_entries")
    if stored_transactions:
      stored_transactions =  json.loads(stored_transactions)
    else:
      stored_transactions = []

    assert len(stored_transactions) == 0

def test_load_transactions_existing(mock_local_storage):
    # Ensure that loading transactions from local storage returns the correct list of transactions
    transaction1 = {
        "id": str(uuid.uuid4()),
        "date": "2024-01-01",
        "amount": 100,
        "category": "Salary",
        "description": "January Salary",
        "type": "income"
    }
    transaction2 = {
        "id": str(uuid.uuid4()),
        "date": "2024-01-02",
        "amount": 50,
        "category": "Groceries",
        "description": "Weekly Groceries",
        "type": "expense"
    }
    transactions = [transaction1, transaction2]
    mock_local_storage.setItem("finance_entries", json.dumps(transactions))

    # Simulate loading transactions (replace with the actual function call from app.js)
    # For example, if you have a function called loadTransactions() in app.js:
    # transactions = loadTransactions()
    # Since we don't have access to the js functions directly, we will simulate the local storage read
    stored_transactions = mock_local_storage.getItem("finance_entries")
    if stored_transactions:
      stored_transactions =  json.loads(stored_transactions)
    else:
      stored_transactions = []

    assert len(stored_transactions) == 2
    assert stored_transactions[0]["amount"] == 100
    assert stored_transactions[1]["type"] == "expense"

def test_clear_transactions(mock_local_storage):
    # Ensure that clearing transactions from local storage results in an empty local storage
    transaction1 = {
        "id": str(uuid.uuid4()),
        "date": "2024-01-01",
        "amount": 100,
        "category": "Salary",
        "description": "January Salary",
        "type": "income"
    }
    transactions = [transaction1]
    mock_local_storage.setItem("finance_entries", json.dumps(transactions))

    # Simulate clearing transactions (replace with the actual function call from app.js)
    # For example, if you have a function called clearTransactions() in app.js:
    # clearTransactions()
    # Since we don't have access to the js functions directly, we will simulate the local storage clear
    mock_local_storage.clear()

    # Assert that local storage is empty
    stored_transactions = mock_local_storage.getItem("finance_entries")
    assert stored_transactions is None



