import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator, ScrollView, StyleSheet, Text, TextInput, TouchableOpacity,
  useWindowDimensions, View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import {
  getProjectArtifactContent, getProjectDashboard, getProjectLogs, getProjectMessages,
  getProjectVerification, runProjectVerification, sendMessage, stopProject,
} from '../services/api';
import ScreenState from '../components/ScreenState';
import { colors, statusColor, type } from '../theme';

const STEP_ICONS = {
  brief: 'chatbubbles-outline', plan: 'git-network-outline', build: 'construct-outline',
  test: 'flask-outline', run: 'terminal-outline', deliver: 'checkmark-done-outline',
};

const EVENT_ICONS = {
  plan: 'git-network-outline', assignment: 'person-add-outline', file: 'document-text-outline',
  fix: 'build-outline', test: 'flask-outline', verification: 'shield-checkmark-outline',
};

function Panel({ title, copy, action, children, style }) {
  return <View style={[styles.panel, style]}>
    <View style={styles.panelHeader}>
      <View style={{ flex: 1 }}><Text style={styles.panelTitle}>{title}</Text>{copy ? <Text style={styles.panelCopy}>{copy}</Text> : null}</View>
      {action}
    </View>
    {children}
  </View>;
}

function StatusPill({ status }) {
  return <View style={[styles.pill, { borderColor: statusColor(status) }]}><View style={[styles.dot, { backgroundColor: statusColor(status) }]} /><Text style={[styles.pillText, { color: statusColor(status) }]}>{String(status || 'pending').replaceAll('_', ' ')}</Text></View>;
}

function Terminal({ result, empty }) {
  return <View style={styles.terminal}>
    <View style={styles.terminalBar}><View style={[styles.terminalLight, { backgroundColor: colors.danger }]} /><View style={[styles.terminalLight, { backgroundColor: colors.warning }]} /><View style={[styles.terminalLight, { backgroundColor: colors.success }]} /><Text style={styles.terminalCommand}>{result?.command || 'Awaiting command'}</Text></View>
    <ScrollView style={styles.terminalBody}><Text style={styles.terminalText}>{result?.output || empty}</Text></ScrollView>
  </View>;
}

function CodeViewer({ artifact, loading }) {
  const lines = String(artifact?.content || '').split('\n');
  return <View style={styles.codeBox}>
    <View style={styles.codeHeader}><Ionicons name="code-slash-outline" size={15} color={colors.primary} /><Text style={styles.codePath}>{artifact?.path || 'Select a generated file'}</Text><Text style={styles.codeLanguage}>{artifact?.language || ''}</Text></View>
    <ScrollView horizontal><ScrollView style={styles.codeBody}>
      {loading ? <ActivityIndicator color={colors.primary} /> : lines.map((line, index) => <View key={index} style={styles.codeLine}><Text style={styles.lineNumber}>{String(index + 1).padStart(2, '0')}</Text><Text style={styles.sourceLine}>{line || ' '}</Text></View>)}
    </ScrollView></ScrollView>
  </View>;
}

