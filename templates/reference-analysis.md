# REFERENCE_ANALYSIS — 模板

> 用途：参考片分析报告（Phase-2 §22 / v0.2 §6 / Phase-1 §11）。对每个参考视频做 6 层分析
> （Content / Editorial / Composition / Motion / Visual / Audio），提炼可复用规律 R-NN 与避免清单，
> 作为 Creative / Style / Sound / Editorial 四位 Director 的输入。原则：学习规律，不逐镜复制；
> 只保留 Normalized Reference Output 字段，不暴露外部 Skill 私有 CoT。
>
> 使用时机：REFERENCE_ANALYSIS 阶段填充（workflows/reference-analysis.md）；无参考结构化跳过；
> ≥ 2 references 时另写 REFERENCE_COMPARISON.md 并在第 4 节引用。目标 60-150 行；语言中文，
> 枚举 / 技术术语英文大写。字段块约定：每字段两行 —— `# <字段>: <占位>` + 中文说明；list 为空写 []。

## 1. Executive Summary
> 用途：2-3 段极简摘要，让四位 Director 不读全稿也能抓住要点。字段：Summary（一段）、Key Takeaways（3-5 条）。
# Summary: <3-5 句话概括所有参考片整体"好在哪">
   第一段写"参考片讲什么 + 为什么值得学"；第二段写"最值得带走的一条规律"。
# Key Takeaways: [<Takeaway-1>, <Takeaway-2>, <Takeaway-3>]
   每条一句话，直接服务本项目方向判断。

## 2. Reference List
> 用途：列出全部参考来源。每条 Reference 一个块，字段：source_url / source_type / title / duration_seconds / label。
# Reference 1
#   source_url: <URL 或本地文件路径>
#   source_type: <youtube | bilibili | local | ad | product | explainer | motion_design | film_clip | ...>
#   title: <参考片标题>
#   duration_seconds: <整数秒>
#   label: <REF-A>
# Reference 2..N：同上字段逐项填写，label 递增（REF-B ...）

## 3. Per-reference Analysis
> 用途：每个 reference 独立跑 6 层，互不污染；复制本块并递增 label。字段：content_summary /
> editorial_summary / composition_summary / motion_summary / visual_summary / audio_summary /
> reusable_rules / avoid_traits。证据规则：主观结论尽量附时间轴位置 `t: <mm:ss>`；无证据写 unresolved。
# REF-A content_summary: <1-3 句>
   视频讲了什么（内容主题与产品/主题的对应关系）。
# REF-A editorial_summary: <Hook: ... / Pacing: ... / B-roll frequency: ... / Build-Reveal-Payoff: ...>
   剪辑叙事层：钩子、节奏、B-roll 频率、构建-揭示-回报结构。
# REF-A composition_summary: <Layout: ... / Whitespace: ... / Typography hierarchy: ... / Depth: ...>
   画面构图层：版式、留白、文字层级、深度 / 分层。
# REF-A motion_summary: <Motion character: ... / Easing: ... / Micro-motion: ... / Hero-effect frequency: ...>
   动效层：运动性格、缓动曲线、微动效密度、主角特效频率。
# REF-A visual_summary: <Color: ... / Light: ... / Material: ... / 2D-3D balance: ... / Footage treatment: ...>
   视觉层：色彩、光线、材质、2D-3D 平衡、实拍素材处理方式。
# REF-A audio_summary: <Music style: ... / SFX frequency: ... / Silence: ... / Ducking: ...>
   声音层：音乐风格、音效频率、静音运用、闪避（Ducking）。
# REF-A reusable_rules: [<R-NN>]
   本片提炼出的 R-NN 规则编号（见第 9 节，只列编号）。
# REF-A avoid_traits: [<不复制特性的简短描述>]
   本片中明确不要复制的特性。

## 4. Cross-reference Comparison
> 用途：仅当 reference ≥ 2 时填充。完整对比见 `REFERENCE_COMPARISON.md`，本节省略版只留结论引用。
# Comparison File: <references/REFERENCE_COMPARISON.md>
   多参考对比报告的相对路径。
# Has Conflicting Patterns: <true | false>
   参考间是否存在冲突特征。
# Conflict Resolution Note: <一句话结论>
   冲突裁决（以用户偏好 / Creative 方向为准，或分阶段使用），详细处理见 comparison 第 2 节。

## 5. Motion Language
> 用途：合成统一运动语言（供 Style Director 的 VISUAL_BIBLE 与 Motion 约束）。字段：Motion character / Default Easing / Micro-motion density / Hero-effect frequency / Transition language。
# Motion Character: <如 沉稳 | 灵动 | 刚性科技感>
   本项目统一的运动性格。
# Default Easing: <ease-out | ease-in-out | spring | ...>
   默认缓动曲线，并说明何时例外。
# Micro-motion Density: <高 | 中 | 低 + 一句话>
   微动效（hover、呼吸、位移）的密度档位。
