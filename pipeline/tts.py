"""
TTS 语音合成：edge-tts 配音 + 句段时间戳捕获
"""

import sys
from pathlib import Path

from pipeline.utils import info, warn, error, run_command

TTS_SCRIPT_TEMPLATE = '''"""Generate TTS narration + word timestamps using edge-tts."""
import asyncio
import edge_tts
import json

VOICE = 'zh-CN-XiaoyiNeural'
RATE = '-25%'

async def main():
    with open('script.txt', 'r', encoding='utf-8') as f:
        script = f.read()
    communicate = edge_tts.Communicate(script, VOICE, rate=RATE)

    audio_data = b""
    word_times = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
        elif chunk["type"] == "SentenceBoundary":
            word_times.append({
                "text": chunk["text"],
                "offset": round(chunk["offset"] / 1e7, 3),
                "duration": round(chunk["duration"] / 1e7, 3),
            })

    with open("narration.wav", "wb") as f:
        f.write(audio_data)
    with open("word_timestamps.json", "w", encoding="utf-8") as f:
        json.dump(word_times, f, ensure_ascii=False, indent=2)

    print(f"已生成 narration.wav（{len(audio_data)} bytes, {len(word_times)} 个句段时间戳）")

if __name__ == '__main__':
    asyncio.run(main())
'''


def run_tts(project_dir: str) -> bool:
    """运行 TTS 生成配音，返回 True/False 表示成功/失败"""
    tts_script = Path(project_dir) / "generate_tts.py"

    try:
        __import__("edge_tts")
    except ImportError:
        warn("edge-tts 未安装，尝试使用 HyperFrames 内置 TTS...")
        return run_command(
            ["npx", "--yes", "hyperframes@0.6.6", "tts", "script.txt", "--output", "narration.wav"],
            cwd=project_dir,
            desc="TTS",
            timeout=300,
        )

    # 总是重新写入最新模板（覆盖旧版），确保句段时间戳逻辑最新
    tts_script.write_text(TTS_SCRIPT_TEMPLATE, encoding="utf-8")
    info("已生成 generate_tts.py（edge-tts），运行配音生成...")
    return run_command(
        [sys.executable, "generate_tts.py"],
        cwd=project_dir,
        desc="TTS",
        timeout=300,
    )
