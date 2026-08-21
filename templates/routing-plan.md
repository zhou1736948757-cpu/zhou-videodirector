# ROUTING_PLAN — 模板

> 用途：Routing 阶段的人类可读总输出（Phase-3 §51）。**给 `ROUTING_REVIEW` 审批门的人看**（§68-70），
> 不是给机器看的——机器细节见 `routing/S###.yaml` 与 `layers/S###.yaml`，本文件只做追溯。
>
> §70 原则：**只列 high-cost / high-risk / hybrid / AI-generated / large-3D / low-confidence / baked 的 Shot**。
> 普通 photo+subtitle 类简单 Shot 不浪费用户注意力，无需逐镜解释。
>
> 生成引擎：`modules/router/router.py`（`build_routing_plan`）；落地路径：`<project>/ROUTING_PLAN.md`。
> 使用时机：`SHOT_ROUTING` → `LAYER_ROUTING` 完成后生成；`ROUTING_REVIEW` 批准后作为 `RESOURCE_PLANNING` 依据。
> 语言约定：正文中文；枚举/技术术语英文大写（REMOTION / GENERATIVE_VIDEO / JY_NATIVE / HYBRID …）。

---

## Executive Summary

> 给审批人 30 秒看到全貌：镜头总数、路由分布、需要关注的数量（HYBRID 数 / 原型数 / 低置信度数 / BAKE 层数）。

- 镜头总数：8；路由分布：REMOTION×3, GENERATIVE_VIDEO×2, HYBRID×2, JY_NATIVE×1。
- HYBRID 需 Layer 拆分：2；需原型验证：1；低置信度（<0.55）：1；建议 BAKE：3 层。

<!-- 生成规则
1. 逐项与 routing/S###.yaml 汇总对齐，禁止手填。
2. 只保留关注点数字，不给每个普通 Shot 列细节（§70）。
-->

---

## Route Distribution

> §52 示例式分布表。**数量不是质量指标**：REMOTION 多不代表质量高，JY_NATIVE 多也不代表偷懒——
> 每个 Route 决策都必须能回到 12 项因子与 `reason`；分布只用于让审批人快速看到技术构成。

| Route | Count | Shots |
|---|---|---|
| REMOTION | 3 | S001, S003, S004 |
| GENERATIVE_VIDEO | 2 | S002, S006 |
| HYBRID | 2 | S005, S008 |
| JY_NATIVE | 1 | S007 |

---

## Hybrid Shots

> HYBRID 强制 Layer 拆分（§22），每条给出原因（引用 `decision_summary`）。

| Shot | Reason |
|---|---|
| S005 | 真实街道黄昏环境 + 招牌文字必须精确；拆 BACKGROUND（GENERATIVE_VIDEO）+ TYPOGRAPHY（REMOTION）+ SUBTITLE（KEEP_EDITABLE） |
| S008 | 3D 产品 + 轨道运镜 + 字幕层；拆 3D_OBJECT（THREE_D）+ SUBTITLE（JY_NATIVE） |

---

## High-risk Shots

> §70：只列 high-cost / high-risk / hybrid / AI-generated / large-3D / low-confidence 的 Shot。
> 普通 photo+subtitle 简单 Shot 不在这里。

| Shot | Confidence | Risk |
|---|---|---|
| S006 | 0.42 (LOW) | 抽象概念，无具象对象，低置信度需 Review |
| S002 | 0.71 (MEDIUM) | AI 高熵街景，生成成本与一致性不确定 |

---

## Prototype-required Shots

> confidence < 0.80（MEDIUM / LOW）时的原型验证计划（§40-43）。

| Shot | Route | Prototype | Goal |
|---|---|---|---|
| S006 | GENERATIVE_VIDEO | AI_IMAGE_CONCEPT | 先出概念图锁定氛围与一致性，再决定是否进入视频生成 |

---

## Editability Strategy

> §57 三级覆盖。对 footage / subtitles / titles / motion assets / AI clips / music / SFX / images
> 逐项标记 `KEEP_EDITABLE / ASSET_REPLACEABLE / BAKED`。

