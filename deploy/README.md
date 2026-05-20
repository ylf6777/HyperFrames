# 文生视频 — 部署指南

## 环境要求

- Python 3.11+
- Node.js 20+
- Nginx（可选，生产推荐）
- Supervisor（Linux，进程守护）

## 快速启动（开发/单机）

```bash
# 1. 构建前端
cd frontend && npm install && npm run build

# 2. 设置环境变量
export FEISHU_APP_ID="..."
export FEISHU_APP_SECRET="..."
export FEISHU_BASE_TOKEN="..."
export FEISHU_TABLE_ID="..."
export HYPERFRAMES_API_KEY="..."
export HYPERFRAMES_BASE_URL="..."

# 3. 启动服务端（自带前端托管）
uvicorn server:app --host 0.0.0.0 --port 8000

# 4. 启动 Worker
python worker.py
```

访问 `http://服务器IP:8000` 即可使用。

## 生产部署（Nginx + Supervisor）

见 `nginx.conf` 和 `supervisord.conf`。

## 环境变量说明

| 变量 | 说明 | 必填 |
|------|------|------|
| FEISHU_APP_ID | 飞书应用 ID | 是 |
| FEISHU_APP_SECRET | 飞书应用 Secret | 是 |
| FEISHU_BASE_TOKEN | 多维表格 Base Token | 是 |
| FEISHU_TABLE_ID | 用户表 ID | 是 |
| HYPERFRAMES_API_KEY | LLM API 密钥 | 是 |
| HYPERFRAMES_BASE_URL | LLM API 地址 | 是 |
| SMTP_HOST / SMTP_USER / SMTP_PASS | SMTP 配置 | 发邮件必填 |
| PUBLIC_URL | 前端公网地址 | 推荐 |
| ALLOW_ORIGINS | CORS 白名单 | 推荐 |
| MAX_FILE_SIZE_MB | 上传文件上限 | 默认 50 |
| MAX_TASKS_GLOBAL | 全局最大任务数 | 默认 100 |

## 目录结构

```
_server_data/
  tasks.db     # SQLite 任务数据库
  docs/        # 上传文档
  videos/      # 生成视频
  llm_cache/   # LLM 响应缓存
```
