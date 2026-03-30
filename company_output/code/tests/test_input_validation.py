import pytest
from app import validate_input  # Assuming validate_input is in app.js

def test_validate_input_valid():
    assert validate_input("2024-01-01", 100, "food", "groceries") == True

def test_validate_input_invalid_date():
    assert validate_input("2024/01/01", 100, "food", "groceries") == False

def test_validate_input_invalid_amount():
    assert validate_input("2024-01-01", "abc", "food", "groceries") == False

def test_validate_input_empty_category():
    assert validate_input("2024-01-01", 100, "", "groceries") == False

def test_validate_input_empty_description():
    assert validate_input("2024-01-01", 100, "food", "") == False

def test_validate_input_amount_is_zero():
    assert validate_input("2024-01-01", 0, "food", "groceries") == True  # Zero is valid

def test_validate_input_amount_is_negative():
    assert validate_input("2024-01-01", -100, "food", "groceries") == True # Negative is valid

def test_validate_input_category_is_too_long():
    assert validate_input("2024-01-01", 100, "This category is way too long and exceeds the limit", "groceries") == False

def test_validate_input_description_is_too_long():
    assert validate_input("2024-01-01", 100, "food", "This description is way too long and exceeds the limit") == False

