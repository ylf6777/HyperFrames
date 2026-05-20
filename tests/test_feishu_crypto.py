"""密码哈希测试 — 从 feishu_db 导入哈希函数测试"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.feishu_db import _hash_password, _verify_password


class TestPasswordHashing:
    def test_hash_and_verify(self):
        hashed = _hash_password("my_password123")
        # 格式: salt$hash
        assert "$" in hashed
        salt, h = hashed.split("$", 1)
        assert len(salt) == 16  # 8 字节 hex = 16 字符
        assert len(h) == 64     # SHA-256 hex = 64 字符

        assert _verify_password("my_password123", hashed) is True

    def test_wrong_password(self):
        hashed = _hash_password("correct_password")
        assert _verify_password("wrong_password", hashed) is False

    def test_empty_password(self):
        hashed = _hash_password("")
        assert _verify_password("", hashed) is True
        assert _verify_password("x", hashed) is False

    def test_invalid_format(self):
        # 没有 $ 分隔符的存储值
        assert _verify_password("pwd", "invalid_hash_format") is False
        assert _verify_password("pwd", "") is False

    def test_unique_salts(self):
        """每次哈希应产生不同的 salt（相同密码的哈希值不同）"""
        h1 = _hash_password("same_password")
        h2 = _hash_password("same_password")
        assert h1 != h2

        s1 = h1.split("$")[0]
        s2 = h2.split("$")[0]
        assert s1 != s2
