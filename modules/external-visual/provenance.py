#!/usr/bin/env python3
"""provenance.py — VISUAL_PROVENANCE_MANIFEST 生成器（Phase-6 §96-99；P6-07）.

每个外部视觉资产一条 PV-### 溯源记录（schemas/provenance-manifest.schema.json 条目）：
asset_ref / source_type / source / provider / model / prompt_packet_id / license /
ownership / generation_date / original_file / normalized_file / usage，
外加 content_credentials 槽位原样带出（§99，Phase 6 只预留不实现 C2PA）。

- 数据聚合自 asset JSON 的扩展字段（origin / source_type / provider / model /
  prompt_packet_id / checksum / original_path / local_path / content_credentials 等，
  P6-04 ingestion 产物）。
- **6 问全覆盖**（§97）：哪来 / AI 还是实拍 / 版权 / Prompt / 能否重生成 / 能否商用。
  答案字段缺省一律写 UNKNOWN（禁止猜值，§43 政策），并在容器级 `entry_notes`
  标注缺省原因（schema additionalProperties=false，notes 放在 manifest 层，
  与条目 provenance_id 一一对应）。
- 全确定性：按 asset_ref 排序；无 LLM、无联网。

CLI：
    python3 -m modules.external-visual.provenance <assets_dir|asset_jsons...> \
        [--packets <packets_dir>] [--out <out.json>] [--project <id>] [--json]

技术约束：Python3 stdlib only；确定性；无第三方依赖。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PV_ID_RE = re.compile(r"^PV-\d{3}$")
ASSET_ID_RE = re.compile(r"^A\d{3}$")

#: source_type 五枚举（§42-43，与 asset.schema / ingestion.py 对齐）
SOURCE_TYPES = (
    "API_GENERATED",      # API 自动生成
    "WEB_GENERATED",      # 网页端生成
    "USER_UPLOAD",        # 用户上传
    "EXTERNAL_TOOL",      # 外部工具产出
    "FOOTAGE_DOWNLOAD",   # 素材下载
)
#: 判"AI 生成"的 source_type（§98 origin=GENERATED 的 3 个来源方式）
AI_GENERATED_TYPES = ("API_GENERATED", "WEB_GENERATED", "EXTERNAL_TOOL")

#: ownership 六枚举（§68）
OWNERSHIPS = (
    "USER_PROVIDED", "PROJECT", "PURCHASED", "LICENSED", "PUBLIC_DOMAIN", "UNKNOWN",
)
#: source_type → 缺省 ownership（与 ingestion.py OWNERSHIP_FOR_SOURCE_TYPE 对齐）
_OWNERSHIP_FOR_SOURCE_TYPE = {
    "API_GENERATED": "PROJECT",
    "WEB_GENERATED": "PROJECT",
    "USER_UPLOAD": "USER_PROVIDED",
    "EXTERNAL_TOOL": "PROJECT",
    "FOOTAGE_DOWNLOAD": "LICENSED",
}
#: source_type → origin（§98）
_ORIGIN_FOR_SOURCE_TYPE = {
    "API_GENERATED": "GENERATED",
    "WEB_GENERATED": "GENERATED",
    "USER_UPLOAD": "USER_PROVIDED",
    "EXTERNAL_TOOL": "GENERATED",
    "FOOTAGE_DOWNLOAD": "REAL_FOOTAGE",
}

MODEL_UNKNOWN = "UNKNOWN"
LICENSE_UNKNOWN = "UNKNOWN"


def now_iso() -> str:
    """UTC 时间戳（ISO 8601，秒精度；与 modules/production/planner.py 同款）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 输入归一化
# ---------------------------------------------------------------------------

def _is_asset_dict(obj: Any) -> bool:
    return isinstance(obj, dict) and bool(obj.get("asset_id"))


