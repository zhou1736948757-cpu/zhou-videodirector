#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZHOU_Videodirector — Phase-3 Shot / Layer Router 核心引擎 (P3-1)

Architecture (§35): Hard Constraints -> Heuristics -> Candidate Generation
                     -> LLM Evaluation (hook) -> Confidence -> Prototype Decision

Python 3 stdlib only. No third-party imports. No real LLM calls.

Two entry points:
  1. CLI :  python3 modules/router/router.py <project_dir> [--json] [--selftest]
  2. API :  route_single(shot: dict, context: dict) -> dict   (benchmark hook)

Shared contract:
  Route enum:      REMOTION | THREE_D | REAL_FOOTAGE | GENERATIVE_VIDEO | JY_NATIVE | HYBRID
  12 factors:      structural_precision, photorealism, organic_motion, scene_entropy,
                   text_accuracy, data_accuracy, revision_requirement, timing_precision,
                   atmosphere_requirement, physical_complexity, camera_complexity,
                   editability_requirement            (0.0 - 1.0)
  Bake policy:     BAKE | KEEP_EDITABLE | ASSET_REPLACEABLE
  Route source:    AUTO | USER_OVERRIDE | DIRECTOR_OVERRIDE | PROTOTYPE_RESULT
  Confidence:      >=0.80 HIGH / 0.55-0.79 MEDIUM / <0.55 LOW
  Prototype:       STATIC_KEYFRAME | REMOTION_MICRO_PROTOTYPE | THREE_D_PREVIS |
                   AI_IMAGE_CONCEPT | AI_VIDEO_TEST | JY_TIMELINE_TEST
  Layer role (16): BACKGROUND FOREGROUND SUBJECT TYPOGRAPHY UI DATA 3D_OBJECT PARTICLE
                   DECORATION FOOTAGE IMAGE OVERLAY MASK LIGHTING ATMOSPHERE SUBTITLE
  Layer ID:        S###-L##
  Entropy:         LOW | MEDIUM | HIGH
  Only decision_summary is persisted (§38); private CoT is forbidden.
"""

import json
import os
import re
import sys
import tempfile

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FACTOR_KEYS = [
    "structural_precision", "photorealism", "organic_motion", "scene_entropy",
    "text_accuracy", "data_accuracy", "revision_requirement", "timing_precision",
    "atmosphere_requirement", "physical_complexity", "camera_complexity",
    "editability_requirement",
]

ROUTES = ["REMOTION", "THREE_D", "REAL_FOOTAGE", "GENERATIVE_VIDEO", "JY_NATIVE", "HYBRID"]

LAYER_ROLES = [
    "BACKGROUND", "FOREGROUND", "SUBJECT", "TYPOGRAPHY", "UI", "DATA",
    "3D_OBJECT", "PARTICLE", "DECORATION", "FOOTAGE", "IMAGE", "OVERLAY",
    "MASK", "LIGHTING", "ATMOSPHERE", "SUBTITLE",
]

ROLE_PRIORITY = [
    "BACKGROUND", "ATMOSPHERE", "FOREGROUND", "FOOTAGE", "IMAGE", "DECORATION",
    "PARTICLE", "SUBJECT", "DATA", "3D_OBJECT", "UI", "MASK", "OVERLAY",
    "TYPOGRAPHY", "SUBTITLE", "LIGHTING",
]

BASE_COST = {
    "REMOTION": "LOW", "THREE_D": "HIGH", "REAL_FOOTAGE": "MEDIUM",
    "GENERATIVE_VIDEO": "HIGH", "JY_NATIVE": "LOW", "HYBRID": "MEDIUM",
}

RATIONALE = {
    "REMOTION": "structured/text/data/timing-driven; programmatic control required",
    "THREE_D": "3D product / physical / camera complexity",
    "REAL_FOOTAGE": "photoreal organic content; real footage preferred",
    "GENERATIVE_VIDEO": "photoreal high-entropy content without a physical shoot",
    "JY_NATIVE": "simple content; timeline-native assembly",
    "HYBRID": "mixed needs; split into layers per producer",
}

# keyword signal tables ----------------------------------------------------
# P3-7: "table" removed — a desk/table scene must not raise structural_precision
# (a real product on a table is a footage/3D/AI shot, not a structured UI shot).
# "user interface" added; "ui" is matched word-boundary (\bui\b) via _hit_count.
STRUCTURAL_TERMS = [
    "dashboard", "ui", "interface", "user interface", "界面", "看板", "board",
    "card", "卡片", "grid", "栅格", "布局", "layout", "chart", "图表",
    "diagram", "表格", "栏", "alignment", "对齐", "panel", "面板", "timeline",
    "时间轴", "tabs", "tab", "按钮", "button", "form", "表单",
]
PHOTOREAL_TERMS = [
    "真人", "人脸", "face", "hair", "头发", "皮肤", "skin", "water", "水",
    "烟", "smoke", "crowd", "人群", "street", "街道", "city", "城市",
    "natural", "photo", "photograph", "照片", "photo-real", "photoreal",
    "实拍", "真实", "film", "footage", "实景", "outdoor", "户外", "sunset",
    "黄昏", "food", "食物", "landscape", "风景", "forest", "森林", "海边",
    "beach", "neon", "霓虹",
]
ORGANIC_TERMS = [
    "水", "烟", "smoke", "crowd", "人群", "hair", "头发", "cloth", "布料",
    "wave", "波浪", "fluid", "流体", "fire", "火焰", "风", "wind", "leaf",
    "树叶", "organic", "自然", "人体", "身体", "hair", "skin", "morph", "变形",
]
SCENE_ENTROPY_TERMS = [
    "street", "街道", "crowd", "人群", "busy", "复杂场景", "high-entropy",
    "entropy", "密集", "forest", "森林", "market", "市场", "爆炸", "explosion",
    "烟雾", "混乱", "chaotic", "cluttered", "杂物", "夜市", "night market",
]
TEXT_ACCURACY_TERMS = [
    "exact", "精确", "文案", "label", "labels", "角标", "标题", "title",
    "字幕", "subtitle", "on-screen", "screen text", "文字", "网址", "url",
    "keyword", "等宽数字", "slogan", "brand name", "品牌名",
]
DATA_ACCURACY_TERMS = [
    "数据", "data", "数字", "numbers", "chart", "图表", "dashboard", "statistics",
    "统计", "数值", "map", "地图", "timeline", "时间轴", "metric", "指标",
    "百分比", "%", "count", "计数", "score", "分数", "rate", "比率", "growth",
]
REVISION_TERMS = [
    "revision", "修改", "反复调整", "必替换", "容易变", "经常改", "需重做",
    "文案替换", "参数化", "parameterized", "会变", "可变",
]
TIMING_TERMS = [
    "timing", "时序", "同步", "sync", "同拍", "精确时间", "stagger", "spring",
    "逐字", "跳动", "tick", "节奏", "beat", "帧", "frame", "micro",
]
ATMOSPHERE_TERMS = [
    "氛围", "atmosphere", "情绪", "mood", "冷", "安静", "quiet", "呼吸",
    "呼吸感", "余韵", "高级", "克制", "温暖", "warm", "峰值", "hero",
    "留白", "沉稳", "premium", "质感",
]
PHYSICAL_TERMS = [
    "爆炸图", "exploded", "chip", "芯片", "机械", "mechanical", "物理",
    "physics", "碰撞", "collision", "布料模拟", "fluid sim", "刚体", "rigid",
    "gear", "齿轮", "crystal", "晶体", "procedural", "程序化", "mesh", "模型",
]
CAMERA_TERMS = [
    "orbit", "环绕", "复杂运镜", "一镜到底", "oner", "crane", "摇臂",
    "drone", "航拍", "follow", "跟拍", "spatial", "空间相机", "推拉摇移",
    "handheld", "手持", "zoom", "推", "whip", "甩镜",
]
THREE_D_TERMS = ["3d", "chip", "芯片", "exploded", "爆炸图", "mesh", "零件",
                 "product model", "产品模型", "部件"]
ABSTRACT_TERMS = ["抽象", "vague", "模糊不清"]

HINT_MAP = [
    ("structured motion graphic", ["REMOTION"]),
    ("remotion", ["REMOTION"]),
    ("jy_native", ["JY_NATIVE"]),
    ("2.5d", ["THREE_D"]),
    ("3d", ["THREE_D"]),
    ("three.js", ["THREE_D"]),
    ("three_d", ["THREE_D"]),
    ("footage", ["REAL_FOOTAGE"]),
    ("实拍", ["REAL_FOOTAGE"]),
    ("generative", ["GENERATIVE_VIDEO"]),
    ("ai video", ["GENERATIVE_VIDEO"]),
    ("hybrid", ["HYBRID"]),
    ("字幕", ["JY_NATIVE"]),
    ("简单淡入淡出", ["JY_NATIVE"]),
    ("简单剪辑", ["JY_NATIVE"]),
]

# ---------------------------------------------------------------------------
# P3-7 engine tuning constants (Phase-3 Prompt references in comments)
# ---------------------------------------------------------------------------

# Director "Likely: <route>" intent is a STRONG prior / tie-breaker, not a weak
# nudge (Phase-3 Prompt: Likely 意向应作为强 prior / tie-breaker). Raised from
# +0.12 (P3-6) to +0.30 so STORYBOARD intent can break score ties decisively,
# while hard constraints (§36) still outrank it (constraints zero scores after
# hints are added in generate_candidates).
LIKELY_HINT_BONUS = 0.30

# Frame-exact sync signals: 帧/frame/72/精确/beat 精确 (e.g. "第72帧数字出现").
# Only these push timing_precision to the HIGH band (>=0.8) that REMOTION needs;
# ordinary "beat 对齐 / music cue / 字幕出现" sync stays in the medium band.
_TIMING_STRONG_RE = re.compile(
    r"(?:帧|frame|精确|到帧|frame\s*-?\s*exact|第\s*\d+\s*帧|\b72\b)", re.I
)

# P3-7: photoreal content must be sourced/produced (REAL_FOOTAGE /
# GENERATIVE_VIDEO / THREE_D), it is never a from-scratch timeline assembly.
# Photorealism enters JY complexity as a first-class dimension (weight 0.25,
# on par with structural_precision). The decisive demotion for
# photoreal-but-asset-less shots (e.g. "a real product on a table") is applied
# in generate_candidates via JY_PHOTOREAL_PENALTY: photoreal >= 0.5 with NO
# existing-media evidence is not a timeline edit at all. Still-photo /
# archive / B-roll / footage / screenshot shots (existing media) keep the
# timeline-native path (benchmark ROUTE-075 fail_hint vs ROUTE-046/055).
JY_PHOTOREAL_WEIGHT = 0.25
JY_PHOTOREAL_PENALTY = 0.55
JY_PHOTOREAL_MIN = 0.5

# Existing-media evidence that keeps a photoreal shot timeline-native:
# a real photo / archive / B-roll / footage / screenshot asset to edit.
_PHOTO_ASSET_RE = re.compile(
    r"\bphotos?\b|photograph|照片|图片|archive|b-roll|b roll|素材|footage|"
    r"实拍|录屏|空镜|截图|still|剧照",
    re.I,
)

# LLM judgment hook: default None (pure heuristic). A skill/runtime can inject:
#   import router; router.llm_judgment = my_judge
# where my_judge(shot, factors, candidates, context) -> dict | None
# dict may contain {"route": X} and/or {"score_adjust": {route: delta}}.
llm_judgment = None

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, float(v)))


def _fmt_float(v):
    return "%.2f" % float(v)


def _to_text(v):
    """Flatten a value (str / dict / list / None) into a searchable string."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        parts = []
        for val in v.values():
            t = _to_text(val)
            if t:
                parts.append(t)
        return " ".join(parts)
    if isinstance(v, (list, tuple)):
        parts = [_to_text(x) for x in v]
        return " ".join(x for x in parts if x)
    return str(v)


