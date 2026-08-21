#!/usr/bin/env python3
"""ingestion.py — External Visual Asset Ingestion 编排层（Phase-6 §42-51 / §69 /
§90-95 / §98-100；P6-04）.

统一摄取链（§42）：任何来源（API / 网页生成 / 用户上传 / 外部工具 / 素材下载）的
外部视频进入同一条链路：

    copy 原始文件 → storage 布局（§90-95）→ probe（§69）→ technical_validate
    （§100）→ audio_decision（§83-84）→ normalize 按需（§44-45）→ proxy（§46）
    → checksum(sha256) → asset JSON（对齐 asset.schema.json 扩展字段）

铁律：
- **原始文件永远保留**（§47），输出一律新文件名（``{asset_id}_v{n}_original.ext`` /
  ``_norm.mp4`` / ``_proxy.mp4``）。
- **不无脑重编码**（§45）：已满足要求 → changed=[] 且不重编码。
- model 未知写 ``UNKNOWN`` 不猜（§43）；``USER_UPLOAD`` 强制
  origin=ownership=``USER_PROVIDED`` 且绝不标为网上素材（§67-68）。
- 确定性 + 失败可重入：同 asset_id 同内容重复 ingest → 幂等返回已有记录（同 version）；
  同 asset_id 不同内容 → 版本递增（v1/v2 不覆盖，§90）。

CLI：
    python3 -m modules.external-visual.ingestion ingest   --source <f> --asset-id A001 --project-dir <dir> [--source-type USER_UPLOAD] [--meta k=v ...] [--audio-mode KEEP] [--fps 25] [--resolution 1920x1080] [--storage-policy KEEP_SELECTED_AND_PREVIEWS] [--json]
    python3 -m modules.external-visual.ingestion probe    --source <f> [--json]
    python3 -m modules.external-visual.ingestion validate --source <f> [--json]
    python3 -m modules.external-visual.ingestion normalize --source <f> [--out-dir <d>] [--out-stem <s>] [--fps 25] [--resolution 1920x1080] [--audio-mode MUTE] [--json]
    python3 -m modules.external-visual.ingestion proxy    --source <f> [--proxy-dir <d>] [--out-stem <s>] [--json]

依赖：Python3 stdlib + ffmpeg/ffprobe（subprocess，超时默认 120s）；不联网、无 LLM。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 适配器加载（Python 标识符禁止连字符，连字符包名只能 importlib 全名加载）
# ---------------------------------------------------------------------------

_ADAPTERS: dict = {}


def _adapter(name: str):
    if name not in _ADAPTERS:
        _ADAPTERS[name] = importlib.import_module(f"adapters.external-visual.{name}")
    return _ADAPTERS[name]


def probe_module():
    return _adapter("probe")


def validate_module():
    return _adapter("validate")


def audio_decision_module():
    return _adapter("audio_decision")


def color_module():
    return _adapter("color")


def normalize_module():
    return _adapter("normalize")


def proxy_module():
    return _adapter("proxy")


def storage_module():
    return _adapter("storage")


# ---------------------------------------------------------------------------
# 契约常量（§42-43 / §67-68 / §98 / §103；与 P6-01 扩展 schema 对齐，见 REPORT）
# ---------------------------------------------------------------------------

ASSET_ID_RE = re.compile(r"^A\d{3}$")

SOURCE_TYPES = (
    "API_GENERATED",      # AI Video API 生成（§42-43）
    "WEB_GENERATED",      # 网页端生成
    "USER_UPLOAD",        # 用户上传（§67：必须 ownership=USER_PROVIDED）
    "EXTERNAL_TOOL",      # 外部工具产出
    "FOOTAGE_DOWNLOAD",   # 素材下载（§42）
)

# source_type → origin（§98：GENERATED / REAL_FOOTAGE / USER_PROVIDED）
ORIGIN_FOR_SOURCE_TYPE = {
    "API_GENERATED": "GENERATED",
    "WEB_GENERATED": "GENERATED",
    "USER_UPLOAD": "USER_PROVIDED",
    "EXTERNAL_TOOL": "GENERATED",
    "FOOTAGE_DOWNLOAD": "REAL_FOOTAGE",
}
AI_GENERATED_SOURCE_TYPES = ("API_GENERATED", "WEB_GENERATED", "EXTERNAL_TOOL")

ACCEPTANCE_STATUS_DEFAULT = "CANDIDATE"   # §103：摄取后先进入候选
MODEL_UNKNOWN = "UNKNOWN"                 # §43：model 未知写 UNKNOWN 不猜


def now_iso() -> str:
    """UTC 时间戳（ISO 8601，秒精度；与 modules/production/planner.py 同款）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def sha256_file(path) -> str:
    """流式 sha256（确定性；大文件不整读内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _require_asset_id(asset_id) -> str:
    aid = str(asset_id or "").strip().upper()
    if not ASSET_ID_RE.match(aid):
        raise ValueError(f"asset_id 必须匹配 A###，得到 {asset_id!r}")
    return aid


def _normalize_source_type(value) -> str:
    st = str(value or "USER_UPLOAD").strip().upper()
    if st not in SOURCE_TYPES:
        raise ValueError(
            f"source_type={value!r} 不在五枚举内：{sorted(SOURCE_TYPES)}")
    return st


# ---------------------------------------------------------------------------
# asset JSON 构建（对齐 asset.schema.json 扩展字段，§43/§98-100；P6-01 已落盘扩展）
# ---------------------------------------------------------------------------

# ownership 枚举对齐（§68：USER_PROVIDED/PROJECT/PURCHASED/LICENSED/PUBLIC_DOMAIN/UNKNOWN）
OWNERSHIP_FOR_SOURCE_TYPE = {
    "API_GENERATED": "PROJECT",
    "WEB_GENERATED": "PROJECT",
    "USER_UPLOAD": "USER_PROVIDED",
    "EXTERNAL_TOOL": "PROJECT",
    "FOOTAGE_DOWNLOAD": "LICENSED",
}


def _build_asset_json(asset_id: str, meta: dict, source_type: str,
                      src: Path, orig_path: Path, norm_result: dict,
                      proxy_result: dict, probe: dict, color: dict,
                      storage_policy: str, version: int,
                      src_sha: str) -> dict:
    """按扩展后的 asset.schema.json 生成 **schema-valid** asset JSON。

    - required 字符串字段缺失时给诚实默认（license=UNKNOWN 不猜，§43 政策；
      purpose/timeline_usage 标注"未提供"），保证 21 个 required 全非 null。
    - 可选字段无值 → **省略该键**（P6-01 schema 的 string 字段不接受 null）。
    - verbose 明细（normalization changed / audio reason / proxy rationale /
      完整 probe）由 ingest() 另写 ``{asset}_v{n}_ingest.json`` 边车。
    """
    video = probe.get("video") or {}
    duration = probe.get("duration")
    norm_path = Path(norm_result["output_path"])
    is_norm_same = norm_path.resolve() == orig_path.resolve()
    fps = norm_result.get("target", {}).get("fps") or video.get("fps")
    t_res = norm_result.get("target", {}).get("resolution")
    if is_norm_same:
        width, height = video.get("width"), video.get("height")
    elif isinstance(t_res, dict) and t_res.get("w") and t_res.get("h"):
        width, height = int(t_res["w"]), int(t_res["h"])
    else:
        width, height = video.get("width"), video.get("height")
    rot = video.get("rotation")
    if rot in (90, 270):
        width, height = height, width

    timeline_hint = _drop_none({
        "preferred_start": 0,
        "preferred_duration": round(float(duration), 3) if duration else None,
        "track_hint": "video",
    })

    origin = meta.get("origin") or ORIGIN_FOR_SOURCE_TYPE[source_type]
    if source_type == "USER_UPLOAD":
        origin = "USER_PROVIDED"
    ownership = OWNERSHIP_FOR_SOURCE_TYPE[source_type]
    if meta.get("ownership"):
        ownership = str(meta["ownership"]).upper()

    audio_mode = str(norm_result.get("audio_mode") or "KEEP").upper()
    proxy_generated = bool(proxy_result.get("generated"))
    proxy_path = proxy_result.get("proxy_path")

    # media_probe 只保留有值的键（§48/§69；gamma 转字符串对齐 schema）
    media_probe = _drop_none({
        "duration": round(float(duration), 6) if duration else None,
        "resolution": {"w": video.get("width"), "h": video.get("height")},
        "fps": round(float(video.get("fps")), 6) if video.get("fps") else None,
        "codec": video.get("codec"),
        "bitrate": video.get("bitrate") or probe.get("bitrate"),
        "audio_streams": probe.get("audio_streams"),
        "aspect_ratio": video.get("aspect_ratio"),
        "rotation": video.get("rotation"),
        "color_space": video.get("color_space"),
        "transfer": video.get("color_transfer"),
        "gamma": str(color.get("gamma")) if color.get("gamma") is not None else None,
        "hdr": color.get("hdr") == "HDR",
        "source_look": color.get("source_look"),
    })

    doc = _drop_none({
        # —— asset.schema required（Phase-1/5 既有；缺失给诚实默认）——
        "asset_id": asset_id,
        "name": meta.get("name") or asset_id,
        "type": meta.get("type") or "FOOTAGE",
        "purpose": meta.get("purpose") or "external visual asset（未提供 purpose）",
        "producer": "EXTERNAL_VISUAL",
        "source": str(src.resolve()),
        "local_path": str(norm_path),
        "format": "mp4",
        "resolution": {"w": width, "h": height},
        "fps": round(float(fps), 6) if fps else None,
        "duration": round(float(duration), 6) if duration else None,
        "alpha": False,
        "version": f"v{version}",
        "license": meta.get("license") or "UNKNOWN",   # 政策：UNKNOWN 不猜（§43）
        "license_url": meta.get("license_url") or "",
        "attribution_required": bool(meta.get("attribution_required", False)),
        "commercial_use": bool(meta.get("commercial_use", True)),
        "preview": proxy_path,
        "cached": True,
        "replaceable": True,
        "timeline_usage": meta.get("timeline_usage") or "external visual asset（未指定）",
        "timeline_hint": timeline_hint,
        "status": "completed",
        "created_at": now_iso(),
        "modified_at": now_iso(),
        # —— Phase-6 扩展（对齐 P6-01 扩展后的 asset.schema.json）——
        "source_type": source_type,
        "provider": meta.get("provider"),
        "model": meta.get("model") or MODEL_UNKNOWN,          # §43：UNKNOWN 不猜
        "generation_date": meta.get("generation_date"),
        "prompt_packet_id": meta.get("prompt_packet_id"),
        "variant_id": meta.get("variant_id"),
        "origin": origin,                                     # §98 3 枚举
        "ownership": ownership,                               # §68 6 枚举
        "checksum": src_sha,                                  # §43 sha256 hex
        "original_path": str(orig_path),                      # §47 原始文件路径
        "proxy_path": proxy_path,                             # §46
        "proxy_resolution": "1080p H.264" if proxy_generated else None,
        "media_probe": media_probe,                           # §48/§69 技术档案
        "audio_behavior": audio_mode,                         # §83-84 5 枚举（string）
        "storage_policy": storage_policy,                     # §94
        "acceptance_status": ACCEPTANCE_STATUS_DEFAULT,       # §103 CANDIDATE
        "review_ref": None,                                   # 审核通过后由 review 回填
        "provenance_ref": None,                               # §96 PV-###（允许 null）
        "rejected_variants": [],                              # §93 被拒变体（storage 层记录）
        # §99 Content Credentials：仅 metadata 槽位，Phase 6 不实现 C2PA
        "content_credentials": {
            "signed": False,
            "authority": None,
            "note": "Phase-6 §99：仅元数据槽位，未实现 C2PA 签名",
        },
    })
    return doc


def _drop_none(doc: dict) -> dict:
    """去掉值为 None 的键（schema string 字段不接受 null；required 已给默认）。"""
    return {k: v for k, v in doc.items() if v is not None}


def _build_ingest_details(asset_id: str, probe: dict, validation: dict,
                          audio_dec: dict, norm_result: dict, proxy_result: dict,
                          color: dict, ai_generated: bool,
                          online_material: bool) -> dict:
    """摄取明细边车（写 ``{asset}_v{n}_ingest.json``，供审计/自测，不进 schema）。"""
    return {
        "asset_id": asset_id,
        "media_probe_full": probe,
        "validation": validation,
        "audio_behavior": audio_dec,
        "normalization": {
            "changed": norm_result.get("changed", []),
            "notes": norm_result.get("notes", []),
            "reencoded": norm_result.get("reencoded", False),
            "target": norm_result.get("target"),
        },
        "proxy": proxy_result,
        "color": color,
        "ai_generated": bool(ai_generated),
        "online_material": bool(online_material),
        "schema_note": "本文件为摄取明细边车，未写入 asset.schema.json（additionalProperties=false）",
    }


def _reload_ingest_details(adir, asset_id: str, version: int,
                           orig_path, existing: Optional[dict] = None) -> tuple:
    """幂等重入时从边车读回摄取明细；边车缺失则重建最小 details。

    返回 (details, validation_ok)：
    - 边车存在 → 原样读回；validation_ok = details["validation"]["ok"]（真实值）。
    - 边车缺失/损坏 → 重建键形状对齐 _build_ingest_details 的 details（details
      键必须存在，且含 CLI/调用方消费的 validation / normalization / proxy /
      online_material 槽位），validation_ok 用真实重验 technical_validate 的结果
      （明确语义，不记永假 / 永不 None）。重建的缺失明细用空值 + note 注明，不伪造。
    """
    detail_path = adir / f"{asset_id}_v{version}_ingest.json"
    if detail_path.is_file():
        try:
            details = json.loads(detail_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            details = None
        if isinstance(details, dict):
            validation = details.get("validation") or {}
            return details, validation.get("ok")
    # 边车缺失 → 重验并重建最小 details（幂等读路径不写回边车）
    probe = probe_module().probe_video(str(orig_path))
    validation = validate_module().technical_validate(str(orig_path), probe)
    existing = existing if isinstance(existing, dict) else {}
    source_type = str(existing.get("source_type") or "USER_UPLOAD")
    online_material = (False if source_type == "USER_UPLOAD"
                       else bool(existing.get("online_material",
                                              source_type == "FOOTAGE_DOWNLOAD")))
    proxy_path = existing.get("proxy_path")
    proxy_generated = bool(proxy_path and str(proxy_path)
                           and Path(str(proxy_path)).is_file()
                           and Path(str(proxy_path)).resolve()
                           != Path(str(orig_path)).resolve())
    return {
        "asset_id": asset_id,
        "media_probe_full": probe,
        "validation": validation,
        "audio_behavior": {"mode": existing.get("audio_behavior")},
        "normalization": {
            "changed": [], "notes": ["边车缺失，重建最小 details（未保留原变更记录）"],
            "reencoded": False, "target": None,
        },
        "proxy": {"generated": proxy_generated, "proxy_path": proxy_path,
                  "rationale": "边车缺失，重建最小 details"},
        "color": {},
        "ai_generated": existing.get("origin") == "GENERATED",
        "online_material": online_material,
        "schema_note": "本文件为摄取明细边车（重建最小形态：原边车缺失时重验生成）",
    }, validation.get("ok")


# ---------------------------------------------------------------------------
# 编排：ingest（§42-51 / §67-68 / §90-95）
# ---------------------------------------------------------------------------

def ingest(source_file, asset_meta: dict, project_dir, opts: Optional[dict] = None) -> dict:
    """完整摄取链（§42）。

    参数：
        source_file  外部视频路径（**永不修改/删除**）
        asset_meta   {asset_id, name, type, purpose, source_type, provider, model,
                      generation_date, prompt_packet_id, variant_id, license,
                      license_url, attribution_required, commercial_use, origin,
                      ownership, shot_id, layer_id, timeline_usage}
        project_dir  项目根目录（存储布局 <project>/assets/external-visual/）
        opts         {target, audio_direction, packet_audio_requirement,
                      storage_policy, ai_generated}

    返回：{asset, original_path, norm_path, proxy_path, checksum, version,
          idempotent, validation_ok}。失败抛 ValueError（可重入，不破坏已有文件）。
    """
    src = Path(source_file)
    project = Path(project_dir)
    meta = dict(asset_meta or {})
    opts = dict(opts or {})

    if not src.is_file():
        raise ValueError(f"源文件不存在或不可读: {src}")
    asset_id = _require_asset_id(meta.get("asset_id"))
    source_type = _normalize_source_type(meta.get("source_type"))

    # §67-68：USER_UPLOAD 强制 origin=ownership=USER_PROVIDED，绝不标网上素材
    if source_type == "USER_UPLOAD":
        meta["origin"] = "USER_PROVIDED"
        meta["ownership"] = "USER_PROVIDED"
        meta["online_material"] = False

    ai_generated = bool(opts.get("ai_generated",
                                 source_type in AI_GENERATED_SOURCE_TYPES))

    storage = storage_module()
    adir = storage.asset_dir(project, asset_id)
    adir.mkdir(parents=True, exist_ok=True)

    # —— 版本 + 幂等（§90；失败可重入）——
    src_sha = sha256_file(src)
    version = None
    for v in range(1, 10000):
        orig_candidate = adir / f"{asset_id}_v{v}_original{src.suffix}"
        if not orig_candidate.exists():
            version = v
            break
        if sha256_file(orig_candidate) == src_sha:
            version = v  # 同内容 → 幂等复用该版本
            break
    if version is None:
        raise ValueError(f"asset {asset_id} 版本号耗尽（>9999），中止")

    orig_path = adir / f"{asset_id}_v{version}_original{src.suffix}"
    json_path = adir / f"{asset_id}_v{version}_asset.json"

    if orig_path.exists() and sha256_file(orig_path) == src_sha:
        # 幂等重入：同一文件同一版本已摄取（返回结构对齐主路径：asset/details 都在）
        if json_path.is_file():
            try:
                existing = json.loads(json_path.read_text(encoding="utf-8"))
                details, validation_ok = _reload_ingest_details(
                    adir, asset_id, version, orig_path, existing)
                return {"asset": existing, "details": details,
                        "original_path": str(orig_path),
                        "norm_path": existing.get("local_path"),
                        "proxy_path": existing.get("proxy_path"),
                        "checksum": src_sha, "version": f"v{version}",
                        "idempotent": True,
                        "validation_ok": validation_ok,
                        "storage_dir": str(adir)}
            except (OSError, ValueError):
                pass  # 元数据损坏 → 重新摄取该版本（不覆盖原文件）

    # 1) copy 原始文件（§47 / §90：新文件名，永不覆盖已有）
    if not (orig_path.exists() and sha256_file(orig_path) == src_sha):
        shutil.copy2(src, orig_path)

    # 2) probe（§69）
    probe = probe_module().probe_video(str(orig_path))

    # 3) technical validate（§100）
    validation = validate_module().technical_validate(str(orig_path), probe)

    # 4) audio decision（§83-84）
    audio_dec = audio_decision_module().decide_audio_detailed(
        probe,
        audio_direction=opts.get("audio_direction"),
        packet_audio_requirement=opts.get("packet_audio_requirement"),
        ai_generated=ai_generated, source_type=source_type,
    )

    # 5) normalize（§44-45：按需，绝不无脑重编码）
    target = dict(opts.get("target") or {})
    target.setdefault("container", "mp4")
    target.setdefault("codec", "h264")
    target.setdefault("audio_mode", audio_dec.get("mode", "KEEP"))
    norm_result = normalize_module().normalize(
        str(orig_path), probe, target, out_dir=adir,
        out_stem=f"{asset_id}_v{version}",
    )

    # 6) proxy（§46）
    proxy_result = proxy_module().make_proxy(
        str(orig_path), probe, proxy_dir=adir, out_stem=f"{asset_id}_v{version}",
    )

    # 7) checksum（sha256，原文件）
    checksum = sha256_file(orig_path)

    # 8) asset JSON（schema-valid，新文件名不覆盖）+ 摄取明细边车
    color = color_module().color_metadata(probe)
    storage_policy = str(opts.get("storage_policy")
                         or storage.DEFAULT_STORAGE_POLICY).upper()
    online_material = (False if source_type == "USER_UPLOAD"
                       else bool(meta.get("online_material",
                                          source_type == "FOOTAGE_DOWNLOAD")))
    asset = _build_asset_json(
        asset_id, meta, source_type, src, orig_path, norm_result, proxy_result,
        probe, color, storage_policy, version, checksum,
    )
    details = _build_ingest_details(
        asset_id, probe, validation, audio_dec, norm_result, proxy_result,
        color, ai_generated, online_material,
    )
    json_path.write_text(json.dumps(asset, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    detail_path = adir / f"{asset_id}_v{version}_ingest.json"
    detail_path.write_text(json.dumps(details, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    return {"asset": asset, "details": details,
            "original_path": str(orig_path),
            "norm_path": str(norm_result["output_path"]),
            "proxy_path": str(proxy_result["proxy_path"]),
            "checksum": checksum, "version": f"v{version}",
            "idempotent": False, "validation_ok": validation.get("ok"),
            "storage_dir": str(adir)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_meta(pairs) -> dict:
    out: dict = {}
    for item in pairs:
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"--meta 需 k=v 格式，得到 {item!r}")
        k, _, v = item.partition("=")
        if v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        else:
            out[k] = v
    return out


def _parse_resolution(text) -> Optional[dict]:
    if not text:
        return None
    m = re.fullmatch(r"(\d+)x(\d+)", str(text).strip())
    if not m:
        raise argparse.ArgumentTypeError(f"分辨率需 WxH 格式，得到 {text!r}")
    return {"w": int(m.group(1)), "h": int(m.group(2))}


def _json_or_text(payload: dict, as_json: bool) -> str:
    if as_json:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    summary = payload.get("summary", payload)
    lines = []
    for k, v in summary.items():
        if isinstance(v, (dict, list)):
            lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _cmd_ingest(args) -> dict:
    meta = dict(args.meta or {})
    meta.setdefault("asset_id", args.asset_id)
    meta.setdefault("source_type", args.source_type)
    target: dict = {}
    if args.fps is not None:
        target["fps"] = float(args.fps)
    if args.resolution:
        target["resolution"] = _parse_resolution(args.resolution)
    if args.audio_mode:
        target["audio_mode"] = args.audio_mode.upper()
    result = ingest(
        args.source, meta, args.project_dir,
        opts={"target": target, "storage_policy": args.storage_policy},
    )
    details = result["details"]
    return {"summary": {
        "asset_id": result["asset"]["asset_id"],
        "version": result["version"],
        "idempotent": result["idempotent"],
        "source_type": result["asset"]["source_type"],
        "origin": result["asset"]["origin"],
        "ownership": result["asset"]["ownership"],
        "model": result["asset"]["model"],
        "original_path": result["original_path"],
        "norm_path": result["norm_path"],
        "proxy_path": result["proxy_path"],
        "checksum": result["checksum"],
        "normalization_changed": details["normalization"]["changed"],
        "audio_mode": result["asset"]["audio_behavior"],
        "validation_ok": result["validation_ok"],
        "validation_issues": details["validation"]["issues"],
    }, "asset": result["asset"], "details": details}


def _cmd_probe(args) -> dict:
    p = probe_module().probe_video(args.source)
    return {"summary": {
        "path": p.get("path"),
        "ok": p.get("ok"),
        "error": p.get("error"),
        "duration": p.get("duration"),
        "resolution": {"w": (p.get("video") or {}).get("width"),
                       "h": (p.get("video") or {}).get("height")},
        "fps": (p.get("video") or {}).get("fps"),
        "codec": (p.get("video") or {}).get("codec"),
        "rotation": (p.get("video") or {}).get("rotation"),
        "audio_streams": p.get("audio_streams"),
    }, "probe": p}


def _cmd_validate(args) -> dict:
    v = validate_module().technical_validate(args.source)
    return {"summary": {
        "ok": v["ok"],
        "issues": v["issues"],
        "warnings": v["warnings"],
    }, "validation": v}


def _cmd_normalize(args) -> dict:
    target: dict = {}
    if args.fps is not None:
        target["fps"] = float(args.fps)
    if args.resolution:
        target["resolution"] = _parse_resolution(args.resolution)
    if args.audio_mode:
        target["audio_mode"] = args.audio_mode.upper()
    if args.orientation:
        target["orientation"] = args.orientation
    r = normalize_module().normalize(
        args.source, None, target, out_dir=args.out_dir, out_stem=args.out_stem,
    )
    return {"summary": {
        "output_path": r["output_path"],
        "changed": r["changed"],
        "notes": r["notes"],
        "reencoded": r["reencoded"],
        "audio_artifact": r["audio_artifact"],
    }, "normalize": r}


def _cmd_proxy(args) -> dict:
    r = proxy_module().make_proxy(
        args.source, None, proxy_dir=args.proxy_dir, out_stem=args.out_stem,
    )
    return {"summary": {
        "proxy_path": r["proxy_path"],
        "generated": r["generated"],
        "rationale": r["rationale"],
    }, "proxy": r}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m modules.external-visual.ingestion",
        description="External Visual Asset Ingestion（Phase-6 §42-51/§69/§90-95/§98-100）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="完整摄取链")
    p_ingest.add_argument("--source", required=True)
    p_ingest.add_argument("--asset-id", required=True)
    p_ingest.add_argument("--project-dir", default=".")
    p_ingest.add_argument("--source-type", default="USER_UPLOAD",
                          choices=SOURCE_TYPES)
    p_ingest.add_argument("--meta", action="append", default=[],
                          help="k=v 元数据（可多次），如 --meta provider=user --meta license=CC0")
    p_ingest.add_argument("--fps", type=float)
    p_ingest.add_argument("--resolution", help="WxH，如 1920x1080")
    p_ingest.add_argument("--audio-mode")
    p_ingest.add_argument("--storage-policy", default=None)
    p_ingest.add_argument("--json", action="store_true")

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--source", required=True)
    p_probe.add_argument("--json", action="store_true")

    p_val = sub.add_parser("validate")
    p_val.add_argument("--source", required=True)
    p_val.add_argument("--json", action="store_true")

    p_norm = sub.add_parser("normalize")
    p_norm.add_argument("--source", required=True)
    p_norm.add_argument("--out-dir")
    p_norm.add_argument("--out-stem")
    p_norm.add_argument("--fps", type=float)
    p_norm.add_argument("--resolution")
    p_norm.add_argument("--audio-mode")
    p_norm.add_argument("--orientation")
    p_norm.add_argument("--json", action="store_true")

    p_proxy = sub.add_parser("proxy")
    p_proxy.add_argument("--source", required=True)
    p_proxy.add_argument("--proxy-dir")
    p_proxy.add_argument("--out-stem")
    p_proxy.add_argument("--json", action="store_true")
    return parser


_COMMANDS = {
    "ingest": _cmd_ingest,
    "probe": _cmd_probe,
    "validate": _cmd_validate,
    "normalize": _cmd_normalize,
    "proxy": _cmd_proxy,
}


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in _COMMANDS:
        parser.error(f"未知命令 {args.command!r}")
    try:
        if args.command == "ingest":
            args.meta = _parse_meta(args.meta or [])
        result = _COMMANDS[args.command](args)
        print(_json_or_text(result, getattr(args, "json", False)))
        return 0
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    assert ASSET_ID_RE.match("A001")
    assert not ASSET_ID_RE.match("A01")
    assert _normalize_source_type("user_upload") == "USER_UPLOAD"
    assert _normalize_source_type("FOOTAGE_DOWNLOAD") == "FOOTAGE_DOWNLOAD"
    assert ORIGIN_FOR_SOURCE_TYPE["USER_UPLOAD"] == "USER_PROVIDED"
    assert MODEL_UNKNOWN == "UNKNOWN"
    print("modules/external-visual/ingestion selftest OK")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main())
    selftest()
