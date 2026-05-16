"""
HyperFrames 视频渲染
"""

from pathlib import Path

from pipeline.utils import info, success, warn, error, run_command


def _clean_old_renders(project_dir: str):
    """渲染前清理旧 MP4 文件，避免累积占空间"""
    for subdir in ("renders", "output"):
        d = Path(project_dir) / subdir
        if d.exists():
            for f in d.glob("*.mp4"):
                f.unlink(missing_ok=True)


def run_render(project_dir: str) -> Path | None:
    """运行 HyperFrames 渲染，返回 MP4 路径，失败返回 None"""
    # 先清理旧文件，只保留最新渲染结果
    _clean_old_renders(project_dir)

    info("渲染视频（这可能需要几分钟）...")
    success_render = run_command(
        ["npm", "run", "render"],
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
                # 清理后只有一个文件，直接返回
                return mp4_files[0]

    # 也可能在项目根目录
    mp4_files = list(Path(project_dir).glob("*.mp4"))
    if mp4_files:
        return mp4_files[0]

    warn("未找到输出 MP4 文件")
    return None
