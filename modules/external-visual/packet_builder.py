#!/usr/bin/env python3
"""packet_builder.py — Generative Video Packet Builder（Phase-6 Prompt §8-25 / §33-34 / §40-41 / §49 / §79 / §91；P6-2）.

把已批准的 External Visual Request（EV-###，P6-01 external-visual-request.schema.json）
转成 Provider-neutral 的 GENERATIVE VIDEO PRODUCTION PACKET（GV-###，字段对齐 P6-01
generative-video-packet.schema.json）。本模块只产出 Packet / 连续性 / 冲突记录，不产生资产
文件、不调用任何生成服务；Packet 不写死任何具体视频模型（§25，provider 只以配置/字符串概念
存在，代码无 if model == "XYZ" 分支）。

规则实现（§→PHASE6_PROMPT.md）：
- §10 purpose_first：purpose 先回答"这个镜头为何存在"（从 ev.purpose + storyboard 节拍
  推导功能陈述），再谈画面
- §7/§14 no_exact_text（硬规则）：EXACT_UI/EXACT_TEXT/EXACT_NUMBER/LOGO/DATA/LABEL 任意
  一类命中时，model_ready_prompt 与 subject/environment 一律不含具体文字；postproduction_plan
  追加 overlay 条目（REMOTION/JY_NATIVE 承担精确信息层）；review_criteria 必含 text_artifacts；
  用独立函数 enforce_no_exact_text(packet) 强制并校验
- §13/§14 text_safe_area：composition 六键齐备；有 overlay_requirements 时必须写预留静区
- §15-17 camera：shot_size/height/angle/lens(6 枚举)/movement(13 枚举)/movement_speed/
  stabilization 全结构化，禁止 "cinematic camera" 空话；lens 只写类型，不编造焦段
- §18 organic_motion：environment_motion 单独描述 people/cloth/hair/smoke/water/plants/
  crowd/ambient_objects
- §19 lighting：source_direction/softness/contrast/temperature/practical/volumetric/shadows
- §20 motion_character：继承 Visual Bible 的 motion_character；缺省 restrained，
  禁止默认 dramatic cinematic
- §21 start/end_frame：ev 有 start/end_frame_requirement 时必须生成明确首/尾帧状态描述
- §22-23 continuity 10 项；adjacent_shots 提供时填 previous/next_shot_context 并做
  screen_direction 检查（冲突且无导演意图 → generation_notes 记 warning）
- §24 reference_inputs 7 类引用（6 个键位 + REF 条目，兼容性由 adapter 决定）
- §33-34 variant_strategy：6 风险因子命中 ≥3 或 hero_shot=true → TWO_TO_FOUR
- §40-41 detect_overload(packet)：7 项中 ≥4 项命中 → OVERLOAD + 简化建议
  （simplify/split_shot/reduce_requirements 附理由）；split_shot 建议 → 生成
  PRODUCTION_CONFLICT 记录（PC-###，approval_required=true），禁止引擎自行改 storyboard
- §49 postproduction_plan 十项布尔+说明；凡有精确信息层要求 → text 或 overlay 必须为 true
- negative_constraints：ev.avoid + 硬规则基础项（no text / no watermark / no logo）
- model_ready_prompt：确定性模板拼接（英文，subject→environment→composition→camera→
  lighting→motion→style 顺序），无 LLM
- §79/§91 prompt_hash（规范化 JSON → sha256，照抄 modules/production/planner.py 口径）+
  packet_version 版本化：同 request_id 重建且 hash 变化 → version+1 且 supersedes 指向旧版

技术约束：Python 3 stdlib only；无 LLM、无联网；确定性（同输入同输出，纯函数风格）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 共享契约常量（与 P6-01 generative-video-packet.schema.json 字段表对齐）
# ---------------------------------------------------------------------------

REQUEST_ID_RE = re.compile(r"^EV-\d{3}$")
PACKET_ID_RE = re.compile(r"^GV-\d{3}$")

# §16 lens 6 枚举（P6-01 enums_phase6.lens）
LENS_ENUM = ("WIDE", "NORMAL", "TELEPHOTO", "MACRO", "SHALLOW_DOF", "DEEP_FOCUS")
# §17 camera movement 13 枚举（P6-01 enums_phase6.camera_movement）
CAMERA_MOVEMENT_ENUM = (
    "STATIC", "PUSH_IN", "PULL_OUT", "PAN", "TILT", "ORBIT", "DOLLY",
    "TRACKING", "CRANE", "HANDHELD", "POV", "COMPLEX", "CUSTOM",
)
# §7 硬规则：精确文字类（P6-01 overlay_verbatim_classes）
EXACT_TEXT_CLASSES = ("EXACT_UI", "EXACT_TEXT", "EXACT_NUMBER", "LOGO", "DATA", "LABEL")
# §33 variant range（P6-01 variant_range）
VARIANT_RANGES = ("ONE_TO_TWO", "TWO_TO_FOUR")
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH")
# §20 motion_character（Phase-5 motion-family 10 枚举）
MOTION_CHARACTERS = (
    "restrained", "soft", "precise", "spatial", "kinetic", "cinematic",
    "editorial", "elastic", "mechanical", "organic",
)
# §24 reference_inputs 键位（P6-01：reference_image/style_frame/character_reference/
# environment_reference/product_reference/previous_generated_frame）
REFERENCE_KEYS = (
    "reference_image", "style_frame", "character_reference",
    "environment_reference", "product_reference", "previous_generated_frame",
)
# §36 review_criteria 18 维度
REVIEW_DIMENSIONS = (
    "prompt_adherence", "composition", "subject_consistency", "motion_quality",
    "camera_quality", "temporal_coherence", "anatomy", "physics", "lighting",
    "continuity", "visual_bible_fit", "text_artifacts", "unwanted_logos",
    "flicker", "warping", "usability_for_overlays", "editability",
    "overall_production_value",
)
# §22 continuity 10 项
CONTINUITY_KEYS = (
    "subject_identity", "wardrobe", "environment", "lighting", "camera_direction",
    "movement_direction", "screen_direction", "object_position", "time_of_day", "color",
)
# §40 overload 7 因子
OVERLOAD_FACTORS = (
    "complex_scene", "complex_camera", "two_or_more_people", "precise_action",
    "heavy_background_behavior", "special_lighting", "complex_end_frame",
)
# §49 postproduction_plan 10 项
POSTPRODUCTION_KEYS = (
    "crop", "stabilization", "speed", "color", "overlay", "mask", "text",
    "grain", "sound", "transition",
)

# 自由文本 motion_character -> 10 枚举 token（确定性映射；§20）
_CHAR_SYNONYMS = {
    "restrained": "restrained", "克制": "restrained", "calm": "restrained",
    "subtle": "restrained", "平稳": "restrained",
    "soft": "soft", "柔": "soft", "gentle": "soft", "dreamlike": "soft",
    "precise": "precise", "精确": "precise", "technical": "precise", "技术": "precise",
    "spatial": "spatial", "空间": "spatial",
    "kinetic": "kinetic", "动感": "kinetic", "energetic": "kinetic", "活力": "kinetic",
    "cinematic": "cinematic", "电影": "cinematic", "dramatic": "cinematic",
    "editorial": "editorial", "编辑": "editorial", "documentary": "editorial",
    "organic": "organic", "有机": "organic",
    "elastic": "elastic", "弹性": "elastic", "bouncy": "elastic",
    "mechanical": "mechanical", "机械": "mechanical",
}
# 精确动作 / 复杂 motion 标记（确定性启发式；§34 / §40）
_PRECISE_ACTION_MARKERS = (
    "精确", "exact", "precise", "coordinated", "同步", "按拍点", "specific",
    "精确动作", "synchronized",
)
_COMPLEX_MOTION_MARKERS = (
    "complex", "multiple", "crowd", "人群", "高速", "fast", "复杂", "大量",
    "heavy", "intricate",
)
_HUMAN_MARKERS = (
    "person", "people", "human", "man", "woman", "actor", "character",
    "人物", "人", "人群", "couple", "two people", "three people",
)
_IMPORTANCE_MARKERS = ("hero", "关键", "climax", "payoff", "重要", "关键镜头")
_REVEAL_MARKERS = ("reveal", "wide", "zoom out", "expand", "拉开", "整个", "entire",
                   "transition to", "pan across", "转场")

# P6-01 generative-video-packet.schema.json required 字段表（用于 validate_packet_fields）
_PACKET_REQUIRED = (
    "packet_id", "packet_version", "request_id", "shot_id", "layer_id", "purpose",
    "duration", "aspect_ratio", "resolution", "fps", "subject", "environment",
    "composition", "framing", "camera", "lens", "camera_movement", "subject_action",
    "environment_motion", "lighting", "time_of_day", "mood", "style",
    "material_character", "color_direction", "motion_character", "start_frame",
    "end_frame", "continuity", "text_safe_area", "overlay_safe_area",
    "postproduction_plan", "negative_constraints", "model_ready_prompt",
    "negative_prompt", "variant_strategy", "recommended_variant_count",
    "reference_inputs", "generation_notes", "review_criteria",
)

_COMPOSITION_KEYS = (
    "subject_placement", "negative_space", "visual_hierarchy", "depth_layers",
    "safe_zones", "intended_overlay_area",
)


# ---------------------------------------------------------------------------
# 基础工具（纯函数）
# ---------------------------------------------------------------------------

def _pick(d: Optional[dict], *keys: str, default: Any = None) -> Any:
    """按顺序取第一个存在且非 None 的值。"""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def _norm_enum(value: Any, allowed: tuple, default: Any = None) -> Any:
    """字符串枚举规范化；无法映射 → default（不抛错，保证确定性降级）。"""
    if value is None:
        return default
    s = str(value).upper().replace("-", "_").replace(" ", "_")
    return s if s in allowed else default


def _join(parts) -> str:
    """拼接非空字符串片段（", " 分隔）。"""
    return ", ".join(str(p).strip() for p in parts if p not in (None, ""))


def _canonical(value: Any) -> Any:
    """递归规范化（照抄 modules/production/planner.py 口径）：dict 键转 str 排序、
    tuple→list、整值 float→int、bool 优先、非有限 float→字符串。"""
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


def _sha256_spec(spec: dict) -> str:
    """规范化 JSON → sha256（§79 / §91；照抄 planner.spec_hash 口径）。"""
    if not isinstance(spec, dict):
        spec = {}
    payload = json.dumps(_canonical(spec), sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _scrub_literal_text(text: Any) -> Any:
    """去掉字符串中的"具体文字内容"（引号包裹的字面文本；§7 no_exact_text）。

    确定性实现：仅剥离引号包裹内容（中英文引号），替换为占位说明；
    非字符串原样返回。
    """
    if not isinstance(text, str):
        return text
    s = text
    s = re.sub(r'["\u201c\u201d]([^"\u201c\u201d]{1,80})["\u201c\u201d]',
               "［文字由 overlay 层呈现，生成画面内禁止出现］", s)
    s = re.sub(r"['\u2018\u2019]([^'\u2018\u2019]{1,80})['\u2018\u2019]",
               "［文字由 overlay 层呈现，生成画面内禁止出现］", s)
    return s


def has_literal_text(packet: dict) -> bool:
    """校验 packet 的生成描述里是否残留具体文字（引号包裹内容；供 enforce 与单测使用）。"""
    texts: list = []
    for key in ("subject", "environment"):
        obj = packet.get(key)
        if isinstance(obj, dict):
            texts.extend(str(v) for v in obj.values() if isinstance(v, str))
        elif isinstance(obj, str):
            texts.append(obj)
    texts.append(str(packet.get("model_ready_prompt") or ""))
    for t in texts:
        if re.search(r'["\u201c\u201d][^"\u201c\u201d]{2,}["\u201c\u201d]', t):
            return True
        if re.search(r"['\u2018\u2019][^'\u2018\u2019]{2,}['\u2018\u2019]", t):
            return True
    return False


# ---------------------------------------------------------------------------
# §7 no_exact_text 硬规则：独立强制函数
# ---------------------------------------------------------------------------

def _detect_exact_text(ev: dict) -> list:
    """确定性检测 ev 是否命中精确文字类（§7 / P6-01 overlay_verbatim_classes）。"""
    classes: list = []
    seen: set = set()

    def add(c: str) -> None:
        if c in EXACT_TEXT_CLASSES and c not in seen:
            seen.add(c)
            classes.append(c)

    for item in _as_list(ev.get("overlay_requirements")):
        if isinstance(item, dict):
            cls = _pick(item, "class", "type", "kind", "verbatim_class")
            if cls is not None:
                add(str(cls).upper())
            # 字典里直接写类名（如 {"EXACT_TEXT": "..."} 或 ["EXACT_TEXT"] 值）
            for k, v in item.items():
                if str(k).upper() in EXACT_TEXT_CLASSES:
                    add(str(k).upper())
                if isinstance(v, str) and v.upper() in EXACT_TEXT_CLASSES:
                    add(v.upper())
        else:
            s = str(item).upper()
            for c in EXACT_TEXT_CLASSES:
                if c in s:
                    add(c)
    for key in ("overlay_verbatim_classes", "text_requirements", "exact_text_classes"):
        for item in _as_list(ev.get(key)):
            add(str(item).upper())
    ta = ev.get("text_accuracy")
    if isinstance(ta, str):
        for c in EXACT_TEXT_CLASSES:
            if c in ta.upper():
                add(c)
    elif isinstance(ta, (int, float)) and ta >= 0.7:
        # 路由评分 text_accuracy 高 → 视为精确文字需求（保守按 EXACT_TEXT）
        add("EXACT_TEXT")
    if ev.get("exact_text") is True:
        add("EXACT_TEXT")
    if ev.get("text_required") is True:
        add("EXACT_TEXT")
    return sorted(classes)


def enforce_no_exact_text(packet: dict) -> dict:
    """§7 硬规则强制函数（独立、幂等）：从 packet 中读取 text_policy 标记，
    若命中精确文字类，则保证：
      1) subject/environment/model_ready_prompt 不含具体文字（引号字面量剥除）
      2) postproduction_plan.overlay 必须 required=true 且注明 REMOTION/JY_NATIVE
      3) postproduction_plan.text 必须 required=true（§49）
      4) review_criteria 必含 text_artifacts
    返回修改后的深拷贝；未命中时原样返回。
    """
    p = deepcopy(packet)
    exact_required = False
    for note in _as_list(p.get("generation_notes")):
        if isinstance(note, str) and note.startswith("text_policy:"):
            exact_required = True
            break
    if not exact_required:
        return p

    # 1) 剥除具体文字
    for key in ("subject", "environment"):
        obj = p.get(key)
        if isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = _scrub_literal_text(v)
        elif isinstance(obj, str):
            p[key] = _scrub_literal_text(obj)
    p["model_ready_prompt"] = _scrub_literal_text(p.get("model_ready_prompt") or "")

    # 2) overlay 条目（REMOTION/JY_NATIVE 承担精确信息层）
    plan = p.setdefault("postproduction_plan", {})
    overlay = plan.get("overlay")
    owner_note = "精确信息层由 REMOTION/JY_NATIVE overlay 承担，生成画面保持无文字（§7/§49）"
    if not isinstance(overlay, dict) or not overlay.get("required"):
        plan["overlay"] = {"required": True, "note": owner_note, "owner": "REMOTION/JY_NATIVE"}
    else:
        merged = dict(overlay)
        merged["required"] = True
        merged["owner"] = "REMOTION/JY_NATIVE"
        if not (("REMOTION" in str(merged.get("note") or ""))
                or ("JY_NATIVE" in str(merged.get("note") or ""))):
            merged["note"] = str(merged.get("note") or "") + "；" + owner_note
        plan["overlay"] = merged

    # 3) text 条目（§49：凡有精确信息层要求必须 text 或 overlay 为 true）
    text = plan.get("text")
    if not isinstance(text, dict) or not text.get("required"):
        plan["text"] = {"required": True,
                        "note": "精确文字/数字/标签由文本层承担（REMOTION/JY_NATIVE）"}

    # 4) review_criteria 必含 text_artifacts
    rc = p.setdefault("review_criteria", [])
    if "text_artifacts" not in list(rc):
        rc.append("text_artifacts")
    return p


# ---------------------------------------------------------------------------
# §40 overload 检测（独立函数）
# ---------------------------------------------------------------------------

def _factor_hit(packet: dict, factor: str) -> bool:
    """7 个 overload 因子各自的确定性判据（§40）。"""
    env = packet.get("environment") or {}
    cam = packet.get("camera") or {}
    light = packet.get("lighting") or {}
    subj = packet.get("subject") or {}
    env_motion = packet.get("environment_motion") or {}
    subject_action = str(packet.get("subject_action") or "")
    end = packet.get("end_frame") or {}
    start = packet.get("start_frame") or {}

    if factor == "complex_scene":
        density = str(env.get("density") or "").lower()
        entropy = env.get("scene_entropy")
        depth = str(env.get("depth_layers") or "")
        if isinstance(entropy, (int, float)) and entropy >= 0.7:
            return True
        if density in ("high", "dense", "复杂", "高", "very_high"):
            return True
        if "3" in depth or "三" in depth or "4" in depth:
            return True
        return False
    if factor == "complex_camera":
        movement = _norm_enum(cam.get("movement"), CAMERA_MOVEMENT_ENUM)
        speed = str(cam.get("movement_speed") or "").lower()
        if movement in ("COMPLEX", "CRANE", "ORBIT", "HANDHELD"):
            return True
        if speed in ("fast", "high", "极快", "高速"):
            return True
        return False
    if factor == "two_or_more_people":
        who = str(subj.get("who_what") or "") + " " + subject_action
        low = who.lower()
        if any(m in low for m in ("two", "three", "four", "crowd", "人群",
                                  "couple", "多人", "双人")):
            return True
        hits = sum(1 for m in _HUMAN_MARKERS if m in low)
        return hits >= 2
    if factor == "precise_action":
        low = subject_action.lower()
        return any(m.lower() in low for m in _PRECISE_ACTION_MARKERS)
    if factor == "heavy_background_behavior":
        active = [k for k in ("people", "cloth", "hair", "smoke", "water",
                              "plants", "crowd", "ambient_objects")
                  if str(env_motion.get(k) or "").strip()]
        return len(active) >= 3
    if factor == "special_lighting":
        if light.get("practical") is True or light.get("volumetric") is True:
            return True
        return str(light.get("contrast") or "").lower() in ("high", "extreme", "高")
    if factor == "complex_end_frame":
        end_state = str(end.get("state") or "")
        start_state = str(start.get("state") or "")
        if end.get("changes_scene") is True:
            return True
        return any(m in end_state.lower() for m in _REVEAL_MARKERS) and \
            end_state.lower() != start_state.lower()
    return False


def detect_overload(packet: dict) -> dict:
    """§40：7 项中 ≥4 项命中 → OVERLOAD，并返回简化建议清单
    （simplify/split_shot/reduce_requirements 三选，附理由）。"""
    hits = [f for f in OVERLOAD_FACTORS if _factor_hit(packet, f)]
    overload = len(hits) >= 4
    suggestions: list = []
    if overload:
        suggestions.append({
            "action": "simplify",
            "reason": "单镜头同时承担 7 项中的 %d 项高要求（%s），继续堆词只会增加"
                      "伪影/漂移风险（§40）" % (len(hits), ", ".join(hits)),
        })
        # 针对性降载建议（确定性）
        if "heavy_background_behavior" in hits and "complex_scene" in hits:
            suggestions.append({
                "action": "reduce_requirements",
                "reason": "背景行为与复杂场景叠加：建议把环境动效压到 1-2 类、降低"
                          "画面熵，保留前景主体表现力",
            })
        if "special_lighting" in hits and "complex_scene" in hits:
            suggestions.append({
                "action": "reduce_requirements",
                "reason": "特殊灯光叠加复杂场景：建议先保证基础打光与主光方向稳定，"
                          "practical/volumetric 效果后续合成",
            })
        # split_shot：多人物+精确动作 或 复杂运镜+复杂结束帧 → 拆镜
        if ("two_or_more_people" in hits and "precise_action" in hits) or \
                ("complex_camera" in hits and "complex_end_frame" in hits):
            suggestions.append({
                "action": "split_shot",
                "reason": "建议拆分为两个镜头（如 S0XXA/S0XXB）分别承担人物动作与运镜"
                          "结束帧，降低单镜生成难度（§41）——这属于 storyboard 修改，"
                          "必须走 PRODUCTION_CONFLICT 审批，引擎不自行改动",
            })
    return {
        "verdict": "OVERLOAD" if overload else "OK",
        "hit_factors": hits,
        "hits": len(hits),
        "suggestions": suggestions,
    }


def _conflict_id(request_id: str) -> str:
    """确定性 PC-###：取 request_id 数字部分末 3 位（EV-001 → PC-001）。"""
    digits = re.sub(r"\D", "", str(request_id))
    if not digits:
        digits = "0"
    return "PC-%03d" % (int(digits[-3:]) % 1000)