def _shot_text(shot):
    """Concatenate every descriptive field of a shot for keyword scanning."""
    fields = [
        "visual_description", "camera", "motion", "narrative_purpose",
        "voiceover", "on_screen_text", "notes",
    ]
    parts = [_to_text(shot.get(k)) for k in fields]
    vd = shot.get("visual_direction") or {}
    parts.append(_to_text(vd.get("intent")))
    parts.append(_to_text(vd.get("reason")))
    return "\n".join(parts)


def _hit_count(text, terms):
    """Count keyword hits in `text`.

    P3-7: ASCII (English) keywords match on word boundaries (\b...\b) so
    substring false positives are avoided — "ui" inside "fluid"/"building",
    "tab" inside "editability", "board" inside "dashboard", "photo" inside
    "photoreal" no longer inflate a factor. CJK keywords (no word concept)
    keep plain substring matching.
    """
    n = 0
    for t in terms:
        if t.isascii() and re.search(r"\b" + re.escape(t) + r"\b", text, re.I):
            n += 1
        elif t in text:
            n += 1
    return n


def _is_abstract(shot):
    text = _shot_text(shot).lower()
    if "抽象" in text:
        return True
    if re.search(r"\babstract\b", text):
        return True
    if re.search(r"\bvague\b", text):
        return True
    return False


def _subtitle_present(shot):
    text = _shot_text(shot).lower()
    return ("subtitle" in text) or ("字幕" in text) or ("SUBTITLE" in text)


def _read_text(path, limit=None):
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = fh.read()
    except (OSError, UnicodeDecodeError):
        return ""
    if limit:
        data = data[:limit]
    return data


# ---------------------------------------------------------------------------
# 1. compute_factors — 12 项因子 (0.0-1.0)
# ---------------------------------------------------------------------------


def compute_factors(shot, context=None):
    """Derive the 12 routing factors from shot features (keyword heuristics +
    structural signals). Context may carry visual_bible_summary /
    audio_sync_requirements / budget_priority / production_mode etc."""
    context = context or {}
    text = _shot_text(shot)
    ltext = text.lower()
    ost = _to_text(shot.get("on_screen_text"))
    audio = shot.get("audio") if isinstance(shot.get("audio"), dict) else {}
    sync_points = audio.get("sync_points") or []
    vd = shot.get("visual_direction") or {}
    edit_tag = _to_text(vd.get("editability"))
    edit_high = (
        edit_tag.upper() == "HIGH"
        or "editability: high" in ltext
        or "editability:high" in ltext
    )

    f = {
        "structural_precision": 0.12 + 0.22 * _hit_count(ltext, STRUCTURAL_TERMS),
        "photorealism": 0.12 + 0.22 * _hit_count(ltext, PHOTOREAL_TERMS),
        "organic_motion": 0.12 + 0.22 * _hit_count(ltext, ORGANIC_TERMS),
        "scene_entropy": 0.12 + 0.22 * _hit_count(ltext, SCENE_ENTROPY_TERMS),
        "text_accuracy": 0.12 + 0.22 * _hit_count(ltext, TEXT_ACCURACY_TERMS),
        "data_accuracy": 0.12 + 0.22 * _hit_count(ltext, DATA_ACCURACY_TERMS),
        "revision_requirement": 0.12 + 0.22 * _hit_count(ltext, REVISION_TERMS),
        "timing_precision": 0.12 + 0.22 * _hit_count(ltext, TIMING_TERMS),
        "atmosphere_requirement": 0.12 + 0.22 * _hit_count(ltext, ATMOSPHERE_TERMS),
        "physical_complexity": 0.12 + 0.22 * _hit_count(ltext, PHYSICAL_TERMS),
        "camera_complexity": 0.12 + 0.22 * _hit_count(ltext, CAMERA_TERMS),
        "editability_requirement": 0.12 + 0.22 * _hit_count(ltext, REVISION_TERMS),
    }
    # structural / boolean signals
    if ost:
        f["text_accuracy"] += 0.25
    if ost and re.search(r"\d", ost):
        f["data_accuracy"] += 0.2
    # P3-7: sync granularity split. sync_points full of beat/event-level marks
    # (字幕出现 / 卡片消失 / music cue) is timeline-native (JY can snap to
    # beats) -> cap at MEDIUM. Only frame-exact signals (帧/frame/72/精确)
    # raise timing_precision to the HIGH band REMOTION actually needs.
    if sync_points:
        sync_text = " ".join(_to_text(sp) for sp in sync_points).lower()
        if _TIMING_STRONG_RE.search(sync_text) or _TIMING_STRONG_RE.search(ltext):
            f["timing_precision"] = max(f["timing_precision"], 0.85)
        else:
            f["timing_precision"] = max(f["timing_precision"], 0.55)
    if audio.get("sfx"):
        f["timing_precision"] += 0.15
    if edit_high:
        f["editability_requirement"] += 0.55
        f["revision_requirement"] += 0.3
    # visual bible hints (style-level)
    vb = _to_text(context.get("visual_bible_summary")).lower()
    if vb and ("photoreal" in vb or "写实" in vb):
        f["photorealism"] += 0.05
    if vb and ("generative" in vb or "不用 ai" not in vb):
        pass
    # policy hints from context
    if context.get("ai_video_policy") is False or _ctx_policy(context, "ai_video_policy") is False:
        f["photorealism"] = max(f["photorealism"], 0.2)
    return {k: _clamp(v) for k, v in f.items()}


def _ctx_policy(context, key):
    """Read a policy flag from context; default True when absent."""
    v = context.get(key)
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("false", "no", "0", "off", "禁止", "否")


def _policies(context):
    return {
        "ai_video_policy": _ctx_policy(context, "ai_video_policy"),
        "real_footage_policy": _ctx_policy(context, "real_footage_policy"),
        "three_d_policy": _ctx_policy(context, "three_d_policy"),
        "has_footage": bool(context.get("available_assets")),
    }


# ---------------------------------------------------------------------------
# 2. hard_constraints (§36)
# ---------------------------------------------------------------------------


def hard_constraints(factors, shot):
    """Return a list of active hard-constraint strings (§36)."""
    cons = []
    ost = _to_text(shot.get("on_screen_text"))
    if ost and factors["text_accuracy"] >= 0.4:
        cons.append(
            "exact text present: GENERATIVE_VIDEO must not be the sole producer of "
            "the text layer (use HYBRID with a REMOTION/JY_NATIVE text layer)"
        )
    if factors["data_accuracy"] >= 0.6:
        cons.append(
            "critical data present: generative video cannot act as the data producer "
            "(data must be produced by a structured producer)"
        )
    if _subtitle_present(shot):
        cons.append("subtitle present: text layer must be KEEP_EDITABLE")
    return cons


# ---------------------------------------------------------------------------
# 3. Candidate scoring + generation (§37)
# ---------------------------------------------------------------------------


def _score_remotion(f):
    # P3-7: timing_precision only drives REMOTION at the frame-exact HIGH band
    # (>=0.8). Beat-level alignment (medium 0.4-0.7) is achievable in a native
    # editor timeline, so its pull on REMOTION is capped to avoid the whole
    # explainer saturating to REMOTION just because every shot snaps to a beat.
    tp = f["timing_precision"]
    tp_eff = tp if tp >= 0.8 else min(tp, 0.35)
    return _clamp(
        0.22 * f["structural_precision"]
        + 0.18 * f["text_accuracy"]
        + 0.18 * f["data_accuracy"]
        + 0.30 * tp_eff
        + 0.12 * f["editability_requirement"]
    )


def _score_three_d(f):
    return _clamp(
        0.40 * f["physical_complexity"]
        + 0.25 * f["camera_complexity"]
        + 0.15 * f["structural_precision"]
        + 0.10 * f["photorealism"]
    )


