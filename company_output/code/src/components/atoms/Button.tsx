import React from 'react';

interface ButtonProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
}

export const Button: React.FC<ButtonProps> = ({ label, onClick, variant = 'primary' }) => {
  const style = {
    padding: '8px 16px',
    backgroundColor: variant === 'primary' ? '#0070f3' : '#e0e0e0',
    color: variant === 'primary' ? 'white' : 'black',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer'
  };

  return <button style={style} onClick={onClick}>{label}</button>;
};
