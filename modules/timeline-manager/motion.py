#!/usr/bin/env python3
"""modules/timeline-manager/motion.py — Motion Spec 归一化 + 采样/预算/升级判定（Phase-7 §39-52；P7-4）.

把一个 Motion Spec（Remotion / JianYing 共用的动效抽象，§39-41）归一化为
`schemas/motion-spec.schema.json` 形状，并承担：

1. ``normalize_motion_spec`` — 把 Phase 5 MOTION_SPEC / timeline_hint / JY_NATIVE 意图
   统一为 motion-spec.schema.json 形状（帧为整数基准 §26-27）。
2. ``plan_sampling`` — §46-48 采样判定：原生 easing 支持→直接曲线；不支持→按
   曲线复杂度/duration/visual sensitivity/backend limits 选 4/6/8/12 采样点。
3. ``keyframe_budget_check`` — §49 关键帧预算（单 clip / 全片）+ 爆炸检测（Test 18）。
4. ``escalation_check`` — §50-51 超预算或 complex 类型 → TIMELINE_OPTIMIZATION_PROPOSAL
   （REMOTION 建议，approval_required=true，只提案，Test 19）。采样点阈值按动效类型
   分型（FR-001 / rv-P7-1b）：simple（linear/ease）> 8 升级；complex
   （cubic_bezier/spring/custom）> 12 升级（§50 curved smooth travel 允许 JY 采样）。
5. ``deescalation_check`` — §52 原 route=REMOTION 但属简单动效 → 建议 JY_NATIVE（提案留痕）。

设计约束：
- 确定性：无随机、无 LLM、无联网；同输入同输出。
- 枚举全部与 `schemas/motion-spec.schema.json` / `motion-family.schema.json` 对齐，
  不自造（P7-2 SCHEMA_CONTRACT7 §5 约束 1）。
- 曲线函数优先复用 ``modules/production/motion.py``（import 桥）。实测该模块只提供
  ``EASINGS`` 枚举与 ``_norm_easing`` 归一化，**没有**任何曲线求值函数（cubic_bezier/
  spring 求值），故曲线数学自带实现并在 docstring 注明（P7-4 工单 motion_norm 约束）。
- 帧为整数基准（§26-27 帧安全计时，不累积浮点秒）。

技术约束：Python 3 stdlib only。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 共享枚举（真源 = schemas/motion-spec.schema.json / motion-family.schema.json）
# ---------------------------------------------------------------------------

# §42 motion_property 八枚举（对齐 motion-spec.schema.json properties[] 与
# timeline-clip.schema.json keyframes[].property）
MOTION_PROPERTY_ENUM = [
    "POSITION_X",
    "POSITION_Y",
    "SCALE",
    "SCALE_X",
    "SCALE_Y",
    "ROTATION",
    "OPACITY",
    "VOLUME",
]

# §41 easing 五枚举（对齐 motion-family.schema.json easing 枚举）
EASING_TYPES = ["linear", "ease", "cubic_bezier", "spring", "custom"]

# §47-48 采样策略（对齐 motion-spec.schema.json sampling.strategy）
SAMPLING_STRATEGIES = ["ADAPTIVE", "FIXED", "MANUAL"]

# §51-52 后端偏好（对齐 motion-spec.schema.json backend_preferences.preferred）
BACKEND_PREFERENCES = ["REMOTION", "JY_NATIVE", "EITHER"]

# motion quality（对齐 motion-spec.schema.json quality）
MOTION_QUALITIES = ["LOW", "MEDIUM", "HIGH"]

# ---------------------------------------------------------------------------
# 预算常量（docstring 注明依据）
# ---------------------------------------------------------------------------

# §46 简单 Motion 2-3 关键帧，不要采样几十帧；单 clip 预算 8 是硬阈值：
# 简单动效（linear/ease）应 ≤3；复杂 easing 采样 4-8 点在预算内不升级，
# 12 点（spring/custom/长时长/HIGH quality）才触发升级提案（§48 4/6/8/12）。
KEYFRAME_BUDGET_PER_CLIP = 8

# §49 避免"一个简单元素 200 个 keyframe"：全片关键帧总量预算（Test 18 语义：
# 简单 Motion 产生 150 个关键帧 → QA 必须警告）。
KEYFRAME_BUDGET_PROJECT = 200

# §48 采样点最大档位（4/6/8/12…）；禁止每帧一个关键帧。
KEYFRAME_MAX_SAMPLES = 12

# §50-51 升级阈值按动效类型分型（FR-001 / rv-P7-1b known_risk C 裁定）：
#   simple（linear/ease）采样点 > ESCALATE_SIMPLE_THRESHOLD(8) → 升级；
#   complex（cubic_bezier/spring/custom）采样点 > ESCALATE_COMPLEX_THRESHOLD(12) → 升级。
# 依据：§50 "curved smooth travel 允许 JY 采样"——复杂曲线 4/6/8/12 采样档位是
# 正常 JY 离散关键帧表达（§48），12 点 spring 属正常档位不升级；而简单动效
# （linear/ease）只需 2-3 帧（§46），超过 8 点即超额 → 升级提案 REMOTION。
# REVIEW 出处：work/review/rv-P7-1b.md FR-001 [MAJOR] + known_risk C（原"12 点
# 一律升级"对简单动效误升级，按 mtype/easing 拆分后 simple>8 / complex>12）。
ESCALATE_SIMPLE_THRESHOLD = KEYFRAME_BUDGET_PER_CLIP  # 8
ESCALATE_COMPLEX_THRESHOLD = KEYFRAME_MAX_SAMPLES     # 12

# ---------------------------------------------------------------------------
# 简单 / 复杂动效类型表（§46 / §51 语义）
# ---------------------------------------------------------------------------

# §46/§52/§77 简单动效：JY_NATIVE 原生关键帧（2-3 帧）即可，不需要几十帧。
SIMPLE_TYPES = {
    "slide_in", "slide_out", "slide_up", "slide_down", "slide_left", "slide_right",
    "fade_in", "fade_out", "crossfade", "slow_zoom", "zoom_in", "zoom_out",
    "photo_slow_zoom", "ken_burns", "pan", "pan_left", "pan_right", "push_in",
    "push_out", "pull_back", "tilt", "generic", "static", "slide",
    "zoom", "fade", "slow_pan",
}

# §51 复杂动效：complex morph / multi-object structural transformation → REMOTION。
# 即使采样点少也按 REMOTION 提案（Test 19 语义）。
COMPLEX_TYPES = {
    "morph", "morphing", "shape_morph", "ui_morph", "liquid_morph",
    "morph_transition", "structural_transformation", "structural_morph",
    "layout_transition", "compositional_transform", "multi_object_transform",
    "3d_flip", "3d_transform",
}

# 采样判定表（§47-48）：
#   cubic_bezier/spring 按时长桶选点数；quality HIGH/HERO 升一档；custom 恒 12 点。
#   时长桶（@30fps 基准）：short < 0.33s(<10f)；medium 0.33-1s(10-30f)；long > 1s(>30f)。
#   依据：工单例 "cubic_bezier 0.55s@30fps→6 点" → 0.55*30=16.5≈17f ∈ medium → 6。
_SAMPLING_TABLE: Dict[str, Any] = {
    "cubic_bezier": {"short": 4, "medium": 6, "long": 8},
    "spring": {"short": 6, "medium": 8, "long": 12},
}
_BUCKET_SHORT_FRAMES = 10  # <10f → short
_BUCKET_MEDIUM_FRAMES = 30  # 10..30f → medium；>30f → long
# HIGH/HERO quality 升一档
_BUCKET_BUMP = {"4": 6, "6": 8, "8": 12, "12": 12}

# easing 别名 -> 规范枚举（对齐 modules/production/motion.py _EASING_ALIASES）
_EASING_ALIASES = {
    "ease_in": "ease", "ease_out": "ease", "ease_in_out": "ease",
    "easeinout": "ease", "ease_in-out": "ease", "springy": "spring",
    "bezier": "cubic_bezier", "cubic": "cubic_bezier", "inout": "ease",
}

# §40 示例默认 cubic_bezier 控制点
_DEFAULT_BEZIER_VALUES = [0.16, 1.0, 0.3, 1.0]

# from/to 键名与静止默认值（motion-spec §40 示例 from{x,y,scale}）
_PROPERTY_KEY = {
    "POSITION_X": "x", "POSITION_Y": "y", "SCALE": "scale", "SCALE_X": "scale_x",
    "SCALE_Y": "scale_y", "ROTATION": "rotation", "OPACITY": "opacity",
    "VOLUME": "volume",
}
_DEFAULT_REST = {
    "x": 0.0, "y": 0.0, "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0,
    "rotation": 0.0, "opacity": 1.0, "volume": 1.0,
}

# ---------------------------------------------------------------------------
# 复用桥：modules/production/motion.py 的曲线工具（工单约束：能复用则复用并注明）
# ---------------------------------------------------------------------------

def _production_motion_constants() -> Dict[str, Any]:
    """尝试 import modules.production.motion 复用其枚举/归一化；失败返回空。

    实测（P7-4 读码）：该模块只提供 ``EASINGS`` 常量与 ``_norm_easing``/``_norm``
    归一化函数，**无任何曲线求值函数**（cubic_bezier/spring 求值均不在其 1200 行内）。
    因此本模块仅复用枚举归一化逻辑（确保与 Phase 5 对齐），曲线数学自带实现。
    """
    try:
        import modules.production.motion as p5  # noqa: PLC0415  (import 桥)
        return {
            "EASINGS": list(getattr(p5, "EASINGS", [])),
            "norm_easing": getattr(p5, "_norm_easing", None),
        }
    except Exception:  # noqa: BLE001 — import 桥失败兜底
        return {}


_P5 = _production_motion_constants()


def _norm_easing(value: Any) -> str:
    """easing 变体 -> 规范 5 枚举（复用 production.motion._norm_easing，失败走本地）。"""
    fn = _P5.get("norm_easing")
    if callable(fn):
        try:
            out = fn(value)
            if isinstance(out, str) and out in EASING_TYPES:
                return out
        except Exception:  # noqa: BLE001
            pass
    if not isinstance(value, str):
        return "ease"
    v = value.strip().lower().replace(" ", "_").replace("-", "_")
    for e in EASING_TYPES:
        if v == e:
            return e
    if v in _EASING_ALIASES:
        return _EASING_ALIASES[v]
    for e in EASING_TYPES:
        if e in v:
            return e
    return "ease"


def _norm_property(value: Any) -> str:
    """属性变体 -> §42 八枚举；无法识别抛 ValueError（枚举对齐，不自造）。"""
    if isinstance(value, str):
        v = value.strip().upper().replace("-", "_").replace(" ", "_")
        if v == "POSITION":
            return "POSITION_X"  # 位置缺省取 X（y 视 from/to 有无决定，见 _extract_props）
        if v in MOTION_PROPERTY_ENUM:
            return v
    raise ValueError("未知 motion property: %r（允许值=%s）" % (value, MOTION_PROPERTY_ENUM))


# ---------------------------------------------------------------------------
# 曲线求值（自带实现；production.motion 无曲线函数，见 _production_motion_constants）
# ---------------------------------------------------------------------------

def _bezier_1d(p0: float, p1: float, p2: float, p3: float, s: float) -> float:
    mt = 1.0 - s
    return mt * mt * mt * p0 + 3 * mt * mt * s * p1 + 3 * mt * s * s * p2 + s * s * s * p3


def _cubic_bezier_progress(x1: float, y1: float, x2: float, y2: float, t: float) -> float:
    """cubic_bezier 求值：先二分求解 x(s)=t 的参数 s，再取 y(s)（标准 easing 曲线 x 单调）。

    与 Remotion `interpolate`/CSS `cubic-bezier` 同语义（§40）。确定性，40 次二分。
    """
    t = max(0.0, min(1.0, float(t)))
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _bezier_1d(0.0, x1, x2, 1.0, mid) < t:
            lo = mid
        else:
            hi = mid
    s = (lo + hi) / 2.0
    return _bezier_1d(0.0, y1, y2, 1.0, s)


def _spring_progress(t: float, stiffness: float = 170.0, damping: float = 26.0,
                     overshoot: Optional[float] = None) -> float:
    """归一化阻尼弹簧（§41 spring/overshoot；deterministic）。

    采用阻尼简谐振荡的归一化单位阶跃响应：
        ζ = damping/(2√stiffness)（阻尼比）
        y(t) = (1 - e^{-ζω0t}·cos(ωd·t)) / (1 - e^{-ζω0}·cos(ωd))
    其中 ω0=4（基频，使振荡在 t∈[0,1] 内收敛）、ωd=ω0·√(1-ζ²)。
    y(0)=0、y(1)=1 精确；欠阻尼（ζ<1）中途 y 短暂 >1（超调），
    结果截断到 [0, 1.2] 防极端参数爆炸。``overshoot`` 参数暂作透传备注
    （motion-family spring 已用 stiffness/damping 表达；overshoot 字段保留兼容）。
    """
    t = max(0.0, min(1.0, float(t)))
    stiff = max(1.0, float(stiffness or 1.0))
    damp = max(0.0, float(damping or 0.0))
    zeta = damp / (2.0 * math.sqrt(stiff))
    w0 = 4.0
    if zeta >= 1.0:  # 临界/过阻尼：无振荡
        y = 1.0 - math.exp(-w0 * zeta * t)
        denom = 1.0 - math.exp(-w0 * zeta)
        if denom <= 0.0:
            return t
        return max(0.0, min(1.2, y / denom))
    wd = w0 * math.sqrt(max(0.0, 1.0 - zeta * zeta))
    y = 1.0 - math.exp(-zeta * w0 * t) * math.cos(wd * t)
    denom = 1.0 - math.exp(-zeta * w0) * math.cos(wd)
    if denom <= 0.0:
        return t
    return max(0.0, min(1.2, y / denom))


def easing_progress(easing: Dict[str, Any], t: float) -> float:
    """对 easing 规格求归一化进度 progress∈[0,1]（spring 允许轻微 >1，见截断）。

    Args:
        easing: {"type": "linear|ease|cubic_bezier|spring|custom",
                 "values": list[number], "overshoot": number|None}（motion-spec easing 形状）
        t: 归一化时间 [0,1]

    Returns:
        float：缓动曲线在 t 处的进度（用于 from→to 线性插值：value=from+(to-from)*progress）
    """
    etype = _norm_easing((easing or {}).get("type") or "ease")
    values = (easing or {}).get("values") or []
    overshoot = (easing or {}).get("overshoot")
    t = max(0.0, min(1.0, float(t)))

    if etype == "linear":
        return t
    if etype == "ease":
        # 标准 ease-in-out 近似（CSS ease ≈ cubic-bezier(0.25,0.1,0.25,1)；
        # 取对称标准曲线 cubic-bezier(0.33,0,0.67,1)）
        return _cubic_bezier_progress(0.33, 0.0, 0.67, 1.0, t)
    if etype == "cubic_bezier":
        if len(values) == 4 and all(isinstance(v, (int, float)) for v in values):
            x1, y1, x2, y2 = (float(v) for v in values)
            return _cubic_bezier_progress(x1, y1, x2, y2, t)
        return _cubic_bezier_progress(*_DEFAULT_BEZIER_VALUES, t)  # §40 示例默认
    if etype == "spring":
        stiffness = float(values[0]) if len(values) >= 1 else 170.0
        damping = float(values[1]) if len(values) >= 2 else 26.0
        return _spring_progress(t, stiffness=stiffness, damping=damping,
                                overshoot=overshoot)
    if etype == "custom":
        if len(values) == 4 and all(isinstance(v, (int, float)) for v in values):
            return _cubic_bezier_progress(*(float(v) for v in values), t)
        # 无 values 的 custom：确定性兜底 = 带轻微超调的 ease（近似自定义弹性）
        return _spring_progress(t, stiffness=170.0, damping=30.0, overshoot=overshoot)
    return t  # 未知 type 保守退化为线性


# ---------------------------------------------------------------------------
# 归一化工具
# ---------------------------------------------------------------------------

def _extract_fps(src: Dict[str, Any]) -> int:
    for key in ("fps",):
        v = src.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    comp = src.get("composition")
    if isinstance(comp, dict):
        v = comp.get("fps")
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    return 30


def _extract_frames(src: Dict[str, Any], fps: int) -> Dict[str, int]:
    """抽取整数帧范围（§26-27 整数帧为 Canonical Timing）。

    优先显式 start_frame/end_frame；其次 Phase 5 timing.entry（入场段）；
    再次 duration(秒)/duration_frames/timeline_hint.suggested_duration 换算。
    """
    start = src.get("start_frame")
    end = src.get("end_frame")
    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
        return {"start": int(start), "end": int(end)}

    timing = src.get("timing")
    if isinstance(timing, dict):
        entry = timing.get("entry")
        if isinstance(entry, dict) and int(entry.get("frames") or 0) > 0:
            s = entry.get("start_frame", timing.get("start_frame"))
            e = entry.get("end_frame", timing.get("end_frame"))
            if isinstance(s, (int, float)) and isinstance(e, (int, float)):
                return {"start": int(s), "end": int(e)}
        s = timing.get("start_frame")
        e = timing.get("end_frame")
        if isinstance(s, (int, float)) and isinstance(e, (int, float)):
            return {"start": int(s), "end": int(e)}

    # 秒 -> 帧
    for key in ("duration",):
        v = src.get(key)
        if isinstance(v, (int, float)) and v > 0:
            return {"start": 0, "end": max(0, round(float(v) * fps))}
    v = src.get("duration_frames")
    if isinstance(v, (int, float)) and v > 0:
        return {"start": 0, "end": int(v)}
    v = src.get("suggested_duration")  # timeline_hint（§84）
    if isinstance(v, (int, float)) and v > 0:
        return {"start": 0, "end": max(0, round(float(v) * fps))}
    return {"start": 0, "end": 0}


def _extract_type(src: Dict[str, Any]) -> str:
    for key in ("type", "motion_type"):
        v = src.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().lower().replace(" ", "_").replace("-", "_")
    # Phase 5 MOTION_SPEC：由 purpose/motion_requirements 文本推导
    text = ("%s %s %s" % (
        str(src.get("purpose") or ""),
        str(src.get("motion_requirements") or ""),
        str(src.get("visual_requirements") or ""),
    )).lower()
    if "ken" in text or "burns" in text:
        return "ken_burns"
    if "zoom" in text or "推" in text or "scale" in text or "缩放" in text:
        return "zoom_in"
    if "slide" in text or "滑" in text or "平移" in text or "入场" in text:
        return "slide_in"
    if "fade" in text or "淡" in text:
        return "fade_in"
    if "pan" in text or "摇" in text:
        return "pan"
    return "generic"


def _extract_easing(src: Dict[str, Any]) -> Dict[str, Any]:
    e = src.get("easing")
    if isinstance(e, dict):
        etype = _norm_easing(e.get("type") or "ease")
        out: Dict[str, Any] = {"type": etype}
        values = e.get("values")
        if isinstance(values, list) and values:
            nums = [float(v) for v in values if isinstance(v, (int, float))]
            if nums:
                out["values"] = nums
        if isinstance(e.get("overshoot"), (int, float)):
            out["overshoot"] = float(e["overshoot"])
        return out
    if isinstance(e, str):
        return {"type": _norm_easing(e)}
    if isinstance(src.get("overshoot"), (int, float)):
        return {"type": "ease", "overshoot": float(src["overshoot"])}
    return {"type": "ease"}


def _phase5_transform_value(block: Any, key: str, default: Optional[float]) -> Optional[float]:
    """从 Phase 5 的 entry/hold/exit 块取 value_from/value_to/或标量。"""
    if isinstance(block, dict):
        if key in block and isinstance(block[key], (int, float)):
            return float(block[key])
        for k in ("value_from", "value_to", "value"):
            v = block.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    return default


def _extract_props(src: Dict[str, Any], mtype: str) -> Dict[str, Any]:
    """推导 properties（§42 八枚举）+ from/to（键名见 _PROPERTY_KEY）。

    来源优先级：
      1. 显式 properties + from/to（motion-spec / JY_NATIVE 形状）
      2. Phase 5 scale/position/rotation/opacity entry 块
      3. from/to 键名推导（x/y/scale/scale_x/scale_y/rotation/opacity/volume）
      4. 按 type 兜底（slide_in→POSITION_X、fade_in→OPACITY、zoom→SCALE…）
    """
    props: List[str] = []
    from_v: Dict[str, float] = {}
    to_v: Dict[str, float] = {}

    explicit = src.get("properties")
    if isinstance(explicit, list) and explicit and "from" in src and "to" in src:
        for p in explicit:
            pn = _norm_property(p)
            if pn not in props:
                props.append(pn)
        f, t = src["from"], src["to"]
        for p in props:
            key = _PROPERTY_KEY[p]
            fv = f.get(key) if isinstance(f, dict) else None
            tv = t.get(key) if isinstance(t, dict) else None
            if not isinstance(fv, (int, float)):
                fv = _DEFAULT_REST[key]
            if not isinstance(tv, (int, float)):
                tv = _DEFAULT_REST[key]
            from_v[key] = float(fv)
            to_v[key] = float(tv)
        if props and len(props) == 1 and props[0] == "POSITION_X" and \
                isinstance(f, dict) and "y" in f:
            props.append("POSITION_Y")
            from_v["y"] = float(f["y"]) if isinstance(f.get("y"), (int, float)) else _DEFAULT_REST["y"]
            to_v["y"] = float(t["y"]) if isinstance(t, dict) and isinstance(t.get("y"), (int, float)) else _DEFAULT_REST["y"]
        return {"properties": props, "from": from_v, "to": to_v}

    # Phase 5 形状：scale/position/rotation/opacity
    has_p5 = any(isinstance(src.get(k), dict) for k in ("scale", "position", "rotation", "opacity"))
    if has_p5:
        for p, key, rest in [
            ("SCALE", "scale", 1.0),
            ("SCALE_X", "scale_x", 1.0),
            ("SCALE_Y", "scale_y", 1.0),
            ("POSITION_X", "x", 0.0),
            ("POSITION_Y", "y", 0.0),
            ("ROTATION", "rotation", 0.0),
            ("OPACITY", "opacity", 1.0),
            ("VOLUME", "volume", 1.0),
        ]:
            block = src.get(key)
            if not isinstance(block, dict):
                continue
            entry = block.get("entry")
            target = entry if isinstance(entry, dict) else block
            fv = _phase5_transform_value(target, "value_from", None)
            tv = _phase5_transform_value(target, "value_to", None)
            if fv is None and isinstance(entry, dict):
                # entry 里可能是 {x:..., y:...}（position）或标量
                if isinstance(entry.get("value_from"), dict) and key in entry["value_from"]:
                    fv = entry["value_from"][key]
                if isinstance(entry.get("value_to"), dict) and key in entry["value_to"]:
                    tv = entry["value_to"][key]
            if fv is None and isinstance(block.get("value_from"), dict) and key in block["value_from"]:
                fv = block["value_from"][key]
            if tv is None and isinstance(block.get("value_to"), dict) and key in block["value_to"]:
                tv = block["value_to"][key]
            if fv is None or tv is None:
                continue
            if isinstance(fv, (int, float)) and isinstance(tv, (int, float)) and float(fv) != float(tv):
                props.append(p)
                from_v[key] = float(fv)
                to_v[key] = float(tv)
        if props:
            return {"properties": props, "from": from_v, "to": to_v}

    # from/to 键名推导
    f = src.get("from")
    t = src.get("to")
    if isinstance(f, dict) or isinstance(t, dict):
        f = f if isinstance(f, dict) else {}
        t = t if isinstance(t, dict) else {}
        for p, key in _PROPERTY_KEY.items():
            has_f = isinstance(f.get(key), (int, float))
            has_t = isinstance(t.get(key), (int, float))
            if has_f or has_t:
                if p not in props:
                    props.append(p)
                from_v[key] = float(f[key]) if has_f else _DEFAULT_REST[key]
                to_v[key] = float(t[key]) if has_t else _DEFAULT_REST[key]
        if props:
            return {"properties": props, "from": from_v, "to": to_v}

    # 按 type 兜底（保证 properties 至少 1 项，schema minItems=1）
    if mtype in ("slide_in", "slide_out", "slide_up", "slide_down", "slide_left",
                 "slide_right", "slide", "pan", "pan_left", "pan_right", "push_in",
                 "push_out", "pull_back"):
        props, from_v, to_v = ["POSITION_X"], {"x": -0.25}, {"x": 0.0}
        if "slide_up" in mtype or "pan" in mtype or "tilt" in mtype:
            props.append("POSITION_Y")
            from_v["y"] = 0.05
            to_v["y"] = 0.0
    elif mtype in ("fade_in", "fade_out", "crossfade", "fade"):
        props, from_v, to_v = ["OPACITY"], {"opacity": 0.0}, {"opacity": 1.0}
        if "out" in mtype:
            from_v, to_v = {"opacity": 1.0}, {"opacity": 0.0}
    elif mtype in ("ken_burns", "slow_zoom", "photo_slow_zoom"):
        props, from_v, to_v = ["SCALE"], {"scale": 1.0}, {"scale": 1.05}
    elif mtype in ("zoom_in", "zoom", "push_in"):
        props, from_v, to_v = ["SCALE"], {"scale": 0.96}, {"scale": 1.0}
    elif mtype in ("zoom_out", "push_out", "pull_back"):
        props, from_v, to_v = ["SCALE"], {"scale": 1.0}, {"scale": 1.05}
    else:  # generic/static 占位（无动效）
        props, from_v, to_v = ["SCALE"], {"scale": 1.0}, {"scale": 1.0}
    return {"properties": props, "from": from_v, "to": to_v}


# ---------------------------------------------------------------------------
# 1. normalize_motion_spec
# ---------------------------------------------------------------------------

def normalize_motion_spec(raw: Dict[str, Any]) -> Dict[str, Any]:
    """把 Phase 5 MOTION_SPEC / timeline_hint / JY_NATIVE 意图统一为
    ``schemas/motion-spec.schema.json`` 形状。

    Args:
        raw: dict。接受：
            - 已是 motion-spec 形状（type/start_frame/end_frame/properties/from/to）
            - Phase 5 MOTION_SPEC（timing/scale/position/rotation/opacity/easing/fps）
            - JY_NATIVE 意图（type/from/to/easing/duration/fps）
            - timeline_hint（suggested_duration/track/...，产出保守占位 spec）
            - 嵌套 ``{"motion": {...}}`` 亦识别

    Returns:
        dict：motion-spec.schema.json 形状。帧为整数（§26-27）；properties 用 §42
        八枚举（唯一、≥1）；easing 用 5 枚举；sampling/quality/backend_preferences
        补齐默认值。输出保证能过 motion-spec.schema.json（AC-1）。
    """
    if not isinstance(raw, dict):
        raise TypeError("normalize_motion_spec 需要 dict 输入，收到 %s" % type(raw).__name__)
    src = raw.get("motion") if isinstance(raw.get("motion"), dict) else raw

    fps = _extract_fps(src)
    frames = _extract_frames(src, fps)
    start_frame, end_frame = frames["start"], frames["end"]
    mtype = _extract_type(src)
    easing = _extract_easing(src)
    props_info = _extract_props(src, mtype)
    properties = props_info["properties"]
    from_v, to_v = props_info["from"], props_info["to"]

    # 采样默认（§47-48）；raw 显式 sampling 时透传
    sampling = src.get("sampling")
    if not isinstance(sampling, dict) or not isinstance(sampling.get("strategy"), str):
        sampling = {"strategy": "ADAPTIVE", "max_points": KEYFRAME_MAX_SAMPLES}
    else:
        strategy = str(sampling.get("strategy")).upper()
        if strategy not in SAMPLING_STRATEGIES:
            strategy = "ADAPTIVE"
        max_points = int(sampling.get("max_points") or 4)
        sampling = {"strategy": strategy, "max_points": max(2, min(KEYFRAME_MAX_SAMPLES, max_points))}

    # quality（§41 quality；Phase 5 intensity 映射）
    quality = str(src.get("quality") or "").upper()
    if quality not in MOTION_QUALITIES:
        intensity = str(src.get("intensity") or "MEDIUM").upper()
        quality = {"LOW": "LOW", "MEDIUM": "MEDIUM", "HIGH": "HIGH", "HERO": "HIGH"}.get(intensity, "MEDIUM")

    # backend_preferences（§51-52）
    bp = src.get("backend_preferences")
    preferred = None
    reason = ""
    if isinstance(bp, dict):
        preferred = str(bp.get("preferred") or "").upper()
        reason = str(bp.get("reason") or "")
    if preferred not in BACKEND_PREFERENCES:
        route = str(src.get("route") or "EITHER").upper()
        preferred = route if route in BACKEND_PREFERENCES else "EITHER"
        reason = reason or ("route=%s 透传" % route if route in ("REMOTION", "JY_NATIVE") else "未指定，默认 EITHER")

    out: Dict[str, Any] = {
        "type": mtype,
        "start_frame": int(start_frame),
        "end_frame": int(end_frame),
        "properties": properties,
        "from": from_v,
        "to": to_v,
        "easing": easing,
        "sampling": sampling,
        "backend_preferences": {"preferred": preferred, "reason": reason},
        "quality": quality,
    }

    # 可选字段仅在存在时输出（schema additionalProperties=false 白名单内）
    for key, default in (("overshoot", 0.1), ("path", None), ("anchor", None), ("relative_to", None)):
        v = src.get(key)
        if v is None:
            continue
        if key == "overshoot" and not isinstance(v, (int, float)):
            continue
        out[key] = v

    # 归一化后的 properties 保持 §42 顺序 + 唯一（uniqueItems=true）
    ordered = [p for p in MOTION_PROPERTY_ENUM if p in properties]
    if len(ordered) != len(properties):
        ordered = properties  # 含非标准顺序时保持原序（仍唯一）
    out["properties"] = ordered
    return out


# ---------------------------------------------------------------------------
# 2. plan_sampling
# ---------------------------------------------------------------------------

def _capability_view(capability: Any) -> Dict[str, Any]:
    """归一化 capability 输入：直接 dict / {"ok":True,"result":{...}} / None。"""
    if capability is None:
        return {}
    if isinstance(capability, dict) and capability.get("ok") is True \
            and isinstance(capability.get("result"), dict):
        return capability["result"]
    if isinstance(capability, dict):
        return capability
    return {}


def _cap_supported(caps: Dict[str, Any], key: str) -> bool:
    """能力键 supported 是否 True（False/'partial'/缺失 → 视为不支持，§44 不假装）。"""
    node = caps.get(key)
    if not isinstance(node, dict):
        return False
    return node.get("supported") is True


def _duration_bucket(duration_frames: int) -> str:
    if duration_frames < _BUCKET_SHORT_FRAMES:
        return "short"
    if duration_frames <= _BUCKET_MEDIUM_FRAMES:
        return "medium"
    return "long"


def _adaptive_point_count(spec: Dict[str, Any], duration_frames: int) -> int:
    """§46-48 判定表：返回采样点数（确定性，写死表 + docstring 依据）。"""
    easing = spec.get("easing") or {}
    etype = _norm_easing(easing.get("type") or "ease")
    mtype = str(spec.get("type") or "")
    quality = str(spec.get("quality") or "MEDIUM").upper()

    # §46 简单动效 + 简单缓动 → 2-3 点
    if mtype in SIMPLE_TYPES and etype in ("linear", "ease"):
        return 2 if etype == "linear" else 3

    if etype in ("linear",):
        return 2
    if etype in ("ease",):
        return 3

    if etype == "custom":
        return KEYFRAME_MAX_SAMPLES  # §48 自定义曲线按最高档采样

    if etype in _SAMPLING_TABLE:
        bucket = _duration_bucket(duration_frames)
        count = _SAMPLING_TABLE[etype][bucket]
        if quality in ("HIGH", "HERO"):  # visual sensitivity 升一档
            count = _BUCKET_BUMP.get(str(count), count)
        return count

    # 未知 easing 类型保守退化
    return 4


def plan_sampling(spec: Dict[str, Any], duration_frames: int = 0,
                  capability: Any = None) -> Dict[str, Any]:
    """§47-48 采样规划：原生 easing 支持→直接曲线；不支持→4/6/8/12 采样点。

    Args:
        spec: motion-spec.schema.json 形状（normalize_motion_spec 输出）
        duration_frames: 时长（帧）。<=0 时用 spec.end_frame - spec.start_frame
        capability: P7-1 能力矩阵（TIMELINE_BACKEND_CAPABILITIES dict，或
            {"ok":True,"result":{...}}，或 None）

    Returns:
        dict::

            {"strategy": "ADAPTIVE|FIXED|MANUAL",       # 使用的采样策略
             "easing_mode": "NATIVE_CURVE|SAMPLED",     # §47 原生 vs 采样
             "easing_type": "cubic_bezier|...",
             "keyframe_count": int,                     # len(samples)
             "samples": [{"frame": int, "progress": float}, ...],  # 离散关键帧点
             "notes": [str]}

        确定性；``samples`` 首尾帧 == spec.start_frame/end_frame；
        短时长+多点时连续重复帧去重（进度取首个）。
    """
    spec = spec or {}
    start = int(spec.get("start_frame") or 0)
    end = int(spec.get("end_frame") or start)
    if end < start:
        end = start
    span = end - start
    if not duration_frames or duration_frames <= 0:
        duration_frames = span

    caps = _capability_view(capability)
    easing = spec.get("easing") or {}
    etype = _norm_easing(easing.get("type") or "ease")
    sampling = spec.get("sampling") or {}
    strategy = str(sampling.get("strategy") or "ADAPTIVE").upper()
    if strategy not in SAMPLING_STRATEGIES:
        strategy = "ADAPTIVE"

    # 显式 FIXED/MANUAL：直接用 max_points（clamp 2..12）
    if strategy in ("FIXED", "MANUAL"):
        count = int(sampling.get("max_points") or 4)
        count = max(2, min(KEYFRAME_MAX_SAMPLES, count))
    else:
        count = _adaptive_point_count(spec, duration_frames)

    # 原生 easing 支持判定（§47：原生支持 → 直接曲线，只留端点）
    native_easing = etype in ("linear",) or (
        etype in ("cubic_bezier", "spring", "custom") and _cap_supported(caps, "bezier_easing")
    )
    easing_mode = "NATIVE_CURVE" if native_easing else "SAMPLED"
    if easing_mode == "NATIVE_CURVE":
        count = min(count, 2) if etype == "linear" else 2

    notes: List[str] = []
    if etype in ("cubic_bezier", "spring", "custom") and not _cap_supported(caps, "bezier_easing"):
        notes.append(
            "bezier_easing 不支持（P7-1: keyframe.py:23-34 curveType=Line 硬编码）"
            "→ 采样 %d 个离散关键帧（§47-48）" % count
        )
    if spec.get("path") and not _cap_supported(caps, "custom_motion_path"):
        notes.append("custom_motion_path 不支持（P7-1: keyframe.py:23-34）→ 位置采样近似 / Remotion 烘焙（§51）")

    # 采样点生成（t ∈ [0,1] → frame + progress）
    if count <= 1:
        tlist = [0.0]
    else:
        tlist = [i / (count - 1) for i in range(count)]

    samples: List[Dict[str, Any]] = []
    seen_frames = set()
    for t in tlist:
        frame = start if span <= 0 else round(start + span * t)
        if frame in seen_frames:  # 短时长+多点：连续重复帧去重
            continue
        seen_frames.add(frame)
        samples.append({
            "frame": frame,
            "progress": round(easing_progress(easing, t), 6),
        })
    if not samples:
        samples = [{"frame": start, "progress": 0.0}]

    return {
        "strategy": strategy,
        "easing_mode": easing_mode,
        "easing_type": etype,
        "keyframe_count": len(samples),
        "samples": samples,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# 3. keyframe_budget_check
# ---------------------------------------------------------------------------

def keyframe_budget_check(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """§49 关键帧预算检查（Test 18 语义：简单 Motion 150 关键帧 → 必须警告）。

    Args:
        specs: list of ``{"clip_id": str, "count": int}``（兼容键
            "count"/"sampled_count"/"keyframe_count"）

    Returns:
        dict::

            {"total": int, "per_clip": {clip_id: count},
             "warnings": [{"clip_id": str|None, "level": "WARNING",
                           "code": "KEYFRAME_OVER_BUDGET|KEYFRAME_PROJECT_OVER_BUDGET",
                           "message": str}, ...]}

    预算依据（docstring）：
        - 单 clip ≤ KEYFRAME_BUDGET_PER_CLIP(8)：§46 简单 Motion 2-3 帧；
          复杂 easing 采样 4-8 点在预算内，12 点才触发升级（§48/§50）。
        - 全片 ≤ KEYFRAME_BUDGET_PROJECT(200)：§49 防"简单元素 200 个 keyframe"。
    """
    total = 0
    per_clip: Dict[str, Any] = {}
    warnings: List[Dict[str, Any]] = []
    for item in specs or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("clip_id") or item.get("clip") or "?")
        cnt = item.get("count")
        if cnt is None:
            cnt = item.get("sampled_count")
        if cnt is None:
            cnt = item.get("keyframe_count")
        try:
            cnt = int(cnt or 0)
        except (TypeError, ValueError):
            cnt = 0
        per_clip[cid] = cnt
        total += cnt
        if cnt > KEYFRAME_BUDGET_PER_CLIP:
            warnings.append({
                "clip_id": cid,
                "level": "WARNING",
                "code": "KEYFRAME_OVER_BUDGET",
                "message": (
                    "clip %s 关键帧 %d 超过单 clip 预算 %d（§46/§49，Test 18 "
                    "Keyframe Explosion 语义）" % (cid, cnt, KEYFRAME_BUDGET_PER_CLIP)
                ),
            })
    if total > KEYFRAME_BUDGET_PROJECT:
        warnings.append({
            "clip_id": None,
            "level": "WARNING",
            "code": "KEYFRAME_PROJECT_OVER_BUDGET",
            "message": (
                "全片关键帧 %d 超过项目预算 %d（§49 防简单元素 200 个 keyframe）"
                % (total, KEYFRAME_BUDGET_PROJECT)
            ),
        })
    return {"total": total, "per_clip": per_clip, "warnings": warnings}


# ---------------------------------------------------------------------------
# 4. escalation_check / 5. deescalation_check
# ---------------------------------------------------------------------------

def _escalation_threshold(spec: Dict[str, Any]) -> int:
    """按动效类型返回升级采样点阈值（FR-001 / rv-P7-1b known_risk C）。

    simple（linear/ease）→ ``ESCALATE_SIMPLE_THRESHOLD``(8)；complex
    （cubic_bezier/spring/custom）→ ``ESCALATE_COMPLEX_THRESHOLD``(12)。
    easing 缺失/未知保守按 simple 处理（阈值更低，更早提案，符合 §50 语义）。
    """
    easing = spec.get("easing") or {}
    etype = _norm_easing(easing.get("type") or "ease")
    if etype in ("cubic_bezier", "spring", "custom"):
        return ESCALATE_COMPLEX_THRESHOLD
    return ESCALATE_SIMPLE_THRESHOLD


def escalation_check(spec: Dict[str, Any], sampled_count: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """§50-51 升级判定：采样点超预算 或 type 属 complex → TIMELINE_OPTIMIZATION_PROPOSAL
    （REMOTION 建议，approval_required=true，只提案不私改 route）。

    采样点阈值按动效类型分型（FR-001 / rv-P7-1b known_risk C）：
    simple（linear/ease）> 8 点升级；complex（cubic_bezier/spring/custom）> 12 点升级。
    依据 §50 "curved smooth travel 允许 JY 采样"：复杂曲线 4/6/8/12 采样档位属正常
    JY 离散关键帧表达（§48），12 点 spring 不升级；简单动效超 8 点（如 HIGH quality
    12 点 slide_in(linear)）超额 → 升级提案 REMOTION（test 断言见 work/p7-4/test_self.py）。

    Args:
        spec: motion-spec 形状
        sampled_count: plan_sampling 的 keyframe_count（可 None，仅按类型判定）

    Returns:
        proposal dict 或 None::

            {"kind": "TIMELINE_OPTIMIZATION_PROPOSAL", "target": type,
             "current_route": "JY_NATIVE", "proposed_route": "REMOTION",
             "reason": str, "approval_required": True,
             "sampled_keyframe_count": int|None, "motion_type": str}
    """
    spec = spec or {}
    mtype = str(spec.get("type") or "")
    reasons: List[str] = []
    if sampled_count is not None:
        threshold = _escalation_threshold(spec)
        if sampled_count > threshold:
            reasons.append(
                "采样关键帧 %d 超过%s动效阈值 %d（FR-001 分型：simple>8 / "
                "complex>12；§50，Test 18/19 语义）"
                % (sampled_count,
                   "complex" if threshold == ESCALATE_COMPLEX_THRESHOLD else "simple",
                   threshold)
            )
    if mtype in COMPLEX_TYPES:
        reasons.append(
            "动效类型 '%s' 属 complex（morph / multi-object structural transformation，§51 Test 19）"
            % mtype
        )
    if spec.get("path"):
        reasons.append("存在 custom motion path，剪映无路径关键帧（§51 custom_motion_path→Remotion 烘焙）")
    if not reasons:
        return None
    return {
        "kind": "TIMELINE_OPTIMIZATION_PROPOSAL",
        "target": mtype or "unknown",
        "current_route": "JY_NATIVE",
        "proposed_route": "REMOTION",
        "reason": "；".join(reasons),
        "approval_required": True,
        "sampled_keyframe_count": sampled_count,
        "motion_type": mtype,
    }


def deescalation_check(route: Optional[str], spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """§52 降级判定：原 route=REMOTION 但属简单动效（photo slow zoom 等）→
    建议 JY_NATIVE（提案留痕，approval_required=true，不私改 route）。

    Args:
        route: 上游生产 route（如 "REMOTION"）
        spec: motion-spec 形状

    Returns:
        proposal dict 或 None（形状与 escalation_check 一致，方向相反）。
    """
    spec = spec or {}
    if str(route or "").upper() != "REMOTION":
        return None
    mtype = str(spec.get("type") or "")
    easing = spec.get("easing") or {}
    etype = _norm_easing(easing.get("type") or "linear")
    quality = str(spec.get("quality") or "MEDIUM").upper()
    if mtype in SIMPLE_TYPES and etype in ("linear", "ease") \
            and not spec.get("path") and quality not in ("HIGH", "HERO"):
        return {
            "kind": "TIMELINE_OPTIMIZATION_PROPOSAL",
            "target": mtype,
            "current_route": "REMOTION",
            "proposed_route": "JY_NATIVE",
            "reason": (
                "'%s' 属简单动效（§52 示例 photo slow zoom；§77 图片 JY_NATIVE），"
                "可由剪映原生关键帧实现（§46 简单 Motion 2-3 帧），无需 Remotion 烘焙"
                % mtype
            ),
            "approval_required": True,
            "sampled_keyframe_count": None,
            "motion_type": mtype,
        }
    return None


# ---------------------------------------------------------------------------
# 便捷工具（帧↔微秒；供适配器/测试使用）
# ---------------------------------------------------------------------------

def _load_planner_time_utils():
    """importlib 加载 planner.time_utils（FR-006 换算权威实现所在模块）。

    ``modules/timeline-manager`` 为连字符包，不能用 ``import x.y`` 语句直接导入，
    用 importlib.import_module 全名加载（与 planner.py 加载 templates 同约定）。
    加载失败返回 None（调用方走本地兜底，docstring 注明）。
    """
    try:
        import importlib as _il
        return _il.import_module("modules.timeline-manager.planner")
    except Exception:  # noqa: BLE001 — 权威模块不可用时本地兜底，不允许本函数崩
        return None


_PLANNER_TIME_UTILS = _load_planner_time_utils()


def frames_to_us(frame: int, fps: int = 30) -> int:
    """帧 → 微秒（int）。换算权威实现位于 planner.time_utils.to_backend_unit
    （FR-006 架构裁定：planner/motion/backend 三处同源，round-half-even，
    与 Phase 5 modules/production/motion.py:294 ``round(duration*fps)`` 一致）。

    P7-1 finding 3：AudioSegment.add_keyframe 只收 int 微秒（audio_segment.py:189）。
    权威模块不可加载时本地公式兜底（round-half-even 同语义）。
    """
    if _PLANNER_TIME_UTILS is not None:
        out = _PLANNER_TIME_UTILS.to_backend_unit(int(frame), max(1, int(fps)), "us")
        if out is not None:
            return out
    return int(round(int(frame) * 1_000_000 / max(1, int(fps))))
