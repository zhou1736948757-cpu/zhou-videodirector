# VISUAL_BIBLE — 模板

> 用途：`Style Director` 阶段（workflow: `workflows/style-direction.md`）的输出模板。
> 输出为 `<project>/VISUAL_BIBLE.md`——项目后续所有视觉决策的**最高约束之一**（Storyboard / Shot / Asset / QA 都必须对齐它）。
> 创建后进入 `VISUAL_BIBLE_REVIEW`（waiting_user）等待用户确认。
>
> 填写依据：`<project>/PROJECT_BRIEF.md` + `<project>/CREATIVE_DIRECTION.md`（必须）+ `<project>/references/REFERENCE_ANALYSIS.md`。
> Style 来源：`presets/` 6 个预设之一 / 多预设 Mix / 项目专属 Style（见 `workflows/style-direction.md`）。
> 语言：中文；枚举与技术术语英文大写。禁止空洞词（"高级""有冲击力"必须展开为什么）。

<!-- 使用规则
- 字段名以中文标签 + 英文 key 形式给出，与 schemas/visual-bible.schema.json 字段尽量对齐。
- 每个字段：先写结论，再写 1-2 句"为什么"（依据来自 Creative Direction 或 Reference Report）。
- Style Mix 用 "60% Style A + 30% Style B + 10% Style C" 形式表达视觉语言权重（语义权重，非数学混合）。
- 所有 negative 表述（Avoid / 不用 / 避免）必须具体，禁止"避免不好看的转场"这类无信息量写法。
-->

# 1. Style 声明

- **Style Name**：<风格名称，如 "minimal_spatial_tech" / "reality_paper_editorial" / 自定义名称>
- **Style Mix**：<如 "60% minimal_spatial_tech + 30% reality_paper_editorial + 10% documentary_archive">，并解释每个比例的视觉语言含义（谁负责底色、谁负责情绪、谁负责点缀）
- **Design Philosophy**：<一句设计信条，如 "信息先行，空间叙事，克制是最强的表达"；说明这条信条从哪条 Creative Direction 推出>

# 2. 视觉系统

- **Color System**：<主色 / 辅色 / 强调色 + 各自 HEX 或色域描述 + 用途边界；如 "黑白灰基底 + 单一强调蓝 #2D7FF9，强调色只用于数据与 CTA">；为什么这样选（依据）
- **Typography**：<字体族 / 层级 / 字重 / 用途边界，如 "标题 Sans-Serif 700、正文 400、数字等宽字体">；为什么
- **Composition**：<构图规则，如 "三分法 + 安全边距，信息元素靠左，视觉重心靠右">；为什么
- **Spacing**：<留白 / 间距系统，如 "8pt 网格，卡片内 24pt，区块间 48pt；大量留白承载呼吸感">；为什么
- **Grid**：<栅格系统，如 "12 列网格，内容区最大 1440px，移动端 4 列">；为什么
- **Depth**：<纵深策略，如 "两层深度：前景信息层 + 背景空间层，相机轻微视差">；为什么
- **Material**：<材质语言，如 "磨砂玻璃 / 哑光塑料 / 金属高光的具体使用位置">；为什么
- **Lighting**：<光照方案，如 "顶部柔光 + 单侧轮廓光，无硬阴影；产品段落用 45° 三点布光">；为什么

# 3. 镜头语言

- **Camera Language**：<相机运动词汇表，如 "推为强调、摇为连接、升降为揭示">；为什么
- **Motion Character**：<动效性格：速度基准 / 缓动曲线 / 节奏，如 "基础 300ms，ease-out 偏多，关键揭示用 ease-in-out">；为什么
- **Motion Intensity**：<动效强度档位说明，如 "常规段落 2/5，Hero 段落 4/5，永不超过 4.5/5">；为什么
- **Micro-motion**：<大量使用的精细微动，如 "hover 位移 2px、数据跳动 tick、卡片入场 8ms 偏移">；为什么（大量精细效果，少量显眼效果）
- **Transition Language**：<转场词汇表，如 "切 = 换章节，推近 = 深入细节，白闪 = 时间跳转">；为什么

# 4. 维度与素材

- **2D / 3D Balance**：<2D 与 3D 的边界，如 "信息层 2D，空间背景 2.5D，产品模型 3D；3D 只用于产品与空间隐喻">；为什么
- **AI Video Treatment**：<AI 生成镜头的处理规则，如 "只用于氛围 B-roll 与空间背景，不用来呈现关键信息；生成后统一调色">；为什么
- **Real Footage Treatment**：<真实素材规则，如 "保留胶片颗粒，统一 LUT，人物素材优先实拍">；为什么
- **Image Treatment**：<图片处理规则，如 "统一圆角 8px、轻微描边、悬停放大 1.02">；为什么

# 5. 文字与图形

- **Subtitle Style**：<字幕规范，如 "底部居中，最大 3 行，关键信息高亮 60%，字数 ≤ 16 字/行">；为什么
- **Graphic Elements**：<图形元素语言，如 "线性图标 1.5px、数据图表统一折线+柱状、装饰元素低透明度">；为什么
- **Texture · Grain**：<纹理与颗粒，如 "全片叠加 2% 胶片颗粒 + 轻微暗角，避免数字感">；为什么

# 6. Effect Philosophy（特效哲学）

> 三级原则（v0.2 §11 声音 / §36 动效同构）：**大量精细效果，少量显眼效果**。
> 每个 Level 给出本项目中的具体例子 + 为什么在这个位置用。

- **Level 1 — Invisible（大量）**：<本项目 Invisible 效果例子，如 "按钮微光、数值跳动、页面入场、滚动视差"，为什么它们贡献质感而不抢信息>
- **Level 2 — Narrative（按需）**：<本项目 Narrative 效果例子，如 "章节切换的卡片展开、数据增长的地图流动"，为什么它们承担叙事功能>
- **Level 3 — Hero（极少量）**：<本项目 Hero 效果例子，如 "Payoff 时刻的记忆宫殿全景构建、Logo 收尾"，为什么只在 1-2 处使用>
- **Hero Effect Policy**：<Hero 效果的使用条件，如 "全片不超过 2 处；必须对应 Creative Direction 的 Payoff / Memory Point；出现前有静默铺垫">；为什么
- **Avoid List**：<具体 Avoid 清单，如 "避免 strong glitch / 避免 3D 旋转 logo / 避免每 5 秒一个转场 / 避免默认字体（PingFang 常规直出）">；每一条给一句为什么

<!-- 评审提示
用户批准前不进入下一阶段。revision_requested 时回到 STYLE_DIRECTION，旧 Decision 标记 superseded。
本文件字段与 schemas/visual-bible.schema.json 的 18 字段存在映射差异（模板更细），映射关系见 workflows/style-direction.md。
-->
