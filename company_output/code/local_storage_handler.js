/**
 * Handles localStorage operations with error handling and user-friendly messages.
 */

const localStorageHandler = {
  /**
   * Sets an item in localStorage.
   * @param {string} key - The key to store the item under.
   * @param {string} value - The value to store.
   * @returns {boolean} - True if the operation was successful, false otherwise.
   */
  setItem: (key, value) => {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (error) {
      console.error(`Failed to set item in localStorage: ${error}`);
      // Display user-friendly message (replace with your actual UI display method)
      alert("Failed to save data. Please try again later.");
      return false;
    }
  },

  /**
   * Gets an item from localStorage.
   * @param {string} key - The key of the item to retrieve.
   * @returns {string | null} - The item's value, or null if the item doesn't exist or an error occurred.
   */
  getItem: (key) => {
    try {
      const value = localStorage.getItem(key);
      return value;
    } catch (error) {
      console.error(`Failed to get item from localStorage: ${error}`);
      // Display user-friendly message (replace with your actual UI display method)
      alert("Failed to retrieve data. Please try again later.");
      return null;
    }
  },

  /**
   * Removes an item from localStorage.
   * @param {string} key - The key of the item to remove.
   * @returns {boolean} - True if the operation was successful, false otherwise.
   */
  removeItem: (key) => {
    try {
      localStorage.removeItem(key);
      return true;
    } catch (error) {
      console.error(`Failed to remove item from localStorage: ${error}`);
      // Display user-friendly message (replace with your actual UI display method)
      alert("Failed to delete data. Please try again later.");
      return false;
    }
  },

  /**
   * Clears all items from localStorage.
   * @returns {boolean} - True if the operation was successful, false otherwise.
   */
  clear: () => {
    try {
      localStorage.clear();
      return true;
    } catch (error) {
      console.error(`Failed to clear localStorage: ${error}`);
      // Display user-friendly message (replace with your actual UI display method)
      alert("Failed to clear data. Please try again later.");
      return false;
    }
  },
};

export default localStorageHandler;