import React, { useState } from 'react';
import './TaskInput.css';

interface TaskInputProps {
  onSubmit: (t: string) => void;
  isSubmitting?: boolean;
}

export const TaskInput: React.FC<TaskInputProps> = ({ onSubmit, isSubmitting = false }) => {
  const [value, setValue] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim()) {
      onSubmit(value);
      setValue('');
    }
  };

  return (
    <form className="task-input" onSubmit={handleSubmit}>
      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={isSubmitting}
        placeholder="Add a new task..."
      />
      <button type="submit" disabled={isSubmitting || !value.trim()}>
        Add
      </button>
    </form>
  );
};
