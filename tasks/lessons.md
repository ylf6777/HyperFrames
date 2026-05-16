# 经验教训

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
