#!/usr/bin/env python3
"""modules/timeline-manager/patch.py — TIMELINE_PATCH 补丁系统（Phase-7 §98-108；P7-6）.

AI 修改已有 Timeline 而不重建整个 Draft 的操作集合（§102 Patch Instead of Rebuild）。
本模块提供四个确定性子功能：

1. ``build_patch(ops, base_timeline, target_timeline, ...)``
   —— 构建 schema-valid 的 TP-### 补丁清单（timeline-patch.schema.json），
      九操作（§103：replace_asset/shift_clip/resize_clip/change_text/
      change_subtitle/change_audio/add_clip/remove_clip/change_transition）。
2. ``timeline_diff(before, after)``
   —— §105 摘要五类 + 明细（clips_changed / assets_replaced /
      subtitles_modified / music_changed / ...），Test 23 语义：只改一字幕
      时 diff 只含该字幕，不重建整条时间线。
3. ``patch_safety(timeline_state, patch, ...)``
   —— §104/§106 安全闸：HUMAN_EDITED 草稿 + 高风险 op → requires_approval=true
      并先出 diff；owner=HUMAN 的 clip 被 AI patch 触碰一律需批准（§108）；
      三级锁定（shot/track/clip，§107）触碰到 → allowed=false；
      GENERATED_BASELINE 低风险 op 直接 allowed。
4. ``ownership_transition(state, event)``
   —— §99-102 draft ownership 状态机（GENERATED_BASELINE→HUMAN_EDITED→
      AI_PATCHABLE/LOCKED 迁移规则写死并测）。

设计铁律：
- §106 硬规则：人类编辑优先，除非用户明确要求替换（explicit_user_request）。
- §102 补丁不重建：只允许九操作，禁止"重建整个 Timeline"语义。
- 全确定性：无 LLM、无联网、stdlib only；按 clip_id 排序，不依赖 dict 顺序。

CLI:
    python3 modules/timeline-manager/patch.py --selftest
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from typing import Any, Optional

CLIP_ID_RE = re.compile(r"^TC-\d{3}$")
TRACK_ID_RE = re.compile(r"^TR-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")
PATCH_ID_RE = re.compile(r"^TP-\d{3}$")

# ---------------------------------------------------------------------------
# §103 九操作 + 风险分级
# ---------------------------------------------------------------------------

#: 补丁九操作（§103，枚举与 timeline-patch.schema.json ops[].op 一致）
PATCH_OPS: tuple = (
    "replace_asset",
    "shift_clip",
    "resize_clip",
    "change_text",
    "change_subtitle",
    "change_audio",
    "add_clip",
    "remove_clip",
    "change_transition",
)

#: 高风险 op（结构/破坏性，可能覆盖用户劳动）：§104 中 HUMAN_EDITED 草稿
#: 上执行此类 op 必须先出 diff + 审批；§106 不覆盖用户劳动。
HIGH_RISK_OPS: frozenset = frozenset({
    "replace_asset",      # 换素材（结构变更）
    "shift_clip",         # 移动片段（影响全轨时序）
    "resize_clip",        # 改片段时长（可能截断内容）
    "add_clip",           # 插入片段（推挤既有片段）
    "remove_clip",        # 删除片段（不可逆）
    "change_transition",  # 改转场（编辑意图）
})

#: 低风险 op（内容级微调，容易撤销）：GENERATED_BASELINE 上直接 allowed。
LOW_RISK_OPS: frozenset = frozenset({
    "change_text",        # 改文字内容
    "change_subtitle",    # 改字幕内容
    "change_audio",       # 改音量/淡入淡出
})

# ---------------------------------------------------------------------------
# §99 draft ownership 状态机
# ---------------------------------------------------------------------------

#: draft ownership 四枚举（§99）
OWNERSHIP_STATES: tuple = ("GENERATED_BASELINE", "HUMAN_EDITED", "AI_PATCHABLE", "LOCKED")

#: 状态机事件与合法迁移表（§99-102，规则写死并测）：
#:   GENERATED_BASELINE --MANUAL_EDIT--> HUMAN_EDITED        §101 用户手工修改
#:   GENERATED_BASELINE --LOCK----------> LOCKED             §107 用户锁定
#:   GENERATED_BASELINE --PATCH_APPROVED> AI_PATCHABLE       用户批准 AI 补丁
#:   HUMAN_EDITED      --PATCH_APPROVED> AI_PATCHABLE        §104 审批通过后可补丁
#:   HUMAN_EDITED      --LOCK----------> LOCKED              §107
#:   AI_PATCHABLE      --MANUAL_EDIT---> HUMAN_EDITED        §101 用户又手工改
#:   AI_PATCHABLE      --LOCK----------> LOCKED              §107
#:   LOCKED            --UNLOCK--------> AI_PATCHABLE        §107 解锁允许 AI 补丁
#: 其余迁移非法（如 LOCKED 状态下直接 MANUAL_EDIT 需先 UNLOCK）。
OWNERSHIP_TRANSITIONS: dict = {
    "GENERATED_BASELINE": {"MANUAL_EDIT": "HUMAN_EDITED", "LOCK": "LOCKED",
                           "PATCH_APPROVED": "AI_PATCHABLE"},
    "HUMAN_EDITED": {"PATCH_APPROVED": "AI_PATCHABLE", "LOCK": "LOCKED",
                     "MANUAL_EDIT": "HUMAN_EDITED"},  # 幂等：再次手工编辑
    "AI_PATCHABLE": {"MANUAL_EDIT": "HUMAN_EDITED", "LOCK": "LOCKED",
                     "PATCH_APPROVED": "AI_PATCHABLE"},  # 幂等
    "LOCKED": {"UNLOCK": "AI_PATCHABLE"},
}


def now_iso() -> str:
    """UTC 时间戳（ISO 8601，秒精度；与 modules/external-visual/handoff.py 同款）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _clips_by_id(timeline: dict) -> dict:
    """从 timeline 提取 {clip_id: clip}（兼容旧形状：无 clip_id 的跳过）。"""
    out: dict = {}
    for c in timeline.get("clips") or []:
        if isinstance(c, dict) and c.get("clip_id"):
            out[str(c["clip_id"])] = c
    return out


