import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginPage from './LoginPage';

const mockLogin = vi.fn();
const mockRegister = vi.fn();
const mockSendCode = vi.fn();
const mockVerifyCode = vi.fn();
const mockSendActivation = vi.fn();
const mockForgotSendCode = vi.fn();
const mockForgotReset = vi.fn();

vi.mock('../api', () => ({
  login: (...args: unknown[]) => mockLogin(...args),
  register: (...args: unknown[]) => mockRegister(...args),
  sendCode: (...args: unknown[]) => mockSendCode(...args),
  verifyCode: (...args: unknown[]) => mockVerifyCode(...args),
  sendActivation: (...args: unknown[]) => mockSendActivation(...args),
  forgotPasswordSendCode: (...args: unknown[]) => mockForgotSendCode(...args),
  forgotPasswordReset: (...args: unknown[]) => mockForgotReset(...args),
}));

const onLogin = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

/* ── 模式切换 ─────────────────────────────────────────── */
describe('模式切换', () => {
  it('默认登录模式', () => {
    render(<LoginPage onLogin={onLogin} />);
    expect(screen.getByText('登录后继续')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('账号')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('密码')).toBeInTheDocument();
  });

  it('切换到注册模式', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    expect(screen.getByText('注册新账号')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('确认密码')).toBeInTheDocument();
  });

  it('切换到忘记密码模式', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('忘记密码'));

    // 重置密码同时出现在副标题和按钮中，用 getAllByText
    const resetTexts = screen.getAllByText('重置密码');
    expect(resetTexts.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('发送重置验证码')).toBeInTheDocument();
  });

  it('忘记密码下可返回登录', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('忘记密码'));
    await user.click(screen.getByText('去登录'));
    expect(screen.getByText('登录后继续')).toBeInTheDocument();
  });
});

/* ── 表单验证 ─────────────────────────────────────────── */
describe('表单验证', () => {
  it('空账号密码显示错误', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByRole('button', { name: '登 录' }));
    expect(screen.getByText('请输入账号和密码')).toBeInTheDocument();
  });

  it('注册时账号只允许字母数字', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('账号'), '中文!@#');
    await user.type(screen.getByPlaceholderText('密码'), '123456');
    await user.type(screen.getByPlaceholderText('确认密码'), '123456');
    await user.click(screen.getByRole('button', { name: '注 册' }));
    expect(screen.getByText('账号只能包含英文字母和数字')).toBeInTheDocument();
  });

  it('注册密码少于 6 位', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('账号'), 'testuser');
    await user.type(screen.getByPlaceholderText('密码'), '123');
    await user.type(screen.getByPlaceholderText('确认密码'), '123');
    await user.click(screen.getByRole('button', { name: '注 册' }));
    expect(screen.getByText('密码至少 6 位')).toBeInTheDocument();
  });

  it('注册密码不一致', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('账号'), 'testuser');
    await user.type(screen.getByPlaceholderText('密码'), '123456');
    await user.type(screen.getByPlaceholderText('确认密码'), '654321');
    await user.click(screen.getByRole('button', { name: '注 册' }));
    expect(screen.getByText('两次密码不一致')).toBeInTheDocument();
  });

  it('手机号格式验证', async () => {
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('账号'), 'testuser');
    await user.type(screen.getByPlaceholderText('密码'), '123456');
    await user.type(screen.getByPlaceholderText('确认密码'), '123456');
    await user.type(screen.getByPlaceholderText('手机号'), '12345');
    await user.click(screen.getByRole('button', { name: '注 册' }));
    expect(screen.getByText(/手机号格式不正确/)).toBeInTheDocument();
  });
});

/* ── 登录流程 ─────────────────────────────────────────── */
describe('登录流程', () => {
  it('成功登录调用 onLogin', async () => {
    mockLogin.mockResolvedValue({ token: 'abc', user: { account: 'test' } });
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.type(screen.getByPlaceholderText('账号'), 'testuser');
    await user.type(screen.getByPlaceholderText('密码'), '123456');
    await user.click(screen.getByRole('button', { name: '登 录' }));
    expect(mockLogin).toHaveBeenCalledWith('testuser', '123456');
    expect(onLogin).toHaveBeenCalledWith({ account: 'test' }, 'abc');
  });

  it('登录失败显示错误', async () => {
    mockLogin.mockRejectedValue(new Error('账号或密码错误'));
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.type(screen.getByPlaceholderText('账号'), 'testuser');
    await user.type(screen.getByPlaceholderText('密码'), 'wrong');
    await user.click(screen.getByRole('button', { name: '登 录' }));
    expect(await screen.findByText('账号或密码错误')).toBeInTheDocument();
  });
});

