# Router — Shot / Layer Capability Router 参考

> 机器可读契约：`schemas/routing.schema.json`、`schemas/layer.schema.json`
> 状态机：`SHOT_ROUTING` → `LAYER_ROUTING` → `ROUTING_REVIEW`（见 `schemas/state-machine.json`）
> 工作流：`workflows/routing.md`
> 本文档解释 Phase-3 的 Router 定位、12 项因子、六条 Route、Bake / Confidence / Prototype / Override 等规则，供实现（P3-1 引擎、P3-3 模板、P3-4 校验、P3-5 benchmark）与审核对照。

## 1. Router 定位

Phase 3 的唯一目标：让系统回答

> **这个视觉到底应该由谁来做？**

Router 是本阶段核心模块，但**不负责生产**。它只做八个动作：

1. **Analyze**：读取已批准的 Storyboard（Scene / Shot / Layer），分析每个视觉需求。
2. **Decompose**：判断是否需要拆 Layer（仅当存在多个视觉职责 / 多个 Producer / 不同可编辑性 / 不同精度要求时）。
3. **Score**：按 12 项因子对每个目标打分（0.0–1.0）。
4. **Route**：给出 Shot / Layer 的技术路线（六条 Route 之一）。
5. **Explain**：输出可审计的 `decision_summary`（禁止保存私有 Chain-of-Thought）。
6. **Prototype decision**：按置信度决定直荐 / 建议 Prototype / 进入 Concept Exploration。
7. **Approve**：整体 Routing Plan 走 `ROUTING_REVIEW` 审批门（requires_approval: true）。
8. **Persist**：路由记录落盘（`routing/S###.yaml`、`layers/S###.yaml`、`ROUTING_PLAN.md`、`EDITABILITY_PLAN`）。

**明确禁止（属于后续 Phase）**：正式写 Remotion、下载正式模型、生成正式 AI Video、大量搜 Footage、创建正式剪映工程、制作完整音效/音乐、启动 Resource Registry 大规模开发。

## 2. Router 不是"复杂度判断器"

不要实现

```text
简单 → Remotion
复杂 → AI Video
```

这是错误模型。真正判断至少考虑 §3 的 12 项因子，组合使用 rules + weighted heuristics + LLM judgment（Phase-3 §3、§34）。

## 3. 12 项评分因子

每个因子打分 0.0–1.0（值越高需求越强）。表格给出「HIGH 时倾向哪条 Route」与示例。

| # | 因子（schema 键） | 定义 | HIGH 时倾向 Route | 示例 |
|---|---|---|---|---|
| 1 | `structural_precision` | 画面结构是否必须精确可控 | REMOTION / THREE_D | UI、Graph、Timeline、Map、Typography、Chart、Data、Product layout |
| 2 | `photorealism` | 是否需要逼真的现实世界外观 | REAL_FOOTAGE / GENERATIVE_VIDEO / HYBRID | 真实办公室、东京街道、博物馆、森林、真人、自然光照 |
| 3 | `organic_motion` | 自然运动复杂度（难以程序化重建） | REAL_FOOTAGE / GENERATIVE_VIDEO | human gesture、hair、cloth、water、smoke、plants、crowd、animal |
| 4 | `scene_entropy` | 画面中不可规则描述、难以程序化控制的视觉变量数量（制作复杂度指标，非信息论定义） | LOW→REMOTION/THREE_D；HIGH→REAL_FOOTAGE/GENERATIVE_VIDEO | 见 §4 |
| 5 | `text_accuracy` | 是否需要精确文字/数字/label（不应直接生成在 AI Video 内） | REMOTION / JY_NATIVE / HYBRID（AI 背景 + 精确文字层） | precise text、numbers、labels、UI、brand copy |
| 6 | `data_accuracy` | 是否需要精确数据展示 | REMOTION / THREE_D | chart、statistics、map、timeline、scientific data、financial numbers |
| 7 | `revision_requirement` | 内容是否很可能被修改 | REMOTION / JY_NATIVE（不 Bake 进 AI Video） | text、number、UI、product feature、subtitle、timeline |
| 8 | `timing_precision` | 是否需要帧级/beat 级时间对齐 | REMOTION / JY_NATIVE | 第 72 帧数字出现、跟音乐 beat 对齐、三个节点连续出现、跟 VO 精确同步 |
| 9 | `atmosphere_requirement` | 镜头主要价值是氛围/情绪/电影感 | GENERATIVE_VIDEO / REAL_FOOTAGE（权重提升） | mood、lighting、cinematic atmosphere、human feeling、dreamlike |
| 10 | `physical_complexity` | 物理现象复杂度 | 判断 Three.js 是否合理；不合理则 AI / Footage | explosion、fluid、cloth、crowd、destruction、complex machinery |
| 11 | `camera_complexity` | 运镜复杂度 | 简单运镜→REMOTION/THREE_D；复杂实景运镜→AI / Footage | push、orbit、pan、zoom vs handheld、穿越实景、高速跟拍、复杂 Steadicam |
| 12 | `editability_requirement` | 用户之后手动修改该内容的可能性（本系统与普通 Router 的最大区别之一） | JY_NATIVE 或保留独立 Asset；不全部 Bake | subtitle、photo duration、B-roll timing、simple title、music、basic crop |

