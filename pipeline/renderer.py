"""
HyperFrames 视频渲染
"""

import threading
from pathlib import Path

from pipeline.utils import info, warn, error, run_command, HYPERFRAMES_VERSION

# 渲染锁：确保一次只渲染一个视频（GPU/浏览器资源争抢）
_render_lock = threading.Lock()


def _clean_old_renders(project_dir: str):
    """渲染前清理旧 MP4 文件，避免累积占空间"""
    for subdir in ("renders", "output"):
        d = Path(project_dir) / subdir
        if d.exists():
            for f in d.glob("*.mp4"):
                f.unlink(missing_ok=True)


def run_render(project_dir: str) -> Path | None:
    """运行 HyperFrames 渲染，返回 MP4 路径，失败返回 None"""
    info("等待渲染锁（串行执行，避免 GPU 争抢）...")
    _render_lock.acquire()
    try:
        _clean_old_renders(project_dir)

        info("渲染视频（这可能需要几分钟）...")
        # 直接调 npx，不需要 package.json / node_modules
        success_render = run_command(
            ["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "render"],
            cwd=project_dir,
            desc="render",
            timeout=1800,
        )
        if not success_render:
            error("渲染失败")
            return None

        # HyperFrames v0.6.6+ 输出到 renders/，旧版输出到 output/
        for subdir in ("renders", "output"):
            search_dir = Path(project_dir) / subdir
            if search_dir.exists():
                mp4_files = list(search_dir.glob("*.mp4"))
                if mp4_files:
                    return mp4_files[0]

        # 也可能在项目根目录
        mp4_files = list(Path(project_dir).glob("*.mp4"))
        if mp4_files:
            return mp4_files[0]

        warn("未找到输出 MP4 文件")
        return None
    finally:
        _render_lock.release()
