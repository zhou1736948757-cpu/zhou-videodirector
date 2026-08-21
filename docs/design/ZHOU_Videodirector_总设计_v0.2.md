# ZHOU_Videodirector
## AI 视频导演与可编辑生产系统 — 总设计 v0.2

# 0. 项目最终定位

`ZHOU_Videodirector` 不是单纯的 Remotion Skill，也不是“一句话自动生成成片”的视频机器人。

它是一个：

> **以导演决策为核心，能够调度 Motion Design、3D、真实素材、AI Video、Sound Design 与可编辑时间线的视频生产总控 Skill。**

系统最终负责：

```text
IDEA
↓
理解需求
↓
创意设计
↓
风格设计
↓
叙事设计
↓
分镜设计
↓
Shot / Layer 技术路由
↓
素材搜索与制作
↓
Remotion / 3D / AI Video / Footage
↓
Sound Design
↓
剪映可编辑时间线
↓
人工 + AI 联合编辑
↓
QA
↓
Final
```

核心不是“一次生成最终 MP4”。

而是：

> **生成一个既能自动化生产，又能由人继续接手的视频工程。**

---

# 1. 整个系统最核心的生产哲学

最终我们不再认为：

```text
Remotion = 视频制作软件
```

而是：

```text
Remotion
≈ AI-controlled After Effects
≈ Motion Design Engine
```

主要承担：

- Motion Graphics
- Typography
- UI Animation
- Infographic
- Chart
- Map
- Timeline
- 2D / 2.5D
- Three.js / 3D
- Particle
- Shader
- Complex Transition
- Animated Overlay
- Transparent Asset
- Complex Motion Scene

它可以输出：

```text
完整 Scene
小动画片段
透明 Overlay
3D 元素
动态图标
标题动画
背景动画
粒子素材
信息图动画
转场素材
```

而不要求每次都输出完整 Scene。

---

# 2. 剪映是 Final Editable Timeline

这一点现在应该成为整个系统的核心之一。

我们不是：

```text
Remotion
↓
Final MP4
```

而更多时候是：

```text
Remotion / AI Video / Footage / Images / Audio
                        ↓
                    Asset Package
                        ↓
                pyJianYingDraft
                        ↓
                   剪映草稿
                        ↓
                  人工 + AI 编辑
                        ↓
                      Final
```

剪映承担：

- 普通剪辑
- Shot 顺序
- Shot 时长
- B-roll
- 图片
- 字幕
- 简单关键帧
- 普通转场
- 简单 Animation
- 音乐
- SFX
- Voice-over
- Ambience
- Volume Automation
- 简单 Overlay
- 最终人工微调

最大的意义是：

> **AI 可以编辑，人也可以编辑。**

这是纯 Remotion Pipeline 不具备的优势。

---

# 3. 最终生产系统分成四层

```text
┌────────────────────────────┐
│          DIRECT            │
│     创意 / 导演 / 分镜       │
└─────────────┬──────────────┘
              ↓
┌────────────────────────────┐
│         GENERATE           │
│ Remotion / 3D / AI / 素材   │
└─────────────┬──────────────┘
              ↓
┌────────────────────────────┐
│           EDIT             │
│ pyJianYingDraft / 剪映时间线 │
└─────────────┬──────────────┘
              ↓
┌────────────────────────────┐
│          FINISH            │
│ Sound / Color / QA / 人工   │
└────────────────────────────┘
```

---

# 4. Project Intake / Grill Me

项目开始时，用户甚至只需要给一个模糊想法：

> 做一个两分钟介绍某产品的视频。

或者：

> 做一个八分钟科技科普。

系统先确定：

- 视频目的
- 内容主题
- 目标用户
- 发布平台
- 长宽比
- 时长
- 是否旁白
- 是否真人
- 是否使用 AI Video
- 是否使用 3D
- 是否已有素材
- 是否已有参考视频
- 是否已有脚本
- 是否已有产品 UI
- 是否需要最终可编辑剪映工程
- 制作精度
- 对时间 / 成本 / 质量的偏好

通过 Grill Me 补足影响导演决策的信息。

但：

> **不能无限提问。**

达到可以进行创意设计的程度就停止。

---

# 5. Delivery Mode

项目开始时还应该确认最终交付方式。

支持：

```text
FINAL_VIDEO_ONLY

EDITABLE_PROJECT

BOTH
```

多数项目推荐：

```text
BOTH
```

最终交付：

```text
final.mp4

剪映工程

Remotion Source

Motion Assets

AI-generated footage

3D assets

Images

Music

SFX

Voice-over

Storyboard

Project Memory
```

这样整个项目未来仍然可以继续修改。

---

# 6. Reference Analysis

支持用户提供：

- YouTube
- Bilibili
- 本地视频
- 广告
- 产品片
- 科普
- Motion Design
- 电影片段

优先调用已有成熟视频分析 Skill，而不是自己重新造视频下载、字幕、抽帧系统。

Reference Analyzer 分析：

## Visual

- 构图
- 色彩
- 字体
- 排版
- 留白
- 光线
- 材质
- Depth

## Motion

- 平均动画速度
- Easing
- Spring
- Camera
- Parallax
- Micro Motion
- Motion Blur
- Transition

## Editorial

- Shot 长度
- 信息密度
- Hook
- Pattern Interrupt
- Pacing
- Chapter
- Payoff
- B-roll

## Audio

- Music density
- SFX frequency
- Impact
- Whoosh
- UI sounds
- Ambience
- Music transition
- Ducking
- Silence

最后输出：

```text
REFERENCE_ANALYSIS.md
```

重点：

> **学习规律，不逐镜复制。**

---

# 7. Creative Director

负责：

> **视频讲什么、为什么值得看。**

而不是马上考虑怎么实现。

负责：

