import React from 'react';
import { createDrawerNavigator } from '@react-navigation/drawer';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import CustomDrawer from '../components/CustomDrawer';
import AppHeader from '../components/AppHeader';
import ProjectsScreen from '../screens/ProjectsScreen';
import ChatScreen from '../screens/ChatScreen';
import AgentsScreen from '../screens/AgentsScreen';
import ArtifactsScreen from '../screens/ArtifactsScreen';
import LogsScreen from '../screens/LogsScreen';
import OptionsScreen from '../screens/OptionsScreen';
import { colors } from '../theme';

const Drawer = createDrawerNavigator();
const Stack = createNativeStackNavigator();

function ProjectsStack() {
  return (
    <Stack.Navigator screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.bg } }}>
      <Stack.Screen name="Portfolio" component={ProjectsScreen} />
      <Stack.Screen name="ProjectWorkspace" component={ChatScreen} />
    </Stack.Navigator>
  );
}

export default function AppNavigator({ user, onLogout, isDarkMode, onToggleDarkMode, onUpdateUser }) {
  return (
    <Drawer.Navigator
      drawerContent={(props) => <CustomDrawer {...props} user={user} onLogout={onLogout} />}
      screenOptions={({ navigation, route }) => ({
        header: () => <AppHeader navigation={navigation} route={route} user={user} />,
        drawerStyle: { width: 270, backgroundColor: colors.surface },
        sceneStyle: { backgroundColor: colors.bg },
        overlayColor: 'rgba(3,8,13,0.72)',
      })}
    >
      <Drawer.Screen name="Projects" component={ProjectsStack} />
      <Drawer.Screen name="Agents" component={AgentsScreen} />
      <Drawer.Screen name="Artifacts" component={ArtifactsScreen} />
      <Drawer.Screen name="Logs" component={LogsScreen} />
      <Drawer.Screen name="Options">
        {() => <OptionsScreen user={user} onLogout={onLogout} isDarkMode={isDarkMode} onToggleDarkMode={onToggleDarkMode} onUpdateUser={onUpdateUser} />}
      </Drawer.Screen>
    </Drawer.Navigator>
  );
}
