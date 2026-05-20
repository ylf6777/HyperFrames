"""pipeline 包 — 自动加载 .env 环境变量"""

import os
from pathlib import Path

# ── 自动加载项目根目录的 .env 文件 ──
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _val = _line.split("=", 1)
            _key = _key.strip()
            _val = _val.strip().strip("\"'")
            # 不覆盖已存在的环境变量（显式设置的优先级更高）
            if _key not in os.environ:
                os.environ[_key] = _val

from pipeline.pipeline import generate_video