def _write_conflict_record(conflict: dict, conflict_id: str, directory) -> Path:
    """§41 / FR-025：把 PRODUCTION_CONFLICT 结构化记录写成独立 <dir>/PC-###.json。

    与 generation_notes 解耦：notes 只引用记录 id，JSON 只存在于独立文件。
    """
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("%s.json" % conflict_id)
    path.write_text(json.dumps(conflict, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")
    return path


def _strip_none(value: Any) -> Any:
    """递归省略值为 None 的键（FR-006/FR-013：可选空值省略键，不向 schema 写 null）。

    学 P6-04 "可选空值省略键"：dict 中值为 None 的键直接省略；list 元素保留。
    """
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# §23 screen direction 检查
# ---------------------------------------------------------------------------

def _direction_token(direction: Any) -> Optional[str]:
    """运动方向归一化：left_to_right / right_to_left / 其他（未指明方向返回 None）。"""
    if direction is None:
        return None
    s = re.sub(r"[\s_\-]+", "_", str(direction).lower())
    if s in ("left_to_right", "ltr", "lr", "left_to_right_motion"):
        return "left_to_right"
    if s in ("right_to_left", "rtl", "rl", "right_to_left_motion"):
        return "right_to_left"
    return None


def _directions_conflict(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = _direction_token(a), _direction_token(b)
    return bool(ta and tb and ta != tb)


def _director_intent(adj: dict) -> bool:
    intent = _pick(adj, "director_intent", "intent", "deliberate_design", "director_design")
    return intent in (True, "true", "True", "yes", "deliberate", "intentional", "导演设计")


def screen_direction_warnings(current_direction: Any, adjacent_shots: list) -> list:
    """§23：相邻镜头主体运动方向冲突且无导演意图 → warning 清单（确定性）。"""
    warnings: list = []
    for adj in adjacent_shots or []:
        if not isinstance(adj, dict):
            continue
        adj_dir = _pick(adj, "movement_direction", "screen_direction", "subject_direction")
        if not _directions_conflict(current_direction, adj_dir):
            continue
        if _director_intent(adj):
            continue
        relation = str(_pick(adj, "relation", "position", "role") or "adjacent")
        shot = str(adj.get("shot_id") or "?")
        warnings.append(
            "screen_direction: 相邻镜头 %s（%s）主体运动方向 %r 与本镜头 %r 冲突且无"
            "导演意图标记，已记 warning，需人工确认（§23）"
            % (shot, relation, adj_dir, current_direction)
        )
    return warnings


# ---------------------------------------------------------------------------
# §33-34 variant strategy
# ---------------------------------------------------------------------------

def _is_hero_shot(ev: dict) -> bool:
    qt = str(ev.get("quality_target") or "").upper()
    meta = ev.get("shot_metadata") or ev.get("metadata") or {}
    hero_flag = ev.get("hero_shot")
    return (
        hero_flag in (True, "true", "True", "1", "yes", "hero")
        or qt in ("HIGH", "FINAL")
        or str(meta.get("hero") or "").lower() in ("true", "1", "yes", "hero")
    )


def _variant_strategy(ev: dict, packet: dict) -> dict:
    """§33-34：6 风险因子（generation cost / shot importance / prompt uncertainty /
    continuity difficulty / human presence / complex motion）+ hero_shot。"""
    qt = str(ev.get("quality_target") or "").upper()
    res = ev.get("resolution") or {}
    try:
        res_h = int(res.get("h") or res.get("height") or 0)
    except (TypeError, ValueError):
        res_h = 0
    try:
        dur = float(ev.get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0

    hero_shot = _is_hero_shot(ev)
    subj = packet.get("subject") or {}
    who = str(subj.get("who_what") or "").lower()
    action = str(packet.get("subject_action") or "").lower()
    env_motion = packet.get("environment_motion") or {}
    motion_text = str(ev.get("motion") or "") + " " + action

    factors = {
        "generation_cost": qt in ("HIGH", "FINAL") or res_h >= 2160 or dur >= 8,
        "shot_importance": hero_shot or any(m in str(ev.get("purpose") or "").lower()
                                            for m in _IMPORTANCE_MARKERS),
        "prompt_uncertainty": not isinstance(ev.get("subject"), dict) or \
            not isinstance(ev.get("environment"), dict),
        "continuity_difficulty": bool(ev.get("continuity")) or bool(
            ev.get("start_frame_requirement")) and bool(ev.get("end_frame_requirement")),
        "human_presence": any(m in who for m in _HUMAN_MARKERS),
        "complex_motion": any(m in motion_text for m in _COMPLEX_MOTION_MARKERS) or any(
            str(env_motion.get(k) or "") for k in ("crowd", "water", "smoke")),
    }
    hits = sorted(k for k, v in factors.items() if v)
    two_to_four = len(hits) >= 3 or hero_shot
    risk = "HIGH" if two_to_four else ("MEDIUM" if len(hits) == 2 else "LOW")
    return {
        "range": "TWO_TO_FOUR" if two_to_four else "ONE_TO_TWO",
        "risk_level": risk,
        "hero_shot": bool(hero_shot),
        "rationale": "；".join(
            ["%s=%s" % (k, "yes" if v else "no") for k, v in factors.items()]
        ) + ("；hero_shot=true" if hero_shot else ""),
        "hit_factors": hits,
    }


# ---------------------------------------------------------------------------
# §10 purpose / 各 section 构造（确定性派生）
# ---------------------------------------------------------------------------

def _storyboard_beat(ev: dict) -> Optional[str]:
    for key in ("storyboard_beat", "beat", "scene_beat", "story_beat", "narrative_beat"):
        v = ev.get(key)
        if v:
            return str(v)
    sb = ev.get("storyboard")
    if isinstance(sb, dict):
        beat = _pick(sb, "beat", "purpose", "function", "节拍")
        if beat:
            return str(beat)
    return None


def _build_purpose(ev: dict) -> str:
    base = str(ev.get("purpose") or ev.get("visual_description") or "").strip()
    beat = _storyboard_beat(ev)
    if beat:
        func = "叙事功能：%s" % beat
    elif base:
        func = "叙事功能：承接/推进该镜头在叙事中的既定节拍（ev 未单列 storyboard beat，按 purpose 推导）"
    else:
        func = "叙事功能：为后续镜头提供必要的视觉与情绪铺垫"
    if base:
        return "%s。画面目标：%s" % (func, base)
    return func


def _build_subject(ev: dict, exact: bool, profiles: Optional[dict]) -> dict:
    subj_in = ev.get("subject")
    subject: dict = {"who_what": None, "prominence": None, "must_stay_stable": None}
    if isinstance(subj_in, dict):
        subject["who_what"] = _pick(subj_in, "who_what", "subject", "description")
        subject["prominence"] = _pick(subj_in, "prominence", "importance")
        subject["must_stay_stable"] = _pick(subj_in, "must_stay_stable", "stable")
    elif isinstance(subj_in, str):
        subject["who_what"] = subj_in
    if not subject["who_what"]:
        subject["who_what"] = ev.get("visual_description")
    if exact:
        for k, v in subject.items():
            subject[k] = _scrub_literal_text(v)
    return subject


def _build_environment(ev: dict, exact: bool) -> dict:
    env_in = ev.get("environment")
    if isinstance(env_in, dict):
        env = {k: v for k, v in env_in.items() if v is not None}
    elif isinstance(env_in, str):
        env = {"location": env_in}
    else:
        env = {}
    if exact:
        env = {k: _scrub_literal_text(v) for k, v in env.items()}
    return env


def _build_composition(ev: dict, overlay_reqs: list) -> dict:
    comp_in = ev.get("composition")
    if not isinstance(comp_in, dict):
        comp_in = {}
    reserved = ev.get("text_safe_area")
    if not reserved and overlay_reqs:
        reserved = "右 35% 画面保持安静，预留 overlay（§14）"
    composition = {
        "subject_placement": _pick(comp_in, "subject_placement", "placement")
                             or "主体现按 subject 描述自然放置（未指定，由画面目标推导）",
        "negative_space": _pick(comp_in, "negative_space")
                          or ("预留静区供 overlay（%s）" % reserved if reserved
                              else "按 visual hierarchy 留出呼吸空间（未指定）"),
        "visual_hierarchy": _pick(comp_in, "visual_hierarchy")
                            or "主体优先，环境次之，背景元素最后（未指定）",
        "depth_layers": _pick(comp_in, "depth_layers", "depth")
                        or "前景/中景/背景三层（未指定）",
        "safe_zones": _pick(comp_in, "safe_zones", "safe_area")
                      or ("生成画面预留静区：%s" % reserved if reserved else "无特殊安全区要求"),
        "intended_overlay_area": _pick(comp_in, "intended_overlay_area", "overlay_area")
                                 or ("overlay_requirements 存在 → 避开 %s，生成内容让出该区域"
                                     % reserved if reserved else "无 overlay 计划"),
    }
    return composition


def _build_camera(ev: dict) -> dict:
    """§15 camera 对象（5 键，不含 lens/movement——二者为 packet 顶层字段，FR-004）。

    lens 与 camera_movement 由 _camera_lens()/_camera_movement() 派生并落到 packet
    顶层（P6-01 generative-video-packet.schema.json：camera 对象 5 键 + 顶层 lens/
    camera_movement）。"""
    cam_in = ev.get("camera")
    if not isinstance(cam_in, dict):
        cam_in = {}
    return {
        "shot_size": _pick(cam_in, "shot_size", "size") or "未指定（按画面目标推导）",
        "height": _pick(cam_in, "height", "camera_height") or "未指定",
        "angle": _pick(cam_in, "angle") or "未指定",
        "movement_speed": _pick(cam_in, "movement_speed", "speed") or "medium",
        "stabilization": _pick(cam_in, "stabilization", "stabilization_style") or "steady",
    }


def _camera_lens(ev: dict) -> str:
    """§16 顶层 lens（6 枚举）：从 ev.camera 派生，缺省 NORMAL。"""
    cam_in = ev.get("camera")
    if not isinstance(cam_in, dict):
        cam_in = {}
    return _norm_enum(_pick(cam_in, "lens", "lens_character"), LENS_ENUM, default="NORMAL")


def _camera_movement(ev: dict) -> str:
    """§17 顶层 camera_movement（13 枚举）：从 ev.camera 派生，缺省 STATIC。"""
    cam_in = ev.get("camera")
    if not isinstance(cam_in, dict):
        cam_in = {}
    return _norm_enum(
        _pick(cam_in, "movement", "camera_movement", "motion"),
        CAMERA_MOVEMENT_ENUM, default="STATIC",
    )


def _build_lighting(ev: dict) -> dict:
    l_in = ev.get("lighting")
    if not isinstance(l_in, dict):
        l_in = {}
    return {
        "source_direction": _pick(l_in, "source_direction", "direction") or "未指定",
        "softness": _pick(l_in, "softness", "soft_hard") or "未指定",
        "contrast": _pick(l_in, "contrast") or "未指定",
        "temperature": _pick(l_in, "temperature") or "未指定",
        "practical": l_in.get("practical") or False,
        "volumetric": l_in.get("volumetric") or False,
        "shadows": _pick(l_in, "shadows", "shadow_behavior") or "未指定",
    }


def _map_motion_character(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in MOTION_CHARACTERS:
        return s
    for token, canon in _CHAR_SYNONYMS.items():
        if token in s:
            return canon
    return None


def _build_frame_state(req: Any, default_state: str, kind: str) -> dict:
    """§21：ev 有 start/end_frame_requirement 时生成明确首/尾帧状态描述。"""
    if isinstance(req, str):
        state = req.strip()
        if state:
            return {"state": state, "source": "ev_requirement", "kind": kind}
    elif isinstance(req, dict):
        state = _pick(req, "state", "description", "visual", "composition")
        if state:
            out = {"state": str(state).strip(), "source": "ev_requirement", "kind": kind}
            if req.get("changes_scene") is not None:
                out["changes_scene"] = bool(req.get("changes_scene"))
            return out
    return {"state": default_state, "source": "derived_default", "kind": kind}


def _build_continuity(ev: dict, packet: dict, profiles: Optional[dict]) -> dict:
    c_in = ev.get("continuity")
    if not isinstance(c_in, dict):
        c_in = {}
    subj = packet.get("subject") or {}
    env = packet.get("environment") or {}
    light = packet.get("lighting") or {}
    cam = packet.get("camera") or {}
    comp = packet.get("composition") or {}

    movement_direction = _pick(c_in, "movement_direction") or \
        _direction_token(_pick(c_in, "screen_direction")) or "未指定"
    continuity = {
        "subject_identity": _pick(c_in, "subject_identity") or subj.get("who_what") or "未指定",
        "wardrobe": _pick(c_in, "wardrobe") or subj.get("clothing") or "未指定",
        "environment": _pick(c_in, "environment") or env.get("location") or "未指定",
        "lighting": _pick(c_in, "lighting") or _join(
            (light.get("source_direction"), light.get("softness"), light.get("temperature"))
        ) or "未指定",
        "camera_direction": _pick(c_in, "camera_direction") or packet.get("camera_movement") or "未指定",
        "movement_direction": movement_direction,
        "screen_direction": _pick(c_in, "screen_direction") or movement_direction,
        "object_position": _pick(c_in, "object_position") or comp.get("subject_placement") or "未指定",
        "time_of_day": _pick(c_in, "time_of_day") or packet.get("time_of_day") or "未指定",
        "color": _pick(c_in, "color") or packet.get("color_direction") or "未指定",
    }
    # profiles 命中（§85-87 共享档案）：连续性与参考来源
    if profiles:
        char_ref = _pick(ev, "character_profile_ref", "character_profile")
        if char_ref and char_ref in profiles:
            prof = profiles[char_ref]
            ch = prof.get("character") or {}
            if ch.get("name"):
                continuity["subject_identity"] = str(ch["name"])
            if ch.get("appearance"):
                continuity["subject_identity"] = "%s（%s）" % (
                    continuity["subject_identity"], ch["appearance"])
            if ch.get("clothing"):
                continuity["wardrobe"] = str(ch["clothing"])
        env_ref = _pick(ev, "environment_profile_ref", "environment_profile")
        if env_ref and env_ref in profiles:
            prof = profiles[env_ref]
            en = prof.get("environment") or {}
            if en.get("architecture") or en.get("layout"):
                continuity["environment"] = _join(
                    (en.get("architecture"), en.get("layout"))) or continuity["environment"]
            if en.get("lighting"):
                continuity["lighting"] = str(en["lighting"])
    return continuity


def _classify_reference(src: dict) -> tuple:
    """把 reference source 归到 §24 的键位（确定性关键词映射）。"""
    kind = str(_pick(src, "type", "kind", "class", "role") or "").lower()
    if any(k in kind for k in ("character", "人物", "角色")):
        return "character_reference"
    if any(k in kind for k in ("environment", "场景", "环境", "location")):
        return "environment_reference"
    if any(k in kind for k in ("style", "风格", "style_frame", "style reference")):
        return "style_frame"
    if any(k in kind for k in ("product", "产品")):
        return "product_reference"
    if any(k in kind for k in ("previous", "上一帧", "previous_generated")):
        return "previous_generated_frame"
    return "reference_image"


def _build_reference_inputs(ev: dict, profiles: Optional[dict]) -> dict:
    """§24 reference_inputs（6 键位）：ref_id 一律 RF-###（P6-01 schema ^RF-\\d{3}$，FR-003）。"""
    refs = {k: [] for k in REFERENCE_KEYS}
    idx = 0
    for src in _as_list(ev.get("source_preferences")) + _as_list(ev.get("references")):
        if isinstance(src, str):
            src = {"path_or_url": src}
        if not isinstance(src, dict):
            continue
        path = _pick(src, "path_or_url", "path", "url", "file", "file_path")
        if not path:
            continue
        idx += 1
        cls = _classify_reference(src)
        refs[cls].append({
            "ref_id": "RF-%03d" % idx,
            "path_or_url": str(path),
            "purpose": str(_pick(src, "purpose", "note") or "参考素材（adapter 决定兼容性，§24）"),
            "required": _pick(src, "required", default=False) in (True, "true", "True", "yes"),
        })
    # 连续性档案的 reference_assets 进入对应键位（§86/§87）
    for pid, prof in (profiles or {}).items():
        ch = prof.get("character") or {}
        for asset in _as_list(ch.get("reference_assets")):
            idx += 1
            if isinstance(asset, str):
                asset = {"path_or_url": asset}
            if not isinstance(asset, dict):
                continue
            path = _pick(asset, "path_or_url", "path", "url", "file")
            if path:
                refs["character_reference"].append({
                    "ref_id": "RF-%03d" % idx,
                    "path_or_url": str(path),
                    "purpose": "character reference from %s（§86）" % pid,
                    "required": True,
                })
        en = prof.get("environment") or {}
        for frame in _as_list(en.get("reference_frames")):
            idx += 1
            if isinstance(frame, str):
                frame = {"path_or_url": frame}
            if not isinstance(frame, dict):
                continue
            path = _pick(frame, "path_or_url", "path", "url", "file")
            if path:
                refs["environment_reference"].append({
                    "ref_id": "RF-%03d" % idx,
                    "path_or_url": str(path),
                    "purpose": "environment reference from %s（§87）" % pid,
                    "required": True,
                })
    return refs


def _build_postproduction_plan(ev: dict, camera: dict, exact: bool, overlay_reqs: list) -> dict:
    pp_in = ev.get("postproduction") or {}
    if not isinstance(pp_in, dict):
        pp_in = {}
    audio = ev.get("audio_requirement")
    plan: dict = {}
    plan["crop"] = {
        "required": _pick(pp_in, "crop", default=False) in (True, "true", "True"),
        "note": "crop 计划：%s" % (_pick(pp_in, "crop_note", "crop_reason")
                                  or "无裁切计划，保留全画幅（如需 9:16/1:1 由后续裁剪）"),
    }
    plan["stabilization"] = {
        "required": str(camera.get("stabilization") or "").lower() in
                    ("handheld", "手持", "shaky"),
        "note": "stabilization：生成视频如轻微抖动，由后续稳定处理（§82 不自动过度处理）",
    }
    plan["speed"] = {
        "required": False,
        "note": "speed：无变速计划；如需 0.5x/2x 由后续 timeline 处理",
    }
    plan["color"] = {
        "required": False,
        "note": "color：Phase 6 不做 Final Grade（§48），仅记录源 look 供后续匹配",
    }
    plan["overlay"] = {
        "required": bool(overlay_reqs or exact),
        "note": ("overlay：精确信息层由 REMOTION/JY_NATIVE 承担（§7/§50），"
                 "生成画面为干净背景" if (overlay_reqs or exact)
                 else "overlay：无精确信息层需求"),
        "owner": "REMOTION/JY_NATIVE" if (overlay_reqs or exact) else None,
    }
    plan["mask"] = {
        "required": False,
        "note": "mask：如需抠像/ROTO，由后续工具处理（§81 记录意图，不自造跟踪引擎）",
    }
    plan["text"] = {
        "required": bool(exact),
        "note": ("text：精确文字/数字/标签层由文本层承担（REMOTION/JY_NATIVE），"
                 "生成画面禁止含文字" if exact else "text：无文字层需求"),
    }
    plan["grain"] = {
        "required": str(ev.get("style") or "").lower() in ("archival", "复古", "档案感"),
        "note": "grain：如项目风格需要胶片颗粒，由后续统一处理",
    }
    plan["sound"] = {
        "required": bool(audio),
        "note": "sound：音频策略见 EV.audio_requirement（KEEP/MUTE/EXTRACT/REPLACE，§84）；"
                "生成模型自带音频不得默认使用",
    }
    plan["transition"] = {
        "required": False,
        "note": "transition：转场归 Phase 7 装配决定，本 Packet 不写死",
    }
    return plan


def _build_model_prompt(packet: dict) -> str:
    """§确定性模板：英文，subject→environment→composition→camera→lighting→motion→style。
    缺省占位（"未指定" 等）在 prompt 中翻译成英文或省略，保证 prompt 全英文。"""
    subj = packet.get("subject") or {}
    env = packet.get("environment") or {}
    comp = packet.get("composition") or {}
    cam = packet.get("camera") or {}
    light = packet.get("lighting") or {}
    env_motion = packet.get("environment_motion") or {}

    def parts_sections(values: tuple) -> str:
        out = []
        for v in values:
            en = _prompt_en(str(v)) if v is not None else ""
            if en and en != "unspecified":
                out.append(en)
        return ", ".join(out)

    s_subject = parts_sections((subj.get("who_what"),
                                "prominence: %s" % subj["prominence"]
                                if subj.get("prominence") else "",
                                "must stay stable: %s" % subj["must_stay_stable"]
                                if subj.get("must_stay_stable") else ""))
    s_environment = parts_sections((
        env.get("location"), env.get("architecture"),
        "spatial scale: %s" % env["spatial_scale"] if env.get("spatial_scale") else "",
        env.get("foreground"), env.get("midground"), env.get("background"),
        "density: %s" % env["density"] if env.get("density") else "",
        env.get("weather"), env.get("atmosphere"),
        "materials: %s" % env["surface_materials"] if env.get("surface_materials") else ""))
    s_composition = parts_sections((comp.get("subject_placement"), comp.get("negative_space"),
                                    comp.get("visual_hierarchy"), comp.get("depth_layers"),
                                    comp.get("safe_zones"), comp.get("intended_overlay_area")))
    s_camera = "shot size %s, camera height %s, %s angle, %s lens, %s movement (%s speed), %s" % (
        _prompt_en(cam.get("shot_size") or "unspecified"),
        _prompt_en(cam.get("height") or "unspecified"),
        _prompt_en(cam.get("angle") or "unspecified"),
        _prompt_en(packet.get("lens") or "unspecified"),
        _prompt_en(packet.get("camera_movement") or "unspecified"),
        _prompt_en(cam.get("movement_speed") or "unspecified"),
        _prompt_en(cam.get("stabilization") or "unspecified"))
    s_lighting = parts_sections((
        "source %s" % light["source_direction"] if light.get("source_direction")
        and light["source_direction"] != "未指定" else "",
        "light quality %s" % light["softness"] if light.get("softness")
        and light["softness"] != "未指定" else "",
        "contrast %s" % light["contrast"] if light.get("contrast")
        and light["contrast"] != "未指定" else "",
        "color temperature %s" % light["temperature"] if light.get("temperature")
        and light["temperature"] != "未指定" else "",
        "practical lights" if light.get("practical") else "",
        "volumetric light" if light.get("volumetric") else "",
        "shadows: %s" % light["shadows"] if light.get("shadows")
        and light["shadows"] != "未指定" else ""))
    motion_parts = [packet.get("subject_action") or ""]
    em_active = _join("%s: %s" % (k, v) for k, v in env_motion.items()
                      if isinstance(v, str) and v.strip())
    if em_active:
        motion_parts.append("environment motion: %s" % em_active)
    motion_parts.append("motion character: %s" % packet.get("motion_character"))
    s_motion = _join(motion_parts)
    s_style = parts_sections((packet.get("mood"), packet.get("style"),
                              packet.get("material_character"), packet.get("color_direction")))

    lines = []
    lines.append("Subject: " + (s_subject or "not specified"))
    lines.append("Environment: " + (s_environment or "not specified"))
    lines.append("Composition: " + (s_composition or "not specified"))
    lines.append("Camera: " + s_camera)
    lines.append("Lighting: " + (s_lighting or "not specified"))
    lines.append("Motion: " + (s_motion or "not specified"))
    lines.append("Style: " + (s_style or "not specified"))
    return "\n".join(lines)


_EN_DEFAULTS = {
    "主体现按 subject 描述自然放置（未指定，由画面目标推导）":
        "subject placed naturally per the visual goal (unspecified)",
    "按 visual hierarchy 留出呼吸空间（未指定）":
        "breathing room per visual hierarchy (unspecified)",
    "主体优先，环境次之，背景元素最后（未指定）":
        "subject first, environment second, background last (unspecified)",
    "前景/中景/背景三层（未指定）":
        "three depth layers: foreground / midground / background (unspecified)",
    "无特殊安全区要求": "no special safe-zone requirement",
    "无 overlay 计划": "no overlay planned",
    "未指定（按画面目标推导）": "derived from visual goal (unspecified)",
    "未指定": "unspecified",
}


def _prompt_en(text: str) -> str:
    """把中文缺省占位翻译为英文（确定性映射）；其余内容原样保留。"""
    if not isinstance(text, str):
        return str(text)
    for zh, en in _EN_DEFAULTS.items():
        if zh in text:
            text = text.replace(zh, en)
    return text


def _build_negative_constraints(ev: dict) -> list:
    """ev.avoid + 硬规则基础项（§7 无文字需求时基础项仍保留：no text/watermark/logo）。"""
    out: list = ["no text", "no watermark", "no logo"]
    for item in _as_list(ev.get("avoid")) + _as_list(ev.get("avoid_list")):
        if item and str(item) not in out:
            out.append(str(item))
    return out


# ---------------------------------------------------------------------------
# §79/§91 prompt hash + versioning
# ---------------------------------------------------------------------------

def _prompt_spec(packet: dict) -> dict:
    """§79/§91：决定 prompt 的内容字段（purpose / 各 section / 技术参数 / variant）。
    运行态与落盘字段（packet_version / supersedes / generation_notes / hash 自身）不入 spec，
    保证版本比较只看"内容是否变化"。"""
    return {
        "purpose": packet.get("purpose"),
        "subject": packet.get("subject"),
        "environment": packet.get("environment"),
        "composition": packet.get("composition"),
        "framing": packet.get("framing"),
        "camera": packet.get("camera"),
        "lens": packet.get("lens"),
        "camera_movement": packet.get("camera_movement"),
        "subject_action": packet.get("subject_action"),
        "environment_motion": packet.get("environment_motion"),
        "lighting": packet.get("lighting"),
        "motion_character": packet.get("motion_character"),
        "start_frame": packet.get("start_frame"),
        "end_frame": packet.get("end_frame"),
        "text_safe_area": packet.get("text_safe_area"),
        "duration": packet.get("duration"),
        "fps": packet.get("fps"),
        "aspect_ratio": packet.get("aspect_ratio"),
        "resolution": packet.get("resolution"),
        "model_ready_prompt": packet.get("model_ready_prompt"),
        "negative_prompt": packet.get("negative_prompt"),
        "variant_strategy": {k: packet.get("variant_strategy", {}).get(k)
                             for k in ("range", "risk_level", "hero_shot")},
    }


def _version_packet(packet: dict, existing_packets: Optional[list]) -> tuple:
    """同 request_id 重建：hash 相同 → 沿用版本；hash 变化 → version+1 且 supersedes 指向旧版。"""
    rid = packet.get("request_id")
    same = [p for p in (existing_packets or [])
            if isinstance(p, dict) and p.get("request_id") == rid
            and isinstance(p.get("packet_version"), int)]
    if not same:
        return 1, None
    latest = max(same, key=lambda p: int(p.get("packet_version") or 1))
    if latest.get("prompt_hash") == packet.get("prompt_hash"):
        return int(latest.get("packet_version") or 1), latest.get("supersedes")
    new_version = int(latest.get("packet_version") or 1) + 1
    old_path = latest.get("_file_path") or "%s_v%d.json" % (
        latest.get("packet_id") or packet.get("packet_id"), latest.get("packet_version") or 1)
    return new_version, old_path


def _packet_id_for(request_id: str) -> str:
    """确定性 GV-###：取 request_id 数字部分末 3 位（EV-001 → GV-001）。"""
    digits = re.sub(r"\D", "", str(request_id))
    if not digits:
        digits = "0"
    return "GV-%03d" % (int(digits[-3:]) % 1000)


# ---------------------------------------------------------------------------
# 主入口：build_packet
# ---------------------------------------------------------------------------

def build_packet(ev: dict, visual_bible: Optional[dict] = None,
                 profiles: Optional[dict] = None,
                 adjacent_shots: Optional[list] = None,
                 existing_packets: Optional[list] = None,
                 conflict_out_dir: Optional[str] = None) -> dict:
    """EV（External Visual Request）→ GV Production Packet。

    参数：
        ev             已批准的 EV 请求 dict（P6-01 external-visual-request）
        visual_bible   Visual Bible dict（§20 motion_character 继承 / §19 lighting）
        profiles       连续性档案 dict {profile_id: profile}（§85-87 共享）
        adjacent_shots 相邻镜头信息 list（§23 screen_direction 检查），元素为 dict：
                       {shot_id, relation(previous/next), movement_direction, director_intent, ...}
        existing_packets 同一 request_id 的历史 Packet 列表（§91 版本化）
        conflict_out_dir 可选：§41 PRODUCTION_CONFLICT 结构化记录落盘目录（FR-025：
                       PC-### 只写独立文件，generation_notes 只引用 id，不塞 JSON）。

    返回：GV Packet dict（provider-neutral，无任何具体模型名）。
    """
    if not isinstance(ev, dict):
        raise TypeError("build_packet 需要 EV dict")
    request_id = str(ev.get("request_id") or "")
    if not REQUEST_ID_RE.match(request_id):
        raise ValueError("request_id 必须匹配 EV-###，得到 %r" % request_id)
    bible = visual_bible if isinstance(visual_bible, dict) else {}
    profiles = profiles if isinstance(profiles, dict) else {}

    # —— §7 no_exact_text 检测 ——
    overlay_reqs = _as_list(ev.get("overlay_requirements"))
    exact_classes = _detect_exact_text(ev)
    exact = bool(exact_classes)

    packet: dict = {}
    packet["packet_id"] = _packet_id_for(request_id)
    packet["request_id"] = request_id
    packet["shot_id"] = ev.get("shot_id")
    packet["layer_id"] = ev.get("layer_id")

    # §10 purpose_first
    packet["purpose"] = _build_purpose(ev)

    # 技术参数
    packet["duration"] = ev.get("duration")
    packet["aspect_ratio"] = ev.get("aspect_ratio")
    res = ev.get("resolution")
    if isinstance(res, dict):
        packet["resolution"] = {"w": res.get("w") or res.get("width"),
                                "h": res.get("h") or res.get("height")}
    else:
        packet["resolution"] = {"w": None, "h": None}
    packet["fps"] = ev.get("fps")

    # 画面各 section
    packet["subject"] = _build_subject(ev, exact, profiles)
    packet["environment"] = _build_environment(ev, exact)
    packet["composition"] = _build_composition(ev, overlay_reqs)
    packet["camera"] = _build_camera(ev)
    # §16/§17：lens 与 camera_movement 为 packet 顶层字段（FR-004；camera 对象内不含）
    packet["lens"] = _camera_lens(ev)
    packet["camera_movement"] = _camera_movement(ev)
    packet["framing"] = "%s framing; subject placement: %s; negative space: %s" % (
        packet["camera"]["shot_size"],
        packet["composition"]["subject_placement"],
        packet["composition"]["negative_space"],
    )
    packet["subject_action"] = _pick(ev, "subject_action") or \
        (str(ev.get("motion")) if isinstance(ev.get("motion"), str) else None) or \
        "主体按叙事节拍自然行动（未指定精确动作）"

    # §18 organic_motion：8 类环境动效单独描述
    env_motion_in = ev.get("environment_motion")
    if isinstance(env_motion_in, dict):
        em = env_motion_in
    else:
        em = {}
    env_obj = ev.get("environment")
    if isinstance(env_obj, dict) and isinstance(env_obj.get("environmental_motion"), dict):
        em = {**em, **env_obj["environmental_motion"]}
    packet["environment_motion"] = {
        k: (str(em.get(k)) if em.get(k) is not None else "")
        for k in ("people", "cloth", "hair", "smoke", "water", "plants",
                  "crowd", "ambient_objects")
    }

    # §19 lighting
    packet["lighting"] = _build_lighting(ev)

    # 风格 / 时间 / mood / material / color
    packet["time_of_day"] = ev.get("time_of_day") or bible.get("time_of_day") or "未指定"
    packet["mood"] = ev.get("mood") or "未指定"
    packet["style"] = ev.get("style") or bible.get("ai_video_treatment") or "未指定"
    packet["material_character"] = ev.get("material_character") or bible.get("material") or "未指定"
    packet["color_direction"] = ev.get("color_direction") or bible.get("color") or "未指定"

    # §20 motion_character：继承 Visual Bible；缺省 restrained
    raw_mc = ev.get("motion_character") or bible.get("motion_character")
    mc = _map_motion_character(raw_mc) or "restrained"
    packet["motion_character"] = mc

    # §21 start/end frame
    packet["start_frame"] = _build_frame_state(
        ev.get("start_frame_requirement"),
        "镜头起始：按上述 composition 与 camera 状态平稳起画（无特殊首帧要求）",
        "START")
    packet["end_frame"] = _build_frame_state(
        ev.get("end_frame_requirement"),
        "镜头结束：动作/运动收敛于上述画面状态（无特殊尾帧要求）",
        "END")

    # §22 continuity 10 项（profiles 共享）
    packet["continuity"] = _build_continuity(ev, packet, profiles)

    # §14 text_safe_area / overlay_safe_area
    reserved = ev.get("text_safe_area") or (
        "右 35% 画面保持安静，预留 overlay（§14）" if overlay_reqs else None)
    packet["text_safe_area"] = reserved or "无 overlay 计划，全画幅可用"
    packet["overlay_safe_area"] = reserved or "无 overlay 计划"

    # §49 postproduction_plan（十项布尔+说明）
    packet["postproduction_plan"] = _build_postproduction_plan(ev, packet["camera"],
                                                               exact, overlay_reqs)

    # negative_constraints
    packet["negative_constraints"] = _build_negative_constraints(ev)
    packet["negative_prompt"] = ", ".join(packet["negative_constraints"])

    # model_ready_prompt（模板化、确定性）
    packet["model_ready_prompt"] = _build_model_prompt(packet)

    # §33-34 variant_strategy
    vs = _variant_strategy(ev, packet)
    packet["variant_strategy"] = {
        "range": vs["range"], "risk_level": vs["risk_level"],
        "hero_shot": vs["hero_shot"], "rationale": vs["rationale"],
    }
    packet["recommended_variant_count"] = 3 if vs["range"] == "TWO_TO_FOUR" else 2

    # §24 reference_inputs（7 类 / 6 键位）
    packet["reference_inputs"] = _build_reference_inputs(ev, profiles)

    # generation_notes
    notes: list = []
    if exact:
        notes.append("text_policy: classes=[%s] delegated_to=[REMOTION, JY_NATIVE]; "
                     "generated frame must be text-free（§7/§49）" % ",".join(exact_classes))
    cam_raw = ev.get("camera")
    raw_lens = _pick(cam_raw, "lens", "lens_character") if isinstance(cam_raw, dict) else None
    if raw_lens and raw_lens != packet["lens"]:
        notes.append("camera: lens 原始值 %r 非 6 枚举，仅记录类型 %s（§16 不编造焦段）"
                     % (raw_lens, packet["lens"]))
    if raw_mc and raw_mc != mc:
        notes.append("motion_character: 输入 %r → 归一化为 %r（§20；缺省 restrained，"
                     "禁止默认 dramatic cinematic）" % (raw_mc, mc))
    if not raw_mc:
        notes.append("motion_character: 未提供 Visual Bible / ev 值，取 restrained（§20）")

    # §23 screen_direction
    current_dir = packet["continuity"].get("movement_direction")
    if adjacent_shots:
        for adj in adjacent_shots:
            if not isinstance(adj, dict):
                continue
            relation = str(_pick(adj, "relation", "position", "role") or "").lower()
            ctx = {k: adj.get(k) for k in
                   ("shot_id", "movement_direction", "screen_direction", "notes")
                   if adj.get(k) is not None}
            ctx["relation"] = relation
            if relation.startswith("prev") or relation in ("previous", "before", "上"):
                packet["previous_shot_context"] = ctx
            elif relation.startswith("next") or relation in ("next", "after", "下"):
                packet["next_shot_context"] = ctx
        for w in screen_direction_warnings(current_dir, adjacent_shots):
            notes.append(w)
    if adjacent_shots and not any(n.startswith("screen_direction") for n in notes):
        notes.append("screen_direction: 与相邻镜头无运动方向冲突（§23）")

    # §40 overload 检测 + §41 PRODUCTION_CONFLICT
    od = detect_overload(packet)
    if od["verdict"] == "OVERLOAD":
        notes.append("overload: OVERLOAD hits=[%s]（≥4/7）" % ",".join(od["hit_factors"]))
        split = [s for s in od["suggestions"] if s["action"] == "split_shot"]
        if split:
            conflict_id = _conflict_id(request_id)
            conflict = {
                "record_id": conflict_id,
                "request_id": request_id,
                "conflict_type": "DESIGN_UNFEASIBLE",
                "request": "shot %s 生成提示词过载：同时要求 %s（§40）"
                           % (packet.get("shot_id"), ", ".join(od["hit_factors"])),
                "problem": "单镜头 prompt 同时承担 %d/7 个高要求维度（%s），生成模型难以稳定实现"
                           % (od["hits"], ", ".join(od["hit_factors"])),
                "technical_reason": "复杂场景+复杂运镜+多人物+精确动作+背景行为+特殊灯光+复杂"
                                    "结束帧 叠加，单条 prompt 超载，易出现伪影/漂移/身份不一致",
                "visual_impact": "直接生成需要人工大量返修，且跨镜头一致性无法保证",
                "alternatives": [s["reason"] for s in od["suggestions"]],
                "recommended_alternatives": [s["reason"] for s in split],
                "approval_required": True,
            }
            # FR-025：结构化记录只落独立 PC-###.json（调用方给 conflict_out_dir 时），
            # generation_notes 只引用记录 id，禁止 JSON 序列化进 notes。
            if conflict_out_dir:
                _write_conflict_record(conflict, conflict_id, conflict_out_dir)
            notes.append("PRODUCTION_CONFLICT %s approval_required=true"
                         "（结构化记录见独立文件 %s.json，§41/FR-025）"
                         % (conflict_id, conflict_id))
        else:
            notes.append("overload_suggestions: %s"
                         % "; ".join("%s: %s" % (s["action"], s["reason"])
                                     for s in od["suggestions"]))
    else:
        notes.append("overload: none")

    # profiles 共享标记（§85-87）
    if profiles:
        char_ref = _pick(ev, "character_profile_ref", "character_profile")
        env_ref = _pick(ev, "environment_profile_ref", "environment_profile")
        if char_ref in profiles:
            notes.append("continuity: subject_identity 共享档案 %s（§86）" % char_ref)
        if env_ref in profiles:
            notes.append("continuity: environment 共享档案 %s（§87）" % env_ref)

    packet["generation_notes"] = notes

    # §36 review_criteria（18 维度；exact 时强制 text_artifacts）
    packet["review_criteria"] = list(REVIEW_DIMENSIONS)

    # §79/§91 prompt hash + version
    packet["prompt_hash"] = _sha256_spec(_prompt_spec(packet))
    packet["supersedes"] = None
    version, supersedes = _version_packet(packet, existing_packets)
    packet["packet_version"] = version
    packet["supersedes"] = supersedes
    notes.append("packet_version: %d; supersedes: %s" % (version, supersedes or "none"))

    # §7 硬规则最终强制（幂等）
    packet = enforce_no_exact_text(packet)
    # FR-006/FR-013：输出前统一 strip None（subject.*/lighting.*/supersedes 等
    # 值为 None 的键省略不输出，不向 schema 加 null）。
    return _strip_none(packet)


# ---------------------------------------------------------------------------
# P6-01 字段表核对（AC-4；P6-01 完成后用 schema 校验替代）
# ---------------------------------------------------------------------------

def validate_packet_fields(packet: dict) -> dict:
    """按 P6-01 generative-video-packet 字段表人工核对（draft-07 子集语义）：
    required 字段存在性 + 枚举 + 结构键位。返回 {valid, errors, warnings}。"""
    errors: list = []
    warnings: list = []
    if not isinstance(packet, dict):
        return {"valid": False, "errors": ["packet 必须是 dict"], "warnings": []}
    for field in _PACKET_REQUIRED:
        if field not in packet:
            errors.append("缺少 required 字段: %s" % field)
        elif packet.get(field) is None:
            warnings.append("required 字段 %s 值为 null（待补全）" % field)
    if not PACKET_ID_RE.match(str(packet.get("packet_id") or "")):
        errors.append("packet_id 必须匹配 GV-###")
    if not isinstance(packet.get("packet_version"), int) or packet["packet_version"] < 1:
        errors.append("packet_version 必须为正整数（从 1 起）")
    if packet.get("lens") not in LENS_ENUM:
        errors.append("lens=%r 不在 6 枚举内" % packet.get("lens"))
    if packet.get("camera_movement") not in CAMERA_MOVEMENT_ENUM:
        errors.append("camera_movement=%r 不在 13 枚举内" % packet.get("camera_movement"))
    vs = packet.get("variant_strategy") or {}
    if vs.get("range") not in VARIANT_RANGES:
        errors.append("variant_strategy.range=%r 不在 2 枚举内" % vs.get("range"))
    if vs.get("risk_level") not in RISK_LEVELS:
        errors.append("variant_strategy.risk_level=%r 不在 3 枚举内" % vs.get("risk_level"))
    cont = packet.get("continuity") or {}
    for k in CONTINUITY_KEYS:
        if k not in cont:
            errors.append("continuity 缺 %s（§22 十项）" % k)
    pp = packet.get("postproduction_plan") or {}
    for k in POSTPRODUCTION_KEYS:
        if k not in pp:
            errors.append("postproduction_plan 缺 %s（§49 十项）" % k)
        elif not isinstance(pp[k], dict) or "required" not in pp[k]:
            errors.append("postproduction_plan.%s 必须是 {required, note}（§49 布尔+说明）" % k)
    comp = packet.get("composition") or {}
    for k in _COMPOSITION_KEYS:
        if k not in comp:
            errors.append("composition 缺 %s（§13 六键）" % k)
    refs = packet.get("reference_inputs") or {}
    for k in REFERENCE_KEYS:
        if k not in refs:
            errors.append("reference_inputs 缺 %s（§24）" % k)
        elif not isinstance(refs[k], list):
            errors.append("reference_inputs.%s 必须为数组（§24）" % k)
    return {"valid": not errors, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

try:  # scripts/registry.py 为 stdlib 实现（minimal YAML + JSON），Phase-4 已验证
    from scripts.registry import load_json_or_yaml as _load_any  # type: ignore
except Exception:  # pragma: no cover
    _load_any = None


def _load_ev_file(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError("EV 文件不存在: %s" % path)
    if _load_any is not None:
        try:
            data = _load_any(path)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("EV 文件必须是一个对象: %s" % path)
    return data


def _load_profiles_dir(directory: Optional[str]) -> dict:
    out: dict = {}
    if not directory:
        return out
    d = Path(directory)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("profile_id"):
            out[str(data["profile_id"])] = data
    return out


def _load_existing_packets(out_dir: Path, request_id: str) -> list:
    found: list = []
    if not out_dir.is_dir():
        return found
    for f in sorted(out_dir.glob("GV-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("request_id") == request_id:
            data["_file_path"] = str(f)
            found.append(data)
    return found


def _cli_main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m modules.external-visual.packet_builder",
        description="EV-### → GV-### Generative Video Production Packet（P6-2）")
    ap.add_argument("ev", help="EV 请求 JSON/YAML 路径")
    ap.add_argument("--bible", default=None, help="Visual Bible JSON 路径（§20 继承）")
    ap.add_argument("--profiles", default=None, help="连续性档案目录（CP-CHAR/CP-ENV 等）")
    ap.add_argument("--out", default=None, help="Packet 输出路径（缺省 stdout）")
    ap.add_argument("--json", action="store_true", help="stdout 输出 JSON")
    args = ap.parse_args(argv)

    ev = _load_ev_file(Path(args.ev))
    bible = None
    if args.bible:
        bible = json.loads(Path(args.bible).read_text(encoding="utf-8"))
    profiles = _load_profiles_dir(args.profiles)

    existing: list = []
    if args.out:
        existing = _load_existing_packets(Path(args.out).parent, str(ev.get("request_id") or ""))

    packet = build_packet(ev, bible, profiles, None, existing_packets=existing,
                          conflict_out_dir=str(Path(args.out).parent) if args.out else None)
    text = json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
        print("packet written: %s (version %s)" % (out_path, packet["packet_version"]),
              file=sys.stderr)
    if args.json or not args.out:
        sys.stdout.write(text + "\n")
    return 0


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    ev = {
        "request_id": "EV-001", "shot_id": "S025", "layer_id": "S025-L01",
        "purpose": "Create a short emotional transition from abstract AI memory "
                   "to a physical spatial metaphor.",
        "duration": 6, "aspect_ratio": "16:9",
        "resolution": {"w": 1920, "h": 1080}, "fps": 30,
        "visual_description": "dreamlike memory museum",
        "subject": {"who_what": "an elderly man in a trench coat",
                    "prominence": "main subject"},
        "environment": {"location": "memory museum hall", "density": "medium"},
    }
    checks = [
        build_packet(ev)["purpose"].startswith("叙事功能"),
        build_packet(ev)["motion_character"] == "restrained",
        build_packet(ev)["lens"] in LENS_ENUM,
        build_packet(ev)["camera_movement"] in CAMERA_MOVEMENT_ENUM,
        build_packet(ev)["variant_strategy"]["range"] in VARIANT_RANGES,
        len(build_packet(ev)["continuity"]) >= 10,
        len(build_packet(ev)["postproduction_plan"]) == 10,
        detect_overload(build_packet(ev))["verdict"] == "OK",
        build_packet(ev) == build_packet(ev),  # 确定性
        build_packet(ev)["prompt_hash"] == build_packet(ev)["prompt_hash"],
    ]
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError("packet_builder selftest check #%d failed" % i)
    print("packet_builder selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(_cli_main())