/* ── 注册流程 ─────────────────────────────────────────── */
describe('注册流程', () => {
  it('成功注册后切换到登录', async () => {
    mockRegister.mockResolvedValue({ success: true, user_id: 'u1', account: 'newuser' });
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('账号'), 'newuser');
    await user.type(screen.getByPlaceholderText('密码'), '123456');
    await user.type(screen.getByPlaceholderText('确认密码'), '123456');
    await user.click(screen.getByRole('button', { name: '注 册' }));
    expect(mockRegister).toHaveBeenCalled();
    expect(await screen.findByText('注册成功！请登录')).toBeInTheDocument();
  });

  it('注册失败显示错误', async () => {
    mockRegister.mockRejectedValue(new Error('账号已存在'));
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('账号'), 'existing');
    await user.type(screen.getByPlaceholderText('密码'), '123456');
    await user.type(screen.getByPlaceholderText('确认密码'), '123456');
    await user.click(screen.getByRole('button', { name: '注 册' }));
    expect(await screen.findByText('账号已存在')).toBeInTheDocument();
  });
});

/* ── 验证码 ────────────────────────────────────────────── */
describe('验证码', () => {
  it('发送验证码', async () => {
    mockSendCode.mockResolvedValue({ success: true, dev_code: '123456' });
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('手机号'), '13800138000');
    await user.click(screen.getByText('获取验证码'));
    expect(mockSendCode).toHaveBeenCalledWith('13800138000');
    expect(await screen.findByText(/验证码: 123456/)).toBeInTheDocument();
  });

  it('发送验证码失败', async () => {
    mockSendCode.mockRejectedValue(new Error('发送过于频繁'));
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('手机号'), '13800138000');
    await user.click(screen.getByText('获取验证码'));
    expect(await screen.findByText('发送过于频繁')).toBeInTheDocument();
  });
});

/* ── 忘记密码 ─────────────────────────────────────────── */
describe('忘记密码', () => {
  it('发送重置验证码', async () => {
    mockForgotSendCode.mockResolvedValue({ success: true, dev_code: '654321' });
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('忘记密码'));
    await user.type(screen.getByPlaceholderText('账号'), 'lostuser');
    await user.click(screen.getByText('发送重置验证码'));
    expect(mockForgotSendCode).toHaveBeenCalledWith('lostuser');
    expect(await screen.findByText(/验证码: 654321/)).toBeInTheDocument();
  });

  it('重置密码成功', async () => {
    mockForgotSendCode.mockResolvedValue({ success: true, dev_code: '654321' });
    mockForgotReset.mockResolvedValue({ success: true, message: 'ok' });
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('忘记密码'));
    await user.type(screen.getByPlaceholderText('账号'), 'lostuser');
    await user.click(screen.getByText('发送重置验证码'));

    expect(await screen.findByText(/验证码: 654321/)).toBeInTheDocument();
    await user.type(screen.getAllByPlaceholderText('输入验证码')[0], '654321');
    await user.type(screen.getByPlaceholderText('新密码（至少 6 位）'), 'newpass123');
    await user.type(screen.getByPlaceholderText('确认新密码'), 'newpass123');
    await user.click(screen.getByRole('button', { name: '重置密码' }));

    expect(mockForgotReset).toHaveBeenCalledWith('lostuser', '654321', 'newpass123');
  });
});

/* ── 发送激活邮件 ──────────────────────────────────────── */
describe('激活邮件', () => {
  it('发送激活邮件', async () => {
    mockSendActivation.mockResolvedValue({ success: true });
    const user = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await user.click(screen.getByText('注册'));
    await user.type(screen.getByPlaceholderText('邮箱（可选）'), 'a@b.com');
    await user.click(screen.getByText('激活邮箱'));
    expect(mockSendActivation).toHaveBeenCalledWith('a@b.com');
  });
});
