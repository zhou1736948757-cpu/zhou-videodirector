---
workflow_id: WF-008
name: Shot / Layer 技术路由
stage_ids: [SHOT_ROUTING, LAYER_ROUTING, ROUTING_REVIEW]
requires_approval: [ROUTING_REVIEW]
phase3_status: implemented
---

# Shot / Layer 技术路由（Routing）

## 目标
为每个 Shot（必要时每个 Layer）决定生产技术路线，输出人类可读 `ROUTING_PLAN.md` 供 `ROUTING_REVIEW` 审批门审查，批准后进入 `RESOURCE_PLANNING`。核心原则：**Router 只建议不裁决创意**（§49）——技术上不可行的 Storyboard 走 `ROUTING_CONFLICT` 回 `STORYBOARD_REVIEW` 等用户确认，不偷偷改。

## 触发时机
`STORYBOARD_REVIEW` 已批准后触发（中间可先经可选的 `SUBAGENT_CONFIGURATION` 配置并行 Subagent）。

## 输入
- `<project>/STORYBOARD.md` + `scenes/SC###.json` + `shots/S###.json`（`STORYBOARD_REVIEW` 已批准的 storyboard）
- `<project>/VISUAL_BIBLE.md`（视觉约束，影响候选 Route 概率；非硬规则）
- `<project>/AUDIO_DIRECTION.md`（audio sync 需求，提高 `timing_precision` 因子）
- `<project>/PROJECT_BRIEF.md` + `project.json`（`production_mode` / `budget_priority` / AI Video Policy / Real Footage Policy / 3D Policy）
- 引擎：`modules/router/router.py`（CLI：`python3 modules/router/router.py <project_dir> [--json]`）
- 模板：`templates/routing-plan.md` / `templates/routing-shot.yaml` / `templates/routing-layer.yaml`
- 契约：`schemas/routing.schema.json`、`schemas/layer.schema.json`；状态机：`schemas/state-machine.json`

## 执行步骤

### 1. Shot Router（一级路由）
逐 Shot 跑 `modules/router/router.py`（Hard Constraints → 12 因子启发式 → 候选生成 → LLM judgment hook → 置信度 → 原型决策 → Bake 决策）。
- 简单 Shot → 单 Route 直出（`routing/S###.yaml`），不做 Layer 拆分。
- 只保存可审计的 `decision_summary`（≤300 字符），禁止保存私有 Chain-of-Thought（§38）。
- 升级/降级规则（§64-66）：JY_NATIVE 复杂度超限 → 升级 REMOTION；REMOTION 的简单照片慢推 → 降级 JY_NATIVE。

### 2. Layer Router（二级路由，仅按需）
满足以下之一才启用 Layer 拆分（§23 决策树）：
- Shot Route = HYBRID（强制拆，§22）；
- 存在多个 Producer / 多视觉职责；
- 不同 editability 需求（部分要可编辑、部分可 bake）。

拆分依据：
- **Production Responsibility Boundary**（§28）：可能由不同 Producer / 不同资源 / 不同更新周期 / 不同编辑方式完成时才拆。
- **Editability Boundary**（§29）：主动判断 `Should this remain editable in JianYing?`——subtitle→KEEP_EDITABLE、B-roll→KEEP_EDITABLE、连续大段运动→BAKE、AI footage→ASSET_REPLACEABLE、3D overlay→ASSET_REPLACEABLE。
- **不过度 Layer 化**（§27）：不拆成 background gradient / left shadow / icon A 这类无意义数据。

输出 `layers/S###.yaml`（Layer ID：`S###-L##`，role 16 枚举）；音频不参与 Layer 路由（由 Shot Audio 体系管理）。

### 3. ROUTING_CONFLICT 协议（§48-49）
若发现 storyboard 技术上不合理（如极端成本、生成式无法实现的精确内容、路线不可行）：
- **不偷偷改 Storyboard**；
- 输出 Conflict 记录，字段：`Shot / Problem / Why / Suggested adaptation / Impact on creative`；
- 回 `STORYBOARD_REVIEW` 等用户确认后重走。
Router 无创意裁决权：可以说「这个设计很贵」，不能说「我换成另一个创意」；Creative 修改必须回到对应 Approval。

### 4. User Override（§71-73）
- 用户直接指定 Route（如「这个镜头不要 AI，用 3D」）→ 写 `<project>/routing/overrides.json`（`route` / `source: USER_OVERRIDE` / `note`）。
- 重新路由时 override 持久化应用，**不被自动结果覆盖**；`route_source: USER_OVERRIDE`，`confidence: 1.0`。
- 用户再次修改 → 旧 Route **不删除**，新决策记录 `supersedes` 指向旧 route（§73），并更新 Shot Current State。
- `route_source` 4 枚举：`AUTO | USER_OVERRIDE | DIRECTOR_OVERRIDE | PROTOTYPE_RESULT`。

### 5. ROUTING_REVIEW Approval Gate（§68-70）
- 向用户呈现**人类可读摘要**（`ROUTING_PLAN.md`，9 节 §51）：Which shots use Remotion / AI Video / Footage / 3D / JianYing-editable / Hybrid / prototypes。
- §70 原则：只列 high-cost / high-risk / hybrid / AI-generated / large-3D / low-confidence / baked 的 Shot；普通 photo+subtitle 不浪费用户注意力。
- **不审 100 个 YAML**：机器细节在 `routing/S###.yaml` / `layers/S###.yaml`，仅作追溯。
- 批准 → 状态机迁移 `ROUTING_REVIEW → RESOURCE_PLANNING`；
- 打回 → `ROUTING_REVIEW → SHOT_ROUTING` 重新产出（或按 Conflict 回 `STORYBOARD_REVIEW`）。

## 输出（项目文件）
- `routing/S###.yaml`：每 Shot 一条路由决策（§53，见 `templates/routing-shot.yaml`）
- `layers/S###.yaml`：需要 Layer 拆分的 Shot 的 Layer 数组（§54，见 `templates/routing-layer.yaml`）
- `<project>/ROUTING_PLAN.md`：人类可读 Routing Plan（§51，9 节，见 `templates/routing-plan.md`）
- `EDITABILITY_PLAN` 节：覆盖 footage / subtitles / titles / motion assets / AI clips / music / SFX / images，逐项标记 `KEEP_EDITABLE / ASSET_REPLACEABLE / BAKED`（§57）
- 更新 `shots/S###.md` 的 route 字段（把 storyboard 阶段的 "Likely: …" 意向落为最终 Route）
- 记录到 `<project>/DECISIONS.md`；`ROUTING_REVIEW` 的审批态写入 `approvals.yaml` / `PROJECT_STATE.md`

## 阶段状态变更
`SHOT_ROUTING` → `LAYER_ROUTING` → `ROUTING_REVIEW` → `RESOURCE_PLANNING`
（`ROUTING_REVIEW` 打回 → `SHOT_ROUTING`；ROUTING_CONFLICT → `STORYBOARD_REVIEW`）

## Approval Gate
`ROUTING_REVIEW`（requires_approval: true，§68）。高影响执行动作（Subagent 激活、大型下载）仍需 Execution Approval（v0.2 §50）。

## 禁止
- 不实现路由逻辑（引擎已在 `modules/router/`）；不改 schemas；不改其它 workflow。
- 不写 Remotion / 生产代码（属后续 Phase）。
- 不保存私有 CoT；不偷偷修改 Storyboard（创意修改必须回 Approval）。
