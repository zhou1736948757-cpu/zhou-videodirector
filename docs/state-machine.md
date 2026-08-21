# ZHOU_Videodirector — 状态机（State Machine）

> 机器可读真源：`schemas/state-machine.json`
> 本文档为人类可读说明，与机器数据必须保持一致。

## A. 概览

Phase 1 不做视频，但必须建立**机器可判断的状态机骨架**。

目的：

- 任何时刻都能回答「当前视频项目进行到了哪一步」。
- 任何时刻都能回答「下一步是什么」。
- 禁止跨阶段擅自执行：未通过审批的 Review 阶段不得推进。
- 每个 Stage 的状态用结构化枚举表达，禁止用自由文本作为唯一状态来源。

`schemas/state-machine.json` 是机器可读真源（machine-readable source of truth），所有 stage 迁移、审批门、打回关系的判定都以该文件为准；本文档只做解释与补充约定。

## B. 阶段总表

下表列出全部 Stage（按共享契约枚举清单顺序，共 31 个）。

| Stage ID | 目的（一句话） | requires_approval | typical_next |
|---|---|---|---|
| `INIT` | 项目初始化，建立项目目录结构与初始记忆文件；状态机入口 | false | `PROJECT_INTAKE` |
| `PROJECT_INTAKE` | Grill Me 需求采集，产出 Project Brief（目标、平台、时长、制作/交付模式、优先级） | false | `PROJECT_BRIEF_REVIEW` |
| `PROJECT_BRIEF_REVIEW` | 审批 Project Brief 内容，用户确认后进入导演流程 | true | `REFERENCE_ANALYSIS` |
| `REFERENCE_ANALYSIS` | 分析参考视频/素材，产出 `REFERENCE_ANALYSIS.md`（无参考时可跳过） | false | `REFERENCE_REVIEW` |
| `REFERENCE_REVIEW` | 审批参考分析报告，确认提取的规律（学习规律，不逐镜复制） | true | `CREATIVE_DIRECTION` |
| `CREATIVE_DIRECTION` | 创意导演产出 `CREATIVE_DIRECTION.md`（Hook / Core Idea / 情绪方向） | false | `CREATIVE_REVIEW` |
| `CREATIVE_REVIEW` | 审批创意方向 | true | `STYLE_DIRECTION` |
| `STYLE_DIRECTION` | 风格导演推荐 Style，产出 `VISUAL_BIBLE.md` | false | `VISUAL_BIBLE_REVIEW` |
| `VISUAL_BIBLE_REVIEW` | 审批 Visual Bible（色彩/字体/构图/运镜/动效等视觉最高约束） | true | `SOUND_DIRECTION` |
| `SOUND_DIRECTION` | 声音导演产出 `AUDIO_DIRECTION.md`（音乐方向 / SFX 语言 / 环境音） | false | `AUDIO_DIRECTION_REVIEW` |
| `AUDIO_DIRECTION_REVIEW` | 审批 Audio Direction | true | `EDITORIAL_DIRECTION` |
| `EDITORIAL_DIRECTION` | 编辑导演产出 STORY / BEAT MAP（叙事结构、章节、节奏） | false | `STORY_REVIEW` |
| `STORY_REVIEW` | 审批故事结构与 Beat Map | true | `STORYBOARD` |
| `STORYBOARD` | 分镜引擎产出 Scene / Shot / Layer 层级故事板 | false | `STORYBOARD_REVIEW` |
| `STORYBOARD_REVIEW` | 审批故事板（Scene / Shot / Layer 划分与设计） | true | `SUBAGENT_CONFIGURATION` |
| `SUBAGENT_CONFIGURATION` | 配置 Subagent 数量/模型/职责/并发（无需 Subagent 时可跳过） | false | `SHOT_ROUTING` |
| `SHOT_ROUTING` | Shot 级技术路由（REMOTION / THREE_D / REAL_FOOTAGE / GENERATIVE_VIDEO / JY_NATIVE / HYBRID） | false | `LAYER_ROUTING` |
| `LAYER_ROUTING` | 必要时 Layer 级技术路由与 z 序分解 | false | `ROUTING_REVIEW` |
| `ROUTING_REVIEW` | 审批 Routing Plan（Shot/Layer 路由、Bake 与 Editability 策略、Prototype 需求） | true | `RESOURCE_PLANNING` |
| `RESOURCE_PLANNING` | 资源规划（Registry 搜索 + Asset Plan + Sound Plan），产出 PRODUCTION_PLAN | false | `PRODUCTION_PLAN_REVIEW` |
| `PRODUCTION_PLAN_REVIEW` | 审批 Production Plan（Asset 计划 / Sound 计划 / 时间与成本） | true | `ASSET_ACQUISITION` |
| `ASSET_ACQUISITION` | 获取素材（Registry / Provider 下载），受 Execution Approval 约束 | false | `ASSET_PRODUCTION` |
| `ASSET_PRODUCTION` | 生产资产（Remotion / Three.js / AI Video / Footage / Music / SFX），产出 Asset Package | false | `TIMELINE_BUILD` |
| `TIMELINE_BUILD` | 用 pyJianYingDraft 等后端构建可编辑时间线草稿 | false | `TIMELINE_REVIEW` |
| `TIMELINE_REVIEW` | 审批时间线计划/草稿结构（轨道、剪辑、可编辑边界） | true | `PREVIEW` |
| `PREVIEW` | 预览成片，供 QA 与用户查看 | false | `QA` |
| `QA` | 四层 QA（Technical / Visual / Editorial / Sound）并审批 QA 结果 | true | `CHANGE_REVIEW` |
| `CHANGE_REVIEW` | 审批 CHANGE PROPOSAL；通过后可迁至任意非 COMPLETE 阶段返工（见 C 节例外） | false | `FINAL_EDIT` |
| `FINAL_EDIT` | 最终人工 + AI 联合编辑 | false | `FINAL_RENDER` |
| `FINAL_RENDER` | 最终渲染输出 final.mp4 等交付物 | false | `COMPLETE` |
| `COMPLETE` | 项目完成，收尾归档（终态） | false | — |

