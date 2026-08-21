#!/usr/bin/env python3
"""modules/timeline-manager/validate.py — Timeline Validation（Phase-7 §109-118；P7-6）.

生成 Draft 前后对 Timeline Manifest 的确定性校验。主入口::

    validate_timeline(manifest, asset_index=None, storyboard=None,
                      intentional_gaps=None, check_files=False)
        -> {"ok": bool, "issues": [{"code", "level", "detail", ...}]}

12 项必校验（§109）+ 额外 4 项（§110-115），逐项可测：

    1. required assets exist（§109）
    2. clips inside timeline bounds（§109）
    3. no negative duration（§109）
    4. no illegal overlap（§112 主视频轨非 overlay 重叠）
    5. no missing media（§118 MISSING_MEDIA 标记，报错不崩）
    6. all asset links resolve（§109/§116-117）
    7. no invalid track mapping（§109）
    8. subtitle timing valid（§109）
    9. audio timing valid（§109）
    10. keyframe timing valid（§109）
    11. replacement slots valid（§109/§33-35，AS-### 存在）
    12. continuity group intact（§109/§8 复杂连续 Motion 不拆）
    额外：gap detection（§110 意外黑场 vs §111 intentional black——
          Test 14/15 语义）、subtitle collision（§113 subtitle+title+lower-third
          同区）、safe area（§114）、alpha 校验（§115 透明 overlay 后端格式
          保留，不支持则给转换建议且保留原资产）。

issue 结构：{code, level: "ERROR"|"WARNING", detail, clip_id?/track_id?/asset_id?}。
level=WARNING 不置 ``ok=False``（§163 语义：警告只提示不阻塞）。

全确定性：无 LLM、无联网、stdlib only；与 P7-2 schema 契约同枚举/ID。

CLI:
    python3 modules/timeline-manager/validate.py <manifest.json> [<asset_index.json>]
    python3 modules/timeline-manager/validate.py --selftest
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional

CLIP_ID_RE = re.compile(r"^TC-\d{3}$")
TRACK_ID_RE = re.compile(r"^TR-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")
SLOT_ID_RE = re.compile(r"^AS-\d{3}$")

#: 全屏轨道类型（同轨内非 overlay 重叠视为非法，§112）。
FULLSCREEN_TRACKS: frozenset = frozenset({
    "VIDEO_MAIN", "VIDEO_BROLL", "VIDEO_MOTION", "VIDEO_3D", "VIDEO_AI", "IMAGE",
})

#: 音频轨类型（timing 校验用，§109 audio timing valid）。
AUDIO_TRACK_TYPES: frozenset = frozenset({
    "VOICEOVER", "MUSIC", "SFX", "AMBIENCE",
})

#: 安全区边距（§114 safe area）：字幕/文字 position 必须在
#: x∈[0.05,0.95]、y∈[0.05,0.95] 内（归一化坐标），避免平台 UI 遮挡。
SAFE_AREA_X_MIN, SAFE_AREA_Y_MIN, SAFE_AREA_X_MAX, SAFE_AREA_Y_MAX = 0.05, 0.05, 0.95, 0.95

#: alpha 可保留通道的后端友好格式（§115）：其余格式建议转换，且保留原资产。
ALPHA_FORMATS: frozenset = frozenset({
    "mov", "webm", "png", "apng", "prores", "tiff", "exr",
})

#: alpha 资产允许放置的轨道类型（§80 transparent overlay → overlay track）。
ALPHA_OK_TRACKS: frozenset = frozenset({
    "VIDEO_OVERLAY", "GRAPHIC", "VIDEO_MOTION", "VIDEO_3D",
})

#: 连续性组语义关键词（storyboard note / marker 标注 intentional black 时
#: gap 不误报，§111 Test 15）。命中即视为"设计黑场"。
INTENTIONAL_BLACK_KEYWORDS: tuple = ("black", "fade", "故意", "黑场", "设计")


def _track_map(manifest: dict) -> dict:
    """{track_id: track dict}。"""
    out = {}
    for t in manifest.get("tracks") or []:
        if isinstance(t, dict) and t.get("track_id"):
            out[str(t["track_id"])] = t
    return out


def _clips(manifest: dict) -> list:
    """兼容新旧 clip 形状（无 clip_id 的旧形状仍参与按位置解析）。"""
    return [c for c in manifest.get("clips") or [] if isinstance(c, dict)]


def _frames_end(manifest: dict) -> int:
    """时间线总长（帧）：duration_frames > 0 用之，否则取全部 clip 最大 end。"""
    dur = manifest.get("duration_frames")
    if isinstance(dur, (int, float)) and dur > 0:
        return int(dur)
    mx = 0
    for c in _clips(manifest):
        e = c.get("timeline_end_frame")
        if isinstance(e, (int, float)):
            mx = max(mx, int(e))
    return mx


def _issue(code: str, level: str, detail: str, **ids) -> dict:
    return {"code": code, "level": level, "detail": detail, **ids}


def _overlaps(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def _region_of(item: dict, default: str) -> str:
    """区域判定（§113）：显式 region > position.y 三段 > 轨道默认。"""
    r = item.get("region")
    if isinstance(r, str) and r:
        return r
    pos = item.get("position")
    if isinstance(pos, dict) and isinstance(pos.get("y"), (int, float)):
        y = float(pos["y"])
        if y < 0.33:
            return "top"
        if y > 0.67:
            return "bottom"
        return "center"
    return default


def _textlike_items(manifest: dict, track_map: dict) -> list:
    """收集参与字幕碰撞/安全区检查的文本类条目。

    - manifest.subtitle_items（默认 bottom）
    - manifest.text_items（默认 top）
    - SUBTITLE / TEXT / GRAPHIC 轨 clip（默认按轨型）
    """
    items = []
    for s in manifest.get("subtitle_items") or []:
        if isinstance(s, dict):
            items.append((s, "bottom"))
    for t in manifest.get("text_items") or []:
        if isinstance(t, dict):
            items.append((t, "top"))
    for c in _clips(manifest):
        track = track_map.get(str(c.get("track_id") or ""), {})
        ty = track.get("type")
        if ty in ("SUBTITLE", "TEXT", "GRAPHIC"):
            default = {"SUBTITLE": "bottom", "TEXT": "top", "GRAPHIC": "center"}[ty]
            items.append((c, default))
        elif ty == "VIDEO_OVERLAY" and isinstance(c.get("position"), dict):
            # §113 lower-third/UI 图形：有 position 的 overlay 元素参与碰撞检测
            items.append((c, "center"))
    return items


def _region_bucket(item: dict, default: str) -> str:
    """带默认的 region 判定。"""
    return _region_of(item, default)


def _is_intentional_gap(start: int, end: int, manifest: dict,
                        storyboard: Any, intentional_gaps: Any) -> bool:
    """§111：判断 [start,end) 是否属于"设计黑场"（不误报 Test 15）。

    命中任一即 intentional：
    - intentional_gaps 参数中的 (start,end) / {start_frame,end_frame} 区间；
    - storyboard 中 note/label 含 black/fade/黑场 等关键词的 shot 区间；
    - manifest.markers 中 type/label 含关键词的标记区间。
    """
    def within(s0, s1):
        return s0 <= start and end <= s1

    if intentional_gaps is not None:
        for g in intentional_gaps:
            if isinstance(g, dict):
                gs, ge = g.get("start_frame"), g.get("end_frame")
            elif isinstance(g, (tuple, list)) and len(g) >= 2:
                gs, ge = g[0], g[1]
            else:
                continue
            if isinstance(gs, (int, float)) and isinstance(ge, (int, float)) \
                    and within(int(gs), int(ge)):
                return True

    if storyboard is not None:
        shots = storyboard.get("shots") if isinstance(storyboard, dict) else storyboard
        for s in shots or []:
            if not isinstance(s, dict):
                continue
            s0 = s.get("start_frame")
            if s0 is None and isinstance(s.get("start"), (int, float)):
                s0 = s.get("start")
            s1 = s.get("end_frame")
            if s1 is None and isinstance(s.get("end"), (int, float)):
                s1 = s.get("end")
            if not isinstance(s0, (int, float)) or not isinstance(s1, (int, float)):
                continue
            note = " ".join(str(s.get(k) or "") for k in
                            ("note", "label", "description", "action", "transition"))
            if within(int(s0), int(s1)) and any(
                    kw in note.lower() for kw in INTENTIONAL_BLACK_KEYWORDS):
                return True

    for m in manifest.get("markers") or []:
        if not isinstance(m, dict):
            continue
        if not isinstance(m.get("frame"), (int, float)):
            continue
        text = f"{m.get('type') or ''} {m.get('label') or ''}".lower()
        if within(int(m["frame"]), int(m["frame"]) + 1) and any(
                kw in text for kw in INTENTIONAL_BLACK_KEYWORDS):
            return True
    return False


# ---------------------------------------------------------------------------
# 12 项必校验 + 额外项
# ---------------------------------------------------------------------------

def _check_assets_exist(manifest: dict, asset_index: dict, issues: list,
                        check_files: bool) -> None:
    """1. required assets exist（§109）+ 5. missing media（§118）。

    - asset_id 不在 asset_index → ERROR ASSET_NOT_FOUND；
    - asset 显式标记 missing（"missing_media": true / status=failed）→
      ERROR MISSING_MEDIA；
    - check_files=True 且 asset.local_path 存在但文件不存在 → ERROR MISSING_MEDIA
      （Test 13 语义：Asset 不存在时 Validator 报错，不崩）。
    """
    for c in _clips(manifest):
        aid = str(c.get("asset_id") or "")
        if not aid:
            continue
        if asset_index is None or aid not in asset_index:
            issues.append(_issue("ASSET_NOT_FOUND", "ERROR",
                                 f"clip {c.get('clip_id')} 引用的 asset {aid} 不在 asset_index（§109）",
                                 clip_id=c.get("clip_id"), asset_id=aid))
            continue
        asset = asset_index[aid]
        if asset.get("missing_media") is True or asset.get("status") == "failed":
            issues.append(_issue("MISSING_MEDIA", "ERROR",
                                 f"asset {aid} 标记为缺失（MISSING_MEDIA，§118）",
                                 clip_id=c.get("clip_id"), asset_id=aid))
            continue
        if check_files and not asset.get("virtual") and asset.get("local_path"):
            if not os.path.isfile(str(asset["local_path"])):
                issues.append(_issue("MISSING_MEDIA", "ERROR",
                                     f"asset {aid} 本地文件不存在: {asset['local_path']}（§118）",
                                     clip_id=c.get("clip_id"), asset_id=aid))


def _check_bounds_and_duration(manifest: dict, issues: list) -> None:
    """2. clips in bounds + 3. no negative duration（§109）。"""
    total = _frames_end(manifest)
    for c in _clips(manifest):
        s, e = c.get("timeline_start_frame"), c.get("timeline_end_frame")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            issues.append(_issue("CLIP_TIMING_MISSING", "ERROR",
                                 f"clip {c.get('clip_id')} 缺 timeline_start/end_frame（§29）",
                                 clip_id=c.get("clip_id")))
            continue
        s, e = int(s), int(e)
        if e <= s:
            issues.append(_issue("NEGATIVE_DURATION", "ERROR",
                                 f"clip {c.get('clip_id')} 时长为负/零: {s}→{e}（§109）",
                                 clip_id=c.get("clip_id")))
        if s < 0 or e > total:
            issues.append(_issue("CLIP_OUT_OF_BOUNDS", "ERROR",
                                 f"clip {c.get('clip_id')} 超出时间线边界 [0,{total}]: {s}→{e}（§109）",
                                 clip_id=c.get("clip_id")))


def _check_overlap(manifest: dict, track_map: dict, issues: list) -> None:
    """4. no illegal overlap（§112 主视频轨非 overlay 重叠）。"""
    by_track: dict = {}
    for c in _clips(manifest):
        tid = str(c.get("track_id") or "")
        by_track.setdefault(tid, []).append(c)
    for tid in sorted(by_track):
        ty = track_map.get(tid, {}).get("type")
        if ty not in FULLSCREEN_TRACKS:
            continue  # overlay/text/subtitle/audio 轨的并置是设计（§112）
        clips = sorted(by_track[tid], key=lambda c: c["timeline_start_frame"])
        for i, a in enumerate(clips):
            for b in clips[i + 1:]:
                a0, a1 = a["timeline_start_frame"], a["timeline_end_frame"]
                b0, b1 = b["timeline_start_frame"], b["timeline_end_frame"]
                if _overlaps(a0, a1, b0, b1):
                    issues.append(_issue(
                        "ILLEGAL_OVERLAP", "ERROR",
                        f"全屏轨 {tid} 上 clip {a.get('clip_id')} 与 "
                        f"{b.get('clip_id')} 非法重叠（§112）",
                        clip_id=a.get("clip_id"), track_id=tid))


def _check_asset_links(manifest: dict, asset_index: Optional[dict], issues: list) -> None:
    """6. all asset links resolve（§109/§116-117）。"""
    for link in manifest.get("asset_links") or []:
        if not isinstance(link, dict):
            continue
        ref = (link.get("asset_ref") or link.get("asset_id") or link.get("asset"))
        if not ref:
            continue
        if asset_index is not None and str(ref) not in asset_index:
            issues.append(_issue("ASSET_LINK_UNRESOLVED", "ERROR",
                                 f"asset_link 引用 {ref} 未解析（§116 media relink）",
                                 asset_id=str(ref)))


def _check_track_mapping(manifest: dict, track_map: dict, issues: list) -> None:
    """7. no invalid track mapping（§109）。"""
    for c in _clips(manifest):
        tid = str(c.get("track_id") or "")
        if tid and tid not in track_map:
            issues.append(_issue("INVALID_TRACK", "ERROR",
                                 f"clip {c.get('clip_id')} 引用不存在的轨 {tid}（§109）",
                                 clip_id=c.get("clip_id"), track_id=tid))


def _check_subtitle_timing(manifest: dict, issues: list) -> None:
    """8. subtitle timing valid（§109）。"""
    total = _frames_end(manifest)
    for s in manifest.get("subtitle_items") or []:
        if not isinstance(s, dict):
            continue
        st, et = s.get("start_frame"), s.get("end_frame")
        if not isinstance(st, (int, float)) or not isinstance(et, (int, float)):
            issues.append(_issue("SUBTITLE_TIMING", "ERROR",
                                 f"字幕 {s.get('subtitle_id')} 缺 start/end_frame（§54）"))
            continue
        st, et = int(st), int(et)
        if et <= st:
            issues.append(_issue("SUBTITLE_TIMING", "ERROR",
                                 f"字幕 {s.get('subtitle_id')} 时长为负/零（§109）"))
        if st < 0 or et > total:
            issues.append(_issue("SUBTITLE_TIMING", "ERROR",
                                 f"字幕 {s.get('subtitle_id')} 超出边界（§109）"))


def _check_audio_timing(manifest: dict, track_map: dict, issues: list) -> None:
    """9. audio timing valid（§109）：音频轨 clip + 音频类数组条目。"""
    total = _frames_end(manifest)

    def check_span(aid, start, end):
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            issues.append(_issue("AUDIO_TIMING", "ERROR",
                                 f"音频项 {aid} 缺 start/end_frame（§109）"))
            return
        start, end = int(start), int(end)
        if end <= start:
            issues.append(_issue("AUDIO_TIMING", "ERROR",
                                 f"音频项 {aid} 时长为负/零（§109）"))
        if start < 0 or end > total:
            issues.append(_issue("AUDIO_TIMING", "ERROR",
                                 f"音频项 {aid} 超出边界（§109）"))

    for c in _clips(manifest):
        ty = track_map.get(str(c.get("track_id") or ""), {}).get("type")
        if ty in AUDIO_TRACK_TYPES:
            check_span(c.get("clip_id"), c.get("timeline_start_frame"),
                       c.get("timeline_end_frame"))
    for bucket in ("audio_tracks", "sfx_tracks", "music_tracks"):
        for a in manifest.get(bucket) or []:
            if isinstance(a, dict):
                check_span(a.get("audio_id") or a.get("id"),
                           a.get("start_frame"), a.get("end_frame"))


def _check_keyframe_timing(manifest: dict, issues: list) -> None:
    """10. keyframe timing valid（§109）：KF 帧必须落在 clip 范围内。"""
    for c in _clips(manifest):
        for kf in c.get("keyframes") or []:
            if not isinstance(kf, dict) or not isinstance(kf.get("frame"), (int, float)):
                continue
            f = int(kf["frame"])
            if not (c["timeline_start_frame"] <= f <= c["timeline_end_frame"]):
                issues.append(_issue("KEYFRAME_TIMING", "ERROR",
                                     f"clip {c.get('clip_id')} 关键帧 {kf.get('keyframe_id')} "
                                     f"frame={f} 超出 clip 范围（§109）",
                                     clip_id=c.get("clip_id")))


def _check_replacement_slots(manifest: dict, issues: list,
                             slot_index: Optional[dict] = None) -> None:
    """11. replacement slots valid（§109/§33-35）：AS-### 格式 + 槽位存在性。"""
    for c in _clips(manifest):
        slot = c.get("asset_slot_id")
        if slot is None:
            continue
        if not SLOT_ID_RE.match(str(slot)):
            issues.append(_issue("REPLACEMENT_SLOT_INVALID", "ERROR",
                                 f"clip {c.get('clip_id')} 的 asset_slot_id {slot} 非法，"
                                 f"格式 AS-###（§33-34）", clip_id=c.get("clip_id")))
        elif slot_index is not None and str(slot) not in slot_index:
            issues.append(_issue("REPLACEMENT_SLOT_INVALID", "ERROR",
                                 f"clip {c.get('clip_id')} 的 asset_slot_id {slot} 不存在于槽位表（§34）",
                                 clip_id=c.get("clip_id")))


