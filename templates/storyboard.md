# STORYBOARD — 模板

> 用途：分镜设计的总输出（Phase-2 §62）。**Storyboard = Scene × Shot 完整镜头分解表**：
> 把已批准的 STORY_BEAT_MAP 拆成 Scene，每个 Scene 拆成 Shot，每个 Shot 落到 Layer Intent / Editability / Audio Intention。
> 对应的机器可读结构见 `templates/scene.scene.json` 与 `templates/shot.shot.json`（落地到 `<project>/scenes/SC###.json`、`<project>/shots/S###.json`）。
>
> 使用时机：`STORY_REVIEW` 已批准后生成；`STORYBOARD_REVIEW` 通过前可修订，通过后作为 Phase 3 Routing 与 Phase 5 生产的依据。
>
> ID 契约：Scene `SC###` / Shot `S###` / Layer `L###` / Approval `AP-###` / Decision `D-###`；`scene.shots[].shot_id` 与 `shot.id` 一致。
> 语言约定：正文中文；枚举/技术术语英文大写（REMOTION / GENERATIVE_VIDEO / JY_NATIVE / HIGH / LOW …）。

---

## 1. Scene × Shot 总览表

> 每个 Scene 一行。Duration 为该 Scene 内 Shot 时长之和（秒）；Avg Shot Duration = Duration ÷ Shot Count。

| Scene ID | Title | Duration (s) | Shot Count | Avg Shot Duration (s) |
|---|---|---|---|---|
| SC001 | 开场：问题 | 18.0 | 2 | 9.0 |
| SC002 | 揭晓：工作原理 | 45.0 | 3 | 15.0 |
| SC003 | 收尾：价值 | 27.0 | 3 | 9.0 |
| **合计** | — | **90.0** | **8** | **11.25** |

<!-- 生成规则
1. 按 STORY_BEAT_MAP 的 Chapter 划分 Scene，SC### 全局递增；order 按出场顺序。
2. 每个 Scene 的 Shot 时长求和必须等于 Scene.target_duration（允许 ±5% 容差，偏差需在 notes 说明）。
3. 总览表是 STORYBOARD_REVIEW 提交给用户的第一屏，先给结构、再进细节。
-->

---

## 2. Scene 小节

> 每个 Scene 一节，含 Scene 设计 9 字段（Phase-2 §56）+ 该场景 Shot 列表。

### SC001 — 开场：问题

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `SC001` |
| 2 | Chapter | Ch1: AI 为什么需要记忆 |
| 3 | Order | 1 |
| 4 | Title | 开场：问题 |
| 5 | Narrative Role | Hook |
| 6 | Purpose | 18 秒内建立「AI 没有记忆」的日常痛点，抛出核心张力，不解释答案 |
| 7 | Target Duration | 18.0 s |
| 8 | Visual Direction | summary: 冷色低饱和、大留白、单调空界面；intensity: low；tempo: slow → moderate |
| 9 | Audio Direction | summary: 极简环境音 + 低音垫，留呼吸停顿；music_cue: 00:00 低音垫进入；ambience: 房间底噪 |

**该场景 Shot 列表**

| Order | Shot ID | 时长 (s) | 时间轴 | 一句话内容 |
|---|---|---|---|---|
| 1 | S001 | 8.0 | 00:00–00:08 | 空白对话窗口，光标闪烁，「每次对话都像第一次认识你」 |
| 2 | S002 | 10.0 | 00:08–00:18 | 多条历史会话被逐个清空，「没有记忆，就无法真正理解你」 |

---

### SC002 — 揭晓：工作原理

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `SC002` |
| 2 | Chapter | Ch2: 记忆系统如何工作 |
| 3 | Order | 2 |
| 4 | Title | 揭晓：工作原理 |
| 5 | Narrative Role | Setup → Development |
| 6 | Purpose | 用 45 秒讲清「记忆=长期向量库+实时召回」三层结构，并用一句话带出技术 |
| 7 | Target Duration | 45.0 s |
| 8 | Visual Direction | summary: 中景结构化示意，Map/图表为主，信息逐层叠加；intensity: medium；tempo: moderate |
| 9 | Audio Direction | summary: 音乐进主题层，SFX 跟随结构出现；music_cue: 00:18 主题进入；ambience: 低频脉冲 |

