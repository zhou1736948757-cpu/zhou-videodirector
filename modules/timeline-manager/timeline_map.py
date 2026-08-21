#!/usr/bin/env python3
"""timeline_map.py — TIMELINE_MAP.md 生成器（Phase-7 Prompt §87-88/§134/§154；P7-3）.

把 TIMELINE_MANIFEST + Storyboard 装配成人类可读的段表（§87：时间码区间 / Shot ID /
内容 / 轨道说明），并给出 §154 的 Clip→Asset→Source 溯源链。用户不打开 JSON 就能看懂
"整条视频怎么装的"（§88）。

输入：
- ``manifest``：plan_timeline() 产出的 TIMELINE_MANIFEST（§12 真相来源）。
- ``storyboard``（可选）：{shots:[...]} 或 shot 列表，用于把 shot id 映射成叙事内容
  （narrative_purpose / visual_description / voiceover）。
- ``map_title`` / ``map_ref``（可选）：标题与引用名。

输出：
- ``generate_timeline_map(...)``：返回 Markdown 字符串（确定性，无时间戳）。
- ``write_timeline_map(...)``：写入文件（out 路径或由 manifest.timeline_map_ref 决定）。

技术约束：Python 3 stdlib only；无 LLM；无联网；确定性。
"""

from __future__ import annotations

import importlib as _importlib
import re
from typing import Any, Dict, List, Optional
from pathlib import Path

# 连字符包：兄弟模块 planner.py 用 importlib 全名加载
_planner = _importlib.import_module("modules.timeline-manager.planner")


def _tc(frames: Optional[int], fps: int) -> str:
    return _planner.timecode(frames, fps)


def _fmt_seconds(seconds: Optional[float]) -> str:
    if seconds is None:
        return "--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:05.2f}"
    return f"{m:02d}:{s:05.2f}"


def _normalize_storyboard(storyboard: Any) -> Dict[str, Dict[str, str]]:
    """storyboard → {shot_id: {narrative, visual, voiceover}}。"""
    out: Dict[str, Dict[str, str]] = {}
    if isinstance(storyboard, dict):
        shots = storyboard.get("shots")
    else:
        shots = storyboard
    if isinstance(shots, dict):
        shots = list(shots.values())
    for sh in shots or []:
        if not isinstance(sh, dict):
            continue
        sid = str(sh.get("id") or sh.get("shot_id") or "")
        if not sid:
            continue
        out[sid] = {
            "narrative": str(sh.get("narrative_purpose") or ""),
            "visual": str(sh.get("visual_description") or ""),
            "voiceover": str(sh.get("voiceover") or ""),
        }
    return out


def _content_for(shot_info: Optional[Dict[str, str]],
                 clip: Dict[str, Any], track: Dict[str, Any]) -> str:
    """段表内容：字幕 clip 用文本；Shot 用叙事；否则 clip 资产 + 轨道用途。"""
    bmd = clip.get("backend_metadata") or {}
    text = bmd.get("text")
    if text:
        return str(text)
    if shot_info:
        narrative = shot_info.get("narrative") or shot_info.get("visual")
        if narrative:
            return str(narrative)
    aid = clip.get("asset_id", "")
    if aid:
        return f"asset {aid}"
    return track.get("name", "")


