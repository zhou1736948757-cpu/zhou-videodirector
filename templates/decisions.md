# DECISIONS — 模板

> 用途：保存项目全部重要历史决定，是长期记忆的核心（v0.2 §53 / Phase-1 §16）。
>
> 使用时机：任何经用户确认、或影响后续方向的决定都必须追加记录；复盘、判断「当初为什么这么做」、跨会话续接时读取。
>
> 硬规则：本文件所有 Decision 只追加，不覆盖。新决定替代旧决定时新增 D-NNN 条目，Supersedes 字段写明被替代的 D-MMM。禁止删除或改写历史条目来伪装「当前只有一个决定」。

<!-- 字段说明
Decision ID            D-NNN，全局递增，永不复用
Date                   ISO8601，如 2026-08-01
Scope                  决定影响范围（如 Global Motion Language / Shot S002 Audio）
Decision               决定的实质内容
Reason                 为什么这样决定
User Feedback          用户当时的反馈原文（无则留空）
Status                 Draft / Pending / Approved / Rejected / Superseded
Supersedes             被本决定替代的旧 D-MMM 列表；无则空
Related Scene/Shots/Assets   受影响对象，如 SC001 / S002-S004 / A005
-->

## D-014

- Decision ID: D-014
- Date: 2026-08-01
- Scope: Global Motion Language
- Decision: Do not use large glitch effects.
- Reason: Breaks restrained visual language.
- User Feedback: （无）
- Status: Approved
- Supersedes: []
- Related Scene/Shots/Assets: 全部 Scene（全局约束）

## D-029

- Decision ID: D-029
- Date: 2026-08-10
- Scope: Global Motion Language
- Decision: Motion language updated to "depth movement + micro blur"; large glitch remains banned.
- Reason: User wanted stronger dynamics while keeping restraint.
- User Feedback: "动感可以更强，但不要花哨。"
- Status: Approved
- Supersedes: [D-014]
- Related Scene/Shots/Assets: 全部 Scene（全局约束）

<!-- 追加规则
1. 新条目永远追加在文件末尾，Decision ID 递增：D-015、D-016 ...
2. 决定被替代时：新增新条目，Supersedes 写明被替代的旧 ID；旧条目保持原样，不删除、不修改。
3. 状态流转：Draft → Pending → Approved / Rejected；被替代后旧条目置为 Superseded。
4. 需要长期记住的决定必须写进来，禁止依赖聊天上下文记忆。
5. Supersedes 引用必须指向存在的 D-MMM，避免悬空引用（由 validator 校验）。
-->
