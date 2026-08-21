---
workflow_id: WF-003
name: 创意方向
stage_ids: [CREATIVE_DIRECTION, CREATIVE_REVIEW]
requires_approval: [CREATIVE_REVIEW]
phase1_status: superseded
phase2_status: implemented
---

# 创意方向（Creative Direction）

## 目标
回答"视频讲什么、为什么值得看"：产出 **Core Idea / Viewer Promise / Hook / Central Tension / Creative Angle / Narrative Device / Emotional Direction / Reveal Strategy / Payoff / Memory Point / Closing Impression**，并给出 **2-3 个 Creative Options + 推荐**。本阶段**严格不**考虑如何实现（Director Before Engineer，宪法 #1）。

## 触发时机
`REFERENCE_REVIEW` 已批准（或无参考被结构化跳过）后触发。

## 输入（3 路，均需前序 Approval 通过）
1. `<project>/PROJECT_BRIEF.md` — 项目目的 / 目标用户 / 平台 / 时长 / 是否旁白等（`PROJECT_BRIEF_REVIEW` 已批准）。
2. `<project>/references/REFERENCE_ANALYSIS.md` — 参考规律四维分析（`REFERENCE_REVIEW` 已批准；无参考则结构化跳过，不伪造依据）。
3. `<project>/PROJECT_STATE.md` + `<project>/DECISIONS.md` — 当前阶段与历史决定，作为决策边界。

## 输出（项目文件）
- `<project>/CREATIVE_DIRECTION.md` — 使用模板 `templates/creative-direction.md`。

## 禁止（§24：本阶段不做任何工具/技术选择）
- **绝不出现** React / Three.js / Remotion / 模型下载 / AI Video 调用 / 渲染引擎等任何技术选型字样。
- 不写视觉实现细节（不写构图、字体、特效、镜头）。
- 不暴露私有 chain-of-thought；所有结论可被用户从 Brief / Reference 中复核。

## 执行步骤
1. 读取三路输入（§输入）。
2. **判断创意复杂度**：需求明确（如"新品 60s 发布片"）→ 2 个 Options；需求模糊（如"讲 AI Memory"）→ 3 个 Options；不强行凑满 3 个。
3. **生成 Creative Options**：每个 Option 必须给出 Concept / Why it works / Strength / Weakness / Best for / Risk。
4. **推荐 1 个**并写理由：引用 Project Brief 的具体条目 + Reference Report 的可复用规则；说明为什么不选其它 Option；给出风险缓解方式与下一阶段（Style / Sound / Editorial）的输入提示。
5. 写入 `<project>/CREATIVE_DIRECTION.md`，在 `DECISIONS.md` 落一条长期决策（D-xxx，记录推荐结论与理由摘要）。
6. 更新 `PROJECT_STATE.md`（Current Stage: CREATIVE_REVIEW, Pending Decisions），推进到 `CREATIVE_REVIEW`（waiting_user）。

## 示例扩展（§27：模糊需求 → 3 路发散）
需求示例："做一个 2 分钟介绍 AI 记忆产品的视频"。常见 3 路概念：
- **Option A — Memory Palace（记忆宫殿）**：把产品能力具象为一座可走入的空间，记忆是其中的房间与陈列。Best for：强调 AI 组织能力、视觉辨识度。Risk：抽象隐喻对非目标用户有理解门槛。
- **Option B — Fragments to Understanding（碎片到理解）**：用"信息碎片逐渐拼合成完整图景"的过程讲产品价值。Best for：逻辑型受众、强调"整理"功能。Risk：过程感强但记忆点偏弱。
- **Option C — Invisible Companion（隐形伙伴）**：产品是画外的隐形助手，故事围绕主角与它的互动展开。Best for：情感化叙事、强调陪伴与安全感。Risk：产品露出不足。

每个 Option 照此补齐 Strength / Weakness / Best for / Risk 后再进入推荐环节。

## 阶段状态变更
`CREATIVE_DIRECTION` → `CREATIVE_REVIEW` →（approve 后）`STYLE_DIRECTION`

## Approval Gate（CREATIVE_REVIEW, waiting_user）
向用户呈现（必须包含，缺一不可）：
1. **Core Idea**（一句话核心主张 + 依据）
2. **Hook**（前 3-5 秒的具体设计）
3. **推荐 Option + Why**（引用 Brief 与 Reference 的可复核理由；并列其它 Options 的取舍）

用户选择：
- approved → 进入 style-direction
- revision_requested → 回到 `CREATIVE_DIRECTION`，新 Decision Supersedes 旧决定，本文件追加修订说明（append-only）
- rejected → 停止并记录原因

## 引用
- 模板：`templates/creative-direction.md`
- 宪法 #1（Director Before Engineer）、#7（Effects Serve Narrative）
- 设计 v0.2 §7（Creative Director）、§60（Workflow 顺序）
