# STORY_BEAT_MAP — 模板

> 用途：叙事信息节奏层（总设计 v0.2 §16、§58-59；Editorial Director 输出，对应工作流 `workflows/editorial-direction.md`）。
>
> **Story Beat Map ≠ Shot List。** 本模板的单位是 **Beat**——叙事弧上的关键时刻。每个 Beat 是一个「信息传达节拍」：一条旁白、一组画面、一个信息点或一次情绪转折的最小叙事单元。它回答「此刻观众接收什么信息、产生什么情绪、被引导到什么问题」。
>
> Shot（镜头）是**视觉分解层**的单元，由 Storyboard 阶段从 Beat 展开：一个 Beat 可对应一个或多个 Shot，一个 Shot 也可能承载多个 Beat 的信息。本层**不做**镜头分解、不写运镜 / 图层 / 资产。
>
> 原则（v0.2 §16）：**不是每句旁白都做复杂动画**。每个 Beat 决定自己的视觉承载方式：照片即可 / 地图 / Timeline / Remotion / 3D / 真实素材 / AI Video / 留视觉休息。
>
> 使用时机：AUDIO_DIRECTION_REVIEW 批准后、Storyboard 之前生成；`STORY_REVIEW` 批准后作为 Storyboard 阶段的叙事依据。本模板给出结构骨架与两种节奏模板（Product Short / Editorial Explainer），项目使用时按实际叙事填充。

---

## 一、什么是 Beat（必读）

- **Beat 是信息节奏层的单元**：每个 Beat 是一拍叙事节拍，有明确的 Purpose（叙事目的）。
- **Beat 不是 Shot**：不在本层写镜头 / 运镜 / 图层 / 资产细节；那些属于 Storyboard（`templates/storyboard.md`）与 Shot / Layer 阶段。
- **Beat 不是 Chapter**：Chapter 是更大的章节单元（Scene 级）；Beat 是章节内部的节拍。每个 Beat 必须注明所属 Chapter。
- **Beat 必须可被观众感知**：如果删掉这个 Beat，叙事会缺一块（信息、情绪或转折），否则应合并进相邻 Beat。
- **Beat 顺序即播放顺序**：Time Range / Duration 用目标时长预估（MM:SS / 秒），Storyboard 阶段再锁定到 Shot。

## 二、节奏表（推荐 ≥ 12 个 Beat 占位，覆盖 Hook→Payoff 全节奏）

> 每个 Beat 一行；先定 Purpose 再补时间，不要让时间反过来决定叙事。
>
> <!-- 节奏角色序列：Hook → Context → Setup → Development ×2 → Pattern Interrupt → Examples → Visual Breathing Room → B-roll → Build → Reveal → Payoff + Recap -->

