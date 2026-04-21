import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  TouchableOpacity,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
  ScrollView,
  Animated,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import {
  getProjectMessages,
  sendMessage as sendProjectMessage,
  getGeneralMessages,
  sendGeneralMessage,
  getProjectProgress,
  getProjectDashboard,
  stopProject,
} from '../services/api';

const CEO_NAME = 'Alex Morgan';
const STATUS_COLOR = {
  pending:     '#555',
  in_progress: '#f0a500',
  completed:   '#4ecca3',
  failed:      '#e94560',
};
const STATUS_ICON = {
  pending:     '○',
  in_progress: '⚙',
  completed:   '✓',
  failed:      '✗',
};
const AGENT_COLOR = { idle: '#555', working: '#f0a500', done: '#4ecca3' };

export default function ChatScreen({ route }) {
  const projectId   = route?.params?.projectId   || null;
  const projectName = route?.params?.projectName || null;

  const [messages, setMessages]         = useState([]);
  const [inputText, setInputText]       = useState('');
  const [sending, setSending]           = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [panelOpen, setPanelOpen]       = useState(false);
  const [stopping, setStopping]         = useState(false);
  const [activeTab, setActiveTab]       = useState('tasks'); // 'tasks' | 'agents'
  const [dashboard, setDashboard]       = useState({ tasks: [], agents: [], done: 0, total: 0 });

  const flatListRef  = useRef(null);
  const pollRef      = useRef(null);
  const dashPollRef  = useRef(null);
  const panelAnim    = useRef(new Animated.Value(0)).current;
  const LIVE_ID      = 'live-progress';

  useEffect(() => {
    loadMessages();
    return () => { stopPolling(); stopDashPoll(); };
  }, [projectId]);

  useEffect(() => {
    Animated.timing(panelAnim, {
      toValue: panelOpen ? 1 : 0,
      duration: 260,
      useNativeDriver: false,
    }).start();
  }, [panelOpen]);

  // ── polling helpers ──────────────────────────────────────────────────────

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };
  const stopDashPoll = () => {
    if (dashPollRef.current) { clearInterval(dashPollRef.current); dashPollRef.current = null; }
  };

  const startPolling = () => {
    if (!projectId || pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const p = await getProjectProgress(projectId);
        const pct = p.total > 0 ? Math.round((p.done / p.total) * 100) : 0;
        const bar = p.total > 0
          ? `[${'█'.repeat(Math.round(pct / 10)).padEnd(10, '░')}] ${pct}%  (${p.done}/${p.total} tasks)`
          : '';
        const logLine = p.last_line ? `\n\n${p.last_line}` : '';

        if (p.status === 'In Progress') {
          const liveText = `⚙️ Engineers working...\n${bar}${logLine}`;
          setMessages(prev => {
            const has = prev.find(m => m.id === LIVE_ID);
            if (has) return prev.map(m => m.id === LIVE_ID ? { ...m, text: liveText } : m);
            return [...prev, { id: LIVE_ID, text: liveText, sender: 'ai', time: '' }];
          });
        } else {
          stopPolling();
          stopDashPoll();
          const doneText = p.status === 'Completed'
            ? `✅ Done!${p.total > 0 ? ` All ${p.total} tasks completed.` : ''} Check the project output.`
            : `⚠️ Engineering run ended with status: ${p.status}.`;
          setMessages(prev => prev.map(m => m.id === LIVE_ID ? { ...m, text: doneText } : m));
          // final dashboard fetch
          if (projectId) getProjectDashboard(projectId).then(setDashboard).catch(() => {});
        }
      } catch (e) {}
    }, 2000);
  };

  const startDashPoll = () => {
    if (!projectId || dashPollRef.current) return;
    dashPollRef.current = setInterval(async () => {
      try {
        const d = await getProjectDashboard(projectId);
        setDashboard(d);
      } catch (e) {}
    }, 3000);
  };

  const handleStop = async () => {
    if (!projectId || stopping) return;
    setStopping(true);
    try {
      const data = await stopProject(projectId);
      stopPolling();
      stopDashPoll();
      setMessages(prev => prev.map(m =>
        m.id === LIVE_ID ? { ...m, text: '⛔ Stopped.' } : m
      ).concat(prev.find(m => m.id === LIVE_ID) ? [] : [data.aiReply]));
      setDashboard(d => ({ ...d }));
    } catch (e) {
      // ignore
    } finally {
      setStopping(false);
    }
  };

  // ── load messages ────────────────────────────────────────────────────────

  const loadMessages = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const data = projectId
        ? await getProjectMessages(projectId)
        : await getGeneralMessages();
      setMessages(data.messages || []);
      if (projectId) {
        try {
          const p = await getProjectProgress(projectId);
          if (p.status === 'In Progress') { startPolling(); startDashPoll(); }
          const d = await getProjectDashboard(projectId);
          setDashboard(d);
        } catch (e) {}
      }
    } catch (error) {
      setMessages([{
        id: '1',
        text: projectName
          ? `Welcome! Let's discuss the "${projectName}" project. How can I help?`
          : "Welcome! I'm Alex Morgan, CEO of MyApp. Feel free to reach out with any questions.",
        sender: 'ceo',
        time: '9:00 AM',
      }]);
    } finally {
      setLoadingHistory(false);
    }
  }, [projectId, projectName]);

  // ── send message ─────────────────────────────────────────────────────────

  const handleSend = async () => {
    if (!inputText.trim() || sending) return;
    const text = inputText.trim();
    const now = new Date();
    const h = now.getHours() % 12 || 12;
    const m = now.getMinutes().toString().padStart(2, '0');
    const timeStr = `${h}:${m} ${now.getHours() >= 12 ? 'PM' : 'AM'}`;

    const tempUserMsg = { id: `temp-${Date.now()}`, text, sender: 'user', time: timeStr };
    setMessages(prev => [...prev, tempUserMsg]);
    setInputText('');
    setSending(true);

    try {
      const data = projectId
        ? await sendProjectMessage(projectId, text)
        : await sendGeneralMessage(text);

      setMessages(prev => {
        const without = prev.filter(m => m.id !== tempUserMsg.id);
        return [...without, data.userMessage, data.aiReply];
      });

      if (projectId && data.aiReply?.text?.startsWith('Got it!')) {
        startPolling();
        startDashPoll();
      }
    } catch (error) {
      setMessages(prev => [...prev, {
        id: `err-${Date.now()}`,
        text: 'Sorry, I could not reach the server. Please try again.',
        sender: 'ceo',
        time: timeStr,
      }]);
    } finally {
      setSending(false);
    }
  };

  // ── render helpers ────────────────────────────────────────────────────────

  const renderMessage = ({ item }) => {
    const isUser = item.sender === 'user';
    return (
      <View style={[styles.messageBubbleRow, isUser && styles.userRow]}>
        {!isUser && <View style={styles.avatar}><Text style={styles.avatarText}>AM</Text></View>}
        <View style={[styles.messageBubble, isUser ? styles.userBubble : styles.ceoBubble]}>
          {!isUser && <Text style={styles.senderName}>{CEO_NAME}</Text>}
          <Text style={[styles.messageText, isUser && styles.userMessageText]}>{item.text}</Text>
          {!!item.time && <Text style={[styles.timeText, isUser && styles.userTimeText]}>{item.time}</Text>}
        </View>
      </View>
    );
  };

  const renderTaskRow = (task) => {
    const color = STATUS_COLOR[task.status] || '#555';
    const icon  = STATUS_ICON[task.status]  || '○';
    return (
      <View key={task.id} style={styles.taskRow}>
        <Text style={[styles.taskIcon, { color }]}>{icon}</Text>
        <View style={{ flex: 1 }}>
          <Text style={styles.taskFile} numberOfLines={1}>{task.file || task.id}</Text>
          {task.assigned_to && (
            <Text style={styles.taskAssigned}>{task.assigned_to}</Text>
          )}
        </View>
        {task.retries > 0 && <Text style={styles.taskRetry}>↻{task.retries}</Text>}
      </View>
    );
  };

  const renderAgentCard = (agent) => {
    const color = AGENT_COLOR[agent.status] || '#555';
    return (
      <View key={agent.key} style={styles.agentCard}>
        <View style={[styles.agentDot, { backgroundColor: color }]} />
        <View style={{ flex: 1 }}>
          <Text style={styles.agentKey}>{agent.key}</Text>
          {agent.current_file
            ? <Text style={styles.agentFile} numberOfLines={1}>{agent.current_file}</Text>
            : <Text style={styles.agentIdle}>{agent.status === 'done' ? `${agent.tasks_done} done` : 'idle'}</Text>
          }
        </View>
        {agent.tasks_done > 0 && agent.status !== 'done' && (
          <Text style={styles.agentDoneCount}>✓{agent.tasks_done}</Text>
        )}
      </View>
    );
  };

  const panelHeight = panelAnim.interpolate({ inputRange: [0, 1], outputRange: [0, 280] });

  // ── render ────────────────────────────────────────────────────────────────

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      {/* Header */}
      <View style={styles.chatHeader}>
        <View style={styles.headerAvatar}><Text style={styles.headerAvatarText}>AM</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={styles.headerName}>{CEO_NAME}</Text>
          <Text style={styles.headerStatus}>
            {projectName ? `Project: ${projectName}` : 'CEO · Online'}
          </Text>
        </View>
        {projectId && dashboard.agents.some(a => a.status === 'working') && (
          <TouchableOpacity onPress={handleStop} disabled={stopping} style={styles.stopBtn}>
            {stopping
              ? <ActivityIndicator size="small" color="#e94560" />
              : <Ionicons name="stop-circle" size={26} color="#e94560" />
            }
          </TouchableOpacity>
        )}
        {projectId && (
          <TouchableOpacity onPress={() => setPanelOpen(v => !v)} style={styles.panelToggle}>
            <Ionicons
              name={panelOpen ? 'chevron-up' : 'analytics-outline'}
              size={22}
              color="#4ecca3"
            />
            {dashboard.total > 0 && (
              <Text style={styles.panelBadge}>{dashboard.done}/{dashboard.total}</Text>
            )}
          </TouchableOpacity>
        )}
        <View style={styles.onlineDot} />
      </View>

      {/* Collapsible dashboard panel */}
      {projectId && (
        <Animated.View style={[styles.panel, { height: panelHeight, overflow: 'hidden' }]}>
          {/* Tab bar */}
          <View style={styles.tabBar}>
            <TouchableOpacity
              style={[styles.tab, activeTab === 'tasks' && styles.tabActive]}
              onPress={() => setActiveTab('tasks')}
            >
              <Text style={[styles.tabText, activeTab === 'tasks' && styles.tabTextActive]}>
                Tasks {dashboard.total > 0 ? `(${dashboard.done}/${dashboard.total})` : ''}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.tab, activeTab === 'agents' && styles.tabActive]}
              onPress={() => setActiveTab('agents')}
            >
              <Text style={[styles.tabText, activeTab === 'agents' && styles.tabTextActive]}>
                Agents ({dashboard.agents.filter(a => a.status === 'working').length} active)
              </Text>
            </TouchableOpacity>
          </View>

          {/* Progress bar */}
          {dashboard.total > 0 && (
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, {
                width: `${Math.round((dashboard.done / dashboard.total) * 100)}%`
              }]} />
            </View>
          )}

          {/* Panel content */}
          <ScrollView style={styles.panelScroll} showsVerticalScrollIndicator={false}>
            {activeTab === 'tasks'
              ? dashboard.tasks.length > 0
                  ? dashboard.tasks.map(renderTaskRow)
                  : <Text style={styles.emptyText}>Waiting for task plan...</Text>
              : dashboard.agents.length > 0
                  ? dashboard.agents.map(renderAgentCard)
                  : <Text style={styles.emptyText}>Agents not yet assigned.</Text>
            }
          </ScrollView>
        </Animated.View>
      )}

      {/* Messages */}
      {loadingHistory ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color="#e94560" />
          <Text style={styles.loadingText}>Loading messages...</Text>
        </View>
      ) : (
        <FlatList
          ref={flatListRef}
          data={messages}
          renderItem={renderMessage}
          keyExtractor={item => item.id}
          contentContainerStyle={styles.messagesList}
          onContentSizeChange={() => flatListRef.current?.scrollToEnd({ animated: true })}
        />
      )}

      {/* Input bar */}
      <View style={styles.inputBar}>
        <TextInput
          style={styles.input}
          placeholder="Type a message..."
          placeholderTextColor="#666"
          value={inputText}
          onChangeText={setInputText}
          multiline
          maxLength={500}
          editable={!sending}
        />
        <TouchableOpacity
          style={[styles.sendButton, (!inputText.trim() || sending) && styles.sendButtonDisabled]}
          onPress={handleSend}
          disabled={!inputText.trim() || sending}
        >
          {sending
            ? <ActivityIndicator size="small" color="#fff" />
            : <Ionicons name="send" size={20} color={inputText.trim() ? '#fff' : '#666'} />
          }
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container:        { flex: 1, backgroundColor: '#1a1a2e' },
  chatHeader: {
    flexDirection: 'row', alignItems: 'center', padding: 16,
    backgroundColor: '#16213e', borderBottomWidth: 1, borderBottomColor: '#0f3460',
  },
  headerAvatar: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: '#e94560',
    alignItems: 'center', justifyContent: 'center', marginRight: 12,
  },
  headerAvatarText: { color: '#fff', fontWeight: 'bold', fontSize: 16 },
  headerName:    { color: '#eee', fontSize: 17, fontWeight: '600' },
  headerStatus:  { color: '#4ecca3', fontSize: 13, marginTop: 2 },
  onlineDot: {
    width: 10, height: 10, borderRadius: 5, backgroundColor: '#4ecca3', marginLeft: 8,
  },
  stopBtn:       { padding: 6, marginRight: 2 },
  panelToggle:   { flexDirection: 'row', alignItems: 'center', padding: 6, marginRight: 4 },
  panelBadge:    { color: '#4ecca3', fontSize: 11, marginLeft: 4, fontWeight: '700' },

  // Panel
  panel:          { backgroundColor: '#12172b', borderBottomWidth: 1, borderBottomColor: '#0f3460' },
  tabBar:         { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: '#0f3460' },
  tab:            { flex: 1, paddingVertical: 8, alignItems: 'center' },
  tabActive:      { borderBottomWidth: 2, borderBottomColor: '#4ecca3' },
  tabText:        { color: '#666', fontSize: 12, fontWeight: '600' },
  tabTextActive:  { color: '#4ecca3' },
  progressTrack: {
    height: 3, backgroundColor: '#1a1a2e', marginHorizontal: 12, marginTop: 6, borderRadius: 2,
  },
  progressFill:  { height: '100%', backgroundColor: '#4ecca3', borderRadius: 2 },
  panelScroll:   { flex: 1, paddingHorizontal: 12, paddingTop: 6 },
  emptyText:     { color: '#555', fontSize: 12, textAlign: 'center', marginTop: 16 },

  // Task rows
  taskRow:       { flexDirection: 'row', alignItems: 'center', paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: '#1a1a2e' },
  taskIcon:      { fontSize: 14, width: 20, fontWeight: '700' },
  taskFile:      { color: '#ccc', fontSize: 12, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
  taskAssigned:  { color: '#f0a500', fontSize: 10, marginTop: 1 },
  taskRetry:     { color: '#e94560', fontSize: 11 },

  // Agent cards
  agentCard:     { flexDirection: 'row', alignItems: 'center', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: '#1a1a2e' },
  agentDot:      { width: 8, height: 8, borderRadius: 4, marginRight: 10 },
  agentKey:      { color: '#eee', fontSize: 13, fontWeight: '600' },
  agentFile:     { color: '#f0a500', fontSize: 11, marginTop: 1 },
  agentIdle:     { color: '#555', fontSize: 11, marginTop: 1 },
  agentDoneCount:{ color: '#4ecca3', fontSize: 11 },

  // Messages
  messagesList:  { padding: 16, paddingBottom: 8 },
  messageBubbleRow: { flexDirection: 'row', marginBottom: 12, alignItems: 'flex-end' },
  userRow:       { justifyContent: 'flex-end' },
  avatar: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: '#e94560',
    alignItems: 'center', justifyContent: 'center', marginRight: 8,
  },
  avatarText:    { color: '#fff', fontWeight: 'bold', fontSize: 12 },
  messageBubble: { maxWidth: '75%', borderRadius: 16, padding: 12 },
  ceoBubble:     { backgroundColor: '#16213e', borderBottomLeftRadius: 4, borderWidth: 1, borderColor: '#0f3460' },
  userBubble:    { backgroundColor: '#e94560', borderBottomRightRadius: 4 },
  senderName:    { color: '#e94560', fontSize: 12, fontWeight: '700', marginBottom: 4 },
  messageText:   { color: '#ddd', fontSize: 15, lineHeight: 21 },
  userMessageText: { color: '#fff' },
  timeText:      { color: '#666', fontSize: 11, marginTop: 6, textAlign: 'right' },
  userTimeText:  { color: 'rgba(255,255,255,0.7)' },

  loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  loadingText:   { color: '#888', fontSize: 14, marginTop: 12 },

  inputBar: {
    flexDirection: 'row', alignItems: 'flex-end', padding: 12,
    backgroundColor: '#16213e', borderTopWidth: 1, borderTopColor: '#0f3460',
  },
  input: {
    flex: 1, backgroundColor: '#1a1a2e', borderRadius: 20, paddingHorizontal: 16,
    paddingVertical: 10, color: '#eee', fontSize: 15, maxHeight: 100,
    borderWidth: 1, borderColor: '#0f3460',
  },
  sendButton: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: '#e94560',
    alignItems: 'center', justifyContent: 'center', marginLeft: 8,
  },
  sendButtonDisabled: { backgroundColor: '#16213e' },
});
