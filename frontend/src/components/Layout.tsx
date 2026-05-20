import type { ReactNode } from 'react';
import type { UserInfo } from '../types';

interface Props {
  children: ReactNode;
  currentPath: string;
  onNavigate: (path: string) => void;
  user: UserInfo;
  onLogout: () => void;
}

export default function Layout({ children, currentPath, onNavigate, user, onLogout }: Props) {
  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <h1 className="app-title" onClick={() => onNavigate('/')}>
            文生视频
          </h1>
          <div className="header-right">
            <nav className="app-nav">
              <button
                className={`nav-btn ${currentPath === '/' ? 'active' : ''}`}
                onClick={() => onNavigate('/')}
              >
                新建任务
              </button>
              <button
                className={`nav-btn ${currentPath === '/history' ? 'active' : ''}`}
                onClick={() => onNavigate('/history')}
              >
                历史记录
              </button>
            </nav>
            <div className="user-info">
              <span className="user-name">{user.nickname}</span>
              <span className="user-level">{user.member_level}</span>
              <button className="logout-btn" onClick={onLogout} title="退出登录">退出</button>
            </div>
          </div>
        </div>
      </header>
      <main className="app-main">
        {children}
      </main>
    </div>
  );
}
