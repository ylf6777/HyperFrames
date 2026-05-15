#!/usr/bin/env python3
"""
auto_pipeline.py — 全自动文档到视频生成管线
===========================================
流程: 文档 → Claude AI 生成 composition → TTS 配音 → HyperFrames 渲染 → MP4

使用方法:
  1. 设置 API Key:
     set ANTHROPIC_API_KEY=sk-xxx     (Windows)
     export ANTHROPIC_API_KEY=sk-xxx  (Linux/Mac)

  2. 运行:
     python auto_pipeline.py 文档.docx --project zoo-safety --output 我的视频.mp4
     python auto_pipeline.py 文档.txt
     python auto_pipeline.py --help

依赖安装:
  pip install anthropic python-docx
"""

import os
import sys
import json
import time
import argparse
import subprocess
import tempfile
from pathlib import Path

# ── 颜色输出 ──────────────────────────────────────────────────────────────
class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

def info(msg):
    print(f"{Color.CYAN}▶{Color.RESET} {msg}")

def success(msg):
    print(f"{Color.GREEN}✔{Color.RESET} {msg}")

def warn(msg):
    print(f"{Color.YELLOW}⚠{Color.RESET} {msg}")

def error(msg):
    print(f"{Color.RED}✘{Color.RESET} {msg}")

def step(n, total, msg):
    print(f"\n{Color.BOLD}[{n}/{total}] {msg}{Color.RESET}")
    print(f"  {Color.DIM}{'─' * 50}{Color.RESET}")


# ── 文档读取 ──────────────────────────────────────────────────────────────
def read_document(filepath: str) -> str:
    """读取 DOCX / TXT / PDF 文件，返回文本内容"""
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(filepath)
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            # 也读取表格内容
            tables_text = []
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells:
                        tables_text.append(" | ".join(cells))
            all_text = "\n".join(paras)
            if tables_text:
                all_text += "\n\n【表格内容】\n" + "\n".join(tables_text)
            return all_text
        except ImportError:
            error("请安装 python-docx: pip install python-docx")
            sys.exit(1)

    elif ext == ".txt":
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    elif ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(filepath)
            texts = [page.extract_text() for page in reader.pages if page.extract_text()]
            return "\n".join(texts)
        except ImportError:
            error("请安装 pypdf: pip install pypdf")
            sys.exit(1)
    else:
        error(f"不支持的文件格式: {ext}，支持 .docx / .txt / .pdf")
        sys.exit(1)


# ── LLM 内容生成 ──────────────────────────────────────────────────────────
SUMMARIZE_PROMPT = """你是一个幼儿教育专家。分析下面的教案文档，提取一份结构化的摘要，供后续视频制作使用。

请提取以下内容：
1. 教案主题与核心教育目标（一句话）
2. 适合 3-5 岁儿童的关键知识点（3-5 个点，每点一句话）
3. 教案中的故事/情境元素（如角色、场景、游戏等）
4. 建议使用的儿童化语言表达（把书面语转为口语）

摘要格式：
## 主题
...
## 核心目标
...
## 关键知识点
- ...
## 情境元素
- ...
## 建议表达
- ..."""

