# Remotion Production Adapter

> Phase-5 Motion Engine（P5-3）实现层 Adapter。对应 Phase-5 Prompt §84（Motion Adapter）、§89-§92（Preview / 报告）、§100 / §104-§105（QA）。
>
> 一句话定位：**ZHOU_Videodirector 控制 Project State（MOTION_SPEC / 决策 / QA / Asset 归一化），官方 Remotion Skill 只做实现层（项目脚手架、React 标记、渲染命令）**。ZHOU 不重新发明 Remotion，也不重新维护 Remotion Best Practices。

---

## 1. 职责边界（§84）

### ZHOU_Videodirector 负责（控制层 / Project State）

- 生成并持有 **MOTION_SPEC**（全字段契约见 [shared contract](#5-motionspec-字段契约)）——这是唯一实现输入，frame 精确计数，不用自然语言时序。
- **Reuse 决策**（`reuse_mode`：`USE_AS_IS | ADAPT | COMPOSE | BUILD_NEW`），查 Registry（`scripts/registry.py find --json`），BUILD_NEW 必须记 `build_reason`。
- **Motion Family 选择**（`MF-*`）：复用优先，只有特殊 Hero 场景才建特殊 Motion（设计 §15-17）。
- **Taste / 技术 QA**（`motion_qa_taste` / `motion_qa_technical`）、**Visual Bible 冲突检查**（`check_visual_bible`）、**Preview First 流程**（`preview_plan`）、**Continuity 合并建议**（`continuity_check`）、**alpha 校验清单**（`alpha_validation_checks`）。
- 实现完成后做 **归一化**：把 Remotion 渲染产物转成 **Project Asset**（`A###`，`schemas/asset.schema.json`），Asset Contract 字段全填，版本化（v1/v2 不覆盖），保留 Remotion 源码。

### 官方 Remotion Skill 负责（实现层）

- 脚手架 / Composition / React 标记：`~/.agents/skills/remotion-create/SKILL.md`
- 渲染 / alpha 透明视频：`~/.agents/skills/remotion-render/SKILL.md` + `~/.agents/skills/remotion-render/transparent-videos.md`
- Best Practices / 排版 / 字幕 / 交互 / Map / 多媒体：`~/.agents/skills/remotion-{best-practices,captions,interactivity,maps,markup,multimedia,saas,upgrade,docs}/SKILL.md`

> **不重新维护 Remotion Best Practices**：任何 Remotion 本身的写法（布局、字幕、性能、交互、渲染参数）一律引用官方 skill，ZHOU 侧只维护「导演决策层」（该动什么、怎么动、为什么）。官方 skill 内容不复制进本仓库（对齐 `docs/reuse-map.md` remotion-official 条目 `do_not: vendor_all_docs_into_repo`）。

## 2. 生产流水线

```
PRODUCTION_REQUEST
      │  (request_id / shot_id / layer_id / route / duration / fps / visual_requirements /
      │   motion_requirements / alpha_required / continuity_group / sync_points ...)
      ▼
modules/production/motion.py::build_motion_spec(request, visual_bible_summary, motion_family)
      │  └─ timing 用 frame 计数（start_frame/end_frame/duration_frames/entry/hold/exit/sync_points）
      ▼
                ┌───────────────────────────────┐
                │  MOTION_SPEC (JSON)           │  ← 唯一实现输入（Project State）
                └───────────────────────────────┘
      │
      ▼
modules/production/motion.py::choose_reuse(needs)
      │  └─ registry.py find --json（remotion-bits / onda / remotion-ui / remocn 组件）
      │  └─ USE_AS_IS / ADAPT / COMPOSE / BUILD_NEW(+build_reason)
      ▼
官方 Remotion Skill（实现层）
      │  remotion-create：npx create-video@latest 脚手架 / Composition
      │  remotion-markup / best-practices：React 标记实现 MOTION_SPEC 语义
      │  remotion-render：npx remotion render（--image-format=png --pixel-format=yuva444p10le
      │                   --codec=prores --prores-profile=4444 支持 alpha，见 transparent-videos.md）
      ▼
PREVIEW First（§89-91）
      │  motion.py::preview_plan(spec) → {asset}_preview.mp4（480p/720p 低清短段）
      │  [用户/导演确认] → 才产出高质量 final
      ▼
motion_qa_technical / motion_qa_taste / alpha 探针（ffmpeg，P5-6）
      ▼
归一化 → Project Asset（asset contract 字段，见 §4）
      │  assets/A###.md + 媒体文件 + Remotion 源码保留
      ▼
Asset Registry（项目 Asset 记忆）
```

## 3. 与 Registry 的关系

- Registry Resource ≠ Project Asset（docs/registry.md §21 / §84-86）：
  - **Registry Resource**：外部目录条目 `{provider}:{type}:{slug}`，跨项目共享，只存元数据。
  - **Project Asset**：项目内生产实体 `A###`（asset.schema.json），有本地路径 / 时间线用法 / 生产状态。
  - 回链：Project Asset 用 `registry_resource_id` 指回 `{provider}:{type}:{slug}`。
- Motion 复用来源（143 条种子索引）：`remotion-bits`（18）、`onda`（17）、`remotion-ui`（15）为 Remotion 组件来源；`remocn` 为 primitive 来源。
- `choose_reuse` 调 `scripts/registry.py find --json <query> --route REMOTION`，用返回的 `fit`（8 因子 score）与 `factors.relevance` 决策：
  - `fit >= 0.90` → `USE_AS_IS`（完全匹配）
  - `fit >= 0.80`（或 `rel >= 0.85 且 fit >= 0.60`）→ `ADAPT`（记 `adapt_notes`）。
    注：registry 8 因子 score 偏保守，无项目风格/缓存上下文时完美相关候选也只到 ~0.71-0.77；
    故对高相关候选（rel≥0.85）放宽 ADAPT 下限到 0.60，保证 ADAPT 可达。
  - 两个现成 primitive 可组合（`fit >= 0.35` 且候选 ≥2）→ `COMPOSE`（记 `components`）
  - relevance ≤ 基线 0.25（route 类型偏置，query 无实质命中）→ `BUILD_NEW` + `build_reason`
  - 其余无方案 → `BUILD_NEW` + `build_reason`（§80 格式，如 `No existing component supports continuous card-to-graph morph`）

## 4. 归一化输出契约（实现完成后转 Project Asset）

实现完成后把渲染产物 + 元数据归一化为 Project Asset（`schemas/asset.schema.json`，asset contract 字段）：

| 字段 | 来源 | 说明 |
|---|---|---|
| `asset_id` | 生产计划 | `A###` |
| `name` / `type` | 生产计划 + MOTION_SPEC.purpose | type 用 asset.schema.json 枚举（FULL_SCENE / MOTION_CLIP / TRANSPARENT_OVERLAY / ANIMATED_TEXT / 3D_ELEMENT / BACKGROUND / PARTICLE_LAYER / TRANSITION_ASSET / INFOGRAPHIC / UI_COMPONENT / DECORATIVE_ELEMENT） |
| `producer` | 固定 | `REMOTION` |
| `purpose` | MOTION_SPEC.purpose | |
| `format` | render_format | alpha 时 `mov`（prores-4444）/ `webm`（vp9）；非 alpha `mp4`（h264） |
| `alpha` | MOTION_SPEC.alpha | 是否带透明通道 |
| `fps` / `duration` | MOTION_SPEC.fps / duration | |
| `resolution` | composition | `{w, h}` |
| `timeline_usage` | shot 引用 | 槽位说明 |
| `replaceable` / `version` | 生产计划 | 版本化，v1/v2/v3 不覆盖旧文件 |
| `license` / `attribution_required` | registry 命中资源 / BUILD_NEW 自产 | |
| `preview` | preview_plan | `{asset}_preview.mp4` 路径 |
| `registry_resource_id` | choose_reuse | 回链（§85-86） |
| `source` | Remotion 源码目录 | **Remotion 源必须保留**（§72 源保留） |
| `status` | production 状态机 | PLANNED → … → COMPLETED / BLOCKED |

## 5. MOTION_SPEC 字段契约

`modules/production/motion.py::build_motion_spec` 输出全字段（Phase-5 Prompt §10）：

```
purpose  duration  fps  composition  elements  timing  motion_character  intensity
easing  spring  stagger  camera  parallax  scale  position  rotation  opacity  blur
shadow  lighting  depth  motion_blur  transition_in  transition_out
audio_sync_points  continuity  alpha  render_format  avoid
```

枚举契约：

- **motion_character（10）**：`restrained soft kinetic cinematic editorial spatial technical organic elastic glitch`（primary 取首 token；列表可含次要描述 token）
- **intensity（4）**：`LOW MEDIUM HIGH HERO`
- **easing（5）**：`linear ease_in ease_out ease_in_out cubic_bezier`
- **reuse_mode（4）**：`USE_AS_IS ADAPT COMPOSE BUILD_NEW`（BUILD_NEW 记 `build_reason`，§80）
- **timing**：frame 计数（§13）——`start_frame / end_frame / duration_frames / entry{start,end,frames} / hold{start,end,frames} / exit{start,end,frames} / sync_points[]`，不用自然语言
- **alpha 相关**（§21）：`alpha_required=true` 时 render_format 必须支持透明（prores-4444 / vp9-webm），并过 `alpha_validation_checks`（真实校验在 render 后由 ffmpeg 探针执行）

## 6. 依赖清单（Phase 5 已批准安装，项目内 npm，放 e2e 项目目录）

| 依赖 | 版本基线（e2e-remotion/package.json） | 用途 | License |
|---|---|---|---|
| remotion | ^4.0.509 | 核心 | MIT |
| @remotion/cli | ^4.0.509 | 脚手架 / render CLI | MIT |
| react / react-dom | ^19.2.8 | 渲染运行时 | MIT |
| @remotion/three | ^4.0.509 | 3D 合成（Hybrid 用） | MIT |
| three | ^0.185.1 | 3D 运行时 | MIT |
| @react-three/fiber | ^9.7.0 | R3F | MIT |
| drei | ^2.2.21 | R3F Helper | MIT |

安装：`npm install`（在 e2e 项目目录执行；不进 skill 仓库源码树）。ffmpeg（已装 8.1.2）用于 render 后 alpha / 分辨率 / 帧数探针（P5-6）。

## 7. Preview 与 QA（§22 / §89-92 / §100 / §104-105）

- **Preview First**（§89-91）：复杂 motion / hero / 昂贵 render → 先 `{asset}_preview.mp4`（480p/720p、短段 ≤5s），导演确认后才出高质量 final；preview 与 final 文件分离（`A018_preview.mp4` vs `A018_v1.mov`）。
- **技术 QA**（§24 / §100 / §104）：render success / frame count / duration / fps / resolution / alpha / text overflow / asset missing / font missing / layout overflow / animation discontinuity / NaN invalid transform / dependency errors —— `motion_qa_technical`。
- **Taste QA**（§25 / §105）：too flashy / too plain / too bouncy / too much camera / meaningless motion / inconsistent easing / excessive hero / motion not serving information —— `motion_qa_taste`。
- **Visual Bible 冲突**（§105）：VB=restrained 而 intensity=HERO（非 hero 场景）→ violation；VB avoid 词命中 motion_character / spring → violation —— `check_visual_bible`。
- **重试上限**（§93-94）：render 失败 3 次（normal fix → targeted fix → alternative approach）→ BLOCKED 报告，不无限循环。

## 8. 相关文件

- 引擎实现：`modules/production/motion.py`
- 共享 Schema（P5-1 并行产出）：`schemas/motion-family.schema.json`（MF-* 族字段）、`schemas/asset.schema.json`、`schemas/visual-bible.schema.json`
- Registry 引擎：`scripts/registry.py`（find --json / detail / preview / fetch）
- 官方 Remotion 能力索引：`docs/reuse-map.md`（remotion-official / remotion-bits / onda / remotion-ui / remocn）
- 生产宪法：`docs/production.md`（P5-1）
