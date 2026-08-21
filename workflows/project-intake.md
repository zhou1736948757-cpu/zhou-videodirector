---
workflow_id: WF-001
name: 项目接入与需求确认
stage_ids: [PROJECT_INTAKE, PROJECT_BRIEF_REVIEW]
requires_approval: [PROJECT_BRIEF_REVIEW]
phase1_status: skeleton
phase2_status: implemented
---

# 项目接入与需求确认（Project Intake）

## 目标
把用户的一个模糊想法（一句话 / 一段文字 / 一个链接）通过 Grill Me 补足为结构化 Project Brief，确定 Production Mode 与 Delivery Mode，形成 `PROJECT_STATE.md` 的初始段，并在用户确认前不进入任何后续阶段。

## 触发时机
当前 stage 为 `INIT` 或 `PROJECT_INTAKE`，用户提出新视频项目需求时触发。

## 输入
- 用户初始想法（任意形式）
- 项目目录（由 `templates/project-state.md` 拷贝初始化，位于 `<project>/PROJECT_STATE.md`）
- 必填字段：见 `schemas/project.schema.json`（title / production_mode / delivery_mode / platform / aspect_ratio / fps / target_duration / audience / ai_video_allowed / 3d_allowed / real_footage_allowed / editable_timeline_required 等）
- Grill Me 问题 Taxonomy：`modules/grill-me/questions.json`
- Grill Me 选择器：`modules/grill-me/selector.py`

## 输出（项目文件）
- `<project>/PROJECT_STATE.md` — 填充 init 段：Production Mode、Delivery Mode、Current Stage、Next Action、Last Updated 等关键字段
- `<project>/DECISIONS.md` — 初始为空表
- `<project>/approvals.yaml` — `project.project_brief.status: pending`
- `<project>/PROJECT_BRIEF.md` — 结构化需求文档（模板 `templates/project-brief.md`）
- `<project>/source/` — 用户已有脚本 / Storyboard 落盘（如走快捷分支）

## 执行步骤
1. 读取 `<project>/PROJECT_STATE.md` 与 `<project>/approvals.yaml`（遵守 Persist Decisions，禁止依赖聊天记忆）。
2. 触发 Grill Me（v0.2 §4，`modules/grill-me/`）：按 schema 字段逐项收敛；达到可进行创意设计的程度即停止，禁止无限提问。
3. 确定 `production_mode`：`PRODUCT_TECH_SHORT` / `EDITORIAL_EXPLAINER` / `CUSTOM`（v0.2 §58-59）。
4. 确定 `delivery_mode`：`FINAL_VIDEO_ONLY` / `EDITABLE_PROJECT` / `BOTH`；多数项目推荐 `BOTH`。
5. 生成 `PROJECT_BRIEF.md`，写入 `<project>/PROJECT_STATE.md` init 段，approvals.yaml 置 pending。
6. 推进到 `PROJECT_BRIEF_REVIEW`（waiting_user），提交 Approval Gate。

## Phase 2：Adaptive Grill Me（模块化需求采集）

> 实现：`modules/grill-me/questions.json`（19 问：Tier 1×7 / Tier 2×8 / Tier 3×4）+ `modules/grill-me/selector.py`。

### 2.1 每步调用选择器（Adaptive Grill Me）
每一步只问一个问题，下一步由 `select_next_question(intake_state)` 决定：

```text
intake_state（已答字段，从项目文件恢复）
  → select_next_question(intake_state)
  → {"action": "ask", "next": {question}, "reason": "..."}
    或 {"action": "stop", "next": null, "reason": "..."}
```

- 优先级：Tier 1（必须知道）→ Tier 2（强烈影响决策）→ Tier 3（导演推断，不询问）。
- 跳过已回答的问题与 `blocking: false` 的问题；每答一题即重新调用选择器。
- **Stop Asking Rule（v0.2 §4）**：达到可以进行创意设计的程度就停止，禁止无限提问。停止条件：
  1. Tier 1 全部回答 + Tier 2 已答 ≥ 5 + Tier 3 全部 assumed；或
  2. `intake_state.user_already_has_brief == true`。

