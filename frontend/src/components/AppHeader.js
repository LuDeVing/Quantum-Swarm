import React from 'react';
import { View, Text, TouchableOpacity, TextInput, StyleSheet, useWindowDimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '../theme';

const items = [
  ['Projects', 'Portfolio'],
  ['Agents', 'Agents'],
  ['Artifacts', 'Artifacts'],
  ['Logs', 'Logs'],
  ['Options', 'Settings'],
];

export default function AppHeader({ navigation, route, user }) {
  const { width } = useWindowDimensions();
  const compact = width < 920;
  const active = route.name === 'Projects' || route.name === 'ProjectWorkspace' ? 'Projects' : route.name;
  const navigateTo = (name) => {
    if (name === 'Projects') navigation.navigate('Projects', { screen: 'Portfolio' });
    else navigation.navigate(name);
  };

  return (
    <View style={styles.header}>
      <TouchableOpacity style={styles.brand} onPress={() => compact ? navigation.openDrawer() : navigateTo('Projects')}>
        <View style={styles.brandMark}>
          <Ionicons name={compact ? 'menu' : 'layers'} size={19} color={colors.primary} />
        </View>
        {!compact && <Text style={styles.brandText}>QUANTUM{'\n'}SWARM</Text>}
      </TouchableOpacity>

      {!compact && (
        <View style={styles.nav}>
          {items.map(([name, label]) => (
            <TouchableOpacity key={name} onPress={() => navigateTo(name)} style={styles.navItem}>
              <Text style={[styles.navText, active === name && styles.navTextActive]}>{label}</Text>
              {active === name && <View style={styles.navIndicator} />}
            </TouchableOpacity>
          ))}
        </View>
      )}

      <View style={styles.search}>
        <Ionicons name="search-outline" size={18} color={colors.textDim} />
        <TextInput
          style={styles.searchInput}
          placeholder={compact ? 'Search' : 'Search projects, agents, artifacts...'}
          placeholderTextColor={colors.textDim}
        />
      </View>

      <TouchableOpacity style={styles.iconButton}>
        <Ionicons name="notifications-outline" size={20} color={colors.textMuted} />
      </TouchableOpacity>
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{user?.name?.charAt(0)?.toUpperCase() || 'Q'}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    height: 62,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    backgroundColor: colors.bg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  brand: { flexDirection: 'row', alignItems: 'center', marginRight: 24 },
  brandMark: {
    width: 34, height: 34, borderRadius: 8, alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.primarySoft,
  },
  brandText: { color: colors.text, fontSize: 12, lineHeight: 13, fontWeight: '800', marginLeft: 9, letterSpacing: 0.7 },
  nav: { flexDirection: 'row', alignSelf: 'stretch' },
  navItem: { justifyContent: 'center', paddingHorizontal: 14 },
  navText: { color: colors.textMuted, fontSize: 14, fontWeight: '600' },
  navTextActive: { color: colors.primary },
  navIndicator: { position: 'absolute', height: 2, left: 12, right: 12, bottom: 0, backgroundColor: colors.primary },
  search: {
    flex: 1, maxWidth: 430, minWidth: 120, height: 36, marginLeft: 'auto',
    flexDirection: 'row', alignItems: 'center', paddingHorizontal: 11,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 8,
  },
  searchInput: { flex: 1, color: colors.text, marginLeft: 8, fontSize: 13, outlineStyle: 'none' },
  iconButton: { width: 38, height: 38, alignItems: 'center', justifyContent: 'center', marginLeft: 10 },
  avatar: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.surfaceRaised, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: colors.text, fontWeight: '700', fontSize: 12 },
});
