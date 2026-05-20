# 经验教训

## 2026-05-20: Vitest 组件测试中的 fake timers 和 file upload 陷阱

### fake timers 导致 findByText 超时
- `vi.useFakeTimers()` 会 mock `setTimeout`/`setInterval`，而 `@testing-library` 的 `findByText` / `waitFor` 内部用 `setTimeout` 轮询
- fake timers 下这些轮询不会触发 → 测试超时 5000ms
- **修复**：不要在全局 `beforeEach` 设置 fake timers。只在需要控制时间的特定测试内使用，并在组件渲染 *之前* 调用 `vi.useFakeTimers()`

### fireEvent.change 优于 user.upload
- `userEvent.upload(element, file)` 在 jsdom 环境下偶尔不触发 `onChange` 或 `inputRef.current.files` 为空
- 更可靠的方式：`fireEvent.change(input, { target: { files: [file] } })` 直接触发 React 合成事件
- 注意：`getByLabelText` 获取隐藏的 `display:none` 文件输入框可能失败，改用 `document.querySelector('#id')` 更可靠

### 组件内重复文本导致 getByText/findByText 失败
- `TaskProgress` 组件在 `.status-label` 和 `.progress-text` 中同时显示相同状态文字（如"排队中"、"已完成"）
- `getByText`/`findByText` 找到多个匹配时抛出异常，不返回第一个
- **修复**：用 `findAllByText` 返回数组检查 `length >= 1`，或查询唯一内容（如文件名、data-testid）

## 2026-05-16: 全面修复 — 默认project/优雅关闭/fallback/CORS/孤儿任务等7项

### 发现问题清单
1. `auto_pipeline.py --project` 默认 `zoo-safety`，不指定时覆盖同一目录
2. `server.py` 无优雅关闭，重启时任务中断
3. `_fallback_durations` 极端场景 speech_dur 负数
4. `pipeline.py` 二次复制失败静默忽略
5. `server.py` shutil.copy2 在外层 try 里，复制失败误标任务 failed
6. CORS `allow_origins=["*"]` 无配置入口
7. `recover_orphaned_tasks` 两个 SQL 全覆盖，冗余

### 修复要点
- issue 1: `default="zoo-safety"` → `default=None`，pipeline 已支持 project=None 自动用文件名
- issue 2: 新增 `_shutdown_event`，worker 循环用 `event.wait()` 替代 `time.sleep()`，lifespan shutdown 时 signal + join + 等待运行中任务（30s 超时）
- issue 3: `speech_dur = max(audio_dur - pause * n_scenes, audio_dur * 0.5)`，去掉两层 if/else
- issue 4: `except: pass` → `except Exception as e: warn(f"二次复制失败: {e}")`
- issue 5: copy2 包独立 try/except，失败时降级使用原始视频路径，不标记任务 failed
- issue 6: `ALLOW_ORIGINS = os.environ.get("ALLOW_ORIGINS", "*").split(",")`，支持用逗号分隔多个来源
- issue 7: 两个 SQL 合并为无条件 `WHERE status='processing'`

## 2026-05-16: adjust_timing fallback 路径所有场景 data-start=0 修复

### 问题
`_fallback_durations()` 返回的 `scene_times` 是 `[(0, sd), (0, sd), ...]`（全是 0 起始）。`adjust_timing()` 第 443 行用 `if scene_times and ...` 判断是否使用 TTS 时间，但 `scene_times` 在 fallback 路径也是 truthy（空列表 != None），导致所有场景 `data-start=0`，视频总长变成最长单场景时长而非总时长。

### 根因
`aligned`（TTS 对齐成功 → list，失败 → None）和 `scene_times`（两个路径都赋值）两个变量混用，判断条件用了错误的一个。

### 修复
所有 `if scene_times and ...` 改为 `if aligned is not None and ...`，区分 TTS 对齐成功和 fallback 路径。

## 2026-05-16: renderer.py glob 返回无序列表取到旧 mp4

### 问题
多次渲染后 `renders/` 目录累积多个 mp4。`list(search_dir.glob("*.mp4"))` 返回顺序由文件系统决定（非 mtime 排序），可能取到旧的错误版本。

### 修复
`sorted(search_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)` 取最新的。

## 2026-05-16: 路径穿越漏洞修复 + 磁盘空间检查

