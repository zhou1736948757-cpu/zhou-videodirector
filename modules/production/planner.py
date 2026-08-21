#!/usr/bin/env python3
"""planner.py — Production Planner（Phase-5 Prompt §76-79 / §93-94 / §99；P5-2）.

生产规划层：把已批准设计（Approved Storyboard + Routing + Resource Selection，
总设计 §5 "只吃已批准设计"）转成 Production Request（PR-###，字段对齐
`schemas/production-request.schema.json`），并负责：

- §76 状态机语义（11 状态：PLANNED → WAITING_APPROVAL/READY → … → COMPLETED/FAILED/BLOCKED）
- §23/§5 审批分类：复杂 motion / hero 3D / 昂贵 render / 定制音乐 → WAITING_APPROVAL，
  普通低风险微动画 → READY
- §5  PRODUCTION_CONFLICT 协议（docs/production.md §3 字段格式）：设计不可实现时
  不偷偷改，产出冲突记录（approval_required=true），请求停在 WAITING_APPROVAL
- §99 Render Profile 4 级（PREVIEW 720p / STANDARD 1080p / HIGH 项目分辨率 / FINAL 交付级；
  Phase 5 拒绝 FINAL 并提示）
- §79 spec hash（规范化 JSON → sha256；spec = 设计引用 + 资源引用 + 参数 + 版本，
  见 `spec_content`；轻量，不建 build 系统）
- §94 重试上限（normal_fix → targeted_fix → alternative_approach → BLOCKED）
- §78 依赖跟踪（dependencies 字段解析出 PR-### 依赖链）

技术约束：**Python stdlib only**。YAML 读取优先复用 scripts/registry.py 的
`load_json_or_yaml` 桥（Phase-4 产物，stdlib 实现，已验证）；桥不可用时
降级为 json + 内置 flat-subset 解析（覆盖 Router stdlib emitter 的平铺字段）。

确定性：本模块无 LLM、无随机；相同输入 → 相同输出。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 共享契约常量（与 schemas/ 对齐）
# ---------------------------------------------------------------------------

PRODUCTION_STATUSES = (
    "PLANNED",
    "WAITING_APPROVAL",
    "READY",
    "IN_PROGRESS",
    "PREVIEW_READY",
    "REVISION_REQUESTED",
    "RENDERING",
    "VALIDATING",
    "COMPLETED",
    "FAILED",
    "BLOCKED",
)

REQUEST_ID_RE = re.compile(r"^PR-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")

ROUTES = (
    "REMOTION",
    "THREE_D",
    "REAL_FOOTAGE",
    "GENERATIVE_VIDEO",
    "JY_NATIVE",
    "HYBRID",
    "UNDECIDED",
)

# production-request.schema.json：asset_type 18 枚举
ASSET_TYPES = (
    "FULL_SCENE", "MOTION_CLIP", "TRANSPARENT_OVERLAY", "ANIMATED_TEXT",
    "3D_ELEMENT", "BACKGROUND", "PARTICLE_LAYER", "TRANSITION_ASSET",
    "INFOGRAPHIC", "UI_COMPONENT", "DECORATIVE_ELEMENT", "FOOTAGE",
    "IMAGE", "MUSIC", "SFX", "VOICEOVER", "AMBIENCE", "SOUNDFONT",
)

# editability_policy 3 枚举（production-request.schema.json，沿 routing.bake_policy）
BAKE_POLICIES = ("KEEP_EDITABLE", "ASSET_REPLACEABLE", "BAKE")
EDITABILITY_LEVELS = ("HIGH", "MEDIUM", "LOW")  # 导演侧 Phase-3 语义，可兼容传入

QUALITY_TARGETS = ("PREVIEW", "STANDARD", "HIGH", "FINAL")

APPROVAL_STATUSES = ("pending", "approved", "rejected")

PRODUCER_FOR_ROUTE = {
    "REMOTION": "REMOTION",
    "THREE_D": "THREE_D",
    "REAL_FOOTAGE": "REAL_FOOTAGE",
    "GENERATIVE_VIDEO": "GENERATIVE_VIDEO",
    "JY_NATIVE": "JY_NATIVE",
    "HYBRID": "HYBRID",
}

# §99 Render Profile 4 级（宽高以像素计）。
RENDER_PROFILES = {
    "PREVIEW": {"width": 1280, "height": 720,
                "usage": "低清 preview（720p；复杂/昂贵资产先确认再高质量产出，§89-91）"},
    "STANDARD": {"width": 1920, "height": 1080,
                 "usage": "标准资产渲染（1080p）"},
    "HIGH": {"width": None, "height": None,
             "usage": "项目分辨率（Phase 5 生产最高级别）"},
    "FINAL": {"width": None, "height": None,
              "usage": "交付级渲染（含调色/终混/母版）；Phase 5 拒绝该请求"},
}

# §94 重试上限：失败第 n 次 → 下一步动作；>3 即 BLOCKED，不无限循环。
RETRY_STEPS = {1: "normal_fix", 2: "targeted_fix", 3: "alternative_approach"}

# §76 状态机（显式允许迁移；REVISION_REQUESTED / FAILED / BLOCKED 任意态可达）。
_EXPLICIT_TRANSITIONS = {
    "PLANNED": {"WAITING_APPROVAL", "READY"},
    "WAITING_APPROVAL": {"READY", "BLOCKED"},
    "READY": {"IN_PROGRESS", "PREVIEW_READY"},
    "IN_PROGRESS": {"RENDERING", "PREVIEW_READY"},
    "PREVIEW_READY": {"RENDERING", "REVISION_REQUESTED"},
    "RENDERING": {"VALIDATING"},
    "VALIDATING": {"COMPLETED", "REVISION_REQUESTED"},
    "REVISION_REQUESTED": {"READY"},
    "FAILED": {"READY", "IN_PROGRESS"},  # §16 FAILED 允许重试（normal/targeted/alternative fix 后）
    "COMPLETED": set(),
    "BLOCKED": set(),
}
_ANY_TARGET = {"REVISION_REQUESTED", "FAILED", "BLOCKED"}

DEFAULT_PROJECT_RESOLUTION = (1920, 1080)

# classify_request 用关键词标记（§23 复杂 motion / hero 3D / 定制音乐；确定性启发式）。
COMPLEX_MOTION_MARKERS = ("hero", "complex", "climax", "payoff", "复杂", "高复杂度", "大量粒子")
CUSTOM_MUSIC_MARKERS = ("custom", "定制", "procedural", "程序化", "original", "原创")

# 参与 spec hash 的"运行态字段"（排除：状态/审批/落盘/内部字段）。
_OPERATIONAL_FIELDS = {
    "asset_id", "status", "approval_status", "approval", "output", "validation",
    "spec_hash", "dirty", "version", "created_at", "updated_at", "_dep_versions",
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """UTC 时间戳（ISO 8601，秒精度）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_route(route: Optional[str]) -> str:
    if not route:
        return "UNDECIDED"
    r = str(route).upper()
    return r if r in ROUTES else "UNDECIDED"


