import { useEffect, useState, useCallback } from 'react';
import { getCurrentUser } from './api';
import type { UserInfo, AppRoute } from './types';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import HistoryPage from './pages/HistoryPage';
import TaskView from './pages/TaskView';

/** 解析 location.pathname 为 AppRoute */
function parsePath(path: string): AppRoute {
  if (path === '/history') return { type: 'history' };
  const m = path.match(/^\/task\/(.+)$/);
  if (m) return { type: 'task', taskId: decodeURIComponent(m[1]) };
  return { type: 'home' };
}

export default function App() {
  const [route, setRoute] = useState<AppRoute>(() => parsePath(window.location.pathname));
  const [user, setUser] = useState<UserInfo | null>(null);
  const [checking, setChecking] = useState(true);
  const [activeTasks, setActiveTasks] = useState<Array<{ taskId: string; filename: string }>>([]);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      setChecking(false);
      return;
    }
    getCurrentUser()
      .then(u => setUser(u))
      .catch(() => localStorage.removeItem('token'))
      .finally(() => setChecking(false));
  }, []);

  const handleLogin = (u: UserInfo, token: string) => {
    localStorage.setItem('token', token);
    setUser(u);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setUser(null);
    setRoute({ type: 'home' });
  };

  const navigate = useCallback((r: AppRoute) => {
    setRoute(r);
    const path = r.type === 'home' ? '/' : r.type === 'history' ? '/history' : `/task/${encodeURIComponent(r.taskId)}`;
    window.history.pushState({}, '', path);
  }, []);

  useEffect(() => {
    const onPop = () => {
      setRoute(parsePath(window.location.pathname));
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const addActiveTask = useCallback((taskId: string, filename: string) => {
    setActiveTasks(prev => {
      if (prev.some(t => t.taskId === taskId)) return prev;
      return [...prev, { taskId, filename }];
    });
  }, []);

  const removeActiveTask = useCallback((taskId: string) => {
    setActiveTasks(prev => prev.filter(t => t.taskId !== taskId));
  }, []);

  if (checking) {
    return (
      <div className="login-loading">
        <div className="spinner" />
        <p>加载中...</p>
      </div>
    );
  }

  if (!user) {
    return <LoginPage onLogin={handleLogin} />;
  }

  return (
    <Layout currentRoute={route} onNavigate={navigate} user={user} onLogout={handleLogout}>
      {route.type === 'home' && (
        <HomePage
          onNavigate={navigate}
          activeTasks={activeTasks}
          addActiveTask={addActiveTask}
        />
      )}
      {route.type === 'history' && (
        <HistoryPage onNavigate={navigate} />
      )}
      {route.type === 'task' && (
        <TaskView
          taskId={route.taskId}
          activeTasks={activeTasks}
          onNavigate={navigate}
          removeActiveTask={removeActiveTask}
        />
      )}
    </Layout>
  );
}
