# Scene Memory — 模板

> 用途：记录单个 Scene 的完整记忆（v0.2 §17 / Phase-1 §17）。每 Scene 一个文件：`scenes/SC###.md`。
>
> 使用时机：进入或修改某个 Scene 时读取/更新；Scene 审批通过、Shot 列表变化、音频方向变化时更新。

<!-- 字段块：每字段两行 —— 第 1 行 `# <字段名>: <占位值>`，第 2 行说明 -->
# Narrative Role: <如 "Chapter 2 开场" / "Hook" / "Payoff">
   该 Scene 在整片中的叙事角色。
# Chapter: <章节名或编号>
   所属 Chapter，如 Chapter 2。
# Scene Goal: <一句话目标>
   该 Scene 要让观众理解/感受到什么。
# Approved Direction: <已批准的视觉/叙事方向简述>
   引用已批准的 CREATIVE_DIRECTION / VISUAL_BIBLE / STORYBOARD 对应内容。
# Shots: []
   该 Scene 下的 Shot ID 列表，如 [S001, S002, S003]。
# Audio: <音频方向简述>
   该 Scene 的音频设计方向（Music / SFX / Ambience），引用 AUDIO_DIRECTION / AUDIO_MAP。
# Constraints: []
   针对该 Scene 的约束（用户反馈、避免项、技术限制）。
# Change History: []
   每次变更：时间 + 变更摘要 + 原因（只追加）。
# Status: <Draft | Pending | Approved | In Production | Completed | Superseded>
   当前状态，状态流转由 workflow 控制。
