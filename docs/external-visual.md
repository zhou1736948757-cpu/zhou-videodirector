# ZHOU_Videodirector — Phase 6 External Visual Architecture（External Visual 宪法参考）

本文件是 `ZHOU_Videodirector` Phase 6（Generative Video / Real Footage Pipeline）的
宪法级参考文档：两大管线怎么走、EV→GV/FR 流转、执行模式与门禁、验收状态机、
Normalization/Proxy、Provenance、Handoff、与 Phase 5 ASSET_PACKAGE_MANIFEST 的衔接。

- 来源：Phase-6 Prompt §6-134（重点 §42-51 / §54-58 / §62-64 / §71-76 / §83-84 /
  §90-104 / §115-117 / §129-134），总设计 v0.2，PHASE6_PROMPT 原文见
  `/Users/mac/.zcode/workspace/default/zhou-videodirector-phase6/PHASE6_PROMPT.md`。
- 配套：机器可读契约 `schemas/external-visual-request.schema.json`、
  `schemas/generative-video-packet.schema.json`、`schemas/footage-request.schema.json`、
  `schemas/video-review.schema.json`、`schemas/provenance-manifest.schema.json`、
  `schemas/timeline-handoff.schema.json`、`schemas/asset.schema.json`（Phase 6 扩展）；
  引擎 `modules/external-visual/`（Wave 1：packet_builder / continuity / footage /
  ingestion / review / gates / workflow / **provenance / handoff**）；统一入口
  `scripts/external-visual.py`（P6-07）。
- 相关政策：[constitution.md](constitution.md)（Reuse Before Build / 审批 / 渐进披露）、
  [registry.md](registry.md)（Phase 4 Registry 宪法，footage 搜索复用）、
  [production.md](production.md)（Phase 5 Production 宪法，ASSET_PACKAGE_MANIFEST 衔接）、
  [reuse-map.md](reuse-map.md)（Reuse → Adapt → Compose → Build Last）。

---

## 1. 定位：两个正式生产分支（§0 / §6 / §52）

Phase 6 建立两个模型无关、素材来源无关的正式生产分支：

```text
┌─────────────────────────────┐      ┌─────────────────────────────┐
│  GENERATIVE VIDEO PIPELINE  │      │     REAL FOOTAGE PIPELINE   │
│  （AI 生成，§6-51）            │      │     （真实素材，§52-84）       │
│                             │      │                             │
│  EV ─→ GV Packet ─→ 生成      │      │  EV ─→ FR ─→ Search ─→ Rank │
│  （provider-neutral）        │      │   ─→ Select(License 硬门槛)    │
│       ↓                     │      │       ↓                    │
│  Candidate ─→ Review ─→ QA  │      │  Plan Use（可用区间）         │
│       ↓                     │      │       ↓                    │
│  Ingestion / Normalize /    │      │  Ingestion / Normalize /    │
│  Proxy（同一链路 §42-51）      │      │  Proxy（同一链路）             │
│       ↓                     │      │       ↓                    │
│  Asset（asset.schema A###）   │      │  Asset（A###）              │
└─────────────────────────────┘      └─────────────────────────────┘
              ↓ 统一收口（P6-07）
  VISUAL_PROVENANCE_MANIFEST（§96-97）
  TIMELINE_HANDOFF_MANIFEST（§133-134，只提示不建时间线）
  ASSET_PACKAGE_MANIFEST 扩展（§105/§132，向后兼容）
```

**唯一目标**：让「已批准 Shot/Layer 的视觉需求」变成「可追溯、可校验、可复用的
外部视觉 Asset」，且不依赖任何具体视频模型或素材站点。

## 2. EV → GV / FR 流转（§5 / §8-25 / §54）

`EV-###`（external-visual-request，`schemas/external-visual-request.schema.json`）
是 Phase 6 的**唯一输入**：已批准的 Shot/Layer 视觉需求。按 `route` 分流：

```text
EV.route = GENERATIVE_VIDEO  ─→ packet_builder.build_packet → GV-### Production Packet
EV.route = REAL_FOOTAGE      ─→ footage.build_request → FR-### Footage Request
```

| 产物 | ID | 模块 | 关键语义 |
|---|---|---|---|
| GV-### | `^GV-\d{3}$` | `modules/external-visual/packet_builder.py` | Provider-neutral Prompt（§25 不硬编码模型名）、subject/environment/camera/lighting/continuity、start/end frame、postproduction_plan、variant_strategy、reference_inputs |
| FR-### | `^FR-\d{3}$` | `modules/external-visual/footage.py` | authenticity_requirement（历史事件→STRICT）、provenance_requirements、search_budget（§119）、source_preferences（§55） |

- **版本语义（§90-91）**：GV Packet 版本演化 `packet_version` 递增 + `supersedes`
  指向旧版，不换 ID。
- **Text 安全（§7/§14/Test 2-3）**：GV 不拥有精确文字；overlay 需求归 Remotion 信息层；
  `enforce_no_exact_text` / text safe area 由 packet_builder 处理。

