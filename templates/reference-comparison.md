# REFERENCE_COMPARISON — 模板

> 用途：多参考对比报告（Phase-2 §21 / §22）。当 reference 数量 ≥ 2 时，在 `REFERENCE_ANALYSIS.md` 之外另写本文件。
> 解决的问题：参考片之间的**共同点**（= 用户审美的可靠信号）、**冲突点**（如何裁决）、**各自最强项**（学什么）、
> **哪些是个性哪些可学**，以及"哪些不能混"。
> 输入：每份 reference 的 Normalized Reference Output（见 templates/reference-analysis.md 第 3 节）。
> 目标行数：40-100 行。输出语言：中文；枚举 / 技术术语英文大写。

<!-- 字段块约定：每字段两行 —— 第 1 行 `# <字段>: <占位>`，第 2 行中文说明；list 为空写 [] -->

## 1. Common Patterns

> 用途：跨 reference 共同出现的特征。共同特征优先级最高，直接进入 Reusable Rules 候选。
> 字段：Common-NN（每条一句话 + 来源）。

# Common-001: <跨参考共同特征一句话>
   出现于哪些参考（REF-A / REF-B / ...）与证据（如 @t:mm:ss）。
# Common-002: <跨参考共同特征一句话>
   出现于哪些参考与证据。
# Common-003: <跨参考共同特征一句话>
   出现于哪些参考与证据（可增删）。

## 2. Conflicting Patterns

> 用途：参考间相互冲突的特征。冲突不抹平，必须给出裁决。
> 裁决优先级：用户偏好 > Creative Direction > 与项目约束不冲突者先采用 > 分阶段各用各的。
> 字段：Conflict-NN（冲突双方）+ Resolution。

# Conflict-001: <REF-A 主张 X | REF-B 主张 Y>
#   Resolution: <裁决结果 + 理由>
   冲突裁决一句话，并写明是否写入 R-NN 或 AVOID。
# Conflict-002: <REF-A 主张 X | REF-B 主张 Y>
#   Resolution: <裁决结果 + 理由>
   冲突裁决一句话（可增删）。

## 3. Best Traits of Each

> 用途：每个 reference 的最强项（只此一家、别处学不到的）。字段：REF-X Best Trait（每参考一条，可多条）。

# REF-A Best Trait: <该参考最强的一项能力或特征>
   为什么强 + 用在项目哪里最值。
# REF-B Best Trait: <该参考最强的一项能力或特征>
   为什么强 + 用在项目哪里最值。

## 4. Traits to Avoid

> 用途：所有 reference 中不该复用的特性汇总（与 REFERENCE_ANALYSIS.md 第 10 节呼应）。
> 字段：Avoid-NN（每条一句话 + 来源）。

# Avoid-001: <不要复制的特性 + 来源参考>
   为什么不要复制。
# Avoid-002: <不要复制的特性 + 来源参考>
   为什么不要复制（可增删，保持 ≥ 2 条）。

## 5. Creator-specific vs Generalizable

> 用途：区分"这个创作者的个性签名"与"可迁移的通用规律"。只有 Generalizable 才进 R-NN。
> 字段：Creator-specific（列表）/ Generalizable（列表）。

# Creator-specific: [<REF-A 的个人风格特征>, <REF-B 的个人风格特征>]
   依赖特定创作者 / 品牌 / 题材才成立的特性，不迁移。
# Generalizable: [<可学规律 1>, <可学规律 2>, <可学规律 3>]
   跨项目可复用的规律，进入 R-NN 候选。

## 6. Recommendations

> 用途：最终学习清单：A 该学什么、B 该学什么、哪些不能混。
> 字段：REF-A Should Borrow / REF-B Should Borrow / Do Not Mix。

# REF-A Should Borrow: [<具体学 A 的哪几点>]
   逐条指向第 3/5 节，标注对应 R-NN（如有）。
# REF-B Should Borrow: [<具体学 B 的哪几点>]
   逐条指向第 3/5 节，标注对应 R-NN（如有）。
# Do Not Mix: [<A 与 B 不能同时用的组合>]
   明确哪些组合会打架（如"A 的克制节奏 + B 的炫技特效"），给出取舍建议。
