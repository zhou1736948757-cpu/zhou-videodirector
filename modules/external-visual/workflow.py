#!/usr/bin/env python3
"""workflow.py — Generative Video Workflow Modes（Phase-6 Prompt §29-30/§78-79/§41/§115-117；P6-06）.

Phase 6 执行模式与提案记录层：

- §29 run_manual     一等公民：导出 packet → 用户网页生成 → 返回文件 → P6-04 ingest。
                     本函数不阻塞等待，只落导出物与状态记录（WAITING_USER）。
- §30 run_assisted   ZHOU 完成 packet/search/metadata，生成/购买由用户执行 → READY_FOR_USER。
- §115-116 run_automated  无凭据/无成本规则时一律 BLOCKED_NOT_CONFIGURED 并回退建议
                     run_manual；绝不清空拦截（本阶段无真实凭据）。
- §78-79 route_optimization  ROUTE_OPTIMIZATION_PROPOSAL（RO-###）：只提案，
                     状态机不允许直接改 routing 文件。
- §41 production_conflict    PRODUCTION_CONFLICT（PC-###，docs/production.md §3 字段）：
                     shot split 必须批准后才改 storyboard。

FR-025 对齐（R2）：结构化记录（RO-###/PC-###）一律只落独立记录/状态文件（本模块写
workflow-state.json；packet_builder 的 PRODUCTION_CONFLICT 写独立 PC-###.json），
禁止把 JSON 序列化塞进 generation_notes——packet/请求里只引用记录 id。本模块
不写 generation_notes 字段（已 grep 核验无该路径）。

状态落盘到工作区/项目状态文件（JSON，workflow-state.json），不依赖对话记忆。
attempt 计数与 BLOCKED 语义与 P6-05 review.py 的 §117 阶梯衔接（本单只做 workflow 侧状态）。

技术约束：**Python3 stdlib only**；无 LLM；无联网；确定性。
代码风格照抄 modules/production/planner.py。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

import importlib as _importlib

# 包目录含连字符（modules/external-visual），import 语句无法写这段名——
# 按本包约定用 importlib 加载兄弟模块（gates.py，§115-116）。
_gates_mod = _importlib.import_module("modules.external-visual.gates")
automation_level = _gates_mod.automation_level

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: RO / PC 记录 ID 模式（P6-01 契约）
RO_ID_RE = re.compile(r"^RO-\d{3}$")
PC_ID_RE = re.compile(r"^PC-\d{3}$")

#: workflow 状态文件（JSON）
STATE_FILENAME = "workflow-state.json"

#: §115 三档枚举
AUTOMATION_LEVELS = ("MANUAL", "ASSISTED", "AUTOMATED")

#: §117 失败恢复阶梯（与 P6-05 review.py 衔接；workflow 侧仅记录 attempt 状态）
RETRY_STEPS = {1: "prompt_refinement", 2: "reduce_complexity", 3: "alternative_strategy"}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 状态落盘（JSON，工作区/项目状态文件）
# ---------------------------------------------------------------------------

def load_state(state_dir) -> dict:
    """读 <state_dir>/workflow-state.json；缺失 → 空结构。"""
    p = Path(state_dir) / STATE_FILENAME
    if not p.is_file():
        return {"route_optimizations": {}, "production_conflicts": {},
                "workflow_runs": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"route_optimizations": {}, "production_conflicts": {},
                "workflow_runs": []}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("route_optimizations", {})
    data.setdefault("production_conflicts", {})
    data.setdefault("workflow_runs", [])
    return data


def save_state(state_dir, data: dict) -> Path:
    """写 <state_dir>/workflow-state.json（确定性 JSON）。"""
    p = Path(state_dir) / STATE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return p


def _next_id(state: dict, key: str, prefix: str) -> str:
    """从 state 字典计算下一个 RO-###/PC-###（确定性递增）。"""
    nums = []
    for rid in (state.get(key) or {}):
        m = re.match(rf"^{prefix}-(\d{{3}})$", str(rid))
        if m:
            nums.append(int(m.group(1)))
    return f"{prefix}-{max(nums) + 1 if nums else 1:03d}"


