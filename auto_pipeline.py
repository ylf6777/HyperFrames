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
import re
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
    elif ext == ".doc":
        try:
            import olefile
            ole = olefile.OleFileIO(filepath)
            wd = ole.openstream('WordDocument').read()
            ole.close()
            # Word Binary 格式存储 UTF-16LE 文本
            text = wd.decode('utf-16le', errors='replace')
            # 过滤出可读的中文内容（跳过二进制乱码）
            lines = []
            for line in text.split('\n'):
                cleaned = line.strip()
                chinese_count = sum(1 for c in cleaned if '一' <= c <= '鿿')
                # 保留包含较多中文且有意义的行
                if chinese_count >= 5 and len(cleaned) > 5:
                    lines.append(cleaned)
            # 找到第一个有意义的标题行作为起始
            result = '\n'.join(lines)
            # 去掉尾部无意义的残留字符
            import re
            result = re.sub(r'[^一-鿿　-〿＀-￯0-9a-zA-Z\s，。、；：！？（）【】""''《》—…·\n—-]', '', result)
            result = re.sub(r'\n{3,}', '\n\n', result).strip()
            return result
        except ImportError:
            error("请安装 olefile: pip install olefile")
            sys.exit(1)
        except Exception as e:
            error(f"读取 .doc 文件失败: {e}")
            sys.exit(1)

    else:
        error(f"不支持的文件格式: {ext}，支持 .docx / .doc / .txt / .pdf")
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
- ...

**要求：摘要总字数控制在 1200 字以内。**
"""

GENERATION_SYSTEM_PROMPT = """你是一个儿童教育视频制作专家。根据提供的教案摘要，生成两个文件：

## 文件 1: script.txt
用简单口语化的中文撰写旁白脚本，适合 3-5 岁儿童理解。
- 使用短句，每句话独立成行
- 语言生动活泼，带情感
- 总时长控制在 40-60 秒（约 150-300 字）
- **每段之间用空行分隔，第一段是开场引入（对应标题场景），后续段落对应各知识点**
- **段落数必须等于 HTML 场景数，每个段落按顺序对应一个场景（绝对不能多段或少段）**

## 文件 2: index.html
根据脚本内容生成完整的 HyperFrames 合成 HTML 文件。

### 设计要求：
- 温暖明亮的配色：#FFF8E7 背景，#FF6B6B 珊瑚红，#4ECDC4 青绿色，#3D2E1E 深褐文字
- 使用 emoji 图标增强画面趣味性（每个场景一个主 emoji）
- 字体: font-family "Microsoft YaHei", "PingFang SC", sans-serif
- 分辨率: 1920x1080

### 场景结构（必须严格遵守）：
根据内容需要灵活决定场景数量（5-8 个），但必须遵循以下规则：

**1. 场景 div 格式：**
```html
<div id="scene1" class="scene scene-s1 clip" data-start="0" data-duration="6">
  <div class="emoji-main clip">🧸</div>
  <div class="title clip">大标题</div>
  <div class="content clip">正文内容</div>
</div>
<div id="scene2" class="scene scene-s2 clip" data-start="6" data-duration="8">
  ...
</div>
```
- id 必须是 `scene1`, `scene2`, `scene3`... 数字紧跟在 scene 后面
- **每个场景容器必须有 `class="scene scene-sN clip"`**（按顺序 s1, s2, s3...）
- **所有带 data-start/data-duration 的元素必须有 `class="clip"`**
- 第一个场景必须是独立的标题场景（配 emoji + 大标题）
- 每个场景使用不同的渐变背景色
- 最后一个场景结束前留 1-1.5s 淡出

### GSAP 动画规则（必须严格遵守）：
- 必须使用 **静态绝对时间位置**作为 `tl.from()` 的第三个参数
- **禁止**使用动态循环、`delay` 属性或 `tl.time()` 计算位置
- 每个场景的动画时间 = 该场景的 data-start + 固定偏移量（0.2-0.5s）
- 同一场景内不同元素错开 0.3-0.5s
- 动画时长 0.4-0.6s

