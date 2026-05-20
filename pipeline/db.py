"""
db.py — 共享数据库层（Server + Worker 共用）
SQLite 任务持久化，启用 WAL 模式支持多进程并发
"""

import os
import time
import sqlite3
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "_server_data"
TASKS_DIR = DATA_DIR / "tasks"
VIDEOS_DIR = DATA_DIR / "videos"
DOCS_DIR = DATA_DIR / "docs"
DB_PATH = DATA_DIR / "tasks.db"

for d in (DATA_DIR, TASKS_DIR, VIDEOS_DIR, DOCS_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ── 数据库连接 ─────────────────────────────────────────────
def get_conn():
    """获取 SQLite 连接（WAL 模式，支持多进程并发读写）"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """初始化数据库表，含兼容迁移"""
    conn = get_conn()
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
    # 迁移：添加 client_ip 列（旧表升级）
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN client_ip TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()


def recover_orphaned_tasks():
    """启动时恢复：将 processing 状态的任务重置为 pending"""
    conn = get_conn()
    count = conn.execute(
        "UPDATE tasks SET status='pending', progress='已恢复（服务重启）', updated_at=? "
        "WHERE status='processing'",
        (time.time(),),
    ).rowcount
    conn.commit()
    conn.close()
    if count:
        print(f"[db] 启动恢复: 重置了 {count} 个孤儿任务")


def db_get_task(task_id: str) -> dict | None:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def db_update_task(task_id: str, **kw):
    sets = ", ".join(f"{k}=?" for k in kw)
    vals = list(kw.values()) + [task_id]
    conn = get_conn()
    conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def db_create_task(task_id: str, filename: str, client_ip: str = ""):
    now = time.time()
    conn = get_conn()
    conn.execute(
        "INSERT INTO tasks (id, status, filename, client_ip, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (task_id, "pending", filename, client_ip, now, now),
    )
    conn.commit()
    conn.close()


def db_list_tasks(limit: int = 20, offset: int = 0) -> list[dict]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, status, filename, progress, error, created_at, updated_at "
        "FROM tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [{"task_id": r["id"], **{k: v for k, v in dict(r).items() if k != "id"}} for r in rows]


def db_count_tasks() -> int:
    """返回任务总数"""
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    return cnt


def db_pending_tasks(max_concurrent: int) -> list[dict]:
    """获取待处理任务列表（最多 max_concurrent 个）"""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='pending' ORDER BY created_at LIMIT ?",
        (max_concurrent,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_claim_task(task_id: str) -> bool:
    """原子性抢占任务（返回 True 表示抢到）"""
    conn = get_conn()
    now = time.time()
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT status FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    if row and row[0] == "pending":
        conn.execute(
            "UPDATE tasks SET status='processing', progress='开始处理', updated_at=? WHERE id=?",
            (now, task_id),
        )
        conn.commit()
        conn.close()
        return True
    conn.commit()  # 回滚 BEGIN
    conn.close()
    return False


def count_ip_pending(client_ip: str) -> int:
    conn = get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE client_ip=? AND status IN ('pending','processing')",
        (client_ip,),
    ).fetchone()[0]
    conn.close()
    return cnt


def count_ip_total(client_ip: str) -> int:
    conn = get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE client_ip=?",
        (client_ip,),
    ).fetchone()[0]
    conn.close()
    return cnt


def count_global() -> int:
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    return cnt


# ── 模块加载时自动初始化 ──
init_db()