## 3. 执行模式：MANUAL / ASSISTED / AUTOMATED（§29-30 / §115-116）

`modules/external-visual/workflow.py` + `gates.py automation_level()`：

| 模式 | 语义 | 本阶段行为（P6-06 硬规则） |
|---|---|---|
| MANUAL | §29 一等公民：导出 packet → 用户网页生成 → 返回文件 → ingest | `run_manual` 只落 `{packet_id}_prompt.txt` + `{packet_id}_instructions.md`，状态 WAITING_USER；**不阻塞等待** |
| ASSISTED | §30 ZHOU 完成 packet/search/metadata，生成/购买由用户执行 | `run_assisted` 落 packet 副本 + search_summary → READY_FOR_USER |
| AUTOMATED | §115-116 理论自动化 | 无凭据/无成本规则 → **恒 BLOCKED_NOT_CONFIGURED** + fallback=run_manual，绝不清空拦截（本阶段无真实凭据） |

## 4. Cost / Privacy 门禁（§31-32 / §64 / §111 / §115-116）

`modules/external-visual/gates.py` 七类 gate，全部产出 `approval.schema.json` 形状的
`AP-###` 记录并追加到项目 `approvals.yaml`（`append_approval`）：

```text
cost_gate                   生成成本（§31）             —— 六要素判定，需批准
privacy_gate               数据/隐私（§32/Test 11）    —— upload_identified 等，需批准
paid_stock_gate            付费素材（§64/Test 12）     —— 候选付费 → 需批准 + 免费替代建议
large_download_gate        大文件下载（§65-66/Test 16）—— 阈值判定，需批准
route_change_gate          路由变更（§78-79）          —— 只产 RO-### 提案，不改路由文件
prompt_strategy_change_gate 提示策略大改                —— 需批准
character_ref_upload_gate  角色参考图上传                —— 需批准（隐私红线）
```

- `assert_upload_allowed()`：无匹配 approved 记录时抛 `UploadBlockedError`（BLOCKED）。
- **RO-### / PC-###**：`route_optimization`（只提案，`routing_files_modified=false`）
  与 `production_conflict`（shot split 必须批准，`storyboard_modified=false`）
  只写独立记录文件，不私改任何既有文件。

## 5. Review / 验收状态机（§35-41 / §100-104）

`modules/external-visual/review.py`：

```text
CANDIDATE ──SELECTED──→ APPROVED ──NORMALIZED──→ READY_FOR_TIMELINE
    │                    │
    └──REJECTED──┘       └──REVISION_REQUIRED（verdict REGENERATE/REJECT）
```

- `machine_checks`：ffmpeg 抽帧 + 纯 Python 信号统计（flicker / freeze / 黑帧 /
  temporal_coherence / overlay 静区），**不会"看"视频**；证据缺失 → NEEDS_EVIDENCE，
  score 按 0，verdict 不得 PASS。
- `aggregate`：18 维 × 伪影；hard 伪影（face/hand deformation 等）→ 最高
  PASS_WITH_ISSUES，且 APPROVED 迁移被拒（§37）。
- `advance_acceptance`：到 READY_FOR_TIMELINE 必须 QA + License + metadata 齐（§104）。
- `diagnose_regeneration`：§117 阶梯 prompt_refinement → reduce_complexity →
  alternative_strategy；>3 次 → BLOCKED + approval_required。

## 6. Normalization / Proxy / Original Preservation（§44-47 / §90-95）

`modules/external-visual/ingestion.py` + `adapters/external-visual/`：

```text
copy 原始文件 → storage 布局 → probe → technical_validate → audio_decision
  → normalize 按需（§44-45 不无脑重编码）→ proxy（§46）→ sha256 → asset JSON
```

铁律：
- **原始文件永远保留**（§47）：输出新文件名 `{asset_id}_v{n}_original.ext` /
  `_norm.mp4` / `_proxy.mp4`。
- 已满足要求 → `changed=[]` 且不重编码（§45）。
- `USER_UPLOAD` 强制 `origin=ownership=USER_PROVIDED`，绝不标为网上素材（§67-68）。
- model 未知写 `UNKNOWN` 不猜（§43）；幂等可重入（同 asset_id 同内容 → 同 version，
  不同内容 → 版本递增）。

## 7. Provenance（§96-99 / P6-07）

`modules/external-visual/provenance.py` → `VISUAL_PROVENANCE_MANIFEST`：

```text
python3 -m modules.external-visual.provenance <assets_dir|asset_jsons> \
    [--packets <packets_dir>] [--out <out.json>]
```

- 每个外部素材一条 `PV-###`：asset_ref / source_type / source / provider / model /
  prompt_packet_id / license / ownership / generation_date / original_file /
  normalized_file / usage（§96）+ content_credentials 槽位原样带出（§99）。
