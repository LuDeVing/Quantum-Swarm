import { useState, useCallback } from 'react';
import { requestQueue } from '../services/requestQueue';
import { useTaskStore } from '../store/taskStore';

export function useTaskMutation() {
  const [isSyncing, setIsSyncing] = useState(false);
  const { addTask, updateTask, removeTask } = useTaskStore();

  const mutate = useCallback(async (action: 'add' | 'update' | 'delete', data: any) => {
    // 1. Optimistic update
    const tempId = Date.now().toString();
    const task = { ...data, id: data.id || tempId, status: 'pending' };
    
    if (action === 'add') addTask(task);
    else if (action === 'update') updateTask(task);
    else if (action === 'delete') removeTask(data.id);

    // 2. Queue for persistence
    setIsSyncing(true);
    try {
      await requestQueue.add({ action, data: task });
      // On success, we might want to mark as synced in state if we had a syncing status
    } catch (error) {
      console.error('Failed to sync task:', error);
      // Handle rollback if necessary
    } finally {
      setIsSyncing(false);
    }
  }, [addTask, updateTask, removeTask]);

  return { mutate, isSyncing };
}