def _score_real_footage(f):
    return _clamp(
        0.35 * f["photorealism"]
        + 0.30 * f["organic_motion"]
        + 0.25 * f["scene_entropy"]
        + 0.10 * f["atmosphere_requirement"]
    )


def _score_generative(f):
    return _clamp(
        0.30 * f["photorealism"]
        + 0.30 * f["organic_motion"]
        + 0.30 * f["scene_entropy"]
        + 0.10 * f["atmosphere_requirement"]
    )


def _score_jy(f):
    # P3-7: photorealism is now a first-class complexity dimension — photoreal
    # content (real product / real scene / photoreal look) must be sourced or
    # produced by FOOTAGE/GENERATIVE/THREE_D, not assembled from scratch in a
    # timeline editor. See JY_PHOTOREAL_WEIGHT (benchmark ROUTE-075 fail_hint).
    complexity = (
        0.25 * f["structural_precision"]
        + 0.20 * f["text_accuracy"]
        + 0.15 * f["data_accuracy"]
        + 0.28 * f["timing_precision"]
        + 0.20 * f["organic_motion"]
        + 0.20 * f["scene_entropy"]
        + 0.15 * f["camera_complexity"]
        + 0.20 * f["physical_complexity"]
        + JY_PHOTOREAL_WEIGHT * f["photorealism"]
    )
    return _clamp(1.0 - complexity)


def _score_hybrid(f):
    text_dim = max(f["structural_precision"], f["text_accuracy"], f["data_accuracy"])
    photoreal_dim = max(f["photorealism"], f["organic_motion"], f["scene_entropy"])
    if text_dim < 0.45 or photoreal_dim < 0.45:
        return 0.0
    return _clamp(0.5 * (text_dim + photoreal_dim) + 0.15 * f["editability_requirement"])


def _cost(route, f):
    c = BASE_COST[route]
    if route == "REMOTION" and f["timing_precision"] >= 0.7:
        c = "MEDIUM"
    if route == "REAL_FOOTAGE" and f["scene_entropy"] >= 0.7:
        c = "HIGH"
    if route == "JY_NATIVE" and f["timing_precision"] >= 0.6:
        c = "MEDIUM"
    if route == "HYBRID":
        c = "HIGH"
    return c


def _likely_hints(shot, storyboard_text=""):
    """Parse 'Likely: <route intent>' annotations (Phase-2 notes / STORYBOARD.md)
    into route score bonuses. Since P3-7 raised the bonus to a strong prior
    (LIKELY_HINT_BONUS), the STORYBOARD scan is scoped to the shot's own
    '### <shot_id>' section so a stronger hint cannot leak from neighbouring
    shots (the old fixed 900-char window could pull in other shots' 'Likely:'
    annotations from the overview table). Hard constraints still outrank hints
    (they zero scores after hints are applied)."""
    hints = {}
    snippets = [
        shot.get("notes", "")
        + " "
        + _to_text((shot.get("visual_direction") or {}).get("intent")),
    ]
    sid = shot.get("id", "")
    if storyboard_text and sid:
        m = re.search(
            r"^#{2,4}\s*%s\b" % re.escape(sid), storyboard_text, re.M
        )
        if m:
            rest = storyboard_text[m.end():]
            bound = re.search(r"\n#{2,4}\s+", rest)
            section = rest if not bound else rest[: bound.start()]
            snippets.append(section)
    for snip in snippets:
        for m in re.finditer(r"Likely\s*[:：]\s*([^\n;]+)", snip):
            phrase = m.group(1).lower()
            for key, routes in HINT_MAP:
                if key in phrase:
                    for r in routes:
                        hints[r] = hints.get(r, 0.0) + LIKELY_HINT_BONUS
    return hints


def generate_candidates(shot, factors, context=None):
    """Build 1-3 route candidates (score-ordered) honoring policies and hard
    constraints."""
    context = context or {}
    hints = _likely_hints(shot, context.get("storyboard_text", ""))
    pol = _policies(context)
    text = _shot_text(shot).lower()
    ltext = _shot_text(shot).lower()

    def s(fn, route):
        return _clamp(fn(factors) + hints.get(route, 0.0))

    scores = {
        "REMOTION": s(_score_remotion, "REMOTION"),
        "THREE_D": s(_score_three_d, "THREE_D"),
        "REAL_FOOTAGE": s(_score_real_footage, "REAL_FOOTAGE"),
        "GENERATIVE_VIDEO": s(_score_generative, "GENERATIVE_VIDEO"),
        "JY_NATIVE": s(_score_jy, "JY_NATIVE"),
        "HYBRID": s(_score_hybrid, "HYBRID"),
    }
    # 3D signal bonus + JY penalty (a 3D product shot is not a simple editor edit)
    if any(t in text for t in THREE_D_TERMS):
        scores["THREE_D"] = _clamp(scores["THREE_D"] + 0.2)
        scores["JY_NATIVE"] = _clamp(scores["JY_NATIVE"] - 0.25)
    # P3-7: photoreal production need — a photoreal shot WITHOUT existing media
    # assets (no photo/archive/B-roll/footage/screenshot to edit) cannot be
    # assembled from scratch in a timeline editor; it must be sourced or
    # produced (REAL_FOOTAGE/GENERATIVE_VIDEO/THREE_D). Still-photo/asset shots
    # are exempt and stay timeline-native (benchmark ROUTE-075 vs ROUTE-046).
    if factors["photorealism"] >= JY_PHOTOREAL_MIN and not _PHOTO_ASSET_RE.search(text):
        scores["JY_NATIVE"] = _clamp(scores["JY_NATIVE"] - JY_PHOTOREAL_PENALTY)
    # footage preference (§19: existing assets -> prefer FOOTAGE)
    if pol["has_footage"] and factors["photorealism"] >= 0.5:
        scores["REAL_FOOTAGE"] = _clamp(scores["REAL_FOOTAGE"] + 0.15)
    # hard constraints (§36)
    constraints = hard_constraints(factors, shot)
    for c in constraints:
        if c.startswith("exact text") or c.startswith("critical data"):
            scores["GENERATIVE_VIDEO"] = 0.0
    # policies
    if not pol["ai_video_policy"]:
        scores["GENERATIVE_VIDEO"] = 0.0
    if not pol["real_footage_policy"]:
        scores["REAL_FOOTAGE"] = 0.0
    if not pol["three_d_policy"]:
        scores["THREE_D"] = 0.0

    cands = sorted(
        (
            {
                "route": r,
                "score": sc,
                "rationale": RATIONALE[r],
                "cost": _cost(r, factors),
            }
            for r, sc in scores.items()
            if sc > 0.12
        ),
        key=lambda c: c["score"],
        reverse=True,
    )
    if not cands:
        cands = [
            {
                "route": "JY_NATIVE",
                "score": 0.3,
                "rationale": "fallback to the simplest route",
                "cost": "LOW",
            }
        ]
    return cands[:3]


# ---------------------------------------------------------------------------
# 4. evaluate_candidates + llm_judgment hook (§34)
# ---------------------------------------------------------------------------


def evaluate_candidates(candidates, factors, context=None, shot=None):
    """Rank candidates. A callable llm_judgment hook may adjust scores; the
    default implementation returns None and ranking stays purely heuristic."""
    context = context or {}
    hook = context.get("llm_judgment") or llm_judgment
    if callable(hook):
        verdict = hook(shot, factors, candidates, context)
        if isinstance(verdict, dict):
            cand_map = {c["route"]: c for c in candidates}
            target = verdict.get("route")
            if target:
                if target in cand_map:
                    cand_map[target]["score"] += 0.6
                else:
                    candidates.append(
                        {
                            "route": target,
                            "score": 1.0,
                            "rationale": verdict.get("rationale", "LLM judgment"),
                            "cost": verdict.get("cost", "MEDIUM"),
                        }
                    )
            adjust = verdict.get("score_adjust") or {}
            for route, delta in adjust.items():
                if route in cand_map:
                    cand_map[route]["score"] = _clamp(cand_map[route]["score"] + delta)
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# 5. confidence (§39)
# ---------------------------------------------------------------------------


def confidence(ranked, factors, context=None, constraints=None, shot=None):
    constraints = list(constraints or [])
    if not ranked:
        return 0.0
    scores = [c["score"] for c in ranked]
    top = _clamp(scores[0])
    second = scores[1] if len(scores) > 1 else None
    diff = 0.5 if second is None else _clamp(top - second)
    conflicts = 0
    if factors["text_accuracy"] >= 0.5 and factors["scene_entropy"] >= 0.5:
        conflicts += 1
    if factors["data_accuracy"] >= 0.5 and factors["organic_motion"] >= 0.5:
        conflicts += 1
    if factors["editability_requirement"] >= 0.5 and factors["scene_entropy"] >= 0.5:
        conflicts += 1
    if factors["timing_precision"] >= 0.5 and factors["organic_motion"] >= 0.5:
        conflicts += 1
    conf = (
        0.40 + 0.25 * top + 0.50 * diff
        - 0.05 * conflicts
        - 0.05 * len(constraints)
    )
    if shot is not None and _is_abstract(shot):
        conf -= 0.45
    return _clamp(conf)


def confidence_level(c):
    if c >= 0.80:
        return "HIGH"
    if c >= 0.55:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# 6. prototype_decision (§40-43)
# ---------------------------------------------------------------------------

