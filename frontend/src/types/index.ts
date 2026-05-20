/** 任务状态 */
export type TaskStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled';

/** 任务信息 */
export interface Task {
  task_id: string;
  status: TaskStatus;
  filename: string;
  progress: string;
  error: string;
  created_at: number;
  updated_at: number;
}

/** 创建任务响应 */
export interface CreateTaskResponse {
  task_id: string;
  status: 'pending';
}

/** 健康检查响应 */
export interface HealthResponse {
  status: string;
}

/** 上传状态 */
export type UploadState =
  | { type: 'idle' }
  | { type: 'uploading'; progress: number }
  | { type: 'done'; taskId: string }
  | { type: 'error'; message: string };