| Asset 类别 | 策略 | 说明 |
|---|---|---|
| footage | KEEP_EDITABLE | B-roll / 实拍素材保持时间线可调时长与裁剪 |
| subtitles | KEEP_EDITABLE | 字幕必须 KEEP_EDITABLE（硬约束 §36） |
| titles | KEEP_EDITABLE | 标题 / 文字层不 bake，文案随时可改 |
| motion assets | BAKED | 连续 Motion（continuity_group 非空）→ 渲染为单一 Asset（§56） |
| AI clips | ASSET_REPLACEABLE | AI 片段内部 Bake，但整个片段可替换重生成 |
| music | KEEP_EDITABLE | 音乐轨道保持可替换可调速 |
| SFX | KEEP_EDITABLE | SFX 独立轨道，音量 / 时间点可调 |
| images | KEEP_EDITABLE | 照片 / 图片的时长、叠放、缩放保持时间线可调 |

<!-- 生成规则
1. 先按类别给全片统一基线策略，再列出与基线不同的 BAKE / ASSET_REPLACEABLE 例外层（引用 layers/S###.yaml）。
2. BAKE 必须写明理由（连续 Motion / 整体渲染成本），禁止默认 Bake（§35 Human Editable 是硬要求）。
-->

---

## Continuity Groups

> §31 + §56：同一 continuity_group 的一组镜头建议作为一个连续 Motion Asset 一起渲染，
> 禁止为可编辑性硬拆。**Remotion Asset Boundary**：一次渲染一个 Asset（如 `S018-A01 memory-card-transformation.mov`），
> 而不是拆成 card.mov / arrow.mov / text.mov / node.mov。

| Group | Shots | Route | Asset Boundary |
|---|---|---|---|
| CG001 | S001–S002 | REMOTION | CG001-A01 motion-sequence.mov |

---

## Potential Production Bottlenecks

> 高成本 / 长耗时 / 多 Producer 对齐风险的环节，供 `RESOURCE_PLANNING` 排期参考。

| Shot | Route | Bottleneck |
|---|---|---|
| S002 | GENERATIVE_VIDEO | AI 生成成本与不确定性高，需 Prompt / Seed 迭代 |
| S008 | HYBRID | 多 Producer 并行 + 合成对齐成本 |

---

## User Decisions Required

> §70-73：需要用户拍板的事项（低置信度 Review / 原型批准 / Override 确认），
> 每一条对应 `ROUTING_REVIEW` 中的一个决策问题。

| Shot | Route | Confidence | Question |
|---|---|---|---|
| S006 | GENERATIVE_VIDEO | 0.42 | 低置信度路由需要 Review（决策理由见 routing/S006.yaml） |
| S002 | GENERATIVE_VIDEO | 0.71 | 批准原型验证（AI_IMAGE_CONCEPT）后进入生产？ |

---

## 提交前自检清单

- [ ] 9 节齐全：Executive Summary / Route Distribution / Hybrid Shots / High-risk Shots / Prototype-required Shots / Editability Strategy / Continuity Groups / Potential Production Bottlenecks / User Decisions Required
- [ ] Route Distribution 表带「数量不是质量指标」提示
- [ ] High-risk Shots 只列 high-cost / high-risk / hybrid / AI-generated / large-3D / low-confidence / baked 的 Shot，普通 photo+subtitle 不出现（§70）
- [ ] Editability Strategy 覆盖 footage / subtitles / titles / motion assets / AI clips / music / SFX / images 八类（§57）
- [ ] 与 `routing/S###.yaml`、`layers/S###.yaml` 数据一致（数量、Route、Shot ID、confidence）
- [ ] 所有数字来自引擎输出，禁止手填（生成规则内嵌于各节）

<!-- 生成/修订由 workflows/routing.md 驱动；`ROUTING_REVIEW` 批准后进入 RESOURCE_PLANNING。 -->
