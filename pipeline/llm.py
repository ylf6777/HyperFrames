"""
LLM 内容生成：文档总结 → 剧本 + 分镜 HTML
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Tuple

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

**要求：摘要总字数控制在 1200 字以内。**"""

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
<div id="scene1" class="scene scene-s1 clip" data-start="0" data-duration="6" data-track-index="1">
  <div class="emoji-main">🧸</div>
  <div class="title">大标题</div>
  <div class="content">正文内容</div>
</div>
<div id="scene2" class="scene scene-s2 clip" data-start="6" data-duration="8" data-track-index="2">
  ...
</div>
```
- id 必须是 `scene1`, `scene2`, `scene3`... 数字紧跟在 scene 后面
- **每个场景容器必须有 `class="scene scene-sN clip"`**（按顺序 s1, s2, s3...）
- **每个场景容器必须有 `data-track-index="1"`、`data-track-index="2"`... 依次递增**
- **只有场景容器（.scene）加 `class="clip"`，里面的内容元素不要加 clip**
- 第一个场景必须是独立的标题场景（配 emoji + 大标题）
- 每个场景使用不同的渐变背景色
- 最后一个场景结束前留 1-1.5s 淡出

### GSAP 动画规则（必须严格遵守）：
- 必须使用 **静态绝对时间位置** 作为 `tl.from()` 的第三个参数
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

### 场景可见性管理：
HyperFrames 会自动管理 `clip` 元素的可见性，**不需要手动添加 updateScenes 函数**。
只需在 CSS 中设置 `.scene { opacity: 1 }`（不要设置 opacity: 0）。
HyperFrames 会在每个场景的 data-start 到 data-duration 范围内自动显示场景。

### 时间线注册（使用 `<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>`）：
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

# ── LLM 缓存 ─────────────────────────────────────────────────
_PROMPT_HASH = hashlib.sha256(
    (SUMMARIZE_PROMPT + GENERATION_SYSTEM_PROMPT).encode()
).hexdigest()[:12]

CACHE_TTL_DAYS = int(os.environ.get("LLM_CACHE_TTL_DAYS", "7"))
_DEFAULT_CACHE_DIR = os.environ.get("LLM_CACHE_DIR") or str(
    Path(__file__).resolve().parent.parent / "_server_data" / "llm_cache"
)


class LLMCache:
    """LLM 响应缓存：内容 hash + 模型名 + 提示词版本 → 7 天自动淘汰"""

    def __init__(self, cache_dir: str = _DEFAULT_CACHE_DIR):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, text: str, model: str) -> str:
        text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        raw = f"{text_hash}||{model}||{_PROMPT_HASH}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, text: str, model: str) -> tuple[str, str] | None:
        """读取缓存，命中时更新 accessed_at"""
        key = self._make_key(text, model)
        path = self.cache_dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["accessed_at"] = time.time()
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data["script"], data["html"]
        except Exception:
            return None

    def put(self, text: str, model: str, script: str, html: str):
        """写入缓存，写入后触发淘汰检查"""
        key = self._make_key(text, model)
        now = time.time()
        data = {
            "key": key,
            "model": model,
            "prompt_version": _PROMPT_HASH,
            "script": script,
            "html": html,
            "created_at": now,
            "accessed_at": now,
        }
        (self.cache_dir / f"{key}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._evict_old()

    def _evict_old(self):
        """删除超过 TTL 天未被访问的缓存"""
        cutoff = time.time() - CACHE_TTL_DAYS * 86400
        for f in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("accessed_at", 0) < cutoff:
                    f.unlink()
            except Exception:
                f.unlink(missing_ok=True)

    def list_entries(self) -> list[dict]:
        """列出所有缓存条目（不含 script/html 内容）"""
        entries = []
        for f in self.cache_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entries.append({
                    "key": data.get("key", f.stem),
                    "model": data.get("model", "?"),
                    "created_at": data.get("created_at", 0),
                    "accessed_at": data.get("accessed_at", 0),
                    "size_bytes": f.stat().st_size,
                })
            except Exception:
                pass
        entries.sort(key=lambda e: e["accessed_at"], reverse=True)
        return entries

    def clear(self):
        """清空所有缓存"""
        for f in self.cache_dir.glob("*.json"):
            f.unlink(missing_ok=True)

    def delete(self, key: str) -> bool:
        """删除指定缓存，返回是否成功"""
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def stats(self) -> dict:
        """缓存统计"""
        entries = self.list_entries()
        return {
            "count": len(entries),
            "size_bytes": sum(e["size_bytes"] for e in entries),
            "ttl_days": CACHE_TTL_DAYS,
            "cache_dir": str(self.cache_dir),
        }


def call_claude_api(
    api_key: str,
    document_text: str,
    max_retries: int = 3,
    api_base: str | None = None,
    model: str = "claude-sonnet-4-6",
    cache_dir: str | None = None,
) -> Tuple[str, str]:
    """两轮 LLM 调用: 先总结文档, 再根据总结生成剧本+HTML，返回 (script, html)。

    支持缓存：相同文档+模型+提示词版本时自动跳过 API 调用。
    """
    cache = LLMCache(cache_dir or _DEFAULT_CACHE_DIR)

    # 检查缓存
    cached = cache.get(document_text, model)
    if cached:
        print(f"[llm] 缓存命中（{model}），跳过 API 调用")
        return cached

    try:
        import anthropic
    except ImportError:
        raise ImportError("请安装 anthropic: pip install anthropic")

    client_kwargs = {"api_key": api_key}
    if api_base:
        client_kwargs["base_url"] = api_base
    client = anthropic.Anthropic(**client_kwargs)

    # ── 第一轮：总结文档 ──
    summary = ""
    for attempt in range(1, max_retries + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=SUMMARIZE_PROMPT,
                messages=[{"role": "user", "content": document_text}],
            )
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    summary = block.text
                    break
            if summary:
                break
        except Exception as e:
            if attempt < max_retries:
                print(f"[llm] 总结调用失败 (第{attempt}次): {e}，正在重试...")
                time.sleep(2**attempt)
            else:
                raise RuntimeError(f"总结调用失败: {e}")

    if not summary:
        raise RuntimeError("总结返回为空")

    # ── 第二轮：根据摘要生成剧本和分镜 ──
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
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    content = block.text
                    break
            break
        except Exception as e:
            if attempt < max_retries:
                print(f"[llm] 创作调用失败 (第{attempt}次): {e}，正在重试...")
                time.sleep(2**attempt)
            else:
                raise RuntimeError(f"创作调用失败: {e}")

    # ── 提取 script 和 html ──
    script_content = _extract_script(content)
    html_content = _extract_html(content)

    if not script_content:
        blocks = re.findall(r"```(?:\w*)\n?(.*?)\n?```", content, re.DOTALL)
        for block in blocks:
            block = block.strip()
            if not block.startswith("<") and len(block) > 50:
                script_content = block
                break
        if not script_content:
            script_content = document_text[:500]

    if not html_content:
        raise RuntimeError("未能从 LLM 输出中解析出 index.html，请检查 API 返回内容")

    if "data-composition-id" not in html_content:
        print("[llm] 警告: 生成的 HTML 缺少 data-composition-id，可能不是有效的 HyperFrames 合成")

    # 写入缓存
    cache.put(document_text, model, script_content, html_content)
    return script_content, html_content


def _extract_script(text: str) -> str:
    m = re.search(r"```script\n?(.*?)\n?```", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _extract_html(text: str) -> str:
    # 策略1: ```html 标记块
    m = re.search(r"```html\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        return m.group(1).strip()

    # 策略2: 任何 ``` 代码块里包含 HTML 标签
    blocks = re.findall(r"```(?:\w*)\n?(.*?)\n?```", text, re.DOTALL)
    for block in blocks:
        block = block.strip()
        if block.startswith("<") and (
            "<!doctype" in block.lower()
            or "<html" in block.lower()
            or "<div" in block.lower()
        ):
            return block

    # 策略3: 直接找 <!DOCTYPE html> 或 <html
    for prefix in ("<!DOCTYPE html>", "<html", "<HTML"):
        start = text.find(prefix)
        if start >= 0:
            end = text.rfind("</html>")
            if end > start:
                return text[start : end + 7].strip()
            return text[start:].strip()

    # 策略4: 找已知顶层 div
    for tag in ('<div id="root"', '<div id="popup"', '<div id="scene1"'):
        start = text.find(tag)
        if start >= 0:
            end = text.rfind("</html>")
            if end > start:
                return text[start : end + 7].strip()
            return text[start:].strip()

    return ""
