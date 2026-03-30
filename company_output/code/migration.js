/**
 * migration.js - Handles data migration for the Personal Finance Tracker.
 */

/**
 * Applies data migrations to localStorage.
 * @param {string} localStorageKey - The key under which the data is stored in localStorage.
 * @param {function[]} migrations - An array of migration functions to apply.
 */
const applyMigrations = (localStorageKey, migrations) => {
  const storedData = localStorage.getItem(localStorageKey);

  if (storedData) {
    let data = JSON.parse(storedData);
    let currentVersion = data.version || 0; // Default to version 0 if no version is present.

    for (let i = currentVersion; i < migrations.length; i++) {
      console.log(`Applying migration version ${i + 1}`);
      data = migrations[i](data);
      data.version = i + 1;
    }

    localStorage.setItem(localStorageKey, JSON.stringify(data));
    console.log("Migrations applied successfully.");
  } else {
    console.log("No data found in localStorage. Skipping migrations.");
  }
};

/**
 * Example migration: Adds a new field to the data.
 * @param {object} data - The data to migrate.
 * @returns {object} - The migrated data.
 */
const migration1 = (data) => {
  // Example: Add a 'type' field to each transaction.
  if (data.transactions && Array.isArray(data.transactions)) {
    data.transactions = data.transactions.map(transaction => ({
      ...transaction,
      type: transaction.amount >= 0 ? 'income' : 'expense', // Example logic
    }));
  }
  return data;
};

/**
 * Example migration: Converts amount to integer representing cents.
 * @param {object} data - The data to migrate.
 * @returns {object} - The migrated data.
 */
const migration2 = (data) => {
  if (data.transactions && Array.isArray(data.transactions)) {
    data.transactions = data.transactions.map(transaction => ({
      ...transaction,
      amount: Math.round(transaction.amount * 100),
    }));
  }
  return data;
};

/**
 * Example migration: Adds UUID to each transaction.
 * @param {object} data - The data to migrate.
 * @returns {object} - The migrated data.
 */
const migration3 = (data) => {
    if (data.transactions && Array.isArray(data.transactions)) {
        data.transactions = data.transactions.map(transaction => ({
            ...transaction,
            id: crypto.randomUUID(), // Generate UUID
        }));
    }
    return data;
};

/**
 * Example migration: Converts date to ISO 8601.
 * @param {object} data - The data to migrate.
 * @returns {object} - The migrated data.
 */
const migration4 = (data) => {
    if (data.transactions && Array.isArray(data.transactions)) {
        data.transactions = data.transactions.map(transaction => ({
            ...transaction,
            date: new Date(transaction.date).toISOString().slice(0, 10), // Convert to ISO 8601
        }));
    }
    return data;
};


// Add more migrations as needed

const migrations = [migration1, migration2, migration3, migration4];

// Export the applyMigrations function and the migrations array
export { applyMigrations, migrations };