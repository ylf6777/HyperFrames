import { useState, type FormEvent } from 'react';
import { login as apiLogin, register as apiRegister, sendCode, verifyCode, sendActivation } from '../api';
import type { UserInfo } from '../types';

interface Props {
  onLogin: (user: UserInfo, token: string) => void;
}

export default function LoginPage({ onLogin }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [nickname, setNickname] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false);
  const [codeCountdown, setCodeCountdown] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const switchMode = () => {
    setMode(m => (m === 'login' ? 'register' : 'login'));
    setError('');
    setSuccessMsg('');
  };

  const startCountdown = () => {
    setCodeCountdown(60);
    const timer = setInterval(() => {
      setCodeCountdown(c => {
        if (c <= 1) { clearInterval(timer); return 0; }
        return c - 1;
      });
    }, 1000);
  };

  const validateAccount = (v: string) => /^[a-zA-Z0-9]+$/.test(v);
  const validatePhone = (v: string) => /^1\d{10}$/.test(v);

  const handleSendCode = async () => {
    if (!phone) { setError('请先填写手机号'); return; }
    if (!validatePhone(phone)) { setError('手机号格式不正确（11 位，以 1 开头）'); return; }
    setError('');
    try {
      const res = await sendCode(phone);
      setCodeSent(true);
      startCountdown();
      if ((res as any).dev_code) {
        setSuccessMsg(`验证码: ${(res as any).dev_code}（开发模式）`);
      } else {
        setSuccessMsg('验证码已发送，请查看手机');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送失败');
    }
  };

  const handleSendActivation = async () => {
    if (!email) { setError('请先填写邮箱'); return; }
    setError('');
    try {
      await sendActivation(email);
      setSuccessMsg('激活邮件已发送，请查看邮箱（开发模式查看服务端控制台）');
    } catch (err) {
      setError(err instanceof Error ? err.message : '发送失败');
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (!account.trim() || !password) {
      setError('请输入账号和密码');
      return;
    }

    if (mode === 'register') {
      if (!validateAccount(account)) {
        setError('账号只能包含英文字母和数字');
        return;
      }
      if (password.length < 6) {
        setError('密码至少 6 位');
        return;
      }
      if (password !== confirmPwd) {
        setError('两次密码不一致');
        return;
      }
      if (phone && !validatePhone(phone)) {
        setError('手机号格式不正确（11 位，以 1 开头）');
        return;
      }
    }

    setLoading(true);
    try {
      if (mode === 'register') {
        await apiRegister(account, password, nickname || account, phone, email, code);
        setSuccessMsg('注册成功！请登录');
        setMode('login');
        setLoading(false);
        return;
      }

      const res = await apiLogin(account, password);
      onLogin(res.user, res.token);
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-icon">🎬</div>
        <h2>文生视频</h2>
        <p className="login-subtitle">{mode === 'login' ? '登录后继续' : '注册新账号'}</p>

        <form onSubmit={handleSubmit} className="login-form">
          <input
            className="login-input"
            type="text"
            placeholder="账号"
            value={account}
            onChange={e => setAccount(e.target.value)}
            autoFocus
          />
          <input
            className="login-input"
            type="password"
            placeholder="密码"
            value={password}
            onChange={e => setPassword(e.target.value)}
          />

          {mode === 'register' && (
            <>
              <input
                className="login-input"
                type="password"
                placeholder="确认密码"
                value={confirmPwd}
                onChange={e => setConfirmPwd(e.target.value)}
              />
              <input
                className="login-input"
                type="text"
                placeholder="昵称（可选）"
                value={nickname}
                onChange={e => setNickname(e.target.value)}
              />

              <div className="code-row">
                <input
                  className="login-input code-input"
                  type="text"
                  placeholder="手机号"
                  value={phone}
                  onChange={e => setPhone(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-secondary code-btn"
                  onClick={handleSendCode}
                  disabled={codeCountdown > 0}
                >
                  {codeCountdown > 0 ? `${codeCountdown}s` : '获取验证码'}
                </button>
              </div>
              {codeSent && (
                <input
                  className="login-input"
                  type="text"
                  placeholder="输入验证码"
                  value={code}
                  onChange={e => setCode(e.target.value)}
                />
              )}

              <div className="code-row">
                <input
                  className="login-input code-input"
                  type="email"
                  placeholder="邮箱（可选）"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                />
                <button
                  type="button"
                  className="btn btn-secondary code-btn"
                  onClick={handleSendActivation}
                >
                  激活邮箱
                </button>
              </div>
            </>
          )}

          {error && <p className="login-error">{error}</p>}
          {successMsg && <p className="login-success">{successMsg}</p>}

          <button type="submit" className="btn btn-primary login-btn" disabled={loading}>
            {loading ? '处理中...' : mode === 'login' ? '登 录' : '注 册'}
          </button>
        </form>

        <p className="login-switch">
          {mode === 'login' ? (
            <>没有账号？<button className="link-btn" onClick={switchMode}>注册</button></>
          ) : (
            <>已有账号？<button className="link-btn" onClick={switchMode}>去登录</button></>
          )}
        </p>
      </div>
    </div>
  );
}
