#!/usr/bin/env python3
"""
worker.py — 独立后台 Worker 进程
=================================
从 SQLite 数据库轮询 pending 任务，串行执行文档→视频生成。
可与多实例 Server 配合，支持水平扩展。

启动:
  python worker.py                       # 前台运行
  python worker.py --concurrent 3        # 并行处理 3 个任务
  nohup python worker.py > worker.log &  # 后台守护

环境变量:
  MAX_CONCURRENT  并行任务数 (默认 2)
  WORKER_SLEEP    轮询间隔秒数 (默认 3)
"""

import os
import sys
import time
import signal
import logging
import argparse
from pathlib import Path

# 确保能找到 pipeline 包
_BASE = Path(__file__).resolve().parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from pipeline import generate_video
from pipeline.utils import sanitize_filename, check_disk_space, remove_project_dir, check_env
from pipeline.db import (
    DATA_DIR, TASKS_DIR, DOCS_DIR,
    db_get_task, db_update_task, db_pending_tasks, db_claim_task,
    recover_orphaned_tasks, cleanup_old_videos,
)


# ── 日志 ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%m-%d %H:%M:%S",
)
logger = logging.getLogger("worker")


# ── 配置 ──────────────────────────────────────────────────
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
WORKER_SLEEP = int(os.environ.get("WORKER_SLEEP", "3"))
TASK_TIMEOUT = int(os.environ.get("TASK_TIMEOUT", "600"))  # 单个任务超时秒数（默认 10 分钟）

# 启动时校验必填环境变量
check_env(role="worker")

# ── 全局退出信号 ──
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.warning("收到信号 %s，正在优雅退出...", signum)
    _shutdown = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── 任务执行 ────────────────────────────────────────────────
