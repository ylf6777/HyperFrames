"""
时长自动调整：句段时间戳对齐 + 备用字数比例分配
"""

import json
import os
import re
import subprocess
from pathlib import Path

from pipeline.utils import info, success, warn, error


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
                    # 去掉标签，不同元素间的文字用逗号隔开（产生自然停顿）
                    text = re.sub(r'<[^>]+>', '，', scene_html)
                    text = re.sub(r'，+', '，', text)  # 合并连续逗号
                    text = re.sub(r'\s+', '', text)    # 先清空白
                    text = text.strip('，')            # 再去首尾逗号
                    texts.append(text)
                    break
    return texts


def _norm_text(t: str) -> str:
    """清理文本用于匹配：去空白、统一引号、移除修饰符。"""
    t = re.sub(r'\s+', '', t)
    # 统一引号
    for a in '“”':
        t = t.replace(a, '"')
    for a in '‘’':
        t = t.replace(a, "'")
    # 移除 BOM + 变体选择器
    t = re.sub('[﻿︀-️]', '', t)
    # 仅保留常用文本字符
    keep = set()
    for cp in range(0x4e00, 0xa000):
        keep.add(chr(cp))
    for cp in range(0x3000, 0x3040):
        keep.add(chr(cp))
    for cp in range(0xff00, 0xfff0):
        keep.add(chr(cp))
    for cp in range(0x20, 0x7f):
        keep.add(chr(cp))
    t = ''.join(c for c in t if c in keep)
    return t


def _best_match_prefix(text: str, corpus: str, start: int) -> tuple[int, int] | None:
    """在 corpus[start:] 中查找 text 的最佳前缀匹配，返回 (pos, match_len) 或 None。"""
    if not text or not corpus:
        return None
    best_len, best_pos = 0, -1
    limit = min(start + 200, len(corpus))
    for try_pos in range(start, limit):
        ml = 0
        while (try_pos + ml < len(corpus) and ml < len(text)
               and corpus[try_pos + ml] == text[ml]):
            ml += 1
        if ml > best_len:
            best_len, best_pos = ml, try_pos
        if ml == len(text):
            break
    return (best_pos, best_len) if best_len >= 5 else None


def _text_containment(a: str, b: str) -> float:
    """字符包含率：短文本字符集在长文本字符集中的占比"""
    a_set = set(_norm_text(a))
    b_set = set(_norm_text(b))
    if not a_set or not b_set:
        return 0.0
    shorter = a_set if len(a_set) <= len(b_set) else b_set
    longer = b_set if len(a_set) <= len(b_set) else a_set
    return len(shorter & longer) / len(shorter)


