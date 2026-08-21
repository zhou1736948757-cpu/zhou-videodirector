---
name: ZHOU_Videodirector
description: >-
  Use 当用户要做一个「导演级」视频生产工程时：完整视频项目的需求理解、参考视频
  分析（Reference Analysis）、创意方向（Creative Direction）、风格与声音方向
  （Style / Sound Direction）、Storyboard / Scene / Shot / Layer 分镜拆解、
  Remotion Motion 生产编排、AI Video Prompt、剪映可编辑时间线、项目级视频记忆
  与 Approval 审批流程（关键词：导演、分镜、创意策划、Remotion Motion、AI Video、
  剪映时间线、可编辑工程、参考分析、项目记忆）。
  Do NOT use for 一次性小需求：如「帮我写一段动画代码」、单个 Remotion 组件写法、
  或「一句话直接生成一个 MP4」的黑盒出片。本 Skill 是一个视频生产操作系统
  （Director OS），不是动画代码助手，也不是一键生成成片工具。
---

# ZHOU_Videodirector

## 1. Identity

`ZHOU_Videodirector` = **AI Video Production Director**。

一个以导演决策为核心、能够调度 Motion Design、3D、真实素材、AI Video、Sound Design
与剪映可编辑时间线的视频生产总控 Skill。它负责把 IDEA 变成「既能自动化生产、又能由人
继续接手编辑」的视频工程；它不是单纯的 Remotion Skill，也不是一句话生成最终 MP4 的
黑盒。用户始终可以打开剪映工程，直接接管最后的剪辑。

## 2. Core Workflow

```text
IDEA
→ Direct
→ Design
→ Route
→ Produce
→ Edit
→ QA
→ Final
```

细节不在此展开：各阶段流程见 `docs/`，运行时行为见 `workflows/*.md`，
数据结构见 `schemas/*.json`。

## 3. Constitution References

- [docs/constitution.md](docs/constitution.md)
- [docs/state-machine.md](docs/state-machine.md)
- [docs/approval-system.md](docs/approval-system.md)
- [docs/memory-system.md](docs/memory-system.md)
- [docs/reuse-map.md](docs/reuse-map.md)
- [docs/external-capability-policy.md](docs/external-capability-policy.md)

## 3.1 Phase 6 — Generative Video / Real Footage Pipeline

Phase 6 建立 **Generative Video（AI 生成）** 与 **Real Footage（真实素材）** 两个正式
生产分支，产物进入 Asset Pipeline 并回接到 Phase 5 ASSET_PACKAGE_MANIFEST：

- 架构文档：[docs/external-visual.md](docs/external-visual.md)（两大管线图、EV→GV/FR
  流转、MANUAL/ASSISTED/AUTOMATED、Cost/Privacy gate、Review/验收状态机、
  Normalization/Proxy、Provenance、Handoff，与 PHASE6_PROMPT §对应）。
- **统一入口**：`python3 scripts/external-visual.py <subcommand> [--json]`，任意 cwd
  可直跑（脚本自举 sys.path）。子命令：
  `request / packet / search / select / plan-use / review / ingest / normalize /
  proxy / provenance / handoff / package / manual-export`。
- 引擎模块：`modules/external-visual/`（packet_builder / continuity / footage /
  ingestion / review / gates / workflow / provenance / handoff）。
- 契约：`schemas/` 的 EV / GV / FR / review / provenance-manifest / timeline-handoff
  与扩展后的 asset schema（ID/枚举总表见 `work/p6-01/SCHEMA_CONTRACT.md`）。
- 铁律：provider-neutral（不硬编码模型名）；6 问 Provenance 缺省写 UNKNOWN 不猜值；
  Timeline Handoff **只提示、不创建时间线**（§134）。

## 4. Progressive Disclosure

按需加载，禁止一次性把所有内容塞进上下文。只有必要时才进入下一层：

```text
SKILL.md
  → Workflow (workflows/*.md)
  → Module / Docs (docs/*.md)
  → Registry Metadata (LEVEL 0 catalog)
  → Resource Detail (LEVEL 1 details)
  → Actual Source (LEVEL 2 fetch / clone / install)
```

Resource 只有确认使用之后才 fetch / 下载 / Clone。

## 5. Phase 1 状态

当前处于 **Phase 1（Constitution & Skeleton）**。它**不会**做视频。

本阶段只建立导演操作系统骨架：Constitution、State Machine、Approval、Memory、
Scene / Shot / Layer / Asset 数据结构与依赖地图。真正的分镜设计、Shot Router、
Remotion 生产、AI Video 与剪映时间线属于 **Phase 2+**，本 SKILL 当前不执行
这些流程，也不实现任何视频制作能力。

## 6. 与现有技能边界

- `remotion-*` skills（remotion-create / remotion-best-practices / remotion-docs /
  remotion-render 等）：`ZHOU_Videodirector` 是它们的**总控**——决定何时调用它们
  做什么，但**不**实现 Remotion 组件细节；具体 Remotion 写法交给它们。
- `video-analyst`：Reference Analysis 阶段调用它做本地视频分析（ASR / 抽帧 / 分析报告）。
- `ds-vision-skill`：需要识别参考图片、截图、分镜图等视觉输入时调用。

## 7. Quick Reference

何时 invoke 本 SKILL：看 Project Intent 是否为「导演级视频工程」。

- 触发：用户要做完整视频项目，涉及创意、风格、声音、分镜、路由、剪辑等多阶段决策；
  需要跨 Shot 一致性、项目记忆、Approval 审批、可编辑时间线；需要编排 Remotion /
  AI Video / 3D / 剪映 等多能力。
- 不触发：单个组件写法、一次性出片、纯 Remotion 编码问题 → 交给对应 `remotion-*` skill。
