#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZHOU_Videodirector — Phase-5 3D Production Engine (P5-4)

Produces the THREE_D_SPEC contract for a THREE_D production request, plus the
adjacent decision helpers required by the 3D pipeline:

  - build_threed_spec            THREE_D_SPEC 全字段生成（Phase-5 §29）
  - recommend_texture_resolution 2K/4K/8K 推荐 + Approval Gate（§30-31）
  - postprocessing_plan          VB 驱动的后处理开关（§38），默认全 off
  - seeded_random                确定性 PRNG（§33-34），重复 render 一致
  - determinism_check            非确定性来源检测（§33）
  - performance_budget_check     性能预算检查清单（§40/§98）
  - physics_conflict_check       organic/chaotic 模拟 → PRODUCTION_CONFLICT（§35）
  - preview_plan                 Preview First 计划（§39）

Shared contracts:
  - THREE_D_SPEC 字段（§29 全部）：purpose/model/scale/position/rotation/material/
    texture/lighting/hdri/camera/lens/camera_path/animation/depth_of_field/
    postprocessing/background/alpha/resolution/fps/duration/performance_budget/
    lod/texture_resolution/continuity_group/audio_sync_points/avoid
  - 技术栈（§27）：@remotion/three + R3F + Drei + Postprocessing + gltfjsx
    （adapter 见 adapters/three-production/README.md，本模块不重造 Helper）
  - Render Profile 4 级（PREVIEW/STANDARD/HIGH/FINAL，Phase 5 最高 HIGH）
  - editability 3（BAKE/KEEP_EDITABLE/ASSET_REPLACEABLE）
  - reuse_mode 4（USE_AS_IS/ADAPT/COMPOSE/BUILD_NEW）

Python 3 stdlib only. No third-party imports. No real LLM calls.
"""

import hashlib
import math
import random
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPEC_VERSION = "THREE_D_SPEC-v1"

# Render Profile 4 级（§99）；Phase 5 最多用到 HIGH
RENDER_PROFILES = {
    "PREVIEW": {"resolution": [1280, 720], "quality": "preview", "max_texture": "2K"},
    "STANDARD": {"resolution": [1920, 1080], "quality": "standard", "max_texture": "4K"},
    "HIGH": {"resolution": None, "quality": "high", "max_texture": "4K"},  # 项目分辨率
    "FINAL": {"resolution": None, "quality": "final", "max_texture": "8K"},  # 交付级
}

# 性能预算默认表（§40/§98）。真实数据由 render 环境提供；缺省/ mock 时用此表评估。
DEFAULT_BUDGETS = {
    "PREVIEW": {"max_poly_count": 500000, "max_texture_mb": 512,
                "max_memory_mb": 2048, "max_frame_render_s": 0.25, "fps": 30},
    "STANDARD": {"max_poly_count": 300000, "max_texture_mb": 256,
                 "max_memory_mb": 1024, "max_frame_render_s": 0.10, "fps": 30},
    "HIGH": {"max_poly_count": 200000, "max_texture_mb": 192,
             "max_memory_mb": 1024, "max_frame_render_s": 0.08, "fps": 30},
    "FINAL": {"max_poly_count": 200000, "max_texture_mb": 256,
              "max_memory_mb": 2048, "max_frame_render_s": 0.08, "fps": 30},
}

# 模拟场景（mock）：真实模型元数据由 render 环境回填，这里演示评估路径。
MOCK_MODEL_META = {
    "mock": True,
    "poly_count": 150000,
    "vertex_count": 300000,
    "textures": [
        {"name": "base_color", "w": 2048, "h": 2048},
        {"name": "normal", "w": 2048, "h": 2048},
        {"name": "roughness", "w": 2048, "h": 2048},
        {"name": "metalness", "w": 2048, "h": 2048},
    ],
    "draw_calls": 40,
    "shader_compile": "ok",
    "missing_textures": [],
    "frame_render_s": 0.09,
    "camera_clipping": "ok",
    "z_fighting": False,
    "aliasing": False,
    "frame_stability": "stable",
}

# organic / chaotic 模拟（§35）：成本过高应转 GENERATIVE_VIDEO / HYBRID
ORGANIC_SIM_TERMS = [
    "cloth", "布料", "hair", "头发", "fluid", "流体", "liquid", "液体",
    "smoke", "烟", "water", "水", "fire", "火焰", "explosion", "爆炸",
    "debris", "碎片", "rigid body", "刚体", "collision", "碰撞",
    "physics sim", "物理模拟", "chaos", "混沌", "organic", "有机",
    "crowd", "人群", "plant", "植物", "wave", "波浪", "splash", "水花",
]

# 相机关键词 → movement（§36：position/target/fov/lens/movement/duration/easing）
_CAM_MOVEMENT = [
    ("orbit", ["orbit", "环绕", "turntable", "转台", "rotate camera"]),
    ("crane", ["crane", "摇臂"]),
    ("drone", ["drone", "航拍"]),
    ("handheld", ["handheld", "手持"]),
    ("dolly", ["dolly", "跟拍", "跟随", "follow"]),
    ("tilt", ["tilt", "俯仰", "上下摇"]),
    ("pan", ["pan", "横移", "摇移"]),
    ("push_in", ["push", "推进", "推近", "dolly in", "zoom in", "慢推"]),
    ("pull_out", ["pull", "拉远", "zoom out"]),
]

# 后处理关键词（§38，只在 VB 需要时开启）
_PP_KEYWORDS = {
    "bloom": ["bloom", "辉光", "光晕", "glow", "发光"],
    "depth_of_field": ["dof", "景深", "bokeh", "焦外", "浅景深", "depth of field"],
    "vignette": ["vignette", "暗角"],
    "tone_mapping": ["tone mapping", "tone mapped", "aces", "电影感", "cinematic",
                     "胶片", "film look", "对比"],
    "chromatic_aberration": ["chromatic aberration", "色差", "ca"],
}

# 视觉圣经灯光倾向（§37）
_VB_LIGHT_RULES = [
    # (关键词组, 应用于 lighting 的覆写 dict)
    (["无阴影", "no shadow", "flat", "均匀", "软件界面", "平面"], {
        "shadow_enabled": False, "contrast": 1.0, "fill_ratio": 0.9, "rim_intensity": 0.4}),
    (["dramatic", "强烈", "高对比", "high contrast", "film noir"], {
        "shadow_enabled": True, "contrast": 2.0, "rim_intensity": 1.8, "fill_ratio": 0.3}),
    (["warm", "暖", "暖色", "golden"], {"temperature": 4200}),
    (["cold", "冷", "冷色", "blue hour"], {"temperature": 7500}),
    (["neon", "霓虹"], {"temperature": 7000, "shadow_enabled": False}),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _clamp(v, lo, hi):
    return max(lo, min(hi, float(v)))


def _to_text(v):
    """Flatten str / dict / list / None into a searchable string."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return " ".join(_to_text(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return " ".join(_to_text(x) for x in v)
    return str(v)