### 路径穿越
- 用户上传的 `file.filename` 可能包含 `../`、`..\\` 等路径穿越序列
- **修复**：用 `Path(name).name` 去掉目录部分，然后替换 `<>:"/\\|?*` 危险字符，最后 `.resolve()` 验证路径仍在 DOCS_DIR 内
- **两点防御**：入口消毒（`sanitize_filename`）+ 出口验证（`.resolve()` + `startswith` 检查）

### 磁盘空间检查
- HyperFrames 渲染会生成临时文件，磁盘满时渲染失败且难以排查
- **修复**：在 `server.py` 的 `run_task()` 和 `pipeline.py` 渲染前用 `shutil.disk_usage()` 检查剩余空间
- 默认阈值 500MB，不足时提前报错，避免渲染半途失败

### 函数设计
- `sanitize_filename()` 放在 `pipeline/utils.py` 作为共享工具函数
- `check_disk_space()` 同样放在 `utils.py`，默认 500MB 阈值但可配置
- 磁盘检查在无法获取信息时默认放行（`return (True, -1)`），不阻塞正常流程

## 2026-05-16: align_scenes_by_text 段落匹配 off-by-one 修复

### 问题
`align_scenes_by_text()` 返回的时间线存在场景重叠。原因是 `pos_to_sent_idx(end_char_pos)` 中 `end_char_pos` 是段落文本的**独占结尾**（exclusive end），但 `pos_to_sent_idx` 返回包含该位置的句子索引。当 `end_char_pos` 恰好等于某句子的累积结尾时，会被映射到**下一句**，导致段落后延一个句子。

### 修复
将 `end_sent = pos_to_sent_idx(end_char_pos)` 改为 `end_sent = pos_to_sent_idx(max(end_char_pos - 1, 0))`，使用段落最后一个字符的位置（end - 1）来查找结束句子。

### 根因
`pos_to_sent_idx` 使用严格大于（`ep > p`）来判断位置 p 是否属于某句。当 p == sent_end[i] 时（字符位于句子边界），p 属于下一句的第一个字符位置，不属于当前句。用于 start 正确（段落第一个字符位置），但用于 end 需要传 `end_char_pos - 1`（段落最后一个字符位置）。

### 场景文本匹配策略
两步匹配比单步匹配更可靠：
1. 脚本段落 → TTS 句子：精确文本匹配（TTS 读的就是 script.txt）
2. HTML 场景 → 脚本段落：字符包含率（_text_containment），容忍 LLM 改写

字符包含率（短文本字符集在长文本字符集中的占比）比 Jaccard 相似度更适合处理中文文本的 LLM 改写场景。

## 2026-05-16: LLM 生成的 HTML 画面文字与旁白不一致

### 问题
LLM 生成时，HTML 场景中的显示文本和 script.txt 旁白文本不一致。旁白往往比画面文字多很多额外内容（过度发挥）。导致：
1. TTS 生成的音频时长比画面应有的时长长
2. 按 TTS 对齐后，场景切换时画面文字和正在播放的旁白不匹配
3. 用户反映"从第二个分镜开始，分镜文本就对不上声音"

### 修复
1. **`sync_script_from_html()`**：在 TTS 之前，从 HTML 场景提取显示文本，覆盖写入 script.txt，确保 TTS 只读画面上的字
2. **TTS 对齐 + 非顺序堆叠**：`adjust_timing()` 改用 TTS 对齐起始时间（`scene_times[i][0]`）作为场景 data-start，而非顺序堆叠
3. **跳过 diff 修正**：TTS 对齐模式下，不缩短最后一个场景来匹配音频总长
4. **容器匹配修复**：`_extract_scene_texts` 容器正则中，`title|subtitle` 误匹配和 `tag` 误匹配 `tag-row`，用 `(?=\s|")` 锚定完整类名

### 教训
- LLM 生成的两个产出（HTML 显示文本、script.txt 旁白）必须保持一致。不应依赖 prompt 保证，而应加后处理同步步骤
- 场景的 data-start 必须基于 TTS 中该场景旁白的实际开始时间，而非前一个场景结束时间
- 正则中匹配类名时，必须用 `(?=\s|")` 或 `(?<=\s|")` 锚定完整类名，避免 `tag` 匹配 `tag-row`、`title` 匹配 `subtitle` 等问题
