#!/usr/bin/env python3
"""routing-validate.py — ZHOU_Videodirector Phase-3 §74 Routing Validation（P3-4）.

对已生成 Routing Plan 的项目目录执行 Phase-3 Prompt §74 的十项路由校验，验证
`routing/S###.yaml`（Shot Routing，§53）与 `layers/S###.yaml`（Layer Routing，§54）
是否满足共享契约：Route 6 枚举、HYBRID 强制 Layer Decomposition（§22）、Layer 均带
Route、Layer asset boundary 无冲突、JY_NATIVE 不误标 baked-only、exact text 不被
AI Video 独占（§36）、critical data 不被 Generative 独占（§36）、subtitle 保持
editable（§29）、confidence ∈ [0,1]、continuity group 无非法切割（§31/§56）。

预期项目结构（<project_dir>/）:
    routing/           必备：routing/S###.yaml（Shot Route 决策；缺目录 → 致命 exit 2）
    layers/            可选：layers/S###.yaml（HYBRID / 多 Producer 时由 Router 生成）
    ROUTING_PLAN.md    可选：人类可读摘要（本校验不强制读取）

用法:
    python3 scripts/routing-validate.py <project_dir>          # 人类可读报告
    python3 scripts/routing-validate.py <project_dir> --json   # 机器可读 JSON
    python3 scripts/routing-validate.py --selftest             # 内置自检（临时目录）

退出码: 0 = 全 pass/na; 1 = 存在 fail; 2 = 致命错误（缺 routing/ 目录 / 项目目录不存在 /
YAML 顶层结构异常）。

技术约束: Python 3 stdlib only；PyYAML 可用时优先使用（可安全解析手写 YAML），
缺失时回退到内置 subset parser（覆盖 Router 的 stdlib emitter 输出格式）。不修改
schemas、modules/router 与其它脚本。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 共享契约常量（与 modules/router/router.py / routes.json / schemas 对齐）
# ---------------------------------------------------------------------------

ROUTE_ENUM = ("REMOTION", "THREE_D", "REAL_FOOTAGE", "GENERATIVE_VIDEO", "JY_NATIVE", "HYBRID")

# 承担文字产出的 Layer role（§25：TYPOGRAPHY / UI / SUBTITLE 必须由结构化 Producer 产出）
TEXT_ROLES = ("TYPOGRAPHY", "UI", "SUBTITLE")
# 承担数据产出的 Layer role
DATA_ROLES = ("DATA", "UI", "TYPOGRAPHY")

# 合并 asset 建议标记（continuity check 简化实现：routing yaml 文本中出现即视为
# 标注了合并 asset 建议；对应 Router §56 `CG###-A01 motion-sequence.mov` 边界输出）
MERGE_PATTERNS = (
    re.compile(r"-A\d{2,}\b"),
    re.compile(r"motion-sequence", re.I),
    re.compile(r"(?:合并|合拼|单一资产|整合)", re.I),
    re.compile(r"\bmerge", re.I),
    re.compile(r"asset\s*boundary", re.I),
)

# 层内 asset 边界引用提取
ASSET_ID_RE = re.compile(r"\bA\d{3}\b")
ASSET_BOUNDARY_RE = re.compile(r"\b[A-Z]{2,}\d{2,}-A\d{2,}\b")
ASSET_FILE_RE = re.compile(r"\b[\w./-]+\.(?:mov|mp4|png|jpe?g|webp|svg|gif|exr)\b", re.I)

_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")


class FatalError(Exception):
    """致命错误：缺 routing/ 目录 / 项目目录不存在 / YAML 顶层结构异常（退出码 2）。"""


# ---------------------------------------------------------------------------
# YAML 加载：PyYAML 优先，内置 subset parser 兜底
# ---------------------------------------------------------------------------

try:  # PyYAML 可用时优先（更宽容，兼容手写文件）
    import yaml as _yaml  # type: ignore

    HAS_PYYAML = True
except ImportError:  # pragma: no cover - 由 selftest 的 fallback 路径独立覆盖
    _yaml = None
    HAS_PYYAML = False


def _split_flow(s: str) -> list:
    """按顶层逗号拆分 flow 集合（{...} / [...]），引号与嵌套深度感知。"""
    parts, depth, cur, inq = [], 0, "", None
    for ch in s:
        if inq:
            cur += ch
            if ch == inq:
                inq = None
            continue
        if ch in "'\"":
            inq = ch
            cur += ch
        elif ch in "{[":
            depth += 1
            cur += ch
        elif ch in "}]":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def _strip_comment(s: str) -> str:
    """去掉行尾 ` #` 注释（引号内不处理）。"""
    inq = None
    for i, ch in enumerate(s):
        if ch in "'\"":
            if inq == ch:
                inq = None
            elif inq is None:
                inq = ch
        elif ch == "#" and inq is None and i > 0 and s[i - 1] in " \t":
            return s[:i].rstrip()
    return s.rstrip()


def _scalar(s: str):
    """把 YAML 标量文本转成 Python 值（flow dict/list、引号、null/bool/数字）。"""
    s = _strip_comment(s).strip()
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        d = {}
        if inner:
            for part in _split_flow(inner):
                k, _, v = part.partition(":")
                if k.strip():
                    d[k.strip()] = _scalar(v)
        return d
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in _split_flow(inner)] if inner else []
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        body = s[1:-1]
        if s[0] == "'":
            body = body.replace("''", "'")
        else:
            body = body.replace('\\"', '"').replace("\\\\", "\\")
        return body
    low = s.lower()
    if low in ("", "null", "~"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT_RE.match(s):
        return int(s)
    if _FLOAT_RE.match(s):
        return float(s)
    return s


def _parse_block(raw: list, i: int, indent: int):
    """递归解析从 raw[i] 开始的缩进块（dict 或 list）。返回 (value, next_i)。"""
    _, first = raw[i]
    if first.startswith("-"):
        return _parse_list(raw, i, indent)
    return _parse_map(raw, i, indent)


def _parse_map(raw: list, i: int, indent: int):
    d = {}
    while i < len(raw):
        ind, content = raw[i]
        if ind < indent or content.startswith("-"):
            break
        key, sep, val = content.partition(":")
        if not sep:
            i += 1
            continue
        key = key.strip()
        val = val.strip()
        if val:
            d[key] = _scalar(val)
            i += 1
        elif i + 1 < len(raw) and raw[i + 1][0] > ind:
            sub, i = _parse_block(raw, i + 1, raw[i + 1][0])
            d[key] = sub
        else:
            d[key] = None
            i += 1
    return d, i


def _parse_list(raw: list, i: int, indent: int):
    items = []
    while i < len(raw):
        ind, content = raw[i]
        if ind < indent or not content.startswith("-"):
            break
        rest = content[1:].lstrip()
        if not rest:
            i += 1
            continue
        if ":" in rest:
            item = {}
            k, _, v = rest.partition(":")
            k = k.strip()
            v = v.strip()
            if v:
                item[k] = _scalar(v)
            elif i + 1 < len(raw) and raw[i + 1][0] > ind:
                sub, i = _parse_block(raw, i + 1, raw[i + 1][0])
                item[k] = sub
            else:
                item[k] = None
            i += 1
            while i < len(raw) and raw[i][0] > ind and not raw[i][1].startswith("-"):
                kid, kcontent = raw[i]
                k2, sep2, v2 = kcontent.partition(":")
                if not sep2:
                    i += 1
                    continue
                k2 = k2.strip()
                v2 = v2.strip()
                if v2:
                    item[k2] = _scalar(v2)
                    i += 1
                elif i + 1 < len(raw) and raw[i + 1][0] > kid:
                    sub, i = _parse_block(raw, i + 1, raw[i + 1][0])
                    item[k2] = sub
                else:
                    item[k2] = None
                    i += 1
            items.append(item)
        else:
            items.append(_scalar(rest))
            i += 1
    return items, i


def fallback_parse_yaml(text: str):
    """内置 subset YAML parser：覆盖 Router emitter 输出（缩进 dict/list + flow scores）。"""
    raw = []
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        s = _strip_comment(line.rstrip())
        if not s.strip():
            continue
        indent = len(s) - len(s.lstrip(" "))
        raw.append((indent, s.strip()))
    if not raw:
        return {}
    value, _ = _parse_block(raw, 0, raw[0][0])
    return value if isinstance(value, dict) else {"_root": value}


def load_yaml_text(text: str):
    if HAS_PYYAML:
        try:
            v = _yaml.safe_load(text)
            return v if isinstance(v, dict) else (v if v is not None else {})
        except Exception:
            pass
    return fallback_parse_yaml(text)


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class CheckResult:
    id: str
    name: str
    status: str  # pass | fail | na
    details: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "status": self.status, "details": self.details}


@dataclasses.dataclass
class Report:
    project: str
    checks: list
    summary: dict
    exit_code: int

    def as_dict(self) -> dict:
        return {
            "project": self.project,
            "checks": [c.as_dict() for c in self.checks],
            "summary": self.summary,
            "exit_code": self.exit_code,
        }


@dataclasses.dataclass
class Bundle:
    routing: dict      # shot_id -> routing yaml dict
    routing_raw: dict  # shot_id -> routing yaml 原始文本
    layers: dict       # shot_id -> layer list（缺文件时不含该 key）


def _r(cid: str, name: str, status: str, details: str = "") -> CheckResult:
    return CheckResult(cid, name, status, details)


def _score(data: dict, key: str):
    """从 routing yaml 的 scores 取单因子（0-1），无法解析返回 None。"""
    scores = data.get("scores")
    if not isinstance(scores, dict):
        return None
    try:
        return float(scores.get(key))
    except (TypeError, ValueError):
        return None


def _route(layer) -> str:
    return str(layer.get("route") or "") if isinstance(layer, dict) else ""


def _role(layer) -> str:
    return str(layer.get("role") or "") if isinstance(layer, dict) else ""


def _asset_tokens(layer) -> set:
    blob = " ".join(
        str(v) for v in (layer.get("notes"), layer.get("asset"), layer.get("asset_id"))
        if isinstance(layer, dict) and v
    )
    return (set(ASSET_BOUNDARY_RE.findall(blob))
            | set(ASSET_ID_RE.findall(blob))
            | {m.lower() for m in ASSET_FILE_RE.findall(blob)})


# ---------------------------------------------------------------------------
# 十项检查（Phase-3 Prompt §74）
# ---------------------------------------------------------------------------

def check_01_route_enum_legal(bundle: Bundle) -> CheckResult:
    """每 routing/S###.yaml 的 route ∈ 6 枚举（REMOTION | THREE_D | REAL_FOOTAGE |
    GENERATIVE_VIDEO | JY_NATIVE | HYBRID；UNDECIDED 属于 shot.schema 的"未路由"态，
    不允许出现在路由产物中）。"""
    if not bundle.routing:
        return _r("01", "route_enum_legal", "na", "routing/ 下无 *.yaml")
    bad = []
    for sid in sorted(bundle.routing):
        route = bundle.routing[sid].get("route")
        if route not in ROUTE_ENUM:
            bad.append(f"{sid} route={route!r}")
    if bad:
        return _r("01", "route_enum_legal", "fail", "非法 route: " + "; ".join(bad))
    return _r("01", "route_enum_legal", "pass",
              f"{len(bundle.routing)} 个 Shot 的 route 均在 6 枚举内")


def check_02_hybrid_has_layers(bundle: Bundle) -> CheckResult:
    """route=HYBRID 的 Shot 必须有 layers/S###.yaml 且 layers 数组非空（§22 强制
    Layer Decomposition）。"""
    hybrids = [sid for sid, d in sorted(bundle.routing.items()) if d.get("route") == "HYBRID"]
    if not hybrids:
        return _r("02", "hybrid_has_layers", "pass", "无 HYBRID Shot")
    bad = []
    for sid in hybrids:
        ls = bundle.layers.get(sid)
        if not ls:
            bad.append(f"{sid} 缺 layers/{sid}.yaml 或 layers 为空")
    if bad:
        return _r("02", "hybrid_has_layers", "fail", "; ".join(bad))
    return _r("02", "hybrid_has_layers", "pass", f"{len(hybrids)} 个 HYBRID Shot 均有非空 layers")


def check_03_all_layers_have_route(bundle: Bundle) -> CheckResult:
    """每个 layer 的 route ∈ 6 枚举（layer 级不允许 HYBRID/UNDECIDED 之外的任意值）。"""
    if not bundle.layers:
        return _r("03", "all_layers_have_route", "na", "无 layers/*.yaml")
    bad = []
    for sid in sorted(bundle.layers):
        for layer in bundle.layers[sid]:
            route = _route(layer)
            if route not in ROUTE_ENUM:
                bad.append(f"{sid}/{layer.get('id') if isinstance(layer, dict) else '?'} route={route!r}")
    if bad:
        return _r("03", "all_layers_have_route", "fail", "非法 layer route: " + "; ".join(bad))
    total = sum(len(v) for v in bundle.layers.values())
    return _r("03", "all_layers_have_route", "pass", f"{total} 个 layer 的 route 均在 6 枚举内")


def check_04_layer_asset_boundary_conflict(bundle: Bundle) -> CheckResult:
    """同一 Shot 内多个 layer 的 asset 边界描述冲突（两个 layer 声称产出同一 asset）
    → fail；同时检查 layer id 唯一。"""
    if not bundle.layers:
        return _r("04", "layer_asset_boundary_conflict", "na", "无 layers/*.yaml")
    problems = []
    for sid in sorted(bundle.layers):
        ls = bundle.layers[sid]
        ids = [layer.get("id") if isinstance(layer, dict) else None for layer in ls]
        seen = set()
        for lid in ids:
            if lid is None:
                problems.append(f"{sid} 存在缺 id 的 layer")
            elif lid in seen:
                problems.append(f"{sid} layer id 重复: {lid}")
            else:
                seen.add(lid)
        asset_owners = {}
        for layer in ls:
            lid = layer.get("id") if isinstance(layer, dict) else None
            for tok in _asset_tokens(layer):
                asset_owners.setdefault(tok, []).append(lid)
        for tok, owners in sorted(asset_owners.items()):
            if len(owners) >= 2:
                problems.append(f"{sid} asset 边界冲突: {tok} 被多个 layer 声称产出 ({', '.join(str(o) for o in owners)})")
    if problems:
        return _r("04", "layer_asset_boundary_conflict", "fail", "; ".join(problems))
    total = sum(len(v) for v in bundle.layers.values())
    return _r("04", "layer_asset_boundary_conflict", "pass",
              f"{total} 个 layer：id 唯一，无 asset 边界重复产出")


def check_05_jy_native_bake_mislabel(bundle: Bundle) -> CheckResult:
    """JY_NATIVE route 的 layer 若 bake_policy=BAKE → fail（§74 "JY_NATIVE 是否误标
    baked-only"；剪映原生应保持 KEEP_EDITABLE）。"""
    problems = []
    for sid in sorted(bundle.layers):
        for layer in bundle.layers[sid]:
            if _route(layer) == "JY_NATIVE" and layer.get("bake_policy") == "BAKE":
                problems.append(f"{sid}/{layer.get('id')} JY_NATIVE 误标 bake_policy=BAKE")
    for sid in sorted(bundle.routing):  # 兼容顶层 bake_policy（schema 允许，emitter 不输出）
        d = bundle.routing[sid]
        if d.get("route") == "JY_NATIVE" and d.get("bake_policy") == "BAKE":
            problems.append(f"{sid} JY_NATIVE 误标 bake_policy=BAKE（Shot 级）")
    if problems:
        return _r("05", "jy_native_bake_mislabel", "fail", "; ".join(problems))
    return _r("05", "jy_native_bake_mislabel", "pass", "无 JY_NATIVE 被误标 baked-only")


