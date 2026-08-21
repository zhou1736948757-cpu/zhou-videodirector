# ZHOU_Videodirector — Production 宪法（Production Constitution）

本文件是 `ZHOU_Videodirector` Phase 5（Motion / 3D / Sound Production Engine）的宪法级参考文档，回答「生产系统是什么、三引擎边界在哪、统一生产管线怎么走、规则是什么」。实现细节以三个 schema、`modules/production/` 与三个引擎为准。

- 来源：Phase-5 Prompt §0-§118（重点 §3-§6 / §11-§21 / §30-§34 / §44-§48 / §53-§58 / §70-§82 / §88-§99 / §100-§106 / §115-§118），总设计 v0.2 相关章节，[registry.md](registry.md)（Phase 4 宪法，衔接）。
- 配套：机器可读契约 `schemas/production-request.schema.json`、`schemas/motion-family.schema.json`、`schemas/sfx-family.schema.json`、`schemas/asset.schema.json`（Phase 5 增补）；引擎编排 `modules/production/`（**P5-2 将建**：planner.py / manifest.py）；生产工作流 [asset-production.md](../workflows/asset-production.md)。
- 相关政策：顶层宪法见 [constitution.md](constitution.md)（原则 2 Reuse Before Build / 原则 10-11 可编辑交付 / 原则 14 审批 / 原则 15 渐进披露 / 原则 16 Before Build Check）；Registry 见 [registry.md](registry.md)；路由见 [router.md](router.md)。

---

## 1. 定位：三个 Production Engine + 统一生产管线（§3）

Phase 5 不是"为每个资产写一段脚本"，而是建立**统一生产管线**与**三个 Production Engine**：

```text
PRODUCTION_REQUEST
        │
        ▼
Production Planner（modules/production/planner.py）
        │  状态机 11 态 / spec hash / 依赖跟踪 / Render Profile / 冲突协议
        ▼
MOTION ENGINE ── REMOTION（Motion / 2D / 2.5D / Typography / UI / Infographic / Particle）
THREE_D ENGINE ── R3F + Drei（3D 模型 / Camera / 空间结构）
SOUND ENGINE ─── SOUND / FLUIDSYNTH / LIBRARY_MUSIC（SFX / 环境音 / 程序化音乐 / 库音乐）
        │
        ▼
Asset(s)（asset.schema.json，A###）
        │
        ▼
Asset Validation（技术 + 契约校验）→ 项目 Asset Registry（Asset Memory）

Timeline Hint（§115）→ 交给 Phase 7 装配（引擎不碰时间线，§88）
```

**唯一目标**：让「这个已批准设计怎么变成可复用、可校验、可版本化的 Asset」这件事被**可预测、可审计、可增量**地完成，而不是每个资产重新发明生产方式。

## 2. 只吃已批准设计（§5）

生产管线的**唯一输入**是已批准设计，禁止引擎自己改设计：

```text
Approved Storyboard（Scene / Shot / Layer）
+ Approved Routing（route / bake_policy）
+ Approved Resource Selection（resource_id）
        ↓
Production Planner 派生 PRODUCTION_REQUEST
```

- 引擎只对「已批准内容」的实现方式做技术选择，不改变叙事、风格、节奏、声音方向。
- 设计在技术层面不可实现时，**禁止偷偷改**，必须走 PRODUCTION_CONFLICT 协议（见 §3）。
- 违反本条 = 违反顶层宪法原则 1（Director Before Engineer）与原则 13（Main Agent Owns Final Direction）。

## 3. PRODUCTION_CONFLICT 协议（字段格式）

当「已批准设计」与「技术现实」冲突（如设计要求的动效无法在目标帧率下渲染、资源 license 不满足商用、alpha 通道无法实现），引擎必须输出冲突报告并停在该请求上，不得自裁：

