import type { ReactNode } from 'react';

interface Props {
  children: ReactNode;
  currentPath: string;
  onNavigate: (path: string) => void;
}

export default function Layout({ children, currentPath, onNavigate }: Props) {
  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <h1 className="app-title" onClick={() => onNavigate('/')}>
            文生视频
          </h1>
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
        </div>
      </header>
      <main className="app-main">
        {children}
      </main>
    </div>
  );
}
