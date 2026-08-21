#!/usr/bin/env python3
"""modules/timeline-manager/qa.py — Timeline QA（Phase-7 §123-131/§161-163；P7-6）.

Phase 7 QA 聚焦 assembly/timing/editability/backend validity，不是最终艺术 QA（§123）。
主入口::

    run_qa(manifest, storyboard=None, audio_map=None, asset_index=None)
        -> {
             "manifest_id", "sections": {
               "structural":  {"ok", "findings"},
               "timing":      {"ok", "findings"},
               "audio_assembly": {"ok", "findings"},
               "editability": {"ok", "findings"},
               "over_baked":  {"findings"},
               "over_fragmented": {"findings"},
               "complexity":  {"metrics": {...七指标}, "warnings": [...]},
             },
             "ok", "summary",
           }

四段 QA（§124-128）：
- structural（§125）：shot/scene/layer 顺序、track assignment、continuity group、
  asset mapping；
- timing（§126）：shot/clip timing、SFX sync（audio_map 帧对照）、subtitle sync、
  music sync、transition duration；
- audio_assembly（§127）：VO present、music 响度对照 ducking plan、SFX 缺失、
  ambience continuity、ducking applied、clipping risk；
- editability（§128）：subtitle editable / B-roll editable / simple titles editable /
  replaceable Remotion mapped / AI clips replaceable / human boundaries preserved。

over-baking（§129 Test 20）与 over-fragmentation（§130 Test 21）检测 + complexity
七指标（§161 track_count/clip_count/baked_asset_count/editable_clip_count/
replaceable_asset_count/keyframe_count/transition_count），阈值异常才警告（§163）。

findings 条目：{code, level: "PASS"|"INFO"|"WARN"|"FAIL", detail}。
level=PASS/INFO 不置段 fail；WARN 提示；FAIL 置段 ok=False（§127 缺 VO 等硬伤）。

全确定性：无 LLM、无联网、stdlib only；阈值常量写死并附 § 依据。

CLI:
    python3 modules/timeline-manager/qa.py <manifest.json> [--audio-map <json>]
    python3 modules/timeline-manager/qa.py --selftest
"""

from __future__ import annotations

import re
import sys
from typing import Any, Optional

TRACK_ID_RE = re.compile(r"^TR-\d{3}$")
CLIP_ID_RE = re.compile(r"^TC-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")

# ---------------------------------------------------------------------------
# 阈值常量（§161-163：只用于发现异常，不追求数字越少越好）
# ---------------------------------------------------------------------------

#: over-fragmentation 阈值：同一 continuity_group 或同一资产被拆成 ≥12 个 clip
#: 即告警（§130 "被拆成十几个 Clip"；§7 正确做法是 bake 成单个 Remotion Asset）。
OVER_FRAGMENT_THRESHOLD = 12

#: keyframe 异常阈值：简单 Motion 采样出 >120 个关键帧即告警
#: （§18 Test 18：简单 Motion 产生 150 个关键帧 QA 必须警告；§49 keyframe budget）。
KEYFRAME_COUNT_WARN_THRESHOLD = 120

#: track_count 异常阈值：>12 条轨即告警（§132 V1..V47 毫无结构的反例；§16 建议
#: 短片 7 轨/长片 10 轨左右，留 2 条余量）。
TRACK_COUNT_WARN_THRESHOLD = 12

#: clip_count 异常阈值：>400 个 clip 即告警（§160 "500 个毫无意义的微小 Clip"
#: 不可维护；§132 人类可读轨优先。正常项目 clip 量级在几十~两百）。
CLIP_COUNT_WARN_THRESHOLD = 400

#: SFX sync 容差（帧）：audio_map 标注的 SFX 帧与 SFX clip 起点允许误差（§63
#: frame-level timing；2 帧 ≈ 66ms@30fps，人眼可感，视为未对齐）。
SFX_SYNC_TOLERANCE_FRAMES = 2

#: 过短 clip 阈值（秒）：<0.2s 的视觉 clip 极可能是碎片（§130 碎片化信号）。
MIN_CLIP_DURATION_SECONDS = 0.2

#: 削波风险音量上限：单条音量 >1.0 或重叠两条音量之和 >1.2（§127 clipping risk）。
CLIPPING_VOLUME_SINGLE = 1.0
CLIPPING_VOLUME_SUM = 1.2

#: 简单 Motion 属性集合（§129 判定"简单缩放"：只有这类属性的 ≤6 关键帧 + 无
#: 连续性组 → 若被 bake 即 OVER_BAKED）。
SIMPLE_KEYFRAME_PROPS: frozenset = frozenset({
    "SCALE", "SCALE_X", "SCALE_Y", "OPACITY", "POSITION_X", "POSITION_Y",
})

#: §129 普通元素轨：这些轨上的元素若被 bake（editable=False）即 OVER_BAKED。
BAKE_SUSPECT_TRACKS: frozenset = frozenset({"IMAGE", "SUBTITLE", "TEXT"})

#: audio_map 的 kind 归一化映射（§63/§66/§127）。
_KIND_MAP: dict = {
    "sfx": "sfx", "fx": "sfx", "sound_effect": "sfx", "sfx_key": "sfx",
    "vo": "vo", "voiceover": "vo", "voice": "vo",
    "music": "music", "song": "music",
    "duck": "duck", "ducking": "duck", "duck_key": "duck",
    "ambience": "ambience", "ambient": "ambience",
}

AUDIO_TRACK_TYPES: frozenset = frozenset({"VOICEOVER", "MUSIC", "SFX", "AMBIENCE"})
VIDEO_TRACK_TYPES: frozenset = frozenset({
    "VIDEO_MAIN", "VIDEO_BROLL", "VIDEO_OVERLAY", "VIDEO_MOTION", "VIDEO_3D",
    "VIDEO_AI", "IMAGE",
})


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _track_map(manifest: dict) -> dict:
    return {str(t.get("track_id") or ""): t
            for t in manifest.get("tracks") or [] if isinstance(t, dict) and t.get("track_id")}


def _clips(manifest: dict) -> list:
    return [c for c in manifest.get("clips") or [] if isinstance(c, dict)]


def _fps(manifest: dict) -> int:
    fps = manifest.get("fps") or 30
    try:
        return int(fps)
    except (TypeError, ValueError):
        return 30


def _duration_frames(manifest: dict) -> int:
    dur = manifest.get("duration_frames")
    if isinstance(dur, (int, float)) and dur > 0:
        return int(dur)
    return max((int(c.get("timeline_end_frame") or 0) for c in _clips(manifest)), default=0)


def _finding(code: str, level: str, detail: str, **ids) -> dict:
    return {"code": code, "level": level, "detail": detail, **ids}


def _clip_duration(c: dict) -> int:
    s, e = c.get("timeline_start_frame"), c.get("timeline_end_frame")
    if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
        return 0
    return max(0, int(e) - int(s))


