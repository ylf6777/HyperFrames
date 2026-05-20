# 文生视频 — 项目笔记

## 服务器部署完整指南

### 0. Docker 部署（推荐）

```bash
# 1. 复制环境变量模板并编辑
cp .env.example .env
# 编辑 .env，至少填写 PG_PASSWORD 和 HYPERFRAMES_API_KEY

# 2. 一键启动
docker compose up -d

# 3. 查看日志
docker compose logs -f app worker

# 4. 停止
docker compose down
```

架构：`app`（API）+ `worker`（后台任务）+ `db`（PostgreSQL）+ `nginx`（反向代理 + 静态文件）。

### A. 传统部署（手工安装）
```bash
# Python 3.11+
apt install python3 python3-pip python3-venv

# Node.js 20+（Hyperframes CLI 需要）
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install nodejs

# Nginx + Supervisor
apt install nginx supervisor

# PostgreSQL（生产推荐）
apt install postgresql postgresql-client
```

### 1. 安装 Python 依赖
```bash
python3 -m venv venv
source venv/bin/activate

# 核心依赖
pip install fastapi uvicorn[standard] python-multipart requests edge-tts

# PostgreSQL 支持（如果需要）
pip install psycopg2-binary
```

### 2. 构建前端
```bash
cd frontend
npm install
npm run build        # 产出 dist/
```

### 3. 配置环境变量
```
HYPERFRAMES_API_KEY=       # LLM API 密钥
HYPERFRAMES_BASE_URL=      # LLM API 地址
HYPERFRAMES_VERSION=0.6.6  # 可选，默认 0.6.6
FEISHU_APP_ID=             # 飞书应用
FEISHU_APP_SECRET=
FEISHU_BASE_TOKEN=
FEISHU_TABLE_ID=
SMTP_HOST=                # 邮件（可选）
SMTP_USER=
SMTP_PASS=
PUBLIC_URL=https://your-domain.com
ALLOW_ORIGINS=https://your-domain.com
MAX_FILE_SIZE_MB=50       # 可选，默认 50
MAX_TASKS_GLOBAL=100      # 可选，默认 100

# PostgreSQL（默认 SQLite，生产建议切换）
DB_TYPE=postgres
DATABASE_URL=postgresql://user:pass@localhost:5432/text2video
```

### 4. 启动服务
```bash
# API 服务（参考 deploy/supervisord.conf）
uvicorn server:app --host 127.0.0.1 --port 8000

# Worker（独立进程）
python worker.py --concurrent 2

# Nginx 配置：复制 deploy/nginx.conf 到 /etc/nginx/
# Supervisor 配置：复制 deploy/supervisord.conf 到 /etc/supervisor/conf.d/
```

### 5. 首次部署注意事项
- 数据库会自动创建（PostgreSQL 不存在时自动建库 + 建表）
- 旧数据迁移: `python scripts/migrate_sqlite_to_pg.py`
- HTTPS 用 certbot / acme.sh 申请证书
- 前端静态文件由 Nginx 托管
- API 通过反向代理到 FastAPI
