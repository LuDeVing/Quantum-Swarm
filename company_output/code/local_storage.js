import CryptoJS from 'crypto-js';

const ENCRYPTION_KEY = process.env.ENCRYPTION_KEY || 'YOUR_DEFAULT_KEY'; // Replace with a secure method for key management

/**
 * Saves transaction data to local storage with AES encryption.
 * @param {Transaction[]} transactions - Array of transaction objects to save.
 */
export function saveTransactions(transactions) {
  try {
    const ciphertext = CryptoJS.AES.encrypt(JSON.stringify(transactions), ENCRYPTION_KEY).toString();
    localStorage.setItem('transactions', ciphertext);
  } catch (error) {
    console.error('Error saving transactions to local storage:', error);
    // Consider a more user-friendly error message or UI update here
    throw new Error('Failed to save transactions. Please try again.');
  }
}

/**
 * Loads transaction data from local storage and decrypts it.
 * @returns {Transaction[]} - Array of transaction objects loaded from local storage, or an empty array if none exist.
 */
export function loadTransactions() {
  try {
    const ciphertext = localStorage.getItem('transactions');
    if (!ciphertext) {
      return [];
    }
    const bytes = CryptoJS.AES.decrypt(ciphertext, ENCRYPTION_KEY);
    const decryptedData = bytes.toString(CryptoJS.enc.Utf8);
    return JSON.parse(decryptedData);
  } catch (error) {
    console.error('Error loading transactions from local storage:', error);
    // Consider a more user-friendly error message or UI update here
    return []; // Return an empty array to avoid breaking the app
  }
}

/**
 * Creates a transaction object and saves it to local storage.
 * @param {Transaction} transaction - The transaction object to create and save.
 */
export function createTransaction(transaction) {
  try {
    const transactions = loadTransactions();
    transactions.push(transaction);
    saveTransactions(transactions);
  } catch (error) {
    console.error('Error creating and saving transaction:', error);
    // Consider a more user-friendly error message or UI update here
    throw new Error('Failed to create transaction. Please try again.');
  }
}

/**
 * Reads all transactions from local storage.
 * @returns {Transaction[]} - Array of transaction objects loaded from local storage.
 */
export function readTransactions() {
  try {
    return loadTransactions();
  } catch (error) {
    console.error('Error reading transactions:', error);
    return [];
  }
}
