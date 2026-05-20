import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TaskProgress from './TaskProgress';

const mockGetTask = vi.fn();
const mockCancelTask = vi.fn();
vi.mock('../api', () => ({
  getTask: (...args: unknown[]) => mockGetTask(...args),
  cancelTask: (...args: unknown[]) => mockCancelTask(...args),
  getVideoUrl: (id: string) => `/api/videos/${id}.mp4`,
}));

const onCancel = vi.fn();
const TASK_ID = 'test-task-001';

function makeTask(overrides: Record<string, unknown> = {}) {
  return {
    task_id: TASK_ID,
    status: 'pending',
    filename: 'doc.docx',
    progress: '',
    error: '',
    created_at: Date.now() / 1000,
    updated_at: Date.now() / 1000,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('加载状态', () => {
  it('loading 时显示 spinner', () => {
    mockGetTask.mockReturnValue(new Promise(() => {}));
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
    expect(screen.getByText('连接服务器...')).toBeInTheDocument();
  });
});

describe('状态渲染', () => {
  async function renderWithStatus(status: string, extra: Record<string, unknown> = {}) {
    mockGetTask.mockResolvedValue(makeTask({ status, ...extra }));
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
  }

  it('pending 状态', async () => {
    await renderWithStatus('pending');
    const items = await screen.findAllByText('排队中');
    expect(items.length).toBeGreaterThanOrEqual(1);
  });

  it('processing 显示进度', async () => {
    await renderWithStatus('processing', { progress: '解析文档中...' });
    expect(await screen.findByText('解析文档中...')).toBeInTheDocument();
  });

  it('completed 显示下载', async () => {
    await renderWithStatus('completed');
    const items = await screen.findAllByText('已完成');
    expect(items.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('下载视频').closest('a')).toHaveAttribute('download');
  });

  it('failed 显示错误和重新上传', async () => {
    await renderWithStatus('failed', { error: 'LLM 超时' });
    const items = await screen.findAllByText('失败');
    expect(items.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/LLM 超时/)).toBeInTheDocument();
    expect(screen.getByText('重新上传')).toBeInTheDocument();
  });

  it('cancelled 调用 onCancel', async () => {
    await renderWithStatus('cancelled');
    expect(await screen.findByText('任务已取消')).toBeInTheDocument();
    expect(onCancel).toHaveBeenCalled();
  });

  it('无进度时降级显示状态标签', async () => {
    await renderWithStatus('processing', { progress: '' });
    const items = await screen.findAllByText('处理中');
    expect(items.length).toBeGreaterThanOrEqual(1);
  });
});

describe('取消流程', () => {
  it('pending 显示取消按钮', async () => {
    mockGetTask.mockResolvedValue(makeTask({ status: 'pending' }));
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
    expect(await screen.findByText('取消任务')).toBeInTheDocument();
  });

  it('点击取消弹出确认框', async () => {
    const user = userEvent.setup();
    mockGetTask.mockResolvedValue(makeTask({ status: 'pending' }));
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
    await screen.findByText('取消任务');
    await user.click(screen.getByText('取消任务'));
    expect(screen.getByText('确定要取消这个任务吗？')).toBeInTheDocument();
  });

  it('确认取消调 API', async () => {
    const user = userEvent.setup();
    mockGetTask.mockResolvedValue(makeTask({ status: 'pending' }));
    mockCancelTask.mockResolvedValue({});
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
    await screen.findByText('取消任务');
    await user.click(screen.getByText('取消任务'));
    await user.click(screen.getByText('确定取消'));
    expect(mockCancelTask).toHaveBeenCalledWith(TASK_ID);
  });

  it('点"我再想想"关闭确认', async () => {
    const user = userEvent.setup();
    mockGetTask.mockResolvedValue(makeTask({ status: 'pending' }));
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
    await screen.findByText('取消任务');
    await user.click(screen.getByText('取消任务'));
    await user.click(screen.getByText('我再想想'));
    expect(screen.queryByText('确定要取消这个任务吗？')).not.toBeInTheDocument();
  });
});

describe('最终状态不显示取消按钮', () => {
  for (const status of ['completed', 'failed', 'cancelled']) {
    it(`${status}`, async () => {
      mockGetTask.mockResolvedValue(makeTask({ status }));
      render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
      // 等状态渲染完成
      await screen.findByTestId('status-card');
      expect(screen.queryByText('取消任务')).not.toBeInTheDocument();
    });
  }
});

describe('query 异常', () => {
  it('网络错误显示错误提示', async () => {
    mockGetTask.mockRejectedValue(new Error('Network error'));
    render(<TaskProgress taskId={TASK_ID} onCancel={onCancel} />);
    expect(await screen.findByText(/Network error/)).toBeInTheDocument();
  });
});
