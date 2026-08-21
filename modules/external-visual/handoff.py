#!/usr/bin/env python3
"""handoff.py — TIMELINE_HANDOFF_MANIFEST 生成器（Phase-6 §133-134；P6-07）.

为 Phase 7 生成时间线交接清单：每条 TH-### 记录一个 Asset 应如何进入编辑器
（preferred_track / preferred_start / preferred_duration / in/out 点 / crop /
blend / overlay / replaceable / proxy / original / audio_behavior / editability，
字段对齐 schemas/timeline-handoff.schema.json 条目）。

**§134 铁律：只提示、不创建时间线。** 本清单只输出"建议"，不创建时间线、
不写死轨道；manifest 头部 note 明确声明，装配与裁决留给 Phase 7。

数据聚合：
- asset.timeline_hint 扩展键（preferred_start/preferred_duration/track_hint/
  in_point/out_point/crop/speed/overlay_safe_area/blend_hint，P6-01 asset schema）
- footage.plan_use 输出（可选，通过 asset 内嵌 `plan_use` 字段传入；含
  recommended_in/out、timeline_hint{track,in,out,suggested_duration,
  preferred_crop,overlay_safe_area}、audio_behavior）
- asset.audio_behavior / asset.editability / asset.replaceable / proxy / original
- shots（可选）用于解析 shot_id/layer_id 归属（asset_ref 匹配）

全确定性：按 asset_id 排序；无 LLM、无联网。

CLI：
    python3 -m modules.external-visual.handoff <asset_jsons...> [--shots <shots_dir>] \
        [--out <out.json>] [--project <id>] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

TH_ID_RE = re.compile(r"^TH-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")

#: audio_behavior 五枚举（§83-84）
AUDIO_BEHAVIORS = ("KEEP", "MUTE", "USE_AS_AMBIENCE", "EXTRACT", "REPLACE")
#: editability 三枚举（asset.editability / production-request.editability_policy）
EDITABILITIES = ("KEEP_EDITABLE", "ASSET_REPLACEABLE", "BAKE")
#: 默认轨道（§88/§134 提示用；asset 无 hint 时按资产类型归类）
_TRACK_BY_TYPE = {
    "MUSIC": "music", "SFX": "sfx", "AMBIENCE": "sfx", "VOICEOVER": "voiceover",
    "TEXT": "text", "TRANSPARENT_OVERLAY": "overlay", "ANIMATED_TEXT": "text",
}


def now_iso() -> str:
    """UTC 时间戳（ISO 8601，秒精度；与 modules/production/planner.py 同款）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 输入归一化
# ---------------------------------------------------------------------------

def _is_asset_dict(obj: Any) -> bool:
    return isinstance(obj, dict) and bool(obj.get("asset_id"))


def _load_json_list(spec, assets_only: bool = False) -> list:
    """把输入归一为 dict 列表（asset 或 shot JSON）。

    assets_only=True（R6 边车过滤）：目录模式只收录文件名以 `_asset.json`
    结尾的资产元数据文件，跳过 `*_ingest.json` 边车及其它干扰 JSON。
    原因：ingest 边车顶层同样含 asset_id，按字典序（`X_asset.json` <
    `X_ingest.json`）后置加载会以边车内容覆盖正式资产文件（P6-09 §8-5
    边车覆盖问题）。显式文件路径 / list / dict 输入不受影响（显式喂入即
    信任调用方）。判定规则写入 docstring：目录内只认 `*_asset.json`。
    """
    out: list = []
    if isinstance(spec, (str, Path)):
        p = Path(spec)
        if p.is_dir():
            files = sorted(p.glob("*.json"))
            for f in files:
                if assets_only and not f.name.endswith("_asset.json"):
                    continue  # R6：跳过 *_ingest.json 边车与非资产元数据 JSON
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                out.extend(data if isinstance(data, list) else [data])
        elif p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            out.extend(data if isinstance(data, list) else [data])
        else:
            raise ValueError(f"路径不存在: {p}")
    elif isinstance(spec, list):
        out = [d for d in spec if isinstance(d, dict)]
    elif isinstance(spec, dict):
        out = [spec]
    else:
        raise ValueError(f"不支持的输入: {type(spec).__name__}")
    return [d for d in out if isinstance(d, dict)]


def _load_assets(spec) -> list:
    by_id: dict = {}
    for a in _load_json_list(spec, assets_only=True):
        if _is_asset_dict(a):
            by_id[str(a["asset_id"])] = a
    return [by_id[k] for k in sorted(by_id)]