```text
PRODUCTION_CONFLICT
- request_id:     PR-###（冲突所在生产请求）
- conflict_type:  DESIGN_UNFEASIBLE | RENDER_LIMIT | LICENSE_ISSUE | DEPENDENCY_MISSING | OTHER
- request:        冲突点描述（引用已批准设计的具体条目）
- problem:        技术问题（事实与证据）
- technical_reason: 为什么现有技术栈无法实现
- visual_impact:  若按技术现实妥协，视觉/叙事影响是什么
- alternatives:   可选替代方案（2-4 个，含各自影响）
- approval_required: true
```

- 输出后该请求进入 `WAITING_APPROVAL`，等主 Agent + 用户裁决（改设计 / 换方案 / 接受妥协）。
- 禁止：为迎合引擎能力静默改写已批准设计；禁止以冲突为借口直接 BUILD_NEW。

## 4. Reuse → Adapt → Compose → Build Last（§6 / §80-82）

生产每一条 Asset 前必须过 Registry（Phase 4），且按固定优先级决策：

| reuse_mode | 判据（§80-82） | 产出要求 |
|---|---|---|
| `USE_AS_IS` | Registry 命中 ≥90% fit | 直接引用 resource_id，不本地复制（fetch-on-demand） |
| `ADAPT` | fit 80-90%，或小改即可 | 记录改动面（改了参数 / 样式 / 时长 / 音色） |
| `COMPOSE` | 现有资源 A + B 可组合满足（A+B 可组合→COMPOSE） | 记录组合边界（如何拼、每部分来源） |
| `BUILD_NEW` | 以上均无可行方案 | **必须记 build_reason**：why existing failed（哪些候选、为何不行），禁止无理由自建 |

- 判据以确定性匹配为主（fit 分数、候选列表、失败原因），不让引擎"感觉该自建"。
- 与 Phase 4 的 `reuse_recommendation`（resource-selection.schema.json）对齐：生产请求的 `selected_resources[]` 来自已批准 selection。
- BUILD_NEW 后新增能力要回流 Registry 学习（registry.md §15 Resource Learning），让系统越来越好用。

## 5. 三大引擎职责边界表

| 引擎 | 载体 | 负责 | 资产类型（asset.type） | producer |
|---|---|---|---|---|
| **Motion Engine** | Remotion + 官方 Skills + Onda / RemotionUI / Remotion Bits / shotcraft（KNOWLEDGE_ADAPTER / PROVIDER） | Motion Graphics / Typography / UI 动画 / 信息图 / 图表 / 地图 / Particle / Shader / 复杂转场 / 2.5D | FULL_SCENE / MOTION_CLIP / TRANSPARENT_OVERLAY / ANIMATED_TEXT / BACKGROUND / PARTICLE_LAYER / TRANSITION_ASSET / INFOGRAPHIC / UI_COMPONENT / DECORATIVE_ELEMENT（十类，§30） | `REMOTION` |
| **3D Engine** | React Three Fiber + Drei + gltfjsx + @remotion/three；模型来自 3D Registry（Poly Haven 等） | 产品模型 / 芯片 / 机器 / 空间 / 爆炸图 / Camera orbit / 3D UI / 结构可视化（§23 / §38） | 3D_ELEMENT（可含 FULL_SCENE / TRANSPARENT_OVERLAY 组合） | `THREE_D` |
| **Sound Engine — SFX/环境音** | SFX Registry（@remotion/sfx / Freesound / Mixkit / Kenney / 项目自定义） | UI 音效 / 动效音 / Impact / Riser / Whoosh / Ambience / Silence（Level 1-3，§11） | SFX / AMBIENCE / VOICEOVER（外部提供时采购） | `SOUND` |
| **Sound Engine — 程序化音乐** | MIDI Composer + FluidSynth + SoundFont（GeneralUser-GS 等） | Intro / Outro / Logo Sting / Chapter Sting / 短 Motif / Minimal Bed / Shot-sync music（§15 / §53-57） | MUSIC（SoundFont 本体为 SOUNDFONT） | `FLUIDSYNTH` |
| **Sound Engine — 库音乐** | Music Registry（Mixkit / Openverse / FMA / CC0 集合） | 长片 Music Bed（长片 = Library bed + Stings + Motif，不整曲 procedural） | MUSIC | `LIBRARY_MUSIC` |

