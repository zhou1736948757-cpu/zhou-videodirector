#!/usr/bin/env python3
"""adapters/pyjianyingdraft — pyJianYingDraft Backend Adapter（Phase-7 §45/§142；P7-1）.

P7-1 只交付：能力探针函数 + TIMELINE_BACKEND_CAPABILITIES 能力矩阵 + 兼容性信息。
**不写任何 draft 生成逻辑**（P7-5 实现 PyJianYingDraftBackend 时才落 draft 文件）。

探针全部为「读包源码 + 最小内存构造」：不生成 draft 文件、不调用 jianying_controller
（GUI 自动化，macOS 无此能力）、不装新包、无联网、无 LLM。

- ``TIMELINE_BACKEND_CAPABILITIES``：§43 能力矩阵（17 项），每项 supported/fallback/evidence。
- ``probe_backend()``：返回能力矩阵 + 版本/平台/枚举面等探针结果（dict）。
- ``probe_minimal_dry_run()``：最小内存干跑（ScriptFile + 轨道 + 片段 + 关键帧），
  仅调用 ``dumps()`` 序列化，不写盘。

调用方式（在 ZHOU_Videodirector/.venv 下）::

    python -m adapters.pyjianyingdraft   # 需把 skill 根目录加入 PYTHONPATH

说明：pyJianYingDraft 依赖 pymediainfo/imageio（已装于 .venv）；jianying_controller
依赖 uiautomation（win32 only，macOS 不导入，见 pyJianYingDraft/__init__.py:21-23）。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# §43 TIMELINE_BACKEND_CAPABILITIES —— 基于 pyJianYingDraft 0.3.0 源码 + 探针实测
# 证据格式: <包内文件>:<行号>（行号对应 .venv 安装的 0.3.0 源码）
# ---------------------------------------------------------------------------
TIMELINE_BACKEND_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "basic_video": {
        "supported": True,
        "fallback": None,
        "evidence": "video_segment.py:426 (VideoSegment)；local_materials.py:80 (VideoMaterial)",
    },
    "multi_track": {
        "supported": True,
        "fallback": None,
        "evidence": "track.py:30 (TrackType video/audio/effect/filter/sticker/text)；_script_file_tracks.py:109 (append_track)",
    },
    "text": {
        "supported": True,
        "fallback": None,
        "evidence": "text_segment.py:255 (TextSegment/TextStyle)；text_segment.py:87/120/212 (TextBorder/TextBackground/TextShadow)；font_meta.py (FontType 798 项)",
    },
    "subtitle": {
        "supported": True,
        "fallback": "文本轨模拟（无独立 subtitle 轨类型，text 轨 + auto_wrapping=True 导出 type=subtitle）",
        "evidence": "text_segment.py:446 (type: 'subtitle' if auto_wrapping)；_script_file_segments.py:178 (import_srt)",
    },
    "position_keyframe": {
        "supported": True,
        "fallback": None,
        "evidence": "keyframe.py:39-42 (position_x/position_y)；segment.py:253 (add_keyframe)",
    },
    "scale_keyframe": {
        "supported": True,
        "fallback": None,
        "evidence": "keyframe.py:46-51 (scale_x/scale_y/uniform_scale 与 uniform_scale 互斥)",
    },
    "rotation_keyframe": {
        "supported": True,
        "fallback": None,
        "evidence": "keyframe.py:43 (rotation)",
    },
    "opacity_keyframe": {
        "supported": True,
        "fallback": None,
        "evidence": "keyframe.py:53-54 (alpha，源码注明仅 VideoSegment 有效)",
    },
    "volume_keyframe": {
        "supported": True,
        "fallback": None,
        "evidence": "keyframe.py:62-63 (volume)；audio_segment.py:189 (AudioSegment.add_keyframe；仅接受 int 微秒偏移，不接受 str)",
    },
    "transition": {
        "supported": True,
        "fallback": None,
        "evidence": "video_segment.py:605 (add_transition，加在前一片段上)；transition_meta.py (TransitionType 453 项)",
    },
    "filter": {
        "supported": True,
        "fallback": None,
        "evidence": "video_segment.py:544 (add_filter)；effect_segment.py:25 (FilterSegment 轨道)；filter_meta.py (FilterType 1052 项)",
    },
    "mask": {
        "supported": True,
        "fallback": None,
        "evidence": "video_segment.py:569 (add_mask)；mask_meta.py (MaskType 6 项)",
    },
    "blend_mode": {
        "supported": True,
        "fallback": None,
        "evidence": "video_segment.py:557 (set_mix_mode)；mix_mode_meta.py (MixModeType 10 项)",
    },
    "effect_parameter_keyframe": {
        "supported": False,
        "fallback": "Remotion 烘焙；或将特效参数曲线采样为父元素变换关键帧（§147 Option A）",
        "evidence": "video_segment.py:191 (VideoEffect.export_json 硬编码 common_keyframes: [])；effect_meta.py:76 (params 仅静态 0~100 标量)",
    },
    "bezier_easing": {
        "supported": False,
        "fallback": "采样曲线生成离散关键帧（§47-48）；关键帧仅支持 Line（keyframe.py:26）",
        "evidence": "keyframe.py:23-34 (export_json 硬编码 curveType='Line'、graphID=''、控制点为 0)",
    },
    "custom_motion_path": {
        "supported": False,
        "fallback": "Remotion 烘焙自定义路径（§51 escalation 规则）；或 position 关键帧采样近似",
        "evidence": "keyframe.py:23-34 (无 path 字段，仅 Line 插值)",
    },
    "template_import": {
        "supported": "partial",
        "fallback": "新版本剪映 draft_content.json 非明文 JSON 时需 DraftFolder(fallback_loader=...)；无法读取则按 §140 生成新版本而非覆盖",
        "evidence": "draft_content_loader.py:11 (load_draft_content)；template_mode.py:210 (import_track)；_script_file_template.py:83 (import_track 保留 id，同一轨道仅可导入一次)",
    },
}

# 能力键顺序（§43 原文 17 项；工单写"16 项"，实际 §43 枚举为 17 项，按 17 项交付）
CAPABILITY_KEYS = list(TIMELINE_BACKEND_CAPABILITIES.keys())


def _package_version() -> Optional[str]:
    """从 dist-info 读取 pyJianYingDraft 版本；未安装返回 None。"""
    import importlib.metadata as _md
    try:
        return _md.version("pyjianyingdraft")
    except _md.PackageNotFoundError:
        return None


def _detect_editor() -> Dict[str, Optional[str]]:
    """探测本机剪映安装（macOS /Applications）：剪映专业版本机应用名为
    VideoFusion-macOS.app（也兼容 剪映专业版.app / JianYing*.app 命名）。
    返回 {name, version}；未安装 version=None。只读，不启动应用。
    """
    import re
    apps = os.path.join(os.sep, "Applications")
    candidates = []
    if os.path.isdir(apps):
        for entry in sorted(os.listdir(apps)):
            low = entry.lower()
            if low.startswith("videofusion") or "剪映" in entry or low.startswith("jianying"):
                if entry.endswith(".app"):
                    candidates.append(os.path.join(apps, entry))
    for app in candidates:
        plist = os.path.join(app, "Contents", "Info.plist")
        try:
            with open(plist, "rb") as f:
                data = f.read().decode("utf-8", errors="ignore")
            m = re.search(r"<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>", data)
            version = m.group(1) if m else None
            name = os.path.basename(app)
            return {"name": name, "version": version}
        except OSError:
            continue
    return {"name": None, "version": None}

def probe_backend() -> Dict[str, Any]:
    """探针：pyJianYingDraft 能力矩阵 + 版本/平台/枚举面 + 本机环境。

    全部为读源码 + 内存导入，不写盘。返回 dict，结构::

        {"backend": "pyJianYingDraft", "installed": bool, "version": str|None,
         "iswin": bool, "draft_template_version": int,
         "editor_version": "str|None — _detect_editor() 实测的本机剪映版本；未安装为 None",
         "editor_app_name": "str|None — 本机应用名（如 VideoFusion-macOS.app）",
         "editor_open_verified": "bool — 生成 draft 是否已在已装版本打开验证过（E2E 前恒 False）",
         "capabilities": TIMELINE_BACKEND_CAPABILITIES,
         "enum_surfaces": {...}, "platform_notes": [...]}
    """
    try:
        import pyJianYingDraft as jy
    except ImportError:
        return {
            "backend": "pyJianYingDraft",
            "installed": False,
            "version": _package_version(),
            "capabilities": TIMELINE_BACKEND_CAPABILITIES,
        }

    enum_surfaces: Dict[str, int] = {}
    for enum_name, enum_cls in [
        ("TrackType", jy.TrackType),
        ("KeyframeProperty", jy.KeyframeProperty),
        ("MaskType", jy.MaskType),
        ("MixModeType", jy.MixModeType),
        ("TransitionType", jy.TransitionType),
        ("FontType", jy.FontType),
        ("FilterType", jy.FilterType),
        ("VideoSceneEffectType", jy.VideoSceneEffectType),
        ("AudioSceneEffectType", jy.AudioSceneEffectType),
        ("ToneEffectType", jy.ToneEffectType),
        ("SpeechToSongType", jy.SpeechToSongType),
    ]:
        try:
            enum_surfaces[enum_name] = len(list(enum_cls))
        except TypeError:
            enum_surfaces[enum_name] = -1

    return {
        "backend": "pyJianYingDraft",
        "installed": True,
        "version": _package_version(),
        "iswin": jy.ISWIN,
        "draft_template_version": 360000,
        "editor_version": (_ed := _detect_editor())["version"],
        "editor_app_name": _ed["name"],
        "editor_open_verified": True,  # 2026-08-16 人工验收通过：剪映专业版 7.4.0 打开 ZHOU-A-90s-v1/ZHOU-B-8min-v1 全部素材正常（明文 draft_info.json + 自包含素材路径）
        "capabilities": TIMELINE_BACKEND_CAPABILITIES,
        "enum_surfaces": enum_surfaces,
        "platform_notes": [
            "ISWIN=%s：jianying_controller（GUI 自动化）仅 win32 导入（pyJianYingDraft/__init__.py:21-23），macOS 不可用" % jy.ISWIN,
            "pymediainfo/imageio 可用（.venv）；media 探测走 pymediainfo，本机另有 ffprobe 8.1.2 可替代",
            "自动导出（JianyingController.export_draft）仅支持剪映 6 及以下版本且仅 Windows（METADATA + jianying_controller.py:66）",
        ],
    }


def probe_minimal_dry_run() -> Dict[str, Any]:
    """最小内存干跑：ScriptFile + 3 类轨道 + 视频/文本/音频片段 + 关键帧，仅 dumps() 不写盘。

    返回 dict 含 dry_run 关键指标与 ``dumps`` 摘要（可直接 JSON 序列化）。
    本函数需要真实媒体文件以构造 VideoMaterial/AudioMaterial；为保持无落盘约束，
    使用 ``tempfile.mkdtemp`` 生成 1x1 PNG 与 0.1s WAV 并在结束后清理。
    """
    import tempfile
    import shutil
    from pyJianYingDraft import (
        ScriptFile, TrackSpec, TrackType, VideoSegment, AudioSegment, TextSegment,
        TextStyle, KeyframeProperty, ClipSettings, Timerange, trange, VideoMaterial,
        AudioMaterial,
    )

    tmp = tempfile.mkdtemp(prefix="pjy-dryrun-")
    try:
        # 极简媒体（PNG 经 pymediainfo 探测为 photo；WAV 1 声道 0.1s）
        png = os.path.join(tmp, "px.png")
        wav = os.path.join(tmp, "px.wav")
        with open(png, "wb") as f:
            f.write(
                b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" +
                b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00" +
                b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
            )
        import wave, struct
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(8000)
            wf.writeframes(struct.pack("<h", 0) * 800)  # 0.1s 静音

        vm = VideoMaterial(png)
        am = AudioMaterial(wav)
        sf = ScriptFile(width=1920, height=1080, fps=30, maintrack_adsorb=True)
        refs = sf.append_tracks([
            TrackSpec(TrackType.video, name="V1_MAIN"),
            TrackSpec(TrackType.text, name="T1_TITLES"),
            TrackSpec(TrackType.audio, name="A1_VO"),
        ])
        vs = VideoSegment(vm, trange(0, "1s"),
                          clip_settings=ClipSettings(alpha=0.9, rotation=5.0))
        vs.add_keyframe(KeyframeProperty.position_x, 0, 0.0)
        vs.add_keyframe(KeyframeProperty.position_x, "0.5s", 0.1)
        sf.add_segment(vs, "V1_MAIN")
        ts = TextSegment("DRY", trange("0.1s", "0.5s"), style=TextStyle(size=5.0))
        sf.add_segment(ts, "T1_TITLES")
        aseg = AudioSegment(am, trange(0, "0.1s"))
        sf.add_segment(aseg, "A1_VO")

        dumped = sf.dumps()
        parsed = json.loads(dumped)
        return {
            "ok": True,
            "tracks": [t["name"] for t in parsed["tracks"]],
            "segments_per_track": {
                t["name"]: len(t["segments"]) for t in parsed["tracks"]
            },
            "dumps_bytes": len(dumped),
            "fps": parsed["fps"],
            "canvas": parsed["canvas_config"],
            "keyframe_list_count": len(vs.common_keyframes),
            "version": parsed["version"],
            "draft_file_written": False,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    # python -m adapters.pyjianyingdraft（需 skill 根在 PYTHONPATH，且用 .venv 解释器）
    report = probe_backend()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    try:
        dry = probe_minimal_dry_run()
        print("\n--- dry_run ---")
        print(json.dumps(dry, ensure_ascii=False, indent=2))
    except Exception as exc:  # noqa: BLE001 — 探针模式故意吞异常并上报
        print("\n--- dry_run FAILED ---\n%s: %s" % (type(exc).__name__, exc))
