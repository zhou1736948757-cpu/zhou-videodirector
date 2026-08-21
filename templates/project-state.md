# PROJECT_STATE — 模板

> 用途：这是项目运行时的「Current Truth」（v0.2 §52 / Phase-1 §15）。每次进入项目首先读取本文件，
> 即可了解当前总体状态：项目在哪一阶段、正在做哪个 Scene/Shot、等待哪些决定、下一步做什么。
>
> 使用时机：
> 1. 任何一次会话开始时，首先读取项目根目录的 `PROJECT_STATE.md`；
> 2. 任何关键推进后立即更新（阶段变更 / 审批通过 / 决定更新 / Scene / Shot 建立）；
> 3. 永远保持短：目标 30-100 行。它不代表完整历史，完整历史在 `DECISIONS.md` 与各 Scene / Shot / Asset Memory 中。

<!-- 使用规则
- 字段名与取值遵循 docs/memory-system.md；阶段枚举以 docs/state-machine.md（机器真源 schemas/state-machine.json）为准。
- list 字段为空写 []，不要留空。
- Last Updated 使用 ISO8601，如 2026-08-13T09:30:00+08:00。
- 本模板为注释形式：复制后把 `#` 去掉即为 YAML-style 字段块，机器可解析。
-->

<!-- 字段块：每字段两行 —— 第 1 行 `# <字段名>: <占位值>`，第 2 行说明 -->
# Project: <项目名>
   项目显示名，取自 Project Brief，如 "AI 产品 90s 介绍"。
# Production Mode: <PRODUCT_TECH_SHORT | EDITORIAL_EXPLAINER | CUSTOM>
   生产模式，决定整体节奏与工具权重（v0.2 §58-59）。
# Delivery Mode: <FINAL_VIDEO_ONLY | EDITABLE_PROJECT | BOTH>
   交付方式，多数项目推荐 BOTH（成片 + 可编辑剪映工程）。
# Current Stage: <阶段枚举之一>
   当前所处阶段，见下方阶段枚举；进入下一阶段前必须满足对应审批。
# Current Scene: <SC### 或空>
   当前正在设计/制作的 Scene，ID 如 SC001；无则空。
# Current Shot: <S### 或空>
   当前正在设计/制作的 Shot，ID 如 S001；无则空。
# Approved Stages: []
   已获用户批准的阶段列表，如 [PROJECT_BRIEF, CREATIVE_DIRECTION]。
# Pending Decisions: []
   等待用户确认的决定列表（Decision ID / 阶段名，逐项列出）。
# Blocked Items: []
   当前阻塞项，每项一句话（阻塞原因 + 建议解法）。
# Current Style: <样式名>
   已批准的 Style 名称，如 minimal_spatial_tech；未批准前留空。
# Current Audio Direction: <音频方向一句话>
   已批准的音频方向简述；未批准前留空。
# Important Constraints: []
   影响后续制作的硬约束（品牌 / 时长 / 避免清单等）。
# Next Action: <下一步动作>
   明确的下一步动作，带对应 workflow 引用，如 "Run Grill Me (workflows/project-intake.md)"。
# Last Updated: <YYYY-MM-DDTHH:MM:SS±HH:MM>
   本次更新的 ISO8601 时间。

<!-- 阶段枚举
INIT 为启动态（状态机入口），不列入 Current Stage 取值。
Current Stage 取值（29 个，权威定义见 docs/state-machine.md / schemas/state-machine.json）：
PROJECT_INTAKE | PROJECT_BRIEF_REVIEW | REFERENCE_ANALYSIS | REFERENCE_REVIEW |
CREATIVE_DIRECTION | CREATIVE_REVIEW | STYLE_DIRECTION | VISUAL_BIBLE_REVIEW |
SOUND_DIRECTION | AUDIO_DIRECTION_REVIEW | EDITORIAL_DIRECTION | STORY_REVIEW |
STORYBOARD | STORYBOARD_REVIEW | SUBAGENT_CONFIGURATION | SHOT_ROUTING |
LAYER_ROUTING | RESOURCE_PLANNING | PRODUCTION_PLAN_REVIEW | ASSET_ACQUISITION |
ASSET_PRODUCTION | TIMELINE_BUILD | TIMELINE_REVIEW | PREVIEW | QA |
CHANGE_REVIEW | FINAL_EDIT | FINAL_RENDER | COMPLETE
-->
