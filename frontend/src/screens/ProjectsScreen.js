import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  TextInput,
  Modal,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation } from '@react-navigation/native';
import {
  getProjects,
  createProject as apiCreateProject,
  deleteProject as apiDeleteProject,
} from '../services/api';

export default function ProjectsScreen() {
  const navigation = useNavigation();
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalVisible, setModalVisible] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getProjects();
      setProjects(data.projects || []);
    } catch (error) {
      // Fallback if backend not connected
      setProjects([
        { id: '1', name: 'Website Redesign', status: 'In Progress', date: '2026-04-10', lastMessage: 'Let\'s finalize the homepage layout' },
        { id: '2', name: 'Mobile App v2', status: 'Planning', date: '2026-04-08', lastMessage: 'We need to discuss the new features' },
        { id: '3', name: 'API Integration', status: 'Completed', date: '2026-03-25', lastMessage: 'All endpoints are live and tested' },
      ]);
    } finally {
      setLoading(false);
    }
  }, []);

  const getStatusColor = (status) => {
    switch (status) {
      case 'Completed':
        return '#4ecca3';
      case 'In Progress':
        return '#ffc107';
      case 'Planning':
        return '#e94560';
      default:
        return '#888';
    }
  };

  const addProject = async () => {
    if (!newProjectName.trim()) {
      Alert.alert('Error', 'Please enter a project name');
      return;
    }
    setCreating(true);
    try {
      const data = await apiCreateProject(newProjectName.trim());
      setProjects([data.project, ...projects]);
    } catch (error) {
      // Fallback: add locally
      const newProject = {
        id: Date.now().toString(),
        name: newProjectName.trim(),
        status: 'Planning',
        date: new Date().toISOString().split('T')[0],
      };
      setProjects([newProject, ...projects]);
    } finally {
      setNewProjectName('');
      setModalVisible(false);
      setCreating(false);
    }
  };

  const handleDeleteProject = (id) => {
    Alert.alert('Delete Project', 'Are you sure you want to delete this project?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: async () => {
          try {
            await apiDeleteProject(id);
          } catch (error) {
            // delete locally even if backend fails
          }
          setProjects(projects.filter((p) => p.id !== id));
        },
      },
    ]);
  };

  const openProjectChat = (project) => {
    navigation.navigate('ProjectChat', {
      projectId: project.id,
      projectName: project.name,
    });
  };

  const renderProject = ({ item }) => (
    <TouchableOpacity
      style={styles.projectCard}
      onPress={() => openProjectChat(item)}
      onLongPress={() => handleDeleteProject(item.id)}
    >
      <View style={styles.projectHeader}>
        <View style={styles.projectIcon}>
          <Ionicons name="folder-open" size={24} color="#e94560" />
        </View>
        <View style={styles.projectInfo}>
          <Text style={styles.projectName}>{item.name}</Text>
          <Text style={styles.projectDate}>{item.date}</Text>
        </View>
        <Ionicons name="chatbubble-ellipses-outline" size={20} color="#666" />
      </View>
      {item.lastMessage && (
        <Text style={styles.lastMessage} numberOfLines={1}>
          CEO: {item.lastMessage}
        </Text>
      )}
      <View style={[styles.statusBadge, { backgroundColor: getStatusColor(item.status) + '20' }]}>
        <View style={[styles.statusDot, { backgroundColor: getStatusColor(item.status) }]} />
        <Text style={[styles.statusText, { color: getStatusColor(item.status) }]}>
          {item.status}
        </Text>
      </View>
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>My Projects</Text>
        <Text style={styles.count}>{projects.length} projects</Text>
      </View>

      <FlatList
        data={projects}
        renderItem={renderProject}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        refreshing={loading}
        onRefresh={loadProjects}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Ionicons name="folder-open-outline" size={64} color="#333" />
            <Text style={styles.emptyText}>No projects yet</Text>
            <Text style={styles.emptySubtext}>Tap + to create your first project</Text>
          </View>
        }
      />

      <TouchableOpacity style={styles.fab} onPress={() => setModalVisible(true)}>
        <Ionicons name="add" size={28} color="#fff" />
      </TouchableOpacity>

      {/* Add Project Modal */}
      <Modal visible={modalVisible} transparent animationType="fade">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContent}>
            <Text style={styles.modalTitle}>New Project</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Project name"
              placeholderTextColor="#666"
              value={newProjectName}
              onChangeText={setNewProjectName}
              autoFocus
            />
            <View style={styles.modalButtons}>
              <TouchableOpacity
                style={[styles.modalButton, styles.cancelButton]}
                onPress={() => {
                  setModalVisible(false);
                  setNewProjectName('');
                }}
              >
                <Text style={styles.cancelButtonText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity style={[styles.modalButton, styles.createButton]} onPress={addProject} disabled={creating}>
                {creating ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={styles.createButtonText}>Create</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1a1a2e',
  },
  header: {
    padding: 20,
    paddingTop: 16,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#eee',
  },
  count: {
    fontSize: 14,
    color: '#888',
  },
  list: {
    padding: 16,
    paddingTop: 0,
  },
  projectCard: {
    backgroundColor: '#16213e',
    borderRadius: 16,
    padding: 16,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#0f3460',
  },
  projectHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 12,
  },
  projectIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#1a1a2e',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 12,
  },
  projectInfo: {
    flex: 1,
  },
  projectName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#eee',
    marginBottom: 4,
  },
  projectDate: {
    fontSize: 13,
    color: '#666',
  },
  lastMessage: {
    color: '#888',
    fontSize: 13,
    marginBottom: 10,
    marginLeft: 56,
    fontStyle: 'italic',
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  statusText: {
    fontSize: 13,
    fontWeight: '600',
  },
  emptyContainer: {
    alignItems: 'center',
    marginTop: 80,
  },
  emptyText: {
    color: '#666',
    fontSize: 18,
    marginTop: 16,
  },
  emptySubtext: {
    color: '#444',
    fontSize: 14,
    marginTop: 8,
  },
  fab: {
    position: 'absolute',
    right: 20,
    bottom: 24,
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#e94560',
    alignItems: 'center',
    justifyContent: 'center',
    elevation: 8,
    shadowColor: '#e94560',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.7)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modalContent: {
    backgroundColor: '#16213e',
    borderRadius: 20,
    padding: 24,
    width: '85%',
    borderWidth: 1,
    borderColor: '#0f3460',
  },
  modalTitle: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#eee',
    marginBottom: 16,
  },
  modalInput: {
    backgroundColor: '#1a1a2e',
    borderRadius: 12,
    padding: 16,
    color: '#eee',
    fontSize: 16,
    borderWidth: 1,
    borderColor: '#0f3460',
    marginBottom: 20,
  },
  modalButtons: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 12,
  },
  modalButton: {
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 10,
  },
  cancelButton: {
    backgroundColor: '#1a1a2e',
  },
  cancelButtonText: {
    color: '#888',
    fontSize: 16,
    fontWeight: '600',
  },
  createButton: {
    backgroundColor: '#e94560',
  },
  createButtonText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '600',
  },
});