**正确的 GSAP 写法示例：**
```js
// 场景1（标题）: 元素在场景开始后依次入场
tl.from('#scene1 .emoji-main', { opacity: 0, scale: 0.5, y: -60, duration: 0.6, ease: "back.out(1.7)" }, 0.3);
tl.from('#scene1 .title',      { opacity: 0, y: 40, duration: 0.5, ease: "power3.out" },             0.8);
tl.from('#scene1 .subtitle',   { opacity: 0, y: 30, duration: 0.5, ease: "power2.out" },             1.3);

// 场景2（内容）: 场景起始于 6s，元素在 6.3s / 6.8s 入场
tl.from('#scene2 .emoji-main', { opacity: 0, scale: 0, rotation: -20, duration: 0.5, ease: "back.out(1.7)" }, 6.3);
tl.from('#scene2 .content',    { opacity: 0, x: -40, duration: 0.5, ease: "power3.out" },                      6.8);

// ...后面场景以此类推

// 最后一个场景在结束前淡出
tl.to('#scene6', { opacity: 0, duration: 1.5, ease: "power2.inOut" }, 43.5);
```

- eases: `back.out(1.7)`（emoji 类）、`power3.out`（内容类）、`power2.out`（副标题）
- 禁用所有 exit 动画（最后一个场景的淡出除外）

