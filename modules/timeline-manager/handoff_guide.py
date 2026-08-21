#!/usr/bin/env python3
"""modules/timeline-manager/handoff_guide.py — 人工交接产物（Phase-7 §151-154；P7-6）.

用户说"后面我自己剪"时系统输出的两份人工文档 + source link 链（§154）：

1. ``generate_handoff_report(manifest, asset_index, draft_path, out_path)``
   → HANDOFF_REPORT.md（§151 至少：draft 位置 / Timeline Map / 可编辑轨 /
     Baked 资产 / Replaceable 资产 / 已知限制 / 最安全手动编辑项 /
     应改 Remotion Source 的项；§152 明确 "CG-04 类勿在剪映拆"）。
2. ``generate_editing_guide(manifest, asset_index, out_path)``
   → EDITING_GUIDE.md（§153 Safe to edit in JianYing vs Better edit in
     Remotion 两栏）。
3. ``resolve_source_links(manifest, asset_index)``
   → §154 Clip→Asset→Source 链（读 asset.local_path / source /
     registry_resources），复杂资产（连续性组/烘焙/可替换）逐条追溯。

铁律：
- §152：连续性组（CG-###）内部动画必须改 Remotion Source，不在剪映拆 Asset。
- §6/§167：文档服务"人类打开剪映继续剪"，不是"假可编辑"推销。
- 全确定性：无 LLM、无联网、stdlib only；排序稳定，输出固定模板。

CLI:
    python3 modules/timeline-manager/handoff_guide.py <manifest.json> \
        [<asset_index.json>] --report <out.md> [--editing-guide <out2.md>]
    python3 modules/timeline-manager/handoff_guide.py --selftest
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional


def frames_to_timecode(frame: int, fps: float = 30.0) -> str:
    """帧 → 时间码 'HH:MM:SS.mmm'（§28 frames↔seconds 转换；确定性）。"""
    sec = float(frame) / max(float(fps), 1e-9)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _clips(manifest: dict) -> list:
    return [c for c in manifest.get("clips") or [] if isinstance(c, dict)]


def _track_map(manifest: dict) -> dict:
    return {str(t.get("track_id") or ""): t
            for t in manifest.get("tracks") or [] if isinstance(t, dict) and t.get("track_id")}


def _fps(manifest: dict) -> float:
    try:
        return float(manifest.get("fps") or 30)
    except (TypeError, ValueError):
        return 30.0


def _asset(asset_index: Optional[dict], asset_id: Any) -> Optional[dict]:
    if not asset_index or not asset_id:
        return None
    a = asset_index.get(str(asset_id))
    return a if isinstance(a, dict) else None


def _draft_location(manifest: dict, draft_path: Optional[str]) -> str:
    if draft_path:
        return str(draft_path)
    md = manifest.get("backend_metadata")
    if isinstance(md, dict) and md.get("draft_path"):
        return str(md["draft_path"])
    if manifest.get("project_path"):
        return str(manifest["project_path"]) + "（Manifest 工程路径；draft 未生成则人工打开剪映新建）"
    return "UNKNOWN（未生成 draft，本文档基于 Timeline Manifest）"


def _editable_tracks(manifest: dict) -> list:
    """可编辑轨：轨上所有 clip 默认可编辑（editable 缺省 true，§6-7）。"""
    out = []
    for t in manifest.get("tracks") or []:
        if not isinstance(t, dict) or not t.get("track_id"):
            continue
        out.append(t)
    return sorted(out, key=lambda t: str(t.get("track_id") or ""))


def _baked_clips(manifest: dict, asset_index: Optional[dict]) -> list:
    baked = []
    for c in _clips(manifest):
        if c.get("editable") is False:
            baked.append({"clip_id": c.get("clip_id"), "asset_id": c.get("asset_id"),
                          "reason": "clip.editable=false"})
            continue
        a = _asset(asset_index, c.get("asset_id"))
        if a and a.get("editability") == "BAKE":
            baked.append({"clip_id": c.get("clip_id"), "asset_id": c.get("asset_id"),
                          "reason": f"asset.editability=BAKE（{a.get('name', '')}）"})
    baked.sort(key=lambda x: str(x["clip_id"]))
    return baked


def _replaceable_items(manifest: dict, asset_index: Optional[dict]) -> list:
    """Replaceable 资产 → 槽位映射：asset_id / asset_slot_id / 使用的 clip。"""
    items = []
    slots = {}  # asset_id -> list[(clip_id, slot)]
    for c in _clips(manifest):
        aid = str(c.get("asset_id") or "")
        if not aid:
            continue
        slots.setdefault(aid, []).append((c.get("clip_id"), c.get("asset_slot_id")))
    replaceable_ids = set()
    for a in manifest.get("replaceable_assets") or []:
        if isinstance(a, str):
            replaceable_ids.add(a)
        elif isinstance(a, dict) and a.get("asset_id"):
            replaceable_ids.add(str(a["asset_id"]))
    if asset_index:
        replaceable_ids |= {aid for aid, a in asset_index.items()
                            if isinstance(a, dict) and a.get("replaceable") is True}
    for aid in sorted(replaceable_ids):
        a = _asset(asset_index, aid)
        items.append({
            "asset_id": aid,
            "asset_name": (a or {}).get("name") or "",
            "slots": sorted({s for _, s in slots.get(aid, []) if s}),
            "clips": sorted({cid for cid, _ in slots.get(aid, []) if cid}),
        })
    return items


def _known_limitations(manifest: dict) -> list:
    """§91-92/§148：已知限制（能力矩阵 supported=false + fallback + warnings）。"""
    out = []
    caps = manifest.get("backend_capabilities")
    if isinstance(caps, dict):
        for key in sorted(caps):
            v = caps[key]
            if not isinstance(v, dict) or v.get("supported") is not False:
                continue
            fb = v.get("fallback") or "无回退"
            out.append(f"{key}: 后端不支持 → {fb}")
    md = manifest.get("backend_metadata")
    if isinstance(md, dict):
        for w in md.get("warnings") or []:
            if isinstance(w, str):
                out.append(f"warning: {w}")
        for uf in md.get("unsupported_features") or []:
            if isinstance(uf, dict):
                out.append(f"{uf.get('feature')}: 不支持 → {uf.get('fallback', '')}")
        for fb in md.get("fallbacks") or []:
            if isinstance(fb, str):
                out.append(f"fallback: {fb}")
    if not out:
        out.append("无已知限制（backend_capabilities 未声明不支持项）")
    return out


def _timeline_map_lines(manifest: dict) -> list:
    """§87/§151 Timeline Map：按时间排序的剪辑/标记行。"""
    fps = _fps(manifest)
    track_map = _track_map(manifest)
    lines = []
    for c in sorted(_clips(manifest), key=lambda c: c["timeline_start_frame"]):
        s, e = c["timeline_start_frame"], c["timeline_end_frame"]
        sid = c.get("shot_id") or "-"
        aid = c.get("asset_id") or "-"
        tname = track_map.get(str(c.get("track_id") or ""), {}).get("name") \
            or str(c.get("track_id") or "-")
        lines.append(f"- {frames_to_timecode(s, fps)}–{frames_to_timecode(e, fps)}  "
                     f"{sid or '-'}  "
                     f"{aid}  {tname}  ({c.get('clip_id')})")
    for m in manifest.get("markers") or []:
        if not isinstance(m, dict) or not isinstance(m.get("frame"), (int, float)):
            continue
        lines.append(f"- {frames_to_timecode(int(m['frame']), fps)}  "
                     f"[MARKER {m.get('type') or ''} {m.get('label') or ''}]".rstrip())
    return lines


def _continuity_groups(manifest: dict) -> list:
    groups: dict = {}
    for c in _clips(manifest):
        g = c.get("continuity_group")
        if isinstance(g, str) and g:
            groups.setdefault(g, []).append(c)
    out = []
    for g in sorted(groups):
        out.append({"group": g,
                    "clips": sorted({str(c.get("clip_id") or "") for c in groups[g]}),
                    "assets": sorted({str(c.get("asset_id") or "") for c in groups[g]})})
    return out


# ---------------------------------------------------------------------------
# §154 Clip→Asset→Source 链
# ---------------------------------------------------------------------------

def resolve_source_link(clip: dict, asset_index: Optional[dict] = None) -> dict:
    """§154 单条 Clip→Asset→Source 链。

    Returns::

        {
          "clip_id": "TC-028",
          "asset_id": "A018",
          "asset_name": "str",
          "asset_type": "str",
          "local_path": "str|None",     # 实际媒体文件（§117 resolved local path）
          "source": "str|None",         # 资产来源（§116 media relink 依 asset_id 重找）
          "registry_resources": [...],  # {provider}:{type}:{slug}（§154 直达 source/...）
          "source_ref": "str",          # 最终追溯引用（local_path/source/registry 首个）
        }
    """
    aid = str(clip.get("asset_id") or "")
    a = _asset(asset_index, aid) if aid else None
    local_path = (a or {}).get("local_path")
    source = (a or {}).get("source")
    registry = (a or {}).get("registry_resources") or []
    if isinstance(registry, list):
        registry = [str(r) for r in registry if isinstance(r, str)]
    source_ref = local_path or source or (registry[0] if registry else None) or "UNKNOWN"
    return {
        "clip_id": str(clip.get("clip_id") or ""),
        "asset_id": aid,
        "asset_name": (a or {}).get("name") or "",
        "asset_type": (a or {}).get("type") or "",
        "local_path": local_path,
        "source": source,
        "registry_resources": registry,
        "source_ref": source_ref,
    }


def resolve_source_links(manifest: dict, asset_index: Optional[dict] = None) -> list:
    """§154 全量 Clip→Asset→Source 链（全部 clip，确定性排序）。"""
    return [resolve_source_link(c, asset_index)
            for c in sorted(_clips(manifest), key=lambda c: str(c.get("clip_id") or ""))]


# ---------------------------------------------------------------------------
# §151-152 HANDOFF_REPORT
# ---------------------------------------------------------------------------

def generate_handoff_report(manifest: dict, asset_index: Optional[dict] = None,
                            draft_path: Optional[str] = None,
                            out_path: Optional[str] = None) -> str:
    """§151-152 HANDOFF_REPORT.md 生成（人工交接）。

    含 §152 硬性说明：连续性组（CG-###）与复杂烘焙资产内部动画必须改
    Remotion Source，不要在剪映拆 Asset。
    """
    fps = _fps(manifest)
    cg_list = _continuity_groups(manifest)
    baked = _baked_clips(manifest, asset_index)
    replaceable = _replaceable_items(manifest, asset_index)
    lines = []
    A = lines.append
    A("# HANDOFF_REPORT — 人工接管说明（Phase-7 §151-152）")
    A("")
    A(f"- timeline: {manifest.get('timeline_id') or 'UNKNOWN'}  version: "
      f"{manifest.get('version') or '-'}")
    A(f"- ownership: {manifest.get('ownership') or 'GENERATED_BASELINE'}（§99）")
    A("")
    A("## 1. Draft 位置（§151）")
    A(f"- {_draft_location(manifest, draft_path)}")
    A("")
    A("## 2. Timeline Map（§87/§151）")
    map_lines = _timeline_map_lines(manifest)
    if map_lines:
        A("\n".join(map_lines))
    else:
        A("- 空时间线")
    A("")
    A("## 3. 可编辑轨（§151）")
    for t in _editable_tracks(manifest):
        A(f"- {t.get('track_id')}  {t.get('name') or ''}  ({t.get('type')})")
    A("")
    A("## 4. Baked 资产（§151，勿手动拆）")
    if baked:
        for b in baked:
            A(f"- {b['clip_id']}  asset={b['asset_id']}  原因: {b['reason']}")
    else:
        A("- 无烘焙资产")
    A("")
    A("## 5. Replaceable 资产（§151/§33-35）")
    if replaceable:
        for r in replaceable:
            slot_txt = ", ".join(r["slots"]) if r["slots"] else "（未映射槽位）"
            A(f"- {r['asset_id']}  {r['asset_name'] or ''}  槽位: {slot_txt}  "
              f"clips: {', '.join(r['clips']) or '-'}")
    else:
        A("- 无可替换资产")
    A("")
    A("## 6. 已知限制（§91-92）")
    for lim in _known_limitations(manifest):
        A(f"- {lim}")
    A("")
    A("## 7. 最安全手动编辑项（§153）")
    for item in ("字幕（subtitle）", "B-roll 时机（B-roll timing）",
                 "图片时长（image duration）", "音乐音量（music level）",
                 "基础标题（basic title）", "片段顺序（clip order）"):
        A(f"- {item}")
    A("")
    A("## 8. 应改 Remotion Source 的项（§152）")
    A("> 铁律 §152：不要为了改内部动画而在剪映里拆 Asset，否则破坏连续性。")
    if cg_list:
        for g in cg_list:
            A(f"- 连续性组 {g['group']}（clips: {', '.join(g['clips'])}，assets: "
              f"{', '.join(g['assets'])}）：内部动画改 Remotion Source 后重新 "
              f"Render，再走 Replace Asset Slot（§154/§168）")
    else:
        A("- 无连续性组")
    if baked:
        A("- 烘焙资产内部内容：改其 Remotion/生产 Source（见 §9 链接）")
    A("")
    A("## 9. Source Link 链（§154 Clip→Asset→Source）")
    links = resolve_source_links(manifest, asset_index)
    complex_links = [l for l in links
                     if l["clip_id"] in {b["clip_id"] for b in baked}
                     or l["clip_id"] in {c for g in cg_list for c in g["clips"]}
                     or l["asset_id"] in {r["asset_id"] for r in replaceable}]
    if complex_links:
        A("| Clip | Asset | Source |")
        A("|---|---|---|")
        for l in complex_links:
            A(f"| {l['clip_id']} | {l['asset_id']} | {l['source_ref']} |")
    else:
        A("- 无复杂资产需要追溯")
    A("")
    A("## 10. 交接说明（§6/§96）")
    A("- Draft 生成 ≠ 自动导出成片：请人工打开剪映检查/继续编辑（§96）。")
    A(f"- 时间基准：{fps:g} fps，帧安全计时（§26-27）。")
    A("")
    text = "\n".join(lines)
    if out_path:
        from pathlib import Path  # noqa: PLC0415
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# §153 EDITING_GUIDE
# ---------------------------------------------------------------------------

def generate_editing_guide(manifest: dict, asset_index: Optional[dict] = None,
                           out_path: Optional[str] = None) -> str:
    """§153 EDITING_GUIDE.md 生成：哪些在剪映安全改、哪些应回 Remotion 改。"""
    cg_list = _continuity_groups(manifest)
    lines = []
    A = lines.append
    A("# EDITING_GUIDE — 哪些能自己改（Phase-7 §153）")
    A("")
    A(f"- timeline: {manifest.get('timeline_id') or 'UNKNOWN'}  "
      f"fps={_fps(manifest):g}")
    A("")
    A("## Safe to edit in JianYing（剪映里改是安全的）")
    A("| 项 | 说明 |")
    A("|---|---|")
    A("| 字幕 subtitle | 改文案/时机/样式（默认 KEEP_EDITABLE，§55） |")
    A("| B-roll 时机 | 增删/移动 B-roll 片段（§75-76） |")
    A("| 图片时长 | 普通图片时长/Ken Burns（§77） |")
    A("| 音乐音量 | 音乐电平/淡入淡出（§64） |")
    A("| 基础标题 | 简单文字内容与位置（§38） |")
    A("| 片段顺序 | 剪映内重排可编辑片段（§128） |")
    A("")
    A("## Better edit in Remotion（应在 Remotion/Source 改，勿在剪映硬拆）")
    A("| 项 | 说明 |")
    A("|---|---|")
    A("| 复杂 UI morph | 逐帧动画拆开即毁（§51） |")
    A("| 3D continuity | 三维连续性依赖渲染管线（§81） |")
    A("| 结构性 Motion | 多对象结构变换（§7/§8） |")
    A("| 透明资产内部 | transparent overlay 内部元素（§115/§152） |")
    A("")
    if cg_list:
        A("## 特殊注意：连续性组（§8/§152）")
        A("> 同一 continuity_group 的片段是一个整体；要改内部动画请改 Remotion "
          "Source 后重 Render，再 Replace Asset Slot（§168）。")
        for g in cg_list:
            A(f"- {g['group']}（clips: {', '.join(g['clips'])}）")
        A("")
    text = "\n".join(lines)
    if out_path:
        from pathlib import Path  # noqa: PLC0415
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n", encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    from pathlib import Path  # noqa: PLC0415
    args = list(argv or [])
    if "--selftest" in args:
        selftest()
        return 0
    if not args:
        print("用法: python3 modules/timeline-manager/handoff_guide.py <manifest.json> "
              "[<asset_index.json>] [--report <out.md>] [--editing-guide <out2.md>]",
              file=sys.stderr)
        return 2
    try:
        manifest = json.loads(Path(args[0]).read_text(encoding="utf-8"))
        asset_index = None
        report_out = None
        guide_out = None
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--report" and i + 1 < len(args):
                report_out = args[i + 1]
                i += 2
            elif a == "--editing-guide" and i + 1 < len(args):
                guide_out = args[i + 1]
                i += 2
            elif a.endswith(".json") and asset_index is None:
                asset_index = json.loads(Path(a).read_text(encoding="utf-8"))
                i += 1
            else:
                i += 1
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report = generate_handoff_report(manifest, asset_index, out_path=report_out)
    guide = generate_editing_guide(manifest, asset_index, out_path=guide_out)
    if report_out:
        print(f"handoff report written: {report_out}", file=sys.stderr)
    if guide_out:
        print(f"editing guide written: {guide_out}", file=sys.stderr)
    if not report_out:
        sys.stdout.write(report + "\n")
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

    manifest = {
        "timeline_id": "TL-001", "version": "timeline_v1", "fps": 30,
        "duration_frames": 600,
        "project_path": "/proj/product",
        "ownership": "GENERATED_BASELINE",
        "tracks": [
            {"track_id": "TR-001", "type": "VIDEO_MAIN", "name": "V1_MAIN"},
            {"track_id": "TR-002", "type": "VIDEO_OVERLAY", "name": "V4_OVERLAY"},
            {"track_id": "TR-003", "type": "SUBTITLE", "name": "T2_SUBTITLES"},
        ],
        "clips": [
            clip("TC-001", "A001", 0, 300, shot_id="S001"),
            clip("TC-028", "A018", 300, 600, shot_id="S002", track="TR-002",
                 continuity_group="CG-04", asset_slot_id="AS-S018-MOTION"),
        ],
        "subtitle_items": [{"subtitle_id": "SUB-01", "text": "hi",
                            "start_frame": 10, "end_frame": 60}],
        "text_items": [], "audio_tracks": [], "sfx_tracks": [],
        "music_tracks": [], "overlays": [], "keyframes": [],
        "transitions": [], "asset_links": [{"asset_ref": "A001"}],
        "replaceable_assets": ["A018"], "manual_edit_safe": True,
        "markers": [{"marker_id": "MK-001", "frame": 0, "type": "Scene start",
                     "label": "Hook"}],
        "backend_capabilities": {
            "custom_motion_path": {"supported": False,
                                   "fallback": "render as Remotion asset"},
        },
        "backend_metadata": {"draft_path": "/proj/product/timeline/backend/draft_v1"},
    }
    assets = {
        "A001": {"asset_id": "A001", "name": "hook footage", "type": "FOOTAGE",
                 "local_path": "/proj/assets/A001_v1.mp4",
                 "source": "footage://proj/A001", "editability": "KEEP_EDITABLE"},
        "A018": {"asset_id": "A018", "name": "motion v2", "type": "MOTION_CLIP",
                 "local_path": "/proj/assets/A018_v2.mov", "producer": "REMOTION",
                 "replaceable": True, "editability": "ASSET_REPLACEABLE",
                 "registry_resources": ["remotion:render:S018"]},
    }
    checks = []

    # --- §154 source link 链 ---
    link = resolve_source_link(manifest["clips"][1], assets)
    checks.append(link["clip_id"] == "TC-028")
    checks.append(link["asset_id"] == "A018")
    checks.append(link["local_path"].endswith("A018_v2.mov"))
    checks.append(link["registry_resources"] == ["remotion:render:S018"])
    checks.append(link["source_ref"].endswith("A018_v2.mov"))
    links = resolve_source_links(manifest, assets)
    checks.append(len(links) == 2)
    checks.append(links[0]["clip_id"] == "TC-001")

    # --- HANDOFF_REPORT 内容完整性（§151 十段 + §152 铁律）---
    report = generate_handoff_report(manifest, assets, draft_path="/proj/draft")
    checks.append("# HANDOFF_REPORT" in report)
    checks.append("## 1. Draft 位置" in report)
    checks.append("/proj/draft" in report)
    checks.append("## 2. Timeline Map" in report)
    checks.append("00:00:00.000" in report)      # 帧转时间码
    checks.append("## 3. 可编辑轨" in report)
    checks.append("V1_MAIN" in report)
    checks.append("## 4. Baked 资产" in report)
    checks.append("## 5. Replaceable 资产" in report)
    checks.append("AS-S018-MOTION" in report)
    checks.append("## 6. 已知限制" in report)
    checks.append("custom_motion_path" in report and "render as Remotion asset" in report)
    checks.append("## 7. 最安全手动编辑项" in report)
    checks.append("字幕（subtitle）" in report)
    checks.append("## 8. 应改 Remotion Source 的项（§152）" in report)
    checks.append("CG-04" in report)
    checks.append("改 Remotion Source" in report)
    # §152 硬性内容：CG-04 勿在剪映拆
    checks.append("不要为了改内部动画而在剪映里拆 Asset" in report)
    checks.append("## 9. Source Link 链（§154 Clip→Asset→Source）" in report)
    checks.append("| TC-028 | A018 |" in report)
    checks.append("## 10. 交接说明" in report)
    checks.append("人工打开剪映检查/继续编辑" in report)

    # --- EDITING_GUIDE 内容（§153）---
    guide = generate_editing_guide(manifest, assets)
    checks.append("# EDITING_GUIDE" in guide)
    checks.append("## Safe to edit in JianYing" in guide)
    checks.append("## Better edit in Remotion" in guide)
    checks.append("复杂 UI morph" in guide)
    checks.append("3D continuity" in guide)
    checks.append("透明资产内部" in guide)
    checks.append("## 特殊注意：连续性组" in guide)
    checks.append("CG-04" in guide)
    checks.append("Replace Asset Slot" in guide)

    # --- 文件写出 + 确定性 ---
    with tempfile.TemporaryDirectory() as td:
        rp = _P(td) / "HANDOFF_REPORT.md"
        gp = _P(td) / "EDITING_GUIDE.md"
        generate_handoff_report(manifest, assets, draft_path="/proj/draft",
                                out_path=str(rp))
        generate_editing_guide(manifest, assets, out_path=str(gp))
        checks.append(rp.exists() and rp.read_text(encoding="utf-8").startswith("# HANDOFF_REPORT"))
        checks.append(gp.exists() and gp.read_text(encoding="utf-8").startswith("# EDITING_GUIDE"))
    checks.append(generate_handoff_report(manifest, assets, draft_path="/proj/draft")
                  == generate_handoff_report(deepcopy(manifest), deepcopy(assets),
                                             draft_path="/proj/draft"))
    checks.append(resolve_source_links(manifest, assets)
                  == resolve_source_links(deepcopy(manifest), deepcopy(assets)))

    # --- 空时间线不崩 ---
    empty = {"timeline_id": "TL-002", "version": "v1", "fps": 30, "tracks": [],
             "clips": [], "subtitle_items": [], "text_items": [], "audio_tracks": [],
             "sfx_tracks": [], "music_tracks": [], "overlays": [], "keyframes": [],
             "transitions": [], "asset_links": [], "replaceable_assets": [],
             "manual_edit_safe": True}
    er = generate_handoff_report(empty)
    checks.append("- 空时间线" in er)

    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"handoff_guide selftest check #{i} failed")
    print(f"handoff_guide selftest OK ({len(checks)} checks)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