- **边界铁律**：Motion Engine 不做 3D（3D 归 THREE_D，除非 2.5D 动效合成）；Sound Engine 不做画面；三引擎都**不写时间线**（§88）。
- **范围外**（本 Phase 不碰，§119）：Generative Video 生产、Footage 大搜索、剪映时间线构建、Final Mix 混音。产出一律是 Asset + Timeline Hint。

## 6. 统一生产状态机（11 态）

每条 PRODUCTION_REQUEST 的状态推进：

```text
PLANNED → WAITING_APPROVAL → READY → IN_PROGRESS → PREVIEW_READY → RENDERING → VALIDATING → COMPLETED
   │            │                                            │                 │
   │            └──────── approval reject → REVISION_REQUESTED ┘                 ├─ FAILED（可重试，§11）
   └────────────────────────── 失败 3 次 → BLOCKED（§11）                        └─ 校验不通过 → REVISION_REQUESTED
```

| 状态 | 含义 |
|---|---|
| PLANNED | 已排期，尚未开工 |
| WAITING_APPROVAL | 等待 Execution Approval / 冲突裁决 |
| READY | 已批准，可执行 |
| IN_PROGRESS | 引擎执行中（写代码 / 拼装 / 生成） |
| PREVIEW_READY | 低清预览已产出，等待确认（§9） |
| REVISION_REQUESTED | 预览/QA 被要求修改 |
| RENDERING | 高质量渲染中（quality_target 档） |
| VALIDATING | 校验中（技术 QA + alpha + spec hash） |
| COMPLETED | 产出落地为 Asset，回填 Asset Memory |
| FAILED | 单次失败，可重试 |
| BLOCKED | 已达重试上限 / 冲突未裁决，需人介入 |

## 7. Render Profile 4 级（§99）

所有渲染按档位执行，**Phase 5 最高到 HIGH**：

| 档位 | 分辨率 | 用途 |
|---|---|---|
| `PREVIEW` | 720p | Preview First 确认（§9） |
| `STANDARD` | 1080p | 常规产出 |
| `HIGH` | 项目分辨率 | 交付级画面（Phase 5 上限） |
| `FINAL` | 交付级 | **Phase 5 不使用**，留给后续 Phase |

- `quality_target` 由 Planner 按请求设置；**FINAL 档在 Phase 5 一律不允许**（即使请求里出现也回落 HIGH 并记说明）。
- preview 与 final 文件分离命名：`A018_preview.mp4` vs `A018_v1.mov`，禁止覆盖。

## 8. 质量决策：不默认最高质量（§30-31）

- **不默认 8K/4K 一定更好**：2K/4K/8K、高复杂度、高精度渲染必须按 shot 的实际需求推荐，并经 Approval Gate。
- 默认走 **STANDARD / HIGH**，HERO 场景才申请更高档。
- 质量与可编辑性冲突时（视觉质量相近），**优先可编辑方案**（宪法原则 10）：能 KEEP_EDITABLE 的 Asset 不默认 BAKE。
- `editability_policy` 与 routing.bake_policy 保持一致；BAKE 必须记录理由。

## 9. Preview First（§89-91）

复杂 motion / hero 3D / 昂贵渲染 / 定制音乐，一律先低清确认再高质量产出：

1. 引擎产出低清 preview（720p、关键段落即可，不必整段）；
2. 预览与最终文件分离存储（`preview_path`）；
3. 用户确认 → 继续高质量产出；被否 → `REVISION_REQUESTED` 并记录修改点；
4. preview 不满足验收时，**禁止直接进入 RENDERING**。

`preview_required=true` 的请求必须走到 `PREVIEW_READY` 才能进 `RENDERING`。

## 10. Motion Family：项目统一动效语言（§15-17）