> 因子以 `schemas/routing.schema.json` 的 `scores` 对象为准（12 项，全必填）。

## 4. Scene Entropy 三级

Scene Entropy 是**制作复杂度指标**，表示画面中不可规则描述、难以程序化控制的视觉变量数量。

| 等级 | 定义/示例 | 倾向 |
|---|---|---|
| **LOW** | solid background、UI、cards、icons、simple diagram、single product | REMOTION / THREE_D |
| **MEDIUM** | stylized room、simple desk、few objects、controlled lighting | 可能 THREE_D / GENERATIVE_VIDEO / HYBRID |
| **HIGH** | Tokyo street、crowd、trees、cars、reflections、wind、signs、complex lighting | REAL_FOOTAGE / GENERATIVE_VIDEO |

## 5. 六条 Route 正式定义

### REMOTION（§17）
- **适合**：UI、Typography、Chart、Data、Map、Timeline、Infographic、SVG、Cards、Icons、2D layout、2.5D、structured particles、motion graphic、precise overlay、controlled typography、deterministic animation。
- **核心特征**：structure、precision、determinism、revision、timing。

### THREE_D（§18）
- **适合**：3D product、chip、machine、server、device、exploded view、3D diagram、spatial UI、orbit、camera move、precise geometry。
- **未来实现栈**：`@remotion/three`、React Three Fiber、Drei、Postprocessing、gltfjsx。

### REAL_FOOTAGE（§19）
- **适合**：real event、historical archive、NASA、news、city、nature、product footage、real human、documentary scene、real-world B-roll。
- **原则**：如果已有高质量真实素材，不要为了"AI"重新生成。

### GENERATIVE_VIDEO（§20）
- **适合**：photoreal scene、high entropy environment、organic motion、cinematic atmosphere、unavailable real scene、imaginary environment、human action、complex natural dynamics。
- **约束**：AI Video 只是 **Asset Producer**，不能默认当 Final Video（精确文字/数据必须走 HYBRID）。

### JY_NATIVE（§21）
- **适合**：normal edit、image、B-roll、subtitle、simple title、Ken Burns、simple zoom、simple pan、simple transform、basic transition、audio placement、simple overlay。
- **核心判断**：是否真的值得启动 Remotion？「剪映 3 个关键帧就能完成」就不要建复杂 Remotion Component。

### HYBRID（§22）
- **适合**：一个 Shot 内存在多个不同类型的视觉需求（如 AI environment + precise typography + 3D object + particles + editable subtitles）。
- **强制**：Shot Route 为 HYBRID 时**必须做 Layer Decomposition**，并记录 `assembly_backend`（JIANYING / REMOTION）。

## 6. 两级路由

```text
Shot Router
↓
Simple enough?
├─ YES → Single Route
└─ NO  → Layer Router（每个 Layer 各自 Route）
```

## 7. Layer 定义与类型

### Production Responsibility Boundary（§27-28，Layer 的正式定义）
Layer 是 **Production Responsibility Boundary**，不是 DOM Layer。只有满足以下之一才值得成为独立 Layer：