export default function ChatScreen({ route, navigation }) {
  const projectId = route?.params?.projectId;
  const projectName = route?.params?.projectName || 'Project workspace';
  const { width } = useWindowDimensions();
  const compact = width < 900;
  const [dashboard, setDashboard] = useState(null);
  const [messages, setMessages] = useState([]);
  const [logs, setLogs] = useState([]);
  const [verification, setVerification] = useState({});
  const [activeStep, setActiveStep] = useState('brief');
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [artifact, setArtifact] = useState(null);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [input, setInput] = useState('');
  const [running, setRunning] = useState('');
  const [error, setError] = useState('');
  const [showRaw, setShowRaw] = useState(false);

  const load = useCallback(async (initial = false) => {
    if (!projectId) return;
    try {
      const [dash, messageData, logData, verify] = await Promise.all([
        getProjectDashboard(projectId), getProjectMessages(projectId), getProjectLogs(projectId, 120), getProjectVerification(projectId),
      ]);
      setDashboard(dash); setMessages(messageData.messages || []); setLogs(logData.lines || []); setVerification(verify || {});
      if (initial) {
        const active = dash.workflow?.find((step) => step.status === 'active' || step.status === 'failed');
        const latest = [...(dash.workflow || [])].reverse().find((step) => step.status === 'complete');
        setActiveStep(active?.key || latest?.key || 'brief');
      }
      setError('');
    } catch (e) { setError(e.message || 'Could not load this project.'); }
  }, [projectId]);

  useEffect(() => {
    load(true);
    const timer = setInterval(() => load(false), 3500);
    return () => clearInterval(timer);
  }, [load]);

  const selectedNode = useMemo(() => dashboard?.tree?.nodes?.find((node) => node.id === selectedNodeId) || dashboard?.tree?.nodes?.[0], [dashboard, selectedNodeId]);
  const root = dashboard?.tree?.nodes?.find((node) => node.id === dashboard?.tree?.rootId);
  const children = dashboard?.tree?.nodes?.filter((node) => node.parentId === dashboard?.tree?.rootId) || [];
  const percent = dashboard?.total ? Math.round((dashboard.done / dashboard.total) * 100) : 0;

  const selectNode = async (node) => {
    setSelectedNodeId(node.id);
    if (!node.file) { setArtifact(null); return; }
    setArtifactLoading(true);
    try { setArtifact(await getProjectArtifactContent(projectId, node.file)); } catch (e) { setArtifact({ path: node.file, content: `Preview unavailable: ${e.message}`, language: 'text' }); }
    finally { setArtifactLoading(false); }
  };

  const verify = async (kind) => {
    setRunning(kind);
    try {
      const result = await runProjectVerification(projectId, kind);
      setVerification((current) => ({ ...current, [kind]: result }));
      await load(false);
    } catch (e) { setError(e.message); }
    finally { setRunning(''); }
  };

  const send = async () => {
    if (!input.trim()) return;
    const text = input.trim(); setInput('');
    try { await sendMessage(projectId, text); await load(false); } catch (e) { setError(e.message); }
  };

  if (!dashboard) return <ScreenState loading={!error} error={error} onRetry={() => load(true)} />;

  const stepBody = {
    brief: <View style={[styles.twoCol, compact && styles.stack]}>
      <Panel title="Project brief" copy="The source request that launched the swarm." style={styles.flexPanel}>
        <ScrollView style={styles.briefScroll}>{messages.map((message) => <View key={message.id} style={[styles.message, message.sender === 'user' && styles.userMessage]}><Text style={styles.messageRole}>{message.sender === 'user' ? 'OPERATOR' : 'AI CEO'}</Text><Text style={styles.messageText}>{message.text}</Text></View>)}</ScrollView>
        <View style={styles.composer}><TextInput value={input} onChangeText={setInput} placeholder="Add direction for the AI CEO..." placeholderTextColor={colors.textDim} style={styles.input} /><TouchableOpacity style={styles.primaryButton} onPress={send}><Ionicons name="send" size={15} color="#fff" /></TouchableOpacity></View>
      </Panel>
      <Panel title="Success contract" copy="What the project must prove before delivery." style={styles.sidePanel}>
        {['Plan decomposed into visible tasks', 'Generated files available for inspection', 'Tests execute successfully', 'Application command produces proof', 'Quality gate passes'].map((item, index) => <View key={item} style={styles.contractRow}><Ionicons name={index < (dashboard.status === 'Completed' ? 5 : 2) ? 'checkmark-circle' : 'ellipse-outline'} size={17} color={index < (dashboard.status === 'Completed' ? 5 : 2) ? colors.success : colors.textDim} /><Text style={styles.contractText}>{item}</Text></View>)}
      </Panel>
    </View>,
    plan: <View style={[styles.twoCol, compact && styles.stack]}>
      <Panel title="Interactive plan graph" copy={`${children.length} canonical work items with real generated-file mappings.`} style={styles.flexPanel}>
        <ScrollView horizontal contentContainerStyle={styles.graph}>
          {root ? <TouchableOpacity style={[styles.rootNode, selectedNode?.id === root.id && styles.selectedNode]} onPress={() => selectNode(root)}><Ionicons name="flag-outline" size={20} color={colors.violet} /><Text style={styles.nodeTitle}>{root.name}</Text><Text style={styles.nodeCopy} numberOfLines={3}>{root.description}</Text></TouchableOpacity> : null}
          <View style={styles.graphConnector} />
          <View style={styles.nodeGrid}>{children.map((node) => <TouchableOpacity key={node.id} style={[styles.graphNode, selectedNode?.id === node.id && styles.selectedNode]} onPress={() => selectNode(node)}><View style={styles.nodeTop}><Ionicons name="document-text-outline" size={15} color={statusColor(node.status)} /><StatusPill status={node.status} /></View><Text style={styles.nodeTitle}>{node.name}</Text><Text style={styles.nodeFile}>{node.file || 'Integration proof'}</Text><Text style={styles.nodeMeta}>{node.complexity} • {node.dependsOn.length} dependencies • {node.retries} retries</Text></TouchableOpacity>)}</View>
        </ScrollView>
      </Panel>
      <Panel title={selectedNode?.name || 'Node details'} copy={selectedNode?.file || 'Project goal'} style={styles.sidePanel}>
        <Text style={styles.detailText}>{selectedNode?.description || 'Select a node to inspect its plan.'}</Text>
        <View style={styles.detailDivider} /><Text style={styles.detailLabel}>DEPENDENCIES</Text><Text style={styles.detailText}>{selectedNode?.dependsOn?.length ? selectedNode.dependsOn.join('\n') : 'No dependencies'}</Text>
        <View style={styles.detailDivider} /><Text style={styles.detailLabel}>ASSIGNED AGENT</Text><Text style={styles.detailText}>{selectedNode?.agent ? `@${selectedNode.agent}` : 'Resolved by swarm orchestration'}</Text>
      </Panel>
    </View>,
    build: <View style={[styles.twoCol, compact && styles.stack]}>
      <Panel title="Meaningful build activity" copy="Planning, assignments, file writes, fixes, tests, and verification." style={styles.flexPanel} action={<TouchableOpacity style={styles.ghostButton} onPress={() => setShowRaw(!showRaw)}><Text style={styles.ghostText}>{showRaw ? 'Hide raw logs' : 'Advanced logs'}</Text></TouchableOpacity>}>
        <ScrollView style={styles.activity}>{showRaw ? logs.map((line, index) => <Text key={index} style={styles.logLine}>{line}</Text>) : dashboard.events.map((event) => <View key={event.id} style={styles.event}><View style={styles.eventIcon}><Ionicons name={EVENT_ICONS[event.type] || 'pulse-outline'} size={15} color={colors.primary} /></View><View style={{ flex: 1 }}><Text style={styles.eventTitle}>{event.title}</Text><Text style={styles.eventDetail} numberOfLines={3}>{event.detail}</Text></View><Text style={styles.eventTime}>{event.timestamp}</Text></View>)}</ScrollView>
      </Panel>
      <Panel title="Agent fleet" copy="Current ownership and delivered work." style={styles.sidePanel}>
        <ScrollView>{dashboard.agents.map((agent) => <View key={agent.key} style={styles.agent}><View style={[styles.agentAvatar, { borderColor: statusColor(agent.status) }]}><Text style={styles.agentInitial}>{agent.key.split('_')[1]}</Text></View><View style={{ flex: 1 }}><Text style={styles.agentName}>@{agent.key}</Text><Text style={styles.agentTask}>{agent.current_file || `${agent.tasks_done} tasks delivered`}</Text></View><StatusPill status={agent.status} /></View>)}</ScrollView>
      </Panel>
    </View>,
    test: <View style={[styles.twoCol, compact && styles.stack]}>
      <Panel title="Test verification" copy="Execute the approved project test command and capture its proof." style={styles.flexPanel} action={<TouchableOpacity style={styles.actionButton} onPress={() => verify('test')} disabled={!!running}>{running === 'test' ? <ActivityIndicator color="#fff" /> : <><Ionicons name="flask-outline" size={15} color="#fff" /><Text style={styles.actionText}>Test again</Text></>}</TouchableOpacity>}>
        <View style={styles.proofMetrics}><Metric label="Status" value={verification.test?.passed ? 'Passed' : 'Awaiting proof'} color={verification.test?.passed ? colors.success : colors.warning} /><Metric label="Exit code" value={verification.test?.exitCode ?? '—'} /><Metric label="Duration" value={verification.test?.durationMs ? `${verification.test.durationMs}ms` : '—'} /></View>
        <Terminal result={verification.test} empty="Run the approved test suite to capture results here." />
      </Panel>
      <Panel title="Quality gate" copy="Delivery remains blocked until test and run proof pass." style={styles.sidePanel}>
        <QualityRow label="Task completion" passed={dashboard.done === dashboard.total && dashboard.total > 0} detail={`${dashboard.done}/${dashboard.total} delivered`} />
        <QualityRow label="Manager verification" passed={dashboard.quality?.quality_passed} detail={dashboard.quality?.quality_summary || 'Awaiting manager'} />
        <QualityRow label="Test command" passed={verification.test?.passed} detail={verification.test?.command || 'Not executed'} />
      </Panel>
    </View>,
    run: <View style={[styles.twoCol, compact && styles.stack]}>
      <Panel title="Integrated application runner" copy="Execute the approved smoke-proof command in a controlled process." style={styles.flexPanel} action={<TouchableOpacity style={styles.actionButton} onPress={() => verify('run')} disabled={!!running}>{running === 'run' ? <ActivityIndicator color="#fff" /> : <><Ionicons name="play-outline" size={15} color="#fff" /><Text style={styles.actionText}>Run again</Text></>}</TouchableOpacity>}>
        <Terminal result={verification.run} empty="Run the generated application to capture working output here." />
      </Panel>
      <Panel title="Runtime proof" copy="Captured evidence that the generated project works." style={styles.sidePanel}>
        <QualityRow label="Approved command" passed={!!verification.commands?.run} detail={verification.commands?.run?.display || 'No run command detected'} />
        <QualityRow label="Successful exit" passed={verification.run?.passed} detail={verification.run ? `Exit code ${verification.run.exitCode}` : 'Not executed'} />
        <QualityRow label="Output captured" passed={!!verification.run?.output} detail={verification.run?.timestamp || 'Awaiting proof'} />
      </Panel>
    </View>,
    deliver: <View style={[styles.twoCol, compact && styles.stack]}>
      <Panel title="Delivery proof" copy="Everything needed to trust and inspect this generated project." style={styles.flexPanel}>
        <View style={styles.deliveryHero}><View style={styles.deliveryIcon}><Ionicons name={dashboard.status === 'Completed' ? 'checkmark-done' : 'alert'} size={30} color={statusColor(dashboard.status)} /></View><View style={{ flex: 1 }}><Text style={styles.deliveryTitle}>{dashboard.status === 'Completed' ? 'Project delivered' : 'Delivery needs attention'}</Text><Text style={styles.deliveryCopy}>{dashboard.quality?.quality_summary || 'Quality verification has not completed yet.'}</Text></View><Text style={styles.deliveryScore}>{percent}%</Text></View>
        <View style={styles.proofMetrics}><Metric label="Tasks" value={`${dashboard.done}/${dashboard.total}`} color={colors.success} /><Metric label="Tests" value={verification.test?.passed ? 'Passed' : 'Not proven'} color={verification.test?.passed ? colors.success : colors.warning} /><Metric label="Run proof" value={verification.run?.passed ? 'Verified' : 'Not proven'} color={verification.run?.passed ? colors.success : colors.warning} /></View>
        <CodeViewer artifact={artifact} loading={artifactLoading} />
      </Panel>
      <Panel title="Generated files" copy="Select a delivered file to inspect its source." style={styles.sidePanel}>
        <ScrollView>{children.filter((node) => node.file).map((node) => <TouchableOpacity key={node.id} style={[styles.fileRow, artifact?.path === node.file && styles.fileRowSelected]} onPress={() => selectNode(node)}><Ionicons name="document-text-outline" size={16} color={colors.primary} /><View style={{ flex: 1 }}><Text style={styles.fileName}>{node.file}</Text><Text style={styles.fileMeta}>{node.status} • {node.complexity}</Text></View><Ionicons name="chevron-forward" size={14} color={colors.textDim} /></TouchableOpacity>)}</ScrollView>
      </Panel>
    </View>,
  };

  return <View style={styles.page}>
    <View style={styles.topbar}>
      <TouchableOpacity style={styles.iconButton} onPress={() => navigation.goBack()}><Ionicons name="arrow-back" size={18} color={colors.textMuted} /></TouchableOpacity>
      <View style={{ flex: 1 }}><Text style={styles.title}>{projectName}</Text><Text style={styles.subtitle}>{dashboard.status} • {dashboard.done}/{dashboard.total} tasks • {percent}% complete</Text></View>
      <StatusPill status={dashboard.status} />
      <TouchableOpacity style={styles.stopButton} onPress={() => stopProject(projectId).then(() => load(false))} disabled={dashboard.status !== 'In Progress'}><Ionicons name="stop-circle-outline" size={17} color={dashboard.status === 'In Progress' ? colors.danger : colors.textDim} /><Text style={styles.stopText}>Stop</Text></TouchableOpacity>
    </View>
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.stepper}>{dashboard.workflow.map((step, index) => <TouchableOpacity key={step.key} onPress={() => setActiveStep(step.key)} style={[styles.step, activeStep === step.key && styles.stepActive]}><View style={[styles.stepIcon, { borderColor: statusColor(step.status), backgroundColor: step.status === 'complete' ? '#102a20' : colors.surfaceAlt }]}><Ionicons name={STEP_ICONS[step.key]} size={16} color={statusColor(step.status)} /></View><View><Text style={styles.stepNumber}>STEP {index + 1}</Text><Text style={[styles.stepLabel, activeStep === step.key && { color: colors.text }]}>{step.label}</Text></View><StatusPill status={step.status} /></TouchableOpacity>)}</ScrollView>
    <View style={styles.progress}><View style={[styles.progressFill, { width: `${percent}%` }]} /></View>
    {!!error && <TouchableOpacity style={styles.error} onPress={() => setError('')}><Text style={styles.errorText}>{error}</Text><Ionicons name="close" size={15} color={colors.danger} /></TouchableOpacity>}
    <View style={styles.content}>{stepBody[activeStep]}</View>
  </View>;
}