def _load_assets(spec) -> list:
    """把 assets 输入归一为 asset dict 列表。

    支持：
    - 目录路径：读取目录下 JSON，只保留含 asset_id 的对象（优先 *_asset.json；
      R6 边车过滤：任何情况下跳过 *_ingest.json 边车 —— 否则回退 glob("*.json")
      时会读入边车（其顶层含 asset_id），且 by_id 去重"保留最后一份"会以边车
      内容覆盖正式资产文件，字典序 X_asset.json < X_ingest.json 后置必覆盖）。
    - 文件路径：JSON 可为单个 asset dict / asset 列表 / {"assets": [...]}。
    - 已是 dict / list：原样规整。
    """
    out: list = []
    if isinstance(spec, (str, Path)):
        p = Path(spec)
        if p.is_dir():
            files = sorted(p.glob("*_asset.json")) or sorted(p.glob("*.json"))
            files = [f for f in files if not f.name.endswith("_ingest.json")]
            for f in files:
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                out.extend(_collect_assets(data))
        elif p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            out.extend(_collect_assets(data))
        else:
            raise ValueError(f"assets 路径不存在: {p}")
    elif isinstance(spec, list):
        for item in spec:
            out.extend(_collect_assets(item))
    elif isinstance(spec, dict):
        out.extend(_collect_assets(spec))
    else:
        raise ValueError(f"不支持的 assets 输入: {type(spec).__name__}")

    # 去重（同 asset_id 保留最后一份）并校验
    by_id: dict = {}
    for a in out:
        if not _is_asset_dict(a):
            continue
        by_id[str(a["asset_id"])] = a
    return [by_id[k] for k in sorted(by_id)]


def _collect_assets(data: Any) -> list:
    if _is_asset_dict(data):
        return [data]
    if isinstance(data, list):
        return [d for d in data if _is_asset_dict(d)]
    if isinstance(data, dict):
        for key in ("assets", "entries", "items"):
            if isinstance(data.get(key), list):
                return [d for d in data[key] if _is_asset_dict(d)]
    return []