# ---------------------------------------------------------------------------
# §29 MANUAL / §30 ASSISTED / §115-116 AUTOMATED
# ---------------------------------------------------------------------------

def run_manual(packet: dict, provider_cap: dict, out_dir) -> dict:
    """§29 一等公民：导出 packet → 等外部文件 → 交给 P6-04 ingest。

    落盘 {packet_id}_prompt.txt + {packet_id}_instructions.md（manual_web adapter），
    返回 {status: WAITING_USER, exports[], handoff_note} 并把状态记录写进
    <out_dir>/workflow-state.json（本函数不阻塞等待，不产生任何生成调用）。
    """
    _manual_mod = _importlib.import_module("adapters.generative-video.manual_web")
    export_packet = _manual_mod.export_packet

    res = export_packet(packet, provider_cap, out_dir)
    state = load_state(out_dir)
    state["workflow_runs"].append({
        "mode": "manual",
        "packet_id": res.get("packet_id"),
        "status": "WAITING_USER",
        "exports": res.get("exports"),
        "handoff_note": res.get("handoff_note"),
        "created_at": _now_iso(),
    })
    save_state(out_dir, state)
    return res


def run_assisted(packet: dict, request: dict, registry_opts: dict) -> dict:
    """§30 ASSISTED：ZHOU 完成 packet/search/metadata，生成/购买由用户执行。

    `registry_opts` 需含 `out_dir`（落盘 packet 副本与状态记录），可选
    `providers`（候选 provider 能力清单）与 `search_budget`（§119）。
    返回 {status: READY_FOR_USER, packet_path, search_summary}。
    """
    if not isinstance(registry_opts, dict) or not registry_opts.get("out_dir"):
        raise ValueError("run_assisted 需要 registry_opts.out_dir（落盘位置）")
    out_dir = Path(registry_opts["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    packet_id = str(packet.get("packet_id") or "GV-000")
    packet_path = out_dir / f"{packet_id}_packet.json"
    packet_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")

    providers = registry_opts.get("providers") or []
    budget = registry_opts.get("search_budget") or {}
    if providers:
        search_summary = (
            f"packet={packet_id} 已就绪；候选 provider："
            + ", ".join(str(p.get("provider_id") or p) for p in providers)
            + f"；search_budget={budget or '未指定'}。生成/购买由用户执行（§30）。"
        )
    else:
        search_summary = (
            f"packet={packet_id} 已就绪；暂无候选 provider（用户可自行选择生成/购买渠道，§30）。"
        )

    state = load_state(out_dir)
    state["workflow_runs"].append({
        "mode": "assisted",
        "packet_id": packet_id,
        "status": "READY_FOR_USER",
        "packet_path": str(packet_path),
        "search_summary": search_summary,
        "created_at": _now_iso(),
    })
    save_state(out_dir, state)

    return {
        "status": "READY_FOR_USER",
        "packet_id": packet_id,
        "packet_path": str(packet_path),
        "search_summary": search_summary,
    }


def run_automated(packet: dict, provider_cap: dict, project_config: dict) -> dict:
    """§115-116 run_automated：无凭据/无成本规则时一律 BLOCKED_NOT_CONFIGURED。

    - automation_level 非 AUTOMATED，或 provider_cap.api_available != true
      → {status: BLOCKED_NOT_CONFIGURED, missing[], fallback: run_manual}。
      绝不清空拦截（本阶段无真实凭据，恒为拦截态）。
    - 理论就绪 → 仅返回 generation_instructions（生成说明），引擎不调用任何
      第三方生成 API（P6-06 硬规则）。
    """
    level = automation_level(project_config)
    if level["automation_level"] != "AUTOMATED" or not provider_cap.get("api_available"):
        missing = list(level.get("missing") or [])
        if not provider_cap.get("api_available"):
            missing.append("api_available=false（未配置凭据）")
        return {
            "status": "BLOCKED_NOT_CONFIGURED",
            "automation_level": level["automation_level"],
            "provider_id": provider_cap.get("provider_id"),
            "missing": missing,
            "reason": level.get("reason"),
            "fallback": "run_manual",
            "fallback_hint": "回退建议：run_manual（人工网页生成，§29 一等公民）；"
                             "拦截绝不清空（§116）",
            "blocks_cleared": False,
        }
    # 理论就绪分支：只产出生成说明（generation instructions），不产生任何真实调用。
    _base_mod = _importlib.import_module("adapters.generative-video.base")
    adapter = _base_mod.ProviderAdapter(provider_cap)
    instructions = adapter.generation_instructions(packet, provider_cap)
    return {
        "status": "INSTRUCTIONS_READY",
        "automation_level": "AUTOMATED",
        "provider_id": provider_cap.get("provider_id"),
        "instructions": instructions,
        "note": "仅生成说明；引擎不调用任何第三方生成 API、不自动上传素材（P6-06 硬规则）。",
    }


# ---------------------------------------------------------------------------
# §78-79 ROUTE_OPTIMIZATION_PROPOSAL（RO-###，只提案）
# ---------------------------------------------------------------------------

def route_optimization(proposal: dict, state_dir=None) -> dict:
    """§78-79/Test 20：ROUTE_OPTIMIZATION_PROPOSAL（RO-###）。

    proposal：{shot_id, current_route, proposed_route, reason, evidence}。
    只产出提案记录 + approval_required=true；绝不修改 routing 文件。
    """
    need = ("shot_id", "current_route", "proposed_route", "reason")
    missing = [k for k in need if not str(proposal.get(k) or "").strip()]
    if missing:
        raise ValueError(f"route_optimization 缺少字段: {missing}（§78）")
    sd = Path(state_dir) if state_dir is not None else Path.cwd()
    state = load_state(sd)
    rid = _next_id(state, "route_optimizations", "RO")
    record = {
        "record_id": rid,
        "type": "ROUTE_OPTIMIZATION_PROPOSAL",
        "shot_id": str(proposal["shot_id"]),
        "current_route": str(proposal["current_route"]),
        "proposed_route": str(proposal["proposed_route"]),
        "reason": str(proposal["reason"]),
        "evidence": proposal.get("evidence"),
        "approval_required": True,
        "routing_files_modified": False,
        "created_at": _now_iso(),
    }
    state["route_optimizations"][rid] = record
    save_state(sd, state)
    return record


# ---------------------------------------------------------------------------
# §41 PRODUCTION_CONFLICT（PC-###，docs/production.md §3 字段）
# ---------------------------------------------------------------------------

def production_conflict(conflict: dict, state_dir=None) -> dict:
    """§41/Test 20：PRODUCTION_CONFLICT（PC-###）。

    conflict 字段对齐 docs/production.md §3：{shot_id, problem, technical_reason,
    visual_impact, alternatives[], recommended_alternatives, conflict_type, note}。
    shot split 等 storyboard 修改必须批准后才执行——本函数只产出记录。
    """
    if not isinstance(conflict, dict):
        raise ValueError("production_conflict 需要 conflict dict")
    need = ("shot_id", "problem", "technical_reason", "visual_impact")
    missing = [k for k in need if not str(conflict.get(k) or "").strip()]
    if missing:
        raise ValueError(f"production_conflict 缺少字段: {missing}（docs/production.md §3）")
    sd = Path(state_dir) if state_dir is not None else Path.cwd()
    state = load_state(sd)
    rid = _next_id(state, "production_conflicts", "PC")
    alternatives = conflict.get("alternatives") or []
    if not isinstance(alternatives, list):
        alternatives = [alternatives]
    record = {
        "record_id": rid,
        "conflict_type": conflict.get("conflict_type") or "DESIGN_UNFEASIBLE",
        "shot_id": str(conflict["shot_id"]),
        "problem": str(conflict["problem"]),
        "technical_reason": str(conflict["technical_reason"]),
        "visual_impact": str(conflict["visual_impact"]),
        "alternatives": alternatives,
        "recommended_alternatives": alternatives,
        "note": conflict.get("note"),
        "approval_required": True,
        "storyboard_modified": False,
        "created_at": _now_iso(),
    }
    state["production_conflicts"][rid] = record
    save_state(sd, state)
    return record


# ---------------------------------------------------------------------------
# §117 attempt 状态（workflow 侧；与 P6-05 review.py 阶梯衔接）
# ---------------------------------------------------------------------------

def attempt_step(attempt: int) -> str:
    """§117：失败第 attempt 次的下一步动作；>3 → BLOCKED（不无限循环）。

    与 P6-05 review.py 的 §117 语义一致：1 → prompt_refinement，2 →
    reduce_complexity，3 → alternative_strategy，>3 → BLOCKED。
    """
    return RETRY_STEPS.get(int(attempt), "BLOCKED")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv: list) -> int:
    """命令行入口：
        python3 -m modules.external-visual.workflow manual <packet.json> <provider_cap.json> <out_dir>
        python3 -m modules.external-visual.workflow assisted <packet.json> <registry_opts.json>
        python3 -m modules.external-visual.workflow automated <packet.json> <provider_cap.json> <project_config.json>
        python3 -m modules.external-visual.workflow route-optimization <proposal.json> <state_dir>
        python3 -m modules.external-visual.workflow conflict <conflict.json> <state_dir>
        python3 -m modules.external-visual.workflow attempt <n>
    """
    if not argv:
        print(__doc__.splitlines()[0])
        return 2
    cmd = argv[0]
    if cmd == "manual":
        packet = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        cap = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(run_manual(packet, cap, argv[3]), ensure_ascii=False, indent=2))
        return 0
    if cmd == "assisted":
        packet = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        registry_opts = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        print(json.dumps(run_assisted(packet, {}, registry_opts), ensure_ascii=False, indent=2))
        return 0
    if cmd == "automated":
        packet = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        cap = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        cfg = json.loads(Path(argv[3]).read_text(encoding="utf-8"))
        print(json.dumps(run_automated(packet, cap, cfg), ensure_ascii=False, indent=2))
        return 0
    if cmd == "route-optimization":
        proposal = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        print(json.dumps(route_optimization(proposal, argv[2] if len(argv) > 2 else None),
                         ensure_ascii=False, indent=2))
        return 0
    if cmd == "conflict":
        conflict = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        print(json.dumps(production_conflict(conflict, argv[2] if len(argv) > 2 else None),
                         ensure_ascii=False, indent=2))
        return 0
    if cmd == "attempt":
        print(attempt_step(int(argv[1])))
        return 0
    print(f"未知子命令: {cmd}")
    return 2


