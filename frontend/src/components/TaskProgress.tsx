import { useEffect, useState } from 'react';
import { getTask, getVideoUrl, cancelTask } from '../api';
import type { Task } from '../types';

interface Props {
  taskId: string;
  onCancel?: () => void;
}

const STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
};

const STATUS_ICONS: Record<string, string> = {
  pending: '⏳',
  processing: '⚙️',
  completed: '✅',
  failed: '❌',
  cancelled: '🛑',
};

export default function TaskProgress({ taskId, onCancel }: Props) {
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let elapsedTimer: ReturnType<typeof setInterval>;

    const poll = async () => {
      try {
        const t = await getTask(taskId);
        if (!active) return;
        setTask(t);
        if (t.status === 'cancelled') { onCancel?.(); return; }
        if (t.status === 'completed' || t.status === 'failed') return;
        timer = setTimeout(poll, 2000);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : '查询失败');
        timer = setTimeout(poll, 3000);
      }
    };

    // 已等待计时器
    elapsedTimer = setInterval(() => {
      setElapsed(e => e + 1);
    }, 1000);

    poll();
    return () => {
      active = false;
      clearTimeout(timer);
      clearInterval(elapsedTimer);
    };
  }, [taskId]);

  const handleCancelClick = () => {
    setShowConfirm(true);
  };

  const handleConfirmCancel = async () => {
    setShowConfirm(false);
    if (cancelling) return;
    setCancelling(true);
    try {
      await cancelTask(taskId);
      onCancel?.();
    } catch {
      setCancelling(false);
    }
  };

  const handleDismissConfirm = () => {
    setShowConfirm(false);
  };

  function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return m > 0 ? `${m}分${s}秒` : `${s}秒`;
  }

  if (error) {
    return <div className="status-card error"><p>❌ {error}</p></div>;
  }

  if (!task) {
    return (
      <div className="status-card loading">
        <div className="spinner" />
        <p>连接服务器...</p>
      </div>
    );
  }

  const isFinal = task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled';

  return (
    <div className={`status-card status-${task.status}`} data-testid="status-card">
      <div className="status-header">
        <span className="status-icon">{STATUS_ICONS[task.status]}</span>
        <span className="status-label">{STATUS_LABELS[task.status]}</span>
      </div>

      {task.status === 'cancelled' && (
        <p className="progress-text" style={{ color: '#991b1b' }}>任务已取消</p>
      )}

      {task.status !== 'cancelled' && !isFinal && (
        <div className="progress-bar">
          <div className="progress-fill indeterminate" />
        </div>
      )}

      {task.status !== 'cancelled' && (
        <p className="progress-text">{task.progress || STATUS_LABELS[task.status]}</p>
      )}

      {task.status !== 'cancelled' && !isFinal && elapsed > 3 && (
        <p className="elapsed-text">已等待 {formatElapsed(elapsed)}</p>
      )}

      <div className="status-meta">
        <span>文件: {task.filename}</span>
        <span>ID: {task.task_id.slice(0, 8)}...</span>
      </div>

      {!isFinal && (
        <div className="status-actions">
          {showConfirm ? (
            <div className="confirm-cancel">
              <p className="confirm-cancel-text">确定要取消这个任务吗？</p>
              <div className="confirm-cancel-actions">
                <button onClick={handleConfirmCancel} className="btn" style={{ background: '#dc2626', color: '#fff', border: 'none' }}>
                  确定取消
                </button>
                <button onClick={handleDismissConfirm} className="btn btn-secondary">
                  我再想想
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={handleCancelClick}
              disabled={cancelling}
              className="btn"
              style={{
                background: cancelling ? '#e5e7eb' : '#fee2e2',
                color: cancelling ? '#9ca3af' : '#dc2626',
                border: 'none',
                cursor: cancelling ? 'not-allowed' : 'pointer',
              }}
            >
              {cancelling ? '取消中...' : '取消任务'}
            </button>
          )}
        </div>
      )}

      {task.status === 'completed' && (
        <div className="status-actions">
          <video src={getVideoUrl(taskId)} controls className="video-preview" />
          <a href={getVideoUrl(taskId)} download className="btn btn-primary" target="_blank" rel="noopener">
            下载视频
          </a>
        </div>
      )}

      {task.status === 'failed' && (
        <div className="status-error">
          <p>错误: {task.error || '生成失败，请查看服务端日志'}</p>
          <button onClick={() => onCancel?.()} className="btn btn-primary" style={{ marginTop: '12px' }}>
            重新上传
          </button>
        </div>
      )}
    </div>
  );
}
