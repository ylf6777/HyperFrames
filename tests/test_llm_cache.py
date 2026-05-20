"""LLM 缓存测试 — 基于文件的 JSON 缓存"""
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.llm import LLMCache


class TestLLMCache:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp(prefix="test_llm_cache_")
        self.cache = LLMCache(cache_dir=self.tmp)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_miss_then_hit(self):
        # 第一次应该 miss
        result = self.cache.get("hello world", "model-v1")
        assert result is None

        # 写入
        self.cache.put("hello world", "model-v1", "script content", "<html>content</html>")

        # 第二次应该 hit
        result = self.cache.get("hello world", "model-v1")
        assert result is not None
        script, html = result
        assert script == "script content"
        assert html == "<html>content</html>"

    def test_different_text_different_key(self):
        self.cache.put("text1", "model-v1", "s1", "h1")
        self.cache.put("text2", "model-v1", "s2", "h2")

        r1 = self.cache.get("text1", "model-v1")
        r2 = self.cache.get("text2", "model-v1")
        assert r1 == ("s1", "h1")
        assert r2 == ("s2", "h2")

    def test_different_model_different_key(self):
        self.cache.put("same text", "model-a", "sa", "ha")
        self.cache.put("same text", "model-b", "sb", "hb")

        r1 = self.cache.get("same text", "model-a")
        r2 = self.cache.get("same text", "model-b")
        assert r1 == ("sa", "ha")
        assert r2 == ("sb", "hb")

    def test_stats(self):
        self.cache.put("stats_test", "m1", "s", "h")
        stats = self.cache.stats()
        assert stats["count"] >= 1
        assert stats["size_bytes"] > 0
        assert stats["ttl_days"] > 0
        assert stats["cache_dir"] == self.tmp

    def test_delete_entry(self):
        self.cache.put("del_test", "m1", "s", "h")
        entries = self.cache.list_entries()
        key = entries[0]["key"]
        assert self.cache.delete(key) is True
        assert self.cache.delete("nonexistent_key") is False

    def test_clear(self):
        self.cache.put("clear1", "m1", "s", "h")
        self.cache.put("clear2", "m1", "s2", "h2")
        self.cache.clear()
        assert self.cache.stats()["count"] == 0
