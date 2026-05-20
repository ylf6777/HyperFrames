import { useEffect, useState } from 'react';
import { getCurrentUser } from './api';
import type { UserInfo } from './types';
import Layout from './components/Layout';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import HistoryPage from './pages/HistoryPage';

type Route = '/' | '/history';

export default function App() {
  const [route, setRoute] = useState<Route>('/');
  const [user, setUser] = useState<UserInfo | null>(null);
  const [checking, setChecking] = useState(true);

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
    setRoute('/');
  };

  const navigate = (path: string) => {
    if (path === '/' || path === '/history') {
      setRoute(path as Route);
      window.history.pushState({}, '', path);
    }
  };

  useEffect(() => {
    const onPop = () => {
      const p = window.location.pathname as Route;
      if (p === '/' || p === '/history') setRoute(p);
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
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
    <Layout currentPath={route} onNavigate={navigate} user={user} onLogout={handleLogout}>
      {route === '/' ? <HomePage /> : <HistoryPage />}
    </Layout>
  );
}