def check_06_exact_text_owned_by_ai(bundle: Bundle) -> CheckResult:
    """text_accuracy >= 0.8 且（layer 全为 GENERATIVE_VIDEO 且无文字层 / 无 layer 且
    Shot route=GENERATIVE_VIDEO）→ fail（exact text 被 AI Video 独占，违反 §36 硬约束）。"""
    if not bundle.routing:
        return _r("06", "exact_text_owned_by_ai", "na", "routing/ 下无 *.yaml")
    bad = []
    for sid in sorted(bundle.routing):
        d = bundle.routing[sid]
        ta = _score(d, "text_accuracy")
        if ta is None or ta < 0.8:
            continue
        ls = bundle.layers.get(sid)
        if ls:
            has_text_layer = any(_role(l) in TEXT_ROLES for l in ls)
            all_generative = all(_route(l) == "GENERATIVE_VIDEO" for l in ls)
            if not has_text_layer and all_generative:
                bad.append(f"{sid} text_accuracy={ta:.2f} 且无文字层，layer 全为 GENERATIVE_VIDEO")
        else:
            if d.get("route") == "GENERATIVE_VIDEO":
                bad.append(f"{sid} text_accuracy={ta:.2f} 但 route=GENERATIVE_VIDEO 且无文字层")
    if bad:
        return _r("06", "exact_text_owned_by_ai", "fail", "; ".join(bad))
    return _r("06", "exact_text_owned_by_ai", "pass", "exact text 未被 AI Video 独占")


