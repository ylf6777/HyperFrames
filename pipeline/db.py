"""
db.py — 共享数据库层（SQLite / PostgreSQL 双后端）

环境变量:
  DB_TYPE      sqlite（默认）| postgres
  DATABASE_URL PG 连接字符串（DB_TYPE=postgres 时必填）
  DB_PATH      SQLite 文件路径（默认 _server_data/tasks.db）

用法：
  from pipeline.db import db_get_task, ...
  切换后端只需改环境变量，业务代码零改动。
"""

import os
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "_server_data"))
TASKS_DIR = DATA_DIR / "tasks"
VIDEOS_DIR = DATA_DIR / "videos"
DOCS_DIR = DATA_DIR / "docs"
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "tasks.db"))

for d in (DATA_DIR, TASKS_DIR, VIDEOS_DIR, DOCS_DIR):
    d.mkdir(parents=True, exist_ok=True)

DB_TYPE = os.environ.get("DB_TYPE", "sqlite")
PARAM = "%s" if DB_TYPE == "postgres" else "?"


# ── 连接工厂 ───────────────────────────────────────────────

class _PGConn:
    """psycopg2 连接包装类：提供 .execute() 快捷方法"""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def cursor(self, **kw):
        return self._conn.cursor(**kw)

    def close(self):
        self._conn.close()


def get_conn():
    if DB_TYPE == "postgres":
        import psycopg2
        dsn = os.environ.get("DATABASE_URL", "postgresql://localhost/text2video")
        try:
            conn = psycopg2.connect(dsn)
        except psycopg2.OperationalError as e:
            # 自动创建不存在的数据库
            if 'does not exist' not in str(e):
                raise
            db_name = dsn.rsplit("/", 1)[-1].split("?")[0]
            parent_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
            print(f"[db] 数据库 '{db_name}' 不存在，正在创建...")
            parent = psycopg2.connect(parent_dsn)
            parent.autocommit = True
            parent.cursor().execute(f'CREATE DATABASE "{db_name}"')
            parent.close()
            conn = psycopg2.connect(dsn)
            print(f"[db] 数据库 '{db_name}' 创建成功")
        return _PGConn(conn)
    # SQLite
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _close(conn):
    """统一关闭连接"""
    if DB_TYPE == "postgres":
        conn.close()
    else:
        conn.close()


def _dict_cursor(conn):
    """使 cursor.fetchone() 返回 dict-like 对象"""
    if DB_TYPE == "postgres":
        import psycopg2.extras
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    import sqlite3
    conn.row_factory = sqlite3.Row
    return conn.cursor()


# ── DDL ────────────────────────────────────────────────────
# 使用 PG 兼容类型名（SQLite 无强制类型检查，兼容）

def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            status      TEXT DEFAULT 'pending',
            filename    TEXT,
            progress    TEXT DEFAULT '',
            video_path  TEXT DEFAULT '',
            error       TEXT DEFAULT '',
            created_at  DOUBLE PRECISION,
            updated_at  DOUBLE PRECISION
        )
    """)
    # 兼容迁移：旧表无 client_ip 列
    try:
        conn.execute("ALTER TABLE tasks ADD COLUMN client_ip TEXT DEFAULT ''")
    except Exception:
        if DB_TYPE == "postgres":
            conn._conn.rollback()  # 防止事务中断

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token     TEXT PRIMARY KEY,
            user_id   TEXT NOT NULL,
            created_at DOUBLE PRECISION
        )
    """)
    conn.commit()
    _close(conn)


# ── 任务 CRUD ──────────────────────────────────────────────

def recover_orphaned_tasks():
    """启动时恢复：将 processing 状态的任务重置为 pending"""
    conn = get_conn()
    count = conn.execute(
        f"UPDATE tasks SET status='pending', progress='已恢复（服务重启）', updated_at={PARAM} "
        f"WHERE status='processing'",
        (time.time(),),
    ).rowcount
    conn.commit()
    _close(conn)
    if count:
        print(f"[db] 启动恢复: 重置了 {count} 个孤儿任务")


def db_get_task(task_id: str) -> dict | None:
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute(f"SELECT * FROM tasks WHERE id={PARAM}", (task_id,))
    row = cur.fetchone()
    _close(conn)
    return dict(row) if row else None


def db_update_task(task_id: str, **kw):
    sets = ", ".join(f"{k}={PARAM}" for k in kw)
    vals = list(kw.values()) + [task_id]
    conn = get_conn()
    conn.execute(f"UPDATE tasks SET {sets} WHERE id={PARAM}", vals)
    conn.commit()
    _close(conn)


def db_create_task(task_id: str, filename: str, client_ip: str = ""):
    now = time.time()
    conn = get_conn()
    conn.execute(
        f"INSERT INTO tasks (id, status, filename, client_ip, created_at, updated_at) "
        f"VALUES ({PARAM},{PARAM},{PARAM},{PARAM},{PARAM},{PARAM})",
        (task_id, "pending", filename, client_ip, now, now),
    )
    conn.commit()
    _close(conn)


def db_list_tasks(limit: int = 20, offset: int = 0) -> list[dict]:
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute(
        "SELECT id, status, filename, progress, error, created_at, updated_at "
        f"FROM tasks ORDER BY created_at DESC LIMIT {PARAM} OFFSET {PARAM}",
        (limit, offset),
    )
    rows = cur.fetchall()
    _close(conn)
    return [{"task_id": r["id"], **{k: v for k, v in dict(r).items() if k != "id"}} for r in rows]


def db_count_tasks() -> int:
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    _close(conn)
    return cnt


