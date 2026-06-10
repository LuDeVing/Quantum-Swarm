import React, { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer, DarkTheme as NavDarkTheme } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import 'react-native-gesture-handler';

import LoadingScreen from './src/screens/LoadingScreen';
import AuthNavigator from './src/navigation/AuthNavigator';
import AppNavigator from './src/navigation/AppNavigator';
import { getMe, logout } from './src/services/api';
import { colors } from './src/theme';

const Theme = {
  ...NavDarkTheme,
  dark: true,
  colors: {
    ...NavDarkTheme.colors,
    primary: colors.primary,
    background: colors.bg,
    card: colors.surface,
    text: colors.text,
    border: colors.border,
    notification: colors.danger,
  },
};

export default function App() {
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState(null);
  const [isDarkMode, setIsDarkMode] = useState(true);

  useEffect(() => { checkLogin(); }, []);

  const checkLogin = async () => {
    try {
      const token = await AsyncStorage.getItem('authToken');
      if (token) {
        const data = await getMe();
        setUser(data.user);
        return;
      }
      const local = JSON.parse(await AsyncStorage.getItem('currentUser') || 'null');
      if (local?.id === 'guest') setUser(local);
    } catch (e) {
      await AsyncStorage.multiRemove(['authToken', 'currentUser']);
      setUser(null);
    }
  };

  const handleLogin = async (nextUser) => {
    setUser(nextUser);
    await AsyncStorage.setItem('currentUser', JSON.stringify(nextUser));
  };

  const handleLogout = async () => {
    await logout();
    setUser(null);
  };

  const updateUser = async (nextUser) => {
    setUser(nextUser);
    await AsyncStorage.setItem('currentUser', JSON.stringify(nextUser));
  };

  if (isLoading) return <><StatusBar style="light" /><LoadingScreen onFinish={() => setIsLoading(false)} /></>;

  return (
    <NavigationContainer theme={Theme}>
      <StatusBar style="light" />
      {user ? (
        <AppNavigator user={user} onLogout={handleLogout} isDarkMode={isDarkMode} onToggleDarkMode={setIsDarkMode} onUpdateUser={updateUser} />
      ) : <AuthNavigator onLogin={handleLogin} />}
    </NavigationContainer>
  );
}
