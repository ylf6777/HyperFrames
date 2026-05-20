import TaskProgress from '../components/TaskProgress';
import type { AppRoute } from '../types';

interface Props {
  taskId: string;
  activeTasks: Array<{ taskId: string; filename: string }>;
  onNavigate: (route: AppRoute) => void;
  removeActiveTask: (taskId: string) => void;
}

export default function TaskView({ taskId, activeTasks, onNavigate, removeActiveTask }: Props) {
  const handleCancel = () => {
    removeActiveTask(taskId);
    onNavigate({ type: 'home' });
  };

  return (
    <div className="page-task">
      <div className="task-tabs" data-testid="task-tabs">
        {activeTasks.map(t => (
          <button
            key={t.taskId}
            className={`task-tab ${t.taskId === taskId ? 'active' : ''}`}
            onClick={() => onNavigate({ type: 'task', taskId: t.taskId })}
          >
            {t.filename}
          </button>
        ))}
        <button
          className="task-tab task-tab-new"
          onClick={() => onNavigate({ type: 'home' })}
        >
          + 新建
        </button>
      </div>
      <TaskProgress taskId={taskId} onCancel={handleCancel} />
    </div>
  );
}
