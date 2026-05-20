import FileUpload from '../components/FileUpload';
import type { AppRoute } from '../types';

interface Props {
  onNavigate: (route: AppRoute) => void;
  activeTasks: Array<{ taskId: string; filename: string }>;
  addActiveTask: (taskId: string, filename: string) => void;
}

export default function HomePage({ onNavigate, activeTasks, addActiveTask }: Props) {
  const handleSuccess = (taskId: string, filename: string) => {
    addActiveTask(taskId, filename);
    onNavigate({ type: 'task', taskId });
  };

  const goToLatestTask = () => {
    if (activeTasks.length > 0) {
      onNavigate({ type: 'task', taskId: activeTasks[activeTasks.length - 1].taskId });
    }
  };

  return (
    <div className="page-home">
      {activeTasks.length > 0 && (
        <div className="active-tasks-banner" onClick={goToLatestTask}>
          <span className="active-tasks-dot" />
          <span>{activeTasks.length} 个任务运行中，点击查看</span>
          <span className="active-tasks-arrow">→</span>
        </div>
      )}
      <FileUpload onSuccess={handleSuccess} />
    </div>
  );
}
