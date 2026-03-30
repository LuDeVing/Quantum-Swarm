import pytest
import json
from unittest.mock import patch, mock_open
from local_storage import saveTransactions, loadTransactions, createTransaction, readTransactions

@pytest.fixture
def sample_transactions():
    return [
        {"id": "1", "date": "2024-01-01", "amount": 1000, "category": "salary", "description": "paycheck"},
        {"id": "2", "date": "2024-01-02", "amount": -200, "category": "groceries", "description": "food"},
    ]

def test_create_transaction():
    transaction = createTransaction("2024-01-03", 50, "coffee", "morning coffee")
    assert transaction["date"] == "2024-01-03"
    assert transaction["amount"] == 50
    assert transaction["category"] == "coffee"
    assert transaction["description"] == "morning coffee"
    assert "id" in transaction # Verify id exists


@patch('local_storage.localStorage')
def test_saveTransactions_success(mock_local_storage, sample_transactions):
    saveTransactions(sample_transactions)
    mock_local_storage.setItem.assert_called_once_with('transactions', json.dumps(sample_transactions))


@patch('local_storage.localStorage')
def test_loadTransactions_success(mock_local_storage, sample_transactions):
    mock_local_storage.getItem.return_value = json.dumps(sample_transactions)
    transactions = loadTransactions()
    assert transactions == sample_transactions


@patch('local_storage.localStorage')
def test_loadTransactions_empty(mock_local_storage):
    mock_local_storage.getItem.return_value = None
    transactions = loadTransactions()
    assert transactions == []


@patch('local_storage.localStorage')
def test_readTransactions_success(mock_local_storage, sample_transactions):
    mock_local_storage.getItem.return_value = json.dumps(sample_transactions)
    transactions = readTransactions()
    assert transactions == sample_transactions

# Mock encryption/decryption for testing purposes (until Dev 1 implements it)
@patch('local_storage.encrypt', lambda x: x)
@patch('local_storage.decrypt', lambda x: x)


@patch('local_storage.localStorage')
def test_saveTransactions_encrypted(mock_local_storage, sample_transactions):
    # Mock the encrypt function to return the same value
    with patch('local_storage.encrypt', return_value=json.dumps(sample_transactions)) as mock_encrypt:
        saveTransactions(sample_transactions)
        mock_encrypt.assert_called_once_with(json.dumps(sample_transactions))
        mock_local_storage.setItem.assert_called_once_with('transactions', json.dumps(sample_transactions))


@patch('local_storage.localStorage')
def test_loadTransactions_decrypted(mock_local_storage, sample_transactions):
    # Mock the decrypt function to return the same value
    with patch('local_storage.decrypt', return_value=json.dumps(sample_transactions)) as mock_decrypt:
        mock_local_storage.getItem.return_value = json.dumps(sample_transactions)
        transactions = loadTransactions()
        mock_decrypt.assert_called_once_with(json.dumps(sample_transactions))
        assert transactions == sample_transactions