def generate_timeline_map(manifest: Dict[str, Any],
                          storyboard: Any = None,
                          map_title: Optional[str] = None,
                          map_ref: Optional[str] = None) -> str:
    """生成 TIMELINE_MAP.md 文本（§87-88/§154）。确定性、纯函数。"""
    fps = int(manifest.get("fps") or 30)
    duration_frames = int(manifest.get("duration_frames") or 0)
    title = map_title or f"TIMELINE_MAP — {manifest.get('timeline_id') or 'TL-???'}"
    shot_info = _normalize_storyboard(storyboard)
    tracks = manifest.get("tracks") or []
    clips = manifest.get("clips") or []
    track_by_id = {t.get("track_id"): t for t in tracks}
    markers = manifest.get("markers") or []
    subtitle_items = manifest.get("subtitle_items") or []
    asset_links = manifest.get("asset_links") or []

    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- timeline_id: {manifest.get('timeline_id') or '-'}")
    lines.append(f"- fps: {fps}  ·  duration: {duration_frames} frame "
                 f"({_fmt_seconds(duration_frames / fps if fps else 0)})")
    lines.append(f"- backend: {manifest.get('backend') or '-'} "
                 f"(preferred: {manifest.get('preferred_timeline_backend') or '-'})")
    lines.append(f"- editability: {manifest.get('editability') or '-'}")
    lines.append("")
    lines.append("> 本文档由 Timeline Planner 确定性生成（§87-88）。"
                 "机器真相来源是 TIMELINE_MANIFEST（§12-13），本 MAP 只做人类可读投影。")
    lines.append("")

    # ---------------------------------------------------------------- §87 段表
    lines.append("## 1. 时间线段表（Clip → Shot → 内容 → 轨道）")
    lines.append("")
    lines.append("| 时间码区间 | Shot | Clip | 轨道 | 内容 / 说明 |")
    lines.append("|---|---|---|---|---|")
    ordered = sorted(clips, key=lambda c: (int(c.get("timeline_start_frame") or 0),
                                           c.get("clip_id", "")))
    for c in ordered:
        track = track_by_id.get(c.get("track_id"), {})
        tc_range = f"{_tc(c.get('timeline_start_frame'), fps)}–{_tc(c.get('timeline_end_frame'), fps)}"
        shot_id = c.get("shot_id") or "-"
        content = _content_for(shot_info.get(str(shot_id)), c, track)
        note_bits: List[str] = []
        if c.get("editable") is True and c.get("replaceable") is True:
            note_bits.append("可编辑")
        elif c.get("editable") is False and c.get("replaceable") is True:
            note_bits.append("可替换(不拆)")
        elif c.get("editable") is False:
            note_bits.append("烘焙")
        if c.get("continuity_group"):
            note_bits.append(f"CG:{c.get('continuity_group')}")
        if c.get("speed") and c.get("speed") != 1.0:
            note_bits.append(f"speed {c.get('speed')}x")
        if c.get("transition_in", {}).get("type") not in (None, "CUT"):
            note_bits.append(f"in:{c['transition_in']['type']}")
        if c.get("transition_out", {}).get("type") not in (None, "CUT"):
            note_bits.append(f"out:{c['transition_out']['type']}")
        cell = str(content).replace("|", "\\|").replace("\n", " ")
        note = "；".join(note_bits)
        if note:
            cell = f"{cell}（{note}）"
        lines.append(f"| {tc_range} | {shot_id} | {c.get('clip_id', '-')} "
                     f"| {track.get('name', c.get('track_id', '-'))} | {cell} |")
    lines.append("")

    # ---------------------------------------------------------------- §87 音频
    audio_types = {"VOICEOVER", "MUSIC", "SFX", "AMBIENCE"}
    audio_clips = [c for c in clips if (track_by_id.get(c.get("track_id")) or {}).get("type")
                   in audio_types]
    if audio_clips:
        lines.append("## 2. 音频装配")
        lines.append("")
        lines.append("| 时间码区间 | Clip | 轨道 | 音频行为 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for c in sorted(audio_clips, key=lambda x: int(x.get("timeline_start_frame") or 0)):
            track = track_by_id.get(c.get("track_id"), {})
            bmd = c.get("backend_metadata") or {}
            extra = []
            if bmd.get("ducking_plan"):
                extra.append("ducking plan 已应用（§66-67）")
            if bmd.get("music_structure"):
                extra.append("music structure 已记录（§65）")
            if bmd.get("ambience_region"):
                extra.append("ambience region（§68-69）")
            if bmd.get("audio_sync"):
                extra.append(f"sync {bmd['audio_sync'].get('event', '')}")
            note = "；".join(extra)
            lines.append(
                f"| {_tc(c.get('timeline_start_frame'), fps)}–"
                f"{_tc(c.get('timeline_end_frame'), fps)} | {c.get('clip_id', '-')} "
                f"| {track.get('name', c.get('track_id', '-'))} "
                f"| {c.get('audio_behavior', '-')} | {note} |")
        lines.append("")

    # ---------------------------------------------------------------- markers
    if markers:
        lines.append("## 3. Markers（§85-86）")
        lines.append("")
        lines.append("| 帧 | 时间码 | Marker | 类型 | 标签 |")
        lines.append("|---|---|---|---|---|")
        for m in sorted(markers, key=lambda x: int(x.get("frame") or 0)):
            lines.append(f"| {m.get('frame')} | {_tc(m.get('frame'), fps)} "
                         f"| {m.get('marker_id', '-')} "
                         f"| {m.get('type', '')} | {str(m.get('label', '')).replace('|', '\\|')} |")
        lines.append("")

    # ---------------------------------------------------------------- subtitles
    if subtitle_items:
        lines.append("## 4. 字幕（§53-57，全部 KEEP_EDITABLE）")
        lines.append("")
        lines.append("| 时间码区间 | subtitle_id | 文本 | 强调 |")
        lines.append("|---|---|---|---|")
        for s in sorted(subtitle_items, key=lambda x: int(x.get("start_frame") or 0)):
            lines.append(f"| {_tc(s.get('start_frame'), fps)}–{_tc(s.get('end_frame'), fps)} "
                         f"| {s.get('subtitle_id', '-')} "
                         f"| {str(s.get('text', '')).replace('|', '\\\\|')} "
                         f"| {s.get('emphasis', 'none')} |")
        lines.append("")

    # ---------------------------------------------------------------- §154 溯源
    lines.append("## 5. Asset Source 溯源链（§154：Clip → Asset → Source）")
    lines.append("")
    lines.append("| Clip | Asset | Source | Producer | 可替换 |")
    lines.append("|---|---|---|---|---|")
    link_by_asset = {a.get("asset_id"): a for a in asset_links}
    src_clips = [c for c in ordered if c.get("asset_id") and c["asset_id"] != "A000"]
    for c in src_clips:
        link = link_by_asset.get(c.get("asset_id"), {})
        source = link.get("source") or (c.get("proxy_usage") or {}).get("original") or "-"
        lines.append(f"| {c.get('clip_id', '-')} | {c.get('asset_id', '-')} "
                     f"| {str(source).replace('|', '\\|')} "
                     f"| {link.get('producer') or '-'} "
                     f"| {'是' if c.get('replaceable') else '否'} |")
    lines.append("")
    lines.append("---")
    lines.append(f"*{map_ref or manifest.get('timeline_map_ref') or 'TIMELINE_MAP.md'}*")
    lines.append("")
    return "\n".join(lines)


def write_timeline_map(manifest: Dict[str, Any],
                       storyboard: Any = None,
                       out_path: Optional[str] = None,
                       map_title: Optional[str] = None) -> str:
    """生成并写入 TIMELINE_MAP.md。返回文件路径。"""
    map_ref = manifest.get("timeline_map_ref") or "TIMELINE_MAP.md"
    text = generate_timeline_map(manifest, storyboard, map_title=map_title, map_ref=map_ref)
    path = Path(out_path) if out_path else Path(map_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    manifest = {
        "timeline_id": "TL-001",
        "fps": 30,
        "duration_frames": 300,
        "backend": "PYJIANYINGDRAFT",
        "preferred_timeline_backend": "PYJIANYINGDRAFT",
        "editability": "KEEP_EDITABLE",
        "timeline_map_ref": "TIMELINE_MAP.md",
        "tracks": [{"track_id": "TR-001", "name": "V1_MAIN", "type": "VIDEO_MAIN"}],
        "clips": [{
            "clip_id": "TC-001", "track_id": "TR-001", "asset_id": "A001",
            "shot_id": "S001",
            "timeline_start_frame": 0, "timeline_end_frame": 149,
            "editable": True, "replaceable": True,
            "proxy_usage": {"policy": "USE_ORIGINAL", "original": "a/A001.mov"},
        }],
        "markers": [{"marker_id": "MK-001", "frame": 0, "type": "Scene start", "label": "Hook"}],
        "subtitle_items": [],
        "asset_links": [{"asset_id": "A001", "track": "V1_MAIN", "manual_edit_safe": True,
                         "source": "source/remotion/S001/", "producer": "REMOTION"}],
    }
    storyboard = {"shots": [{"id": "S001", "narrative_purpose": "Hero hook",
                             "visual_description": "intro"}]}
    md = generate_timeline_map(manifest, storyboard)
    checks = [
        "## 1. 时间线段表" in md,
        "TC-001" in md,
        "S001" in md,
        "Hero hook" in md,
        "A001" in md,
        "source/remotion/S001/" in md,
        "MK-001" in md,
        "## 5. Asset Source 溯源链" in md,
        generate_timeline_map(manifest, storyboard) == md,
    ]
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"timeline_map selftest check #{i} failed")
    print("timeline_map selftest OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
    else:
        print(generate_timeline_map({}, None, map_title="TIMELINE_MAP — empty"))