- 可能由不同 Producer 完成；
- 使用不同资源；
- 有不同更新周期；
- 有不同编辑方式。

**不要过度 Layer 化**：不要拆成 `background gradient / left shadow / right shadow / icon A / icon B` 这种无意义数据。

### Editability Boundary（§29）
Layer Router 必须主动判断 `Should this remain editable in JianYing?`：

- subtitle → yes（KEEP_EDITABLE）
- B-roll → yes（KEEP_EDITABLE）
- large continuous motion transformation → no（BAKE）
- AI footage → asset-level replaceable（ASSET_REPLACEABLE）
- 3D overlay → asset-level replaceable（ASSET_REPLACEABLE）

### 16 种 Layer role（Phase-3 §25）
`BACKGROUND / FOREGROUND / SUBJECT / TYPOGRAPHY / UI / DATA / 3D_OBJECT / PARTICLE / DECORATION / FOOTAGE / IMAGE / OVERLAY / MASK / LIGHTING / ATMOSPHERE / SUBTITLE`

Layer ID 格式：`S###-L##`（如 `S018-L01`；layer.schema 的 `id` 字段仍为 `L###`，文件级 `S###-L##` 命名用于 layers/S###.yaml 内的可读标识）。

音频暂时由 **Shot Audio 体系**管理，不参与 Layer 路由。

## 8. Bake Policy（§29-30）

| 值 | 含义 | 示例 |
|---|---|---|
| `BAKE` | 整体渲染，时间线内无需再改 | complex continuous Remotion scene |
| `KEEP_EDITABLE` | 保持时间线可调 | subtitle、image、B-roll、simple text、music |
| `ASSET_REPLACEABLE` | 内部 Bake，但整个 Asset 可在时间线上替换 | Remotion transparent overlay、AI video、3D render |

Layer 与 Routing 记录都应输出 `bake_policy`（见 `schemas/layer.schema.json`、`schemas/routing.schema.json`）。

## 9. 评分、Confidence 与三档行为（§33、§39-42）

置信度取值 0.0–1.0：

| 档位 | 范围 | 行为 |
|---|---|---|
| **HIGH CONFIDENCE** | >= 0.80 | 直接推荐 Route（直荐）；Production 仍受后续 Approval Gate 控制 |
| **MEDIUM CONFIDENCE** | 0.55–0.79 | `prototype_required: true`，进入 Prototype Recommended（5 秒测试 / 单帧 / keyframe concept / 廉价 3D preview / AI still concept），不马上进入重生产 |
| **LOW CONFIDENCE** | < 0.55 | 不要瞎选，进入 Concept Exploration Required（收集 references、创建 keyframes、对比两条生产路线） |

不要输出私有 CoT，只保存可审计的 `decision_summary`（≤300 字符）。

## 10. Prototype 类型（§43）

| 类型 | 何时用 |
|---|---|
| `STATIC_KEYFRAME` | 用静态关键帧验证构图/节奏假设，成本最低 |
| `REMOTION_MICRO_PROTOTYPE` | 验证程序化动效/时序/结构是否成立（极小 Remotion 片段） |
| `THREE_D_PREVIS` | 验证 3D 几何/相机/爆炸图是否可行（廉价预演） |
| `AI_IMAGE_CONCEPT` | 验证 AI 视觉概念/氛围（单张概念图） |
| `AI_VIDEO_TEST` | 验证 AI 视频生成效果与一致性（短视频测试） |
| `JY_TIMELINE_TEST` | 验证剪映时间线内可编辑性/剪辑节奏（剪映时间线测试） |

Phase 3 不必真正实现全部 Prototype，但路由输出必须给出 `prototype_required` / `prototype_type` / `prototype_goal`。

## 11. 升级 / 降级规则（§64-66）

- **Route Escalation**：若 JY_NATIVE 复杂度超过 manual-edit-friendly threshold（如为了模拟复杂曲线要塞几十/几百关键帧），应升级 `JY_NATIVE → REMOTION`。
- **Route De-escalation**：若 Storyboard 写了 REMOTION，但实际只是 photo slow zoom，应建议 `REMOTION → JY_NATIVE`，避免过度工程化。
- **Motion Path**：复杂曲线先判断 `JY_NATIVE + generated keyframes` 是否仍合理；不合理才升级。