PROTOTYPE_MAP = {
    "THREE_D": ("THREE_D_PREVIS", "Validate 3D model / camera / lighting in a low-cost previs before full production."),
    "GENERATIVE_VIDEO": ("AI_IMAGE_CONCEPT", "Produce AI image concept frames to lock look and style before committing to video generation."),
    "REMOTION": ("REMOTION_MICRO_PROTOTYPE", "Build a micro Remotion prototype to validate timing and choreography of the key motion."),
    "JY_NATIVE": ("JY_TIMELINE_TEST", "Assemble a quick JIANYING timeline test to validate the simple cut/zoom rhythm."),
    "REAL_FOOTAGE": ("STATIC_KEYFRAME", "Collect reference keyframes/plates to confirm footage direction before sourcing."),
    "HYBRID": ("STATIC_KEYFRAME", "Build a static keyframe comp combining all layer roles to validate the hybrid split."),
}


def prototype_decision(route, conf, factors):
    if conf >= 0.80:
        return {"prototype_required": False, "prototype_type": None, "prototype_goal": None}
    if conf >= 0.55:
        ptype, pgoal = PROTOTYPE_MAP.get(
            route, ("STATIC_KEYFRAME", "Validate direction with keyframes.")
        )
        return {"prototype_required": True, "prototype_type": ptype, "prototype_goal": pgoal}
    return {
        "prototype_required": True,
        "prototype_type": "STATIC_KEYFRAME",
        "prototype_goal": "Concept Exploration Required: collect references / keyframes / compare two production routes",
    }


# ---------------------------------------------------------------------------
# 7. decide_bake (§29-30 + §57)
# ---------------------------------------------------------------------------


def decide_bake(layer_role, route, shot):
    """Decide a layer's bake policy from its role, route and shot context."""
    cg = _to_text(shot.get("continuity_group"))
    if cg and layer_role in ("SUBJECT", "BACKGROUND", "FOREGROUND"):
        return "BAKE"
    if layer_role in ("SUBTITLE", "TYPOGRAPHY", "UI"):
        return "KEEP_EDITABLE"
    if layer_role in ("IMAGE", "FOOTAGE", "DECORATION"):
        return "KEEP_EDITABLE"
    if route == "REMOTION":
        return "ASSET_REPLACEABLE"
    if route in ("GENERATIVE_VIDEO", "THREE_D"):
        return "ASSET_REPLACEABLE"
    return "KEEP_EDITABLE"


# ---------------------------------------------------------------------------
# 8. decompose_layers (§22-28, §54) — HYBRID / multi-producer only
# ---------------------------------------------------------------------------

_ROLE_MAP = {
    "BG": "BACKGROUND", "BACKGROUND": "BACKGROUND",
    "CONCEPT": "SUBJECT", "SUBJECT": "SUBJECT",
    "TYPO": "TYPOGRAPHY", "TYPOGRAPHY": "TYPOGRAPHY",
    "ATMO": "ATMOSPHERE", "ATMOSPHERE": "ATMOSPHERE",
    "UI": "UI", "DATA": "DATA",
    "3D": "3D_OBJECT", "3D_OBJECT": "3D_OBJECT",
    "SUBTITLE": "SUBTITLE", "SUBTITLE_": "SUBTITLE",
    "FOREGROUND": "FOREGROUND", "FOOTAGE": "FOOTAGE",
    "PARTICLE": "PARTICLE", "OVERLAY": "OVERLAY", "MASK": "MASK",
    "LIGHTING": "LIGHTING", "DECORATION": "DECORATION", "IMAGE": "IMAGE",
}

_INTENT_RE = re.compile(
    r"(?:^|[;\n]\s*)("
    r"BG|BACKGROUND|CONCEPT|SUBJECT|TYPO|TYPOGRAPHY|ATMO|ATMOSPHERE|UI|DATA|"
    r"3D|3D_OBJECT|SUBTITLE|FOREGROUND|FOOTAGE|PARTICLE|OVERLAY|MASK|LIGHTING|"
    r"DECORATION|IMAGE)\s*:\s*([^;\n]+)"
)


def _parse_layer_intent(shot):
    """Parse 'Layer Intent: BG: ...; CONCEPT: ...; TYPO: ...' annotations."""
    vd = shot.get("visual_direction") or {}
    blob = (
        _to_text(shot.get("notes"))
        + "\n"
        + _to_text(vd.get("intent"))
        + "\n"
        + _to_text(vd.get("visual_description"))
    )
    found = []
    for m in _INTENT_RE.finditer(blob):
        role = _ROLE_MAP.get(m.group(1).upper(), None)
        if role is None or role == "ATMOSPHERE" or role == "ATMO":
            pass
        if role is None:
            continue
        found.append((role, m.group(2).strip()))
    return found


def _layer_route(role, shot_route, factors, context):
    context = context or {}
    if role in ("TYPOGRAPHY", "UI", "SUBTITLE", "DATA", "MASK", "OVERLAY"):
        return "REMOTION"
    if role == "3D_OBJECT":
        return "THREE_D"
    if role == "FOOTAGE":
        return "REAL_FOOTAGE"
    if role in ("BACKGROUND", "ATMOSPHERE", "FOREGROUND"):
        if factors["photorealism"] >= 0.5 or factors["scene_entropy"] >= 0.5:
            if context.get("available_assets") and factors["photorealism"] >= 0.5:
                return "REAL_FOOTAGE"
            return "GENERATIVE_VIDEO"
        return "REMOTION"
    # SUBJECT
    if factors["physical_complexity"] >= 0.5 and factors["camera_complexity"] >= 0.4:
        return "THREE_D"
    if factors["organic_motion"] >= 0.5 or factors["photorealism"] >= 0.5:
        if context.get("available_assets"):
            return "REAL_FOOTAGE"
        return "GENERATIVE_VIDEO"
    if factors["scene_entropy"] >= 0.5:
        return "GENERATIVE_VIDEO"
    return "REMOTION"


def decompose_layers(shot, factors, route, context=None):
    """Return layer list (id/role/route/bake_policy/z_order/notes). Only for
    HYBRID or genuinely multi-producer shots. Avoids over-decomposition (§27)."""
    context = context or {}
    intent = _parse_layer_intent(shot)
    roles_with_desc = list(intent)

    need = route == "HYBRID"
    if not need:
        present = {r for r, _ in roles_with_desc}
        if route in ("REAL_FOOTAGE", "GENERATIVE_VIDEO") and present & {
            "TYPOGRAPHY", "UI", "SUBTITLE", "DATA",
        }:
            need = True
        elif route == "REMOTION" and present & {"FOOTAGE", "IMAGE"}:
            need = True
    if not need:
        return []

    if not roles_with_desc:
        roles_with_desc = [("BACKGROUND", "base background layer")]
        if factors["text_accuracy"] >= 0.5 or factors["data_accuracy"] >= 0.5:
            roles_with_desc.append(("TYPOGRAPHY", "exact text/data overlay layer"))
        roles_with_desc.append(("SUBJECT", "primary subject layer"))
        if factors["atmosphere_requirement"] >= 0.5:
            roles_with_desc.append(("ATMOSPHERE", "atmosphere layer"))

    # de-dup + cap to avoid over-decomposition
    seen = set()
    final = []
    for role, desc in roles_with_desc:
        if role in seen:
            continue
        seen.add(role)
        final.append((role, desc))
    final = final[:5]
    final.sort(key=lambda r: ROLE_PRIORITY.index(r[0]))

    sid = shot.get("id", "S000")
    layers = []
    for i, (role, desc) in enumerate(final, start=1):
        lroute = _layer_route(role, route, factors, context)
        bake = decide_bake(role, lroute, shot)
        layers.append(
            {
                "id": "%s-L%02d" % (sid, i),
                "role": role,
                "route": lroute,
                "bake_policy": bake,
                "z_order": i,
                "notes": desc[:120],
            }
        )
    return layers


# ---------------------------------------------------------------------------
# 9. escalate / deescalate (§65-66)
# ---------------------------------------------------------------------------


def escalate(route, factors, shot=None):
    """JY_NATIVE + complex motion/spatial camera -> REMOTION."""
    if route != "JY_NATIVE":
        return route, None
    if factors["camera_complexity"] >= 0.6:
        return "REMOTION", "escalated from JY_NATIVE: complex spatial camera requires procedural control"
    if shot is not None:
        text = _shot_text(shot).lower()
        if ("morph" in text or "变形" in text or "procedural graph" in text) and (
            factors["timing_precision"] >= 0.4 or factors["organic_motion"] >= 0.5
        ):
            return "REMOTION", "escalated from JY_NATIVE: complex morph/procedural motion requires procedural control"
    return route, None


def deescalate(route, factors, shot=None):
    """REMOTION + simple photo slow zoom -> JY_NATIVE."""
    if route != "REMOTION":
        return route, None
    simple = all(
        factors[k] < 0.4
        for k in ("structural_precision", "text_accuracy", "data_accuracy", "timing_precision")
    )
    if shot is not None and simple:
        text = _shot_text(shot).lower()
        has_photo = any(t in text for t in ("photo", "photograph", "照片", "图片"))
        has_zoom = ("zoom" in text) or ("推" in text) or ("慢推" in text)
        if has_photo and has_zoom:
            return "JY_NATIVE", "de-escalated from REMOTION: simple photo slow zoom fits a timeline-native edit"
    return route, None


# ---------------------------------------------------------------------------
# 10. override (§71-73)
# ---------------------------------------------------------------------------


def apply_override(decision, override):
    """Apply a user/director route override. Override keys: route, source,
    note. Sets confidence to 1.0 (a human decided) and records supersedes."""
    if not override:
        return decision
    old = decision.get("route")
    new = override.get("route")
    decision["supersedes"] = old if old and old != new else None
    decision["route"] = new
    decision["route_source"] = override.get("source", "USER_OVERRIDE")
    decision["confidence"] = 1.0
    note = _to_text(override.get("note")) or "User/director decision overrides engine recommendation."
    decision["decision_summary"] = "User override: %s" % note[:240]
    if decision.get("layer_decomposition_required"):
        # re-bake layers with the overridden route
        for layer in decision.get("layers", []):
            if layer["route"] in ("GENERATIVE_VIDEO", "THREE_D") and new in (
                "REMOTION", "JY_NATIVE",
            ):
                layer["route"] = new
                layer["bake_policy"] = "KEEP_EDITABLE"
    return decision