### 场景可见性管理（必须包含）：
在 GSAP 脚本的末尾添加以下函数，监听时间线进度来切换场景显示/隐藏：
```js
var scenes = document.querySelectorAll('.scene');
function updateScenes() {
  var time = tl.time();
  for (var i = 0; i < scenes.length; i++) {
    var s = scenes[i];
    var start = parseFloat(s.dataset.start);
    var dur = parseFloat(s.dataset.duration);
    s.style.opacity = (time >= start && time < start + dur) ? '1' : '0';
    s.style.pointerEvents = (time >= start && time < start + dur) ? 'auto' : 'none';
  }
}
tl.eventCallback('onUpdate', updateScenes);
updateScenes();
```

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
            summary = ""
            for block in response.content:
                if hasattr(block, 'text') and block.text:
                    summary = block.text
                    break
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
            content = ""
            for block in response.content:
                if hasattr(block, 'text') and block.text:
                    content = block.text
                    break
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

    def extract_script(text):
        m = re.search(r'```script\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        return ""

    def extract_html(text):
        # 策略1: ```html 标记块
        m = re.search(r'```html\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # 策略2: 任何 ``` 代码块里包含 HTML 标签
        blocks = re.findall(r'```(?:\w*)\n?(.*?)\n?```', text, re.DOTALL)
        for block in blocks:
            block = block.strip()
            if block.startswith("<") and ("<!doctype" in block.lower() or "<html" in block.lower() or "<div" in block.lower()):
                return block
        # 策略3: 在无标记的文本里直接找 html 结构
        start = text.find("<!DOCTYPE html")
        if start >= 0:
            end = text.rfind("</html>")
            if end > start:
                return text[start:end + 7].strip()
        start = text.find("<html")
        if start >= 0:
            end = text.rfind("</html>")
            if end > start:
                return text[start:end + 7].strip()
        # 策略4: 找 <div id="root" 或 <div id="popup"
        for tag in ('<div id="root"', '<div id="popup"', '<div id="scene1"'):
            start = text.find(tag)
            if start >= 0:
                end = text.rfind("</html>")
                if end > start:
                    return text[start:end + 7].strip()
                # 如果没有 </html>，取到末尾
                return text[start:].strip()
        return ""

    script_content = extract_script(content)
    html_content = extract_html(content)

    if not script_content:
        # 尝试把第一个非 HTML 的长文本块当脚本
        blocks = re.findall(r'```(?:\w*)\n?(.*?)\n?```', content, re.DOTALL)
        for block in blocks:
            block = block.strip()
            if not block.startswith("<") and len(block) > 50 and not html_content:
                script_content = block
                break
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
# ── 时长自动调整 ──────────────────────────────────────────────────────────
def get_audio_duration(wav_path: str) -> float:
    """读取音频文件时长（秒）"""
    import subprocess, json
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", wav_path],
            capture_output=True, text=True, timeout=30
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        # 降级估算：WAV 16bit 44100Hz
        st = Path(wav_path).stat().st_size
        return st / 44100 / 2


def load_sentence_timestamps(project_dir: str) -> list[dict] | None:
    """加载 word_timestamps.json（edge-tts 输出的句段时间戳）"""
    ts_path = Path(project_dir) / "word_timestamps.json"
    if ts_path.exists():
        try:
            return json.loads(ts_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def map_sentences_to_scenes(sentences: list[dict], chars_per_scene: list[int]) -> list[tuple[float, float]]:
    """将句段时间戳按字数比例映射到每个场景，返回 [(start_sec, end_sec), ...]"""
    if not sentences:
        return []
    total_chars = sum(chars_per_scene) or 1
    n = len(chars_per_scene)
    # 按每场景字数占比，计算每个场景应包含的句子数
    cum_ratio = [sum(chars_per_scene[:i+1]) / total_chars for i in range(n)]
    boundaries = [int(r * len(sentences)) for r in cum_ratio]
    sentence_ends = [s["offset"] + s["duration"] for s in sentences]
    result = []
    prev_idx = 0
    for i, end_idx in enumerate(boundaries):
        end_idx = min(end_idx, len(sentences) - 1)
        if end_idx <= prev_idx:
            result.append((0, 1.5))
            continue
        start = sentences[prev_idx]["offset"]
        end = sentence_ends[end_idx - 1]
        result.append((start, end))
        prev_idx = end_idx
    return result


def adjust_timing(project_dir: str):
    """根据 TTS 实际时长 + 逐词时间戳重新分配场景时间"""
    # ── 1. 读取脚本和 HTML ──
    script_path = Path(project_dir) / "script.txt"
    html_path = Path(project_dir) / "index.html"
    wav_path = Path(project_dir) / "narration.wav"

    script = script_path.read_text(encoding="utf-8")
    raw_scenes = [s.strip() for s in script.split("\n\n") if s.strip()]
    if not raw_scenes:
        warn("脚本无法按空行分场景，跳过时长调整")
        return

    html_content = html_path.read_text(encoding="utf-8") if html_path.exists() else ""

    # ── 2. 检测 HTML 场景数与脚本段落数是否匹配 ──
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

    # ── 3. 计算每场景字数 ──
    chars_per_scene = [len(s.replace("\n", "").replace(" ", "")) for s in raw_scenes]
    total_chars = sum(chars_per_scene) if sum(chars_per_scene) > 0 else 1
    pause = 0.6

    # ── 4. 获取音频总时长 ──
    if not wav_path.exists():
        warn("未找到 narration.wav，跳过时长调整")
        return
    audio_dur = get_audio_duration(str(wav_path))

    # ── 5. 计算场景时长：优先使用句段时间戳 ──
    sentences = load_sentence_timestamps(project_dir)
    scene_durations = []
    scene_times = []

    if sentences and len(sentences) >= n_scenes:
        scene_times = map_sentences_to_scenes(sentences, chars_per_scene)
        info(f"使用句段时间戳对齐（{len(sentences)} 个时间点）")
        for i in range(n_scenes):
            if has_title_scene and i == 0:
                sd = 3.5
            else:
                start, end = scene_times[i]
                sd = round(max(end - start + pause, 1.5), 1)
            scene_durations.append(sd)
    else:
        # 降级：按字数比例分配
        if sentences:
            warn(f"时间戳数量不足（{len(sentences)}），降级为字数比例分配")
        speech_dur = audio_dur - pause * n_scenes
        if speech_dur <= 0:
            speech_dur = audio_dur * 0.85
        for i, c in enumerate(chars_per_scene):
            if c == 0 and i == 0:
                sd = 3.5
            else:
                sd = max(c / total_chars * speech_dur + pause, 1.5)
            scene_durations.append(round(sd, 1))

    # 微调最后场景使总时长对齐音频
    diff = audio_dur - sum(scene_durations)
    scene_durations[-1] = round(scene_durations[-1] + diff, 1)
    if scene_durations[-1] < 1.5:
        scene_durations[-1] = 1.5

    total_dur = sum(scene_durations)
    total_dur_rounded = round(total_dur)

    info(f"音频: {audio_dur:.1f}s | 场景数: {n_scenes} | 重算后总时长: {total_dur:.1f}s")
    for i, (sd, ch) in enumerate(zip(scene_durations, chars_per_scene)):
        if scene_times and i < len(scene_times) and not (has_title_scene and i == 0):
            s, e = scene_times[i]
            print(f"  场景{i+1}: {sd:.1f}s [{s:.1f}-{e:.1f}] ({ch}字, {ch/total_chars*100:.0f}%)")
        else:
            print(f"  场景{i+1}: {sd:.1f}s ({ch}字, {ch/total_chars*100:.0f}%)")

    # ── 5. 读取 HTML，统一 scene id 格式 ──
    html = html_content
    # 兼容旧格式 scene-s1 → scene1
    html = re.sub(r'id="scene-s(\d+)"', r'id="scene\1"', html)

    # 收集旧场景时间
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

    # ── 6. 更新 scene div 的 data-start / data-duration ──
    new_start = 0
    for i in range(n_scenes):
        sid = f"scene{i+1}"
        new_dur = scene_durations[i]

        # 替换 data-start（只替换匹配 id 的那个）
        html = re.sub(
            rf'(id="{sid}"[^>]*?)data-start="[\d.]+"',
            rf'\1data-start="{new_start:.1f}"',
            html
        )
        # 替换 data-duration
        html = re.sub(
            rf'(id="{sid}"[^>]*?)data-duration="[\d.]+"',
            rf'\1data-duration="{new_dur:.1f}"',
            html
        )
        new_start += new_dur

    # ── 7. 更新 GSAP 时间线位置参数 ──
    #   tl.from("#sceneX...", { ... }, <position>)
    #   tl.to("#sceneX...", { ... }, <position>)
    #   position = old_scene_start + offset → new_scene_start + offset
    for i in range(n_scenes):
        sid = f"#scene{i+1}"
        old_ss = old_starts[i]
        new_ss = sum(scene_durations[:i])  # 累计前面场景时长

        # 替换 tl.from/to 中引用该场景的第三个参数（position）
        def shift_pos(m, oss=old_ss, nss=new_ss):
            prefix = m.group(1)
            old_pos_str = m.group(0)[len(prefix):]
            old_pos = float(old_pos_str)
            new_pos = nss + (old_pos - oss)
            return prefix + f"{new_pos:.1f}"

        pat = ("(tl\\.(?:from|to)\\s*\\(\\s*['\"]" + re.escape(sid)
               + "[^'\"]*['\"][^{}]*\\{[^}]*\\}\\s*,\\s*)[\\d.]+")
        html = re.sub(pat, shift_pos, html)

    # ── 8. 更新 root 和 audio 的 data-duration ──
    html = re.sub(
        r'(id="root"[^>]*?)data-duration="[\d.]+"',
        rf'\1data-duration="{total_dur_rounded}"',
        html
    )
    html = re.sub(
        r'(<audio[^>]*?)data-duration="[\d.]+"',
        rf'\1data-duration="{total_dur_rounded}"',
        html
    )

    # ── 9. 写回 ──
    html_path.write_text(html, encoding="utf-8")
    success(f"时长调整完成: {total_dur:.1f}s，每场景末尾预留 {pause}s 停顿")


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


# ── 管线入口（供外部调用）───────────────────────────────────────────────────
def generate_video(
    input_path: str | Path,
    project: str | None = None,
    *,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str = "deepseek-chat",
    base_dir: str | None = None,
    output: str | None = None,
    skip_llm: bool = False,
    dry_run: bool = False,
    on_progress: callable | None = None,
) -> dict:
    """运行全自动文档→视频管线，返回结果字典。

    返回:
        {
            "success": True/False,
            "video_path": "path/to.mp4" or None,
            "project_dir": "path/to/project",
            "script_path": "path/to/script.txt",
            "html_path": "path/to/index.html",
            "duration": 45.0,      # 视频时长（秒）
            "steps": {              # 各步骤状态
                "llm": True/False/None,
                "tts": True/False/None,
                "render": True/False/None,
            }
        }
    """
    from pathlib import Path
    result = {
        "success": False,
        "video_path": None,
        "project_dir": None,
        "script_path": None,
        "html_path": None,
        "duration": 0,
        "steps": {"llm": None, "tts": None, "render": None},
    }

    def progress(msg: str):
        if on_progress:
            on_progress(msg)

    input_path = Path(input_path)
    if not input_path.exists():
        error(f"输入文件不存在: {input_path}")
        return result

    project_name = project or input_path.stem.replace(" ", "_").replace("《", "").replace("》", "")
    total_steps = 5 if not skip_llm else 3
    document_text = ""

    # ── Step 1: 读取文档 ──
    step(1, total_steps, "读取文档内容")
    document_text = read_document(str(input_path))
    info(f"读取到 {len(document_text)} 字符")

    # ── Step 2: LLM 内容生成 ──
    project_dir = None
    if not skip_llm:
        step(2, total_steps, "AI 生成视频内容")
        _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        _api_base = api_base or os.environ.get("ANTHROPIC_BASE_URL")
        _model = model or os.environ.get("ANTHROPIC_MODEL") or "deepseek-chat"

        if not _api_key:
            error("需要 API Key！")
            return result

        script_content, html_content = call_claude_api(_api_key, document_text, api_base=_api_base, model=_model)
        result["steps"]["llm"] = True

        project_dir = find_project_dir(project_name, base_dir)
        write_project_files(project_dir, script_content, html_content)
        info("LLM 内容生成完成 ✓")
    else:
        step(2, total_steps, "跳过 LLM 内容生成")
        project_dir = find_project_dir(project_name, base_dir)
        script_path = Path(project_dir) / "script.txt"
        html_path = Path(project_dir) / "index.html"
        if script_path.exists():
            info(f"使用现有: {script_path}")
        else:
            warn(f"未找到 {script_path}，将使用文档内容作为脚本")
            script_path.write_text(document_text, encoding="utf-8")

    result["project_dir"] = project_dir
    result["script_path"] = str(Path(project_dir) / "script.txt")
    result["html_path"] = str(Path(project_dir) / "index.html")

    if dry_run:
        info("Dry-run 模式，跳过 TTS 和渲染")
        result["success"] = True
        return result

    # ── Step 3: TTS ──
    step(3 if not skip_llm else 2, total_steps, "TTS 语音合成")
    tts_ok = run_tts(project_dir)
    audio_duration = 0
    if tts_ok:
        wav_path = Path(project_dir) / "narration.wav"
        if wav_path.exists():
            audio_duration = get_audio_duration(str(wav_path))
            success(f"配音生成完成: {wav_path.name} ({audio_duration:.1f}s)")
            adjust_timing(project_dir)
            result["steps"]["tts"] = True
            result["duration"] = audio_duration
        else:
            warn("narration.wav 未找到，检查 TTS 输出")
    else:
        error("TTS 生成失败，视频将无配音")

    # ── Step 4: 渲染 ──
    step(4 if not skip_llm else 3, total_steps, "HyperFrames 视频渲染")
    output_mp4 = run_render(project_dir)
    result["steps"]["render"] = output_mp4 is not None

    # ── Step 5: 复制输出 ──
    step_idx = 5 if not skip_llm else 4
    if total_steps >= 4:
        step(step_idx, total_steps, "输出视频文件")

    if output_mp4 and output_mp4.exists():
        output_name = output or f"{input_path.stem}.mp4"
        output_path = Path(output_name)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path.name

        import shutil
        shutil.copy2(str(output_mp4), str(output_path))
        size_mb = output_path.stat().st_size / (1024 * 1024)
        success(f"视频已生成: {output_path} ({size_mb:.1f} MB)")

        # 也复制一份到项目目录旁边
        project_output = Path(project_dir).parent / output_path.name
        if str(project_output) != str(output_path):
            shutil.copy2(str(output_mp4), str(project_output))

        result["video_path"] = str(output_path)
        result["success"] = True
    else:
        error("未找到渲染输出的 MP4 文件")

    return result


# ── 执行命令 ──────────────────────────────────────────────────────────────
def run_command(cmd: list[str], cwd: str | None = None, desc: str = "", timeout: int | None = None):
    """运行命令并实时输出"""
    prefix = f"[{desc}]" if desc else ""
    info(f"{prefix} 执行: {' '.join(cmd)}")

    # Windows 下 subprocess 找不到 npx/npm（需要 .cmd 扩展名）
    if os.name == "nt" and cmd[0] in ("npx", "npm"):
        cmd[0] = cmd[0] + ".cmd"

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
        # 如果是 npx 找不到，尝试升级安装 corepack
        if cmd[0] == "npx":
            warn("尝试手动运行: corepack enable && npm install -g npx")
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


TTS_SCRIPT_TEMPLATE = '''"""Generate TTS narration + word timestamps using edge-tts."""
import asyncio
import edge_tts
import json

VOICE = 'zh-CN-XiaoyiNeural'
RATE = '+15%'

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

def run_tts(project_dir: str):
    """运行 TTS 生成配音"""
    tts_script = Path(project_dir) / "generate_tts.py"

    # 检查 edge-tts 是否可用
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

    # 查找输出文件（HyperFrames v0.6.6+ 输出到 renders/，旧版输出到 output/）
    for subdir in ("renders", "output"):
        search_dir = Path(project_dir) / subdir
        if search_dir.exists():
            mp4_files = list(search_dir.glob("*.mp4"))
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
    parser.add_argument("input", help="输入文档路径 (.docx / .doc / .txt / .pdf)")
    parser.add_argument("--project", "-p", default="zoo-safety", help="项目目录名 (默认: zoo-safety)")
    parser.add_argument("--output", "-o", default=None, help="输出视频文件名 (默认自动生成)")
    parser.add_argument("--api-key", "-k", default=None, help="API Key (默认用 ANTHROPIC_API_KEY 环境变量)")
    parser.add_argument("--api-base", default=None, help="API Base URL (默认用 ANTHROPIC_BASE_URL 环境变量或官方地址)")
    parser.add_argument("--model", default=None, help="模型名 (默认: deepseek-chat)")
    parser.add_argument("--base-dir", "-d", default=None, help="项目根目录 (默认当前目录)")
    parser.add_argument("--skip-llm", action="store_true", help="跳过 LLM 内容生成，直接跑 TTS+渲染")
    parser.add_argument("--dry-run", action="store_true", help="仅生成内容，不执行 TTS 和渲染")

    args = parser.parse_args()

    # 直接调用 generate_video
    result = generate_video(
        input_path=args.input,
        project=args.project,
        api_key=args.api_key,
        api_base=args.api_base,
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
        print(f"  {Color.DIM}项目: {result['project_dir']}{Color.RESET}")
        print(f"  {Color.DIM}脚本: {result['script_path']}{Color.RESET}")
        print(f"  {Color.DIM}合成: {result['html_path']}{Color.RESET}")
        print(f"{Color.BOLD}{'=' * 54}{Color.RESET}\n")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
