"""
文本匹配：4 种匹配策略（精确 / 前缀 / 字符包含率 / 字数比例降级）
"""

from pipeline.utils import info, warn, error
from pipeline.timing.utils import _norm_text, _extract_scene_texts


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
    speech_dur = max(speech_dur, audio_dur * 0.5)
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