def _track_type_map(timeline: dict) -> dict:
    """从 timeline 提取 {track_id: track_type}。"""
    out: dict = {}
    for t in timeline.get("tracks") or []:
        if isinstance(t, dict) and t.get("track_id"):
            out[str(t["track_id"])] = t.get("type")
    return out


def _clip_is_audio(track_type: Any) -> bool:
    return str(track_type or "") in ("VOICEOVER", "MUSIC", "SFX", "AMBIENCE")


# ---------------------------------------------------------------------------
# ops 归一化/校验（§103 九枚举）
# ---------------------------------------------------------------------------

def normalize_ops(ops: Any) -> list:
    """校验并归一 ops 列表（每项 {op, target, payload?, requires_approval?}）。

    - op 必须是 §103 九枚举之一；
    - target 必须是非空字符串；
    - payload 必须是 dict（可选）；
    - requires_approval 必须是 bool（可选）。

    非法输入抛 ValueError（确定性校验，不静默过滤）。排序保持调用方顺序。
    """
    if not isinstance(ops, list) or not ops:
        raise ValueError(f"ops 必须是非空 list，got {type(ops).__name__}")
    out = []
    for i, op in enumerate(ops, 1):
        if not isinstance(op, dict):
            raise ValueError(f"ops[{i}] 不是 dict: {op!r}")
        name = op.get("op")
        if name not in PATCH_OPS:
            raise ValueError(
                f"ops[{i}] 非法 op={name!r}；九枚举: {', '.join(PATCH_OPS)}（§103）")
        target = op.get("target")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"ops[{i}] ({name}) target 必须是非空字符串")
        payload = op.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError(f"ops[{i}] ({name}) payload 必须是 dict")
        ra = op.get("requires_approval")
        if ra is not None and not isinstance(ra, bool):
            raise ValueError(f"ops[{i}] ({name}) requires_approval 必须是 bool")
        out.append({
            "op": name,
            "target": target.strip(),
            **({"payload": payload} if payload else {}),
            **({"requires_approval": ra} if ra is not None else {}),
        })
    return out


# ---------------------------------------------------------------------------
# §105 timeline_diff
# ---------------------------------------------------------------------------

