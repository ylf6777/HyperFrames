import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TaskList from './TaskList';
import type { Task } from '../types';

const mockListTasks = vi.fn();
vi.mock('../api', () => ({
  listTasks: (...args: unknown[]) => mockListTasks(...args),
}));

const onSelect = vi.fn();

function makeTask(id: string, overrides: Partial<Task> = {}): Task {
  return {
    task_id: id,
    status: 'pending',
    filename: `${id}.docx`,
    progress: '',
    error: '',
    created_at: Date.now() / 1000 - 100,
    updated_at: Date.now() / 1000,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('加载 & 空状态', () => {
  it('loading 中显示加载文案', () => {
    mockListTasks.mockReturnValue(new Promise(() => {}));
    render(<TaskList onSelect={onSelect} />);
    expect(screen.getByText('加载中...')).toBeInTheDocument();
  });

  it('无任务时显示空提示', async () => {
    mockListTasks.mockResolvedValue({ tasks: [], total: 0 });
    render(<TaskList onSelect={onSelect} />);
    expect(await screen.findByText('暂无任务记录')).toBeInTheDocument();
  });
});

describe('任务列表', () => {
  it('渲染任务列表', async () => {
    mockListTasks.mockResolvedValue({
      tasks: [
        makeTask('t1', { status: 'completed', filename: 'report.docx' }),
        makeTask('t2', { status: 'processing', filename: 'slide.pptx' }),
      ],
      total: 2,
    });
    render(<TaskList onSelect={onSelect} />);
    expect(await screen.findByText('report.docx')).toBeInTheDocument();
    expect(screen.getByText('slide.pptx')).toBeInTheDocument();
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('处理中')).toBeInTheDocument();
  });

  it('所有状态标签', async () => {
    mockListTasks.mockResolvedValue({
      tasks: [
        makeTask('s1', { status: 'pending' }),
        makeTask('s2', { status: 'processing' }),
        makeTask('s3', { status: 'completed' }),
        makeTask('s4', { status: 'failed' }),
        makeTask('s5', { status: 'cancelled' }),
      ],
      total: 5,
    });
    render(<TaskList onSelect={onSelect} />);
    expect(await screen.findByText('排队中')).toBeInTheDocument();
    expect(screen.getByText('处理中')).toBeInTheDocument();
    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText('失败')).toBeInTheDocument();
    expect(screen.getByText('已取消')).toBeInTheDocument();
  });

  it('点击任务调用 onSelect', async () => {
    mockListTasks.mockResolvedValue({
      tasks: [makeTask('t1', { status: 'completed' })],
      total: 1,
    });
    render(<TaskList onSelect={onSelect} />);
    const item = await screen.findByText('t1.docx');
    await userEvent.click(item);
    expect(onSelect).toHaveBeenCalledWith('t1');
  });
});

describe('API 失败处理', () => {
  it('异常不崩溃', async () => {
    mockListTasks.mockRejectedValue(new Error('err'));
    render(<TaskList onSelect={onSelect} />);
    expect(await screen.findByText('暂无任务记录')).toBeInTheDocument();
  });
});
