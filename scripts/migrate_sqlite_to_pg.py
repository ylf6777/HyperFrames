#!/usr/bin/env python3
"""
将 SQLite 数据迁移到 PostgreSQL

用法:
  DATABASE_URL=postgresql://user:pass@host/db python scripts/migrate_sqlite_to_pg.py

环境变量:
  DB_PATH       SQLite 文件路径（默认 _server_data/tasks.db）
  DATABASE_URL  PG 连接字符串（必填）
"""

import os
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 连接 SQLite ──────────────────────────────────────────────
DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).resolve().parent.parent / "_server_data" / "tasks.db"))
if not DB_PATH.exists():
    print(f"[迁移] SQLite 数据库不存在: {DB_PATH}")
    sys.exit(1)

sqlite_conn = sqlite3.connect(str(DB_PATH))
sqlite_conn.row_factory = sqlite3.Row
print(f"[迁移] 已连接 SQLite: {DB_PATH}")


# ── 连接 PostgreSQL ─────────────────────────────────────────
DSN = os.environ.get("DATABASE_URL")
if not DSN:
    print("[迁移] 请设置 DATABASE_URL 环境变量")
    sys.exit(1)

import psycopg2
pg_conn = psycopg2.connect(DSN)
pg_conn.autocommit = False
cur = pg_conn.cursor()
print(f"[迁移] 已连接 PostgreSQL")


# ── 建表 ──────────────────────────────────────────────────────
print("[迁移] 创建表结构...")
cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id          TEXT PRIMARY KEY,
        status      TEXT DEFAULT 'pending',
        filename    TEXT,
        progress    TEXT DEFAULT '',
        video_path  TEXT DEFAULT '',
        error       TEXT DEFAULT '',
        created_at  DOUBLE PRECISION,
        updated_at  DOUBLE PRECISION,
        client_ip   TEXT DEFAULT ''
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token     TEXT PRIMARY KEY,
        user_id   TEXT NOT NULL,
        created_at DOUBLE PRECISION
    )
""")
pg_conn.commit()


# ── 迁移 tasks ────────────────────────────────────────────────
print("[迁移] 迁移 tasks 表...")
sqlite_rows = sqlite_conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
inserted = 0
for row in sqlite_rows:
    r = dict(row)
    try:
        cur.execute(
            "INSERT INTO tasks (id, status, filename, progress, video_path, error, created_at, updated_at, client_ip) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET "
            "status=EXCLUDED.status, filename=EXCLUDED.filename, progress=EXCLUDED.progress, "
            "video_path=EXCLUDED.video_path, error=EXCLUDED.error, "
            "created_at=EXCLUDED.created_at, updated_at=EXCLUDED.updated_at, client_ip=EXCLUDED.client_ip",
            (r["id"], r["status"], r["filename"], r["progress"], r["video_path"],
             r["error"], r["created_at"], r["updated_at"], r.get("client_ip", "")),
        )
        inserted += 1
    except Exception as e:
        print(f"[迁移] 跳过 tasks {r['id']}: {e}")
pg_conn.commit()
print(f"[迁移] tasks 表完成: {inserted}/{len(sqlite_rows)} 条")


# ── 迁移 sessions ─────────────────────────────────────────────
print("[迁移] 迁移 sessions 表...")
sqlite_rows = sqlite_conn.execute("SELECT * FROM sessions ORDER BY created_at").fetchall()
inserted = 0
for row in sqlite_rows:
    r = dict(row)
    try:
        cur.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (%s,%s,%s) "
            "ON CONFLICT (token) DO UPDATE SET user_id=EXCLUDED.user_id, created_at=EXCLUDED.created_at",
            (r["token"], r["user_id"], r["created_at"]),
        )
        inserted += 1
    except Exception as e:
        print(f"[迁移] 跳过 sessions {r['token'][:12]}...: {e}")
pg_conn.commit()
print(f"[迁移] sessions 表完成: {inserted}/{len(sqlite_rows)} 条")


# ── 清理 ──────────────────────────────────────────────────────
sqlite_conn.close()
cur.close()
pg_conn.close()
print("[迁移] 迁移完成")
