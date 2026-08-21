# ZHOU_Videodirector — 审批系统（Approval System）

> 对应总设计 v0.2 §48-50、Phase-1 Prompt §10-13。
> Stage 状态机见 `docs/state-machine.md`；机器可读真源见 `schemas/state-machine.json`。

## A. 核心流程

整个 Skill 不是 Autonomous Black Box。所有关键动作走五步门控：

```text
PLAN
  ↓
EXPLAIN
  ↓
USER APPROVAL
  ↓
EXECUTE
  ↓
REPORT
```

- **PLAN**：先说明「我要做什么」，给出计划与预期结果。
- **EXPLAIN**：说清楚「为什么这么做、效果大概怎样、成本与取舍」。
- **USER APPROVAL**：等用户明确确认。未确认不得 EXECUTE。
- **EXECUTE**：执行。
- **REPORT**：汇报结果与产出。

审批分两级：**Stage Approval**（阶段级，11 个 `requires_approval: true` 的门）与 **Execution Approval**（动作级，11 种高影响操作）。

## B. Stage Approval（11 个 `requires_approval: true` 的阶段）

Stage Approval 决定「这个阶段的设计产物是否被用户接受」。对应 stage 的 `approval_status`，通过后 stage 才能推进。

| Stage | 审批什么 |
|---|---|
| `PROJECT_BRIEF_REVIEW` | 审批 Project Brief 内容（项目目标、内容主题、平台、长宽比、时长、制作/交付模式、优先级、约束）。 |
| `REFERENCE_REVIEW` | 审批 `REFERENCE_ANALYSIS.md` 参考分析报告与提取的规律（学习规律，不逐镜复制）。 |
| `CREATIVE_REVIEW` | 审批 `CREATIVE_DIRECTION.md` 创意方向（Hook / Core Idea / Viewer Tension / 情绪方向）。 |
| `VISUAL_BIBLE_REVIEW` | 审批 `VISUAL_BIBLE.md`（色彩/字体/构图/留白/运镜/Motion Character/光照/材质/避免清单等视觉最高约束）。 |
| `AUDIO_DIRECTION_REVIEW` | 审批 `AUDIO_DIRECTION.md` 声音方向（音乐方向、SFX 语言、环境音、Hero Sound 策略等）。 |
| `STORY_REVIEW` | 审批 STORY / BEAT MAP 故事结构与节奏（叙事弧线、章节、Pacing、Payoff）。 |
| `STORYBOARD_REVIEW` | 审批 Storyboard（Scene / Shot / Layer 划分与设计、时长、路由建议）。 |
| `ROUTING_REVIEW` | 审批 Routing Plan（Shot/Layer 路由、Bake 与 Editability 策略、Prototype 需求），通过后进入资源规划。 |
| `PRODUCTION_PLAN_REVIEW` | 审批 PRODUCTION_PLAN（Asset 计划 / Sound 计划 / 时间与成本 / 技术路线）。 |
| `TIMELINE_REVIEW` | 审批时间线计划 / 草稿结构（轨道、剪辑顺序、可编辑边界、替换资产）。 |
| `QA` | 审批四层 QA 报告（Technical / Visual / Editorial / Sound），通过后进入 `CHANGE_REVIEW`。 |

## C. Execution Approval（11 种类型）

Execution Approval 针对「高影响、高成本、难回退」的具体动作。执行前必须 EXPLAIN：**要做什么、为什么、效果大概怎样**，用户确认后再执行。

| 类型 | 说明 | 触发条件 | 执行前确认什么 |
|---|---|---|---|
| `SUBAGENT_ACTIVATION` | 启用 Subagent 并行工作 | 需要大量搜索 / 多方案设计 / 并行制作 Scene | 数量、模型、职责、并发度；主模型保留最终导演权 |
| `LARGE_FILE_DOWNLOAD` | 下载大文件 | 模型 / 素材 / 数据文件体积超过阈值 | 文件大小、来源、License、用途、目标路径 |
| `MODEL_3D_SELECTION` | 选择 3D 模型 | 从 3D Registry 挑选模型用于镜头 | 模型、精度、License、是否可替换、体积 |
| `TEXTURE_2K_4K_8K` | 选择贴图分辨率 | 需要在 2K / 4K / 8K 贴图间选择 | 分辨率、体积、渲染成本、视觉收益是否匹配 |
| `LARGE_AUDIO_LIBRARY_DOWNLOAD` | 下载大型音频库 | 音乐 / SFX 库体积超过阈值 | 库体积、License、实际需要哪些条目 |
| `COMPLEX_REMOTION_ANIMATION` | 复杂 Remotion 动画 | 高复杂度 Motion / 长连续渲染 | 动画范围、预计耗时、可编辑性取舍 |
| `COMPLEX_3D_BUILD` | 复杂 3D 构建 | 复杂建模 / 场景 / 渲染 | 构建内容、预计时长、成本 |
| `AI_VIDEO_PACKET` | AI 视频生成包 | 生成 AI Video 镜头 | 完整 Production Packet（Prompt / 时长 / 分辨率 / 连续性 / 负面 Prompt） |
| `MAJOR_TIMELINE_RESTRUCTURE` | 大规模时间线重构 | 重组轨道 / 顺序 / 删除大段内容 | 重构范围、影响面、是否保留备份 |
| `LARGE_RERENDER` | 大规模重新渲染 | 大范围 / 长时长重新 Render | 渲染范围、预估时间、成本 |
| `DESTRUCTIVE_OPERATION` | 破坏性操作 | 删除 / 覆盖 / 清空文件或数据 | 操作对象、不可恢复点、是否已备份 |

