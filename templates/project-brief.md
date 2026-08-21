# PROJECT BRIEF — 模板

> 用途：结构化项目需求文档（v0.2 §4 产出的 PROJECT BRIEF）。由 `workflows/project-intake.md`（Grill Me）生成，
> 在 `PROJECT_BRIEF_REVIEW` 阶段等待用户确认；字段与 `schemas/project.schema.json` 对齐，枚举使用共享契约大写。
>
> 使用时机：Grill Me 达到停止条件后填充本模板；用户 `revision_requested` 时逐字段修订后重新提交审批。

<!-- 使用规则
- 每字段两行：第 1 行 `# <字段名>: <占位值>`，第 2 行中文说明。
- list 字段为空写 []；number 字段写数字；boolean 字段写 true/false。
- 枚举取值见各字段注释；暂无法确定时写 `<待定>` 并在 Open Questions 中列出。
- Assumptions 记录导演推断（含 Tier-3 assumed 值：motion_style / transition_type / bpm / shot_count）。
-->

# Project Name: <项目名>
   项目标题，取自 Grill Me 的 video_about（内容主题），如 "AI 产品 90s 介绍"。
# source: answered
# Type: <项目类型>
   项目类型（project_type，与 production_mode 语义一致的别名），如 product_short / editorial_explainer / custom。
# source: answered
# Production Mode: <PRODUCT_TECH_SHORT | EDITORIAL_EXPLAINER | CUSTOM>
   生产方式，决定整体节奏与工具权重（v0.2 §58-59）。
# source: recommended
# Delivery Mode: <FINAL_VIDEO_ONLY | EDITABLE_PROJECT | BOTH>
   交付方式，多数项目推荐 BOTH（成片 + 可编辑剪映工程）。
# source: recommended
# Platform: <发布平台>
   目标发布平台，决定长宽比 / 分辨率 / 字幕与节奏默认值。
# source: answered
# Aspect Ratio: <16:9 | 9:16 | 1:1 | 4:3 | 21:9>
   画面长宽比，默认 16:9，按平台最佳实践调整。
# source: recommended
# Resolution: <宽 x 高，如 1920x1080>
   目标分辨率（像素），width / height 两个整数。
# source: recommended
# FPS: <帧率，如 30 / 25 / 60>
   帧率，与平台与动效需求匹配。
# source: recommended
# Target Duration: <秒，如 90>
   目标时长（秒），决定 Production Mode 与叙事结构规模。
# source: answered
# Audience: <目标观众>
   目标观众描述，决定语言密度、节奏与风格取舍。
# source: answered
# Primary Goal: <主要目标>
   视频主要目标（产品介绍 / 涨粉 / 教学 / 品牌宣传等）。
# source: answered
# Core Message: <核心信息>
   全片核心信息，创意与叙事的锚点。
# source: answered
# Narrative Format: <叙事形式>
   叙事形式（线性讲解 / 故事化 / 数据化 / 场景演示等），由 Creative Director 细化。
# source: recommended
# Voice-over: <true | false>
   是否使用旁白，决定叙事主轴与音频设计。
# source: answered
# Language: <语言>
   字幕 / 旁白语言，如 中文 / English / 中英双语。
# source: answered
# Available Assets: []
   用户已有可用素材（图片 / 视频 / 产品 UI / 文案等），逗号分隔。
# source: answered
# Reference Sources: []
   参考视频链接 / 本地路径，进入 Reference Analysis（无参考则后续阶段跳过）。
# source: answered
# Style Preferences: []
   风格偏好（含情绪印象 emotional_impression），喂给 Creative / Style Director。
# source: inherited
# Style Avoidances: []
   需要避免的风格元素，写入 Visual Bible 的避免清单。
# source: inherited
# AI Video Policy: <true | false>
   是否允许 AI 生成视频（Shot Router 的 GENERATIVE_VIDEO 路由）。
# source: answered
# Real Footage Policy: <true | false>
   是否允许真实素材（Shot Router 的 REAL_FOOTAGE 路由）。
# source: answered
# 3D Policy: <true | false>
   是否允许 3D（Shot Router 的 THREE_D 路由）。
# source: answered
# Editability Requirement: <true | false>
   是否必须提供可编辑时间线（决定 Delivery Mode 与 Timeline Build 可编辑边界）。
# source: answered
# Quality·Time·Budget Priority: <quality: high|medium|low, time: high|medium|low, budget: high|medium|low>
   三轴优先级，分别对应 quality_priority / time_priority / budget_priority。
# source: answered
# Important User Constraints: []
   关键约束（品牌约束 brand_constraints / 用户补充 user_notes），影响后续所有阶段。
# source: answered
# Assumptions: []
   导演推断与默认假设（含 Tier-3 assumed 值：motion_style / transition_type / bpm / shot_count），用户可修改。
# source: assumed
# Open Questions: []
   未决问题，需用户在审批时明确或由后续阶段解决。
# source: assumed