- **6 问全覆盖（§97）**：manifest 顶层 `six_questions` 逐条回答「哪来 / AI 还是实拍 /
  版权 / Prompt / 能否重生成 / 能否商用」，字段缺省一律 `UNKNOWN` 并在 `entry_notes`
  标注原因，**禁止猜值**（model 缺失写 UNKNOWN，不猜具体模型名）。
- `source_type` 是 schema 枚举（无 UNKNOWN），缺失时按 origin/ownership/producer
  确定性保守归类（USER_PROVIDED→USER_UPLOAD、REAL_FOOTAGE→FOOTAGE_DOWNLOAD、
  GENERATED→EXTERNAL_TOOL），并在 entry_notes 标注「推导」。
- license 未知 → `LICENSE_REVIEW_REQUIRED`（§63），不得当 Commercial Safe。

## 8. Timeline Handoff（§133-134 / P6-07）

`modules/external-visual/handoff.py` → `TIMELINE_HANDOFF_MANIFEST`：

```text
python3 -m modules.external-visual.handoff <asset_jsons> [--shots <shots_dir>] \
    [--out <out.json>]
```

- 每条 `TH-###`：asset_id / shot_id / layer_id / preferred_track / preferred_start /
  preferred_duration / in_point / out_point / crop / blend / overlay / replaceable /
  proxy / original / audio_behavior / editability（§133 全字段）。
- **只提示、不创建时间线（§134）**：manifest 头部 `note` 明确声明「本清单仅建议
  Asset 如何进入编辑器，不创建时间线、不写死轨道；装配与裁决由 Phase 7 完成」。
- 数据聚合自 `asset.timeline_hint` 扩展键 + footage `plan_use` 输出（可选，通过
  asset 内嵌 `plan_use` 传入）+ `audio_behavior`；`--shots` 目录（可选）用于解析
  shot/layer 归属。

## 9. 与 Phase 5 衔接：ASSET_PACKAGE_MANIFEST 扩展（§105 / §132 / P6-07）

`modules/production/manifest.py` 的 `export_package()` 在既有 §114 结构上**只增不改**：

| 既有 section（§114，不变） | Phase-6 新增（§105/§132，全部可选，缺省空数组） |
|---|---|
| motion_assets / three_d_assets / music / sfx / ambience | `generative_video_assets`（type=GENERATIVE_VIDEO 或 origin=GENERATED） |
| sources / previews / licenses / versions / timeline_hints | `real_footage_assets`（origin=REAL_FOOTAGE 或 source_type=FOOTAGE_DOWNLOAD） |
| | `proxies`（proxy_path / preview / _proxy） |
| | `source_files`（original_path，§47 原始文件） |
| | `prompt_packets`（GV-### 引用去重 + 引用资产列表） |
| | `provenance_entries`（PV-### 回链去重） |
| | `license_summary`（每 license 聚合：count / commercial_use / assets） |

- **向后兼容最高优先级**：Phase 5 E2E 既有的 ASSET_PACKAGE_MANIFEST（19 资产）
  仍可读、可再生成；旧字段一个都不能动（回归测试见 `work/p6-07/test_self.py`）。
- 分类由资产目录的 `type / origin / source_type` 确定性判定（§98）。

## 10. 统一 CLI（P6-07）

`scripts/external-visual.py` 是 Phase 6 全链路入口（薄分发层，业务全在 modules/）：

```text
python3 scripts/external-visual.py <subcommand> [--json] ...
request | packet | search | select | plan-use | review | ingest | normalize |
proxy | provenance | handoff | package | manual-export
```

- 脚本顶部自举 sys.path（skill 根目录），任意 cwd / 无 PYTHONPATH 均可直跑；
  子模块加载失败输出可读错误而非裸 ImportError。
- `--json` 输出合法 JSON；业务失败退出码 1，模块加载致命错误退出码 2。

## 11. 禁止项与边界（§2 / §110 / §116）

- **不接具体视频模型**：packet / schema 中禁止出现任何具体模型名（§25/§28）；
  model 未知写 UNKNOWN。
- **不私改路由 / storyboard / 时间线**：RO-### / PC-### 只提案；handoff 只提示。
- **不联网、不真实调用**：本阶段无真实凭据，AUTOMATED 恒拦截；fetch 只产出门禁记录。
- **Reuse 优先（§110）**：video ingestion / probing / frame extraction 先查
  [reuse-map.md](reuse-map.md)（ffmpeg/ffprobe、video-analyst、ds-vision-skill）。

## 附：本文档与其它文档的引用关系

- `schemas/*.schema.json`：机器可读契约（P6-01 产物，冲突时以 schema 文件为准）。
- `docs/registry.md`：footage 搜索经 Phase 4 Registry（find/detail/preview），不自建搜索系统（§59）。
- `docs/production.md`：Phase 5 生产宪法；ASSET_PACKAGE_MANIFEST 结构源头（§114）。
- `work/p6-01/SCHEMA_CONTRACT.md`：Phase 6 ID/枚举总表（EV/GV/FR/RV/PV/TH/AP…）。
