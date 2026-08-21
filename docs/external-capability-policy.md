# ZHOU_Videodirector — 外部能力接入政策（External Capability Policy）

本文件定义 `ZHOU_Videodirector` 如何接入外部能力（第三方 Skill、Library、CLI、API、Registry、资源库），以及"什么情况下可以自建、什么情况下必须复用"。

- 来源：总设计 v0.2 §35 / §62 / §68 / §69 / §70 / §72、Phase-1 Prompt §32 / §34 / §35。
- 配套：能力清单见 [reuse-map.md](reuse-map.md)，机器可读依赖见 `dependencies.yaml`，顶层约束见 [constitution.md](constitution.md)。
- 核心信条：**Reuse → Adapt → Compose → Build Last**。

Integration Mode 全量枚举（本项目唯一合法取值，不得自造新值）：

```text
EXTERNAL_SKILL | PROVIDER | KNOWLEDGE_ADAPTER | ARCHITECTURE_REFERENCE | TIMELINE_BACKEND | RESOURCE_PROVIDER
```

当一个外部能力同时承担两种角色时，只允许从上述枚举中组合（如 `EXTERNAL_SKILL + KNOWLEDGE_ADAPTER`），并以其中一个为主模式。

---

## A. 六种 Integration Mode 的精确定义

### 1. EXTERNAL_SKILL

**定义**：第三方以"完整 Skill"形式提供能力（有自己的 SKILL.md、流程与触发方式），ZHOU_Videodirector 按官方方式加载并整体调用。

- **调用方式**：按官方文档安装 / 链接 Skill；通过其 SKILL.md 入口触发；结果按 Skill 定义的结构返回，ZHOU_Videodirector 负责把结果套进自己的 schema。
- **典型场景**：参考视频观看（watch-video-skill）、官方 Remotion Agent Skills、本机已有 Skill（video-analyst / ds-vision-skill / human-voice / computer-use / remotion 系列）。
- **风险与边界**：Skill 自带 prompt / 行为可能与我们状态机冲突；其输出可能不符合我们的 schema；Skill 内部可能发生行为漂移。边界：Skill 只负责"它那一层"（如看见视频），理解与决策属于 ZHOU_Videodirector。
- **失败处理建议**：捕获失败与超时；降级到备用 Skill 或 PROVIDER 路径（如 Reference 分析备用 claude-video）；绝不把 Skill 内部临时状态当作项目记忆。

### 2. PROVIDER

**定义**：第三方通过 CLI / MCP / API / Registry 暴露能力，ZHOU_Videodirector 只发请求、收结果，不拥有其实现。

- **调用方式**：CLI 二进制调用、MCP 工具、HTTP API、Registry 检索并按需获取。
- **典型场景**：yt-dlp 下载参考视频、FluidSynth 渲染 MIDI→Audio、remotion-bits / onda 按需获取组件、Freesound API 搜索 SFX、gltfjsx 将 GLTF 转 R3F JSX。
- **风险与边界**：依赖网络与第三方可用性；License / ToS 条款需遵守；返回格式可能不稳定。边界：Provider 不拥有导演决策；ZHOU_Videodirector 不 fork Provider 代码。
- **失败处理建议**：重试 + 超时；使用前检查 License / ToS；记录 Provider 版本；返回结构校验失败按 `failed` 记录并上报。

### 3. KNOWLEDGE_ADAPTER

**定义**：借用第三方的方法论、规则、Recipe、分类结构，以"我们自己实现的适配层"形式吸收，不整体复制代码。

- **调用方式**：阅读源码 / 文档，提炼规则写入适配层（如 Shot Recipe 分类、运镜语言、taste 反模板规则），运行时由 ZHOU_Videodirector 自己执行。
- **典型场景**：video-shotcraft（Shot Recipes / 2.5D 运镜 / 节奏）、taste-skill（Design Language / Motion Intensity / Density）、remotion-video-director（从需求到 Scenario 的交互式导演流程）。
- **风险与边界**：提炼的规则可能脱离原文语境；吸收过度会退化为事实复制。边界：不 `copy_entire_repository`；不 `make_it_the_master_workflow`（不把对方流程变成我们的主流程）。
- **失败处理建议**：吸收内容标注出处与提炼时间；与原文冲突时以提炼后的规则文档为准并记录理由；若无法提炼清楚，降级为 ARCHITECTURE_REFERENCE 或放弃。