- Hook
- Core Idea
- Viewer Tension
- Creative Angle
- Emotional Direction
- Core Message
- Product Value
- Narrative Promise
- Reveal
- Payoff

输出：

```text
CREATIVE_DIRECTION.md
```

然后等待用户确认。

---

# 8. Style Director

Style Director 根据：

```text
Project
+
Creative Direction
+
Reference
+
Platform
+
Audience
```

推荐 Style。

目前内置至少六类。

## Minimal Spatial Tech

固定选项之一。

特点：

- Minimal
- Spatial UI
- Editorial UI
- 大量留白
- 黑白灰
- 少量强调色
- 信息结构变形
- Micro Motion
- 克制 Camera
- 高级但不过度华丽

## Reality × Paper Editorial

固定选项之一。

特点：

```text
Photoreal Environment
+
Paper-cut Characters / Objects
+
2.5D
+
Editorial Graphic
+
Realistic Lighting
```

这只是一个普通 Style Option。

**不设默认优先级，也不建立 Personal DNA。**

另外保留：

- Cinematic Product
- Editorial Explainer
- Documentary / Archive
- Kinetic Typography / Graphic

Style Director 也可以根据 Reference 创建新的临时 Style。

并允许：

```text
60% Style A
30% Style B
10% Style C
```

作为表达视觉权重的方式。

---

# 9. Visual Bible

Style 确认以后形成：

```text
VISUAL_BIBLE.md
```

至少包含：

- Color
- Typography
- Composition
- Whitespace
- Motion Character
- Camera Language
- Lighting
- Material
- Depth
- 2D / 3D
- Footage Treatment
- AI Video Treatment
- Image Treatment
- Subtitle
- Transition
- Effect Philosophy
- Avoid List

Visual Bible 是整个项目后面的视觉最高约束之一。

---

# 10. Sound Direction

新增正式：

# Sound Design Layer

声音不再只是最后加 BGM。

Sound Direction 和 Visual Direction 同等进入设计阶段。

负责：

- Music direction
- SFX language
- Ambience
- UI sound
- Motion sound
- Foley
- Impact
- Riser
- Whoosh
- Sonic Motif
- Silence
- Voice-over balance

最终生成：

```text
AUDIO_DIRECTION.md
```

---

# 11. Sound Design 哲学

和 Motion 类似。

不是：

> 每个地方都放明显音效。

而是：

> **Every important visual action should receive intentional audio consideration.**

分三级。

## Level 1 — Invisible Audio

大量使用：

- tiny click
- soft tick
- micro whoosh
- ambience
- subtle texture
- tiny tonal cue
- room tone

这些主要贡献“高级感”。

## Level 2 — Narrative Sound

例如：

- card expansion
- map movement
- page movement
- digital process
- data pulse
- camera pass
- transition

## Level 3 — Hero Sound

少量：

- Bass hit
- Major impact
- Large riser
- Logo sonic identity
- Climax transition

---

# 12. 音效 Resource Provider

Sound Registry 第一版至少考虑：

```text
@remotion/sfx
Google Material Sound Resources
Freesound
Mixkit
Kenney
其他合法 SFX Provider
```

统一进入：

```text
SFX Registry
```

而不是让 Agent 每次逐网站重新寻找。

---

# 13. Music Provider

音乐分三条路线：

```text
LIBRARY_MUSIC

PROCEDURAL_MUSIC

GENERATIVE_MUSIC
```

以及：

```text
HYBRID_MUSIC
```

---

# 14. Library Music

来源可包括：

- Mixkit
- Openverse
- FMA
- CC0 Music Collections
- Internet Archive
- 其他许可明确的音乐来源

Registry 保存：

- Mood
- BPM
- Energy
- Instrumentation
- Vocal
- Duration
- Build
- Narration friendly
- License
- Preview

---

# 15. Procedural Music Engine

新增：

```text
MIDI Composer
↓
FluidSynth
↓
SoundFont
↓
WAV
```

主要用于：

- Intro
- Outro
- Logo Sting
- Chapter Sting
- Minimal Background
- Short Motif
- Shot-sync music

例如：

```text
Visual Beat
↓
自动生成 MIDI event
↓
FluidSynth render
↓
进入剪映
```

SoundFont 也进入 Resource Registry。

第一阶段至少可以准备：

```text
General-purpose SoundFont

Quality SoundFont
```

未来再扩充：

- Piano
- Orchestral
- Electronic
- Lo-fi
- Retro
- Cinematic

---

# 16. Editorial Director

尤其服务长视频。

负责：

- Narrative Arc
- Information Hierarchy
- Chapter
- Pacing
- Hook
- Setup
- Payoff
- Pattern Interrupt
- Joke
- B-roll coverage
- Visual breathing room
- Recap

目标：

> 不是每句旁白都做复杂动画。

而是决定：

```text
这段照片即可

这段地图

这段 Timeline

这段 Remotion

这段 3D

这段真实素材

这段 AI Video

这里留一点视觉休息
```

---

# 17. Storyboard Engine

视频拆成：

```text
Scene
↓
Shot
↓
Layer
↓
Asset
```

这四级必须明确。

---

# 18. Scene

更大的叙事单元。

例如：

```text
Chapter 2
Why AI needs memory
```

---

# 19. Shot

一个连续编辑单元。

至少记录：

- ID
- Duration
- Narrative Purpose
- Voice-over
- Text
- Visual
- Motion
- Camera
- Audio
- Transition
- Route
- Assets
- Approval

---

# 20. Layer

一个 Shot 不一定只有一种生产技术。

例如：

```text
S025
AI Memory Museum
```

内部：

```text
BACKGROUND
→ AI VIDEO

MEMORY CARDS
→ REMOTION

3D DEPTH
→ THREE.JS

PARTICLES
→ REMOTION

TYPOGRAPHY
→ REMOTION

MUSIC
→ PROCEDURAL

AMBIENCE
→ SFX LIBRARY

ASSEMBLY
→ JIANYING
```