def run_task(task_id: str):
    """执行单个生成任务"""
    task = db_get_task(task_id)
    if not task:
        logger.warning("任务 %s 不存在", task_id)
        return

    safe_name = sanitize_filename(task["filename"])
    doc_path = str((DOCS_DIR / f"{task_id}_{safe_name}").resolve())

    # 磁盘空间检查
    ok, free_mb = check_disk_space(DATA_DIR)
    if not ok:
        db_update_task(
            task_id,
            status="failed",
            error=f"磁盘空间不足（剩余 {free_mb}MB，需要 500MB）",
            progress="失败",
            updated_at=time.time(),
        )
        return

    def on_progress(msg: str):
        db_update_task(task_id, progress=msg, updated_at=time.time())

    def should_cancel():
        t = db_get_task(task_id)
        return t and t.get("status") == "cancelled"

    on_progress("读取文档中...")

    try:
        result = generate_video(
            input_path=doc_path,
            project=f"task-{task_id}",
            base_dir=str(TASKS_DIR),
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

        if result.get("cancelled"):
            db_update_task(
                task_id,
                status="cancelled",
                progress="已取消",
                updated_at=time.time(),
            )
            logger.info("任务 %s 已取消", task_id)
            return
        elif result["success"] and result["video_path"]:
            from pipeline.storage import save as storage_save

            video_path = storage_save(result["video_path"], task_id)
            db_update_task(
                task_id,
                status="completed",
                video_path=video_path,
                progress="完成",
                updated_at=time.time(),
            )
            logger.info("任务 %s 完成", task_id)
        else:
            db_update_task(
                task_id,
                status="failed",
                error=result.get("error", "生成失败，详情请查看服务端日志"),
                progress="失败",
                updated_at=time.time(),
            )
            logger.error("任务 %s 失败", task_id)
    except Exception as e:
        db_update_task(
            task_id,
            status="failed",
            error=str(e),
            progress="失败",
            updated_at=time.time(),
        )
        logger.exception("任务 %s 异常", task_id)
    finally:
        # 清理上传的源文档
        try:
            doc_path = str((DOCS_DIR / f"{task_id}_{safe_name}").resolve())
            if os.path.isfile(doc_path):
                os.remove(doc_path)
                logger.info("已清理上传文档: %s", os.path.basename(doc_path))
        except Exception as e:
            logger.warning("清理上传文档失败: %s", e)
        # 清理临时项目目录
        task_project = str(TASKS_DIR / f"task-{task_id}")
        remove_project_dir(task_project)


# ── 主循环 ──────────────────────────────────────────────────
def main_loop():
    """轮询 pending 任务，用进程内抢占避免重复消费"""
    logger.info("启动（最多 %s 个并行任务，轮询间隔 %ss）", MAX_CONCURRENT, WORKER_SLEEP)
    logger.info("按 Ctrl+C 优雅退出")

    # 启动时恢复孤儿任务
    recover_orphaned_tasks()

    # 启动时清理过期视频（默认保留 7 天）
    try:
        cleaned, freed = cleanup_old_videos(7)
        if cleaned:
            logger.info("启动清理: 删除了 %s 个旧视频，释放 %.1f MB", cleaned, freed / 1024 / 1024)
    except Exception as e:
        logger.warning("启动清理旧视频失败: %s", e)
    _last_cleanup = time.time()

    running: dict[str, dict] = {}  # task_id -> {"process": ..., "started": ...}

    while not _shutdown:
        try:
            # 清理已完成/失败的子进程记录，并检查超时
            now = time.time()
            timed_out = []
            for tid, v in list(running.items()):
                if not v["process"].is_alive():
                    continue
                if now - v["started"] > TASK_TIMEOUT:
                    timed_out.append(tid)
            for tid in timed_out:
                logger.warning("任务 %s 超时（>%ss），标记为失败", tid, TASK_TIMEOUT)
                db_update_task(tid, status="failed", error=f"执行超时（超过 {TASK_TIMEOUT} 秒）", progress="超时", updated_at=time.time())
                del running[tid]
            # 只保留仍在运行的线程
            running = {tid: v for tid, v in running.items() if v["process"].is_alive()}

            # 有空闲槽位才拉取新任务
            free_slots = MAX_CONCURRENT - len(running)
            if free_slots > 0:
                pending = db_pending_tasks(free_slots)
                for task in pending:
                    tid = task["id"]
                    # 原子性抢占
                    if not db_claim_task(tid):
                        continue
                    logger.info("开始任务 %s: %s", tid, task["filename"])

                    # 使用线程执行，不阻塞轮询
                    import threading
                    t = threading.Thread(target=run_task, args=(tid,), daemon=True)
                    t.start()
                    running[tid] = {"process": t, "started": time.time()}

        except Exception as e:
            logger.exception("轮询异常")

        # 写入心跳，供 /api/health 检测 Worker 存活
        try:
            (DATA_DIR / ".worker_heartbeat").write_text(f"{time.time()}\n")
        except Exception:
            pass

        # 每天清理一次过期视频
        if time.time() - _last_cleanup > 86400:
            try:
                cleanup_old_videos(7)
            except Exception as e:
                logger.warning("定期清理旧视频失败: %s", e)
            _last_cleanup = time.time()

        # 逐秒检查 _shutdown，避免退出延迟
        for _ in range(WORKER_SLEEP):
            if _shutdown:
                break
            time.sleep(1)

    # ── 优雅退出 ──
    logger.info("正在等待 %s 个运行中的任务...", len(running))
    wait_start = time.time()
    for tid, v in running.items():
        v["process"].join(timeout=30)
        elapsed = time.time() - wait_start
        if elapsed > 30:
            logger.warning("等待超时，%s 个任务强制结束", len(running))
            break
    logger.info("已退出")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立后台 Worker 进程")
    parser.add_argument("--concurrent", type=int, default=MAX_CONCURRENT, help="并行任务数")
    args = parser.parse_args()
    MAX_CONCURRENT = args.concurrent
    main_loop()
