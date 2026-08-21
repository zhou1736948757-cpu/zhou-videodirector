# ZHOU_Videodirector — README

## §1 项目定位

`ZHOU_Videodirector` 是以导演决策为核心、能够调度 Motion Design、3D、真实素材、
AI Video、Sound Design 与剪映可编辑时间线的视频生产总控 Skill。核心价值是生成
「既能自动化生产、又能由人继续接管编辑」的视频工程。

## §2 Phase 1 交付清单

本阶段（Phase 1 — Constitution & Skeleton）交付以下内容。**它不会做视频**，只建立
导演操作系统骨架（依据 Phase-1 Prompt §43-45 验收标准）。

| 类别 | 数量 | 内容 | 对应任务 |
|---|---|---|---|
| docs/ | 6 | constitution.md、state-machine.md、approval-system.md、memory-system.md、external-capability-policy.md、reuse-map.md | P1a / P1b |
| workflows/ | 12 | project-intake、reference-analysis、creative-direction、style-direction、sound-direction、editorial-direction、storyboard、routing、resource-planning、asset-production、timeline-editing、qa | P3 |
| schemas/ | 11 | project、visual-bible、audio-direction、scene、shot、layer、routing、asset、timeline、approval `.schema.json` × 10 + state-machine.json | P1b / P2 |
| templates/ | 7 | project-state.md、decisions.md、scene-memory.md、shot-memory.md、asset-memory.md、audio-map.md、approvals.yaml | P4 |
| project-template/ | 4 | PROJECT_STATE.md、DECISIONS.md、approvals.yaml、README.md（目录职责说明） | P4 |
| scripts/ | 1 | project-validate.py（轻量校验，Python 3 stdlib） | P5b |
| 根文件 | 3 | SKILL.md、README.md、dependencies.yaml | P5a |
| 测试报告 | 1 | Test 1-12 + 验收场景 A-E 执行报告 | P6 |

## §3 目录结构

依据 Phase-1 Prompt §6，当前目标结构（Phase 2+ 目录见 §5，不在此创建）：

```text
ZHOU_Videodirector/
│
├── SKILL.md
├── README.md
├── dependencies.yaml
│
├── docs/
│   ├── constitution.md
│   ├── state-machine.md
│   ├── approval-system.md
│   ├── memory-system.md
│   ├── external-capability-policy.md
│   └── reuse-map.md
│
├── workflows/
│   ├── project-intake.md
│   ├── reference-analysis.md
│   ├── creative-direction.md
│   ├── style-direction.md
│   ├── sound-direction.md
│   ├── editorial-direction.md
│   ├── storyboard.md
│   ├── routing.md
│   ├── resource-planning.md
│   ├── asset-production.md
│   ├── timeline-editing.md
│   └── qa.md
│
├── schemas/
│   ├── project.schema.json
│   ├── visual-bible.schema.json
│   ├── audio-direction.schema.json
│   ├── scene.schema.json
│   ├── shot.schema.json
│   ├── layer.schema.json
│   ├── routing.schema.json
│   ├── asset.schema.json
│   ├── timeline.schema.json
│   ├── approval.schema.json
│   └── state-machine.json
│
├── templates/
│   ├── project-state.md
│   ├── decisions.md
│   ├── scene-memory.md
│   ├── shot-memory.md
│   ├── asset-memory.md
│   ├── audio-map.md
│   └── approvals.yaml
│
├── project-template/
│   ├── PROJECT_STATE.md
│   ├── DECISIONS.md
│   ├── approvals.yaml
│   └── README.md
│
└── scripts/
    └── project-validate.py
```

## §4 路线图（v0.2 Phase 2-8）

| Phase | 目标 | 关键交付 |
|---|---|---|
| Phase 2 — Director Pipeline | 稳定地设计视频，而不是写代码 | Grill Me、Reference workflow、Creative / Style / Sound / Editorial Director、Storyboard |
| Phase 3 — Shot / Layer Router | 决定每一部分谁做（系统最重要的智能之一） | REMOTION / THREE_D / REAL_FOOTAGE / GENERATIVE_VIDEO / JY_NATIVE / HYBRID、Scene Entropy、Layer 分解 |
| Phase 4 — Resource Registry | 统一「用什么已有资源」 | find / detail / preview / fetch；Onda、Remotion Bits、Shotcraft、3D、SFX、Music、SoundFont |
| Phase 5 — Motion / 3D / Sound Engine | 此时能生产真正 Assets | Official Remotion、Three.js / R3F、FluidSynth、SFX Provider |
| Phase 6 — Generative / Footage Pipeline | 真实素材与 AI Video 进入 Asset Pipeline | Real Footage search、AI Video routing、Production Packet、License Metadata |
| Phase 7 — Editable Timeline | 自动生成人可继续编辑的剪映草稿 | pyJianYingDraft、Track schema、Asset placement、Keyframe、Transition |
| Phase 8 — Subagents + QA + E2E | 从 IDEA 走到 Editable Project + Final Video（V1） | Subagent Coordinator、四层 QA、Memory 自动更新、Test A（90s 产品片）/ Test B（8 分钟科普） |

