import React from 'react';
import { TouchableOpacity } from 'react-native';
import { createDrawerNavigator } from '@react-navigation/drawer';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '@react-navigation/native';
import CustomDrawer from '../components/CustomDrawer';
import ProjectsScreen from '../screens/ProjectsScreen';
import ChatScreen from '../screens/ChatScreen';
import OptionsScreen from '../screens/OptionsScreen';

const Drawer = createDrawerNavigator();
const Stack = createNativeStackNavigator();

function ProjectsStack() {
  const theme = useTheme();
  return (
    <Stack.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: theme.colors.card },
        headerTintColor: theme.colors.text,
        headerTitleStyle: { fontWeight: '600' },
        contentStyle: { backgroundColor: theme.colors.background },
      }}
    >
      <Stack.Screen
        name="ProjectsList"
        component={ProjectsScreen}
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="ProjectChat"
        component={ChatScreen}
        options={({ route }) => ({
          title: route.params?.projectName || 'Project Chat',
          animation: 'slide_from_right',
        })}
      />
    </Stack.Navigator>
  );
}

export default function AppNavigator({ user, onLogout, isDarkMode, onToggleDarkMode, onUpdateUser }) {
  const headerBg = isDarkMode ? '#16213e' : '#ffffff';
  const headerTint = isDarkMode ? '#eee' : '#1a1a2e';
  const drawerBg = isDarkMode ? '#16213e' : '#ffffff';
  const sceneBg = isDarkMode ? '#1a1a2e' : '#f0f0f5';

  return (
    <Drawer.Navigator
      drawerContent={(props) => <CustomDrawer {...props} user={user} onLogout={onLogout} />}
      screenOptions={({ navigation }) => ({
        headerStyle: {
          backgroundColor: headerBg,
          elevation: 0,
          shadowOpacity: 0,
        },
        headerTintColor: headerTint,
        headerTitleStyle: {
          fontWeight: '600',
        },
        drawerStyle: {
          width: 280,
          backgroundColor: drawerBg,
        },
        sceneStyle: {
          backgroundColor: sceneBg,
        },
        headerLeft: () => (
          <TouchableOpacity
            onPress={() => navigation.toggleDrawer()}
            style={{ marginLeft: 16, padding: 4 }}
          >
            <Ionicons name="menu" size={26} color={headerTint} />
          </TouchableOpacity>
        ),
      })}
    >
      <Drawer.Screen
        name="Projects"
        component={ProjectsStack}
        options={{ title: 'Projects' }}
      />
      <Drawer.Screen
        name="Chat"
        component={ChatScreen}
        options={{ title: 'Chat with CEO' }}
      />
      <Drawer.Screen
        name="Options"
        options={{ title: 'Options' }}
      >
        {() => (
          <OptionsScreen
            user={user}
            onLogout={onLogout}
            isDarkMode={isDarkMode}
            onToggleDarkMode={onToggleDarkMode}
            onUpdateUser={onUpdateUser}
          />
        )}
      </Drawer.Screen>
    </Drawer.Navigator>
  );
}
