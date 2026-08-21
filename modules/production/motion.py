#!/usr/bin/env python3
"""motion.py — ZHOU_Videodirector Phase 5 Motion Engine (P5-3).

把 PRODUCTION_REQUEST + Visual Bible + Motion Family 归一化成 MOTION_SPEC（frame 精确，
不用自然语言时序），并承担 Registry 复用决策 / Visual Bible 冲突检查 / 技术+Taste QA /
Preview 计划 / Continuity 合并建议 / alpha 校验清单。

共享契约（Phase-5 Prompt §10 全字段 + 枚举）：
    MOTION_SPEC 字段: purpose duration fps composition elements timing motion_character
        intensity easing spring stagger camera parallax scale position rotation opacity
        blur shadow lighting depth motion_blur transition_in transition_out
        audio_sync_points continuity alpha render_format avoid
    motion_character（10, 真源=P5-1 motion-family.schema.json）: restrained soft precise
        spatial kinetic cinematic editorial elastic mechanical organic
    intensity（4）: LOW MEDIUM HIGH HERO
    easing（5, 真源=P5-1 motion-family.schema.json）: linear ease cubic_bezier spring custom
    reuse_mode（4）: USE_AS_IS ADAPT COMPOSE BUILD_NEW（BUILD_NEW 记 build_reason，§80）
    timing: frame 计数（§13）start_frame/end_frame/duration_frames/entry/hold/exit/sync_points

Registry 调用：优先 subprocess 调 scripts/registry.py find --json（读源码确认接口：
    find <query> [--route] [--type] [--limit] --json -> {results:[{resource_id, fit,
    reuse_recommendation, potential_problem, type, provider, ...}]}）。
    subprocess 失败时退回 import scripts.registry（Store/search/candidate_dict）。

设计要点：
    - Reuse→Adapt→Compose→Build Last 是 Phase 5 主线（§6）：BUILD_NEW 必须记 build_reason。
    - Preview First（§89-91）：preview 与 final 分离（{asset}_preview.mp4）。
    - Motion Family（§15-17）：MF-* 复用优先，特殊 Hero 才建特殊 Motion。
    - Continuity（§18-19 / §31）：同 continuity_group 的 requests 合并为单个 Remotion
      composition，不切碎。
    - alpha（§21）：render 后由 ffmpeg 探针真实校验（P5-6 E2E 执行）；本模块只返回清单。

技术约束：Python 3 stdlib only；PyYAML 可选（本模块不强制）；不联网（registry 为本地索引）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PY = SKILL_ROOT / "scripts" / "registry.py"
SCHEMAS_DIR = SKILL_ROOT / "schemas"

# ---------------------------------------------------------------------------
# 共享枚举（真源优先：若 P5-1 motion-family.schema.json 已产出，extend 其枚举；
# 不删除本文件默认值，保证本模块自洽可用）
# ---------------------------------------------------------------------------

MOTION_CHARACTERS = [
    "restrained", "soft", "precise", "spatial", "kinetic",
    "cinematic", "editorial", "elastic", "mechanical", "organic",
]
INTENSITIES = ["LOW", "MEDIUM", "HIGH", "HERO"]
EASINGS = ["linear", "ease", "cubic_bezier", "spring", "custom"]
REUSE_MODES = ["USE_AS_IS", "ADAPT", "COMPOSE", "BUILD_NEW"]

MOTION_SPEC_FIELDS = [
    "purpose", "duration", "fps", "composition", "elements", "timing",
    "motion_character", "intensity", "easing", "spring", "stagger", "camera",
    "parallax", "scale", "position", "rotation", "opacity", "blur", "shadow",
    "lighting", "depth", "motion_blur", "transition_in", "transition_out",
    "audio_sync_points", "continuity", "alpha", "render_format", "avoid",
]

# style 词 -> motion_character token
_STYLE_CHARACTER_MAP = {
    "minimal": "restrained",
    "minimal spatial tech": "restrained",
    "spatial": "spatial",
    "tech": "precise",
    "technical": "precise",
    "cinematic": "cinematic",
    "editorial": "editorial",
    "kinetic": "kinetic",
    "organic": "organic",
    "soft": "soft",
    "elastic": "elastic",
    "mechanical": "mechanical",
    "restrained": "restrained",
    "克制": "restrained",
    "precise": "precise",
    "motion design": "kinetic",
}

# 自由文本 -> token（英文/中文）
_CHAR_SYNONYMS = {
    "restrained": "restrained", "克制": "restrained", "subtle": "restrained",
    "soft": "soft", "柔": "soft", "gentle": "soft",
    "precise": "precise", "精确": "precise", "technical": "precise",
    "tech": "precise", "技术": "precise",
    "kinetic": "kinetic", "动感": "kinetic", "动能": "kinetic",
    "cinematic": "cinematic", "电影": "cinematic",
    "editorial": "editorial", "编辑": "editorial", "排版": "editorial",
    "spatial": "spatial", "空间": "spatial",
    "organic": "organic", "有机": "organic",
    "elastic": "elastic", "弹性": "elastic", "bouncy": "elastic",
    "mechanical": "mechanical", "机械": "mechanical",
}

# 非 character 的效果词（不进 10 枚举；进 spec['effects']，供 VB avoid 检测）
_EFFECT_WORDS = {
    "glitch": "glitch", "故障": "glitch",
    "noise": "noise", "噪点": "noise",
    "neon": "neon", "霓虹": "neon",
    "scanline": "scanline",
    "chromatic": "chromatic", "色散": "chromatic",
    "vhs": "vhs",
}

# 复用 fit 阈值（Phase-5 Prompt：完全匹配 → USE_AS_IS；fit 80-90% → ADAPT；
# 两个现成 primitive 可组合 → COMPOSE；否则 BUILD_NEW）
FIT_USE_AS_IS = 0.90
FIT_ADAPT_MIN = 0.80
FIT_COMPOSE_MIN = 0.35
# registry 的 8 因子 score 偏保守：无项目风格/缓存上下文时，完美相关候选也只有 ~0.71-0.77
# （rel=1.0）。因此对高相关候选（rel>=0.85）放宽 ADAPT 下限到 0.60，使 ADAPT 可达；
# brief 的 "fit 80-90% → ADAPT" 仍是主规则。
FIT_ADAPT_HIGH_REL_MIN = 0.60
ADAPT_HIGH_REL = 0.85
# registry find 的 relevance 基线：route 类型偏好固定 +0.25；query 未命中任何内容时
# rel==0.25（纯基线噪声）。rel<=基线 意味着"无方案"，必须 BUILD_NEW（§80），
# 否则基线噪声会误判成 COMPOSE。
RELEVANCE_BASELINE = 0.25

# 默认 composition（可被 request 覆盖）
DEFAULT_COMPOSITION = {"width": 1920, "height": 1080, "fps": 30,
                       "background": "transparent"}


def _extend_enums_from_schema():
    """P5-1 motion-family.schema.json 已产出时，union 其枚举（只增不删）。"""
    spec_file = SCHEMAS_DIR / "motion-family.schema.json"
    if not spec_file.is_file():
        return
    try:
        data = json.loads(spec_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    props = (data.get("properties") or {}) if isinstance(data, dict) else {}
    # schema 的字段名与 MOTION_SPEC 不同：character(数组枚举) / intensity / easing
    for field, target in (("character", MOTION_CHARACTERS),
                          ("intensity", INTENSITIES),
                          ("easing", EASINGS)):
        node = props.get(field)
        enum = node.get("enum") if isinstance(node, dict) else None
        if isinstance(enum, list) and enum:
            for v in enum:
                if isinstance(v, str) and v.lower() not in [t.lower() for t in target]:
                    target.append(v.lower())


_extend_enums_from_schema()


# ---------------------------------------------------------------------------
# 归一化小工具
# ---------------------------------------------------------------------------

def _norm(value, enum_list, default=None):
    """大小写 / 连字符变体 -> 规范小写枚举；失败返回 default。"""
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower().replace(" ", "_").replace("-", "_")
        for e in enum_list:
            if v == e or v.replace("_", " ") == e:
                return e
        # 宽松匹配：原值里含某枚举词
        for e in enum_list:
            if e in v:
                return e
    return default


def _norm_intensity(value):
    v = _norm(value, [i.lower() for i in INTENSITIES])
    return v.upper() if v else "MEDIUM"


# easing 别名 -> 规范枚举（P5-1 easing 5 枚举的常见变体）
_EASING_ALIASES = {
    "ease_in": "ease", "ease_out": "ease", "ease_in_out": "ease",
    "easeinout": "ease", "ease-in-out": "ease", "springy": "spring",
    "bezier": "cubic_bezier", "cubic": "cubic_bezier", "inout": "ease",
}


def _norm_easing(value):
    v = _norm(value, EASINGS)
    if v:
        return v
    if isinstance(value, str):
        key = value.strip().lower().replace(" ", "_")
        if key in _EASING_ALIASES:
            return _EASING_ALIASES[key]
    return "cubic_bezier"


def _char_tokens(text, mapping):
    """从自由文本提取 motion_character token（含中英文同义词）。"""
    out = []
    if not text:
        return out
    low = str(text).lower()
    for key, token in mapping.items():
        if key in low and token not in out:
            out.append(token)
    # 逐词兜底：匹配枚举词本身
    for t in re.split(r"[^a-z0-9\u4e00-\u9fff_\- ]+", low):
        t = t.strip().lower().replace("-", "_")
        if t in MOTION_CHARACTERS and t not in out:
            out.append(t)
    return out


def _style_characters(style_text):
    """Visual Bible style（如 'Minimal Spatial Tech'）-> character tokens。"""
    out = []
    if not style_text:
        return out
    low = str(style_text).lower()
    for key, token in _STYLE_CHARACTER_MAP.items():
        if key in low and token not in out:
            out.append(token)
    return out


def _uniq(seq):
    return list(dict.fromkeys(seq))


def _effect_tokens(text):
    """从自由文本提取非 character 的效果词（glitch/neon/noise 等）。"""
    out = []
    if not text:
        return out
    low = str(text).lower()
    for key, token in _EFFECT_WORDS.items():
        if key in low and token not in out:
            out.append(token)
    return out


def _frames(seconds, fps):
    """秒 -> frame（四舍五入到最近帧）。"""
    try:
        return max(0, round(float(seconds) * fps))
    except (TypeError, ValueError):
        return 0


def _slug(value):
    if not value:
        return "asset"
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(value)).strip("-") or "asset"


def _get(req, *keys, default=None):
    """按多个候选 key 取 request 字段。"""
    for k in keys:
        if isinstance(req, dict) and req.get(k) is not None:
            return req[k]
    return default


# ---------------------------------------------------------------------------
# build_motion_spec —— 生成 MOTION_SPEC 全字段（frame 精确时序）
# ---------------------------------------------------------------------------

def build_motion_spec(production_request, visual_bible_summary, motion_family):
    """从 request + Visual Bible（restrained 等风格词）+ family 生成 MOTION_SPEC。

    Args:
        production_request: dict，含 request_id/shot_id/layer_id/route/duration/fps/
            alpha_required/visual_requirements/motion_requirements/continuity_group/
            sync_points/transition_in/transition_out/camera 等。
        visual_bible_summary: dict，含 style/style_name/avoid/avoid_list/
            motion_character/effect_philosophy/camera_language。
        motion_family: dict，MF-* 族，含 entry_motion/easing/spring/intensity/
            reuse_mode/build_reason/family_id 等。

    Returns:
        dict：MOTION_SPEC 全字段。timing 全部 frame 计数。
    """
    req = production_request or {}
    vb = visual_bible_summary or {}
    fam = motion_family or {}

    duration = float(req.get("duration") or 0.0)
    fps = int(req.get("fps") or DEFAULT_COMPOSITION["fps"])
    duration_frames = max(0, round(duration * fps))

    visual_req = str(req.get("visual_requirements") or "")
    motion_req = str(req.get("motion_requirements") or "")
    vb_style = _get(vb, "style", "style_name", default="")
    vb_motion = _get(vb, "motion_character", default="")
    vb_effect = _get(vb, "effect_philosophy", default="")
    family_entry = str(fam.get("entry_motion") or "")
    vb_camera = _get(vb, "camera_language", default="")

    # -- motion_character（10 枚举 + 描述 token；首 token 为 primary）-------------
    chars = _uniq(
        _char_tokens(motion_req, _CHAR_SYNONYMS)
        + _char_tokens(family_entry, _CHAR_SYNONYMS)
        + _char_tokens(vb_motion, _CHAR_SYNONYMS)
        + _style_characters(vb_style)
        + _char_tokens(vb_effect, _CHAR_SYNONYMS)
    )
    if not chars:
        chars = ["restrained"]
    # 非 character 效果词（glitch/neon/...）：不进 10 枚举，单独收集供 VB avoid 检测
    effects = _uniq(
        _effect_tokens(motion_req)
        + _effect_tokens(visual_req)
        + _effect_tokens(vb_effect)
        + _effect_tokens(vb_style)
    )

    # -- intensity -------------------------------------------------------------
    intensity = "MEDIUM"
    fam_intensity = _norm_intensity(fam.get("intensity")) if fam.get("intensity") else None
    req_low = str(motion_req).lower() + " " + str(visual_req).lower()
    if fam_intensity is not None:
        intensity = fam_intensity
    elif "hero" in req_low or "heroic" in req_low or "开场爆点" in str(req):
        intensity = "HERO"
    elif "bold" in req_low or "dynamic" in req_low or "intense" in req_low or "high" in req_low:
        intensity = "HIGH"
    elif "restrained" in chars or "soft" in chars or "克制" in str(vb_effect):
        intensity = "LOW"

    # -- easing / spring -------------------------------------------------------
    easing = _norm_easing(fam.get("easing"))
    spring = fam.get("spring") if isinstance(fam.get("spring"), dict) else None
    if spring is None and "elastic" in chars:
        spring = {"stiffness": 220, "damping": 18, "mass": 1}

    # -- timing（frame 计数，§13；不用自然语言）---------------------------------
    entry_ratio, exit_ratio = 0.20, 0.15
    entry_frames = max(0, round(duration_frames * entry_ratio))
    exit_frames = max(0, round(duration_frames * exit_ratio))
    if entry_frames + exit_frames > duration_frames:
        entry_frames, exit_frames = 0, 0
    hold_start = entry_frames
    hold_end = max(hold_start, duration_frames - exit_frames)
    timing = {
        "start_frame": 0,
        "end_frame": duration_frames,
        "duration_frames": duration_frames,
        "entry": {"start_frame": 0, "end_frame": entry_frames, "frames": entry_frames},
        "hold": {"start_frame": hold_start, "end_frame": hold_end,
                 "frames": max(0, hold_end - hold_start)},
        "exit": {"start_frame": hold_end, "end_frame": duration_frames,
                 "frames": max(0, duration_frames - hold_end)},
        "sync_points": [max(0, _frames(s, fps)) for s in
                        (req.get("audio_sync_points") or req.get("sync_points") or [])
                        if isinstance(s, (int, float))],
    }

    # -- elements（visual_requirements 关键词 -> 元素列表）-----------------------
    elements = _build_elements(visual_req, motion_req)

    # -- transform 属性（restrained 优先：低幅值）-------------------------------
    subtle = intensity in ("LOW", "MEDIUM") and "restrained" in chars
    scale = {
        "entry": {"value_from": 0.96 if subtle else 0.88, "value_to": 1.0},
        "hold": {"value": 1.0},
        "exit": {"value_from": 1.0, "value_to": 1.02},
    }
    position = {
        "entry": {"value_from": {"y": 18 if subtle else 40, "x": 0}, "value_to": {"y": 0, "x": 0}},
        "hold": {"value": {"x": 0, "y": 0}},
        "exit": {"value_from": {"x": 0, "y": 0}, "value_to": {"x": 0, "y": -10}},
    }
    rotation = {
        "entry": {"value_from": 0.0, "value_to": 0.0},
        "hold": {"value": 0.0},
        "exit": {"value_from": 0.0, "value_to": 0.0},
    }
    if "kinetic" in chars:
        rotation["entry"] = {"value_from": -3.0, "value_to": 0.0}
    opacity = {
        "entry": {"value_from": 0.0, "value_to": 1.0},
        "hold": {"value": 1.0},
        "exit": {"value_from": 1.0, "value_to": 0.0},
    }
    blur = {
        "entry": {"value_from": 6.0 if "soft" in chars else 0.0, "value_to": 0.0},
        "hold": {"value": 0.0},
        "exit": {"value_from": 0.0, "value_to": 0.0},
    }

    # -- camera / parallax / depth ---------------------------------------------
    camera_movement = "none"
    if "spatial" in chars:
        camera_movement = "subtle-push" if subtle else "push"
    if vb_camera and "push" in str(vb_camera).lower():
        camera_movement = "push"
    camera = {
        "movement": camera_movement,
        "zoom_from": 1.0,
        "zoom_to": 1.04 if camera_movement != "none" else 1.0,
        "pan_deg": 0.0,
        "tilt_deg": 0.0,
        "notes": "restrained: camera 克制，由主体运动承担表达" if subtle else "camera 承担部分表达",
    }
    parallax = ("spatial" in chars) and not subtle
    depth = "layered" if ("spatial" in chars or "3d" in str(visual_req).lower()) else "flat"

    # -- transition ------------------------------------------------------------
    transition_in = req.get("transition_in") or ("fade" if subtle else "slide")
    transition_out = req.get("transition_out") or ("fade" if subtle else "fade")

    # -- alpha / render_format -------------------------------------------------
    alpha = bool(req.get("alpha_required") if req.get("alpha_required") is not None
                 else req.get("alpha"))
    render_format = {
        "codec": "prores" if alpha else "h264",
        "profile": "4444" if alpha else "high",
        "container": "mov" if alpha else "mp4",
        "alpha_supported": alpha,
        "alternative": "webm(vp9)" if alpha else None,
    }

    # -- avoid / continuity ----------------------------------------------------
    avoid = _uniq(
        [str(a).lower() for a in (vb.get("avoid") or vb.get("avoid_list") or [])]
        + [str(a).lower() for a in (fam.get("avoid") or [])]
        + [str(a).lower() for a in (req.get("avoid") or [])]
    )
    continuity = req.get("continuity_group") or fam.get("continuity_group") or "UNGROUPED"

    # -- reuse 信息（family 决策透传；choose_reuse 单独调用）---------------------
    reuse = {
        "family_id": fam.get("family_id"),
        "family_name": fam.get("family_name"),
        "reuse_mode": fam.get("reuse_mode") if fam.get("reuse_mode") in REUSE_MODES else None,
        "build_reason": fam.get("build_reason"),
        "adapt_notes": fam.get("adapt_notes"),
        "components": fam.get("components") or [],
    }

    # purpose：内容优先（narrative_purpose/visual_requirements），
    # 不混入 motion_requirements 的处理词（避免 'hero' 等治疗词污染 hero 场景判定）
    content = _get(req, "purpose", "narrative_purpose", default="")
    primary = str(content).strip() or str(visual_req).strip()
    purpose = "；".join(p for p in [primary, str(family_entry).strip()] if p)
    if not purpose:
        purpose = "motion asset"

    stagger = {
        "enabled": bool("kinetic" in chars or "elastic" in chars),
        "interval_frames": max(1, round(fps * 0.06)) if ("kinetic" in chars
                                                          or "elastic" in chars) else 0,
        "max_delay_frames": max(1, round(fps * 0.3)) if ("kinetic" in chars
                                                          or "elastic" in chars) else 0,
    }

    spec = {
        "purpose": purpose,
        "duration": duration,
        "fps": fps,
        "duration_frames": duration_frames,
        "composition": {
            "width": int(req.get("width") or DEFAULT_COMPOSITION["width"]),
            "height": int(req.get("height") or DEFAULT_COMPOSITION["height"]),
            "fps": fps,
            "background": "transparent" if alpha else "solid",
        },
        "elements": elements,
        "timing": timing,
        "motion_character": chars,
        "effects": effects,
        "intensity": intensity,
        "easing": easing,
        "spring": spring,
        "stagger": stagger,
        "camera": camera,
        "parallax": parallax,
        "scale": scale,
        "position": position,
        "rotation": rotation,
        "opacity": opacity,
        "blur": blur,
        "shadow": {"enabled": False, "intensity": 0},
        "lighting": "flat",
        "depth": depth,
        "motion_blur": False,
        "transition_in": transition_in,
        "transition_out": transition_out,
        "audio_sync_points": timing["sync_points"],
        "continuity": continuity,
        "alpha": alpha,
        "render_format": render_format,
        "avoid": avoid,
        "reuse": reuse,
        "request_id": req.get("request_id"),
        "shot_id": req.get("shot_id"),
        "layer_id": req.get("layer_id"),
        "route": req.get("route") or "REMOTION",
    }
    return spec


def _build_elements(visual_req, motion_req):
    """visual_requirements 关键词 -> 元素列表（确定性映射，不强求穷尽）。"""
    text = (str(visual_req) + " " + str(motion_req)).lower()
    rules = [
        ("card", {"type": "CARD", "behavior": "expand"}),
        ("chart", {"type": "CHART", "behavior": "animate"}),
        ("graph", {"type": "CHART", "behavior": "animate"}),
        ("data", {"type": "CHART", "behavior": "animate"}),
        ("map", {"type": "MAP", "behavior": "pan"}),
        ("text", {"type": "TEXT", "behavior": "reveal"}),
        ("headline", {"type": "TEXT", "behavior": "reveal"}),
        ("title", {"type": "TEXT", "behavior": "reveal"}),
        ("word", {"type": "TEXT", "behavior": "stagger"}),
        ("number", {"type": "NUMBER", "behavior": "count"}),
        ("metric", {"type": "NUMBER", "behavior": "count"}),
        ("particle", {"type": "PARTICLE", "behavior": "emitter"}),
        ("image", {"type": "IMAGE", "behavior": "ken-burns"}),
        ("photo", {"type": "IMAGE", "behavior": "ken-burns"}),
        ("3d", {"type": "THREE_D", "behavior": "orbit"}),
        ("model", {"type": "THREE_D", "behavior": "orbit"}),
        ("object", {"type": "GENERIC", "behavior": "intro"}),
        ("panel", {"type": "PANEL", "behavior": "expand"}),
        ("button", {"type": "UI", "behavior": "press"}),
    ]
    found = []
    for keyword, element in rules:
        if keyword in text and element not in found:
            found.append(element)
    if not found:
        found.append({"type": "GENERIC", "behavior": "intro"})
    return [{"id": f"E{i + 1}", **el, "role": "subject" if i == 0 else "support"}
            for i, el in enumerate(found)]


# ---------------------------------------------------------------------------
# choose_reuse —— 查 Registry 做 reuse_mode 决策
# ---------------------------------------------------------------------------

def _registry_find(query, route=None, single_type=None, limit=8, timeout=30):
    """调 scripts/registry.py find --json；失败退回 import 复用；再失败抛异常。"""
    cmd = [sys.executable, str(REGISTRY_PY), "find", query or "", "--json",
           "--limit", str(limit)]
    if route:
        cmd += ["--route", route]
    if single_type:
        cmd += ["--type", single_type]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=str(SKILL_ROOT))
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            return data.get("results") or []
    except Exception:  # noqa: BLE001
        pass  # 退回 import 复用（registry.py 有 __main__ 保护，可安全 import）
    try:
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        import registry as _reg  # noqa: PLC0415

        store = _reg.Store()
        ranked, _meta = _reg.search(store, query or "", route=route)
        ranked = _reg.apply_family(ranked)
        ranked = _reg.apply_diversity(ranked, limit)
        return [_reg.candidate_dict(c, "any") for c in ranked]
    except Exception:  # noqa: BLE001
        raise


def choose_reuse(needs):
    """查 Registry 决策 reuse_mode（Reuse→Adapt→Compose→Build Last，§6）。

    Args:
        needs: dict，含 query（必填）/ route / types / style / avoid。
            例：{'query': 'subtle spatial transition', 'route': 'REMOTION'}

    Returns:
        dict：{'mode', 'fit', 'query', 'top', 'candidates', 'components'/'adapt_notes'/
        'build_reason', 'registry'}。mode 恒为 4 枚举之一。
    """
    needs = needs or {}
    query = str(needs.get("query") or "").strip()
    route = needs.get("route") or "REMOTION"
    single_type = None
    types = needs.get("types")
    if isinstance(types, (list, tuple)) and types:
        single_type = str(types[0])

    if not query:
        return {"mode": "BUILD_NEW", "fit": 0.0, "query": "", "top": None,
                "candidates": [], "build_reason": "No query provided; cannot reuse-search",
                "registry": "ok"}

    try:
        results = _registry_find(query, route=route, single_type=single_type)
        registry_state = "ok"
    except Exception as exc:  # noqa: BLE001
        return {"mode": "BUILD_NEW", "fit": 0.0, "query": query, "top": None,
                "candidates": [], "build_reason": f"Registry unavailable ({exc}); "
                "cannot verify reuse, must build", "registry": "error"}

    if not results:
        return {"mode": "BUILD_NEW", "fit": 0.0, "query": query, "top": None,
                "candidates": [],
                "build_reason": f"No existing component supports {query}",
                "registry": registry_state}

    top = results[0]
    fit = float(top.get("fit") or 0.0)
    rel = float((top.get("factors") or {}).get("relevance") or 0.0)
    base = {"mode": None, "fit": round(fit, 3), "query": query, "top": top,
            "candidates": results, "registry": registry_state}

    if fit >= FIT_USE_AS_IS:
        base["mode"] = "USE_AS_IS"
        base["selected"] = top.get("resource_id")
        return base

    if fit >= FIT_ADAPT_MIN or (rel >= ADAPT_HIGH_REL and fit >= FIT_ADAPT_HIGH_REL_MIN):
        base["mode"] = "ADAPT"
        base["selected"] = top.get("resource_id")
        base["adapt_notes"] = (
            f"fit {fit:.2f} rel {rel:.2f}: 需按项目需求调整参数/时序；"
            f"potential_problem: {top.get('potential_problem') or '无明显风险'} "
            f"(source: {top.get('resource_id')})"
        )
        return base

    # query 未命中任何内容（relevance 只剩 route 类型基线）-> 无方案，BUILD_NEW（§80）
    if rel <= RELEVANCE_BASELINE + 1e-9:
        base["mode"] = "BUILD_NEW"
        base["build_reason"] = (
            f"No existing component supports {query} (top: {top.get('resource_id')}, "
            f"fit {fit:.2f}, relevance {rel:.2f} 仅路由基线，无实质命中)"
        )
        return base

    # 两个现成 primitive 可组合 -> COMPOSE
    second = results[1] if len(results) >= 2 else None
    if second is not None and fit >= FIT_COMPOSE_MIN:
        components = [top.get("resource_id"), second.get("resource_id")]
        base["mode"] = "COMPOSE"
        base["components"] = components
        base["compose_note"] = (
            f"无单候选 fit≥{FIT_ADAPT_MIN:.0%}，组合现成 primitive："
            f"{components[0]}（fit {fit:.2f}）+ {components[1]}"
            f"（fit {float(second.get('fit') or 0):.2f}）"
        )
        return base

    # 无方案 -> BUILD_NEW + build_reason（§80 格式）
    base["mode"] = "BUILD_NEW"
    base["build_reason"] = (
        f"No existing component supports {query} (top: {top.get('resource_id')}, "
        f"fit {fit:.2f}, {top.get('potential_problem') or '匹配度不足'})"
    )
    return base


# ---------------------------------------------------------------------------
# check_visual_bible —— VB 冲突检查（§105）
# ---------------------------------------------------------------------------

def check_visual_bible(spec, visual_bible):
    """检查 MOTION_SPEC 是否违反 Visual Bible。

    典型冲突（§105）：
        - VB=restrained 而 spec.intensity=HERO 且非 hero 场景 → violation
        - VB avoid 词命中 spec.motion_character / spring（bouncy）→ violation

    Returns:
        (ok: bool, violations: list[str])
    """
    vb = visual_bible or {}
    violations = []
    if not isinstance(spec, dict):
        return False, ["spec 不是 dict，无法检查"]

    chars = [str(c).lower() for c in (spec.get("motion_character") or [])]
    char_text = " ".join(chars)
    effects = [str(e).lower() for e in (spec.get("effects") or [])]
    intensity = str(spec.get("intensity") or "").upper()
    purpose = str(spec.get("purpose") or "").lower()

    # 1) avoid 词 vs 实际 motion 选择（motion_character + effects + spring）
    avoid = [str(a).lower() for a in (vb.get("avoid") or vb.get("avoid_list") or [])]
    for w in avoid:
        if not w:
            continue
        if w in char_text:
            violations.append(f"VB avoid '{w}' 与 spec.motion_character 冲突: {chars}")
        if w in effects:
            violations.append(f"VB avoid '{w}' 与 spec.effects 冲突: {effects}")
        if w == "bounce" and _is_bouncy_spring(spec.get("spring")):
            violations.append("VB avoid 'bounce' 但 spring 欠阻尼（overshoot）")
        if "elastic" in w and "elastic" in char_text:
            violations.append(f"VB avoid '{w}' 但 spec 使用 elastic motion_character")
        if w in ("hero", "flashy", "showy") and intensity == "HERO":
            violations.append(f"VB avoid '{w}' 但 spec.intensity=HERO")

    # 2) restrained / minimal 风格 vs HERO intensity（非 hero 场景）
    style_text = " ".join(str(vb.get(k) or "") for k in
                          ("style", "style_name", "motion_character", "effect_philosophy"))
    style_low = style_text.lower()
    if ("restrained" in style_low or "克制" in style_text or "minimal" in style_low) \
            and intensity == "HERO":
        hero_words = ("hero", "opening", "climax", "payoff", "title", "爆点", "开场")
        if not any(w in purpose for w in hero_words):
            violations.append(
                f"VB=restrained/minimal 但 spec.intensity=HERO（purpose 非 hero 场景）: {purpose}")

    # 3) easing 冲突：VB restrained 而 easing 明显花哨（本枚举无 elastic easing，保守跳过）
    return (len(violations) == 0), violations


def _is_bouncy_spring(spring):
    """spring 欠阻尼 -> 有 bounce/overshoot。临界阻尼 = 2*sqrt(k*m)（m=1 默认）。"""
    if not isinstance(spring, dict):
        return False
    try:
        stiffness = float(spring.get("stiffness") or 0)
        damping = float(spring.get("damping") or 0)
        mass = float(spring.get("mass") or 1)
    except (TypeError, ValueError):
        return False
    if stiffness <= 0 or damping <= 0:
        return False
    critical = 2.0 * (stiffness * mass) ** 0.5
    return damping < 0.5 * critical


# ---------------------------------------------------------------------------
# motion_qa_technical —— 技术 QA（§24 全项）
# ---------------------------------------------------------------------------

TECHNICAL_CHECKS = [
    "render_success", "frame_count", "duration", "fps", "resolution", "alpha",
    "text_overflow", "asset_missing", "font_missing", "layout_overflow",
    "animation_discontinuity", "nan_invalid_transform", "dependency_errors",
]


def motion_qa_technical(spec, render_result):
    """技术 QA（§24 全项）。render_result 由 P5-6 render 管线填充（dict），
    未提供时对应 check 记 not_applicable（不臆造通过/失败）。

    render_result 契约（约定键）：
        success / frame_count / duration / fps / resolution{w,h} / alpha / codec /
        errors[] / missing_assets[] / missing_fonts[] / layout_overflow /
        animation_breaks[] / nan_transforms / dependency_errors[]

    Returns:
        (ok: bool, checks: list[{check, status, detail}])
    """
    rr = render_result if isinstance(render_result, dict) else {}
    spec = spec if isinstance(spec, dict) else {}
    duration_frames = int(spec.get("duration_frames") or 0)
    fps = float(spec.get("fps") or 0)
    expected_duration = float(spec.get("duration") or 0.0)
    alpha_required = bool(spec.get("alpha"))

    errors = [str(e) for e in (rr.get("errors") or [])]
    err_text = " ".join(errors).lower()

    def no_data(key):
        return key not in rr

    checks = []

    # render success
    if no_data("success"):
        checks.append({"check": "render_success", "status": "not_applicable",
                       "detail": "未提供 render_result"})
    elif rr.get("success") is True:
        checks.append({"check": "render_success", "status": "pass", "detail": "render 成功"})
    else:
        checks.append({"check": "render_success", "status": "fail",
                       "detail": f"render 失败: {err_text[:120] or 'unknown'}"})

    # frame count
    if no_data("frame_count"):
        checks.append({"check": "frame_count", "status": "not_applicable", "detail": "未提供"})
    elif int(rr.get("frame_count") or -1) == duration_frames:
        checks.append({"check": "frame_count", "status": "pass",
                       "detail": f"{rr['frame_count']} == spec {duration_frames}"})
    else:
        checks.append({"check": "frame_count", "status": "fail",
                       "detail": f"实际 {rr.get('frame_count')} != spec {duration_frames}"})

    # duration
    if no_data("duration"):
        checks.append({"check": "duration", "status": "not_applicable", "detail": "未提供"})
    else:
        tol = 0.5 / fps if fps > 0 else 0.05
        if abs(float(rr.get("duration")) - expected_duration) <= tol:
            checks.append({"check": "duration", "status": "pass",
                           "detail": f"{rr.get('duration')}s ≈ spec {expected_duration}s"})
        else:
            checks.append({"check": "duration", "status": "fail",
                           "detail": f"实际 {rr.get('duration')}s != spec {expected_duration}s"})

    # fps
    if no_data("fps"):
        checks.append({"check": "fps", "status": "not_applicable", "detail": "未提供"})
    elif abs(float(rr.get("fps") or 0) - fps) <= 0.01:
        checks.append({"check": "fps", "status": "pass", "detail": f"{rr.get('fps')} == spec {fps}"})
    else:
        checks.append({"check": "fps", "status": "fail",
                       "detail": f"实际 {rr.get('fps')} != spec {fps}"})

    # resolution
    if no_data("resolution"):
        checks.append({"check": "resolution", "status": "not_applicable", "detail": "未提供"})
    else:
        res = rr.get("resolution") or {}
        comp = spec.get("composition") or {}
        want_w, want_h = int(comp.get("width") or 0), int(comp.get("height") or 0)
        got_w, got_h = int(res.get("w") or 0), int(res.get("h") or 0)
        if want_w and want_h and got_w >= want_w and got_h >= want_h:
            checks.append({"check": "resolution", "status": "pass",
                           "detail": f"{got_w}x{got_h} ≥ spec {want_w}x{want_h}"})
        elif want_w and want_h:
            checks.append({"check": "resolution", "status": "fail",
                           "detail": f"实际 {got_w}x{got_h} < spec {want_w}x{want_h}"})
        else:
            checks.append({"check": "resolution", "status": "pass",
                           "detail": f"{got_w}x{got_h}（spec 无约束）"})

    # alpha
    if not alpha_required:
        checks.append({"check": "alpha", "status": "not_applicable",
                       "detail": "spec.alpha=false，无需透明通道"})
    elif no_data("alpha"):
        checks.append({"check": "alpha", "status": "not_applicable", "detail": "未提供"})
    elif rr.get("alpha") is True and _codec_supports_alpha(str(rr.get("codec") or "")):
        checks.append({"check": "alpha", "status": "pass",
                       "detail": f"alpha 存在，codec={rr.get('codec')}"})
    else:
        checks.append({"check": "alpha", "status": "fail",
                       "detail": f"spec 要求 alpha，但实际 alpha={rr.get('alpha')} "
                                 f"codec={rr.get('codec')}（h264/mp4 不支持透明）"})

    # text overflow
    if no_data("errors"):
        checks.append({"check": "text_overflow", "status": "not_applicable", "detail": "未提供"})
    elif any(k in err_text for k in ("text overflow", "overflow", "溢出")):
        checks.append({"check": "text_overflow", "status": "fail", "detail": err_text[:120]})
    else:
        checks.append({"check": "text_overflow", "status": "pass", "detail": "无文本溢出"})

    # asset missing
    missing_assets = rr.get("missing_assets")
    if missing_assets is None:
        checks.append({"check": "asset_missing", "status": "not_applicable", "detail": "未提供"})
    elif isinstance(missing_assets, list) and missing_assets:
        checks.append({"check": "asset_missing", "status": "fail",
                       "detail": f"缺失: {missing_assets}"})
    else:
        checks.append({"check": "asset_missing", "status": "pass", "detail": "无缺失素材"})

    # font missing
    missing_fonts = rr.get("missing_fonts")
    if missing_fonts is None:
        checks.append({"check": "font_missing", "status": "not_applicable", "detail": "未提供"})
    elif isinstance(missing_fonts, list) and missing_fonts:
        checks.append({"check": "font_missing", "status": "fail",
                       "detail": f"缺失: {missing_fonts}"})
    else:
        checks.append({"check": "font_missing", "status": "pass", "detail": "无缺失字体"})

    # layout overflow
    if no_data("layout_overflow"):
        checks.append({"check": "layout_overflow", "status": "not_applicable", "detail": "未提供"})
    elif rr.get("layout_overflow"):
        checks.append({"check": "layout_overflow", "status": "fail", "detail": "布局溢出"})
    else:
        checks.append({"check": "layout_overflow", "status": "pass", "detail": "无布局溢出"})

    # animation discontinuity
    breaks = rr.get("animation_breaks")
    if breaks is None:
        checks.append({"check": "animation_discontinuity", "status": "not_applicable",
                       "detail": "未提供"})
    elif isinstance(breaks, list) and breaks:
        checks.append({"check": "animation_discontinuity", "status": "fail",
                       "detail": f"动画断裂点: {breaks}"})
    else:
        checks.append({"check": "animation_discontinuity", "status": "pass",
                       "detail": "动画连续"})

    # NaN invalid transform
    if no_data("nan_transforms"):
        checks.append({"check": "nan_invalid_transform", "status": "not_applicable",
                       "detail": "未提供"})
    elif rr.get("nan_transforms"):
        checks.append({"check": "nan_invalid_transform", "status": "fail",
                       "detail": "存在 NaN/非法 transform"})
    else:
        checks.append({"check": "nan_invalid_transform", "status": "pass",
                       "detail": "transform 合法"})

    # dependency errors
    dep_errs = rr.get("dependency_errors")
    if dep_errs is None:
        checks.append({"check": "dependency_errors", "status": "not_applicable",
                       "detail": "未提供"})
    elif isinstance(dep_errs, list) and dep_errs:
        checks.append({"check": "dependency_errors", "status": "fail",
                       "detail": f"依赖错误: {dep_errs}"})
    else:
        checks.append({"check": "dependency_errors", "status": "pass", "detail": "无依赖错误"})

    ok = all(c["status"] != "fail" for c in checks)
    return ok, checks


def _codec_supports_alpha(codec):
    c = codec.lower()
    return any(k in c for k in ("prores", "vp9", "webm", "qtrle", "png", "ffv1"))


# ---------------------------------------------------------------------------
# motion_qa_taste —— Taste QA（§25 全项）
# ---------------------------------------------------------------------------

def motion_qa_taste(spec, render_result):
    """Taste QA（§25 全项）：too flashy / too plain / too bouncy / too much camera /
    meaningless motion / inconsistent easing / excessive hero / motion not serving
    information。

    Returns:
        (ok: bool, notes: list[{level: block|warn, check, detail}])
    """
    spec = spec if isinstance(spec, dict) else {}
    notes = []
    chars = [str(c).lower() for c in (spec.get("motion_character") or [])]
    effects = [str(e).lower() for e in (spec.get("effects") or [])]
    intensity = str(spec.get("intensity") or "").upper()
    purpose = str(spec.get("purpose") or "").lower()
    camera = spec.get("camera") or {}
    spring = spec.get("spring")
    sync = spec.get("audio_sync_points") or []
    elements = spec.get("elements") or []
    duration_frames = int(spec.get("duration_frames") or 0)
    fps = float(spec.get("fps") or 30) or 30

    # 1) too flashy
    flashy = any(c in ("kinetic", "elastic") for c in chars) or bool(effects)
    if intensity == "HERO" and flashy:
        notes.append({"level": "block", "check": "too_flashy",
                      "detail": f"intensity=HERO + {chars}/effects={effects}，"
                                "非 hero 场景会过度华丽"})
    elif intensity == "HERO":
        notes.append({"level": "warn", "check": "too_flashy",
                      "detail": "intensity=HERO 但 motion_character 尚克制；确认是否 hero 场景"})

    # 2) too plain
    has_transform_motion = any(
        spec.get(k) and str(spec.get(k)) not in ("{}", "None") and
        (isinstance(spec.get(k), dict)) for k in ("scale", "position", "opacity", "blur"))
    has_camera = str(camera.get("movement") or "none") != "none"
    has_transition = bool(spec.get("transition_in") and spec.get("transition_in") != "none")
    if intensity == "LOW" and not has_camera and not has_transition \
            and not has_transform_motion and duration_frames > 2 * fps:
        notes.append({"level": "warn", "check": "too_plain",
                      "detail": "无 camera/transition/transform 动效，长段（"
                                f"{duration_frames / fps:.1f}s）会显得静止无意图"})

    # 3) too bouncy
    if _is_bouncy_spring(spring):
        notes.append({"level": "warn", "check": "too_bouncy",
                      "detail": f"spring 欠阻尼（{spring}），可能 overshoot 明显"})

    # 4) too much camera
    cam_moves = [str(camera.get("movement") or "")]
    if camera.get("pan_deg"):
        cam_moves.append("pan")
    if camera.get("tilt_deg"):
        cam_moves.append("tilt")
    if camera.get("zoom_to") and abs(float(camera.get("zoom_to") or 1.0) - 1.0) > 0.1:
        cam_moves.append("zoom")
    if spec.get("parallax"):
        cam_moves.append("parallax")
    if len({m for m in cam_moves if m and m != "none"}) >= 2:
        notes.append({"level": "warn", "check": "too_much_camera",
                      "detail": f"同时启用多个运镜: {[m for m in cam_moves if m]}"})

    # 5) meaningless motion：多属性同时动画 且 无信息服务行为 且 无 sync/转场锚点
    info_behaviors = ("reveal", "expand", "count", "animate", "press", "stagger")
    serves_info = any(el.get("behavior") in info_behaviors for el in elements)
    animated_props = sum(1 for k in ("scale", "position", "rotation", "opacity", "blur")
                         if isinstance(spec.get(k), dict))
    if animated_props >= 4 and not sync and not serves_info and not has_transition:
        notes.append({"level": "warn", "check": "meaningless_motion",
                      "detail": f"{animated_props} 个属性同时动画、无 sync_points，"
                                "且元素行为不服务信息揭示，可能脱节"})

    # 6) inconsistent easing
    easings = [str(spec.get("easing") or "")]
    entry = (spec.get("timing") or {}).get("entry") or {}
    hold = (spec.get("timing") or {}).get("hold") or {}
    exit_ = (spec.get("timing") or {}).get("exit") or {}
    for seg in (entry, hold, exit_):
        if isinstance(seg, dict) and seg.get("easing"):
            easings.append(str(seg["easing"]).lower())
    distinct = {e for e in easings if e}
    if len(distinct) > 2:
        notes.append({"level": "warn", "check": "inconsistent_easing",
                      "detail": f"多段 easing 不统一: {sorted(distinct)}"})

    # 7) excessive hero
    if intensity == "HERO" and not any(w in purpose for w in
                                      ("hero", "opening", "climax", "payoff", "title", "爆点")):
        notes.append({"level": "block", "check": "excessive_hero",
                      "detail": f"intensity=HERO 但 purpose={purpose!r} 非 hero 场景"})

    # 8) motion not serving information
    if elements and not sync and not any(el.get("behavior") in info_behaviors
                                         for el in elements):
        notes.append({"level": "warn", "check": "motion_not_serving_information",
                      "detail": f"元素行为 {[el.get('behavior') for el in elements]} "
                                "与信息揭示/同步点无关联"})

    ok = all(n["level"] != "block" for n in notes)
    return ok, notes


# ---------------------------------------------------------------------------
# preview_plan —— Preview First（§22 / §89-91）
# ---------------------------------------------------------------------------

def preview_plan(spec):
    """生成 PREVIEW profile：低清（480p/720p）+ 短段（≤5s），文件名 {asset}_preview.mp4，
    与 final 分离（§89-91）。

    Returns:
        dict：profile / resolution / fps / segment(frames) / filename / final_filename /
        codec / separated / notes。
    """
    spec = spec if isinstance(spec, dict) else {}
    comp = spec.get("composition") or {}
    width = int(comp.get("width") or 1920)
    height = int(comp.get("height") or 1080)
    fps = float(spec.get("fps") or 30) or 30
    duration_frames = int(spec.get("duration_frames") or 0)
    alpha = bool(spec.get("alpha"))

    # 低清：最长边 ≤1280（720p）；若源已 ≤720p 则保持
    scale = min(1.0, 1280.0 / max(width, height))
    pv_w, pv_h = max(2, round(width * scale)), max(2, round(height * scale))

    preview_frames = min(duration_frames, max(1, round(5 * fps)))  # 短段 ≤5s
    asset = spec.get("asset_id") or spec.get("request_id") or \
        f"{spec.get('shot_id') or ''}-{spec.get('layer_id') or ''}"
    slug = _slug(asset)
    final_suffix = "mov" if alpha else "mp4"

    return {
        "asset": slug,
        "profile": "PREVIEW",
        "resolution": {"w": pv_w, "h": pv_h},
        "fps": fps,
        "segment": {"start_frame": 0, "end_frame": preview_frames,
                    "frames": preview_frames},
        "segment_seconds": round(preview_frames / fps, 2) if fps else 0.0,
        "filename": f"{slug}_preview.mp4",
        "final_filename": f"{slug}_final.{final_suffix}",
        "codec": "h264",
        "separated": True,
        "notes": "PREVIEW 低清短段（480p/720p），导演确认后再产出高质量 final；"
                 "preview 与 final 文件分离（§89-91）。",
    }


# ---------------------------------------------------------------------------
# continuity_check —— Motion Continuity Group（§18-19 / §31）
# ---------------------------------------------------------------------------

def continuity_check(requests_in_group):
    """同一 continuity_group 的 requests 应合并为单个 Remotion composition
    （§18-19 / §31：连续 -> 一起 Render，不能为了可编辑性硬拆开）。

    Args:
        requests_in_group: list[dict]，每个 request 含 request_id / shot_id /
            continuity_group / duration / fps / route。

    Returns:
        dict：按 continuity_group 分组的合并建议。
    """
    reqs = [r for r in requests_in_group if isinstance(r, dict)] or []
    groups = {}
    for r in reqs:
        cg = r.get("continuity_group") or "UNGROUPED"
        groups.setdefault(cg, []).append(r)

    out_groups = []
    for cg in sorted(groups):
        members = groups[cg]
        fps_set = {int(m.get("fps") or 30) for m in members}
        route_set = {m.get("route") or "REMOTION" for m in members}
        total_duration = sum(float(m.get("duration") or 0.0) for m in members)
        total_frames = sum(round((float(m.get("duration") or 0.0)) * (int(m.get("fps") or 30)))
                           for m in members)
        request_ids = [m.get("request_id") or m.get("id") for m in members]
        request_ids = [rid for rid in request_ids if rid]

        rationale = [
            "同一 continuity_group 存在连续运动（如 card -> node -> camera transition），"
            "需合并渲染保证连续性（§31）",
        ]
        merge = "MERGE"
        if len(members) < 2:
            merge = "KEEP_SEPARATE"
            rationale = ["单 request 组，天然单 composition"]
        if len(fps_set) > 1:
            rationale.append(f"组内 fps 不一致 {sorted(fps_set)}，需统一为单一 composition fps")
        if len(route_set) > 1:
            rationale.append(f"组内 route 混合 {sorted(route_set)}，建议 HYBRID 合成单 composition")

        out_groups.append({
            "continuity_group": cg,
            "request_ids": request_ids,
            "shot_ids": [m.get("shot_id") for m in members if m.get("shot_id")],
            "count": len(members),
            "total_duration": round(total_duration, 3),
            "total_frames": total_frames,
            "fps": sorted(fps_set),
            "routes": sorted(route_set),
            "merge_recommendation": merge,
            "rationale": rationale,
            "composition_plan": {
                "single_composition": merge == "MERGE",
                "composition_duration": round(total_duration, 3),
                "composition_frames": total_frames,
                "notes": ("合并为单个 Remotion composition，不切碎（§31）"
                          if merge == "MERGE" else "单 request 单 composition"),
            },
        })

    return {
        "total_requests": len(reqs),
        "total_groups": len(out_groups),
        "groups": out_groups,
        "summary": ("同一 continuity_group 的 requests 合并为单个 Remotion composition；"
                    "fps/route 不一致需在 composition 层归一。"),
    }


# ---------------------------------------------------------------------------
# alpha_validation_checks —— alpha 校验清单（§21）
# ---------------------------------------------------------------------------

def alpha_validation_checks():
    """返回 alpha 校验检查清单（真实校验在 render 后由 ffmpeg 探针执行，P5-6 E2E 用）。

    Returns:
        list[{id, check, when, how, expect, status}]
    """
    return [
        {
            "id": "alpha_actual_channel",
            "check": "实际 alpha 通道存在",
            "when": "spec.alpha = true",
            "how": "ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt -of json",
            "expect": "pix_fmt 含 alpha（yuva420p / yuva444p10le / rgba / bgra / gbra）",
            "status": "pending",
        },
        {
            "id": "background_truly_transparent",
            "check": "背景真正透明（非伪 alpha）",
            "when": "spec.alpha = true",
            "how": "ffmpeg -i <asset> -vf alphaextract 抽 alpha 帧 + 背景区域采样（如 4 角）",
            "expect": "背景区域 alpha = 0（前景轮廓外全透明）",
            "status": "pending",
        },
        {
            "id": "no_black_matte",
            "check": "无意外黑底 / 黑边 matte（透明误编码成黑色）",
            "when": "spec.alpha = true",
            "how": "多帧采样背景 RGB；若 alpha=0 处 RGB 非黑则被正确透明，若 RGB 全黑且无 alpha 则是黑底",
            "expect": "背景透明而非黑色 matte；容器元数据（如 prores alpha mode）正确",
            "status": "pending",
        },
        {
            "id": "codec_container",
            "check": "codec / 容器支持 alpha",
            "when": "spec.alpha = true",
            "how": "ffprobe 读 codec_name / container_format",
            "expect": "mov + prores(4444) 或 webm + vp9（带 alpha）；禁止 h264/mp4 伪装透明",
            "status": "pending",
        },
        {
            "id": "alpha_through_frames",
            "check": "整段帧连续有 alpha（非首尾两帧）",
            "when": "spec.alpha = true 且 duration_frames > 1",
            "how": "ffprobe 统计帧数 == spec.duration_frames，抽样若干帧验证 alpha 均存在",
            "expect": "帧数与 spec 一致，抽样帧均有 alpha",
            "status": "pending",
        },
    ]


__all__ = [
    "build_motion_spec", "choose_reuse", "check_visual_bible",
    "motion_qa_technical", "motion_qa_taste", "preview_plan",
    "continuity_check", "alpha_validation_checks",
    "MOTION_CHARACTERS", "INTENSITIES", "EASINGS", "REUSE_MODES",
    "MOTION_SPEC_FIELDS",
]

if __name__ == "__main__":
    # 简易冒烟测试
    _spec = build_motion_spec(
        {"request_id": "PR-001", "shot_id": "S001", "layer_id": "S001-L01",
         "route": "REMOTION", "duration": 3.4, "fps": 30, "alpha_required": True,
         "visual_requirements": "spatial card expansion",
         "motion_requirements": "restrained soft entry"},
        {"style": "Minimal Spatial Tech", "avoid": ["glitch", "neon"]},
        {"entry_motion": "soft spatial entry", "easing": "cubic_bezier",
         "spring": {"stiffness": 200, "damping": 25}})
    print("spec.duration_frames =", _spec["duration_frames"])
    print("spec.motion_character =", _spec["motion_character"])
    _ok, _v = check_visual_bible(_spec, {"avoid": ["glitch", "elastic bounce"]})
    print("check_visual_bible =", _ok, _v)
    _r = choose_reuse({"query": "subtle spatial transition"})
    print("choose_reuse =", _r["mode"], _r.get("build_reason", ""))
    print("MOTION OK")
