import { useState, useRef, type FormEvent } from 'react';
import { createTask } from '../api';
import type { UploadState } from '../types';

const ACCEPTED = '.docx,.doc,.txt,.pdf';
const MAX_MB = 50;

interface Props {
  onSuccess: (taskId: string) => void;
}

export default function FileUpload({ onSuccess }: Props) {
  const [state, setState] = useState<UploadState>({ type: 'idle' });
  const [fileName, setFileName] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = () => {
    const file = inputRef.current?.files?.[0];
    setFileName(file ? file.name : '');
  };

  const removeFile = () => {
    if (inputRef.current) inputRef.current.value = '';
    setFileName('');
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const file = inputRef.current?.files?.[0];
    if (!file) return;

    const ext = '.' + file.name.split('.').pop()?.toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      setState({ type: 'error', message: `不支持的文件格式: ${ext}，仅支持 ${ACCEPTED}` });
      return;
    }

    if (file.size > MAX_MB * 1024 * 1024) {
      setState({ type: 'error', message: `文件超过 ${MAX_MB}MB 限制` });
      return;
    }

    setState({ type: 'uploading', progress: 0 });
    try {
      // 模拟进度（真实进度靠轮询任务状态）
      const timer = setInterval(() => {
        setState(s => (s.type === 'uploading' ? { ...s, progress: Math.min(s.progress + 20, 90) } : s));
      }, 300);

      const res = await createTask(file);
      clearInterval(timer);
      setState({ type: 'done', taskId: res.task_id });
      onSuccess(res.task_id);
    } catch (err) {
      setState({ type: 'error', message: err instanceof Error ? err.message : '上传失败' });
    }
  };

  const reset = () => {
    setState({ type: 'idle' });
    setFileName('');
    if (inputRef.current) inputRef.current.value = '';
  };

  return (
    <form onSubmit={handleSubmit} className="upload-card">
      <div className="upload-icon">📄</div>
      <h2>上传文档，生成视频</h2>
      <p className="upload-hint">支持 .docx / .doc / .txt / .pdf，最大 {MAX_MB}MB</p>

      {state.type === 'idle' && (
        <>
          <input ref={inputRef} type="file" accept={ACCEPTED} className="file-input" id="file-input" onChange={handleFileChange} />
          {!fileName ? (
            <label htmlFor="file-input" className="file-label">选择文件</label>
          ) : (
            <div style={{ marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center', padding: '10px 16px', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #86efac' }}>
                <span style={{ fontSize: '20px' }}>📄</span>
                <span style={{ fontWeight: 500, color: '#166534', wordBreak: 'break-all' }}>{fileName}</span>
                <button type="button" onClick={removeFile} style={{ border: 'none', background: 'none', cursor: 'pointer', fontSize: '18px', color: '#dc2626', padding: '4px' }} title="移除文件">✕</button>
              </div>
              <label htmlFor="file-input" style={{ display: 'inline-block', marginTop: '8px', fontSize: '13px', color: '#6b7280', cursor: 'pointer', textDecoration: 'underline' }}>更换文件</label>
            </div>
          )}
          <button type="submit" className="btn btn-primary" disabled={!fileName}>
            开始生成
          </button>
        </>
      )}

      {state.type === 'uploading' && (
        <div className="upload-progress">
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${state.progress}%` }} />
          </div>
          <p>上传中... {state.progress}%</p>
        </div>
      )}

      {state.type === 'done' && (
        <div className="upload-success" style={{ padding: '16px', background: '#dcfce7', borderRadius: '8px', border: '1px solid #86efac' }}>
          <p style={{ fontSize: '16px', fontWeight: 600, color: '#166534' }}>✅ 上传成功！任务已创建</p>
          <p className="task-id" style={{ color: '#166534', margin: '4px 0 12px' }}>任务 ID: {state.taskId}</p>
          <p style={{ fontSize: '13px', color: '#15803d' }}>正在处理中，请查看下方进度...</p>
        </div>
      )}

      {state.type === 'error' && (
        <div className="upload-error" style={{ padding: '16px', background: '#fee2e2', borderRadius: '8px', border: '1px solid #fca5a5' }}>
          <p style={{ fontSize: '16px', fontWeight: 600, color: '#991b1b', marginBottom: '4px' }}>❌ 上传失败</p>
          <p style={{ fontSize: '14px', color: '#b91c1c', marginBottom: '12px' }}>{state.message}</p>
          <button onClick={reset} className="btn btn-secondary">重试</button>
        </div>
      )}
    </form>
  );
}