def _derive_assembly(route, factors, shot):
    """§55 Assembly Route: where final timeline assembly happens."""
    if route == "REMOTION":
        text = _shot_text(shot).lower()
        if "footage" in text or "素材" in text or "照片" in text:
            return "JIANYING"
        return "REMOTION"
    return "JIANYING"


def _build_reason(route, factors):
    if factors["scene_entropy"] >= 0.5 or factors["photorealism"] >= 0.7:
        production = "High-entropy environment is expensive to reproduce procedurally."
    elif factors["organic_motion"] >= 0.6:
        production = "Organic motion is hard to control procedurally; needs real or generated capture."
    elif factors["physical_complexity"] >= 0.6:
        production = "Physical/model complexity benefits from a dedicated 3D pipeline."
    elif factors["structural_precision"] >= 0.6:
        production = "Highly structured layout demands programmatic precision."
    else:
        production = "Low production complexity; choose the cheapest reliable route."
    if factors["text_accuracy"] >= 0.5:
        accuracy = "Exact text/labels must remain accurate."
    elif factors["data_accuracy"] >= 0.5:
        accuracy = "Data values must remain exact."
    else:
        accuracy = "No strict accuracy constraint beyond reference fidelity."
    if factors["editability_requirement"] >= 0.5:
        editability = "Content is expected to change; keep it parameterized/editable."
    else:
        editability = "No strong editability requirement; bake acceptable."
    return {"production": production, "accuracy": accuracy, "editability": editability}


def _build_summary(route, factors, constraints, notes):
    parts = []
    if route == "REMOTION":
        parts.append(
            "Highly structured shot with exact text/timing needs; produce programmatically "
            "in Remotion so layout, text and data stay precise and editable."
        )
    elif route == "THREE_D":
        parts.append(
            "Shot centers on a 3D object with physical/camera complexity; produce via the "
            "3D pipeline and replace the render as an asset."
        )
    elif route == "REAL_FOOTAGE":
        parts.append("Shot needs photoreal organic content best captured or sourced as real footage.")
    elif route == "GENERATIVE_VIDEO":
        parts.append(
            "Shot needs photoreal/high-entropy organic content without a physical shoot; "
            "generate it with AI video."
        )
    elif route == "JY_NATIVE":
        parts.append(
            "Shot is simple (photo/zoom/subtitle/B-roll); assemble natively in the editor timeline."
        )
    elif route == "HYBRID":
        parts.append(
            "Shot mixes photoreal content with exact overlay text/data; split into layers - "
            "environment produced separately, structured UI/text layered in Remotion, then assembled."
        )
    cs = " | ".join(constraints)
    if "critical data" in cs:
        parts.append("Critical data must be produced by a structured producer.")
    for n in notes:
        if n:
            parts.append(n)
    return " ".join(parts)[:300]


# ---------------------------------------------------------------------------
# 11. route_single — API entry (§: benchmark hook)
# ---------------------------------------------------------------------------


def route_single(shot, context=None):
    """Run the full pipeline for one shot and return the decision dict."""
    context = context or {}
    factors = compute_factors(shot, context)
    constraints = hard_constraints(factors, shot)
    candidates = generate_candidates(shot, factors, context)
    ranked = evaluate_candidates(candidates, factors, context, shot)
    top = ranked[0]
    route = top["route"]
    notes = []
    new_route, note = escalate(route, factors, shot)
    if new_route != route:
        route, note2 = new_route, note
        notes.append(note2)
    new_route, note = deescalate(route, factors, shot)
    if new_route != route:
        route = new_route
        notes.append(note)
    conf = confidence(ranked, factors, context, constraints, shot)
    proto = prototype_decision(route, conf, factors)
    layers = decompose_layers(shot, factors, route, context)

    decision = {
        "shot_id": shot.get("id", ""),
        "route": route,
        "confidence": round(conf, 3),
        "route_source": "AUTO",
        "reason": _build_reason(route, factors),
        "decision_summary": _build_summary(route, factors, constraints, notes),
        "scores": {k: round(factors[k], 3) for k in FACTOR_KEYS},
        "layer_decomposition_required": bool(layers),
        "prototype_required": proto["prototype_required"],
        "prototype_type": proto["prototype_type"],
        "prototype_goal": proto["prototype_goal"],
        "continuity_group": _to_text(shot.get("continuity_group")) or None,
        "assembly_backend": _derive_assembly(route, factors, shot),
        "supersedes": None,
        "constraints": constraints,
        "candidate_routes": [c["route"] for c in ranked],
        "confidence_level": confidence_level(conf),
        "layers": layers,
    }
    override = context.get("override")
    if override:
        decision = apply_override(decision, override)
    return decision


# ---------------------------------------------------------------------------
# 12. Minimal YAML emitter (stdlib only)
# ---------------------------------------------------------------------------