### 4. ARCHITECTURE_REFERENCE

**定义**：只学习第三方架构思想（分层、接口、编排方式），不复制其实现代码。

- **调用方式**：阅读架构文档 / 目录结构 / 接口定义；将学到的模式落进 ZHOU_Videodirector 自己的架构文档。
- **典型场景**：OpenMontage（Pipeline / Tool·Provider Registry / Agentic Video 能力编排）、VectCutAPI（Agent 视频编辑 API 与草稿思路）。
- **风险与边界**：借鉴过度会变成实现抄袭。边界：不复制代码文件，不整仓搬入。
- **失败处理建议**：在架构文档中记录借鉴点与出处；review 时专门检查是否存在过度借鉴。

### 5. TIMELINE_BACKEND

**定义**：第三方作为"可编辑时间线"的执行后端，负责把 ZHOU_Videodirector 的时间线意图变成真正可打开的剪映 / CapCut 草稿。

- **调用方式**：通过其 Python API / CLI 生成草稿；ZHOU_Videodirector 负责决定 timeline 结构、资产边界、可编辑边界，并产出 timeline manifest。
- **典型场景**：pyJianYingDraft（第一版主后端）、VectCutAPI、pyCapCut（备用）。
- **风险与边界**：草稿格式随剪映版本升级可能变化；后端可能不支持某些效果。边界：不 `fork_and_rewrite_editor`；后端能力不足时用 Remotion 资产补齐，而不是改写后端。
- **失败处理建议**：草稿生成后必须用剪映打开验证；版本兼容问题记录为已知限制；后端不可用时降级为"资产包 + 手动导入说明"。

### 6. RESOURCE_PROVIDER

**定义**：第三方只作为素材 / 模型 / 音频 / 音乐等资源的来源，即 Resource Registry 的一个 Provider。

- **调用方式**：Registry 保存元数据（Level 0 Catalog / Level 1 Detail），使用时按需 fetch（Level 2）；License 与 Attribution 由提供方定义并原样保留。
- **典型场景**：Poly Haven（3D / HDRI / Texture）、Freesound（SFX）、Mixkit（Music / SFX / Footage）、Openverse（开放授权图片与 Audio）、CC0-1.0-Music、GeneralUser-GS（SoundFont）、@remotion/sfx。
- **风险与边界**：License 误用；下载体积失控；资源可用性变化。边界：不把资源整库搬进本地，只建元数据索引（本地不存素材全集）。
- **失败处理建议**：每次使用前检查 License 字段并写入 asset 元数据；下载失败标记 resource unavailable 并从候选剔除；有 Attribution 要求的必须记录。

---

## B. Major Capability Before Build Check（强制流程）

以下能力（以及其他任何"主要能力"）在开发 / 实现之前，必须按顺序执行本检查，并把检查记录写进对应开发计划：

```text
Reference Analyzer
Motion Engine
Timeline Backend
Sound Engine
3D Asset Search
Generative Video 管线
Subagent Pipeline
QA Engine
```

强制流程：

```text
1. 查 dependencies.yaml           → 是否已有登记的外部依赖 / 参考
2. 查 Reuse Map                  → 是否已有对应参考实现与本机能力（docs/reuse-map.md）
3. 判断 integration_mode         → 从 6 种 mode 中选定（可为组合，但必须落在枚举内）
4. Reuse / Adapt / Compose / Build Last → 优先复用，其次适配，其次组合，最后才自建
5. 才进 Build                    → 无前四步记录，不得进入实现
```

反例（禁止路径）：

```text
Reference Analyzer
  → 直接开始写 yt-dlp wrapper
  → 重新写 ffmpeg 抽帧
  → 重新写字幕提取
  → 重复造轮子
```

本检查的记录至少包含：查了什么、判定的 integration_mode、复用/适配/组合的具体对象、Build 的范围。该记录可由 review 与 validator 校验（见 [constitution.md](constitution.md) 原则 16）。