> 注：`requires_approval: true` 共 11 个阶段，即 Stage Approval 门（见 `docs/approval-system.md` B 节）。该清单与 `schemas/state-machine.json` 的 `requires_approval_stages` 必须一致。

## C. 合法迁移

### C.1 主流程（§60 一段连续迁移）

按总设计 v0.2 §60 Workflow，主流程是一段连续迁移：

```
INIT
 → PROJECT_INTAKE
 → PROJECT_BRIEF_REVIEW
 → REFERENCE_ANALYSIS
 → REFERENCE_REVIEW
 → CREATIVE_DIRECTION
 → CREATIVE_REVIEW
 → STYLE_DIRECTION
 → VISUAL_BIBLE_REVIEW
 → SOUND_DIRECTION
 → AUDIO_DIRECTION_REVIEW
 → EDITORIAL_DIRECTION
 → STORY_REVIEW
 → STORYBOARD
 → STORYBOARD_REVIEW
 → SUBAGENT_CONFIGURATION
 → SHOT_ROUTING
 → LAYER_ROUTING
 → ROUTING_REVIEW
 → RESOURCE_PLANNING
 → PRODUCTION_PLAN_REVIEW
 → ASSET_ACQUISITION
 → ASSET_PRODUCTION
 → TIMELINE_BUILD
 → TIMELINE_REVIEW
 → PREVIEW
 → QA
 → CHANGE_REVIEW
 → FINAL_EDIT
 → FINAL_RENDER
 → COMPLETE
```

该链在机器可读文件中对应 `transition_rules.normal_next_per_stage`。

### C.2 REVIEW 阶段的打回

每个 `*_REVIEW`（及 `QA`）阶段被 `revision_requested` / `rejected` 时，合法打回目标就是它审批的那个非 review 阶段：

| 审批阶段 | 打回目标 |
|---|---|
| `PROJECT_BRIEF_REVIEW` | `PROJECT_INTAKE` |
| `REFERENCE_REVIEW` | `REFERENCE_ANALYSIS` |
| `CREATIVE_REVIEW` | `CREATIVE_DIRECTION` |
| `VISUAL_BIBLE_REVIEW` | `STYLE_DIRECTION` |
| `AUDIO_DIRECTION_REVIEW` | `SOUND_DIRECTION` |
| `STORY_REVIEW` | `EDITORIAL_DIRECTION` |
| `STORYBOARD_REVIEW` | `STORYBOARD` |
| `ROUTING_REVIEW` | `SHOT_ROUTING` |
| `PRODUCTION_PLAN_REVIEW` | `RESOURCE_PLANNING` |
| `TIMELINE_REVIEW` | `TIMELINE_BUILD` |
| `QA` | `PREVIEW` |

