---
workflow_id: WF-009
name: 资源规划
stage_ids: [RESOURCE_PLANNING, PRODUCTION_PLAN_REVIEW]
requires_approval: [PRODUCTION_PLAN_REVIEW]
phase1_status: skeleton
---

# 资源规划（Resource Planning）

## 目标
基于路由结果，通过 Resource Registry 的三级加载为每个 Layer / Asset 决定"已有资源还是新生产"，形成 **Asset Plan + Sound Plan → PRODUCTION_PLAN**，交用户批准后进入生产。

## 触发时机
`LAYER_ROUTING` 完成后触发。

## 输入
- `<project>/STORYBOARD.md`、`<project>/shots/`（含 route）
- `schemas/asset.schema.json`、`schemas/audio-direction.schema.json`

## 输出（项目文件）
- `<project>/PRODUCTION_PLAN.md`：
  - Asset Plan — 每个所需 Asset 的 producer / type / format / resolution / fps / duration / 来源（Registry 命中 or 新生产）
  - Sound Plan — Music Route + SFX Provider + Ambience 获取方式与 License 要求

## 执行步骤
1. **Registry 三级加载**（v0.2 §40-43）：LEVEL 0 Catalog（id/name/type/tags/summary/best_for/preview）→ 需要时 LEVEL 1 Detail（parameters/license/dependencies/compatibility/size/usage/limitations）→ 确认使用后 LEVEL 2 Source（fetch/clone/download/install）。
2. 逐 Layer 决策：Registry 是否命中；未命中则进入 Resource Learning（Registry → Online Search → License Check → Metadata → Preview → 加入 Registry，v0.2 §44）。
3. 制定 Asset Plan（含 replaceable / editable 标记）。
4. 制定 Sound Plan：Music Route（LIBRARY / PROCEDURAL / GENERATIVE / HYBRID）+ SFX Provider + Ambience。
5. 汇总写入 `<project>/PRODUCTION_PLAN.md`。
6. 推进到 `PRODUCTION_PLAN_REVIEW`（waiting_user）。

## 阶段状态变更
`RESOURCE_PLANNING` → `PRODUCTION_PLAN_REVIEW` →（approve 后）`ASSET_ACQUISITION`

## Approval Gate
- approved → 进入 asset-production（ASSET_ACQUISITION）
- revision_requested → 回到 `RESOURCE_PLANNING` 调整计划

## Phase 1 现状
> 当前实现状态：skeleton。完整实现待 Phase 4（Resource Registry）完成。具体的 module 在 `modules/resource-router/`、`modules/asset-manager/` 下开发。
> 涉及的能力路由（reuse_map 引用）：Registry 分类见 `registry/`（motion/transition/3d/texture/hdri/footage/image/sfx/music/soundfont/fonts/references）；设计参考 Remotion Bits 与 Poly Haven Public API 的"索引 + 按需获取"模式（v0.2 §70）。
> 禁止：实现本阶段范围外的功能（禁止实际下载资源 / 填充完整 Registry）。
