"""utils.py 测试 — 工具函数"""
import os
import tempfile
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.utils import sanitize_filename, check_disk_space, Color


class TestSanitizeFilename:
    def test_basic_filename(self):
        assert sanitize_filename("hello.docx") == "hello.docx"

    def test_remove_path_traversal(self):
        assert "/" not in sanitize_filename("../../etc/passwd")
        assert "\\" not in sanitize_filename("..\\..\\etc\\passwd")
        assert not sanitize_filename("../../etc/passwd").startswith("..")

    def test_only_basename(self):
        result = sanitize_filename("/usr/local/bin/file.txt")
        assert result == "file.txt"

    def test_replace_dangerous_chars(self):
        # Path(name).name 在 Windows 上会把 `\` 当分隔符，只剩下 `\|?*` 部分
        result = sanitize_filename("file<>:\"/\\|?*.txt")
        assert "_" in result  # 危险字符被替换
        assert ".." not in result
        assert "/" not in result
        assert "\\" not in result

    def test_max_length(self):
        long_name = "a" * 200 + ".txt"
        result = sanitize_filename(long_name, max_len=50)
        assert len(result) <= 50

    def test_unicode_filename(self):
        result = sanitize_filename("文件名称.docx")
        assert result == "文件名称.docx"


class TestCheckDiskSpace:
    def test_returns_tuple(self):
        ok, free_mb = check_disk_space(".")
        assert isinstance(ok, bool)
        assert isinstance(free_mb, int)
        assert free_mb > 0  # 当前磁盘肯定有空间

    def test_nonexistent_path(self):
        # 不存在的路径应放行
        ok, free_mb = check_disk_space("/nonexistent/path/12345")
        assert ok is True
        assert free_mb == -1


class TestColor:
    def test_ansi_codes(self):
        assert Color.GREEN.startswith("\033[")
        assert Color.RESET == "\033[0m"