该表在机器可读文件中对应 `transition_rules.review_revision`（11 条）。

### C.3 CHANGE_REVIEW 例外（机器可读文件显式记录）

`CHANGE_REVIEW` 通过后，**可迁至任意非 `COMPLETE` 阶段**（返工到任何导演/制作/编辑阶段），且该返工**必须触发新的 Approval**。

这条例外显式写在机器可读文件：

```json
"change_review_post_qa": {
  "after": "QA",
  "allowed_target": "any_stage_except_COMPLETE",
  "requires_new_approval": true
}
```

对应地，`CHANGE_REVIEW.allowed_next` 在 `schemas/state-machine.json` 中列了除 `COMPLETE` 外的全部 stage。

## D. Stage 数据结构

每个 Stage 实例（一个 `project.STAGES[]` 条目）至少包含以下字段：

```yaml
id: PROJECT_BRIEF_REVIEW   # 必须来自 31 个 Stage ID 枚举
status: waiting_user       # 必须来自 stage_status_enum（9 个）
entered_at: 2026-08-13T10:00:00+08:00   # ISO 8601
completed_at: null         # ISO 8601，未完成时为 null
requires_approval: true    # 是否 Stage Approval 门
approval_status: pending   # 必须来自 approval_status_enum（5 个），非审批阶段可省略
outputs: []                # 本阶段产出的文件路径列表
next_stage: REFERENCE_ANALYSIS   # 计划下一步（合法迁移集内）
skip_reason: null          # status=skipped 时必填
notes: ""                  # 自由文本备注，禁止作为状态唯一来源
```

字段语义：

- `status`：该阶段的机器可判定状态。9 个合法取值：
  `not_started`（未进入）、`in_progress`（进行中）、`waiting_user`（等待用户审批或补充信息）、`approved`（审批门已获批准）、`completed`（已完成）、`skipped`（已跳过，必须附 `skip_reason`）、`blocked`（被阻塞，等待外部条件，区别于审批等待）、`failed`（失败，需在 `notes` 记录原因）、`superseded`（被后续返工覆盖，历史保留）。
- `approval_status`：审批门的机器可判定状态。5 个合法取值：
  `pending`（等待用户决定）、`approved`（批准）、`rejected`（否决）、`revision_requested`（要求修改）、`superseded`（被新 Approval 覆盖，历史保留）。

硬规则：

- **禁止自由文本作为唯一状态来源**。状态判定只看 `status` / `approval_status` 的结构化枚举值；自由文本只能放在 `notes` 里作为补充信息。
- `requires_approval: true` 的 stage，其 `approval_status` 未达到 `approved` 前，不得推进到下一正式阶段（Test 2 约束）。

## E. 跳过与失败规则

- **跳过必须结构化记录**：被跳过的 stage 实例 `status: skipped` 且 `skip_reason` 必须非空。`skip_reason` 建议使用受控短语（如 `no_reference_provided`、`no_subagent_needed`），可附加简短补充文本。跳过后按 `next_stage` / `normal_next_per_stage` 继续。
- 例如无参考项目：`REFERENCE_ANALYSIS → skipped`，随后进入 `REFERENCE_REVIEW → skipped`（或直接按 `next_stage` 前进），`skip_reason: no_reference_provided`。
- **持久化**：所有 stage 实例数据写入 `project.STAGES[]`（数组），随项目目录持久化；`project.STAGES[]` 位于项目根目录下的 `PROJECT_STATE.md` 对应项目（详见 `docs/memory-system.md` A 节的四层记忆结构）。每次状态变化都必须同步写入，不能只存在聊天上下文里。
- **失败规则**：stage `status: failed` 时必须在 `notes` 记录失败原因，由主 Agent 决定返回哪个合法阶段（只允许迁移到 `allowed_next` 合法集内）；不允许跨阶段跳跃推进。
- **阻塞 vs 等待**：`blocked` 表示等待外部条件（资源、外部服务、用户提供文件等）；`waiting_user` 表示等待用户审批决定。两者不可混用。

## F. 引用

本状态机机器可读源在 `schemas/state-machine.json`。