# ---------------------------------------------------------------------------
# Registry 桥（Reuse→Adapt，§72）：读 Phase-3/4 的 routing / layers 文件
# ---------------------------------------------------------------------------

try:  # scripts/registry.py 为 stdlib 实现（minimal YAML + JSON），Phase-4 已验证
    from scripts.registry import load_json_or_yaml  # type: ignore

    _REGISTRY_BRIDGE = True
except Exception:  # pragma: no cover - 桥缺失时降级
    _REGISTRY_BRIDGE = False
    load_json_or_yaml = None


def _scalar(s: str) -> Any:
    """flat-subset 标量解析（仅作 bridge 缺失时的降级用）。"""
    s = s.strip()
    if s in ("", "null", "~", "None"):
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d*\.\d+", s):
        return float(s)
    return s


def _flat_subset_yaml(text: str) -> dict:
    """极简 YAML subset：只解析顶层 `key: value` 平铺字段（Router emitter 覆盖）。

    仅用于 scripts.registry 桥不可用时的降级路径；完整嵌套由 bridge 负责。
    """
    out: dict = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.startswith(" "):
            continue  # 嵌套块在降级模式跳过（顶层字段已足够 planner 使用）
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            out[m.group(1)] = _scalar(m.group(2))
    return out


def _load_routing_file(path: Path):
    """读取 routing/layers 文件，返回 (data, error)。"""
    if not path.is_file():
        return None, f"missing {path}"
    if _REGISTRY_BRIDGE and load_json_or_yaml is not None:
        try:
            return load_json_or_yaml(path)
        except Exception as exc:  # pragma: no cover
            return None, f"bridge failed {path}: {exc}"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {path}: {exc}"
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text), None
        except ValueError as exc:
            return None, f"json error {path}: {exc}"
    try:
        return _flat_subset_yaml(text), None
    except Exception as exc:  # pragma: no cover
        return None, f"parse error {path}: {exc}"


