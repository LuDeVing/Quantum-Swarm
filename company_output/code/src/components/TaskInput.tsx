import React, { useState } from 'react';
import tokens from '../tokens.json';

// Styled components using tokens
const styles = {
  container: {
    display: 'flex',
    gap: tokens.spacing.sm,
    padding: tokens.spacing.md,
  },
  input: {
    padding: tokens.spacing.sm,
    border: tokens.border.input,
    borderRadius: tokens.spacing.xs,
    fontFamily: tokens.typography['family-body'],
  },
  button: {
    padding: `${tokens.spacing.sm} ${tokens.spacing.md}`,
    backgroundColor: tokens.colors['brand-primary'],
    color: tokens.colors['bg-primary'],
    border: 'none',
    borderRadius: tokens.spacing.xs,
    cursor: 'pointer',
    fontWeight: tokens.typography['weight-bold'],
    transition: `background-color ${tokens.motion['duration-fast']} ${tokens.motion['transition-ease']}`
  }
};

interface TaskInputProps {
  onSubmit: (title: string) => void;
  isSubmitting?: boolean;
}

export const TaskInput: React.FC<TaskInputProps> = ({ onSubmit, isSubmitting = false }) => {
  const [value, setValue] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (trimmed.length >= 1 && trimmed.length <= 100) {
      onSubmit(trimmed);
      setValue('');
    }
  };

  return (
    <form style={styles.container} onSubmit={handleSubmit}>
      <input
        style={styles.input}
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={isSubmitting}
        placeholder="Add a new task..."
        maxLength={100}
      />
      <button style={styles.button} type="submit" disabled={isSubmitting || value.trim().length < 1}>
        Add
      </button>
    </form>
  );
};
