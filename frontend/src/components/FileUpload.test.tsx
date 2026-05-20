import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import FileUpload from './FileUpload';

const mockCreateTask = vi.fn();
vi.mock('../api', () => ({
  createTask: (...args: unknown[]) => mockCreateTask(...args),
}));

const onSuccess = vi.fn();

/** 选中文件 — 直接 fireEvent.change 避免 jsdom upload 兼容问题 */
function selectFile(file: File) {
  const input = document.querySelector('#file-input') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('初始状态', () => {
  it('渲染上传卡片', () => {
    render(<FileUpload onSuccess={onSuccess} />);
    expect(screen.getByText('上传文档，生成视频')).toBeInTheDocument();
    expect(screen.getByText(/支持 .docx/)).toBeInTheDocument();
  });

  it('文件未选时按钮禁用', () => {
    render(<FileUpload onSuccess={onSuccess} />);
    expect(screen.getByRole('button', { name: '开始生成' })).toBeDisabled();
  });

  it('选择文件后显示文件名且按钮可用', () => {
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['dummy'], 'report.docx', { type: 'application/octet-stream' }));
    expect(screen.getByText('report.docx')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始生成' })).toBeEnabled();
  });
});

describe('文件验证', () => {
  it('不支持格式显示错误', async () => {
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['x'], 'bad.exe', { type: 'application/x-msdownload' }));
    await user.click(screen.getByRole('button', { name: '开始生成' }));
    expect(await screen.findByText(/不支持的文件格式/)).toBeInTheDocument();
    expect(screen.getByText(/重试/)).toBeInTheDocument();
  });

  it('超过大小限制显示错误', async () => {
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    const bigFile = new File(['x'.repeat(60 * 1024 * 1024)], 'big.docx', { type: 'application/octet-stream' });
    selectFile(bigFile);
    await user.click(screen.getByRole('button', { name: '开始生成' }));
    expect(await screen.findByText(/超过 50MB 限制/)).toBeInTheDocument();
  });
});

describe('上传流程', () => {
  it('上传成功后显示提示', async () => {
    mockCreateTask.mockResolvedValue({ task_id: 't123', status: 'pending' });
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['dummy'], 'test.docx', { type: 'application/octet-stream' }));
    await user.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText(/上传成功/)).toBeInTheDocument();
    expect(screen.getByText(/任务 ID: t123/)).toBeInTheDocument();
    expect(onSuccess).toHaveBeenCalledWith('t123', 'test.docx');
  });

  it('上传失败显示错误 + 重试', async () => {
    mockCreateTask.mockRejectedValue(new Error('服务器繁忙'));
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['dummy'], 'fail.docx', { type: 'application/octet-stream' }));
    await user.click(screen.getByRole('button', { name: '开始生成' }));

    expect(await screen.findByText(/上传失败/)).toBeInTheDocument();
    expect(screen.getByText(/服务器繁忙/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });

  it('重试按钮可以重置状态', async () => {
    mockCreateTask.mockRejectedValue(new Error('err'));
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['dummy'], 'retry.docx', { type: 'application/octet-stream' }));
    await user.click(screen.getByRole('button', { name: '开始生成' }));

    await screen.findByText(/上传失败/);
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(screen.getByText('选择文件')).toBeInTheDocument();
  });

  it('上传中显示进度条', async () => {
    let resolvePromise!: (v: unknown) => void;
    mockCreateTask.mockReturnValue(new Promise(r => { resolvePromise = r; }));
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['dummy'], 'progress.docx', { type: 'application/octet-stream' }));
    await user.click(screen.getByRole('button', { name: '开始生成' }));
    expect(screen.getByText(/上传中/)).toBeInTheDocument();
    resolvePromise({ task_id: 't1', status: 'pending' });
  });
});

describe('移除文件', () => {
  it('点击 ✕ 后清除文件名', async () => {
    const user = userEvent.setup();
    render(<FileUpload onSuccess={onSuccess} />);
    selectFile(new File(['d'], 'remove.docx', { type: 'application/octet-stream' }));
    await user.click(screen.getByTitle('移除文件'));
    expect(screen.queryByText('remove.docx')).not.toBeInTheDocument();
  });
});
