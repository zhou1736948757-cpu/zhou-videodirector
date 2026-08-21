# AUDIO_MAP — 模板

> 用途：全片音频时间轴（v0.2 §56）。Storyboard 之外单独生成，作为 Sound Design 与剪映音频轨道的直接依据。
>
> 时间轴格式：`MM:SS.mmm | 事件描述`
> - `MM:SS.mmm` 为绝对时间点（分:秒.毫秒）；
> - 事件描述用中文或英文短语，标注该时刻的音频行为（Music / SFX / Ambience / VO / Ducking / Silence）；
> - 条目按时间递增排列；同一时间点多个事件可并列多行。
>
> 使用时机：Sound Direction 批准后、制作前生成；Shot / Timeline 改动时同步更新。本模板给出示例骨架，项目使用时按实际 Storyboard 时间轴生成。

00:01.200 | Soft impact
00:03.400 | UI click
00:04.200 | Whoosh
00:12.000 | Music layer enters
00:24.000 | Voice emphasis / music duck
00:46.000 | Hero impact
00:52.300 | Transition riser
01:05.800 | Silence (beat before reveal)

<!-- 使用规则
1. 每个重要视觉动作都应经过 intentional audio consideration（v0.2 §11）。
2. 分级：Level 1 Invisible Audio（微音效）/ Level 2 Narrative Sound / Level 3 Hero Sound（v0.2 §11）。
3. 与 AUDIO_DIRECTION.md 保持一致；Ducking / Silence 也要显式标注。
4. 事件描述写清类别（Music / SFX / Ambience / VO），便于剪映分轨。
-->