def selftest() -> None:
    import tempfile
    checks = [
        # §29 run_manual：WAITING_USER + 两个导出物 + 状态落盘
        (lambda: _check_manual()),
        # §30 run_assisted：READY_FOR_USER + packet_path + search_summary
        (lambda: _check_assisted()),
        # §115-116 run_automated：无凭据 → BLOCKED_NOT_CONFIGURED + fallback manual
        (lambda: _check_automated_blocked()),
        # §78-79 RO-###：只提案、不碰 routing、approval_required
        (lambda: _check_route_opt()),
        # §41 PC-###：approval_required + storyboard 不改
        (lambda: _check_conflict()),
        # §117 attempt 阶梯
        (lambda: attempt_step(1) == "prompt_refinement"),
        (lambda: attempt_step(2) == "reduce_complexity"),
        (lambda: attempt_step(3) == "alternative_strategy"),
        (lambda: attempt_step(4) == "BLOCKED"),
        (lambda: attempt_step(9) == "BLOCKED"),
    ]
    for i, check in enumerate(checks, 1):
        if not check():
            raise AssertionError(f"workflow selftest check #{i} failed")
    print("workflow selftest OK")


def _check_manual() -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        packet = {"packet_id": "GV-001", "shot_id": "S001", "layer_id": "S001-L01",
                  "purpose": "transition", "duration": 8, "resolution": {"w": 1920, "h": 1080},
                  "aspect_ratio": "16:9", "fps": 24, "camera_movement": "PUSH_IN",
                  "model_ready_prompt": "dreamlike memory museum", "negative_prompt": "",
                  "recommended_variant_count": 2}
        cap = {"provider_id": "manual-web", "model": "UNKNOWN", "text_to_video": True,
               "image_to_video": True, "first_last_frame": False, "reference_image": True,
               "character_reference": False, "camera_control": "partial",
               "duration_options": [{"min": 3, "max": 15}], "resolution_options": ["1920x1080"],
               "aspect_ratios": ["16:9"], "audio_generation": False, "seed_control": False,
               "commercial_terms": "", "api_available": False, "manual_generation_supported": True}
        res = run_manual(packet, cap, td)
        if res.get("status") != "WAITING_USER" or len(res.get("exports")) != 2:
            return False
        if not Path(res["exports"][0]).is_file() or not Path(res["exports"][1]).is_file():
            return False
        if "model_ready_prompt" not in Path(res["exports"][0]).read_text(encoding="utf-8"):
            return False
        st = load_state(td)
        return len(st["workflow_runs"]) == 1 and st["workflow_runs"][0]["status"] == "WAITING_USER"


