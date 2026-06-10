import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { getPortfolio } from '../services/api';
import { colors, statusColor } from '../theme';
import ScreenState from '../components/ScreenState';

export default function AgentsScreen() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(() => getPortfolio().then((value) => { setData(value); setError(''); }).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); const timer = setInterval(load, 5000); return () => clearInterval(timer); }, [load]);

  return (
    <ScreenState loading={!data && !error} error={error} onRetry={load}>
      <ScrollView style={styles.page} contentContainerStyle={styles.content}>
        <View style={styles.heading}><View><Text style={styles.title}>Agent Grid</Text><Text style={styles.subtitle}>Live workload and delivery health across the engineering swarm.</Text></View><TouchableOpacity style={styles.refresh} onPress={load}><Ionicons name="refresh-outline" size={18} color={colors.text} /></TouchableOpacity></View>
        <View style={styles.summary}>
          <Metric label="Working now" value={data?.summary?.agentsWorking || 0} color={colors.primary} />
          <Metric label="Tasks delivered" value={data?.summary?.completedTasks || 0} color={colors.success} />
          <Metric label="Blockers" value={data?.summary?.blockers || 0} color={colors.danger} />
          <Metric label="Portfolio quality" value={data?.summary?.quality == null ? '--' : `${data.summary.quality}%`} color={colors.violet} />
        </View>
        <View style={styles.grid}>
          {(data?.agents || []).map((agent) => (
            <View key={agent.key} style={styles.agent}>
              <View style={styles.agentHeader}>
                <View style={[styles.agentIcon, { borderColor: statusColor(agent.status) }]}><Ionicons name="hardware-chip-outline" size={20} color={statusColor(agent.status)} /></View>
                <View style={{ flex: 1 }}><Text style={styles.agentName}>{agent.name}</Text><Text style={[styles.agentStatus, { color: statusColor(agent.status) }]}>{agent.status}</Text></View>
                <Text style={styles.agentKey}>@{agent.key}</Text>
              </View>
              <Text style={styles.sectionLabel}>CURRENT ASSIGNMENT</Text>
              <Text style={styles.assignment} numberOfLines={2}>{agent.currentTask || 'Ready for the next assignment'}</Text>
              <View style={styles.stats}><Text style={styles.stat}>{agent.tasksDone} completed</Text><Text style={[styles.stat, agent.tasksFailed > 0 && { color: colors.danger }]}>{agent.tasksFailed} failed</Text></View>
            </View>
          ))}
        </View>
      </ScrollView>
    </ScreenState>
  );
}

function Metric({ label, value, color }) {
  return <View style={styles.metric}><View style={[styles.metricLine, { backgroundColor: color }]} /><Text style={styles.metricValue}>{value}</Text><Text style={styles.metricLabel}>{label}</Text></View>;
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.bg }, content: { padding: 22 },
  heading: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, title: { color: colors.text, fontSize: 24, fontWeight: '800' }, subtitle: { color: colors.textMuted, fontSize: 13, marginTop: 5 },
  refresh: { width: 38, height: 38, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border, borderRadius: 8 },
  summary: { flexDirection: 'row', flexWrap: 'wrap', gap: 10, marginTop: 22 },
  metric: { minWidth: 170, flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 9, padding: 15 }, metricLine: { width: 28, height: 3, marginBottom: 12 }, metricValue: { color: colors.text, fontSize: 22, fontWeight: '800' }, metricLabel: { color: colors.textMuted, fontSize: 11, marginTop: 4 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 18 },
  agent: { minWidth: 260, flex: 1, maxWidth: 390, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 15 },
  agentHeader: { flexDirection: 'row', alignItems: 'center' }, agentIcon: { width: 42, height: 42, borderRadius: 9, alignItems: 'center', justifyContent: 'center', borderWidth: 1, marginRight: 10 },
  agentName: { color: colors.text, fontSize: 14, fontWeight: '700' }, agentStatus: { fontSize: 11, textTransform: 'capitalize', marginTop: 3 }, agentKey: { color: colors.textDim, fontSize: 10 },
  sectionLabel: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 0.7, marginTop: 16 }, assignment: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: 6, minHeight: 36 },
  stats: { flexDirection: 'row', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 11, marginTop: 12 }, stat: { color: colors.textMuted, fontSize: 10 },
});