因此 Router 实际上是：

```text
Shot Router
↓
必要时
Layer Router
```

---

# 21. Shot Capability Router

一级路由：

```text
REMOTION

THREE_D

REAL_FOOTAGE

GENERATIVE_VIDEO

JY_NATIVE

HYBRID
```

`JY_NATIVE` 表示：

> 这个镜头没必要做成 Remotion Asset，剪映原生就够。

例如：

- 图片 Ken Burns
- 普通照片切换
- 简单字幕
- 普通 B-roll
- 基础缩放
- 简单转场

---

# 22. Remotion Route

适合：

- 高结构化
- 高准确性
- 数学可描述 Motion
- UI
- Typography
- Data
- Map
- Chart
- Complex Motion Graphic
- Continuous transformation
- 精确时间
- 频繁修改

---

# 23. Three.js Route

适合：

- 产品模型
- 芯片
- 机器
- 服务器
- 空间
- 爆炸图
- Camera orbit
- 3D UI
- Structure visualization

底层优先：

```text
@remotion/three
React Three Fiber
Drei
Postprocessing
gltfjsx
```

---

# 24. Real Footage Route

有真实素材时优先使用。

包括：

- Archive
- NASA
- News
- Public Domain
- City
- Nature
- Product footage
- Documentary footage

---

# 25. Generative Video Route

优先处理：

- 真人
- 现实环境
- 高 Scene Entropy
- 人群
- 自然运动
- 头发
- 衣服
- 烟
- 水
- 云
- 植物
- 复杂光照
- Cinematic atmospheric shot

---

# 26. JY Native Route

适合：

- 普通剪辑
- 简单关键帧
- Ken Burns
- 图片平移
- 普通缩放
- 字幕
- B-roll
- 普通 Overlay
- 音频
- 简单 Transitions

尽量不要为了一个非常普通的动作创建 Remotion Component。

---

# 27. Hybrid Route

大量高级 Shot 最终应该是 Hybrid。

例如：

```text
AI Background
+
Remotion Overlay
+
3D Product
+
剪映 Text
+
Sound Design
```

---

# 28. Scene Entropy

Router 需要正式使用：

```text
Scene Entropy
```

表示画面在制作意义上的复杂度。

低：

```text
纯背景
UI
简单对象
```

高：

```text
城市
人群
植物
大量反射
复杂自然环境
真实房间
```

一般：

```text
High Scene Entropy
+
High Photorealism
+
Organic Motion
→ AI Video / Footage
```

---

# 29. Router 判断指标

至少：

```text
Structural Precision

Photorealism

Organic Motion

Scene Entropy

Text Accuracy

Data Accuracy

Revision Requirement

Timing Precision

Atmosphere Requirement

Physical Complexity

Camera Complexity

Editability Requirement
```

其中 `Editability Requirement` 非常重要。

如果用户可能经常手工调整，尽量不要把所有内容 bake 成一段不可编辑 MP4。

---

# 30. Remotion 不一定输出 Scene

这是顶层规则之一。

Remotion Asset 类型包括：

```text
FULL_SCENE

MOTION_CLIP

TRANSPARENT_OVERLAY

ANIMATED_TEXT

3D_ELEMENT

BACKGROUND

PARTICLE_LAYER

TRANSITION_ASSET

INFOGRAPHIC

UI_COMPONENT

DECORATIVE_ELEMENT
```

---

# 31. Motion Continuity Group

是否拆分 Remotion Asset，不能只看 Shot。

应该判断：

```text
Motion Continuity
```

例如：

```text
button
↓
expand
↓
card
↓
node
↓
camera transition
```

如果连续：

> 一起 Render。

不能为了剪映可编辑硬拆开。

为此引入：

```text
continuity_group
```

---

# 32. Asset Contract

每一个生成 Asset 都必须具有 Metadata。

例如：

```yaml
asset_id: A018

type:
  transparent_overlay

producer:
  REMOTION

purpose:
  animated_chip

format:
  mov

alpha:
  true

fps:
  30

resolution:
  1920x1080

duration:
  4.2

timeline_start:
  00:01:24.500

replaceable:
  true

version:
  v2
```

这样 AI 和剪映都知道这个资产是什么。

---

# 33. Editable Timeline Backend

建立抽象：

```text
Editable Timeline Backend
```

第一版优先：

```text
pyJianYingDraft
```

但不要写死。

架构预留：

```text
pyJianYingDraft

VectCutAPI

pyCapCut

Future Backend
```

---

# 34. pyJianYingDraft 负责

- 创建剪映工程
- Video Track
- Overlay Track
- Text Track
- Subtitle
- Audio Track
- SFX Track
- BGM
- Keyframes
- Simple Transform
- Filter
- Transition
- Animation
- Volume
- Fade
- 素材位置

最终给用户：

> **一个真正能打开继续编辑的剪映草稿。**

---

# 35. Human Editable 是硬要求

必须写进 Constitution：

> 自动化不得以牺牲用户后期可编辑性为默认代价。

如果两个方案视觉质量相近，则优先：

```text
更可编辑的方案
```

而不是全部 bake。

---

# 36. Motion / Effect 系统

继续保留：

> **Every Shot Must Receive Intentional Motion Treatment.**

但不要求显眼特效。

三级：

## Level 1

Invisible Micro Motion

## Level 2

Narrative Motion

## Level 3

Hero Effect

核心视觉方向：

> 大量精细效果，少量显眼效果。

---

# 37. 已有 Motion 能力

尽量复用：

- video-shotcraft
- taste-skill
- Onda
- RemotionUI
- Remotion Bits
- Remotion official effects

`ZHOU_Videodirector` 自己做：

```text
Selection
Orchestration
Taste Routing
```

