import React from 'react';
import { Button } from '../atoms/Button';

interface Task {
  id: string;
  title: string;
}

export const TaskItem: React.FC<{ task: Task; onDelete: (id: string) => void }> = ({ task, onDelete }) => (
  <div style={{ border: '1px solid #ccc', margin: '8px', padding: '8px' }}>
    <span>{task.title}</span>
    <Button label="Delete" onClick={() => onDelete(task.id)} variant="secondary" />
  </div>
);
