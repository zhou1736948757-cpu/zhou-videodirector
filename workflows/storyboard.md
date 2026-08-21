---
workflow_id: WF-007
name: 分镜设计
stage_ids: [STORYBOARD, STORYBOARD_REVIEW]
requires_approval: [STORYBOARD_REVIEW]
phase2_status: implemented
---

# 分镜设计（Storyboard）

## 目标

把已批准的 Beat Map 拆成 **Scene → Shot → Layer** 完整镜头分解表，生成 `STORYBOARD.md`，并落地 Scene / Shot JSON 与 Scene / Shot Memory。Storyboard = Scene × Shot 完整镜头分解表（Phase-2 §62）。原则：**分镜阶段只做设计，不做技术路由、不写任何实现代码**。

## 触发时机

`STORY_REVIEW`（STORY / BEAT MAP 审批）已批准后触发。前置四份导演文档全部 Approval 后才开始。

## 输入（全部须已批准）

- `<project>/CREATIVE_DIRECTION.md`（Creative Direction，`CREATIVE_REVIEW` 已批准）
- `<project>/VISUAL_BIBLE.md`（Visual Bible，`VISUAL_BIBLE_REVIEW` 已批准）
- `<project>/AUDIO_DIRECTION.md`（Audio Direction，`AUDIO_DIRECTION_REVIEW` 已批准）
- `<project>/STORY_BEAT_MAP.md`（Beat Map / STORY.md，`STORY_REVIEW` 已批准）
- Schema：`schemas/scene.schema.json`、`schemas/shot.schema.json`、`schemas/layer.schema.json`
- 模板：`templates/storyboard.md`、`templates/scene.scene.json`、`templates/shot.shot.json`

## 输出（项目文件）

- `<project>/STORYBOARD.md` — Scene × Shot 完整分解表（模板 `templates/storyboard.md`）
- `<project>/scenes/SC###.json` — Scene JSON（模板 `templates/scene.scene.json`）
- `<project>/shots/S###.json` — Shot JSON（模板 `templates/shot.shot.json`）
- `<project>/scenes/SC###.md` — Scene Memory（模板 `templates/scene-memory.md`）
- `<project>/shots/S###.md` — Shot Memory（模板 `templates/shot-memory.md`）
- （辅助）`<project>/AUDIO_MAP.md` — 音频时间轴（模板 `templates/audio-map.md`，与 shot.audio.sync_points 对齐）

## 执行步骤

1. **读齐四份已批准输入**：Creative / Visual Bible / Audio Direction / Beat Map。任何一份未批准则 `blocked` 并阻塞，不进分镜。
2. **按 Chapter 划分 Scene**（SC001…）：标注 narrative_role（Hook / Setup / Development / Reveal / Payoff / Recap / Closing / …）与 target_duration；Scene 设计 9 字段见 §56（id / chapter / order / title / narrative_role / purpose / target_duration / visual_direction / audio_direction）。
3. **每个 Scene 拆 Shot**（S001…）：Shot 设计 14 字段见 §57（id / duration / narrative_purpose / voiceover / on_screen_text / visual_description / camera / motion / audio / transition_in / transition_out / layers / route / continuity_group）。`start_time / end_time` 由累计时长推导，`duration = end_time - start_time`，Scene 总长与 `target_duration` 对齐（±5%）。
4. **Layer 意图化（不实现 Layer）**：为每个 Shot 写下 Layer Intent（§59），必要时给 Layer ID 占位（L###）但不实现 Layer 实体。
5. **NO premature Route（§58）**：分镜阶段 route 只写 **Likely 意向**（如 `Likely: structured motion graphic` / `Likely: JY_NATIVE simple text`），**禁止断言** REMOTION / AI_VIDEO / HYBRID；Shot JSON 的 `route` 字段一律填 `UNDECIDED`，意向写入 `notes`。最终 Routing 属于 Phase 3（`SUBAGENT_CONFIGURATION` → `SHOT_ROUTING`）。
6. **填 Layer Intent（§59）**：每个 Shot 五段描述 —— Background / Main concept / Typography / Atmosphere / Audio。
7. **填 Editability Requirement（§60）**：每个 Shot 判定 `HIGH / LOW` + Reason。HIGH = 用户可能经常手工调整，保留可编辑源（参数化 / 组件化，不 bake）；LOW = 允许 bake 成不可编辑片段（如连续 Motion 整段渲染）。
8. **填 Audio Intention（§61）**：每个 Shot 六项 —— Music / SFX / Ambience / Sync Point / VO Ducking / Silence。与 AUDIO_DIRECTION 一致；Silence 必须显式保留，防止 Audio Overload。
9. **生成 STORYBOARD.md**：总览表（Scene ID | Title | Duration | Shot Count | Avg Shot Duration）+ 每个 Scene 一节（9 字段 + Shot 列表）+ 每个 Shot 一小节（14 字段 + Layer Intent / Editability / Audio Intention）。
10. **落地 JSON + Memory**：写 `scenes/SC###.json`、`shots/S###.json`，同步更新 `scenes/SC###.md`、`shots/S###.md`（Change History 追加）、`AUDIO_MAP.md`。
11. **内部自检（提交用户前）**：
    - §64 Director Consistency Check（结构一致性 + 密度 + Hero Effect 密度 + Motion Diversity + Audio Overload + Editability 覆盖率）
    - §65 Reference Influence Check（学习原则 vs 复制镜头）
    - 自检清单：见 `templates/storyboard.md` 第 4 节。