而不是自己重新发明所有 Effect。

---

# 38. 3D Resource Layer

包含：

```text
Poly Haven
Smithsonian
Quaternius
Kenney
其他合法 Provider
```

并使用统一 3D Registry。

模型 Metadata 包括：

- Preview
- Style
- Poly Count
- Texture
- Resolution
- File Size
- Format
- License
- Best For
- Cached

---

# 39. Resource Registry

这是整个系统的基础设施。

统一管理：

```text
Motion
Transition
3D
Texture
HDRI
Footage
Image
SFX
Music
SoundFont
Font
Reference
```

---

# 40. Progressive Resource Loading

不能每次读取整个 GitHub。

三级：

```text
LEVEL 0
Catalog

↓

LEVEL 1
Details

↓

LEVEL 2
Source
```

---

# 41. Level 0

只保存：

```text
ID
Name
Type
Tags
Summary
Best For
Preview
```

---

# 42. Level 1

需要时读取：

```text
Parameters
License
Dependencies
Compatibility
Size
Usage
Limitations
```

---

# 43. Level 2

确认使用之后才：

```text
Fetch
Clone
Download
Read Source
Install
```

---

# 44. Resource Learning

当 Registry 没找到：

```text
Registry
↓
Online Search
↓
发现资源
↓
License Check
↓
Metadata
↓
Preview
↓
加入 Registry
```

因此 Skill 会越来越好用。

---

# 45. Subagent Coordinator

在需要大量：

- 搜素材
- 找 Effect
- 找模型
- 设计多个方案
- 并行制作 Scene

时主动询问：

> 是否启用 Subagent？

用户决定：

```text
数量
模型
职责
并发
```

---

# 46. Subagent Role

例如：

```text
Research Agent
Motion Agent
3D Agent
Footage Agent
Sound Agent
Alternative Design Agent
Implementation Agent
QA Agent
```

但：

> **主模型永远拥有导演权。**

---

# 47. Generative Video Production Packet

任何 AI Video 镜头都不能只输出一句 Prompt。

必须包含：

- Shot Purpose
- Duration
- Aspect
- Resolution
- Subject
- Environment
- Composition
- Camera
- Lens
- Camera Movement
- Action
- Lighting
- Mood
- Style
- Motion
- Start Frame
- End Frame
- Continuity
- Text Safe Area
- Negative Prompt
- Post-production Plan
- Model-ready Prompt

然后用户生成。

生成素材重新进入 Asset Pipeline。

---

# 48. Approval Gate

整个 Skill 不是 Autonomous Black Box。

流程：

```text
PLAN
↓
EXPLAIN
↓
USER APPROVAL
↓
EXECUTE
↓
REPORT
```

---

# 49. Stage Approval

例如：

```text
Project Brief
Creative Direction
Style
Visual Bible
Audio Direction
Story
Storyboard
Production Plan
Final QA
```

---

# 50. Execution Approval

具体高影响动作：

- 大模型下载
- 4K / 8K Texture
- 大型素材下载
- 复杂 Motion
- AI Video Prompt
- 3D
- Subagent
- Timeline 大改
- 大规模重新 Render

先说明：

> 我要做什么、为什么、效果大概怎样。

用户确认再执行。

---

# 51. Project Memory

整个项目禁止依赖聊天窗口“记忆”。

每个项目维护：

```text
PROJECT_STATE.md
DECISIONS.md
approvals.yaml
shots/
assets/
```

---

# 52. PROJECT_STATE

保持短。

记录：

```text
Current Stage
Current Scene
Current Shot
Approved
Pending
Blocked
Current Style
Current Audio Direction
Next Action
```

---

# 53. DECISIONS

保存全部重要历史决定。

不能覆盖旧决定。

采用：

```text
D-001
D-002
...
```

如果新决定替代：

```text
Supersedes:
D-001
```

---

# 54. Shot Memory

每 Shot 一个 MD：

```text
Narrative Purpose
Approved Visual
Layers
Motion
Camera
Audio
Route
Assets
Changes
User Feedback
Implementation
QA
```

---

# 55. Asset Memory

增加：

```text
assets/A018.md
```

记录：

- Producer
- Version
- Location
- Purpose
- Shot usage
- Render settings
- Replaceability
- License
- Changes

---

# 56. Audio Map

除了 Storyboard，再生成：

```text
AUDIO_MAP.md
```

例如：

```text
00:01.200
Soft impact

00:03.400
UI click

00:04.200
Whoosh

00:12.000
Music layer enters

00:24.000
Voice emphasis / music duck

00:46.000
Hero impact
```

---

# 57. QA 系统

正式分成四层。

## Technical QA

代码、素材、Render、格式。

## Visual / Motion QA

审美、Motion、特效。

## Editorial QA

故事、节奏、信息。

## Sound QA

音乐、SFX、响度、同步、Ducking、是否过度。

---

# 58. Production Mode A

## Product / Tech Short

通常：

```text
30s–2min
```

更偏：

- Remotion
- UI
- Motion
- 3D
- Cinematic
- Sound Design

剪映作为：

> Final edit / manual refinement。

---

# 59. Production Mode B

## Editorial / Explainer

通常：

```text
5–10min
```

更偏：

- Footage
- Image
- Map
- Archive
- Remotion Assets
- 3D
- AI Video
- 剪映

这里：

> **剪映应该成为真正的主时间线。**

Remotion 更像 AE。

---

# 60. 完整 Workflow

