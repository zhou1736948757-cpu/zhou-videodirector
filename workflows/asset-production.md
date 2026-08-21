---
workflow_id: WF-010
name: 资产生产
stage_ids: [ASSET_ACQUISITION, ASSET_PRODUCTION]
requires_approval: []
phase1_status: skeleton
---

# 资产生产（Asset Production）

## 目标
按路由与生产计划生产 / 获取所有 Asset，每个 Asset 都必须携带完整 **Asset Contract** 元数据，使 AI 与剪映都能理解"这是什么、何时用、可否替换"。

## 触发时机
`PRODUCTION_PLAN_REVIEW` 已批准后触发。

## 输入
- `<project>/PRODUCTION_PLAN.md`、`<project>/shots/`
- `schemas/asset.schema.json`、`schemas/timeline.schema.json`（timeline_start 约束）

## 输出（项目文件）
- `<project>/assets/A###.md` — Asset Memory：asset_id / type / producer / purpose / format / alpha / fps / resolution / duration / timeline_start / replaceable / version / license / status（Asset Contract 字段，v0.2 §32）
- `<project>/assets/` 下的实际媒体文件

## 执行步骤
1. **ASSET_ACQUISITION**：Registry 命中资源先获取并校验 License；未命中且需外部下载时遵循 Execution Approval。
2. **ASSET_PRODUCTION** 按路由分派：
   - `REMOTION` → Motion Design Engine，可输出 FULL_SCENE / MOTION_CLIP / TRANSPARENT_OVERLAY / ANIMATED_TEXT / 3D_ELEMENT / BACKGROUND / PARTICLE_LAYER / TRANSITION_ASSET / INFOGRAPHIC / UI_COMPONENT / DECORATIVE_ELEMENT（v0.2 §30）
   - `THREE_D` → R3F / Drei / gltfjsx + 3D Registry（Poly Haven 等）
   - `REAL_FOOTAGE` → Footage Registry / Archive / 用户素材
   - `GENERATIVE_VIDEO` → 生成 **Video Production Packet**（Shot Purpose / Duration / Aspect / Subject / Environment / Composition / Camera / Lens / Lighting / Mood / Start-End Frame / Continuity / Negative Prompt / Post-production Plan，v0.2 §47），禁止只输出一句 Prompt
   - `JY_NATIVE` → 不产出独立 Asset，由剪映原生完成（简单字幕 / Ken Burns / B-roll）
3. 为每个新 Asset 落 `assets/A###.md`，填满 Asset Contract 关键字段。
4. 更新 `<project>/PROJECT_STATE.md` 与相关 Shot 的 asset 引用。

## 阶段状态变更
`ASSET_ACQUISITION` → `ASSET_PRODUCTION` → `TIMELINE_BUILD`

## Approval Gate
本工作流无 approval gate；高影响动作仍需 Execution Approval（大型素材下载、复杂 Motion、AI Video 生成包、3D 构建等，v0.2 §50）。

## Phase 1 现状
> 当前实现状态：skeleton。完整实现待 Phase 5（Motion / 3D / Sound Engine）与 Phase 6（Generative / Footage Pipeline）完成。具体的 module 在 `modules/asset-manager/`、`modules/video-prompt-builder/` 下开发。
> 涉及的能力路由（reuse_map 引用）：Remotion 官方 Skills（EXTERNAL_SKILL）、Onda / RemotionUI / Remotion Bits（PROVIDER）、R3F / Drei（PROVIDER）、FluidSynth（PROVIDER）、Freesound / Mixkit（RESOURCE_PROVIDER）。
> 禁止：实现本阶段范围外的功能（禁止真实 Render / 下载大型模型 / 生成视频）。
