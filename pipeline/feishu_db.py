"""
feishu_db.py — 飞书多维表格作为用户数据库
===========================================

用法:
    from pipeline.feishu_db import create_user, login, get_user

    # 注册
    u = create_user("账号", "密码", nickname="昵称")

    # 登录
    u = login("账号", "密码", ip="客户端IP")
"""

import os
import time
import uuid
import hashlib
import secrets
import urllib.parse
import threading

import requests

# ── 配置（优先读环境变量，否则用你给我的值）──
APP_ID = os.environ.get("FEISHU_APP_ID", "cli_aa87eac58f389bb3")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "J5GanVtnsJDM2pAe473XybC1NYH2SPD2")
BASE_TOKEN = os.environ.get("FEISHU_BASE_TOKEN", "YH8ibNRPgaQjF0sj2jQcPayZnWh")
TABLE_ID = os.environ.get("FEISHU_TABLE_ID", "tblo4tibU667rtnr")

# ── 连接与会话（复用 TCP 连接，减少握手延迟）──
_HTTP = requests.Session()
_HTTP.headers.update({"Content-Type": "application/json; charset=utf-8"})

# ── 用户缓存（避免重复查飞书，TTL 30 秒）──
_USER_CACHE: dict[str, tuple[float, dict]] = {}  # user_id/account -> (expires_at, user_dict)
_CACHE_TTL = 30


# ── 英中字段名映射（update_user 支持英文名）
FIELD_MAP = {
    "nickname": "昵称",
    "phone": "手机号",
    "email": "邮箱",
    "member_level": "会员等级",
    "remaining_points": "剩余算力(秒)",
    "remaining_count": "剩余次数",
    "total_recharge": "累计充值",
    "expire_time": "过期时间",
    "status": "状态",
    "resolution": "默认分辨率",
    "fps": "默认帧率",
    "export_format": "导出格式",
    "password": "密码",
}

_TOKEN = None
_TOKEN_EXPIRE = 0


# ── 内部工具 ────────────────────────────────────────────────

def _get_token() -> str:
    """获取 tenant_access_token（带缓存）"""
    global _TOKEN, _TOKEN_EXPIRE
    if _TOKEN and time.time() < _TOKEN_EXPIRE - 60:
        return _TOKEN
    resp = _HTTP.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"获取飞书 token 失败: {data.get('msg')}")
    _TOKEN = data["tenant_access_token"]
    _TOKEN_EXPIRE = time.time() + data.get("expire", 7200)
    return _TOKEN


def _request(method: str, path: str, json_data: dict | None = None) -> dict:
    """调用飞书 Open API（连接复用）"""
    token = _get_token()
    url = f"https://open.feishu.cn/open-apis{path}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = _HTTP.request(method, url, json=json_data, headers=headers, timeout=15)
    data = resp.json()
    code = data.get("code", -1)
    if code != 0:
        raise Exception(f"飞书 API 错误 [{code}]: {data.get('msg', 'unknown')}")
    return data.get("data", {})


def _hash_password(password: str) -> str:
    """SHA-256 加盐哈希"""
    salt = secrets.token_hex(8)
    h = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${h}"