### 2.2 intake_state 契约
```json
{
  "user_already_has_brief": false,
  "answers": {
    "video_about": "产品 90s 介绍",
    "primary_goal": "新品发布预热",
    "target_duration": 90
  }
}
```
- 答案 key = question `id`（或 `field_target` 末段，如 `project.primary_goal` → `primary_goal`）。
- `intake_state` 随会话同步写入项目文件（`PROJECT_STATE.md` / 决策记录），禁止仅存于聊天上下文。

### 2.3 用户已有脚本 / Storyboard 分支
- `intake_state.user_has_script == true`：用户已写好脚本 → 选择器立即停止提问，从脚本提取需求字段；脚本入档 `<project>/source/script.md`。
- `intake_state.user_has_storyboard == true`：用户已有 Storyboard → 立即停止提问，从 Storyboard 提取字段；入档 `<project>/source/storyboard/`。
- 两分支视同 `user_already_has_brief`，直接进入 Project Brief 生成；在 `DECISIONS.md` 记录 D-NNN（Scope: intake_shortcut），禁止丢失用户提供的材料。

## Project Brief 生成
1. 按 `templates/project-brief.md` 填充字段（与 `schemas/project.schema.json` 对齐）。
2. 确定 `production_mode`：`PRODUCT_TECH_SHORT` / `EDITORIAL_EXPLAINER` / `CUSTOM`（v0.2 §58-59）。
3. 确定 `delivery_mode`：`FINAL_VIDEO_ONLY` / `EDITABLE_PROJECT` / `BOTH`；多数项目推荐 `BOTH`。
4. Tier 3 assumed 值（motion_style / transition_type / bpm / shot_count）写入 Brief 的 Assumptions，不作为用户回答。
5. 写入 `<project>/PROJECT_BRIEF.md`；`PROJECT_STATE.md` 更新 init 段；`approvals.yaml` 置 pending。

## 用户修改 → 更新 Brief + 决策
1. `PROJECT_BRIEF_REVIEW` 打回（`revision_requested` / `rejected`）→ 回到 `PROJECT_INTAKE`。
2. 修改 `PROJECT_BRIEF.md` 对应字段；决策变更时在 `DECISIONS.md` 追加 D-NNN（Supersedes 旧决定，旧决定保留）。
3. 同步更新 `PROJECT_STATE.md` 与 `approvals.yaml`（status: pending）。
4. 重新提交 Approval Gate。

## 阶段状态变更
`INIT` → `PROJECT_INTAKE` → `PROJECT_BRIEF_REVIEW` →（approve 后）`REFERENCE_ANALYSIS`

无参考素材时，后续 `REFERENCE_ANALYSIS` 允许 skipped，但必须结构化记录 skip_reason。

## Approval Gate
进入 `PROJECT_BRIEF_REVIEW` 后必须等待用户确认（stage status: waiting_user）：
- 向用户呈现 Project Brief（含 production_mode / delivery_mode / 约束 / Assumptions / Open Questions）。
- approved → 进入 reference-analysis
- revision_requested → 回到 `PROJECT_INTAKE` 修改 Brief，创建新 Decision（Supersedes 旧决定）
- rejected → 停止，记录原因

## Phase 1 现状
> Phase 1：skeleton → Phase 2：implemented（Grill Me 模块化就绪，Director Pipeline 接入）。
> 模块：`modules/grill-me/questions.json`、`modules/grill-me/selector.py`；模板：`templates/project-brief.md`。
> 数据契约：`schemas/project.schema.json`；状态机：`schemas/state-machine.json`；记忆：`docs/memory-system.md`；审批：`docs/approval-system.md`。
> 禁止：跳过 Approval 自动推进、确认前进入制作、无限提问、依赖聊天记忆。
