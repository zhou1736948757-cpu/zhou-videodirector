# modules/router — Shot / Layer 技术路由引擎（Phase-3, P3-1）

ZHOU_Videodirector 的 **Shot / Layer Router** 核心实现。为每个 Storyboard Shot（必要时每个
Layer）决定生产技术路线（Route）、置信度、原型验证需求与 Bake 策略，并输出机器可读
`routing/S###.yaml`、`layers/S###.yaml`（HYBRID 时）与人类可读的 `ROUTING_PLAN.md`。

- 纯 Python 3 stdlib 实现，无第三方依赖，不调用任何真实 LLM。
- 遵循共享契约（Route 6 枚举 / 12 因子 / Bake policy / Confidence / Prototype / Layer role 16 / Layer ID `S###-L##`）。
- 禁止保存私有 Chain-of-Thought：只落盘 `decision_summary`（§38）。

## 文件

| 文件 | 内容 |
|---|---|
| `router.py` | 路由引擎 + 双入口（CLI / `route_single`）+ `--selftest` 双路径自检 |
| `routes.json` | 6 条 Route 的机器可读定义（适合场景 / 核心特征 / 禁止场景 / 典型 bake 默认） |
| `README.md` | 本文件 |

## 架构（Phase-3 Prompt §35）

```
        Shot 特征 + 项目 Context
                  │
                  ▼
   ┌─────────────────────────────┐
   │  1. Hard Constraints (§36)  │  exact text → 生成式不得独占文字层
   │                             │  critical data → 生成式不得当数据 Producer
   │                             │  subtitle → 必须 KEEP_EDITABLE
   └──────────────┬──────────────┘
                  ▼
   ┌─────────────────────────────┐
   │  2. Heuristics (12 因子)     │  compute_factors(): 从 visual/camera/motion/
   │     compute_factors          │  on_screen_text/audio/notes(Layer Intent,
   │                              │  Editability)/Likely 意向 推导 12 项 0-1 评分
   └──────────────┬──────────────┘
                  ▼
   ┌─────────────────────────────┐
   │  3. Candidate Generation    │  generate_candidates(): 6 条 Route 打分，
   │     (§37)                   │  按硬约束/政策/已有素材过滤，输出 Top 1-3
   └──────────────┬──────────────┘
                  ▼
   ┌─────────────────────────────┐
   │  4. LLM Evaluation (hook)   │  llm_judgment(shot, factors, candidates,
   │     (§34)                   │  context) -> dict|None；默认 None = 纯启发式，
   │                             │  可注入真实 LLM 判断（不假装智能）
   └──────────────┬──────────────┘
                  ▼
   ┌─────────────────────────────┐
   │  5. Confidence (§39)        │  Top 候选分数差 + 因子冲突度 + 硬约束触发数
   │                             │  >=0.80 HIGH / 0.55-0.79 MEDIUM / <0.55 LOW
   └──────────────┬──────────────┘
                  ▼
   ┌─────────────────────────────┐
   │  6. Prototype Decision      │  HIGH 直荐；MEDIUM 按 Route 给原型类型；
   │     (§40-43)                │  LOW → STATIC_KEYFRAME + Concept Exploration
   └──────────────┬──────────────┘
                  ▼
   Output: routing/S###.yaml + layers/S###.yaml（HYBRID）+ ROUTING_PLAN.md
```

辅助能力（同样可被 API 调用）：

- `decide_bake(layer_role, route, shot)`：SUBTITLE/简单 text/photo/B-roll → `KEEP_EDITABLE`；
  Remotion overlay / AI clip / 3D render → `ASSET_REPLACEABLE`；continuity_group 非空 → `BAKE`。
- `decompose_layers(shot, factors, route, context)`：仅 HYBRID / 多 Producer 时拆 Layer；
  ID `S###-L##`，role 16 种，禁止过度拆（§27）。
- `escalate(route, factors, shot)`（§65）：JY_NATIVE + 复杂 morph / 空间相机 → 升级 REMOTION。
- `deescalate(route, factors, shot)`（§66）：REMOTION + 照片慢推 → 降级 JY_NATIVE。
- `apply_override(decision, override)`（§71-73）：`{route, source, note}` →
  `route_source` 更新、`supersedes` 记录旧 Route、confidence=1.0。
