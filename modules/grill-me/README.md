# Grill Me 模块

> Phase 2 Director Pipeline 的需求采集模块（v0.2 §4「Project Intake / Grill Me」）。
> 上游工作流：`workflows/project-intake.md`；数据契约：`schemas/project.schema.json`、`schemas/state-machine.json`。

## 模块目的

把用户的模糊想法（一句话 / 一段文字 / 一个链接）通过**有节奏的提问**补足为结构化 Project Brief。
核心约束（v0.2 §4）：**不能无限提问，达到可以进行创意设计的程度就停止**（Stop Asking Rule）。

问题按对导演决策的影响程度分三层（Taxonomy：`questions.json`，共 19 条）：

| Tier | 含义 | 数量 | 问题 |
|---|---|---|---|
| 1 | 必须知道 | 7 | `video_about` / `primary_goal` / `audience` / `target_duration` / `platform` / `voiceover` / `available_assets` |
| 2 | 强烈影响决策 | 8 | `reference_videos` / `emotional_impression` / `editable_jianying_required` / `ai_video_allowed` / `3d_allowed` / `real_footage_allowed` / `brand_restrictions` / `language` |
| 3 | 导演推断（默认 assumed，不询问） | 4 | `exact_motion_style` / `exact_transition_type` / `exact_bpm` / `exact_shot_count` |

## 输入（intake_state）

`select_next_question(intake_state)` 的入参，表示当前采集进度。持久化于项目文件（`PROJECT_STATE.md` 等），**禁止依赖聊天记忆**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_already_has_brief` | bool | 用户已提供完整 Brief → 立即 stop |
| `user_has_script` | bool | 用户已有脚本 → 立即 stop（转入脚本提取分支） |
| `user_has_storyboard` | bool | 用户已有 Storyboard → 立即 stop |
| `answers` | dict | 已答字段：key = question `id`（或 `field_target` 末段，如 `project.primary_goal` → `primary_goal`） |

答案 key 同时兼容 `answers` 嵌套与顶层平铺两种形式。布尔 `false` 与数值 `0` 均视为有效回答。

## 输出

`{"action": "ask" | "stop", "next": question_dict | None, "reason": str}`

- `action: "ask"` → 向用户提问 `next.question`（`next.id` 即 next_question_id），拿到答案后写回 `intake_state.answers[next.id]`，再调用一次选择器。
- `action: "stop"` → 采集完成（`next: null`），进入 Project Brief 生成。

## 停止条件（Stop Asking Rule）

1. Tier 1 全部回答 + Tier 2 已答 ≥ 5 + Tier 3 全部 assumed；或
2. `intake_state` 命中 `user_already_has_brief` / `user_has_script` / `user_has_storyboard` = true。

Tier 3 永不提问：`blocking: false` + `assumable: true`，由导演推断；其默认值（如 `micro_motion` / `crossfade`）记入 Project Brief 的 Assumptions，不作为用户回答。

## 集成方式

```text
workflows/project-intake.md（PROJECT_INTAKE 阶段）
  ├─ 从项目文件恢复 intake_state
  ├─ 循环：
  │    result = select_next_question(intake_state)
  │    if result["action"] == "stop": break
  │    提问 result["next"]["question"] → 答案写回 intake_state.answers
  ├─ 生成 PROJECT_BRIEF.md（模板 templates/project-brief.md）
  └─ 推进到 PROJECT_BRIEF_REVIEW（waiting_user），提交 Approval Gate
```

每步一问，选择器只负责「问哪个」，不负责提问话术与答案校验（后者由 workflow 执行）。

## 与 schema / state-machine 的关系

- 每个问题的 `field_target` 映射 `schemas/project.schema.json` 的字段（如 `project.primary_goal`）；`derived.*`（`derived.motion_style` / `derived.transition_type` / `derived.bpm` / `derived.shot_count`）为导演推断字段，记入 Brief 的 Assumptions，不落入 schema 必填项。
- 模块运行于 `PROJECT_INTAKE` 阶段（`requires_approval: false`）；达到停止条件后工作流推进到 `PROJECT_BRIEF_REVIEW`（`requires_approval: true`）。二者为合法迁移（`schemas/state-machine.json` `normal_next_per_stage`），权威说明见 `docs/state-machine.md`。
- 用户打回（`revision_requested` / `rejected`）时按 `review_revision` 回到 `PROJECT_INTAKE` 重新采集 / 修订，决策记入 `DECISIONS.md`（`D-###`，Supersedes 规则），审批态记入 `approvals.yaml`（见 `docs/approval-system.md` / `docs/memory-system.md`）。

## 文件清单

- `questions.json` — 问题 Taxonomy（19 条：Tier 1×7 / Tier 2×8 / Tier 3×4）
- `selector.py` — 选择器（Python 3 stdlib only，含 `self_test()`，覆盖 ≥ 6 个场景）
- `README.md` — 本说明

## 自检

```bash
python3 modules/grill-me/selector.py
```