def _subtitle_items(timeline: dict) -> list:
    """归一化字幕项列表（manifest.subtitle_items + SUBTITLE 轨 clip 映射）。"""
    items = [s for s in timeline.get("subtitle_items") or [] if isinstance(s, dict)]
    sub_track_ids = {tid for tid, ty in _track_type_map(timeline).items() if ty == "SUBTITLE"}
    for c in timeline.get("clips") or []:
        if isinstance(c, dict) and c.get("track_id") in sub_track_ids:
            items.append(c)
    return items


def _diff_subtitles(before: list, after: list) -> tuple:
    """对比字幕列表，返回 (modified_count, 修改的 id 列表)。

    Test 23 语义：只改一个字幕 → diff 只含该字幕。按 (subtitle_id, text,
    start_frame, end_frame) 比对；无 id 时退化为按 (text, start, end) 元组匹配。
    """
    def key(s):
        sid = s.get("subtitle_id") or s.get("clip_id") or s.get("text")
        return str(sid)
    bmap = {}
    for i, s in enumerate(before):
        bmap.setdefault(key(s), []).append(s)
    modified = []
    seen = set()
    for s in after:
        k = key(s)
        bucket = bmap.get(k, [])
        if not bucket:
            # 新增字幕，不算"修改"
            continue
        # 取未消费的 before 条目做逐字段比对
        match = None
        for b in bucket:
            if id(b) in seen:
                continue
            match = b
            break
        if match is None:
            continue
        seen.add(id(match))
        bv = (match.get("text"), match.get("start_frame"), match.get("end_frame"))
        av = (s.get("text"), s.get("start_frame"), s.get("end_frame"))
        if bv != av:
            modified.append(str(s.get("subtitle_id") or s.get("clip_id") or s.get("text")))
    return len(modified), sorted(set(modified))


def timeline_diff(before: dict, after: dict) -> dict:
    """§105 Timeline Diff：对比 before/after 时间线，输出五类摘要 + 明细。

    返回值::

        {
          "clips_changed": int,           # 公共 clip 中被修改的数量
          "clips_added": int, "clips_removed": int,
          "assets_replaced": int,         # asset_id 变更的 clip 数
          "assets_replaced_list": [A###],
          "subtitles_modified": int, "subtitle_ids_modified": [id...],
          "texts_changed": int,           # 文字项内容变更数
          "music_changed": bool,          # MUSIC 轨是否有任何变更
          "audio_changed": bool,          # VO/SFX/AMBIENCE 轨是否有任何变更
          "transitions_changed": int,     # transition_in/out 变更的 clip 数
          "keyframes_changed": int,       # keyframes 变更的 clip 数
          "changes": [{clip_id, field, before, after}...],  # 明细
          "summary": "3 clips changed, 1 asset replaced, ...",
        }

    确定性：clip_id/字幕 id 排序；字段按字母序比对。
    """
    b_clips = _clips_by_id(before)
    a_clips = _clips_by_id(after)
    b_types = _track_type_map(before)
    a_types = _track_type_map(after)

    added = sorted(set(a_clips) - set(b_clips))
    removed = sorted(set(b_clips) - set(a_clips))
    common = sorted(set(a_clips) & set(b_clips))

    changes: list = []
    clips_changed = 0
    assets_replaced: list = []
    transitions_changed = 0
    keyframes_changed = 0
    music_changed = False
    audio_changed = False

    for cid in common:
        bc, ac = b_clips[cid], a_clips[cid]
        touched_fields = []
        for field in sorted(set(bc) | set(ac)):
            if bc.get(field) != ac.get(field):
                changes.append({"clip_id": cid, "field": field,
                                "before": bc.get(field), "after": ac.get(field)})
                touched_fields.append(field)
        if not touched_fields:
            continue
        clips_changed += 1
        if "asset_id" in touched_fields and str(ac.get("asset_id") or "") != "":
            assets_replaced.append(str(ac["asset_id"]))
        if "transition_in" in touched_fields or "transition_out" in touched_fields:
            transitions_changed += 1
        if "keyframes" in touched_fields:
            keyframes_changed += 1
        # 音频轨变更追踪：track 类型以 before 为准，before 无 track 时用 after
        ty = b_types.get(bc.get("track_id")) or a_types.get(ac.get("track_id"))
        if _clip_is_audio(ty):
            audio_changed = True
            if ty == "MUSIC":
                music_changed = True

    # 增删的 clip 归属到音频轨也算 audio/music 变更
    for cid in added:
        ty = a_types.get(a_clips[cid].get("track_id"))
        if _clip_is_audio(ty):
            audio_changed = True
            if ty == "MUSIC":
                music_changed = True
    for cid in removed:
        ty = b_types.get(b_clips[cid].get("track_id"))
        if _clip_is_audio(ty):
            audio_changed = True
            if ty == "MUSIC":
                music_changed = True

    # 字幕/文字
    sub_modified, sub_ids = _diff_subtitles(_subtitle_items(before), _subtitle_items(after))
    texts_changed = 0
    b_text = {str(t.get("text_id") or t.get("id") or t.get("text")): t
              for t in (before.get("text_items") or []) if isinstance(t, dict)}
    a_text = {str(t.get("text_id") or t.get("id") or t.get("text")): t
              for t in (after.get("text_items") or []) if isinstance(t, dict)}
    for k in sorted(set(b_text) | set(a_text)):
        if b_text.get(k) != a_text.get(k):
            texts_changed += 1

    assets_replaced_list = sorted(set(assets_replaced))
    # §105 摘要（"3 clips changed, 1 asset replaced, 2 subtitles modified, music unchanged"）
    parts = [f"{clips_changed} clip{'s' if clips_changed != 1 else ''} changed"]
    if assets_replaced_list:
        parts.append(f"{len(assets_replaced_list)} asset{'s' if len(assets_replaced_list) != 1 else ''} replaced")
    parts.append(f"{sub_modified} subtitle{'s' if sub_modified != 1 else ''} modified")
    if texts_changed:
        parts.append(f"{texts_changed} text{'s' if texts_changed != 1 else ''} changed")
    if audio_changed:
        parts.append("audio changed")
    parts.append("music changed" if music_changed else "music unchanged")
    if transitions_changed:
        parts.append(f"{transitions_changed} transition{'s' if transitions_changed != 1 else ''} changed")
    if keyframes_changed:
        parts.append(f"{keyframes_changed} keyframe clip{'s' if keyframes_changed != 1 else ''} changed")
    if added:
        parts.append(f"{len(added)} clip{'s' if len(added) != 1 else ''} added")
    if removed:
        parts.append(f"{len(removed)} clip{'s' if len(removed) != 1 else ''} removed")

    return {
        "clips_changed": clips_changed,
        "clips_added": len(added),
        "clips_removed": len(removed),
        "assets_replaced": len(assets_replaced_list),
        "assets_replaced_list": assets_replaced_list,
        "subtitles_modified": sub_modified,
        "subtitle_ids_modified": sub_ids,
        "texts_changed": texts_changed,
        "music_changed": music_changed,
        "audio_changed": audio_changed,
        "transitions_changed": transitions_changed,
        "keyframes_changed": keyframes_changed,
        "changes": changes,
        "summary": ", ".join(parts),
    }


