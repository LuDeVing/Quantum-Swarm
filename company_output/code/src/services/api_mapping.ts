/**
 * API Mapping layer ensuring frontend types match the Pydantic schemas defined in backend/schemas.py
 */

export interface TaskDTO {
  id?: number;
  title: string;
  description?: string;
  status: 'todo' | 'in_progress' | 'done';
}

export const API_ROUTES = {
  tasks: '/api/v1/tasks',
  task: (id: number) => `/api/v1/tasks/${id}`,
};

export const mapTaskToDTO = (task: TaskDTO): TaskDTO => ({
  title: task.title,
  description: task.description || '',
  status: task.status || 'todo',
});