def _verify_password(password: str, stored: str) -> bool:
    if "$" not in stored:
        return False
    salt, h = stored.split("$", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == h


def _record_to_user(record: dict) -> dict:
    """飞书记录 → 用户字典（去掉密码、只暴露安全字段）"""
    f = record.get("fields", {})
    return {
        "record_id": record.get("record_id", ""),
        "user_id": f.get("用户ID", ""),
        "account": f.get("账号", ""),
        "nickname": f.get("昵称", ""),
        "phone": f.get("手机号", ""),
        "email": f.get("邮箱", ""),
        "member_level": f.get("会员等级", ""),
        "remaining_points": _num(f.get("剩余算力(秒)", 0)),
        "remaining_count": _num(f.get("剩余次数", 0)),
        "total_recharge": _num(f.get("累计充值", 0)),
        "expire_time": f.get("过期时间", ""),
        "register_time": f.get("注册时间", ""),
        "last_ip": f.get("最后登录IP", ""),
        "status": f.get("状态", "正常"),
        "resolution": f.get("默认分辨率", ""),
        "fps": f.get("默认帧率", ""),
        "export_format": f.get("导出格式", ""),
    }


def _num(v) -> int | float:
    """飞书返回的数字可能是字符串，统一转数字"""
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return 0
    return 0


# ── 缓存 ──────────────────────────────────────────────────

def _cache_set(user_id: str, user: dict):
    _USER_CACHE[user_id] = (time.time() + _CACHE_TTL, user)


def _cache_get(user_id: str) -> dict | None:
    entry = _USER_CACHE.get(user_id)
    if entry and time.time() < entry[0]:
        return entry[1]
    _USER_CACHE.pop(user_id, None)
    return None


def _cache_clear():
    _USER_CACHE.clear()


# ── 公开 API ────────────────────────────────────────────────

def search_records(field_name: str, value: str, page_size: int = 1) -> list:
    """按字段精确搜索记录（用 filter 公式）"""
    # 转义值中的引号
    safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
    formula = f'CurrentValue.{field_name} = "{safe_value}"'
    path = f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records?page_size={page_size}&filter={urllib.parse.quote(formula)}"
    data = _request("GET", path)
    return data.get("items", [])


def create_user(account: str, password: str, ip: str = "", **extra) -> dict:
    """注册新用户（含账号、手机号重复检查）"""
    existing = search_records("账号", account)
    if existing:
        raise ValueError(f"账号 {account} 已存在")
    phone = extra.get("phone", "")
    if phone:
        existing_phone = search_records("手机号", phone)
        if existing_phone:
            raise ValueError(f"手机号 {phone} 已被其他账号绑定")

    user_id = "U" + uuid.uuid4().hex[:8].upper()
    now_ms = int(time.time() * 1000)

    fields = {
        "用户ID": user_id,
        "账号": account,
        "密码": _hash_password(password),
        "昵称": extra.get("nickname", account),
        "手机号": extra.get("phone", ""),
        "邮箱": extra.get("email", ""),
        "会员等级": "普通",
        "剩余算力(秒)": 0,
        "剩余次数": 3,
        "累计充值": 0,
        "注册时间": now_ms,
        "最后登录IP": ip,
        "状态": "正常",
        "默认分辨率": "720p",
        "默认帧率": "24",
        "导出格式": "MP4",
    }
    fields = {k: v for k, v in fields.items() if v != "" and v is not None}

    data = _request(
        "POST",
        f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records",
        {"fields": fields},
    )
    return _record_to_user(data.get("record", {}))


def login(account: str, password: str, ip: str = "") -> dict | None:
    """登录验证，成功返回用户信息（IP 异步更新，不阻塞返回）"""
    # 先查账号缓存（避免重复调用飞书 API）
    cached = _cache_get(f"account:{account}")
    if cached:
        stored_pwd = cached.get("_password", "")
        if stored_pwd and _verify_password(password, stored_pwd):
            user = {k: v for k, v in cached.items() if k != "_password"}
            _cache_set(user["user_id"], user)
            return user
        return None

    records = search_records("账号", account)
    if not records:
        return None

    record = records[0]
    fields = record.get("fields", {})
    stored = fields.get("密码", "")
    if not _verify_password(password, stored):
        return None

    user = _record_to_user(record)

    # 写入缓存（含密码字段供下次验证，用户缓存不暴露密码）
    cache_entry = dict(user)
    cache_entry["_password"] = fields.get("密码", "")
    _cache_set(f"account:{account}", cache_entry)
    _cache_set(user["user_id"], user)

    # IP 更新放到后台线程，不阻塞响应
    if ip:
        rid = record["record_id"]
        threading.Thread(
            target=lambda: _request(
                "PUT",
                f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{rid}",
                {"fields": {"最后登录IP": ip}},
            ),
            daemon=True,
        ).start()

    return user


def get_user(user_id: str) -> dict | None:
    """按用户ID查询（带 10 秒缓存）"""
    cached = _cache_get(user_id)
    if cached:
        return cached
    records = search_records("用户ID", user_id)
    if not records:
        return None
    user = _record_to_user(records[0])
    _cache_set(user_id, user)
    return user


def update_user(user_id: str, **fields) -> dict:
    """更新用户字段（密码除外）。支持英文和中文字段名。"""
    records = search_records("用户ID", user_id)
    if not records:
        raise ValueError(f"用户 {user_id} 不存在")

    # 英文名 → 中文名
    mapped = {}
    for k, v in fields.items():
        cn = FIELD_MAP.get(k, k)
        mapped[cn] = v

    mapped.pop("密码", None)
    mapped.pop("用户ID", None)

    _request(
        "PUT",
        f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records/{records[0]['record_id']}",
        {"fields": mapped},
    )
    # 清除缓存，下次读取时重新从飞书获取
    _cache_clear()
    return get_user(user_id)


def list_users(page_size: int = 50) -> list[dict]:
    """列出所有用户"""
    data = _request(
        "GET",
        f"/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}/records?page_size={page_size}",
    )
    items = data.get("items", [])
    return [_record_to_user(item) for item in items if item.get("fields", {}).get("用户ID")]
