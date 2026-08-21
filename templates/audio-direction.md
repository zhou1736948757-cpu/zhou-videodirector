# AUDIO_DIRECTION — 模板

> 用途：声音方向（Sound Direction）设计文档。声音与视觉同等进入设计阶段（v0.2 §10），
> 本文件是"Not BGM only"声音设计的最高约束之一，与 `VISUAL_BIBLE.md` 平级。
>
> 对应 schema：`schemas/audio-direction.schema.json`（17 个顶层字段）。
> 本模板在 schema 基础上增加派生结构（§43-48：Mood/Energy Curve、Impact/Riser 策略、
> Foley、Procedural Music 用法、三级 Sound Design 应用），共 20+ 字段。
>
> 使用时机：`VISUAL_BIBLE_REVIEW` 批准后、`EDITORIAL_DIRECTION` 之前（workflow：
> `workflows/sound-direction.md`）。生成后由 Sound Direction 写入 `<project>/AUDIO_DIRECTION.md`。
>
> 使用语言：中文；枚举 / 技术术语用英文大写（如 `LIBRARY_MUSIC`、`Level 2 Narrative Sound`）。
> 生成完成后必须在 `DECISIONS.md` 记录 D-xxx 决策，并推进到 `AUDIO_DIRECTION_REVIEW`（waiting_user）。

---

## 1. Sound Philosophy（声音哲学）

> 为什么设计声音，而不是只挂一段 BGM（Not "BGM only" 强规则）。说明声音如何服务叙事与
> 情绪，而不是装饰。必须与 Visual Bible 建立对应关系（Motion Character → Motion Sound、
> Color/Mood → Ambience、Transition → Riser 等）。

<!-- 填写 -->
本项目声音不是"最后加一首歌"。声音是叙事的一等公民（Constitution #6：Important Actions
Receive Intentional Audio Treatment）。设计原则：____。与 Visual Bible 的对应：____
（例如：视觉 Motion 语言克制 → 声音同样克制；Hero Effect 出现的位置 → Hero Sound 出现的位置）。

## 2. Music Direction（音乐方向）

> 音乐整体走向说明：类型、情绪、在片中的作用（引导 / 衬托 / 对峙）。

<!-- 填写 -->
____

## 3. Music Strategy & Music Route（音乐策略与获取路线）

> 音乐获取路线枚举（与 schema `music_route` 一致）。由场景类型决定，只推荐 1 个主路线，
> 其余可备注但不展开讨论。

<!-- 填写（保留一项） -->
- [x] `LIBRARY_MUSIC` — 理由：____
- [ ] `PROCEDURAL_MUSIC` — 理由：____（仅声明占位，Phase 2 不实现）
- [ ] `GENERATIVE_MUSIC` — 理由：____
- [ ] `HYBRID_MUSIC` — 理由：____
- [ ] `UNDECIDED` — 待定原因：____

策略说明（何时进入音乐、何时退出、章节间如何衔接）：____

## 4. Mood / Energy Curve（情绪 / 能量曲线）

> 描述全片能量如何变化：何时低（铺垫 / 呼吸）、何时高（Climax）、何时持续（Info 密集段）、
> 何时爆发（Hero 时刻）。建议按章节或时间线写 3-5 个阶段。

<!-- 填写 -->
- 0:00-0:15（Hook）：____（能量低-中，铺垫）
- 0:15-0:45（Explain）：____（能量持续中高）
- 0:45-1:15（Demo）：____（能量上升）
- 1:15-1:30（Climax / Payoff）：____（能量最高点，Hero Sound）
- 结尾：____（回落或留白）

## 5. Mood（整体情绪基调）

<!-- 填写 -->
____（例：克制、科技感、克制中的温暖）

## 6. Energy（能量水平）

<!-- 填写 -->
____（例：中低能量为主，1-2 个高能爆发点）

## 7. BPM Range（BPM 区间）

> 写区间并说明"何时选 BPM"：如讲解段选区间低端、Demo/Climax 选高端；或说明 BPM 如何
> 跟随旁白节奏。

<!-- 填写 -->
____（例：`80-110`；讲解段 80-90，Hero 段 100-110）