def align_scenes_by_text(
    html: str,
    n_scenes: int,
    sentences: list[dict],
    script_paragraphs: list[str],
) -> list[tuple[float, float]] | None:
    """将场景与 TTS 句段时间戳对齐。

    两步匹配:
    1. 脚本段落 -> TTS 句子（精确/前缀匹配，保证时序正确）
    2. HTML 场景 -> 脚本段落（字符包含率匹配，容忍 LLM 改写）
    """
    if not sentences or not script_paragraphs:
        return None

    # === 阶段1: 脚本段落 -> TTS 句子 ===
    norm_sents = [_norm_text(s["text"]) for s in sentences]
    full_tts = "".join(norm_sents)
    if not full_tts:
        return None

    sent_end = []
    cum = 0
    for ns in norm_sents:
        cum += len(ns)
        sent_end.append(cum)

    def pos_to_sent_idx(p):
        for i, ep in enumerate(sent_end):
            if ep > p:
                return i
        return len(sentences) - 1

    para_times = []
    search_pos = 0

    for para in script_paragraphs:
        norm_para = _norm_text(para)
        if not norm_para:
            para_times.append((0.0, 0.0))  # 占位（标题场景）
            continue

        char_pos = full_tts.find(norm_para, search_pos)
        if char_pos >= 0:
            end_char_pos = char_pos + len(norm_para)
        else:
            best = _best_match_prefix(norm_para, full_tts, search_pos)
            if best is None:
                return None
            char_pos, match_len = best
            end_sent_i = pos_to_sent_idx(char_pos + match_len)
            end_char_pos = sent_end[end_sent_i]

        search_pos = end_char_pos

        start_sent = pos_to_sent_idx(char_pos)
        end_sent = pos_to_sent_idx(max(end_char_pos - 1, 0))

        start = sentences[start_sent]["offset"]
        end = sentences[end_sent]["offset"] + sentences[end_sent]["duration"]
        para_times.append((start, end))

    # === 阶段2: 提取场景文本 ===
    scene_texts = _extract_scene_texts(html, n_scenes)
    if not scene_texts:
        return None

    # === 阶段3: 场景 -> 段落 匹配 ===
    scene_to_para = []
    for si, st in enumerate(scene_texts):
        if not _norm_text(st):
            scene_to_para.append((si, -1))  # 空场景（标题/无旁白）
            continue

        best_para = -1
        best_score = 0.0
        for pi, pt in enumerate(script_paragraphs):
            score = _text_containment(st, pt)
            if score > best_score:
                best_score = score
                best_para = pi

        if best_para < 0 or best_score < 0.15:
            return None

        scene_to_para.append((si, best_para))

    # === 阶段4: 分配时间 ===
    para_scenes = {}
    for si, pi in scene_to_para:
        if pi not in para_scenes:
            para_scenes[pi] = []
        para_scenes[pi].append(si)

    result = [(0.0, 0.0)] * n_scenes

    for pi, scene_indices in para_scenes.items():
        if pi == -1:
            for si in scene_indices:
                result[si] = (0.0, 3.5)
            continue

        p_start, p_end = para_times[pi]
        p_dur = p_end - p_start

        if len(scene_indices) == 1:
            result[scene_indices[0]] = (p_start, p_end)
        else:
            # 多个场景共享一段，按字符数比例分割
            ch = [len(_norm_text(scene_texts[si])) for si in scene_indices]
            total = sum(ch) or 1
            seg_start = p_start
            for j, si in enumerate(scene_indices):
                ratio = ch[j] / total
                seg_end = seg_start + p_dur * ratio if j < len(scene_indices) - 1 else p_end
                result[si] = (seg_start, seg_end)
                seg_start = seg_end

    return result


def _fallback_durations(audio_dur, n_scenes, chars_per_scene, has_title_scene, pause):
    """字数比例分配降级方案"""
    speech_dur = audio_dur - pause * n_scenes
    speech_dur = max(speech_dur, audio_dur * 0.5)  # 保底：纯说话时间不低于总时长 50%
    total_chars = sum(chars_per_scene) or 1

    durations = []
    times = []
    for i, c in enumerate(chars_per_scene):
        if c == 0 and has_title_scene and i == 0:
            sd = 3.5
            times.append((0, 3.5))
        else:
            sd = max(c / total_chars * speech_dur + pause, 1.5)
            times.append((0, sd))
        durations.append(round(sd, 1))

    return durations, times


def write_project_files(project_dir, script_content, html_content):
    """写入 script.txt 和 index.html"""
    script_path = Path(project_dir) / "script.txt"
    html_path = Path(project_dir) / "index.html"
    script_path.write_text(script_content, encoding="utf-8")
    info(f"已写入: {script_path} ({len(script_content)} 字)")
    html_path.write_text(html_content, encoding="utf-8")
    info(f"已写入: {html_path} ({len(html_content)} 字符)")


def _clean_tts_text(text: str) -> str:
    """清理文本，仅保留可朗读的文字（去符号、去图形/emoji）"""
    # 破折号 → 逗号（TTS 可能读"破折号"）
    text = re.sub(r'[—–]+', '，', text)
    # 省略号 → 句号
    text = re.sub(r'[……]+', '。', text)
    # 冒号/分号 → 逗号
    text = text.replace('：', '，').replace('；', '，')
    # 移除 TTS 会出声朗读的符号（书名号、引号、括号）
    text = re.sub(r'[「」『』""《》<>（）()]', '', text)
    # 移除 emoji / 图形字符
    text = re.sub(
        '[\U0001F300-\U0001F9FF'        # Misc symbols + emoji (U+1F300-1F9FF)
        '\U0001FA00-\U0001FA6F'         # Chess symbols (U+1FA00-1FA6F)
        '\U0001FA70-\U0001FAFF'         # Symbols Extended-A (U+1FA70-1FAFF)
        '☀-➿'                 # Misc symbols + dingbats (U+2600-27BF)
        '︀-️'                 # Variation selectors
        ']', '', text)
    # 移除多余空白
    text = re.sub(r'\s+', '', text)
    # 去掉句尾标点后的多余逗号（eg. "。，吃饭" → "。吃饭"）
    text = re.sub(r'([。！？])，', r'\1', text)
    # 合并 emoji/符号删除后产生的连续逗号
    text = re.sub(r'，+', '，', text)
    return text.strip('，')


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

    # 过滤空场景，清理符号
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


