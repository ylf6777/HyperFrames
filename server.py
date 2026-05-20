"""
server.py — 文档→视频 API 服务
================================
FastAPI + SQLite，Worker 已拆分为独立进程。
支持飞书多维表格用户认证。

启动:  uvicorn server:app --host 0.0.0.0 --port 8000
Worker: python worker.py
"""

import os
import re
import random
import time
import uuid
import sqlite3
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Depends, Header
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from pipeline.db import (
    DATA_DIR, VIDEOS_DIR, DOCS_DIR, DB_PATH,
    db_get_task, db_update_task, db_create_task,
    count_ip_pending, count_ip_total, count_global,
)
from pipeline.utils import sanitize_filename
from pipeline.llm import LLMCache
from pipeline.feishu_db import create_user, login, get_user, update_user as feishu_update_user


# ── 配置 ───────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))
ALLOW_ORIGINS = os.environ.get("ALLOW_ORIGINS", "*").split(",")

# ── 速率限制配置 ──
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "1"))
RATE_LIMIT_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))
MAX_TASKS_PER_IP_PENDING = int(os.environ.get("MAX_TASKS_PER_IP_PENDING", "2"))
MAX_TASKS_PER_IP_TOTAL = int(os.environ.get("MAX_TASKS_PER_IP_TOTAL", "10"))
MAX_TASKS_GLOBAL = int(os.environ.get("MAX_TASKS_GLOBAL", "100"))


# ── Rate Limiter ────────────────────────────────────────────────────
from collections import defaultdict as _defaultdict


class RateLimiter:
    """滑动窗口 IP 速率限制器"""
    def __init__(self, max_requests: int, window: float):
        self.max_requests = max_requests
        self.window = window
        self._ips: dict[str, list[float]] = _defaultdict(list)

    def _prune(self, ip: str, cutoff: float):
        pruned = [t for t in self._ips.get(ip, []) if t > cutoff]
        if pruned:
            self._ips[ip] = pruned
        else:
            self._ips.pop(ip, None)

    def allow(self, ip: str) -> bool:
        now = time.time()
        self._prune(ip, now - self.window)
        if len(self._ips.get(ip, [])) >= self.max_requests:
            return False
        self._ips[ip].append(now)
        return True

    def remaining(self, ip: str) -> int:
        self._prune(ip, time.time() - self.window)
        active = len(self._ips.get(ip, []))
        return max(0, self.max_requests - active)


