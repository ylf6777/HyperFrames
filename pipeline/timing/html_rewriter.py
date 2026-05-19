"""
HTML 正则重写：start/duration/GSAP/track-index/退出动画
"""

import os
import re
from pathlib import Path

from pipeline.utils import info, success, warn, error
from pipeline.timing.utils import get_audio_duration, load_sentence_timestamps
from pipeline.timing.aligner import align_scenes_by_text, _fallback_durations


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
        if aligned is not None and i < len(aligned) and not (has_title_scene and i == 0):
            new_ss = aligned[i][0]
        else:
            new_ss = sum(scene_durations[:i])

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
            min_pos = max(old_pos, se - fade_dur - 0.2)
            return prefix + f"{min_pos:.1f}"
        new_html = re.sub(pat_exit, _late_exit, html)
        if new_html != html:
            info(f"  场景{i} 退场动画推后至 data-duration 边界 ({current_end:.1f}s)")
        html = new_html

    # 计算实际结束时间
    scene_ends = []
    cum = 0
    for i in range(n_scenes):
        if aligned is not None and i < len(aligned) and not (has_title_scene and i == 0):
            st = aligned[i][0]
        else:
            st = cum
            cum += scene_durations[i]
        scene_ends.append(st + scene_durations[i])
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
