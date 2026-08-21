---
workflow_id: WF-006
name: 叙事方向
stage_ids: [EDITORIAL_DIRECTION, STORY_REVIEW]
requires_approval: [STORY_REVIEW]
phase2_status: implemented
---

# 叙事方向（Editorial Direction）

## 目标
设计视频的叙事结构：Narrative Arc、Chapter 划分、Pacing 与信息层级，并决定每个叙事 Beat 的视觉承载方式，产出 `STORY_BEAT_MAP.md`。原则：**不是每句旁白都做复杂动画**（v0.2 §16）。

## 职责边界：Editorial Director ≠ Storyboard Engine

- Editorial 负责**信息节奏层**（narrative arc）：单位是 **Beat**——叙事弧上的关键时刻，每个 Beat 是一个「信息传达节拍」。
- Storyboard 负责**视觉分解层**（visual breakdown）：把 Beat 展开为 Scene / Shot / Layer。
- 本阶段只产出 `STORY_BEAT_MAP.md`：**不做**镜头分解、不写运镜 / 图层 / 资产、不生成分镜。避免职责膨胀，避免跳过叙事确认直接进入视觉细节。

## 触发时机
`AUDIO_DIRECTION_REVIEW` 已批准后触发。

## 输入（全部已 Approval）
- `<project>/PROJECT_STATE.md`、`<project>/PROJECT_BRIEF.md`
- `<project>/CREATIVE_DIRECTION.md`（已过 `CREATIVE_REVIEW`）— 用其中的 **Creative Angle / Viewer Tension / Emotional Direction / Reveal / Payoff** 引导节奏
- `<project>/VISUAL_BIBLE.md`（已过 `VISUAL_BIBLE_REVIEW`）— `Visual Opportunity` 的引用源
- `<project>/AUDIO_DIRECTION.md`（已过 `AUDIO_DIRECTION_REVIEW`）— `Audio Opportunity` 的引用源，重点对齐 **Sonic Motif / energy / ducking_strategy**
- `<project>/references/REFERENCE_ANALYSIS.md`（如存在，用 `editorial_summary`）

## 输出（项目文件）
- `<project>/STORY_BEAT_MAP.md`（或 STORY.md）— 按 `templates/story-beat-map.md`：Narrative Arc / Chapter / Beat 节奏表 / Information Hierarchy / Pacing / Hook / Setup / Payoff / Pattern Interrupt / B-roll Strategy / Visual Breathing Room / Recap
- 模板：`templates/story-beat-map.md`

## 模板选择（按 production_mode + target_duration）

| production_mode | target_duration | 节奏模板 | 推荐 Beat 数 |
|---|---|---|---|
| `PRODUCT_TECH_SHORT` | 30s–2min | Product Short（`story-beat-map.md` 第三节） | 6–8 |
| `EDITORIAL_EXPLAINER` | 5–10min | Editorial Explainer（`story-beat-map.md` 第四节） | 12–20 |
| `CUSTOM` | 用户定义 | 与用户确认后取两者之一或混合 | 参考两者 |

## 5–10min Explainer 硬约束（Test 10）

`EDITORIAL_EXPLAINER`（及 CUSTOM 中用户确认的长视频）必须遵守以下五项，缺一即不合格（Test 10 判定 FAIL）：

1. **Chapter structure**：必须有章节划分，每章有明确信息目标与情绪曲线。
2. **Pattern Interrupt**：必须在节奏高峰 / 章节边界设打断点，防疲劳。
3. **Visual Breathing Room**：必须安排视觉休息段，信息高密度时段尤其需要。
4. **B-roll Strategy**：必须有 B-roll 覆盖策略，避免全程动画轰炸。
5. **Recap**：结尾必须回顾，信息收拢成 ≤3 个可记忆要点。

**禁止用 PRODUCT_SHORT 节奏硬套长视频**：短节奏（快 / 密 / 无休息）会拉垮 5–10min 叙事。

## 执行步骤
1. 阅读全部导演层输入（上述输入均为已批准文档）。
2. 用 creative-direction 的 **Creative Angle** 引导整体节奏：Hook 怎么开、信息怎么排序、Payoff / Reveal 放哪、Viewer Question 怎么闭环。
3. 与 audio-direction 的 **Sonic Motif** 对齐：每个 Beat 的 `Audio Opportunity` 引用 `sonic_motif` / `energy` / `ducking_strategy`；Hook / Hero Moment 与 `hero_sound_policy` 对齐。
4. 按 production_mode + target_duration 选择节奏模板（见上表），设计 Narrative Arc 与 Chapter 顺序，生成 Beat Map。
5. 为每个 Beat 指定视觉承载方式：照片即可 / 地图 / Timeline / Remotion / 3D / 真实素材 / AI Video / 留视觉休息；`Visual Opportunity` 引用 Visual Bible 对应字段。
6. 明确信息层级（哪些信息必须强调、哪些弱化），在 `Information` 列标注。
7. 写入 `<project>/STORY_BEAT_MAP.md`，在 `DECISIONS.md` 落一条决策（D-###）。
8. 推进到 `STORY_REVIEW`（waiting_user）。

## 阶段状态变更
`EDITORIAL_DIRECTION` → `STORY_REVIEW` →（approve 后）`STORYBOARD`

## Approval Gate（`STORY_REVIEW`，waiting_user）

审批时逐项核对 `STORY_BEAT_MAP.md`（对应 `approvals.yaml` 的 `story_structure` 审批范围，Approval 记录 `AP-###` 永久保留）：

- **Chapter structure**：章节划分是否清晰、是否贴合 Creative Angle
- **Beat count**：Beat 数与时长是否符合模板（Product Short 6–8 / Explainer 12–20）
- **Visual breathing room pattern**：视觉休息是否成规律出现、不密集轰炸
- **B-roll strategy**：B-roll 覆盖是否足够、是否与信息密度匹配
- **Pattern interrupt points**：打断点位置是否合理（节奏高峰 / 章节边界）

分支：
- approved → 进入 storyboard
- revision_requested → 回到 `EDITORIAL_DIRECTION` 修改故事结构，新 Decision `D-NNN Supersedes: D-MMM`
- rejected → 停止并记录原因

## 典型分支
- 信息密度过高 → 增加 Visual Breathing Room / 拆分 Beat，回到步骤 4-5。
- Chapter 过多 → 合并 Chapter 或调整 Pacing。
- 用户要求改 Hook / 换 Creative Angle → 回到步骤 2，重排 Beat 顺序并更新 `DECISIONS.md`（追加，不覆盖）。
- `CUSTOM` 模式 → 先与用户确认节奏模板再生成。

## 禁止事项
- 不实现 Shot Router（Phase 3）
- 不实现自动 Storyboard（Scene / Shot / Layer 拆解属 `STORYBOARD` 阶段）
- 不修改 schemas（Scene / Shot 字段与 `schemas/scene.schema.json`、`schemas/shot.schema.json` 对齐，不在本层新增）
- 不直接生成动画 / 渲染

## 实现状态
> 当前实现状态：implemented（Phase 2）。
> 模板：`templates/story-beat-map.md`（Beat 节奏表 + Product Short / Editorial Explainer 两种节奏 + 与 Visual Bible / Audio Direction 的衔接）。
> 复用能力（docs/reuse-map.md）：KNOWLEDGE_ADAPTER 参考 `DirectorSKILL`（Beat / 方法论）、`video-shotcraft`（产品节奏、SFX/声音设计），借方法论，不整体复制。
