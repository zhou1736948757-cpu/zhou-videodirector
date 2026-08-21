---
workflow_id: WF-002
name: 参考片分析
stage_ids: [REFERENCE_ANALYSIS, REFERENCE_REVIEW]
requires_approval: [REFERENCE_REVIEW]
phase1_status: implementation
phase2_status: implemented
---

# 参考片分析（Reference Analysis）

## 目标
对用户提供的参考视频（YouTube / Bilibili / 本地文件 / 广告 / 产品片 / 科普 / Motion Design / 电影片段）做 **6 层分析**（Content / Editorial / Composition / Motion / Visual / Audio）。外部 Skill 只负责"看见视频"，本工作流负责"看完以后理解为什么好"（v0.2 §69）。输出经 Normalize Adapter 归一到 Normalized Reference Output，提炼可复用规律 R-NN 并产出 `REFERENCE_ANALYSIS.md`（≥ 2 参考时另产 `REFERENCE_COMPARISON.md`）。原则：**学习规律，不逐镜复制。**

## 触发时机
`PROJECT_BRIEF_REVIEW` 已批准后触发。无参考素材时该阶段结构化跳过（见 No-Reference 分支）。

## 输入
- `<project>/PROJECT_STATE.md`、`<project>/PROJECT_BRIEF.md`
- 参考视频源（链接或本地文件，落 `<project>/references/`）
- 模板：`templates/reference-analysis.md`、`templates/reference-comparison.md`

## 输出（项目文件）
- `<project>/references/REFERENCE_ANALYSIS.md` — 6 层分析报告（模板 `templates/reference-analysis.md`）
- `<project>/references/REFERENCE_COMPARISON.md` — 仅当 reference ≥ 2（模板 `templates/reference-comparison.md`）
- 可选：`<project>/references/normalized/` — 每 reference 一份 Normalized Output（Adapter 产物，原始 Skill 输出不直接入档）

## 强制 Reuse 流程（v0.2 §62 / docs/external-capability-policy.md §B）
调用任何视频分析能力前，必须先执行 Major Capability Before Build Check：
1. 查 `dependencies.yaml` — watch-video-skill / claude-video / video-analyst / yt-dlp 是否已登记。
2. 查 `docs/reuse-map.md` — §A.1 外部参考与 §B 本机能力清单。
3. 判定 integration_mode（仅允许 6 种枚举；本工作流为 EXTERNAL_SKILL）。
4. Reuse → Adapt → Compose → Build Last；无前 3 步记录不得进入实现。

## 视觉能力探测（三档路由）

每次 Reference Analysis 入口**先探测，不假设能力可用**。在任何"看视频 / 看图"动作之前执行：

```text
python3 scripts/visual_capability_probe.py [--model <当前模型名>] [--json]
```

探测 = 本机工具可用性（自动）+ 当前模型视觉能力（内置已知表；未知模型 → `UNKNOWN` → 请用户人工确认）。
按结果选择三档视觉通道之一：

- **A. NATIVE_VISION**（模型支持图片/视频输入）→ 直接把参考视频 / 抽帧交给当前 agent 看（video-analyst 抽帧可辅助）。
- **B. TEXT_WITH_VISION_BRIDGE**（模型纯文本，ds-vision 可用）→ 抽帧链：video-analyst CLI 可用则用它；否则 ffmpeg 抽帧（8.x）→ `mimo-vision.sh` 看图（图片会上传云端，敏感内容需用户确认；用户拒绝则降级 C）→ 结果按 video-analyst 同名 schema 写回后归一。
- **C. TEXT_NO_VISION**（模型纯文本且 ds-vision 不可用/被拒）→ ASR（video-analyst 规格 ASR 可用则用；否则 ffprobe 音频元数据）+ 字幕 + 降级分析；`REFERENCE_ANALYSIS.md` 头如实标注 `vision=degraded`。

各档内部的具体工具按能力清单选择（保留原有优先序，作为档内工具选择）：
1. 首选 `watch-video-skill`（EXTERNAL_SKILL，video ingestion / transcript / frame extraction / temporal alignment）；备用 `bradautomates/claude-video`。
2. 本机 `~/.agents/skills/video-analyst/` — **SKILL.md 规格已装；CLI 脚本未安装（`video-analyst` 命令不可用，2026-08-16 核盘）**；probe 会如实报 `video_analyst_cli=UNINSTALLED_SKILL`，Tier B 下抽帧改用 ffmpeg。
3. `ds-vision-skill` 用于参考抽帧 / 截图的视觉补盲（图片会上传云端服务，敏感内容需用户确认）。
4. `yt-dlp`（`/Users/mac/skills/yt-dlp`，PROVIDER）只作下载 exec 配合上述 Skill，不作为独立管线。

