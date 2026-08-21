---
workflow_id: WF-005
name: 声音方向
stage_ids: [SOUND_DIRECTION, AUDIO_DIRECTION_REVIEW]
requires_approval: [AUDIO_DIRECTION_REVIEW]
phase2_status: implemented
---

# 声音方向（Sound Direction）

## 目标
把声音设计提升到与视觉同等地位（Constitution #6：**Important Actions Receive Intentional Audio Treatment**）。在设计阶段确定完整的 Music / SFX / VO / Ambience / Sonic Motif 声音系统，输出 `AUDIO_DIRECTION.md`。

> **Not "BGM only" 强规则（Phase-2 §41）**：声音不是"最后挂一首歌"。没有完整的 Music / SFX / Voice-over / Ambience / Sonic Motif 设计，本阶段不算完成；只给 BGM 的方向不接受，会被 `AUDIO_DIRECTION_REVIEW` 打回。

## 触发时机
`VISUAL_BIBLE_REVIEW` 已批准后触发。

## 输入
- `<project>/PROJECT_STATE.md`、`<project>/PROJECT_BRIEF.md`
- `<project>/CREATIVE_DIRECTION.md`
- `<project>/VISUAL_BIBLE.md`（已 Approval）— 声音必须与视觉语言对应（Motion Character → Motion Sound、Transition → Riser、Hero Effect → Hero Sound）
- `<project>/references/REFERENCE_ANALYSIS.md`（**Audio Layer**：Music density / SFX frequency / Impact / Whoosh / UI sounds / Ambience / Transition / Ducking / Silence）
- `<project>/STORY_BEAT_MAP.md`（如已完成 — 章节、Hook / Payoff 位置用于能量曲线与 Hero Sound 定位；未完成则以 Creative + Visual Bible 为准）

## 输出（项目文件）
- `<project>/AUDIO_DIRECTION.md` — 按模板 `templates/audio-direction.md` 填充；覆盖 schema `schemas/audio-direction.schema.json` 全部 17 个顶层字段 + 派生结构（Sound Philosophy / Mood-Energy Curve / Impact-Riser Policy / Foley / Procedural Music 用法 / 三级 Sound Design 应用）
- （未来）`AUDIO_MAP.md` 时间轴声音表（模板 `templates/audio-map.md`，v0.2 §56，Storyboard 后生成）

## 执行步骤
1. 读取输入：Visual Bible（已 Approval）确定视觉语言；Reference Report（Audio Layer）提取声音规律（学习规律，不逐镜复制）。
2. 确定 **Music Route**（见下"Music Route 决定逻辑"），只推荐 1 个主路线。
3. 按模板填写：Sound Philosophy → Music Direction/Strategy → Mood-Energy Curve → BPM → Instrumentation → VO/Ducking → SFX/UI/Motion/Ambience/Foley → Impact/Riser/Hero → Silence → Sonic Motif → Avoid → References → Procedural 占位 → 三级 Sound Design 应用。
4. 三层声音设计（§45）：Level 1 Invisible Audio（大量，贡献高级感）→ Level 2 Narrative Sound（按叙事）→ Level 3 Hero Sound（少量，全片 Hero Sound 次数需显式设定上限）。
5. 声明 **Procedural Music 占位**：哪些拍点（Logo Sting / Chapter Transitions / Short Motif / Shot-sync）走 `PROCEDURAL_MUSIC`，但 **Phase 2 不实现 FluidSynth / SoundFont / MIDI 渲染**（Phase 5 接入）。
6. 在 `DECISIONS.md` 记录决策（D-xxx），推进到 `AUDIO_DIRECTION_REVIEW`（waiting_user）。

## Music Route 决定逻辑
按场景类型推荐 1 个主路线（不必 4 个都讨论）：

| 场景类型（production_mode） | 推荐 Route | 理由 |
|---|---|---|
| Product / Tech Short（30s-2min，Remotion/UI 主导） | `LIBRARY_MUSIC` | 篇幅短、节奏可控，音乐库效率最高；Procedural 可留给 Logo Sting |
| Editorial / Explainer（5-10min，Footage 主导） | `LIBRARY_MUSIC` 或 `HYBRID_MUSIC` | 长片信息密度高，库乐垫底 + 少量 Procedural 转场/Sting |
| Documentary / Archive | `LIBRARY_MUSIC` | 档案感、克制，避免花哨合成 |
| 品牌片 / Logo / 高定制短片 | `PROCEDURAL_MUSIC`（占位） | 需要 shot-sync 的节拍贴合；Phase 2 只声明，Phase 5 实现 |
| 需要 AI 生成实验性声音 | `GENERATIVE_MUSIC`（EXPERIMENTAL） | 仅在有明确需求且 License 复核后考虑 |
| 无法判断 | `UNDECIDED` | 记录待定原因，Review 时让用户决定 |

> 无论选哪个 Route，Music 的 Mood / BPM / Instrumentation / Narration-friendly 属性都必须在本阶段写明（Registry 检索依赖这些元数据，Phase 4 落地）。

## Procedural Music 占位规则
- 本阶段**只声明**：哪些拍点走 Procedural（Logo Sting / Chapter Transitions / Short Motif / Shot-sync）。
- **禁止**：Phase 2 实现 FluidSynth / SoundFont / MIDI 事件生成 / WAV 渲染；也禁止下载 SoundFont。
- Phase 5 接 `adapters/fluidsynth/`（MIDI Composer → FluidSynth → SoundFont → WAV，v0.2 §15）；SoundFont 进入 `registry/soundfont/`。

## 阶段状态变更
`SOUND_DIRECTION` → `AUDIO_DIRECTION_REVIEW` →（approve 后）`EDITORIAL_DIRECTION`

## Approval Gate（AUDIO_DIRECTION_REVIEW，waiting_user）
Review 必须明确展示并等待用户确认：
- **Music Strategy**（方向、BPM、Instrumentation、何时进出）
- **Music Route**（选定的主路线 + 理由）
- **Sonic Motif**（核心主题动机）
- **三级 Sound Design 应用**（Level 1 / Level 2 / Level 3 各具体到哪些音效类）
- **What to avoid**（Avoid 清单）

- approved → 进入 editorial-direction
- revision_requested → 回到 `SOUND_DIRECTION` 调整，旧 Decision 标记 superseded，新 Decision 创建
- rejected → 停止并记录原因

## Test 9 验证
Test 9（§71）要求对真实虚拟项目完整生成：**Music / SFX / Ambience / Voice-over balance / Hero sound policy** 五类声音设计。模板 `templates/audio-direction.md` 附带的 Example 段演示了完整填充（90s AI 产品短片）；本 workflow 的执行步骤 1-5 保证上述五项均落到 `AUDIO_DIRECTION.md`，缺任何一项即判定本阶段不完整。

## Phase 2 现状
> 当前实现状态：**implemented**（Director Pipeline 抬升，v0.2 §10-15 / §56 / §58-59）。
> 涉及的能力路由（reuse_map 引用）：SFX 走 `registry/sfx/`（@remotion/sfx、materia-sound-theme、Freesound、Mixkit、Kenney）；Music 走 `registry/music/`（Mixkit / Openverse / CC0-1.0-Music / FMA）；SoundFont 走 `registry/soundfont/`（GeneralUser-GS）；Procedural 渲染 `adapters/fluidsynth/`（Phase 5）；生成式 SFX（Sony Woosh）标注 EXPERIMENTAL 并保留 License 检查。
> 禁止：实现本阶段范围外的功能（禁止实际下载音乐库 / 接入 Provider / FluidSynth 生成配乐 / SFX 下载）。
