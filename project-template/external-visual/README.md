# external-visual/ — Phase 6 外部视觉目录模板

> 用途：Phase 6（Generative Video / Real Footage Pipeline）产物的存放约定。
> 项目进入 Phase 6（已有 GENERATIVE_VIDEO / REAL_FOOTAGE / HYBRID 路由的 Shot）时，
> 在项目根创建本目录，并按下表分目录存放。目录创建由执行 workflow 负责，
> 本文件只说明结构用途。

## 目录结构

```text
external-visual/
├── continuity/     # 连续性档案（CP-CHAR-### / CP-ENV-### / VF-### / SP-### / RFB-###）
├── footage/        # Real Footage 产物（FR-### / search 结果 / select 决策 / plan_use）
├── generative/     # Generative Video 产物（GV-### Packet / prompt / 评审 / 变体）
└── README.md       # 本文件
```

## 各目录用途

| 目录 | 存放内容 | 关联模块 |
|---|---|---|
| `continuity/` | 人物/环境连续性档案、Visual Family、Scene Pack、Reference Frame Bank | `modules/external-visual/continuity.py` |
| `footage/` | FR-### 请求、registry 搜索候选、rank/select 结果、plan_use 输出（可用区间 + timeline_hint） | `modules/external-visual/footage.py` |
| `generative/` | GV-### Packet、`{packet_id}_prompt.txt`、`{packet_id}_instructions.md`、候选评审 RV、被拒变体 | `modules/external-visual/packet_builder.py` / `review.py` / `workflow.py` |

## 与其它目录的关系

- `assets/`：最终 Asset（A###，含 asset JSON 与标准化/代理文件）统一放项目 `assets/`；
  本目录只放 Phase 6 **中间产物**（请求/搜索/评审/plan 等）。
- `production/`：三份 manifest（VISUAL_PROVENANCE_MANIFEST /
  TIMELINE_HANDOFF_MANIFEST / ASSET_PACKAGE_MANIFEST）随项目 `production/` 落盘。
- `approvals.yaml`：Phase 6 所有门禁（cost/privacy/paid_stock/large_download/
  route_change 等）的 AP-### 审批记录追加到项目 `approvals.yaml`。
- 详见 `docs/external-visual.md` 与 `work/p6-01/SCHEMA_CONTRACT.md`。
