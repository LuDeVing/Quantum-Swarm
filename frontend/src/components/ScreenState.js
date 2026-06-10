import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '../theme';

export default function ScreenState({ loading, error, empty, onRetry, children }) {
  if (loading) {
    return <View style={styles.state}><ActivityIndicator color={colors.primary} /><Text style={styles.copy}>Syncing with the swarm...</Text></View>;
  }
  if (error) {
    return (
      <View style={styles.state}>
        <Ionicons name="cloud-offline-outline" size={32} color={colors.danger} />
        <Text style={styles.title}>Could not reach Quantum Swarm</Text>
        <Text style={styles.copy}>{error}</Text>
        {!!onRetry && <TouchableOpacity style={styles.button} onPress={onRetry}><Text style={styles.buttonText}>Retry</Text></TouchableOpacity>}
      </View>
    );
  }
  if (empty) return <View style={styles.state}>{empty}</View>;
  return children;
}

const styles = StyleSheet.create({
  state: { flex: 1, minHeight: 240, alignItems: 'center', justifyContent: 'center', padding: 24, backgroundColor: colors.bg },
  title: { color: colors.text, fontSize: 17, fontWeight: '700', marginTop: 14 },
  copy: { color: colors.textMuted, fontSize: 13, marginTop: 8, textAlign: 'center', maxWidth: 420 },
  button: { marginTop: 16, backgroundColor: colors.primary, borderRadius: 8, paddingHorizontal: 18, paddingVertical: 10 },
  buttonText: { color: '#fff', fontWeight: '700' },
});