def read_shot_routing(project_dir: str | Path, shot_id: str) -> dict:
    """读 <project>/routing/S###.yaml(.json)（Phase-3 已批准路由，§53）。

    缺文件 / 解析失败 → {}（调用方靠显式参数继续，不伪造路由决策）。
    """
    pd = Path(project_dir)
    for ext in (".yaml", ".yml", ".json"):
        data, err = _load_routing_file(pd / "routing" / f"{shot_id}{ext}")
        if err is None and isinstance(data, dict):
            return data
    return {}


def read_shot_layers(project_dir: str | Path, shot_id: str) -> list:
    """读 <project>/layers/S###.yaml(.json)（Phase-3 Layer 路由，§54）。

    返回 layer dict 列表；缺文件 → []。
    """
    pd = Path(project_dir)
    for ext in (".yaml", ".yml", ".json"):
        data, err = _load_routing_file(pd / "layers" / f"{shot_id}{ext}")
        if err is not None or not isinstance(data, dict):
            continue
        layers = data.get("layers")
        if isinstance(layers, list):
            return [l for l in layers if isinstance(l, dict)]
        return []
    return []


# ---------------------------------------------------------------------------
# §79 spec hash（规范化 JSON → sha256；轻量，不建 build 系统）
# ---------------------------------------------------------------------------

