import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput, Modal,
  ActivityIndicator, Alert, useWindowDimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { createProject, deleteProject, getPortfolio, getProjectDashboard } from '../services/api';
import { colors, statusColor, taskColumn } from '../theme';
import ScreenState from '../components/ScreenState';

const columns = ['Planning', 'Building', 'Review', 'Done'];

const PanelTitle = ({ children, action, onAction }) => (
  <View style={styles.panelTitleRow}>
    <Text style={styles.panelTitle}>{children}</Text>
    {!!action && <TouchableOpacity onPress={onAction}><Text style={styles.panelAction}>{action}</Text></TouchableOpacity>}
  </View>
);

export default function ProjectsScreen({ navigation }) {
  const { width } = useWindowDimensions();
  const desktop = width >= 1120;
  const [portfolio, setPortfolio] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [dashboard, setDashboard] = useState({ tasks: [], agents: [], done: 0, total: 0 });
  const [filter, setFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modalVisible, setModalVisible] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const data = await getPortfolio();
      setPortfolio(data);
      setSelectedId((current) => current || data.projects?.[0]?.id || null);
      setError('');
    } catch (e) {
      setError(e.message || 'The API is unavailable.');
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), 5000);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!selectedId) {
      setDashboard({ tasks: [], agents: [], done: 0, total: 0 });
      return;
    }
    getProjectDashboard(selectedId).then(setDashboard).catch(() => {});
  }, [selectedId, portfolio]);

  const projects = useMemo(() => (
    (portfolio?.projects || []).filter((project) => project.name.toLowerCase().includes(filter.toLowerCase()))
  ), [portfolio, filter]);
  const selected = (portfolio?.projects || []).find((project) => project.id === selectedId) || projects[0];
  const artifacts = (portfolio?.artifacts || []).filter((item) => !selected || item.projectId === selected.id).slice(0, 6);

  const create = async () => {
    if (!newProjectName.trim()) return;
    setCreating(true);
    try {
      const data = await createProject(newProjectName.trim());
      setSelectedId(data.project.id);
      setModalVisible(false);
      setNewProjectName('');
      await load(true);
    } catch (e) {
      Alert.alert('Project not created', e.message);
    } finally {
      setCreating(false);
    }
  };

  const remove = (project) => {
    Alert.alert('Delete project', `Delete "${project.name}" and all generated artifacts?`, [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: async () => {
        try {
          await deleteProject(project.id);
          setSelectedId(null);
          await load(true);
        } catch (e) {
          Alert.alert('Delete failed', e.message);
        }
      } },
    ]);
  };

  const openWorkspace = () => {
    if (!selected) return;
    navigation.navigate('ProjectWorkspace', { projectId: selected.id, projectName: selected.name });
  };

  const empty = (
    <View style={styles.empty}>
      <Ionicons name="layers-outline" size={34} color={colors.primary} />
      <Text style={styles.emptyTitle}>Start your engineering portfolio</Text>
      <Text style={styles.emptyCopy}>Create a project, brief the AI CEO, and watch the swarm build it.</Text>
      <TouchableOpacity style={styles.primaryButton} onPress={() => setModalVisible(true)}>
        <Ionicons name="add" size={18} color="#fff" /><Text style={styles.primaryButtonText}>New project</Text>
      </TouchableOpacity>
    </View>
  );

  return (
    <ScreenState loading={loading} error={error} onRetry={load} empty={!portfolio?.projects?.length ? empty : null}>
      <View style={styles.page}>
        {desktop && (
          <View style={styles.projectRail}>
            <View style={styles.railHeader}>
              <Text style={styles.pageTitle}>Engineering Portfolio</Text>
              <TouchableOpacity style={styles.newButton} onPress={() => setModalVisible(true)}>
                <Ionicons name="add" size={16} color="#fff" /><Text style={styles.newButtonText}>New Project</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.railTabs}>
              <Text style={styles.railTabActive}>Active ({projects.length})</Text>
              <Text style={styles.railTab}>Archived</Text>
              <Text style={styles.railTab}>Templates</Text>
            </View>
            <View style={styles.filterBox}>
              <Ionicons name="search-outline" size={17} color={colors.textDim} />
              <TextInput value={filter} onChangeText={setFilter} placeholder="Filter projects..." placeholderTextColor={colors.textDim} style={styles.filterInput} />
            </View>
            <ScrollView style={styles.projectList}>
              {projects.map((project) => (
                <TouchableOpacity key={project.id} style={[styles.projectRow, selected?.id === project.id && styles.projectRowActive]} onPress={() => setSelectedId(project.id)}>
                  <Ionicons name="layers-outline" size={20} color={statusColor(project.status)} />
                  <View style={styles.projectRowBody}>
                    <View style={styles.rowBetween}>
                      <Text style={styles.projectName} numberOfLines={1}>{project.name}</Text>
                      <Text style={styles.projectPercent}>{project.progress}%</Text>
                    </View>
                    <View style={styles.projectMeta}>
                      <Text style={styles.projectStatus}>{project.status}</Text>
                      <Text style={[styles.projectHealth, { color: statusColor(project.failed ? 'Failed' : project.status) }]}>
                        {project.failed ? `${project.failed} failed` : 'On track'}
                      </Text>
                    </View>
                    <View style={styles.progressTrack}><View style={[styles.progressFill, { width: `${project.progress}%`, backgroundColor: statusColor(project.status) }]} /></View>
                  </View>
                  <TouchableOpacity style={styles.deleteButton} onPress={() => remove(project)}>
                    <Ionicons name="trash-outline" size={15} color={colors.textDim} />
                  </TouchableOpacity>
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        )}

        <ScrollView style={styles.main} contentContainerStyle={styles.mainContent}>
          <View style={styles.projectHeader}>
            <View style={styles.projectTitleIcon}><Ionicons name="layers" size={22} color={colors.primary} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.projectTitle}>{selected?.name || 'Portfolio overview'}</Text>
              <Text style={styles.projectSubtitle}>{selected ? `${selected.status}  •  ${selected.progress}% complete  •  ${selected.done}/${selected.total} tasks` : 'No project selected'}</Text>
            </View>
            {!desktop && <TouchableOpacity style={styles.secondaryButton} onPress={() => setModalVisible(true)}><Ionicons name="add" size={17} color={colors.text} /></TouchableOpacity>}
            <TouchableOpacity style={styles.primaryButton} onPress={openWorkspace} disabled={!selected}>
              <Ionicons name="chatbubbles-outline" size={17} color="#fff" /><Text style={styles.primaryButtonText}>Open workspace</Text>
            </TouchableOpacity>
          </View>

          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.boardScroll} contentContainerStyle={styles.board}>
            {columns.map((column) => {
              const tasks = dashboard.tasks.filter((task) => taskColumn(task.status) === column);
              return (
                <View key={column} style={styles.boardColumn}>
                  <View style={styles.columnHeader}>
                    <View style={[styles.columnDot, { backgroundColor: statusColor(column) }]} />
                    <Text style={styles.columnTitle}>{column}</Text>
                    <Text style={styles.columnCount}>{tasks.length}</Text>
                  </View>
                  <ScrollView style={styles.columnScroll} showsVerticalScrollIndicator={false}>
                    {tasks.length ? tasks.map((task) => (
                      <View key={task.id} style={styles.taskCard}>
                        <Text style={styles.taskName} numberOfLines={2}>{task.file || task.id}</Text>
                        <Text style={styles.taskAgent}>{task.assigned_to ? `@${task.assigned_to}` : 'Awaiting assignment'}</Text>
                        <View style={styles.taskFooter}>
                          <Text style={[styles.taskStatus, { color: statusColor(task.status) }]}>{task.status.replaceAll('_', ' ')}</Text>
                          {!!task.retries && <Text style={styles.retry}>{task.retries} retries</Text>}
                        </View>
                      </View>
                    )) : <Text style={styles.columnEmpty}>No tasks in this stage</Text>}
                  </ScrollView>
                </View>
              );
            })}
          </ScrollView>

          <View style={styles.artifactsPanel}>
            <PanelTitle action="View all artifacts" onAction={() => navigation.navigate('Artifacts')}>Recent Artifacts</PanelTitle>
            <View style={styles.tableHeader}>
              <Text style={[styles.tableHead, { flex: 2 }]}>Artifact</Text><Text style={styles.tableHead}>Type</Text><Text style={styles.tableHead}>Created by</Text><Text style={styles.tableHead}>Status</Text>
            </View>
            {artifacts.length ? artifacts.map((artifact) => (
              <View key={artifact.id} style={styles.tableRow}>
                <Text style={[styles.tableText, { flex: 2 }]} numberOfLines={1}>{artifact.name}</Text>
                <Text style={styles.tableText}>{artifact.type}</Text>
                <Text style={styles.tableText}>@{artifact.createdBy}</Text>
                <Text style={[styles.tableText, { color: statusColor(artifact.status) }]}>{artifact.status}</Text>
              </View>
            )) : <Text style={styles.tableEmpty}>Artifacts will appear as agents create files.</Text>}
          </View>
        </ScrollView>

        {desktop && (
          <View style={styles.intelligence}>
            <Text style={styles.intelligenceTitle}>Swarm Intelligence</Text>
            <View style={styles.intelligenceSection}>
              <PanelTitle>Swarm Health</PanelTitle>
              <View style={styles.healthRow}>
                <View style={styles.healthScore}><Text style={styles.healthScoreText}>{portfolio?.summary?.quality ?? '--'}</Text><Text style={styles.healthScoreSub}>/100</Text></View>
                <View style={{ flex: 1 }}>
                  <Metric label="Agents working" value={portfolio?.summary?.agentsWorking || 0} color={colors.primary} />
                  <Metric label="Tasks complete" value={portfolio?.summary?.completedTasks || 0} color={colors.success} />
                  <Metric label="Blockers" value={portfolio?.summary?.blockers || 0} color={colors.danger} />
                </View>
              </View>
            </View>
            <View style={styles.intelligenceSection}>
              <PanelTitle action="View all" onAction={() => navigation.navigate('Agents')}>Current Blockers</PanelTitle>
              {(portfolio?.blockers || []).slice(0, 4).map((blocker) => (
                <View key={`${blocker.projectId}:${blocker.id}`} style={styles.blockerRow}>
                  <Text style={styles.blockerProject}>{blocker.projectName}</Text>
                  <Text style={styles.blockerCopy} numberOfLines={2}>{blocker.file}</Text>
                </View>
              ))}
              {!portfolio?.blockers?.length && <Text style={styles.goodCopy}>No active blockers.</Text>}
            </View>
            <View style={styles.intelligenceSection}>
              <PanelTitle>AI CEO Briefing</PanelTitle>
              <Text style={styles.briefing}>
                {selected?.summary || (selected ? `${selected.name} is ${selected.status.toLowerCase()} with ${selected.progress}% of tracked tasks complete.` : 'Create a project to begin a CEO-guided engineering run.')}
              </Text>
              <TouchableOpacity onPress={openWorkspace}><Text style={styles.panelAction}>Talk to AI CEO</Text></TouchableOpacity>
            </View>
          </View>
        )}

        <Modal visible={modalVisible} transparent animationType="fade">
          <View style={styles.modalOverlay}>
            <View style={styles.modal}>
              <Text style={styles.modalTitle}>Create engineering project</Text>
              <Text style={styles.modalCopy}>Name the initiative. You will brief the AI CEO inside its workspace.</Text>
              <TextInput autoFocus value={newProjectName} onChangeText={setNewProjectName} onSubmitEditing={create} placeholder="Example: Customer self-service portal" placeholderTextColor={colors.textDim} style={styles.modalInput} />
              <View style={styles.modalActions}>
                <TouchableOpacity style={styles.secondaryButton} onPress={() => setModalVisible(false)}><Text style={styles.secondaryButtonText}>Cancel</Text></TouchableOpacity>
                <TouchableOpacity style={styles.primaryButton} onPress={create} disabled={creating || !newProjectName.trim()}>
                  {creating ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryButtonText}>Create project</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>
      </View>
    </ScreenState>
  );
}

