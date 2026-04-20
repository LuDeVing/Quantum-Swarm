import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Switch,
  ScrollView,
  Alert,
  Modal,
  TextInput,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { logout } from '../services/api';
import { useTheme } from '@react-navigation/native';

export default function OptionsScreen({ user, onLogout, isDarkMode, onToggleDarkMode, onUpdateUser }) {
  const theme = useTheme();
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [editProfileVisible, setEditProfileVisible] = useState(false);
  const [changePasswordVisible, setChangePasswordVisible] = useState(false);
  const [editName, setEditName] = useState(user?.name || '');
  const [editEmail, setEditEmail] = useState(user?.email || '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmNewPassword, setConfirmNewPassword] = useState('');

  useEffect(() => {
    loadNotificationSetting();
  }, []);

  const loadNotificationSetting = async () => {
    try {
      const settings = await AsyncStorage.getItem('appSettings');
      if (settings) {
        const parsed = JSON.parse(settings);
        if (parsed.notifications !== undefined) setNotificationsEnabled(parsed.notifications);
      }
    } catch (e) {}
  };

  const toggleNotifications = async (value) => {
    setNotificationsEnabled(value);
    try {
      const settings = await AsyncStorage.getItem('appSettings');
      const parsed = settings ? JSON.parse(settings) : {};
      parsed.notifications = value;
      await AsyncStorage.setItem('appSettings', JSON.stringify(parsed));
    } catch (e) {}
  };

  const handleSaveProfile = () => {
    if (!editName.trim()) {
      Alert.alert('Error', 'Name cannot be empty');
      return;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(editEmail)) {
      Alert.alert('Error', 'Please enter a valid email');
      return;
    }
    const updatedUser = { ...user, name: editName.trim(), email: editEmail.trim() };
    onUpdateUser(updatedUser);
    setEditProfileVisible(false);
    Alert.alert('Success', 'Profile updated');
  };

  const handleChangePassword = () => {
    if (!currentPassword || !newPassword || !confirmNewPassword) {
      Alert.alert('Error', 'Please fill in all fields');
      return;
    }
    if (newPassword.length < 6) {
      Alert.alert('Error', 'New password must be at least 6 characters');
      return;
    }
    if (newPassword !== confirmNewPassword) {
      Alert.alert('Error', 'Passwords do not match');
      return;
    }
    // Would call API here when backend is connected
    setChangePasswordVisible(false);
    setCurrentPassword('');
    setNewPassword('');
    setConfirmNewPassword('');
    Alert.alert('Success', 'Password changed');
  };

  const handleLogout = () => {
    Alert.alert('Log Out', 'Are you sure you want to log out?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Log Out',
        style: 'destructive',
        onPress: async () => {
          await logout();
          onLogout();
        },
      },
    ]);
  };

  const handleClearData = () => {
    Alert.alert(
      'Clear All Data',
      'This will delete all accounts and data. This action cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear',
          style: 'destructive',
          onPress: async () => {
            await AsyncStorage.clear();
            onLogout();
          },
        },
      ]
    );
  };

  // Dynamic colors based on theme
  const bg = theme.colors.background;
  const card = theme.colors.card;
  const text = theme.colors.text;
  const border = theme.colors.border;
  const muted = isDarkMode ? '#888' : '#999';
  const inputBg = isDarkMode ? '#16213e' : '#f5f5f5';
  const inputText = isDarkMode ? '#eee' : '#1a1a2e';

  const SettingRow = ({ icon, label, right, onPress, danger }) => (
    <TouchableOpacity
      style={[styles.settingRow, { backgroundColor: card, borderColor: border }]}
      onPress={onPress}
      disabled={!onPress && !right}
    >
      <View style={styles.settingLeft}>
        <Ionicons name={icon} size={22} color={danger ? '#e94560' : '#e94560'} style={styles.settingIcon} />
        <Text style={[styles.settingLabel, { color: danger ? '#e94560' : text }]}>{label}</Text>
      </View>
      {right || <Ionicons name="chevron-forward" size={20} color={muted} />}
    </TouchableOpacity>
  );

  return (
    <ScrollView style={[styles.container, { backgroundColor: bg }]}>
      {/* Profile section */}
      <View style={[styles.profileSection, { borderBottomColor: border }]}>
        <View style={styles.profileAvatar}>
          <Text style={styles.profileAvatarText}>
            {user?.name?.charAt(0)?.toUpperCase() || 'U'}
          </Text>
        </View>
        <Text style={[styles.profileName, { color: text }]}>{user?.name || 'User'}</Text>
        <Text style={[styles.profileEmail, { color: muted }]}>{user?.email || 'user@email.com'}</Text>
      </View>

      {/* Preferences */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: muted }]}>Preferences</Text>
        <SettingRow
          icon="notifications-outline"
          label="Notifications"
          right={
            <Switch
              value={notificationsEnabled}
              onValueChange={toggleNotifications}
              trackColor={{ false: isDarkMode ? '#333' : '#ccc', true: '#e9456066' }}
              thumbColor={notificationsEnabled ? '#e94560' : muted}
            />
          }
        />
        <SettingRow
          icon={isDarkMode ? 'moon' : 'sunny'}
          label={isDarkMode ? 'Dark Mode' : 'Light Mode'}
          right={
            <Switch
              value={isDarkMode}
              onValueChange={onToggleDarkMode}
              trackColor={{ false: isDarkMode ? '#333' : '#ccc', true: '#e9456066' }}
              thumbColor={isDarkMode ? '#e94560' : '#ffc107'}
            />
          }
        />
      </View>

      {/* General */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: muted }]}>General</Text>
        <SettingRow
          icon="person-outline"
          label="Edit Profile"
          onPress={() => {
            setEditName(user?.name || '');
            setEditEmail(user?.email || '');
            setEditProfileVisible(true);
          }}
        />
        <SettingRow
          icon="lock-closed-outline"
          label="Change Password"
          onPress={() => {
            setCurrentPassword('');
            setNewPassword('');
            setConfirmNewPassword('');
            setChangePasswordVisible(true);
          }}
        />
        <SettingRow
          icon="help-circle-outline"
          label="Help & Support"
          onPress={() => Alert.alert('Support', 'Contact us at support@myapp.com')}
        />
        <SettingRow
          icon="information-circle-outline"
          label="About"
          onPress={() => Alert.alert('MyApp', 'Version 1.0.0\n© 2026 MyApp Inc.')}
        />
      </View>

      {/* Account */}
      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: muted }]}>Account</Text>
        <SettingRow
          icon="trash-outline"
          label="Clear All Data"
          onPress={handleClearData}
          danger
        />
      </View>

      <TouchableOpacity style={[styles.logoutButton, { borderColor: '#e94560' }]} onPress={handleLogout}>
        <Ionicons name="log-out-outline" size={22} color="#e94560" />
        <Text style={styles.logoutText}>Log Out</Text>
      </TouchableOpacity>

      <View style={styles.bottomPadding} />

      {/* ---- Edit Profile Modal ---- */}
      <Modal visible={editProfileVisible} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { backgroundColor: card, borderColor: border }]}>
            <Text style={[styles.modalTitle, { color: text }]}>Edit Profile</Text>

            <Text style={[styles.modalLabel, { color: muted }]}>Name</Text>
            <TextInput
              style={[styles.modalInput, { backgroundColor: inputBg, color: inputText, borderColor: border }]}
              value={editName}
              onChangeText={setEditName}
              placeholder="Your name"
              placeholderTextColor={muted}
              autoFocus
            />

            <Text style={[styles.modalLabel, { color: muted }]}>Email</Text>
            <TextInput
              style={[styles.modalInput, { backgroundColor: inputBg, color: inputText, borderColor: border }]}
              value={editEmail}
              onChangeText={setEditEmail}
              placeholder="Your email"
              placeholderTextColor={muted}
              keyboardType="email-address"
              autoCapitalize="none"
            />

            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={[styles.modalButton, { backgroundColor: isDarkMode ? '#1a1a2e' : '#eee' }]}
                onPress={() => setEditProfileVisible(false)}
              >
                <Text style={[styles.cancelButtonText, { color: muted }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.modalButton, styles.saveButton]} onPress={handleSaveProfile}>
                <Text style={styles.saveButtonText}>Save</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* ---- Change Password Modal ---- */}
      <Modal visible={changePasswordVisible} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={[styles.modalContent, { backgroundColor: card, borderColor: border }]}>
            <Text style={[styles.modalTitle, { color: text }]}>Change Password</Text>

            <Text style={[styles.modalLabel, { color: muted }]}>Current Password</Text>
            <TextInput
              style={[styles.modalInput, { backgroundColor: inputBg, color: inputText, borderColor: border }]}
              value={currentPassword}
              onChangeText={setCurrentPassword}
              placeholder="Enter current password"
              placeholderTextColor={muted}
              secureTextEntry
            />

            <Text style={[styles.modalLabel, { color: muted }]}>New Password</Text>
            <TextInput
              style={[styles.modalInput, { backgroundColor: inputBg, color: inputText, borderColor: border }]}
              value={newPassword}
              onChangeText={setNewPassword}
              placeholder="Min. 6 characters"
              placeholderTextColor={muted}
              secureTextEntry
            />

            <Text style={[styles.modalLabel, { color: muted }]}>Confirm New Password</Text>
            <TextInput
              style={[styles.modalInput, { backgroundColor: inputBg, color: inputText, borderColor: border }]}
              value={confirmNewPassword}
              onChangeText={setConfirmNewPassword}
              placeholder="Re-enter new password"
              placeholderTextColor={muted}
              secureTextEntry
            />

            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={[styles.modalButton, { backgroundColor: isDarkMode ? '#1a1a2e' : '#eee' }]}
                onPress={() => setChangePasswordVisible(false)}
              >
                <Text style={[styles.cancelButtonText, { color: muted }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.modalButton, styles.saveButton]} onPress={handleChangePassword}>
                <Text style={styles.saveButtonText}>Change</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  profileSection: {
    alignItems: 'center',
    paddingVertical: 30,
    borderBottomWidth: 1,
  },
  profileAvatar: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 12,
  },
  profileAvatarText: {
    fontSize: 32,
    fontWeight: 'bold',
    color: '#fff',
  },
  profileName: {
    fontSize: 22,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  profileEmail: {
    fontSize: 14,
  },
  section: {
    marginTop: 24,
    paddingHorizontal: 16,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 12,
    marginLeft: 4,
  },
  settingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderRadius: 12,
    marginBottom: 8,
  },
  settingLeft: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  settingIcon: {
    marginRight: 12,
  },
  settingLabel: {
    fontSize: 16,
  },
  logoutButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 32,
    marginHorizontal: 16,
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
  },
  logoutText: {
    color: '#e94560',
    fontSize: 17,
    fontWeight: '600',
    marginLeft: 8,
  },
  bottomPadding: {
    height: 40,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    borderRadius: 20,
    padding: 24,
    width: '85%',
    borderWidth: 1,
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    marginBottom: 20,
  },
  modalLabel: {
    fontSize: 13,
    fontWeight: '600',
    marginBottom: 6,
    marginLeft: 4,
  },
  modalInput: {
    borderRadius: 12,
    padding: 14,
    fontSize: 16,
    borderWidth: 1,
    marginBottom: 16,
  },
  modalButtons: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 12,
    marginTop: 4,
  },
  modalButton: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 10,
  },
  cancelButtonText: {
    fontSize: 16,
    fontWeight: '600',
  },
  saveButton: {
    backgroundColor: '#e94560',
  },
  saveButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