def _load_packets(spec) -> dict:
    """packets 输入归一为 {packet_id: packet}；None/缺省 → {}。"""
    if spec is None:
        return {}
    out: dict = {}
    if isinstance(spec, (str, Path)):
        p = Path(spec)
        if p.is_dir():
            for f in sorted(p.glob("GV-*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and data.get("packet_id"):
                    out[str(data["packet_id"])] = data
        elif p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("packet_id"):
                out[str(data["packet_id"])] = data
    elif isinstance(spec, list):
        for item in spec:
            if isinstance(item, dict) and item.get("packet_id"):
                out[str(item["packet_id"])] = item
    elif isinstance(spec, dict):
        for k, v in spec.items():
            if isinstance(v, dict):
                out[k] = v
    return out


# ---------------------------------------------------------------------------
# 单条 PV 条目构建（§96-97；条目 schema-valid，缺省不猜值）
# ---------------------------------------------------------------------------

def _default(value: Any, fallback: Any = "UNKNOWN") -> Any:
    """空值（None/''）→ fallback；非空原样返回。"""
    if value is None or value == "":
        return fallback
    return value


def _resolve_source_type(asset: dict) -> tuple:
    """确定性推导 source_type（schema 枚举无 UNKNOWN，必须返回 5 枚举之一）。

    优先级：asset.source_type 合法值 > 按 origin 映射（§98）> 按 ownership/
    producer 保守映射 > 兜底 EXTERNAL_TOOL。返回 (value, derived: bool)。
    derived=True 表示非直接记录、由其他字段推导，调用方应在 notes 标注。
    """
    st = str(asset.get("source_type") or "").upper()
    if st in SOURCE_TYPES:
        return st, False
    origin = str(asset.get("origin") or "").upper()
    if origin == "USER_PROVIDED":
        return "USER_UPLOAD", True
    if origin == "REAL_FOOTAGE":
        return "FOOTAGE_DOWNLOAD", True
    if origin == "GENERATED":
        return "EXTERNAL_TOOL", True
    ownership = str(asset.get("ownership") or "").upper()
    if ownership == "USER_PROVIDED":
        return "USER_UPLOAD", True
    producer = str(asset.get("producer") or "").upper()
    if producer in ("EXTERNAL_VISUAL", "GENERATIVE_VIDEO", "FOOTAGE_PROVIDER", "USER"):
        return {"EXTERNAL_VISUAL": "EXTERNAL_TOOL",
                "GENERATIVE_VIDEO": "EXTERNAL_TOOL",
                "FOOTAGE_PROVIDER": "FOOTAGE_DOWNLOAD",
                "USER": "USER_UPLOAD"}[producer], True
    return "EXTERNAL_TOOL", True


def build_entry(asset: dict, packets: Optional[dict] = None,
                provenance_id: str = "PV-001") -> dict:
    """从单个 asset dict 构建一条 schema-valid 的 PV 条目。

    所有 required 字段都给值；未知一律 UNKNOWN（§43 不猜）。
    `entry_notes`（缺省说明）不放进条目（schema additionalProperties=false），
    由调用方归入 manifest 层。
    """
    packets = packets or {}
    aid = str(asset.get("asset_id") or "")
    source_type, source_type_derived = _resolve_source_type(asset)

    origin = _default(str(asset.get("origin") or "").upper(), None)
    if not source_type_derived:
        origin = _ORIGIN_FOR_SOURCE_TYPE.get(source_type, origin)
    ownership = _default(str(asset.get("ownership") or "").upper(), None)
    if ownership not in OWNERSHIPS:
        ownership = _OWNERSHIP_FOR_SOURCE_TYPE.get(source_type, "UNKNOWN")
        if ownership not in OWNERSHIPS:
            ownership = "UNKNOWN"

    provider = asset.get("provider")
    if not provider and source_type == "USER_UPLOAD":
        provider = "user"
    if not provider:
        provider = "UNKNOWN"

    model = asset.get("model") or MODEL_UNKNOWN
    prompt_packet_id = asset.get("prompt_packet_id") or None  # schema 允许 null
    if prompt_packet_id is not None:
        prompt_packet_id = str(prompt_packet_id)

    entry = {
        "provenance_id": provenance_id,
        "asset_ref": aid or "UNKNOWN",
        "source_type": source_type,
        "source": _default(asset.get("source") or asset.get("original_path")),
        "provider": provider,
        "model": str(model),
        "prompt_packet_id": prompt_packet_id,
        "license": _default(asset.get("license"), LICENSE_UNKNOWN),
        "ownership": ownership,
        "generation_date": _default(asset.get("generation_date")
                                    or asset.get("created_at")),
        "original_file": _default(asset.get("original_path") or asset.get("source")),
        "normalized_file": _default(asset.get("local_path")),
        "usage": _default(asset.get("timeline_usage") or asset.get("purpose")),
    }
    # §99 content_credentials：原样带出（仅在 asset 提供了 dict 时）
    cc = asset.get("content_credentials")
    if isinstance(cc, dict):
        entry["content_credentials"] = {
            "signed": bool(cc.get("signed", False)),
            "authority": cc.get("authority"),
            "note": _default(cc.get("note"),
                             "Phase-6 §99：Content Credentials 仅为 metadata 槽位，"
                             "未实现 C2PA 签名"),
        }
    # §58 可选溯源增强（source_institution/original_page/creator/retrieval_date）
    if isinstance(asset.get("provenance"), dict):
        pv = asset["provenance"]
        if pv.get("source_institution"):
            entry["source_institution"] = str(pv["source_institution"])
        if pv.get("original_page"):
            entry["original_page"] = str(pv["original_page"])
        if pv.get("creator"):
            entry["creator"] = str(pv["creator"])
        if pv.get("retrieval_date"):
            entry["retrieval_date"] = str(pv["retrieval_date"])
    return entry


# ---------------------------------------------------------------------------
# §97 六问（6 questions）：哪来 / AI 还是实拍 / 版权 / Prompt / 能否重生成 / 能否商用
# ---------------------------------------------------------------------------

def six_questions(entry: dict, packets: Optional[dict] = None) -> dict:
    """对一条 PV 条目回答 §97 的 6 个问题。

    全部确定性推导；信息不足 → UNKNOWN / 待审，绝不猜值：
    - where_from    哪来（source + provider + source_type）
    - ai_or_real    AI 生成 / 实拍 / 用户素材（由 source_type 判 origin）
    - copyright     版权（license + ownership；license=UNKNOWN → LICENSE_REVIEW_REQUIRED）
    - prompt        Prompt（prompt_packet_id + packet 内容摘要）
    - regenerable   能否重生成（AI 生成且 model/prompt 齐 → 可；实拍/用户素材 → 否）
    - commercial    能否商用（license 已知 + commercial_use 标志；未知 → 待审）
    """
    packets = packets or {}
    st = entry.get("source_type")
    source = entry.get("source")
    provider = entry.get("provider")
    model = entry.get("model")
    pid = entry.get("prompt_packet_id")
    license_ = entry.get("license")
    ownership = entry.get("ownership")

    # 1. 哪来
    where = f"source_type={st}; source={source}; provider={provider}"
    # 2. AI 还是实拍
    origin = _ORIGIN_FOR_SOURCE_TYPE.get(st)
    if origin is None:
        if st == "USER_UPLOAD":
            origin = "USER_PROVIDED"
        elif st == "UNKNOWN":
            origin = "UNKNOWN"
    ai_or_real = {"GENERATED": "AI 生成", "REAL_FOOTAGE": "实拍",
                  "USER_PROVIDED": "用户素材"}.get(origin, "UNKNOWN")
    # 3. 版权
    if license_ in (None, "", "UNKNOWN"):
        copyright_ = "UNKNOWN → LICENSE_REVIEW_REQUIRED（§63，不得当 Commercial Safe）"
    else:
        copyright_ = f"license={license_}; ownership={ownership}"
    # 4. Prompt
    if pid:
        pkt = packets.get(pid) if isinstance(packets, dict) else None
        if pkt and pkt.get("model_ready_prompt"):
            prompt_ = f"packet={pid}; prompt 已记录（长度 {len(str(pkt['model_ready_prompt']))} 字符）"
        elif pkt:
            prompt_ = f"packet={pid}; packet 已存在但未含 model_ready_prompt"
        else:
            prompt_ = f"packet={pid}; packet 文件缺失（无法回看 Prompt 全文）"
    else:
        prompt_ = "UNKNOWN（未记录 prompt_packet_id；非生成类或未关联生产包）"
    # 5. 能否重生成
    if st in AI_GENERATED_TYPES:
        if model not in (None, "", "UNKNOWN") and pid:
            regenerable = "可重新生成（model 与 prompt_packet 已知）"
        else:
            regenerable = "UNKNOWN（AI 生成但 model/prompt 缺失，无法确认可重生成性）"
    elif st == "FOOTAGE_DOWNLOAD":
        regenerable = "否（实拍素材，不可由本系统重新生成）"
    elif st == "USER_UPLOAD":
        regenerable = "否（用户素材，不可由本系统重新生成）"
    else:
        regenerable = "UNKNOWN（source_type 未知）"
    # 6. 能否商用
    if license_ in (None, "", "UNKNOWN"):
        commercial = "UNKNOWN → LICENSE_REVIEW_REQUIRED（§63，License 未审查前不得商用）"
    elif str(license_).upper() in ("CC0", "CC0-1.0", "PUBLIC_DOMAIN", "PD"):
        commercial = "可商用（CC0/Public Domain）"
    elif str(ownership or "").upper() in ("USER_PROVIDED", "PROJECT", "PURCHASED"):
        commercial = "可商用（自有/项目自产/已购买）"
    else:
        commercial = "需按 License 条款人工确认（LICENSE_REVIEW_REQUIRED）"

    return {
        "where_from": where,
        "ai_or_real": ai_or_real,
        "copyright": copyright_,
        "prompt": prompt_,
        "regenerable": regenerable,
        "commercial": commercial,
    }


def entry_notes(asset: dict, entry: dict) -> list:
    """收集本条目的缺省/未知标注（UNKNOWN 不猜值的原因，供 manifest 层展示）。"""
    notes: list = []
    aid = str(asset.get("asset_id") or "")
    st, st_derived = _resolve_source_type(asset)
    if st_derived:
        notes.append(
            f"{aid}: source_type 缺失 → 由 origin/ownership/producer 确定性推导为"
            f" {st}（非直接记录，保守归类）")
    if entry.get("model") in (None, "", "UNKNOWN"):
        notes.append(f"{aid}: model 缺失 → UNKNOWN（§43 不猜模型名）")
    if not asset.get("prompt_packet_id"):
        notes.append(f"{aid}: prompt_packet_id 缺失 → 未关联生产包（非生成类或未记录）")
    if str(entry.get("license")) in ("UNKNOWN", ""):
        notes.append(f"{aid}: license 缺失 → UNKNOWN → LICENSE_REVIEW_REQUIRED（§63）")
    if str(entry.get("generation_date")) in ("UNKNOWN", ""):
        notes.append(f"{aid}: generation_date 缺失 → UNKNOWN")
    if str(entry.get("original_file")) == "UNKNOWN":
        notes.append(f"{aid}: original_file 缺失 → UNKNOWN（§47 原始文件未记录）")
    if str(entry.get("normalized_file")) == "UNKNOWN":
        notes.append(f"{aid}: normalized_file 缺失 → UNKNOWN（未记录标准化产物）")
    if not notes:
        notes.append(f"{aid}: 来源信息完整，无缺省项")
    return notes


# ---------------------------------------------------------------------------
# 主构建函数
# ---------------------------------------------------------------------------

def build_provenance_manifest(assets, packets=None, out_path=None,
                              project_id: Optional[str] = None) -> dict:
    """生成 VISUAL_PROVENANCE_MANIFEST（§96-97）。

    Args:
        assets:  asset JSON 列表 / 目录 / 文件路径（见 _load_assets）
        packets: GV packet 字典 / 目录 / 文件路径（可选，用于六问的 Prompt 回看）
        out_path: 输出 JSON 路径（可选；None 只返回 dict）
        project_id: 项目名（缺省取 out_path 父目录名或 "UNKNOWN"）

    Returns:
        manifest dict：
            {schema, schema_version, project_id, generated_at, entries[],
             six_questions{}, entry_notes{}}
    """
    asset_list = _load_assets(assets)
    packet_map = _load_packets(packets)
    if project_id:
        pid = str(project_id)
    elif out_path is not None:
        pid = Path(out_path).parent.name or "UNKNOWN"
    else:
        pid = "UNKNOWN"

    entries, questions, notes_map = [], {}, {}
    for i, asset in enumerate(asset_list, 1):
        pv_id = f"PV-{i:03d}"
        entry = build_entry(asset, packet_map, pv_id)
        entries.append(entry)
        questions[pv_id] = six_questions(entry, packet_map)
        notes_map[pv_id] = entry_notes(asset, entry)

    manifest = {
        "schema": "VISUAL_PROVENANCE_MANIFEST",
        "schema_version": "1.0",
        "project_id": pid,
        "generated_at": now_iso(),
        "entries": entries,
        "six_questions": questions,
        "entry_notes": notes_map,
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
        prog="python3 -m modules.external-visual.provenance",
        description="VISUAL_PROVENANCE_MANIFEST 生成器（Phase-6 §96-99）")
    ap.add_argument("assets", nargs="+",
                    help="asset JSON 目录或文件（可多个；目录下 *_asset.json 优先）")
    ap.add_argument("--packets", default=None,
                    help="GV packet 目录/文件（可选，六问的 Prompt 回看）")
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
        manifest = build_provenance_manifest(
            merged, args.packets, args.out, project_id=args.project)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.out:
        print(f"provenance manifest written: {args.out}"
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
        "source": "https://archive.org/details/sample",
        "local_path": "/proj/assets/external-visual/A011/A011_v1_norm.mp4",
        "original_path": "/proj/assets/external-visual/A011/A011_v1_original.mov",
        "source_type": "FOOTAGE_DOWNLOAD",
        "provider": "internet-archive",
        "model": "UNKNOWN",
        "prompt_packet_id": None,
        "license": "CC0-1.0",
        "ownership": "PUBLIC_DOMAIN",
        "generation_date": "2026-08-10T00:00:00+00:00",
        "created_at": "2026-08-10T00:00:00+00:00",
        "checksum": "a" * 64,
        "timeline_usage": "第二节 B-roll 背景",
        "content_credentials": {"signed": False, "authority": None,
                                "note": "slot only"},
        "provenance": {"source_institution": "Internet Archive",
                       "original_page": "https://archive.org/details/sample",
                       "creator": "Prelinger", "retrieval_date": "2026-08-12"},
    }
    entry = build_entry(asset, {}, "PV-001")
    checks = [
        PV_ID_RE.match(entry["provenance_id"]) is not None,
        entry["asset_ref"] == "A011",
        entry["source_type"] == "FOOTAGE_DOWNLOAD",
        entry["model"] == "UNKNOWN",                    # 不猜模型名
        entry["prompt_packet_id"] is None,
        entry["license"] == "CC0-1.0",
        entry["ownership"] == "PUBLIC_DOMAIN",
        entry["content_credentials"]["signed"] is False,
        "Internet Archive" in entry["source_institution"],
        # 6 问
        six_questions(entry)["ai_or_real"] == "实拍",
        "可商用（CC0/Public Domain）" in six_questions(entry)["commercial"],
        "否（实拍素材" in six_questions(entry)["regenerable"],
        # 缺省 → UNKNOWN + 标注
        entry_notes(asset, entry)[0].startswith("A011"),
    ]
    # 生成 dict（内存，不落盘）
    m = build_provenance_manifest([asset])
    checks.append(m["schema"] == "VISUAL_PROVENANCE_MANIFEST")
    checks.append(len(m["entries"]) == 1 and "PV-001" in m["six_questions"])
    checks.append(len(m["entry_notes"]["PV-001"]) >= 1)
    # 确定性：两次生成 entries 一致
    m2 = build_provenance_manifest([deepcopy(asset)])
    checks.append(m["entries"] == m2["entries"])
    # R6 边车过滤：目录内同放 _asset.json 与 _ingest.json → 只读 _asset（含回退 glob）
    import tempfile  # noqa: PLC0415
    from pathlib import Path as _P  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as td:
        tdp = _P(td)
        tdp.joinpath("A011_v1_asset.json").write_text(
            json.dumps({"asset_id": "A011", "name": "asset file", "duration": 4.0}),
            encoding="utf-8")
        tdp.joinpath("A011_v1_ingest.json").write_text(
            json.dumps({"asset_id": "A011", "name": "ingest sidecar",
                        "__from": "ingest"}),
            encoding="utf-8")
        loaded = _load_assets(str(tdp))
        checks.append(len(loaded) == 1 and loaded[0]["asset_id"] == "A011")
        checks.append(loaded[0].get("name") == "asset file"
                      and "__from" not in loaded[0])
        # 只有边车文件的目录（无 *_asset.json）→ 回退 glob 也跳过 *_ingest.json
        tdp.joinpath("A012_v1_ingest.json").write_text(
            json.dumps({"asset_id": "A012", "name": "ingest only", "__from": "ingest"}),
            encoding="utf-8")
        loaded2 = _load_assets(str(tdp))
        checks.append(len(loaded2) == 1 and loaded2[0]["asset_id"] == "A011")
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"provenance selftest check #{i} failed")
    print("provenance selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