**该场景 Shot 列表**

| Order | Shot ID | 时长 (s) | 时间轴 | 一句话内容 |
|---|---|---|---|---|
| 1 | S003 | 12.0 | 00:18–00:30 | 「记忆」拆成三层：工作记忆 / 长期记忆 / 回忆索引 |
| 2 | S004 | 18.0 | 00:30–00:48 | 向量库示意：新对话写入、按相关性召回 |
| 3 | S005 | 15.0 | 00:48–01:03 | 结构总览推镜 + 标题「MEMORY LAYERS」 |

---

### SC003 — 收尾：价值

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `SC003` |
| 2 | Chapter | Ch3: 为什么对你重要 |
| 3 | Order | 3 |
| 4 | Title | 收尾：价值 |
| 5 | Narrative Role | Payoff → Recap → Closing |
| 6 | Purpose | 回到观众：从「记得你」到「真正理解你」，给出可行动的下一步 |
| 7 | Target Duration | 27.0 s |
| 8 | Visual Direction | summary: 回到留白但加入暖色提亮，与 SC001 形成呼应；intensity: medium；tempo: slow |
| 9 | Audio Direction | summary: 主题收束 + 人声回归 + 结尾休止；music_cue: 01:03 主题变奏；ambience: 渐隐 |

**该场景 Shot 列表**

| Order | Shot ID | 时长 (s) | 时间轴 | 一句话内容 |
|---|---|---|---|---|
| 1 | S006 | 9.0 | 01:03–01:12 | 回到第一视角对话，「现在它记得你」 |
| 2 | S007 | 10.0 | 01:12–01:22 | 分屏对比：无记忆 vs 有记忆的同一问题 |
| 3 | S008 | 8.0 | 01:22–01:30 | 收尾标题 + 行动号召 + 冷场休止 |

---

## 3. Shot 小节

> 每个 Shot 一小节，含 Shot 设计 14 字段（Phase-2 §57）+ 三个新字段：**Layer Intent / Editability Requirement / Audio Intention**。
>
> 14 字段 = id / duration / narrative_purpose / voiceover / on_screen_text / visual_description / camera / motion / audio / transition_in / transition_out / layers / route / continuity_group
> （`scene_id`、`order`、`start_time`、`end_time` 由所属 Scene 推导；`assets`、`dependencies`、`approval`、`implementation_status`、`qa_status`、`notes` 为生产/元数据字段，见 `templates/shot.shot.json`。）

