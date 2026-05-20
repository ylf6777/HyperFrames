"""
管线编排：全自动文档 → 视频流程
"""

import os
import shutil
import tempfile
from pathlib import Path

from pipeline.utils import info, success, warn, error, step, find_project_dir, check_disk_space, ensure_template
from pipeline.reader import read_document
from pipeline.llm import call_claude_api
from pipeline.tts import run_tts
from pipeline.renderer import run_render
from pipeline.timing import get_audio_duration, adjust_timing, write_project_files, sync_script_from_html


def generate_video(
    input_path: str | Path,
    project: str | None = None,
    *,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str = "claude-sonnet-4-6",
    base_dir: str | None = None,
    output: str | None = None,
    skip_llm: bool = False,
    dry_run: bool = False,
    on_progress: callable | None = None,
    should_cancel: callable | None = None,
) -> dict:
    """运行全自动文档→视频管线，返回结果字典。

    返回:
        {
            "success": True/False,
            "video_path": "path/to.mp4" or None,
            "project_dir": "path/to/project",
            "script_path": "path/to/script.txt",
            "html_path": "path/to/index.html",
            "duration": 45.0,
            "steps": { "llm": True/False/None, "tts": True/False/None, "render": True/False/None },
        }
    """
    result = {
        "success": False,
        "video_path": None,
        "project_dir": None,
        "script_path": None,
        "html_path": None,
        "duration": 0,
        "steps": {"llm": None, "tts": None, "render": None},
    }

    def _progress(msg: str):
        if on_progress:
            on_progress(msg)

    def _check_cancel(msg: str = "任务已被取消") -> bool:
        if should_cancel and should_cancel():
            warn(msg)
            _progress(msg)
            return True
        return False

    input_path = Path(input_path)
    if not input_path.exists():
        error(f"输入文件不存在: {input_path}")
        return result

    project_name = project or input_path.stem.replace(" ", "_").replace("《", "").replace("》", "")
    total_steps = 5

    # ── Step 1: 读取文档 ──
    step(1, total_steps, "读取文档内容")
    try:
        document_text = read_document(str(input_path))
    except Exception as e:
        error(f"文档读取失败: {e}")
        return result
    info(f"读取到 {len(document_text)} 字符")
    _progress("文档读取完成")

    # ── 创建临时工作目录 ──
    _cleanup_project: str | None = None
    project_dir: str | None = None
    if base_dir or project:
        project_dir = find_project_dir(project_name, base_dir)
    else:
        _cleanup_project = tempfile.mkdtemp(prefix="hf_")
        tmpl_src = Path(ensure_template(Path.cwd())) / "hyperframes.json"
        if tmpl_src.exists():
            shutil.copy2(str(tmpl_src), str(Path(_cleanup_project) / "hyperframes.json"))
        project_dir = _cleanup_project

    result["project_dir"] = project_dir
    result["script_path"] = str(Path(project_dir) / "script.txt")
    result["html_path"] = str(Path(project_dir) / "index.html")

    def _cleanup():
        if _cleanup_project:
            shutil.rmtree(_cleanup_project, ignore_errors=True)

    # ── Step 2: LLM 内容生成 ──
    if not skip_llm:
        step(2, total_steps, "AI 生成视频内容")
        _api_key = api_key or os.environ.get("HYPERFRAMES_API_KEY")
        _api_base = api_base or os.environ.get("HYPERFRAMES_BASE_URL")
        _model = model or os.environ.get("HF_MODEL") or "claude-sonnet-4-6"

        if not _api_key:
            error("需要 API Key！请设置 HYPERFRAMES_API_KEY 环境变量")
            _cleanup()
            return result

        llm_cache_dir = str(Path(__file__).resolve().parent.parent / "_server_data" / "llm_cache")
        try:
            _progress("AI 内容生成中（等待 API 响应，可能需要 1-2 分钟）...")
            script_content, html_content = call_claude_api(
                _api_key, document_text, api_base=_api_base, model=_model, cache_dir=llm_cache_dir,
                on_progress=_progress,
            )
        except Exception as e:
            error(f"AI 内容生成失败: {e}")
            _cleanup()
            return result

        result["steps"]["llm"] = True

        try:
            write_project_files(project_dir, script_content, html_content)
        except Exception as e:
            error(f"写入项目文件失败: {e}")
            _cleanup()
            return result

        info("LLM 内容生成完成 ✓")
    else:
        step(2, total_steps, "跳过 LLM 内容生成")
        script_path = Path(project_dir) / "script.txt"
        html_path = Path(project_dir) / "index.html"
        if script_path.exists():
            info(f"使用现有: {script_path}")
        else:
            warn(f"未找到 {script_path}，将使用文档内容作为脚本")
            script_path.write_text(document_text[:500], encoding="utf-8")

    if _check_cancel():
        _cleanup()
        return result

    if dry_run:
        info("Dry-run 模式，跳过 TTS 和渲染")
        result["success"] = True
        _cleanup()
        return result

    if not project_dir:
        error("项目目录未确定，无法继续")
        _cleanup()
        return result

    # ── Step 3: 同步画面文字到旁白脚本（仅 skip-llm 模式需要从 HTML 同步）──
    if skip_llm:
        step(2, total_steps, "同步画面文字到旁白脚本")
        sync_script_from_html(project_dir)

    if _check_cancel():
        _cleanup()
        return result

    # ── Step 4: TTS ──
    step(3, total_steps, "TTS 语音合成")
    _progress("TTS 配音生成中...")
    tts_ok = run_tts(project_dir)
    audio_duration = 0
    if tts_ok:
        wav_path = Path(project_dir) / "narration.wav"
        if wav_path.exists():
            try:
                audio_duration = get_audio_duration(str(wav_path))
            except Exception:
                audio_duration = 0
            success(f"配音生成完成: {wav_path.name} ({audio_duration:.1f}s)")
            adjust_timing(project_dir)
            result["steps"]["tts"] = True
            result["duration"] = audio_duration
        else:
            warn("narration.wav 未找到，检查 TTS 输出")
    else:
        error("TTS 生成失败，视频将无配音")

    if _check_cancel():
        _cleanup()
        return result

    # ── Step 5: 渲染 ──
    step(4, total_steps, "HyperFrames 视频渲染")
    _progress("视频渲染中（这可能需要几分钟）...")

    # 渲染前检查磁盘空间
    ok, free_mb = check_disk_space(project_dir)
    if not ok:
        error(f"磁盘空间不足（剩余 {free_mb}MB），无法渲染")
        _cleanup()
        return result

    output_mp4 = run_render(project_dir)
    result["steps"]["render"] = output_mp4 is not None

    if _check_cancel():
        _cleanup()
        return result

    # ── Step 6: 复制输出 ──
    step(5, total_steps, "输出视频文件")

    if output_mp4 and output_mp4.exists():
        output_name = output or f"{input_path.stem}.mp4"
        output_path = Path(output_name)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path.name

        try:
            shutil.copy2(str(output_mp4), str(output_path))
        except Exception as e:
            error(f"复制视频文件失败: {e}")
            _cleanup()
            return result

        size_mb = output_path.stat().st_size / (1024 * 1024)
        success(f"视频已生成: {output_path} ({size_mb:.1f} MB)")

        # 也复制一份到项目目录旁边
        project_output = Path(project_dir).parent / output_path.name
        if str(project_output) != str(output_path):
            try:
                shutil.copy2(str(output_mp4), str(project_output))
            except Exception as e:
                warn(f"二次复制到项目目录失败: {e}")

        result["video_path"] = str(output_path)
        result["success"] = True
    else:
        error("未找到渲染输出的 MP4 文件")

    _cleanup()
    return result
