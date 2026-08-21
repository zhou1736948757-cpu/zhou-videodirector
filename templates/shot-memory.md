# Shot Memory — 模板

> 用途：记录单个 Shot 的完整记忆（v0.2 §54 / Phase-1 §18）。每 Shot 一个文件：`shots/S###.md`。
>
> 使用时机：进入或修改某个 Shot 时读取/更新；设计、路由、制作、QA 每个环节推进时更新。

<!-- 字段块：每字段两行 —— 第 1 行 `# <字段名>: <占位值>`，第 2 行说明 -->
# Narrative Purpose: <一句话叙事目的>
   这个镜头在叙事上要完成什么。
# Approved Visual: <已批准的视觉描述>
   经用户批准的视觉内容，是后续实现的依据。
# Layers: []
   Layer 列表（Layer ID + 类型 + Route），详见 v0.2 §20；单层 Shot 可只列一层。
# Motion: <运动设计描述>
   Motion 语言与级别（Invisible Micro Motion / Narrative Motion / Hero Effect）。
# Camera: <运镜描述>
   如 "Slow push in" / "Static" / "Orbit 30deg"。
# Text: <屏幕文字内容>
   屏幕上的文字（标题 / 字幕），JY_NATIVE 文字也要记录。
# Audio: <音频设计>
   Music / SFX / Ambience / Sync Points / VO，参考 AUDIO_MAP 时间点。
# Route: <REMOTION | THREE_D | REAL_FOOTAGE | GENERATIVE_VIDEO | JY_NATIVE | HYBRID | UNDECIDED>
   技术路由（一级）；Hybrid 时在 Layers 里逐层写明二级路由。
# Assets: []
   使用到的 Asset ID 列表，如 [A001, A002]。
# Continuity Group: <group 名或空>
   需要一次连续 Render 的 Motion Continuity Group（v0.2 §31）。
# User Constraints: []
   用户对该 Shot 的硬性要求 / 反馈。
# Change History: []
   每次变更：时间 + 变更摘要 + 原因（只追加）。
# Implementation Status: <Not Started | In Progress | Rendered | Baked | Blocked>
   制作实现状态。
# QA Status: <Not Started | Technical Pass | Visual Pass | Editorial Pass | Sound Pass | Failed>
   QA 状态，见 v0.2 §57 四层 QA。
