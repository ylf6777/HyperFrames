"""
工具函数：颜色输出、命令执行、项目目录查找
"""

import os
import subprocess
from pathlib import Path


class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def info(msg):
    print(f"{Color.CYAN}▶{Color.RESET} {msg}")


def success(msg):
    print(f"{Color.GREEN}✔{Color.RESET} {msg}")


def warn(msg):
    print(f"{Color.YELLOW}⚠{Color.RESET} {msg}")


def error(msg):
    print(f"{Color.RED}✘{Color.RESET} {msg}")


def step(n, total, msg):
    print(f"\n{Color.BOLD}[{n}/{total}] {msg}{Color.RESET}")
    print(f"  {Color.DIM}{'─' * 50}{Color.RESET}")


def run_command(cmd: list[str], cwd: str | None = None, desc: str = "", timeout: int | None = None) -> bool:
    """运行命令并实时输出，返回 True/False 表示成功/失败"""
    prefix = f"[{desc}]" if desc else ""
    info(f"{prefix} 执行: {' '.join(cmd)}")

    # Windows 下 subprocess 找不到 npx/npm（需要 .cmd 扩展名）
    if os.name == "nt" and cmd[0] in ("npx", "npm"):
        cmd[0] = cmd[0] + ".cmd"

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=False,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            if result.stderr:
                print(f"  {Color.DIM}stderr: {result.stderr[:500]}{Color.RESET}")
            return False
        return True
    except subprocess.TimeoutExpired:
        error(f"{prefix} 执行超时")
        return False
    except FileNotFoundError as e:
        error(f"{prefix} 命令未找到: {e}")
        if cmd[0] == "npx":
            warn("尝试手动运行: corepack enable && npm install -g npx")
        return False
    except Exception as e:
        error(f"{prefix} 执行失败: {e}")
        return False


def find_project_dir(project_name: str, base_dir: str | None = None) -> str:
    """查找项目目录，不存在则创建并初始化 HyperFrames 项目"""
    base = Path(base_dir) if base_dir else Path.cwd()
    project_path = base / project_name

    if not project_path.exists():
        info(f"项目目录不存在，创建: {project_path}")
        project_path.mkdir(parents=True, exist_ok=True)
        init_result = run_command(
            ["npx", "--yes", "hyperframes@0.6.6", "init", project_name],
            cwd=str(base),
            desc="hyperframes init",
            timeout=120,
        )
        if not init_result:
            warn("HyperFrames 初始化可能不完整，继续执行...")

    return str(project_path)
