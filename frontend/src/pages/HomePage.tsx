import { useState } from 'react';
import FileUpload from '../components/FileUpload';
import TaskProgress from '../components/TaskProgress';

export default function HomePage() {
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [uploadKey, setUploadKey] = useState(0);

  const handleCancel = () => {
    setActiveTaskId(null);
    setUploadKey(k => k + 1);
  };

  return (
    <div className="page-home">
      <FileUpload key={uploadKey} onSuccess={setActiveTaskId} />
      {activeTaskId && <TaskProgress taskId={activeTaskId} onCancel={handleCancel} />}
    </div>
  );
}
