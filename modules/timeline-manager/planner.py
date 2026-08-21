#!/usr/bin/env python3
"""planner.py — Timeline Planner（Phase-7 Prompt §21-31/§49-52/§57-88；P7-3）.

把 Storyboard + Routing Plan + Asset Package + Timeline Handoff + Audio Map +
Editability Plan 装配成 **Backend-neutral 的 TIMELINE_MANIFEST**（§12-13 真相来源，
不围绕剪映 JSON 写死）。本模块只产 Manifest / 冲突 / 提案 / MAP 引用与 backend_metadata
提示；pyJianYingDraft draft 生成归 P7-5（Backend 调用）。

核心不变量（对应 PHASE7_PROMPT）：
- §23 Planner 不重新导演：不改 Storyboard 时长；技术性时间冲突只输出 TLC-###（§24 九字段）。
- §26-27 帧安全计时：全片时序以**整数帧**为 Canonical Timing，秒→帧只做一次换算，
  之后纯整数累积，杜绝浮点漂移。
- §8/§130 复杂连续 Motion 不拆：continuity_group 整体作为一个 Clip 进入时间线。
- §7 可编辑项保持可编辑：subtitle/B-roll/图片时长/基础标题默认 editable=true；
  complex motion（Remotion 资产）按 §33-35 asset_slot 可整体替换（ASSET_REPLACEABLE）。
- §12-13 Backend-neutral：Manifest 不含剪映专属结构；backend 语义只出现在
  backend / preferred_timeline_backend / backend_capabilities / backend_mapping /
  backend_metadata。
- §74 默认转场 CUT 并写入决策。
- §50-52 keyframe 预算超限 / 过度简单运动 → 只出 TIMELINE_OPTIMIZATION_PROPOSAL 提案，
  不私改 route。

技术约束：Python 3 stdlib only；无 LLM；无联网；确定性（同输入两次字节一致）。
本文件同时提供 time_utils（§28：frames↔seconds↔backend_unit↔timecode）。

包导入约定：`modules/timeline-manager` 是连字符包，兄弟模块一律 importlib 全名加载
（同 adapters/generative-video / modules/external-visual 约定）。
"""

from __future__ import annotations

import importlib as _importlib
import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

# 连字符包：兄弟模块 templates.py 用 importlib 全名加载
_templates_mod = _importlib.import_module("modules.timeline-manager.templates")

# ---------------------------------------------------------------------------
# ID 模式（P7-2 SCHEMA_CONTRACT7 ID 总表；禁止自造）
# ---------------------------------------------------------------------------
TL_ID_RE = re.compile(r"^TL-\d{3}$")
TR_ID_RE = re.compile(r"^TR-\d{3}$")
TC_ID_RE = re.compile(r"^TC-\d{3}$")
AS_ID_RE = re.compile(r"^AS-\d{3}$")
TLC_ID_RE = re.compile(r"^TLC-\d{3}$")
MK_ID_RE = re.compile(r"^MK-\d{3}$")
KF_ID_RE = re.compile(r"^KF-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")
SHOT_ID_RE = re.compile(r"^S\d{3}$")

# ---------------------------------------------------------------------------
# 策略常量（确定性；说明见 REPORT.md notes）
# ---------------------------------------------------------------------------
#: §49 keyframe budget：单 Clip 关键帧预算（Planner 层策略值）。P7-1 能力报告未给
#: 数值，此处定 50（§49 反例是"一个简单元素 200 个 keyframe"）；P7-4 Adapter 可读取。
KEYFRAME_BUDGET = 50
#: 秒→帧换算的容差（帧）：Storyboard 显式 start_time 与整数累积差超过该值才记 TLC。
TIMING_TOLERANCE_FRAMES = 2
#: AUTO 代理策略按 bitrate（bps）判定"大素材走代理"的阈值。
AUTO_PROXY_BITRATE_THRESHOLD = 4_000_000
#: AUDIO_DIRECTION ducking 缺省占位（只在 audio_direction 提供时使用，不硬编码）。
DUCKING_DEFAULTS = {"vo_active_reduction_db": -4.0, "important_phrase_reduction_db": -6.0,
                    "restore_db": 0.0}

# ---------------------------------------------------------------------------
# P7-1 能力矩阵 fallback（仅当 adapters.pyjianyingdraft 无法 import 时使用；
# 内容与 work/p7-1/BACKEND_CAPABILITY_REPORT.md §2 完全一致）
# ---------------------------------------------------------------------------
_FALLBACK_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "basic_video": {"supported": True, "fallback": None, "evidence": "video_segment.py:426"},
    "multi_track": {"supported": True, "fallback": None, "evidence": "track.py:30"},
    "text": {"supported": True, "fallback": None, "evidence": "text_segment.py:255"},
    "subtitle": {"supported": True, "fallback": "文本轨模拟（auto_wrapping→type=subtitle）",
                 "evidence": "text_segment.py:446"},
    "position_keyframe": {"supported": True, "fallback": None, "evidence": "keyframe.py:39-42"},
    "scale_keyframe": {"supported": True, "fallback": None, "evidence": "keyframe.py:46-51"},
    "rotation_keyframe": {"supported": True, "fallback": None, "evidence": "keyframe.py:43"},
    "opacity_keyframe": {"supported": True, "fallback": None, "evidence": "keyframe.py:53-54"},
    "volume_keyframe": {"supported": True, "fallback": None, "evidence": "keyframe.py:62-63"},
    "transition": {"supported": True, "fallback": None, "evidence": "video_segment.py:605"},
    "filter": {"supported": True, "fallback": None, "evidence": "video_segment.py:544"},
    "mask": {"supported": True, "fallback": None, "evidence": "video_segment.py:569"},
    "blend_mode": {"supported": True, "fallback": None, "evidence": "video_segment.py:557"},
    "effect_parameter_keyframe": {"supported": False, "fallback": "Remotion 烘焙 / 采样到父元素变换关键帧",
                                  "evidence": "video_segment.py:191"},
    "bezier_easing": {"supported": False, "fallback": "采样生成离散关键帧（§47-48）",
                      "evidence": "keyframe.py:23-34"},
    "custom_motion_path": {"supported": False, "fallback": "Remotion 烘焙（§51）",
                           "evidence": "keyframe.py:23-34"},
    "template_import": {"supported": True, "fallback": "新版本需 fallback_loader；不可读生成新版本",
                        "evidence": "draft_content_loader.py:11"},
}

#: 轨道类型→排序权重（动态补轨时保持视觉轨/文字轨/音频轨分组顺序，§132 Track Cleanliness）
_TYPE_RANK = {
    "VIDEO_MAIN": 0, "VIDEO_BROLL": 1, "VIDEO_MOTION": 2, "VIDEO_3D": 3,
    "VIDEO_AI": 4, "VIDEO_OVERLAY": 5, "IMAGE": 6, "GRAPHIC": 7, "TEXT": 8,
    "SUBTITLE": 9, "UTILITY": 10, "VOICEOVER": 11, "MUSIC": 12, "SFX": 13,
    "AMBIENCE": 14,
}

#: 资产类型→目标轨道类型（无 hint 时的确定性归类；§15/§22）
_MOTION_TYPES = {
    "MOTION_CLIP", "INFOGRAPHIC", "UI_COMPONENT", "ANIMATED_TEXT",
    "PARTICLE_LAYER", "FULL_SCENE", "DECORATIVE_ELEMENT", "TRANSITION_ASSET",
    "MOTION", "MOTION_GRAPHIC",
}
_OVERLAY_TYPES = {"TRANSPARENT_OVERLAY"}
_AI_TYPES = {"GENERATIVE_VIDEO", "AI_VIDEO", "VIDEO_AI", "AI_GENERATED", "GENERATIVE"}

#: handoff/资产 timeline_hint 的轨道 token → 轨道类型（大小写不敏感）
_TRACK_TOKEN_MAP: Dict[str, str] = {
    "V1": "VIDEO_MAIN", "V1_MAIN": "VIDEO_MAIN", "MAIN": "VIDEO_MAIN",
    "VIDEO": "VIDEO_MAIN", "V2": "VIDEO_BROLL", "V2_BROLL": "VIDEO_BROLL",
    "BROLL": "VIDEO_BROLL", "B-ROLL": "VIDEO_BROLL", "V3": "VIDEO_MOTION",
    "V3_MOTION": "VIDEO_MOTION", "MOTION": "VIDEO_MOTION", "MOTION_GRAPHIC": "VIDEO_MOTION",
    "V4": "VIDEO_OVERLAY", "V4_OVERLAY": "VIDEO_OVERLAY", "OVERLAY": "VIDEO_OVERLAY",
    "V5": "IMAGE", "V5_IMAGE": "IMAGE", "IMAGE": "IMAGE", "PHOTO": "IMAGE",
    "ARCHIVE": "IMAGE", "GRAPHIC": "GRAPHIC", "MAP": "GRAPHIC",
    "T1": "TEXT", "T1_TITLES": "TEXT", "TITLES": "TEXT", "TITLE": "TEXT",
    "TEXT": "TEXT", "LABEL": "TEXT", "T2": "SUBTITLE", "T2_SUBTITLES": "SUBTITLE",
    "SUBTITLE": "SUBTITLE", "A1": "VOICEOVER", "A1_VO": "VOICEOVER",
    "VO": "VOICEOVER", "VOICEOVER": "VOICEOVER", "VOICE": "VOICEOVER",
    "A2": "MUSIC", "A2_MUSIC": "MUSIC", "MUSIC": "MUSIC",
    "A3": "SFX", "A3_SFX": "SFX", "SFX": "SFX", "A4": "AMBIENCE",
    "A4_AMBIENCE": "AMBIENCE", "AMBIENCE": "AMBIENCE", "AMB": "AMBIENCE",
}

# ---------------------------------------------------------------------------
# time_utils（§28 统一时间转换；fps 一律从 config 读）
#
# FR-006 架构裁定（rv-P7-1b FR-006）：帧↔微秒换算权威实现位于本模块
# ``to_backend_unit``（round-half-even，与 Phase 5 modules/production/motion.py:294
# ``round(duration*fps)`` 一致）。motion.py ``frames_to_us`` 与 backend.py
# ``_frames_to_us`` 均 importlib 加载本模块，三处同源。
# ---------------------------------------------------------------------------

def seconds_to_frames(seconds: Optional[float], fps: int) -> Optional[int]:
    """秒 → 整数帧（一次换算；round-half-up，避免 0.1*30=3.0000...0004 漂移）。"""
    if seconds is None:
        return None
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return None
    if s < 0:
        return None
    return int(math.floor(s * fps + 0.5))


def frames_to_seconds(frames: Optional[int], fps: int) -> Optional[float]:
    """整数帧 → 秒（保留 6 位）。"""
    if frames is None:
        return None
    if fps <= 0:
        raise ValueError("fps 必须为正整数")
    return round(int(frames) / float(fps), 6)