| Beat N | Time Range | Duration | Purpose | Viewer Question | Information | Emotion | Visual Opportunity | Audio Opportunity | Transition to next |
|---|---|---|---|---|---|---|---|---|---|
| Beat 01 | 00:00–00:20 | 20s | Hook：抓住注意力 | 这是什么？为什么值得看？ | 一句话主题 / 悬念钩子 | 好奇 | 视觉钩子（高冲击开屏）；引用 `effect_philosophy` / `motion_character` | 开场音 / Music entry；`sonic_motif` 首次进入 | 悬念切入 Context |
| Beat 02 | 00:20–00:50 | 30s | Context：建立语境 | 现在发生了什么？处在什么背景？ | 背景 / 术语 / 现状（先定义再展开） | 理解 / 认同 | 地图 / 时间线 / 静态说明；引用 `composition` / `whitespace` / `typography` | 环境音 / VO 进入；`ambience` / `music_direction` 低层 | 自然过渡到 Setup |
| Beat 03 | 00:50–01:20 | 30s | Setup：问题陈述 | 真正要解决的问题是什么？ | 核心问题 / 冲突点 | 疑问 / 紧张 | 问题可视化（图表 / 图标组合）；引用 `typography` | 音乐收紧 / SFX 铺垫 | 悬念收尾进入 Development |
| Beat 04 | 01:20–01:55 | 35s | Development：展开核心信息 | 那它是怎么运作的？ | 机制 / 原理第一层 | 好奇 / 投入 | 动画 / Timeline / 3D；引用 `depth` / `dimension_2d_3d` / `transition` | 分层音乐 / SFX 点缀；`music_direction` 分层 | 章内自然过渡 |
| Beat 05 | 01:55–02:30 | 35s | Development：细分拆解 | 关键细节是什么？ | 机制 / 原理第二层 + 证据 | 专注 / 惊讶 | 分屏对比 / 细节放大；引用 `transition` | 信息音点缀 / `ducking_strategy`（VO 优先） | 能量推到峰值，为打断蓄力 |
| Beat 06 | 02:30–02:50 | 20s | Pattern Interrupt：节奏突变 | （被打断）什么变了？ | 无新信息；换角度重述 / 短金句 | 惊醒 / 情绪重置 | 黑场 / 白屏 / 字卡突切；引用 `transition`（章节打断词汇） | 静默 / Silence / 单音 SFX；`silence_policy` | 用打断点切入 Examples |
| Beat 07 | 02:50–03:30 | 40s | Examples：实例落地 | 有没有真实例子？ | 案例 / 数据 / 类比 | 惊讶 / 共鸣 | B-roll / 真实素材 / 图表；引用 `footage_treatment` / `image_treatment` | 情绪高点 / Hero SFX；`ambience` / `voiceover_priority` | 数据收尾转向休息 |
| Beat 08 | 03:30–03:50 | 20s | Visual Breathing Room：留白消化 | （暂停发问，仅感受） | 无新信息，只强化情绪 | 沉淀 / 放松 | 留白 / 空镜 / 慢镜头；引用 `whitespace` / `motion_character`（低速段） | Silence / 环境声收低；能量降到最低点 | 舒缓过渡到 B-roll 段 |
| Beat 09 | 03:50–04:30 | 40s | B-roll：补充画面（B-roll Strategy） | 现实里长什么样？ | 场景化呈现（无硬新信息，补足感官） | 代入 / 真实感 | 真实素材 / 照片 / 档案；引用 `footage_treatment` / `ai_video_treatment` | `ambience` 铺底 / 环境音 | 自然过渡到 Build |
| Beat 10 | 04:30–05:10 | 40s | Build：累积张力 | 还差什么？接下来呢？ | 铺垫关键结论的最后一块信息 | 期待 / 紧张 | 节奏加快的蒙太奇 / 重复强化；引用 `motion_character`（高能量段） | 音乐爬升 / 鼓点叠加；`energy` 抬升 | 悬念收尾推向 Reveal |
| Beat 11 | 05:10–05:45 | 35s | Reveal：揭晓 | 那结果是什么？ | 关键结论 / 反转揭晓 | 满足 / 惊讶 | 高冲击 Reveal 画面；引用 `effect_philosophy` | 音乐落点 / impact；`hero_sound_policy` | 收束到 Payoff + Recap |
| Beat 12 | 05:45–06:30 | 45s | Payoff + Recap：兑现悬念并回顾 | 我应该记住什么？ | ≤3 个核心要点收拢 | 笃定 / 信任 | 要点列表 / 回顾图；引用 `typography` / `whitespace` | Music 稳定层 / VO 平稳；`sonic_motif` 再现 | 推向 Closing（项目按需补 CTA / Closing Beat） |

> 上表为占位节奏（≥ 12 个 Beat，覆盖 Hook→Payoff 全节奏）。实际 Beat 数由节奏模板决定：Product Short 6–8 个，Editorial Explainer 12–20 个（见第三、四节）。

### 字段说明（中文）