def _check_continuity(manifest: dict, track_map: dict, issues: list) -> None:
    """12. continuity group intact（§109/§8）：同组 clip 同轨、连续、无插入。"""
    groups: dict = {}
    for c in _clips(manifest):
        g = c.get("continuity_group")
        if isinstance(g, str) and g:
            groups.setdefault(g, []).append(c)
    for g in sorted(groups):
        members = groups[g]
        tracks = {str(m.get("track_id") or "") for m in members}
        if len(tracks) > 1:
            issues.append(_issue("CONTINUITY_BROKEN", "ERROR",
                                 f"连续性组 {g} 的 clip 分布在多轨 {sorted(tracks)}，"
                                 f"必须整组同轨（§8）"))
            continue
        tid = members[0]["track_id"]
        ordered = sorted(members, key=lambda m: (m["timeline_start_frame"], m.get("clip_id")))
        others = [c for c in _clips(manifest)
                  if str(c.get("track_id") or "") == str(tid)
                  and str(c.get("clip_id") or "") not in {str(o.get("clip_id") or "") for o in members}]
        for a, b in zip(ordered, ordered[1:]):
            a0, a1 = a["timeline_start_frame"], a["timeline_end_frame"]
            b0 = b["timeline_start_frame"]
            # 组内间隙（非相邻）
            if b0 > a1:
                issues.append(_issue("CONTINUITY_BROKEN", "ERROR",
                                     f"连续性组 {g} 组内存在间隙 {a1}→{b0}（§8 不得拆开）",
                                     clip_id=b.get("clip_id"), track_id=tid))
            # 组间插入（foreign clip 落在组内相邻成员之间）
            for o in others:
                o0, o1 = o["timeline_start_frame"], o["timeline_end_frame"]
                if o0 >= a1 and o1 <= b0 and not (b0 <= a1):
                    issues.append(_issue("CONTINUITY_BROKEN", "ERROR",
                                         f"连续性组 {g} 组内被 clip {o.get('clip_id')} 插入，"
                                         f"破坏连续性（§8）", clip_id=o.get("clip_id"), track_id=tid))


