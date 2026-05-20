"""server.py API 测试 — 使用 FastAPI TestClient"""
import os
import tempfile
import time
import shutil
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

# ── 每个测试类使用独立临时数据库 ──
import pipeline.db as db


def _setup_test_db():
    """在项目目录内创建临时数据库，避免被系统 temp 清理进程误删"""
    tmp = Path(__file__).resolve().parent.parent / "_test_data" / f"test_server_{int(time.time())}"
    db.DATA_DIR = tmp / "_server_data"
    db.TASKS_DIR = db.DATA_DIR / "tasks"
    db.VIDEOS_DIR = db.DATA_DIR / "videos"
    db.DOCS_DIR = db.DATA_DIR / "docs"
    db.DB_PATH = db.DATA_DIR / "tasks.db"
    for d in (db.DATA_DIR, db.TASKS_DIR, db.VIDEOS_DIR, db.DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    db.init_db()
    return tmp


_tmp_db = _setup_test_db()

import server
from server import app

# 解除速率限制和并发限制，方便测试
server._post_limiter.max_requests = 1000
server.MAX_TASKS_PER_IP_PENDING = 1000

client = TestClient(app)

_test_doc = b"Test document content for video generation."


# ── 防 test_db.py 篡改 db.* 全局变量 ──
@pytest.fixture(autouse=True)
def _reset_db_paths():
    """每个测试前重设 db.* 路径，防止 test_db.py 的 _fresh_db() 覆写"""
    db.DATA_DIR = _tmp_db / "_server_data"
    db.TASKS_DIR = db.DATA_DIR / "tasks"
    db.VIDEOS_DIR = db.DATA_DIR / "videos"
    db.DOCS_DIR = db.DATA_DIR / "docs"
    db.DB_PATH = db.DATA_DIR / "tasks.db"
    # 确保数据库文件存在（test_db.py 的 teardown 可能删除了它）
    for d in (db.DATA_DIR, db.TASKS_DIR, db.VIDEOS_DIR, db.DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    db.init_db()


class TestHealth:
    def test_health_endpoint(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestTaskValidation:
    def test_no_file_returns_422(self):
        resp = client.post("/api/tasks")
        assert resp.status_code == 422

    def test_unsupported_format(self):
        resp = client.post("/api/tasks", files={"file": ("test.exe", b"data", "application/x-msdownload")})
        assert resp.status_code == 400
        assert "不支持" in resp.text

    def test_supported_formats(self):
        """至少一种主流格式能被接受"""
        resp = client.post("/api/tasks", files={"file": ("test.docx", _test_doc, "application/octet-stream")})
        assert resp.status_code in (200, 201), f"docx不被接受: {resp.status_code} {resp.text}"
        resp = client.post("/api/tasks", files={"file": ("test.pdf", _test_doc, "application/octet-stream")})
        assert resp.status_code in (200, 201), f"pdf不被接受: {resp.status_code} {resp.text}"


class TestTaskLifecycle:
    def test_create_and_query(self):
        resp = client.post("/api/tasks", files={"file": ("mydoc.docx", _test_doc, "application/octet-stream")})
        assert resp.status_code in (200, 201), f"创建失败: {resp.status_code} {resp.text}"
        task_id = resp.json()["task_id"]

        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        task = resp.json()
        assert task["task_id"] == task_id
        assert task["status"] == "pending"
        assert task["filename"] == "mydoc.docx"

    def test_get_nonexistent_returns_404(self):
        resp = client.get("/api/tasks/nonexistent_id_12345")
        assert resp.status_code == 404

    def test_cancel_task(self):
        resp = client.post("/api/tasks", files={"file": ("cancel.docx", _test_doc, "application/octet-stream")})
        if resp.status_code != 200:
            pytest.skip(f"create failed ({resp.status_code}), skipping cancel test")
        task_id = resp.json()["task_id"]

        cancel_resp = client.post(f"/api/tasks/{task_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

        # 再次取消应该失败（已取消）
        cancel_resp2 = client.post(f"/api/tasks/{task_id}/cancel")
        assert cancel_resp2.status_code == 400

    def test_list_tasks_paginated(self):
        resp = client.get("/api/tasks?limit=5&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert "total" in data
        assert isinstance(data["tasks"], list)


# ── 清理临时数据库 ──
@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    shutil.rmtree(str(_tmp_db), ignore_errors=True)
