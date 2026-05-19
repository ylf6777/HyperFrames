"""时长自动调整：句段时间戳对齐 + 备用字数比例分配"""
from pipeline.timing.utils import (
    get_audio_duration,
    load_sentence_timestamps,
    _extract_scene_texts,
    _norm_text,
    _clean_tts_text,
    write_project_files,
    sync_script_from_html,
)
from pipeline.timing.aligner import (
    align_scenes_by_text,
    _fallback_durations,
)
from pipeline.timing.html_rewriter import (
    adjust_timing,
)

__all__ = [
    "get_audio_duration",
    "load_sentence_timestamps",
    "write_project_files",
    "sync_script_from_html",
    "align_scenes_by_text",
    "adjust_timing",
]
