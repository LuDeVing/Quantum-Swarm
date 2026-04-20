import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { DrawerContentScrollView } from '@react-navigation/drawer';
import { Ionicons } from '@expo/vector-icons';
import { useTheme } from '@react-navigation/native';

export default function CustomDrawer(props) {
  const { state, navigation, user, onLogout } = props;
  const currentRoute = state.routes[state.index].name;
  const theme = useTheme();
  const dark = theme.dark;

  const bg = theme.colors.card;
  const headerBorder = theme.colors.border;
  const textColor = theme.colors.text;
  const muted = dark ? '#888' : '#999';
  const logoBg = theme.colors.background;
  const userInfoBg = theme.colors.background;

  const menuItems = [
    { name: 'Projects', icon: 'folder-open', label: 'Projects' },
    { name: 'Chat', icon: 'chatbubbles', label: 'Chat with CEO' },
  ];

  return (
    <View style={[styles.container, { backgroundColor: bg }]}>
      {/* Header: Logo & Company Name */}
      <View style={[styles.header, { borderBottomColor: headerBorder }]}>
        <View style={[styles.logoCircle, { backgroundColor: logoBg }]}>
          <Text style={styles.logoText}>M</Text>
        </View>
        <Text style={[styles.appName, { color: textColor }]}>MyApp</Text>
        <Text style={[styles.companyTag, { color: muted }]}>Your Company</Text>
      </View>

      {/* Menu Items */}
      <DrawerContentScrollView {...props} contentContainerStyle={styles.menuContainer}>
        {menuItems.map((item) => {
          const isActive = currentRoute === item.name;
          return (
            <TouchableOpacity
              key={item.name}
              style={[styles.menuItem, isActive && styles.menuItemActive]}
              onPress={() => navigation.navigate(item.name)}
            >
              <Ionicons
                name={isActive ? item.icon : `${item.icon}-outline`}
                size={22}
                color={isActive ? '#e94560' : muted}
              />
              <Text style={[styles.menuLabel, { color: muted }, isActive && styles.menuLabelActive]}>
                {item.label}
              </Text>
              {isActive && <View style={styles.activeIndicator} />}
            </TouchableOpacity>
          );
        })}
      </DrawerContentScrollView>

      {/* Bottom: Options */}
      <View style={styles.bottomSection}>
        <View style={[styles.divider, { backgroundColor: headerBorder }]} />

        <TouchableOpacity
          style={[styles.menuItem, currentRoute === 'Options' && styles.menuItemActive]}
          onPress={() => navigation.navigate('Options')}
        >
          <Ionicons
            name={currentRoute === 'Options' ? 'settings' : 'settings-outline'}
            size={22}
            color={currentRoute === 'Options' ? '#e94560' : muted}
          />
          <Text
            style={[
              styles.menuLabel,
              { color: muted },
              currentRoute === 'Options' && styles.menuLabelActive,
            ]}
          >
            Options
          </Text>
        </TouchableOpacity>

        {/* User info at bottom */}
        <View style={[styles.userInfo, { backgroundColor: userInfoBg }]}>
          <View style={styles.userAvatar}>
            <Text style={styles.userAvatarText}>
              {user?.name?.charAt(0)?.toUpperCase() || 'U'}
            </Text>
          </View>
          <View style={styles.userDetails}>
            <Text style={[styles.userName, { color: textColor }]} numberOfLines={1}>{user?.name || 'User'}</Text>
            <Text style={[styles.userEmail, { color: muted }]} numberOfLines={1}>{user?.email || ''}</Text>
          </View>
          <TouchableOpacity onPress={onLogout} style={styles.logoutIcon}>
            <Ionicons name="log-out-outline" size={20} color="#e94560" />
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    paddingTop: 60,
    paddingBottom: 24,
    paddingHorizontal: 20,
    alignItems: 'center',
    borderBottomWidth: 1,
  },
  logoCircle: {
    width: 64,
    height: 64,
    borderRadius: 32,
    borderWidth: 2,
    borderColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  logoText: {
    fontSize: 28,
    fontWeight: 'bold',
    color: '#e94560',
  },
  appName: {
    fontSize: 22,
    fontWeight: 'bold',
    letterSpacing: 2,
  },
  companyTag: {
    fontSize: 12,
    marginTop: 4,
    letterSpacing: 1,
  },
  menuContainer: {
    paddingTop: 16,
    paddingHorizontal: 12,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 12,
    marginBottom: 4,
  },
  menuItemActive: {
    backgroundColor: '#e9456015',
  },
  menuLabel: {
    marginLeft: 14,
    fontSize: 16,
    fontWeight: '500',
  },
  menuLabelActive: {
    color: '#e94560',
    fontWeight: '600',
  },
  activeIndicator: {
    position: 'absolute',
    left: 0,
    top: 10,
    bottom: 10,
    width: 3,
    borderRadius: 2,
    backgroundColor: '#e94560',
  },
  bottomSection: {
    paddingHorizontal: 12,
    paddingBottom: 30,
  },
  divider: {
    height: 1,
    marginHorizontal: 4,
    marginBottom: 8,
  },
  userInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    marginTop: 8,
    borderRadius: 12,
  },
  userAvatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
  },
  userAvatarText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 15,
  },
  userDetails: {
    flex: 1,
    marginLeft: 10,
  },
  userName: {
    fontSize: 14,
    fontWeight: '600',
  },
  userEmail: {
    fontSize: 12,
    marginTop: 2,
  },
  logoutIcon: {
    padding: 6,
  },
});