| 字段 | 含义 | 填写要求 |
|---|---|---|
| Beat N | 节拍编号 | 顺序即播放顺序，如 Beat 01 |
| Time Range | 预估时间段（MM:SS–MM:SS） | 目标时长预估，Storyboard 阶段锁定 |
| Duration | 预估时长（秒） | 与 Time Range 一致 |
| Purpose | 叙事目的 | 使用节奏角色词：Hook / Context / Setup / Feature / Hero Moment / Development / Example / Pattern Interrupt / Breathing Room / B-roll / Build / Reveal / Payoff / Recap / CTA / Closing |
| Viewer Question | 观众此刻心里的问题 | 每个 Beat 应随叙事提出或解答一个问题，保证「疑问-解答」闭环 |
| Information | 本拍传达的信息点 | 一句话，服从信息层级（哪些强、哪些弱） |
| Emotion | 目标情绪 | 与 Creative Direction 的 Emotional Direction 对齐：好奇 / 紧张 / 惊讶 / 轻松 / 信任… |
| Visual Opportunity | 视觉承载机会 | 引用 Visual Bible：motion_character / composition / whitespace / transition / effect_philosophy；并选承载方式（照片 / 地图 / Timeline / Remotion / 3D / 素材 / AI Video / 留白） |
| Audio Opportunity | 声音机会 | 引用 Audio Direction：sonic_motif / energy / sfx_language / ducking_strategy / silence_policy |
| Transition to next | 过渡到下一拍的方式 | 自然过渡 / 章节打断（Pattern Interrupt）/ 悬念收尾 |

---

## 三、Product Short 节奏模板（30s–2min，6–8 Beats）

> 适用：`production_mode = PRODUCT_TECH_SHORT`，偏 Remotion / UI / Motion / 3D / Cinematic（v0.2 §58）。
> 节奏特征：快、密、短；信息量有限，情绪优先；一镜一义，无长铺垫。

### 模板骨架

| Beat 角色 | 作用 | 注意 |
|---|---|---|
| **Hook**（Beat 1） | 前 3–8 秒抓住注意力 | 视觉冲击或悬念开场，不解释 |
| **Setup**（Beat 2） | 一句话说明「这是什么」 | 不超过 15s |
| **Feature**（Beat 3–4） | 展示核心功能 / 卖点 | 每个卖点一拍；只讲最强 1–3 个 |
| **Hero Moment**（Beat 5） | 全片最强视觉瞬间 | 与 Audio Direction 的 hero_sound_policy 对齐 |
| **CTA**（Beat 6） | 行动号召 | 一个动作，不堆叠 |
| **Closing**（Beat 7，可选） | Logo / 品牌收尾 | 极短，承接 CTA |

### Example：虚构 60s AI 产品短片（6 Beats）

| Beat N | Time Range | Duration | Purpose | 中文说明 |
|---|---|---|---|---|
| Beat 01 | 00:00–00:06 | 6s | Hook | 开场 6 秒：产品核心画面极速切入 + 悬念字幕，抓住注意力 |
| Beat 02 | 00:06–00:18 | 12s | Setup | 用一句话 + 图标说明「这是什么、解决什么问题」，建立背景 |
| Beat 03 | 00:18–00:32 | 14s | Feature | 展示核心功能一：实时转录；同步上屏文字验证 |
| Beat 04 | 00:32–00:46 | 14s | Feature | 展示核心功能二：一键生成摘要；动效演示结果 |
| Beat 05 | 00:46–00:54 | 8s | Hero Moment | 全片最强视觉：摘要卡片流光 Reveal + 声音 impact |
| Beat 06 | 00:54–01:00 | 6s | CTA / Closing | 行动号召 + Logo 收尾，结束 |

> 说明：6 个 Beat 覆盖 6 个角色，不设 Breathing Room 与 Recap——短内容不需要。若时长更长（1.5–2min），可在 Feature 与 Hero Moment 之间加 1–2 个 Feature Beat，最多 8 个。

---

## 四、Editorial Explainer 节奏模板（5–10min，12–20 Beats）

> 适用：`production_mode = EDITORIAL_EXPLAINER`，偏 Footage / Image / Map / Archive / Remotion Assets / 3D / AI Video（v0.2 §59）。
> 节奏特征：张弛有度；旁白重要；信息有层级；**必须有视觉休息**。剪映是主时间线，Remotion 更像 AE。

### 模板骨架（12–20 Beats）

| Beat 角色 | 作用 | 建议 Beat 数 |
|---|---|---|
| **Hook** | 开场抓住注意力，提出核心问题 | 1–2 |
| **Context** | 建立背景、术语、问题的为什么 | 2–3 |
| **Development** | 展开机制 / 原理，信息主战场 | 4–6 |
| **Examples** | 真实案例 / 数据 / 类比，让信息落地 | 2–4 |
| **Recap** | 回顾核心要点 | 1–2 |
| **Closing** | 收束观点 + 行动号召 | 1 |

