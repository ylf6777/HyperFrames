import TaskList from '../components/TaskList';
import type { AppRoute } from '../types';

interface Props {
  onNavigate: (route: AppRoute) => void;
}

export default function HistoryPage({ onNavigate }: Props) {
  return (
    <div className="page-history">
      <h2>历史记录</h2>
      <TaskList onSelect={(taskId) => onNavigate({ type: 'task', taskId })} />
    </div>
  );
}
