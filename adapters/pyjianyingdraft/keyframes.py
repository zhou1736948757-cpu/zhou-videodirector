#!/usr/bin/env python3
"""adapters/pyjianyingdraft/keyframes.py — Motion Spec → JianYing 关键帧（Phase-7 §45-52；P7-4）.

JianYing Keyframe Adapter：Motion Spec（motion-spec.schema.json 形状）→ pyJianYingDraft
关键帧数据结构。只构造数据，**不落盘 draft、不调用 pyJianYingDraft**（P7-5 的
``PyJianYingDraftBackend.add_keyframes`` 负责真实调用；本模块输出的 JSON 可在自测里
dump 供 P7-5 复用）。

流程（§45）：Motion Spec → Backend Capability Check → Keyframe Generation。

能力矩阵依据（P7-1 BACKEND_CAPABILITY_REPORT.md / adapters/pyjianyingdraft/__init__.py）：
- position/scale/rotation/opacity/volume 关键帧 **supported=True**
  （keyframe.py:39-63；alpha 仅 VideoSegment 有效 keyframe.py:53-54）
- bezier_easing **False**（keyframe.py:23-34 硬编码 curveType='Line'、graphID=''）
  → §47-48 采样离散关键帧（Test 17 语义，AC-4）
- custom_motion_path **False**（keyframe.py:23-34 无 path 字段）→ §51 Remotion 烘焙
  或 position 关键帧采样（AC-4 fallback 标注）
- AudioSegment.add_keyframe 只收 **int 微秒**（audio_segment.py:189）→ 本模块
  时间偏移统一 ``frames_to_us`` 转 int（AC-4 关键约束）

属性映射（§42 八枚举 → JY KeyframeProperty）：
    POSITION_X→position_x(KFTypePositionX) / POSITION_Y→position_y(KFTypePositionY)
    SCALE→uniform_scale(UNIFORM_SCALE) / SCALE_X→scale_x(KFTypeScaleX)
    SCALE_Y→scale_y(KFTypeScaleY) / ROTATION→rotation(KFTypeRotation)
    OPACITY→alpha(KFTypeAlpha) / VOLUME→volume(KFTypeVolume)

技术约束：Python 3 stdlib only；确定性；本模块自带 ``frames_to_us``（不跨包 import，
timeline-manager 目录为连字符包，无法 ``import modules.timeline-manager.motion``；
P7-4 工单约束 motion.py 与 keyframes.py 各自自洽）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# §42 八枚举 → JY 属性映射
# ---------------------------------------------------------------------------
# motion_property: §42 八枚举；jy_property: KeyframeProperty 名（backend base.py
# add_keyframes contract applied[].property 的取值）；kf_type: KeyframeProperty.value；
# key: spec.from/to 的键名；capability: §43 能力矩阵键；applies_to: 片段类型语义
# （alpha 仅 VideoSegment 有效，volume 对 Audio/Video 有效 —— P7-1 keyframe.py:53-63）
PROPERTY_JY_MAP: Dict[str, Dict[str, Any]] = {
    "POSITION_X": {
        "jy_property": "position_x", "kf_type": "KFTypePositionX",
        "key": "x", "capability": "position_keyframe", "applies_to": "visual",
    },
    "POSITION_Y": {
        "jy_property": "position_y", "kf_type": "KFTypePositionY",
        "key": "y", "capability": "position_keyframe", "applies_to": "visual",
    },
    "SCALE": {
        "jy_property": "uniform_scale", "kf_type": "UNIFORM_SCALE",
        "key": "scale", "capability": "scale_keyframe", "applies_to": "visual",
    },
    "SCALE_X": {
        "jy_property": "scale_x", "kf_type": "KFTypeScaleX",
        "key": "scale_x", "capability": "scale_keyframe", "applies_to": "visual",
    },
    "SCALE_Y": {
        "jy_property": "scale_y", "kf_type": "KFTypeScaleY",
        "key": "scale_y", "capability": "scale_keyframe", "applies_to": "visual",
    },
    "ROTATION": {
        "jy_property": "rotation", "kf_type": "KFTypeRotation",
        "key": "rotation", "capability": "rotation_keyframe", "applies_to": "visual",
    },
    "OPACITY": {
        "jy_property": "alpha", "kf_type": "KFTypeAlpha",
        "key": "opacity", "capability": "opacity_keyframe",
        "applies_to": "video_only",  # P7-1: keyframe.py:53-54 alpha 仅 VideoSegment
    },
    "VOLUME": {
        "jy_property": "volume", "kf_type": "KFTypeVolume",
        "key": "volume", "capability": "volume_keyframe",
        "applies_to": "audio_or_video",  # P7-1: keyframe.py:62-63
    },
}

# 静止默认值（from/to 缺键时）
_DEFAULT_REST = {
    "x": 0.0, "y": 0.0, "scale": 1.0, "scale_x": 1.0, "scale_y": 1.0,
    "rotation": 0.0, "opacity": 1.0, "volume": 1.0,
}

_COMPLEX_EASING = {"cubic_bezier", "spring", "custom"}


def frames_to_us(frame: int, fps: int = 30) -> int:
    """帧 → 微秒（int）。

    P7-1 finding 3：``AudioSegment.add_keyframe`` 只接受 int 微秒偏移，不接受 str
    （audio_segment.py:189 直传 ``KeyframeList.add_keyframe``→``sort`` 抛 TypeError）。
    因此所有时间偏移统一在 Adapter 层先转 int（P7-1 BACKEND_CAPABILITY_REPORT §1 keyframes 行）。
    """
    return int(round(int(frame) * 1_000_000 / max(1, int(fps))))


def _capability_view(capability: Any) -> Dict[str, Any]:
    """归一化 capability：直接 dict / {"ok":True,"result":{...}} / None。"""
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


def _samples_view(sampled: Any) -> List[Dict[str, Any]]:
    """归一化采样结果：plan_sampling 输出 dict（含 samples[]）或裸 samples 列表。"""
    if isinstance(sampled, dict):
        s = sampled.get("samples")
        if isinstance(s, list):
            return [x for x in s if isinstance(x, dict) and "frame" in x]
        return []
    if isinstance(sampled, list):
        return [x for x in sampled if isinstance(x, dict) and "frame" in x]
    return []


def build_keyframes(spec: Dict[str, Any], sampled: Any, capability: Any = None,
                    fps: int = 30, base_frame: Optional[int] = None) -> Dict[str, Any]:
    """Motion Spec → JianYing 关键帧数据结构（P7-4 唯一对外入口）。

    Args:
        spec: motion-spec.schema.json 形状（``normalize_motion_spec`` 输出）。
        sampled: ``plan_sampling`` 输出 dict（含 ``samples`` [{frame, progress}]），
            或裸 samples 列表。None 时退化为起点/终点 2 点（线性）。
        capability: P7-1 能力矩阵（``adapters/pyjianyingdraft/__init__.py`` 的
            ``TIMELINE_BACKEND_CAPABILITIES``，或 ``{"ok":True,"result":{...}}``，或 None）。
        fps: 帧率（帧→微秒换算用）。
        base_frame: 关键帧偏移基准帧。JY keyframes 时间偏移相对片段起点
            （keyframe.py:6-8 "相对于素材起始点的时间偏移量"）；传 clip 的
            timeline_start_frame 使偏移片段相对；默认 spec.start_frame。

    Returns:
        dict（JSON 可序列化；格式对齐 base.py::add_keyframes 的 result 契约
        ``applied[].property`` + ``keyframes[{time_offset_us, value}]`` + ``sampled``）：:

            {"applied": [
                {"motion_property": "SCALE",      # §42 八枚举
                 "property": "uniform_scale",      # JY 属性名（base.py contract）
                 "kf_type": "UNIFORM_SCALE",       # KeyframeProperty.value
                 "applies_to": "visual",
                 "keyframes": [{"frame": int, "time_offset_us": int, "value": float}],
                 "sampled": bool, "sample_count": int,
                 "supported": bool, "fallback": str|None}],
             "warnings": [str],
             "keyframe_budget": int}

        - 时间偏移全部为 **int 微秒**（AudioSegment 约束）。
        - 能力缺失属性 → ``supported:false`` + fallback 标注，不假装（§44，AC-4）。
        - 复杂 easing 且 bezier_easing 不支持 → ``sampled:true`` 离散关键帧 + warning
          （§47-48，Test 17/AC-4）。
    """
    spec = spec or {}
    caps = _capability_view(capability)

    properties = spec.get("properties") or []
    if isinstance(properties, str):
        properties = [properties]
    if not isinstance(properties, list):
        properties = []

    from_v = spec.get("from") if isinstance(spec.get("from"), dict) else {}
    to_v = spec.get("to") if isinstance(spec.get("to"), dict) else {}
    start_frame = int(spec.get("start_frame") or 0)
    end_frame = int(spec.get("end_frame") or start_frame)
    if base_frame is None:
        base_frame = start_frame
    base_frame = int(base_frame)

    easing = spec.get("easing") if isinstance(spec.get("easing"), dict) else {}
    etype = str(easing.get("type") or "ease").lower()

    samples = _samples_view(sampled)
    if not samples:
        # 退化：起点/终点 2 点线性（§46 简单 Motion 最少 2 帧）
        samples = [
            {"frame": start_frame, "progress": 0.0},
            {"frame": end_frame, "progress": 1.0},
        ]

    # 是否采样模式：复杂 easing 且后端无原生曲线 → sampled（§47-48）
    sampled_mode = False
    if etype in _COMPLEX_EASING and not _cap_supported(caps, "bezier_easing"):
        sampled_mode = True
    if isinstance(sampled, dict):
        if str(sampled.get("easing_mode") or "").upper() == "SAMPLED":
            sampled_mode = True

    warnings: List[str] = []
    if etype in _COMPLEX_EASING and not _cap_supported(caps, "bezier_easing"):
        warnings.append(
            "bezier_easing 不支持（P7-1: keyframe.py:23-34 仅 curveType='Line'）"
            "→ 采样 %d 个离散关键帧（§47-48，Test 17 语义）" % len(samples)
        )
    if spec.get("path") and not _cap_supported(caps, "custom_motion_path"):
        warnings.append(
            "custom_motion_path 不支持（P7-1: keyframe.py:23-34 无 path 字段）"
            "→ Remotion 烘焙（§51）或 position 关键帧采样近似"
        )

    applied: List[Dict[str, Any]] = []
    budget = 0
    for prop in properties:
        pinfo = PROPERTY_JY_MAP.get(prop)
        if pinfo is None:
            warnings.append("未知 motion_property '%s'，跳过（§42 八枚举）" % prop)
            continue

        cap_key = pinfo["capability"]
        supported = _cap_supported(caps, cap_key)
        if not supported:
            fallback = None
            node = caps.get(cap_key)
            if isinstance(node, dict) and node.get("fallback"):
                fallback = str(node["fallback"])
            # §44 不假装：能力缺失 → supported:false + fallback 标注，不生成伪关键帧
            applied.append({
                "motion_property": prop,
                "property": pinfo["jy_property"],
                "jy_property": pinfo["jy_property"],
                "kf_type": pinfo["kf_type"],
                "applies_to": pinfo["applies_to"],
                "keyframes": [],
                "sampled": False,
                "sample_count": 0,
                "supported": False,
                "fallback": fallback,
            })
            continue

        key = pinfo["key"]
        f0 = from_v.get(key)
        t1 = to_v.get(key)
        f0 = float(f0) if isinstance(f0, (int, float)) else _DEFAULT_REST[key]
        t1 = float(t1) if isinstance(t1, (int, float)) else _DEFAULT_REST[key]

        keyframes = []
        for s in samples:
            frame = int(s.get("frame", start_frame))
            progress = float(s.get("progress", 0.0))
            value = round(f0 + (t1 - f0) * progress, 6)
            offset_us = frames_to_us(frame - base_frame, fps)
            if offset_us < 0:  # base_frame 在 spec 起点之后：防负偏移
                offset_us = 0
            keyframes.append({"frame": frame, "time_offset_us": offset_us, "value": value})
        budget += len(keyframes)
        applied.append({
            "motion_property": prop,
            "property": pinfo["jy_property"],
            "jy_property": pinfo["jy_property"],
            "kf_type": pinfo["kf_type"],
            "applies_to": pinfo["applies_to"],
            "keyframes": keyframes,
            "sampled": sampled_mode,
            "sample_count": len(keyframes),
            "supported": True,
            "fallback": None,
        })

    return {
        "applied": applied,
        "warnings": warnings,
        "keyframe_budget": budget,
    }
