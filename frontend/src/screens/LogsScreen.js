import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { getPortfolio, getProjectLogs } from '../services/api';
import { colors, statusColor, type } from '../theme';
import ScreenState from '../components/ScreenState';

export default function LogsScreen() {
  const [portfolio, setPortfolio] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [logs, setLogs] = useState({ lines: [], status: 'Planning' });
  const [error, setError] = useState('');
  const loadPortfolio = useCallback(async () => {
    try {
      const data = await getPortfolio(); setPortfolio(data); setSelectedId((id) => id || data.projects?.[0]?.id || null); setError('');
    } catch (e) { setError(e.message); }
  }, []);
  useEffect(() => { loadPortfolio(); }, [loadPortfolio]);
  useEffect(() => {
    if (!selectedId) return;
    const load = () => getProjectLogs(selectedId).then(setLogs).catch((e) => setError(e.message));
    load(); const timer = setInterval(load, 3000); return () => clearInterval(timer);
  }, [selectedId]);

  return (
    <ScreenState loading={!portfolio && !error} error={error} onRetry={loadPortfolio}>
      <View style={styles.page}>
        <View style={styles.rail}><Text style={styles.railTitle}>Execution Logs</Text>{(portfolio?.projects || []).map((project) => <TouchableOpacity key={project.id} style={[styles.project, selectedId === project.id && styles.projectActive]} onPress={() => setSelectedId(project.id)}><View style={[styles.dot, { backgroundColor: statusColor(project.status) }]} /><View style={{ flex: 1 }}><Text style={styles.projectName} numberOfLines={1}>{project.name}</Text><Text style={styles.projectStatus}>{project.status}</Text></View></TouchableOpacity>)}</View>
        <View style={styles.console}>
          <View style={styles.consoleHeader}><View><Text style={styles.title}>{portfolio?.projects?.find((p) => p.id === selectedId)?.name || 'Select project'}</Text><Text style={[styles.status, { color: statusColor(logs.status) }]}>{logs.status}</Text></View><Ionicons name="terminal-outline" size={23} color={colors.primary} /></View>
          <ScrollView style={styles.logBody} contentContainerStyle={styles.logContent}>{logs.lines.length ? logs.lines.map((line, index) => <Text key={`${index}:${line}`} style={styles.line}><Text style={styles.lineNumber}>{String(index + 1).padStart(3, '0')}  </Text>{line}</Text>) : <Text style={styles.empty}>No run log exists yet. Brief the AI CEO inside a project workspace to begin.</Text>}</ScrollView>
        </View>
      </View>
    </ScreenState>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, flexDirection: 'row', backgroundColor: colors.bg }, rail: { width: 270, backgroundColor: colors.surface, borderRightWidth: 1, borderRightColor: colors.border, paddingTop: 18 }, railTitle: { color: colors.text, fontSize: 17, fontWeight: '800', paddingHorizontal: 16, marginBottom: 14 },
  project: { flexDirection: 'row', alignItems: 'center', padding: 13, borderBottomWidth: 1, borderBottomColor: colors.border }, projectActive: { backgroundColor: colors.primarySoft, borderLeftWidth: 3, borderLeftColor: colors.primary }, dot: { width: 7, height: 7, borderRadius: 4, marginRight: 9 }, projectName: { color: colors.text, fontSize: 12, fontWeight: '700' }, projectStatus: { color: colors.textMuted, fontSize: 10, marginTop: 3 },
  console: { flex: 1, padding: 20 }, consoleHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderColor: colors.border, borderBottomWidth: 0, borderTopLeftRadius: 9, borderTopRightRadius: 9, backgroundColor: colors.surfaceRaised, padding: 14 }, title: { color: colors.text, fontSize: 16, fontWeight: '800' }, status: { fontSize: 10, marginTop: 4 },
  logBody: { flex: 1, borderWidth: 1, borderColor: colors.border, borderBottomLeftRadius: 9, borderBottomRightRadius: 9, backgroundColor: '#050b11' }, logContent: { padding: 14 }, line: { color: '#a9c0d2', fontSize: 11, lineHeight: 18, fontFamily: type.mono }, lineNumber: { color: colors.textDim }, empty: { color: colors.textDim, fontSize: 12, padding: 14 },
});
