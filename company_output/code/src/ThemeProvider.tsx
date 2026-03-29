import React, { createContext, useContext, ReactNode } from 'react';
import './styles/theme.css';
import tokens from './tokens.json';

const ThemeContext = createContext(tokens);

export const ThemeProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  return (
    <ThemeContext.Provider value={tokens}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);