### S001 — 空白对话窗口

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S001` |
| 2 | Duration | 8.0 s（00:00–00:08） |
| 3 | Narrative Purpose | 建立「AI 没有记忆」的日常痛点，第一人称代入 |
| 4 | Voice-over | 「每次对话，AI 都像第一次认识你。」 |
| 5 | On-screen Text | `SESSION 01 / 00:08`（小号等宽字，右下角） |
| 6 | Visual Description | 黑底白字的空白对话窗口，输入框始终为空，光标匀速闪烁；窗外微光缓慢变化 |
| 7 | Camera | static；极缓推 2%（1080p→1100p 等效），K1 缓动 |
| 8 | Motion | character: 光标闪烁（1.2s 周期）+ 极少量微尘粒子；intensity: micro |
| 9 | Audio | music: continue（低音垫）；sfx: [cursor tick]；ambience: [room tone]；sync_points: [00:02 光标声] |
| 10 | Transition In | cut |
| 11 | Transition Out | dissolve 0.3s |
| 12 | Layers | L001 BG（静态底色）/ L002 TYPOGRAPHY（等宽字体）/ L003 OVERLAY（光标层） |
| 13 | Route | Likely: REMOTION（精确光标时序与文字控制）；底层视觉不做 AI Video |
| 14 | Continuity Group | CG001（与 S002 同组，连续 Motion，禁止拆散） |

**Layer Intent（§59）**

- Background: 单色渐变底（VISUAL_BIBLE 主色 +5% 亮度），无纹理，呼吸感来自窗外光斑。
- Main concept: 空的对话窗口就是「记忆缺失」本身，不做多余装饰。
- Typography: 等宽字体小号角标，仅保留 `SESSION 01`，不解释。
- Atmosphere: 冷、安静、略带压迫；留白 ≥ 60%。
- Audio: 光标声是唯一高频 SFX，克制。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 用户大概率会反复调整光标节奏、VO 文案与角标文字；必须保留可编辑源（文案/时序参数化），禁止 bake 成 MP4。

**Audio Intention（§61）**

- Music: continue —— 低音垫延续，不抢 VO。
- SFX: cursor tick @00:02、00:04（Level 1 Invisible Audio）。
- Ambience: room tone -20 dB，恒定。
- Sync Point: 00:02 光标声与闪烁同拍。
- VO Ducking: VO 期间音乐 duck -3 dB。
- Silence: 00:06–00:08 保留 2 秒停顿（呼吸，不填音效）。

---

### S002 — 历史会话被清空

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S002` |
| 2 | Duration | 10.0 s（00:08–00:18） |
| 3 | Narrative Purpose | 把「没有记忆」具体化为可感画面：昨天说的话全部消失 |
| 4 | Voice-over | 「没有记忆，就无法真正理解你。」 |
| 5 | On-screen Text | `HISTORY CLEARED`（顶部淡入） |
| 6 | Visual Description | 一排历史会话卡片，从新到旧逐张淡出清空，最后只剩一个空白窗口 |
| 7 | Camera | static；微下沉（-3% Y），配合消失感 |
| 8 | Motion | character: 卡片逐张 alpha 0→100 消隐（stagger 0.2s）；intensity: narrative |
| 9 | Audio | music: continue；sfx: [page swipe ×3]；ambience: [room tone]；sync_points: [00:12 卡片清空] |
| 10 | Transition In | dissolve 0.3s |
| 11 | Transition Out | cut |
| 12 | Layers | L004 BG / L005 CARD_LIST（REMOTION）/ L006 TYPOGRAPHY |
| 13 | Route | Likely: REMOTION（stagger 消隐需要精确时序）；图片为占位素材 |
| 14 | Continuity Group | CG001 |

**Layer Intent（§59）**

- Background: 延续 SC001 底色。
- Main concept: 消隐的卡片墙 = 被清空的记忆。
- Typography: `HISTORY CLEARED` 大号标题，只出现一次。
- Atmosphere: 失落感；卡片消失瞬间给一次轻微运动模糊。
- Audio: 消隐与 page swipe 同拍。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 卡片数量、消失顺序可能随文案变动；参数化列表驱动。

**Audio Intention（§61）**

- Music: continue —— 低音垫保持不变，不推进。
- SFX: page swipe @00:09 / @00:11 / @00:13（每张卡）。
- Ambience: room tone -20 dB。
- Sync Point: 00:12 最后一张卡清空 = 视觉重音。
- VO Ducking: 无 VO 期间，music 恢复 0 dB。
- Silence: 00:17–00:18 1 秒静音接入 SC002 主题进入。

---

