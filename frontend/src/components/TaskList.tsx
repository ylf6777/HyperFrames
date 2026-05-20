import { useEffect, useState, useCallback } from 'react';
import { listTasks } from '../api';
import type { Task } from '../types';
import { STATUS_LABEL } from '../types';

const PAGE_SIZE = 20;

const STATUS_BADGE: Record<string, string> = {
  pending: 'badge-pending',
  processing: 'badge-processing',
  completed: 'badge-completed',
  failed: 'badge-failed',
  cancelled: 'badge-cancelled',
};

export default function TaskList({ onSelect }: { onSelect?: (taskId: string) => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const res = await listTasks(PAGE_SIZE, offset);
      setTasks(res.tasks);
      setTotal(res.total);
    } catch {
      // 静默失败
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    fetchTasks();
    const timer = setInterval(fetchTasks, 5000);
    return () => clearInterval(timer);
  }, [fetchTasks]);

  const goPrev = () => { if (page > 1) setPage(p => p - 1); };
  const goNext = () => { if (page < totalPages) setPage(p => p + 1); };

  if (loading && tasks.length === 0) return <p className="loading-text">加载中...</p>;

  return (
    <div className="task-list">
      {tasks.length === 0 ? (
        <p className="empty-text">暂无任务记录</p>
      ) : (
        <>
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
          <div className="pagination">
            <span className="pagination-info">共 {total} 条 · 第 {page}/{totalPages} 页</span>
            <div className="pagination-btns">
              <button className="btn btn-secondary" disabled={page <= 1} onClick={goPrev}>上一页</button>
              <button className="btn btn-secondary" disabled={page >= totalPages} onClick={goNext}>下一页</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