def _yaml_scalar(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _fmt_float(v)
    s = str(v).replace("\n", " ")
    if s == "":
        return "''"
    needs_quote = (
        s != s.strip()
        or s[0] in "-?:,[]{}#&*!|>'\"%@`"
        or ": " in s
        or s.endswith(":")
        or " #" in s
        or s.lower() in ("null", "true", "false", "yes", "no", "on", "off")
    )
    if needs_quote:
        return "'" + s.replace("'", "''") + "'"
    return s


def _yaml_emit(obj, indent=0):
    pad = "  " * indent
    lines = []
    for k, v in obj.items():
        if isinstance(v, dict):
            lines.append("%s%s:" % (pad, k))
            lines.extend(_yaml_emit(v, indent + 1))
        elif isinstance(v, list):
            lines.append("%s%s:" % (pad, k))
            if not v:
                lines.append("%s  []" % pad)
            for item in v:
                if isinstance(item, dict):
                    first = True
                    for ik, iv in item.items():
                        prefix = "- " if first else "  "
                        if isinstance(iv, (dict, list)):
                            lines.append("%s%s%s:" % (pad, prefix, ik))
                            if isinstance(iv, dict):
                                lines.extend(_yaml_emit(iv, indent + 1))
                            elif iv:
                                for sub in iv:
                                    lines.append("%s  - %s" % (pad, _yaml_scalar(sub)))
                            else:
                                lines.append("%s  []" % pad)
                        else:
                            lines.append("%s%s%s: %s" % (pad, prefix, ik, _yaml_scalar(iv)))
                        first = False
                else:
                    lines.append("%s- %s" % (pad, _yaml_scalar(item)))
        else:
            lines.append("%s%s: %s" % (pad, k, _yaml_scalar(v)))
    return lines


def _scores_flow(scores):
    inner = ", ".join("%s: %s" % (k, _fmt_float(v)) for k, v in scores.items())
    return "{%s}" % inner


def to_routing_yaml(decision):
    """§53 routing/S###.yaml content."""
    scores = decision["scores"]
    lines = []
    lines.append("shot_id: %s" % _yaml_scalar(decision["shot_id"]))
    lines.append("route: %s" % _yaml_scalar(decision["route"]))
    lines.append("confidence: %s" % _fmt_float(decision["confidence"]))
    lines.append("route_source: %s" % _yaml_scalar(decision["route_source"]))
    lines.append("reason:")
    for k, v in decision["reason"].items():
        lines.append("  %s: %s" % (k, _yaml_scalar(v)))
    lines.append("decision_summary: %s" % _yaml_scalar(decision["decision_summary"]))
    lines.append("scores: %s" % _scores_flow(scores))
    lines.append("layer_decomposition_required: %s" % ("true" if decision["layer_decomposition_required"] else "false"))
    lines.append("prototype_required: %s" % ("true" if decision["prototype_required"] else "false"))
    lines.append("prototype_type: %s" % _yaml_scalar(decision["prototype_type"]))
    lines.append("prototype_goal: %s" % _yaml_scalar(decision["prototype_goal"]))
    lines.append("continuity_group: %s" % _yaml_scalar(decision["continuity_group"]))
    lines.append("assembly_backend: %s" % _yaml_scalar(decision["assembly_backend"]))
    lines.append("supersedes: %s" % _yaml_scalar(decision["supersedes"]))
    if decision.get("constraints"):
        lines.append("constraints:")
        for c in decision["constraints"]:
            lines.append("  - %s" % _yaml_scalar(c))
    return "\n".join(lines) + "\n"


def to_layers_yaml(decision):
    """§54 layers/S###.yaml content."""
    lines = ["shot_id: %s" % _yaml_scalar(decision["shot_id"]), "layers:"]
    for layer in decision.get("layers", []):
        lines.append("  - id: %s" % _yaml_scalar(layer["id"]))
        lines.append("    role: %s" % _yaml_scalar(layer["role"]))
        lines.append("    route: %s" % _yaml_scalar(layer["route"]))
        lines.append("    bake_policy: %s" % _yaml_scalar(layer["bake_policy"]))
        lines.append("    z_order: %d" % int(layer["z_order"]))
        lines.append("    notes: %s" % _yaml_scalar(layer.get("notes", "")))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 13. Project context loading (CLI)
# ---------------------------------------------------------------------------


def _extract_policies(brief):
    pol = {}
    m = re.search(r"AI Video Policy:\s*(\w+)", brief)
    if m:
        pol["ai_video_policy"] = m.group(1).lower() not in ("false", "no")
    m = re.search(r"Real Footage Policy:\s*(\w+)", brief)
    if m:
        pol["real_footage_policy"] = m.group(1).lower() not in ("false", "no")
    m = re.search(r"3D Policy:\s*(\w+)", brief)
    if m:
        pol["three_d_policy"] = m.group(1).lower() not in ("false", "no")
    return pol


def build_context(project_dir):
    ctx = {}
    brief = _read_text(os.path.join(project_dir, "PROJECT_BRIEF.md"))
    state = _read_text(os.path.join(project_dir, "PROJECT_STATE.md"))
    proj_json = os.path.join(project_dir, "project.json")
    if os.path.isfile(proj_json):
        try:
            proj = json.load(open(proj_json, "r", encoding="utf-8"))
            if proj.get("production_mode"):
                ctx["production_mode"] = proj["production_mode"]
        except (OSError, ValueError):
            pass
    if "production_mode" not in ctx:
        m = re.search(r"Production Mode\s*[:：]\s*([A-Z0-9_]+)", brief + "\n" + state)
        if m:
            ctx["production_mode"] = m.group(1)
    ctx.update(_extract_policies(brief))
    m = re.search(r"Available Assets\s*[:：]\s*\[([^\]]*)\]", brief)
    if m:
        assets = [a.strip() for a in m.group(1).split(",") if a.strip()]
        ctx["available_assets"] = assets
        has_footage = any(
            ("footage" in a.lower() or "video" in a.lower() or "录屏" in a or "素材" in a)
            for a in assets
        )
        ctx["has_footage"] = has_footage
    m = re.search(r"Quality·Time·Budget Priority\s*[:：]\s*(.+)", brief)
    if m:
        bp = {}
        for part in m.group(1).split(","):
            kv = part.strip().split(":")
            if len(kv) == 2:
                bp[kv[0].strip()] = kv[1].strip()
        ctx["budget_priority"] = bp
    vb = _read_text(os.path.join(project_dir, "VISUAL_BIBLE.md"))
    ctx["visual_bible_summary"] = vb[:3000]
    ad = _read_text(os.path.join(project_dir, "AUDIO_DIRECTION.md"))
    sync_lines = [ln for ln in ad.splitlines() if ("sync" in ln.lower() or "同步" in ln)]
    ctx["audio_sync_requirements"] = "\n".join(sync_lines[:40])
    ctx["storyboard_text"] = _read_text(os.path.join(project_dir, "STORYBOARD.md"))
    return ctx


def load_shots(project_dir):
    shots = []
    d = os.path.join(project_dir, "shots")
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                p = os.path.join(d, fn)
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        shots.append(json.load(fh))
                except (OSError, ValueError) as e:
                    print("warn: cannot load %s: %s" % (p, e), file=sys.stderr)
    shots.sort(key=lambda s: (s.get("order", 0), s.get("id", "")))
    return shots


def load_overrides(project_dir):
    p = os.path.join(project_dir, "routing", "overrides.json")
    if os.path.isfile(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}
    return {}


def _project_name(project_dir):
    brief = _read_text(os.path.join(project_dir, "PROJECT_BRIEF.md"))
    m = re.search(r"^# Project Name\s*[:：]\s*(.+)$", brief, re.M)
    if m:
        return m.group(1).strip()
    return os.path.basename(project_dir.rstrip("/"))


# ---------------------------------------------------------------------------
# 14. ROUTING_PLAN.md (§51, §70)
# ---------------------------------------------------------------------------


def _shots_by_route(decisions):
    out = {}
    for d in decisions:
        out.setdefault(d["route"], []).append(d["shot_id"])
    return out


def _continuity_groups(decisions):
    groups = {}
    for d in decisions:
        g = d.get("continuity_group")
        if g:
            groups.setdefault(g, []).append(d)
    return groups


def build_routing_plan(decisions, project_dir):
    name = _project_name(project_dir)
    L = []
    L.append("# ROUTING_PLAN — %s" % name)
    L.append("")
    L.append("> 生成: `modules/router/router.py`（Phase-3 Shot/Layer Router，P3-1）。"
             "仅供人类 Review（§70），机器细节见 `routing/S###.yaml`。")
    L.append("")

    # Executive Summary
    n = len(decisions)
    by_route = _shots_by_route(decisions)
    hybrid = [d for d in decisions if d["route"] == "HYBRID"]
    proto = [d for d in decisions if d["prototype_required"]]
    low_conf = [d for d in decisions if d["confidence"] < 0.55]
    baked = [
        (d, l) for d in decisions for l in d.get("layers", []) if l["bake_policy"] == "BAKE"
    ]
    L.append("## Executive Summary")
    L.append("")
    L.append("- 镜头总数: %d；路由分布: %s。" % (
        n,
        ", ".join("%s×%d" % (r, len(v)) for r, v in sorted(by_route.items())) or "—",
    ))
    L.append("- HYBRID 需 Layer 拆分: %d；需原型验证: %d；低置信度(<0.55): %d；建议 BAKE: %d 层。"
             % (len(hybrid), len(proto), len(low_conf), len(baked)))
    L.append("")

    # Route Distribution
    L.append("## Route Distribution")
    L.append("")
    L.append("| Route | Count | Shots |")
    L.append("|---|---|---|")
    for r in ROUTES:
        if r in by_route:
            L.append("| %s | %d | %s |" % (r, len(by_route[r]), ", ".join(by_route[r])))
    L.append("")

    # Hybrid Shots
    L.append("## Hybrid Shots")
    L.append("")
    if hybrid:
        L.append("| Shot | Reason |")
        L.append("|---|---|")
        for d in hybrid:
            L.append("| %s | %s |" % (d["shot_id"], d["decision_summary"][:120]))
    else:
        L.append("无。")
    L.append("")

    # High-risk Shots (§70: only high-cost/high-risk/low-confidence/conflict)
    high_risk = [
        d for d in decisions
        if d["confidence"] < 0.55
        or d["route"] in ("HYBRID", "GENERATIVE_VIDEO", "THREE_D")
        or (d.get("constraints") and d["route"] == "GENERATIVE_VIDEO")
    ]
    L.append("## High-risk Shots")
    L.append("")
    if high_risk:
        L.append("| Shot | Confidence | Risk |")
        L.append("|---|---|---|")
        for d in high_risk:
            risk = "; ".join(d.get("constraints") or [])
            if not risk:
                risk = "high-cost/uncertain route or low confidence"
            L.append("| %s | %s (%s) | %s |" % (
                d["shot_id"], _fmt_float(d["confidence"]), d["confidence_level"], risk,
            ))
    else:
        L.append("无。")
    L.append("")

    # Prototype-required Shots
    L.append("## Prototype-required Shots")
    L.append("")
    if proto:
        L.append("| Shot | Route | Prototype | Goal |")
        L.append("|---|---|---|---|")
        for d in sorted(proto, key=lambda x: x["shot_id"]):
            L.append("| %s | %s | %s | %s |" % (
                d["shot_id"], d["route"], d["prototype_type"] or "—",
                (d["prototype_goal"] or "")[:100],
            ))
    else:
        L.append("无。")
    L.append("")

    # Editability Strategy
    L.append("## Editability Strategy")
    L.append("")
    L.append("- 文字 / 字幕 / UI / 照片 / B-roll 层一律 `KEEP_EDITABLE`（§29）。")
    L.append("- Remotion 渲染层 / AI 生成片段 / 3D 渲染 → `ASSET_REPLACEABLE`（可整体重渲替换）。")
    L.append("- 连续运动（continuity_group 非空）→ 建议 `BAKE` 为单一资产。")
    if baked:
        L.append("- 建议 BAKE 的层：")
        for d, layer in baked:
            L.append("  - %s `%s` (%s)" % (d["shot_id"], layer["id"], layer["role"]))
    else:
        L.append("- 建议 BAKE 的层：无。")
    L.append("")

    # Continuity Groups (§31 + §56)
    groups = _continuity_groups(decisions)
    L.append("## Continuity Groups")
    L.append("")
    if groups:
        L.append("| Group | Shots | Route | Asset Boundary |")
        L.append("|---|---|---|---|")
        for g, ds in sorted(groups.items()):
            shots = sorted(x["shot_id"] for x in ds)
            routes = set(x["route"] for x in ds)
            boundary = "—"
            if all(x["route"] == "REMOTION" for x in ds):
                boundary = "%s-A01 motion-sequence.mov" % g
            L.append("| %s | %s | %s | %s |" % (g, ", ".join(shots), "/".join(sorted(routes)), boundary))
        L.append("")
        L.append("> 同一 continuity_group 的一组镜头建议作为一个连续 Motion Asset 一起渲染，"
                 "禁止为可编辑性硬拆（v0.2 §31）。")
    else:
        L.append("无。")
    L.append("")

    # Potential Production Bottlenecks (§70)
    bottlenecks = [
        d for d in decisions
        if d["route"] in ("THREE_D", "GENERATIVE_VIDEO", "HYBRID")
        or d["prototype_required"]
        or len(d.get("layers", [])) >= 3
    ]
    L.append("## Potential Production Bottlenecks")
    L.append("")
    if bottlenecks:
        L.append("| Shot | Route | Bottleneck |")
        L.append("|---|---|---|")
        for d in sorted(bottlenecks, key=lambda x: x["shot_id"]):
            if d["route"] == "GENERATIVE_VIDEO":
                bt = "AI 生成成本与不确定性高；需 Prompt/Seed 迭代"
            elif d["route"] == "THREE_D":
                bt = "3D 建模 / 渲染成本高；建议 previs 先行"
            elif d["route"] == "HYBRID":
                bt = "多 Producer 并行 + 合成对齐成本"
            elif d["prototype_required"]:
                bt = "需原型验证后进入生产"
            else:
                bt = "Layer 数量多，装配复杂度上升"
            L.append("| %s | %s | %s |" % (d["shot_id"], d["route"], bt))
    else:
        L.append("无。")
    L.append("")

    # User Decisions Required
    udr = [
        d for d in decisions
        if d["confidence"] < 0.55
        or d["prototype_required"]
        or d["route_source"] != "AUTO"
    ]
    L.append("## User Decisions Required")
    L.append("")
    if udr:
        L.append("| Shot | Route | Confidence | Question |")
        L.append("|---|---|---|---|")
        for d in sorted(udr, key=lambda x: x["shot_id"]):
            if d["route_source"] != "AUTO":
                q = "确认 override 是否保留（source=%s, supersedes=%s）" % (
                    d["route_source"], d.get("supersedes") or "—",
                )
            elif d["prototype_required"]:
                q = "批准原型验证（%s）后进入生产？" % (d["prototype_type"] or "STATIC_KEYFRAME")
            else:
                q = "低置信度路由需要 Review（决策理由见 routing/%s.yaml）" % d["shot_id"]
            L.append("| %s | %s | %s | %s |" % (
                d["shot_id"], d["route"], _fmt_float(d["confidence"]), q,
            ))
    else:
        L.append("无（全部 AUTO 高置信度直荐）。")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 15. CLI
# ---------------------------------------------------------------------------


def run_cli(project_dir, json_out=False):
    shots = load_shots(project_dir)
    context = build_context(project_dir)
    overrides = load_overrides(project_dir)
    decisions = []
    for shot in shots:
        o = overrides.get(shot.get("id"))
        if o:
            context = dict(context)
            context["override"] = o
        else:
            context.pop("override", None)
        decisions.append(route_single(shot, context))

    routing_dir = os.path.join(project_dir, "routing")
    layers_dir = os.path.join(project_dir, "layers")
    os.makedirs(routing_dir, exist_ok=True)
    os.makedirs(layers_dir, exist_ok=True)

    for d in decisions:
        with open(os.path.join(routing_dir, "%s.yaml" % d["shot_id"]), "w", encoding="utf-8") as fh:
            fh.write(to_routing_yaml(d))
        if d["layer_decomposition_required"] and d.get("layers"):
            with open(os.path.join(layers_dir, "%s.yaml" % d["shot_id"]), "w", encoding="utf-8") as fh:
                fh.write(to_layers_yaml(d))

    plan = build_routing_plan(decisions, project_dir)
    with open(os.path.join(project_dir, "ROUTING_PLAN.md"), "w", encoding="utf-8") as fh:
        fh.write(plan)

    if json_out:
        out = []
        for d in decisions:
            o = dict(d)
            o.pop("layers", None)
            out.append(o)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("ROUTING_PLAN -> %s" % os.path.join(project_dir, "ROUTING_PLAN.md"))
        for d in decisions:
            print("%s\t%s\tconf=%s\t%s%s" % (
                d["shot_id"],
                d["route"],
                _fmt_float(d["confidence"]),
                d["confidence_level"],
                "  [override:%s]" % d["route_source"] if d["route_source"] != "AUTO" else "",
            ))
    return decisions


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    args = [a for a in argv if not a.startswith("-")]
    flags = set(a for a in argv if a.startswith("-"))
    if "--selftest" in flags:
        sys.exit(_selftest())
    if not args:
        print(
            "usage: python3 modules/router/router.py <project_dir> [--json] [--selftest]",
            file=sys.stderr,
        )
        sys.exit(2)
    run_cli(os.path.abspath(args[0]), json_out=("--json" in flags))
    sys.exit(0)


# ---------------------------------------------------------------------------
# 16. --selftest (double-path coverage, must pass)
# ---------------------------------------------------------------------------

_CLEAN_SHOTS = [
    {
        "id": "S001", "scene_id": "SC001", "order": 1, "duration": 8.0,
        "start_time": 0.0, "end_time": 8.0,
        "narrative_purpose": "Show the app dashboard overview.",
        "voiceover": "Review all metrics at a glance.",
        "on_screen_text": "Q3 REVENUE $1.2M / GROWTH 34%",
        "visual_description": "UI dashboard with metric cards, bar charts and a grid layout, dark background, precise alignment.",
        "camera": "static",
        "motion": "cards stagger in with spring, numbers tick up in sync with beats",
        "audio": {
            "music": {"mode": "continue", "cue": "", "action": ""},
            "sfx": ["tick"],
            "ambience": [],
            "sync_points": ["00:03 number tick"],
            "voiceover": {"present": True, "ducking": "duck -3dB"},
            "notes": "",
        },
        "transition_in": "cut", "transition_out": "cut",
        "layers": [], "route": "UNDECIDED", "continuity_group": "",
        "assets": [], "dependencies": [],
        "approval": {"approval_id": "AP-001", "status": "approved"},
        "implementation_status": "not_started", "qa_status": "not_started",
        "notes": "Layer Intent: BG: 深色底; UI: 指标卡片; DATA: 等宽数字; Editability: HIGH (指标与文案参数化)",
        "visual_direction": {"intent": "BG: dark; UI: cards; DATA: numbers", "editability": "HIGH", "reason": "metrics change every release"},
    },
    {
        "id": "S002", "scene_id": "SC001", "order": 2, "duration": 6.0,
        "start_time": 8.0, "end_time": 14.0,
        "narrative_purpose": "Show the chip design.",
        "voiceover": "",
        "on_screen_text": "",
        "visual_description": "3D microchip product model exploded into parts, metallic materials, orbiting camera, physics assembly.",
        "camera": "orbit 360 around the chip, slow push",
        "motion": "exploded parts reassemble into the chip with subtle physics",
        "audio": {
            "music": {"mode": "continue", "cue": "", "action": ""},
            "sfx": [], "ambience": [], "sync_points": [],
            "voiceover": {"present": False, "ducking": "none"}, "notes": "",
        },
        "transition_in": "cut", "transition_out": "cut",
        "layers": [], "route": "UNDECIDED", "continuity_group": "",
        "assets": [], "dependencies": [],
        "approval": {"approval_id": "AP-001", "status": "approved"},
        "implementation_status": "not_started", "qa_status": "not_started",
        "notes": "Layer Intent: BG: 深空背景; CONCEPT: 芯片; 3D: 爆炸图; Editability: LOW",
        "visual_direction": {"intent": "BG: space; CONCEPT: chip; 3D: exploded", "editability": "LOW", "reason": "render replaces as asset"},
    },
    {
        "id": "S003", "scene_id": "SC001", "order": 3, "duration": 5.0,
        "start_time": 14.0, "end_time": 19.0,
        "narrative_purpose": "Emotional close on a family photo.",
        "voiceover": "",
        "on_screen_text": "",
        "visual_description": "an old family photograph, gentle slow zoom in, warm lighting.",
        "camera": "static slow zoom 5%",
        "motion": "none, just slow zoom",
        "audio": {
            "music": {"mode": "continue", "cue": "", "action": ""},
            "sfx": [], "ambience": ["room tone"], "sync_points": [],
            "voiceover": {"present": False, "ducking": "none"}, "notes": "",
        },
        "transition_in": "dissolve", "transition_out": "fade_to_black",
        "layers": [], "route": "UNDECIDED", "continuity_group": "",
        "assets": [], "dependencies": [],
        "approval": {"approval_id": "AP-001", "status": "approved"},
        "implementation_status": "not_started", "qa_status": "not_started",
        "notes": "Layer Intent: BG: 照片; Editability: LOW",
        "visual_direction": {"intent": "BG: photo", "editability": "LOW", "reason": "single still, slow zoom"},
    },
]

_FACTORS_EMPTY = {k: 0.12 for k in FACTOR_KEYS}


def _factors(**kw):
    f = dict(_FACTORS_EMPTY)
    f.update(kw)
    return f


def _selftest():
    """Run double-path coverage. Returns 0 on success, 1 on any failure."""
    errors = []

    def check(cond, msg):
        if cond:
            print("  PASS  %s" % msg)
        else:
            errors.append(msg)
            print("  FAIL  %s" % msg)

    print("== selftest: module/router.py ==")

    # ---- Path 1: route_single API on clean shots ----
    print("[Path 1] route_single() on clean fixture shots")
    d1 = route_single(_CLEAN_SHOTS[0], {})
    d2 = route_single(_CLEAN_SHOTS[1], {})
    d3 = route_single(_CLEAN_SHOTS[2], {})
    check(d1["route"] == "REMOTION", "UI dashboard -> REMOTION (got %s)" % d1["route"])
    check(d2["route"] == "THREE_D", "3D chip orbit -> THREE_D (got %s)" % d2["route"])
    check(d3["route"] == "JY_NATIVE", "photo slow zoom -> JY_NATIVE (got %s)" % d3["route"])
    check(set(d1["scores"].keys()) == set(FACTOR_KEYS),
          "scores has exactly the 12 factor keys")
    check(all(0.0 <= v <= 1.0 for v in d1["scores"].values()),
          "all factor values within 0..1")

    # ---- Path 2: CLI on a clean project fixture ----
    print("[Path 2] CLI run on a clean project fixture")
    tmp = tempfile.mkdtemp(prefix="router_selftest_")
    shots_dir = os.path.join(tmp, "shots")
    os.makedirs(shots_dir)
    for s in _CLEAN_SHOTS:
        with open(os.path.join(shots_dir, s["id"] + ".json"), "w", encoding="utf-8") as fh:
            json.dump(s, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(tmp, "PROJECT_BRIEF.md"), "w", encoding="utf-8") as fh:
        fh.write("# Project Name: Selftest Fixture\n# Production Mode: PRODUCT_TECH_SHORT\n")
    script = os.path.abspath(__file__)
    import subprocess
    r = subprocess.run(
        [sys.executable, script, tmp], capture_output=True, text=True, timeout=120
    )
    check(r.returncode == 0, "CLI exits 0 (rc=%s stderr=%s)" % (r.returncode, r.stderr[-300:]))
    for sid, want in (("S001", "REMOTION"), ("S002", "THREE_D"), ("S003", "JY_NATIVE")):
        p = os.path.join(tmp, "routing", "%s.yaml" % sid)
        content = _read_text(p)
        check("route: %s" % want in content, "routing/%s.yaml route=%s" % (sid, want))
    plan = _read_text(os.path.join(tmp, "ROUTING_PLAN.md"))
    for section in (
        "## Executive Summary", "## Route Distribution", "## Hybrid Shots",
        "## High-risk Shots", "## Prototype-required Shots",
        "## Editability Strategy", "## Continuity Groups",
        "## Potential Production Bottlenecks", "## User Decisions Required",
    ):
        check(section in plan, "ROUTING_PLAN.md contains %s" % section)

    # ---- Edge cases via route_single ----
    print("[Edge] dirty / conflict scenarios")

    # Tokyo street: photoreal high-entropy, no text
    tokyo = {
        "id": "S010", "on_screen_text": "",
        "visual_description": "busy Tokyo street at night, dense crowd, neon signs, chaotic traffic, steam from food stalls",
        "camera": "handheld follow",
        "motion": "organic crowd motion, smoke drifting",
        "audio": {"sync_points": [], "sfx": [], "voiceover": {"present": False}},
        "notes": "Editability: LOW",
    }
    dt = route_single(tokyo, {})
    check(dt["route"] in ("REAL_FOOTAGE", "GENERATIVE_VIDEO"),
          "Tokyo street -> REAL_FOOTAGE|GENERATIVE_VIDEO (got %s)" % dt["route"])
    check(dt["route"] != "REMOTION", "Tokyo street is NOT REMOTION")

    # exact text + photoreal -> HYBRID, AI must not own text
    hybrid_shot = {
        "id": "S018", "on_screen_text": "CAFÉ 24H",
        "visual_description": "photoreal street corner at dusk with a glowing storefront, the sign text must be exact and readable",
        "camera": "static",
        "motion": "gentle bokeh, people passing",
        "audio": {"sync_points": [], "sfx": [], "voiceover": {"present": False}},
        "notes": "Layer Intent: BG: 真实街道黄昏; TYPO: 招牌文字必须精确; Editability: HIGH",
        "visual_direction": {"editability": "HIGH", "intent": "BG: real street; TYPO: exact sign"},
    }
    dh = route_single(hybrid_shot, {})
    check(dh["route"] == "HYBRID", "exact text + photoreal -> HYBRID (got %s)" % dh["route"])
    check(dh["layer_decomposition_required"], "HYBRID requires layer decomposition")
    text_layers = [l for l in dh.get("layers", []) if l["role"] in ("TYPOGRAPHY", "UI", "SUBTITLE")]
    check(text_layers and all(l["route"] == "REMOTION" for l in text_layers),
          "text layer routed to REMOTION (AI does not own text)")
    check(any("exact text" in c for c in dh.get("constraints", [])),
          "hard constraint recorded: GENERATIVE_VIDEO must not own text")

    # subtitle -> KEEP_EDITABLE
    sub_shot = {
        "id": "S020", "on_screen_text": "字幕台词", "notes": "SUBTITLE: 字幕层; Editability: HIGH",
        "audio": {"sync_points": [], "sfx": [], "voiceover": {"present": True}},
    }
    check(decide_bake("SUBTITLE", "REMOTION", sub_shot) == "KEEP_EDITABLE",
          "subtitle layer -> KEEP_EDITABLE")
    check(any("subtitle present" in c for c in hard_constraints(compute_factors(sub_shot, {}), sub_shot)),
          "subtitle hard constraint recorded")

    # continuous morph -> continuity_group + BAKE
    morph_shot = {
        "id": "S030", "continuity_group": "CG-M",
        "on_screen_text": "",
        "visual_description": "liquid metal blob continuously morphing, procedural graph, water-like surface, complex spatial camera",
        "camera": "spatial camera flythrough",
        "motion": "continuous morph, fluid",
        "audio": {"sync_points": [], "sfx": [], "voiceover": {"present": False}},
        "notes": "",
    }
    dm = route_single(morph_shot, {})
    check(dm["continuity_group"] == "CG-M", "continuity_group preserved")
    check(decide_bake("SUBJECT", dm["route"], morph_shot) == "BAKE",
          "continuous motion layer -> BAKE")
    groups = _continuity_groups([dm])
    check("CG-M" in groups, "continuity group appears in plan data")

    # two REMOTION shots in one group -> asset boundary suggestion
    a1 = route_single({**_CLEAN_SHOTS[0], "id": "S040", "continuity_group": "CG-A"}, {})
    a2 = route_single({**_CLEAN_SHOTS[0], "id": "S041", "continuity_group": "CG-A"}, {})
    check(a1["route"] == "REMOTION" and a2["route"] == "REMOTION",
          "group CG-A shots route REMOTION")
    grp = _continuity_groups([a1, a2])
    boundary = "%s-A01 motion-sequence.mov" % "CG-A" if all(
        x["route"] == "REMOTION" for x in grp["CG-A"]
    ) else None
    check(boundary == "CG-A-A01 motion-sequence.mov",
          "REMOTION continuity group -> asset boundary suggestion")

    # abstract concept -> LOW/MEDIUM confidence + prototype
    abstract_shot = {
        "id": "S050", "on_screen_text": "",
        "visual_description": "a vague abstract idea of freedom, soft floating shapes, no concrete objects, no words",
        "camera": "none",
        "motion": "none",
        "audio": {"sync_points": [], "sfx": [], "voiceover": {"present": False}},
        "notes": "",
    }
    da = route_single(abstract_shot, {})
    check(da["confidence"] < 0.80,
          "abstract concept -> confidence < 0.80 (got %s)" % da["confidence"])
    check(da["prototype_required"], "abstract concept -> prototype_required")
    check(da["prototype_type"] == "STATIC_KEYFRAME",
          "LOW confidence -> STATIC_KEYFRAME prototype")
    check("Concept Exploration" in (da["prototype_goal"] or ""),
          "LOW confidence -> concept-exploration prototype goal")

    # escalate / deescalate
    f_complex = _factors(camera_complexity=0.8)
    esc_route, esc_note = escalate("JY_NATIVE", f_complex, None)
    check(esc_route == "REMOTION" and esc_note and "escalat" in esc_note,
          "JY_NATIVE + complex camera -> escalate REMOTION")
    photo_shot = {"id": "S060", "visual_description": "an old photograph, slow zoom in",
                  "camera": "slow zoom", "motion": "none", "on_screen_text": "",
                  "audio": {}, "notes": ""}
    f_simple = _factors(structural_precision=0.1, text_accuracy=0.1,
                        data_accuracy=0.1, timing_precision=0.1)
    des_route, des_note = deescalate("REMOTION", f_simple, photo_shot)
    check(des_route == "JY_NATIVE" and des_note and "de-escalat" in des_note,
          "REMOTION + photo slow zoom -> de-escalate JY_NATIVE")

    # user override + persistence
    print("[Edge] user override + persistence")
    ov = {"route": "JY_NATIVE", "source": "USER_OVERRIDE", "note": "client wants a simple edit"}
    base = route_single(_CLEAN_SHOTS[0], {})
    overridden = apply_override(dict(base), ov)
    check(overridden["route"] == "JY_NATIVE", "override forces route JY_NATIVE")
    check(overridden["route_source"] == "USER_OVERRIDE", "route_source=USER_OVERRIDE")
    check(overridden["supersedes"] == "REMOTION", "supersedes records old route")
    check(overridden["confidence"] == 1.0, "override sets confidence 1.0")
    # persistence through overrides.json + CLI
    ovdir = os.path.join(tmp, "routing")
    os.makedirs(ovdir, exist_ok=True)
    with open(os.path.join(ovdir, "overrides.json"), "w", encoding="utf-8") as fh:
        json.dump({"S001": ov}, fh)
    r2 = subprocess.run(
        [sys.executable, script, tmp], capture_output=True, text=True, timeout=120
    )
    check(r2.returncode == 0, "CLI with overrides exits 0")
    ov_content = _read_text(os.path.join(tmp, "routing", "S001.yaml"))
    check("route: JY_NATIVE" in ov_content, "override persisted into routing/S001.yaml")
    check("route_source: USER_OVERRIDE" in ov_content, "override source persisted")
    check("supersedes: REMOTION" in ov_content, "supersedes persisted")
    check("confidence: 1.00" in ov_content, "override confidence persisted")
    # second run still applies (file is the persistence store)
    r3 = subprocess.run(
        [sys.executable, script, tmp], capture_output=True, text=True, timeout=120
    )
    check(r3.returncode == 0, "CLI second run with overrides exits 0")
    check("route: JY_NATIVE" in _read_text(os.path.join(tmp, "routing", "S001.yaml")),
          "override re-applied on second run (persistent)")

    # llm_judgment hook injection path
    print("[Edge] llm_judgment hook")
    def fake_judge(shot, factors, candidates, context):
        return {"score_adjust": {"JY_NATIVE": 0.6}}
    res = evaluate_candidates(
        [
            {"route": "REMOTION", "score": 0.8},
            {"route": "JY_NATIVE", "score": 0.3},
        ],
        _factors(), {"llm_judgment": fake_judge}, {}
    )
    check(res[0]["route"] == "JY_NATIVE", "llm_judgment hook can re-rank candidates")

    # layer decomposition sanity: no over-decomposition, roles valid
    roles = {l["role"] for d in (dh,) for l in d.get("layers", [])}
    check(roles <= set(LAYER_ROLES), "layer roles within the 16-role enum")
    check(len(dh.get("layers", [])) <= 5, "layer count capped (no over-decomposition)")

    if errors:
        print("")
        print("selftest FAILED (%d assertions)" % len(errors))
        for e in errors:
            print("  - " + e)
        return 1
    print("")
    print("selftest PASSED")
    return 0


if __name__ == "__main__":
    main()
