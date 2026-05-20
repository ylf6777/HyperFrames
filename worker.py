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
import shutil
import argparse
from pathlib import Path

# 确保能找到 pipeline 包
_BASE = Path(__file__).resolve().parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from pipeline import generate_video
from pipeline.utils import sanitize_filename, check_disk_space, remove_project_dir, info, success, warn, error
from pipeline.db import (
    DATA_DIR, TASKS_DIR, VIDEOS_DIR, DOCS_DIR,
    db_get_task, db_update_task, db_pending_tasks, db_claim_task,
    recover_orphaned_tasks,
)


# ── 配置 ──────────────────────────────────────────────────
MAX_CONCURRENT = int(os.environ.get("MAX_CONCURRENT", "2"))
WORKER_SLEEP = int(os.environ.get("WORKER_SLEEP", "3"))

# ── 全局退出信号 ──
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    print(f"\n[worker] 收到信号 {signum}，正在优雅退出...")
    _shutdown = True


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ── 任务执行 ────────────────────────────────────────────────
def run_task(task_id: str):
    """执行单个生成任务"""
    task = db_get_task(task_id)
    if not task:
        warn(f"[worker] 任务 {task_id} 不存在")
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
            info(f"[worker] 任务 {task_id} 已取消")
            return
        elif result["success"] and result["video_path"]:
            video_dst = VIDEOS_DIR / f"{task_id}.mp4"
            try:
                shutil.copy2(result["video_path"], str(video_dst))
                video_path = str(video_dst)
            except Exception as e:
                print(f"[worker] 复制视频到存储目录失败: {e}")
                video_path = result["video_path"]
            db_update_task(
                task_id,
                status="completed",
                video_path=video_path,
                progress="完成",
                updated_at=time.time(),
            )
            success(f"[worker] 任务 {task_id} 完成")
        else:
            db_update_task(
                task_id,
                status="failed",
                error="生成失败，详情请查看服务端日志",
                progress="失败",
                updated_at=time.time(),
            )
            error(f"[worker] 任务 {task_id} 失败")
    except Exception as e:
        db_update_task(
            task_id,
            status="failed",
            error=str(e),
            progress="失败",
            updated_at=time.time(),
        )
        error(f"[worker] 任务 {task_id} 异常: {e}")
    finally:
        # 清理上传的源文档
        try:
            doc_path = str((DOCS_DIR / f"{task_id}_{safe_name}").resolve())
            if os.path.isfile(doc_path):
                os.remove(doc_path)
                info(f"[worker] 已清理上传文档: {os.path.basename(doc_path)}")
        except Exception as e:
            warn(f"[worker] 清理上传文档失败: {e}")
        # 清理临时项目目录
        task_project = str(TASKS_DIR / f"task-{task_id}")
        remove_project_dir(task_project)


# ── 主循环 ──────────────────────────────────────────────────
def main_loop():
    """轮询 pending 任务，用进程内抢占避免重复消费"""
    print(f"[worker] 启动（最多 {MAX_CONCURRENT} 个并行任务，轮询间隔 {WORKER_SLEEP}s）")
    print(f"[worker] 按 Ctrl+C 优雅退出\n")

    # 启动时恢复孤儿任务
    recover_orphaned_tasks()

    running: dict[str, dict] = {}  # task_id -> {"process": ..., "started": ...}

    while not _shutdown:
        try:
            # 清理已完成/失败的子进程记录
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
                    info(f"[worker] 开始任务 {tid}: {task['filename']}")

                    # 使用线程执行，不阻塞轮询
                    import threading
                    t = threading.Thread(target=run_task, args=(tid,), daemon=True)
                    t.start()
                    running[tid] = {"process": t, "started": time.time()}

        except Exception as e:
            print(f"[worker] 轮询异常: {e}")

        # 逐秒检查 _shutdown，避免退出延迟
        for _ in range(WORKER_SLEEP):
            if _shutdown:
                break
            time.sleep(1)

    # ── 优雅退出 ──
    print(f"[worker] 正在等待 {len(running)} 个运行中的任务...")
    wait_start = time.time()
    for tid, v in running.items():
        v["process"].join(timeout=30)
        elapsed = time.time() - wait_start
        if elapsed > 30:
            print(f"[worker] 等待超时，{len(running)} 个任务强制结束")
            break
    print("[worker] 已退出")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="独立后台 Worker 进程")
    parser.add_argument("--concurrent", type=int, default=MAX_CONCURRENT, help="并行任务数")
    args = parser.parse_args()
    MAX_CONCURRENT = args.concurrent
    main_loop()