禁止：自行实现 yt-dlp wrapper、ffmpeg 抽帧、字幕提取；重造 video ingestion / transcript / frame extraction。

## Normalize Adapter 层
外部 Skill 输出结构不统一且含私有 CoT，必须先经 Adapter 归一，**禁止直接拼接进 ZHOU 数据结构**。
- 归一目标 = Normalized Reference Output（共享契约，逐项核对）：
  `content_summary` / `editorial_summary` / `composition_summary` / `motion_summary` / `visual_summary` / `audio_summary` / `reusable_rules[]`（R-NN）/ `avoid_traits[]`。
- 私有 CoT、Agent 临时状态、推理过程不得透出；证据可保留时间轴位置 `t: <mm:ss>`。
- Adapter 校验失败：按 `failed` 记录并上报，降级到备用 Skill，绝不带病写报告。

## 单 Reference 流程
```
0. 视觉通道探测：python3 scripts/visual_capability_probe.py --model <当前模型>
   → 记录 tier（A/B/C）与选中通道；Tier C 或模型 UNKNOWN 时
     在 REFERENCE_ANALYSIS.md 头注明 vision=degraded / 需人工确认
External Skill（watch-video-skill / video-analyst；Tier B 抽帧走 ffmpeg → mimo-vision.sh）
  → Adapter（归一化到 Normalized Reference Output）
  → 6 层填充（Content / Editorial / Composition / Motion / Visual / Audio）
  → Reusable Rules（R-NN）
  → 写 <project>/references/REFERENCE_ANALYSIS.md
```

## 多 Reference 流程（reference ≥ 2）
1. 每个 reference 独立跑单 Reference 流程，互不污染。
2. 写 `<project>/references/REFERENCE_COMPARISON.md`（Common / Conflicting / Best Traits / Avoid / Creator-specific vs Generalizable / Recommendations）。
3. 将 reusable_rules 推送给 Creative + Style + Sound + Editorial 四个 Director 作为各自输入。

## No-Reference 分支
用户未提供参考素材时结构化跳过：
- `REFERENCE_ANALYSIS` 状态 = `skipped`，`skip_reason: "No reference material supplied."`
- 不生成 REFERENCE_ANALYSIS.md，直接进入 `CREATIVE_DIRECTION`（不经过 `REFERENCE_REVIEW`）。

## 阶段状态变更
`REFERENCE_ANALYSIS` → `REFERENCE_REVIEW` →（approve 后）`CREATIVE_DIRECTION`

## Approval Gate
进入 `REFERENCE_REVIEW`（waiting_user）后，向用户呈现以下四类结论供确认：
- **Common patterns**（跨参考共同特征）
- **Conflicts**（参考间冲突与裁决建议）
- **Reusable rules**（R-NN 列表）
- **What to avoid**（避免清单）
- approved → 进入 creative-direction
- revision_requested → 回到 `REFERENCE_ANALYSIS` 修订

## 修订流程（用户要求改分析时）
1. 回到 `REFERENCE_ANALYSIS`，更新 REFERENCE_ANALYSIS.md / REFERENCE_COMPARISON.md。
2. 在 `<project>/DECISIONS.md` 追加 D-NNN 记录修订决定（Supersedes 旧决定）。
3. 重新提交 `REFERENCE_REVIEW` 等待确认。

## Phase 2 实现状态
> Phase 1：skeleton → Phase 2：implemented（Director Pipeline 就绪）。
> 模板：`templates/reference-analysis.md`、`templates/reference-comparison.md`。
> 视觉通道：入口先跑 `scripts/visual_capability_probe.py` 三档探测（reuse_map 引用）：`watch-video-skill`（EXTERNAL_SKILL）、`claude-video`（备用）、`video-analyst`（本机；**SKILL.md 规格已装，CLI 未安装——`video-analyst` 命令不可用，2026-08-16 核盘，probe 如实报 `video_analyst_cli=UNINSTALLED_SKILL`，Tier B 用 ffmpeg 抽帧兜底**）、`ds-vision-skill`、`yt-dlp`（PROVIDER）。
> 禁止：实现本阶段范围外的功能；把外部 Skill 输出直接拼进 ZHOU 数据结构；跳过 Approval；Phase 2 内下载大素材。