```text
IDEA
 │
 ▼
Project Intake
 │
 ▼
Grill Me
 │
 ▼
PROJECT BRIEF
 │
[CONFIRM]
 │
 ▼
Reference Analysis
 │
 ▼
REFERENCE REPORT
 │
[CONFIRM]
 │
 ▼
Creative Director
 │
 ▼
CREATIVE DIRECTION
 │
[CONFIRM]
 │
 ▼
Style Director
 │
 ▼
VISUAL BIBLE
 │
[CONFIRM]
 │
 ▼
Sound Direction
 │
 ▼
AUDIO DIRECTION
 │
[CONFIRM]
 │
 ▼
Editorial Director
 │
 ▼
STORY / BEAT MAP
 │
[CONFIRM]
 │
 ▼
Storyboard
 │
 ▼
Scene
 │
 ▼
Shot
 │
 ▼
Layer
 │
[CONFIRM]
 │
 ▼
Subagent Configuration
 │
 ▼
Shot + Layer Router
 │
 ├── REMOTION
 ├── THREE_D
 ├── REAL_FOOTAGE
 ├── AI_VIDEO
 ├── JY_NATIVE
 └── HYBRID
 │
 ▼
Resource Registry Search
 │
 ▼
Asset Plan
 │
 ▼
Sound Plan
 │
 ▼
PRODUCTION PLAN
 │
[CONFIRM]
 │
 ▼
Asset Production
 │
 ├── Remotion
 ├── Three.js
 ├── AI Video
 ├── Footage
 ├── Image
 ├── Music
 └── SFX
 │
 ▼
Asset Package
 │
 ▼
pyJianYingDraft
 │
 ▼
Editable JianYing Project
 │
 ▼
AI / Human Editing
 │
 ▼
Preview
 │
 ▼
Technical QA
Visual QA
Editorial QA
Sound QA
 │
 ▼
CHANGE PROPOSAL
 │
[CONFIRM]
 │
 ▼
Final Edit
 │
 ▼
FINAL
```

---

# 61. 最终工程结构

```text
ZHOU_Videodirector/
│
├── SKILL.md
├── README.md
├── dependencies.yaml
│
├── workflows/
│   ├── project-intake.md
│   ├── reference-analysis.md
│   ├── creative-direction.md
│   ├── style-direction.md
│   ├── sound-direction.md
│   ├── editorial-direction.md
│   ├── storyboard.md
│   ├── routing.md
│   ├── resource-planning.md
│   ├── asset-production.md
│   ├── timeline-editing.md
│   └── qa.md
│
├── modules/
│   ├── grill-me/
│   ├── reference-analyzer/
│   ├── creative-director/
│   ├── style-director/
│   ├── sound-director/
│   ├── editorial-director/
│   ├── storyboard-engine/
│   ├── shot-router/
│   ├── layer-router/
│   ├── resource-router/
│   ├── subagent-coordinator/
│   ├── video-prompt-builder/
│   ├── asset-manager/
│   ├── timeline-manager/
│   └── qa/
│
├── presets/
│   ├── minimal-spatial-tech.md
│   ├── reality-paper-editorial.md
│   ├── cinematic-product.md
│   ├── editorial-explainer.md
│   ├── documentary-archive.md
│   └── kinetic-typography.md
│
├── adapters/
│   ├── watch-video/
│   ├── video-shotcraft/
│   ├── taste-skill/
│   ├── remotion-bits/
│   ├── onda/
│   ├── remotion-ui/
│   ├── remotion-official/
│   ├── remotion-three/
│   ├── pyjianyingdraft/
│   ├── vectcut/
│   ├── fluidsynth/
│   └── external-video/
│
├── registry/
│   ├── motion/
│   ├── transition/
│   ├── 3d/
│   ├── texture/
│   ├── hdri/
│   ├── footage/
│   ├── image/
│   ├── sfx/
│   ├── music/
│   ├── soundfont/
│   ├── fonts/
│   └── references/
│
├── previews/
│
├── schemas/
│   ├── project.schema.json
│   ├── visual-bible.schema.json
│   ├── audio-direction.schema.json
│   ├── scene.schema.json
│   ├── shot.schema.json
│   ├── layer.schema.json
│   ├── routing.schema.json
│   ├── asset.schema.json
│   ├── timeline.schema.json
│   └── approval.schema.json
│
├── templates/
│   ├── project-brief.md
│   ├── visual-bible.md
│   ├── audio-direction.md
│   ├── storyboard.md
│   ├── video-generation-packet.md
│   ├── audio-map.md
│   └── qa-report.md
│
├── scripts/
│   ├── registry-search.*
│   ├── registry-update.*
│   ├── asset-check.*
│   ├── timeline-build.*
│   ├── memory-update.*
│   └── project-validate.*
│
└── project-template/
    ├── PROJECT_STATE.md
    ├── DECISIONS.md
    ├── approvals.yaml
    ├── scenes/
    ├── shots/
    ├── assets/
    ├── references/
    ├── source/
    ├── audio/
    ├── remotion/
    ├── timeline/
    ├── previews/
    └── renders/
```

---

# 62. 外部能力接入方式

统一分成：

```text
external_skill
provider
knowledge_adapter
architecture_reference
timeline_backend
resource_provider
```

### `external_skill`

完整 Skill 调用。

### `provider`

通过 CLI / MCP / API / Registry 使用。

### `knowledge_adapter`

借用方法论、规则、Recipe，不整体复制。

### `architecture_reference`

学习架构，不复制实现。

### `timeline_backend`

作为可编辑时间线执行后端。

### `resource_provider`

素材、模型、音频、音乐等资源来源。

---

# 63. 开发总原则

最终 Constitution 至少包含：

1. **Director Before Engineer**
2. **Reuse Before Build**
3. **No Default Style**
4. **Reference Means Learn, Not Copy**
5. **Every Shot Receives Intentional Visual Treatment**
6. **Important Actions Receive Intentional Audio Treatment**
7. **Effects Serve Narrative**
8. **Correct Tool for Correct Layer**
9. **Remotion Is a Motion Engine, Not Necessarily the Final Editor**
10. **Prefer Editable Deliverables When Quality Is Comparable**
11. **Human Must Be Able to Take Over**
12. **Persist Important Decisions**
13. **Main Agent Owns Final Direction**
14. **Do Not Download or Build Large Resources Before Approval**
15. **Use Progressive Resource Disclosure**
16. **Before implementing any major capability, inspect the Reference Implementations & Reuse Map.**