# ---------------------------------------------------------------------------
# §104/§106/§107/§108 patch_safety
# ---------------------------------------------------------------------------

def _collect_locked(timeline: dict) -> tuple:
    """收集三级锁定（§107）+ 轨道/片段锁定标记。

    返回 (clip_locked_ids:set, track_locked_ids:set, shot_locked_ids:set)。
    - timeline.locked_regions[].{target_type: shot|track|clip, target_id}
    - tracks[].locked == True → track 锁定
    - clips[].locked == True → clip 锁定
    """
    clip_locked: set = set()
    track_locked: set = set()
    shot_locked: set = set()
    for reg in timeline.get("locked_regions") or []:
        if not isinstance(reg, dict):
            continue
        tt = reg.get("target_type")
        tid = str(reg.get("target_id") or "")
        if not tid:
            continue
        if tt == "clip":
            clip_locked.add(tid)
        elif tt == "track":
            track_locked.add(tid)
        elif tt == "shot":
            shot_locked.add(tid)
    for t in timeline.get("tracks") or []:
        if isinstance(t, dict) and t.get("locked") is True and t.get("track_id"):
            track_locked.add(str(t["track_id"]))
    for c in timeline.get("clips") or []:
        if isinstance(c, dict) and c.get("locked") is True and c.get("clip_id"):
            clip_locked.add(str(c["clip_id"]))
    return clip_locked, track_locked, shot_locked


