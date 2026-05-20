"""
server.py — 文档→视频 API 服务
================================
FastAPI + SQLite，Worker 已拆分为独立进程。

启动:  uvicorn server:app --host 0.0.0.0 --port 8000
Worker: python worker.py
"""

import os
import uuid
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pipeline.db import (
    DATA_DIR, VIDEOS_DIR, DOCS_DIR, DB_PATH,
    db_get_task, db_update_task, db_create_task,
    count_ip_pending, count_ip_total, count_global,
)
from pipeline.utils import sanitize_filename
from pipeline.llm import LLMCache


# ── 配置 ───────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))
ALLOW_ORIGINS = os.environ.get("ALLOW_ORIGINS", "*").split(",")

# ── 速率限制配置 ──
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "1"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))
MAX_TASKS_PER_IP_PENDING = int(os.environ.get("MAX_TASKS_PER_IP_PENDING", "2"))
MAX_TASKS_PER_IP_TOTAL = int(os.environ.get("MAX_TASKS_PER_IP_TOTAL", "10"))
MAX_TASKS_GLOBAL = int(os.environ.get("MAX_TASKS_GLOBAL", "100"))


# ── Rate Limiter ────────────────────────────────────────────────────
from collections import defaultdict as _defaultdict


class RateLimiter:
    """滑动窗口 IP 速率限制器"""
    def __init__(self, max_requests: int, window: float):
        self.max_requests = max_requests
        self.window = window
        self._ips: dict[str, list[float]] = _defaultdict(list)

    def _prune(self, ip: str, cutoff: float):
        pruned = [t for t in self._ips.get(ip, []) if t > cutoff]
        if pruned:
            self._ips[ip] = pruned
        else:
            self._ips.pop(ip, None)

    def allow(self, ip: str) -> bool:
        now = time.time()
        self._prune(ip, now - self.window)
        if len(self._ips.get(ip, [])) >= self.max_requests:
            return False
        self._ips[ip].append(now)
        return True

    def remaining(self, ip: str) -> int:
        self._prune(ip, time.time() - self.window)
        active = len(self._ips.get(ip, []))
        return max(0, self.max_requests - active)


import time
_post_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


# ── FastAPI ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：无需启动 Worker（独立进程管理）
    yield
    # 关闭：无需停止 Worker
    pass


app = FastAPI(title="文档→视频生成服务", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/tasks")
async def create_task(file: UploadFile = File(...), request: Request = None):
    """上传文档，创建生成任务"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".doc", ".docx", ".txt", ".pdf"):
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    # 限制文件大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"文件大小超过 {MAX_FILE_SIZE_MB}MB 限制")

    # ── 速率限制检查 ──
    client_ip = get_client_ip(request)

    if not _post_limiter.allow(client_ip):
        raise HTTPException(
            429,
            f"请求过于频繁，请等待 {RATE_LIMIT_WINDOW} 秒后再试（每 IP 每分钟 {RATE_LIMIT_REQUESTS} 次）",
        )

    pending_count = count_ip_pending(client_ip)
    if pending_count >= MAX_TASKS_PER_IP_PENDING:
        raise HTTPException(
            429,
            f"同 IP 待处理任务过多（{pending_count} ≥ {MAX_TASKS_PER_IP_PENDING}），请等待当前任务完成",
        )

    total_ip = count_ip_total(client_ip)
    if total_ip >= MAX_TASKS_PER_IP_TOTAL:
        raise HTTPException(
            429,
            f"同 IP 总任务数已达上限（{total_ip} ≥ {MAX_TASKS_PER_IP_TOTAL}）",
        )

    total_global = count_global()
    if total_global >= MAX_TASKS_GLOBAL:
        raise HTTPException(
            429,
            f"系统任务总量已达上限（{total_global} ≥ {MAX_TASKS_GLOBAL}）",
        )

    task_id = uuid.uuid4().hex[:12]
    safe_name = sanitize_filename(file.filename)
    db_create_task(task_id, safe_name, client_ip)

    doc_path = (DOCS_DIR / f"{task_id}_{safe_name}").resolve()
    if not str(doc_path).startswith(str(DOCS_DIR.resolve())):
        raise HTTPException(400, "非法文件名")
    doc_path.write_bytes(content)

    return {"task_id": task_id, "status": "pending"}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查询任务状态"""
    task = db_get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {
        "task_id": task["id"],
        "status": task["status"],
        "filename": task["filename"],
        "progress": task["progress"],
        "error": task["error"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    """取消一个正在处理的任务"""
    task = db_get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] not in ("pending", "processing"):
        raise HTTPException(400, f"当前状态不允许取消（{task['status']}）")
    import time
    db_update_task(task_id, status="cancelled", progress="已取消", updated_at=time.time())
    return {"task_id": task_id, "status": "cancelled"}


@app.get("/api/videos/{task_id}.mp4")
def get_video(task_id: str):
    """下载生成的视频"""
    task = db_get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] != "completed":
        raise HTTPException(400, "视频尚未生成完成")
    if not task["video_path"] or not os.path.exists(task["video_path"]):
        raise HTTPException(404, "视频文件不存在")

    return FileResponse(
        task["video_path"],
        media_type="video/mp4",
        filename=f"{task_id}.mp4",
    )


@app.get("/api/tasks")
def list_tasks(limit: int = 20):
    """查看最近的任务列表"""
    from pipeline.db import db_list_tasks
    return db_list_tasks(limit)


# ── LLM 缓存管理 ────────────────────────────────────────────────

_llm_cache = LLMCache()


@app.get("/api/cache")
def get_cache():
    """查看 LLM 缓存状态"""
    stats = _llm_cache.stats()
    entries = _llm_cache.list_entries()
    return {"stats": stats, "entries": entries}


@app.delete("/api/cache")
def clear_cache():
    """清空所有 LLM 缓存"""
    _llm_cache.clear()
    return {"status": "ok"}


@app.delete("/api/cache/{key}")
def delete_cache_entry(key: str):
    """删除指定缓存"""
    ok = _llm_cache.delete(key)
    return {"status": "ok" if ok else "not_found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
