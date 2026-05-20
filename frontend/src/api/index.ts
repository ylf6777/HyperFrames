import type { Task, CreateTaskResponse, HealthResponse, LoginResponse, UserInfo } from '../types';

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
export function listTasks(limit = 20, offset = 0): Promise<{ tasks: Task[]; total: number }> {
  return fetch(`${BASE}/tasks?limit=${limit}&offset=${offset}`).then(r =>
    handleResponse<{ tasks: Task[]; total: number }>(r),
  );
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

// ── 认证 ──────────────────────────────────────────────────

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('token');
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

/** 登录 */
export function login(account: string, password: string): Promise<LoginResponse> {
  return fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, password }),
  }).then(r => handleResponse<LoginResponse>(r));
}

/** 注册（支持手机号和邮箱验证） */
export function register(account: string, password: string, nickname?: string, phone?: string, email?: string, code?: string): Promise<{ success: boolean; user_id: string; account: string }> {
  return fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, password, nickname, phone, email, code }),
  }).then(r => handleResponse(r));
}

/** 发送验证码 */
export function sendCode(phone: string): Promise<{ success: boolean; dev_code?: string }> {
  return fetch(`${BASE}/auth/send-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone }),
  }).then(r => handleResponse(r));
}

/** 验证验证码 */
export function verifyCode(phone: string, code: string): Promise<{ success: boolean; verified: boolean }> {
  return fetch(`${BASE}/auth/verify-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, code }),
  }).then(r => handleResponse(r));
}

/** 发送邮箱激活 */
export function sendActivation(email: string): Promise<{ success: boolean }> {
  return fetch(`${BASE}/auth/send-activation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  }).then(r => handleResponse(r));
}

/** 获取当前用户信息 */
export function getCurrentUser(): Promise<UserInfo> {
  return fetch(`${BASE}/auth/me`, { headers: authHeaders() }).then(r => handleResponse<UserInfo>(r));
}

/** 退出登录 */
export function logout(): Promise<void> {
  return fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    headers: authHeaders(),
  }).then(() => {});
}

/** 忘记密码 — 发送重置验证码 */
export function forgotPasswordSendCode(account: string): Promise<{ success: boolean; dev_code?: string }> {
  return fetch(`${BASE}/auth/forgot-password/send-code`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account }),
  }).then(r => handleResponse(r));
}

/** 忘记密码 — 验证码验证后重置 */
export function forgotPasswordReset(account: string, code: string, newPassword: string): Promise<{ success: boolean; message: string }> {
  return fetch(`${BASE}/auth/forgot-password/reset`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, code, new_password: newPassword }),
  }).then(r => handleResponse(r));
}