def to_backend_unit(frames: Optional[int], fps: int, unit: str = "us") -> Optional[int]:
    """帧 → 后端时间单位（§28）。pyJianYingDraft 用微秒（us），VectCut 可能用其它；
    默认返回整数微秒，供 P7-5 Adapter 统一换算。

    **换算权威实现（FR-006）**：帧↔微秒的单一权威入口，round-half-even
    （``int(round(sec*1e6))``，与 Phase 5 motion.py:294 ``round`` 一致）。
    motion.py ``frames_to_us`` 与 backend.py ``_frames_to_us`` 均委托本函数。
    """
    sec = frames_to_seconds(frames, fps)
    if sec is None:
        return None
    if unit == "us":
        return int(round(sec * 1_000_000))
    if unit == "ms":
        return int(round(sec * 1_000))
    if unit == "ns":
        return int(round(sec * 1_000_000_000))
    if unit == "s":
        return int(round(sec))
    raise ValueError(f"未知时间单位: {unit}")


def timecode(frames: Optional[int], fps: int) -> str:
    """帧 → SMPTE 风格时间码 'HH:MM:SS:FF'。

    fps 必须为**整数**（§26-27 整数帧基准）。非整数帧率（如 NTSC 29.97）明确拒绝并
    抛 ``ValueError``，本模块不建模 drop-frame 时间码——FR-004 验证：29.97 作为 float
    fps 传入时 ``ff:02d`` 曾抛 ``ValueError: Unknown format code 'd' for object of
    type 'float'``；此处改为显式校验，避免外部调用方误传 float fps 时崩溃位置难定位。
    （Planner 内部由 ``_normalize_config`` 强制 ``fps = int(...)``，不会走到此分支。）
    """
    if frames is None:
        return "--:--:--:--"
    try:
        fps_int = int(fps)
    except (TypeError, ValueError):
        raise ValueError(
            "timecode fps 必须为整数，收到 %r；NTSC 非整数帧率（如 29.97）需先取整"
            "（FR-004，本模块不建模 drop-frame）" % (fps,)) from None
    if fps_int <= 0 or (isinstance(fps, (int, float)) and fps_int != fps):
        raise ValueError(
            "timecode fps 必须为正整数，收到 %r；NTSC 非整数帧率（如 29.97）需先取整"
            "（FR-004，本模块不建模 drop-frame）" % (fps,))
    total = max(0, int(frames))
    ff = total % fps_int
    total_s = total // fps_int
    hh = total_s // 3600
    mm = (total_s % 3600) // 60
    ss = total_s % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def parse_timecode(value: Any) -> Optional[float]:
    """时间码/数字 → 秒（float）。

    支持：
    - 'HH:MM:SS.mmm'（三段）→ 时分秒；
    - 'MM:SS.mmm'（两段）→ 分秒（footage hint 的 '00:27.0' = 27s）；
    - 'MM:SS 后接说明文字'（如 '00:02 卡片消失'）→ 取前导时间码；
    - 纯数字秒（'4.2' / 16.1）。
    解析失败返回 None（不抛错）。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", ".")
    if not s:
        return None
    m = re.match(r"^(\d{1,3}):(\d{1,2})(?::(\d{1,2}))?(?:\.(\d{1,6}))?", s)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        frac = float("0." + m.group(4)) if m.group(4) else 0.0
        if m.group(3) is not None:
            return a * 3600.0 + b * 60.0 + int(m.group(3)) + frac
        return a * 60.0 + b + frac
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _get_num(d: Any, *keys: str, default: Optional[float] = None) -> Optional[float]:
    if not isinstance(d, dict):
        return default
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        if isinstance(v, str):
            p = parse_timecode(v)
            if p is not None:
                return p
    return default


def _normalize_enum(value: Any, enum: Tuple[str, ...], default: str) -> str:
    if value is None:
        return default
    v = str(value).strip().upper()
    return v if v in enum else default


def _load_capabilities() -> Dict[str, Dict[str, Any]]:
    """加载 P7-1 能力矩阵（机器可读版在 adapters.pyjianyingdraft）；import 失败回退到
    BACKEND_CAPABILITY_REPORT 摘要表。返回的每个条目都满足 timeline.schema.json 的
    capability_entry（supported 必须为 boolean，§44 不假装支持）。"""
    try:
        mod = _importlib.import_module("adapters.pyjianyingdraft")
        raw = getattr(mod, "TIMELINE_BACKEND_CAPABILITIES", None)
    except Exception:  # noqa: BLE001 — 能力加载失败降级，不允许 planner 崩
        raw = None
    if not isinstance(raw, dict) or not raw:
        raw = _FALLBACK_CAPABILITIES
    out: Dict[str, Dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        supported = entry.get("supported")
        is_supported = supported is True or str(supported).lower() == "partial"
        item: Dict[str, Any] = {"supported": bool(is_supported)}
        fb = entry.get("fallback")
        if fb is not None:
            item["fallback"] = str(fb)
        ev = entry.get("evidence")
        if ev is not None:
            item["evidence"] = str(ev)
        out[str(key)] = item
    return out


# ---------------------------------------------------------------------------
# TimelinePlanner
# ---------------------------------------------------------------------------

class TimelinePlanner:
    """确定性 Timeline Planner。

    用法::

        result = TimelinePlanner(inputs).plan()
        # result = {"manifest": {...}, "conflicts": [...], "proposals": [...],
        #           "map_ref": "TIMELINE_MAP.md", "complexity": {...}, "warnings": [...]}

    输入 inputs 键（全部可选，缺失时取安全默认，保证确定性）：
        storyboard {shots[], scenes[]}、routing_plan、asset_package、
        timeline_handoff、audio_map、editability_plan、visual_bible、
        audio_direction、editorial_direction、config{fps,canvas,backend,
        proxy_policy,template,...}。
    """

    def __init__(self, inputs: Dict[str, Any]):
        self.inputs = inputs if isinstance(inputs, dict) else {}
        self.config = self._normalize_config(self.inputs.get("config"))
        self.fps = int(self.config["fps"])
        self.template = self._pick_template()
        self.capabilities = _load_capabilities()
        self.keyframe_budget = int(self.config.get("keyframe_budget") or KEYFRAME_BUDGET)

        # 归一化输入
        self.storyboard = self._normalize_storyboard(self.inputs.get("storyboard"))
        self.shots = self.storyboard["shots"]
        self.scenes = self.storyboard["scenes"]
        self.routing_plan = self._norm_dict(self.inputs.get("routing_plan"))
        self.asset_package = self._norm_dict(self.inputs.get("asset_package"))
        self.assets, self._asset_warnings = self._collect_assets(self.asset_package)
        self.handoff = self._normalize_handoff(self.inputs.get("timeline_handoff"))
        self.audio_map = self._normalize_audio_map(self.inputs.get("audio_map"))
        self.editability = self._norm_dict(self.inputs.get("editability_plan"))
        self.visual_bible = self._norm_dict(self.inputs.get("visual_bible"))
        self.audio_direction = self._norm_dict(self.inputs.get("audio_direction"))
        self.editorial = self._norm_dict(self.inputs.get("editorial_direction"))

        # 输出容器（确定性：每次 plan() 都是全新实例）
        self.tracks: List[Dict[str, Any]] = []
        self.clips: List[Dict[str, Any]] = []
        self.conflicts: List[Dict[str, Any]] = []
        self.proposals: List[Dict[str, Any]] = []
        self.warnings: List[str] = list(self._asset_warnings)
        self.markers: List[Dict[str, Any]] = []
        self.continuity_groups: List[Dict[str, Any]] = []
        self.locked_regions: List[Dict[str, Any]] = []
        self.replaceable_assets: List[str] = []
        self.asset_links: List[Dict[str, Any]] = []
        self.subtitle_items: List[Dict[str, Any]] = []

        # 计数器
        self._n_tc = 0
        self._n_as = 0
        self._n_kf = 0
        self._n_tlc = 0
        self._n_mk = 0
        self._n_prop = 0

        # Shot 帧区间（Step 1 填充）
        self.shot_frames: Dict[str, Tuple[int, int]] = {}
        self.timeline_duration_frames = 0
        self.total_seconds = 0.0

        # 音频 map 辅助
        self._audio_map_entries = self._flatten_audio_map(self.audio_map)

    # ------------------------------------------------------------ 归一化
    @staticmethod
    def _norm_dict(v: Any) -> Dict[str, Any]:
        return v if isinstance(v, dict) else {}

    def _normalize_config(self, raw: Any) -> Dict[str, Any]:
        cfg = self._norm_dict(raw)
        fps_raw = cfg.get("fps", 30)
        try:
            fps = int(fps_raw)
        except (TypeError, ValueError):
            fps = 30
        if fps <= 0:
            fps = 30
        canvas = cfg.get("canvas") or cfg.get("resolution") or {"w": 1920, "h": 1080}
        res = cfg.get("resolution") or canvas
        backend_choice = str(cfg.get("backend") or "PYJIANYINGDRAFT").strip().upper()
        if backend_choice in ("PYJIANYINGDRAFT", "VECTCUT", "PYCAPCUT", "AUTO"):
            preferred = backend_choice
            manifest_backend = "UNDECIDED" if backend_choice == "AUTO" else backend_choice
        else:
            preferred = "PYJIANYINGDRAFT"
            manifest_backend = "PYJIANYINGDRAFT"
        proxy = _normalize_enum(
            cfg.get("proxy_policy"), ("USE_ORIGINAL", "USE_PROXY_FOR_EDIT", "AUTO"), "AUTO")
        norm = {
            "fps": fps,
            "canvas": {"w": int(canvas.get("w", 1920)), "h": int(canvas.get("h", 1080))},
            "resolution": {"w": int(res.get("w", 1920)), "h": int(res.get("h", 1080))},
            "backend": manifest_backend,
            "preferred_timeline_backend": preferred,
            "proxy_policy": proxy,
            "template": cfg.get("template"),
            "project_id": str(cfg.get("project_id") or "UNKNOWN"),
            "timeline_id": str(cfg.get("timeline_id") or "TL-001"),
            "backend_version": str(cfg.get("backend_version") or ""),
            "project_path": str(cfg.get("project_path") or "timeline/manifest/timeline_v1.json"),
            "version": str(cfg.get("version") or "v1"),
            "status": str(cfg.get("status") or "in_progress"),
            "timeline_map_ref": str(cfg.get("timeline_map_ref") or "TIMELINE_MAP.md"),
            "baseline_ref": str(cfg.get("baseline_ref") or "timeline/manifest/timeline_v1.json"),
            "review_points": _as_list(cfg.get("review_points")),
            "keyframe_budget": self._safe_int(cfg.get("keyframe_budget"), KEYFRAME_BUDGET),
            "music_start_seconds": _get_num(cfg, "music_start_seconds", "music_start"),
            "b_roll_density": self._norm_dict(self._norm_dict(
                self._norm_dict(cfg.get("editorial_direction")).get("b_roll_density") or
                cfg.get("b_roll_density"))),
        }
        # backend_mapping 基础值（backend-neutral：仅当 config 提供具体后端轨道名）
        bm = cfg.get("backend_mapping")
        if isinstance(bm, dict) and bm:
            norm["backend_mapping"] = dict(bm)
        return norm

    @staticmethod
    def _safe_int(v: Any, default: int) -> int:
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _pick_template(self) -> str:
        total = _get_num(self._norm_dict(self.inputs.get("storyboard")), "total_duration",
                         "duration", "target_duration")
        if total is None:
            shots = self._norm_dict(self.inputs.get("storyboard")).get("shots")
            if isinstance(shots, list):
                total = sum(float(_get_num(s, "duration", "end_time") or 0.0)
                            for s in shots if isinstance(s, dict))
        return _templates_mod.resolve_template(self.config.get("template"), total)

    # ------------------------------------------------------------ Storyboard
    def _normalize_storyboard(self, raw: Any) -> Dict[str, Any]:
        sb = self._norm_dict(raw)
        scenes_raw = _as_list(sb.get("scenes"))
        shots_raw = _as_list(sb.get("shots"))
        if isinstance(sb.get("shots"), dict):
            shots_raw = [dict(v, id=k) if not (v or {}).get("id") and not (v or {}).get("shot_id")
                         else v for k, v in sb["shots"].items()]
        scenes: List[Dict[str, Any]] = []
        for i, sc in enumerate(scenes_raw, 1):
            if not isinstance(sc, dict):
                continue
            sid = str(sc.get("id") or sc.get("scene_id") or "").strip()
            scenes.append({
                "id": sid or f"SC{i:03d}",
                "chapter": str(sc.get("chapter") or ""),
                "order": self._safe_int(sc.get("order"), i),
                "title": str(sc.get("title") or sid),
                "shots": _as_list(sc.get("shots")),
            })
        scenes.sort(key=lambda s: s["order"])

        shots: List[Dict[str, Any]] = []
        scene_order_map = {s["id"]: s["order"] for s in scenes}
        for sh in shots_raw:
            if not isinstance(sh, dict):
                continue
            sid = str(sh.get("id") or sh.get("shot_id") or "").strip()
            if not sid:
                continue
            scene_id = str(sh.get("scene_id") or "")
            duration = _get_num(sh, "duration", "target_duration")
            start = _get_num(sh, "start_time", "start")
            end = _get_num(sh, "end_time", "end")
            if duration is None and start is not None and end is not None:
                duration = max(0.0, end - start)
            if duration is None:
                duration = 1.0
            duration = max(0.0, float(duration))
            shots.append({
                "id": sid,
                "scene_id": scene_id,
                "scene_order": scene_order_map.get(scene_id, 10 ** 6),
                "order": self._safe_int(sh.get("order"), 10 ** 6),
                "duration_seconds": duration,
                "start_time": start,
                "end_time": end,
                "narrative_purpose": str(sh.get("narrative_purpose") or ""),
                "visual_description": str(sh.get("visual_description") or ""),
                "voiceover": str(sh.get("voiceover") or ""),
                "on_screen_text": str(sh.get("on_screen_text") or ""),
                "camera": str(sh.get("camera") or ""),
                "motion": str(sh.get("motion") or ""),
                "transition_in": str(sh.get("transition_in") or "").lower(),
                "transition_out": str(sh.get("transition_out") or "").lower(),
                "continuity_group": str(sh.get("continuity_group") or ""),
                "route": str(sh.get("route") or "").upper(),
                "audio": self._norm_dict(sh.get("audio")),
                "assets": _as_list(sh.get("assets")),
                "raw": sh,
            })
        shots.sort(key=lambda s: (s["scene_order"], s["order"], s["id"]))
        total = sum(s["duration_seconds"] for s in shots)
        return {"shots": shots, "scenes": scenes, "total_seconds": total}

    def _route_for(self, shot_id: str) -> str:
        """routing_plan 中查 shot 的 route（确定性优先级：shots 映射 > entries > shot 自带）。"""
        shot = next((s for s in self.shots if s["id"] == shot_id), None)
        if shot and shot["route"]:
            return shot["route"]
        rp = self.routing_plan
        if isinstance(rp.get("shots"), dict):
            v = rp["shots"].get(shot_id)
            if isinstance(v, dict):
                r = str(v.get("route") or "").upper()
                if r:
                    return r
        for entry in _as_list(rp.get("entries")):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("shot_id") or "") == shot_id:
                r = str(entry.get("route") or "").upper()
                if r:
                    return r
        return ""

    # ------------------------------------------------------------ Assets
    def _collect_assets(self, package: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """从 ASSET_PACKAGE_MANIFEST 确定性收集资产。

        按固定 section 顺序扫描，asset_id 去重（先到先得），按 asset_id 排序返回。
        """
        sections = (
            "assets", "motion_assets", "three_d_assets", "music", "sfx",
            "ambience", "sources", "images", "real_footage_assets",
            "generative_video_assets",
        )
        by_id: Dict[str, Dict[str, Any]] = {}
        warnings: List[str] = []
        for sec in sections:
            for item in _as_list(package.get(sec)):
                if not isinstance(item, dict):
                    continue
                aid = str(item.get("asset_id") or "").strip()
                if not ASSET_ID_RE.match(aid):
                    if aid:
                        warnings.append(f"{sec} 资产缺合法 asset_id {aid!r}，跳过")
                    continue
                if aid not in by_id:
                    by_id[aid] = dict(item, asset_id=aid)
        return [by_id[k] for k in sorted(by_id)], warnings

    def _normalize_handoff(self, raw: Any) -> Dict[str, Dict[str, Any]]:
        m = self._norm_dict(raw)
        by_asset: Dict[str, Dict[str, Any]] = {}
        for entry in _as_list(m.get("entries")):
            if not isinstance(entry, dict):
                continue
            aid = str(entry.get("asset_id") or "").strip()
            if ASSET_ID_RE.match(aid):
                by_asset[aid] = dict(entry)
        return by_asset

    def _normalize_audio_map(self, raw: Any) -> Dict[str, Any]:
        m = self._norm_dict(raw)
        out = dict(m)
        if isinstance(m.get("entries"), list):
            out["entries"] = m["entries"]
        else:
            out["entries"] = _as_list(m.get("sfx")) + _as_list(m.get("sync"))
        return out

    def _flatten_audio_map(self, am: Dict[str, Any]) -> List[Dict[str, Any]]:
        """audio_map → 归一化条目列表。每条含可选的 frame/type/asset_id/event。"""
        out: List[Dict[str, Any]] = []
        for e in _as_list(am.get("entries")):
            if not isinstance(e, dict):
                continue
            frame = e.get("frame")
            if frame is None:
                t = e.get("time")
                sec = parse_timecode(t)
                if sec is not None:
                    frame = seconds_to_frames(sec, self.fps)
            frame = self._safe_int(frame, -1)
            asset_id = str(e.get("asset_id") or e.get("asset") or e.get("sfx_ref") or "").strip()
            out.append({
                "frame": frame if frame >= 0 else None,
                "type": str(e.get("type") or "").upper(),
                "event": str(e.get("event") or e.get("label") or e.get("name") or ""),
                "asset_id": asset_id if ASSET_ID_RE.match(asset_id) else "",
                "shot_id": str(e.get("shot_id") or ""),
            })
        return out

    # ------------------------------------------------------------ Step 1: shot timing
    def _plan_shot_timing(self) -> None:
        """§25-26 帧安全计时：秒→帧一次换算，之后整数累积，不浮点累积。"""
        cursor = 0
        for shot in self.shots:
            dur_f = seconds_to_frames(shot["duration_seconds"], self.fps)
            if dur_f is None or dur_f < 1:
                dur_f = 1
            start = cursor
            end = cursor + dur_f
            if shot["start_time"] is not None:
                expected = seconds_to_frames(shot["start_time"], self.fps)
                if expected is not None and abs(expected - start) > TIMING_TOLERANCE_FRAMES:
                    self._add_conflict(
                        shot_id=shot["id"],
                        problem="technical timing conflict: 时间线帧级累积与 Storyboard 显式 start_time 漂移",
                        reason="帧安全计时按 Storyboard 时长整数累积（§26-27），Shot 显式 start_time 与累积值不一致",
                        current=f"{shot['id']} 累积 start={start} frame ({frames_to_seconds(start, self.fps)} s)",
                        required=f"{shot['id']} storyboard start_time={shot['start_time']} s "
                                 f"≈ {expected} frame",
                        solution="保持 Storyboard 时长为准（§23），接受 <1 frame 级漂移或人工在剪映微调",
                        creative_impact="整片切点最多偏离 1-2 帧，节奏几乎无感",
                    )
            self.shot_frames[shot["id"]] = (start, end)
            cursor = end
        self.timeline_duration_frames = cursor
        self.total_seconds = float(frames_to_seconds(cursor, self.fps) or 0.0)

    def _add_conflict(self, shot_id: str, problem: str, reason: str,
                      current: str, required: str, solution: str,
                      creative_impact: str, approval: bool = True) -> Dict[str, Any]:
        """§24 九字段 TLC-### 冲突记录（Planner 不私改导演时长）。"""
        self._n_tlc += 1
        c = {
            "conflict_id": f"TLC-{self._n_tlc:03d}",
            "shot_id": shot_id,
            "problem": problem,
            "reason": reason,
            "current_timing": current,
            "required_timing": required,
            "recommended_solution": solution,
            "creative_impact": creative_impact,
            "approval_required": approval,
        }
        self.conflicts.append(c)
        return c

    # ------------------------------------------------------------ Step 2: tracks
    def _ensure_track(self, track_type: str, name: str, purpose: str) -> Dict[str, Any]:
        """按类型找轨道，缺则动态补建（§16 按项目规模动态建轨）。"""
        for t in self.tracks:
            if t["type"] == track_type:
                return t
        t = {
            "track_id": "TR-000",
            "type": track_type,
            "name": name,
            "order": 0,
            "locked": False,
            "visible": True,
            "muted": False,
            "purpose": purpose,
            "backend_mapping": dict(self.config.get("backend_mapping") or {}),
        }
        self.tracks.append(t)
        self._renumber_tracks()
        return t

    def _renumber_tracks(self) -> None:
        """按 §132 类型分组顺序重排 + 重编号 TR-###（确定性）。"""
        self.tracks.sort(key=lambda t: (_TYPE_RANK.get(t["type"], 99),
                                        int(t.get("order") or 0)))
        for i, t in enumerate(self.tracks, 1):
            t["order"] = i
            t["track_id"] = f"TR-{i:03d}"

    def _track_id_for_type(self, track_type: str) -> Optional[str]:
        for t in self.tracks:
            if t["type"] == track_type:
                return t["track_id"]
        return None

    def _resolve_track_type(self, asset: Dict[str, Any],
                            handoff: Optional[Dict[str, Any]]) -> Optional[str]:
        """资产/交接 → 轨道类型（§15/§16/§22，确定性优先级）。"""
        # 1) handoff preferred_track（footage/plan_use 的 track hint）
        if handoff:
            htrack = str(handoff.get("preferred_track") or "").strip()
            tt = _TRACK_TOKEN_MAP.get(htrack.upper())
            if tt:
                return tt
        # 2) asset.timeline_hint.track
        th = asset.get("timeline_hint")
        if isinstance(th, dict):
            for key in ("track", "track_hint"):
                tt = _TRACK_TOKEN_MAP.get(str(th.get(key) or "").upper())
                if tt:
                    return tt
        plan = asset.get("plan_use")
        if isinstance(plan, dict):
            th2 = plan.get("timeline_hint")
            if isinstance(th2, dict):
                tt = _TRACK_TOKEN_MAP.get(str(th2.get("track") or "").upper())
                if tt:
                    return tt
        # 3) 按类型归类（§15/§18-20/§80-83）
        atype = str(asset.get("type") or "").upper()
        if atype in _OVERLAY_TYPES:
            return "VIDEO_OVERLAY"
        if atype in _MOTION_TYPES:
            return "VIDEO_MOTION"
        if atype in ("3D_ELEMENT", "THREE_D", "THREE_D_ELEMENT"):
            return "VIDEO_OVERLAY"
        if atype in _AI_TYPES:
            return "VIDEO_AI"
        if atype in ("VOICEOVER", "VOICE", "NARRATION"):
            return "VOICEOVER"
        if atype == "MUSIC":
            return "MUSIC"
        if atype == "SFX":
            return "SFX"
        if atype in ("AMBIENCE", "ROOM_TONE"):
            return "AMBIENCE"
        if atype in ("IMAGE", "PHOTO", "STILL", "ARCHIVE_IMAGE"):
            return "IMAGE"
        if atype in ("TEXT", "TITLE"):
            return "TEXT"
        if atype == "SUBTITLE":
            return "SUBTITLE"
        if atype == "FOOTAGE":
            # footage：B-roll 标记 → VIDEO_BROLL，否则主轨
            if self._is_broll(asset, handoff):
                return "VIDEO_BROLL"
            return "VIDEO_MAIN"
        return None

    def _is_broll(self, asset: Dict[str, Any],
                  handoff: Optional[Dict[str, Any]]) -> bool:
        """§75-76：B-roll 判定（确定性）。"""
        if handoff:
            htrack = str(handoff.get("preferred_track") or "").upper()
            if "BROLL" in htrack or htrack in ("V2", "V2_BROLL", "B-ROLL"):
                return True
        if asset.get("b_roll") is True:
            return True
        plan = asset.get("plan_use")
        if isinstance(plan, dict) and (plan.get("b_roll_density") or plan.get("b_roll")):
            return True
        th = asset.get("timeline_hint")
        if isinstance(th, dict) and str(th.get("track") or "").upper() in ("V2", "V2_BROLL"):
            return True
        shot_id = str(asset.get("shot_id") or "")
        shot = self._shot_by_id(shot_id)
        if shot:
            text = (shot["narrative_purpose"] + " " + shot["visual_description"]).lower()
            if any(k in text for k in ("b-roll", "broll", "补充", "支撑素材", "背景素材",
                                       "backup", "supporting")):
                return True
        return False

    def _shot_by_id(self, shot_id: str) -> Optional[Dict[str, Any]]:
        for s in self.shots:
            if s["id"] == shot_id:
                return s
        return None

    def _shot_frame_range(self, shot_id: str) -> Tuple[Optional[int], Optional[int]]:
        if shot_id in self.shot_frames:
            return self.shot_frames[shot_id]
        return None, None

    # ------------------------------------------------------------ Step 3: clip placement
    def _next_clip_id(self) -> str:
        self._n_tc += 1
        return f"TC-{self._n_tc:03d}"

    def _next_asset_slot(self, asset_id: str) -> str:
        self._n_as += 1
        return f"AS-{self._n_as:03d}"

    def _clip_editability(self, asset: Dict[str, Any], clip_id: str,
                          track_type: str) -> Tuple[bool, bool, str]:
        """clip 级 editable / replaceable（§6-7/§33-35/§55）。

        优先级：editability_plan.clips[asset_id|shot_id] > asset.editability > 轨道/类型默认。
        """
        edit_plan = self.editability
        clips_plan = edit_plan.get("clips")
        shot_id = str(asset.get("shot_id") or "")
        if isinstance(clips_plan, dict):
            for key in (str(asset.get("asset_id") or ""), shot_id):
                spec = clips_plan.get(key)
                if isinstance(spec, dict):
                    editable = spec.get("editable", True)
                    replaceable = spec.get("replaceable", True)
                    return bool(editable), bool(replaceable), str(spec.get("owner") or "AI")
        editable_asset = str(asset.get("editability") or "").upper()
        if editable_asset == "BAKE":
            return False, False, "AI"
        if editable_asset == "KEEP_EDITABLE":
            return True, False, "AI"
        if editable_asset == "ASSET_REPLACEABLE":
            return False, True, "AI"
        # 轨道/类型默认：字幕/B-roll/图片/基础文字保持可编辑（§7/§55/§76/§78）
        if track_type in ("SUBTITLE", "TEXT", "IMAGE", "VIDEO_BROLL"):
            return True, True, "AI"
        if track_type == "VIDEO_MOTION":
            return False, True, "AI"  # Remotion 连续 Motion：整体替换不拆（§8/§130）
        if track_type in ("MUSIC", "SFX", "AMBIENCE", "VOICEOVER"):
            return True, False, "AI"
        return True, True, "AI"

    def _proxy_usage(self, asset: Dict[str, Any],
                     handoff: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """§31-32 proxy 映射：policy 来自 config；AUTO 按 bitrate/分辨率判定。"""
        policy = self.config["proxy_policy"]
        proxy = (handoff or {}).get("proxy") or asset.get("proxy_path") or asset.get("preview")
        original = ((handoff or {}).get("original")
                    or asset.get("original_path") or asset.get("source")
                    or asset.get("local_path"))
        original = str(original) if original else None
        proxy = str(proxy) if proxy else None
        if policy == "USE_ORIGINAL":
            out_policy = "USE_ORIGINAL"
        elif policy == "USE_PROXY_FOR_EDIT":
            out_policy = "USE_PROXY_FOR_EDIT"
        else:  # AUTO
            probe = asset.get("media_probe")
            bitrate = None
            if isinstance(probe, dict):
                bitrate = probe.get("bitrate")
                try:
                    bitrate = float(bitrate) if bitrate is not None else None
                except (TypeError, ValueError):
                    bitrate = None
            res = asset.get("resolution")
            large = False
            if isinstance(res, dict):
                w = res.get("w", 0) or 0
                h = res.get("h", 0) or 0
                large = int(w) * int(h) > 1920 * 1080
            if proxy and (bitrate is None or bitrate > AUTO_PROXY_BITRATE_THRESHOLD or large):
                out_policy = "USE_PROXY_FOR_EDIT"
            else:
                out_policy = "USE_ORIGINAL"
        out: Dict[str, Any] = {"policy": out_policy}
        if proxy:
            out["proxy"] = proxy
        if original:
            out["original"] = original
        return out

    def _source_range(self, asset: Dict[str, Any],
                      handoff: Optional[Dict[str, Any]],
                      timeline_dur_frames: int,
                      media_bounds_check: bool = True) -> Tuple[int, int]:
        """§30/§84 source in/out（footage 用 timeline_hint 推荐区间）。

        优先级：handoff.in_point > asset.timeline_hint.in > asset.recommended_in > 0；
        out 优先取 hint；否则 in + timeline_dur/speed。素材源区间超媒体时长（仅视频/图片类，
        media_bounds_check=True）→ TLC-###（§23 不改导演时长，只记录并裁切源区间）。
        """
        in_sec = parse_timecode((handoff or {}).get("in_point"))
        if in_sec is None:
            th = asset.get("timeline_hint")
            if isinstance(th, dict):
                in_sec = parse_timecode(th.get("in"))
        if in_sec is None:
            in_sec = _get_num(asset, "recommended_in")
        in_frame = seconds_to_frames(in_sec, self.fps) if in_sec is not None else 0
        if in_frame is None:
            in_frame = 0

        speed = 1.0
        if handoff and handoff.get("speed") is not None:
            speed = parse_timecode(str(handoff["speed"])) or 1.0
        elif isinstance(asset.get("timeline_hint"), dict):
            speed = parse_timecode(str(asset["timeline_hint"].get("speed"))) or 1.0
        if speed <= 0:
            speed = 1.0

        out_sec = parse_timecode((handoff or {}).get("out_point"))
        if out_sec is None:
            th = asset.get("timeline_hint")
            if isinstance(th, dict):
                out_sec = parse_timecode(th.get("out"))
        if out_sec is None:
            out_sec = _get_num(asset, "recommended_out")
        if out_sec is not None:
            out_frame = seconds_to_frames(out_sec, self.fps)
            if out_frame is None:
                out_frame = in_frame + max(1, int(round(timeline_dur_frames / speed)))
        else:
            out_frame = in_frame + max(1, int(round(timeline_dur_frames / speed)))
        if out_frame <= in_frame:
            out_frame = in_frame + max(1, int(round(timeline_dur_frames / speed)))

        # 源区间超媒体时长（视频/图片才检查；音频 loop/trim 语义不同，不报 TLC）
        media_dur = _get_num(asset.get("media_probe"), "duration") or _get_num(asset, "duration")
        shot_id = str(asset.get("shot_id") or "")
        if media_bounds_check and media_dur is not None and media_dur > 0:
            media_frames = seconds_to_frames(media_dur, self.fps) or 1
            if out_frame > media_frames:
                self._add_conflict(
                    shot_id=shot_id or "UNKNOWN",
                    problem="technical timing conflict: 推荐源区间超出素材可用时长",
                    reason=f"timeline_hint 推荐 out={out_frame} frame 超出素材 {media_dur}s"
                           f"（{media_frames} frame）",
                    current=f"{asset.get('asset_id')} 源区间 {in_frame}..{out_frame} frame",
                    required=f"素材可用 {0}..{media_frames} frame",
                    solution="裁剪源区间到素材末尾，或换更长素材/扩展镜头",
                    creative_impact="尾段最多缺 0.5-2s 画面，需人工在剪映补 B-roll 或重取素材",
                )
                out_frame = media_frames
                if out_frame <= in_frame:
                    in_frame = max(0, media_frames - max(1, int(timeline_dur_frames / speed)))
                    if in_frame < 0:
                        in_frame = 0
        elif not media_bounds_check and media_dur is not None and media_dur > 0:
            media_frames = seconds_to_frames(media_dur, self.fps) or 1
            if out_frame > media_frames:
                out_frame = media_frames
                if out_frame <= in_frame:
                    in_frame = 0
                    out_frame = max(1, min(media_frames, 1))
        return in_frame, out_frame

    def _transition(self, shot: Optional[Dict[str, Any]],
                    which: str) -> Tuple[Dict[str, Any], str]:
        """§72-74 转场：默认 CUT 写入决策；Storyboard 简单转场映射基础四枚举；
        复杂转场 → (CUT 占位, 原始文本)，复杂文本交给上层记 Remotion 资产引用。

        Returns:
            (transition_dict, complex_transition_text)：复杂转场时 second 非空。
        """
        default: Dict[str, Any] = {"type": "CUT", "duration_frames": 0}
        if shot is None:
            return default, ""
        text = str(shot.get(which) or "").strip().lower()
        if not text or text in ("cut", "c", "无", "none", "硬切"):
            return default, ""
        dur = 0
        m = re.search(r"(\d+(?:\.\d+)?)\s*s", text)
        if m:
            dur = seconds_to_frames(float(m.group(1)), self.fps) or 0
        if "dissolve" in text or "叠化" in text:
            return {"type": "DISSOLVE", "duration_frames": max(0, dur)}, ""
        if "fade" in text or "淡入" in text or "淡出" in text or "黑场" in text:
            return {"type": "FADE", "duration_frames": max(0, dur)}, ""
        if "slide" in text or "滑动" in text:
            return {"type": "SLIDE", "duration_frames": max(0, dur)}, ""
        # 复杂转场：保留 CUT 决策（§74），原始文本交给 _note_complex_transition（§72）
        return default, text

    # ------------------------------------------------------------ clip builders
    def _add_clip(self, asset: Dict[str, Any], track_type: str,
                  start_frame: int, end_frame: int,
                  handoff: Optional[Dict[str, Any]] = None,
                  shot_id: Optional[str] = None,
                  layer_id: Optional[str] = None,
                  extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """构造一条 timeline-clip 并挂入 tracks/clips（§29 全字段子集，全 schema 合法）。"""
        if end_frame <= start_frame:
            self.warnings.append(
                f"{asset.get('asset_id')} 片段时长非正（{start_frame}..{end_frame}），跳过")
            return None
        clip_id = self._next_clip_id()
        editable, replaceable, owner = self._clip_editability(asset, clip_id, track_type)
        track = self._ensure_track(track_type, *self._default_track_name(track_type))
        track_id = track["track_id"]

        shot_id = shot_id or str(asset.get("shot_id") or "")
        layer_id = layer_id or str(asset.get("layer_id") or "")
        speed_raw = None
        if handoff and handoff.get("speed") is not None:
            speed_raw = parse_timecode(str(handoff["speed"]))
        elif isinstance(asset.get("timeline_hint"), dict):
            speed_raw = parse_timecode(str(asset["timeline_hint"].get("speed")))
        speed = round(float(speed_raw) if speed_raw and speed_raw > 0 else 1.0, 3)

        src_in, src_out = self._source_range(
            asset, handoff, end_frame - start_frame,
            media_bounds_check=track_type in (
                "VIDEO_MAIN", "VIDEO_BROLL", "VIDEO_MOTION", "VIDEO_OVERLAY",
                "VIDEO_3D", "VIDEO_AI", "IMAGE"))

        clip: Dict[str, Any] = {
            "clip_id": clip_id,
            "track_id": track_id,
            "asset_id": str(asset.get("asset_id") or ""),
            "timeline_start_frame": start_frame,
            "timeline_end_frame": end_frame,
            "editable": editable,
            "replaceable": replaceable,
            "owner": owner,
            "locked": False,
            "proxy_usage": self._proxy_usage(asset, handoff),
        }
        # §33-34 可替换资产槽：仅 replaceable 资产建 AS-###（KEEP_EDITABLE 无需槽位）
        if replaceable:
            clip["asset_slot_id"] = self._next_asset_slot(asset.get("asset_id", ""))
        if shot_id:
            clip["shot_id"] = shot_id
        if layer_id:
            clip["layer_id"] = layer_id
        if src_in or src_out:
            clip["source_in_frame"] = src_in
            clip["source_out_frame"] = src_out
        if speed != 1.0:
            clip["speed"] = speed

        # audio_behavior（§84：footage 用 handoff/plan 带入）
        ab = (handoff or {}).get("audio_behavior") or asset.get("audio_behavior")
        ab = _normalize_enum(ab, ("KEEP", "MUTE", "USE_AS_AMBIENCE", "EXTRACT", "REPLACE"),
                             "MUTE" if track_type == "VIDEO_MAIN" else "KEEP")
        clip["audio_behavior"] = ab

        # transform（资产 hint 带入；无则省略）
        pos = asset.get("position") or (handoff or {}).get("position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            clip["position"] = {"x": float(pos["x"]), "y": float(pos["y"])}
        scale = asset.get("scale")
        if isinstance(scale, dict) and "x" in scale and "y" in scale:
            clip["scale"] = {"x": float(scale["x"]), "y": float(scale["y"])}
        crop = asset.get("crop") or (handoff or {}).get("crop")
        if crop:
            clip["crop"] = {"hint": str(crop)}
        blend = asset.get("blend_mode") or (handoff or {}).get("blend")
        if blend:
            clip["blend_mode"] = str(blend)

        # continuity_group（§8 原样保留；复杂连续 Motion 不拆）。CG 只挂在视觉运动类
        # 资产上（Remotion Motion 整体）；字幕/VO/音频不继承 shot 的 CG。
        cg = str(asset.get("continuity_group") or "").strip()
        if not cg and track_type in ("VIDEO_MOTION", "VIDEO_OVERLAY", "VIDEO_3D", "VIDEO_AI"):
            cg = self._continuity_for_shot(shot_id)
        if cg:
            clip["continuity_group"] = cg

        # 转场（§72-74；默认 CUT 写入决策）
        shot = self._shot_by_id(shot_id)
        tin, complex_in = self._transition(shot, "transition_in")
        tout, complex_out = self._transition(shot, "transition_out")
        clip["transition_in"] = tin
        clip["transition_out"] = tout
        if complex_in or complex_out:
            self._note_complex_transition(clip, complex_in or complex_out)

        # overlay_safe_area（§83）→ backend_metadata
        bmd: Dict[str, Any] = dict(extra or {})
        osa = self._overlay_safe_area(asset, handoff)
        if osa:
            bmd["overlay_safe_area"] = osa
        if shot_id:
            bmd["shot_id"] = shot_id
        if isinstance(asset.get("media_probe"), dict):
            bmd["media_probe_codec"] = str(asset["media_probe"].get("codec") or "")
        bmd["producer"] = str(asset.get("producer") or "")
        bmd["asset_version"] = str(asset.get("version") or "v1")
        if clip["transition_in"]["type"] != "CUT" or clip["transition_out"]["type"] != "CUT":
            bmd["transition_note"] = "非默认转场：来自 Storyboard/Visual Bible（§72-74）"
        clip["backend_metadata"] = bmd

        # locked（editability_plan.locked 命中 clip/asset/shot → clip_locked，§107）
        if self._is_locked(clip, asset):
            clip["locked"] = True
            clip["owner"] = "HUMAN"
            self.locked_regions.append({
                "target_type": "clip", "target_id": clip_id,
                "reason": "editability_plan 锁定（§107 clip_locked）",
            })

        self.clips.append(clip)
        self.asset_links.append({
            "asset_id": clip["asset_id"],
            "track": track["name"],
            "manual_edit_safe": editable,
            "source": str(asset.get("source") or asset.get("original_path")
                         or asset.get("local_path") or ""),
            "producer": str(asset.get("producer") or ""),
        })
        if replaceable and clip["asset_id"] not in self.replaceable_assets:
            self.replaceable_assets.append(clip["asset_id"])
        self._register_continuity(clip, cg)
        return clip

    def _default_track_name(self, track_type: str) -> Tuple[str, str]:
        """默认轨道名 + purpose（§133 命名；与模板一致）。"""
        names = {
            "VIDEO_MAIN": ("V1_MAIN", "主画面：真实素材 / AI Video"),
            "VIDEO_BROLL": ("V2_BROLL", "补充素材（§75-76）"),
            "VIDEO_MOTION": ("V3_MOTION", "Motion Graphic / Remotion 资产（§8）"),
            "VIDEO_OVERLAY": ("V4_OVERLAY", "透明图形 / 3D Overlay（§80-81）"),
            "VIDEO_3D": ("V5_3D", "3D 资产"),
            "VIDEO_AI": ("V6_AI", "AI Video（§82，按 shot purpose）"),
            "IMAGE": ("V7_IMAGE", "图片 / 档案素材（§77-79）"),
            "GRAPHIC": ("V8_GRAPHIC", "地图 / 图解"),
            "TEXT": ("T1_TITLES", "标题 / 标注（§78 可编辑）"),
            "SUBTITLE": ("T2_SUBTITLES", "可编辑字幕（§55）"),
            "UTILITY": ("U1_UTILITY", "工具轨道"),
            "VOICEOVER": ("A1_VO", "旁白（§58-59）"),
            "MUSIC": ("A2_MUSIC", "音乐（§64-67）"),
            "SFX": ("A3_SFX", "音效（§63）"),
            "AMBIENCE": ("A4_AMBIENCE", "环境声 region（§68-69）"),
        }
        return names.get(track_type, (track_type, ""))

    def _continuity_for_shot(self, shot_id: str) -> str:
        for s in self.shots:
            if s["id"] == shot_id and s["continuity_group"]:
                return s["continuity_group"]
        # routing_plan 的 merge_asset_suggestion（§8 CG 合并建议）
        rp = self.routing_plan
        for entry in _as_list(rp.get("entries")):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("shot_id") or "") == shot_id:
                mg = str(entry.get("merge_asset_suggestion") or "")
                m = re.search(r"(CG-?\d+|CG\d+)", mg)
                if m:
                    return m.group(1)
        return ""

    def _register_continuity(self, clip: Dict[str, Any], cg: str) -> None:
        if not cg:
            return
        for group in self.continuity_groups:
            if group.get("continuity_group") == cg:
                if clip["clip_id"] not in group["clip_ids"]:
                    group["clip_ids"].append(clip["clip_id"])
                return
        self.continuity_groups.append({"continuity_group": cg, "clip_ids": [clip["clip_id"]]})

    def _overlay_safe_area(self, asset: Dict[str, Any],
                           handoff: Optional[Dict[str, Any]]) -> Optional[str]:
        """§83 overlay_safe_area：handoff.overlay > timeline_hint.overlay_safe_area > plan。"""
        if handoff and handoff.get("overlay"):
            v = str(handoff["overlay"]).strip()
            if v and v.lower() not in ("none", "null"):
                return v
        th = asset.get("timeline_hint")
        if isinstance(th, dict):
            v = th.get("overlay_safe_area")
            if v and str(v).lower() not in ("none", "null"):
                return str(v)
        plan = asset.get("plan_use")
        if isinstance(plan, dict):
            th2 = plan.get("timeline_hint")
            if isinstance(th2, dict) and th2.get("overlay_safe_area"):
                return str(th2["overlay_safe_area"])
        return None

    def _note_complex_transition(self, clip: Dict[str, Any], text: str) -> None:
        """§72 复杂转场：Clip backend_metadata 记 Remotion 资产引用 + 提案（不改 route）。"""
        if not text:
            return
        clip.setdefault("backend_metadata", {})["complex_transition"] = {
            "original_text": text,
            "route": "REMOTION_ASSET_REFERENCE",
        }
        self._add_proposal(
            kind="COMPLEX_TRANSITION_TO_REMOTION",
            clip_id=clip["clip_id"], asset_id=clip["asset_id"],
            current_route="JY_NATIVE_TRANSITION", proposed_route="REMOTION_ASSET",
            reason=f"复杂转场 '{text}' 超出基础四枚举（§72），建议 Remotion 烘焙资产引用",
            approval_required=True,
        )

    def _is_locked(self, clip: Dict[str, Any], asset: Dict[str, Any]) -> bool:
        locked = _as_list(self.editability.get("locked"))
        targets = {clip["clip_id"], clip.get("shot_id", ""), asset.get("asset_id", "")}
        for item in locked:
            if isinstance(item, str) and item in targets:
                return True
            if isinstance(item, dict) and str(item.get("target_id") or "") in targets:
                return True
        return False

    def _add_proposal(self, kind: str, clip_id: str, asset_id: str,
                      current_route: str, proposed_route: str,
                      reason: str, approval_required: bool) -> Dict[str, Any]:
        """TIMELINE_OPTIMIZATION_PROPOSAL（§50-52：只提案，不私改 route）。"""
        self._n_prop += 1
        p = {
            "proposal_id": f"PROP-{self._n_prop:03d}",  # module-local 自由格式（非契约 ID 表）
            "kind": kind,
            "clip_id": clip_id,
            "asset_id": asset_id,
            "current_route": current_route,
            "proposed_route": proposed_route,
            "reason": reason,
            "approval_required": approval_required,
        }
        self.proposals.append(p)
        return p

    # ------------------------------------------------------------ Step 4-7: 落位
    def _place_visual_clips(self) -> None:
        """footage / remotion / image / overlay / 3d / AI video 落位（§29-30/§75-83）。"""
        for asset in self.assets:
            atype = str(asset.get("type") or "").upper()
            if atype in ("SFX", "MUSIC", "AMBIENCE", "VOICEOVER", "VOICE", "NARRATION",
                         "SUBTITLE"):
                continue  # 音频/字幕走专用步骤
            handoff = self.handoff.get(asset.get("asset_id", ""))
            track_type = self._resolve_track_type(asset, handoff)
            if track_type is None:
                self.warnings.append(
                    f"{asset.get('asset_id')} 无法判定轨道类型（type={atype}），跳过")
                continue
            shot_id = str(asset.get("shot_id") or "")
            start, end = self._shot_frame_range(shot_id)
            if start is None:
                pref_start = _get_num(handoff, "preferred_start")
                if pref_start is not None:
                    start = seconds_to_frames(pref_start, self.fps)
                if start is None:
                    start = 0
                dur = (_get_num(asset, "duration") or _get_num(handoff, "preferred_duration")
                       or 2.0)
                end = start + (seconds_to_frames(dur, self.fps) or 1)
                if end > self.timeline_duration_frames:
                    end = self.timeline_duration_frames
                if end <= start:
                    end = start + 1
            self._add_clip(asset, track_type, start, end, handoff=handoff, shot_id=shot_id,
                           layer_id=str(asset.get("layer_id") or ""))
            # §79 图片 Ken Burns：JY_NATIVE 克制缩放 1.00→1.05（两帧关键帧，§46）
            if track_type == "IMAGE":
                clip = self.clips[-1]
                self._add_image_ken_burns(clip)

    def _add_image_ken_burns(self, clip: Dict[str, Any]) -> None:
        """§77/§79：普通图片 JY_NATIVE，slow zoom 1.00→1.05 克制。"""
        start = clip["timeline_start_frame"]
        end = clip["timeline_end_frame"]
        if end - start < 2:
            return
        self._n_kf += 1
        kf1 = {"keyframe_id": f"KF-{self._n_kf:03d}", "frame": start,
               "property": "SCALE", "value": 1.0}
        self._n_kf += 1
        kf2 = {"keyframe_id": f"KF-{self._n_kf:03d}", "frame": end,
               "property": "SCALE", "value": 1.05}
        clip.setdefault("keyframes", []).extend([kf1, kf2])
        clip["backend_metadata"]["motion"] = {"route": "JY_NATIVE", "kind": "ken_burns",
                                              "scale": "1.00 -> 1.05"}

    def _place_subtitles(self) -> None:
        """§53-57：普通对白字幕 → SUBTITLE 轨 JY_NATIVE、editable=true；样式从 VISUAL_BIBLE。"""
        for shot in self.shots:
            text = shot["voiceover"].strip()
            if not text:
                continue
            start, end = self.shot_frames[shot["id"]]
            style = self._subtitle_style()
            emphasis = self._detect_emphasis(shot)
            sub_id = f"SUB-{shot['id']}"
            # subtitle_items（subtitle.schema.json 结构，editable 默认 true，§55）
            self.subtitle_items.append({
                "subtitle_id": sub_id,
                "text": text,
                "start_frame": start,
                "end_frame": end,
                "speaker": "narrator",
                "style_id": style.get("style_id", "STYLE_DEFAULT"),
                "position": {"x": 0.5, "y": 0.9},
                "line_break": "auto",
                "emphasis": emphasis,
                "editable": True,
            })
            # 轨道 clip（backend_metadata 承载文本/样式，供 P7-5 生成 text 轨字幕）
            bmd = {
                "text": text,
                "subtitle_id": sub_id,
                "style": style,
                "emphasis": emphasis,
                "route": "JY_NATIVE" if emphasis == "none" else "REMOTION_REFERENCE",
                "asset_note": "字幕为文本轨（§55 JY_NATIVE / §57 强调字 REMOTION 只标引用），"
                              "无独立媒体资产；A000 为合成占位 asset_id（P7-5 读 backend_metadata.text）",
            }
            if emphasis != "none":
                bmd["route_note"] = "叙事强调字：REMOTION 只标引用（§57），不建 REMOTION 片段"
            self._add_clip({
                "asset_id": "A000",
                "type": "SUBTITLE",
                "shot_id": shot["id"],
                "duration": frames_to_seconds(end - start, self.fps),
                "editability": "KEEP_EDITABLE",
                "producer": "JY_NATIVE",
            }, "SUBTITLE", start, end, extra=bmd, shot_id=shot["id"])

    def _subtitle_style(self) -> Dict[str, Any]:
        """§56 字幕样式：从 VISUAL_BIBLE 读；缺省 STYLE_DEFAULT。"""
        vb = self.visual_bible
        sub = vb.get("subtitle") or vb.get("subtitles") or vb.get("text") or {}
        if not isinstance(sub, dict):
            sub = {}
        style_id = str(sub.get("style_id") or vb.get("style_id") or "STYLE_DEFAULT")
        style: Dict[str, Any] = {"style_id": style_id}
        for key in ("font", "size", "position", "background", "shadow", "outline",
                    "line_spacing", "max_lines", "safe_area"):
            if sub.get(key) is not None:
                style[key] = sub[key]
        if "position" not in style:
            style["position"] = {"x": 0.5, "y": 0.9}
        if "safe_area" not in style:
            style["safe_area"] = "safe"
        return style

    @staticmethod
    def _detect_emphasis(shot: Dict[str, Any]) -> str:
        text = (str(shot.get("on_screen_text") or "") + " " + str(shot.get("motion") or "")).lower()
        if any(k in text for k in ("强调", "emphasis", "强调字", "typography", "大字",
                                   "emphasis word", "animated text")):
            return "REMOTION_REFERENCE"
        return "none"

    def _place_archive_labels(self) -> None:
        """§77-78：档案图片标注（date/location/source）→ TEXT 轨可编辑 clip。"""
        for asset in self.assets:
            atype = str(asset.get("type") or "").upper()
            if atype not in ("IMAGE", "PHOTO", "STILL", "ARCHIVE_IMAGE"):
                continue
            label = self._archive_label(asset)
            if not label:
                continue
            shot_id = str(asset.get("shot_id") or "")
            start, end = self._shot_frame_range(shot_id)
            if start is None:
                start = 0
                end = start + (seconds_to_frames(_get_num(asset, "duration") or 2.0, self.fps) or 1)
            self._add_clip({
                "asset_id": asset["asset_id"],
                "type": "TEXT",
                "shot_id": shot_id,
                "duration": frames_to_seconds(end - start, self.fps),
                "editability": "KEEP_EDITABLE",
                "producer": "JY_NATIVE",
            }, "TEXT", start, end, handoff=None, shot_id=shot_id,
                extra={"text": label, "text_kind": "archive_label",
                       "archive": label})

    @staticmethod
    def _archive_label(asset: Dict[str, Any]) -> str:
        parts = []
        for key in ("date", "location", "source_label", "source"):
            v = asset.get(key)
            if v and str(v) not in ("UNKNOWN", "none", "None"):
                parts.append(str(v))
        if not parts:
            at = asset.get("archive_treatment")
            if isinstance(at, dict) and at.get("date_label"):
                parts.append(str(at["date_label"]))
        if not parts:
            return ""
        return " | ".join(parts)

    # ------------------------------------------------------------ Step 9: audio
    def _place_voiceover(self) -> None:
        """§58-59：VO 主时间轴；EXPLAINER 时 VO drives timing（VO 时长 > shot → TLC）。"""
        for asset in self.assets:
            atype = str(asset.get("type") or "").upper()
            if atype not in ("VOICEOVER", "VOICE", "NARRATION"):
                continue
            handoff = self.handoff.get(asset.get("asset_id", ""))
            shot_id = str(asset.get("shot_id") or "")
            start, end = self._shot_frame_range(shot_id)
            if start is None:
                pref = _get_num(handoff, "preferred_start")
                start = seconds_to_frames(pref, self.fps) if pref is not None else 0
                dur = _get_num(asset, "duration") or _get_num(handoff, "preferred_duration") or 2.0
                end = start + (seconds_to_frames(dur, self.fps) or 1)
            else:
                vo_dur = seconds_to_frames(_get_num(asset, "duration"), self.fps)
                shot_dur = end - start
                if vo_dur is not None and vo_dur > shot_dur + TIMING_TOLERANCE_FRAMES:
                    self._add_conflict(
                        shot_id=shot_id,
                        problem="technical timing conflict: VO 时长超过所属 Shot",
                        reason=f"VO 资产 {asset.get('asset_id')} {vo_dur} frame 超 Shot {shot_dur} frame",
                        current=f"VO = {vo_dur} frame（{frames_to_seconds(vo_dur, self.fps)} s）",
                        required=f"Shot {shot_id} = {shot_dur} frame",
                        solution="延长 Shot 时长或拆分 VO（需导演审批，Planner 不改时长）",
                        creative_impact="旁白尾音会越过画面切点，J/L-cut 由人工在剪映微调",
                    )
            self._add_clip(asset, "VOICEOVER", start, end, handoff=handoff, shot_id=shot_id)

    def _place_music(self) -> None:
        """§64-67：Music 放置 + 结构对齐 + Ducking Plan（值来自 Audio Direction，不硬编码）。"""
        for asset in self.assets:
            atype = str(asset.get("type") or "").upper()
            if atype != "MUSIC":
                continue
            handoff = self.handoff.get(asset.get("asset_id", ""))
            start = self.config.get("music_start_seconds")
            start_f = seconds_to_frames(start, self.fps) if start is not None else 0
            dur = (_get_num(asset, "duration") or _get_num(handoff, "preferred_duration")
                   or float(frames_to_seconds(self.timeline_duration_frames, self.fps) or 10.0))
            end = start_f + (seconds_to_frames(dur, self.fps) or 1)
            bmd: Dict[str, Any] = {}
            struct = asset.get("structure")
            if isinstance(struct, dict):
                bmd["music_structure"] = {k: v for k, v in struct.items()
                                          if k in ("intro", "build", "drop", "resolve")}
                # §65 结构对齐：Reveal 对齐 Music lift → 记录结构章节帧
                bmd["chapter_transition_frames"] = self._music_structure_markers(
                    start_f, struct)
            duck = self._ducking_plan()
            if duck:
                bmd["ducking_plan"] = duck
            self._add_clip(asset, "MUSIC", start_f, end, handoff=handoff, extra=bmd)

    def _music_structure_markers(self, music_start_f: int, struct: Dict[str, Any]) -> Dict[str, int]:
        """§65：music 结构（intro/build/drop/resolve）相对帧 → 绝对帧（供 P7-5/QA）。"""
        out: Dict[str, int] = {}
        for key in ("intro", "build", "drop", "resolve"):
            v = struct.get(key)
            sec = parse_timecode(v) if isinstance(v, str) else v
            f = seconds_to_frames(sec, self.fps) if isinstance(sec, (int, float)) else None
            if f is not None:
                out[key] = music_start_f + f
        return out

    def _ducking_plan(self) -> Dict[str, Any]:
        """§66-67 Ducking：值来自 Audio Direction / audio_map，不硬编码固定值。"""
        src = self.audio_direction.get("ducking") or self.audio_map.get("ducking")
        if isinstance(src, dict):
            plan = {k: v for k, v in src.items() if k in (
                "vo_active_reduction_db", "important_phrase_reduction_db", "restore_db",
                "hero_visual_lift_db", "note")}
            plan["source"] = "AUDIO_DIRECTION"
            return plan
        # audio_map 内有 vo_active/music 描述 → 提取 dB
        for e in self._audio_map_entries:
            if "DUCK" in e["event"].upper() or "DUCK" in e["type"]:
                m = re.search(r"(-?\d+(?:\.\d+)?)\s*dB", e["event"], re.IGNORECASE)
                if m:
                    return {"vo_active_reduction_db": float(m.group(1)),
                            "restore_db": 0.0, "source": "AUDIO_MAP"}
        return {}

    def _place_sfx(self) -> None:
        """§62-63：SFX 帧级对齐（用 audio_map 帧值，不做肉眼大概对齐）。"""
        sfx_by_id = {a["asset_id"]: a for a in self.assets
                     if str(a.get("type") or "").upper() == "SFX"}
        placed = 0
        for e in self._audio_map_entries:
            if e["type"] and e["type"] not in ("SFX", "MUSIC_CHANGE", "MUSIC CHANGE", "SYNC",
                                               "IMPORTANT_SYNC", ""):
                continue
            if not e["asset_id"]:
                if e["frame"] is not None and e["event"]:
                    self.warnings.append(
                        f"audio_map 条目 {e['event']!r} 无对应 SFX 资产（asset_id 缺失），未落位")
                continue
            asset = sfx_by_id.get(e["asset_id"])
            if asset is None:
                self.warnings.append(f"audio_map 引用未知 SFX 资产 {e['asset_id']}，未落位")
                continue
            frame = e["frame"]
            if frame is None:
                frame = 0
            if frame >= self.timeline_duration_frames:
                self.warnings.append(
                    f"audio_map SFX {e['asset_id']} 帧 {frame} 超出时间线（{self.timeline_duration_frames}），未落位")
                continue
            dur = seconds_to_frames(_get_num(asset, "duration") or 1.0, self.fps) or 1
            if frame + dur > self.timeline_duration_frames:
                dur = self.timeline_duration_frames - frame
            shot_id = e["shot_id"] or str(asset.get("shot_id") or "")
            self._add_clip(asset, "SFX", frame, frame + dur,
                           handoff=self.handoff.get(asset["asset_id"]), shot_id=shot_id,
                           extra={"audio_sync": {"source": "AUDIO_MAP", "event": e["event"]}})
            placed += 1
        if placed == 0 and self._audio_map_entries:
            self.warnings.append("audio_map 无有效 SFX 条目可落位")

    def _place_ambience(self) -> None:
        """§68-69：Ambience region 跨 Shot 连续（同环境连续 shot 合并为一条，不逐 shot 重切）。"""
        amb_assets = [a for a in self.assets
                      if str(a.get("type") or "").upper() in ("AMBIENCE", "ROOM_TONE")]
        if not amb_assets:
            return
        # shot → ambience 归属（shot.audio.ambience 名称匹配资产名 token）
        shot_amb: Dict[str, str] = {}
        for shot in self.shots:
            amb_list = _as_list((shot["audio"] or {}).get("ambience"))
            names = " ".join(str(x) for x in amb_list).lower()
            for a in amb_assets:
                token = str(a.get("name") or a.get("asset_id")).lower()
                if token in names or a["asset_id"].lower() in names:
                    shot_amb[shot["id"]] = a["asset_id"]
                    break
        # 无 shot 归属时：每 ambience 资产一条 region 覆盖全片（若 shot_amb 为空）
        if not shot_amb:
            for a in amb_assets:
                self._add_clip(a, "AMBIENCE", 0, self.timeline_duration_frames,
                               handoff=self.handoff.get(a["asset_id"]))
            return
        # 连续 run 合并
        ordered = [s["id"] for s in self.shots]
        runs: List[Tuple[str, str, int, int]] = []  # (asset_id, first_shot, start, end)
        for sid in ordered:
            aid = shot_amb.get(sid)
            if aid is None:
                continue
            start, end = self.shot_frames[sid]
            if runs and runs[-1][0] == aid and runs[-1][3] == start:
                runs[-1] = (runs[-1][0], runs[-1][1], runs[-1][2], end)
            else:
                runs.append((aid, sid, start, end))
        for aid, first_shot, start, end in runs:
            asset = next((a for a in amb_assets if a["asset_id"] == aid), None)
            if asset is None:
                continue
            self._add_clip(asset, "AMBIENCE", start, end,
                           handoff=self.handoff.get(aid), shot_id=first_shot,
                           extra={"ambience_region": f"{start}..{end} frame（跨 Shot 连续，§68-69）"})

    # ------------------------------------------------------------ Step 11: markers
    def _plan_markers(self) -> None:
        """§85-86：Scene/Chapter/Hero/Review/Music change/Important sync 六类 → MK-###。"""
        def _add(frame: int, mtype: str, label: str) -> None:
            if frame < 0 or frame > self.timeline_duration_frames:
                return
            self._n_mk += 1
            self.markers.append({"marker_id": f"MK-{self._n_mk:03d}",
                                 "frame": frame, "type": mtype, "label": label})

        scene_shots: Dict[str, List[str]] = {}
        for s in self.shots:
            scene_shots.setdefault(s["scene_id"], []).append(s["id"])

        prev_chapter = None
        for sc in sorted(self.scenes, key=lambda x: x["order"]):
            first = None
            for sid in scene_shots.get(sc["id"], []):
                if sid in self.shot_frames:
                    first = self.shot_frames[sid][0]
                    break
            if first is None:
                continue
            _add(first, "Scene start", sc["title"])
            if sc["chapter"] and sc["chapter"] != prev_chapter:
                _add(first, "Chapter", sc["chapter"])
            prev_chapter = sc["chapter"] or prev_chapter

        # Hero moment（shot.motion 强度 HERO / 高光关键词）
        for shot in self.shots:
            text = (shot["motion"] + " " + shot["narrative_purpose"]).lower()
            if "hero" in text or "高光" in text or "intensity: hero" in shot["motion"].lower():
                _add(self.shot_frames[shot["id"]][0], "Hero moment", shot["id"])

        # Review point（config.review_points）
        for rp in _as_list(self.config.get("review_points")):
            if isinstance(rp, dict):
                frame = rp.get("frame")
                label = str(rp.get("label") or "review")
            else:
                frame = rp
                label = "review"
            f = self._safe_int(frame, -1)
            if f >= 0:
                _add(f, "Review point", label)

        # Music change（audio_map 条目 + 音乐结构对齐帧）
        for e in self._audio_map_entries:
            if e["frame"] is not None and ("MUSIC" in e["type"] or "music" in e["event"].lower()):
                _add(e["frame"], "Music change", e["event"] or "music cue")
        for clip in self.clips:
            st = clip["backend_metadata"].get("music_structure")
            if isinstance(st, dict) and st:
                for name, frame in clip["backend_metadata"].get(
                        "chapter_transition_frames", {}).items():
                    _add(frame, "Music change", f"music {name}")

        # Important sync（shot.audio.sync_points）
        for shot in self.shots:
            sync = _as_list((shot["audio"] or {}).get("sync_points"))
            for sp in sync:
                f: Optional[int] = None
                if isinstance(sp, dict):
                    if sp.get("frame") is not None:
                        f = self._safe_int(sp.get("frame"), -1)
                        if f < 0:
                            f = None
                    elif sp.get("time") is not None or sp.get("at") is not None:
                        sec = parse_timecode(sp.get("time") or sp.get("at"))
                        f = seconds_to_frames(sec, self.fps) if sec is not None else None
                else:
                    sec = parse_timecode(sp)
                    f = seconds_to_frames(sec, self.fps) if isinstance(sec, (int, float)) else None
                if f is not None and f >= 0:
                    _add(f, "Important sync", str(sp))

    # ------------------------------------------------------------ Step 12: escalation
    def _run_escalation(self) -> None:
        """§50-52：keyframe 超预算 → REMOTION 提案；photo slow zoom 原计划 Remotion → JY_NATIVE 提案。"""
        for clip in self.clips:
            kf_count = len(clip.get("keyframes") or [])
            if kf_count > self.keyframe_budget:
                self._add_proposal(
                    kind="ESCALATE_TO_REMOTION",
                    clip_id=clip["clip_id"], asset_id=clip["asset_id"],
                    current_route="JY_NATIVE", proposed_route="REMOTION",
                    reason=f"clip {clip['clip_id']} 关键帧 {kf_count} 超预算 {self.keyframe_budget}"
                           f"（§49-51），建议烘焙为 Remotion 资产",
                    approval_required=True,
                )
        for asset in self.assets:
            atype = str(asset.get("type") or "").upper()
            producer = str(asset.get("producer") or "").upper()
            purpose = str(asset.get("purpose") or "").lower()
            if atype in ("IMAGE", "PHOTO", "STILL", "ARCHIVE_IMAGE") and producer == "REMOTION":
                if any(k in purpose for k in ("slow zoom", "ken burns", "肯尼", "照片缩放",
                                              "photo zoom", "slow pan")):
                    self._add_proposal(
                        kind="DEESCALATE_TO_JY_NATIVE",
                        clip_id="", asset_id=asset["asset_id"],
                        current_route="REMOTION", proposed_route="JY_NATIVE",
                        reason="photo slow zoom 是 JY_NATIVE 能力（§37/§77），"
                               "建议降级为剪映原生缩放（只提案，route 变更需记录，§52）",
                        approval_required=False,
                    )

    # ------------------------------------------------------------ Step 13: complexity
    def _track_type_of(self, track_id: str) -> str:
        for t in self.tracks:
            if t["track_id"] == track_id:
                return t["type"]
        return ""

    def _broll_density_rule(self) -> Optional[Dict[str, Any]]:
        """§75-76 B-roll 密度约束：editorial_direction > config；缺省 3 cuts/min
        （对齐 modules/external-visual/footage.py DEFAULT_B_ROLL_PER_MINUTE=3）。"""
        src = None
        for candidate in (self.editorial.get("b_roll_density"),
                          self.editorial.get("max_cuts_per_minute"),
                          self.config.get("b_roll_density"),
                          self.config["b_roll_density"] if self.config.get("b_roll_density")
                          else None):
            if candidate is not None:
                src = candidate
                break
        if src is None:
            return None
        if isinstance(src, (int, float)):
            return {"max_per_minute": float(src), "source": "editorial_direction"}
        if isinstance(src, dict):
            v = src.get("max") or src.get("max_per_minute") or src.get("max_cuts_per_minute")
            if v is not None:
                return {"max_per_minute": float(v), "source": "editorial_direction.b_roll_density"}
        return None

    def _complexity_metrics(self) -> Dict[str, Any]:
        track_count = len(self.tracks)
        clip_count = len(self.clips)
        baked = [c for c in self.clips if c["editable"] is False and c["replaceable"] is False]
        editable = [c for c in self.clips if c["editable"] is True]
        replaceable = [c for c in self.clips if c["replaceable"] is True]
        keyframe_count = sum(len(c.get("keyframes") or []) for c in self.clips)
        transition_count = sum(
            1 for c in self.clips
            for k in ("transition_in", "transition_out")
            if (c.get(k) or {}).get("type") != "CUT")
        # §75-76 B-roll 密度：长片按 editorial_direction 密度规则；允许 breathing room
        broll_count = sum(1 for c in self.clips
                          if self._track_type_of(c.get("track_id")) == "VIDEO_BROLL")
        duration_min = max(0.01, self.timeline_duration_frames / self.fps / 60.0)
        broll_per_minute = round(broll_count / duration_min, 3)
        density_rule = self._broll_density_rule()
        density_compliant = True
        if density_rule is not None:
            allowed = density_rule["max_per_minute"]
            density_compliant = broll_per_minute <= allowed + 1e-9
            if not density_compliant:
                self.warnings.append(
                    f"B-roll 密度 {broll_per_minute}/min 超 editorial 约束 "
                    f"{allowed}/min（§75-76，需人工合并/删减）")
        metrics = {
            "track_count": track_count,
            "clip_count": clip_count,
            "baked_asset_count": len(baked),
            "editable_clip_count": len(editable),
            "replaceable_asset_count": len(replaceable),
            "keyframe_count": keyframe_count,
            "transition_count": transition_count,
            "b_roll_count": broll_count,
            "b_roll_per_minute": broll_per_minute,
            "b_roll_density_compliant": density_compliant,
        }
        # §162 异常警告（§163：不追求数字最小化，只查异常）
        if track_count > 20:
            self.warnings.append(f"track_count={track_count} 过大（§132 Track Cleanliness）")
        if clip_count > 200:
            self.warnings.append(f"clip_count={clip_count} 异常偏多，检查是否过度碎片化（§130）")
        if keyframe_count > self.keyframe_budget * 4:
            self.warnings.append(f"keyframe_count={keyframe_count} 巨大（§49/§162）")
        # §130 over-fragmentation：同一 continuity_group 必须连续（Planner 不拆，理应全连续）
        for group in self.continuity_groups:
            ids = group["clip_ids"]
            if len(ids) < 2:
                continue
            frames = [next((c["timeline_start_frame"] for c in self.clips
                            if c["clip_id"] == i), None) for i in ids]
            frames = [f for f in frames if f is not None]
            if frames and (max(frames) - min(frames)) > sum(
                    (c["timeline_end_frame"] - c["timeline_start_frame"])
                    for c in self.clips if c["clip_id"] in group["clip_ids"]):
                self.warnings.append(
                    f"continuity_group {group['continuity_group']} 片段不连续（§8/§130）")
        return metrics

    # ------------------------------------------------------------ manifest 装配
    def _build_manifest(self, map_ref: str) -> Dict[str, Any]:
        editability_default = _normalize_enum(
            self.editability.get("default"),
            ("KEEP_EDITABLE", "ASSET_REPLACEABLE", "BAKE"), "KEEP_EDITABLE")
        bm = self.config.get("backend_mapping")
        tracks = []
        for t in self.tracks:
            tt = dict(t)
            if bm:
                tt["backend_mapping"] = dict(bm)
            tracks.append(tt)
        manifest: Dict[str, Any] = {
            "timeline_id": self.config["timeline_id"],
            "backend": self.config["backend"],
            "preferred_timeline_backend": self.config["preferred_timeline_backend"],
            "project_path": self.config["project_path"],
            "canvas": dict(self.config["canvas"]),
            "fps": self.fps,
            "resolution": dict(self.config["resolution"]),
            "duration_frames": self.timeline_duration_frames,
            "tracks": tracks,
            "clips": list(self.clips),
            "text_items": [],
            "subtitle_items": list(self.subtitle_items),
            "audio_tracks": [],
            "sfx_tracks": [],
            "music_tracks": [],
            "overlays": [],
            "keyframes": [],
            "transitions": [],
            "markers": list(self.markers),
            "groups": [],
            "asset_links": list(self.asset_links),
            "replaceable_assets": list(self.replaceable_assets),
            "continuity_groups": list(self.continuity_groups),
            "editability": editability_default,
            "backend_capabilities": dict(self.capabilities),
            "timeline_map_ref": map_ref,
            "ownership": "GENERATED_BASELINE",
            "locked_regions": list(self.locked_regions),
            "baseline_ref": self.config["baseline_ref"],
            "manual_edit_safe": True,
            "version": self.config["version"],
            "status": self.config["status"],
        }
        if self.config["backend_version"]:
            manifest["backend_version"] = self.config["backend_version"]
        return manifest

    # ------------------------------------------------------------ 主流程
    def plan(self) -> Dict[str, Any]:
        # Step 1 帧安全计时
        self._plan_shot_timing()
        # Step 2 轨道（模板预设 + 动态补建）
        self.tracks = _templates_mod.build_tracks(self.template)
        # Step 3-7 视觉资产 / 字幕 / 档案标注
        self._place_visual_clips()
        self._place_subtitles()
        self._place_archive_labels()
        # Step 9 音频
        self._place_voiceover()
        self._place_music()
        self._place_sfx()
        self._place_ambience()
        # Step 11 markers
        self._plan_markers()
        # Step 12 escalation
        self._run_escalation()
        # Step 13 complexity
        complexity = self._complexity_metrics()

        map_ref = self.config["timeline_map_ref"]
        manifest = self._build_manifest(map_ref)
        # 结束：tracks/clips 已含全部内容；replaceable_assets 确定性排序已在生成时保持
        return {
            "manifest": manifest,
            "conflicts": list(self.conflicts),
            "proposals": list(self.proposals),
            "map_ref": map_ref,
            "complexity": complexity,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# 模块级入口（工单 spec：plan_timeline(inputs) -> dict）
# ---------------------------------------------------------------------------

def plan_timeline(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """确定性装配 Timeline Manifest（P7-3 入口）。

    Returns:
        dict：{manifest, conflicts[], proposals[], map_ref, complexity, warnings[]}。
    """
    return TimelinePlanner(inputs).plan()


def dump_plan(result: Dict[str, Any], out_path: Optional[str] = None) -> str:
    """把 plan() 结果序列化为确定性的紧凑 JSON（sort_keys，字节级可复现）。"""
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if out_path is not None:
        from pathlib import Path
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    """最小冒烟：3 shot 基础样例能装配出完整 manifest 且满足基本形状。"""
    inputs = {
        "storyboard": {
            "shots": [
                {"id": "S001", "order": 1, "duration": 3.0},
                {"id": "S002", "order": 2, "duration": 2.0},
                {"id": "S003", "order": 3, "duration": 5.0},
            ]
        },
        "config": {"fps": 30},
    }
    r = plan_timeline(inputs)
    checks = [
        isinstance(r["manifest"], dict),
        r["manifest"]["fps"] == 30,
        r["manifest"]["duration_frames"] == 300,
        len(r["manifest"]["tracks"]) >= 7,
        len(r["manifest"]["clips"]) == 0,
        r["map_ref"] == "TIMELINE_MAP.md",
        r["conflicts"] == [],
    ]
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"planner selftest check #{i} failed")
    print("planner selftest OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
    else:
        print("TimelinePlanner / plan_timeline / time_utils")
        print("timecode(150, 30):", timecode(150, 30))
        print("seconds_to_frames(0.1, 30):", seconds_to_frames(0.1, 30))
        print("to_backend_unit(3, 30):", to_backend_unit(3, 30))
