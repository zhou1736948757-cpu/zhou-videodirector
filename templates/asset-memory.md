# Asset Memory — 模板

> 用途：记录单个 Asset 的完整记忆（v0.2 §55 / Phase-1 §19）。每 Asset 一个文件：`assets/A###.md`。
>
> 使用时机：Asset 获取 / 制作 / 替换时更新；剪映时间线引用 Asset 前应核对 License 与 Replaceable。

<!-- 字段块：每字段两行 —— 第 1 行 `# <字段名>: <占位值>`，第 2 行说明 -->
# Asset ID: <A###>
   全局唯一，如 A018。
# Purpose: <用途，如 animated_chip / hero_impact>
   该资产在片中承担的角色。
# Producer: <REMOTION | THREE_D | AI_VIDEO | REAL_FOOTAGE | IMAGE | MUSIC | SFX | VOICEOVER | LIBRARY | SOUNDFONT>
   生产方。
# Type: <Asset Type 枚举>
   见下方类型枚举。
# Version: <v1 / v2 ...>
   版本号，替换后递增，旧版本文件保留。
# File / Source Location: <相对路径或 URL>
   文件位置或来源（Provider / URL）。
# License: <License 名>
   许可与归属要求（是否可商用、是否需署名）。
# Resolution: <如 1920x1080>
   画面资产的分辨率；音频资产留空。
# FPS: <如 30>
   帧率。
# Alpha: <true | false>
   是否带透明通道。
# Duration: <如 4.2（秒）>
   时长，单位秒。
# Used In: []
   使用到的 Shot 列表，如 [S001, S002]。
# Replaceable: <true | false>
   是否可被替换 / 重新生成，影响后续编辑自由度（v0.2 §35 Human Editable）。
# Render Settings: <关键渲染参数>
   如 format mov / 编码 ProRes 4444 / 是否带 Alpha。
# Change History: []
   每次变更：时间 + 变更摘要 + 原因（只追加）。
# Status: <Planned | In Production | Available | Superseded | Removed>
   当前状态。

<!-- Asset Type 枚举（Phase-1 §25）
FULL_SCENE | MOTION_CLIP | TRANSPARENT_OVERLAY | ANIMATED_TEXT | 3D_ELEMENT |
BACKGROUND | PARTICLE_LAYER | TRANSITION_ASSET | INFOGRAPHIC | UI_COMPONENT |
DECORATIVE_ELEMENT | FOOTAGE | IMAGE | MUSIC | SFX | VOICEOVER | AMBIENCE | SOUNDFONT
-->