# ---------------------------------------------------------------------------
# 额外校验（§110-115）
# ---------------------------------------------------------------------------

def _check_gaps(manifest: dict, track_map: dict, issues: list,
                storyboard: Any, intentional_gaps: Any) -> None:
    """额外：gap detection（§110 意外黑场 vs §111 intentional black，Test 14/15）。"""
    main_tracks = [tid for tid, t in track_map.items() if t.get("type") == "VIDEO_MAIN"]
    if not main_tracks:
        return
    total = _frames_end(manifest)
    covered = []
    for c in _clips(manifest):
        if str(c.get("track_id") or "") in main_tracks:
            covered.append((c["timeline_start_frame"], c["timeline_end_frame"]))
    covered.sort()
    cursor = 0
    for s, e in covered:
        if s > cursor:
            gap = (cursor, s)
            if not _is_intentional_gap(gap[0], gap[1], manifest, storyboard, intentional_gaps):
                issues.append(_issue("UNEXPECTED_GAP", "WARNING",
                                     f"主视频轨意外黑场 [{gap[0]},{gap[1]})（§110；"
                                     f"若为设计黑场请在 storyboard 标注 black/fade，§111）"))
        cursor = max(cursor, e)
    if cursor < total:
        gap = (cursor, total)
        if not _is_intentional_gap(gap[0], gap[1], manifest, storyboard, intentional_gaps):
            issues.append(_issue("UNEXPECTED_GAP", "WARNING",
                                 f"主视频轨尾部黑场 [{gap[0]},{gap[1]})（§110）"))


