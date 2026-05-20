import type { ReactNode } from 'react';
import type { UserInfo, AppRoute } from '../types';

interface Props {
  children: ReactNode;
  currentRoute: AppRoute;
  onNavigate: (route: AppRoute) => void;
  user: UserInfo;
  onLogout: () => void;
}

export default function Layout({ children, currentRoute, onNavigate, user, onLogout }: Props) {
  const navToHome = () => onNavigate({ type: 'home' });
  const navToHistory = () => onNavigate({ type: 'history' });

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <h1 className="app-title" onClick={navToHome}>
            文生视频
          </h1>
          <div className="header-right">
            <nav className="app-nav">
              <button
                className={`nav-btn ${currentRoute.type === 'home' ? 'active' : ''}`}
                onClick={navToHome}
              >
                新建任务
              </button>
              <button
                className={`nav-btn ${currentRoute.type === 'history' ? 'active' : ''}`}
                onClick={navToHistory}
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
