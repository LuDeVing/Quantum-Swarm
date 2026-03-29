export interface Task {
  id: string;
  title: string;
  status: 'PENDING' | 'COMPLETED';
}

export type TaskAction = 'ADD' | 'UPDATE' | 'DELETE';
export type Request = {
  id: string;
  action: TaskAction;
  data: any;
  sequence: number;
};