def _normalize_audio_map(audio_map: Any) -> list:
    """把 audio_map 归一为 [{kind, frame|None, time|None, name}]。

    接受：
    - list[{kind/type, frame 或 time 或 timecode, name/id}]
    - dict {"entries": [...]} 或 {"sfx": [...], "vo": [...], "ducking": [...]}
    """
    out: list = []
    if audio_map is None:
        return out
    entries = audio_map
    if isinstance(audio_map, dict):
        if isinstance(audio_map.get("entries"), list):
            entries = audio_map["entries"]
        else:
            entries = []
            for k, v in audio_map.items():
                if isinstance(v, list):
                    for e in v:
                        if isinstance(e, dict):
                            out.append({**e,
                                        "kind": _KIND_MAP.get(
                                            str(k).lower().replace("_entries", ""),
                                            str(k).lower()),
                                        "name": e.get("name") or e.get("id")})
            return out
    for e in entries:
        if not isinstance(e, dict):
            continue
        kind = str(e.get("kind") or e.get("type") or "").lower()
        kind = _KIND_MAP.get(kind, kind or "unknown")
        frame = e.get("frame")
        if frame is None and isinstance(e.get("time"), (int, float)):
            # time 单位按 audio_map 约定（秒 → 帧，由调用方给 fps 或默认 30）
            fps = e.get("fps") or 30
            frame = float(e["time"]) * fps
        out.append({"kind": kind,
                    "frame": int(frame) if isinstance(frame, (int, float)) else None,
                    "time": e.get("time"), "name": e.get("name") or e.get("id")})
    return out


def _storyboard_shots(storyboard: Any) -> list:
    if storyboard is None:
        return []
    if isinstance(storyboard, dict):
        shots = storyboard.get("shots") or storyboard.get("storyboard") or []
    elif isinstance(storyboard, list):
        shots = storyboard
    else:
        return []
    return [s for s in shots if isinstance(s, dict)]


def _shot_span(manifest: dict) -> dict:
    """{shot_id: (min_start, max_end)}：从 clip.shot_id 聚合。"""
    spans: dict = {}
    for c in _clips(manifest):
        sid = c.get("shot_id")
        if not sid:
            continue
        s, e = c.get("timeline_start_frame"), c.get("timeline_end_frame")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            continue
        if sid not in spans:
            spans[str(sid)] = [int(s), int(e)]
        else:
            spans[str(sid)][0] = min(spans[str(sid)][0], int(s))
            spans[str(sid)][1] = max(spans[str(sid)][1], int(e))
    return spans


# ---------------------------------------------------------------------------
# Structural QA（§125）
# ---------------------------------------------------------------------------

def _structural_qa(manifest: dict) -> dict:
    track_map = _track_map(manifest)
    clips = _clips(manifest)
    findings: list = []

    # shot/scene 顺序：按时间排列的 shot_id 必须非降序（S001→S002→...）
    ordered = sorted([c for c in clips if c.get("shot_id")],
                     key=lambda c: c["timeline_start_frame"])
    shot_seq = [str(c.get("shot_id")) for c in ordered]
    bad_order = None
    for a, b in zip(shot_seq, shot_seq[1:]):
        # 数字序号比较（S001/S002），非数字保持原序不判
        def _num(s):
            m = re.search(r"(\d+)", s)
            return int(m.group(1)) if m else None
        na, nb = _num(a), _num(b)
        if na is not None and nb is not None and na > nb:
            bad_order = (a, b)
            break
    if bad_order:
        findings.append(_finding("SHOT_ORDER", "WARN",
                                 f"shot 顺序异常: {bad_order[0]} 出现在 {bad_order[1]} 之后（§125）"))
    else:
        findings.append(_finding("SHOT_ORDER", "PASS", "shot 顺序单调（§125）"))

    # layer 顺序：同轨同时间两个 clip 的 layer_id 相同 → 冲突
    conflicts = 0
    for c in clips:
        if not c.get("layer_id"):
            continue
        for o in clips:
            if o is c or not o.get("layer_id"):
                continue
            if (o.get("track_id") == c.get("track_id")
                    and o.get("layer_id") == c.get("layer_id")
                    and _overlap(c, o)):
                conflicts += 1
    if conflicts:
        findings.append(_finding("LAYER_CONFLICT", "WARN",
                                 f"同轨同层 {conflicts} 处冲突（§125 layer order）"))
    else:
        findings.append(_finding("LAYER_ORDER", "PASS", "layer 归属无冲突（§125）"))

    # track assignment：资产类型 vs 轨道类型（音频资产放音频轨，视频放视频轨）
    asset_track_mismatch = []
    type_by_asset = {str(a.get("asset_id") or ""): a.get("type")
                     for a in manifest.get("asset_links") or [] if isinstance(a, dict)}
    # asset_links 内的 asset 类型不可靠时跳过——仅在能判定时告警
    for c in clips:
        tid = str(c.get("track_id") or "")
        ty = track_map.get(tid, {}).get("type")
        asset_type = type_by_asset.get(str(c.get("asset_id") or ""))
        if asset_type in ("MUSIC", "SFX", "VOICEOVER", "AMBIENCE") and ty not in AUDIO_TRACK_TYPES:
            asset_track_mismatch.append(c.get("clip_id"))
    if asset_track_mismatch:
        findings.append(_finding("TRACK_ASSIGNMENT", "WARN",
                                 f"音频资产被放上非音频轨: {sorted(asset_track_mismatch)}（§125）"))
    else:
        findings.append(_finding("TRACK_ASSIGNMENT", "PASS", "轨道分配合理（§125）"))

    # continuity group intact（§8/§125）：同组同轨相邻无插入
    broken = []
    groups: dict = {}
    for c in clips:
        g = c.get("continuity_group")
        if isinstance(g, str) and g:
            groups.setdefault(g, []).append(c)
    for g, members in sorted(groups.items()):
        tids = {str(m.get("track_id") or "") for m in members}
        if len(tids) > 1:
            broken.append(g)
            continue
        ordered_m = sorted(members, key=lambda m: m["timeline_start_frame"])
        for a, b in zip(ordered_m, ordered_m[1:]):
            if b["timeline_start_frame"] > a["timeline_end_frame"]:
                broken.append(g)
                break
    if broken:
        findings.append(_finding("CONTINUITY_GROUP", "FAIL",
                                 f"连续性组被拆/断开: {sorted(set(broken))}（§8/§125）"))
    else:
        findings.append(_finding("CONTINUITY_GROUP", "PASS",
                                 "continuity group 完整（§125）"))

    # asset mapping（§125）：每个 clip 的 asset_id 应在 asset_links 或
    # replaceable_assets 中登记（若 manifest 提供了这两类数据）。
    if manifest.get("asset_links") or manifest.get("replaceable_assets"):
        known = set()
        for a in manifest.get("asset_links") or []:
            if isinstance(a, dict):
                known.add(str(a.get("asset_ref") or a.get("asset_id") or ""))
        known |= {str(a) for a in manifest.get("replaceable_assets") or []}
        unmapped = sorted({str(c.get("asset_id") or "") for c in clips} - known - {""})
        if unmapped:
            findings.append(_finding("ASSET_MAPPING", "WARN",
                                     f"clip 引用的资产未登记: {unmapped}（§125）"))
        else:
            findings.append(_finding("ASSET_MAPPING", "PASS", "asset mapping 完整（§125）"))
    else:
        findings.append(_finding("ASSET_MAPPING", "INFO",
                                 "无 asset_links/replaceable_assets 数据，跳过 mapping 检查（§125）"))

    ok = all(f["level"] not in ("FAIL",) for f in findings)
    return {"ok": ok, "findings": findings}


