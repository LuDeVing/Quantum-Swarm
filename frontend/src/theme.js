export const colors = {
  bg: '#071019',
  surface: '#0b1621',
  surfaceAlt: '#0f1c28',
  surfaceRaised: '#132230',
  border: '#223342',
  borderStrong: '#314657',
  text: '#f2f6f8',
  textMuted: '#91a3b3',
  textDim: '#607487',
  primary: '#4f8cff',
  primarySoft: '#142b4c',
  success: '#59d38c',
  warning: '#f4aa3b',
  danger: '#ff5d67',
  violet: '#a675ed',
};

export const type = {
  mono: 'monospace',
};

export const radii = {
  sm: 6,
  md: 10,
  lg: 14,
};

export const statusColor = (status) => {
  const normalized = String(status || '').toLowerCase();
  if (normalized.includes('complete') || normalized === 'done' || normalized === 'ready') return colors.success;
  if (normalized.includes('progress') || normalized === 'working' || normalized === 'building') return colors.primary;
  if (normalized.includes('fail') || normalized.includes('block') || normalized.includes('stop')) return colors.danger;
  if (normalized.includes('review') || normalized.includes('wait')) return colors.warning;
  return colors.textDim;
};

export const taskColumn = (status) => {
  if (status === 'completed') return 'Done';
  if (status === 'in_progress') return 'Building';
  if (status === 'failed' || status === 'blocked' || status === 'waiting') return 'Review';
  return 'Planning';
};