## D. Approval 数据结构（§13）

每一条审批记录使用统一结构：

```yaml
approval_id: AP-001
scope: visual_bible
target: project
status: approved
decision:
  summary: Use current visual direction.
user_feedback:
  - avoid strong glitch
  - preserve subtle motion
created_at: 2026-08-13T10:00:00+08:00
supersedes: null
```

字段含义：

- `approval_id`：审批记录唯一 ID（`AP-###`）。
- `scope`：审批范围。可取值包括 `project_brief` / `reference_report` / `creative_direction` / `visual_bible` / `audio_direction` / `story_structure` / `storyboard` / `production_plan` / `timeline_plan` / `final_qa`，以及 scene / shot / asset 级范围（如 `shot:S018`）。
- `target`：审批目标对象（`project`，或 scene / shot / asset ID）。
- `status`：`approval_status` 枚举之一（见 E 节）。
- `decision.summary`：决定摘要（用户批准或否决了什么）。
- `user_feedback`：用户反馈条目列表，逐条保留。
- `created_at`：创建时间（ISO 8601）。
- `supersedes`：被本记录覆盖的旧 Approval ID；没有则为 `null`。

## E. 审批规则硬约束

1. **禁止删除历史 Approval 来伪装「当前只有一个决定」**。所有审批记录永久保留，即使后续被推翻。
2. **Supersedes 关系必须显式**。新决定覆盖旧决定时，必须在新记录上写 `supersedes: AP-0XX`，并将旧记录 `status` 标记为 `superseded`。不能「覆盖内容就当删除」。
3. **5 个 Approval Status 完整含义**：

| Status | 含义 |
|---|---|
| `pending` | 等待用户决定，阶段不得推进 |
| `approved` | 用户批准，可以继续下一步 |
| `rejected` | 用户否决，不得推进；按打回规则退回对应阶段 |
| `revision_requested` | 用户要求修改，按打回规则退回对应非 review 阶段重新产出 |
| `superseded` | 被新 Approval 覆盖；历史保留，不再作为当前决定 |

4. Approval 记录是机器可读审批态（`approvals.yaml`）与 `PROJECT_STATE.md`（`Approved Stages` / `Pending Decisions`）一致性的唯一事实来源。两处矛盾即为非法状态（Validator 必须发现，Phase-1 Test 11）。

## F. approvals.yaml 当前态结构（§20）

`approvals.yaml` 是机器可读 Approval Current State，保存在项目目录根。

示例（§20 原文结构；`approvals:` 为审批历史列表，新项目初始化时置空 `[]`，
`gates.py append_approval` 只向此列表追加，不覆盖既有记录）：

```yaml
project:
  project_brief:
    status: pending

  creative_direction:
    status: not_started

  visual_bible:
    status: not_started

  audio_direction:
    status: not_started

  storyboard:
    status: not_started

scenes: {}

shots: {}

assets: {}

approvals: []
```

完整注释版（含 Stage 对应关系与历史记录区）：

```yaml
# approvals.yaml — 机器可读审批当前态
# 结构分两区：
#   1) project / scenes / shots / assets：当前态索引（key → 当前 status + 生效 approval_id）
#   2) approvals：全部审批历史记录（AP-### 明细，永久保留，不可删除）

project:
  project_brief:            # key = 审批范围，对应 Stage: PROJECT_BRIEF_REVIEW
    status: pending         # 当前 Approval Status（未进入阶段时可为 not_started）
    approval_id: null       # 当前生效的 AP-### 记录 ID

  reference_report:         # 对应 Stage: REFERENCE_REVIEW
    status: not_started
    approval_id: null

  creative_direction:       # 对应 Stage: CREATIVE_REVIEW
    status: not_started
    approval_id: null

  visual_bible:             # 对应 Stage: VISUAL_BIBLE_REVIEW
    status: not_started
    approval_id: null

  audio_direction:          # 对应 Stage: AUDIO_DIRECTION_REVIEW
    status: not_started
    approval_id: null

  story_structure:          # 对应 Stage: STORY_REVIEW
    status: not_started
    approval_id: null

  storyboard:               # 对应 Stage: STORYBOARD_REVIEW
    status: not_started
    approval_id: null

  production_plan:          # 对应 Stage: PRODUCTION_PLAN_REVIEW
    status: not_started
    approval_id: null

  timeline_plan:            # 对应 Stage: TIMELINE_REVIEW
    status: not_started
    approval_id: null

  final_qa:                 # 对应 Stage: QA
    status: not_started
    approval_id: null

approvals:                  # 审批历史（含全部 AP-### 记录，永不删除）
  - approval_id: AP-001
    scope: project_brief
    target: project
    status: approved
    decision:
      summary: Project brief approved as drafted.
    user_feedback: []
    created_at: 2026-08-13T10:00:00+08:00
    supersedes: null

scenes: {}                  # scene 级审批：key = scene ID（如 SC001）
shots: {}                   # shot 级审批：key = shot ID（如 S018）
assets: {}                  # asset 级审批：key = asset ID（如 A018）
```

字段含义注记：

- `status` 取值：未进入的阶段可为 `not_started`；进入后的阶段必须使用 Approval Status 枚举（`pending` / `approved` / `rejected` / `revision_requested` / `superseded`）。
- `project.*` 的每个 key 对应一个 Stage Approval 门（与 `requires_approval_stages` 一一对应）。
- `approvals:` 列表保存全部历史记录，禁止删除；`supersedes` 与 `superseded` 显式表达覆盖关系。
- `approvals.yaml` 的当前态必须与 `PROJECT_STATE.md` 的 `Approved Stages` / `Pending Decisions` 一致。