def check_07_critical_data_owned_by_generative(bundle: Bundle) -> CheckResult:
    """data_accuracy >= 0.8 且（DATA 层 route=GENERATIVE_VIDEO / 无数据层且 layer 全
    generative / 无 layer 且 Shot route=GENERATIVE_VIDEO）→ fail（critical data 被生成式
    当数据 Producer，违反 §36 硬约束）。"""
    if not bundle.routing:
        return _r("07", "critical_data_owned_by_generative", "na", "routing/ 下无 *.yaml")
    bad = []
    for sid in sorted(bundle.routing):
        d = bundle.routing[sid]
        da = _score(d, "data_accuracy")
        if da is None or da < 0.8:
            continue
        ls = bundle.layers.get(sid)
        if ls:
            bad_data = [layer.get("id") for layer in ls
                        if _role(layer) == "DATA" and _route(layer) == "GENERATIVE_VIDEO"]
            if bad_data:
                bad.append(f"{sid} data_accuracy={da:.2f} 且 DATA 层 {', '.join(str(b) for b in bad_data)} 走 GENERATIVE_VIDEO")
                continue
            has_data_layer = any(_role(l) in DATA_ROLES for l in ls)
            all_generative = all(_route(l) == "GENERATIVE_VIDEO" for l in ls)
            if not has_data_layer and all_generative:
                bad.append(f"{sid} data_accuracy={da:.2f} 且无数据层，layer 全为 GENERATIVE_VIDEO")
        else:
            if d.get("route") == "GENERATIVE_VIDEO":
                bad.append(f"{sid} data_accuracy={da:.2f} 但 route=GENERATIVE_VIDEO 且无结构化数据层")
    if bad:
        return _r("07", "critical_data_owned_by_generative", "fail", "; ".join(bad))
    return _r("07", "critical_data_owned_by_generative", "pass", "critical data 未由生成式独占")


