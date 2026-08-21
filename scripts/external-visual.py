#!/usr/bin/env python3
"""external-visual.py — Phase 6 External Visual 全链路统一入口（P6-07）.

薄分发层：所有业务逻辑都在 modules/external-visual/ 下（Wave 1 各工单产物），
本脚本只做子命令解析 + 转发 + 统一 JSON 输出 + 退出码，禁止在此重写业务逻辑。

子命令（对应 Wave 1 模块入口，docstring 见 modules/external-visual/*.py）：
    request        EV(route=REAL_FOOTAGE) → FR-###（footage.build_request，§54）
    packet         EV → GV Production Packet（packet_builder.build_packet，§8-25）
    search         FR → Registry FOOTAGE 搜索（footage.search，§59/§119）
    select         License 硬门槛 + 审批（footage.select，§62-64）
    plan-use       可用区间 + Timeline Hint + Treatment（footage.plan_use，§71-76）
    review         候选评审（review.review_candidate，§35-41/§100-104）
    ingest         外部素材统一摄取（ingestion.ingest，§42-51/§90-95）
    normalize      按需标准化（ingestion.normalize_module().normalize，§44-45）
    proxy          代理文件生成（ingestion.proxy_module().make_proxy，§46）
    provenance     VISUAL_PROVENANCE_MANIFEST（provenance.build_provenance_manifest，§96-97）
    handoff        TIMELINE_HANDOFF_MANIFEST（handoff.build_timeline_handoff，§133-134）
    package        ASSET_PACKAGE_MANIFEST（manifest.export_package，§105/§132）
    manual-export  §29 MANUAL 导出 prompt.txt + instructions.md（workflow.run_manual）

退出码：0 = 成功；1 = 业务失败（参数/校验/模块内部错误）；2 = 致命错误（模块加载失败等）。

bootstrap（review C FR-009 采纳）：脚本顶部自举 sys.path，把 skill 根目录
（本文件上两级）插入 sys.path，任意 cwd / 无 PYTHONPATH 下均可直接
`python3 scripts/external-visual.py <subcommand> ...` 运行；
子模块加载失败时输出可读错误（提示 cd 到 skill 根或检查包结构）而非裸 ImportError。

技术约束：Python3 stdlib only；无 LLM；无联网；确定性。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# bootstrap：把 skill 根目录插入 sys.path（本文件位于 <skill_root>/scripts/）
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))


def _load_module(module_path: str):
    """加载 skill 子模块；失败时输出可读错误（不抛裸 ImportError）。"""
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        print(
            f"模块加载失败: {module_path}\n"
            f"  原因: {exc}\n"
            f"  提示: 请 cd 到 skill 根目录（{SKILL_ROOT}）后重试，"
            "或确认包结构完整（modules/external-visual/、modules/production/ 存在）。",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _load_json_arg(value, name="参数"):
    """读取 JSON 文件路径或内联 JSON 字符串 → dict。"""
    if value is None:
        return None
    s = str(value)
    p = Path(s)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{name} 文件解析失败 {s}: {exc}") from exc
    try:
        return json.loads(s)
    except ValueError as exc:
        raise ValueError(f"{name} 不是合法 JSON 文件路径或 JSON 字符串: {s!r}") from exc


def _emit(obj, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


# ---------------------------------------------------------------------------
# 各子命令转发（薄分发：只组装参数，业务在 modules/）
# ---------------------------------------------------------------------------

def cmd_request(args) -> dict:
    """EV → FR（footage.build_request，§54/§56-57）。"""
    footage = _load_module("modules.external-visual.footage")
    ev = _load_json_arg(args.ev, "--ev")
    if not isinstance(ev, dict):
        raise ValueError("--ev 需要 EV dict（JSON 文件或内联 JSON）")
    ed = _load_json_arg(args.editorial, "--editorial")
    return footage.build_request(ev, ed)


def cmd_packet(args) -> dict:
    """EV → GV Production Packet（packet_builder.build_packet，§8-25）。"""
    packet_builder = _load_module("modules.external-visual.packet_builder")
    ev = _load_json_arg(args.ev, "--ev")
    if not isinstance(ev, dict):
        raise ValueError("--ev 需要 EV dict")
    bible = _load_json_arg(args.bible, "--bible")
    profiles = _load_json_arg(args.profiles, "--profiles")
    return packet_builder.build_packet(ev, bible, profiles)


def cmd_search(args) -> dict:
    """FR → Registry FOOTAGE 搜索（footage.search，§59/§119）。"""
    footage = _load_module("modules.external-visual.footage")
    fr = _load_json_arg(args.request, "--request")
    if not isinstance(fr, dict):
        raise ValueError("--request 需要 FR dict（footage request，可先用 request 子命令生成）")
    return footage.search(fr, registry_index=args.index)


def cmd_select(args) -> dict:
    """License 硬门槛 + 审批（footage.select，§62-64）。"""
    footage = _load_module("modules.external-visual.footage")
    fr = _load_json_arg(args.request, "--request")
    ranked = _load_json_arg(args.ranked, "--ranked")
    if isinstance(ranked, dict) and "ranked" in ranked:
        ranked = ranked["ranked"]
    approvals = _load_json_arg(args.approvals, "--approvals") or {}
    return footage.select(ranked, fr, approvals)


def cmd_plan_use(args) -> dict:
    """可用区间 + Timeline Hint + Treatment（footage.plan_use，§71-76）。"""
    footage = _load_module("modules.external-visual.footage")
    fr = _load_json_arg(args.request, "--request")
    sel = _load_json_arg(args.selected, "--selected")
    if isinstance(sel, list):
        sel = sel[0] if sel else None
    if isinstance(sel, dict) and "selected" in sel and "license_gate" in sel:
        sel = sel.get("selected")
    adj = _load_json_arg(args.adjacent, "--adjacent")
    ed = _load_json_arg(args.editorial, "--editorial")
    return footage.plan_use(sel, fr, adj, ed)


def cmd_review(args) -> dict:
    """候选评审（review.review_candidate，§35-41/§100-104）。"""
    review = _load_module("modules.external-visual.review")
    packet = _load_json_arg(args.packet, "--packet")
    evidence = _load_json_arg(args.evidence, "--evidence")
    bible = _load_json_arg(args.bible, "--bible")
    adjacent = _load_json_arg(args.adjacent, "--adjacent")
    return review.review_candidate(args.video, packet, evidence, bible, adjacent,
                                   review_id=args.review_id)


def cmd_ingest(args) -> dict:
    """外部素材统一摄取（ingestion.ingest，§42-51/§90-95/§98-100）。"""
    ingestion = _load_module("modules.external-visual.ingestion")
    meta = {}
    for pair in (args.meta or []):
        k, _, v = pair.partition("=")
        meta[k.strip()] = v.strip()
    if args.asset_id:
        meta["asset_id"] = args.asset_id
    if args.source_type:
        meta["source_type"] = args.source_type
    target = {}
    if args.fps is not None:
        target["fps"] = float(args.fps)
    if args.resolution:
        w, _, h = args.resolution.partition("x")
        target["resolution"] = {"w": int(w), "h": int(h)}
    if args.audio_mode:
        target["audio_mode"] = args.audio_mode.upper()
    result = ingestion.ingest(args.source, meta, args.project_dir,
                              opts={"target": target,
                                    "storage_policy": args.storage_policy})
    return {"summary": {
        "asset_id": result["asset"]["asset_id"],
        "version": result["version"],
        "idempotent": result["idempotent"],
        "source_type": result["asset"]["source_type"],
        "origin": result["asset"]["origin"],
        "model": result["asset"]["model"],
        "checksum": result["checksum"],
        "validation_ok": result["validation_ok"],
    }, "asset": result["asset"]}


def cmd_normalize(args) -> dict:
    """按需标准化（ingestion.normalize_module().normalize，§44-45）。"""
    ingestion = _load_module("modules.external-visual.ingestion")
    target = {}
    if args.fps is not None:
        target["fps"] = float(args.fps)
    if args.resolution:
        w, _, h = args.resolution.partition("x")
        target["resolution"] = {"w": int(w), "h": int(h)}
    if args.audio_mode:
        target["audio_mode"] = args.audio_mode.upper()
    if args.orientation:
        target["orientation"] = args.orientation
    r = ingestion.normalize_module().normalize(
        args.source, None, target, out_dir=args.out_dir, out_stem=args.out_stem)
    return {"summary": {
        "output_path": r["output_path"],
        "changed": r["changed"],
        "reencoded": r["reencoded"],
    }, "normalize": r}


def cmd_proxy(args) -> dict:
    """代理文件生成（ingestion.proxy_module().make_proxy，§46）。"""
    ingestion = _load_module("modules.external-visual.ingestion")
    r = ingestion.proxy_module().make_proxy(
        args.source, None, proxy_dir=args.proxy_dir, out_stem=args.out_stem)
    return {"summary": {
        "proxy_path": r["proxy_path"],
        "generated": r["generated"],
        "rationale": r["rationale"],
    }, "proxy": r}


def cmd_provenance(args) -> dict:
    """VISUAL_PROVENANCE_MANIFEST（provenance.build_provenance_manifest，§96-97）。"""
    provenance = _load_module("modules.external-visual.provenance")
    merged: list = []
    for spec in args.assets:
        merged.extend(provenance._load_assets(spec))
    manifest = provenance.build_provenance_manifest(
        merged, args.packets, args.out, project_id=args.project)
    if args.out:
        print(f"provenance manifest written: {args.out}", file=sys.stderr)
    return manifest


def cmd_handoff(args) -> dict:
    """TIMELINE_HANDOFF_MANIFEST（handoff.build_timeline_handoff，§133-134）。"""
    handoff = _load_module("modules.external-visual.handoff")
    merged: list = []
    for spec in args.assets:
        merged.extend(handoff._load_assets(spec))
    manifest = handoff.build_timeline_handoff(
        merged, args.shots, args.out, project_id=args.project)
    if args.out:
        print(f"timeline handoff manifest written: {args.out}", file=sys.stderr)
    return manifest


def cmd_package(args) -> dict:
    """ASSET_PACKAGE_MANIFEST（manifest.export_package，§105/§132）。"""
    manifest_mod = _load_module("modules.production.manifest")
    m = manifest_mod.ProductionManifest(args.project_dir)
    pkg = m.export_package()
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        print(f"asset package manifest written: {args.out}", file=sys.stderr)
    return pkg


def cmd_manual_export(args) -> dict:
    """§29 MANUAL：导出 prompt.txt + instructions.md（workflow.run_manual）。"""
    workflow = _load_module("modules.external-visual.workflow")
    packet = _load_json_arg(args.packet, "--packet")
    cap = _load_json_arg(args.cap, "--cap") or {}
    return workflow.run_manual(packet, cap, args.out_dir)


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------

_SUBCOMMANDS = {
    "request": (cmd_request, "EV(route=REAL_FOOTAGE) → FR-###（footage.build_request，§54）"),
    "packet": (cmd_packet, "EV → GV Production Packet（packet_builder.build_packet，§8-25）"),
    "search": (cmd_search, "FR → Registry FOOTAGE 搜索（footage.search，§59/§119）"),
    "select": (cmd_select, "License 硬门槛 + 审批（footage.select，§62-64）"),
    "plan-use": (cmd_plan_use, "可用区间 + Timeline Hint + Treatment（footage.plan_use，§71-76）"),
    "review": (cmd_review, "候选评审（review.review_candidate，§35-41/§100-104）"),
    "ingest": (cmd_ingest, "外部素材统一摄取（ingestion.ingest，§42-51/§90-95）"),
    "normalize": (cmd_normalize, "按需标准化（§44-45）"),
    "proxy": (cmd_proxy, "代理文件生成（§46）"),
    "provenance": (cmd_provenance, "VISUAL_PROVENANCE_MANIFEST（§96-97）"),
    "handoff": (cmd_handoff, "TIMELINE_HANDOFF_MANIFEST（§133-134）"),
    "package": (cmd_package, "ASSET_PACKAGE_MANIFEST（§105/§132）"),
    "manual-export": (cmd_manual_export, "§29 MANUAL 导出 prompt.txt + instructions.md"),
}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="stdout 输出纯 JSON")
    ap = argparse.ArgumentParser(
        prog="python3 scripts/external-visual.py",
        description="Phase 6 External Visual 全链路统一入口（薄分发层，业务在 "
                    "modules/external-visual/）。任意 cwd 可直跑（脚本自举 sys.path）。",
        parents=[common])
    sub = ap.add_subparsers(dest="command", required=True,
                            help="子命令（见各模块 docstring）")

    p = sub.add_parser("request", parents=[common], help=_SUBCOMMANDS["request"][1])
    p.add_argument("--ev", required=True, help="EV JSON 文件或内联 JSON")
    p.add_argument("--editorial", default=None, help="editorial_direction JSON（可选）")

    p = sub.add_parser("packet", parents=[common], help=_SUBCOMMANDS["packet"][1])
    p.add_argument("--ev", required=True, help="EV JSON 文件或内联 JSON")
    p.add_argument("--bible", default=None, help="Visual Bible JSON（可选）")
    p.add_argument("--profiles", default=None, help="连续性档案目录（可选）")

    p = sub.add_parser("search", parents=[common], help=_SUBCOMMANDS["search"][1])
    p.add_argument("--request", required=True, help="FR JSON 文件或内联 JSON")
    p.add_argument("--index", default=None, help="Registry 索引目录（可选）")

    p = sub.add_parser("select", parents=[common], help=_SUBCOMMANDS["select"][1])
    p.add_argument("--request", required=True, help="FR JSON")
    p.add_argument("--ranked", required=True, help="ranked candidates JSON")
    p.add_argument("--approvals", default=None, help="已批准 gate JSON（可选）")

    p = sub.add_parser("plan-use", parents=[common], help=_SUBCOMMANDS["plan-use"][1])
    p.add_argument("--request", required=True, help="FR JSON")
    p.add_argument("--selected", required=True, help="selected candidate JSON")
    p.add_argument("--adjacent", default=None, help="adjacent_shots JSON（可选）")
    p.add_argument("--editorial", default=None, help="editorial_direction JSON（可选）")

    p = sub.add_parser("review", parents=[common], help=_SUBCOMMANDS["review"][1])
    p.add_argument("video", help="视频文件路径")
    p.add_argument("--packet", default=None, help="packet/request JSON（可选）")
    p.add_argument("--evidence", default=None, help="evidence JSON（可选）")
    p.add_argument("--bible", default=None, help="visual bible JSON（可选）")
    p.add_argument("--adjacent", default=None, help="adjacent_shots JSON（可选）")
    p.add_argument("--review-id", default=None, help="RV-###（可选）")

    p = sub.add_parser("ingest", parents=[common], help=_SUBCOMMANDS["ingest"][1])
    p.add_argument("--source", required=True, help="源视频文件")
    p.add_argument("--asset-id", default=None, help="A###（缺省由引擎分配）")
    p.add_argument("--project-dir", default=".", help="项目根目录")
    p.add_argument("--source-type", default=None,
                   choices=["API_GENERATED", "WEB_GENERATED", "USER_UPLOAD",
                            "EXTERNAL_TOOL", "FOOTAGE_DOWNLOAD"])
    p.add_argument("--meta", action="append", default=[], help="k=v 元数据（可多次）")
    p.add_argument("--fps", type=float, default=None)
    p.add_argument("--resolution", default=None, help="WxH，如 1920x1080")
    p.add_argument("--audio-mode", default=None)
    p.add_argument("--storage-policy", default=None)

    p = sub.add_parser("normalize", parents=[common], help=_SUBCOMMANDS["normalize"][1])
    p.add_argument("--source", required=True)
    p.add_argument("--out-dir", default=None)
    p.add_argument("--out-stem", default=None)
    p.add_argument("--fps", type=float, default=None)
    p.add_argument("--resolution", default=None)
    p.add_argument("--audio-mode", default=None)
    p.add_argument("--orientation", default=None)

    p = sub.add_parser("proxy", parents=[common], help=_SUBCOMMANDS["proxy"][1])
    p.add_argument("--source", required=True)
    p.add_argument("--proxy-dir", default=None)
    p.add_argument("--out-stem", default=None)

    p = sub.add_parser("provenance", parents=[common], help=_SUBCOMMANDS["provenance"][1])
    p.add_argument("assets", nargs="+", help="asset JSON 目录或文件（可多个）")
    p.add_argument("--packets", default=None, help="GV packet 目录（可选）")
    p.add_argument("--out", default=None, help="manifest 输出路径")
    p.add_argument("--project", default=None, help="项目名（可选）")

    p = sub.add_parser("handoff", parents=[common], help=_SUBCOMMANDS["handoff"][1])
    p.add_argument("assets", nargs="+", help="asset JSON 目录或文件（可多个）")
    p.add_argument("--shots", default=None, help="shot JSON 目录/文件（可选）")
    p.add_argument("--out", default=None, help="manifest 输出路径")
    p.add_argument("--project", default=None, help="项目名（可选）")

    p = sub.add_parser("package", parents=[common], help=_SUBCOMMANDS["package"][1])
    p.add_argument("--project-dir", required=True, help="项目根目录（含 production/manifest.json）")
    p.add_argument("--out", default=None, help="manifest 输出路径")

    p = sub.add_parser("manual-export", parents=[common], help=_SUBCOMMANDS["manual-export"][1])
    p.add_argument("--packet", required=True, help="GV packet JSON")
    p.add_argument("--cap", default=None, help="provider capability JSON（可选）")
    p.add_argument("--out-dir", required=True, help="导出目录")

    return ap


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    handler = _SUBCOMMANDS[args.command][0]
    try:
        result = handler(args)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:  # _load_module 的致命错误
        return int(exc.code or 2)
    _emit(result, getattr(args, "json", False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