- 一个项目在 Style 确认后建立少量 **Motion Family**（`schemas/motion-family.schema.json`，id 形如 `MF-MINIMAL-SPATIAL-01`）。
- 每个 MOTION_SPEC 引用一个 family id，只做局部参数化（时长 / 文本 / 具体元素），**禁止全独立设计**每个资产的动效语言。
- family 定义：character（10 枚举可多选）/ intensity（LOW/MEDIUM/HIGH/HERO）/ entry_motion / exit_motion / easing（linear/ease/cubic_bezier/spring/custom）/ spring / stagger / camera / parallax / blur_policy / motion_blur_policy / hero_variants / avoid。
- **Hero Effect 只来自 `hero_variants`**，且只出现在 Payoff / Climax 等少数位置（宪法原则 5、7）。
- intensity 三级：LOW=大量微动 / MEDIUM=叙事动效 / HIGH=显眼效果；"大量精细效果、少量显眼效果"（§36）。
- 跨 Shot 连续段落（同一 continuity_group）必须引用**同一 family**，保证视觉连续（§18-19）。

## 11. SFX Family：项目统一音效语言（§45-46）

- 每个项目建立少量 **SFX Family**（`schemas/sfx-family.schema.json`，id 形如 `SFXF-UI-CLICK-01`），统一 click / confirm / error / transition / impact / hero。
- 每个 SFX_SPEC 引用 family id 并做局部参数化；**禁止每个资产各做一套音效**。
- 三级声音（§11）：Level 1 Invisible Audio（click / tick / micro whoosh / ambience，大量）；Level 2 Narrative Sound（card expansion / map movement / transition）；Level 3 Hero Sound（bass hit / logo sting / climax，极少量）。
- family 定义 character / frequency_profile / loudness_target（供 Sound QA 响度校验）；avoid 清单防廉价感。
- **Every important visual action should receive intentional audio consideration**（宪法原则 6）；声音由 AUDIO_DIRECTION 主导，SFX Family 是其执行层。

## 12. Continuity Group 生产（§18-19）

- 连续运动（如 button → expand → card → node → camera transition）属于同一 `continuity_group`：**一起 Render，不切碎**。不能为了剪映可编辑性硬拆开。
- 同 continuity_group 的多个 PRODUCTION_REQUEST 共享同一 composition / 同一 seed / 同一 family，保证接缝连续。
- continuity_group 为空 = 该资产是独立单元，可单独生产。

## 13. Transparent / Alpha 校验（§20-21）

- `alpha_required=true` 的请求（TRANSPARENT_OVERLAY / 3D_ELEMENT 等），产出 Asset 必须**真带 alpha 通道**，不能是黑底。
- 校验：读取输出文件的通道信息，确认存在 alpha 且边缘干净；透明区域无脏边 / 无错误噪点。
- 不满足即 `REVISION_REQUESTED`，禁止带病进入时间线。
- 格式：优先 mov（ProRes 4444 / 同类支持 alpha 的编码）；渲染参数里 alpha 配置必须显式。

## 14. 资产契约 + 版本化 + 源保留（§70-73）

每个产出的 Asset 必须写满 **Asset Contract**（asset.schema.json）并落 **Asset Memory**（`<project>/assets/A###.md`）：

```text
asset_id / name / type / purpose / producer / request_id / reuse_mode / build_reason
registry_resources[] / local_path / preview_path / format / resolution / fps / duration
alpha / editability / version / license / license_url / attribution_required / timeline_usage
timeline_hint / created_at / modified_at / status
```

- **版本化**：同一 Asset 的 v1/v2/v3 文件并存，**不覆盖旧版本**；`version` 递增；Asset Memory 记录版本历史与变化原因。
- **源保留**：Remotion 源码 / 3D 场景源码 / MIDI + SoundFont 源必须保留在项目内（`remotion/` / `3d/` / `audio/`），保证未来可重渲染、可修改（宪法原则 11 Human Must Be Able to Take Over）。
- **License**：沿用 registry.md §9 政策——UNKNOWN 不猜测、商用过滤、署名记录、license_snapshot 落盘；asset 的 license 必须可追溯。
- **替换性**：`editability=ASSET_REPLACEABLE` 或 `BAKE` 的资产仍可整体替换；Asset Memory 记录 render 设置与 replaceability。