GENERATION_SYSTEM_PROMPT = """你是一个儿童教育视频制作专家。根据提供的教案摘要，生成两个文件：

## 文件 1: script.txt
用简单口语化的中文撰写旁白脚本，适合 3-5 岁儿童理解。
- 使用短句，每句话独立成行
- 语言生动活泼，带情感
- 总时长控制在 40-60 秒（约 150-300 字）

## 文件 2: index.html
根据脚本内容生成完整的 HyperFrames 合成 HTML 文件。

### 设计要求：
- 温暖明亮的配色：#FFF8E7 背景，#FF6B6B 珊瑚红，#4ECDC4 青绿色，#3D2E1E 深褐文字
- 使用 emoji 图标增强画面趣味性（每个场景一个主 emoji）
- 字体: font-family "Microsoft YaHei", "PingFang SC", sans-serif
- 分辨率: 1920x1080

### 场景结构：
将脚本分成 5-7 个场景，每个场景对应一个知识点或段落：
- 每个场景有 data-start 和 data-duration 属性
- 每个场景使用不同的渐变背景 (scene-s1~s6)
- 所有带 data-start 的元素必须有 class="clip"
- 最后一个场景在结束前留 1-1.5 秒淡出

### GSAP 动画规则：
- 每个场景的元素使用 tl.from() 做入场动画
- 动画时间 = 场景开始时间 + 0.2-0.5s 偏移
- 动画时长 0.4-0.6s
- 不同元素错开 0.3-0.5s 入场
- 禁用所有 exit 动画（最后一个场景除外，最后淡出）
- eases: back.out(1.7), power3.out, power2.out

### 时间线注册：
```js
window.__timelines = window.__timelines || {};
window.__timelines["main"] = gsap.timeline({ paused: true });
```

### 音频元素（文件末尾）：
```html
<audio id="narration" data-start="0" data-duration="总秒数" data-track-index="0" src="narration.wav" data-volume="1"></audio>
```

### 视频文件元数据（开头的 #root 元素）：
```html
<div id="root" data-composition-id="main" data-start="0" data-duration="总秒数" data-width="1920" data-height="1080">
```

输出格式: 先输出 script.txt 内容（用 ```script 标记），再输出 index.html 内容（用 ```html 标记）。"""


def call_claude_api(api_key: str, document_text: str, max_retries: int = 3,
                    api_base: str | None = None, model: str = "deepseek-chat") -> tuple[str, str]:
    """两轮调用: 先总结文档, 再根据总结创作剧本+分镜"""
    try:
        import anthropic
    except ImportError:
        error("请安装 anthropic: pip install anthropic")
        sys.exit(1)

    client_kwargs = {"api_key": api_key}
    if api_base:
        client_kwargs["base_url"] = api_base
    client = anthropic.Anthropic(**client_kwargs)

    # ── 第一轮：总结文档 ──
    info("第1步: 总结文档内容...")
    summary = ""
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=SUMMARIZE_PROMPT,
                messages=[{"role": "user", "content": document_text}],
            )
            summary = response.content[0].text if response.content else ""
            if summary:
                break
        except Exception as e:
            if attempt < max_retries:
                warn(f"总结调用失败 (第{attempt}次): {e}，正在重试...")
                time.sleep(2 ** attempt)
            else:
                error(f"总结调用失败: {e}")
                sys.exit(1)

    if not summary:
        error("总结返回为空")
        sys.exit(1)

    info(f"总结完成 ({len(summary)} 字符)")
    print(f"  {Color.DIM}{summary[:200].replace(chr(10), ' ')}...{Color.RESET}")

    # ── 第二轮：根据摘要生成剧本和分镜 ──
    info("第2步: 根据总结创作剧本和分镜...")

    user_prompt = f"""请根据以下教案摘要，生成幼儿园安全教育视频的旁白脚本和 HTML 合成文件。

教案摘要：
{summary}

请先生成 script.txt（旁白脚本），再生成 index.html（合成文件）。"""

    content = ""
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8192,
                system=GENERATION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            content = response.content[0].text if response.content else ""
            break
        except Exception as e:
            if attempt < max_retries:
                warn(f"创作调用失败 (第{attempt}次): {e}，正在重试...")
                time.sleep(2 ** attempt)
            else:
                error(f"创作调用失败: {e}")
                sys.exit(1)

    # 从返回内容中提取 script.txt 和 index.html
    import re
    script_content = ""
    html_content = ""

    script_match = re.search(r'```script\n?(.*?)\n?```', content, re.DOTALL)
    if script_match:
        script_content = script_match.group(1).strip()

    html_match = re.search(r'```html\n?(.*?)\n?```', content, re.DOTALL)
    if html_match:
        html_content = html_match.group(1).strip()

    if not script_content:
        blocks = re.findall(r'```(?:\w*)\n?(.*?)\n?```', content, re.DOTALL)
        for block in blocks:
            block = block.strip()
            if block.startswith("<") and ("<!doctype" in block.lower() or "<html" in block.lower() or "<div" in block.lower()):
                html_content = block
            elif not html_content and len(block) > 50:
                script_content = block

    if not script_content:
        warn("未能从 LLM 输出中解析出 script.txt，将使用占位内容")
        script_content = document_text[:500]

    if not html_content:
        error("未能从 LLM 输出中解析出 index.html，请检查 API 返回内容")
        sys.exit(1)

    if "data-composition-id" not in html_content:
        warn("生成的 HTML 缺少 data-composition-id，可能不是有效的 HyperFrames 合成")

    return script_content, html_content