### S003 — 记忆三层结构

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S003` |
| 2 | Duration | 12.0 s（00:18–00:30） |
| 3 | Narrative Purpose | 给出第一个结构信息：工作记忆 / 长期记忆 / 回忆索引 |
| 4 | Voice-over | 「记忆分三层：正在用的、长期存的、和随时调回的索引。」 |
| 5 | On-screen Text | `WORKING / LONG-TERM / INDEX` |
| 6 | Visual Description | 三张卡片从下往上叠层，逐层点亮，配 2.5D 层间距 |
| 7 | Camera | static；层点亮时每层微前推 5% |
| 8 | Motion | character: 卡片 stacking + 点亮光晕；intensity: narrative |
| 9 | Audio | music: cue（主题首次进入）；sfx: [soft impact ×3]；ambience: [低频脉冲]；sync_points: [00:20/00:24/00:28 三层点亮] |
| 10 | Transition In | dissolve 0.4s |
| 11 | Transition Out | dissolve 0.3s |
| 12 | Layers | L007 BG / L008 CARD_STACK（REMOTION）/ L009 TYPOGRAPHY |
| 13 | Route | Likely: REMOTION（2.5D stacking 精确结构）；底层不用 AI Video |
| 14 | Continuity Group | CG002（S003–S005 结构段连续） |

**Layer Intent（§59）**

- Background: 深色渐变，中景景深。
- Main concept: 三层结构本身即内容，不画具象物体。
- Typography: 英文标签 + 中文说明双行。
- Atmosphere: 开始「讲技术」，节奏稍快但保持整洁。
- Audio: 三层点亮各一次 soft impact，密度控制在 Level 2。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 层名/文案可能改；三层的点亮顺序与时机参数化。

**Audio Intention（§61）**

- Music: cue —— 00:18 主题进入（与 Scene 音乐 cue 对齐）。
- SFX: soft impact @00:20 / 00:24 / 00:28。
- Ambience: 低频脉冲垫底，-25 dB。
- Sync Point: 三层点亮 = 三个 soft impact。
- VO Ducking: VO 期间 music duck -3 dB。
- Silence: 无（结构段维持推进感）。

---

### S004 — 向量库写入与召回

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S004` |
| 2 | Duration | 18.0 s（00:30–00:48） |
| 3 | Narrative Purpose | 说明「写入 + 召回」两个动作，一句话带过技术 |
| 4 | Voice-over | 「每条对话写入向量库；下次提问，按相关性实时召回。」 |
| 5 | On-screen Text | `WRITE → STORE → RETRIEVE` |
| 6 | Visual Description | 左侧消息块飞入库体，右侧按相关性高亮召回 3 条 |
| 7 | Camera | pan（左→右 15°）；配合数据流向 |
| 8 | Motion | character: 数据点流动 + 召回高亮；intensity: narrative |
| 9 | Audio | music: continue；sfx: [data pulse]；ambience: [低频脉冲]；sync_points: [00:36 写入 / 00:42 召回] |
| 10 | Transition In | dissolve 0.3s |
| 11 | Transition Out | dissolve 0.3s |
| 12 | Layers | L010 BG / L011 VECTOR_FIELD（REMOTION）/ L012 TYPOGRAPHY |
| 13 | Route | Likely: REMOTION（数据流动画）；背景库体可用 GENERATIVE 概念预览 |
| 14 | Continuity Group | CG002 |

**Layer Intent（§59）**

- Background: 抽象库体（粒子/网格），保持非具象。
- Main concept: 写入与召回的双向数据流。
- Typography: 三阶段标签横向排布。
- Atmosphere: 信息感、秩序感。
- Audio: data pulse 跟随流动节拍。

**Editability Requirement（§60）**

- 等级: **LOW**
- Reason: 数据流动画是整体连续 Motion，局部微调收益低；改文字/节奏时整段重渲代价可控（短镜头）。若用户未来想高频改，需升级为 HIGH 并拆层。

**Audio Intention（§61）**

- Music: continue —— 主题维持，不做新 cue。
- SFX: data pulse @00:36 / 00:42。
- Ambience: 低频脉冲 -25 dB。
- Sync Point: 00:36 写入、00:42 召回。
- VO Ducking: VO 期间 duck -3 dB。
- Silence: 无。

---