- Continuity（§31/§56）：同 `continuity_group` 的一组 REMOTION 镜头 → 输出 asset boundary
  建议（如 `CG001-A01 motion-sequence.mov`）。

## 双入口用法

### 1. CLI（整项目路由）

```bash
python3 modules/router/router.py <project_dir> [--json] [--selftest]
```

输入（project_dir 内）：
- `shots/*.json`（必须，Phase-2 Storyboard 输出；route 恒为 `UNDECIDED` 由引擎定夺）
- `project.json` 或 `PROJECT_BRIEF.md` / `PROJECT_STATE.md`（提取 `production_mode`、AI/Real/3D 政策、Available Assets、预算优先级）
- `VISUAL_BIBLE.md`、`AUDIO_DIRECTION.md`、`STORYBOARD.md`（可选；提供风格摘要、音频同步要求、
  `Likely: <route>` 意向提示——提示只作候选加分，不作断言）

输出（写入 project_dir）：
- `routing/S###.yaml`（§53：shot_id / route / confidence / route_source / reason / decision_summary / scores / prototype / continuity_group / assembly_backend / supersedes）
- `layers/S###.yaml`（§54：`layers:` 数组，仅 HYBRID 或多 Producer 时生成）
- `ROUTING_PLAN.md`（§51：Executive Summary / Route Distribution / Hybrid / High-risk / Prototype-required / Editability / Continuity Groups / Bottlenecks / User Decisions Required）

用户 Route 覆盖持久化：`<project_dir>/routing/overrides.json`

```json
{ "S001": { "route": "JY_NATIVE", "source": "USER_OVERRIDE", "note": "客户要求简单剪辑" } }
```

CLI 每次运行自动读取并应用，重跑幂等（supersedes 保留被覆盖前的 Route）。

### 2. API（供 Benchmark / skill 运行时调用）

```python
from modules.router import router

decision = router.route_single(
    shot,                      # dict，Phase-2 shot JSON 字段（visual_description/camera/motion/
                               # on_screen_text/audio.sync_points/notes/visual_direction…）
    context,                   # dict，含 production_mode / visual_bible_summary /
                               # audio_sync_requirements / budget_priority / 政策键 / override
)
```

`decision` 返回 dict：`route`、`confidence`、`confidence_level`、`route_source`、`reason`、
`decision_summary`、`scores`（12 项）、`prototype_required` / `prototype_type` / `prototype_goal`、
`continuity_group`、`assembly_backend`、`supersedes`、`constraints`、`candidate_routes`、
`layer_decomposition_required`、`layers`（HYBRID 时）。

### LLM 判断注入（§34）

默认纯启发式。skill 运行时可以注入真实判断：

```python
import router
def my_judge(shot, factors, candidates, context):
    # 返回 {"route": "REAL_FOOTAGE"} 或 {"score_adjust": {"REAL_FOOTAGE": 0.3}}
    ...
router.llm_judgment = my_judge          # 模块级全局
# 或 context["llm_judgment"] = my_judge  # 单次调用
```

## 自检

```bash
python3 modules/router/router.py --selftest; echo "exit=$?"
python3 -c "import json; json.load(open('modules/router/routes.json'))" && echo "routes.json OK"
```

`--selftest` 覆盖双路径：干净项目 CLI 全流程 + `route_single` 边角场景（Tokyo street 不路由
REMOTION；exact text + photoreal → HYBRID 且文字层归 REMOTION；subtitle → KEEP_EDITABLE；
连续 morph → continuity_group + BAKE；抽象概念 → LOW/MEDIUM + 原型；user override 持久化；
escalate/deescalate；llm_judgment hook）。全部断言通过 exit 0，任一失败 exit 1。

## 兼容性

- 输出 YAML 由内置 stdlib emitter 生成（无 PyYAML 依赖），已被 `routing.schema.json`（P3-2
  将补 6 字段）与 `layer.schema.json`（P3-2 将补 bake_policy / role 16 枚举）契约对齐。
- 本模块不修改 `schemas/`、不修改其它 skill 文件；Schema 增补属 P3-2。