def check_08_subtitle_editable(bundle: Bundle) -> CheckResult:
    """SUBTITLE role layer 的 bake_policy 必须为 KEEP_EDITABLE（§29 Editability
    Boundary）。"""
    if not bundle.layers:
        return _r("08", "subtitle_editable", "na", "无 layers/*.yaml")
    bad = []
    for sid in sorted(bundle.layers):
        for layer in bundle.layers[sid]:
            if _role(layer) == "SUBTITLE" and layer.get("bake_policy") != "KEEP_EDITABLE":
                bad.append(f"{sid}/{layer.get('id')} SUBTITLE bake_policy={layer.get('bake_policy')!r}（须 KEEP_EDITABLE）")
    if bad:
        return _r("08", "subtitle_editable", "fail", "; ".join(bad))
    return _r("08", "subtitle_editable", "pass", "SUBTITLE 层均保持 KEEP_EDITABLE")


def check_09_confidence_range(bundle: Bundle) -> CheckResult:
    """每 routing yaml 的 confidence 为数值且在 [0,1]。"""
    if not bundle.routing:
        return _r("09", "confidence_range", "na", "routing/ 下无 *.yaml")
    bad = []
    for sid in sorted(bundle.routing):
        c = bundle.routing[sid].get("confidence")
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            bad.append(f"{sid} confidence={c!r} 非数值")
        elif not (0.0 <= c <= 1.0):
            bad.append(f"{sid} confidence={c} 超出 [0,1]")
    if bad:
        return _r("09", "confidence_range", "fail", "; ".join(bad))
    return _r("09", "confidence_range", "pass", f"{len(bundle.routing)} 个 Shot 的 confidence 均在 [0,1]")