## 8. Instrumentation（乐器 / Synth 风格）

<!-- 填写 -->
____（例：Minimal synth pad + 钢琴点缀 + 模拟 sub bass；避免铜管）

## 9. Voice-over Priority（旁白优先度）

> 数值或描述：VO 与音乐/SFX 的优先级关系；典型取值如 VO 优先 → duck 6-12 dB。

<!-- 填写 -->
____（例：VO 最高优先级；音乐 duck -8 dB；SFX 不盖 VO 频段）

## 10. Ducking Strategy（Music Ducking）

<!-- 填写 -->
____（例：VO 进入时 music -8 dB / 250ms 起落；Hero 时刻临时取消 duck 让音乐顶上来）

## 11. SFX Language（SFX 语言）

> 音效种类与风格：本片允许哪些 SFX 家族（click / whoosh / impact / data pulse…），
> 风格统一在哪个频段与质感上。

<!-- 填写 -->
____（例：以 micro click / soft whoosh / data pulse 为主，高频清脆、低频克制）

## 12. UI Sound Language（UI 声音语言）

<!-- 填写 -->
____（例：参考 Google Material 声音语言；短促 click，音高随层级递进）

## 13. Motion Sound Language（动效声音语言）

<!-- 填写 -->
____（例：Motion 入场配 soft whoosh / tick；退场配无音效或短 tick，防止吵闹）

## 14. Ambience（环境声）

<!-- 填写 -->
____（例：极轻 digital room tone + 低频 airy hum；全片常驻 -30 dB 以下）

## 15. Foley（拟音）

<!-- 填写 -->
____（例：卡片翻动 / 键盘敲击 / 设备开合等物理质感，按需少量使用）

## 16. Impact Policy（Impact 策略）

> 何时用 impact、什么强度、频次上限。

<!-- 填写 -->
____（例：全片 ≤ 3 次大 impact，只在章节首尾 / 数据揭示处）

## 17. Riser Policy（Riser 策略）

<!-- 填写 -->
____（例：转场 riser ≤ 1.2s，能量层级只升不降，Hero 前不使用）

## 18. Hero Sound Policy（Hero Sound 策略）

> 对应 Level 3 Hero Sound：哪些关键时刻配 Hero Sound、用什么类型（Bass hit / 大 riser /
> Logo sonic identity / climax transition）、全片最多几次。

<!-- 填写 -->
____（例：Climax 1 次 Hero bass hit + 1 次 Logo sting；全片 Hero Sound ≤ 2 次）

## 19. Silence Policy（沉默策略）

> 何时用沉默作为设计元素（reveal 前的留白、情绪落点、Pattern Interrupt）。

<!-- 填写 -->
____（例：Climax 揭示前 0.5s 全静音；每次章节结束留 0.3s 呼吸）

## 20. Sonic Motif（核心主题动机）

> 全片反复出现的短小声音身份：节奏型 / 音高 / 音色特征，用于唤起同一主题。

<!-- 填写 -->
____（例：三音下行动机（C-G-E），钢琴 + 正弦；每次"产品价值"出现时复用）

## 21. Avoid（明确不要什么）

<!-- 填写（列表） -->
- ____
- ____

## 22. References（音频参考）

> 与哪些 Reference Report（Audio Layer）对得上；可附链接 / 本地路径。

<!-- 填写 -->
- ____
- ____

## 23. Procedural Music 用法（占位声明）

> §44 用法：Logo Sting / Chapter Transitions / Short Motif / Shot-sync。
> **Phase 2 只声明"哪些拍点用 Procedural Music"，不实现真程序**；
> Phase 5+ 用 FluidSynth + SoundFont（GeneralUser-GS 等）渲染 MIDI → WAV 才真实现。

<!-- 填写 -->
- Logo Sting：____（拍点：____）
- Chapter Transitions：____
- Short Motif：____
- Shot-sync：____
- Phase 2 实现状态：仅声明占位，不生成 MIDI / 不渲染 WAV。

## 24. 三级 Sound Design 的本项目应用（§45）

