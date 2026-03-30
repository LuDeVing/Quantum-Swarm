
import pytest
import json
from unittest.mock import patch

# Assuming local_storage.js is transpiled and available as a module
# If not, adjust the import based on your build process
# For example:
# from your_dist_folder import local_storage
from local_storage import saveTransactions, loadTransactions, createTransaction, readTransactions

TRANSACTION_KEY = "finance_entries"

@pytest.fixture
def sample_transaction():
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "date": "2024-01-01T00:00:00.000Z",
        "amount": 100,
        "category": "salary",
        "description": "paycheck",
        "type": "income"
    }

@pytest.fixture
def sample_transactions():
    return [
        {
            "id": "123e4567-e89b-12d3-a456-426614174001",
            "date": "2024-01-02T00:00:00.000Z",
            "amount": 50,
            "category": "food",
            "description": "groceries",
            "type": "expense"
        },
        {
            "id": "123e4567-e89b-12d3-a456-426614174002",
            "date": "2024-01-03T00:00:00.000Z",
            "amount": 25,
            "category": "entertainment",
            "description": "movies",
            "type": "expense"
        }
    ]

def test_saveTransactions_success(sample_transactions):
    with patch('local_storage.localStorage') as mock_local_storage:
        saveTransactions(sample_transactions)
        mock_local_storage.setItem.assert_called_once_with('transactions', json.dumps(sample_transactions))

def test_saveTransactions_error(sample_transactions):
    with patch('local_storage.localStorage') as mock_local_storage:
        mock_local_storage.setItem.side_effect = Exception("Simulated error")
        with pytest.raises(Exception, match="Simulated error"):
            saveTransactions(sample_transactions)

def test_loadTransactions_success(sample_transactions):
    with patch('local_storage.localStorage') as mock_local_storage:
        mock_local_storage.getItem.return_value = json.dumps(sample_transactions)
        transactions = loadTransactions()
        assert transactions == sample_transactions

def test_loadTransactions_empty():
    with patch('local_storage.localStorage') as mock_local_storage:
        mock_local_storage.getItem.return_value = None
        transactions = loadTransactions()
        assert transactions == []

def test_loadTransactions_error():
    with patch('local_storage.localStorage') as mock_local_storage:
        mock_local_storage.getItem.side_effect = Exception("Simulated error")
        transactions = loadTransactions()
        assert transactions == []

def test_createTransaction_success(sample_transaction):
    with patch('local_storage.loadTransactions') as mock_loadTransactions, \
            patch('local_storage.saveTransactions') as mock_saveTransactions:
        mock_loadTransactions.return_value = []
        createTransaction(sample_transaction)
        mock_loadTransactions.assert_called_once()
        mock_saveTransactions.assert_called_once_with([sample_transaction])

def test_createTransaction_error(sample_transaction):
    with patch('local_storage.loadTransactions') as mock_loadTransactions, \
            patch('local_storage.saveTransactions') as mock_saveTransactions:
        mock_loadTransactions.return_value = []
        mock_saveTransactions.side_effect = Exception("Simulated error")
        with pytest.raises(Exception, match="Simulated error"):
            createTransaction(sample_transaction)

def test_readTransactions_success(sample_transactions):
    with patch('local_storage.loadTransactions') as mock_loadTransactions:
        mock_loadTransactions.return_value = sample_transactions
        transactions = readTransactions()
        assert transactions == sample_transactions

def test_readTransactions_error():
    with patch('local_storage.loadTransactions') as mock_loadTransactions:
        mock_loadTransactions.side_effect = Exception("Simulated error")
        # readTransactions should not raise exception, but return []
        transactions = readTransactions()
        assert transactions == []