---

## 运行时视觉能力探测（Runtime Visual Capability Probe）

Phase 2 Reference Analysis 与 Phase 8 Full QA 的入口，在任何"看视频 / 看图"动作之前必须执行一次**运行时视觉能力探测**（不假设能力可用）：

```text
python3 scripts/visual_capability_probe.py [--model <当前模型名>] [--json]
```

探测两部分：① 本机工具可用性（自动：video-analyst CLI / ffmpeg / yt-dlp / mimo-vision.sh）；② 当前模型视觉能力（内置已知表，未知模型 → `UNKNOWN` → 请用户人工确认）。按结果选择三档视觉通道：

```text
A NATIVE_VISION           : 模型支持图片/视频 → 当前 agent 直接看（video-analyst 抽帧可辅助）
B TEXT_WITH_VISION_BRIDGE : 模型纯文本，ds-vision 可用 → ffmpeg 抽帧（video-analyst CLI 可用则优先）
                            → mimo-vision.sh（mimo-v2.5）看图 → 按 video-analyst 同名 schema 写回
C TEXT_NO_VISION          : 模型纯文本且 ds-vision 不可用/被拒 → ASR（video-analyst 规格 ASR，
                            否则 ffprobe 元数据）+ 字幕 + 降级分析，报告头标注 vision=degraded
```

- **何时探测**：每次 Phase 2 Reference Analysis 与 Phase 8 Full QA 的入口（进入即探测，结果记入当次工程状态与报告头）。
- **诚实原则**：探测不到（模型不在已知表 / 工具缺失 / 云端通道被用户拒绝）就询问用户确认，**绝不假设能力可用**；Tier C 或模型 UNKNOWN 时，产出物必须带 `vision=degraded` 或"需人工确认"标注。
- **video-analyst 事实**：SKILL.md 规格已装，CLI 脚本未安装（`video-analyst` 命令不可用，2026-08-16 核盘）；探测如实报 `video_analyst_cli=UNINSTALLED_SKILL`，Tier B 下用 ffmpeg 抽帧 + mimo-vision.sh 替代。
- **不是新的 Integration Mode**：视觉探测只是运行时前置检查，仍属既有 `EXTERNAL_SKILL`（ds-vision-skill / video-analyst，含 PROVIDER 语义的 ffmpeg / yt-dlp 组合）范畴，**不新增枚举**；`integration_mode` 仍按 §A 的六种枚举判定。

---

## C. 禁止"Copy Everything"

**硬规则**：

> 不允许为了方便，将第三方 Skill / Repository 整体复制进入 `ZHOU_Videodirector`，除非其官方集成方式本身要求这样做。

**允许的操作**（按优先级）：

```text
install
invoke
adapt
index
link
fetch-on-demand
```

**禁止的操作**：

- 把整个第三方仓库 clone 进 `ZHOU_Videodirector` 目录当作"参考代码库"。
- 把第三方 Skill 全文复制进我们自己的 SKILL.md / modules / workflows。
- 把整个素材 / 音色 / 模型资源库下载到本地做"保险"。

**合规义务**：

- 复用任何外部能力时保留原 License 与 Attribution，写进 asset / 依赖元数据。
- 实验性能力（如 Sony Woosh，Text-to-Audio / Video-to-Audio）必须标注 `EXPERIMENTAL`，使用前额外做 License 检查，不进入默认生产路径。
- 每次接入前查证"该外部能力的官方集成方式"；官方方式要求整体安装的（如正式 Skill），按 EXTERNAL_SKILL 处理，不属于 Copy Everything 违规。

---

## 附：与本项目其他文档的关系

- Integration Mode 枚举与 [reuse-map.md](reuse-map.md) 中每项外部参考的 `integration_mode` 字段一一对应。
- `dependencies.yaml` 保存机器可读的依赖 / 参考清单（name / url / integration_mode / role / status / reuse / do_not / license_notes / required_phase）。
- Before Build Check 的产物由 [constitution.md](constitution.md) 原则 16 与不可妥协清单第 8 条强制约束。
