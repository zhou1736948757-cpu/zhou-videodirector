#!/usr/bin/env python3
"""adapters/pyjianyingdraft/backend.py — PyJianYingDraftBackend（Phase-7 §89-96 / §141-147；P7-5）.

运行环境：``/Users/mac/skills/ZHOU_Videodirector/.venv/bin/python``（pyjianyingdraft 0.3.0，
Python 3.14，stdlib + pyjianyingdraft only）。本文件是 Phase-7 第一版完整 Backend Adapter（§142），
实现 ``modules/timeline-manager/backend/base.py`` 的 ``TimelineBackend`` 13 方法契约：

    capabilities / validate_manifest / create_project / add_track / add_clip / add_text /
    add_subtitle / add_audio / add_keyframes / add_transition / replace_asset /
    export_draft / validate_draft

职责边界（§90）：Adapter 只"翻译意图为后端操作"，不改 Shot 顺序 / 音乐 / Route / Style，
没有导演权。能力真源是 P7-1 的 ``TIMELINE_BACKEND_CAPABILITIES``（本包 ``__init__.py``）：
**不支持的能力（effect_parameter_keyframe / bezier_easing / custom_motion_path，以及
subtitle 无原生轨、AudioSegment.add_keyframe 仅 int 微秒）一律走 fallback 记录，不静默丢**（§92）。

诚实原则（§96）：本 Adapter 只生成 Draft 文件并明确声明
"Draft generated. Human opens JianYing for inspection/export."，**不假装全自动渲染/导出**；
macOS 无 jianying_controller（GUI 自动化仅 win32）。编辑器版本由探针 ``_detect_editor``
动态取值（FR-002）：本机已装剪映专业版 7.4.0（VideoFusion-macOS.app），
draft 打开验证待人工验收（editor_open_verified=false）；未检测到时如实写 UNKNOWN。

路径策略（§116-117）：draft 内素材 ``path`` 一律写**相对 project 根（output_dir）**的路径，
resolved（绝对）路径记录在 export 返回的 backend_metadata / REPORT 中。素材缺失（§118）→
``MISSING_MEDIA`` 标记 + fallback 报告，跳过该 clip，不产出损坏时间线。

版本策略（§136-137）：每次 ``export_draft`` 生成 ``draft_v{n}``（n 递增），不覆盖已有草稿；
同时落 ``timeline/manifest/manifest_v{n}.json`` 基线快照（§138）与
``timeline/reports/BACKEND_FALLBACK_REPORT.md``（§92）。

关键帧：``add_keyframes`` 入口做形状识别（FR-003 / rv-P7-1b known_risk D）——
输入为 motion-spec 形状（含 type/from/to/easing/sampling）时先调
``adapters/pyjianyingdraft.keyframes.build_keyframes`` 转换再落 JY；输入已是
timeline-clip keyframes 形状（``{keyframes:[{property,frame,value,easing?}]}``）时
直落本文件内置最小实现。bezier_easing 不支持 → 采样离散关键帧（sampled=True）。

continuity_group（FR-008 验证结论）：CG 在 manifest 层是单条不拆资产，一个 manifest
clip → 恰好一个 JY segment，JY 片段级本无拆切风险，**无需向 JY 物理片段传播 CG 字段**
（JY 无原生 CG 概念，draft JSON 无此字段）；§8 复杂连续 Motion 不拆语义由单资产保证，
CG 关联在 manifest 快照（timeline/manifest/manifest_v{n}.json）中可回查。
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 兼容加载：
#   1) ``modules/timeline-manager/backend/base.py``（目录名带连字符，无法常规 import）
#   2) 本包 ``__init__.py`` 的 TIMELINE_BACKEND_CAPABILITIES（相对 import 失败时兜底）
# ---------------------------------------------------------------------------
def _load_timeline_backend_base() -> Any:
    """用 importlib 加载 ``modules/timeline-manager/backend/base.py`` 的 TimelineBackend。"""
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _path = os.path.join(_root, "modules", "timeline-manager", "backend", "base.py")
    _spec = importlib.util.spec_from_file_location("timeline_backend_base", _path)
    if _spec is None or _spec.loader is None:
        raise ImportError("无法加载 timeline-manager/backend/base.py: %s" % _path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod.TimelineBackend


TimelineBackend = _load_timeline_backend_base()

try:  # 正常包路径：adapters.pyjianyingdraft
    _PYJY_ADAPTER = importlib.import_module("adapters.pyjianyingdraft")
except ImportError:  # 直接以文件运行时的兜底
    _dir = os.path.dirname(os.path.abspath(__file__))
    _spec = importlib.util.spec_from_file_location("pjy_adapter_pkg", os.path.join(_dir, "__init__.py"))
    _mod = importlib.util.module_from_spec(_spec)  # type: ignore
    _spec.loader.exec_module(_mod)  # type: ignore
    _PYJY_ADAPTER = _mod

TIMELINE_BACKEND_CAPABILITIES = _PYJY_ADAPTER.TIMELINE_BACKEND_CAPABILITIES

from pyJianYingDraft import (
    AudioMaterial,
    ClipSettings,
    DraftFolder,
    KeyframeProperty,
    MaskType,
    MixModeType,
    ScriptFile,
    TextSegment,
    TextStyle,
    Timerange,
    TrackSpec,
    TrackType,
    TransitionType,
    VideoMaterial,
    VideoSegment,
)
from pyJianYingDraft.audio_segment import AudioSegment
from pyJianYingDraft.exceptions import SegmentOverlap
from pyJianYingDraft.local_materials import CropSettings

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SEC = 1_000_000  # 1s = 1e6 微秒

# §43 17 项能力键顺序（与 P7-1 矩阵一致）
CAPABILITY_KEYS = [
    "basic_video", "multi_track", "text", "subtitle", "position_keyframe",
    "scale_keyframe", "rotation_keyframe", "opacity_keyframe", "volume_keyframe",
    "transition", "filter", "mask", "blend_mode", "effect_parameter_keyframe",
    "bezier_easing", "custom_motion_path", "template_import",
]

# §15 15 种 Track type → JY 轨道（三大类 video/text/audio；无独立 subtitle/效用轨）
# UTILITY 无 JY 映射 → fallback 记录，不静默丢。
_TRACK_TYPE_TO_JY: Dict[str, Optional[TrackType]] = {
    "VIDEO_MAIN": TrackType.video,
    "VIDEO_BROLL": TrackType.video,
    "VIDEO_OVERLAY": TrackType.video,
    "VIDEO_MOTION": TrackType.video,
    "VIDEO_3D": TrackType.video,
    "VIDEO_AI": TrackType.video,
    "IMAGE": TrackType.video,
    "TEXT": TrackType.text,
    "SUBTITLE": TrackType.text,   # 无原生字幕轨 → text 轨模拟（P7-1 §2）
    "GRAPHIC": TrackType.text,    # 图形层按文本轨近似（JY 贴纸需 resource_id，本单无来源）
    "VOICEOVER": TrackType.audio,
    "MUSIC": TrackType.audio,
    "SFX": TrackType.audio,
    "AMBIENCE": TrackType.audio,
    "UTILITY": None,              # 效用轨 JY 无对应 → fallback
}

# §15 轨道类型 → 建议命名前缀（用于无 name 时生成唯一 JY 轨道名）
_TRACK_PREFIX = {
    "VIDEO_MAIN": "V1_MAIN", "VIDEO_BROLL": "V_BROLL", "VIDEO_OVERLAY": "V_OVERLAY",
    "VIDEO_MOTION": "V_MOTION", "VIDEO_3D": "V_3D", "VIDEO_AI": "V_AI",
    "IMAGE": "IMG", "TEXT": "TXT", "SUBTITLE": "SUB", "GRAPHIC": "GRPH",
    "VOICEOVER": "VO", "MUSIC": "MUS", "SFX": "SFX", "AMBIENCE": "AMB", "UTILITY": "UTIL",
}

# §42 8 属性枚举 → JY KeyframeProperty 成员名
_PROPERTY_TO_JY: Dict[str, str] = {
    "POSITION_X": "position_x",
    "POSITION_Y": "position_y",
    "SCALE": "uniform_scale",   # JY uniform_scale 与 scale_x/y 互斥
    "SCALE_X": "scale_x",
    "SCALE_Y": "scale_y",
    "ROTATION": "rotation",
    "OPACITY": "alpha",         # 仅 VideoSegment/TextSegment（VisualSegment）
    "VOLUME": "volume",
}

# §72 transition_basic 四枚举 → JY TransitionType 名称（from_name 解析）
_TRANSITION_MAP: Dict[str, Optional[str]] = {
    "CUT": None,        # §74 cut 是合法且常用转场 → 不产生 JY 转场对象
    "DISSOLVE": "叠化",
    "SLIDE": "滑动",
    "FADE": "闪白",
}

# blend_mode（英语）→ JY MixModeType 中文名；normal 不产生 mix mode
_BLEND_MODE_MAP: Dict[str, str] = {
    "multiply": "正片叠底",
    "screen": "滤色",
    "overlay": "叠加",
    "soft-light": "柔光",
    "hard-light": "强光",
    "lighten": "变亮",
    "darken": "变暗",
    "color-dodge": "颜色减淡",
    "color-burn": "颜色加深",
    "linear-burn": "线性加深",
}

# mask 英语 → JY MaskType 中文名
_MASK_TYPE_MAP: Dict[str, str] = {
    "linear": "线性", "mirror": "镜面", "circle": "圆形",
    "rect": "矩形", "rectangle": "矩形", "heart": "爱心", "star": "星形",
}

_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".wma"}

# 关键帧预算（§49）：单 clip ≤8（超出记录警告 + REMOTION 建议，不静默丢）
KEYFRAME_BUDGET_PER_CLIP = 8
# bezier/spring/custom easing 采样点数（§47-48，本单最小实现用 6 点；P7-4 判定表对齐后可能覆盖）
_BEZIER_SAMPLE_POINTS = 6

# 替换冲突阈值（§36）：时长变化 >25% 或宽高比变化 >10% 视为"剧变"
_CONFLICT_DURATION_RATIO = 0.25
_CONFLICT_ASPECT_RATIO = 0.10


# ---------------------------------------------------------------------------
# 内部状态
# ---------------------------------------------------------------------------
class _ProjectState:
    """单个 project 的构建期状态（create_project → export_draft 生命周期）。"""

    def __init__(self) -> None:
        self.manifest: Dict[str, Any] = {}
        self.project_id: str = ""
        self.sf: Optional[ScriptFile] = None
        self.width: int = 1920
        self.height: int = 1080
        self.fps: float = 30.0
        self.canvas: Dict[str, int] = {}
        self.assets: Dict[str, Dict[str, Any]] = {}   # asset_id → {"path","kind"}
        self.track_names: Dict[str, str] = {}         # 逻辑 track_id(TR-###) → JY track name
        self.track_refs: Dict[str, Any] = {}          # 逻辑 track_id → TrackRef
        self.track_types: Dict[str, str] = {}         # 逻辑 track_id → §15 track_type
        self.segments: Dict[str, Any] = {}            # clip_id → JY segment（Video/Text/Audio）
        self.clip_info: Dict[str, Dict[str, Any]] = {}  # clip_id → 记录（timing/material/track）
        self.material_registry: Dict[str, Any] = {}   # asset_id → (JY material, abs_path)
        self.used_names: set = set()
        self.warnings: List[str] = []
        self.unsupported: List[Dict[str, str]] = []   # {feature, requested, backend, fallback}
        self.missing_media: List[Dict[str, str]] = []  # {asset_id, path, clip_id}
        self.conflicts: List[Dict[str, str]] = []      # {clip_id, reason, message}
        self.draft_export_count: int = 0
        self.draft_id: str = ""            # R3-P7：uuid4 唯一草稿 ID（create_project 生成）
        self.draft_display_name: str = ""  # R3-P7：显示名（draft_meta_info.json draft_name 字段）
        self.out_dir: Optional[str] = None
        self.asset_root: Optional[str] = None


def _err(code: str, message: str, fallback: str = "") -> Dict[str, Any]:
    return {"ok": False, "error": code, "message": message, "fallback": fallback}


def _ok(result: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# FR-002：编辑器版本动态探测（与 adapters/pyjianyingdraft/__init__.py 探针同源）
# ---------------------------------------------------------------------------
_EDITOR_DETECT_CACHE: Dict[str, Optional[str]] = {}


def _detect_editor_version() -> str:
    """探测本机剪映专业版版本（FR-002 / rv-P7-1b known_risk A）。

    优先调用 ``adapters.pyjianyingdraft._detect_editor``（读 /Applications 下
    VideoFusion-macOS.app 的 Info.plist），失败时回退 ``probe_backend()['editor_version']``。
    取不到时返回 "UNKNOWN" 兜底（本机未安装或路径异常），诚实声明如实呈现，不假设。
    结果缓存（探测只读文件系统，重复调用昂贵且应保持确定性）。
    """
    if "version" in _EDITOR_DETECT_CACHE:
        return _EDITOR_DETECT_CACHE["version"]  # type: ignore[return-value]
    version: Optional[str] = None
    try:
        fn = getattr(_PYJY_ADAPTER, "_detect_editor", None)
        if callable(fn):
            info = fn()
            if isinstance(info, dict) and info.get("version"):
                version = str(info["version"])
        if version is None:
            probe = getattr(_PYJY_ADAPTER, "probe_backend", None)
            if callable(probe):
                pb = probe()
                if isinstance(pb, dict) and pb.get("editor_version"):
                    version = str(pb["editor_version"])
    except Exception:  # noqa: BLE001 — 探针失败不阻断 backend，兜底 UNKNOWN
        version = None
    _EDITOR_DETECT_CACHE["version"] = version or "UNKNOWN"
    return _EDITOR_DETECT_CACHE["version"]


def _detect_editor_app() -> str:
    """探测本机剪映应用名（VideoFusion-macOS.app）；未检测到返回空串。"""
    if "app" in _EDITOR_DETECT_CACHE:
        return _EDITOR_DETECT_CACHE["app"] or ""  # type: ignore[return-value]
    app = ""
    try:
        fn = getattr(_PYJY_ADAPTER, "_detect_editor", None)
        if callable(fn):
            info = fn()
            if isinstance(info, dict) and info.get("name"):
                app = str(info["name"])
    except Exception:  # noqa: BLE001
        app = ""
    _EDITOR_DETECT_CACHE["app"] = app
    return app


def _editor_declaration() -> Tuple[str, str]:
    """返回 (known_limitations/诚实声明文案, tested_editor_version 值)。

    文案由探针动态取值（FR-002）：本机已装剪映专业版 <版本>（<app 名>）；
    draft 打开验证待人工验收（editor_open_verified=false）。未检测到 → UNKNOWN。
    """
    version = _detect_editor_version()
    app = _detect_editor_app()
    if version == "UNKNOWN" or not app:
        return (
            "本机未检测到剪映安装（tested_editor_version=UNKNOWN），未做真实编辑器打开验证",
            "UNKNOWN",
        )
    return (
        "本机已装剪映专业版 %s（%s）；draft 打开验证待人工验收（editor_open_verified=false）"
        % (version, app),
        "%s (installed, open_verified=false)" % version,
    )


_PLANNER_TIME_UTILS: Any = None


def _load_planner_time_utils() -> Any:
    """importlib 加载 planner.time_utils（FR-006 换算权威实现所在模块）。

    ``modules.timeline-manager`` 为连字符包，不能用 ``from x import y`` 语句，
    用 importlib.import_module 全名加载（同 planner.py 加载 templates 约定）。
    加载失败返回 None（调用方走本地兜底，docstring 注明）。
    """
    global _PLANNER_TIME_UTILS
    if _PLANNER_TIME_UTILS is None:
        try:
            import importlib as _il
            _PLANNER_TIME_UTILS = _il.import_module("modules.timeline-manager.planner")
        except Exception:  # noqa: BLE001 — 权威模块不可用时本地兜底，不允许本函数崩
            _PLANNER_TIME_UTILS = False
    return _PLANNER_TIME_UTILS if _PLANNER_TIME_UTILS is not False else None


def _frames_to_us(frames: Any, fps: float) -> int:
    """整数帧 → 微秒（§26-27 帧安全计时；§28 时间换算）。

    换算权威实现位于 planner.time_utils.to_backend_unit（FR-006：planner/motion/
    backend 三处同源，round-half-even，与 Phase 5 motion.py:294 一致）；
    权威模块不可加载时本地公式兜底（同语义，docstring 注明）。
    异常（TypeError/ValueError/ZeroDivisionError）返回 0，与历史行为一致。
    """
    try:
        tu = _load_planner_time_utils()
        if tu is not None:
            out = tu.to_backend_unit(int(round(float(frames))),
                                     max(1, int(round(float(fps)))), "us")
            if out is not None:
                return out
        return int(round(float(frames) * SEC / float(fps)))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0


def _is_motion_spec_shape(spec: Any) -> bool:
    """FR-003 形状识别：motion-spec 形状 vs timeline-clip keyframes 形状。

    - motion-spec 形状：含 ``type``（动效类型）且含 ``from``/``to``/``properties``
      之一（``normalize_motion_spec`` 输出必然满足；raw motion-spec 也满足）。
    - timeline-clip 形状（§45 manifest keyframes）：顶层含 ``keyframes`` 列表。
    """
    if not isinstance(spec, dict):
        return False
    if isinstance(spec.get("keyframes"), list):
        return False  # timeline-clip 形状 → 直落
    return (isinstance(spec.get("type"), str) and bool(spec.get("type"))
            and (spec.get("from") is not None or spec.get("to") is not None
                 or spec.get("properties") is not None))


def _load_motion_module() -> Any:
    """importlib 加载 motion.py（P7-4 plan_sampling）；失败返回 None（桥退化为端点）。"""
    try:
        import importlib as _il
        return _il.import_module("modules.timeline-manager.motion")
    except Exception:  # noqa: BLE001
        return None


def _load_keyframes_module() -> Any:
    """加载同包 keyframes.py（build_keyframes）；包路径失败时按文件路径兜底。"""
    try:
        import importlib as _il
        return _il.import_module("adapters.pyjianyingdraft.keyframes")
    except Exception:  # noqa: BLE001
        _dir = os.path.dirname(os.path.abspath(__file__))
        _spec = importlib.util.spec_from_file_location(
            "pjy_keyframes_mod", os.path.join(_dir, "keyframes.py"))
        _mod = importlib.util.module_from_spec(_spec)  # type: ignore
        _spec.loader.exec_module(_mod)  # type: ignore
        return _mod


# ---------------------------------------------------------------------------
# 后端类
# ---------------------------------------------------------------------------
class PyJianYingDraftBackend(TimelineBackend):
    """pyJianYingDraft 0.3.0 后端适配器（§142）：TIMELINE_MANIFEST → JY Draft。

    Adapter 只翻译意图（§90）；能力真源 = P7-1 ``TIMELINE_BACKEND_CAPABILITIES``
    （本包 ``__init__.py``，与 ``work/p7-1/BACKEND_CAPABILITY_REPORT.md`` 同源）。
    """

    backend = "pyJianYingDraft"
    backend_version = "0.3.0"

    def __init__(self, out_dir: Optional[str] = None, asset_root: Optional[str] = None) -> None:
        """可选的默认输出目录与素材根目录（均可在 create_project/export_draft 覆盖）。"""
        self._projects: Dict[str, _ProjectState] = {}
        self._default_out_dir = out_dir
        self._default_asset_root = asset_root
        _editor_note, _editor_version = _editor_declaration()
        self._compatibility_report = {
            "tested_backend_version": "pyJianYingDraft 0.3.0",
            "tested_editor_version": _editor_version,  # FR-002：探针动态取值（7.4.0 installed）
            "supported_features": [
                "basic_video", "multi_track", "text", "subtitle", "position_keyframe",
                "scale_keyframe", "rotation_keyframe", "opacity_keyframe", "volume_keyframe",
                "transition", "filter", "mask", "blend_mode", "template_import",
            ],
            "known_limitations": [
                "effect_parameter_keyframe 不支持（特效参数静态标量，无参数关键帧）",
                "bezier_easing 不支持（关键帧仅 Line 插值，需采样为离散关键帧）",
                "custom_motion_path 不支持（无路径关键帧）",
                "无独立 subtitle 轨（文本轨 + auto_wrapping 模拟）",
                "AudioSegment.add_keyframe 不接受字符串时间偏移（仅 int 微秒）",
                "macOS 无 jianying_controller（GUI 自动化仅 win32；自动导出仅剪映 6 及以下）",
                "新版本剪映 draft_content.json 非明文 JSON，模板回读需 fallback_loader",
                _editor_note,
            ],
            "probe_date": "2026-08-15",
        }

    # ----------------------------------------------------------------- §141
    def capabilities(self) -> Dict[str, Any]:
        """返回 P7-1 能力矩阵的 Backend 视图（§43 17 项；与 BACKEND_CAPABILITY_REPORT 同源）。

        返回值契约（base.py docstring）：``result`` 直接映射 capability_key →
        {supported, fallback, evidence}。
        """
        result: Dict[str, Any] = {}
        for key in CAPABILITY_KEYS:
            entry = TIMELINE_BACKEND_CAPABILITIES.get(key, {})
            result[key] = {
                "supported": entry.get("supported", False),
                "fallback": entry.get("fallback") or None,
                "evidence": entry.get("evidence", ""),
            }
        return _ok(result)

    # ---------------------------------------------------- validate_manifest
    def validate_manifest(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """输入侧校验（§109-115 基础项）：canvas/fps/轨道映射合法/clip timing/素材存在性。

        深度校验（重叠/字幕碰撞/gap/continuity）归 P7-6；此处只做后端侧必需项。
        素材不存在 → ``MISSING_MEDIA`` WARNING（§118），不判 ERROR（后端会跳过该 clip）。
        """
        issues: List[Dict[str, Any]] = []
        if not isinstance(manifest, dict):
            return _ok({"valid": False, "issues": [
                {"level": "ERROR", "code": "MANIFEST_NOT_OBJECT", "message": "manifest 必须是对象", "clip_id": None}]})

        # canvas
        canvas = manifest.get("canvas") or {}
        w, h = canvas.get("w"), canvas.get("h")
        if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
            issues.append({"level": "ERROR", "code": "INVALID_CANVAS",
                           "message": "canvas.w/h 必须为正整数", "clip_id": None})
        # fps
        fps = manifest.get("fps")
        if not isinstance(fps, (int, float)) or fps <= 0:
            issues.append({"level": "ERROR", "code": "INVALID_FPS",
                           "message": "fps 必须为正数", "clip_id": None})

        # 资产表（assets dict 或 asset_links list）
        assets: Dict[str, Dict[str, Any]] = {}
        if isinstance(manifest.get("assets"), dict):
            assets = dict(manifest["assets"])
        for link in manifest.get("asset_links") or []:
            if isinstance(link, dict) and link.get("asset_id"):
                assets.setdefault(link["asset_id"], link)

        # tracks
        track_types: Dict[str, str] = {}
        for tr in manifest.get("tracks") or []:
            if not isinstance(tr, dict) or not tr.get("track_id"):
                issues.append({"level": "ERROR", "code": "TRACK_NO_ID",
                               "message": "轨道缺少 track_id", "clip_id": None})
                continue
            tid = tr["track_id"]
            ttype = tr.get("type")
            if ttype not in _TRACK_TYPE_TO_JY:
                issues.append({"level": "ERROR", "code": "INVALID_TRACK_TYPE",
                               "message": "track %s 的 type=%r 不在 15 枚举内" % (tid, ttype), "clip_id": None})
            track_types[tid] = ttype

        # clips
        for clip in manifest.get("clips") or []:
            if not isinstance(clip, dict) or not clip.get("clip_id"):
                issues.append({"level": "ERROR", "code": "CLIP_NO_ID", "message": "clip 缺少 clip_id", "clip_id": None})
                continue
            cid = clip["clip_id"]
            start, end = clip.get("timeline_start_frame"), clip.get("timeline_end_frame")
            if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
                issues.append({"level": "ERROR", "code": "NEGATIVE_OR_REVERSED_TIMING",
                               "message": "clip %s 的 timeline_start/end 非法（需 0<=start<end）" % cid,
                               "clip_id": cid})
            tid = clip.get("track_id")
            if tid and tid not in track_types:
                issues.append({"level": "ERROR", "code": "CLIP_TRACK_NOT_FOUND",
                               "message": "clip %s 引用不存在的轨道 %s" % (cid, tid), "clip_id": cid})
            # 素材存在性
            asset_id = clip.get("asset_id")
            path = self._asset_path_from(assets, clip)
            if path is None:
                issues.append({"level": "WARNING", "code": "ASSET_PATH_UNKNOWN",
                               "message": "clip %s 的资产 %s 未提供路径" % (cid, asset_id), "clip_id": cid})
            elif not os.path.exists(path):
                issues.append({"level": "WARNING", "code": "MISSING_MEDIA",
                               "message": "clip %s 的资产 %s 文件不存在: %s" % (cid, asset_id, path),
                               "clip_id": cid})

        valid = not any(issue["level"] == "ERROR" for issue in issues)
        return _ok({"valid": valid, "issues": issues})

    # ------------------------------------------------------ create_project
    def create_project(self, manifest: Dict[str, Any],
                       out_dir: Optional[str] = None,
                       draft_name: Optional[str] = None) -> Dict[str, Any]:
        """初始化 project 状态（§89）：解析 manifest，构造内存 ScriptFile。

        - ``out_dir`` / ``draft_name``：可选的默认导出目录/草稿显示名（会被 export_draft 的
          output_dir / options 覆盖）。**不在本方法落盘**——真实 Draft 生成统一在
          ``export_draft``（§136-137 版本递增、不覆盖）。
        - 目录约定（§135）：``<out_dir>/timeline/backend/draft_v{n}/``。
        - R3-P7：本方法用 ``str(uuid.uuid4()).upper()`` 生成唯一 ``draft_id``（非
          pyJianYingDraft 模板默认值），保存到 project 状态；``export_draft`` 把
          ``draft_id`` 与显示名写入 ``draft_meta_info.json``。``draft_name`` 缺省规则：
          未传时由 project_id 派生 ``ZHOU-<project_id>-v1``（如 ``ZHOU-TL-001-v1``），
          调用方不传仍可用（缺省值规则 docstring 化）。
        """
        state = _ProjectState()
        state.manifest = manifest
        state.project_id = manifest.get("timeline_id") or "TL-001"
        state.draft_id = str(uuid.uuid4()).upper()  # R3-P7：唯一草稿 ID（非模板默认 BC69C7CD…）
        state.out_dir = out_dir or self._default_out_dir
        # R3-P7：显示名缺省规则（docstring）——project_id 派生；E2E 场景显式传
        # "ZHOU-A-90s-v1"/"ZHOU-B-8min-v1" 覆盖。
        state.draft_display_name = draft_name or ("ZHOU-%s-v1" % (state.project_id or "TL"))
        state.asset_root = self._default_asset_root

        canvas = manifest.get("canvas") or {"w": 1920, "h": 1080}
        state.width, state.height = int(canvas.get("w", 1920)), int(canvas.get("h", 1080))
        state.canvas = {"w": state.width, "h": state.height}
        state.fps = float(manifest.get("fps", 30.0))

        # 资产表：manifest["assets"] dict 或 asset_links list
        if isinstance(manifest.get("assets"), dict):
            for aid, ainfo in manifest["assets"].items():
                state.assets[aid] = ainfo if isinstance(ainfo, dict) else {"path": ainfo}
        for link in manifest.get("asset_links") or []:
            if isinstance(link, dict) and link.get("asset_id"):
                state.assets.setdefault(link["asset_id"], link)

        # 模板模式（§93-94）：manifest 标注 template 且可读 → 用之；不可用不影响 manifest 构建路径
        template_used = None
        template_ref = manifest.get("template_draft")
        if template_ref and os.path.exists(template_ref):
            try:
                folder = DraftFolder(os.path.dirname(template_ref))
                state.sf = folder.load_template(os.path.basename(template_ref))
                template_used = template_ref
                self._record(state, "template_import", "template_draft=" + str(template_ref),
                             "partial",
                             "模板已加载（明文 JSON 前提，fallback_loader 未提供）；new version drafts 需 fallback_loader，不可读时走 manifest 构建")
            except Exception as exc:  # noqa: BLE001 — 模板不可用不阻断 manifest 路径（§94）
                state.sf = ScriptFile(state.width, state.height, int(state.fps), True)
                self._record(state, "template_import", "template_draft=" + str(template_ref),
                             "partial",
                             "模板读取失败: %s；按 §140 生成新版本而非覆盖，模板不影响 manifest 构建" % exc)
        else:
            state.sf = ScriptFile(state.width, state.height, int(state.fps), True)

        duration_us = _frames_to_us(manifest.get("duration_frames", 0), state.fps)
        state.sf.duration = duration_us

        self._projects[state.project_id] = state
        return _ok({
            "project_id": state.project_id,
            "draft_id": state.draft_id,                    # R3-P7：唯一草稿 ID
            "draft_name": state.draft_display_name,        # R3-P7：显示名
            "backend": self.backend,
            "backend_version": self.backend_version,
            "canvas": state.canvas,
            "fps": int(state.fps) if float(state.fps).is_integer() else state.fps,
            "duration_us": state.sf.duration,
            "template_used": template_used,
        })

    # ---------------------------------------------------------- add_track
    def add_track(self, project_id: str, track_spec: Dict[str, Any]) -> Dict[str, Any]:
        """按 §15 15 种 track_type 映射 JY 轨道（video/text/audio 三大类）。

        name/order/muted 尽力映射（§14 九键）；UTILITY 无 JY 映射 → fallback 记录，
        返回 ``{ok: False, error: TRACK_TYPE_UNSUPPORTED}``。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        track_type = track_spec.get("type") or track_spec.get("track_type")
        track_id = track_spec.get("track_id")
        if track_type not in _TRACK_TYPE_TO_JY:
            return _err("INVALID_TRACK_TYPE", "track_type=%r 不在 15 枚举内" % track_type)
        jy_type = _TRACK_TYPE_TO_JY[track_type]
        if jy_type is None:  # UTILITY
            self._record(state, "multi_track", "track_type=" + track_type,
                         "unsupported",
                         "JY 无 UTILITY 效用轨类型；该轨道跳过，语义保存在 Manifest（Track System Truth）")
            return _err("TRACK_TYPE_UNSUPPORTED",
                        "track_type=%s 无 JY 映射" % track_type,
                        "该轨道跳过；语义保存在 Manifest（Track System Truth）")

        name = self._unique_track_name(state, track_spec.get("name") or _TRACK_PREFIX.get(track_type, track_type))
        muted = bool(track_spec.get("muted", False))
        try:
            ref = state.sf.append_track(TrackSpec(jy_type, name=name, mute=muted))
        except NameError as exc:  # 同名/同类型未命名冲突
            return _err("TRACK_NAME_CONFLICT", str(exc), "换名重试或跳过该轨道")
        state.track_names[track_id] = name
        state.track_refs[track_id] = ref
        state.track_types[track_id] = track_type
        order = track_spec.get("order")
        # JY 轨道顺序 = 追加顺序；manifest 的 order 尽力映射，异常记录 backend_metadata
        if order is not None and not isinstance(order, int):
            state.warnings.append("track %s 的 order 非整数，忽略" % track_id)
        return _ok({
            "track_id": track_id,
            "track_ref": name,
            "track_type": track_type,
            "name": name,
            "order": order,
        })

    def _unique_track_name(self, state: _ProjectState, base: str) -> str:
        """JY 轨道名必须唯一（同名拒绝）；重名加 _2/_3 后缀。"""
        name = base or "TRACK"
        if name not in state.used_names:
            state.used_names.add(name)
            return name
        i = 2
        while "%s_%d" % (name, i) in state.used_names:
            i += 1
        final = "%s_%d" % (name, i)
        state.used_names.add(final)
        return final

    # ----------------------------------------------------------- add_clip
    def add_clip(self, project_id: str, track_ref: str, clip_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加视频/图片片段（§29-32/§84）。

        - 资产路径解析顺序：clip_spec["asset"]["path"] > manifest assets 表。
        - 文件不存在 → ``MISSING_MEDIA`` 标记 + 跳过该 clip（§118，不产出损坏时间线）。
        - audio_behavior=MUTE → volume=0.0（§84）。
        - proxy/original（§31-32）：按 policy 选择 proxy 或 original（存在性判断）。
        - 相对路径在 export 阶段统一改写（§117）。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        clip_id = clip_spec.get("clip_id")
        asset_id = clip_spec.get("asset_id")
        if not clip_id or not asset_id:
            return _err("CLIP_MISSING_IDS", "clip_spec 需要 clip_id 与 asset_id")

        # 解析轨道
        seg_track = self._resolve_jy_track(state, track_ref)
        if seg_track is None:
            return _err("TRACK_NOT_FOUND", "轨道 %r 不存在" % track_ref)

        # 解析资产路径
        path, kind = self._resolve_asset_path(state, asset_id, clip_spec)
        if path is None:
            self._mark_missing(state, asset_id, None, clip_id, reason="ASSET_PATH_UNKNOWN")
            return _ok({"clip_id": clip_id, "skipped": True, "reason": "MISSING_MEDIA",
                        "track_id": track_ref, "start_us": 0, "duration_us": 0,
                        "source_in_us": 0, "source_out_us": 0, "material_id": ""})
        if not os.path.exists(path):
            self._mark_missing(state, asset_id, path, clip_id, reason="MISSING_MEDIA")
            return _ok({"clip_id": clip_id, "skipped": True, "reason": "MISSING_MEDIA",
                        "track_id": track_ref, "start_us": 0, "duration_us": 0,
                        "source_in_us": 0, "source_out_us": 0, "material_id": ""})

        # proxy/original（§31-32）
        path = self._apply_proxy_policy(state, clip_spec, path)

        fps = state.fps
        start_us = _frames_to_us(clip_spec.get("timeline_start_frame", 0), fps)
        end_us = _frames_to_us(clip_spec.get("timeline_end_frame", 0), fps)
        target = Timerange(start_us, max(end_us - start_us, 1))
        source_in_us = _frames_to_us(clip_spec.get("source_in_frame", 0), fps)
        source_out_us = _frames_to_us(clip_spec.get("source_out_frame", 0), fps)
        source = None
        if "source_in_frame" in clip_spec or "source_out_frame" in clip_spec:
            src_dur = max(source_out_us - source_in_us, 1)
            source = Timerange(source_in_us, src_dur)
        speed = clip_spec.get("speed")

        # 音频行为（§84）
        volume = 1.0
        if clip_spec.get("audio_behavior") == "MUTE":
            volume = 0.0

        clip_settings = self._build_clip_settings(state, clip_spec)

        try:
            material, abs_path = self._material_for(state, asset_id, path, kind, clip_spec.get("crop"))
            segment = VideoSegment(
                material, target,
                source_timerange=source, speed=speed, volume=volume,
                clip_settings=clip_settings,
            )
        except (ValueError, TypeError) as exc:
            return _err("CLIP_BUILD_FAILED", "构造视频片段失败: %s" % exc)

        # blend_mode / mask 扩展（需在 add_segment 前应用，素材 ref 才会进 materials）
        self._apply_clip_extras(state, segment, clip_id, clip_spec)

        # 轨道类型匹配检查（如 GRAPHIC→text 轨上放视频片段会 TypeError）
        try:
            state.sf.add_segment(segment, seg_track)
        except TypeError as exc:
            self._record(state, "multi_track", "clip=%s on track=%s" % (clip_id, track_ref),
                         "unsupported", "JY 片段类型与轨道不匹配: %s" % exc,
                         "该 clip 跳过；语义保存在 Manifest")
            return _err("SEGMENT_TRACK_MISMATCH", str(exc), "该 clip 跳过；语义保存在 Manifest")
        except SegmentOverlap as exc:
            return _err("SEGMENT_OVERLAP", "片段重叠: %s" % exc, "调整目标时间范围")

        self._remember_clip(state, clip_id, segment, track_ref, start_us, end_us - start_us,
                            source_in_us, source_out_us, asset_id, abs_path,
                            start_frame=clip_spec.get("timeline_start_frame"))
        return _ok({
            "clip_id": clip_id,
            "track_id": track_ref,
            "start_us": start_us,
            "duration_us": max(end_us - start_us, 1),
            "source_in_us": source_in_us,
            "source_out_us": source_out_us,
            "material_id": segment.material_id,
        })

    # ----------------------------------------------------------- add_text
    def add_text(self, project_id: str, track_ref: str, text_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加文本片段（§53-57）：TextSegment + TextStyle（映射 VISUAL_BIBLE 字段）。"""
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        seg_track = self._resolve_jy_track(state, track_ref)
        if seg_track is None:
            return _err("TRACK_NOT_FOUND", "轨道 %r 不存在" % track_ref)

        text = text_spec.get("text", "")
        start_us = _frames_to_us(text_spec.get("start_frame", 0), state.fps)
        end_us = _frames_to_us(text_spec.get("end_frame", 0), state.fps)
        trange = Timerange(start_us, max(end_us - start_us, 1))
        style = self._build_text_style(text_spec.get("style") or {}, auto_wrapping=False)
        clip_settings = self._text_position_settings(text_spec, default_y=0.0)

        segment = TextSegment(text, trange, style=style, clip_settings=clip_settings)
        try:
            state.sf.add_segment(segment, seg_track)
        except (TypeError, SegmentOverlap) as exc:
            return _err("TEXT_ADD_FAILED", "添加文本片段失败: %s" % exc)
        self._remember_clip(state, text_spec.get("text_id") or text_spec.get("clip_id"),
                            segment, track_ref, start_us, end_us - start_us, 0, 0, None, None,
                            start_frame=text_spec.get("start_frame"))
        return _ok({
            "text_id": text_spec.get("text_id") or text_spec.get("clip_id"),
            "track_id": track_ref,
            "start_us": start_us,
            "duration_us": max(end_us - start_us, 1),
            "text": text,
        })

    # -------------------------------------------------------- add_subtitle
    def add_subtitle(self, project_id: str, track_ref: str, subtitle_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加字幕片段（§53-57）：text 轨模拟（P7-1：无原生 subtitle 轨）。

        ``auto_wrapping=True`` → JY 素材 ``type="subtitle"``（text_segment.py:446），
        保留 KEEP_EDITABLE 语义（§55：JY 文本天然可编辑，不烘焙）。机制标注 ``text_track``。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        seg_track = self._resolve_jy_track(state, track_ref)
        if seg_track is None:
            return _err("TRACK_NOT_FOUND", "轨道 %r 不存在" % track_ref)

        text = subtitle_spec.get("text", "")
        start_us = _frames_to_us(subtitle_spec.get("start_frame", 0), state.fps)
        end_us = _frames_to_us(subtitle_spec.get("end_frame", 0), state.fps)
        trange = Timerange(start_us, max(end_us - start_us, 1))
        style = self._build_text_style(subtitle_spec.get("style") or {}, auto_wrapping=True)
        # 字幕默认位置：底部（y=0.1 归一化 → transform_y=-0.8，对齐 import_srt 默认）
        clip_settings = self._text_position_settings(subtitle_spec, default_y=0.1)

        segment = TextSegment(text, trange, style=style, clip_settings=clip_settings)
        try:
            state.sf.add_segment(segment, seg_track)
        except (TypeError, SegmentOverlap) as exc:
            return _err("SUBTITLE_ADD_FAILED", "添加字幕片段失败: %s" % exc)
        self._remember_clip(state, subtitle_spec.get("subtitle_id") or subtitle_spec.get("clip_id"),
                            segment, track_ref, start_us, end_us - start_us, 0, 0, None, None,
                            start_frame=subtitle_spec.get("start_frame"))
        return _ok({
            "subtitle_id": subtitle_spec.get("subtitle_id") or subtitle_spec.get("clip_id"),
            "track_id": track_ref,
            "start_us": start_us,
            "duration_us": max(end_us - start_us, 1),
            "text": text,
            "mechanism": "text_track",   # 无原生字幕轨（P7-1 §2）
        })

    # ---------------------------------------------------------- add_audio
    def add_audio(self, project_id: str, track_ref: str, audio_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加音频片段（§58-71）：volume/fade（add_fade）/ducking 音量关键帧。

        - AudioSegment.add_keyframe **只接受 int 微秒**（P7-1：audio_segment.py:189）——
          统一先转 int 再下发。
        - ducking_plan: [{frame|time_us, volume}] → volume 关键帧（§66-67）。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        seg_track = self._resolve_jy_track(state, track_ref)
        if seg_track is None:
            return _err("TRACK_NOT_FOUND", "轨道 %r 不存在" % track_ref)

        audio_id = audio_spec.get("audio_id") or audio_spec.get("clip_id")
        asset_id = audio_spec.get("asset_id") or audio_spec.get("asset", {}).get("asset_id")
        path = (audio_spec.get("asset") or {}).get("path")
        if path is None and asset_id:
            path = (state.assets.get(asset_id) or {}).get("path")
        if path is None:
            self._mark_missing(state, asset_id, None, audio_id, reason="ASSET_PATH_UNKNOWN")
            return _ok({"audio_id": audio_id, "skipped": True, "reason": "MISSING_MEDIA",
                        "track_id": track_ref, "start_us": 0, "duration_us": 0,
                        "volume": 1.0, "fade_in_us": 0, "fade_out_us": 0})
        if not os.path.exists(path):
            self._mark_missing(state, asset_id, path, audio_id, reason="MISSING_MEDIA")
            return _ok({"audio_id": audio_id, "skipped": True, "reason": "MISSING_MEDIA",
                        "track_id": track_ref, "start_us": 0, "duration_us": 0,
                        "volume": 1.0, "fade_in_us": 0, "fade_out_us": 0})

        fps = state.fps
        start_us = _frames_to_us(audio_spec.get("start_frame", 0), fps)
        end_us = _frames_to_us(audio_spec.get("end_frame", 0), fps)
        target = Timerange(start_us, max(end_us - start_us, 1))
        source_in_us = _frames_to_us(audio_spec.get("source_in_frame", 0), fps)
        source_out_us = _frames_to_us(audio_spec.get("source_out_frame", 0), fps)
        source = None
        if "source_in_frame" in audio_spec or "source_out_frame" in audio_spec:
            source = Timerange(source_in_us, max(source_out_us - source_in_us, 1))

        try:
            material = self._audio_material(state, path)
        except (ValueError, TypeError) as exc:
            return _err("AUDIO_MATERIAL_FAILED", "构造音频素材失败: %s" % exc)

        volume = float(audio_spec.get("volume", 1.0))
        segment = AudioSegment(material, target, source_timerange=source, volume=volume)

        fade_in = int(audio_spec.get("fade_in_us", 0) or 0)
        fade_out = int(audio_spec.get("fade_out_us", 0) or 0)
        if fade_in > 0 or fade_out > 0:
            segment.add_fade(fade_in, fade_out)

        # ducking（§66-67）：音量关键帧；时间统一 int 微秒
        ducking = audio_spec.get("ducking_plan") or []
        applied_duck = 0
        for item in ducking:
            if not isinstance(item, dict):
                continue
            t_us = item.get("time_us")
            if t_us is None and "frame" in item:
                t_us = _frames_to_us(item["frame"], fps)
            t_us = int(round(float(t_us))) if t_us is not None else 0
            try:
                segment.add_keyframe(t_us, float(item.get("volume", 1.0)))
                applied_duck += 1
            except (TypeError, ValueError) as exc:
                self._record(state, "volume_keyframe", "ducking@%s" % t_us,
                             "partial", "关键帧添加失败: %s；跳过该点" % exc)

        try:
            state.sf.add_segment(segment, seg_track)
        except (TypeError, SegmentOverlap) as exc:
            return _err("AUDIO_ADD_FAILED", "添加音频片段失败: %s" % exc)

        self._remember_clip(state, audio_id, segment, track_ref, start_us, end_us - start_us,
                            source_in_us, source_out_us, asset_id, path,
                            start_frame=audio_spec.get("start_frame"))
        return _ok({
            "audio_id": audio_id,
            "track_id": track_ref,
            "start_us": start_us,
            "duration_us": max(end_us - start_us, 1),
            "volume": volume,
            "fade_in_us": fade_in,
            "fade_out_us": fade_out,
            "ducking_keyframes": applied_duck,
        })

    # -------------------------------------------------------- add_keyframes
    def add_keyframes(self, project_id: str, clip_id: str,
                      keyframes_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加关键帧（§45-51）。

        **FR-003 桥接（rv-P7-1b known_risk D）**：入口做形状识别——
        - 输入为 motion-spec 形状（含 type/from/to/easing/sampling，normalize_motion_spec
          输出）→ 先调 ``adapters.pyjianyingdraft.keyframes.build_keyframes`` 转换
          （采样计划由 P7-4 ``motion.plan_sampling`` 生成，不可加载时退化为 2 端点），
          再落 JY segment；
        - 输入已是 timeline-clip keyframes 形状（``{"keyframes":[{property,frame,
          value,easing?}], "fps": ...}``，§45）→ 直落本方法内置最小实现。

        两种路径共用能力检查：bezier_easing/custom_motion_path 不支持（P7-1 矩阵
        false）→ 采样离散关键帧（§47-48，sampled=True）并记录 fallback；
        AudioSegment.add_keyframe 仅 int 微秒；OPACITY 仅 VisualSegment 有效。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        segment = state.segments.get(clip_id)
        if segment is None:
            return _err("CLIP_NOT_FOUND", "clip %s 不存在" % clip_id)

        # FR-003：motion-spec 形状 → 桥接 build_keyframes（两条路径都有自测）
        if _is_motion_spec_shape(keyframes_spec):
            return self._add_keyframes_via_build_keyframes(
                state, clip_id, segment, keyframes_spec, state.clip_info.get(clip_id, {}))

        clip_info = state.clip_info.get(clip_id, {})
        # clip 本地时间基准：以 start_us（微秒）换算帧，避免依赖未落盘的 frame 字段
        clip_start_us = clip_info.get("start_us", 0)
        fps = state.fps
        keyframes = keyframes_spec.get("keyframes") or []
        applied: List[Dict[str, Any]] = []
        total = 0
        budget_warned = False
        is_audio = isinstance(segment, AudioSegment)

        for kf in keyframes:
            if not isinstance(kf, dict):
                continue
            prop = kf.get("property")
            frame = kf.get("frame")
            value = kf.get("value")
            if prop is None or frame is None or value is None:
                continue
            frame_us = _frames_to_us(frame, fps)
            offset_us = max(int(round(frame_us - clip_start_us)), 0)
            jy_name = _PROPERTY_TO_JY.get(prop)

            # 能力检查：AudioSegment 只支持 VOLUME；OPACITY 仅 VisualSegment（keyframe.py:54）
            if is_audio and prop != "VOLUME":
                self._record(state, prop.lower() + "_keyframe",
                             "clip=%s property=%s" % (clip_id, prop),
                             "unsupported",
                             "AudioSegment 仅支持 volume 关键帧（audio_segment.py:189）；跳过该属性，语义保存在 Manifest")
                continue
            if prop == "OPACITY" and is_audio:
                continue
            if jy_name is None:
                self._record(state, "keyframe", "clip=%s property=%s" % (clip_id, prop),
                             "unsupported", "未知属性 %s；跳过该关键帧" % prop)
                continue

            # easing 能力检查（§47-48）：bezier/spring/custom → 采样
            easing = kf.get("easing") or {}
            easing_type = easing.get("type")
            if easing_type in ("cubic_bezier", "spring", "custom"):
                self._record(state, "bezier_easing",
                             "clip=%s property=%s easing=%s" % (clip_id, prop, easing_type),
                             "unsupported",
                             "JY 关键帧仅 Line 插值（keyframe.py:23-34 curveType='Line'）；"
                             "采样为离散关键帧（§47-48；%d 点）" % _BEZIER_SAMPLE_POINTS)

            if easing_type in ("cubic_bezier",) and easing.get("values"):
                pts = self._sample_bezier(
                    easing["values"], offset_us, float(value), _BEZIER_SAMPLE_POINTS)
                for t_off, v in pts:
                    self._apply_one_keyframe(segment, jy_name, t_off, v, is_audio)
                    total += 1
                applied.append({"property": jy_name, "motion_property": prop, "sampled": True,
                                "sample_count": len(pts), "easing": easing_type})
            elif easing_type in ("spring", "custom"):
                # spring/custom 无统一解析 → 端点离散关键帧（有限采样，§47）
                self._apply_one_keyframe(segment, jy_name, offset_us, float(value), is_audio)
                total += 1
                applied.append({"property": jy_name, "motion_property": prop, "sampled": True,
                                "sample_count": 1, "easing": easing_type})
            else:  # linear / ease / 未标注
                self._apply_one_keyframe(segment, jy_name, offset_us, float(value), is_audio)
                total += 1
                applied.append({"property": jy_name, "motion_property": prop, "sampled": False,
                                "sample_count": 1, "easing": easing_type or "linear"})

            if total > KEYFRAME_BUDGET_PER_CLIP and not budget_warned:
                budget_warned = True
                state.warnings.append(
                    "KEYFRAME_BUDGET: clip %s 关键帧数 %d 超预算 %d（§49）→ 建议 REMOTION 烘焙（§50）"
                    % (clip_id, total, KEYFRAME_BUDGET_PER_CLIP))
                self._record(state, "keyframe_budget", "clip=%s count=%d" % (clip_id, total),
                             "warn",
                             "超过单 clip 关键帧预算 %d；TIMELINE_OPTIMIZATION_PROPOSAL: REMOTION（§50-51）"
                             % KEYFRAME_BUDGET_PER_CLIP)

        return _ok({"clip_id": clip_id, "applied": applied, "keyframe_budget": total})

    def _add_keyframes_via_build_keyframes(self, state: _ProjectState, clip_id: str,
                                           segment: Any, spec: Dict[str, Any],
                                           clip_info: Dict[str, Any]) -> Dict[str, Any]:
        """FR-003 桥：motion-spec → ``adapters.pyjianyingdraft.keyframes.build_keyframes``。

        流程：motion.plan_sampling（P7-4 判定表，不可加载时 samples=None → build_keyframes
        退化为 2 端点）→ build_keyframes 转换（capability=TIMELINE_BACKEND_CAPABILITIES）→
        逐关键帧下发 JY segment（``_apply_one_keyframe``，AudioSegment 仅 int 微秒）。

        ``base_frame`` 传 clip 本地起始帧（clip_info.start_frame），使 build_keyframes
        的 ``time_offset_us`` 相对片段起点（keyframe.py:6-8 语义）。
        """
        fps = state.fps
        clip_start_us = clip_info.get("start_us", 0)
        start_frame = int(spec.get("start_frame") or 0)
        end_frame = int(spec.get("end_frame") or start_frame)
        clip_start_frame = clip_info.get("start_frame")
        if clip_start_frame is None:
            clip_start_frame = int(round(clip_start_us * fps / 1_000_000))
        clip_start_frame = int(clip_start_frame)

        caps = TIMELINE_BACKEND_CAPABILITIES
        samples: Any = None
        try:
            motion_mod = _load_motion_module()
            if motion_mod is not None:
                samples = motion_mod.plan_sampling(
                    spec, max(0, end_frame - start_frame), caps)
        except Exception:  # noqa: BLE001 — 采样规划失败退化为 2 端点
            samples = None

        try:
            built = _load_keyframes_module().build_keyframes(
                spec, samples, caps, fps=fps, base_frame=clip_start_frame)
        except Exception as exc:  # noqa: BLE001
            return _err("KEYFRAMES_BUILD_FAILED", "build_keyframes 转换失败: %s" % exc)

        is_audio = isinstance(segment, AudioSegment)
        applied: List[Dict[str, Any]] = []
        total = 0
        budget_warned = False
        for entry in built.get("applied") or []:
            if not isinstance(entry, dict):
                continue
            mprop = str(entry.get("motion_property") or "")
            if is_audio and mprop != "VOLUME":
                self._record(state, (mprop or "keyframe").lower() + "_keyframe",
                             "clip=%s property=%s" % (clip_id, mprop),
                             "unsupported",
                             "AudioSegment 仅支持 volume 关键帧（audio_segment.py:189）；"
                             "跳过该属性，语义保存在 Manifest")
                continue
            if entry.get("supported") is not True:
                self._record(state, (mprop or "keyframe").lower() + "_keyframe",
                             "clip=%s property=%s" % (clip_id, mprop),
                             "unsupported",
                             "能力缺失：%s" % (entry.get("fallback") or "unsupported property"))
                continue
            jy_name = str(entry.get("property") or "")
            if jy_name not in _PROPERTY_TO_JY.values():
                self._record(state, "keyframe", "clip=%s property=%s" % (clip_id, mprop),
                             "unsupported", "未知 JY 属性 %s；跳过该关键帧" % jy_name)
                continue
            kf_count = 0
            for kf in entry.get("keyframes") or []:
                if not isinstance(kf, dict):
                    continue
                offset_us = kf.get("time_offset_us")
                value = kf.get("value")
                if offset_us is None or value is None:
                    continue
                self._apply_one_keyframe(segment, jy_name, int(round(float(offset_us))),
                                         float(value), is_audio)
                total += 1
                kf_count += 1
            applied.append({
                "property": jy_name, "motion_property": mprop,
                "sampled": bool(entry.get("sampled")),
                "sample_count": kf_count,
                "easing": str((spec.get("easing") or {}).get("type") or ""),
            })
            if total > KEYFRAME_BUDGET_PER_CLIP and not budget_warned:
                budget_warned = True
                state.warnings.append(
                    "KEYFRAME_BUDGET: clip %s 关键帧数 %d 超预算 %d（§49）→ 建议 REMOTION 烘焙（§50）"
                    % (clip_id, total, KEYFRAME_BUDGET_PER_CLIP))
                self._record(state, "keyframe_budget", "clip=%s count=%d" % (clip_id, total),
                             "warn",
                             "超过单 clip 关键帧预算 %d；TIMELINE_OPTIMIZATION_PROPOSAL: REMOTION（§50-51）"
                             % KEYFRAME_BUDGET_PER_CLIP)

        for w in built.get("warnings") or []:
            if "bezier_easing" in str(w):
                self._record(state, "bezier_easing",
                             "clip=%s motion-spec type=%s" % (clip_id, str(spec.get("type") or "")),
                             "unsupported", str(w))
            else:
                state.warnings.append(str(w))

        return _ok({"clip_id": clip_id, "applied": applied, "keyframe_budget": total})

    def _apply_one_keyframe(self, segment: Any, jy_name: str, offset_us: int,
                            value: float, is_audio: bool) -> None:
        """下发单个关键帧；AudioSegment 只收 int 微秒偏移。"""
        prop = KeyframeProperty[jy_name]
        if is_audio:
            segment.add_keyframe(int(round(offset_us)), float(value))
        else:
            segment.add_keyframe(prop, int(round(offset_us)), float(value))

    def _sample_bezier(self, values: List[float], end_offset_us: int, end_value: float,
                       n: int) -> List[Tuple[int, float]]:
        """cubic_bezier(values=[x1,y1,x2,y2]) 从 0→end 采样 n 个中间离散关键帧（§47-48）。"""
        x1, y1, x2, y2 = (float(v) for v in (values + [0.0, 0.0, 1.0, 1.0])[:4])
        pts: List[Tuple[int, float]] = []
        for i in range(1, n + 1):
            t = i / (n + 1.0)
            # 用 x 曲线做时间重映射，y 曲线做值插值（标准 CSS cubic-bezier 语义）
            mt = 1.0 - t
            bez_x = 3 * mt * mt * t * x1 + 3 * mt * t * t * x2 + t * t * t
            bez_y = 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t * t * t
            pts.append((int(round(bez_x * end_offset_us)), bez_y * end_value))
        return pts

    # -------------------------------------------------------- add_transition
    def add_transition(self, project_id: str, clip_id: str,
                       transition_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加转场（§72-74）。转场应加在**前一个**片段上（由调用方传 clip_id）。

        CUT → 不产生 JY 转场对象（§74 合法默认）；DISSOLVE→叠化 / SLIDE→滑动 / FADE→闪白。
        枚举面为 TransitionType 453 项（transition_meta.py），复杂转场→Remotion 烘焙（§72）。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        segment = state.segments.get(clip_id)
        if segment is None:
            return _err("CLIP_NOT_FOUND", "clip %s 不存在" % clip_id)
        if not isinstance(segment, VideoSegment):
            return _err("TRANSITION_ON_NON_VIDEO", "转场只支持 VideoSegment（clip %s）" % clip_id,
                        "文本/音频片段不支持转场；CUT 语义由 Manifest 保证")

        ttype = transition_spec.get("transition_type") or transition_spec.get("type")
        if ttype not in _TRANSITION_MAP:
            self._record(state, "transition", "transition_type=%r" % ttype,
                         "unsupported",
                         "不在 transition_basic 四枚举内（§72）；复杂转场 → Remotion 烘焙（§72），Manifest 保留语义")
            return _err("TRANSITION_TYPE_UNSUPPORTED", "transition_type=%r 不支持" % ttype,
                        "复杂转场 → Remotion 烘焙（§72）")

        jy_name = _TRANSITION_MAP[ttype]
        if jy_name is None:  # CUT
            return _ok({"clip_id": clip_id, "transition_id": None,
                        "transition_type": "CUT", "duration_us": 0, "is_overlap": False})

        duration_us = transition_spec.get("duration_us")
        if duration_us is not None:
            duration_us = int(round(float(duration_us)))
        try:
            trans = TransitionType.from_name(jy_name)
        except ValueError as exc:
            return _err("TRANSITION_NOT_FOUND", str(exc))
        try:
            segment.add_transition(trans, duration=duration_us)
        except ValueError as exc:
            return _err("TRANSITION_ADD_FAILED", str(exc))
        return _ok({
            "clip_id": clip_id,
            "transition_id": segment.transition.global_id,
            "transition_type": ttype,
            "duration_us": segment.transition.duration,
            "is_overlap": segment.transition.is_overlap,
        })

    # --------------------------------------------------------- replace_asset
    def replace_asset(self, project_id: str, clip_id: str, asset_slot_id: str,
                      new_asset: Dict[str, Any]) -> Dict[str, Any]:
        """Asset Slot 替换（§33-36/§99-108：replace_asset 优先于重建；保留 timing/track/transform/keyframes）。

        新素材时长/分辨率/宽高比/alpha 显著变化 → ``ASSET_REPLACEMENT_CONFLICT``，不静默替换（§36/Test 11）。
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        segment = state.segments.get(clip_id)
        if segment is None:
            return _err("CLIP_NOT_FOUND", "clip %s 不存在" % clip_id)
        if not isinstance(segment, (VideoSegment, AudioSegment)):
            return _err("REPLACE_ON_UNSUPPORTED_SEGMENT", "clip %s 不是媒体片段" % clip_id)

        new_path = new_asset.get("path")
        if not new_path or not os.path.exists(new_path):
            return _err("ASSET_REPLACEMENT_CONFLICT",
                        "新素材文件不存在: %s" % new_path,
                        "保留原素材；确认新素材路径后重试")

        # 构造新素材并做 §36 安全比较
        try:
            if isinstance(segment, AudioSegment):
                new_mat = self._audio_material(state, new_path)
            else:
                new_mat = VideoMaterial(new_path)
        except (ValueError, TypeError) as exc:
            return _err("ASSET_REPLACEMENT_CONFLICT", "新素材解析失败: %s" % exc, "保留原素材")

        old_mat = segment.material_instance
        conflict_reasons: List[str] = []

        # 时长剧变（§36）
        if isinstance(segment, VideoSegment) and segment.source_timerange is not None:
            need_end = segment.source_timerange.end
            if new_mat.duration < need_end:
                conflict_reasons.append("新素材时长(%dus) < 所需源时长(%dus)" % (new_mat.duration, need_end))
        old_dur = getattr(old_mat, "duration", 0) or 1
        if old_dur > 0:
            ratio = abs(new_mat.duration - old_dur) / old_dur
            if ratio > _CONFLICT_DURATION_RATIO:
                conflict_reasons.append("时长变化 %d%% > 阈值 %d%%" % (ratio * 100, _CONFLICT_DURATION_RATIO * 100))

        # 分辨率/宽高比剧变（§36）
        if isinstance(new_mat, VideoMaterial) and isinstance(old_mat, VideoMaterial):
            old_ar = old_mat.width / max(old_mat.height, 1)
            new_ar = new_mat.width / max(new_mat.height, 1)
            if abs(new_ar - old_ar) / max(old_ar, 1e-6) > _CONFLICT_ASPECT_RATIO:
                conflict_reasons.append("宽高比变化超过 %d%%" % (_CONFLICT_ASPECT_RATIO * 100))
            # photo ↔ video 类型切换视为显著变化
            if new_mat.material_type != old_mat.material_type:
                conflict_reasons.append("素材类型 %s → %s" % (old_mat.material_type, new_mat.material_type))

        if conflict_reasons:
            self._record(state, "replace_asset", "clip=%s slot=%s" % (clip_id, asset_slot_id),
                         "conflict",
                         "; ".join(conflict_reasons) + "；保留原素材，人工审核后手动替换（§36 不静默替换）")
            state.conflicts.append({"clip_id": clip_id, "reason": "ASSET_REPLACEMENT_CONFLICT",
                                    "message": "; ".join(conflict_reasons)})
            return {"ok": False, "error": "ASSET_REPLACEMENT_CONFLICT",
                    "message": "新素材与 clip %s 不兼容: %s" % (clip_id, "; ".join(conflict_reasons)),
                    "fallback": "保留原素材；人工审核后手动替换（§36 不静默替换）"}

        # 通过安全检查 → 替换（保留 timing/track/transform/keyframes：不改 segment 其它字段）
        if isinstance(segment, VideoSegment):
            segment.material_instance = new_mat
            segment.material_id = new_mat.material_id
            segment.material_size = (new_mat.width, new_mat.height)
            # 同步 materials 列表
            for i, m in enumerate(state.sf.materials.videos):
                if m.material_id == old_mat.material_id:
                    state.sf.materials.videos[i] = new_mat
                    break
        else:
            segment.material_instance = new_mat
            segment.material_id = new_mat.material_id
            for i, m in enumerate(state.sf.materials.audios):
                if m.material_id == old_mat.material_id:
                    state.sf.materials.audios[i] = new_mat
                    break
        clip_info = state.clip_info.setdefault(clip_id, {})
        clip_info["asset_id"] = new_asset.get("asset_id") or clip_info.get("asset_id")
        clip_info["resolved_path"] = new_path
        state.material_registry.pop(new_asset.get("asset_id"), None)

        return _ok({"clip_id": clip_id, "asset_slot_id": asset_slot_id,
                    "new_material_id": new_mat.material_id,
                    "preserved": {"timing": True, "track": True, "transform": True, "keyframes": True}})

    # ---------------------------------------------------------- export_draft
    def export_draft(self, project_id: str, output_dir: Optional[str] = None,
                     options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """生成真实 Draft 文件（§89-92/§96/§135-137）。

        目录（§135）：``<output_dir>/timeline/backend/draft_v{n}/draft_content.json``；
        同时写 ``timeline/manifest/manifest_v{n}.json`` 基线快照（§138）与
        ``timeline/reports/BACKEND_FALLBACK_REPORT.md``（§92）。

        素材路径统一改写为 **project-relative**（§117），resolved 绝对路径记录在
        backend_metadata / fallback 报告。每次 export 版本递增，不覆盖（§136-137）。

        §96：只生成 Draft，"Draft generated. Human opens JianYing for inspection/export."
        """
        state = self._projects.get(project_id)
        if state is None or state.sf is None:
            return _err("PROJECT_NOT_FOUND", "project %s 不存在" % project_id)
        output_dir = output_dir or state.out_dir or self._default_out_dir
        if not output_dir:
            return _err("NO_OUTPUT_DIR", "缺少输出目录（create_project 或 export_draft 需提供）")
        options = options or {}

        state.draft_export_count += 1
        version = state.draft_export_count
        backend_dir = os.path.join(output_dir, "timeline", "backend")
        os.makedirs(backend_dir, exist_ok=True)

        # 版本递增不覆盖（§136-137）：显式 options.draft_name（文件夹名）存在则报错；
        # 否则 draft_v{n} 递增。create_project 的 draft_name 是**显示名**（R3-P7，
        # 写入 draft_meta_info.json 的 draft_name 字段），与文件夹名解耦，不改变目录约定（§135）。
        folder_name = options.get("draft_name")
        if folder_name:
            target = os.path.join(backend_dir, folder_name)
            if os.path.exists(target):
                return _err("DRAFT_NAME_EXISTS", "草稿 %s 已存在（§137 不覆盖）" % folder_name,
                            "换 draft_name 或让版本自动递增 draft_v{n}")
        else:
            folder_name = "draft_v%d" % version

        folder = DraftFolder(backend_dir)
        sf = folder.create_draft(folder_name, state.width, state.height, int(state.fps))
        # 转移构建期状态
        sf.materials = state.sf.materials
        sf.tracks = state.sf.tracks
        sf.duration = state.sf.duration
        sf.imported_materials = state.sf.imported_materials
        sf.imported_tracks = state.sf.imported_tracks
        sf.content["config"]["maintrack_adsorb"] = state.sf.maintrack_adsorb

        # §117 相对路径改写 + resolved 记录
        resolved_paths: Dict[str, str] = {}
        for mat in sf.materials.videos:
            if mat.path:
                abs_p = os.path.abspath(mat.path)
                resolved_paths.setdefault(mat.material_id, abs_p)
                mat.path = os.path.relpath(abs_p, output_dir)
        for mat in sf.materials.audios:
            if mat.path:
                abs_p = os.path.abspath(mat.path)
                resolved_paths.setdefault(mat.material_id, abs_p)
                mat.path = os.path.relpath(abs_p, output_dir)

        sf.save()
        draft_path = sf.save_path

        # R3-P7：把 create_project 生成的唯一 draft_id（uuid4）与 draft_name（显示名）写入
        # draft_meta_info.json。pyJianYingDraft 模板默认 draft_id=BC69C7CD-… 且 draft_name
        # 为空，若不覆盖会导致剪映项目列表按 draft_id/文件夹识别草稿时多草稿混淆（本修复目标）。
        draft_meta_path = os.path.join(os.path.dirname(draft_path), "draft_meta_info.json")
        self._write_draft_meta_info(draft_meta_path, state.draft_id, state.draft_display_name)

        # §138 基线 manifest 快照
        manifest_dir = os.path.join(output_dir, "timeline", "manifest")
        os.makedirs(manifest_dir, exist_ok=True)
        manifest_path = os.path.join(manifest_dir, "manifest_v%d.json" % version)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(state.manifest, f, ensure_ascii=False, indent=2)

        # §92 fallback 报告
        report_path = self._write_fallback_report(state, output_dir, version)

        generated_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        unsupported = [{"feature": u.get("feature", ""), "fallback": u.get("fallback", "")}
                       for u in state.unsupported]
        fallbacks = sorted({u.get("fallback", "") for u in state.unsupported})
        warnings = list(state.warnings)
        warnings.append("Draft generated. Human opens JianYing for inspection/export. (macOS 无自动导出，§96)")

        return _ok({
            "backend": self.backend,
            "backend_version": self.backend_version,
            "draft_path": draft_path,
            "generated_at": generated_at,
            "manifest_version": str(state.manifest.get("version", version)),
            "warnings": warnings,
            "unsupported_features": unsupported,
            "fallbacks": fallbacks,
            "compatibility_report": self._compatibility_report,
            "backend_metadata": {
                "draft_version": version,
                "draft_id": state.draft_id,                        # R3-P7：唯一 uuid4
                "draft_name": state.draft_display_name,            # R3-P7：显示名
                "draft_folder": folder_name,
                "relative_path_base": output_dir,
                "resolved_paths": resolved_paths,
                "fallback_report_path": report_path,
                "manifest_snapshot_path": manifest_path,
                "missing_media": state.missing_media,
                "conflicts": state.conflicts,
            },
        })

    # --------------------------------------------------------- validate_draft
    def validate_draft(self, project_id: str, draft_path: str) -> Dict[str, Any]:
        """回读校验已生成草稿（§109-115 基础项）：文件存在/JSON 可解析/关键段存在/无负时长。"""
        issues: List[Dict[str, Any]] = []
        if not os.path.exists(draft_path):
            return _ok({"valid": False, "issues": [
                {"level": "ERROR", "code": "DRAFT_NOT_FOUND",
                 "message": "草稿文件不存在: %s" % draft_path, "clip_id": None}]})
        try:
            with open(draft_path, "r", encoding="utf-8") as f:
                content = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            return _ok({"valid": False, "issues": [
                {"level": "ERROR", "code": "DRAFT_JSON_INVALID",
                 "message": "draft_content.json 解析失败: %s" % exc, "clip_id": None}]})

        if not isinstance(content, dict):
            return _ok({"valid": False, "issues": [
                {"level": "ERROR", "code": "DRAFT_NOT_OBJECT",
                 "message": "draft_content 顶层不是对象", "clip_id": None}]})

        tracks = content.get("tracks")
        materials = content.get("materials")
        if not isinstance(tracks, list) or len(tracks) == 0:
            issues.append({"level": "ERROR", "code": "DRAFT_NO_TRACKS",
                           "message": "草稿无 tracks", "clip_id": None})
        if not isinstance(materials, dict):
            issues.append({"level": "ERROR", "code": "DRAFT_NO_MATERIALS",
                           "message": "草稿无 materials", "clip_id": None})

        # 片段负时长检查
        for tr in tracks or []:
            for seg in tr.get("segments") or []:
                trange_ = seg.get("target_timerange") or {}
                if trange_.get("duration", 0) < 0 or trange_.get("start", 0) < 0:
                    issues.append({"level": "ERROR", "code": "NEGATIVE_TIMERANGE",
                                   "message": "track %s 片段负时长: %s" % (tr.get("name"), trange_),
                                   "clip_id": None})
        # 素材 path 非空
        for bucket in ("videos", "audios", "texts"):
            for mat in (materials or {}).get(bucket) or []:
                if bucket in ("videos", "audios") and not mat.get("path"):
                    issues.append({"level": "WARNING", "code": "MATERIAL_EMPTY_PATH",
                                   "message": "%s 素材 %s 缺 path" % (bucket, mat.get("id")), "clip_id": None})

        valid = not any(i["level"] == "ERROR" for i in issues)
        return _ok({"valid": valid, "issues": issues,
                    "summary": {"tracks": len(tracks or []), "materials": list((materials or {}).keys())}})

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _record(self, state: _ProjectState, feature: str, requested: str,
                backend: str, fallback: str) -> None:
        """记录一条 unsupported/fallback 条目（§92，不静默丢）。"""
        state.unsupported.append({
            "feature": feature, "requested": requested,
            "backend": backend, "fallback": fallback,
        })

    def _mark_missing(self, state: _ProjectState, asset_id: Optional[str], path: Optional[str],
                      clip_id: Optional[str], reason: str) -> None:
        state.missing_media.append({
            "asset_id": asset_id or "", "path": path or "", "clip_id": clip_id or "", "reason": reason,
        })
        state.warnings.append("MISSING_MEDIA: clip=%s asset=%s path=%s（§118 已跳过）" % (clip_id, asset_id, path))

    @staticmethod
    def _asset_path_from(assets: Dict[str, Dict[str, Any]], clip: Dict[str, Any]) -> Optional[str]:
        """从 manifest 资产表 + clip_spec 解析资产路径。"""
        spec_asset = clip.get("asset")
        if isinstance(spec_asset, dict) and spec_asset.get("path"):
            return spec_asset["path"]
        asset_id = clip.get("asset_id")
        info = assets.get(asset_id) or {}
        return info.get("path")

    def _resolve_asset_path(self, state: _ProjectState, asset_id: str,
                            clip_spec: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """解析 clip 的资产路径与类型；返回 (abs_path|None, kind|None)。"""
        spec_asset = clip_spec.get("asset") or {}
        path = spec_asset.get("path")
        kind = spec_asset.get("kind")
        info = state.assets.get(asset_id) or {}
        if path is None:
            path = info.get("path")
        if kind is None:
            kind = info.get("kind")
        if not path:
            return None, kind
        if not os.path.isabs(path):
            candidates = []
            if state.asset_root:
                candidates.append(os.path.join(state.asset_root, path))
            if state.out_dir:
                candidates.append(os.path.join(state.out_dir, path))
            candidates.append(os.path.join(os.getcwd(), path))
            for c in candidates:
                if os.path.exists(c):
                    path = c
                    break
            else:
                path = candidates[0]
        return os.path.abspath(path), kind

    def _apply_proxy_policy(self, state: _ProjectState, clip_spec: Dict[str, Any], path: str) -> str:
        """§31-32 proxy/original 选择：USE_PROXY_FOR_EDIT 且 proxy 存在 → proxy；否则原片。"""
        proxy_usage = clip_spec.get("proxy_usage") or {}
        policy = proxy_usage.get("policy", "USE_ORIGINAL")
        if policy == "USE_PROXY_FOR_EDIT":
            proxy = proxy_usage.get("proxy")
            if proxy and os.path.exists(proxy):
                return os.path.abspath(proxy)
            state.warnings.append("PROXY: clip %s 请求 proxy 但 proxy 不可用，回退原片" % clip_spec.get("clip_id"))
        return path

    def _material_for(self, state: _ProjectState, asset_id: str, path: str, kind: Optional[str],
                      crop: Any) -> Tuple[Any, str]:
        """按 asset_id 复用或新建 JY 素材；带 crop 时按 clip 单独构造（裁剪在素材层）。"""
        cached = state.material_registry.get(asset_id)
        if cached is not None and not crop:
            return cached[0], cached[1]
        if kind == "audio" or (kind is None and os.path.splitext(path)[1].lower() in _AUDIO_EXTS):
            mat: Any = self._audio_material(state, path)
        else:
            crop_settings = CropSettings()
            if isinstance(crop, dict):
                crop_settings = self._build_crop_settings(crop)
            mat = VideoMaterial(path, crop_settings=crop_settings)
        if not crop:
            state.material_registry[asset_id] = (mat, path)
        return mat, path

    def _audio_material(self, state: _ProjectState, path: str) -> AudioMaterial:
        cached = state.material_registry.get(path)
        if isinstance(cached, tuple) and isinstance(cached[0], AudioMaterial):
            return cached[0]
        mat = AudioMaterial(path)
        return mat

    @staticmethod
    def _build_crop_settings(crop: Dict[str, Any]) -> CropSettings:
        """crop dict → CropSettings（0-1 归一化；可传 8 角键或 left/top/right/bottom）。"""
        if any(k in crop for k in ("upper_left_x", "upper_right_x", "lower_left_x", "lower_right_x")):
            return CropSettings(
                upper_left_x=float(crop.get("upper_left_x", 0.0)),
                upper_left_y=float(crop.get("upper_left_y", 0.0)),
                upper_right_x=float(crop.get("upper_right_x", 1.0)),
                upper_right_y=float(crop.get("upper_right_y", 0.0)),
                lower_left_x=float(crop.get("lower_left_x", 0.0)),
                lower_left_y=float(crop.get("lower_left_y", 1.0)),
                lower_right_x=float(crop.get("lower_right_x", 1.0)),
                lower_right_y=float(crop.get("lower_right_y", 1.0)),
            )
        left = float(crop.get("left", 0.0)); top = float(crop.get("top", 0.0))
        right = float(crop.get("right", 1.0)); bottom = float(crop.get("bottom", 1.0))
        return CropSettings(upper_left_x=left, upper_left_y=top,
                            upper_right_x=right, upper_right_y=top,
                            lower_left_x=left, lower_left_y=bottom,
                            lower_right_x=right, lower_right_y=bottom)

    def _build_clip_settings(self, state: _ProjectState, clip_spec: Dict[str, Any]) -> ClipSettings:
        """manifest clip 的 position/scale/rotation/opacity/blend/mask → JY ClipSettings。

        position 为归一化 0-1 → transform 单位为半画布（(v-0.5)*2）。blend/mask 另用
        add_segment 后的 segment 方法处理（此处返回基础 transform，扩展在 add_clip 后补）。
        """
        pos = clip_spec.get("position") or {}
        scale = clip_spec.get("scale") or {}
        transform_x = float((pos.get("x", 0.5) - 0.5) * 2)
        transform_y = float((pos.get("y", 0.5) - 0.5) * 2)
        cs = ClipSettings(
            alpha=float(clip_spec.get("opacity", 1.0)),
            rotation=float(clip_spec.get("rotation", 0.0)),
            scale_x=float(scale.get("x", 1.0)),
            scale_y=float(scale.get("y", 1.0)),
            transform_x=transform_x,
            transform_y=transform_y,
        )
        return cs

    def _apply_clip_extras(self, state: _ProjectState, segment: VideoSegment,
                           clip_id: str, clip_spec: Dict[str, Any]) -> None:
        """blend_mode / mask 应用（在 add_clip 的 segment 上，需在 add_segment 前调用）。"""
        # blend_mode（§13）
        blend = clip_spec.get("blend_mode")
        if blend and blend != "normal":
            jy_name = _BLEND_MODE_MAP.get(str(blend).lower())
            if jy_name:
                try:
                    segment.set_mix_mode(MixModeType.from_name(jy_name))
                except ValueError:
                    self._record(state, "blend_mode", "clip=%s blend=%s" % (clip_id, blend),
                                 "unsupported", "JY 无该混合模式；跳过（Manifest 保留语义）")
            else:
                self._record(state, "blend_mode", "clip=%s blend=%s" % (clip_id, blend),
                             "unsupported", "未知混合模式名；跳过（Manifest 保留语义）")
        # mask（§12）
        mask = clip_spec.get("mask")
        if isinstance(mask, dict) and mask.get("type"):
            jy_name = _MASK_TYPE_MAP.get(str(mask["type"]).lower())
            if jy_name:
                try:
                    segment.add_mask(
                        MaskType.from_name(jy_name),
                        center_x=float(mask.get("cx", mask.get("center_x", 0.0))),
                        center_y=float(mask.get("cy", mask.get("center_y", 0.0))),
                        size=float(mask.get("size", 0.5)),
                        rotation=float(mask.get("rotation", 0.0)),
                        feather=float(mask.get("feather", 0.0)),
                        invert=bool(mask.get("invert", False)),
                        rect_width=mask.get("rect_width"),
                        round_corner=mask.get("round_corner"),
                    )
                except ValueError as exc:
                    self._record(state, "mask", "clip=%s mask=%s" % (clip_id, mask.get("type")),
                                 "unsupported", "蒙版应用失败: %s；跳过蒙版（Manifest 保留语义）" % exc)
            else:
                self._record(state, "mask", "clip=%s mask=%s" % (clip_id, mask.get("type")),
                             "unsupported", "未知蒙版类型；跳过蒙版（Manifest 保留语义）")

    @staticmethod
    def _build_text_style(style: Dict[str, Any], auto_wrapping: bool) -> TextStyle:
        """VISUAL_BIBLE 样式字段 → TextStyle。color 支持 0-255（自动归一化到 0-1）。"""
        color = style.get("color", (1.0, 1.0, 1.0))
        if isinstance(color, (list, tuple)) and len(color) == 3:
            if max(color) > 1.0:
                color = tuple(c / 255.0 for c in color)
            else:
                color = tuple(float(c) for c in color)
        return TextStyle(
            size=float(style.get("size", 8.0)),
            bold=bool(style.get("bold", False)),
            italic=bool(style.get("italic", False)),
            underline=bool(style.get("underline", False)),
            color=color,  # type: ignore[arg-type]
            alpha=float(style.get("alpha", 1.0)),
            align=int(style.get("align", 1)),
            vertical=bool(style.get("vertical", False)),
            letter_spacing=int(style.get("letter_spacing", 0)),
            line_spacing=int(style.get("line_spacing", 0)),
            auto_wrapping=auto_wrapping,
            max_line_width=float(style.get("max_line_width", 0.82)),
        )

    @staticmethod
    def _text_position_settings(spec: Dict[str, Any], default_y: float) -> ClipSettings:
        """文本/字幕位置：归一化 0-1 → transform（半画布单位）。字幕默认底部 y=0.1。"""
        pos = spec.get("position") or {}
        x = float(pos.get("x", 0.5))
        y = float(pos.get("y", default_y))
        return ClipSettings(transform_x=(x - 0.5) * 2, transform_y=(y - 0.5) * 2)

    def _resolve_jy_track(self, state: _ProjectState, track_ref: str) -> Any:
        """track_ref 可以是 JY track 名（add_track 返回的 track_ref）或逻辑 TR-### id。"""
        if track_ref in state.sf.tracks:
            return track_ref
        jy_name = state.track_names.get(track_ref)
        if jy_name and jy_name in state.sf.tracks:
            return jy_name
        return None

    def _remember_clip(self, state: _ProjectState, clip_id: Optional[str], segment: Any,
                       track_ref: str, start_us: int, duration_us: int,
                       source_in_us: int, source_out_us: int,
                       asset_id: Optional[str], path: Optional[str],
                       start_frame: Optional[int] = None) -> None:
        if not clip_id:
            return
        state.segments[clip_id] = segment
        state.clip_info[clip_id] = {
            "start_us": start_us, "duration_us": duration_us,
            "source_in_us": source_in_us, "source_out_us": source_out_us,
            "asset_id": asset_id, "resolved_path": path, "track_ref": track_ref,
            "start_frame": start_frame,  # FR-003 桥：motion-spec 关键帧偏移基准帧
        }

    def _write_draft_meta_info(self, meta_path: str, draft_id: str, draft_name: str) -> None:
        """R3-P7：把唯一 draft_id 与 draft_name（显示名）写入 draft_meta_info.json。

        pyJianYingDraft ``create_draft`` 拷贝的模板带默认 ``draft_id=BC69C7CD-…`` 且
        ``draft_name`` 为空；剪映项目列表按 draft_id/文件夹识别草稿，重复 ID 会混淆两个项目。
        本方法覆盖这两个字段：draft_id 用 create_project 生成的 uuid4（大写），draft_name
        用显示名（如 "ZHOU-A-90s-v1"）。JSON 结构完整读改写，不丢其它键。
        """
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, json.JSONDecodeError):
            return  # meta 不可读时跳过（不阻断 draft 落盘），保留模板原样
        if not isinstance(meta, dict):
            return
        meta["draft_id"] = draft_id
        meta["draft_name"] = draft_name
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent="\t")
        except OSError:
            return  # 写失败不阻断 export_draft（draft_content.json 已落盘）

    def _write_fallback_report(self, state: _ProjectState, output_dir: str, version: int) -> str:
        """§92 BACKEND_FALLBACK_REPORT.md：Requested/Backend/Fallback 三行式。"""
        report_dir = os.path.join(output_dir, "timeline", "reports")
        os.makedirs(report_dir, exist_ok=True)
        path = os.path.join(report_dir, "BACKEND_FALLBACK_REPORT.md")
        lines = [
            "# BACKEND_FALLBACK_REPORT — PyJianYingDraft 0.3.0（Phase-7 §92）",
            "",
            "> 生成时间: %s（draft_v%d）" % (time.strftime("%Y-%m-%dT%H:%M:%S%z"), version),
            "> 原则：不支持的能力**不静默丢**（§92），一律落此报告；Manifest 仍是系统真相来源（§12）。",
            "",
            "## 1. Unsupported Features（§92 三行式）",
            "",
        ]
        if not state.unsupported:
            lines.append("（无）")
        for i, u in enumerate(state.unsupported, 1):
            lines += [
                "### %d. %s" % (i, u["feature"]),
                "- Requested: %s" % u["requested"],
                "- Backend: %s" % u["backend"],
                "- Fallback: %s" % u["fallback"],
                "",
            ]
        lines += ["## 2. Missing Media（§118）", ""]
        if not state.missing_media:
            lines.append("（无）")
        for m in state.missing_media:
            lines.append("- asset=%s clip=%s path=%s（%s）" % (m["asset_id"], m["clip_id"], m["path"], m["reason"]))
        lines += ["", "## 3. Replacement Conflicts（§36）", ""]
        if not state.conflicts:
            lines.append("（无）")
        for c in state.conflicts:
            lines.append("- clip=%s: %s" % (c["clip_id"], c["message"]))
        lines += ["", "## 4. Warnings", ""]
        if not state.warnings:
            lines.append("（无）")
        for w in state.warnings:
            lines.append("- %s" % w)
        lines += [
            "",
            "## 5. 诚实声明（§96）",
            "",
            "本适配器只生成 JianYing Draft；人类打开剪映检查/导出。",
            "Draft generated. Human opens JianYing for inspection/export.",
            "macOS 无 jianying_controller（自动导出仅 Windows 且仅剪映 6 及以下）。",
        ]
        _note, _version = _editor_declaration()
        lines.append("tested_editor_version=%s。%s" % (_version, _note))
        lines.append("")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path