def check_10_continuity_illegal_cut(bundle: Bundle) -> CheckResult:
    """同一 continuity_group 的多个 Shot（≥2）若把连续 motion 切碎（组内 route 不一致
    且无任何 shot 标注合并 asset 建议）→ fail。简化实现（§31/§56）：组内至少一个 shot
    标注了合并 asset 建议（或组内 route 全部一致）即视为合法。"""
    groups = {}
    for sid, d in bundle.routing.items():
        g = d.get("continuity_group")
        if isinstance(g, str) and g.strip():
            groups.setdefault(g.strip(), []).append(sid)
    if not groups:
        return _r("10", "continuity_illegal_cut", "pass", "无 continuity_group")
    bad, ok_groups = [], []
    for g in sorted(groups):
        sids = groups[g]
        if len(sids) < 2:
            continue
        has_merge = any(any(p.search(bundle.routing_raw[sid]) for p in MERGE_PATTERNS) for sid in sids)
        routes = {bundle.routing[sid].get("route") for sid in sids}
        if not has_merge and len(routes) > 1:
            bad.append(f"group={g} ({', '.join(sorted(sids))}) route 不一致且无合并 asset 建议")
        else:
            ok_groups.append(g)
    if bad:
        return _r("10", "continuity_illegal_cut", "fail", "; ".join(bad))
    if not ok_groups:
        return _r("10", "continuity_illegal_cut", "pass", "无 ≥2 镜头的 continuity_group 可检查")
    return _r("10", "continuity_illegal_cut", "pass",
              f"{len(ok_groups)} 个 group 连续运动未被切碎（合并 asset 建议或组内 route 一致）")