---

# 64. 开发流程

整个开发建议分成八个 Phase。

## Phase 1 — Constitution & Skeleton

完成：

- SKILL
- Workflow
- State Machine
- Approval
- Memory
- Scene / Shot / Layer / Asset Schema
- dependencies
- Project Template

先不做真正视频。

## Phase 2 — Director Pipeline

完成：

- Grill Me
- Reference workflow
- Creative Director
- Style Director
- Sound Direction
- Editorial Director
- Storyboard

目标：

> 稳定地设计视频，而不是写代码。

## Phase 3 — Shot / Layer Router

完成：

```text
REMOTION
THREE_D
REAL_FOOTAGE
GENERATIVE_VIDEO
JY_NATIVE
HYBRID
```

加：

- Scene Entropy
- Editability
- Prototype route
- Layer decomposition

这是整个系统最重要的智能之一。

## Phase 4 — Resource Registry

先建立统一 Registry。

第一批：

- Onda
- Remotion Bits
- Shotcraft
- 3D
- SFX
- Music
- SoundFont

完成：

```text
find
detail
preview
fetch
```

## Phase 5 — Motion / 3D / Sound Engine

接入：

- Official Remotion
- Onda
- RemotionUI
- Remotion Bits
- video-shotcraft
- Three.js
- R3F
- FluidSynth
- SoundFont
- SFX Provider

此时能生产真正 Assets。

## Phase 6 — Generative / Footage Pipeline

完成：

- Real Footage search
- AI Video routing
- AI Video Production Packet
- Asset ingestion
- License Metadata

## Phase 7 — Editable Timeline

接：

```text
pyJianYingDraft
```

实现：

- Track schema
- Asset placement
- Text
- Subtitle
- BGM
- SFX
- Keyframe
- Transition
- Overlay
- Asset replacement
- Draft generation

目标：

> 自动生成一个人可以继续编辑的剪映草稿。

## Phase 8 — Subagents + QA + E2E

最后：

- Subagent Coordinator
- Parallel production
- Technical QA
- Visual QA
- Editorial QA
- Sound QA
- Memory auto update
- E2E tests

最终测试：

### Test A

90 秒科技产品片。

### Test B

8 分钟科普。

两者都能从：

```text
IDEA
```

走到：

```text
Editable Project + Final Video
```

才算 V1。

---

# 65. V1 Definition of Done

最终 V1 应该能够：

```text
理解需求                     ✓
分析参考                     ✓
创意策划                     ✓
Style                        ✓
Sound Direction              ✓
故事结构                     ✓
Storyboard                   ✓
Scene / Shot / Layer         ✓
技术路由                     ✓
资源 Registry               ✓
Remotion Asset              ✓
3D Asset                    ✓
AI Video Prompt             ✓
真实素材                     ✓
Music / SFX                  ✓
Procedural MIDI Music       ✓
剪映草稿                     ✓
人工后期可编辑               ✓
长期项目记忆                 ✓
Approval                     ✓
QA                           ✓
Final                        ✓
```

---

# 66. 这个系统最终最有价值的六个核心资产

## Director Workflow

决定：

> 从 IDEA 到 Final 怎么走。

## Shot / Layer Router

决定：

> 每一部分谁做。

## Resource Registry

决定：

> 用什么已有资源。

## Remotion Motion Engine

决定：

> 高级 Motion 怎么做。

## Editable Timeline Backend

决定：

> 如何变成 AI 和人都能继续编辑的工程。

## Approval + Memory

决定：

> 长项目怎样不失控、不失忆。

---

# 67. 最终目标

最终的 `ZHOU_Videodirector` 不应该像：

> 一个帮你写 Remotion 的 Codex。

也不应该像：

> 一个一句话生成 MP4 的视频模型。

而应该更接近：

> **一个 AI 视频制作团队的总导演。**

下面分别有：

```text
Creative Director
Editorial Director
Style Director
Motion Designer
3D Artist
Sound Designer
Music Composer
Footage Researcher
AI Video Department
Remotion Engineer
Timeline Editor
QA
```

而最终编辑台是：

> **剪映。**

Remotion 更像：

> **AI 驱动的 AE / Motion Graphics 工作站。**

AI Video 更像：

> **虚拟摄影棚 / 特殊素材生成部门。**

而用户本人始终可以：

> **打开剪映工程，直接接管最后的剪辑。**

这点是 `ZHOU_Videodirector` 和单纯“AI 自动做视频系统”之间最核心的区别之一。

---

# 68. Reference Implementations & Reuse Map
## 外部参考实现与复用地图

`ZHOU_Videodirector` 遵循：

> **Reuse → Adapt → Compose → Build Last**

因此开发任何模块之前，必须优先检查以下参考实现。

接入方式统一分成：

```text
EXTERNAL_SKILL
完整 Skill 调用

PROVIDER
通过 CLI / MCP / API / Registry 使用

KNOWLEDGE_ADAPTER
借用方法论、规则、Recipe，不整体复制

ARCHITECTURE_REFERENCE
学习架构，不复制实现

TIMELINE_BACKEND
作为可编辑时间线执行后端

RESOURCE_PROVIDER
素材、模型、音频等资源来源
```