def _target_clips(op: dict, timeline: dict) -> list:
    """解析 op 命中的 clip 列表（safety 评估用）。

    - target 是 clip TC-### → 该 clip；
    - target 是 asset A### 且 op=replace_asset → 所有使用该 asset 的 clip；
    - target 是 track TR-### → 该轨全部 clip；
    - 其余（text/subtitle 等，无 owner 元数据）→ []。
    """
    target = str(op.get("target") or "")
    clips = _clips_by_id(timeline)
    if CLIP_ID_RE.match(target):
        return [clips[target]] if target in clips else []
    if ASSET_ID_RE.match(target):
        return [c for cid, c in sorted(clips.items()) if str(c.get("asset_id") or "") == target]
    if TRACK_ID_RE.match(target):
        return [c for cid, c in sorted(clips.items()) if str(c.get("track_id") or "") == target]
    return []


def patch_safety(timeline_state: dict, patch: dict,
                 explicit_user_request: bool = False) -> dict:
    """§104/§106 补丁安全闸。

    Args:
        timeline_state: 当前时间线 manifest（读 ownership/locked_regions/
            tracks/clips/owner/locked）。
        patch: TP-### 补丁 dict（读 ops / diff_summary）。
        explicit_user_request: §106 例外——用户明确要求替换时，锁定项
            allowed 放宽为 True（但仍要求审批标记，尊重 HUMAN 所有权）。

    Returns::

        {
          "allowed": bool,             # False=不可应用（触碰锁定项/草稿 LOCKED）
          "requires_approval": bool,   # True=必须先出 diff 并获审批（§104）
          "diff_summary": str,         # 先出 diff（§105 摘要）
          "reasons": [str],            # 触发审批/禁止的原因（可追溯）
        }

    判定规则（写死，见函数 docstring 与各 §）：
    - owner=HUMAN 的 clip 被 AI patch 触碰 → requires_approval=true（§108）；
    - HUMAN_EDITED 草稿 + 高风险 op → requires_approval=true（§104，先出 diff）；
    - GENERATED_BASELINE + 低风险 op → allowed=true 且无需审批；
    - 三级锁定（§107）或草稿 ownership=LOCKED 被触碰 → allowed=false
      （除非 explicit_user_request=True，§106 用户明确要求替换）。
    """
    ownership = timeline_state.get("ownership") or "GENERATED_BASELINE"
    if ownership not in OWNERSHIP_STATES:
        raise ValueError(f"非法 ownership={ownership!r}；四枚举: {OWNERSHIP_STATES}（§99）")

    ops = patch.get("ops") or []
    ops = normalize_ops(ops) if ops else ops  # 与 build_patch 同样的校验
    clip_locked, track_locked, shot_locked = _collect_locked(timeline_state)

    requires_approval = False
    touches_locked = False
    reasons: list = []

    for op in ops:
        name = op["op"]
        tclips = _target_clips(op, timeline_state)
        for clip in tclips:
            cid = str(clip.get("clip_id") or "")
            if clip.get("owner") == "HUMAN":
                requires_approval = True
                reasons.append(f"{name} 触碰 HUMAN 拥有项 {cid}（§108 AI patch 对 HUMAN 项一律需批准）")
            locked = (clip.get("locked") is True
                      or cid in clip_locked
                      or str(clip.get("track_id") or "") in track_locked
                      or str(clip.get("shot_id") or "") in shot_locked)
            if locked:
                touches_locked = True
                reasons.append(f"{name} 触碰锁定项 {cid}（§107 AI 不得修改）")
        if name in HIGH_RISK_OPS and ownership == "HUMAN_EDITED":
            requires_approval = True
            reasons.append(f"{name} 为高风险 op 且草稿 HUMAN_EDITED（§104 先 diff 后审批）")
    if ownership == "LOCKED":
        touches_locked = True
        reasons.append("草稿 ownership=LOCKED（§107 整体锁定）")

    allowed = not touches_locked or bool(explicit_user_request)
    diff_summary = patch.get("diff_summary")
    if not isinstance(diff_summary, str) or not diff_summary:
        # 无显式 diff_summary 时按 op 统计给出粗略摘要（完整 diff 由调用方用 timeline_diff）
        counts: dict = {}
        for op in ops:
            counts[op["op"]] = counts.get(op["op"], 0) + 1
        diff_summary = ", ".join(f"{n}×{name}" for name, n in sorted(counts.items()))

    return {
        "allowed": allowed,
        "requires_approval": requires_approval,
        "diff_summary": diff_summary,
        "reasons": sorted(set(reasons)),
    }