def _check_subtitle_collision(manifest: dict, track_map: dict, issues: list) -> None:
    """额外：subtitle collision（§113 subtitle+title+lower-third 同区）。"""
    items = _textlike_items(manifest, track_map)
    boxes = []
    for it, default in items:
        # clip 用 timeline_start_frame / timeline_end_frame，字幕/文字项用 start_frame
        st = it.get("start_frame")
        if st is None:
            st = it.get("timeline_start_frame")
        et = it.get("end_frame")
        if et is None:
            et = it.get("timeline_end_frame")
        if not isinstance(st, (int, float)) or not isinstance(et, (int, float)):
            continue
        boxes.append({"id": it.get("subtitle_id") or it.get("clip_id") or it.get("text_id")
                      or it.get("id") or it.get("text"),
                      "start": int(st), "end": int(et),
                      "region": _region_bucket(it, default)})
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a["region"] == b["region"] and _overlaps(a["start"], a["end"],
                                                        b["start"], b["end"]):
                issues.append(_issue(
                    "SUBTITLE_COLLISION", "WARNING",
                    f"文本项 {a['id']} 与 {b['id']} 同区({a['region']})且时间重叠（§113）"))


def _check_safe_area(manifest: dict, track_map: dict, issues: list) -> None:
    """额外：safe area validation（§114 subtitle/text 必须留在安全区内）。"""
    for it, _default in _textlike_items(manifest, track_map):
        pos = it.get("position")
        if not isinstance(pos, dict):
            continue
        x, y = pos.get("x"), pos.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            continue
        if not (SAFE_AREA_X_MIN <= x <= SAFE_AREA_X_MAX
                and SAFE_AREA_Y_MIN <= y <= SAFE_AREA_Y_MAX):
            issues.append(_issue(
                "SAFE_AREA_VIOLATION", "WARNING",
                f"文本项 {it.get('subtitle_id') or it.get('clip_id') or it.get('text')} "
                f"位置 ({x:.2f},{y:.2f}) 超出安全区 "
                f"[{SAFE_AREA_X_MIN},{SAFE_AREA_X_MAX}]×"
                f"[{SAFE_AREA_Y_MIN},{SAFE_AREA_Y_MAX}]（§114）"))