| ZHOU_Videodirector 模块 | 首选参考 | 接入方式 | 主要借用什么 |
|---|---|---|---|
| Reference Video Analyzer | [Newuxtreme/watch-video-skill](https://github.com/Newuxtreme/watch-video-skill) | `EXTERNAL_SKILL` | 视频下载/读取、抽帧、字幕与时间轴，让 Agent 能真正“看视频” |
| Reference Analyzer 备用方案 | [bradautomates/claude-video](https://github.com/bradautomates/claude-video) | `EXTERNAL_SKILL / REFERENCE` | `yt-dlp + ffmpeg + transcript + frames` 的轻量视频观看流程 |
| Creative / Video Director | [BayramAnnakov/remotion-video-director](https://github.com/BayramAnnakov/remotion-video-director) | `KNOWLEDGE_ADAPTER` | 从需求到 Scenario、创意方案、Remotion Production 的交互式导演流程 |
| Cinematic / AI Video Director | [wuwangzhang1216/DirectorSKILL](https://github.com/wuwangzhang1216/DirectorSKILL) | `EXTERNAL_SKILL / KNOWLEDGE_ADAPTER` | Beat、Blocking、Shot List、Camera、Keyframe Prompt、Video Prompt、Continuity、Edit Timeline |
| Motion Shot Design | [Vincentwei1021/video-shotcraft](https://github.com/Vincentwei1021/video-shotcraft) | `KNOWLEDGE_ADAPTER` | 产品视频 Shot Recipes、2.5D 运镜、节奏、Motion Preview、SFX/声音设计思路 |
| Taste / Anti-slop | [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill) | `KNOWLEDGE_ADAPTER` | Design Language、Motion Intensity、Density、反模板感规则 |
| Agentic Video Architecture | [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) | `ARCHITECTURE_REFERENCE` | Pipeline、Tool/Provider Registry、Agentic Video Production、能力编排 |
| Remotion 正确实现 | [Remotion Official Agent Skills](https://www.remotion.dev/docs/ai/skills) | `EXTERNAL_SKILL` | 官方 Remotion Agent Skills 与 Best Practices |
| Remotion Motion Components | [av/remotion-bits](https://github.com/av/remotion-bits) | `PROVIDER` | Text、Transition、Particle、3D Scene 等 Remotion 组件与按需查找/获取模式 |
| Remotion Motion Components | [degueba/onda](https://github.com/degueba/onda) | `PROVIDER` | Copy-paste Remotion Motion Graphics |
| Remotion UI / Scene Components | [riaz37/remotion-ui](https://github.com/riaz37/remotion-ui) / [RemotionUI Docs](https://remotionui.com/docs) | `PROVIDER` | Caption、Scene、Transition、Composition 等现成组件 |
| 其他 Remotion Primitive 参考 | [kapishdima/remocn](https://github.com/kapishdima/remocn) | `RESOURCE_PROVIDER` | 可复制的 Remotion Primitive 与确定性动画模式 |
| 3D Rendering Core | [pmndrs/react-three-fiber](https://github.com/pmndrs/react-three-fiber) + Remotion Three | `PROVIDER` | React/Three.js 3D 渲染基础 |
| 3D Helpers | [pmndrs/drei](https://github.com/pmndrs/drei) | `PROVIDER` | React Three Fiber 高层 Helper |
| GLTF → React | [pmndrs/gltfjsx](https://github.com/pmndrs/gltfjsx) | `PROVIDER` | 将 GLTF 转为 React Three Fiber JSX Component |
| 3D Model / HDRI / Texture Registry | [Poly Haven Public API](https://github.com/Poly-Haven/Public-API) | `RESOURCE_PROVIDER` | Asset Lists、Categories、单 Asset Metadata 与按需下载 |
| 剪映主时间线 | [GuanYixuan/pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) | `TIMELINE_BACKEND` | Python 生成剪映草稿、轨道、关键帧、字幕、音频等 |
| Timeline Agent 备用/参考 | [sun-guannan/VectCutAPI](https://github.com/sun-guannan/VectCutAPI) | `TIMELINE_BACKEND / ARCHITECTURE_REFERENCE` | Agent 视频编辑 API/Skills 与剪映/CapCut 草稿思路 |
| CapCut Backend | [GuanYixuan/pyCapCut](https://github.com/GuanYixuan/pyCapCut) | `TIMELINE_BACKEND` | CapCut 草稿自动化方案 |
| Remotion SFX Tier-0 | [@remotion/sfx](https://www.remotion.dev/docs/sfx/) | `RESOURCE_PROVIDER` | Remotion 官方即取即用 SFX |
| UI Sound Reference | [nana-4/materia-sound-theme](https://github.com/nana-4/materia-sound-theme) | `RESOURCE_PROVIDER / REFERENCE` | Google Material sound resources 的 UI / Product Sound Language |
| 大型 SFX 搜索 | [Freesound API](https://freesound.org/docs/api/resources_apiv2.html) | `RESOURCE_PROVIDER` | API 搜索声音、Metadata、Tag、License |
| 免费 Music / SFX / Footage | [Mixkit](https://mixkit.co/) | `RESOURCE_PROVIDER` | Stock Video、Music、Sound Effects |
| 开放授权 Audio 聚合搜索 | [WordPress/Openverse](https://github.com/WordPress/openverse) | `RESOURCE_PROVIDER` | 开放授权图片和 Audio 聚合检索 |
| CC0 Music Corpus | [SoundSafari/CC0-1.0-Music](https://github.com/SoundSafari/CC0-1.0-Music) | `RESOURCE_PROVIDER` | CC0/Public Domain 音乐集合，适合做索引而不是整体 Clone |
| Procedural Music Renderer | [FluidSynth/fluidsynth](https://github.com/FluidSynth/fluidsynth) | `PROVIDER` | MIDI + SoundFont → Audio |
| 默认 General MIDI SoundFont | [mrbumpy409/GeneralUser-GS](https://github.com/mrbumpy409/GeneralUser-GS) | `RESOURCE_PROVIDER` | GM/GS 通用音色库 |
| AI SFX Generation 实验路线 | [SonyResearch/Woosh](https://github.com/SonyResearch/Woosh) | `PROVIDER / EXPERIMENTAL` | Text-to-Audio / Video-to-Audio Sound Effect Generation |

---

# 69. 每个参考项目必须声明“怎么借”

不能只记录：

```yaml
reference:
  video-shotcraft
```

应该写成：

```yaml
video-shotcraft:
  url: https://github.com/Vincentwei1021/video-shotcraft

  integration_mode:
    KNOWLEDGE_ADAPTER

  reuse:
    - shot_recipe_taxonomy
    - motion_language
    - camera_patterns
    - product_video_structure
    - sound_design_patterns
    - aesthetic_qa

  do_not:
    - copy_entire_repository
    - make_it_the_master_workflow

  owner:
    motion_design_layer
```

例如视频分析：

```yaml
watch-video:
  url: https://github.com/Newuxtreme/watch-video-skill

  integration_mode:
    EXTERNAL_SKILL

  reuse:
    - video_ingestion
    - transcript
    - frame_extraction
    - temporal_alignment

  ZHOU_Videodirector_responsibility:
    - style_analysis
    - pacing_analysis
    - motion_analysis
    - reference_comparison
    - extracting_reusable_rules
```

也就是：

> `watch-video` 负责“让 Agent 看见视频”。

> `ZHOU_Videodirector` 负责“看完以后理解这个视频为什么好”。

再比如剪映：

```yaml
pyJianYingDraft:
  url: https://github.com/GuanYixuan/pyJianYingDraft

  integration_mode:
    TIMELINE_BACKEND

  reuse:
    - draft_generation
    - timeline_tracks
    - media_placement
    - basic_keyframes
    - subtitles
    - audio
    - simple_effects

  ZHOU_Videodirector_responsibility:
    - decide_timeline_structure
    - decide_asset_boundaries
    - decide_editable_boundaries
    - generate_timeline_manifest

  do_not:
    - fork_and_rewrite_editor
```

---

# 70. Resource Registry 本身也要尽量借现有设计

重点参考两套思想。

## Remotion Bits

```text
Find
↓
Inspect metadata
↓
Fetch only selected component
```

它适合作为 Effect Registry 的一个 Provider。

## Poly Haven Public API

```text
List
Category
Asset metadata
↓
选中
↓
Download requested resolution
```

因此 `ZHOU_Videodirector` 的 Registry 不应该是：

```text
把所有素材下载到本地
```

而应该：

```text
LOCAL METADATA INDEX
        │
        ▼
Search / Preview / Rank
        │
        ▼
Selected Resource
        │
        ▼
Provider fetch
```

---

# 71. `dependencies.yaml` 应直接保存链接

建议：

```yaml
references:

  reference_video_analysis:
    primary:
      name: watch-video-skill
      url: https://github.com/Newuxtreme/watch-video-skill
      mode: external_skill

  motion_design:
    primary:
      name: video-shotcraft
      url: https://github.com/Vincentwei1021/video-shotcraft
      mode: knowledge_adapter

    providers:
      - name: remotion-bits
        url: https://github.com/av/remotion-bits

      - name: onda
        url: https://github.com/degueba/onda

      - name: remotion-ui
        url: https://github.com/riaz37/remotion-ui

  taste:
    name: taste-skill
    url: https://github.com/Leonxlnx/taste-skill
    mode: knowledge_adapter

  remotion:
    name: official-remotion-skills
    url: https://www.remotion.dev/docs/ai/skills
    mode: external_skill

  cinematic_direction:
    name: DirectorSKILL
    url: https://github.com/wuwangzhang1216/DirectorSKILL
    mode: external_skill

  timeline:
    primary:
      name: pyJianYingDraft
      url: https://github.com/GuanYixuan/pyJianYingDraft
      mode: timeline_backend

    alternatives:
      - name: VectCutAPI
        url: https://github.com/sun-guannan/VectCutAPI

      - name: pyCapCut
        url: https://github.com/GuanYixuan/pyCapCut

  architecture:
    name: OpenMontage
    url: https://github.com/calesthio/OpenMontage
    mode: architecture_reference

  procedural_music:
    renderer:
      name: FluidSynth
      url: https://github.com/FluidSynth/fluidsynth

    soundfont:
      name: GeneralUser-GS
      url: https://github.com/mrbumpy409/GeneralUser-GS

  generative_sfx:
    name: Woosh
    url: https://github.com/SonyResearch/Woosh
    mode: experimental
```

---

# 72. 开发硬规则：Major Capability Before Build Check

以后开发任何主要模块，例如：

```text
Reference Analyzer
Motion Engine
Timeline Backend
Sound Engine
3D Asset Search
```

必须先：

```text
dependencies.yaml
↓
Reference Implementations & Reuse Map
↓
检查已有能力
↓
判断 integration mode
↓
Reuse / Adapt / Compose
↓
最后才 Build
```

禁止：

```text
Reference Analyzer
↓
直接开始写 yt-dlp wrapper
↓
重新写 ffmpeg 抽帧
↓
重新写字幕提取
↓
重复造轮子
```

顶层 Constitution 应明确写入：

> **Before implementing any major capability, inspect the Reference Implementations & Reuse Map. If an existing project already solves the underlying problem adequately, integrate or adapt it before building a replacement.**

---

# 最终开发理念

`ZHOU_Videodirector` 的真正价值不在于它内部拥有最多代码。

它的真正价值在于：

```text
导演决策
+
能力路由
+
外部优秀能力编排
+
资源索引
+
可编辑时间线
+
长期项目记忆
+
用户审批
+
AI / 人协作
```

因此整个项目始终遵守：

> **Reuse → Adapt → Compose → Build Last**

以及：

> **Remotion 负责高级 Motion，AI Video 负责复杂高熵视觉，真实素材负责真实世界，剪映负责最终可编辑时间线，人始终可以接管。**