def _pick(obj, keys, default=None):
    """First present key lookup (tolerant to parallel P5-1 schema)."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj and obj[k] is not None:
            return obj[k]
    return default


def _fnum(v, default, lo=None, hi=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        f = default
    if lo is not None:
        f = max(lo, f)
    if hi is not None:
        f = min(hi, f)
    return f


def _parse_resolution(value):
    """Parse '1920x1080' / [1920, 1080] / {'w':..,'h':..} -> [w, h] or None."""
    if isinstance(value, dict):
        w = value.get("w") or value.get("width")
        h = value.get("h") or value.get("height")
        if w and h:
            return [int(w), int(h)]
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [int(value[0]), int(value[1])]
    if isinstance(value, str):
        m = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", value)
        if m:
            return [int(m.group(1)), int(m.group(2))]
    return None


def _lens_mm_from_fov(fov_deg):
    """35mm 等效焦距：水平传感器宽 36mm，fov 为水平视场角。"""
    return round(36.0 / (2.0 * math.tan(math.radians(fov_deg) / 2.0)), 1)


# ---------------------------------------------------------------------------
# build_threed_spec — THREE_D_SPEC 全字段（§29）
# ---------------------------------------------------------------------------


def _parse_camera(camera_requirements, duration, fov=None):
    """§36 camera spec：position/target/fov/lens/movement/duration/easing。
    禁止只写 'cinematic camera' —— 输出必须是可执行的数值参数。"""
    text = _to_text(camera_requirements)
    ltext = text.lower()
    movement = "static"
    for move, kws in _CAM_MOVEMENT:
        if any(k in ltext for k in kws):
            movement = move
            break

    speed = "normal"
    if any(k in ltext for k in ("slow", "慢", "克制", "平稳", "缓缓")):
        speed = "slow"
    elif any(k in ltext for k in ("fast", "快", "急促")):
        speed = "fast"

    if fov is None:
        if any(k in ltext for k in ("tele", "长焦")):
            fov = 24.0
        elif any(k in ltext for k in ("wide", "广角")):
            fov = 50.0
        else:
            fov = 35.0  # 产品展示默认

    # position / target 由 movement 与距离语义推导
    radius = 4.0
    if any(k in ltext for k in ("close", "近", "特写")):
        radius = 2.5
    elif any(k in ltext for k in ("far", "远", "全景")):
        radius = 6.0
    if movement == "orbit":
        position = [round(radius * 0.7071, 2), 1.2, round(radius * 0.7071, 2)]
        sweep = 360
        if speed == "slow":
            sweep = 180
        elif speed == "fast":
            sweep = 540
        easing = "linear"
        orbit_note = "orbit sweep %d deg over duration; angular velocity constant (frame-driven)." % sweep
    else:
        position = [0.0, 1.2, radius]
        sweep = None
        orbit_note = None
        if movement == "static":
            easing = "none"
        elif speed == "slow":
            easing = "easeInOutSine"
        elif speed == "fast":
            easing = "easeInCubic"
        else:
            easing = "easeInOutCubic"
    target = [0.0, 0.5, 0.0]

    camera = {
        "position": position,
        "target": target,
        "fov": fov,
        "lens": _lens_mm_from_fov(fov),  # 35mm 等效
        "movement": movement,
        "duration": duration,
        "easing": easing,
        "speed": speed,
    }
    if sweep is not None:
        camera["orbit_sweep_degrees"] = sweep
    if orbit_note:
        camera["notes"] = orbit_note
    return camera


def _parse_lighting(visual_requirements, vb):
    """§37 lighting spec：key/fill/rim/environment/contrast/temperature/shadow。"""
    text = ((visual_requirements or "") + " " + _to_text(vb)).lower()
    lighting = {
        "key": {"intensity": 2.0, "position": [3.0, 4.0, 3.0], "color": "#FFFFFF"},
        "fill": {"intensity": 0.6, "position": [-3.0, 1.0, 2.0], "color": "#FFFFFF"},
        "rim": {"intensity": 1.2, "position": [-2.0, 3.0, -3.0], "color": "#FFFFFF"},
        "environment": None,
        "contrast": 1.2,
        "temperature": 5500,
        "shadow": {"enabled": True, "softness": 0.3, "map_resolution": 1024},
        "notes": [],
    }
    for kws, overrides in _VB_LIGHT_RULES:
        if any(k in text for k in kws):
            if "shadow_enabled" in overrides:
                lighting["shadow"]["enabled"] = overrides["shadow_enabled"]
            if "contrast" in overrides:
                lighting["contrast"] = overrides["contrast"]
            if "fill_ratio" in overrides:
                lighting["fill"]["intensity"] = round(overrides["fill_ratio"] * 0.6, 2)
            if "rim_intensity" in overrides:
                lighting["rim"]["intensity"] = overrides["rim_intensity"]
            if "temperature" in overrides:
                lighting["temperature"] = overrides["temperature"]
            lighting["notes"].append("VB override applied: %s" % ",".join(kws[:2]))
    return lighting


def _parse_material(visual_requirements, vb):
    text = ((visual_requirements or "") + " " + _to_text(vb)).lower()
    if any(k in text for k in ("glass", "玻璃", "磨砂", "frosted", "translucent")):
        return {"base": "glass", "metalness": 0.0, "roughness": 0.1,
                "transmission": 0.9, "clearcoat": 1.0,
                "notes": "transmission material (meshPhysicalMaterial)"}
    if any(k in text for k in ("metal", "金属", "chrome", "mirror", "银")):
        return {"base": "metal", "metalness": 1.0, "roughness": 0.2,
                "transmission": 0.0, "clearcoat": 0.0,
                "notes": "high-metalness PBR"}
    if any(k in text for k in ("matte", "哑光", "plastic", "塑料", "fabric", "布料")):
        return {"base": "matte", "metalness": 0.0, "roughness": 0.85,
                "transmission": 0.0, "clearcoat": 0.0,
                "notes": "diffuse-dominant matte surface"}
    return {"base": "standard_pbr", "metalness": 0.3, "roughness": 0.5,
            "transmission": 0.0, "clearcoat": 0.0,
            "notes": "neutral PBR fallback"}


def _parse_animation(visual_requirements, duration):
    text = _to_text(visual_requirements).lower()
    anim = {"type": "none", "duration": duration, "easing": "easeOutCubic",
            "seeded": True, "seed": None, "frame_driven": True}
    if any(k in text for k in ("explode", "exploded", "爆炸", "拆解")):
        anim["type"] = "exploded_view"
    elif any(k in text for k in ("reveal", "展开", "揭示")):
        anim["type"] = "reveal"
    elif any(k in text for k in ("assemble", "组装", "reassemble", "拼装")):
        anim["type"] = "assembly"
    elif any(k in text for k in ("spin", "rotate", "旋转", "转动")):
        anim["type"] = "rotation"
    elif any(k in text for k in ("float", "悬浮", "hover")):
        anim["type"] = "float"
    elif any(k in text for k in ("scale", "缩放", "pulse")):
        anim["type"] = "scale_pulse"
    return anim


def _extract_registry_resources(context):
    """从 context 的 resource selections 中提取 model / hdri / texture 引用。"""
    out = {"model": None, "hdri": None, "textures": []}
    context = context or {}
    for key in ("resource_selections", "resources", "selected_resources"):
        items = context.get(key) or []
        if isinstance(items, dict):
            items = list(items.values())
        for item in items:
            if not isinstance(item, dict):
                continue
            sel = item.get("selected_resource") or item
            rid = _pick(sel, ["resource_id", "id"], "") or ""
            rtype = _pick(sel, ["type"], "") or ""
            if rtype == "THREE_D_MODEL" or ":three-d-model:" in rid:
                out["model"] = out["model"] or rid
            elif rtype == "HDRI" or ":hdri:" in rid:
                out["hdri"] = out["hdri"] or rid
            elif rtype == "TEXTURE" or ":texture:" in rid:
                out["textures"].append(rid)
    return out


def _texture_resolution_ctx(pr, context, shot_size, camera_req):
    """聚合 recommend_texture_resolution 的输入。"""
    out = {"shot_size": shot_size or "medium shot",
           "camera_distance": camera_req if isinstance(camera_req, (int, float)) else None,
           "output_resolution": _parse_resolution(pr.get("output_resolution"))
           or _parse_resolution(context.get("output_resolution")) or [1920, 1080]}
    rp = (context.get("render_profile") or pr.get("render_profile") or "STANDARD").upper()
    if rp in RENDER_PROFILES:
        out["render_performance"] = rp
    if context.get("asset_reuse"):
        out["asset_reuse"] = context["asset_reuse"]
    return out


def build_threed_spec(production_request, context=None):
    """生成 THREE_D_SPEC 全字段（Phase-5 §29）。

    production_request: dict，含 request_id/shot_id/layer_id/route/duration/fps/
        alpha_required/visual_requirements/camera_requirements/output_resolution/
        continuity_group/audio/avoid 等（对 P5-1 并行 schema 缺失字段做防御性读取）。
    context: dict，可含 visual_bible / resource_selections / render_profile 等。
    """
    pr = production_request or {}
    context = context or {}
    vb = context.get("visual_bible") or context.get("visual_bible_summary") or {}
    vb_text = _to_text(vb)

    duration = _fnum(_pick(pr, ["duration"], 5.0), 5.0, lo=0.1)
    fps = int(_fnum(_pick(pr, ["fps"], 30), 30, lo=1, hi=120))
    alpha = bool(_pick(pr, ["alpha_required"], False))
    render_profile = (_pick(context, ["render_profile"], "")
                      or _pick(pr, ["render_profile"], "") or "STANDARD").upper()
    if render_profile not in RENDER_PROFILES:
        render_profile = "STANDARD"

    visual_req = _pick(pr, ["visual_requirements", "visual_requirement", "visual"], "")
    camera_req = _pick(pr, ["camera_requirements", "camera_requirement"], "")
    shot_size = _pick(pr, ["shot_size", "framing"], "")

    camera = _parse_camera(camera_req, duration)
    lighting = _parse_lighting(visual_req, vb_text)
    registry = _extract_registry_resources(context)

    tex_ctx = _texture_resolution_ctx(pr, context, shot_size, camera_req)
    texture_rec = recommend_texture_resolution(tex_ctx)

    audio = pr.get("audio") if isinstance(pr.get("audio"), dict) else {}
    sync_points = audio.get("sync_points") or context.get("audio_sync_points") or []

    avoid = _pick(pr, ["avoid", "avoid_list"], [])
    if isinstance(avoid, str):
        avoid = [avoid]
    if isinstance(vb, dict) and vb.get("avoid"):
        avoid = list(avoid or []) + (vb["avoid"] if isinstance(vb["avoid"], list) else [vb["avoid"]])

    background_type = "transparent" if alpha else "solid"
    if lighting.get("environment"):
        background_type = "hdri"
    background = {
        "type": background_type,
        "color": "#000000" if background_type == "solid" else None,
        "hdri": registry["hdri"] if background_type == "hdri" else None,
        "alpha_channel": alpha,
    }

    reuse_mode = "BUILD_NEW"
    build_reason = None
    if registry["model"]:
        reuse_mode = "USE_AS_IS"
    elif registry["textures"] or registry["hdri"]:
        reuse_mode = "COMPOSE"  # 模型自建，但纹理/环境复用 Registry
        build_reason = "no matching THREE_D_MODEL in registry; composing from primitives + registry textures/HDRI"
    else:
        build_reason = "no registry match; building from R3F primitives (one-off simple model, no long-term framework)"

    spec = {
        "spec_version": SPEC_VERSION,
        "request_id": _pick(pr, ["request_id"], ""),
        "shot_id": _pick(pr, ["shot_id"], ""),
        "layer_id": _pick(pr, ["layer_id"], ""),
        "route": "THREE_D",
        "render_profile": render_profile,
        "purpose": _pick(pr, ["purpose"], visual_req) or "3D product visualization",
        "model": {
            "source": registry["model"] or "R3F primitives",
            "style": _pick(vb, ["style"], "") if isinstance(vb, dict) else vb_text[:80],
            "reuse_mode": reuse_mode,
            "build_reason": build_reason,
            "gltfjsx_required": bool(registry["model"] and camera["movement"] not in ("static",)),
        },
        "scale": [1.0, 1.0, 1.0],
        "position": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0],
        "material": _parse_material(visual_req, vb_text),
        "texture": {
            "maps": registry["textures"] or [],
            "resolution": texture_rec["recommendation"],
            "source": registry["textures"][0] if registry["textures"] else None,
        },
        "lighting": lighting,
        "hdri": registry["hdri"] or None,
        "camera": camera,
        "lens": camera["lens"],
        "camera_path": [],
        "animation": _parse_animation(visual_req, duration),
        "depth_of_field": bool(re.search(r"dof|景深|bokeh|浅景深", vb_text, re.I)),
        "postprocessing": postprocessing_plan(vb),
        "background": background,
        "alpha": alpha,
        "resolution": _parse_resolution(pr.get("output_resolution"))
        or RENDER_PROFILES[render_profile]["resolution"]
        or [1920, 1080],
        "fps": fps,
        "duration": duration,
        "performance_budget": {
            "profile": render_profile,
            "limits": DEFAULT_BUDGETS.get(render_profile, DEFAULT_BUDGETS["STANDARD"]),
            "texture_cap": RENDER_PROFILES[render_profile]["max_texture"],
        },
        "lod": "auto",  # 渲染环境按相机距离自动降级
        "texture_resolution": texture_rec,
        "continuity_group": _pick(pr, ["continuity_group"], None),
        "audio_sync_points": sync_points,
        "avoid": avoid,
        "editability": "ASSET_REPLACEABLE",
        "determinism_seed": None,  # 由 seeded_random 派生后回填
        "notes": [],
    }
    # 确定性：为动画 seed 生成确定性种子（请求稳定哈希派生）
    seed_src = "%s|%s|%s|%s" % (spec["request_id"], spec["shot_id"], spec["layer_id"],
                                spec["purpose"])
    spec["determinism_seed"] = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:8], 16)
    spec["animation"]["seed"] = spec["determinism_seed"]
    if camera.get("notes"):
        spec["notes"].append(camera["notes"])
    return spec


# ---------------------------------------------------------------------------
# recommend_texture_resolution — 2K/4K/8K 推荐 + Approval Gate（§30-31）
# ---------------------------------------------------------------------------


def _shot_size_class(shot_context):
    """shot_size / camera_distance → CLOSE / MEDIUM / WIDE。"""
    s = _to_text(shot_context.get("shot_size") or "").lower()
    if any(k in s for k in ("hero close-up", "extreme close-up", "macro",
                            "extreme closeup", "特写", "微距", "大特写")):
        return "CLOSE"
    if any(k in s for k in ("close-up", "close up", "closeup", "近景")):
        return "CLOSE"
    if any(k in s for k in ("medium", "中景", "waist")):
        return "MEDIUM"
    if any(k in s for k in ("wide", "full", "long shot", "establishing",
                            "全景", "远景")):
        return "WIDE"
    d = _camera_distance(shot_context)
    if d is not None:
        if d <= 1.0:
            return "CLOSE"
        if d <= 3.5:
            return "MEDIUM"
        return "WIDE"
    return "MEDIUM"


def _camera_distance(shot_context):
    v = shot_context.get("camera_distance")
    if isinstance(v, (int, float)):
        return float(v)
    s = _to_text(v)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(m|meters|米)?", s)
    if m:
        return float(m.group(1))
    return None


def _output_width(shot_context):
    res = shot_context.get("output_resolution")
    parsed = _parse_resolution(res)
    if parsed:
        return parsed[0]
    s = _to_text(res)
    m = re.search(r"(\d{3,5})\s*p", s)
    if m:
        return int(m.group(1))
    return 1920


def recommend_texture_resolution(shot_context):
    """§30-31 核心：按 shot 需求推荐 2K/4K/8K。

    输入: shot_size / camera_distance / output_resolution / render_performance /
          asset_reuse。
    输出: recommendation + reason + approval_required。
    硬规则: 禁止「8K=always better」—— 8K 只在极端特写 + 4K 输出 + 高预算时才给出，
    否则明确标注 unnecessary；4K/8K 纹理获取必须走 Approval Gate（总设计 §50）。
    """
    sc = shot_context or {}
    cls = _shot_size_class(sc)
    width = _output_width(sc)
    perf = _to_text(sc.get("render_performance") or "").upper()

    if cls == "CLOSE":
        if width >= 3840 and perf not in ("PREVIEW", "LOW"):
            rec = "4K"
            reason = ("hero close-up on >=4K output: 4K preserves surface detail "
                      "for tight framing")
        elif perf in ("PREVIEW", "LOW"):
            rec = "2K"
            reason = ("hero close-up but preview/low performance budget: 2K keeps "
                      "render time in budget; upgrade to 4K for final")
        else:
            rec = "4K"
            reason = ("hero close-up: 4K texture resolution for on-screen detail; "
                      "8K unnecessary (screen <=1080p, texel density already exceeds screen)")
    elif cls == "WIDE":
        rec = "2K"
        reason = "2K sufficient for wide shot: subject occupies a small screen area"
    else:
        rec = "2K"
        reason = "2K sufficient for medium shot: texel density on screen below 1:1 even at 1080p"

    # asset reuse：已缓存资源优先复用，避免重复下载（§70 渐进加载）
    reuse_note = None
    reuse = sc.get("asset_reuse")
    if isinstance(reuse, dict):
        res = _to_text(reuse.get("resolution") or "")
        if res.upper() in ("2K", "4K", "8K"):
            reuse_note = "existing cached asset resolution is %s; prefer reuse to avoid re-fetch" % res.upper()
    if reuse_note:
        reason += "; " + reuse_note

    # 8K 判定：只在「宏/极特写 + 8K 输出 + 高预算」才给出，其余一律 unnecessary
    if cls == "CLOSE" and width >= 7680 and perf in ("HIGH", "FINAL"):
        rec = "8K"
        reason = ("extreme close-up on 8K output with high budget: 8K justified; "
                  "rarely needed in Phase 5")
        approval_required = True
        approval_reason = "8K texture download is large and expensive (Execution Approval, §50)"
        eight_k_verdict = "justified for 8K output extreme close-up only"
    else:
        approval_required = rec in ("4K", "8K")
        approval_reason = (
            "4K/8K texture acquisition is a large download and requires Execution Approval (§50)"
            if approval_required else
            "2K texture is a small download; no approval gate"
        )
        eight_k_verdict = ("unnecessary: screen resolution and framing do not benefit "
                           "from 8K texel density (8K is never 'always better', §30-31)")

    return {
        "recommendation": rec,
        "recommended_px": {"2K": 2048, "4K": 4096, "8K": 8192}[rec],
        "shot_size_class": cls,
        "reason": reason,
        "approval_required": approval_required,
        "approval_reason": approval_reason,
        "eight_k_verdict": eight_k_verdict,
        "rule_notes": ("No default maximum quality: 8K is never 'always better' — "
                       "resolution is driven by shot need (§30-31), and 4K/8K always "
                       "carries an approval gate."),
    }


# ---------------------------------------------------------------------------
# postprocessing_plan — VB 驱动的后处理开关（§38）
# ---------------------------------------------------------------------------


def postprocessing_plan(visual_bible_summary):
    """只在 Visual Bible 需要时启用 bloom/dof/vignette/tone mapping/CA，默认全 off。"""
    text = _to_text(visual_bible_summary).lower()
    flags = {}
    enabled = []
    for key, kws in _PP_KEYWORDS.items():
        on = any(k in text for k in kws)
        flags[key] = on
        if on:
            enabled.append(key)
    return {
        "bloom": flags["bloom"],
        "depth_of_field": flags["depth_of_field"],
        "vignette": flags["vignette"],
        "tone_mapping": flags["tone_mapping"],
        "chromatic_aberration": flags["chromatic_aberration"],
        "enabled": enabled,
        "reason": ("VB requests: %s" % ", ".join(enabled)) if enabled
                  else "VB does not request postprocessing; default all off (§38)",
        "notes": "Postprocessing enabled only when the Visual Bible requires it.",
    }


# ---------------------------------------------------------------------------
# seeded_random — 确定性 PRNG（§33-34）
# ---------------------------------------------------------------------------


def seeded_random(seed, n):
    """返回 n 个 [0,1) 的确定性随机数。

    使用 random.Random(seed)，同一 seed 在任何进程/平台产生相同序列 →
    粒子/噪声/抖动在重复 render 中逐帧一致。种子应来自
    build_threed_spec 的 determinism_seed 并版本化保存。
    """
    rng = random.Random(int(seed))
    return [rng.random() for _ in range(int(n))]


# ---------------------------------------------------------------------------
# determinism_check — 非确定性来源检测（§33）
# ---------------------------------------------------------------------------


def determinism_check(scene_desc):
    """检测 wall-clock 动画 / 未 seed 随机 / 非确定性模拟，返回 (ok, notes[])。

    scene_desc: dict（可含 random_positions/random_rotation/noise/jitter/
    wall_clock/physics_simulation/seed/animation 等）。
    """
    sd = scene_desc or {}
    text = _to_text(sd).lower()
    notes = []

    seed = sd.get("seed")
    if seed is None:
        seed = sd.get("random_seed")
    has_seed = seed not in (None, False, "", 0)

    random_claims = [
        "random_positions", "random_rotation", "random_scale", "random_offset",
        "particle_noise", "noise", "jitter", "randomness",
    ]
    for key in random_claims:
        v = sd.get(key)
        if v in (True, 1, "true", "yes"):
            if not has_seed:
                notes.append("%s=True without a seed" % key)
    if not has_seed and re.search(r"random|噪声|noise|抖动|jitter", text):
        notes.append("randomness/noise present but no seed set")

    wall_claims = ["wall_clock", "wall-clock", "performance_now", "date_now",
                   "time_since_start", "uses_wall_clock"]
    for key in wall_claims:
        if sd.get(key) in (True, 1, "true", "yes"):
            notes.append("%s=True: wall-clock animation is non-deterministic" % key)
    if re.search(r"date\.now|performance\.now|math\.random|new date\(", text):
        notes.append("source text contains Date.now/performance.now/Math.random (wall-clock/unseeded)")

    sim_claims = ["physics_simulation", "rigid_body_sim", "fluid_sim", "cloth_sim",
                  "simulation", "collision_sim"]
    for key in sim_claims:
        if sd.get(key) in (True, 1, "true", "yes"):
            if not has_seed:
                notes.append("%s=True without a seed: non-deterministic simulation" % key)
            else:
                notes.append("%s=True but simulation physics may still be non-deterministic" % key)
    if any(k in text for k in ("cloth sim", "fluid sim", "rigid body", "chaos")) and not has_seed:
        notes.append("physical simulation requested without a seed")

    if not has_seed and not notes:
        notes.append("no seed found; seed all random sources for repeatable renders")
    ok = not notes
    return ok, notes


# ---------------------------------------------------------------------------
# performance_budget_check — 性能预算检查清单（§40/§98）
# ---------------------------------------------------------------------------

_CHECK_RULES = [
    ("polygon_count", "poly_count", "model poly count within budget"),
    ("texture_size", None, "total texture memory within budget"),
    ("memory_estimate", None, "estimated GPU/CPU memory within budget"),
    ("render_time_budget", "frame_render_s", "per-frame render time within frame budget"),
    ("missing_texture", "missing_textures", "no missing texture files"),
    ("shader_errors", "shader_compile", "shaders compile without errors"),
    ("camera_clipping", "camera_clipping", "camera near/far planes do not clip geometry"),
    ("z_fighting", "z_fighting", "no z-fighting coplanar surfaces"),
    ("aliasing", "aliasing", "no visible aliasing (MSAA/multisampling)"),
    ("frame_stability", "frame_stability", "frame render times stable across the shot"),
]


def _texture_bytes(model_meta):
    total = 0
    for t in model_meta.get("textures", []) or []:
        if isinstance(t, dict):
            w = t.get("w") or t.get("width") or 0
            h = t.get("h") or t.get("height") or 0
            total += int(w) * int(h) * 4  # RGBA8
    return total


def performance_budget_check(model_meta, budget=None):
    """返回 (ok, checks[])。checks 每项 {check, status, detail}。

    真实数据由 render 环境提供（model_meta 回填 render 实测值）；当 model_meta
    为空或带 mock 标记时，使用 MOCK_MODEL_META 演示评估路径。
    budget 可为 dict 或 Render Profile 字符串（PREVIEW/STANDARD/HIGH/FINAL）。
    """
    meta = dict(model_meta or {})
    if not meta or meta.get("mock") or "poly_count" not in meta:
        meta = dict(MOCK_MODEL_META)

    if isinstance(budget, str):
        profile = budget.upper()
        if profile not in DEFAULT_BUDGETS:
            profile = "STANDARD"
        limits = dict(DEFAULT_BUDGETS[profile])
    elif isinstance(budget, dict):
        limits = dict(budget)
    else:
        limits = dict(DEFAULT_BUDGETS["STANDARD"])
    limits.setdefault("max_poly_count", 300000)
    limits.setdefault("max_texture_mb", 256)
    limits.setdefault("max_memory_mb", 1024)
    limits.setdefault("max_frame_render_s", 0.10)
    limits.setdefault("fps", 30)

    fps = _fnum(limits.get("fps"), 30, lo=1)
    frame_budget_s = 1.0 / fps
    max_frame_s = _fnum(limits.get("max_frame_render_s"), frame_budget_s, lo=0.001)

    poly = _fnum(meta.get("poly_count"), 0)
    tex_bytes = _texture_bytes(meta)
    tex_mb = tex_bytes / (1024.0 * 1024.0)
    mem_bytes = poly * 64 + tex_bytes  # 粗估：每三角面 ~64B + 纹理
    mem_mb = mem_bytes / (1024.0 * 1024.0)
    frame_s = _fnum(meta.get("frame_render_s"), 0.0)
    missing = meta.get("missing_textures") or []
    shader = _to_text(meta.get("shader_compile") or "ok")
    clip = _to_text(meta.get("camera_clipping") or "ok")
    zfight = meta.get("z_fighting") in (True, "true", "yes")
    alias = meta.get("aliasing") in (True, "true", "yes")
    stability = _to_text(meta.get("frame_stability") or "stable")

    vals = {
        "polygon_count": (poly, limits["max_poly_count"]),
        "texture_size": (tex_mb, limits["max_texture_mb"]),
        "memory_estimate": (mem_mb, limits["max_memory_mb"]),
        "render_time_budget": (frame_s, max_frame_s),
    }

    checks = []
    for name, meta_key, label in _CHECK_RULES:
        if name in vals:
            v, cap = vals[name]
            ok = v <= cap
            checks.append({
                "check": name,
                "status": "pass" if ok else "fail",
                "detail": "%s: %.2f / limit %.2f (%s)" % (label, v, cap, "ok" if ok else "over"),
            })
        elif name == "missing_texture":
            ok = not missing
            checks.append({
                "check": name, "status": "pass" if ok else "fail",
                "detail": "%s: %s" % (label, "none" if ok else ", ".join(missing)),
            })
        elif name == "shader_errors":
            ok = shader.lower() in ("ok", "none", "")
            checks.append({
                "check": name, "status": "pass" if ok else "fail",
                "detail": "%s: %s" % (label, shader),
            })
        elif name == "camera_clipping":
            ok = clip.lower() in ("ok", "none", "clipped:none")
            checks.append({
                "check": name, "status": "pass" if ok else "fail",
                "detail": "%s: %s" % (label, clip),
            })
        elif name == "z_fighting":
            checks.append({
                "check": name, "status": "fail" if zfight else "pass",
                "detail": "%s: %s" % (label, "detected" if zfight else "none"),
            })
        elif name == "aliasing":
            checks.append({
                "check": name, "status": "warn" if alias else "pass",
                "detail": "%s: %s" % (label, "visible; enable MSAA/render at higher res" if alias else "none"),
            })
        elif name == "frame_stability":
            ok = stability.lower() in ("stable", "ok", "")
            checks.append({
                "check": name, "status": "pass" if ok else "warn",
                "detail": "%s: %s" % (label, stability),
            })

    ok = all(c["status"] != "fail" for c in checks)
    return ok, checks


# ---------------------------------------------------------------------------
# physics_conflict_check — organic/chaotic 模拟冲突（§35）
# ---------------------------------------------------------------------------


def physics_conflict_check(spec):
    """检测 organic/chaotic 模拟需求（布料/流体/头发/烟/刚体碰撞等）。

    程序化 3D 管线无法低成本可靠复现这类运动 → 返回 PRODUCTION_CONFLICT，
    建议转 GENERATIVE_VIDEO（或 HYBRID 分层），不偷偷改设计。
    返回 dict：status=PRODUCTION_CONFLICT | OK。
    """
    if not isinstance(spec, dict):
        return {"status": "OK", "problem": "no spec"}
    blob = " ".join([
        _to_text(spec.get("visual_requirements")),
        _to_text(spec.get("purpose")),
        _to_text((spec.get("animation") or {}).get("type")),
        _to_text(spec.get("notes")),
        _to_text(spec.get("material")),
    ]).lower()
    hits = [t for t in ORGANIC_SIM_TERMS if t in blob]
    if not hits:
        return {
            "status": "OK",
            "problem": "no organic/chaotic simulation requested; procedural 3D is appropriate",
            "hits": [],
        }
    return {
        "status": "PRODUCTION_CONFLICT",
        "request": {
            "request_id": _pick(spec, ["request_id"], ""),
            "shot_id": _pick(spec, ["shot_id"], ""),
            "layer_id": _pick(spec, ["layer_id"], ""),
        },
        "problem": "organic/chaotic simulation requested: %s" % ", ".join(hits[:5]),
        "technical_reason": ("cloth/fluid/hair/smoke/rigid-body simulation has high "
                             "compute cost and unstable results in a deterministic "
                             "frame-driven renderer; procedural 3D cannot reliably "
                             "reproduce it"),
        "visual_impact": "simulation-based motion would break determinism and raise render cost sharply",
        "alternatives": [
            {"route": "GENERATIVE_VIDEO",
             "note": "generate the organic/chaotic element as AI video footage and composite it"},
            {"route": "HYBRID",
             "note": "keep procedural 3D for the structured subject, generate the organic layer via AI video"},
        ],
        "approval_required": True,
        "hits": hits,
    }


# ---------------------------------------------------------------------------
# preview_plan — Preview First 计划（§39 / §89-91）
# ---------------------------------------------------------------------------


def preview_plan(spec):
    """为 3D shot 规划低清预览：still / turntable / low-res animation / camera test。

    Preview 与 final 文件分离（A###_preview.mp4 vs A###_v1.mov），
    复杂 motion / hero 3D / 昂贵 render 必须先 preview 确认。
    """
    spec = spec or {}
    camera = spec.get("camera") or {}
    movement = camera.get("movement", "static")
    anim = spec.get("animation") or {}
    has_path = bool(spec.get("camera_path"))
    has_anim = bool(anim.get("type")) and anim.get("type") not in (None, "none")
    duration = _fnum(spec.get("duration"), 5.0, lo=0.1)
    fps = int(_fnum(spec.get("fps"), 30, lo=1, hi=120))

    if has_path and has_anim:
        ptype = "low_res_animation"
        goal = "validate full camera path + animation choreography at low resolution"
    elif movement == "orbit":
        ptype = "turntable"
        goal = "validate the model, materials and lighting from all angles"
    elif movement not in ("static",) or has_path:
        ptype = "camera_test"
        goal = "validate camera framing, clipping and path before animation work"
    else:
        ptype = "still"
        goal = "lock look: model, material, lighting and framing in a single frame"

    return {
        "preview_type": ptype,
        "resolution": [1280, 720],
        "fps": min(fps, 30),
        "duration": round(min(duration, 3.0), 2),
        "goal": goal,
        "output": "A###_preview.mp4 (separate file; never overwrites A###_v1.mov)",
        "approval_required": True,
        "approval_reason": "preview must be confirmed before high-quality render (§89-91)",
        "viable_previews": ["still", "turntable", "low_res_animation", "camera_test"],
        "notes": "expensive/hero 3D renders always route through a preview first.",
    }


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------


def _selftest():
    spec = build_threed_spec(
        {"request_id": "PR-010", "shot_id": "S010", "layer_id": "S010-L01",
         "route": "THREE_D", "duration": 5.0, "fps": 30, "alpha_required": False,
         "visual_requirements": "3D product orbit reveal",
         "camera_requirements": "slow orbit"},
        {"visual_bible": "Minimal Spatial Tech"},
    )
    assert spec["camera"]["movement"] == "orbit", spec["camera"]
    assert spec["camera"]["duration"] == 5.0
    assert spec["camera"]["lens"] > 0
    assert spec["route"] == "THREE_D"
    assert spec["render_profile"] == "STANDARD"

    rec = recommend_texture_resolution(
        {"shot_size": "hero close-up", "output_resolution": "1920x1080"})
    assert rec["recommendation"] in ("2K", "4K", "8K"), rec
    assert rec["approval_required"] is True
    rec8 = recommend_texture_resolution(
        {"shot_size": "wide shot", "output_resolution": "1920x1080"})
    assert rec8["recommendation"] == "2K" and rec8["approval_required"] is False
    assert "8K is never" in rec8["rule_notes"]

    a = seeded_random(42, 5)
    b = seeded_random(42, 5)
    assert a == b
    assert len(a) == 5 and all(0.0 <= x < 1.0 for x in a)
    c = seeded_random(43, 5)
    assert a != c

    ok, notes = determinism_check({"random_positions": True, "seed": None})
    assert not ok and notes, notes
    ok2, notes2 = determinism_check({"random_positions": True, "seed": 42})
    assert ok2, notes2
    ok3, _ = determinism_check({"wall_clock": True})
    assert not ok3

    pp = postprocessing_plan({"style": "Minimal Spatial Tech"})
    assert pp["bloom"] is False and pp["enabled"] == []
    pp2 = postprocessing_plan({"style": "cinematic bloom dof vignette"})
    assert pp2["bloom"] and pp2["depth_of_field"] and pp2["vignette"]

    ok4, checks = performance_budget_check(MOCK_MODEL_META, "STANDARD")
    assert isinstance(ok4, bool) and len(checks) >= 10
    names = [c["check"] for c in checks]
    for req in ("polygon_count", "texture_size", "memory_estimate",
                "render_time_budget", "missing_texture", "shader_errors",
                "camera_clipping", "z_fighting", "aliasing", "frame_stability"):
        assert req in names, req
    ok5, checks5 = performance_budget_check(
        {"poly_count": 900000, "textures": [{"w": 8192, "h": 8192}],
         "missing_textures": ["base.png"], "shader_compile": "ERROR: x",
         "frame_render_s": 0.5},
        {"max_poly_count": 300000, "max_texture_mb": 256, "max_memory_mb": 1024,
         "max_frame_render_s": 0.1, "fps": 30})
    assert not ok5

    conflict = physics_conflict_check({"visual_requirements": "cloth simulation"})
    assert conflict["status"] == "PRODUCTION_CONFLICT"
    assert conflict["alternatives"][0]["route"] == "GENERATIVE_VIDEO"
    no_conflict = physics_conflict_check({"visual_requirements": "product orbit reveal"})
    assert no_conflict["status"] == "OK"

    ppv = preview_plan({"camera": {"movement": "orbit"}, "duration": 5.0, "fps": 30})
    assert ppv["preview_type"] == "turntable"
    assert ppv["approval_required"] is True

    print("3D selftest OK")
    return 0


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    if "--selftest" in argv:
        sys.exit(_selftest())
    print("usage: python3 modules/production/threed.py --selftest", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
