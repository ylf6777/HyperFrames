"""
音频时长读取 / 文本提取与规范化 / 文件 I/O
"""

import json
import os
import re
import subprocess
from pathlib import Path

from pipeline.utils import info, success, warn, error

# 字符白名单（一次构建，全局复用）
_NORM_KEEP: set[str] = set()
for _cp in range(0x4e00, 0xa000):
    _NORM_KEEP.add(chr(_cp))
for _cp in range(0x3000, 0x3040):
    _NORM_KEEP.add(chr(_cp))
for _cp in range(0xff00, 0xfff0):
    _NORM_KEEP.add(chr(_cp))
for _cp in range(0x20, 0x7f):
    _NORM_KEEP.add(chr(_cp))
del _cp


def get_audio_duration(wav_path: str) -> float:
    """读取音频文件时长（秒），降级估算"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", wav_path],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        st = Path(wav_path).stat().st_size
        return st / 44100 / 2


def load_sentence_timestamps(project_dir: str) -> list[dict] | None:
    """加载 word_timestamps.json（edge-tts 句段时间戳）"""
    ts_path = Path(project_dir) / "word_timestamps.json"
    if ts_path.exists():
        try:
            return json.loads(ts_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _extract_scene_texts(html: str, n_scenes: int) -> list[str]:
    """提取每个场景内的所有可见文字（不限元素类型和 class 名）"""
    texts = []
    for i in range(1, n_scenes + 1):
        m = re.search(rf'<div[^>]*?id="scene{i}"[^>]*?>', html)
        if not m:
            texts.append("")
            continue
        start_pos = m.end()
        depth = 1
        pos = start_pos
        while depth > 0:
            no = html.find("<div", pos)
            nc = html.find("</div>", pos)
            if nc < 0:
                break
            if no >= 0 and no < nc:
                depth += 1
                pos = no + 4
            else:
                depth -= 1
                pos = nc + 6
                if depth == 0:
                    scene_html = html[start_pos:nc]
                    text = re.sub(r'<[^>]+>', '，', scene_html)
                    text = re.sub(r'，+', '，', text)
                    text = re.sub(r'\s+', '', text)
                    text = text.strip('，')
                    texts.append(text)
                    break
    return texts


def _norm_text(t: str) -> str:
    """清理文本用于匹配：去空白、统一引号、移除修饰符。"""
    t = re.sub(r'\s+', '', t)
    for a in '""':
        t = t.replace(a, '"')
    for a in "''":
        t = t.replace(a, "'")
    t = re.sub('[﻿️-️]', '', t)
    t = ''.join(c for c in t if c in _NORM_KEEP)
    return t


def _clean_tts_text(text: str) -> str:
    """清理文本，仅保留可朗读的文字（去符号、去图形/emoji）"""
    text = re.sub(r'[—–]+', '，', text)
    text = re.sub(r'[……]+', '。', text)
    text = text.replace('：', '，').replace('；', '，')
    text = re.sub(r'[「」『』""《》<>（）()]', '', text)
    text = re.sub(
        '[\U0001F300-\U0001F9FF'
        '\U0001FA00-\U0001FA6F'
        '\U0001FA70-\U0001FAFF'
        '\U00002B00-\U00002BFF'
        '☀-➿'
        '️-️'
        ']', '', text)
    text = re.sub(r'\s+', '', text)
    text = re.sub(r'([。！？])，', r'\1', text)
    text = re.sub(r'，+', '，', text)
    return text.strip('，')


def write_project_files(project_dir, script_content, html_content):
    """写入 script.txt 和 index.html"""
    script_path = Path(project_dir) / "script.txt"
    html_path = Path(project_dir) / "index.html"
    script_path.write_text(script_content, encoding="utf-8")
    info(f"已写入: {script_path} ({len(script_content)} 字)")
    html_path.write_text(html_content, encoding="utf-8")
    info(f"已写入: {html_path} ({len(html_content)} 字符)")


def sync_script_from_html(project_dir: str) -> bool:
    """从 HTML 场景中提取显示文本，覆盖写入 script.txt（旁白只读画面上的字）"""
    html_path = Path(project_dir) / "index.html"
    script_path = Path(project_dir) / "script.txt"
    if not html_path.exists():
        warn(f"未找到 {html_path}，跳过同步")
        return False

    html_content = html_path.read_text(encoding="utf-8")
    n_scenes = len(re.findall(r'id="scene\d+"', html_content))
    if n_scenes == 0:
        warn("HTML 没有 scene 元素，跳过同步")
        return False

    texts = _extract_scene_texts(html_content, n_scenes)

    paragraphs = []
    for i, t in enumerate(texts):
        if not t.strip():
            continue
        cleaned = _clean_tts_text(t)
        if cleaned:
            paragraphs.append(cleaned)

    if not paragraphs:
        warn("所有场景均为空文本，跳过同步")
        return False

    script = "\n\n".join(paragraphs)
    script_path.write_text(script, encoding="utf-8")
    info(f"已从 HTML 同步旁白文本: {script_path} ({len(script)} 字, {len(paragraphs)} 段)")
    return True