def _load_shots(spec) -> list:
    return _load_json_list(spec)


# ---------------------------------------------------------------------------
# shot/layer 归属解析（asset_ref → shot_id/layer_id）
# ---------------------------------------------------------------------------

def _find_shot_for_asset(asset: dict, shots: list) -> tuple:
    """在 shots 中查找引用该 asset 的 (shot_id, layer_id)。

    - 优先 asset 自带 shot_id / layer_id；
    - 否则扫描 shot.layers（layer 的 asset/asset_ref 字段）与 shot.assets
      （list[str] 或 list[{asset_ref}]）匹配 asset_id；
    - 找不到 → ("UNKNOWN", "UNKNOWN")。
    """
    aid = str(asset.get("asset_id") or "")
    shot_id = str(asset.get("shot_id") or "").strip() or None
    layer_id = str(asset.get("layer_id") or "").strip() or None
    if shot_id and layer_id:
        return shot_id, layer_id

    for shot in shots:
        sid = str(shot.get("id") or shot.get("shot_id") or "").strip() or None
        # layers 含 asset/asset_ref → 精确匹配 layer
        for layer in shot.get("layers") or []:
            if not isinstance(layer, dict):
                continue
            lref = layer.get("asset") or layer.get("asset_ref") or layer.get("asset_id")
            if str(lref or "") == aid:
                lid = str(layer.get("id") or layer.get("layer_id") or "").strip()
                return sid or "UNKNOWN", lid or layer_id or "UNKNOWN"
        # shot.assets 直接含 asset_id（无 layer 归属时返回 shot + UNKNOWN layer）
        refs = shot.get("assets") or []
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, dict):
                    if str(ref.get("asset_ref") or ref.get("asset_id") or "") == aid:
                        return sid or "UNKNOWN", layer_id or "UNKNOWN"
                elif str(ref) == aid:
                    return sid or "UNKNOWN", layer_id or "UNKNOWN"
    if shot_id:
        return shot_id, layer_id or "UNKNOWN"
    return "UNKNOWN", layer_id or "UNKNOWN"


# ---------------------------------------------------------------------------
# 单条 TH 条目构建
# ---------------------------------------------------------------------------

