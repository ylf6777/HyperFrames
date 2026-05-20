import { useEffect, useState } from 'react';
import { listTasks } from '../api';
import type { Task } from '../types';

const STATUS_BADGE: Record<string, string> = {
  pending: 'badge-pending',
  processing: 'badge-processing',
  completed: 'badge-completed',
  failed: 'badge-failed',
  cancelled: 'badge-cancelled',
};

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  processing: '处理中',
  completed: '完成',
  failed: '失败',
  cancelled: '已取消',
};

export default function TaskList({ onSelect }: { onSelect?: (taskId: string) => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchTasks = async () => {
    try {
      setTasks(await listTasks(20));
    } catch {
      // 静默失败
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
    const timer = setInterval(fetchTasks, 5000);
    return () => clearInterval(timer);
  }, []);

  if (loading) return <p className="loading-text">加载中...</p>;
  if (tasks.length === 0) return <p className="empty-text">暂无任务记录</p>;

  return (
    <div className="task-list">
      {tasks.map(t => (
        <div
          key={t.task_id}
          className="task-item"
          onClick={() => onSelect?.(t.task_id)}
        >
          <div className="task-item-left">
            <span className={`badge ${STATUS_BADGE[t.status]}`}>{STATUS_LABEL[t.status]}</span>
            <span className="task-filename">{t.filename}</span>
          </div>
          <div className="task-item-right">
            <span className="task-time">{new Date(t.created_at * 1000).toLocaleString()}</span>
            <span className="task-arrow">→</span>
          </div>
        </div>
      ))}
    </div>
  );
}