function Metric({ label, value, color }) {
  return <View style={styles.metric}><View style={[styles.metricDot, { backgroundColor: color }]} /><Text style={styles.metricLabel}>{label}</Text><Text style={styles.metricValue}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  page: { flex: 1, flexDirection: 'row', backgroundColor: colors.bg },
  projectRail: { width: 306, borderRightWidth: 1, borderRightColor: colors.border, backgroundColor: colors.surface, paddingTop: 16 },
  railHeader: { paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  pageTitle: { color: colors.text, fontSize: 17, fontWeight: '800' },
  newButton: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.primary, borderRadius: 7, paddingHorizontal: 10, paddingVertical: 8 },
  newButtonText: { color: '#fff', fontSize: 12, fontWeight: '700', marginLeft: 4 },
  railTabs: { flexDirection: 'row', paddingHorizontal: 16, marginTop: 22, borderBottomWidth: 1, borderBottomColor: colors.border },
  railTab: { color: colors.textMuted, fontSize: 12, paddingBottom: 10, marginRight: 18 },
  railTabActive: { color: colors.text, fontSize: 12, fontWeight: '700', paddingBottom: 10, marginRight: 18, borderBottomWidth: 2, borderBottomColor: colors.primary },
  filterBox: { height: 36, margin: 12, paddingHorizontal: 10, flexDirection: 'row', alignItems: 'center', backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, borderRadius: 7 },
  filterInput: { flex: 1, color: colors.text, marginLeft: 7, fontSize: 12, outlineStyle: 'none' },
  projectList: { flex: 1 },
  projectRow: { minHeight: 76, flexDirection: 'row', alignItems: 'flex-start', padding: 13, borderBottomWidth: 1, borderBottomColor: colors.border },
  projectRowActive: { backgroundColor: colors.primarySoft, borderLeftWidth: 3, borderLeftColor: colors.primary },
  projectRowBody: { flex: 1, marginLeft: 10 },
  rowBetween: { flexDirection: 'row', justifyContent: 'space-between' },
  projectName: { color: colors.text, fontSize: 13, fontWeight: '700', flex: 1 },
  projectPercent: { color: colors.textMuted, fontSize: 11 },
  projectMeta: { flexDirection: 'row', marginTop: 5 },
  projectStatus: { color: colors.textMuted, fontSize: 11, marginRight: 8 },
  projectHealth: { fontSize: 11 },
  progressTrack: { height: 3, backgroundColor: colors.border, marginTop: 8, borderRadius: 2, overflow: 'hidden' },
  progressFill: { height: 3 },
  deleteButton: { padding: 4, marginLeft: 3 },
  main: { flex: 1, backgroundColor: colors.bg },
  mainContent: { paddingBottom: 20 },
  projectHeader: { height: 72, paddingHorizontal: 14, flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, borderBottomColor: colors.border },
  projectTitleIcon: { width: 38, height: 38, borderRadius: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primarySoft, marginRight: 11 },
  projectTitle: { color: colors.text, fontSize: 17, fontWeight: '800' },
  projectSubtitle: { color: colors.textMuted, fontSize: 11, marginTop: 3 },
  primaryButton: { minHeight: 36, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', paddingHorizontal: 13, borderRadius: 7, backgroundColor: colors.primary, marginLeft: 8 },
  primaryButtonText: { color: '#fff', fontSize: 12, fontWeight: '700', marginLeft: 5 },
  secondaryButton: { minHeight: 36, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 13, borderRadius: 7, borderWidth: 1, borderColor: colors.borderStrong },
  secondaryButtonText: { color: colors.textMuted, fontWeight: '700', fontSize: 12 },
  boardScroll: { height: 485, flexGrow: 0 },
  board: { padding: 12, height: 485 },
  boardColumn: { width: 190, height: 455, borderWidth: 1, borderColor: colors.border, borderRadius: 8, marginRight: 8, padding: 7, backgroundColor: colors.surface },
  columnHeader: { height: 34, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 4 },
  columnDot: { width: 7, height: 7, borderRadius: 4, marginRight: 7 },
  columnTitle: { color: colors.text, fontSize: 12, fontWeight: '700', flex: 1 },
  columnCount: { color: colors.textMuted, fontSize: 11, backgroundColor: colors.surfaceRaised, paddingHorizontal: 7, paddingVertical: 2, borderRadius: 8 },
  columnScroll: { flex: 1 },
  taskCard: { minHeight: 86, padding: 10, backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border, borderRadius: 7, marginBottom: 7 },
  taskName: { color: colors.text, fontSize: 12, lineHeight: 17, fontWeight: '600' },
  taskAgent: { color: colors.textMuted, fontSize: 10, marginTop: 5 },
  taskFooter: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 9 },
  taskStatus: { fontSize: 10, textTransform: 'capitalize', fontWeight: '700' },
  retry: { color: colors.danger, fontSize: 10 },
  columnEmpty: { color: colors.textDim, fontSize: 11, textAlign: 'center', marginTop: 30 },
  artifactsPanel: { marginHorizontal: 12, borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: colors.surface, overflow: 'hidden' },
  panelTitleRow: { minHeight: 42, paddingHorizontal: 11, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  panelTitle: { color: colors.text, fontSize: 13, fontWeight: '800' },
  panelAction: { color: colors.primary, fontSize: 11, fontWeight: '600' },
  tableHeader: { flexDirection: 'row', paddingHorizontal: 11, paddingVertical: 8, backgroundColor: colors.surfaceRaised, borderTopWidth: 1, borderBottomWidth: 1, borderColor: colors.border },
  tableHead: { flex: 1, color: colors.textMuted, fontSize: 10, fontWeight: '700' },
  tableRow: { flexDirection: 'row', paddingHorizontal: 11, paddingVertical: 9, borderBottomWidth: 1, borderBottomColor: colors.border },
  tableText: { flex: 1, color: colors.textMuted, fontSize: 10 },
  tableEmpty: { color: colors.textDim, fontSize: 11, padding: 16 },
  intelligence: { width: 282, borderLeftWidth: 1, borderLeftColor: colors.border, backgroundColor: colors.surface, padding: 12 },
  intelligenceTitle: { color: colors.text, fontSize: 14, fontWeight: '800', marginBottom: 10 },
  intelligenceSection: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: colors.surfaceAlt, marginBottom: 10, paddingHorizontal: 9, paddingBottom: 10 },
  healthRow: { flexDirection: 'row', alignItems: 'center', paddingVertical: 7 },
  healthScore: { width: 70, height: 70, borderRadius: 35, borderWidth: 5, borderColor: colors.success, alignItems: 'center', justifyContent: 'center', marginRight: 12 },
  healthScoreText: { color: colors.text, fontSize: 22, fontWeight: '800' },
  healthScoreSub: { color: colors.textMuted, fontSize: 9 },
  metric: { flexDirection: 'row', alignItems: 'center', marginBottom: 7 },
  metricDot: { width: 6, height: 6, borderRadius: 3, marginRight: 6 },
  metricLabel: { color: colors.textMuted, fontSize: 10, flex: 1 },
  metricValue: { color: colors.text, fontSize: 10, fontWeight: '700' },
  blockerRow: { borderTopWidth: 1, borderTopColor: colors.border, paddingVertical: 8 },
  blockerProject: { color: colors.text, fontSize: 11, fontWeight: '700' },
  blockerCopy: { color: colors.textMuted, fontSize: 10, marginTop: 3 },
  goodCopy: { color: colors.success, fontSize: 11, paddingVertical: 8 },
  briefing: { color: colors.textMuted, fontSize: 11, lineHeight: 17, borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 9, marginBottom: 10 },
  empty: { alignItems: 'center', maxWidth: 460 },
  emptyTitle: { color: colors.text, fontSize: 20, fontWeight: '800', marginTop: 14 },
  emptyCopy: { color: colors.textMuted, fontSize: 13, textAlign: 'center', marginTop: 8, marginBottom: 14 },
  modalOverlay: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(3,8,13,0.78)', padding: 20 },
  modal: { width: '100%', maxWidth: 480, backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.borderStrong, borderRadius: 12, padding: 20 },
  modalTitle: { color: colors.text, fontSize: 18, fontWeight: '800' },
  modalCopy: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: 7 },
  modalInput: { color: colors.text, backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 12, marginTop: 18, outlineStyle: 'none' },
  modalActions: { flexDirection: 'row', justifyContent: 'flex-end', marginTop: 16 },
});