# ── 文件写入 ──────────────────────────────────────────────────────────────
def write_project_files(project_dir: str, script_content: str, html_content: str):
    """将生成的内容写入项目目录"""
    script_path = Path(project_dir) / "script.txt"
    html_path = Path(project_dir) / "index.html"

    script_path.write_text(script_content, encoding="utf-8")
    info(f"已写入: {script_path} ({len(script_content)} 字)")

    html_path.write_text(html_content, encoding="utf-8")
    info(f"已写入: {html_path} ({len(html_content)} 字符)")

    # 验证总时长
    dur_match = __import__('re').search(r'data-duration="(\d+)"', html_content)
    if dur_match:
        duration = int(dur_match.group(1))
        info(f"视频总时长: {duration} 秒")
    else:
        warn("未找到 data-duration，可能需要在 HTML 中手动设置")


# ── 执行命令 ──────────────────────────────────────────────────────────────
def run_command(cmd: list[str], cwd: str | None = None, desc: str = "", timeout: int | None = None):
    """运行命令并实时输出"""
    prefix = f"[{desc}]" if desc else ""
    info(f"{prefix} 执行: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=False,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            if result.stderr:
                print(f"  {Color.DIM}stderr: {result.stderr[:500]}{Color.RESET}")
            return False
        return True
    except subprocess.TimeoutExpired:
        error(f"{prefix} 执行超时")
        return False
    except FileNotFoundError as e:
        error(f"{prefix} 命令未找到: {e}")
        return False
    except Exception as e:
        error(f"{prefix} 执行失败: {e}")
        return False


# ── 步骤执行 ──────────────────────────────────────────────────────────────
def find_project_dir(project_name: str, base_dir: str | None = None) -> str:
    """查找项目目录，如果不存在则创建"""
    base = Path(base_dir) if base_dir else Path.cwd()
    project_path = base / project_name

    if not project_path.exists():
        info(f"项目目录不存在，创建: {project_path}")
        project_path.mkdir(parents=True, exist_ok=True)
        # 初始化 HyperFrames 项目
        init_result = run_command(
            ["npx", "--yes", "hyperframes@0.6.6", "init", project_name],
            cwd=str(base),
            desc="hyperframes init",
            timeout=120,
        )
        if not init_result:
            warn("HyperFrames 初始化可能不完整，继续执行...")

    return str(project_path)


def run_tts(project_dir: str):
    """运行 TTS 生成配音"""
    tts_script = Path(project_dir) / "generate_tts.py"
    if tts_script.exists():
        info("运行 generate_tts.py 生成配音...")
        return run_command(
            [sys.executable, "generate_tts.py"],
            cwd=project_dir,
            desc="TTS",
            timeout=300,
        )
    else:
        warn(f"未找到 {tts_script}，尝试使用 cli 内置 TTS...")
        return run_command(
            ["npx", "--yes", "hyperframes@0.6.6", "tts", "script.txt", "--output", "narration.wav"],
            cwd=project_dir,
            desc="TTS",
            timeout=300,
        )


def run_render(project_dir: str) -> Path | None:
    """运行 HyperFrames 渲染"""
    info("渲染视频（这可能需要几分钟）...")
    success_render = run_command(
        ["npm", "run", "render"],
        cwd=project_dir,
        desc="render",
        timeout=1800,
    )
    if not success_render:
        error("渲染失败")
        return None

    # 查找输出文件
    output_dir = Path(project_dir) / "output"
    if output_dir.exists():
        mp4_files = list(output_dir.glob("*.mp4"))
        if mp4_files:
            return mp4_files[0]

    # 也可能在项目根目录
    mp4_files = list(Path(project_dir).glob("*.mp4"))
    if mp4_files:
        return mp4_files[0]

    warn("未找到输出 MP4 文件")
    return None


# ── 主流程 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="全自动文档到视频生成管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python auto_pipeline.py 教案.docx
  python auto_pipeline.py 教案.docx --project zoo-safety --output 我的视频.mp4
  python auto_pipeline.py 教案.txt --skip-llm   (仅执行 TTS + 渲染)
  python auto_pipeline.py 教案.docx --api-key sk-xxx
        """,
    )
    parser.add_argument("input", help="输入文档路径 (.docx / .txt / .pdf)")
    parser.add_argument("--project", "-p", default="zoo-safety", help="项目目录名 (默认: zoo-safety)")
    parser.add_argument("--output", "-o", default=None, help="输出视频文件名 (默认自动生成)")
    parser.add_argument("--api-key", "-k", default=None, help="API Key (默认用 ANTHROPIC_API_KEY 环境变量)")
    parser.add_argument("--api-base", default=None, help="API Base URL (默认用 ANTHROPIC_BASE_URL 环境变量或官方地址)")
    parser.add_argument("--model", default=None, help="模型名 (默认: deepseek-chat)")
    parser.add_argument("--base-dir", "-d", default=None, help="项目根目录 (默认当前目录)")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 内容生成，直接跑 TTS+渲染")
    parser.add_argument("--dry-run", action="store_true", help="仅生成内容，不执行 TTS 和渲染")

    args = parser.parse_args()

    # ── 检查输入文件 ────────────────────────────────────────────────────
    input_path = Path(args.input)
    if not input_path.exists():
        error(f"输入文件不存在: {args.input}")
        sys.exit(1)

    total_steps = 5 if not args.skip_llm else 3

    print(f"\n{Color.BOLD}{'=' * 54}{Color.RESET}")
    print(f"{Color.BOLD}  HyperFrames 全自动文档 → 视频生成管线{Color.RESET}")
    print(f"{Color.BOLD}{'=' * 54}{Color.RESET}")
    print(f"  输入:   {input_path.name}")
    print(f"  项目:   {args.project}")
    print(f"  跳过LLM: {'是' if args.skip_llm else '否'}")
    print(f"  DryRun: {'是' if args.dry_run else '否'}")
    print(f"{'=' * 54}\n")

    # ── Step 1: 读取文档 ──────────────────────────────────────────────
    step(1, total_steps, "读取文档内容")
    document_text = read_document(str(input_path))
    info(f"读取到 {len(document_text)} 字符")
    print(f"  {Color.DIM}前 200 字: {document_text[:200].replace(chr(10), ' ')}...{Color.RESET}")

    # ── Step 2: LLM 内容生成 ──────────────────────────────────────────
    if not args.skip_llm:
        step(2, total_steps, "Claude AI 生成视频内容")

        api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")
        api_base = args.api_base or os.environ.get("ANTHROPIC_BASE_URL")
        model_name = args.model or os.environ.get("ANTHROPIC_MODEL") or "deepseek-chat"

        if not api_key:
            error("需要 API Key！")
            error("请设置环境变量: set ANTHROPIC_API_KEY=sk-xxx")
            error("或在命令行传入: --api-key sk-xxx")
            sys.exit(1)

        script_content, html_content = call_claude_api(api_key, document_text, api_base=api_base, model=model_name)

        # 找到项目目录
        project_dir = find_project_dir(args.project, args.base_dir)
        write_project_files(project_dir, script_content, html_content)

        info("LLM 内容生成完成 ✓")
    else:
        step(2, total_steps, "跳过 LLM 内容生成")
        project_dir = find_project_dir(args.project, args.base_dir)
        # 检查现有文件
        script_path = Path(project_dir) / "script.txt"
        html_path = Path(project_dir) / "index.html"
        if script_path.exists():
            info(f"使用现有: {script_path}")
        else:
            warn(f"未找到 {script_path}，将使用文档内容作为脚本")
            script_path.write_text(document_text, encoding="utf-8")

    # ── Step 3: 配音生成 ──────────────────────────────────────────────
    step(3, total_steps, "TTS 语音合成")
    if args.dry_run:
        info("Dry-run 模式，跳过 TTS")
    else:
        tts_ok = run_tts(project_dir)
        if tts_ok:
            wav_path = Path(project_dir) / "narration.wav"
            if wav_path.exists():
                duration = wav_path.stat().st_size / 44100 / 2  # 估算: WAV 16bit 44100Hz
                success(f"配音生成完成: {wav_path.name} (约 {duration:.0f}s)")
            else:
                warn("narration.wav 未找到，检查 TTS 输出")
        else:
            error("TTS 生成失败，视频将无配音")
            if not args.dry_run:
                proceed = input(f"{Color.YELLOW}继续渲染吗? (y/n): {Color.RESET}").lower()
                if proceed != "y":
                    info("已取消")
                    sys.exit(1)

    # ── Step 4: 渲染 ──────────────────────────────────────────────────
    if total_steps >= 4:
        step(4, total_steps, "HyperFrames 视频渲染")
    else:
        step(3, total_steps, "HyperFrames 视频渲染")

    if args.dry_run:
        info("Dry-run 模式，跳过渲染")
        print(f"\n{Color.BOLD}生成的文件:{Color.RESET}")
        print(f"  {Path(project_dir) / 'script.txt'}")
        print(f"  {Path(project_dir) / 'index.html'}")
        info("Dry-run 完成。去掉 --dry-run 执行完整渲染。")
        return

    output_mp4 = run_render(project_dir)

    # ── Step 5: 复制输出 ──────────────────────────────────────────────
    if total_steps >= 5:
        step(5, total_steps, "输出视频文件")
    else:
        step(4 if total_steps == 3 else 5, total_steps, "输出视频文件")

    if output_mp4 and output_mp4.exists():
        output_name = args.output or f"{input_path.stem}.mp4"
        output_path = Path(output_name)

        # 如果输出路径是相对路径，放到当前目录
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path.name

        import shutil
        shutil.copy2(str(output_mp4), str(output_path))
        size_mb = output_path.stat().st_size / (1024 * 1024)
        success(f"视频已生成: {output_path} ({size_mb:.1f} MB)")

        # 也复制一份到项目目录旁边方便查看
        project_output = Path(project_dir).parent / output_path.name
        if str(project_output) != str(output_path):
            shutil.copy2(str(output_mp4), str(project_output))
    else:
        error("未找到渲染输出的 MP4 文件")
        warn(f"请检查 {Path(project_dir) / 'output'} 目录")

    # ── 完成 ──────────────────────────────────────────────────────────
    print(f"\n{Color.BOLD}{'=' * 54}{Color.RESET}")
    print(f"{Color.GREEN}{Color.BOLD}  生成完成！{Color.RESET}")
    if output_mp4 and output_mp4.exists():
        print(f"  {Color.GREEN}视频: {output_path}{Color.RESET}")
    print(f"  {Color.DIM}项目: {project_dir}{Color.RESET}")
    print(f"  {Color.DIM}脚本: {Path(project_dir) / 'script.txt'}{Color.RESET}")
    print(f"  {Color.DIM}合成: {Path(project_dir) / 'index.html'}{Color.RESET}")
    print(f"{Color.BOLD}{'=' * 54}{Color.RESET}\n")


if __name__ == "__main__":
    main()