## 15. 增量生产 + spec hash + 依赖跟踪（§77-79）

- **增量生产**：只有 spec 变化才重新生产对应 Asset，**改 A018 只产 A018**，不整段重跑。
- **spec hash**：planner 为每条请求的 spec 计算哈希（输入 = 设计引用 + 资源引用 + 参数 + 版本）。spec 未变且 Asset 已 COMPLETED → 直接复用，跳过生产。
- **dirty detection**：依赖链上任一节点变化 → 下游标记 dirty → 重新校验/重产受影响资产。
- **依赖跟踪**：`dependencies[]`（type + target_id）记录请求间依赖（asset / request / resource）；依赖未完成，请求停在 `PLANNED` 或 `WAITING_APPROVAL`。

## 16. 重试规则（§93-94）

单条请求的失败处理按固定路径，**3 次即停**：

```text
第 1 次失败 → normal fix（修明显问题，重试）
第 2 次失败 → targeted fix（定位根因，针对性修复）
第 3 次失败 → alternative approach（换实现路径，如换 easing/换资源/换渲染参数）
仍失败 → BLOCKED（报告，禁止无限循环）
```

- 每次失败记录：失败阶段（IN_PROGRESS / RENDERING / VALIDATING）、错误证据、尝试的修复、结果。
- `FAILED` 状态允许重试；`BLOCKED` 必须由主 Agent + 用户裁决（改设计 / 降档 / 换方案 / 升级到 pro-repair 兜底）。
- **禁止**：同根因无脑重试超过 3 次；禁止用"换一个随机参数再渲染"赌概率。

## 17. 确定性（§33-34）

- 3D 动画 **frame-driven**（按帧号求值，禁止依赖实时时钟 / requestAnimationFrame 累计时间）。
- particles / noise / 随机散布**必须 seeded**：同一 spec + 同一 seed 重复 render 结果一致（渲染可复现、可增量、QA 可对帧）。
- seed 记录在 spec 中；同一 continuity_group 共享 seed 链。
- 引擎生成代码 / MIDI 事件同样要求确定性（给定输入产出相同事件序列）。

## 18. QA 三类（§100-106）

产出 Asset 在 VALIDATING 阶段过三类 QA（不默认只查"跑没跑通"）：

| QA 类 | 校验内容 | 通过标准 |
|---|---|---|
| **Technical QA** | 文件可读、格式/分辨率/fps/时长符合 spec、alpha 通道存在、spec hash 匹配、渲染参数正确、无截断/花屏 | 全部通过 |
| **Taste QA** | 动效节奏、easing、spring 是否自然；SFX 是否过度 / 刺耳 / 廉价；是否符合 family 语言与 intensity 档位 | 无 template-slop 特征（对照 taste-skill 思路） |
| **Design-Bible QA** | 对照 **VISUAL_BIBLE**（风格 / 运动性格 / 相机语言 / 色彩 / 排版）与 **AUDIO_DIRECTION**（响度 / 音色 / 同步）逐条核对 | 与已批准设计一致 |

- QA 失败 → `REVISION_REQUESTED` + 具体违反条目；修改后重新 VALIDATING。
- QA 报告可审计，引用 spec 与 Bible 的对应条目；禁止"感觉可以就通过"。
- Phase 8 还有 Editorial QA / Sound QA（成片级），本 Phase 只做资产级三类 QA。

## 19. 依赖安装审批（§95-97）

本 Phase 需要的任何新依赖（remotion npm 包、@remotion/three + three + R3F、FluidSynth、GeneralUser-GS SoundFont 等）都必须先走审批：

```text
What（装什么）+ Source（来源）+ Size（大小）+ Why（为什么）
+ License（许可证）+ Alternatives（替代方案）→ 用户批准 → 安装
```

- 未经批准禁止 `npm install` / `brew install` / 下载 SoundFont。
- 依赖缺失时不伪造结果：FluidSynth 缺席 → 输出 `DEPENDENCY_MISSING` 报告（PRODUCTION_CONFLICT，conflict_type=DEPENDENCY_MISSING），MIDI 事件照常生成但 WAV 渲染留待安装后。
- 安装属于高影响动作，适用 Execution Approval（宪法原则 14）；具体清单见 Phase-5 PLAN.md 批准表。

