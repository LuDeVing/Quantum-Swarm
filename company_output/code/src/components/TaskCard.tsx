import React from 'react';
import './TaskCard.css';

interface Task {
  id: string;
  title: string;
  status: 'PENDING' | 'COMPLETED';
}

interface TaskCardProps {
  task: Task;
  onToggle: (id: string) => void;
}

export const TaskCard: React.FC<TaskCardProps> = ({ task, onToggle }) => {
  return (
    <div className={`task-card ${task.status.toLowerCase()}`}>
      <span className="task-title">{task.title}</span>
      <button 
        onClick={() => onToggle(task.id)}
        className="toggle-button"
      >
        {task.status === 'PENDING' ? 'Complete' : 'Reopen'}
      </button>
    </div>
  );
};