## 12. Style / Production Mode / Visual Bible / Audio 集成原则（§44-47、§58-59）

- Router **不能被 Style 控死**：Style（如 Reality × Paper Editorial）决定视觉语言，Router 决定如何以合理技术实现它；个别镜头仍可能是 REAL_FOOTAGE。
- Router **不能被 Production Mode 控死**：Product Short 不意味着全部 Remotion，Explainer 不意味着全部剪映。Production Mode 只是 **Prior**（可倾向，不是硬规则）。
- **Visual Bible Integration**：必须读取 `VISUAL_BIBLE.md`（如 Minimal Spatial Tech 可能提高 REMOTION / THREE_D 候选概率，但非硬规则）。
- **Audio Direction Integration**：读取 audio sync requirement（如 visual must hit beat at exact frame → 提高 `timing_precision`，影响 Route）。

## 13. ROUTING_CONFLICT 协议（§48-49）

Router 以 Phase-2 Storyboard 为输入，**不能重新导演一遍**。若发现 Storyboard idea technically unreasonable：

- **不要偷偷改 Storyboard**；
- 输出 `ROUTING_CONFLICT`，字段格式：

```text
Shot
Problem
Why
Suggested adaptation
Impact on creative
```

- 等待用户确认。

**Router 不拥有 Creative Authority**：可以说"这个设计很贵"，不能说"那我换成另外一个创意"。Creative 修改必须回到对应 Approval。

## 14. User Override 与 Route Source（§71-73）

- 用户可直接指定 Route（如"这个镜头我不要 AI，给我用 3D"），Router 必须允许 manual override。
- 每个 Routing Decision 记录 `route_source`（`schemas/routing.schema.json`）：

```text
AUTO                引擎自动判定
USER_OVERRIDE       用户手动指定
DIRECTOR_OVERRIDE   导演/主 Agent 指定
PROTOTYPE_RESULT    由原型验证结果决定
```

- **Supersedes**：用户后来修改 Route 时，旧 Route **不删除**，记录 `supersedes`（指向被替代的旧 route 记录），并更新 Shot Current State，避免下一轮又自动改回来。

## 15. 输出文件契约（§50-57）

| 产物 | 内容 |
|---|---|
| `ROUTING_PLAN.md` | Executive Summary、Route Distribution、Hybrid Shots、High-risk Shots、Prototype-required Shots、Editability Strategy、Continuity Groups、Potential Production Bottlenecks、User Decisions Required |
| `routing/S###.yaml` | 每 Shot 一条：`shot_id / route / confidence / reason / scores(12) / layer_decomposition_required / prototype_required`（§53） |
| `layers/S###.yaml` | 每 Shot 的 Layer 数组：`id(S###-L##) / role / route / bake_policy`（§54） |
| `EDITABILITY_PLAN` | 覆盖 footage、subtitles、titles、motion assets、AI clips、music、SFX、images，逐项标记 `KEEP_EDITABLE / ASSET_REPLACEABLE / BAKED`（§57） |
| `assembly_backend` | HYBRID Shot 额外记录 `JIANYING` / `REMOTION`（§55）；长视频优先 JianYing Assembly，复杂连续 Motion 可由 Remotion Assembly |

**Remotion Asset Boundary（§56）**：必须决定"Remotion 一次渲染一个 Asset 是什么"——有强 Motion Continuity 的内容应渲染为一个 Asset（如 `S018-A01 memory-card-transformation.mov`），而不是拆成 card.mov / arrow.mov / text.mov / node.mov。

**Motion Continuity（§31）**：接入 Phase-1 `continuity_group`；不能随意切断的 Motion Sequence（card → expands → becomes graph → graph becomes 3D space）应为同一 continuity group，并倾向 REMOTION 作为完整 Asset。

**Hard Constraints（§36）**：critical exact text / critical data 不能由生成式视频独占（→ HYBRID 或 REMOTION）；字幕必须 KEEP_EDITABLE。

**禁止输出私有 CoT**：只保存 `decision_summary`（§38）。
