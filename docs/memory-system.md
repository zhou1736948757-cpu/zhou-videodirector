# ZHOU_Videodirector — 项目记忆系统（Memory System）

> 对应总设计 v0.2 §51-56、Phase-1 Prompt §14-20。
> 核心原则：**整个项目禁止依赖聊天窗口「记忆」**，所有重要状态与决定写入项目目录。

## A. 四层记忆总览

| 层 | 文件 | 角色 | 说明 |
|---|---|---|---|
| 1 | `PROJECT_STATE.md` | Current Truth | 当前项目总态快照，约 30-100 行；进入项目先读它 |
| 2 | `DECISIONS.md` | 长期决策 | `D-###` 决策记录，只追加不覆盖，Supersedes 关系保留 |
| 3 | Scene / Shot / Asset Memory | 对象记忆 | `scenes/SC###.md`、`shots/S###.md`、`assets/A###.md`，每对象独立文件 |
| 4 | `approvals.yaml` | 机器可读审批当前态 | 结构化审批状态，历史不删除（见 `docs/approval-system.md` F 节） |

所有文件都位于项目目录下：

```text
<project_dir>/
├── PROJECT_STATE.md
├── DECISIONS.md
├── approvals.yaml
├── scenes/SC###.md
├── shots/S###.md
├── assets/A###.md
└── ...（references/ source/ audio/ remotion/ timeline/ previews/ renders/）
```

## B. 读取顺序（重要）

进项目时按以下顺序恢复上下文：

1. **先读 `PROJECT_STATE.md`** 知当前总态（Current Stage / Current Shot / 阻塞项 / 下一步）。
2. **按需打开细节**：根据 `Current Shot` 打开 `shots/S###.md`，根据 `Pending Decisions` / `Approved Stages` 打开 `DECISIONS.md`、`approvals.yaml`，根据 `Current Scene` 打开 `scenes/SC###.md`。
3. **不要扫描整个聊天记录**。聊天记录不是记忆来源；所有状态以项目文件为准。

## C. 写入规则

1. `PROJECT_STATE.md` 是**当前态快照**，需要整理而非堆历史；每次状态变化后同步更新，保持约 30-100 行。
2. `DECISIONS.md` **永远追加，不覆盖**。修改旧决定时新增一条：`D-NNN Supersedes: D-MMM`，旧决定保留并标记为 `superseded`。
3. Scene / Shot / Asset Memory **每个对象独立文件**，互不污染；引用关系用 ID 链接，不复制内容。
4. `approvals.yaml` 是**结构化审批态**，包含历史不该删除；Supersedes 关系必须显式。

## D. 详细每层字段表

### D.1 PROJECT_STATE.md（Current Truth，约 30-100 行）

| 字段 | 含义 | 约束 |
|---|---|---|
| Project | 项目名 / 标题 | 必须存在 |
| Production Mode | 制作模式：`PRODUCT_TECH_SHORT` / `EDITORIAL_EXPLAINER` / `CUSTOM` | 枚举 |
| Delivery Mode | 交付方式：`FINAL_VIDEO_ONLY` / `EDITABLE_PROJECT` / `BOTH` | 枚举 |
| Current Stage | 当前 Stage ID（来自状态机枚举） | 必须与 `project.STAGES[]` 一致 |
| Current Scene | 当前 Scene ID（如 SC001），无则 `null` | 引用 scenes/ |
| Current Shot | 当前 Shot ID（如 S018），无则 `null` | 引用 shots/ |
| Approved Stages | 已获批的 Stage / Approval 列表 | 必须与 `approvals.yaml` 一致 |
| Pending Decisions | 待用户决定的决策 / 审批 | 对应 `waiting_user` |
| Blocked Items | 阻塞项与原因 | 对应 stage `blocked` |
| Current Style | 当前视觉 Style（引用 Visual Bible） | 获批后写入 |
| Current Audio Direction | 当前声音方向（引用 AUDIO_DIRECTION） | 获批后写入 |
| Important Constraints | 关键约束（避免清单、可编辑性要求等） | 简明 |
| Next Action | 下一步动作 | 与状态机 `next_stage` 对齐 |
| Last Updated | 最后更新时间（ISO 8601） | 每次修改必须更新 |

### D.2 DECISIONS.md（长期决策，只追加）

每条决策（§16）：