> 把三级声音设计落到本项目，每级具体到"哪 X 类音效"。

<!-- 填写 -->
- **Level 1 Invisible Audio**（大量）：本项目用 ____ 类（例：tiny click / soft tick /
  micro whoosh / room tone / subtle texture），目标：高级感、不抢注意力。
- **Level 2 Narrative Sound**（按叙事）：本项目用 ____ 类（例：card expansion /
  map movement / data pulse / transition whoosh），对应叙事动作。
- **Level 3 Hero Sound**（少量）：本项目用 ____ 类（例：Bass hit / Large riser /
  Logo sonic identity / climax transition），全片 ≤ ____ 次。

---

## 附：Test 9 完整填充示例（Example）

> 演示一个虚拟项目走完后 `AUDIO_DIRECTION.md` 的样子（≤60 行）。
> 虚拟项目：90 秒 AI 效率工具产品短片（Production Mode A / Product-Tech Short）。

### Example: "Focus" — 90s AI 效率工具短片

- **Sound Philosophy**：声音叙事化，不做 BGM 装饰；所有 Hero 视觉点（Logo / 数据揭示）
  都有对应声音决策。与 Visual Bible（Minimal Spatial Tech）对齐：视觉克制 → 声音克制。
- **Music Direction**：Minimal electronica，情绪从好奇到确信。
- **Music Route**：`LIBRARY_MUSIC`（短片 + 旁白，音乐库效率最高；Procedural 留到 Logo Sting）。
- **Mood / Energy Curve**：0-15s 低能量好奇 → 16-45s 持续中低（讲解）→ 46-70s 上升（Demo）
  → 71-85s 峰值（Hero）→ 86-90s 回落留白。
- **BPM Range**：`85-105`；讲解 85-90，Hero 段 100-105。
- **Instrumentation**：synth pad + 钢琴 + 模拟 sub bass；无人声。
- **Voice-over Priority**：VO 最高，音乐 duck -8 dB。
- **Ducking Strategy**：VO 起时 250ms 内 -8 dB；Hero 4s 取消 duck。
- **SFX Language**：micro click / soft whoosh / data pulse；高频清脆。
- **UI Sound Language**：Material 风格 click，层级越高音高越高。
- **Motion Sound Language**：入场 whoosh / tick，退场无声。
- **Ambience**：digital room tone -32 dB 常驻。
- **Foley**：键盘敲击 2 次（Demo 段）。
- **Impact Policy**：全片 2 次大 impact（Logo 出、数据揭示）。
- **Riser Policy**：转场 riser ≤ 1s，Hero 前不用大 riser。
- **Hero Sound Policy**：2 次（Climax bass hit + Logo sting）。
- **Silence Policy**：Climax 前 0.5s 全静音。
- **Sonic Motif**：C-G-E 三音下行，每次产品价值出现复用。
- **Avoid**：不追节奏的炫技 glitch SFX、不叠层不清频、避免大交响 BGM。
- **References**：Reference Report Audio Layer（Apple Keynote 风格点击 + 软音乐）。
- **Procedural**：Logo Sting + 章节转场占位声明（Phase 2 不实现 FluidSynth）。
- **三级应用**：L1 = click/tick/room tone 三类；L2 = whoosh/data pulse/card 三类；
  L3 = bass hit + Logo sting 两类，共 2 次。

<!-- 使用规则
1. 所有 schema 顶层字段（17 个）都必须填写；派生结构（Philosophy / Curve / Impact /
   Riser / Foley / Procedural / 三级应用）必须存在但可精简。
2. "Not BGM only"：没有 Music/SFX/VO/Ambience/Sonic Motif 全部设计就不算完成，空降 BGM 不接受。
3. Music Route 只推荐 1 个主路线（按场景类型），其余不必逐一展开。
4. Procedural Music 仅占位声明；Phase 2 禁止实现 FluidSynth / SoundFont / MIDI 渲染。
5. 与 AUDIO_MAP.md（templates/audio-map.md）保持一致；Shot 级 audio 结构（music/sfx/
   ambience/sync_points/ducking/voiceover）在 Storyboard 阶段引用本文件。
-->
