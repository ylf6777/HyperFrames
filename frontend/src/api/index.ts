import type { Task, CreateTaskResponse, HealthResponse } from '../types';

const BASE = '/api';

async function handleResponse<T>(resp: Response): Promise<T> {
  const text = await resp.text();
  if (!resp.ok) {
    let msg: string;
    try {
      const err = JSON.parse(text);
      msg = err.detail || err.message || text;
    } catch {
      msg = text || `HTTP ${resp.status}`;
    }
    throw new Error(msg);
  }
  return JSON.parse(text) as T;
}

/** 健康检查 */
export function healthCheck(): Promise<HealthResponse> {
  return fetch(`${BASE}/health`).then(r => handleResponse<HealthResponse>(r));
}

/** 上传文档创建任务 */
export async function createTask(file: File): Promise<CreateTaskResponse> {
  const form = new FormData();
  form.append('file', file);
  return fetch(`${BASE}/tasks`, { method: 'POST', body: form }).then(r =>
    handleResponse<CreateTaskResponse>(r),
  );
}

/** 查询单个任务状态 */
export function getTask(taskId: string): Promise<Task> {
  return fetch(`${BASE}/tasks/${taskId}`).then(r => handleResponse<Task>(r));
}

/** 获取任务历史列表 */
export function listTasks(limit = 20): Promise<Task[]> {
  return fetch(`${BASE}/tasks?limit=${limit}`).then(r => handleResponse<Task[]>(r));
}

/** 取消任务 */
export function cancelTask(taskId: string): Promise<{ task_id: string; status: string }> {
  return fetch(`${BASE}/tasks/${taskId}/cancel`, { method: 'POST' }).then(r =>
    handleResponse(r),
  );
}

/** 获取视频下载 URL */
export function getVideoUrl(taskId: string): string {
  return `${BASE}/videos/${taskId}.mp4`;
}
