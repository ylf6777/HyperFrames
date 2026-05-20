"""
storage.py — 视频存储后端抽象（本地 / S3 兼容对象存储）

环境变量:
  STORAGE_BACKEND     local（默认）| s3
  S3_ENDPOINT         S3 兼容存储端点（MinIO / R2 / 阿里云OSS）
  S3_REGION           region（默认 auto）
  S3_ACCESS_KEY       Access Key
  S3_SECRET_KEY       Secret Key
  S3_BUCKET           存储桶名
  S3_PUBLIC_URL       可选，CDN / 公开访问 URL 模板，含 {key} 占位符
                       例: https://cdn.example.com/{key}
  S3_FORCE_PATH_STYLE 是否 path-style 寻址（MinIO 需要 true，默认 false）
"""

import os
import logging

logger = logging.getLogger("storage")

BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()


# ── 本地存储 ──────────────────────────────────────────────


class _LocalStorage:
    """视频存本地 _server_data/videos/"""

    def save(self, local_path: str, task_id: str) -> str:
        import shutil
        from pipeline.db import VIDEOS_DIR

        dst = VIDEOS_DIR / f"{task_id}.mp4"
        shutil.copy2(local_path, str(dst))
        logger.info("视频已保存到本地: %s", dst)
        return str(dst)

    def get_url(self, storage_path: str) -> str:
        return storage_path  # 直接返回本地路径

    def delete(self, storage_path: str):
        try:
            if storage_path and os.path.isfile(storage_path):
                os.remove(storage_path)
        except OSError:
            pass


# ── S3 兼容存储 ────────────────────────────────────────────


class _S3Storage:
    def __init__(self):
        self.endpoint = os.environ["S3_ENDPOINT"]
        self.region = os.environ.get("S3_REGION", "auto")
        self.access_key = os.environ["S3_ACCESS_KEY"]
        self.secret_key = os.environ["S3_SECRET_KEY"]
        self.bucket = os.environ["S3_BUCKET"]
        self.public_url_tpl = os.environ.get("S3_PUBLIC_URL", "")
        self.force_path_style = os.environ.get("S3_FORCE_PATH_STYLE", "").lower() in ("1", "true")

    @property
    def _client(self):
        import boto3
        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            region_name=self.region,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=boto3.session.Config(
                s3={"addressing_style": "path" if self.force_path_style else "virtual"},
                connect_timeout=10,
                read_timeout=30,
            ),
        )

    def save(self, local_path: str, task_id: str) -> str:
        key = f"videos/{task_id}.mp4"
        self._client.upload_file(local_path, self.bucket, key)
        if self.public_url_tpl:
            url = self.public_url_tpl.replace("{key}", key)
            logger.info("视频已上传到 S3: %s", url)
            return url
        # 无公开 URL 时返回 S3 原生地址
        url = f"{self.endpoint.rstrip('/')}/{self.bucket}/{key}"
        logger.info("视频已上传到 S3: %s", url)
        return url

    def get_url(self, storage_path: str) -> str:
        # 已经是一个 HTTP URL
        if storage_path.startswith(("http://", "https://")):
            return storage_path
        # S3 原生路径
        if storage_path.startswith("s3://"):
            key = storage_path.split("/", 3)[-1]
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=3600,
            )
        # 本地路径兜底（不应发生）
        return storage_path

    def delete(self, storage_path: str):
        """从 S3 删除视频"""
        if storage_path.startswith(("http://", "https://")):
            # 从 URL 中提取 key
            key = storage_path.split("/", 3)[-1]  # https://host/bucket/videos/id.mp4
            # 去掉可能的查询参数
            key = key.split("?")[0]
        else:
            return  # 非 URL 格式不处理

        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            logger.warning("S3 删除失败: %s", e)


# ── 工厂 ──────────────────────────────────────────────────


def _create():
    if BACKEND == "s3":
        missing = [k for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET")
                   if k not in os.environ]
        if missing:
            raise RuntimeError(f"S3 存储缺少必填环境变量: {', '.join(missing)}")
        logger.info("存储后端: S3 (%s)", os.environ["S3_ENDPOINT"])
        return _S3Storage()

    logger.info("存储后端: 本地文件系统")
    return _LocalStorage()


_storage = None


def _get():
    global _storage
    if _storage is None:
        _storage = _create()
    return _storage


# ── 公开 API ──────────────────────────────────────────────


def save(local_path: str, task_id: str) -> str:
    """保存视频到存储后端，返回存储路径/URL"""
    return _get().save(local_path, task_id)


def get_url(storage_path: str) -> str:
    """获取视频的可访问 URL（本地返回路径，S3 返回 URL/presigned URL）"""
    return _get().get_url(storage_path)


def delete(storage_path: str):
    """从存储后端删除视频"""
    _get().delete(storage_path)
