import { useState } from 'react';
import Layout from './components/Layout';
import HomePage from './pages/HomePage';
import HistoryPage from './pages/HistoryPage';

type Route = '/' | '/history';

export default function App() {
  const [route, setRoute] = useState<Route>('/');

  const navigate = (path: string) => {
    if (path === '/' || path === '/history') {
      setRoute(path as Route);
      window.history.pushState({}, '', path);
    }
  };

  window.addEventListener('popstate', () => {
    const p = window.location.pathname as Route;
    if (p === '/' || p === '/history') setRoute(p);
  });

  return (
    <Layout currentPath={route} onNavigate={navigate}>
      {route === '/' ? <HomePage /> : <HistoryPage />}
    </Layout>
  );
}
