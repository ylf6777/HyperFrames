#!/usr/bin/env python3
"""
auto_pipeline.py — CLI 入口：全自动文档到视频生成管线

流程: 文档 → Claude AI 生成 composition → TTS 配音 → HyperFrames 渲染 → MP4

使用方法:
  1. 设置环境变量:
     export HYPERFRAMES_API_KEY=sk-xxx  (API Key)
     export HYPERFRAMES_BASE_URL=...    (可选，自定义 API 地址)

  2. 运行:
     python auto_pipeline.py 文档.docx --project my-video --output 我的视频.mp4
     python auto_pipeline.py 文档.txt
     python auto_pipeline.py --help

依赖安装:
  pip install anthropic python-docx
"""

import argparse
import sys

from pipeline import generate_video
from pipeline.utils import Color


def main():
    parser = argparse.ArgumentParser(
        description="全自动文档到视频生成管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python auto_pipeline.py 教案.docx
  python auto_pipeline.py 教案.docx --project zoo-safety --output 我的视频.mp4
  python auto_pipeline.py 教案.txt --skip-llm   (仅执行 TTS + 渲染)

API Key 请通过环境变量设置:
  export HYPERFRAMES_API_KEY=sk-xxx
  export HYPERFRAMES_BASE_URL=https://... (可选)
        """,
    )
    parser.add_argument("input", help="输入文档路径 (.docx / .doc / .txt / .pdf)")
    parser.add_argument("--project", "-p", default=None, help="项目目录名 (默认: 输入文件名)")
    parser.add_argument("--output", "-o", default=None, help="输出视频文件名 (默认自动生成)")
    parser.add_argument("--model", default=None, help="模型名 (默认: claude-sonnet-4-6，也可用 HF_MODEL 环境变量)")
    parser.add_argument("--base-dir", "-d", default=None, help="项目根目录 (默认当前目录)")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 内容生成，直接跑 TTS+渲染")
    parser.add_argument("--dry-run", action="store_true", help="仅生成内容，不执行 TTS 和渲染")

    args = parser.parse_args()

    result = generate_video(
        input_path=args.input,
        project=args.project,
        model=args.model,
        base_dir=args.base_dir,
        output=args.output,
        skip_llm=args.skip_llm,
        dry_run=args.dry_run,
    )

    if result["success"]:
        print(f"\n{Color.BOLD}{'=' * 54}{Color.RESET}")
        print(f"{Color.GREEN}{Color.BOLD}  生成完成！{Color.RESET}")
        if result["video_path"]:
            print(f"  {Color.GREEN}视频: {result['video_path']}{Color.RESET}")
        print(f"{Color.BOLD}{'=' * 54}{Color.RESET}\n")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
