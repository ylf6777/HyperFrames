import { useState } from 'react';
import TaskList from '../components/TaskList';
import TaskProgress from '../components/TaskProgress';

export default function HistoryPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="page-history">
      <h2>历史记录</h2>
      <TaskList onSelect={setSelectedId} />
      {selectedId && (
        <div className="history-detail">
          <h3>任务详情</h3>
          <TaskProgress taskId={selectedId} />
        </div>
      )}
    </div>
  );
}