def _check_alpha(manifest: dict, track_map: dict, asset_index: Optional[dict],
                 issues: list) -> None:
    """额外：alpha asset validation（§115 透明 overlay 后端格式保留）。"""
    caps = manifest.get("backend_capabilities")
    alpha_cap = None
    if isinstance(caps, dict):
        for key in ("alpha", "transparent_overlay"):
            v = caps.get(key)
            if isinstance(v, dict):
                alpha_cap = v
                break

    for c in _clips(manifest):
        aid = str(c.get("asset_id") or "")
        asset = None
        if asset_index is not None:
            asset = asset_index.get(aid)
        alpha = bool(asset.get("alpha")) if isinstance(asset, dict) else None
        a_type = asset.get("type") if isinstance(asset, dict) else None
        if alpha is not True and a_type != "TRANSPARENT_OVERLAY":
            continue
        tid = str(c.get("track_id") or "")
        ty = track_map.get(tid, {}).get("type")
        if ty not in ALPHA_OK_TRACKS:
            issues.append(_issue("ALPHA_TRACK_MISMATCH", "WARNING",
                                 f"alpha 资产 {aid} 放在非 overlay 轨 {tid}({ty})，"
                                 f"透明度可能丢失（§80/§115）",
                                 clip_id=c.get("clip_id"), asset_id=aid))
        fmt = str((asset or {}).get("format") or "").lower()
        if alpha_cap is not None and alpha_cap.get("supported") is False:
            issues.append(_issue("ALPHA_UNSUPPORTED", "WARNING",
                                 f"后端不支持 alpha 资产 {aid}（{alpha_cap.get('fallback', '')}）；"
                                 f"建议转 mov(ProRes4444)/webm 后重新导入，保留原资产（§115）",
                                 clip_id=c.get("clip_id"), asset_id=aid))
        elif fmt and fmt not in ALPHA_FORMATS:
            issues.append(_issue("ALPHA_UNSUPPORTED", "WARNING",
                                 f"alpha 资产 {aid} 格式 {fmt} 非 alpha 友好；"
                                 f"建议转换 mov(ProRes4444)/webm 且保留原资产（§115）",
                                 clip_id=c.get("clip_id"), asset_id=aid))


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def validate_timeline(manifest: dict,
                      asset_index: Optional[dict] = None,
                      storyboard: Any = None,
                      intentional_gaps: Any = None,
                      slot_index: Optional[dict] = None,
                      check_files: bool = False) -> dict:
    """§109-118 全量校验。

    Args:
        manifest: Timeline Manifest（backend-neutral，§12）。
        asset_index: {asset_id: asset dict}（§109 required assets exist /
            MISSING_MEDIA / alpha / asset link 用；缺省 None=跳过存在性判定）。
        storyboard: 导演文档（§111 intentional black 判定；Test 15 语义）。
            可为 list[shot dict] 或 {"shots": [...]}，shot 含 start/end_frame
            （或 start/end）与 note/label 关键词。
        intentional_gaps: 设计黑场区间列表 [(start_frame, end_frame), ...] 或
            [{"start_frame","end_frame"}, ...]（§111 可替代 storyboard）。
        slot_index: {AS-###: 槽位元数据}（§34 槽位存在性；缺省仅校验格式）。
        check_files: True 时对 asset.local_path 做真实文件存在性检查（Test 13）。

    Returns::

        {"ok": bool,                    # 无 ERROR 级 issue
         "issues": [{"code", "level", "detail", ...}]}   # 确定性顺序
    """
    if not isinstance(manifest, dict):
        raise ValueError("manifest 必须是 dict")
    track_map = _track_map(manifest)
    issues: list = []

    _check_assets_exist(manifest, asset_index or {}, issues, check_files)
    _check_bounds_and_duration(manifest, issues)
    _check_overlap(manifest, track_map, issues)
    _check_asset_links(manifest, asset_index, issues)
    _check_track_mapping(manifest, track_map, issues)
    _check_subtitle_timing(manifest, issues)
    _check_audio_timing(manifest, track_map, issues)
    _check_keyframe_timing(manifest, issues)
    _check_replacement_slots(manifest, issues, slot_index)
    _check_continuity(manifest, track_map, issues)
    # 额外（§110-115）
    _check_gaps(manifest, track_map, issues, storyboard, intentional_gaps)
    _check_subtitle_collision(manifest, track_map, issues)
    _check_safe_area(manifest, track_map, issues)
    _check_alpha(manifest, track_map, asset_index, issues)

    ok = all(i["level"] != "ERROR" for i in issues)
    return {"ok": ok, "issues": issues}


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
        print("用法: python3 modules/timeline-manager/validate.py <manifest.json> "
              "[<asset_index.json>]", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        asset_index = None
        if len(args) > 1:
            asset_index = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    result = validate_timeline(manifest, asset_index, check_files=False)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    from copy import deepcopy  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415

    def clip(cid, asset, s, e, track="TR-001", **kw):
        return {"clip_id": cid, "track_id": track, "asset_id": asset,
                "timeline_start_frame": s, "timeline_end_frame": e, **kw}

    def base_manifest(**kw):
        m = {
            "timeline_id": "TL-001",
            "version": "timeline_v1",
            "tracks": [
                {"track_id": "TR-001", "type": "VIDEO_MAIN", "name": "V1_MAIN"},
                {"track_id": "TR-002", "type": "MUSIC", "name": "A2_MUSIC"},
                {"track_id": "TR-003", "type": "SUBTITLE", "name": "T2_SUBTITLES"},
                {"track_id": "TR-004", "type": "VIDEO_OVERLAY", "name": "V4_OVERLAY"},
            ],
            "clips": [
                clip("TC-001", "A001", 0, 100),
                clip("TC-002", "A001", 100, 200),
                clip("TC-006", "A001", 200, 300),
                clip("TC-003", "A002", 0, 300, track="TR-002"),
                clip("TC-004", "A003", 50, 150, track="TR-004"),
            ],
            "subtitle_items": [
                {"subtitle_id": "SUB-01", "text": "hi", "start_frame": 10, "end_frame": 60},
            ],
            "text_items": [], "audio_tracks": [], "sfx_tracks": [],
            "music_tracks": [], "overlays": [], "keyframes": [],
            "transitions": [], "asset_links": [],
            "replaceable_assets": [], "manual_edit_safe": True,
            "duration_frames": 300,
        }
        m.update(kw)
        return m

    assets = {
        "A001": {"asset_id": "A001", "local_path": "/proj/a001.mp4", "alpha": False,
                 "format": "mp4", "type": "FOOTAGE", "status": "completed"},
        "A002": {"asset_id": "A002", "local_path": "/proj/a002.mp3", "format": "mp3",
                 "type": "MUSIC", "status": "completed"},
        "A003": {"asset_id": "A003", "local_path": "/proj/a003.mov", "format": "mov",
                 "alpha": True, "type": "TRANSPARENT_OVERLAY", "status": "completed"},
    }
    checks = []

    # --- 干净时间线 → ok=True，无 issue ---
    r0 = validate_timeline(base_manifest(), assets)
    checks.append(r0["ok"] is True and r0["issues"] == [])

    # --- Test 13 MISSING_MEDIA：asset 显式 missing 标记 + 真实文件缺失 ---
    missing = deepcopy(assets)
    missing["A001"]["missing_media"] = True
    r1 = validate_timeline(base_manifest(), missing)
    codes1 = [i["code"] for i in r1["issues"]]
    checks.append(any(c == "MISSING_MEDIA" for c in codes1))
    checks.append(any(i["level"] == "ERROR" for i in r1["issues"]))
    checks.append(r1["ok"] is False)

    with tempfile.TemporaryDirectory() as td:
        real_file = _P(td) / "a001.mp4"
        real_file.write_bytes(b"x")  # 真实存在的文件
        fs_assets = {
            "A001": {**assets["A001"], "local_path": str(real_file), "missing_media": False},
            "A002": {**assets["A002"], "local_path": str(_P(td) / "missing.mp3"),
                     "missing_media": False},
            "A003": {**assets["A003"], "local_path": str(_P(td) / "a003.mov")},
        }
        r_fs = validate_timeline(base_manifest(), fs_assets, check_files=True)
        codes_fs = [i["code"] for i in r_fs["issues"]]
        # A002 的 mp3 文件不存在 → MISSING_MEDIA；A001 存在 → 无
        checks.append(any(c == "MISSING_MEDIA" for c in codes_fs))
        checks.append(any("a002.mp3" in i["detail"] or "missing.mp3" in i["detail"]
                          for i in r_fs["issues"]))

    # --- 12 项校验逐条可测（AC-1）---
    # 1 asset not found
    r2 = validate_timeline(base_manifest(), {})  # 空 asset_index → 全部 ASSET_NOT_FOUND
    checks.append(all(i["code"] == "ASSET_NOT_FOUND" for i in r2["issues"]))
    # 2/3 bounds + negative duration
    bad = base_manifest(clips=[clip("TC-001", "A001", 0, 500),
                               clip("TC-002", "A001", 50, 50)])
    r3 = validate_timeline(bad, assets)
    codes3 = [i["code"] for i in r3["issues"]]
    checks.append("CLIP_OUT_OF_BOUNDS" in codes3)
    checks.append("NEGATIVE_DURATION" in codes3)
    # 4 illegal overlap（主视频轨）
    ov = base_manifest(clips=[clip("TC-001", "A001", 0, 100),
                              clip("TC-002", "A001", 50, 150)])
    r4 = validate_timeline(ov, assets)
    checks.append(any(i["code"] == "ILLEGAL_OVERLAP" and i["level"] == "ERROR"
                      for i in r4["issues"]))
    # overlay 轨重叠不报（TR-004 上两个 overlay 是设计）
    ov2 = base_manifest(clips=[clip("TC-001", "A001", 0, 100),
                               clip("TC-004", "A003", 20, 80, track="TR-004"),
                               clip("TC-005", "A003", 60, 120, track="TR-004")])
    r4b = validate_timeline(ov2, assets)
    checks.append(not any(i["code"] == "ILLEGAL_OVERLAP" for i in r4b["issues"]))
    # 6 asset link unresolvable
    link_bad = base_manifest(asset_links=[{"asset_ref": "A999"}])
    r6 = validate_timeline(link_bad, assets)
    checks.append(any(i["code"] == "ASSET_LINK_UNRESOLVED" for i in r6["issues"]))
    # 7 invalid track
    tr = base_manifest(clips=[clip("TC-001", "A001", 0, 100, track="TR-999")])
    r7 = validate_timeline(tr, assets)
    checks.append(any(i["code"] == "INVALID_TRACK" for i in r7["issues"]))
    # 8 subtitle timing
    st = base_manifest(subtitle_items=[
        {"subtitle_id": "SUB-01", "text": "hi", "start_frame": 10, "end_frame": 5}])
    r8 = validate_timeline(st, assets)
    checks.append(any(i["code"] == "SUBTITLE_TIMING" for i in r8["issues"]))
    # 9 audio timing
    at = base_manifest(clips=[clip("TC-001", "A001", 0, 100),
                              clip("TC-003", "A002", 400, 500, track="TR-002")])
    r9 = validate_timeline(at, assets)
    checks.append(any(i["code"] == "AUDIO_TIMING" for i in r9["issues"]))
    # 10 keyframe timing
    kt = base_manifest(clips=[clip("TC-001", "A001", 0, 100,
                                   keyframes=[{"keyframe_id": "KF-001",
                                               "frame": 200, "property": "SCALE",
                                               "value": 1.2}])])
    r10 = validate_timeline(kt, assets)
    checks.append(any(i["code"] == "KEYFRAME_TIMING" for i in r10["issues"]))
    # 11 replacement slot invalid（格式 + 槽位表缺失）
    rp = base_manifest(clips=[clip("TC-001", "A001", 0, 100, asset_slot_id="AS-001"),
                              clip("TC-002", "A001", 100, 200, asset_slot_id="BROKEN")])
    r11 = validate_timeline(rp, assets)
    checks.append(any(i["code"] == "REPLACEMENT_SLOT_INVALID" for i in r11["issues"]))
    r11b = validate_timeline(rp, assets, slot_index={"AS-001": {}})
    # AS-001 合法存在；BROKEN 仍非法
    checks.append(any(i["code"] == "REPLACEMENT_SLOT_INVALID" and "BROKEN" in i["detail"]
                      for i in r11b["issues"]))
    # 12 continuity broken（组内间隙）
    cg = base_manifest(clips=[
        clip("TC-001", "A001", 0, 100, continuity_group="CG-04"),
        clip("TC-002", "A001", 150, 250, continuity_group="CG-04"),
    ])
    r12 = validate_timeline(cg, assets)
    checks.append(any(i["code"] == "CONTINUITY_BROKEN" for i in r12["issues"]))
    # 组内连续 → 不报
    cg_ok = base_manifest(clips=[
        clip("TC-001", "A001", 0, 100, continuity_group="CG-04"),
        clip("TC-002", "A001", 100, 200, continuity_group="CG-04"),
    ])
    r12b = validate_timeline(cg_ok, assets)
    checks.append(not any(i["code"] == "CONTINUITY_BROKEN" for i in r12b["issues"]))

    # --- Test 14/15 gap vs intentional black ---
    gap_manifest = base_manifest(duration_frames=300, clips=[
        clip("TC-001", "A001", 0, 100),
        clip("TC-002", "A001", 150, 300),  # 100-150 黑场
    ])
    r14 = validate_timeline(gap_manifest, assets)
    codes14 = [i["code"] for i in r14["issues"]]
    checks.append("UNEXPECTED_GAP" in codes14)
    # Test 15：storyboard 标注 fade to black → 不误报
    storyboard = {"shots": [{"id": "S001", "start_frame": 90, "end_frame": 160,
                             "note": "fade to black"}]}
    r15 = validate_timeline(gap_manifest, assets, storyboard=storyboard)
    checks.append(not any(i["code"] == "UNEXPECTED_GAP" for i in r15["issues"]))
    # intentional_gaps 参数形式
    r15b = validate_timeline(gap_manifest, assets, intentional_gaps=[(100, 150)])
    checks.append(not any(i["code"] == "UNEXPECTED_GAP" for i in r15b["issues"]))
    # 部分覆盖 → 仍报未标注的部分
    r15c = validate_timeline(gap_manifest, assets, intentional_gaps=[(100, 130)])
    checks.append(any(i["code"] == "UNEXPECTED_GAP" for i in r15c["issues"]))

    # --- Test 16 subtitle collision（§113）+ safe area（§114）---
    col = base_manifest(
        subtitle_items=[
            {"subtitle_id": "SUB-01", "text": "bottom", "start_frame": 0,
             "end_frame": 100, "position": {"x": 0.5, "y": 0.85}},
        ],
        clips=[clip("TC-001", "A001", 0, 100),
               clip("TC-005", "A003", 10, 90, track="TR-004",
                    position={"x": 0.5, "y": 0.85})],
    )
    r16 = validate_timeline(col, assets)
    checks.append(any(i["code"] == "SUBTITLE_COLLISION" for i in r16["issues"]))
    # 不同区 → 不碰撞
    col_ok = base_manifest(
        subtitle_items=[
            {"subtitle_id": "SUB-01", "text": "bottom", "start_frame": 0,
             "end_frame": 100, "position": {"x": 0.5, "y": 0.85}},
        ],
        clips=[clip("TC-005", "A003", 10, 90, track="TR-004",
                    position={"x": 0.5, "y": 0.15})],
    )
    r16b = validate_timeline(col_ok, assets)
    checks.append(not any(i["code"] == "SUBTITLE_COLLISION" for i in r16b["issues"]))
    # safe area violation
    sa = base_manifest(subtitle_items=[
        {"subtitle_id": "SUB-01", "text": "x", "start_frame": 0, "end_frame": 10,
         "position": {"x": 0.02, "y": 0.99}}])
    r_sa = validate_timeline(sa, assets)
    checks.append(any(i["code"] == "SAFE_AREA_VIOLATION" for i in r_sa["issues"]))

    # --- alpha 校验（§115）：overlay 轨 + mov → 通过；非 overlay 轨 → 警告 ---
    # A003 是 alpha mov；放 TR-004 overlay → 无 alpha issue
    r_al = validate_timeline(base_manifest(), assets)
    checks.append(not any(i["code"].startswith("ALPHA") for i in r_al["issues"]))
    # alpha asset 放主视频轨 → ALPHA_TRACK_MISMATCH
    alpha_wrong = base_manifest(clips=[
        clip("TC-001", "A001", 0, 100),
        clip("TC-004", "A003", 0, 50, track="TR-001"),  # 主轨放 alpha
    ])
    r_al2 = validate_timeline(alpha_wrong, assets)
    checks.append(any(i["code"] == "ALPHA_TRACK_MISMATCH" for i in r_al2["issues"]))
    # alpha asset 格式不支持 → 转换建议且保留原资产
    alpha_fmt = deepcopy(assets)
    alpha_fmt["A003"]["format"] = "mp4"
    alpha_fmt["A003"]["alpha"] = True
    alpha_fmt["A003"]["type"] = "TRANSPARENT_OVERLAY"
    r_al3 = validate_timeline(base_manifest(), alpha_fmt)
    al_issues = [i for i in r_al3["issues"] if i["code"] == "ALPHA_UNSUPPORTED"]
    checks.append(any("保留原资产" in i["detail"] for i in al_issues))

    # --- 确定性：同输入同输出 ---
    checks.append(validate_timeline(base_manifest(), assets)
                  == validate_timeline(deepcopy(base_manifest()), deepcopy(assets)))

    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"validate selftest check #{i} failed")
    print(f"validate selftest OK ({len(checks)} checks)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