function Metric({ label, value, color = colors.text }) {
  return <View style={styles.metric}><Text style={styles.metricLabel}>{label}</Text><Text style={[styles.metricValue, { color }]}>{value}</Text></View>;
}

function QualityRow({ label, passed, detail }) {
  return <View style={styles.qualityRow}><Ionicons name={passed ? 'checkmark-circle' : 'ellipse-outline'} size={19} color={passed ? colors.success : colors.warning} /><View style={{ flex: 1 }}><Text style={styles.qualityLabel}>{label}</Text><Text style={styles.qualityDetail} numberOfLines={2}>{detail}</Text></View></View>;
}

const styles = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.bg }, topbar: { minHeight: 64, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 14, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 10 }, iconButton: { width: 34, height: 34, borderRadius: 8, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.border }, title: { color: colors.text, fontSize: 15, fontWeight: '800' }, subtitle: { color: colors.textMuted, fontSize: 10, marginTop: 3 },
  stepper: { padding: 10, gap: 7 }, step: { width: 178, minHeight: 58, flexDirection: 'row', alignItems: 'center', padding: 8, gap: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, borderRadius: 9 }, stepActive: { borderColor: colors.primary, backgroundColor: colors.primarySoft }, stepIcon: { width: 34, height: 34, borderRadius: 9, borderWidth: 1, alignItems: 'center', justifyContent: 'center' }, stepNumber: { color: colors.textDim, fontSize: 7, fontWeight: '800' }, stepLabel: { color: colors.textMuted, fontSize: 11, fontWeight: '800', marginTop: 2 }, progress: { height: 3, backgroundColor: colors.border }, progressFill: { height: 3, backgroundColor: colors.success },
  content: { flex: 1, padding: 10 }, twoCol: { flex: 1, flexDirection: 'row', gap: 9 }, stack: { flexDirection: 'column' }, panel: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, overflow: 'hidden' }, flexPanel: { flex: 1 }, sidePanel: { width: 330 }, panelHeader: { minHeight: 58, flexDirection: 'row', alignItems: 'center', paddingHorizontal: 13, borderBottomWidth: 1, borderBottomColor: colors.border, gap: 8 }, panelTitle: { color: colors.text, fontSize: 12, fontWeight: '800' }, panelCopy: { color: colors.textMuted, fontSize: 9, marginTop: 3 },
  pill: { flexDirection: 'row', alignItems: 'center', gap: 5, borderWidth: 1, borderRadius: 20, paddingHorizontal: 7, paddingVertical: 4 }, dot: { width: 5, height: 5, borderRadius: 3 }, pillText: { fontSize: 7, fontWeight: '900', textTransform: 'uppercase' }, stopButton: { flexDirection: 'row', alignItems: 'center', gap: 4, padding: 8, borderWidth: 1, borderColor: colors.border, borderRadius: 7 }, stopText: { color: colors.textMuted, fontSize: 9, fontWeight: '700' },
  briefScroll: { flex: 1, padding: 12 }, message: { maxWidth: '86%', padding: 10, marginBottom: 9, backgroundColor: colors.surfaceAlt, borderWidth: 1, borderColor: colors.border, borderRadius: 8 }, userMessage: { alignSelf: 'flex-end', backgroundColor: colors.primarySoft, borderColor: '#24518d' }, messageRole: { color: colors.violet, fontSize: 8, fontWeight: '900', marginBottom: 5 }, messageText: { color: colors.textMuted, fontSize: 10, lineHeight: 16 }, composer: { flexDirection: 'row', padding: 10, gap: 7, borderTopWidth: 1, borderTopColor: colors.border }, input: { flex: 1, color: colors.text, backgroundColor: colors.bg, borderWidth: 1, borderColor: colors.border, borderRadius: 7, padding: 9, fontSize: 10, outlineStyle: 'none' }, primaryButton: { width: 36, height: 36, borderRadius: 7, backgroundColor: colors.primary, alignItems: 'center', justifyContent: 'center' },
  contractRow: { flexDirection: 'row', gap: 9, alignItems: 'center', padding: 12, borderBottomWidth: 1, borderBottomColor: colors.border }, contractText: { color: colors.textMuted, fontSize: 10, flex: 1 }, graph: { padding: 18, alignItems: 'center', minHeight: 420 }, rootNode: { width: 190, minHeight: 130, padding: 13, borderWidth: 1, borderColor: colors.violet, borderRadius: 10, backgroundColor: '#171527' }, graphConnector: { width: 42, height: 1, backgroundColor: colors.borderStrong }, nodeGrid: { width: 560, flexDirection: 'row', flexWrap: 'wrap', gap: 9 }, graphNode: { width: 174, minHeight: 128, padding: 10, borderWidth: 1, borderColor: colors.border, borderRadius: 9, backgroundColor: colors.surfaceAlt }, selectedNode: { borderColor: colors.primary, backgroundColor: colors.primarySoft }, nodeTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, nodeTitle: { color: colors.text, fontSize: 10, lineHeight: 14, fontWeight: '800', marginTop: 8 }, nodeCopy: { color: colors.textMuted, fontSize: 8, lineHeight: 13, marginTop: 6 }, nodeFile: { color: colors.primary, fontSize: 8, marginTop: 6 }, nodeMeta: { color: colors.textDim, fontSize: 7, lineHeight: 12, marginTop: 7 }, detailText: { color: colors.textMuted, fontSize: 10, lineHeight: 17, padding: 13 }, detailDivider: { height: 1, backgroundColor: colors.border }, detailLabel: { color: colors.textDim, fontSize: 8, fontWeight: '900', paddingHorizontal: 13, paddingTop: 12 },
  activity: { flex: 1, padding: 10 }, event: { flexDirection: 'row', alignItems: 'flex-start', gap: 9, padding: 9, marginBottom: 7, borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: colors.surfaceAlt }, eventIcon: { width: 30, height: 30, borderRadius: 8, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.primarySoft }, eventTitle: { color: colors.text, fontSize: 10, fontWeight: '800' }, eventDetail: { color: colors.textMuted, fontSize: 8, lineHeight: 13, marginTop: 3 }, eventTime: { color: colors.textDim, fontSize: 7 }, ghostButton: { borderWidth: 1, borderColor: colors.border, borderRadius: 7, padding: 7 }, ghostText: { color: colors.textMuted, fontSize: 8, fontWeight: '800' }, logLine: { color: '#9fb4c4', fontFamily: type.mono, fontSize: 8, lineHeight: 14, marginBottom: 2 }, agent: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 10, borderBottomWidth: 1, borderBottomColor: colors.border }, agentAvatar: { width: 30, height: 30, borderRadius: 8, borderWidth: 1, alignItems: 'center', justifyContent: 'center' }, agentInitial: { color: colors.text, fontSize: 10, fontWeight: '900' }, agentName: { color: colors.text, fontSize: 9, fontWeight: '800' }, agentTask: { color: colors.textDim, fontSize: 7, marginTop: 3 },
  actionButton: { minWidth: 95, minHeight: 32, paddingHorizontal: 10, borderRadius: 7, backgroundColor: colors.primary, flexDirection: 'row', gap: 5, alignItems: 'center', justifyContent: 'center' }, actionText: { color: '#fff', fontSize: 9, fontWeight: '800' }, proofMetrics: { flexDirection: 'row', gap: 8, padding: 10 }, metric: { flex: 1, minHeight: 58, padding: 9, borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: colors.surfaceAlt }, metricLabel: { color: colors.textDim, fontSize: 8, fontWeight: '800', textTransform: 'uppercase' }, metricValue: { fontSize: 15, fontWeight: '900', marginTop: 7 }, terminal: { flex: 1, minHeight: 260, margin: 10, marginTop: 0, borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: '#04090e', overflow: 'hidden' }, terminalBar: { height: 34, flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: 10, backgroundColor: '#0a1118', borderBottomWidth: 1, borderBottomColor: colors.border }, terminalLight: { width: 7, height: 7, borderRadius: 4 }, terminalCommand: { color: colors.textMuted, fontFamily: type.mono, fontSize: 8, marginLeft: 6 }, terminalBody: { padding: 11 }, terminalText: { color: '#b9d3c4', fontFamily: type.mono, fontSize: 9, lineHeight: 15 }, qualityRow: { flexDirection: 'row', gap: 9, padding: 12, borderBottomWidth: 1, borderBottomColor: colors.border }, qualityLabel: { color: colors.text, fontSize: 10, fontWeight: '800' }, qualityDetail: { color: colors.textDim, fontSize: 8, lineHeight: 13, marginTop: 3 },
  deliveryHero: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: 16, borderBottomWidth: 1, borderBottomColor: colors.border }, deliveryIcon: { width: 56, height: 56, borderRadius: 15, alignItems: 'center', justifyContent: 'center', backgroundColor: '#10251c' }, deliveryTitle: { color: colors.text, fontSize: 17, fontWeight: '900' }, deliveryCopy: { color: colors.textMuted, fontSize: 9, lineHeight: 14, marginTop: 5 }, deliveryScore: { color: colors.success, fontSize: 24, fontWeight: '900' }, fileRow: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 11, borderBottomWidth: 1, borderBottomColor: colors.border }, fileRowSelected: { backgroundColor: colors.primarySoft }, fileName: { color: colors.text, fontFamily: type.mono, fontSize: 9 }, fileMeta: { color: colors.textDim, fontSize: 7, marginTop: 3 },
  codeBox: { flex: 1, minHeight: 250, margin: 10, marginTop: 0, borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: '#050a0f', overflow: 'hidden' }, codeHeader: { height: 34, flexDirection: 'row', gap: 7, alignItems: 'center', paddingHorizontal: 10, borderBottomWidth: 1, borderBottomColor: colors.border }, codePath: { color: colors.text, fontFamily: type.mono, fontSize: 8, flex: 1 }, codeLanguage: { color: colors.primary, fontSize: 7, fontWeight: '900', textTransform: 'uppercase' }, codeBody: { padding: 8, minWidth: 650 }, codeLine: { flexDirection: 'row' }, lineNumber: { width: 32, color: colors.textDim, fontFamily: type.mono, fontSize: 8, lineHeight: 15, textAlign: 'right', marginRight: 12 }, sourceLine: { color: '#b9d1e2', fontFamily: type.mono, fontSize: 8, lineHeight: 15 },
  error: { flexDirection: 'row', padding: 8, backgroundColor: '#29161c' }, errorText: { color: colors.danger, fontSize: 9, flex: 1 },
});
