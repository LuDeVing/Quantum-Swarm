import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { DrawerContentScrollView } from '@react-navigation/drawer';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '../theme';

const items = [
  ['Projects', 'grid-outline', 'Portfolio'],
  ['Agents', 'hardware-chip-outline', 'Agents'],
  ['Artifacts', 'documents-outline', 'Artifacts'],
  ['Logs', 'terminal-outline', 'Logs'],
  ['Options', 'settings-outline', 'Settings'],
];

export default function CustomDrawer({ state, navigation, user, onLogout, ...props }) {
  const current = state.routes[state.index].name;
  return (
    <View style={styles.page}>
      <View style={styles.brand}><View style={styles.mark}><Ionicons name="layers" size={22} color={colors.primary} /></View><View><Text style={styles.brandName}>QUANTUM SWARM</Text><Text style={styles.brandSub}>Engineering control center</Text></View></View>
      <DrawerContentScrollView {...props} contentContainerStyle={styles.menu}>
        {items.map(([name, icon, label]) => <TouchableOpacity key={name} style={[styles.item, current === name && styles.itemActive]} onPress={() => navigation.navigate(name)}><Ionicons name={icon} size={19} color={current === name ? colors.primary : colors.textMuted} /><Text style={[styles.itemText, current === name && styles.itemTextActive]}>{label}</Text></TouchableOpacity>)}
      </DrawerContentScrollView>
      <View style={styles.user}><View style={styles.avatar}><Text style={styles.avatarText}>{user?.name?.charAt(0)?.toUpperCase() || 'Q'}</Text></View><View style={{ flex: 1 }}><Text style={styles.userName}>{user?.name || 'Local workspace'}</Text><Text style={styles.email}>{user?.email || 'Guest mode'}</Text></View><TouchableOpacity onPress={onLogout}><Ionicons name="log-out-outline" size={19} color={colors.danger} /></TouchableOpacity></View>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.surface }, brand: { flexDirection: 'row', alignItems: 'center', padding: 18, paddingTop: 48, borderBottomWidth: 1, borderBottomColor: colors.border }, mark: { width: 38, height: 38, borderRadius: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primarySoft, borderWidth: 1, borderColor: colors.primary, marginRight: 10 }, brandName: { color: colors.text, fontSize: 13, fontWeight: '800' }, brandSub: { color: colors.textDim, fontSize: 9, marginTop: 3 }, menu: { padding: 10 }, item: { flexDirection: 'row', alignItems: 'center', padding: 12, borderRadius: 8, marginBottom: 4 }, itemActive: { backgroundColor: colors.primarySoft }, itemText: { color: colors.textMuted, fontSize: 13, marginLeft: 11, fontWeight: '600' }, itemTextActive: { color: colors.primary }, user: { flexDirection: 'row', alignItems: 'center', padding: 14, borderTopWidth: 1, borderTopColor: colors.border }, avatar: { width: 34, height: 34, borderRadius: 17, backgroundColor: colors.surfaceRaised, alignItems: 'center', justifyContent: 'center', marginRight: 9 }, avatarText: { color: colors.text, fontWeight: '800' }, userName: { color: colors.text, fontSize: 11, fontWeight: '700' }, email: { color: colors.textDim, fontSize: 9, marginTop: 3 },
});