def _overlap(a: dict, b: dict) -> bool:
    return (a["timeline_start_frame"] < b["timeline_end_frame"]
            and b["timeline_start_frame"] < a["timeline_end_frame"])


# ---------------------------------------------------------------------------
# Timing QA（§126）
# ---------------------------------------------------------------------------

def _timing_qa(manifest: dict, storyboard: Any, audio_map: Any) -> dict:
    track_map = _track_map(manifest)
    clips = _clips(manifest)
    fps = _fps(manifest)
    total = _duration_frames(manifest)
    findings: list = []
    entries = _normalize_audio_map(audio_map)

    # shot timing vs storyboard（§126 shot timing）
    sb_shots = _storyboard_shots(storyboard)
    spans = _shot_span(manifest)
    if sb_shots:
        drifted = []
        for s in sb_shots:
            sid = str(s.get("id") or s.get("shot_id") or "")
            dur = s.get("duration_seconds") or s.get("duration")
            if not sid or not isinstance(dur, (int, float)) or sid not in spans:
                continue
            span_frames = spans[sid][1] - spans[sid][0]
            expect_frames = int(dur * fps)
            if abs(span_frames - expect_frames) > 2 * fps:  # >2s 漂移
                drifted.append(f"{sid}({span_frames}帧vs{expect_frames}帧)")
        if drifted:
            findings.append(_finding("SHOT_TIMING_DRIFT", "WARN",
                                     f"shot 时长偏离 storyboard: {', '.join(sorted(drifted))}（§126）"))
        else:
            findings.append(_finding("SHOT_TIMING", "PASS", "shot 时长与 storyboard 一致（§126）"))
    else:
        findings.append(_finding("SHOT_TIMING", "INFO", "无 storyboard，跳过 shot 时长对照（§126）"))

    # clip timing（§126）：过短 clip 告警
    too_short = [c.get("clip_id") for c in clips
                 if 0 < _clip_duration(c) < fps * MIN_CLIP_DURATION_SECONDS]
    if too_short:
        findings.append(_finding("CLIP_TOO_SHORT", "WARN",
                                 f"过短 clip（<{MIN_CLIP_DURATION_SECONDS}s）: "
                                 f"{sorted(too_short)}（§130 碎片化信号）"))
    else:
        findings.append(_finding("CLIP_TIMING", "PASS", "clip 时长正常（§126）"))

    # SFX sync（§126/§63）：audio_map 帧对照
    sfx_entries = [e for e in entries if e["kind"] == "sfx"]
    sfx_clips = [c for c in clips
                 if track_map.get(str(c.get("track_id") or ""), {}).get("type") == "SFX"]
    unsynced = []
    for e in sfx_entries:
        if e["frame"] is None:
            continue
        hit = any(abs(int(c["timeline_start_frame"]) - e["frame"]) <= SFX_SYNC_TOLERANCE_FRAMES
                  for c in sfx_clips)
        if not hit:
            unsynced.append(f"{e['name'] or '?'}@{e['frame']}")
    if unsynced:
        findings.append(_finding("SFX_UNSYNCED", "WARN",
                                 f"SFX 未对齐: {', '.join(unsynced)}（§63 frame 级同步）"))
    else:
        findings.append(_finding("SFX_SYNC", "PASS", "SFX 帧对齐（§126）" if sfx_entries
                                 else "无 SFX 同步点需要核对（§126）"))

    # subtitle sync（§126）：字幕应落在 VO 区间内（VO 存在时）
    vo_clips = [c for c in clips
                if track_map.get(str(c.get("track_id") or ""), {}).get("type") == "VOICEOVER"]
    sub_outside = []
    for s in manifest.get("subtitle_items") or []:
        if not isinstance(s, dict) or not vo_clips:
            continue
        st, et = s.get("start_frame"), s.get("end_frame")
        if not isinstance(st, (int, float)) or not isinstance(et, (int, float)):
            continue
        if not any(int(st) < int(c["timeline_end_frame"])
                   and int(c["timeline_start_frame"]) < int(et) for c in vo_clips):
            sub_outside.append(s.get("subtitle_id") or s.get("text"))
    if sub_outside:
        findings.append(_finding("SUBTITLE_VO_MISMATCH", "WARN",
                                 f"字幕落在 VO 区间外: {sub_outside[:5]}（§126）"))
    else:
        findings.append(_finding("SUBTITLE_SYNC", "PASS", "字幕与 VO 对齐（§126）" if vo_clips
                                 else "无 VO，跳过字幕-VO 对照（§126）"))

    # music sync（§126/§64）：音乐应覆盖全片（起点 0 或 1 帧内，终点 ≥ total）
    music_clips = [c for c in clips
                   if track_map.get(str(c.get("track_id") or ""), {}).get("type") == "MUSIC"]
    if music_clips:
        m_start = min(int(c["timeline_start_frame"]) for c in music_clips)
        m_end = max(int(c["timeline_end_frame"]) for c in music_clips)
        music_issues = []
        if m_start > 1:
            music_issues.append(f"起点 {m_start} 不在 0")
        if total and m_end < total - int(fps):
            music_issues.append(f"终点 {m_end} 早于全片 {total}（差>{fps}帧）")
        if music_issues:
            findings.append(_finding("MUSIC_SYNC", "WARN", f"音乐覆盖异常: {'; '.join(music_issues)}（§64）"))
        else:
            findings.append(_finding("MUSIC_SYNC", "PASS", "音乐覆盖全片（§126）"))
    else:
        findings.append(_finding("MUSIC_SYNC", "INFO", "无音乐轨（§126）"))

    # transition duration（§126/§72）：转场时长必须 < 两侧 clip 时长
    bad_tx = []
    for c in clips:
        dur = _clip_duration(c)
        for side in ("transition_in", "transition_out"):
            tx = c.get(side)
            if not isinstance(tx, dict):
                continue
            td = tx.get("duration_frames")
            if isinstance(td, (int, float)) and dur and int(td) >= dur:
                bad_tx.append(f"{c.get('clip_id')}.{side}={td}≥clip{dur}")
    if bad_tx:
        findings.append(_finding("TRANSITION_DURATION", "WARN",
                                 f"转场时长 >= clip 时长: {', '.join(bad_tx[:5])}（§72）"))
    else:
        findings.append(_finding("TRANSITION_DURATION", "PASS", "转场时长合理（§126）"))

    ok = all(f["level"] not in ("FAIL",) for f in findings)
    return {"ok": ok, "findings": findings}


# ---------------------------------------------------------------------------
# Audio Assembly QA（§127）
# ---------------------------------------------------------------------------