def _check_assisted() -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        packet = {"packet_id": "GV-002", "shot_id": "S002"}
        res = run_assisted(packet, {}, {"out_dir": td, "providers": [
            {"provider_id": "provider-t2v-cinematic"}]})
        if res.get("status") != "READY_FOR_USER":
            return False
        if not Path(res["packet_path"]).is_file():
            return False
        return "候选 provider" in res["search_summary"]


def _check_automated_blocked() -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        packet = {"packet_id": "GV-003", "duration": 8, "resolution": {"w": 1920, "h": 1080}}
        cap = {"provider_id": "provider-t2v-cinematic", "model": "UNKNOWN", "api_available": False,
               "text_to_video": True, "image_to_video": True, "first_last_frame": True,
               "reference_image": True, "character_reference": True, "camera_control": True,
               "duration_options": [5, 8], "resolution_options": ["1920x1080"],
               "aspect_ratios": ["16:9"], "audio_generation": False, "seed_control": True,
               "commercial_terms": "", "manual_generation_supported": True}
        res = run_automated(packet, cap, {"providers": {"provider-t2v-cinematic": {
            "configured": True, "authorized": True, "cost_rules": {"max": 10}}}})
        if res.get("status") != "BLOCKED_NOT_CONFIGURED":
            return False
        return res.get("fallback") == "run_manual" and res.get("blocks_cleared") is False


def _check_route_opt() -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rec = route_optimization({"shot_id": "S001", "current_route": "GENERATIVE_VIDEO",
                                  "proposed_route": "REAL_FOOTAGE", "reason": "found NASA footage",
                                  "evidence": "registry: nasa:footage:x"}, td)
        if not RO_ID_RE.match(rec["record_id"]):
            return False
        if rec["approval_required"] is not True or rec["routing_files_modified"] is not False:
            return False
        st = load_state(td)
        return rec["record_id"] in st["route_optimizations"]


def _check_conflict() -> bool:
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rec = production_conflict({"shot_id": "S018", "problem": "无法稳定生成",
                                   "technical_reason": "多角色+复杂运镜",
                                   "visual_impact": "一致性下降", "alternatives": ["S018A+S018B"]}, td)
        if not PC_ID_RE.match(rec["record_id"]):
            return False
        if rec["approval_required"] is not True or rec["storyboard_modified"] is not False:
            return False
        st = load_state(td)
        return rec["record_id"] in st["production_conflicts"]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        selftest()
    else:
        sys.exit(_cli(sys.argv[1:]))
