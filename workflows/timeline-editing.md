---
workflow_id: WF-011
name: 可编辑时间线
stage_ids: [TIMELINE_BUILD, TIMELINE_REVIEW]
requires_approval: [TIMELINE_REVIEW]
phase1_status: skeleton
---

# 可编辑时间线（Timeline Editing）

## 目标
把 Asset Package 组装为一个 **AI 和人共同可编辑** 的时间线工程（优先剪映草稿）。硬要求：**Human Must Be Able to Take Over**；视觉质量相近时优先"更可编辑"的方案，而不是全部 bake。

## 触发时机
`ASSET_PRODUCTION` 完成后触发。

## 输入
- `<project>/assets/`、`<project>/shots/`、`<project>/STORYBOARD.md`
- `schemas/timeline.schema.json`（backend / tracks / clips / text_items / subtitle_items / audio_tracks / sfx_tracks / music_tracks / overlays / keyframes / transitions / asset_links / replaceable_assets / manual_edit_safe / version / status）

## 输出（项目文件）
- `<project>/timeline/` 下的可编辑工程文件（优先剪映草稿 draft）
- `<project>/timeline/TIMELINE_MANIFEST.md` — 时间线 manifest，标注 backend 与 manual_edit_safe

## 执行步骤
1. **Editable Timeline Backend 抽象**（v0.2 §33）：第一版优先 `pyJianYingDraft`，架构预留 VectCutAPI / pyCapCut / Future Backend，枚举见 `schemas/timeline.schema.json`。
2. 依据 Shot 顺序 / 时长 / Transition 组装轨道：Video / Overlay / Text / Subtitle / Audio / SFX / Music（pyJianYingDraft 负责 track / keyframes / transform / filter / transition / volume / fade 等，v0.2 §34）。
3. 放置 Asset（timeline_start 对齐），写入 asset_links 与 replaceable_assets；有 `editable: true` / `baked: false` 的 Asset 必须保留在可编辑边界内。
4. 尊重 Motion Continuity Group：连续 Motion 不可为了可编辑性硬拆（v0.2 §31）。
5. 生成可打开继续编辑的剪映草稿，交付 AI / 人工联合编辑。
6. 推进到 `TIMELINE_REVIEW`（waiting_user）。

## 阶段状态变更
`TIMELINE_BUILD` → `TIMELINE_REVIEW` →（approve 后）`PREVIEW`

## Approval Gate
- approved → 进入 qa 工作流（PREVIEW）
- revision_requested → 回到 `TIMELINE_BUILD` 修改时间线

## Phase 1 现状
> 当前实现状态：skeleton。完整实现待 Phase 7（Editable Timeline）完成。具体的 module 在 `modules/timeline-manager/` 下开发。
> 涉及的能力路由（reuse_map 引用）：`adapters/pyjianyingdraft/`（TIMELINE_BACKEND，reuse draft_generation / timeline_tracks / media_placement / keyframes / subtitles / audio），备选 `adapters/vectcut/`、`adapters/pycapcut/`。
> 禁止：实现本阶段范围外的功能（禁止生成正式剪映草稿 / 实现时间线引擎）。