# Hero-effect Frequency: <每 Shot | 每 N 秒一次>
   主角特效出现频率，防"每镜都 Hero"。
# Transition Language: <硬切 | 叠化 | 位移动画 | ...>
   转场语言与使用条件。

## 6. Editorial Language
> 用途：合成统一剪辑叙事语言（供 Editorial Director 的 BEAT MAP）。字段：Hook / Pacing / Shot length range / B-roll frequency / Build-Reveal-Payoff / Pattern interrupt。
# Hook: <前 3-5 秒如何抓住观众>
   开场钩子的统一做法。
# Pacing: <快 | 中 | 慢 + 变化策略>
   整体节奏档位与起伏策略。
# Shot Length Range: <最短 - 最长 秒，中位数>
   镜头时长区间，供 Shot 规划约束。
# B-roll Frequency: <每 N 秒一次 + 用途>
   B-roll 出现频率与功能（覆盖、情绪、信息补充）。
# Build-Reveal-Payoff: <构建-揭示-回报的结构模式>
   关键信息的揭示节奏。
# Pattern Interrupt: <每 N 秒一次 | 无>
   规律打断的刻意安排。

## 7. Visual Language
> 用途：合成统一视觉语言（供 Style Director 的 VISUAL_BIBLE）。字段：Color system / Light / Materials / Typography hierarchy / Depth & layering / 2D-3D balance / Footage treatment。
# Color System: <主色 + 辅色 + 强调色，如 深蓝 + 白 + 青色高光>
   统一色彩体系。
# Light: <高调 | 低调 | 棚光 | 自然光 + 一句话>
   光线风格。
# Materials: <玻璃 | 金属 | 哑光塑料 | 纸张 | ...>
   材质语言。
# Typography Hierarchy: <标题字重 / 层级数量，如 2 级标题 + 正文>
   文字层级规则。
# Depth & Layering: <前景-中景-背景 / Z 深度分层方式>
   深度与分层。
# 2D-3D Balance: <2D 为主 + 3D 点缀 | 全 3D | ...>
   2D-3D 配比。
# Footage Treatment: <实拍 | 转绘 | 分级风格>
   实拍素材的处理方式。

## 8. Audio Language
> 用途：合成统一声音语言（供 Sound Director 的 AUDIO_DIRECTION）。字段：Music style / Music density / SFX frequency / Silence usage / Ducking / Ambience。
# Music Style: <风格 + 节奏档位，如 极简电子、中速>
   统一音乐方向。
# Music Density: <高 | 中 | 低>
   音乐铺底密度。
# SFX Frequency: <每 N 秒一次 + 主要类型>
   音效频率与类型（Impact / Whoosh / UI 音等）。
# Silence Usage: <有 | 无 + 位置>
   静音 / 留白的刻意运用。
# Ducking: <on | off + 触发场景>
   音乐闪避策略。
# Ambience: <有 | 无 + 氛围类型>
   环境音层。

## 9. Reusable Rules
> 用途：跨项目可复用的规律清单，编号 R-NN（Phase-2 §20），一句话可执行、可迁移，至少 3 条；
> 来源注 `REF-A @t:mm:ss`（可选）。每条两行：`# R-NN: <规则>` + 中文说明。
# R-001: <一句话原则>
   规则含义与适用边界。
# R-002: <一句话原则>
   规则含义与适用边界。
# R-003: <一句话原则>
   规则含义与适用边界。
# R-004: <一句话原则>
   规则含义与适用边界（可增删，保持 ≥ 3 条）。

## 10. Avoid Copying
> 用途：明确"不要复用"清单，防止逐镜复制（v0.2 §6）。条目格式 AVOID-NN，保持 ≥ 2 条。
# AVOID-001: <不要复制的特性 + 为什么>
   如"原片炫光扫过全屏，与本项目克制视觉冲突"。
# AVOID-002: <不要复制的特性 + 为什么>
   如"每 0.5 秒一切，信息密度过高"。
# AVOID-003: <不要复制的特性 + 为什么>
   可增删，保持 ≥ 2 条。

## 11. Implications for Current Project
> 用途：把上述规律落到四位 Director 各自职责，每位 Director 一段，写明"本阶段怎么用"。
# For Creative Director: <Hook / Core Idea / 情绪方向怎么用 R-NN>
   创意导演如何消费本报告（如：R-001 决定开场钩子写法）。
# For Style Director: <Visual + Composition + Motion 怎么落到 VISUAL_BIBLE>
   风格导演如何把第 5/7 节语言固化为 Visual Bible 约束。
# For Sound Director: <Audio 怎么落到 AUDIO_DIRECTION>
   声音导演如何把第 8 节语言固化为音频方向。
# For Editorial Director: <Pacing / 结构怎么落到 BEAT MAP>
   编辑导演如何把第 6 节语言固化为叙事结构。
