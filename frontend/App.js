import React, { useState, useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DarkTheme as NavDarkTheme, DefaultTheme as NavLightTheme } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import 'react-native-gesture-handler';

import LoadingScreen from './src/screens/LoadingScreen';
import AuthNavigator from './src/navigation/AuthNavigator';
import AppNavigator from './src/navigation/AppNavigator';
import { getMe, logout } from './src/services/api';

const DarkTheme = {
  ...NavDarkTheme,
  dark: true,
  colors: {
    ...NavDarkTheme.colors,
    primary: '#e94560',
    background: '#1a1a2e',
    card: '#16213e',
    text: '#eee',
    border: '#0f3460',
    notification: '#e94560',
  },
};

const LightTheme = {
  ...NavLightTheme,
  dark: false,
  colors: {
    ...NavLightTheme.colors,
    primary: '#e94560',
    background: '#f0f0f5',
    card: '#ffffff',
    text: '#1a1a2e',
    border: '#ddd',
    notification: '#e94560',
  },
};

export default function App() {
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState(null);
  const [isDarkMode, setIsDarkMode] = useState(true);

  useEffect(() => {
    checkLogin();
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const settings = await AsyncStorage.getItem('appSettings');
      if (settings) {
        const parsed = JSON.parse(settings);
        if (parsed.darkMode !== undefined) setIsDarkMode(parsed.darkMode);
      }
    } catch (e) {}
  };

  const toggleDarkMode = async (value) => {
    setIsDarkMode(value);
    try {
      const settings = await AsyncStorage.getItem('appSettings');
      const parsed = settings ? JSON.parse(settings) : {};
      parsed.darkMode = value;
      await AsyncStorage.setItem('appSettings', JSON.stringify(parsed));
    } catch (e) {}
  };

  const updateUser = async (updatedUser) => {
    setUser(updatedUser);
    await AsyncStorage.setItem('currentUser', JSON.stringify(updatedUser));
  };

  const checkLogin = async () => {
    try {
      const token = await AsyncStorage.getItem('authToken');
      if (token) {
        try {
          const data = await getMe();
          setUser(data.user);
          return;
        } catch (e) {
          // Backend unreachable — fall back to local storage
        }
      }
      // Fallback: check local user data
      const userJSON = await AsyncStorage.getItem('currentUser');
      if (userJSON) {
        setUser(JSON.parse(userJSON));
      }
    } catch (e) {
      // ignore
    }
  };

  const handleLogout = async () => {
    await logout();
    setUser(null);
  };

  if (isLoading) {
    return (
      <>
        <StatusBar style="light" />
        <LoadingScreen onFinish={() => setIsLoading(false)} />
      </>
    );
  }

  return (
    <NavigationContainer theme={isDarkMode ? DarkTheme : LightTheme}>
      <StatusBar style={isDarkMode ? 'light' : 'dark'} />
      {user ? (
        <AppNavigator
          user={user}
          onLogout={handleLogout}
          isDarkMode={isDarkMode}
          onToggleDarkMode={toggleDarkMode}
          onUpdateUser={updateUser}
        />
      ) : (
        <AuthNavigator onLogin={(u) => setUser(u)} />
      )}
    </NavigationContainer>
  );
}
