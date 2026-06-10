import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TextInput, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { getPortfolio } from '../services/api';
import { colors, statusColor } from '../theme';
import ScreenState from '../components/ScreenState';

export default function ArtifactsScreen() {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(() => getPortfolio().then((value) => { setData(value); setError(''); }).catch((e) => setError(e.message)), []);
  useEffect(load, [load]);
  const artifacts = useMemo(() => (data?.artifacts || []).filter((item) => `${item.name} ${item.projectName}`.toLowerCase().includes(query.toLowerCase())), [data, query]);

  return (
    <ScreenState loading={!data && !error} error={error} onRetry={load}>
      <View style={styles.page}>
        <View style={styles.header}><View><Text style={styles.title}>Artifacts</Text><Text style={styles.subtitle}>Generated files and planned components across every project.</Text></View><TouchableOpacity style={styles.refresh} onPress={load}><Ionicons name="refresh-outline" size={18} color={colors.text} /></TouchableOpacity></View>
        <View style={styles.search}><Ionicons name="search-outline" size={17} color={colors.textDim} /><TextInput value={query} onChangeText={setQuery} placeholder="Search artifacts or projects..." placeholderTextColor={colors.textDim} style={styles.input} /></View>
        <ScrollView style={styles.table}>
          <View style={styles.tableHeader}><Text style={[styles.head, { flex: 2 }]}>Artifact</Text><Text style={styles.head}>Project</Text><Text style={styles.head}>Type</Text><Text style={styles.head}>Created by</Text><Text style={styles.head}>Status</Text></View>
          {artifacts.map((item) => (
            <View key={item.id} style={styles.row}>
              <View style={[styles.cell, { flex: 2, flexDirection: 'row', alignItems: 'center' }]}><Ionicons name="document-text-outline" size={16} color={colors.primary} /><Text style={styles.artifactName} numberOfLines={1}>{item.name}</Text></View>
              <Text style={styles.cell} numberOfLines={1}>{item.projectName}</Text><Text style={styles.cell}>{item.type}</Text><Text style={styles.cell}>@{item.createdBy}</Text><Text style={[styles.cell, { color: statusColor(item.status) }]}>{item.status}</Text>
            </View>
          ))}
          {!artifacts.length && <Text style={styles.empty}>No matching artifacts yet.</Text>}
        </ScrollView>
      </View>
    </ScreenState>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.bg, padding: 22 }, header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, title: { color: colors.text, fontSize: 24, fontWeight: '800' }, subtitle: { color: colors.textMuted, fontSize: 13, marginTop: 5 },
  refresh: { width: 38, height: 38, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border, borderRadius: 8 },
  search: { maxWidth: 460, height: 38, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 11, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 8, marginTop: 20 }, input: { flex: 1, color: colors.text, fontSize: 12, marginLeft: 8, outlineStyle: 'none' },
  table: { marginTop: 16, borderWidth: 1, borderColor: colors.border, borderRadius: 9, backgroundColor: colors.surface }, tableHeader: { flexDirection: 'row', padding: 12, backgroundColor: colors.surfaceRaised, borderBottomWidth: 1, borderBottomColor: colors.border }, head: { flex: 1, color: colors.textMuted, fontSize: 10, fontWeight: '800', textTransform: 'uppercase' },
  row: { flexDirection: 'row', minHeight: 48, alignItems: 'center', paddingHorizontal: 12, borderBottomWidth: 1, borderBottomColor: colors.border }, cell: { flex: 1, color: colors.textMuted, fontSize: 11 }, artifactName: { color: colors.text, fontSize: 11, fontWeight: '600', marginLeft: 8, flex: 1 }, empty: { color: colors.textDim, padding: 20, textAlign: 'center' },
});