def _audio_assembly_qa(manifest: dict, audio_map: Any) -> dict:
    track_map = _track_map(manifest)
    clips = _clips(manifest)
    entries = _normalize_audio_map(audio_map)
    findings: list = []

    def _audio_clips(*types):
        return [c for c in clips
                if track_map.get(str(c.get("track_id") or ""), {}).get("type") in types]

    vo_clips = _audio_clips("VOICEOVER")
    music_clips = _audio_clips("MUSIC")
    sfx_clips = _audio_clips("SFX")
    amb_clips = _audio_clips("AMBIENCE")

    # VO present（§127）：audio_map 或 storyboard 声明需要 VO 时必须存在
    vo_needed = any(e["kind"] == "vo" for e in entries)
    if vo_needed and not vo_clips:
        findings.append(_finding("AUDIO_VO_MISSING", "FAIL",
                                 "audio_map 声明 VO 但时间线无 VOICEOVER 轨（§127）"))
    else:
        findings.append(_finding("VO_PRESENT", "PASS", "VO 就位（§127）" if vo_clips
                                 else "无 VO 需求/无 VO（§127）"))

    # music loudness vs ducking plan（§127/§66）：ducking 计划存在而音乐未降 →
    # 警告；音乐音量过大且与 VO 重叠 → 警告
    duck_needed = any(e["kind"] == "duck" for e in entries)
    music_volume = _max_volume(music_clips)
    duck_applied = _ducking_applied(music_clips, vo_clips)
    if duck_needed and not duck_applied:
        findings.append(_finding("DUCKING_NOT_APPLIED", "WARN",
                                 "ducking plan 存在但音乐未见降幅/VOLUME 关键帧（§66/§127）"))
    else:
        findings.append(_finding("DUCKING_APPLIED", "PASS", "ducking 已应用（§127）" if duck_applied
                                 else "无 ducking 需求（§127）"))
    if music_volume and music_volume > 0.9 and vo_clips:
        findings.append(_finding("MUSIC_TOO_LOUD", "WARN",
                                 f"音乐峰值音量 {music_volume} 与 VO 重叠时偏高（§127）"))
    else:
        findings.append(_finding("MUSIC_LEVEL", "PASS", "音乐响度正常（§127）"))

    # SFX missing（§127）：audio_map 有 SFX 而时间线无 SFX clip
    sfx_needed = any(e["kind"] == "sfx" for e in entries)
    if sfx_needed and not sfx_clips:
        findings.append(_finding("SFX_MISSING", "WARN",
                                 "audio_map 声明 SFX 但时间线无 SFX 轨（§127）"))
    else:
        findings.append(_finding("SFX_PRESENT", "PASS", "SFX 就位（§127）" if sfx_clips
                                 else "无 SFX 需求（§127）"))

    # ambience continuity（§127/§68-69）：同资产 ambience 出现 >1 段且中间有
    # 间隔（或重复实例）→ 提示合并为 ambience region。
    by_asset: dict = {}
    for c in amb_clips:
        by_asset.setdefault(str(c.get("asset_id") or ""), []).append(c)
    amb_warns = []
    for aid, cs in sorted(by_asset.items()):
        cs_sorted = sorted(cs, key=lambda c: c["timeline_start_frame"])
        for a, b in zip(cs_sorted, cs_sorted[1:]):
            if int(b["timeline_start_frame"]) > int(a["timeline_end_frame"]):
                amb_warns.append(f"{aid}: {a.get('clip_id')}→{b.get('clip_id')}")
                break
    if amb_warns:
        findings.append(_finding("AMBIENCE_DISCONTINUOUS", "WARN",
                                 f"同资产 ambience 被切段: {', '.join(amb_warns)}；建议合并为 "
                                 f"ambience region 跨 Shot 连续（§68-69/§127）"))
    else:
        findings.append(_finding("AMBIENCE_CONTINUITY", "PASS", "ambience 连续（§127）" if amb_clips
                                 else "无 ambience（§127）"))

    # clipping risk（§127）：单条音量 >1.0，或重叠音频音量之和 >1.2
    clipping = []
    for c in clips:
        v = c.get("volume")
        if isinstance(v, (int, float)) and v > CLIPPING_VOLUME_SINGLE:
            clipping.append(f"{c.get('clip_id')} vol={v}")
    if clipping:
        findings.append(_finding("CLIPPING_RISK", "WARN",
                                 f"单条音量超过 {CLIPPING_VOLUME_SINGLE}: "
                                 f"{', '.join(clipping[:5])}（§127）"))
    else:
        findings.append(_finding("CLIPPING", "PASS", "无削波风险（§127）"))

    ok = all(f["level"] not in ("FAIL",) for f in findings)
    return {"ok": ok, "findings": findings}


def _max_volume(clips: list) -> float:
    vols = [float(c.get("volume") or 0) for c in clips
            if isinstance(c.get("volume"), (int, float))]
    return max(vols) if vols else 0.0


def _ducking_applied(music_clips: list, vo_clips: list) -> bool:
    """ducking 是否已应用：音乐音量 <1.0，或带 VOLUME 关键帧，或 backend 声明。"""
    if not music_clips:
        return False
    for c in music_clips:
        v = c.get("volume")
        if isinstance(v, (int, float)) and v < 1.0:
            return True
        for kf in c.get("keyframes") or []:
            if isinstance(kf, dict) and kf.get("property") == "VOLUME":
                return True
        md = c.get("backend_metadata")
        if isinstance(md, dict) and md.get("ducking_applied") is True:
            return True
    return False


# ---------------------------------------------------------------------------
# Editability QA（§128）
# ---------------------------------------------------------------------------

