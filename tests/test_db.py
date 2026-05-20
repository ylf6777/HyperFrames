"""db.py 测试 — 每个类使用独立的临时 SQLite 数据库"""
import os
import time
import tempfile
import shutil
import pytest
from pathlib import Path

import pipeline.db as db


def _fresh_db():
    """创建临时数据库目录，重新初始化 db 模块"""
    tmp = Path(tempfile.mkdtemp(prefix="test_db_"))
    db.DATA_DIR = tmp / "_server_data"
    db.TASKS_DIR = db.DATA_DIR / "tasks"
    db.VIDEOS_DIR = db.DATA_DIR / "videos"
    db.DOCS_DIR = db.DATA_DIR / "docs"
    db.DB_PATH = db.DATA_DIR / "tasks.db"
    for d in (db.DATA_DIR, db.TASKS_DIR, db.VIDEOS_DIR, db.DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    db.init_db()
    return tmp


class TestTaskCRUD:
    def setup_method(self):
        self._tmp = _fresh_db()

    def teardown_method(self):
        shutil.rmtree(str(self._tmp), ignore_errors=True)

    def test_create_and_get(self):
        db.db_create_task("task001", "test.docx", "127.0.0.1")
        task = db.db_get_task("task001")
        assert task is not None
        assert task["id"] == "task001"
        assert task["filename"] == "test.docx"
        assert task["status"] == "pending"
        assert task["client_ip"] == "127.0.0.1"

    def test_get_nonexistent(self):
        assert db.db_get_task("nonexistent") is None

    def test_update(self):
        db.db_create_task("task002", "test.pdf", "127.0.0.1")
        db.db_update_task("task002", status="processing", progress="处理中")
        task = db.db_get_task("task002")
        assert task["status"] == "processing"
        assert task["progress"] == "处理中"

    def test_list_tasks(self):
        for i in range(5):
            db.db_create_task(f"list_{i}", f"doc{i}.txt", "127.0.0.1")
        tasks = db.db_list_tasks(limit=3, offset=0)
        assert len(tasks) <= 3
        assert "task_id" in tasks[0]
        assert "filename" in tasks[0]

    def test_list_tasks_with_offset(self):
        for i in range(5):
            db.db_create_task(f"offset_{i}", f"doc{i}.txt", "127.0.0.1")
        all_tasks = db.db_list_tasks(limit=100, offset=0)
        page1 = db.db_list_tasks(limit=2, offset=0)
        page2 = db.db_list_tasks(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["task_id"] != page2[0]["task_id"]

    def test_count_tasks(self):
        for i in range(3):
            db.db_create_task(f"cnt_{i}", f"doc{i}.txt", "127.0.0.1")
        assert db.db_count_tasks() >= 3

    def test_pending_tasks(self):
        db.db_create_task("pend001", "a.docx", "127.0.0.1")
        db.db_create_task("pend002", "b.docx", "127.0.0.1")
        pending = db.db_pending_tasks(10)
        assert len(pending) >= 2
        assert all(t["status"] == "pending" for t in pending)

    def test_claim_task(self):
        db.db_create_task("claim001", "c.docx", "127.0.0.1")
        assert db.db_claim_task("claim001") is True
        assert db.db_claim_task("claim001") is False
        task = db.db_get_task("claim001")
        assert task["status"] == "processing"

    def test_claim_already_claimed(self):
        db.db_create_task("claim002", "c2.docx", "127.0.0.1")
        db.db_claim_task("claim002")
        assert db.db_claim_task("claim002") is False


class TestIPCounters:
    def setup_method(self):
        self._tmp = _fresh_db()

    def teardown_method(self):
        shutil.rmtree(str(self._tmp), ignore_errors=True)

    def test_count_ip_pending(self):
        db.db_create_task("ip001", "f1.docx", "192.168.1.1")
        db.db_create_task("ip002", "f2.docx", "192.168.1.1")
        assert db.count_ip_pending("192.168.1.1") >= 2

    def test_count_ip_total(self):
        db.db_create_task("ip003", "f3.docx", "10.0.0.1")
        assert db.count_ip_total("10.0.0.1") >= 1

    def test_global_count(self):
        db.db_create_task("g001", "g.docx", "10.0.0.1")
        assert db.count_global() >= 1


class TestOrphanRecovery:
    def setup_method(self):
        self._tmp = _fresh_db()

    def teardown_method(self):
        shutil.rmtree(str(self._tmp), ignore_errors=True)

    def test_recover_orphaned(self):
        db.db_create_task("orphan001", "lost.docx", "127.0.0.1")
        db.db_claim_task("orphan001")
        db.recover_orphaned_tasks()
        task = db.db_get_task("orphan001")
        assert task["status"] == "pending"