_post_limiter = RateLimiter(RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


# ── FastAPI ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：无需启动 Worker（独立进程管理）
    yield
    # 关闭：无需停止 Worker
    pass


app = FastAPI(title="文档→视频生成服务", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 用户会话 ──────────────────────────────────────────────────
# token → user_id 的简单内存映射（重启后失效）
_sessions: dict[str, str] = {}


def _get_current_user(authorization: str = Header("")) -> dict | None:
    """从 Authorization header 解析当前登录用户"""
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    user_id = _sessions.get(token)
    if not user_id:
        return None
    return get_user(user_id)


# ── 验证码 & 邮箱激活 ─────────────────────────────────────────
_verify_codes: dict[str, dict] = {}
_activation_tokens: dict[str, str] = {}
_activated_emails: set[str] = set()  # 已激活邮箱列表

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

import random


def _send_email(to: str, subject: str, body: str):
    """通过 SMTP 发送邮件（不配置则只打印到控制台）"""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        print(f"[auth] SMTP 未配置，邮件内容:\n  To: {to}\n  Subject: {subject}\n  Body: {body}")
        return False
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        print(f"[auth] 邮件已发送到 {to}")
        return True
    except Exception as e:
        print(f"[auth] SMTP 发送失败: {e}")
        return False


@app.post("/api/auth/send-code")
def send_verify_code(payload: dict):
    """发送验证码到手机或邮箱"""
    phone = payload.get("phone", "")
    email = payload.get("email", "")
    target = phone or email
    if not target:
        raise HTTPException(400, "手机号或邮箱不能为空")

    code = str(random.randint(100000, 999999))
    expires = time.time() + 300  # 5 分钟
    _verify_codes[target] = {"code": code, "expires": expires, "verified": False}

    if email:
        _send_email(email, "文生视频 - 验证码", f"您的验证码是：{code}，5 分钟内有效。")
    else:
        print(f"[auth] 验证码: {code}（发给 {phone}）")

    # 开发模式（未配置 SMTP）直接返回验证码，方便调试
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS) or not email:
        return {"success": True, "dev_code": code}

    return {"success": True}


@app.post("/api/auth/verify-code")
def verify_code(payload: dict):
    """验证手机/邮箱验证码"""
    phone = payload.get("phone", "")
    email = payload.get("email", "")
    target = phone or email
    code = payload.get("code", "")
    if not target or not code:
        raise HTTPException(400, "参数不完整")
    entry = _verify_codes.get(target)
    if not entry:
        raise HTTPException(400, "请先发送验证码")
    if time.time() > entry["expires"]:
        _verify_codes.pop(target, None)
        raise HTTPException(400, "验证码已过期，请重新发送")
    if entry["code"] != code:
        raise HTTPException(400, "验证码错误")
    entry["verified"] = True
    return {"success": True, "verified": True}


@app.post("/api/auth/send-activation")
def send_activation(payload: dict):
    """发送邮箱激活链接"""
    email = payload.get("email", "")
    if not email:
        raise HTTPException(400, "邮箱不能为空")
    token = uuid.uuid4().hex
    _activation_tokens[token] = email
    frontend_url = os.environ.get("PUBLIC_URL", "http://localhost:3000")
    link = f"{frontend_url}/activate?token={token}"
    _send_email(email, "文生视频 - 邮箱激活",
                f"请点击以下链接激活您的邮箱：\n\n{link}\n\n链接 30 分钟内有效。")
    print(f"[auth] 激活链接: {link}")
    return {"success": True}


@app.get("/api/auth/activate")
def activate_email(token: str = ""):
    """激活邮箱"""
    email = _activation_tokens.pop(token, None)
    if not email:
        raise HTTPException(400, "激活链接无效或已过期")
    _activated_emails.add(email)
    return {"success": True, "email": email, "message": "邮箱已激活"}


# ── 认证 API ──────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(payload: dict, request: Request = None):
    """注册新用户（支持手机验证码和邮箱激活验证）"""
    account = payload.get("account", "")
    password = payload.get("password", "")
    nickname = payload.get("nickname", "")
    phone = payload.get("phone", "")
    email = payload.get("email", "")
    code = payload.get("code", "")

    if not account or not password:
        raise HTTPException(400, "账号和密码不能为空")
    if len(password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    if not re.match(r'^[a-zA-Z0-9]+$', account):
        raise HTTPException(400, "账号只能包含英文字母和数字")
    if phone:
        if not re.match(r'^1\d{10}$', phone):
            raise HTTPException(400, "手机号格式不正确（11 位，以 1 开头）")

    if phone:
        entry = _verify_codes.get(phone)
        if not entry or not entry.get("verified"):
            raise HTTPException(400, "手机号未验证，请先获取验证码并验证")
        _verify_codes.pop(phone, None)

    if email and email not in _activated_emails:
        raise HTTPException(400, "邮箱未激活，请先通过激活链接激活")

    try:
        user = create_user(
            account, password,
            ip=get_client_ip(request),
            nickname=nickname or account,
            phone=phone,
            email=email,
        )
        return {"success": True, "user_id": user["user_id"], "account": user["account"]}
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/auth/login")
def auth_login(payload: dict, request: Request = None):
    """登录，返回会话 token"""
    account = payload.get("account", "")
    password = payload.get("password", "")
    if not account or not password:
        raise HTTPException(400, "账号和密码不能为空")
    user = login(account, password, ip=get_client_ip(request))
    if not user:
        raise HTTPException(401, "账号或密码错误")

    token = uuid.uuid4().hex
    _sessions[token] = user["user_id"]
    return {"token": token, "user": user}


@app.get("/api/auth/me")
def auth_me(current_user: dict = Depends(_get_current_user)):
    """获取当前登录用户信息"""
    if not current_user:
        raise HTTPException(401, "未登录")
    return current_user


@app.put("/api/auth/me")
def auth_update(fields: dict, current_user: dict = Depends(_get_current_user)):
    """更新当前用户信息"""
    if not current_user:
        raise HTTPException(401, "未登录")
    updated = feishu_update_user(current_user["user_id"], **fields)
    return updated


@app.post("/api/auth/logout")
def auth_logout(authorization: str = Header("")):
    """退出登录"""
    if authorization.startswith("Bearer "):
        _sessions.pop(authorization[7:], None)
    return {"success": True}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/tasks")
async def create_task(file: UploadFile = File(...), request: Request = None):
    """上传文档，创建生成任务"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".doc", ".docx", ".txt", ".pdf"):
        raise HTTPException(400, f"不支持的文件格式: {ext}")

    # 限制文件大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(400, f"文件大小超过 {MAX_FILE_SIZE_MB}MB 限制")

    # ── 速率限制检查 ──
    client_ip = get_client_ip(request)

    if not _post_limiter.allow(client_ip):
        raise HTTPException(
            429,
            f"请求过于频繁，请等待 {RATE_LIMIT_WINDOW} 秒后再试（每 IP 每分钟 {RATE_LIMIT_REQUESTS} 次）",
        )

    pending_count = count_ip_pending(client_ip)
    if pending_count >= MAX_TASKS_PER_IP_PENDING:
        raise HTTPException(
            429,
            f"同 IP 待处理任务过多（{pending_count} ≥ {MAX_TASKS_PER_IP_PENDING}），请等待当前任务完成",
        )

    total_ip = count_ip_total(client_ip)
    if total_ip >= MAX_TASKS_PER_IP_TOTAL:
        raise HTTPException(
            429,
            f"同 IP 总任务数已达上限（{total_ip} ≥ {MAX_TASKS_PER_IP_TOTAL}）",
        )

    total_global = count_global()
    if total_global >= MAX_TASKS_GLOBAL:
        raise HTTPException(
            429,
            f"系统任务总量已达上限（{total_global} ≥ {MAX_TASKS_GLOBAL}）",
        )

    task_id = uuid.uuid4().hex[:12]
    safe_name = sanitize_filename(file.filename)
    db_create_task(task_id, safe_name, client_ip)

    doc_path = (DOCS_DIR / f"{task_id}_{safe_name}").resolve()
    if not str(doc_path).startswith(str(DOCS_DIR.resolve())):
        raise HTTPException(400, "非法文件名")
    doc_path.write_bytes(content)

    return {"task_id": task_id, "status": "pending"}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    """查询任务状态"""
    task = db_get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {
        "task_id": task["id"],
        "status": task["status"],
        "filename": task["filename"],
        "progress": task["progress"],
        "error": task["error"],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    """取消一个正在处理的任务"""
    task = db_get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] not in ("pending", "processing"):
        raise HTTPException(400, f"当前状态不允许取消（{task['status']}）")
    db_update_task(task_id, status="cancelled", progress="已取消", updated_at=time.time())
    return {"task_id": task_id, "status": "cancelled"}


@app.get("/api/videos/{task_id}.mp4")
def get_video(task_id: str):
    """下载生成的视频"""
    task = db_get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] != "completed":
        raise HTTPException(400, "视频尚未生成完成")
    if not task["video_path"] or not os.path.exists(task["video_path"]):
        raise HTTPException(404, "视频文件不存在")

    return FileResponse(
        task["video_path"],
        media_type="video/mp4",
        filename=f"{task_id}.mp4",
    )


@app.get("/api/tasks")
def list_tasks(limit: int = 20):
    """查看最近的任务列表"""
    from pipeline.db import db_list_tasks
    return db_list_tasks(limit)


# ── LLM 缓存管理 ────────────────────────────────────────────────

_llm_cache = LLMCache()


@app.get("/api/cache")
def get_cache():
    """查看 LLM 缓存状态"""
    stats = _llm_cache.stats()
    entries = _llm_cache.list_entries()
    return {"stats": stats, "entries": entries}


@app.delete("/api/cache")
def clear_cache():
    """清空所有 LLM 缓存"""
    _llm_cache.clear()
    return {"status": "ok"}


@app.delete("/api/cache/{key}")
def delete_cache_entry(key: str):
    """删除指定缓存"""
    ok = _llm_cache.delete(key)
    return {"status": "ok" if ok else "not_found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