CHECKS = [
    check_01_route_enum_legal,
    check_02_hybrid_has_layers,
    check_03_all_layers_have_route,
    check_04_layer_asset_boundary_conflict,
    check_05_jy_native_bake_mislabel,
    check_06_exact_text_owned_by_ai,
    check_07_critical_data_owned_by_generative,
    check_08_subtitle_editable,
    check_09_confidence_range,
    check_10_continuity_illegal_cut,
]

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def load_project(project_dir: Path) -> Bundle:
    routing = {}
    routing_raw = {}
    layers = {}
    routing_dir = project_dir / "routing"
    if not routing_dir.is_dir():
        raise FatalError(f"缺 routing/ 目录: {routing_dir}")
    files = sorted(routing_dir.glob("*.yaml")) + sorted(routing_dir.glob("*.yml"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        data = load_yaml_text(text)
        if not isinstance(data, dict):
            raise FatalError(f"routing YAML 顶层需为映射: {f}")
        routing[f.stem] = data
        routing_raw[f.stem] = text
    layers_dir = project_dir / "layers"
    if layers_dir.is_dir():
        for f in sorted(layers_dir.glob("*.yaml")) + sorted(layers_dir.glob("*.yml")):
            text = f.read_text(encoding="utf-8")
            data = load_yaml_text(text)
            if not isinstance(data, dict):
                raise FatalError(f"layers YAML 顶层需为映射: {f}")
            layers[f.stem] = data.get("layers") if isinstance(data.get("layers"), list) else []
    return Bundle(routing=routing, routing_raw=routing_raw, layers=layers)


def run_project(project_dir: str) -> Report:
    p = Path(project_dir)
    if not p.is_dir():
        raise FatalError(f"项目目录不存在: {p}")
    bundle = load_project(p)
    results = [fn(bundle) for fn in CHECKS]
    summary = {
        "passed": sum(1 for c in results if c.status == "pass"),
        "failed": sum(1 for c in results if c.status == "fail"),
        "na": sum(1 for c in results if c.status == "na"),
    }
    exit_code = 1 if summary["failed"] else 0
    return Report(project=p.name, checks=results, summary=summary, exit_code=exit_code)


def render_human(report: Report) -> str:
    tag = {"pass": "OK ", "fail": "FAIL", "na": "N/A "}
    lines = [f"=== Routing Validation: {report.project} ==="]
    for c in report.checks:
        line = f"[{tag[c.status]}] check_{c.id}_{c.name}"
        if c.details and c.status in ("fail", "na"):
            line += f": {c.details}"
        lines.append(line)
    s = report.summary
    lines.append(f"Summary: {s['passed']} passed, {s['failed']} failed, {s['na']} N/A")
    lines.append(f"Exit code: {report.exit_code}")
    return "\n".join(lines)


def render_fatal_json(project_name: str, message: str) -> str:
    return json.dumps({
        "project": project_name,
        "checks": [],
        "summary": {"passed": 0, "failed": 0, "na": 0},
        "exit_code": 2,
        "error": message,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 自检 fixtures（clean 十项全 pass / dirty 十项各触发一次 fail）
# ---------------------------------------------------------------------------

def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _scores(**over) -> str:
    base = {
        "structural_precision": 0.5, "photorealism": 0.3, "organic_motion": 0.3,
        "scene_entropy": 0.3, "text_accuracy": 0.3, "data_accuracy": 0.3,
        "revision_requirement": 0.4, "timing_precision": 0.4, "atmosphere_requirement": 0.2,
        "physical_complexity": 0.2, "camera_complexity": 0.2, "editability_requirement": 0.6,
    }
    base.update(over)
    inner = ", ".join(f"{k}: {v}" for k, v in base.items())
    return "{%s}" % inner


def _routing_yaml(sid, route, confidence, scores, *, group=None, constraints=None,
                  bake_policy=None) -> str:
    lines = [
        f"shot_id: {sid}",
        f"route: {route}",
        f"confidence: {confidence}",
        "route_source: AUTO",
        "reason:",
        "  production: reason text",
        "  accuracy: accuracy text",
        "  editability: editability text",
        "decision_summary: 路由决策摘要",
        f"scores: {scores}",
        "layer_decomposition_required: true" if route == "HYBRID" else "layer_decomposition_required: false",
        "prototype_required: false",
        "prototype_type: null",
        "prototype_goal: ''",
        f"continuity_group: {group if group else 'null'}",
        "assembly_backend: JIANYING",
        "supersedes: null",
    ]
    if bake_policy is not None:
        lines.append(f"bake_policy: {bake_policy}")
    if constraints:
        lines.append("constraints:")
        for c in constraints:
            lines.append(f"  - {c}")
    return "\n".join(lines) + "\n"


def _layers_yaml(sid, layers) -> str:
    lines = [f"shot_id: {sid}", "layers:"]
    for layer in layers:
        lines.append(f"  - id: {layer['id']}")
        lines.append(f"    role: {layer['role']}")
        lines.append(f"    route: {layer['route']}")
        lines.append(f"    bake_policy: {layer['bake_policy']}")
        lines.append(f"    z_order: {layer['z_order']}")
        lines.append(f"    notes: '{layer['notes']}'")
    return "\n".join(lines) + "\n"


def build_clean_fixture(root: Path) -> None:
    """clean fixture：6 Shot 路由产物，十项检查全部 pass。"""
    r = root / "routing"
    l = root / "layers"
    _write_text(r / "S001.yaml", _routing_yaml(
        "S001", "REMOTION", 0.85, _scores(text_accuracy=0.9, data_accuracy=0.6,
                                          structural_precision=0.8)))
    _write_text(r / "S002.yaml", _routing_yaml(
        "S002", "HYBRID", 0.72, _scores(text_accuracy=0.95, data_accuracy=0.3)))
    _write_text(l / "S002.yaml", _layers_yaml("S002", [
        {"id": "S002-L01", "role": "TYPOGRAPHY", "route": "REMOTION",
         "bake_policy": "KEEP_EDITABLE", "z_order": 1, "notes": "精确 UI 文案层"},
        {"id": "S002-L02", "role": "BACKGROUND", "route": "GENERATIVE_VIDEO",
         "bake_policy": "ASSET_REPLACEABLE", "z_order": 2, "notes": "AI 生成背景环境"},
    ]))
    _write_text(r / "S003.yaml", _routing_yaml(
        "S003", "JY_NATIVE", 0.8, _scores(text_accuracy=0.4, data_accuracy=0.2)))
    _write_text(l / "S003.yaml", _layers_yaml("S003", [
        {"id": "S003-L01", "role": "SUBTITLE", "route": "JY_NATIVE",
         "bake_policy": "KEEP_EDITABLE", "z_order": 1, "notes": "时间线原生字幕"},
    ]))
    _write_text(r / "S004.yaml", _routing_yaml(
        "S004", "REMOTION", 0.9, _scores(text_accuracy=0.5, data_accuracy=0.2),
        group="CG01", constraints=["与 S005 合并渲染为单一 Asset: CG01-A01 motion-sequence.mov"]))
    _write_text(r / "S005.yaml", _routing_yaml(
        "S005", "REMOTION", 0.88, _scores(text_accuracy=0.5, data_accuracy=0.2), group="CG01"))
    _write_text(r / "S006.yaml", _routing_yaml(
        "S006", "REAL_FOOTAGE", 0.7, _scores(text_accuracy=0.1, data_accuracy=0.1)))


def build_dirty_fixture(root: Path) -> None:
    """dirty fixture：7 Shot 路由产物，十项检查各触发一次 fail。"""
    r = root / "routing"
    l = root / "layers"
    # check 01 route_enum_legal + check 09 confidence_range
    _write_text(r / "S001.yaml", _routing_yaml(
        "S001", "MAGIC", 1.5, _scores(text_accuracy=0.2, data_accuracy=0.2)))
    # check 02 hybrid_has_layers（无 layers/S002.yaml）
    _write_text(r / "S002.yaml", _routing_yaml(
        "S002", "HYBRID", 0.7, _scores(text_accuracy=0.5, data_accuracy=0.2)))
    # check 06 exact_text_owned_by_ai + check 07 critical_data_owned_by_generative
    _write_text(r / "S003.yaml", _routing_yaml(
        "S003", "GENERATIVE_VIDEO", 0.75, _scores(text_accuracy=0.85, data_accuracy=0.9)))
    # check 10 continuity_illegal_cut（CG-A 组内 route 不一致且无合并 asset 建议）
    _write_text(r / "S004.yaml", _routing_yaml(
        "S004", "REMOTION", 0.6, _scores(text_accuracy=0.2, data_accuracy=0.2), group="CG-A"))
    _write_text(r / "S005.yaml", _routing_yaml(
        "S005", "GENERATIVE_VIDEO", 0.6, _scores(text_accuracy=0.2, data_accuracy=0.2), group="CG-A"))
    # check 05 jy_native_bake_mislabel + check 08 subtitle_editable
    _write_text(r / "S006.yaml", _routing_yaml(
        "S006", "JY_NATIVE", 0.8, _scores(text_accuracy=0.2, data_accuracy=0.2)))
    _write_text(l / "S006.yaml", _layers_yaml("S006", [
        {"id": "S006-L01", "role": "SUBTITLE", "route": "JY_NATIVE",
         "bake_policy": "BAKE", "z_order": 1, "notes": "字幕"},
    ]))
    # check 03 all_layers_have_route + check 04 layer_asset_boundary_conflict
    _write_text(r / "S007.yaml", _routing_yaml(
        "S007", "REMOTION", 0.5, _scores(text_accuracy=0.1, data_accuracy=0.1)))
    _write_text(l / "S007.yaml", _layers_yaml("S007", [
        {"id": "S007-L01", "role": "SUBJECT", "route": "MAGIC",
         "bake_policy": "BAKE", "z_order": 1, "notes": "产出 CG007-A01 主体资产"},
        {"id": "S007-L02", "role": "FOREGROUND", "route": "REMOTION",
         "bake_policy": "KEEP_EDITABLE", "z_order": 2, "notes": "产出 CG007-A01 前景资产"},
        {"id": "S007-L01", "role": "BACKGROUND", "route": "REMOTION",
         "bake_policy": "KEEP_EDITABLE", "z_order": 3, "notes": "背景层"},
    ]))


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    print("selftest: 开始（临时目录，clean/dirty 双 fixture + fallback parser 双路径）")
    try:
        with tempfile.TemporaryDirectory(prefix="routing-validate-") as td:
            tdir = Path(td)
            clean_dir = tdir / "clean"
            build_clean_fixture(clean_dir)
            r_clean = run_project(str(clean_dir))
            for c in r_clean.checks:
                assert c.status == "pass", \
                    f"clean check_{c.id}_{c.name} 期望 pass, 实际 {c.status}: {c.details}"
            assert r_clean.exit_code == 0
            assert r_clean.summary == {"passed": 10, "failed": 0, "na": 0}, r_clean.summary
            print("selftest: clean fixture -> 10 pass / 0 fail (exit 0) OK")

            dirty_dir = tdir / "dirty"
            build_dirty_fixture(dirty_dir)
            r_dirty = run_project(str(dirty_dir))
            dirty_by = {c.id: c for c in r_dirty.checks}
            for cid in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10"):
                c = dirty_by[cid]
                assert c.status == "fail", \
                    f"dirty check_{cid} 期望 fail, 实际 {c.status}: {c.details}"
            assert r_dirty.exit_code == 1
            assert r_dirty.summary["failed"] == 10, r_dirty.summary
            print("selftest: dirty fixture -> 10 fail (exit 1) OK")

            clean_by = {c.id: c for c in r_clean.checks}
            for cid in ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10"):
                assert clean_by[cid].status == "pass" and dirty_by[cid].status == "fail", \
                    f"check_{cid} 双路径覆盖失败（clean={clean_by[cid].status}, dirty={dirty_by[cid].status}）"
            print("selftest: 双路径覆盖 -> 十项 check 各命中 pass(clean) + fail(dirty) OK")

            # fallback parser 双路径：禁用 PyYAML 后重跑 clean，关键字段一致
            for f in sorted((clean_dir / "routing").glob("*.yaml")):
                text = f.read_text(encoding="utf-8")
                want = load_yaml_text(text)
                got = fallback_parse_yaml(text)
                assert isinstance(got, dict) and got.get("route") == want.get("route"), f
                assert got.get("confidence") == want.get("confidence"), f
                assert got.get("continuity_group") == want.get("continuity_group"), f
            for f in sorted((clean_dir / "layers").glob("*.yaml")):
                text = f.read_text(encoding="utf-8")
                want = load_yaml_text(text)
                got = fallback_parse_yaml(text)
                assert isinstance(got, dict) and len(got.get("layers") or []) == len(want.get("layers") or []), f
                gl = (got.get("layers") or [])[0]
                wl = (want.get("layers") or [])[0]
                assert gl.get("id") == wl.get("id") and gl.get("bake_policy") == wl.get("bake_policy"), f
            print("selftest: fallback YAML parser 与 PyYAML 解析结果一致 OK")

            fatal_dir = tdir / "fatal"
            shutil.copytree(clean_dir, fatal_dir)
            shutil.rmtree(fatal_dir / "routing")
            raised = False
            try:
                run_project(str(fatal_dir))
            except FatalError:
                raised = True
            assert raised, "缺 routing/ 目录应抛 FatalError（exit 2 路径）"
            print("selftest: 致命错误路径（缺 routing/ 目录）-> FatalError OK")

            human = render_human(r_clean)
            assert human.startswith("=== Routing Validation: clean ==="), human[:60]
            assert "Summary: 10 passed, 0 failed, 0 N/A" in human
            human_dirty = render_human(r_dirty)
            assert "[FAIL] check_10_continuity_illegal_cut" in human_dirty
            data = json.loads(json.dumps(r_clean.as_dict(), ensure_ascii=False))
            assert data["project"] == "clean" and data["exit_code"] == 0
            assert len(data["checks"]) == 10 and data["checks"][0]["id"] == "01"
            fatal_json = json.loads(render_fatal_json("fatal", "缺 routing/ 目录"))
            assert fatal_json["exit_code"] == 2 and fatal_json["summary"]["failed"] == 0
            print("selftest: human / JSON 输出格式 OK")
        print("SELFTEST PASSED")
        return 0
    except AssertionError as exc:
        print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
        return 1
    except FatalError as exc:
        print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="routing-validate.py",
        description="ZHOU_Videodirector Phase-3 §74 Routing Validation（P3-4）：十项路由校验。")
    ap.add_argument("project_dir", nargs="?", help="ZHOU_Videodirector 项目目录（含 routing/）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--selftest", action="store_true",
                    help="运行内置自检（clean/dirty 双 fixture，十项检查双路径断言；exit 0=通过）")
    args = ap.parse_args(argv)
    if args.selftest:
        return run_selftest()
    if not args.project_dir:
        ap.error("需要 <project_dir>（或使用 --selftest）")
    try:
        report = run_project(args.project_dir)
    except FatalError as exc:
        if args.json:
            print(render_fatal_json(Path(args.project_dir).name, str(exc)))
        else:
            print(f"致命错误: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False))
    else:
        print(render_human(report))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