| 字段 | 含义 |
|---|---|
| Decision ID | `D-###` 唯一 ID |
| Date | 日期 |
| Scope | 范围（如 `Global Motion Language`、`Visual Bible`） |
| Decision | 决定内容 |
| Reason | 理由 |
| User Feedback | 用户反馈 |
| Status | 状态（Approved / Superseded / 等） |
| Supersedes | 本决定覆盖的旧决定 ID（如 `D-014`） |
| Related Scene | 相关 Scene ID |
| Related Shots | 相关 Shot ID |
| Related Assets | 相关 Asset ID |

约束：只追加；新决定替代旧决定必须写 `Supersedes: D-###`；旧决定保留并标记 `superseded`，不得删除或改写历史。

### D.3 Scene Memory（`scenes/SC###.md`）

| 字段 | 含义 | 约束 |
|---|---|---|
| Narrative Role | 叙事角色（Hook / Build / Payoff 等） | — |
| Chapter | 所属章节 | — |
| Scene Goal | 场景目标 | — |
| Approved Direction | 已获批的场景方向 | 关联 Approval ID |
| Shots | 包含的 Shot ID 列表 | 引用 shots/ |
| Audio | 场景级声音安排 | 引用 AUDIO_DIRECTION |
| Constraints | 场景约束 | — |
| Change History | 变更记录（追加） | 不覆盖 |
| Status | 场景状态（枚举） | — |

### D.4 Shot Memory（`shots/S###.md`，§18 完整字段）

| 字段 | 含义 |
|---|---|
| Narrative Purpose | 叙事目的 |
| Approved Visual | 已获批的视觉方案 |
| Layers | 包含的 Layer 列表 |
| Motion | 动效设计 |
| Camera | 运镜 |
| Text | 字幕 / 屏幕文字 |
| Audio | 声音（music / sfx / ambience / ducking） |
| Route | 技术路由（REMOTION / THREE_D / REAL_FOOTAGE / GENERATIVE_VIDEO / JY_NATIVE / HYBRID） |
| Assets | 使用到的 Asset ID 列表 |
| Continuity Group | Motion Continuity Group（是否应连续 Render） |
| User Constraints | 用户约束 |
| Change History | 变更记录（追加，不覆盖） |
| Implementation Status | 实现状态 |
| QA Status | QA 状态 |

### D.5 Asset Memory（`assets/A###.md`，§19 完整字段）

| 字段 | 含义 |
|---|---|
| Asset ID | `A###` |
| Purpose | 用途 |
| Producer | 生产者（REMOTION / THREE_D / AI_VIDEO / FOOTAGE / 等） |
| Type | Asset Type 枚举（TRANSPARENT_OVERLAY / ANIMATED_TEXT / 等） |
| Version | 版本（v1 / v2 / …） |
| File / Source Location | 文件路径或来源 |
| License | 许可 |
| Resolution | 分辨率 |
| FPS | 帧率 |
| Alpha | 是否含透明通道 |
| Duration | 时长 |
| Used In | 使用于哪些 Shot |
| Replaceable | 是否可替换 |
| Render Settings | 渲染设置 |
| Change History | 变更记录（追加，不覆盖） |
| Status | 资产状态（枚举） |

## E. PROJECT_TEMPLATE 初始化链路

新项目初始化流程（`project-template/` 目录由 P4 创建并维护模板文件）：

1. **复制模板文件**：从 `project-template/` 复制 `PROJECT_STATE.md`、`DECISIONS.md`、`approvals.yaml` 到新项目目录。
2. **创建目录**：创建 `scenes/`、`shots/`、`assets/`、`references/`、`source/`、`audio/`、`remotion/`、`timeline/`、`previews/`、`renders/` 等目录。
3. **初始化状态机**：在 `PROJECT_STATE.md` 将 `Current Stage` 置为 `PROJECT_INTAKE`（由 `INIT` 进入），并在 `project.STAGES[]` 建立 INIT 的实例记录。
4. **初始化审批态**：`approvals.yaml` 中项目级审批门全部为 `not_started`，`approvals:` 历史列表为空，`scenes/shots/assets` 为空对象。
5. **后续同步**：每个 stage 变化、每次审批、每个对象创建都同步更新对应记忆文件（见 C 节写入规则）。

依赖约定：

- 初始化由项目创建流程触发（Test 1：必须生成 `PROJECT_STATE.md`、`DECISIONS.md`、`approvals.yaml`、`scenes/`、`shots/`、`assets/`、`audio/`、`timeline/`）。
- 模板与项目的差异（新增 / 修改字段）需在 `project-template/` 中同步，避免模板漂移。