### S005 — 结构总览推镜

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S005` |
| 2 | Duration | 15.0 s（00:48–01:03） |
| 3 | Narrative Purpose | 总结记忆系统整体结构，给出本段唯一 Hero Effect 机会 |
| 4 | Voice-over | 「这就是完整的记忆层。」 |
| 5 | On-screen Text | `MEMORY LAYERS`（Hero 标题） |
| 6 | Visual Description | 三层结构整体透视，镜头从 45° 俯视推到平视，标题缩放进场 |
| 7 | Camera | orbit 45°→0° + push in 20% |
| 8 | Motion | character: 整体透视旋转 + 标题缩放（spring）；intensity: hero（全片 Hero Effect 密度需 ≤20–30%，见 §64） |
| 9 | Audio | music: cue（主题变奏）；sfx: [hero impact + whoosh]；ambience: [riser]；sync_points: [01:00 Hero impact] |
| 10 | Transition In | dissolve 0.4s |
| 11 | Transition Out | dissolve 0.5s |
| 12 | Layers | L013 BG / L014 STRUCTURE_3D（THREE_D 或 REMOTION 伪 3D）/ L015 TYPOGRAPHY |
| 13 | Route | Likely: REMOTION（结构化运动图形）+ 可选 THREE_D 3D 层；**不得断言**（Phase 3 定） |
| 14 | Continuity Group | CG002 |

**Layer Intent（§59）**

- Background: 深色纵深空间。
- Main concept: 三层结构整体 = 记忆系统全貌。
- Typography: `MEMORY LAYERS` 全片唯一 Hero 标题。
- Atmosphere: 峰值时刻；升调 riser + 一次 hero impact。
- Audio: Hero Sound（Level 3）只此一处，其余保持 Level 1/2。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 全片视觉峰值，用户大概率会反复调整标题、节奏、转场；透视与文字必须参数化。
- 注意（§63 示例）：本镜头最容易「做太花」。若修订反馈为「太花」，按 `workflows/storyboard.md` §63 处理：降级 motion 到 narrative、更新 Shot Memory、追加 D 决策并把旧决策标 superseded。

**Audio Intention（§61）**

- Music: cue —— 00:48 主题变奏进入。
- SFX: hero impact @01:00 + whoosh @00:58。
- Ambience: riser 00:48→01:00。
- Sync Point: 01:00 impact = 标题落位瞬间。
- VO Ducking: VO 结束后 music 可 +2 dB 顶到 impact。
- Silence: 01:02–01:03 收尾 1 秒休止，为 SC003 换场。

---

### S006 — 回到第一视角

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S006` |
| 2 | Duration | 9.0 s（01:03–01:12） |
| 3 | Narrative Purpose | 情感回收：从技术回到用户 |
| 4 | Voice-over | 「现在，它记得你。」 |
| 5 | On-screen Text | 无 |
| 6 | Visual Description | 与 S001 同一视角的对话窗口，但光标旁多了一个「记忆」光点，输入框有历史提示 |
| 7 | Camera | static（与 S001 严格同机位，形成对照） |
| 8 | Motion | character: 记忆光点脉冲 + 历史提示浮现；intensity: micro |
| 9 | Audio | music: continue（变奏延续）；sfx: [soft chime]；ambience: [room tone]；sync_points: [01:06 光点脉冲] |
| 10 | Transition In | dissolve 0.5s |
| 11 | Transition Out | cut |
| 12 | Layers | L016 BG / L017 WINDOW（复用 S001 组件）/ L018 GLOW |
| 13 | Route | Likely: REMOTION（复用 S001 组件，改参数） |
| 14 | Continuity Group | — |

**Layer Intent（§59）**

- Background: 同 S001，亮度 +8%（暖化）。
- Main concept: 同一窗口 + 记忆光点 = 前后对照。
- Typography: 无。
- Atmosphere: 温和、被记住的安心感。
- Audio: soft chime 替代 cursor tick，标记状态变化。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 复用 S001 组件，改参数即可，天然可编辑。

**Audio Intention（§61）**

- Music: continue —— 变奏延续。
- SFX: soft chime @01:06。
- Ambience: room tone -20 dB。
- Sync Point: 01:06 光点脉冲 = chime。
- VO Ducking: VO 期间 duck -3 dB。
- Silence: 无。

---