# ---------------------------------------------------------------------------
# §99-102 ownership 状态机
# ---------------------------------------------------------------------------

def ownership_transition(state: str, event: str) -> str:
    """draft ownership 状态迁移（§99-102）。

    Args:
        state: GENERATED_BASELINE / HUMAN_EDITED / AI_PATCHABLE / LOCKED
        event: MANUAL_EDIT（§101 用户手工修改）/ PATCH_APPROVED（§104 审批通过）
               / LOCK（§107 用户锁定）/ UNLOCK（§107 解锁）

    Returns: 迁移后的新状态。

    Raises:
        ValueError: 非法 state / event，或该迁移未定义（§99 规则写死不静默）。
    """
    if state not in OWNERSHIP_STATES:
        raise ValueError(f"非法 state={state!r}；四枚举: {OWNERSHIP_STATES}（§99）")
    table = OWNERSHIP_TRANSITIONS[state]
    if event not in table:
        raise ValueError(
            f"非法迁移 {state} --{event}--> ? （§99-102 未定义；可选事件: "
            f"{sorted({e for t in OWNERSHIP_TRANSITIONS.values() for e in t})}）")
    return table[event]


# ---------------------------------------------------------------------------
# §102/§103 build_patch
# ---------------------------------------------------------------------------

def build_patch(ops: list, base_timeline: dict, target_timeline: dict,
                patch_id: Optional[str] = None,
                created_at: Optional[str] = None,
                status: Optional[str] = None) -> dict:
    """§102/§103 构建 TP-### 补丁清单（schema 对齐 timeline-patch.schema.json）。

    Args:
        ops: 九操作列表（§103）。target 语义：clip TC-### / track TR-### /
             asset A### / subtitle / text。
        base_timeline: 补丁基线时间线（读 timeline_id / version）。
        target_timeline: 期望结果时间线（用于 timeline_diff，Test 23）。
        patch_id: 可选，缺省 "TP-001"（编排层负责分配递增 ID；保持确定性）。
        created_at: 可选，缺省 now_iso()。
        status: 可选，缺省按 patch_safety 判定：requires_approval → "needs_approval"
                else "pending"（语义登记 SCHEMA_CONTRACT7 §2.2）。

    Returns::

        {
          "patch_id": "TP-###", "timeline_id": "TL-###",
          "base_version": "str", "ops": [...九操作...],
          "diff_summary": "str（§105）",
          "created_at": "ISO 8601", "status": "pending|needs_approval|...",
        }
    """
    ops = normalize_ops(ops)
    if patch_id is not None and not PATCH_ID_RE.match(str(patch_id)):
        raise ValueError(f"非法 patch_id={patch_id!r}；格式 TP-###（契约 ID 总表）")
    base_id = base_timeline.get("timeline_id")
    if not base_id:
        raise ValueError("base_timeline 缺 timeline_id")
    base_version = base_timeline.get("version") or base_timeline.get("base_version")
    if not base_version:
        raise ValueError("base_timeline 缺 version（§102/§137 diff 必须针对该版本）")

    diff = timeline_diff(base_timeline, target_timeline)
    safety = patch_safety(base_timeline, {
        "ops": ops, "diff_summary": diff["summary"]})

    if status is None:
        status = "needs_approval" if safety["requires_approval"] else "pending"

    return {
        "patch_id": patch_id or "TP-001",
        "timeline_id": str(base_id),
        "base_version": str(base_version),
        "ops": ops,
        "diff_summary": diff["summary"],
        "created_at": created_at or now_iso(),
        "status": status,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    """CLI 入口：把两个时间线 JSON 文件 diff 后输出 TP-### 到 stdout。

    用法:
        python3 modules/timeline-manager/patch.py --diff <before.json> <after.json>
    """
    if len(argv or []) != 3 or (argv or [])[0] != "--diff":
        print("用法: python3 modules/timeline-manager/patch.py --diff <before.json> <after.json>",
              file=sys.stderr)
        return 2
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    try:
        before = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        after = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(timeline_diff(before, after), ensure_ascii=False, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    from copy import deepcopy  # noqa: PLC0415

    # ---- 构造 base 时间线（GENERATED_BASELINE）----
    def make_clip(cid, asset, start, end, track="TR-001", **kw):
        return {"clip_id": cid, "track_id": track, "asset_id": asset,
                "timeline_start_frame": start, "timeline_end_frame": end, **kw}

    base = {
        "timeline_id": "TL-001",
        "version": "timeline_v1",
        "ownership": "GENERATED_BASELINE",
        "tracks": [
            {"track_id": "TR-001", "type": "VIDEO_MAIN", "name": "V1_MAIN"},
            {"track_id": "TR-002", "type": "MUSIC", "name": "A2_MUSIC"},
            {"track_id": "TR-003", "type": "SUBTITLE", "name": "T2_SUBTITLES"},
        ],
        "clips": [
            make_clip("TC-001", "A001", 0, 150),
            make_clip("TC-002", "A002", 150, 300, track="TR-002"),
        ],
        "subtitle_items": [
            {"subtitle_id": "SUB-01", "text": "hello", "start_frame": 10, "end_frame": 60},
            {"subtitle_id": "SUB-02", "text": "world", "start_frame": 70, "end_frame": 120},
        ],
        "text_items": [],
        "audio_tracks": [], "sfx_tracks": [], "music_tracks": [],
        "overlays": [], "keyframes": [], "transitions": [],
        "asset_links": [], "replaceable_assets": [],
        "manual_edit_safe": True, "duration_frames": 300,
    }
    after = deepcopy(base)
    after["subtitle_items"][0]["text"] = "changed text"  # 只改一字幕（Test 23）

    checks = []

    # --- timeline_diff：只改一字幕 → diff 只含该字幕，clips_changed=0 ---
    diff = timeline_diff(base, after)
    checks.append(diff["clips_changed"] == 0)
    checks.append(diff["clips_added"] == 0 and diff["clips_removed"] == 0)
    checks.append(diff["subtitles_modified"] == 1)
    checks.append(diff["subtitle_ids_modified"] == ["SUB-01"])
    checks.append(diff["music_changed"] is False)
    checks.append("1 subtitle modified" in diff["summary"])
    checks.append(diff["summary"] == "0 clips changed, 1 subtitle modified, music unchanged")

    # --- timeline_diff：换 asset → assets_replaced=1 ---
    after2 = deepcopy(base)
    after2["clips"][0]["asset_id"] = "A099"
    after2["clips"][0]["scale"] = {"x": 1.1, "y": 1.1}
    diff2 = timeline_diff(base, after2)
    checks.append(diff2["clips_changed"] == 1)
    checks.append(diff2["assets_replaced"] == 1)
    checks.append(diff2["assets_replaced_list"] == ["A099"])
    checks.append("1 asset replaced" in diff2["summary"])

    # --- timeline_diff：音乐轨变更 → music_changed=True ---
    after3 = deepcopy(base)
    after3["clips"][1]["timeline_end_frame"] = 320
    diff3 = timeline_diff(base, after3)
    checks.append(diff3["music_changed"] is True)
    checks.append("music changed" in diff3["summary"])

    # --- normalize_ops 校验 ---
    checks.append(len(normalize_ops([{"op": "change_subtitle", "target": "SUB-01"}])) == 1)
    try:
        normalize_ops([{"op": "rebuild_timeline", "target": "x"}])
        checks.append(False)
    except ValueError:
        checks.append(True)
    try:
        normalize_ops([])
        checks.append(False)
    except ValueError:
        checks.append(True)

    # --- build_patch（Test 23：只改字幕 → status=pending，不重建）---
    patch = build_patch([{"op": "change_subtitle", "target": "SUB-01",
                          "payload": {"text": "changed text"}}], base, after)
    checks.append(patch["patch_id"] == "TP-001")
    checks.append(patch["timeline_id"] == "TL-001")
    checks.append(patch["base_version"] == "timeline_v1")
    checks.append(patch["status"] == "pending")
    checks.append(len(patch["ops"]) == 1 and patch["ops"][0]["op"] == "change_subtitle")
    checks.append("1 subtitle modified" in patch["diff_summary"])

    # --- patch_safety：GENERATED_BASELINE + 低风险 → allowed ---
    s1 = patch_safety(base, patch)
    checks.append(s1["allowed"] is True and s1["requires_approval"] is False)

    # --- patch_safety：HUMAN_EDITED + 高风险 → requires_approval（Test 24）---
    he = deepcopy(base)
    he["ownership"] = "HUMAN_EDITED"
    high = build_patch([{"op": "replace_asset", "target": "TC-001",
                         "payload": {"asset_id": "A099"}}], base, after2)
    s2 = patch_safety(he, high)
    checks.append(s2["requires_approval"] is True)
    checks.append(s2["allowed"] is True)
    checks.append(any("高风险" in r for r in s2["reasons"]))
    checks.append(s2["diff_summary"])

    # --- patch_safety：owner=HUMAN clip 被 AI patch 触碰 → requires_approval（§108）---
    ho = deepcopy(base)
    ho["clips"][0]["owner"] = "HUMAN"
    s3 = patch_safety(ho, patch)  # change_subtitle 低风险，但 target 非 clip → 不触碰
    checks.append(s3["requires_approval"] is False)
    low_on_human = build_patch([{"op": "change_audio", "target": "TC-001",
                                 "payload": {"volume": 0.5}}], base, base)
    s4 = patch_safety(ho, low_on_human)
    checks.append(s4["requires_approval"] is True)
    checks.append(any("HUMAN" in r for r in s4["reasons"]))

    # --- patch_safety：HUMAN locked clip → requires_approval + allowed=False（Test 22）---
    locked = deepcopy(base)
    locked["clips"][0] = {**locked["clips"][0], "owner": "HUMAN", "locked": True}
    s5 = patch_safety(locked, low_on_human)
    checks.append(s5["allowed"] is False)
    checks.append(s5["requires_approval"] is True)
    # §106：用户明确要求替换 → allowed 放宽
    s6 = patch_safety(locked, low_on_human, explicit_user_request=True)
    checks.append(s6["allowed"] is True)

    # --- 三级锁定：shot/track/clip locked_regions（§107）---
    reg = deepcopy(base)
    reg["locked_regions"] = [{"target_type": "track", "target_id": "TR-001",
                              "reason": "human fine-tune"}]
    s7 = patch_safety(reg, low_on_human)  # TC-001 在 TR-001
    checks.append(s7["allowed"] is False)
    reg2 = deepcopy(base)
    reg2["clips"][0]["shot_id"] = "S001"
    reg2["locked_regions"] = [{"target_type": "shot", "target_id": "S001"}]
    s8 = patch_safety(reg2, low_on_human)
    checks.append(s8["allowed"] is False)

    # --- ownership=LOCKED 整体禁止 ---
    locked_all = deepcopy(base)
    locked_all["ownership"] = "LOCKED"
    s9 = patch_safety(locked_all, patch)
    checks.append(s9["allowed"] is False)

    # --- ownership_transition 状态机（§99-102）---
    checks.append(ownership_transition("GENERATED_BASELINE", "MANUAL_EDIT") == "HUMAN_EDITED")
    checks.append(ownership_transition("HUMAN_EDITED", "PATCH_APPROVED") == "AI_PATCHABLE")
    checks.append(ownership_transition("AI_PATCHABLE", "MANUAL_EDIT") == "HUMAN_EDITED")
    checks.append(ownership_transition("HUMAN_EDITED", "LOCK") == "LOCKED")
    checks.append(ownership_transition("LOCKED", "UNLOCK") == "AI_PATCHABLE")
    checks.append(ownership_transition("GENERATED_BASELINE", "LOCK") == "LOCKED")
    try:
        ownership_transition("LOCKED", "MANUAL_EDIT")
        checks.append(False)
    except ValueError:
        checks.append(True)
    try:
        ownership_transition("GENERATED_BASELINE", "UNLOCK")
        checks.append(False)
    except ValueError:
        checks.append(True)
    # 迁移表完整性：全状态 x 全事件不抛 KeyError
    all_events = {"MANUAL_EDIT", "PATCH_APPROVED", "LOCK", "UNLOCK"}
    for st in OWNERSHIP_STATES:
        for ev in all_events:
            try:
                ownership_transition(st, ev)
            except ValueError:
                pass
    checks.append(True)

    # --- 确定性：同输入同输出 ---
    checks.append(timeline_diff(base, after) == timeline_diff(deepcopy(base), deepcopy(after)))
    checks.append(build_patch([{"op": "change_subtitle", "target": "SUB-01"}], base, after,
                              patch_id="TP-005")["patch_id"] == "TP-005")

    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"patch selftest check #{i} failed")
    print(f"patch selftest OK ({len(checks)} checks)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main(sys.argv[1:]))