def db_pending_tasks(max_concurrent: int) -> list[dict]:
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute(
        f"SELECT * FROM tasks WHERE status='pending' ORDER BY created_at LIMIT {PARAM}",
        (max_concurrent,),
    )
    rows = cur.fetchall()
    _close(conn)
    return [dict(r) for r in rows]


def db_claim_task(task_id: str) -> bool:
    """原子性抢占任务"""
    conn = get_conn()
    now = time.time()

    if DB_TYPE == "postgres":
        conn.execute("BEGIN")
        cur = conn.cursor()
        cur.execute(f"SELECT status FROM tasks WHERE id={PARAM} FOR UPDATE", (task_id,))
        row = cur.fetchone()
        if row and row[0] == "pending":
            conn.execute(
                f"UPDATE tasks SET status='processing', progress='开始处理', updated_at={PARAM} WHERE id={PARAM}",
                (now, task_id),
            )
            conn.commit()
            _close(conn)
            return True
        conn.commit()
        _close(conn)
        return False

    # SQLite
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(f"SELECT status FROM tasks WHERE id={PARAM}", (task_id,)).fetchone()
    if row and row[0] == "pending":
        conn.execute(
            f"UPDATE tasks SET status='processing', progress='开始处理', updated_at={PARAM} WHERE id={PARAM}",
            (now, task_id),
        )
        conn.commit()
        _close(conn)
        return True
    conn.commit()  # 回滚
    _close(conn)
    return False


# ── 统计 ────────────────────────────────────────────────────

def count_ip_pending(client_ip: str) -> int:
    conn = get_conn()
    cnt = conn.execute(
        f"SELECT COUNT(*) FROM tasks WHERE client_ip={PARAM} AND status IN ('pending','processing')",
        (client_ip,),
    ).fetchone()[0]
    _close(conn)
    return cnt


def count_ip_total(client_ip: str) -> int:
    conn = get_conn()
    cnt = conn.execute(
        f"SELECT COUNT(*) FROM tasks WHERE client_ip={PARAM}",
        (client_ip,),
    ).fetchone()[0]
    _close(conn)
    return cnt


def count_global() -> int:
    conn = get_conn()
    cnt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    _close(conn)
    return cnt


# ── 会话持久化 ─────────────────────────────────────────────

def db_create_session(token: str, user_id: str):
    conn = get_conn()
    now = time.time()
    if DB_TYPE == "postgres":
        conn.execute(
            f"INSERT INTO sessions (token, user_id, created_at) VALUES ({PARAM},{PARAM},{PARAM}) "
            f"ON CONFLICT (token) DO UPDATE SET user_id=EXCLUDED.user_id, created_at=EXCLUDED.created_at",
            (token, user_id, now),
        )
    else:
        conn.execute(
            f"INSERT OR REPLACE INTO sessions (token, user_id, created_at) VALUES ({PARAM},{PARAM},{PARAM})",
            (token, user_id, now),
        )
    conn.commit()
    _close(conn)


def db_get_session(token: str) -> str | None:
    conn = get_conn()
    row = conn.execute(f"SELECT user_id FROM sessions WHERE token={PARAM}", (token,)).fetchone()
    _close(conn)
    return row[0] if row else None


def db_delete_session(token: str):
    conn = get_conn()
    conn.execute(f"DELETE FROM sessions WHERE token={PARAM}", (token,))
    conn.commit()
    _close(conn)


# ── 磁盘管理 ──────────────────────────────────────────────────


def cleanup_old_videos(max_age_days: int = 7):
    """清理超过 N 天的已完成任务的视频文件

    扫描 completed 状态且 created_at 超过 max_age_days 的任务，
    从存储后端（本地/S3）删除视频文件，然后清空 DB 中的 video_path。

    返回: (removed_count, freed_bytes)
    """
    from pipeline.storage import delete as storage_delete

    cutoff = time.time() - max_age_days * 86400
    conn = get_conn()
    cur = _dict_cursor(conn)
    cur.execute(
        f"SELECT id, video_path FROM tasks WHERE status='completed' AND created_at < {PARAM} "
        f"AND video_path != '' AND video_path IS NOT NULL",
        (cutoff,),
    )
    rows = cur.fetchall()
    removed = 0
    freed = 0

    for row in rows:
        path = row["video_path"]
        # S3 路径
        if path.startswith(("http://", "https://", "s3://")):
            storage_delete(path)
            removed += 1
        # 本地路径
        elif path and os.path.isfile(path):
            size = os.path.getsize(path)
            try:
                os.remove(path)
                removed += 1
                freed += size
            except OSError as e:
                conn.execute(
                    f"UPDATE tasks SET error = COALESCE(error, '') || {PARAM} WHERE id={PARAM}",
                    (f"[cleanup] 删除旧视频失败: {e}; ", row["id"]),
                )
        # 即使文件已不存在也清空路径记录
        conn.execute(
            f"UPDATE tasks SET video_path='' WHERE id={PARAM}",
            (row["id"],),
        )

    conn.commit()
    _close(conn)

    if removed:
        unit = "MB" if BACKEND != "s3" else ""
        detail = f"，释放 {freed / 1024 / 1024:.1f} MB" if freed else ""
        print(f"[db] 清理了 {removed} 个旧视频{detail}")

    # 同时清理空目录
    try:
        for p in Path(VIDEOS_DIR).iterdir():
            if p.is_file() and p.suffix != ".mp4":
                # 清理残留的非视频文件
                p.unlink(missing_ok=True)
    except Exception:
        pass

    return removed, freed


# ── 模块加载时自动初始化 ──
init_db()
