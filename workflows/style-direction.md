---
workflow_id: WF-004
name: 风格方向
stage_ids: [STYLE_DIRECTION, VISUAL_BIBLE_REVIEW]
requires_approval: [VISUAL_BIBLE_REVIEW]
phase1_status: superseded
phase2_status: implemented
---

# 风格方向（Style Direction）

## 目标
基于 Project + Creative Direction + Reference + Platform + Audience 决定视觉风格，并固化为 `VISUAL_BIBLE.md`——项目后续所有视觉决策的最高约束之一（Storyboard / Shot / Asset / QA 对齐）。

## 触发时机
`CREATIVE_REVIEW` 已批准后触发。

## 输入（均需前序 Approval 通过）
1. `<project>/PROJECT_BRIEF.md`（`PROJECT_BRIEF_REVIEW` 已批准）
2. `<project>/CREATIVE_DIRECTION.md`（`CREATIVE_REVIEW` 已批准，含推荐 Option 与下一阶段输入提示）
3. `<project>/references/REFERENCE_ANALYSIS.md`（`REFERENCE_REVIEW` 已批准；无参考则结构化跳过）
4. `<project>/PROJECT_STATE.md` + `<project>/DECISIONS.md`

## 输出（项目文件）
- `<project>/VISUAL_BIBLE.md` — 使用模板 `templates/visual-bible.md`（全部 24 字段：Style Name / Style Mix / Design Philosophy / Color System / Typography / Composition / Spacing / Grid / Depth / Material / Lighting / Camera Language / Motion Character / Motion Intensity / Micro-motion / Transition Language / 2D-3D Balance / AI Video Treatment / Real Footage Treatment / Image Treatment / Subtitle Style / Graphic Elements / Texture · Grain / Effect Philosophy / Hero Effect Policy / Avoid List）。

## No Default Style 强规则（§30，宪法 #3）
- `presets/` 下 6 个 Style **完全同级**，无默认优先级，不建立 Personal DNA。
- **禁止**以"系统有 X 就推 X"或"之前项目用了 X"为由推荐某风格。每个推荐必须给出本项目依据（Brief / Creative Direction / Reference）。
- 允许根据 Reference 创建项目专属临时 Style；允许 Style Mix（语义权重，非数学混合）。

## 3 类选择动作（选一）
1. **单一 Preset**：直接选用 `presets/` 中的一个，Visual Bible 以该 preset 为基底展开。
2. **多 Preset Mix**：用 `60% Style A + 30% Style B + 10% Style C` 形式表达视觉语言权重（语义权重：谁负责底色、谁负责情绪、谁负责点缀），并在 Visual Bible 的 Style Mix 字段解释每个百分比含义。
3. **完全项目专属**：无合适 preset 时，依据 Reference 规律与 Creative Direction 自建 Style；必须在 Visual Bible 中写清它与 6 个 preset 的差异点，避免悄悄退回某个默认。

## 执行步骤
1. 读取输入，定位 Creative Direction 的推荐 Option 与"下一阶段输入提示"。
2. 从上述 3 类选择动作中做 Style 决定（写明为什么选/不选每个候选，引用本项目依据）。
3. 生成 Visual Bible：按模板 24 字段逐项填写；每个字段先结论后依据（依据来自 Creative Direction 的叙事方向或 Reference Report 的可复用规则），禁止空洞词。
4. **Effect Philosophy 3 级**：在 Visual Bible 的 Effect Philosophy 节列出本项目具体适用情况——Level 1 Invisible（大量）、Level 2 Narrative（按需）、Level 3 Hero（极少量）；并给出 Hero Effect Policy（数量上限 / 出现位置 / 铺垫要求）与具体 Avoid List（如"避免 strong glitch"，附理由）。
5. 在 `DECISIONS.md` 记录 Style 决策（D-xxx，含 Style 选择、Mix 权重、Hero Policy、Avoid 关键项）。
6. 更新 `PROJECT_STATE.md`（Current Style / Current Stage: VISUAL_BIBLE_REVIEW / Pending Decisions），推进到 `VISUAL_BIBLE_REVIEW`（waiting_user）。

## 阶段状态变更
`STYLE_DIRECTION` → `VISUAL_BIBLE_REVIEW` →（approve 后）`SOUND_DIRECTION`

## Approval Gate（VISUAL_BIBLE_REVIEW, waiting_user）
向用户呈现（必须包含，缺一不可）：
1. **What Style**（选择了哪个 preset / Mix / 专属 Style，含权重与原因）
2. **Why**（引用 Creative Direction 的叙事方向 + Brief / Reference 依据；说明为什么不是别的 Style）
3. **Effect Philosophy**（本项目 Invisible / Narrative / Hero 三级各用在哪里，Hero 数量上限）
4. **What to avoid**（具体 Avoid List + 理由）

用户选择：
- approved → 进入 sound-direction
- revision_requested → 回到 `STYLE_DIRECTION`，旧 Decision 标记 superseded，新 Decision 创建；本文件追加修订说明
- rejected → 停止并记录原因

## 引用
- 模板：`templates/visual-bible.md`；预设：`presets/`（6 个）
- 宪法 #3（No Default Style）、#5（Every Shot Receives Intentional Visual Treatment）
- 设计 v0.2 §8（Style Director / 6 类 Style / Mix 权重）、§9（Visual Bible）、§36（Effect 三级）

## 模板字段 ↔ visual-bible.schema.json 映射
模板（24 字段，更细）与 `schemas/visual-bible.schema.json`（18 必填 key）按以下映射落盘；模板独占字段并入 schema 对应字段的自由文本或项目 `notes`，不静默增删 schema。

| 模板字段 | schema key | 说明 |
|---|---|---|
| Style Name | `title` | 直接映射 |
| Style Mix | `title` / `notes` | schema 无独立 key，作为标题或备注保留权重表达 |
| Design Philosophy | `title` / `notes` | 并入标题描述或备注 |
| Color System | `color` | 直接映射 |
| Typography | `typography` | 直接映射 |
| Composition | `composition` | 直接映射 |
| Spacing | `whitespace` | 直接映射 |
| Grid | `whitespace` | 并入留白/间距描述 |
| Depth | `depth` | 直接映射 |
| Material | `material` | 直接映射 |
| Lighting | `lighting` | 直接映射 |
| Camera Language | `camera_language` | 直接映射 |
| Motion Character | `motion_character` | 直接映射 |
| Motion Intensity | `motion_character` | 并入动效性格（含强度档位） |
| Micro-motion | `motion_character` | 并入动效性格（含微动清单） |
| Transition Language | `transition` | 直接映射 |
| 2D / 3D Balance | `dimension_2d_3d` | 直接映射 |
| AI Video Treatment | `ai_video_treatment` | 直接映射 |
| Real Footage Treatment | `footage_treatment` | 直接映射 |
| Image Treatment | `image_treatment` | 直接映射 |
| Subtitle Style | `subtitle` | 直接映射 |
| Graphic Elements | `composition` / `notes` | 并入构图或备注 |
| Texture · Grain | `material` / `notes` | 并入材质或备注 |
| Effect Philosophy（三级） | `effect_philosophy` | 直接映射（含三级例子） |
| Hero Effect Policy | `effect_philosophy` | 并入特效哲学 |
| Avoid List | `avoid_list` | 直接映射（数组） |
