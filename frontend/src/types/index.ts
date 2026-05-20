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

/** 用户信息 */
export interface UserInfo {
  user_id: string;
  account: string;
  nickname: string;
  phone: string;
  email: string;
  member_level: string;
  remaining_points: number;
  remaining_count: number;
  total_recharge: number;
  expire_time: string;
  status: string;
}

/** 登录响应 */
export interface LoginResponse {
  token: string;
  user: UserInfo;
}

/** 应用路由 */
export type AppRoute =
  | { type: 'home' }
  | { type: 'history' }
  | { type: 'task'; taskId: string };

/** 任务状态中文名 */
export const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};