### S007 — 无记忆 vs 有记忆分屏

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S007` |
| 2 | Duration | 10.0 s（01:12–01:22） |
| 3 | Narrative Purpose | 直接对比：同一问题，两种回答 |
| 4 | Voice-over | 「同一个问题，过去是一片空白，现在是你的上下文。」 |
| 5 | On-screen Text | `BEFORE / AFTER` |
| 6 | Visual Description | 左右分屏：左侧空窗口，右侧完整上下文对话 |
| 7 | Camera | static；分屏中线从左向右滑动 |
| 8 | Motion | character: 分屏 wipe + 右侧内容逐行浮现；intensity: narrative |
| 9 | Audio | music: continue；sfx: [wipe whoosh]；ambience: [room tone]；sync_points: [01:15 wipe] |
| 10 | Transition In | cut |
| 11 | Transition Out | dissolve 0.3s |
| 12 | Layers | L019 LEFT（复用 S001）/ L020 RIGHT（REMOTION）/ L021 TYPOGRAPHY |
| 13 | Route | Likely: REMOTION（wipe + 内容时序） |
| 14 | Continuity Group | — |

**Layer Intent（§59）**

- Background: 中性底色，左右各半。
- Main concept: 对比即内容。
- Typography: `BEFORE / AFTER` 顶部小标。
- Atmosphere: 说服感，节奏轻快。
- Audio: 一次 wipe whoosh（Level 2），不过量。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 右侧示例文案可能替换；wipe 时机参数化。

**Audio Intention（§61）**

- Music: continue —— 维持推进。
- SFX: wipe whoosh @01:15。
- Ambience: room tone -20 dB。
- Sync Point: 01:15 wipe 与 whoosh。
- VO Ducking: VO 期间 duck -3 dB。
- Silence: 无。

---

### S008 — 收尾标题与行动号召

| # | 字段 | 值 |
|---|---|---|
| 1 | ID | `S008` |
| 2 | Duration | 8.0 s（01:22–01:30） |
| 3 | Narrative Purpose | 给出唯一行动号召并收束全片 |
| 4 | Voice-over | 「让 AI 记得你。」 |
| 5 | On-screen Text | `REMEMBER_AI` + 网址（Hero 收尾） |
| 6 | Visual Description | 深色底，标题逐字浮现，尾部淡出到黑 |
| 7 | Camera | static；极缓推 5% |
| 8 | Motion | character: 标题逐字入场（stagger）+ 结尾整体淡出；intensity: narrative |
| 9 | Audio | music: cue（收束）；sfx: []；ambience: [渐隐]；sync_points: [01:26 标题完全显现] |
| 10 | Transition In | dissolve 0.3s |
| 11 | Transition Out | fade to black 1.0s |
| 12 | Layers | L022 BG / L023 TYPOGRAPHY |
| 13 | Route | Likely: REMOTION（逐字入场）；或 JY_NATIVE 简单字幕（若无需精确时序） |
| 14 | Continuity Group | — |

**Layer Intent（§59）**

- Background: 黑底，无装饰。
- Main concept: 标题 + 网址即全部。
- Typography: 大号标题逐字浮现。
- Atmosphere: 收束、留白、呼吸。
- Audio: 无 SFX，音乐收束后 2 秒静音淡出。

**Editability Requirement（§60）**

- 等级: **HIGH**
- Reason: 网址/标题必然改动；逐字节奏参数化。

**Audio Intention（§61）**

- Music: cue —— 01:22 收束和弦，01:28 淡出。
- SFX: 无。
- Ambience: 渐隐至 -60 dB。
- Sync Point: 01:26 标题完全显现 = 和弦落点。
- VO Ducking: 无 VO 冲突。
- Silence: 01:28–01:30 全静（结尾冷场，符合 AUDIO_DIRECTION）。

---

## 4. 提交前自检清单

- [ ] 每个 Scene 的 `scene.shots[].shot_id` 与对应 Shot 的 `id` 完全一致（S###）
- [ ] Scene.target_duration = Σ Shot.duration（±5%）
- [ ] 每个 Shot 都有 Layer Intent 五段（Background / Main concept / Typography / Atmosphere / Audio）
- [ ] 每个 Shot 都有 Editability Requirement（HIGH / LOW + Reason）
- [ ] 每个 Shot 都有 Audio Intention 六项（Music / SFX / Ambience / Sync Point / VO Ducking / Silence）
- [ ] route 全部是 "Likely: …" 意向，没有断言 REMOTION / AI_VIDEO / HYBRID（§58）
- [ ] Director Consistency Check 已跑完且无阻塞项（§64）
- [ ] Reference Influence Check 已确认「学习原则」而非「复制镜头」（§65）
- [ ] 数据同步：`scenes/SC###.json`、`shots/S###.json`、`scenes/SC###.md`、`shots/S###.md` 均已生成

<!-- 生成/修订由 workflows/storyboard.md 驱动；批准后进入 Phase 3 SHOT_ROUTING。 -->
