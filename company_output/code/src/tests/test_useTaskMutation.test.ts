import { renderHook, act } from '@testing-library/react';
import { useTaskMutation } from './useTaskMutation';
import { useTaskStore } from '../store/taskStore';

describe('useTaskMutation', () => {
  it('should optimistically add a task', async () => {
    const { result } = renderHook(() => useTaskMutation());
    
    await act(async () => {
      await result.current.mutate('add', { title: 'New Task' });
    });

    const tasks = useTaskStore.getState().tasks;
    expect(tasks.length).toBe(1);
    expect(tasks[0].title).toBe('New Task');
  });
});