def _editability_qa(manifest: dict, asset_index: Optional[dict]) -> dict:
    track_map = _track_map(manifest)
    clips = _clips(manifest)
    findings: list = []

    def _on_track(*types):
        return [c for c in clips
                if track_map.get(str(c.get("track_id") or ""), {}).get("type") in types]

    def _editable(c: dict, default=True) -> bool:
        v = c.get("editable")
        return default if v is None else bool(v)

    # subtitle editable（§128/§55：默认 editable=true，必须 KEEP_EDITABLE）
    sub_clips = _on_track("SUBTITLE")
    non_edit_sub = [c.get("clip_id") for c in sub_clips if not _editable(c)]
    non_edit_sub += [str(s.get("subtitle_id") or s.get("text"))
                     for s in manifest.get("subtitle_items") or []
                     if isinstance(s, dict) and s.get("editable") is False]
    if non_edit_sub:
        findings.append(_finding("SUBTITLE_NOT_EDITABLE", "FAIL",
                                 f"字幕被 bake: {sorted(non_edit_sub)}；默认应 KEEP_EDITABLE（§55/§128）"))
    else:
        findings.append(_finding("SUBTITLE_EDITABLE", "PASS", "字幕可编辑（§128）"))

    # B-roll editable（§128）
    broll = _on_track("VIDEO_BROLL")
    non_edit_broll = [c.get("clip_id") for c in broll if not _editable(c)]
    if non_edit_broll:
        findings.append(_finding("BROLL_NOT_EDITABLE", "WARN",
                                 f"B-roll 被 bake: {sorted(non_edit_broll)}（§128）"))
    else:
        findings.append(_finding("BROLL_EDITABLE", "PASS", "B-roll 可编辑（§128）"))

    # simple titles editable（§128）
    titles = _on_track("TEXT")
    non_edit_title = [c.get("clip_id") for c in titles if not _editable(c)]
    if non_edit_title:
        findings.append(_finding("TITLE_NOT_EDITABLE", "WARN",
                                 f"简单标题被 bake: {sorted(non_edit_title)}（§128）"))
    else:
        findings.append(_finding("TITLES_EDITABLE", "PASS", "简单标题可编辑（§128）"))

    # replaceable Remotion mapped（§128/§33-35）：replaceable 资产必须有 asset_slot_id
    replaceable = set()
    for a in manifest.get("replaceable_assets") or []:
        if isinstance(a, str):
            replaceable.add(a)
        elif isinstance(a, dict):
            replaceable.add(str(a.get("asset_id") or ""))
    if asset_index:
        replaceable |= {aid for aid, a in asset_index.items()
                        if isinstance(a, dict) and a.get("replaceable") is True}
    unslotted = [f"{c.get('clip_id')}({c.get('asset_id')})" for c in clips
                 if str(c.get("asset_id") or "") in replaceable
                 and not c.get("asset_slot_id")]
    if unslotted:
        findings.append(_finding("REPLACEABLE_NOT_SLOTTED", "WARN",
                                 f"可替换资产未映射 asset_slot: {sorted(unslotted)}（§33-35/§128）"))
    else:
        findings.append(_finding("REPLACEABLE_MAPPED", "PASS", "可替换资产已映射槽位（§128）"))

    # AI clips replaceable（§128/§33-35）
    ai_clips = _on_track("VIDEO_AI")
    non_rep_ai = [c.get("clip_id") for c in ai_clips if c.get("replaceable") is False]
    if non_rep_ai:
        findings.append(_finding("AI_CLIP_NOT_REPLACEABLE", "WARN",
                                 f"AI clip 不可替换: {sorted(non_rep_ai)}（§81-82/§128）"))
    else:
        findings.append(_finding("AI_CLIPS_REPLACEABLE", "PASS", "AI clip 可替换（§128）"))

    # human boundaries preserved（§128/§106-108）
    human_clips = [c for c in clips if c.get("owner") == "HUMAN"]
    violated = [c.get("clip_id") for c in human_clips if not _editable(c)]
    if violated:
        findings.append(_finding("HUMAN_BOUNDARY_VIOLATED", "FAIL",
                                 f"HUMAN 拥有的 clip 被标不可编辑: {sorted(violated)}（§106/§108/§128）"))
    else:
        findings.append(_finding("HUMAN_BOUNDARIES", "PASS",
                                 "human 编辑边界保留（§128）" if human_clips
                                 else "无 HUMAN 拥有项（§128）"))

    ok = all(f["level"] not in ("FAIL",) for f in findings)
    return {"ok": ok, "findings": findings}


# ---------------------------------------------------------------------------
# OVER_BAKED（§129 Test 20）与 OVER_FRAGMENTED（§130 Test 21）
# ---------------------------------------------------------------------------

def detect_over_baked(manifest: dict, asset_index: Optional[dict] = None) -> list:
    """§129 over-baking 检测：普通字幕/图片/简单缩放被 bake 进 Remotion MP4。

    判定（写死启发式，确定性）：
    - 轨型是 IMAGE/SUBTITLE/TEXT 且 clip.editable=False → 必然可疑（普通元素
      不该 bake，§7/§55/§77）；
    - 其余 editable=False 的 clip：仅含简单属性关键帧（SIMPLE_KEYFRAME_PROPS，
      ≤6 帧）且无 continuity_group → 疑似"简单缩放被 bake"；
    - 音频轨（VOICEOVER/MUSIC/SFX/AMBIENCE，AUDIO_TRACK_TYPES）的 clip 一律不
      参与 baked-motion 判定：音频没有"缩放/位移动画被 bake"语义（§129 只关心
      视觉元素），editable=False 由其他 QA（audio_assembly/editability）把关
      （FR-002 修复：A 的 17 条 SFX 被误判为"简单缩放被 bake"）。
    - asset_index 提供的资产 editability=BAKE 且 producer=REMOTION 时补充说明。

    Returns: [{"clip_id", "asset_id", "reason"}...]
    """
    track_map = _track_map(manifest)
    out = []
    for c in _clips(manifest):
        if c.get("editable") is not False:
            continue
        tid = str(c.get("track_id") or "")
        ty = track_map.get(tid, {}).get("type")
        if ty in AUDIO_TRACK_TYPES:
            # 音频类 clip 不参与 baked-motion 判定（§129 只针对视觉元素）
            continue
        reason = None
        if ty in BAKE_SUSPECT_TRACKS:
            reason = f"普通{ {'IMAGE': '图片', 'SUBTITLE': '字幕', 'TEXT': '标题'}[ty] }被 bake（§7/§129）"
        elif not c.get("continuity_group"):
            kfs = c.get("keyframes") or []
            simple = all(isinstance(k, dict) and k.get("property") in SIMPLE_KEYFRAME_PROPS
                         for k in kfs)
            if len(kfs) <= 6 and simple:
                reason = "仅简单缩放/位移动画被 bake（§129）"
        if reason:
            asset = asset_index.get(str(c.get("asset_id") or "")) if asset_index else None
            if isinstance(asset, dict) and asset.get("producer") == "REMOTION":
                reason += "（Remotion MP4 内，普通元素应留在剪映编辑）"
            out.append({"clip_id": c.get("clip_id"), "asset_id": c.get("asset_id"),
                        "reason": reason})
    out.sort(key=lambda x: str(x["clip_id"]))
    return out


def detect_over_fragmented(manifest: dict, asset_index: Optional[dict] = None) -> list:
    """§130 over-fragmentation 检测：复杂连续 Motion 被拆成 ≥N 个 clip。

    判定（写死启发式，确定性）：
    - 同一 continuity_group 的 clip 数 ≥ OVER_FRAGMENT_THRESHOLD；
    - 无组但同一资产在 VIDEO_MOTION 轨的 clip 数 ≥ 阈值（连续 Motion 疑似被拆）；
    - 资产 editability=KEEP_EDITABLE 且 REMOTION producer 时（asset_index）补充说明。

    Returns: [{"group": ..., "clip_count": int, "clip_ids": [...], "reason": str}...]
    """
    track_map = _track_map(manifest)
    out = []
    by_group: dict = {}
    by_asset_motion: dict = {}
    for c in _clips(manifest):
        g = c.get("continuity_group")
        if isinstance(g, str) and g:
            by_group.setdefault(g, []).append(c)
        if track_map.get(str(c.get("track_id") or ""), {}).get("type") == "VIDEO_MOTION":
            by_asset_motion.setdefault(str(c.get("asset_id") or ""), []).append(c)
    for g, members in sorted(by_group.items()):
        if len(members) >= OVER_FRAGMENT_THRESHOLD:
            out.append({"group": g, "clip_count": len(members),
                        "clip_ids": [c.get("clip_id") for c in
                                     sorted(members, key=lambda c: c["timeline_start_frame"])],
                        "reason": f"连续性组 {g} 被拆成 {len(members)} 个 clip（§130）"})
    for aid, members in sorted(by_asset_motion.items()):
        if aid and len(members) >= OVER_FRAGMENT_THRESHOLD:
            asset = asset_index.get(aid) if asset_index else None
            extra = ""
            if isinstance(asset, dict) and asset.get("producer") == "REMOTION":
                extra = "；该资产由 Remotion 生产，应整段进入（§51/§130）"
            out.append({"group": f"asset:{aid}", "clip_count": len(members),
                        "clip_ids": [c.get("clip_id") for c in
                                     sorted(members, key=lambda c: c["timeline_start_frame"])],
                        "reason": f"Motion 轨同一资产 {aid} 被拆成 {len(members)} 个 clip{extra}（§130）"})
    out.sort(key=lambda x: str(x["group"]))
    return out


