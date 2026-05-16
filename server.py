"""
server.py — 文档→视频 API 服务
================================
FastAPI + SQLite + 后台 Worker

启动:  uvicorn server:app --host 0.0.0.0 --port 8000
"""

import os
import json
import time
import uuid
import threading
import sqlite3
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pipeline import generate_video
from pipeline.utils import sanitize_filename, check_disk_space

# ── 配置 ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "_server_data"
TASKS_DIR = DATA_DIR / "tasks"
VIDEOS_DIR = DATA_DIR / "videos"
DOCS_DIR = DATA_DIR / "docs"
DB_PATH = DATA_DIR / "tasks.db"
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
WORKER_SLEEP = int(os.environ.get("WORKER_SLEEP", "2"))
ORPHAN_TIMEOUT = int(os.environ.get("ORPHAN_TIMEOUT", "300"))
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))

for d in (DATA_DIR, TASKS_DIR, VIDEOS_DIR, DOCS_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ── 数据库 ─────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            status      TEXT DEFAULT 'pending',
            filename    TEXT,
            progress    TEXT DEFAULT '',
            video_path  TEXT DEFAULT '',
            error       TEXT DEFAULT '',
            created_at  REAL,
            updated_at  REAL
        )
    """)
    conn.commit()
    conn.close()


def recover_orphaned_tasks():
    """启动时恢复：将上次服务中断时残留在 processing 状态的任务重置为 pending。"""
    conn = sqlite3.connect(str(DB_PATH))
    now = time.time()
    cutoff = now - ORPHAN_TIMEOUT
    count = conn.execute(
        "UPDATE tasks SET status='pending', progress='已恢复（服务重启）', updated_at=? "
        "WHERE status='processing' AND updated_at < ?",
        (now, cutoff),
    ).rowcount
    # 如果服务刚启动，所有 processing 都是孤儿（不受超时限制）
    count += conn.execute(
        "UPDATE tasks SET status='pending', progress='已恢复（服务重启）', updated_at=? "
        "WHERE status='processing' AND updated_at >= ?",
        (now, cutoff),
    ).rowcount
    conn.commit()
    conn.close()
    if count:
        print(f"[server] 启动恢复: 重置了 {count} 个孤儿任务")


init_db()
recover_orphaned_tasks()


def db_get_task(task_id: str) -> dict | None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def db_update_task(task_id: str, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    vals = list(kw.values()) + [task_id]
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def db_create_task(task_id: str, filename: str):
    now = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO tasks (id, status, filename, created_at, updated_at) VALUES (?,?,?,?,?)",
        (task_id, "pending", filename, now, now),
    )
    conn.commit()
    conn.close()


# ── Worker ─────────────────────────────────────────────────────────
_running_tasks: set[str] = set()
_lock = threading.Lock()


def worker_loop():
    """后台线程：轮询 pending 任务，逐个执行"""
    while True:
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status='pending' ORDER BY created_at LIMIT ?",
                (MAX_CONCURRENT,),
            ).fetchall()
            conn.close()

            for row in rows:
                tid = row["id"]
                with _lock:
                    if tid in _running_tasks:
                        continue
                    if len(_running_tasks) >= MAX_CONCURRENT:
                        break
                    _running_tasks.add(tid)

                thread = threading.Thread(target=run_task, args=(tid,), daemon=True)
                thread.start()

        except Exception as e:
            print(f"[worker] error: {e}")

        time.sleep(WORKER_SLEEP)


def run_task(task_id: str):
    """执行单个生成任务"""
    task = db_get_task(task_id)
    if not task:
        return

    safe_name = sanitize_filename(task["filename"])
    doc_path = str((DOCS_DIR / f"{task_id}_{safe_name}").resolve())

    # 磁盘空间检查：至少 500MB 剩余
    ok, free_mb = check_disk_space(DATA_DIR)
    if not ok:
        db_update_task(task_id, status="failed", error=f"磁盘空间不足（剩余 {free_mb}MB，需要 500MB）", progress="失败", updated_at=time.time())
        return

    def on_progress(msg: str):
        db_update_task(task_id, progress=msg, updated_at=time.time())

    on_progress("读取文档中...")

    try:
        result = generate_video(
            input_path=doc_path,
            project=f"task-{task_id}",
            base_dir=str(TASKS_DIR),
            on_progress=on_progress,
        )

        if result["success"] and result["video_path"]:
            video_dst = VIDEOS_DIR / f"{task_id}.mp4"
            shutil.copy2(result["video_path"], str(video_dst))
            db_update_task(
                task_id,
                status="completed",
                video_path=str(video_dst),
                progress="完成",
                updated_at=time.time(),
            )
        else:
            db_update_task(
                task_id,
                status="failed",
                error="生成失败，详情请查看服务端日志",
                progress="失败",
                updated_at=time.time(),
            )
    except Exception as e:
        db_update_task(
            task_id,
            status="failed",
            error=str(e),
            progress="失败",
            updated_at=time.time(),
        )
    finally:
        with _lock:
            _running_tasks.discard(task_id)


# ── FastAPI ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    yield


app = FastAPI(title="文档→视频生成服务", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/tasks")
async def create_task(file: UploadFile = File(...)):
    """上传文档，创建生成任务"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".doc", ".docx", ".txt", ".pdf"):
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    # 限制文件大小（50MB）
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"文件大小超过 {MAX_FILE_SIZE_MB}MB 限制")

    task_id = uuid.uuid4().hex[:12]
    safe_name = sanitize_filename(file.filename)
    db_create_task(task_id, safe_name)

    doc_path = (DOCS_DIR / f"{task_id}_{safe_name}").resolve()
    # 验证最终路径仍在 DOCS_DIR 内（防御路径穿越）
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
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, status, filename, progress, error, created_at, updated_at "
        "FROM tasks ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