## 20. Timeline Hint：非硬编码（§115-116）

- 引擎产出 `timeline_hint`（asset.schema.json）：preferred_start / preferred_duration / track_hint / blend_hint / audio_sync_point。
- **它是"提示"，不是"写入"**：时间线由 Phase 7 装配器决定；Phase 5 的引擎绝不直接改时间线。
- hint 基于已批准设计推导（如 storyboard 的 start_time、AUDIO_MAP 的同步点），语义可解释。

## 21. 引擎不碰时间线（§88）

- Phase 5 引擎的输出边界 = **Asset + Timeline Hint**。
- 禁止任何引擎直接写剪映草稿 / 改时间线 / 决定装配顺序（那是 Phase 7 pyJianYingDraft 的活）。
- 装配冲突（hint 与实际装配不一致）由 Phase 7 负责协调，Phase 5 不提前处理。

## 22. 生产请求 ↔ 资产回链（§4 / §77）

- 生产请求 `request_id`（`PR-###`）→ 产出 asset 回填 `asset.request_id`。
- asset 回链已选资源：`registry_resources[]`（resource_id `{provider}:{type}:{slug}`）→ registry.md §85-86。
- 一条 selection（asset_id 回链）→ 生产请求 → Asset 全链可追溯：从"已批准设计"到"已落地资产"每一步都有记录。

## 23. 生产管线与其他 Phase 的衔接

| 上游（Phase 3/4） | 本 Phase 5 | 下游（Phase 6/7） |
|---|---|---|
| Routing（route / bake_policy） | PRODUCTION_REQUEST 派生 | Asset Package |
| Resource Selection（resource_id） | Reuse / Adapt / Compose / Build | pyJianYingDraft 装配（吃 Asset + Timeline Hint） |
| VISUAL_BIBLE / AUDIO_DIRECTION | Motion/SFX Family + QA Bible 校验 | 剪映草稿 |

- 状态推进衔接 [state-machine.md](state-machine.md)：`ASSET_ACQUISITION → ASSET_PRODUCTION → TIMELINE_BUILD`；本 Phase 覆盖 ASSET_PRODUCTION 内部实现。
- Phase 5 不触碰 `TIMELINE_BUILD` 及之后的状态。

## 24. 禁止项（§119）与范围边界

本 Phase 明确**不实现 / 不调用**：

1. Generative Video 生产（AI Video Prompt 组装属 Phase 6）；
2. Footage 大搜索与采购；
3. 剪映时间线构建（pyJianYingDraft 装配，Phase 7）；
4. Final Mix / 成片混音；
5. 8K / FINAL 档渲染（§7）；
6. 未批准的依赖安装（§19）。

一切产出以 Asset + Timeline Hint 为边界；超出边界即视为流程错误。

---

## 附：本文档与其它文档的引用关系

- `schemas/production-request.schema.json`：生产请求（PR-###），Planner 输入契约。
- `schemas/motion-family.schema.json` / `schemas/sfx-family.schema.json`：项目统一运动 / 音效语言。
- `schemas/asset.schema.json`：Phase 5 增补 producer 枚举 + request_id / editability / reuse_mode / registry_resources / preview_path / build_reason / timeline_hint（全部 optional，不破坏 Phase 1 兼容）。
- `modules/production/`（P5-2 将建）：planner.py（状态机 11 态 / 冲突协议 / Render Profile / reuse 决策）+ manifest.py（PRODUCTION_MANIFEST / spec hash / dirty detection / 依赖跟踪）。
- `docs/registry.md`：Registry 检索、family 复用、license 政策、reuse_recommendation（Phase 4 宪法）。
- `docs/constitution.md`：顶层宪法原则（Reuse Before Build / 可编辑交付 / 审批 / Before Build Check）。
- `workflows/asset-production.md`：ASSET_ACQUISITION / ASSET_PRODUCTION 阶段工作流。
