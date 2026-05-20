"""
工具函数：颜色输出、命令执行、项目目录查找
"""

import os
import sys
import shutil
import subprocess
import threading
from pathlib import Path

HYPERFRAMES_VERSION = os.environ.get("HYPERFRAMES_VERSION", "0.6.6")

# ── GBK 兼容输出 ──
# Windows 重定向 stdout 到文件时默认用 GBK，Unicode 符号会报错
_ENC = getattr(sys.stdout, "encoding", "") or ""
_USE_ASCII = _ENC.upper() in ("GBK", "GB2312", "GB18030")

_SYMBOLS = {
    "info": ">" if _USE_ASCII else "▶",
    "ok": "v" if _USE_ASCII else "✔",
    "warn": "!" if _USE_ASCII else "⚠",
    "err": "x" if _USE_ASCII else "✘",
    "bar": "-" if _USE_ASCII else "─",
}


def _safe_print(*args, **kw):
    """打印时捕获 UnicodeEncodeError，自动降级"""
    try:
        print(*args, **kw)
    except UnicodeEncodeError:
        # 降级：移除 ANSI 和 Unicode 符号，只打纯文本
        plain = " ".join(str(a) for a in args)
        import re
        plain = re.sub(r"\033\[[0-9;]*m", "", plain)
        try:
            print(plain.encode("ascii", errors="replace").decode("ascii"), **kw)
        except Exception:
            pass  # 实在不行就放弃


class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def info(msg):
    _safe_print(f"{Color.CYAN}{_SYMBOLS['info']}{Color.RESET} {msg}")


def success(msg):
    _safe_print(f"{Color.GREEN}{_SYMBOLS['ok']}{Color.RESET} {msg}")


def warn(msg):
    _safe_print(f"{Color.YELLOW}{_SYMBOLS['warn']}{Color.RESET} {msg}")


def error(msg):
    _safe_print(f"{Color.RED}{_SYMBOLS['err']}{Color.RESET} {msg}")


def step(n, total, msg):
    _safe_print(f"\n{Color.BOLD}[{n}/{total}] {msg}{Color.RESET}")
    _safe_print(f"  {Color.DIM}{_SYMBOLS['bar'] * 50}{Color.RESET}")


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


def sanitize_filename(name: str, max_len: int = 128) -> str:
    """消毒文件名，移除路径穿越和危险字符，仅保留安全的文件名部分。"""
    # 只取文件名部分（去掉目录路径）
    name = Path(name).name
    # 替换 Windows/Linux 路径分隔符和遍历序列
    unsafe = set('<>:"/\\|?*')
    safe = "".join(c if c not in unsafe else "_" for c in name)
    # 限制长度
    return safe[:max_len]


def check_disk_space(path: str | Path, min_free_mb: int = 500) -> tuple[bool, int]:
    """检查磁盘剩余空间是否 >= min_free_mb，返回 (是否充足, 剩余MB)"""
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free // (1024 * 1024)
        return (free_mb >= min_free_mb, free_mb)
    except Exception:
        return (True, -1)  # 无法检查时默认放行


_TEMPLATE_DIR: str | None = None
_TEMPLATE_LOCK = threading.Lock()


def ensure_template(project_base_dir: str | Path) -> str:
    """确保共享模板存在（全局只 init 一次），返回模板路径"""
    base = Path(project_base_dir)
    template_dir = base / "_server_data" / "template"

    if not template_dir.exists():
        info("创建共享 HyperFrames 模板（仅一次）...")
        template_dir.mkdir(parents=True, exist_ok=True)
        result = run_command(
            ["npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "init", "template"],
            cwd=str(template_dir.parent),
            desc="模板初始化",
            timeout=120,
        )
        if result:
            success("共享模板创建完成")
        else:
            warn("模板初始化可能不完整")

    return str(template_dir)


def find_project_dir(project_name: str, base_dir: str | None = None) -> str:
    """查找项目目录，不存在则从共享模板创建（无 node_modules / npm install）。"""
    base = Path(base_dir) if base_dir else Path.cwd()
    project_path = base / project_name

    if not project_path.exists():
        project_path.mkdir(parents=True, exist_ok=True)

        # 从共享模板复制 hyperframes.json（tiny, ~300B）
        global _TEMPLATE_DIR
        if _TEMPLATE_DIR is None:
            with _TEMPLATE_LOCK:
                if _TEMPLATE_DIR is None:
                    _TEMPLATE_DIR = ensure_template(base)
        tmpl = Path(_TEMPLATE_DIR)
        for f in ("hyperframes.json",):
            src = tmpl / f
            if src.exists():
                shutil.copy2(str(src), str(project_path / f))

        info(f"项目目录已创建: {project_path}")

    return str(project_path)


def remove_project_dir(project_dir: str):
    """删除项目目录（服务器临时任务用）。"""
    try:
        shutil.rmtree(project_dir, ignore_errors=True)
    except Exception:
        pass


def check_env(role: str = "server"):
    """启动时校验必填环境变量，缺少则输出错误并退出

    role: 'server' | 'worker'
    """
    errors = []
    warnings = []

    # 所有角色都需要的通用校验
    db_type = os.environ.get("DB_TYPE", "sqlite")
    if db_type == "postgres" and not os.environ.get("DATABASE_URL"):
        errors.append("DB_TYPE=postgres 但 DATABASE_URL 未设置")

    storage = os.environ.get("STORAGE_BACKEND", "local")
    if storage == "s3":
        for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"):
            if k not in os.environ:
                errors.append(f"S3 存储缺少 {k}")

    # Worker 专用校验
    if role == "worker":
        if not os.environ.get("HYPERFRAMES_API_KEY"):
            errors.append("缺少 HYPERFRAMES_API_KEY，视频生成将失败")

    # 飞书（可选，只在配置了部分变量时检查完整性）
    feishu_keys = ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_BASE_TOKEN", "FEISHU_TABLE_ID")
    configured_feishu = [k for k in feishu_keys if os.environ.get(k)]
    if configured_feishu and len(configured_feishu) < len(feishu_keys):
        missing = [k for k in feishu_keys if k not in configured_feishu]
        warnings.append(f"飞书配置不完整，缺少: {', '.join(missing)}")

    if errors:
        print("=" * 50)
        print("  环境变量检查失败，请配置以下项后重试：")
        for e in errors:
            print(f"    - {e}")
        print("=" * 50)
        sys.exit(1)

    for w in warnings:
        print(f"[启动警告] {w}")
