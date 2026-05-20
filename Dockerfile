# ============================================================
# Stage 1: 构建前端
# ============================================================
FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ============================================================
# Stage 2: 运行环境（Python + Node.js）
# ============================================================
FROM python:3.11-slim

# 安装 Node.js 22（HyperFrames CLI 依赖 npx）
RUN apt-get update && \
    apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir psycopg2-binary

# 复制应用代码
COPY pipeline/ pipeline/
COPY server.py worker.py ./

# 复制构建好的前端
COPY --from=frontend-builder /build/frontend/dist frontend/dist/

# 数据目录
ENV DATA_DIR=/app/_server_data
VOLUME /app/_server_data

EXPOSE 8000

# 默认启动 API 服务（worker 通过 command 覆盖）
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