def _canonical(value: Any) -> Any:
    """递归规范化：dict 键转 str 并排序、tuple→list、整值 float→int、
    bool 优先于 int 判断、非有限 float → 字符串。保证 {'a':1}=={'a':1.0}。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return int(value) if isinstance(value, float) and value.is_integer() else value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if value is None:
        return None
    return str(value)


def spec_hash(spec: dict) -> str:
    """§79：规范化 JSON 后 sha256。非 dict 输入按空 spec 处理（确定性）。"""
    if not isinstance(spec, dict):
        spec = {}
    payload = json.dumps(_canonical(spec), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def spec_content(req: dict) -> dict:
    """一条请求的"spec"内容（§79：输入 = 设计引用 + 资源引用 + 参数 + 版本）。

    排除运行态/落盘字段（status/approval/output/validation/hash/dirty/时间戳等），
    使审批、状态推进、输出回填都不会触发"spec 变化"。manifest 以此计算 spec_hash
    并做 dirty detection（§77-79）。
    """
    if not isinstance(req, dict):
        return {}
    return {k: v for k, v in req.items() if k not in _OPERATIONAL_FIELDS}


# ---------------------------------------------------------------------------
# §76 状态机
# ---------------------------------------------------------------------------

def can_transition(current: str, new: str) -> bool:
    """状态迁移是否合法（§76 建议语义；REVISION_REQUESTED/FAILED/BLOCKED 任意态可达）。"""
    c = str(current).upper()
    n = str(new).upper()
    if n in _ANY_TARGET and n not in _EXPLICIT_TRANSITIONS.get(c, set()):
        return True
    return n in _EXPLICIT_TRANSITIONS.get(c, set())


# ---------------------------------------------------------------------------
# Production Request（字段对齐 schemas/production-request.schema.json）
# ---------------------------------------------------------------------------

class ProductionRequest(dict):
    """生产请求（P5-1 schema）。结构上等同 dict，便于 JSON 持久化与引擎传递。"""


def _validate_request_id(request_id: str) -> None:
    if not REQUEST_ID_RE.match(str(request_id)):
        raise ValueError(f"request_id 必须匹配 PR-###，得到 {request_id!r}")


def create_request(
    *,
    request_id: str,
    project_id: Optional[str] = None,
    scene_id: Optional[str] = None,
    shot_id: Optional[str] = None,
    layer_id: Optional[str] = None,
    route: Optional[str] = None,
    asset_type: Optional[str] = None,
    purpose: Optional[str] = None,
    visual_requirements: Optional[str] = None,
    motion_requirements: Optional[str] = None,
    camera_requirements: Optional[str] = None,
    audio_requirements: Optional[str] = None,
    duration: Optional[float] = None,
    resolution: Optional[dict] = None,
    fps: Optional[float] = None,
    alpha_required: Optional[bool] = None,
    continuity_group: Optional[str] = None,
    editability: Optional[str] = None,            # 兼容别名（自检/Phase-3 命名）
    editability_policy: Optional[str] = None,     # schema 字段名
    input_resources: Optional[list] = None,       # 兼容别名（§75 manifest 命名）
    selected_resources: Optional[list] = None,    # schema 字段名
    dependencies: Optional[list] = None,
    quality_target: Optional[str] = None,
    preview_required: Optional[bool] = None,
    approval_status: Optional[str] = None,
    producer: Optional[str] = None,
    spec: Optional[dict] = None,   # 引擎结构化扩展（hero/complexity/music_mode/…）
    project_dir: Optional[str | Path] = None,
    status: Optional[str] = None,
    output: Optional[dict] = None,
    approval: Optional[dict] = None,
    validation: Optional[dict] = None,
) -> ProductionRequest:
    """生成 Production Request（P5-1 schema 字段，全部 required 字段就位）。

    数据来源（§5 只吃已批准设计）：
    - routing/S###.yaml + layers/S###.yaml（Phase-3）：route / continuity_group /
      bake_policy / layer 级 route —— 当 `project_dir` + `shot_id` 给出时自动读取，
      显式参数优先。
    - resource selection（Phase-4）：`selected_resources`（或兼容别名 input_resources）
      由调用方传入 resource_id（{provider}:{type}:{slug}）。

    派生规则（确定性）：
    - `editability` 是 `editability_policy` 的兼容别名（自检脚本用前者）。
    - `quality_target=FINAL` 在 Phase 5 一律回落 HIGH 并记 validation.warning（§7）。
    - `alpha_required` 默认按 asset_type 推导（TRANSPARENT_OVERLAY / 3D_ELEMENT → True）。
    - `approval_status` 默认按 §23 推导（需批 → pending；低风险 → approved 自动放行）。
    - `preview_required` 默认按 §9 推导（复杂/昂贵 → True）。
    - `spec_hash` 由 manifest 管理；本函数先算一次便于引擎侧比对。
    """
    _validate_request_id(request_id)

    # —— 文件派生（可选 enrich；显式参数优先）——
    if project_dir is not None and shot_id is not None:
        routing = read_shot_routing(project_dir, shot_id)
        if route is None:
            route = routing.get("route")
        if continuity_group is None:
            continuity_group = routing.get("continuity_group")
        if editability_policy is None and editability is None and routing.get("bake_policy"):
            editability_policy = routing.get("bake_policy")
        if layer_id is not None:
            for lyr in read_shot_layers(project_dir, shot_id):
                if lyr.get("id") == layer_id or lyr.get("layer_id") == layer_id:
                    if route is None:
                        route = lyr.get("route")
                    if editability_policy is None and editability is None \
                            and lyr.get("bake_policy"):
                        editability_policy = lyr.get("bake_policy")
                    break

    route_n = _normalize_route(route)
    asset_type_n = str(asset_type or "").upper()
    if asset_type_n and asset_type_n not in ASSET_TYPES:
        raise ValueError(f"未知 asset_type={asset_type!r}；允许 {sorted(ASSET_TYPES)}")

    # quality_target：FINAL 在 Phase 5 一律不允许（§7 回落 HIGH 并记说明）。
    qt = str(quality_target or "STANDARD").upper()
    if qt not in QUALITY_TARGETS:
        raise ValueError(f"未知 quality_target={quality_target!r}；允许 {sorted(QUALITY_TARGETS)}")
    qt_warning = None
    if qt == "FINAL":
        qt = "HIGH"
        qt_warning = ("quality_target=FINAL 在 Phase 5 不允许（§99 交付级留给后续 Phase），"
                      "已回落到 HIGH（项目分辨率）并记录说明")

    # editability_policy：schema 字段名；兼容自检脚本的 editability 别名。
    ep = editability_policy or editability or "KEEP_EDITABLE"
    if ep not in BAKE_POLICIES and ep not in EDITABILITY_LEVELS:
        raise ValueError(f"未知 editability={ep!r}；允许 {sorted(BAKE_POLICIES)}")

    if alpha_required is None:
        alpha_required = asset_type_n in ("TRANSPARENT_OVERLAY", "3D_ELEMENT")

    res = dict(resolution) if isinstance(resolution, dict) else {"w": 1920, "h": 1080}
    res.setdefault("w", 1920)
    res.setdefault("h", 1080)

    selected = list(selected_resources if selected_resources is not None
                    else input_resources or [])

    req = ProductionRequest()
    # —— P5-1 schema required 字段 ——
    req["request_id"] = request_id
    req["project_id"] = project_id or (Path(project_dir).name if project_dir else None)
    req["scene_id"] = scene_id
    req["shot_id"] = shot_id
    req["layer_id"] = layer_id
    req["route"] = route_n
    req["asset_type"] = asset_type_n or None
    req["purpose"] = purpose
    req["visual_requirements"] = visual_requirements
    req["motion_requirements"] = motion_requirements
    req["camera_requirements"] = camera_requirements
    req["audio_requirements"] = audio_requirements
    req["duration"] = duration
    req["resolution"] = {"w": int(res["w"]), "h": int(res["h"])}
    req["fps"] = fps
    req["alpha_required"] = bool(alpha_required)
    req["continuity_group"] = continuity_group
    req["editability_policy"] = ep
    req["selected_resources"] = selected
    req["dependencies"] = list(dependencies) if dependencies else []
    req["quality_target"] = qt
    req["preview_required"] = preview_required  # 下方按 §9 推导回填
    req["approval_status"] = None  # 下方按 §23 推导回填
    req["status"] = str(status or "PLANNED").upper()

    # —— 引擎 / manifest 管理字段 ——
    req["asset_id"] = None
    req["producer"] = producer or PRODUCER_FOR_ROUTE.get(route_n, "UNDECIDED")
    req["spec"] = dict(spec) if isinstance(spec, dict) else {}
    req["spec_hash"] = None  # 审批/预览推导后统一计算（manifest.add 会重算）
    req["version"] = "v1"
    req["dirty"] = False
    req["approval"] = dict(approval) if isinstance(approval, dict) else {
        "required": False, "status": "not_required", "reason": None,
    }
    req["output"] = dict(output) if isinstance(output, dict) else {
        "format": None, "resolution": None, "fps": None,
        "alpha": None, "local_path": None, "preview_path": None,
    }
    req["validation"] = dict(validation) if isinstance(validation, dict) else {
        "schema": "production-request", "valid": None, "errors": [], "warnings": [],
    }
    now = now_iso()
    req["created_at"] = now
    req["updated_at"] = now

    # —— 审批 / 预览推导（§23 / §9，确定性）——
    reasons = approval_reasons(req)
    if approval_status is not None:
        if str(approval_status) not in APPROVAL_STATUSES:
            raise ValueError(f"未知 approval_status={approval_status!r}；"
                             f"允许 {sorted(APPROVAL_STATUSES)}")
        req["approval_status"] = str(approval_status)
    else:
        req["approval_status"] = "pending" if reasons else "approved"
    if approval is None:
        req["approval"] = {
            "required": bool(reasons),
            "status": req["approval_status"],
            "reason": "；".join(reasons) if reasons else None,
        }
    if req["preview_required"] is None:
        req["preview_required"] = bool(reasons) or qt == "HIGH"

    if qt_warning is not None:
        req["validation"]["warnings"] = list(req["validation"]["warnings"]) + [qt_warning]

    req["spec_hash"] = spec_hash(spec_content(req))  # §79（manifest 以同一口径重算/比对）
    return req


# ---------------------------------------------------------------------------
# §23/§5 审批分类
# ---------------------------------------------------------------------------

def approval_reasons(req: dict) -> list:
    """返回需要 WAITING_APPROVAL 的可解释原因列表（空 = 低风险可直产 READY）。"""
    if not isinstance(req, dict):
        return []
    route = _normalize_route(req.get("route"))
    producer = str(req.get("producer") or "").upper()
    asset_type = str(req.get("asset_type") or "").upper()
    qt = str(req.get("quality_target") or "").upper()
    spec = req.get("spec") or {}
    reasons: list = []

    # 昂贵 / 高不确定性路由
    if route in ("GENERATIVE_VIDEO", "HYBRID"):
        reasons.append(f"route={route}：生成式/混合路由成本与一致性不确定")
    # Hero / 复杂 3D（§23）
    hero3d = (
        route == "THREE_D" or asset_type == "3D_ELEMENT"
    ) and (
        spec.get("hero") is True
        or str(spec.get("complexity") or "").lower() in ("complex", "hero", "high")
        or _has_marker(req, "visual_requirements", "motion_requirements",
                       markers=COMPLEX_MOTION_MARKERS)
    )
    if hero3d:
        reasons.append("hero/复杂 3D：渲染昂贵，需先确认设计与预算")
    # 昂贵渲染：HIGH 档或 ≥4K
    if qt in ("HIGH", "FINAL"):
        reasons.append(f"quality_target={qt}：昂贵渲染需先确认")
    res = req.get("resolution")
    if isinstance(res, dict):
        h = res.get("h") or res.get("height")
        if isinstance(h, (int, float)) and h >= 2160:
            reasons.append(f"resolution={int(h)}p：≥4K 昂贵渲染需先确认")
    # 定制 / 程序化音乐（§23）
    if producer in ("FLUIDSYNTH", "PROCEDURAL_MUSIC", "CUSTOM_MUSIC"):
        reasons.append("定制/程序化音乐：音乐方向需先确认")
    elif (asset_type == "MUSIC"
          and _has_marker(req, "audio_requirements", None, markers=CUSTOM_MUSIC_MARKERS)):
        reasons.append("定制音乐：音乐方向需先确认")
    music_mode = spec.get("music_mode") or spec.get("custom_music")
    if music_mode in ("CUSTOM", "PROCEDURAL") or spec.get("custom_music") is True:
        reasons.append("custom music：定制音乐需先确认")
    # 显式标记
    if spec.get("approval_required") is True:
        reasons.append("spec 显式标记 approval_required")
    if str(spec.get("estimated_cost") or "").upper() == "EXPENSIVE":
        reasons.append("estimated_cost=EXPENSIVE：昂贵生产需先确认")
    # 去重保序
    seen: set = set()
    out = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _has_marker(req: dict, *fields: Optional[str], markers: tuple) -> bool:
    text = " ".join(
        str(req.get(f) or "") for f in fields if f is not None
    ).lower()
    return any(mk.lower() in text for mk in markers)


def classify_request(req: dict) -> str:
    """§23 审批分类：返回 'WAITING_APPROVAL'（需批）或 'READY'（低风险可直产）。

    复杂 motion / hero 3D / 昂贵 render / 定制音乐 → WAITING_APPROVAL；
    普通低风险微动画 → READY。
    """
    if not isinstance(req, dict):
        raise ValueError("classify_request 需要 ProductionRequest dict")
    return "WAITING_APPROVAL" if approval_reasons(req) else "READY"


# ---------------------------------------------------------------------------
# §5 PRODUCTION_CONFLICT 协议（docs/production.md §3 字段格式）
# ---------------------------------------------------------------------------

def raise_conflict(
    req,
    problem: str,
    technical_reason: str,
    visual_impact: str,
    alternatives: list,
    conflict_type: str = "DESIGN_UNFEASIBLE",
    request_note: Optional[str] = None,
) -> dict:
    """§5：引擎发现设计不可实现时调用 —— 不偷偷改，产出冲突记录等待审批/裁决。

    字段对齐 docs/production.md §3：
        {request_id, conflict_type, request, problem, technical_reason,
         visual_impact, alternatives, recommended_alternatives, approval_required: true}
    conflict_type ∈ DESIGN_UNFEASIBLE | RENDER_LIMIT | LICENSE_ISSUE |
                     DEPENDENCY_MISSING | OTHER。
    """
    if isinstance(req, dict):
        request_id = req.get("request_id")
    else:
        request_id = req
    _validate_request_id(request_id)
    if conflict_type not in ("DESIGN_UNFEASIBLE", "RENDER_LIMIT", "LICENSE_ISSUE",
                             "DEPENDENCY_MISSING", "OTHER"):
        raise ValueError(f"未知 conflict_type={conflict_type!r}")
    return {
        "request_id": request_id,
        "conflict_type": conflict_type,
        "request": request_note if request_note is not None else str(problem),
        "problem": str(problem),
        "technical_reason": str(technical_reason),
        "visual_impact": str(visual_impact),
        "alternatives": list(alternatives),
        "recommended_alternatives": list(alternatives),
        "approval_required": True,
        "created_at": now_iso(),
    }


# ---------------------------------------------------------------------------
# §99 Render Profile
# ---------------------------------------------------------------------------

def render_profile(quality_target: str, project_resolution=None) -> dict:
    """§99 Render Profile 4 级。

    PREVIEW → 720p；STANDARD → 1080p；HIGH → 项目分辨率；
    FINAL → 交付级 —— **Phase 5 拒绝 FINAL 请求并提示**（raise ValueError）。

    `project_resolution` 可给 tuple/list(w,h) 或 dict{w,h|width,height}；
    缺省时 HIGH 用 1920x1080（并注明推断）。
    """
    q = str(quality_target or "").upper()
    if q not in RENDER_PROFILES:
        raise ValueError(
            f"未知 quality_target={quality_target!r}；允许 {sorted(RENDER_PROFILES)}"
        )
    base = RENDER_PROFILES[q]

    if q == "FINAL":
        raise ValueError(
            "Phase 5 拒绝 FINAL 渲染请求：FINAL 为交付级渲染（调色/终混/母版），"
            "Phase 5 生产阶段最高支持 HIGH（项目分辨率）。"
            "请先用 PREVIEW/STANDARD/HIGH 产出资产，交付渲染交给后续 FINISH 阶段。"
        )

    if q == "HIGH":
        w, h, note = _resolve_project_resolution(project_resolution)
        return {
            "name": "HIGH",
            "resolution": f"{w}x{h}",
            "width": w,
            "height": h,
            "usage": base["usage"],
            "note": note,
        }

    return {
        "name": q,
        "resolution": f"{base['width']}x{base['height']}",
        "width": base["width"],
        "height": base["height"],
        "usage": base["usage"],
    }


def _resolve_project_resolution(project_resolution):
    """解析项目分辨率；无法确定时回退 1920x1080 并注明。"""
    pr = project_resolution
    if isinstance(pr, (tuple, list)) and len(pr) == 2:
        try:
            w, h = int(pr[0]), int(pr[1])
            return w, h, "来自 project_resolution 参数"
        except (TypeError, ValueError):
            pass
    if isinstance(pr, dict):
        w = pr.get("w", pr.get("width"))
        h = pr.get("h", pr.get("height"))
        try:
            return int(w), int(h), "来自 project_resolution 参数"
        except (TypeError, ValueError):
            pass
    w, h = DEFAULT_PROJECT_RESOLUTION
    return w, h, "项目分辨率未提供，按默认 1920x1080 处理"


# ---------------------------------------------------------------------------
# §94 重试策略
# ---------------------------------------------------------------------------

def retry_policy(attempt: int, error_type: str) -> str:
    """§94：失败第 attempt 次后的下一步动作。

    1 → normal_fix；2 → targeted_fix；3 → alternative_approach；>3 → BLOCKED（不无限循环）。
    `error_type` 保留用于将来按错误类分流（当前不改变结果，保证确定性）。
    """
    return RETRY_STEPS.get(int(attempt), "BLOCKED")


# ---------------------------------------------------------------------------
# §78 依赖跟踪
# ---------------------------------------------------------------------------

def depends_on(req: dict) -> list:
    """从 dependencies 字段解析 PR-### 依赖请求链（§78）。

    兼容三种形态：["PR-001"]；[{"type":"…","target_id":"PR-001"}]；
    {"production": ["PR-001", …]}。保持顺序、去重。
    """
    if not isinstance(req, dict):
        return []
    deps = req.get("dependencies")
    result: list = []

    def add(x):
        if x is not None and x not in result:
            result.append(x)

    if isinstance(deps, list):
        for d in deps:
            if isinstance(d, str):
                if REQUEST_ID_RE.match(d):
                    add(d)
            elif isinstance(d, dict):
                t = d.get("target_id") or d.get("request_id")
                if t and REQUEST_ID_RE.match(str(t)):
                    add(str(t))
    elif isinstance(deps, dict):
        for v in deps.values():
            if isinstance(v, list):
                for t in v:
                    if isinstance(t, str) and REQUEST_ID_RE.match(t):
                        add(t)
            elif isinstance(v, str) and REQUEST_ID_RE.match(v):
                add(v)
    return result


# ---------------------------------------------------------------------------
# P5-1 schema 审计工具（可选；manifest 不强制调用）
# ---------------------------------------------------------------------------

_SCHEMA_REQUIRED = (
    "request_id", "project_id", "route", "asset_type", "purpose",
    "visual_requirements", "motion_requirements", "camera_requirements",
    "audio_requirements", "duration", "resolution", "fps", "alpha_required",
    "continuity_group", "editability_policy", "selected_resources",
    "dependencies", "quality_target", "preview_required", "approval_status", "status",
)


def validate_request(req: dict) -> dict:
    """按 P5-1 schema 审计请求，返回 {valid, errors, warnings}（不抛异常）。

    - required 字段按 **key 存在性** 判定（JSON Schema "required" 语义；值为 None 记
      warning，不算 error——planner 生成的请求可能尚未填满设计细节，引擎补全）。
    - 枚举字段做值校验。
    """
    errors: list = []
    warnings: list = []
    if not isinstance(req, dict):
        return {"valid": False, "errors": ["请求必须是 dict"], "warnings": []}
    for field in _SCHEMA_REQUIRED:
        if field not in req:
            errors.append(f"缺少 required 字段: {field}")
        elif req.get(field) is None:
            warnings.append(f"required 字段 {field} 值为 null（待引擎/调用方补全）")
    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings}
    route = _normalize_route(req.get("route"))
    if route == "UNDECIDED" and req.get("route"):
        warnings.append(f"route={req['route']!r} 不是合法路由枚举，已按 UNDECIDED 处理")
    if str(req.get("status") or "").upper() not in PRODUCTION_STATUSES:
        errors.append(f"status={req.get('status')!r} 不在 11 枚举内")
    if str(req.get("quality_target") or "").upper() not in QUALITY_TARGETS:
        errors.append(f"quality_target={req.get('quality_target')!r} 不在 4 枚举内")
    if str(req.get("approval_status") or "") not in APPROVAL_STATUSES:
        errors.append(f"approval_status={req.get('approval_status')!r} 不在 3 枚举内")
    ep = req.get("editability_policy")
    if ep not in BAKE_POLICIES:
        errors.append(f"editability_policy={ep!r} 不在 3 枚举内")
    if not REQUEST_ID_RE.match(str(req.get("request_id") or "")):
        errors.append("request_id 必须匹配 PR-###")
    return {"valid": not errors, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    checks = [
        spec_hash({"a": 1}) == spec_hash({"a": 1}),
        spec_hash({"a": 1}) != spec_hash({"a": 2}),
        spec_hash({"a": 1}) == spec_hash({"a": 1.0}),
        retry_policy(1, "render") == "normal_fix",
        retry_policy(2, "render") == "targeted_fix",
        retry_policy(3, "render") == "alternative_approach",
        retry_policy(4, "render") == "BLOCKED",
        can_transition("PLANNED", "READY"),
        can_transition("WAITING_APPROVAL", "READY"),
        can_transition("VALIDATING", "COMPLETED"),
        can_transition("PLANNED", "FAILED"),
        not can_transition("RENDERING", "COMPLETED"),
        depends_on({"dependencies": [{"type": "x", "target_id": "PR-001"}, "PR-002"]})
        == ["PR-001", "PR-002"],
        # schema 对齐
        create_request(request_id="PR-001", shot_id="S001", layer_id="S001-L01",
                       route="REMOTION", editability="ASSET_REPLACEABLE")
        ["editability_policy"] == "ASSET_REPLACEABLE",
        create_request(request_id="PR-002", shot_id="S002", route="REMOTION")
        ["quality_target"] == "STANDARD",
        classify_request(create_request(request_id="PR-003", shot_id="S003",
                                        route="REMOTION")) == "READY",
        classify_request(create_request(request_id="PR-004", shot_id="S004",
                                        route="THREE_D", asset_type="3D_ELEMENT",
                                        spec={"hero": True}, quality_target="HIGH"))
        == "WAITING_APPROVAL",
        create_request(request_id="PR-005", shot_id="S005", route="REMOTION",
                       quality_target="FINAL")["quality_target"] == "HIGH",
        raise_conflict("PR-001", "p", "t", "v", ["a"])["approval_required"] is True,
    ]
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"selftest check #{i} failed")
    print("planner selftest OK")


if __name__ == "__main__":
    selftest()
