# CREATIVE_DIRECTION — 模板

> 用途：`Creative Director` 阶段（workflow: `workflows/creative-direction.md`）的输出模板。
> 回答两个问题：**视频讲什么**、**为什么值得看**。本文件只讲创意，不写任何视觉/技术实现（Director Before Engineer）。
> 输出为 `<project>/CREATIVE_DIRECTION.md`，创建后进入 `CREATIVE_REVIEW`（waiting_user）等待用户确认。
>
> 填写依据：`<project>/PROJECT_BRIEF.md`（必须）+ `<project>/references/REFERENCE_ANALYSIS.md`（如存在）。
> 语言：中文；枚举与技术术语英文大写。禁止出现"高级 / 有冲击力"这类不解释理由的空洞词。

<!-- 使用规则
- 每个字段先写结论，再给一句"为什么"（引用 Brief 或 Reference Report 中的依据）。
- Creative Options 建议 2-3 个，复杂度低时 2 个即可，不强凑 3 个。
- 所有选项必须可被用户理解：Concept 一句话 + Why it works 一段。
- 不暴露私有 chain-of-thought；推荐理由引用可公开的依据（Brief / Reference）。
-->

# 1. 创意核心

- **Core Idea**：<一句话说清这个视频最核心的主张，如"让观众在 90 秒内理解并信任某 AI 笔记产品的记忆能力">
  - 为什么：<引用 Brief 中的项目目的 / 目标用户，说明为什么是这个主张，如"Brief 明确受众是对信息焦虑的深度工作者">
- **Viewer Promise**：<观众看完后应该带走的一个承诺，如"看完你会知道你的记忆为什么值得被保存">
  - 为什么：<这条承诺与用户痛点的对应关系>
- **Hook**：<前 3-5 秒抓住注意力的具体设计，必须可执行，如"开场一句反问 + 一屏倒计时的记忆消失画面">
  - 为什么：<引用 Reference Report 的 Editorial 分析（如"参考片平均 3.2s 内给出 Pattern Interrupt"）>
- **Central Tension**：<全片围绕的核心矛盾，如"记忆被遗忘 vs 记忆被 AI 找回">
  - 为什么：<矛盾来源，如 Brief 中的用户核心顾虑>
- **Creative Angle**：<切入角度，避免行业陈词滥调，如"不讲功能清单，讲记忆如何塑造你是谁">
  - 为什么：<与竞品/常见做法的差异点>

# 2. 叙事装置

- **Narrative Device**：<叙事载体，如"一个普通人的一天 / 时空对照 / 数据可视化故事线">
  - 为什么：<该装置为什么适配 Core Idea 与目标平台节奏>
- **Emotional Direction**：<观众情绪曲线，从什么到什么的转变，如"好奇 → 共鸣 → 释然 → 行动"；每段情绪必须写触发它的叙事原因>
  - 为什么：<情绪峰值位置对应 Payoff，避免无根据的情绪堆叠>

# 3. 揭示与收尾

- **Reveal Strategy**：<信息揭示顺序与节奏，如"先展示痛点，再揭示产品能力，最后揭示底层原理"；说明每一步为什么在这个位置揭示>
- **Payoff**：<全片最高情绪点的具体画面/情节，如"产品把十年日记按主题重构的瞬间"；必须与 Hook 呼应>
- **Memory Point**：<观众离场后记住的那个单点，如"一句话：记忆不丢失，只是需要被整理">
- **Closing Impression**：<最后一帧/最后一句话留给观众的感受，如"留下行动邀请 + 一句余韵"；说明为什么这样收尾能让 Memory Point 落地>

# 4. Creative Options（创意选项）

> 规则：产出 2-3 个完整 concept，**不一定凑 3 个**——视需求复杂度而定。每个 option 的 Strength / Weakness / Risk 必须具体，禁止空洞表述。

## Option A：<概念名>
- **Concept**：<一句话概念，如"Memory Palace：把产品能力具象成一座可走进去的记忆宫殿">
- **Why it works**：<为什么这个概念能成立，引用 Brief 的目标用户/平台/时长>
- **Strength**：<1-2 条真实优势，如"概念空间大，便于用 3D/空间叙事承载，视觉辨识度极高">
- **Weakness**：<1-2 条真实劣势，如"制作成本高，需要较强的空间建模能力">
- **Best for**：<最适配的场景，如"强调产品 AI 能力、目标用户为年轻科技人群">
- **Risk**：<如"宫殿隐喻可能让非目标用户觉得抽象" + 缓解方式>

## Option B：<概念名>
- **Concept** / **Why it works** / **Strength** / **Weakness** / **Best for** / **Risk**：<同上结构>

## Option C：<概念名（可选）>
- **Concept** / **Why it works** / **Strength** / **Weakness** / **Best for** / **Risk**：<同上结构>

# 5. 推荐（Recommendation）

> ⭐ **推荐：Option X（<概念名>）**
>
> 理由（引用可公开依据）：
> - **Brief 依据**：<引用 PROJECT_BRIEF 中的关键条目，如"项目目的为建立信任，时长 90s，无真人出镜">
> - **Reference 依据**：<引用 REFERENCE_ANALYSIS 中的可复用规则，如"参考片以空间隐喻承载抽象概念，观众留存最高">
> - **风险控制**：<说明 Option X 的 Risk 为什么可接受/如何缓解>
> - **与其它 Option 的取舍**：<一句话说明为什么不选 A/B/C>
> - **落地提示**：<给后续 Style / Sound / Editorial 阶段的输入，如"下一阶段需要空间感的 Visual Bible 与克制的音色">

<!-- 评审提示
用户批准前不进入下一阶段。若 revision_requested，新增 Decision 并 Supersedes 旧决定，本文件保持 append-only 修订说明。
-->