def _extract_gsap_positions(html, scene_id):
    """提取某个场景的所有 GSAP 位置参数"""
    times = []
    pat = (
        r"tl\.(?:from|to)\s*\(\s*['\"]"
        + re.escape(scene_id)
        + r"[^'\"]*['\"][^{}]*\{[^}]*\}\s*,\s*([\d.]+)"
    )
    for m in re.finditer(pat, html):
        try:
            times.append(float(m.group(1)))
        except ValueError:
            pass
    return times


def adjust_timing(project_dir):
    """根据 TTS 实际时长 + 句段时间戳重新分配场景时间"""
    script_path = Path(project_dir) / "script.txt"
    html_path = Path(project_dir) / "index.html"
    wav_path = Path(project_dir) / "narration.wav"

    script = script_path.read_text(encoding="utf-8")
    raw_scenes = [s.strip() for s in script.split("\n\n") if s.strip()]
    if not raw_scenes:
        warn("脚本无法按空行分场景，跳过时长调整")
        return

    html_content = html_path.read_text(encoding="utf-8") if html_path.exists() else ""

    html_scene_count = len(re.findall(r'id="scene\d+"', html_content))
    if html_scene_count == 0:
        html_scene_count = len(re.findall(r'id="scene-s\d+"', html_content))

    n_scenes = len(raw_scenes)
    has_title_scene = False
    if html_scene_count == len(raw_scenes) + 1:
        info("HTML 比脚本多 1 个场景，视为独立标题场景（无旁白）")
        raw_scenes.insert(0, "")
        n_scenes = html_scene_count
        has_title_scene = True

    chars_per_scene = [len(s.replace("\n", "").replace(" ", "")) for s in raw_scenes]
    total_chars = sum(chars_per_scene) if sum(chars_per_scene) > 0 else 1
    pause = float(os.environ.get("SCENE_PAUSE", "0.6"))

    if not wav_path.exists():
        warn("未找到 narration.wav，跳过时长调整")
        return

    audio_dur = get_audio_duration(str(wav_path))

    sentences = load_sentence_timestamps(project_dir)
    aligned = None
    scene_durations = []
    scene_times = []

    if sentences:
        aligned = align_scenes_by_text(html_content, n_scenes, sentences, raw_scenes)
        if aligned:
            info(f"使用文本匹配对齐句段时间戳（{len(sentences)} 个时间点）")
            for i in range(n_scenes):
                if has_title_scene and i == 0:
                    sd = 3.5
                else:
                    start, end = aligned[i]
                    sd = round(max(end - start + pause, 1.5), 1)
                scene_durations.append(sd)
            scene_times = aligned
        else:
            warn(f"文本匹配失败（{len(sentences)} 句），降级为字数比例分配")
            scene_durations, scene_times = _fallback_durations(
                audio_dur, n_scenes, chars_per_scene, has_title_scene, pause)
    else:
        warn("无线索时长数据，降级为字数比例分配")
        scene_durations, scene_times = _fallback_durations(
            audio_dur, n_scenes, chars_per_scene, has_title_scene, pause)

    # 仅非 TTS 对齐模式（字数比例降级）才用 diff 修正最后一个场景
    if aligned is None:
        diff = audio_dur - sum(scene_durations)
        scene_durations[-1] = round(scene_durations[-1] + diff, 1)
        if scene_durations[-1] < 1.5:
            scene_durations[-1] = 1.5

    # 文本对齐模式下，填补场景间的间隙（丢失的 TTS 句子）
    if aligned is not None:
        for i in range(n_scenes - 1):
            _, curr_end = aligned[i]
            next_start, _ = aligned[i + 1]
            gap = next_start - (curr_end + pause)
            if gap > 0.3:
                scene_durations[i] = round(scene_durations[i] + gap, 1)
                info(f"  场景{i+1} 延长 {gap:.1f}s 填补至下一场景的间隙")

    info(f"音频: {audio_dur:.1f}s | 场景数: {n_scenes}")
    for i, (sd, ch) in enumerate(zip(scene_durations, chars_per_scene)):
        if aligned is not None and i < len(aligned) and not (has_title_scene and i == 0):
            s, e = aligned[i]
            print(f"  场景{i+1}: {sd:.1f}s [{s:.1f}-{e:.1f}] ({ch}字, {ch/total_chars*100:.0f}%)")
        else:
            # 计算顺序堆叠的起始位置
            fallback_start = sum(scene_durations[:i])
            fallback_end = fallback_start + sd
            print(f"  场景{i+1}: {sd:.1f}s [{fallback_start:.1f}-{fallback_end:.1f}] ({ch}字, {ch/total_chars*100:.0f}%)")

    html = re.sub(r'id="scene-s(\d+)"', r'id="scene\1"', html_content)

    old_starts = []
    old_durs = []
    for i in range(1, n_scenes + 1):
        m_start = re.search(rf'id="scene{i}"[^>]*?data-start="([\d.]+)"', html)
        m_dur = re.search(rf'id="scene{i}"[^>]*?data-duration="([\d.]+)"', html)
        if m_start and m_dur:
            old_starts.append(float(m_start.group(1)))
            old_durs.append(float(m_dur.group(1)))
        else:
            old_starts.append(0)
            old_durs.append(10)

    for i in range(n_scenes):
        sid = f"scene{i+1}"
        new_dur = scene_durations[i]
        old_ss = old_starts[i]
        # 使用 TTS 对齐的起始时间，让场景在对应旁白播放时出现
        if aligned is not None and i < len(aligned) and not (has_title_scene and i == 0):
            new_ss = aligned[i][0]
        else:
            new_ss = sum(scene_durations[:i])  # 降级：顺序堆叠

        html = re.sub(
            rf'(id="{sid}"[^>]*?)data-start="[\d.]+"',
            rf'\1data-start="{new_ss:.1f}"',
            html,
        )
        html = re.sub(
            rf'(id="{sid}"[^>]*?)data-duration="[\d.]+"',
            rf'\1data-duration="{new_dur:.1f}"',
            html,
        )

        gsap_sid = f"#scene{i+1}"
        pat = (
            r"(tl\.(?:from|to)\s*\(\s*['\"]"
            + re.escape(gsap_sid)
            + r"[^'\"]*['\"][^{}]*\{[^}]*\}\s*,\s*)[\d.]+"
        )

        def shift_gsap(m, oss=old_ss, nss=new_ss):
            prefix = m.group(1)
            old_pos = float(m.group(0)[len(prefix):])
            new_pos = nss + (old_pos - oss)
            return prefix + f"{new_pos:.1f}"

        html = re.sub(pat, shift_gsap, html)

    # 确保退出动画在 TTS 音频结束后触发
    if aligned is not None:
        for i in range(n_scenes):
            if has_title_scene and i == 0:
                continue
            if i >= len(aligned):
                continue
            tts_end = aligned[i][1]

            sid = f"#scene{i+1}"
            pat = (
                r"(tl\.to\s*\(\s*['\"]"
                + re.escape(sid)
                + r"['\"]\s*,\s*\{[^}]*?duration\s*:\s*([\d.]+)[^}]*?\}\s*,\s*)[\d.]+"
            )

            old_html = html

            def _push_exit(m, te=tts_end):
                prefix = m.group(1)
                fade_dur = float(m.group(2))
                old_pos = float(m.group(0)[len(prefix):])
                min_pos = te - fade_dur + 0.3
                new_pos = max(old_pos, min_pos)
                return prefix + f"{new_pos:.1f}"

            html = re.sub(pat, _push_exit, html)

            if html != old_html:
                info(f"  场景{i+1} 退出动画已推迟到 TTS 结束后 ({tts_end:.1f}s)")

    for i in range(1, n_scenes + 1):
        sid = f"scene{i}"
        scene_tag_re = rf'<div[^>]*?id="{sid}"[^>]*?class="[^"]*clip[^"]*"[^>]*>'
        for m in re.finditer(scene_tag_re, html):
            tag = m.group(0)
            if 'data-track-index' not in tag:
                new_tag = tag.rstrip('>') + f' data-track-index="{i}">'
                html = html.replace(tag, new_tag, 1)
                info(f'  场景{i} 自动补充 data-track-index="{i}"')

    for i in range(1, n_scenes + 1):
        gsap_times = _extract_gsap_positions(html, f"#scene{i}")
        if not gsap_times:
            continue
        max_gsap = max(gsap_times)
        m_start = re.search(rf'id="scene{i}"[^>]*?data-start="([\d.]+)"', html)
        m_dur = re.search(rf'id="scene{i}"[^>]*?data-duration="([\d.]+)"', html)
        if not m_start or not m_dur:
            continue
        scene_start = float(m_start.group(1))
        current_dur = float(m_dur.group(1))
        current_end = scene_start + current_dur
        needed_end = max_gsap + 0.5
        if current_end < needed_end:
            new_dur = round(needed_end - scene_start, 1)
            html = re.sub(
                rf'(id="scene{i}"[^>]*?)data-duration="[\d.]+"',
                rf'\1data-duration="{new_dur:.1f}"',
                html,
            )
            info(f"  场景{i} data-duration 从 {current_dur:.1f}s 扩展到 {new_dur:.1f}s")
            scene_durations[i-1] = new_dur
            current_dur = new_dur
            current_end = scene_start + current_dur

        # 安全网：确保 tl.to(/#sceneN 退场动画不会在 data-duration 结束前完成淡出
        sid = f"#scene{i}"
        pat_exit = (
            r"(tl\.to\s*\(\s*['\"]"
            + re.escape(sid)
            + r"['\"]\s*,\s*\{[^}]*?duration\s*:\s*([\d.]+)[^}]*?\}\s*,\s*)[\d.]+"
        )
        def _late_exit(m, se=current_end):
            prefix = m.group(1)
            fade_dur = float(m.group(2))
            old_pos = float(m.group(0)[len(prefix):])
            min_pos = max(old_pos, se - fade_dur - 0.2)  # 退场结束 ≈ data-duration 边界
            return prefix + f"{min_pos:.1f}"
        new_html = re.sub(pat_exit, _late_exit, html)
        if new_html != html:
            info(f"  场景{i} 退场动画推后至 data-duration 边界 ({current_end:.1f}s)")
        html = new_html

    # 计算实际结束时间：取所有场景 data-start + data-duration 的最大值
    scene_ends = []
    cum = 0
    for i in range(n_scenes):
        if aligned is not None and i < len(aligned) and not (has_title_scene and i == 0):
            st = aligned[i][0]
        else:
            st = cum
            cum += scene_durations[i]
        scene_ends.append(st + scene_durations[i])
    # 对于 TTS 对齐的场景，结束时间也要考虑 TTS 结束 + 停顿
    if aligned is not None:
        for i in range(n_scenes):
            if i < len(aligned) and not (has_title_scene and i == 0):
                tts_end = aligned[i][1] + pause
                if tts_end > scene_ends[i]:
                    scene_ends[i] = tts_end

    total_dur = max(scene_ends)
    total_dur_rounded = round(total_dur)

    html = re.sub(
        r'(id="root"[^>]*?)data-duration="[\d.]+"',
        rf'\1data-duration="{total_dur_rounded}"',
        html,
    )
    html = re.sub(
        r'(<audio[^>]*?)data-duration="[\d.]+"',
        rf'\1data-duration="{total_dur_rounded}"',
        html,
    )

    html_path.write_text(html, encoding="utf-8")
    success(f"时长调整完成: {total_dur:.1f}s，每场景末尾预留 {pause}s 停顿")
