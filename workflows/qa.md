---
workflow_id: WF-012
name: QA 与变更复审
stage_ids: [PREVIEW, QA, CHANGE_REVIEW]
requires_approval: [QA]
phase1_status: skeleton
---

# QA 与变更复审（QA / Change Review）

## 目标
对成片做 **四层 QA**（Technical / Visual / Editorial / Sound），发现问题通过 `CHANGE_REVIEW` 回打相关阶段修正，直至用户批准进入 Final。

## 触发时机
`TIMELINE_REVIEW` 已批准并产出 Preview 后触发。

## 输入
- `<project>/timeline/`、`<project>/assets/`、`<project>/previews/`
- `<project>/STORYBOARD.md`、`<project>/VISUAL_BIBLE.md`、`<project>/AUDIO_DIRECTION.md`

## 输出（项目文件）
- `<project>/previews/` — Preview 产物
- `<project>/QA_REPORT.md` — 四层 QA 结果（模板 `templates/qa-report.md`）

## 执行步骤
1. **PREVIEW**：生成 Preview，供用户与 QA 使用。
2. **Technical QA**：代码、素材、Render、格式、Asset Contract 元数据完整性。
3. **Visual / Motion QA**：审美、Motion、特效是否违反 Visual Bible 与 Avoid List。
4. **Editorial QA**：故事、节奏、信息密度是否符合 Editorial Direction。
5. **Sound QA**：音乐、SFX、响度、同步、Ducking、是否过度（对照 AUDIO_DIRECTION.md）。
6. 汇总 `<project>/QA_REPORT.md`，推进到 `QA`（waiting_user）。

## 阶段状态变更
`PREVIEW` → `QA` →（approve 后）`FINAL_EDIT` → `FINAL_RENDER` → `COMPLETE`

QA 未通过 → `CHANGE_REVIEW`：走 `review_revision` 规则回打相关阶段（visual 问题 → `VISUAL_BIBLE_REVIEW` / `STORYBOARD_REVIEW`；时间线问题 → `TIMELINE_REVIEW`；资产问题 → 对应 ASSET 阶段），修正后重新走 QA。

## Approval Gate
`QA` 需要用户确认：
- approved → 进入 Final Edit / Final Render
- revision_requested → 进入 `CHANGE_REVIEW` 回打，修正后重跑 QA

## Phase 1 现状
> 当前实现状态：skeleton。完整实现待 Phase 8（Subagents + QA + E2E）完成。具体的 module 在 `modules/qa/` 下开发。
> 涉及的能力路由（reuse_map 引用）：审美与反模板参考 `taste-skill`（KNOWLEDGE_ADAPTER）、`video-shotcraft` 的 aesthetic_qa；回打规则见 `state-machine.json` 的 `change_review_post_qa` 规则。
> 禁止：实现本阶段范围外的功能（禁止实现 QA Engine / E2E 测试）。