## §4.1 Phase 6 能力与入口

Phase 6（Generative Video / Real Footage Pipeline）已落地：

- **统一 CLI**：`python3 scripts/external-visual.py <subcommand> [--json]` ——
  request / packet / search / select / plan-use / review / ingest / normalize /
  proxy / provenance / handoff / package / manual-export（薄分发层，任意 cwd 可直跑）。
- **架构文档**：`docs/external-visual.md`（两大管线图、EV→GV/FR 流转、
  MANUAL/ASSISTED/AUTOMATED、Cost/Privacy gate、Review/验收状态机、
  Normalization/Proxy、Provenance、Handoff，与 PHASE6_PROMPT §对应）。
- **引擎模块**：`modules/external-visual/`（packet_builder / continuity / footage /
  ingestion / review / gates / workflow / provenance / handoff）。
- **三份 manifest**：VISUAL_PROVENANCE_MANIFEST（6 问溯源，§96-97）、
  TIMELINE_HANDOFF_MANIFEST（只提示不建时间线，§133-134）、
  ASSET_PACKAGE_MANIFEST 扩展（§105/§132，向后兼容 Phase 5）。
- 运行时依赖：ffmpeg/ffprobe 8.x（homebrew，见 `dependencies.yaml`）。

## §5 v0.2 §61 未来目录（Phase 2+ 才建）

以下目录属于总设计 v0.2 §61 的最终工程结构，**当前（Phase 1）不创建**，
原因引用 Phase-1 Prompt §6：

> 不要为了看起来“专业”创建大量空目录。每一个创建的文件必须有明确职责。

| 未来目录 | 何时创建 |
|---|---|
| modules/（grill-me、creative-director、shot-router …） | Phase 2-3 各模块实现时 |
| presets/（6 个 Style 预设） | Phase 2 Style Director 实现时 |
| adapters/（watch-video、video-shotcraft、pyjianyingdraft …） | 各外部能力接入时 |
| registry/（motion、3d、sfx、music …） | Phase 4 Resource Registry 建立时 |
| previews/ | Phase 3+ 需要本地预览时 |
| scripts/ 其余（registry-search、timeline-build、memory-update …） | 对应 Phase 需要时 |
| project-template 子目录（scenes/、shots/、assets/ …） | 项目初始化时按 workflow 创建（Test 1 覆盖） |

## §6 加载与部署

当前 Skill 位于 `/Users/mac/skills/ZHOU_Videodirector/`，**未在 ZCode 默认技能发现路径内**
（`~/.zcode/skills`、`~/.agents/skills`、工作区）。开发阶段可直接在本目录进行；后续
真正被调用时需要选择：

- 选项 A：符号链接 `~/.agents/skills/ZHOU_Videodirector → /Users/mac/skills/ZHOU_Videodirector/`
- 选项 B：在 ZCode 配置中显式添加技能根目录
- 选项 C：整个 `cp` 到 `~/.agents/skills/`

具体方式待 **Phase 2+** 真正被调用时由用户决定（当前不修改任何技能发现配置）。

## §7 版本说明

- **主设计文档**：`docs/design/ZHOU_Videodirector_总设计_v0.2.md`（权威）。
- 旧版 v0.1：`/Users/mac/Downloads/ZHOU_Videodirector_开发总目标与系统设计_v0.1.md`，
  仅记录于 `dependencies.yaml`，**不**引入仓库；冲突时按 `v0.2 > v0.1` 处理。
- 本仓库内 v0.2 设计文档为唯一设计依据；Phase-1 Prompt 约束本阶段范围。

## §8 验收

Phase 1 验收由 **P6** 阶段执行：

- Phase-1 Prompt §42 的 Test 1-12（Project Init、Approval Blocking/Success/Revision、
  Scene/Shot/Layer、Hybrid Shot、Asset Metadata、Audio、Invalid Stage、Broken Relationship、
  Approval Conflict、Human Editable）
- Phase-1 Prompt §43 的验收场景 A-E（不提前制作视频、Brief 后等待审批、Decision
  Supersede、重开 Agent 只读 PROJECT_STATE、Reference Analyzer 先查依赖地图）

测试报告路径（占位）：`/Users/mac/.zcode/workspace/default/zhou-videodirector-phase1/`，
本 README 完成后由 P6 产出正式测试报告。