def _fmt_ts(value: Any) -> Optional[str]:
    """秒数 → 时间码字符串（如 16.1 → '00:00:16.100'）；非数字原样返回。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        total = float(value)
        h = int(total // 3600)
        m = int((total % 3600) // 60)
        s = total % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    s = str(value).strip()
    return s or None


def build_entry(asset: dict, shots: Optional[list] = None,
                handoff_id: str = "TH-001") -> dict:
    """从单个 asset dict 构建一条 schema-valid 的 TH 条目（§133 字段）。"""
    shots = shots or []
    aid = str(asset.get("asset_id") or "")
    shot_id, layer_id = _find_shot_for_asset(asset, shots)

    hint = asset.get("timeline_hint")
    if not isinstance(hint, dict):
        hint = {}
    plan = asset.get("plan_use")
    if not isinstance(plan, dict):
        plan = {}
    plan_hint = plan.get("timeline_hint")
    if not isinstance(plan_hint, dict):
        plan_hint = {}

    # preferred_track：timeline_hint.track/track_hint > plan.track > 类型归类 > video
    track = (hint.get("track") or hint.get("track_hint")
             or plan_hint.get("track") or plan.get("track"))
    if not track:
        track = _TRACK_BY_TYPE.get(str(asset.get("type") or "").upper())
    if not track:
        track = "video"

    # preferred_duration：hint > asset.duration > plan.suggested_duration（必填 >0）
    duration = (hint.get("preferred_duration")
                or asset.get("duration")
                or plan_hint.get("suggested_duration"))
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is None or duration <= 0:
        duration = 0.0  # schema exclusiveMinimum>0 由校验方提示；此处保留最小占位
        # 注：正常 ingest 资产必有 duration；占位仅防 CLI 崩溃，REPORT 记录。

    # in/out：hint.in_point > plan_hint.in（footage plan_use 的可用区间 §71-72）
    in_point = _fmt_ts(hint.get("in_point") or plan_hint.get("in")
                       or plan.get("recommended_in"))
    out_point = _fmt_ts(hint.get("out_point") or plan_hint.get("out")
                        or plan.get("recommended_out"))
    crop = (hint.get("crop") or plan_hint.get("preferred_crop"))
    blend = hint.get("blend_hint")
    overlay = (hint.get("overlay_safe_area")
               or plan_hint.get("overlay_safe_area")
               or hint.get("overlay"))

    audio_behavior = (asset.get("audio_behavior")
                      or plan.get("audio_behavior")
                      or str(asset.get("audio_mode") or "").upper() or None)
    if audio_behavior is not None:
        audio_behavior = str(audio_behavior).upper()
        if audio_behavior not in AUDIO_BEHAVIORS:
            audio_behavior = None

    editability = str(asset.get("editability") or "").upper()
    if editability not in EDITABILITIES:
        editability = "ASSET_REPLACEABLE" if asset.get("replaceable") is True \
            else "KEEP_EDITABLE"

    entry: dict = {
        "handoff_id": handoff_id,
        "asset_id": aid or "UNKNOWN",
        "shot_id": shot_id,
        "layer_id": layer_id,
        "preferred_track": str(track),
        "preferred_duration": round(duration, 3),
        "editability": editability,
    }
    # 可选字段：仅有值才写入（schema 缺省省略键）
    if hint.get("preferred_start") is not None or plan_hint.get("preferred_start") is not None:
        ps = hint.get("preferred_start")
        if ps is None:
            ps = plan_hint.get("preferred_start")
        try:
            entry["preferred_start"] = round(float(ps), 3)
        except (TypeError, ValueError):
            pass
    if in_point:
        entry["in_point"] = in_point
    if out_point:
        entry["out_point"] = out_point
    if crop:
        entry["crop"] = str(crop)
    if blend:
        entry["blend"] = str(blend)
    if overlay:
        entry["overlay"] = str(overlay)
    if asset.get("replaceable") is not None:
        entry["replaceable"] = bool(asset["replaceable"])
    if asset.get("proxy_path"):
        entry["proxy"] = str(asset["proxy_path"])
    elif asset.get("preview"):
        entry["proxy"] = str(asset["preview"])
    if asset.get("original_path"):
        entry["original"] = str(asset["original_path"])
    elif asset.get("source"):
        entry["original"] = str(asset["source"])
    if audio_behavior:
        entry["audio_behavior"] = audio_behavior
    speed = hint.get("speed") or plan_hint.get("speed")
    if speed is not None:
        entry["speed"] = str(speed)
    return entry


# ---------------------------------------------------------------------------
# 主构建函数
# ---------------------------------------------------------------------------

def build_timeline_handoff(assets, shots=None, out_path=None,
                           project_id: Optional[str] = None) -> dict:
    """生成 TIMELINE_HANDOFF_MANIFEST（§133-134）。

    Args:
        assets:  asset JSON 列表 / 目录 / 文件路径
        shots:   shot JSON 列表 / 目录 / 文件路径（可选，解析 shot/layer 归属）
        out_path: 输出 JSON 路径（可选；None 只返回 dict）
        project_id: 项目名（缺省取 out_path 父目录名或 "UNKNOWN"）

    Returns:
        manifest dict：{schema, schema_version, project_id, generated_at,
                        note（§134 头部声明）, entries[]}
    """
    asset_list = _load_assets(assets)
    shot_list = _load_shots(shots) if shots is not None else []
    if project_id:
        pid = str(project_id)
    elif out_path is not None:
        pid = Path(out_path).parent.name or "UNKNOWN"
    else:
        pid = "UNKNOWN"

    entries = []
    for i, asset in enumerate(asset_list, 1):
        entries.append(build_entry(asset, shot_list, f"TH-{i:03d}"))

    manifest = {
        "schema": "TIMELINE_HANDOFF_MANIFEST",
        "schema_version": "1.0",
        "project_id": pid,
        "generated_at": now_iso(),
        # §134：只提示、不创建时间线——头部明确声明（装配与裁决由 Phase 7 完成）。
        "note": "§134 只提示、不创建时间线：本清单仅建议每个 Asset 如何进入编辑器"
                "（preferred_track/start/duration、in/out 点、裁剪/混合/叠加、"
                "音频行为、可替换性），不创建时间线、不写死轨道；"
                "可编辑时间线总装与裁决由 Phase 7 完成。",
        "entries": entries,
    }
    if out_path is not None:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python3 -m modules.external-visual.handoff",
        description="TIMELINE_HANDOFF_MANIFEST 生成器（Phase-6 §133-134；只提示不建时间线）")
    ap.add_argument("assets", nargs="+",
                    help="asset JSON 目录或文件（可多个）")
    ap.add_argument("--shots", default=None, help="shot JSON 目录/文件（可选）")
    ap.add_argument("--out", default=None, help="manifest 输出路径（缺省 stdout）")
    ap.add_argument("--project", default=None, help="项目名（缺省取 out 父目录名）")
    ap.add_argument("--json", action="store_true", help="stdout 输出 JSON")
    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        merged: list = []
        for spec in args.assets:
            merged.extend(_load_assets(spec))
        manifest = build_timeline_handoff(
            merged, args.shots, args.out, project_id=args.project)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.out:
        print(f"timeline handoff manifest written: {args.out}"
              f"（entries={len(manifest['entries'])}）", file=sys.stderr)
    if args.json or not args.out:
        sys.stdout.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return 0


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    from copy import deepcopy  # noqa: PLC0415

    asset = {
        "asset_id": "A011",
        "name": "city archive",
        "type": "FOOTAGE",
        "shot_id": "S003",
        "layer_id": "S003-L01",
        "duration": 4.0,
        "replaceable": True,
        "audio_behavior": "MUTE",
        "editability": "ASSET_REPLACEABLE",
        "source": "/proj/orig/A011_v1.mov",
        "original_path": "/proj/orig/A011_v1.mov",
        "local_path": "/proj/assets/A011_v1_norm.mp4",
        "proxy_path": "/proj/assets/A011_v1_proxy.mp4",
        "timeline_hint": {
            "preferred_start": 12.0,
            "preferred_duration": 4.0,
            "track_hint": "video",
            "in_point": "00:00:16.100",
            "out_point": "00:00:20.100",
            "crop": "16:9 full",
            "blend_hint": "normal",
            "overlay_safe_area": "safe",
        },
        "plan_use": {
            "recommended_in": 16.1,
            "recommended_out": 20.1,
            "audio_behavior": "MUTE",
            "timeline_hint": {"track": "V1", "preferred_crop": "16:9 full"},
        },
    }
    entry = build_entry(asset, [], "TH-001")
    checks = [
        TH_ID_RE.match(entry["handoff_id"]) is not None,
        entry["asset_id"] == "A011",
        entry["shot_id"] == "S003",
        entry["layer_id"] == "S003-L01",
        entry["preferred_track"] == "video",
        entry["preferred_duration"] == 4.0,
        entry["editability"] == "ASSET_REPLACEABLE",
        entry["audio_behavior"] == "MUTE",
        entry["in_point"] == "00:00:16.100",
        entry["crop"] == "16:9 full",
        entry["replaceable"] is True,
        entry["proxy"].endswith("_proxy.mp4"),
        # §134 头部 note
        "只提示、不创建时间线" in build_timeline_handoff([asset])["note"],
        # 排序确定性
        build_timeline_handoff([asset])["entries"]
        == build_timeline_handoff([deepcopy(asset)])["entries"],
    ]
    # shots 归属解析（无 asset.shot_id 时从 shots 匹配）
    asset2 = dict(asset)
    asset2.pop("shot_id")
    asset2.pop("layer_id")
    shots = [{"id": "S009",
              "assets": [{"asset_ref": "A011"}],
              "layers": [{"id": "S009-L02", "asset_ref": "A011"}]}]
    e2 = build_entry(asset2, shots, "TH-002")
    checks.append(e2["shot_id"] == "S009")
    checks.append(e2["layer_id"] == "S009-L02")
    # R6 边车过滤：目录内同放 _asset.json 与 _ingest.json → 只读 _asset
    import tempfile  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as td:
        tdp = _P(td)
        tdp.joinpath("A101_v1_asset.json").write_text(
            json.dumps({"asset_id": "A101", "name": "asset file", "duration": 4.0}),
            encoding="utf-8")
        tdp.joinpath("A101_v1_ingest.json").write_text(
            json.dumps({"asset_id": "A101", "name": "ingest sidecar",
                        "duration": 999.0, "__from": "ingest"}),
            encoding="utf-8")
        tdp.joinpath("A102_v1_asset.json").write_text(
            json.dumps({"asset_id": "A102", "name": "asset 2", "duration": 3.0}),
            encoding="utf-8")
        loaded = _load_assets(str(tdp))
        checks.append(len(loaded) == 2)
        checks.append(loaded[0]["asset_id"] == "A101"
                      and loaded[0].get("name") == "asset file"
                      and "__from" not in loaded[0])
        checks.append(loaded[1]["asset_id"] == "A102"
                      and loaded[1].get("duration") == 3.0)
        # 目录模式（不 assets_only）仍可读任意 *_ingest.json（shots 等通用加载不受影响）
        generic = _load_json_list(str(tdp))
        checks.append(len(generic) == 3)  # asset×2 + ingest×1
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"handoff selftest check #{i} failed")
    print("handoff selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