### 5–10min Explainer 硬约束（Test 10）

以下五项**必须全部出现**，缺一即不合格：

1. **Chapter structure**：必须有章节划分，每个 Chapter 有明确信息目标与情绪曲线。
2. **Pattern Interrupt**：必须在节奏高峰 / 章节边界设打断点（视觉或叙事变化）防疲劳。
3. **Visual Breathing Room**：必须安排视觉休息段（留白 / 空镜 / 静默），信息密度过高时段尤其需要。
4. **B-roll Strategy**：必须有 B-roll 覆盖策略——哪段信息配真实素材 / 照片 / 档案，避免全程动画轰炸。
5. **Recap**：结尾必须回顾，把信息收拢成 ≤3 个可记忆要点。

**Example：虚构 8 分钟科普「为什么 AI 需要记忆」（16 Beats，含章节划分）**

| Beat N | Time Range | Duration | Purpose | 中文说明 |
|---|---|---|---|---|
| **Ch.1 · 悬念开场** | 00:00–01:00 | 60s | Chapter Marker | 信息目标：抛反直觉问题 + 建立背景；情绪曲线：好奇 → 理解 |
| Beat 01 | 00:00–00:20 | 20s | Hook | 抛反直觉问题「AI 记不住昨天，这正常吗」，配高冲击视觉钩子，抓注意力 |
| Beat 02 | 00:20–01:00 | 40s | Context | 用地图 / 时间线对比人类与 AI 的记忆差异，建立背景 |
| **Ch.2 · 机制** | 01:00–02:50 | 110s | Chapter Marker | 信息目标：讲清上下文窗口与遗忘机制；情绪曲线：好奇 → 紧张 |
| Beat 03 | 01:00–01:45 | 45s | Development | 核心机制一：上下文窗口是什么、容量为何有限；动画 / Timeline 示意 |
| Beat 04 | 01:45–02:30 | 45s | Development | 核心机制二：训练与推理分离、记忆不持久；3D 示意图 |
| Beat 05 | 02:30–02:50 | 20s | Pattern Interrupt #1 | 节奏突变：黑场 + 静默 + 单字字幕「失忆」，形成情绪冲击点 |
| **Ch.3 · 后果** | 02:50–04:00 | 70s | Chapter Marker | 信息目标：展示遗忘造成的实际问题；情绪曲线：紧张 → 代入 |
| Beat 06 | 02:50–03:30 | 40s | Development | 后果：忘记上下文导致答非所问；动画演示一段错误对话 |
| Beat 07 | 03:30–04:00 | 30s | B-roll | B-roll 段：真实办公 / 客服场景素材 + 录屏片段（B-roll Strategy），避免全程动画轰炸 |
| **Ch.4 · 案例** | 04:00–05:20 | 80s | Chapter Marker | 信息目标：用真实案例与数据让信息落地；情绪曲线：惊讶 → 共鸣 |
| Beat 08 | 04:00–04:30 | 30s | Example | 案例一：实测「AI 忘记对话」录屏，展示错误回答全过程 |
| Beat 09 | 04:30–05:00 | 30s | Example | 案例二：数据图表——遗忘导致准确率骤降 |
| Beat 10 | 05:00–05:20 | 20s | Pattern Interrupt #2 | 节奏突变：白屏 + 环境声残留 + 语速加快，与前一拍形成反差 |
| **Ch.5 · 方案与成果** | 05:20–06:40 | 80s | Chapter Marker | 信息目标：给出解法并验证效果；情绪曲线：期待 → 释然 |
| Beat 11 | 05:20–05:50 | 30s | Development (Solution) | 方案：外置记忆 / 记忆层是什么，示意动画 |
| Beat 12 | 05:50–06:20 | 30s | Example | 案例三：加入记忆后准确率提升，前后对比图表 |
| Beat 13 | 06:20–06:40 | 20s | Visual Breathing Room | 留白空镜 + 静默，让观众消化信息（无新信息，只强化情绪） |
| **Ch.6 · 收束** | 06:40–08:00 | 80s | Chapter Marker | 信息目标：回顾要点、收束观点；情绪曲线：笃定 → 行动 |
| Beat 14 | 06:40–07:10 | 30s | Recap | 要点图回顾 ≤3 个核心结论：上下文窗口有限 / 训练推理分离 / 外置记忆可行 |
| Beat 15 | 07:10–07:30 | 20s | Closing | 收束观点：记忆是智能的基础；抛出一个开放问题 |
| Beat 16 | 07:30–08:00 | 30s | CTA / Outro | 行动号召（关注下期「AI 如何学会长期记忆」）+ 片尾淡出 |

