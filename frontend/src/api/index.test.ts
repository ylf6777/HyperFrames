import { describe, it, expect, vi, beforeEach } from 'vitest';

/* ── mock fetch ──────────────────────────────────────── */
function mockFetch(response: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    text: () => Promise.resolve(JSON.stringify(response)),
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

/* ── 测试入口：导入所有 API 函数 ──────────────────────── */
import {
  healthCheck, createTask, getTask, listTasks, cancelTask,
  login, register, sendCode, verifyCode, sendActivation,
  getCurrentUser, logout,
  forgotPasswordSendCode, forgotPasswordReset,
} from './index';

describe('healthCheck', () => {
  it('返回健康检查结果', async () => {
    globalThis.fetch = mockFetch({ status: 'ok' });
    const res = await healthCheck();
    expect(res).toEqual({ status: 'ok' });
  });
});

describe('createTask', () => {
  it('POST /api/tasks 上传文件', async () => {
    globalThis.fetch = mockFetch({ task_id: 'abc', status: 'pending' });
    const file = new File(['dummy'], 'test.docx', { type: 'application/octet-stream' });
    const res = await createTask(file);
    expect(res.task_id).toBe('abc');
    expect(fetch).toHaveBeenCalledWith('/api/tasks', expect.objectContaining({ method: 'POST' }));
  });
});

describe('getTask', () => {
  it('GET /api/tasks/{id}', async () => {
    globalThis.fetch = mockFetch({ task_id: 't1', status: 'pending', filename: 'a.docx' });
    const res = await getTask('t1');
    expect(res.task_id).toBe('t1');
    expect(fetch).toHaveBeenCalledWith('/api/tasks/t1');
  });
});

describe('listTasks', () => {
  it('传 limit/offset 参数', async () => {
    globalThis.fetch = mockFetch({ tasks: [], total: 0 });
    await listTasks(10, 5);
    expect(fetch).toHaveBeenCalledWith('/api/tasks?limit=10&offset=5');
  });
});

describe('cancelTask', () => {
  it('POST /api/tasks/{id}/cancel', async () => {
    globalThis.fetch = mockFetch({ task_id: 't1', status: 'cancelled' });
    const res = await cancelTask('t1');
    expect(res.status).toBe('cancelled');
    expect(fetch).toHaveBeenCalledWith('/api/tasks/t1/cancel', expect.objectContaining({ method: 'POST' }));
  });
});

describe('login', () => {
  it('POST /api/auth/login 返回 token', async () => {
    globalThis.fetch = mockFetch({ token: 'xyz', user: { account: 'test' } });
    const res = await login('test', 'pass');
    expect(res.token).toBe('xyz');
  });

  it('网络错误抛出 Error', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
    await expect(login('test', 'pass')).rejects.toThrow('Network error');
  });

  it('HTTP 422 抛出后端 detail', async () => {
    globalThis.fetch = mockFetch({ detail: '账号或密码错误' }, 422);
    await expect(login('test', 'wrong')).rejects.toThrow('账号或密码错误');
  });
});

describe('register', () => {
  it('传递所有字段', async () => {
    globalThis.fetch = mockFetch({ success: true, user_id: 'u1', account: 'newuser' });
    const res = await register('newuser', '123456', 'nick', '13800138000', 'a@b.com', '888888');
    expect(res.success).toBe(true);
    expect(fetch).toHaveBeenCalledWith('/api/auth/register', expect.objectContaining({
      method: 'POST',
      body: expect.stringContaining('"account":"newuser"'),
    }));
  });
});

describe('sendCode / verifyCode', () => {
  it('sendCode POST 手机号', async () => {
    globalThis.fetch = mockFetch({ success: true, dev_code: '123456' });
    const res = await sendCode('13800138000');
    expect(res.dev_code).toBe('123456');
  });

  it('verifyCode POST 验证码', async () => {
    globalThis.fetch = mockFetch({ success: true, verified: true });
    const res = await verifyCode('13800138000', '123456');
    expect(res.verified).toBe(true);
  });
});

describe('sendActivation', () => {
  it('POST 邮箱', async () => {
    globalThis.fetch = mockFetch({ success: true });
    const res = await sendActivation('a@b.com');
    expect(res.success).toBe(true);
  });
});

describe('getCurrentUser', () => {
  it('带 Bearer token 请求', async () => {
    localStorage.setItem('token', 'my_token');
    globalThis.fetch = mockFetch({ account: 'test' });
    await getCurrentUser();
    const call = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(call[1].headers.Authorization).toBe('Bearer my_token');
  });
});

describe('logout', () => {
  it('POST 带 token', async () => {
    localStorage.setItem('token', 'my_token');
    globalThis.fetch = mockFetch(null);
    await logout();
    expect(fetch).toHaveBeenCalledWith('/api/auth/logout', expect.objectContaining({ method: 'POST' }));
  });
});

describe('forgotPassword', () => {
  it('sendCode', async () => {
    globalThis.fetch = mockFetch({ success: true, dev_code: '654321' });
    const res = await forgotPasswordSendCode('testuser');
    expect(res.dev_code).toBe('654321');
  });

  it('reset', async () => {
    globalThis.fetch = mockFetch({ success: true, message: 'ok' });
    const res = await forgotPasswordReset('testuser', '654321', 'newpass');
    expect(res.success).toBe(true);
    expect(fetch).toHaveBeenCalledWith('/api/auth/forgot-password/reset', expect.objectContaining({
      body: expect.stringContaining('"new_password":"newpass"'),
    }));
  });
});

describe('handleResponse error handling', () => {
  it('不能解析 JSON 时回退到 text', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      text: () => Promise.resolve('Bad Gateway'),
    });
    await expect(healthCheck()).rejects.toThrow('Bad Gateway');
  });

  it('空响应体回退到 HTTP 状态码', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve(''),
    });
    await expect(healthCheck()).rejects.toThrow('HTTP 500');
  });
});
