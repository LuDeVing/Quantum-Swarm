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
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import {
  getProjectMessages,
  sendMessage as sendProjectMessage,
  getGeneralMessages,
  sendGeneralMessage,
} from '../services/api';

const CEO_NAME = 'Alex Morgan';

export default function ChatScreen({ route }) {
  const projectId = route?.params?.projectId || null;
  const projectName = route?.params?.projectName || null;

  const [messages, setMessages] = useState([]);
  const [inputText, setInputText] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const flatListRef = useRef(null);

  useEffect(() => {
    loadMessages();
  }, [projectId]);

  const loadMessages = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const data = projectId
        ? await getProjectMessages(projectId)
        : await getGeneralMessages();
      setMessages(data.messages || []);
    } catch (error) {
      // If backend is not connected yet, show a welcome message
      setMessages([
        {
          id: '1',
          text: projectName
            ? `Welcome! Let's discuss the "${projectName}" project. How can I help?`
            : "Welcome! I'm Alex Morgan, CEO of MyApp. Feel free to reach out with any questions, feedback, or ideas.",
          sender: 'ceo',
          time: '9:00 AM',
        },
      ]);
    } finally {
      setLoadingHistory(false);
    }
  }, [projectId, projectName]);

  const handleSend = async () => {
    if (!inputText.trim() || sending) return;

    const text = inputText.trim();
    const now = new Date();
    let hours = now.getHours();
    const mins = now.getMinutes().toString().padStart(2, '0');
    const ampm = hours >= 12 ? 'PM' : 'AM';
    hours = hours % 12 || 12;
    const timeStr = `${hours}:${mins} ${ampm}`;

    // Optimistically add user message
    const tempUserMsg = {
      id: `temp-${Date.now()}`,
      text,
      sender: 'user',
      time: timeStr,
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setInputText('');
    setSending(true);

    try {
      const data = projectId
        ? await sendProjectMessage(projectId, text)
        : await sendGeneralMessage(text);

      // Replace temp message with server response and add AI reply
      setMessages((prev) => {
        const withoutTemp = prev.filter((m) => m.id !== tempUserMsg.id);
        return [...withoutTemp, data.userMessage, data.aiReply];
      });
    } catch (error) {
      // If backend not connected, show fallback
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          text: 'Sorry, I could not reach the server. Please try again.',
          sender: 'ceo',
          time: timeStr,
        },
      ]);
    } finally {
      setSending(false);
    }
  };

  const renderMessage = ({ item }) => {
    const isUser = item.sender === 'user';
    return (
      <View style={[styles.messageBubbleRow, isUser && styles.userRow]}>
        {!isUser && (
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>AM</Text>
          </View>
        )}
        <View style={[styles.messageBubble, isUser ? styles.userBubble : styles.ceoBubble]}>
          {!isUser && <Text style={styles.senderName}>{CEO_NAME}</Text>}
          <Text style={[styles.messageText, isUser && styles.userMessageText]}>{item.text}</Text>
          <Text style={[styles.timeText, isUser && styles.userTimeText]}>{item.time}</Text>
        </View>
      </View>
    );
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      {/* Chat header */}
      <View style={styles.chatHeader}>
        <View style={styles.headerAvatar}>
          <Text style={styles.headerAvatarText}>AM</Text>
        </View>
        <View>
          <Text style={styles.headerName}>{CEO_NAME}</Text>
          <Text style={styles.headerStatus}>
            {projectName ? `Project: ${projectName}` : 'CEO · Online'}
          </Text>
        </View>
        <View style={styles.onlineDot} />
      </View>

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
          keyExtractor={(item) => item.id}
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
          {sending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Ionicons name="send" size={20} color={inputText.trim() ? '#fff' : '#666'} />
          )}
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1a1a2e',
  },
  chatHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    backgroundColor: '#16213e',
    borderBottomWidth: 1,
    borderBottomColor: '#0f3460',
  },
  headerAvatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  headerAvatarText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 16,
  },
  headerName: {
    color: '#eee',
    fontSize: 17,
    fontWeight: '600',
  },
  headerStatus: {
    color: '#4ecca3',
    fontSize: 13,
    marginTop: 2,
  },
  onlineDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#4ecca3',
    marginLeft: 'auto',
  },
  messagesList: {
    padding: 16,
    paddingBottom: 8,
  },
  messageBubbleRow: {
    flexDirection: 'row',
    marginBottom: 12,
    alignItems: 'flex-end',
  },
  userRow: {
    justifyContent: 'flex-end',
  },
  avatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 8,
  },
  avatarText: {
    color: '#fff',
    fontWeight: 'bold',
    fontSize: 12,
  },
  messageBubble: {
    maxWidth: '75%',
    borderRadius: 16,
    padding: 12,
  },
  ceoBubble: {
    backgroundColor: '#16213e',
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: '#0f3460',
  },
  userBubble: {
    backgroundColor: '#e94560',
    borderBottomRightRadius: 4,
  },
  senderName: {
    color: '#e94560',
    fontSize: 12,
    fontWeight: '700',
    marginBottom: 4,
  },
  messageText: {
    color: '#ddd',
    fontSize: 15,
    lineHeight: 21,
  },
  userMessageText: {
    color: '#fff',
  },
  timeText: {
    color: '#666',
    fontSize: 11,
    marginTop: 6,
    textAlign: 'right',
  },
  userTimeText: {
    color: 'rgba(255,255,255,0.7)',
  },
  inputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: 12,
    backgroundColor: '#16213e',
    borderTopWidth: 1,
    borderTopColor: '#0f3460',
  },
  input: {
    flex: 1,
    backgroundColor: '#1a1a2e',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    color: '#eee',
    fontSize: 15,
    maxHeight: 100,
    borderWidth: 1,
    borderColor: '#0f3460',
  },
  sendButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    marginLeft: 8,
  },
  sendButtonDisabled: {
    backgroundColor: '#16213e',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    color: '#888',
    fontSize: 14,
    marginTop: 12,
  },
});
