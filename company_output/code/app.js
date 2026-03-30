/**
 * app.js - Main application logic for the Personal Finance Tracker.
 */

// Import localStorage handler
import localStorageHandler from './local_storage_handler.js';

// Function to generate a unique ID (UUID v4)
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

// Initialize transactions array (in-memory or from localStorage)
let transactions = JSON.parse(localStorageHandler.getItem('transactions') || '[]') || [];

// Function to get the running balance
function getRunningBalance() {
  let balance = 0;
  transactions.forEach(transaction => {
    balance += transaction.amount;
  });
  return balance;
}

// Function to render the transaction list
function renderTransactionList() {
  const transactionList = document.getElementById('transactionList');
  transactionList.innerHTML = ''; // Clear existing list

  transactions.forEach(transaction => {
    const listItem = document.createElement('li');
    listItem.innerHTML = `
      ${transaction.date}: ${transaction.description} (${transaction.category}) - $${(transaction.amount / 100).toFixed(2)}
    `;
    transactionList.appendChild(listItem);
  });
}

// Function to update the balance display
function updateBalanceDisplay() {
  const balanceDisplay = document.getElementById('balance');
  balanceDisplay.textContent = `$${(getRunningBalance() / 100).toFixed(2)}`;
}

// Function to display error alerts
function displayErrorAlert(message) {
  // Standardized error alert component (replace with actual implementation)
  alert(message);
}

// Input validation functions
function validateDate(date) {
  const dateRegex = /^\d{4}-\d{2}-\d{2}$/;
  return dateRegex.test(date);
}

function validateAmount(amount) {
  return !isNaN(parseFloat(amount)) && isFinite(amount);
}

function validateCategory(category) {
  return category.trim() !== '';
}

function validateDescription(description) {
  return description.trim() !== '';
}

// Function to handle form submission
function handleFormSubmit(event) {
  event.preventDefault();

  // Get form values
  const date = document.getElementById('date').value;
  const amountInput = document.getElementById('amount').value;
  const category = document.getElementById('category').value;
  const description = document.getElementById('description').value;

  // Validate form values
  let isValid = true;
  let errorMessage = '';

  if (!validateDate(date)) {
    isValid = false;
    errorMessage += 'Invalid date format. Please use YYYY-MM-DD.\n';
  }

  if (!validateAmount(amountInput)) {
    isValid = false;
    errorMessage += 'Invalid amount. Please enter a number.\n';
  }

  if (!validateCategory(category)) {
    isValid = false;
    errorMessage += 'Category cannot be empty.\n';
  }

  if (!validateDescription(description)) {
    isValid = false;
    errorMessage += 'Description cannot be empty.\n';
  }

  if (!isValid) {
    displayErrorAlert(errorMessage);
    return;
  }

  // Convert amount to cents (integer)
  const amount = parseInt(parseFloat(amountInput) * 100);

  // Create transaction object
  const transaction = {
    id: generateUUID(),
    date: date,
    amount: amount,
    category: category,
    description: description,
  };

  // Add transaction to array
  transactions.push(transaction);

  // Save transactions to localStorage
  localStorageHandler.setItem('transactions', JSON.stringify(transactions));

  // Update the transaction list and balance display
  renderTransactionList();
  updateBalanceDisplay();

  // Reset the form
  document.getElementById('transactionForm').reset();
}

// Event listener for form submission
document.getElementById('transactionForm').addEventListener('submit', handleFormSubmit);

// Initial render of transaction list and balance
renderTransactionList();
updateBalanceDisplay();