> 说明：本示例用 **16 个 Beat + 6 个 Chapter 边界**覆盖完整叙事弧（Hook / Context / Development / Examples / Recap / Closing 全部到位），显式标注 Chapter 边界，且包含 **2 次 Pattern Interrupt、1 个 Visual Breathing Room、1 段明确 B-roll**，末尾 Recap 收拢为 ≤3 个要点——满足第四节五项硬约束（Test 10）。Time Range 为预估，实际以 Storyboard 为准。

---

## 五、与 Visual Bible / Audio Direction 的衔接

每个 Beat 的 `Visual Opportunity` 与 `Audio Opportunity` 两列是**桥**：本层只做选择与引用，不展开实现。

### Visual Opportunity → Visual Bible

| 节奏角色 | 引用 Visual Bible 字段（`schemas/visual-bible.schema.json`） |
|---|---|
| Hook / Hero Moment / Payoff | `effect_philosophy`、`motion_character`（高能量段） |
| Setup / Context | `composition`、`whitespace`、`typography` |
| Feature / Development | `depth`、`dimension_2d_3d`、`transition` |
| Examples / B-roll | `footage_treatment`、`image_treatment`、`ai_video_treatment` |
| Breathing Room | `whitespace`、`motion_character`（低速段）、`subtitle` |
| Transition to next | `transition`（章内 / 章节打断的转场词汇） |

### Audio Opportunity → Audio Direction

| 节奏角色 | 引用 Audio Direction 字段（`schemas/audio-direction.schema.json`） |
|---|---|
| Hook / Hero Moment | `hero_sound_policy`、`energy`、`sonic_motif` 首次进入 |
| Setup / Context | `ambience`、`music_direction` 低层 |
| Development | `music_direction` 分层、`sfx_language`、`motion_sound_language` |
| Examples / B-roll | `ambience`、`voiceover_priority`、`ducking_strategy` |
| Breathing Room | `silence_policy`、能量降到最低点 |
| CTA / Closing | `sonic_motif` 收束 / 再现，收尾音 |

### 向下游交接

`STORY_REVIEW` 批准后，Storyboard 阶段把每个 Beat 展开为 Shot；`Visual Opportunity` 的承载方式与 Visual Bible 引用继承进 `shot.visual_description` / `scene.visual_direction`，`Audio Opportunity` 的 Sonic Motif 引用继承进 `shot.audio` / `scene.audio_direction`（与 `schemas/scene.schema.json`、`schemas/shot.schema.json` 对齐）。若某个 Beat 的 `Visual Opportunity` 选「留视觉休息」，Storyboard 阶段必须保留该 Beat 为低信息密度段，不得反填动画。

<!-- 使用规则
1. Beat 是信息节奏层单元，不是 Shot；本模板不写运镜 / 图层 / 资产。
2. 先按 production_mode + target_duration 选节奏模板（第三节 / 第四节），再填节奏表。
3. EDITORIAL_EXPLAINER 必须满足第四节五项硬约束（Test 10），缺一即不合格。
4. 每列的填写要求见「字段说明（中文）」；Purpose 用节奏角色词，保持与 Creative Direction 的 Creative Angle / Emotional Direction 一致。
5. Visual Opportunity / Audio Opportunity 只引用 Visual Bible / Audio Direction 字段，不展开实现。
6. 与 DECISIONS.md：重大叙事结构变更需记录 D-### 决策（追加，不覆盖）。
-->