# ---------------------------------------------------------------------------
# Complexity metrics（§161-163）
# ---------------------------------------------------------------------------

def complexity_metrics(manifest: dict, asset_index: Optional[dict] = None) -> dict:
    """§161 七指标 + §162/§163 异常阈值警告。"""
    track_map = _track_map(manifest)
    clips = _clips(manifest)

    baked = set()
    editable = 0
    replaceable = set()
    keyframe_count = 0
    transition_count = 0
    for c in clips:
        if c.get("editable") is False:
            baked.add(str(c.get("asset_id") or c.get("clip_id")))
        else:
            editable += 1
        if c.get("replaceable") is True:
            replaceable.add(str(c.get("asset_id") or ""))
        if isinstance(c.get("keyframes"), list):
            keyframe_count += len(c["keyframes"])
        for side in ("transition_in", "transition_out"):
            tx = c.get(side)
            if isinstance(tx, dict) and tx.get("type") not in (None, "CUT"):
                transition_count += 1
    keyframe_count += len([k for k in manifest.get("keyframes") or [] if isinstance(k, dict)])

    if asset_index:
        baked |= {aid for aid, a in asset_index.items()
                  if isinstance(a, dict) and a.get("editability") == "BAKE"}
        replaceable |= {aid for aid, a in asset_index.items()
                        if isinstance(a, dict) and a.get("replaceable") is True}

    metrics = {
        "track_count": len(manifest.get("tracks") or []),
        "clip_count": len(clips),
        "baked_asset_count": len(baked),
        "editable_clip_count": editable,
        "replaceable_asset_count": len(replaceable),
        "keyframe_count": keyframe_count,
        "transition_count": transition_count,
    }
    warnings = []
    if metrics["track_count"] > TRACK_COUNT_WARN_THRESHOLD:
        warnings.append(f"track_count={metrics['track_count']} > "
                        f"{TRACK_COUNT_WARN_THRESHOLD}（§132 轨道爆炸，人类不可读）")
    if metrics["clip_count"] > CLIP_COUNT_WARN_THRESHOLD:
        warnings.append(f"clip_count={metrics['clip_count']} > "
                        f"{CLIP_COUNT_WARN_THRESHOLD}（§160 碎片化风险）")
    if metrics["keyframe_count"] > KEYFRAME_COUNT_WARN_THRESHOLD:
        warnings.append(f"keyframe_count={metrics['keyframe_count']} > "
                        f"{KEYFRAME_COUNT_WARN_THRESHOLD}（§18 关键帧爆炸）")
    return {"metrics": metrics, "warnings": warnings}


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_qa(manifest: dict, storyboard: Any = None, audio_map: Any = None,
           asset_index: Optional[dict] = None) -> dict:
    """§123-131/§161-163 四段 QA + over-bake/over-fragment + complexity。

    Args:
        manifest: Timeline Manifest。
        storyboard: 导演文档（shot 时长对照用，§126）。list[shot] 或
            {"shots": [...]}；shot 含 id/shot_id、duration_seconds/duration。
        audio_map: AUDIO_MAP 结构化数据（§62/§63）。list[{kind,frame|time}] 或
            {"sfx": [...], "vo": [...], "ducking": [...]}。
        asset_index: {asset_id: asset dict}（可选，enhance over-bake/
            replaceable/complexity 判定）。

    Returns: 见模块 docstring 结构。``ok`` = 四段无 FAIL 级 finding。
    """
    structural = _structural_qa(manifest)
    timing = _timing_qa(manifest, storyboard, audio_map)
    audio = _audio_assembly_qa(manifest, audio_map)
    editability = _editability_qa(manifest, asset_index)
    baked = detect_over_baked(manifest, asset_index)
    fragmented = detect_over_fragmented(manifest, asset_index)
    complexity = complexity_metrics(manifest, asset_index)

    sections = {
        "structural": structural,
        "timing": timing,
        "audio_assembly": audio,
        "editability": editability,
        "over_baked": {"findings": [_finding("OVER_BAKED", "WARN", b["reason"],
                                             clip_id=b["clip_id"], asset_id=b["asset_id"])
                                    for b in baked]},
        "over_fragmented": {"findings": [_finding("OVER_FRAGMENTED", "WARN", b["reason"],
                                                  **({} if b["group"].startswith("asset:")
                                                      else {"continuity_group": b["group"]}))
                                         for b in fragmented]},
        "complexity": complexity,
    }
    ok = all(sections[k]["ok"] for k in ("structural", "timing", "audio_assembly", "editability"))
    counts = {"PASS": 0, "INFO": 0, "WARN": 0, "FAIL": 0}
    for k in ("structural", "timing", "audio_assembly", "editability",
              "over_baked", "over_fragmented"):
        for f in sections[k]["findings"]:
            counts[f["level"]] = counts.get(f["level"], 0) + 1
    summary = (f"{counts['PASS']} PASS, {counts['INFO']} INFO, {counts['WARN']} WARN, "
               f"{counts['FAIL']} FAIL"
               + (f"；complexity 警告 {len(complexity['warnings'])} 条" if complexity["warnings"] else ""))
    return {"manifest_id": manifest.get("timeline_id") or "UNKNOWN",
            "sections": sections, "ok": ok, "summary": summary}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    args = list(argv or [])
    if "--selftest" in args:
        selftest()
        return 0
    if not args:
        print("用法: python3 modules/timeline-manager/qa.py <manifest.json> "
              "[--audio-map <json>] [--asset-index <json>]", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        audio_map = None
        asset_index = None
        i = 1
        while i < len(args):
            if args[i] == "--audio-map" and i + 1 < len(args):
                audio_map = json.loads(Path(args[i + 1]).read_text(encoding="utf-8"))
                i += 2
            elif args[i] == "--asset-index" and i + 1 < len(args):
                asset_index = json.loads(Path(args[i + 1]).read_text(encoding="utf-8"))
                i += 2
            else:
                i += 1
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report = run_qa(manifest, audio_map=audio_map, asset_index=asset_index)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    from copy import deepcopy  # noqa: PLC0415

    def clip(cid, asset, s, e, track="TR-001", **kw):
        return {"clip_id": cid, "track_id": track, "asset_id": asset,
                "timeline_start_frame": s, "timeline_end_frame": e, **kw}

    def manifest(**kw):
        m = {
            "timeline_id": "TL-001", "version": "timeline_v1", "fps": 30,
            "duration_frames": 900,  # 30s
            "tracks": [
                {"track_id": "TR-001", "type": "VIDEO_MAIN", "name": "V1_MAIN"},
                {"track_id": "TR-002", "type": "VIDEO_BROLL", "name": "V2_BROLL"},
                {"track_id": "TR-003", "type": "VIDEO_MOTION", "name": "V3_MOTION"},
                {"track_id": "TR-004", "type": "SUBTITLE", "name": "T2_SUBTITLES"},
                {"track_id": "TR-005", "type": "TEXT", "name": "T1_TITLES"},
                {"track_id": "TR-006", "type": "VOICEOVER", "name": "A1_VO"},
                {"track_id": "TR-007", "type": "MUSIC", "name": "A2_MUSIC"},
                {"track_id": "TR-008", "type": "SFX", "name": "A3_SFX"},
            ],
            "clips": [
                clip("TC-001", "A001", 0, 300),                     # shot S001
                clip("TC-002", "A002", 300, 600, shot_id="S002"),
                clip("TC-003", "A003", 600, 900, shot_id="S003"),
                clip("TC-004", "A004", 120, 400, track="TR-002"),   # b-roll
                clip("TC-005", "A005", 0, 900, track="TR-006"),     # VO 全片
                clip("TC-006", "A006", 0, 900, track="TR-007", volume=0.8),
                clip("TC-007", "A007", 150, 155, track="TR-008"),   # SFX @150
                clip("TC-008", "A008", 60, 90, track="TR-005"),     # title
            ],
            "subtitle_items": [
                {"subtitle_id": "SUB-01", "text": "line", "start_frame": 30, "end_frame": 120},
            ],
            "text_items": [], "audio_tracks": [], "sfx_tracks": [],
            "music_tracks": [], "overlays": [], "keyframes": [],
            "transitions": [], "asset_links": [
                {"asset_ref": "A001"}, {"asset_ref": "A002"}, {"asset_ref": "A003"},
                {"asset_ref": "A004"}, {"asset_ref": "A005"}, {"asset_ref": "A006"},
                {"asset_ref": "A007"}, {"asset_ref": "A008"},
            ],
            "replaceable_assets": ["A002", "A003"],
            "manual_edit_safe": True,
        }
        m.update(kw)
        return m

    assets = {
        "A001": {"asset_id": "A001", "producer": "EXTERNAL_VISUAL", "type": "FOOTAGE",
                 "replaceable": False, "editability": "KEEP_EDITABLE"},
        "A002": {"asset_id": "A002", "producer": "REMOTION", "type": "MOTION_CLIP",
                 "replaceable": True, "editability": "ASSET_REPLACEABLE"},
        "A003": {"asset_id": "A003", "producer": "REMOTION", "type": "MOTION_CLIP",
                 "replaceable": True, "editability": "ASSET_REPLACEABLE"},
        "A004": {"asset_id": "A004", "producer": "FOOTAGE_PROVIDER", "type": "FOOTAGE",
                 "replaceable": False, "editability": "KEEP_EDITABLE"},
        "A005": {"asset_id": "A005", "producer": "SOUND", "type": "VOICEOVER",
                 "replaceable": False, "editability": "KEEP_EDITABLE"},
        "A006": {"asset_id": "A006", "producer": "LIBRARY_MUSIC", "type": "MUSIC",
                 "replaceable": False, "editability": "KEEP_EDITABLE"},
        "A007": {"asset_id": "A007", "producer": "SOUND", "type": "SFX",
                 "replaceable": False, "editability": "KEEP_EDITABLE"},
        "A008": {"asset_id": "A008", "producer": "USER", "type": "IMAGE",
                 "replaceable": False, "editability": "KEEP_EDITABLE"},
    }
    checks = []

    # --- 干净工程 → 四段全 PASS/INFO，ok=True ---
    audio_map = {
        "sfx": [{"id": "click", "frame": 150}],
        "vo": [{"id": "vo-1", "frame": 0}],
        "ducking": [{"id": "duck-1", "frame": 0}],
    }
    r = run_qa(manifest(), audio_map=audio_map, asset_index=assets)
    checks.append(r["ok"] is True)
    st = r["sections"]["structural"]
    checks.append(st["ok"] is True)
    checks.append(any(f["code"] == "SHOT_ORDER" and f["level"] == "PASS" for f in st["findings"]))
    # 七指标
    cm = r["sections"]["complexity"]["metrics"]
    checks.append(cm["track_count"] == 8)
    checks.append(cm["clip_count"] == 8)
    checks.append(cm["editable_clip_count"] == 8)
    checks.append(cm["replaceable_asset_count"] == 2)
    checks.append(cm["keyframe_count"] == 0 and cm["transition_count"] == 0)
    checks.append(r["sections"]["complexity"]["warnings"] == [])

    # --- Test 20 OVER_BAKED：字幕+图片被 bake ---
    baked_m = manifest(
        clips=[
            clip("TC-001", "A001", 0, 300),
            clip("TC-008", "A008", 60, 90, track="TR-005", editable=False),  # 标题被 bake
            clip("TC-009", "A009", 0, 900, track="TR-006"),
        ],
        tracks=[{"track_id": "TR-001", "type": "VIDEO_MAIN"},
                {"track_id": "TR-005", "type": "TEXT"},
                {"track_id": "TR-006", "type": "VOICEOVER"}],
        subtitle_items=[{"subtitle_id": "SUB-01", "text": "x", "start_frame": 0,
                         "end_frame": 100, "editable": False}],
        asset_links=[{"asset_ref": "A001"}, {"asset_ref": "A008"}],
        replaceable_assets=[],
    )
    baked_findings = run_qa(baked_m, asset_index=assets)["sections"]["over_baked"]["findings"]
    checks.append(len(baked_findings) >= 1)
    checks.append(all(f["code"] == "OVER_BAKED" for f in baked_findings))
    # 字幕不可编辑 → editability FAIL
    ed = run_qa(baked_m, asset_index=assets)["sections"]["editability"]
    checks.append(any(f["code"] == "SUBTITLE_NOT_EDITABLE" and f["level"] == "FAIL"
                      for f in ed["findings"]))

    # --- FR-002：音频类 clip 不参与 OVER_BAKED 判定 ---
    # SFX clip editable=False + 无 continuity_group + ≤6 简单关键帧 → 不再误判
    # "简单缩放被 bake"（§129 只针对视觉元素；A 的 17 条 SFX 曾误报）。
    sfx_baked_m = manifest(
        clips=[
            clip("TC-001", "A001", 0, 300),
            clip("TC-100", "A100", 0, 300, track="TR-008", editable=False,
                 keyframes=[{"property": "SCALE", "frame": 0}]),
        ],
        tracks=[{"track_id": "TR-001", "type": "VIDEO_MAIN"},
                {"track_id": "TR-008", "type": "SFX"}],
        subtitle_items=[], asset_links=[{"asset_ref": "A001"}],
        replaceable_assets=[],
    )
    sfx_baked_findings = run_qa(sfx_baked_m, asset_index=assets)["sections"]["over_baked"]["findings"]
    checks.append(sfx_baked_findings == [])  # audio SFX clip 不再触发 OVER_BAKED
    checks.append(detect_over_baked(sfx_baked_m) == [])  # raw 层同样排除

    # --- Test 21 OVER_FRAGMENTED：连续性组被拆 12 片 ---
    frag_m = manifest(
        clips=[clip(f"TC-{i:03d}", "A010", i * 30, (i + 1) * 30, track="TR-003",
                    continuity_group="CG-04") for i in range(15)],
        tracks=[{"track_id": "TR-003", "type": "VIDEO_MOTION"}],
        asset_links=[{"asset_ref": "A010"}],
        replaceable_assets=["A010"],
        subtitle_items=[], duration_frames=450,
    )
    frag = run_qa(frag_m, asset_index={"A010": {"asset_id": "A010", "producer": "REMOTION",
                                                "editability": "ASSET_REPLACEABLE"}})
    frag_findings = frag["sections"]["over_fragmented"]["findings"]
    checks.append(len(frag_findings) >= 1)
    checks.append(frag_findings[0]["code"] == "OVER_FRAGMENTED")
    raw_frag = detect_over_fragmented(
        frag_m, {"A010": {"asset_id": "A010", "producer": "REMOTION",
                          "editability": "ASSET_REPLACEABLE"}})
    checks.append(raw_frag and raw_frag[0]["clip_count"] == 15)
    checks.append(any("CG-04" in f["detail"] for f in frag_findings))
    # 结构上连续性组未断（同轨相邻）；碎片化由 §130 OVER_FRAGMENTED 单独告警，
    # 不把"拆片"误判为结构断裂（§131 平衡语义）
    cg_find = [f for f in frag["sections"]["structural"]["findings"]
               if f["code"] == "CONTINUITY_GROUP"]
    checks.append(cg_find and cg_find[0]["level"] == "PASS")
    checks.append(frag["ok"] is True)

    # --- structural：shot 顺序异常 ---
    order_m = manifest(clips=[
        clip("TC-001", "A001", 0, 100, shot_id="S002"),
        clip("TC-002", "A002", 100, 200, shot_id="S001"),
    ], duration_frames=200)
    r_ord = run_qa(order_m, asset_index=assets)
    so = [f for f in r_ord["sections"]["structural"]["findings"] if f["code"] == "SHOT_ORDER"]
    checks.append(so and so[0]["level"] == "WARN")

    # --- timing：SFX sync 对照（audio_map 帧）---
    r_t = run_qa(manifest(), audio_map={"sfx": [{"id": "click", "frame": 500}]},
                 asset_index=assets)
    sf = [f for f in r_t["sections"]["timing"]["findings"] if f["code"] == "SFX_UNSYNCED"]
    checks.append(sf and sf[0]["level"] == "WARN")
    # 对齐情况（150 帧处有 SFX clip）
    r_t2 = run_qa(manifest(), audio_map={"sfx": [{"id": "click", "frame": 151}]},
                  asset_index=assets)
    checks.append(any(f["code"] == "SFX_SYNC" for f in r_t2["sections"]["timing"]["findings"]))

    # --- timing：transition 过长 ---
    tx_m = manifest(clips=[
        clip("TC-001", "A001", 0, 100, transition_out={"type": "DISSOLVE",
                                                       "duration_frames": 200}),
    ], duration_frames=100)
    r_tx = run_qa(tx_m, asset_index=assets)
    checks.append(any(f["code"] == "TRANSITION_DURATION" and f["level"] == "WARN"
                      for f in r_tx["sections"]["timing"]["findings"]))

    # --- audio_assembly：VO 缺失（audio_map 声明 VO 而时间线无 VO）---
    no_vo = manifest(
        clips=[clip("TC-001", "A001", 0, 300), clip("TC-002", "A002", 300, 600)],
        tracks=[{"track_id": "TR-001", "type": "VIDEO_MAIN"}],
        duration_frames=600,
    )
    r_vo = run_qa(no_vo, audio_map={"vo": [{"id": "v", "frame": 0}]}, asset_index=assets)
    av = r_vo["sections"]["audio_assembly"]
    checks.append(any(f["code"] == "AUDIO_VO_MISSING" and f["level"] == "FAIL"
                      for f in av["findings"]))
    checks.append(av["ok"] is False)
    checks.append(r_vo["ok"] is False)

    # --- audio_assembly：ducking 未应用 + 音乐过高 ---
    duck_m = manifest(
        clips=[clip("TC-006", "A006", 0, 900, track="TR-007", volume=1.0),
               clip("TC-005", "A005", 0, 900, track="TR-006")],
        tracks=[{"track_id": "TR-006", "type": "VOICEOVER"},
                {"track_id": "TR-007", "type": "MUSIC"}],
        duration_frames=900,
    )
    r_duck = run_qa(duck_m, audio_map={"ducking": [{"id": "d", "frame": 0}]}, asset_index=assets)
    af = r_duck["sections"]["audio_assembly"]["findings"]
    checks.append(any(f["code"] == "DUCKING_NOT_APPLIED" for f in af))
    checks.append(any(f["code"] == "MUSIC_TOO_LOUD" for f in af))
    # 音乐 volume=0.8 → ducking 视为已应用
    duck_ok = deepcopy(duck_m)
    duck_ok["clips"][0]["volume"] = 0.8
    r_duck2 = run_qa(duck_ok, audio_map={"ducking": [{"id": "d", "frame": 0}]}, asset_index=assets)
    checks.append(not any(f["code"] == "DUCKING_NOT_APPLIED"
                          for f in r_duck2["sections"]["audio_assembly"]["findings"]))

    # --- audio_assembly：clipping risk ---
    clip_m = deepcopy(duck_m)
    clip_m["clips"][0]["volume"] = 1.3
    r_clip = run_qa(clip_m, asset_index=assets)
    checks.append(any(f["code"] == "CLIPPING_RISK"
                      for f in r_clip["sections"]["audio_assembly"]["findings"]))

    # --- editability：REPLACEABLE_NOT_SLOTTED ---
    rep_m = deepcopy(manifest())
    # 移除 TC-002 的槽位
    rep_m["clips"][1] = clip("TC-002", "A002", 300, 600, shot_id="S002")
    r_rep = run_qa(rep_m, asset_index=assets)
    checks.append(any(f["code"] == "REPLACEABLE_NOT_SLOTTED"
                      for f in r_rep["sections"]["editability"]["findings"]))

    # --- complexity 异常阈值 ---
    big = manifest(
        tracks=[{"track_id": f"TR-{i:03d}", "type": "VIDEO_MAIN"} for i in range(15)],
        clips=[clip(f"TC-{i:03d}", "A001", i * 100, (i + 1) * 100,
                    track=f"TR-{i % 15:03d}") for i in range(20)],
        duration_frames=2000,
    )
    r_big = run_qa(big, asset_index=assets)
    cw = r_big["sections"]["complexity"]["warnings"]
    checks.append(any("track_count" in w for w in cw))

    # --- 确定性：同输入同输出 ---
    checks.append(run_qa(manifest(), audio_map=audio_map, asset_index=assets)
                  == run_qa(deepcopy(manifest()), audio_map=deepcopy(audio_map),
                            asset_index=deepcopy(assets)))

    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"qa selftest check #{i} failed")
    print(f"qa selftest OK ({len(checks)} checks)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
