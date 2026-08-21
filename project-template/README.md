# project-template — 新项目初始化说明

> 用途：新建视频项目时的初始快照。初始化步骤与目录结构如下。
> 项目推进完全由执行 workflow 控制：第一步执行 `workflows/project-intake.md`（Grill Me → Project Brief → Approval）。
> 本 README 只说明结构与目录用途，不提供创建命令；目录创建由执行 workflow 负责。

## 初始化步骤

1. 复制 `PROJECT_STATE.md`、`DECISIONS.md`、`approvals.yaml` 到新项目根目录。
   - `PROJECT_STATE.md`：项目当前真相（Current Truth），每次会话开始首先读取。
   - `DECISIONS.md`：长期决定记忆，只追加不覆盖。
   - `approvals.yaml`：机器可读审批状态，初始全部 `not_started`。
2. 在新项目根目录创建以下目录（用于存放后续产生的 Scene / Shot / Asset 等文件）：
   - `scenes/` — Scene Memory 文件（`scenes/SC###.md`）
   - `shots/` — Shot Memory 文件（`shots/S###.md`）
   - `assets/` — Asset Memory 文件（`assets/A###.md`）
   - `references/` — 参考视频与分析报告（`REFERENCE_ANALYSIS.md`）
   - `source/` — 源文件与原始素材（脚本、工程源）
   - `audio/` — 音频素材（Music / SFX / VO / Ambience / SoundFont）
   - `remotion/` — Remotion 工程与渲染输出
   - `timeline/` — 可编辑时间线（剪映草稿等）
   - `previews/` — 预览图 / 预览视频
   - `renders/` — 最终渲染输出
   - `external-visual/` — Phase 6 外部视觉中间产物（`continuity/` `footage/` `generative/`）
3. 每个目录只存放对应类型的文件；ID 格式统一：Scene `SC###`、Shot `S###`、Layer `L###`、Asset `A###`、Decision `D-###`、Approval `AP-###`。
4. 项目进入 Phase 6（存在 GENERATIVE_VIDEO / REAL_FOOTAGE / HYBRID 路由的 Shot）时，
   创建 `external-visual/` 目录（`continuity/`、`footage/`、`generative/` 三个子目录，
   见 `external-visual/README.md`），存放 Phase 6 中间产物（请求/搜索/评审/plan 等）；
   最终 Asset 与三份 manifest 仍走 `assets/` 与 `production/`。

## 记忆与审批的关系

- `PROJECT_STATE.md` 代表 Current Truth（当前真相），不保存完整历史。
- `DECISIONS.md` 保存完整决定历史。
- `approvals.yaml` 是审批的机器可读状态；`PROJECT_STATE.md` 的 Approved Stages 必须与之一致（由 validator 校验）。