12. **推进到 `STORYBOARD_REVIEW`**（waiting_user），提交摘要含 Approval Gate 要求的六项指标。

## 阶段状态变更

`STORYBOARD` → `STORYBOARD_REVIEW` →（approve 后）`SUBAGENT_CONFIGURATION`

## Approval Gate（STORYBOARD_REVIEW → waiting_user）

提交给用户审批时，摘要必须列出：

- Scene count（场景数）
- Shot count（镜头数）
- Avg shot duration（平均镜头时长）
- Layer Intent coverage（每个 Shot 是否都有五段 Layer Intent；覆盖率 %）
- Editability note coverage（每个 Shot 是否都有 Editability HIGH/LOW + Reason；覆盖率 %）
- Director Consistency Check pre-result（§64 内部检查预检结果：通过 / 警告清单）

- approved → 进入 Phase 3 routing（`SUBAGENT_CONFIGURATION`）
- revision_requested → 回到 `STORYBOARD`，按 §63 Revision 处理

## §63 Revision 处理（示例：S05 太花）

用户对 STORYBOARD_REVIEW 打回 `revision_requested`，反馈「S05 太花」。执行：

1. 定位问题：S05 的 motion.intensity=hero + 透视旋转 + 标题 spring，可能超出 Visual Bible 约束或 Hero Effect 密度上限。
2. 修改设计：把 S05 降级为 narrative 强度（去掉多余旋转，标题 spring 改缓入）；同步改 `shots/S005.json` 的 `motion` / `visual_description` / `notes`。
3. 更新 Shot Memory：`shots/S005.md` 的 Approved Visual / Motion 更新，Change History 追加一条（时间 + 变更摘要 + 原因）。
4. 创建 Decision：`DECISIONS.md` 追加 `D-NNN`（Scope: Shot S005，Decision: S005 由 hero 降级为 narrative，Reason: 用户反馈「太花」）。
5. 旧 Decision 标 superseded：若原 S005 设计存在旧 D 记录，新 D 的 `Supersedes: [D-旧]`，并把旧记录 Status 置为 Superseded（只追加、不删除、不改写历史，见 `docs/memory-system.md`）。
6. 同步更新 Scene JSON / STORYBOARD.md / approvals.yaml（如涉及审批记录），重新推进 `STORYBOARD_REVIEW`（waiting_user）。

## §64 Director Consistency Check（提交用户前的内部检查）

提交 STORYBOARD_REVIEW 前必须完成（结构性脚本 `scripts/director-consistency-check.py` 提供量化支持，P2-7）：

| 检查项 | 内容 | 通过标准 |
|---|---|---|
| Creative Consistency | 每个 Scene/Shot 是否符合 CREATIVE_DIRECTION 的 Core Idea / Viewer Tension | 无漂移 |
| Visual Consistency | 是否符合 VISUAL_BIBLE（色彩 / 字体 / 构图 / 留白 / 避免清单） | 无违反避免清单项 |
| Audio Consistency | 是否符合 AUDIO_DIRECTION（音乐方向 / SFX 语言 / Hero Sound 策略） | 无冲突 |
| Editorial Consistency | 是否符合 STORY_BEAT_MAP 的 Pacing / 信息层级 / 呼吸感 | 节奏连续 |
| Density | 信息密度合理（不是每句旁白都做复杂动画） | 低信息 Beat 用静态/简单镜头承载 |
| Hero Effect Density | Hero Effect（intensity=hero）占比 | ≤ 20–30% |
| Motion Diversity | Motion 类型分布 | ≥ 3 种不同 Motion Character，避免全片单一 |
| Audio Overload | Music / SFX / Ambience 密度与 Silence 保留 | 每 Scene 至少 1 处 Silence / 呼吸点 |
| Editability | Editability Requirement 标注覆盖率 | 100%（每个 Shot 有 HIGH/LOW + Reason） |

结果记录在提交摘要的 pre-result 字段。警告项必须逐条处理或显式说明保留理由。

## §65 Reference Influence Check

提交前确认每个高视觉强度镜头：

- **学习原则 vs 复制镜头**：镜头是否来自 Reference 提炼出的可复用规律（构图原则 / 节奏规律 / 转场习惯），而非逐镜复刻 Reference 的画面。
- **太接近原 Reference 时主动调整**：若某镜头与原 Reference 的画面构成、运镜、时序高度相似，主动调整（换景别 / 换节奏 / 换视觉载体 / 换转场），并在 notes 记录调整理由。
- 结论写入 STORYBOARD.md 自检清单；有刻意保留的相似镜头，必须追加 D 决策说明理由（避免清单有冲突时优先服从避免清单）。

## 禁止事项

- 不实现 Shot / Layer Router（Phase 3 才做）。
- 不写 Remotion / Three.js / AI Video Prompt 等实现代码。
- route 不断言（§58）：只写 Likely 意向，JSON 中一律 `UNDECIDED`。
- 不生成或生产真实资产（Phase 2 只允许占位 Asset Requirement）。
- 不修改其它 worker 负责的文件；不修改 `schemas/shot.schema.json` 顶层（Phase 2 不容许 schema minimal fix，新增字段只能放 notes / 嵌套对象）。
