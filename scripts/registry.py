#!/usr/bin/env python3
"""registry.py - ZHOU_Videodirector Phase 4 Resource Registry engine (P4-2).

Metadata First, Payload Later（docs/registry.md 宪法 §2）的引擎实现：
先索引 -> 搜索 -> 预览 -> 最后才 fetch；fetch 前必须过 License 门与 Approval 门。

子命令（共享契约 §102）:
    find    搜索 + 排序（8 因子）+ 可解释结果（§39-46）；支持 --project-dir / --route /
            --offline / --from-requests（Router 桥，输出 resource-selection）
    detail  单条 Level 1 懒加载详情（§47）
    preview 返回 preview 引用；无预览时 preview_status=not_available，不假装存在（§48-51）
    fetch   获取门（LIGHTWEIGHT/MEDIUM/LARGE/EXTERNAL_INSTALL 四分类；LARGE/EXTERNAL_INSTALL
            必须审批且不下载；安全红线 §100-101）
    add     写入新条目（schema 校验 + 重复检测 + aliases，§72-75）
    update  刷新 metadata 状态（默认 dry-run 不改库；不发网络，§68-71）
    validate 七项校验（§67）
    request Router->Registry 桥（§80-81/§107/§114-115）：读 routing/S###.yaml + layers/S###.yaml
            生成 resource-request（HYBRID 拆多个 request，不产模糊单 query）

--selftest  内置自检：临时目录 fixture（fake provider + 10+ 条 fake 资源）+ 真实 Phase-3 e2e
            项目副本，覆盖 find/detail/preview/fetch/add/validate/request 全部断言。

技术约束: Python 3 stdlib only；YAML 优先 PyYAML，缺省退回内置最小读取器（子集）。
运行期不联网：find/update 零网络；fetch 不真下载（Phase 4 演示路径，见 README）。

退出码: 0 = 成功 / 全部 PASS；1 = 业务失败（未命中、校验失败、重复、审批、路径逃逸…）；
        2 = 致命错误（索引缺失 / 参数非法无法继续）。

环境变量（selftest 与测试用）:
    ZHOU_REGISTRY_INDEX_DIR   覆盖索引目录（resources.jsonl/providers.json/tags.json）
    ZHOU_REGISTRY_CACHE_DIR   覆盖本地缓存状态目录（local_state.json）
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_INDEX_DIR = SKILL_ROOT / "registry" / "index"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "zhou-videodirector-registry"
E2E_PROJECT = (
    Path.home()
    / ".zcode/workspace/default/zhou-videodirector-phase3/e2e-projects/test-A-90s-product"
)

ID_RE = re.compile(r"^[a-z0-9-]+:[a-z0-9_-]+:[a-z0-9._-]+$")
# 校验用宽松 id 模式：slug 段允许大写（P4-1 种子数据含 polyhaven:three-d-model:ArmChair_01 等）
ID_VALIDATE_RE = re.compile(r"^[a-z0-9-]+:[a-z0-9_-]+:[A-Za-z0-9._-]+$")
RR_RE = re.compile(r"^RR-\d{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
STALE_WINDOW_DAYS = 90

# 内置风格词表（与 tags.json 三类词表合并使用；用于项目风格 / avoid 词提取）
STYLE_VOCAB = set(
    """minimal spatial tech cinematic soft kinetic organic editorial retro luxury premium sharp
digital mechanical glitch neon photoreal stylized product architecture interior nature low-poly futuristic
motion sfx music ambient dynamic fast elastic airy bright dark warm cold industrial clean elegant bold subtle
paper data-viz map particle 2d 2.5d 3d typography svg glsl toon documentary""".split()
)

# 兜底枚举（schemas 缺省时使用；正常以 schemas 为准）
FALLBACK_ENUMS = {
    "RESOURCE_TYPES": [
        "MOTION_EFFECT", "TRANSITION", "SHOT_RECIPE", "REMOTION_COMPONENT", "THREE_D_MODEL",
        "TEXTURE", "HDRI", "FOOTAGE", "IMAGE", "SFX", "MUSIC", "SOUNDFONT", "FONT",
        "REFERENCE", "OTHER",
    ],
    "RESOURCE_NATURES": ["KNOWLEDGE", "CODE", "MEDIA", "MODEL", "PACKAGE"],
    "PREVIEW_TYPES": ["image", "gif", "video", "audio", "waveform", "external_url",
                      "generated_preview", "none"],
    "CACHE_STATES": ["NOT_CACHED", "METADATA_CACHED", "PREVIEW_CACHED", "PAYLOAD_CACHED",
                     "INSTALLED"],
    "VERIFICATION": ["CURRENT", "STALE", "BROKEN", "UNKNOWN"],
    "AVAILABILITY": ["REMOTE_ONLINE", "REMOTE_OFFLINE", "LOCAL_ONLY", "UNKNOWN"],
    "RESOURCE_STATUS": ["ACTIVE", "DEPRECATED", "RETIRED"],
    "PROVIDER_TYPES": ["LOCAL", "GITHUB", "API", "CLI", "MCP", "WEBSITE", "PACKAGE",
                       "STATIC_INDEX"],
    "INTEGRATION_MODES": ["EXTERNAL_SKILL", "PROVIDER", "KNOWLEDGE_ADAPTER",
                          "ARCHITECTURE_REFERENCE", "TIMELINE_BACKEND", "RESOURCE_PROVIDER"],
    "PROVIDER_STATUS": ["ACTIVE", "DEGRADED", "BROKEN", "UNKNOWN"],
    "AUTH_MODES": ["NONE", "API_KEY", "OAUTH", "TOKEN", "CREDENTIALS", "UNKNOWN"],
    "REUSE": ["USE_AS_IS", "ADAPT", "COMPOSE", "BUILD_NEW"],
    "ENERGY": ["VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH"],
    "ROUTES": ["REMOTION", "THREE_D", "REAL_FOOTAGE", "GENERATIVE_VIDEO", "JY_NATIVE",
               "HYBRID", "UNDECIDED"],
    "BAKE_POLICIES": ["BAKE", "KEEP_EDITABLE", "ASSET_REPLACEABLE"],
    "REQUEST_STATUS": ["OPEN", "IN_PROGRESS", "SELECTED", "FULFILLED", "CANCELLED"],
    "SIZE_PREFS": ["LIGHTWEIGHT", "MEDIUM", "LARGE", "ANY"],
    "QUALITY_PREFS": ["LOW", "MEDIUM", "HIGH", "ANY"],
    "CAPABILITIES": ["partial", "manual_or_semiautomatic", "requires_authentication"],
    "RESOURCE_REQUEST_REQUIRED": ["request_id", "project_id", "resource_types",
                                  "description", "status"],
}

ROUTE_TYPE_MAP = {
    "REMOTION": ["MOTION_EFFECT", "TRANSITION", "REMOTION_COMPONENT"],
    "THREE_D": ["THREE_D_MODEL", "TEXTURE", "HDRI"],
    "REAL_FOOTAGE": ["FOOTAGE", "IMAGE"],
    "JY_NATIVE": ["TRANSITION", "IMAGE", "SFX"],
    "GENERATIVE_VIDEO": ["REFERENCE"],
    "UNDECIDED": ["MOTION_EFFECT", "TRANSITION", "REMOTION_COMPONENT"],
}
# HYBRID 无 layer 文件时的兜底分组（不产模糊单 query，§115）
HYBRID_FALLBACK_GROUPS = [
    ("THREE_D", ["THREE_D_MODEL", "TEXTURE", "HDRI"]),
    ("REMOTION", ["MOTION_EFFECT", "TRANSITION", "REMOTION_COMPONENT"]),
]

RESOURCE_SCHEMA_REQUIRED = [
    "id", "type", "name", "provider", "source_url", "summary", "resource_nature",
    "tags", "best_for", "avoid_when", "style", "status", "availability",
    "verification_status", "preview", "license", "local_state", "metadata_version",
    "last_verified", "added_by", "added_at", "discovery_source",
]

# ---------------------------------------------------------------------------
# 最小 YAML 读取器（PyYAML 不可用时退回；只覆盖本项目 YAML 子集）
# ---------------------------------------------------------------------------

class YamlError(Exception):
    pass


def _qi(s, ch):
    q1 = q2 = False
    for i, c in enumerate(s):
        if c == "'" and not q2:
            q1 = not q1
        elif c == '"' and not q1:
            q2 = not q2
        elif c == ch and not q1 and not q2:
            return i
    return -1


def _scom(s):
    i = _qi(s, '#')
    return s[:i] if i >= 0 else s


def _kv(s):
    i = _qi(s, ':')
    return (s[:i].strip(), s[i + 1:].strip()) if i >= 0 else (None, None)


def _sl(s):
    out = []
    while True:
        i = _qi(s, ',')
        if i < 0:
            out.append(s)
            return out
        out.append(s[:i])
        s = s[i + 1:]


def _sc(s):
    s = s.strip()
    if s in ('', 'null', '~'):
        return None
    if s in ('true', 'True'):
        return True
    if s in ('false', 'False'):
        return False
    if s == '{}':
        return {}
    if s[:1] == '[' and s[-1:] == ']':
        x = s[1:-1].strip()
        return [] if x == '' else [_sc(t) for t in _sl(x)]
    if len(s) >= 2 and s[0] in '"\'' and s[-1] == s[0]:
        return s[1:-1]
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    if re.fullmatch(r'-?\d*\.\d+', s):
        return float(s)
    return s


def _block(L, i, ind):
    if i >= len(L) or L[i][0] != ind:
        return None, i
    return _blist(L, i, ind) if L[i][1].startswith('- ') else _bmap(L, i, ind)


def _bmap(L, i, ind):
    o = {}
    while i < len(L):
        p, c, n = L[i]
        if p != ind or c.startswith('- '):
            break
        k, v = _kv(c)
        if k is None:
            raise YamlError(f"line {n}: expected 'key: value', got {c!r}")
        if k in o:
            raise YamlError(f"line {n}: duplicate key {k!r}")
        i += 1
        if v == '':
            v, i = _block(L, i, L[i][0]) if i < len(L) and L[i][0] > ind else (None, i)
        else:
            v = _sc(v)
        o[k] = v
    return o, i


def _blist(L, i, ind):
    o = []
    while i < len(L):
        p, c, n = L[i]
        if p != ind or not c.startswith('- '):
            break
        v = c[2:].strip()
        i += 1
        if v == '':
            v, i = _block(L, i, L[i][0]) if i < len(L) and L[i][0] > ind else (None, i)
        else:
            v = _sc(v)
        o.append(v)
    return o, i


def minimal_load_yaml(text):
    L = []
    for n, raw in enumerate(text.split('\n'), 1):
        s = _scom(raw).rstrip()
        if not s.strip():
            continue
        lead = len(s) - len(s.lstrip(' '))
        if '\t' in s[:lead]:
            raise YamlError(f"line {n}: tab indentation not allowed")
        L.append((lead, s.strip(), n))
    if not L:
        return {}
    v, i = _block(L, 0, L[0][0])
    if i != len(L):
        raise YamlError(f"line {L[i][2]}: indentation mismatch with parent block")
    return v


try:
    import yaml as _yaml  # PyYAML（允许）

    def _load_yaml(text, source):
        try:
            data = _yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001
            raise YamlError(f"{source}: {exc}") from exc
        return data if data is not None else {}

    YAML_STRATEGY = "pyyaml"
except ImportError:  # pragma: no cover
    def _load_yaml(text, source):
        try:
            return minimal_load_yaml(text)
        except YamlError as exc:
            raise YamlError(f"{source}: {exc}") from exc

    YAML_STRATEGY = "minimal_reader"


def load_json_or_yaml(path):
    """按扩展名读取 JSON / YAML 文件。返回 (data, error)。"""
    text = None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read {path}: {exc}"
    try:
        if path.suffix.lower() == ".json":
            return json.loads(text), None
        return _load_yaml(text, str(path)), None
    except (ValueError, YamlError) as exc:
        return None, f"parse error in {path}: {exc}"


# ---------------------------------------------------------------------------
# Schema 枚举（真源）+ 归一化
# ---------------------------------------------------------------------------

def _load_schema_enums():
    enums = dict(FALLBACK_ENUMS)
    files = {
        "resource.schema.json": {
            "RESOURCE_TYPES": ("properties", "type", "enum"),
            "RESOURCE_NATURES": ("properties", "resource_nature", "enum"),
            "RESOURCE_STATUS": ("properties", "status", "enum"),
            "AVAILABILITY": ("properties", "availability", "enum"),
            "VERIFICATION": ("properties", "verification_status", "enum"),
            "CACHE_STATES": ("properties", "local_state", "properties", "cache_state", "enum"),
            "PREVIEW_TYPES": ("properties", "preview", "properties", "type", "enum"),
            "ENERGY": ("properties", "type_specific", "properties", "music",
                       "properties", "energy", "enum"),
        },
        "provider.schema.json": {
            "PROVIDER_TYPES": ("properties", "type", "enum"),
            "INTEGRATION_MODES": ("properties", "integration_mode", "enum"),
            "PROVIDER_STATUS": ("properties", "status", "enum"),
            "AUTH_MODES": ("properties", "authentication", "enum"),
            "CAPABILITIES": ("definitions", "capability_value", "oneOf"),
        },
        "resource-request.schema.json": {
            "ROUTES": ("properties", "route", "enum"),
            "BAKE_POLICIES": ("properties", "bake_policy", "enum"),
            "REQUEST_STATUS": ("properties", "status", "enum"),
            "SIZE_PREFS": ("properties", "size_preference", "enum"),
            "QUALITY_PREFS": ("properties", "quality_preference", "enum"),
        },
        "resource-selection.schema.json": {
            "REUSE": ("properties", "selected_resource", "properties",
                      "reuse_recommendation", "enum"),
        },
    }
    for fname, mapping in files.items():
        try:
            spec = json.loads((SKILL_ROOT / "schemas" / fname).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for key, path in mapping.items():
            node = spec
            ok = True
            for part in path:
                node = node.get(part) if isinstance(node, dict) else None
                if node is None:
                    ok = False
                    break
            if ok and isinstance(node, list) and node:
                if key == "CAPABILITIES":
                    vals = []
                    for br in node:
                        if isinstance(br, dict) and br.get("type") == "string":
                            vals.extend(br.get("enum") or [])
                    if vals:
                        enums[key] = vals
                else:
                    enums[key] = list(node)
    return enums


ENUMS = _load_schema_enums()

RESOURCE_TYPES = ENUMS["RESOURCE_TYPES"]
RESOURCE_NATURES = ENUMS["RESOURCE_NATURES"]
PREVIEW_TYPES = ENUMS["PREVIEW_TYPES"]
CACHE_STATES = ENUMS["CACHE_STATES"]
VERIFICATION = ENUMS["VERIFICATION"]
AVAILABILITY = ENUMS["AVAILABILITY"]
RESOURCE_STATUS = ENUMS["RESOURCE_STATUS"]
PROVIDER_TYPES = ENUMS["PROVIDER_TYPES"]
INTEGRATION_MODES = ENUMS["INTEGRATION_MODES"]
PROVIDER_STATUS = ENUMS["PROVIDER_STATUS"]
AUTH_MODES = ENUMS["AUTH_MODES"]
REUSE = ENUMS["REUSE"]
ENERGY = ENUMS["ENERGY"]
ROUTES = ENUMS["ROUTES"]
BAKE_POLICIES = ENUMS["BAKE_POLICIES"]
REQUEST_STATUS = ENUMS["REQUEST_STATUS"]
CAPABILITIES = ENUMS["CAPABILITIES"]

PREVIEW_TYPE_SET = set(PREVIEW_TYPES)
TYPE_SET = set(RESOURCE_TYPES)
NATURE_SET = set(RESOURCE_NATURES)


def norm_enum(value, enum_list, default=None):
    """枚举归一化：接受大小写 / 连字符变体，返回规范大写值；失败返回 default。"""
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip()
        up = v.upper().replace('-', '_')
        for e in enum_list:
            if v == e:
                return e
        for e in enum_list:
            if up == e:
                return e
    return default


def norm_availability(value):
    if isinstance(value, str):
        v = value.strip().lower()
        if v == 'remote':
            return 'REMOTE_ONLINE'  # 种子数据历史值（P4-1），按验证状态最优解读
        if v == 'local':
            return 'LOCAL_ONLY'
        if v == 'offline':
            return 'REMOTE_OFFLINE'
    return norm_enum(value, AVAILABILITY, default='UNKNOWN')


def normalize_resource(r, raw=None):
    """把一条 resource 归一化到规范枚举（返回副本；不修改原 dict）。"""
    out = dict(r)
    out["id"] = str(r.get("id") or "").strip()
    out["type"] = norm_enum(r.get("type"), RESOURCE_TYPES, default="OTHER")
    out["resource_nature"] = norm_enum(r.get("resource_nature"), RESOURCE_NATURES, default="OTHER")
    out["status"] = norm_enum(r.get("status"), RESOURCE_STATUS, default="UNKNOWN")
    out["availability"] = norm_availability(r.get("availability"))
    out["verification_status"] = norm_enum(r.get("verification_status"), VERIFICATION,
                                           default="UNKNOWN")
    if not isinstance(out.get("tags"), list):
        out["tags"] = []
    if not isinstance(out.get("best_for"), list):
        out["best_for"] = []
    if not isinstance(out.get("avoid_when"), list):
        out["avoid_when"] = []
    if not isinstance(out.get("style"), list):
        out["style"] = []
    if not isinstance(out.get("aliases"), list):
        out["aliases"] = []
    ls = r.get("local_state") or {}
    if isinstance(ls, dict):
        ls = dict(ls)
        ls["cache_state"] = norm_enum(ls.get("cache_state"), CACHE_STATES, default="NOT_CACHED")
    else:
        ls = {"cache_state": "NOT_CACHED"}
    out["local_state"] = ls
    pv = r.get("preview")
    if isinstance(pv, dict):
        pv = dict(pv)
        if pv.get("type") is not None:
            pv["type"] = norm_enum(str(pv["type"]), PREVIEW_TYPES, default="none")
    else:
        pv = {"type": "none", "url": ""}
    out["preview"] = pv
    lic = r.get("license")
    if isinstance(lic, dict):
        out["license"] = dict(lic)
    else:
        out["license"] = {}
    if not out.get("license"):
        out["license"] = {"license_type": "UNKNOWN", "commercial_use": None,
                          "license_review_required": True}
    return out


def human_size(b):
    if b is None:
        return "未知"
    try:
        b = float(b)
    except (TypeError, ValueError):
        return "未知"
    if b < 0:
        return "未知"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024 or unit == "TB":
            return f"{b:.0f}{unit}" if unit == "B" else f"{b:.1f}{unit}"
        b /= 1024
    return "未知"


def parse_date(value):
    """解析 ISO 日期（支持 'YYYY-MM-DD' 与 date-time）；失败返回 None。"""
    if not isinstance(value, str):
        return None
    m = DATE_RE.match(value)
    if not m:
        return None
    try:
        return datetime.date.fromisoformat(m.group(0))
    except ValueError:
        return None


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Registry Store
# ---------------------------------------------------------------------------

class FatalError(Exception):
    pass


class Store:
    """索引 + provider + tags + 本地缓存状态叠加（local_state.json 不污染 skill 源码树，§59）。"""

    def __init__(self, index_dir=None, cache_dir=None):
        self.index_dir = Path(index_dir) if index_dir else (
            Path(os.environ["ZHOU_REGISTRY_INDEX_DIR"]) if os.environ.get("ZHOU_REGISTRY_INDEX_DIR")
            else DEFAULT_INDEX_DIR)
        self.cache_dir = Path(cache_dir) if cache_dir else (
            Path(os.environ["ZHOU_REGISTRY_CACHE_DIR"]) if os.environ.get("ZHOU_REGISTRY_CACHE_DIR")
            else DEFAULT_CACHE_DIR)
        self.resources_file = self.index_dir / "resources.jsonl"
        self.providers_file = self.index_dir / "providers.json"
        self.tags_file = self.index_dir / "tags.json"
        self.local_state_file = self.cache_dir / "local_state.json"
        self.resources = []
        self.raw_resources = []
        self.providers = {}
        self.tags = {}
        self._overlay = {}
        self.warnings = []
        self.writable = bool(os.environ.get("ZHOU_REGISTRY_INDEX_DIR"))  # 测试/显式写库开关
        self._load()

    # -- 加载 ----------------------------------------------------------------
    def _load(self):
        if not self.resources_file.is_file():
            raise FatalError(f"index file not found: {self.resources_file}")
        if not self.providers_file.is_file():
            raise FatalError(f"providers file not found: {self.providers_file}")

        try:
            text = self.resources_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise FatalError(f"cannot read {self.resources_file}: {exc}")
        seen_ids = {}
        raw_warnings = []
        for ln, line in enumerate(text.split("\n"), 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except ValueError as exc:
                raw_warnings.append(f"resources.jsonl:{ln}: 非法 JSON 行已跳过: {exc}")
                continue
            if not isinstance(raw, dict):
                raw_warnings.append(f"resources.jsonl:{ln}: 非对象行已跳过")
                continue
            r = normalize_resource(raw)
            rid = r["id"]
            if not rid:
                raw_warnings.append(f"resources.jsonl:{ln}: 缺 id 的行已跳过")
                continue
            # 非规范枚举提示（如 status=active / availability=remote），不判错（P4-1 历史值）
            if raw.get("status") and raw["status"].strip().upper() != r["status"]:
                raw_warnings.append(f"resources.jsonl:{ln}: status={raw['status']!r} "
                                    f"已归一化为 {r['status']}（非规范大小写）")
            if raw.get("availability") and raw["availability"].strip().lower() not in \
                    ("remote", "local", "offline") and \
                    raw["availability"].strip().upper() != r["availability"]:
                raw_warnings.append(f"resources.jsonl:{ln}: availability={raw['availability']!r} "
                                    f"已归一化为 {r['availability']}")
            if rid in seen_ids:
                raw_warnings.append(f"resources.jsonl:{ln}: 重复 id {rid!r}")
            else:
                seen_ids[rid] = ln
            self.resources.append(r)
            self.raw_resources.append(raw)
        self.warnings.extend(raw_warnings)

        pdata, err = load_json_or_yaml(self.providers_file)
        if err is not None:
            raise FatalError(f"cannot load providers: {err}")
        for p in (pdata or {}).get("providers", []) if isinstance(pdata, dict) else (pdata or []):
            if not isinstance(p, dict) or not p.get("id"):
                continue
            self.providers[str(p["id"])] = p

        if self.tags_file.is_file():
            tdata, terr = load_json_or_yaml(self.tags_file)
            if terr is None and isinstance(tdata, dict):
                self.tags = tdata

        # 本地缓存状态叠加（METADATA_CACHED 以上级别的运行期状态，存 ~/.cache 或项目目录）
        if self.local_state_file.is_file():
            odata, oerr = load_json_or_yaml(self.local_state_file)
            if oerr is None and isinstance(odata, dict):
                for rid, ov in odata.items():
                    if isinstance(ov, dict):
                        self._overlay[rid] = ov
        self._apply_overlay()

    def _apply_overlay(self):
        for r in self.resources:
            ov = self._overlay.get(r["id"])
            if not ov:
                continue
            ls = dict(r["local_state"])
            for k, v in ov.items():
                ls[k] = v
            if ls.get("cache_state") is not None:
                ls["cache_state"] = norm_enum(ls["cache_state"], CACHE_STATES,
                                              default="NOT_CACHED")
            r["local_state"] = ls

    def provider(self, pid):
        return self.providers.get(pid)

    # -- 解析 ----------------------------------------------------------------
    def resolve_id(self, rid):
        """精确 id 或 alias 解析 -> 资源对象；未命中返回 None。"""
        for r in self.resources:
            if r["id"] == rid:
                return r
        for r in self.resources:
            if rid in (r.get("aliases") or []):
                return r
        return None

    def type_segment_ok(self, r):
        """校验 id 的 type 段是否为该条目 type 的合法小写形式（容忍缩略历史形式）。"""
        parts = r["id"].split(":")
        if len(parts) != 3:
            return False
        return True

    # -- 写 ----------------------------------------------------------------
    def save_resources(self, resources):
        """全量重写 resources.jsonl（add / update 持久化用）。"""
        tmp = self.resources_file.with_suffix(".jsonl.tmp")
        try:
            tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in resources) + "\n",
                           encoding="utf-8")
            tmp.replace(self.resources_file)
        except OSError as exc:
            raise FatalError(f"cannot write index {self.resources_file}: {exc}")

    def save_local_state(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.local_state_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._overlay, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.local_state_file)
        except OSError as exc:
            raise FatalError(f"cannot write local state {self.local_state_file}: {exc}")


def open_store():
    try:
        return Store()
    except FatalError as exc:
        print(json.dumps({"fatal": str(exc), "exit_code": 2}, indent=2))
        sys.exit(2)


# ---------------------------------------------------------------------------
# 项目上下文（project-aware §43 / avoid 词）
# ---------------------------------------------------------------------------

def extract_project_style(project_dir):
    """从 VISUAL_BIBLE.md / PROJECT_BRIEF.md 提取 style tokens 与 avoid tokens。"""
    ctx = {"style_tokens": [], "avoid_tokens": [], "files_read": []}
    pd = Path(project_dir)
    if not pd.is_dir():
        return ctx
    for fn in ("VISUAL_BIBLE.md", "PROJECT_BRIEF.md"):
        p = pd / fn
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        ctx["files_read"].append(fn)
        m = re.search(r"Style\s*Name[^\n:]*[:：]\s*([^\n]+)", text)
        if m:
            for t in re.split(r"[_\-\s,/]+", m.group(1).strip().lower()):
                if t and t in STYLE_VOCAB:
                    ctx["style_tokens"].append(t)
        # Avoid List 段：从 "Avoid List" 行开始到下一个 '#' 标题为止（含同一行内的避免词）
        block_parts = []
        capturing = False
        for ln in text.split("\n"):
            if re.search(r"Avoid\s*List", ln):
                capturing = True
            elif capturing and re.match(r"^\s*#", ln):
                break
            if capturing:
                block_parts.append(ln)
        block = "\n".join(block_parts)
        for w in STYLE_VOCAB:
            if re.search(rf"(?<![a-z0-9-]){re.escape(w)}(?![a-z0-9-])", block.lower()):
                ctx["avoid_tokens"].append(w)
        if not ctx["style_tokens"]:
            for w in STYLE_VOCAB:
                if re.search(rf"(?<![a-z0-9-]){re.escape(w)}(?![a-z0-9-])", text.lower()):
                    ctx["style_tokens"].append(w)
    # 去重保持顺序
    ctx["style_tokens"] = list(dict.fromkeys(ctx["style_tokens"]))
    ctx["avoid_tokens"] = list(dict.fromkeys(ctx["avoid_tokens"]))
    return ctx


# ---------------------------------------------------------------------------
# 排序 8 因子 + 过滤链（find 核心）
# ---------------------------------------------------------------------------

class Candidate:
    __slots__ = ("r", "prov", "score", "factors", "why", "hits", "fit",
                 "reuse", "reuse_why", "avoid_hits", "style_hits", "family_members")

    def __init__(self, r, prov, score, factors, why, hits, fit, reuse, reuse_why,
                 avoid_hits, style_hits):
        self.r = r
        self.prov = prov
        self.score = score
        self.factors = factors
        self.why = why
        self.hits = hits
        self.fit = fit
        self.reuse = reuse
        self.reuse_why = reuse_why
        self.avoid_hits = avoid_hits
        self.style_hits = style_hits
        self.family_members = []


def tokenize_query(query):
    if not query:
        return []
    q = query.lower()
    tokens = [t for t in re.split(r"[^a-z0-9\u4e00-\u9fff\-]+", q) if t]
    return list(dict.fromkeys(tokens))


def _query_hits(r, tokens, whole):
    """query 在 name/summary/tags/best_for/style/aliases 上的加权命中。返回 (加权和, 命中词集合)。"""
    score = 0.0
    hits = set()
    name = (r.get("name") or "").lower()
    summary = (r.get("summary") or "").lower()
    tags = [t.lower() for t in (r.get("tags") or [])]
    best = [b.lower() for b in (r.get("best_for") or [])]
    style = [s.lower() for s in (r.get("style") or [])]
    aliases = [a.lower() for a in (r.get("aliases") or [])]
    type_lower = (r.get("type") or "").lower()
    type_variants = {type_lower, type_lower.replace("_", "-")}
    for t in tokens:
        if not t:
            continue
        if t in type_variants:  # 类型名命中（如 "transition" -> TRANSITION）
            score += 2.5
            hits.add(t)
        if len(t) >= 2 and t in name:
            score += 3.0
            hits.add(t)
        if t in tags:
            score += 2.0
            hits.add(t)
        if t in style:
            score += 1.5
            hits.add(t)
        if any(t in b for b in best):
            score += 1.0
            hits.add(t)
        if t in summary:
            score += 1.0
            hits.add(t)
        if t in aliases:
            score += 1.5
            hits.add(t)
    if whole and len(whole) >= 3:
        if whole in name or whole in summary:
            score += 2.0
            hits.add("whole-query")
    return score, hits


def _best_for_factor(r, tokens):
    best = [b.lower() for b in (r.get("best_for") or [])]
    if not best:
        return 0.0
    hits = 0
    for t in tokens:
        if any(t in b for b in best):
            hits += 1
    return min(1.0, hits / max(1, len(tokens)))


def _style_factor(r, proj_style, avoid_tokens):
    tags = [t.lower() for t in (r.get("tags") or [])]
    style = [s.lower() for s in (r.get("style") or [])]
    both = set(tags) | set(style)
    f = 0.0
    if proj_style:
        hits = both & set(proj_style)
        if hits:
            f = min(1.0, len(hits) / max(1, len(proj_style)) * 1.5)
    avoid_hits = both & set(avoid_tokens) if avoid_tokens else set()
    if avoid_hits:
        f = max(0.0, f - 0.35 * len(avoid_hits))
    return f, sorted(avoid_hits)


def _license_score(r, license_mode):
    lic = r.get("license") or {}
    t = (lic.get("license_type") or "UNKNOWN").upper()
    if t == "UNKNOWN" or lic.get("license_review_required") is True:
        return 0.35
    if lic.get("commercial_use") is True:
        return 1.0
    if lic.get("commercial_use") is False:
        return 0.4
    return 0.5


def _local_score(r):
    cs = (r.get("local_state") or {}).get("cache_state") or "NOT_CACHED"
    if cs in ("PAYLOAD_CACHED", "INSTALLED"):
        return 1.0
    if cs == "PREVIEW_CACHED":
        return 0.8
    if cs == "METADATA_CACHED":
        return 0.5
    return 0.0


def _dep_count(r):
    deps = r.get("dependencies") or {}
    n = 0
    for k in ("npm_packages", "python_packages", "peer_dependencies"):
        v = deps.get(k)
        if isinstance(v, list):
            n += len(v)
    return n


def _verification_score(r):
    vs = r.get("verification_status") or "UNKNOWN"
    return {"CURRENT": 1.0, "STALE": 0.6, "UNKNOWN": 0.4, "BROKEN": 0.0}.get(vs, 0.4)


def license_summary(r):
    lic = r.get("license") or {}
    t = (lic.get("license_type") or "UNKNOWN").upper()
    parts = [t]
    if lic.get("commercial_use") is True:
        parts.append("可商用")
    elif lic.get("commercial_use") is False:
        parts.append("不可商用")
    else:
        parts.append("商用未知")
    if lic.get("attribution_required"):
        parts.append("需署名")
    if lic.get("license_review_required") is True or t == "UNKNOWN":
        parts.append("需审核")
    return "，".join(parts)


def deps_summary(r):
    deps = r.get("dependencies") or {}
    items = []
    for k in ("npm_packages", "python_packages", "peer_dependencies"):
        v = deps.get(k)
        if isinstance(v, list) and v:
            items.extend(f"{k[:-9]}:{x}" if k == "peer_dependencies" else x for x in v)
    compat = []
    for k in ("remotion_compat", "react_compat", "threejs_requirements"):
        v = deps.get(k)
        if v and str(v).lower() != "none":
            compat.append(f"{k}={v}")
    if not items and not compat:
        return "无"
    return "; ".join((items + compat)[:6])


def potential_problem(r, prov, license_mode):
    problems = []
    lic = r.get("license") or {}
    t = (lic.get("license_type") or "UNKNOWN").upper()
    if lic.get("license_review_required") is True or t == "UNKNOWN":
        problems.append("license 需人工审核(UNKNOWN)")
    if lic.get("commercial_use") is False and license_mode == "commercial":
        problems.append("不可商用")
    vs = r.get("verification_status")
    if vs == "BROKEN":
        problems.append("来源不可达(BROKEN)")
    elif vs == "STALE":
        problems.append("验证过期(STALE)")
    elif vs == "UNKNOWN":
        problems.append("未验证(UNKNOWN)")
    if r.get("availability") == "REMOTE_OFFLINE":
        problems.append("远端不可达")
    if prov:
        if (prov.get("status") or "ACTIVE") == "DEGRADED":
            problems.append("provider 降级(DEGRADED)")
        auth = prov.get("authentication")
        if auth not in (None, "NONE", "UNKNOWN"):
            problems.append(f"需认证({auth})")
    b = r.get("estimated_size_bytes")
    if isinstance(b, (int, float)) and b >= 100 * 1024 * 1024:
        problems.append(f"体积大({human_size(b)})")
    if r.get("status") == "DEPRECATED":
        problems.append("DEPRECATED")
    if not problems:
        return "无明显风险"
    return "; ".join(problems[:4])


def fetch_classify(r):
    if (r.get("resource_nature") or "").upper() == "PACKAGE":
        return "EXTERNAL_INSTALL"
    b = r.get("estimated_size_bytes")
    if isinstance(b, (int, float)) and b >= 0:
        if b >= 100 * 1024 * 1024:
            return "LARGE"
        if b >= 1024 * 1024:
            return "MEDIUM"
        return "LIGHTWEIGHT"
    lt = r.get("type")
    if lt in ("THREE_D_MODEL", "HDRI", "SOUNDFONT", "FOOTAGE"):
        return "LARGE"
    if lt in ("MUSIC", "TEXTURE", "IMAGE"):
        return "MEDIUM"
    return "LIGHTWEIGHT"


def estimate_size_text(r):
    b = r.get("estimated_size_bytes")
    if isinstance(b, (int, float)) and b >= 0:
        return human_size(b)
    return f"未知(类型 {r.get('type')} 估算 {fetch_classify(r).lower()})"


def reuse_for_fit(fit, top_cand=None):
    """§109-111：fit>=0.9 USE_AS_IS；0.6-0.9 ADAPT；0.35-0.6 COMPOSE；否则 BUILD_NEW+why。"""
    if fit >= 0.90:
        return "USE_AS_IS", ""
    if fit >= 0.60:
        return "ADAPT", "需按项目需求调整参数/时序（改动面见 potential_problem）"
    if fit >= 0.35:
        return "COMPOSE", "需与其它候选/本地资产组合使用"
    why = "现有候选均不满足（top: %s，fit %.2f，%s）"
    why = why % ((top_cand["resource_id"] if top_cand else "无"), fit,
                 (top_cand or {}).get("potential_problem", "匹配度不足"))
    return "BUILD_NEW", why


def reuse_for_fit_obj(fit, top_cand=None):
    code, why = reuse_for_fit(fit, top_cand)
    return {"reuse_recommendation": code, "reuse_note": why}


def filter_candidates(store, rs, tokens, whole, *, types=None, provider=None, tags=None,
                      style=None, best_for=None, license_mode="any", local_only=False,
                      offline=False, bake_policy=None):
    out = []
    warnings = []
    for r in rs:
        if r.get("status") == "RETIRED":
            continue
        if types and r.get("type") not in types:
            continue
        if provider and r.get("provider") != provider:
            continue
        if tags:
            tagset = {t.lower() for t in (r.get("tags") or [])}
            if not all(t in tagset for t in tags):
                continue
        if style:
            sset = {s.lower() for s in (r.get("style") or [])} | \
                   {t.lower() for t in (r.get("tags") or [])}
            if not any(t in sset for t in style):
                continue
        if best_for:
            bjoin = " ".join(r.get("best_for") or []).lower()
            if not any(t in bjoin for t in best_for):
                continue
        if license_mode == "commercial":
            lic = r.get("license") or {}
            t = (lic.get("license_type") or "UNKNOWN").upper()
            if lic.get("commercial_use") is not True or t == "UNKNOWN":
                continue
        if local_only:
            cs = (r.get("local_state") or {}).get("cache_state") or "NOT_CACHED"
            if cs == "NOT_CACHED" and r.get("availability") != "LOCAL_ONLY":
                continue
        if offline:
            cs = (r.get("local_state") or {}).get("cache_state") or "NOT_CACHED"
            if r.get("availability") != "LOCAL_ONLY" and cs == "NOT_CACHED":
                continue
        if bake_policy == "KEEP_EDITABLE":
            # 非 CODE/KNOWLEDGE 本质不降权（仅排序扣分），此处不过滤；由 score 调整处理
            pass
        out.append(r)
    return out, warnings


def search(store, query, *, types=None, provider=None, tags=None, style=None, best_for=None,
           license_mode="any", local_only=False, offline=False, route=None,
           proj_style=None, avoid_tokens=None, bake_policy=None, request_style=None):
    """过滤链 + 排序 8 因子 + 多样化。返回 (ranked, meta)。"""
    warnings = list(store.warnings)
    provider_errors = {}
    tokens = tokenize_query(query)
    whole = query.strip().lower() if query else ""

    # provider 失败隔离（§98）：BROKEN provider 剔除并记录
    ok_providers = set(store.providers)
    for pid, p in store.providers.items():
        if (p.get("status") or "ACTIVE") == "BROKEN":
            provider_errors[pid] = "provider status=BROKEN，已从候选剔除"
            ok_providers.discard(pid)

    rs = [r for r in store.resources if r.get("provider") in ok_providers]
    rs, _ = filter_candidates(store, rs, tokens, whole, types=types, provider=provider,
                              tags=tags, style=style, best_for=best_for,
                              license_mode=license_mode, local_only=local_only,
                              offline=offline, bake_policy=bake_policy)

    # route-aware（§44）：偏好类型加权
    route_pref = []
    if route:
        rte = norm_enum(route, ROUTES)
        if rte:
            route_pref = ROUTE_TYPE_MAP.get(rte, [])

    # 项目风格：--project-dir 的 VISUAL_BIBLE 或 request.style 优先
    pstyle = proj_style or []
    avoid = avoid_tokens or []
    if request_style:
        extra = [t for t in re.split(r"[_\-\s,/]+", request_style.lower()) if t in STYLE_VOCAB]
        pstyle = list(dict.fromkeys(pstyle + extra))

    ranked = []
    for r in rs:
        prov = store.provider(r.get("provider")) or {}
        qscore, hits = _query_hits(r, tokens, whole)
        max_q = 3.0 * max(1, len(tokens)) + 2.0
        rel = min(1.0, qscore / max_q)
        type_fit = 1.0
        type_note = ""
        if route_pref:
            if r.get("type") in route_pref:
                rel = min(1.0, rel + 0.25)
                type_fit = 1.25
                type_note = f"类型 {r['type']} 属 route={route} 偏好"
        if types:
            type_fit *= 1.2

        style_f, avoid_hits = _style_factor(r, pstyle, avoid)
        style_note = ""
        if avoid_hits:
            style_note = f"avoid 命中({', '.join(sorted(avoid_hits))}) 降权"
        elif style_f > 0 and pstyle:
            matched_style = sorted((set(r.get('style') or [])
                                    | {t.lower() for t in (r.get('tags') or [])}) & set(pstyle))
            style_note = f"风格 {matched_style or 'tag'} 匹配项目风格"

        best_f = _best_for_factor(r, tokens)
        prov_prio = (prov.get("priority") or 0) if isinstance(prov.get("priority"), (int, float)) else 0
        lic_s = _license_score(r, license_mode)
        local_s = _local_score(r)
        dep_s = 1.0 / (1.0 + _dep_count(r))       # dependency 因子：依赖越少越高
        ver_s = _verification_score(r)            # verification 可信度：降级为 tie-break 次级排序键（不占主 score 权重）
        prev_s = 1.0 if (r.get("preview") or {}).get("type") not in (None, "none") else 0.0

        # bake_policy=KEEP_EDITABLE 约束（§107）：非 CODE/KNOWLEDGE 本质扣分
        bake_penalty = 0.0
        bake_note = ""
        if bake_policy == "KEEP_EDITABLE" and (r.get("resource_nature") or "MEDIA") not in ("CODE", "KNOWLEDGE"):
            bake_penalty = 0.05
            bake_note = " 非 CODE/KNOWLEDGE，KEEP_EDITABLE 下可能不可拆 Bake"

        # 排序 8 因子（规格 §13：relevance / best_for / style / provider_priority /
        # license / local_availability / dependency / preview）。
        # verification（CURRENT/STALE 可信度）与 size_cost 已从 factors 与主 score 移除：
        #   - verification 保留为 tie-break 次级排序键（见下方 ranked.sort），不占 8 因子权重；
        #   - size_cost 不再参与评分。
        factors = {
            "relevance": round(min(1.0, rel), 3),
            "best_for": round(best_f, 3),
            "style": round(max(0.0, style_f), 3),
            "provider_priority": round(min(1.0, prov_prio / 10.0), 3),
            "license": round(lic_s, 3),
            "local_availability": round(local_s, 3),
            "dependency": round(dep_s, 3),   # 少依赖者得分高（依赖数越少越轻量）
            "preview": round(prev_s, 3),     # 有预览者得分高（preview.type != none）
        }
        # 8 因子权重（总和 1.0）：relevance 主导相关度；style / best_for 服务项目适配；
        # provider_priority 承接提供方优先级；dependency / preview 为规格新增并参与评分。
        score = (
            0.30 * factors["relevance"]
            + 0.12 * factors["best_for"]
            + 0.15 * factors["style"]
            + 0.10 * factors["provider_priority"]
            + 0.08 * factors["license"]
            + 0.07 * factors["local_availability"]
            + 0.10 * factors["dependency"]
            + 0.08 * factors["preview"]
            - bake_penalty
        )
        score = max(0.0, min(1.0, score))

        why = []
        if hits:
            why.append("命中词: " + ", ".join(sorted(hits)))
        if type_note:
            why.append(type_note)
        if style_note:
            why.append(style_note)
        if best_f > 0 and not type_note:
            bf = sorted(set(hits) & set(tokens))
            why.append(f"best_for 命中({', '.join(bf) or 'tag'})")
        why.append(f"provider {r['provider']} 优先级 {prov_prio}")
        if local_s >= 0.8:
            why.append(f"本地缓存 {(r.get('local_state') or {}).get('cache_state')}")
        if lic_s >= 0.9:
            why.append("license 可商用")
        if dep_s >= 0.9:
            why.append("无/少外部依赖")
        elif dep_s <= 0.4:
            why.append(f"依赖较多({_dep_count(r)} 个) 降权")
        if prev_s == 1.0:
            why.append(f"有预览({(r.get('preview') or {}).get('type')})")
        if bake_note:
            why.append(bake_note.strip())

        cand = Candidate(r, prov, score, factors, why, sorted(hits),
                         score, "", "", avoid_hits, style_f > 0)
        ranked.append(cand)

    # 主排序：score（8 因子加权，权重总和 1.0）降序。同分时以 provider_priority，
    # 再以 verification（CURRENT > STALE > UNKNOWN > BROKEN）作次级/三级 tie-break——
    # verification 的可信度语义在此保留，但不参与主 score 的 8 因子权重分配。
    ranked.sort(key=lambda c: (-c.score, -c.factors["provider_priority"],
                               -_verification_score(c.r)))
    return ranked, {"warnings": warnings, "provider_errors": provider_errors}


def apply_diversity(ranked, limit):
    """候选多样化（§105-106）：仅当同一 provider 在 top 中占 ≥3 且存在高质量替代时，
    穿插其它 provider 的结果。避免为了多样化牺牲相关度（不强制按 provider 配额截断）。"""
    if not ranked or limit <= 1:
        return ranked[:limit]
    pool = list(ranked)
    out = pool[:limit]
    per = {}
    for c in out:
        per[c.r.get("provider")] = per.get(c.r.get("provider"), 0) + 1
    distinct_all = len({c.r.get("provider") for c in pool})
    if distinct_all <= 1:
        return out
    rest = pool[limit:]
    for prov, cnt in list(per.items()):
        if cnt < 3:
            continue
        min_score = min(c.score for c in out if c.r.get("provider") == prov)
        best_alt = None
        for c in rest:
            if c.r.get("provider") == prov:
                continue
            if c.score >= 0.55 * max(0.01, min_score) and (best_alt is None
                                                           or c.score > best_alt.score):
                best_alt = c
        if best_alt is not None:
            idx = min((i for i, c in enumerate(out) if c.r.get("provider") == prov),
                      key=lambda i: out[i].score)
            out[idx] = best_alt
            per[prov] -= 1
    return out[:limit]


def apply_family(ranked):
    """家族（§118-121）：同 family 只保留 leader + 成员列表。"""
    fam = {}
    for c in ranked:
        fid = c.r.get("family_id")
        if fid:
            fam.setdefault(fid, []).append(c)
    out = []
    for c in ranked:
        fid = c.r.get("family_id")
        if fid:
            if c is not fam[fid][0]:
                continue
            c.family_members = [m.r["id"] for m in fam[fid][1:]]
            c.r = dict(c.r)
            c.r["family_members"] = c.family_members
        out.append(c)
    return out


def candidate_dict(c, license_mode):
    r = c.r
    lic = r.get("license") or {}
    est = estimate_size_text(r)
    dep = deps_summary(r)
    reuse, reuse_note = reuse_for_fit(c.fit if c.fit else c.score,
                                      {"resource_id": r["id"], "potential_problem":
                                       potential_problem(r, c.prov, license_mode)})
    c.reuse = reuse
    c.reuse_why = reuse_note
    return {
        "resource_id": r["id"],
        "name": r.get("name"),
        "provider": r.get("provider"),
        "type": r.get("type"),
        "resource_nature": r.get("resource_nature"),
        "why_matched": "; ".join(c.why),
        "best_use": (r.get("best_for") or ["通用"])[0],
        "potential_problem": potential_problem(r, c.prov, license_mode),
        "license": license_summary(r),
        "estimated_fetch_size": est,
        "dependencies": dep,
        "reuse_recommendation": reuse,
        "reuse_note": reuse_note,
        "score": round(c.score, 3),
        "factors": c.factors,
        "fit": round(max(c.fit, c.score), 3),
        "verification_status": r.get("verification_status"),
        "availability": r.get("availability"),
        "cache_state": (r.get("local_state") or {}).get("cache_state"),
        "family_members": r.get("family_members") or [],
        "preview_type": (r.get("preview") or {}).get("type"),
        "preview_url": (r.get("preview") or {}).get("url"),
        "source_url": r.get("source_url"),
    }


def run_find(args, store):
    query = " ".join(args.query or [])
    types = None
    if args.type:
        t = norm_enum(args.type, RESOURCE_TYPES)
        if not t:
            return cli_error(f"非法 --type {args.type!r}（合法: {', '.join(RESOURCE_TYPES)}）", args.json)
        types = [t]
    provider = args.provider
    tags = [t.strip().lower() for t in (args.tags or "").split(",") if t.strip()] if args.tags else None
    style = [s.strip().lower() for s in (args.style or "").split(",") if s.strip()] if args.style else None
    best_for = [b.strip().lower() for b in (args.best_for or "").split(",") if b.strip()] if args.best_for else None
    license_mode = args.license or "any"
    route = args.route
    proj_style = avoid = None
    if args.project_dir:
        pctx = extract_project_style(args.project_dir)
        proj_style = pctx["style_tokens"]
        avoid = pctx["avoid_tokens"]

    ranked, meta = search(
        store, query, types=types, provider=provider, tags=tags, style=style,
        best_for=best_for, license_mode=license_mode, local_only=args.local_only,
        offline=args.offline, route=route, proj_style=proj_style, avoid_tokens=avoid,
    )
    ranked = apply_family(ranked)
    ranked = apply_diversity(ranked, args.limit)
    results = [candidate_dict(c, license_mode) for c in ranked]

    payload = {
        "command": "find",
        "query": query,
        "filters": {
            "type": types, "provider": provider, "tags": tags, "style": style,
            "best_for": best_for, "license": license_mode, "local_only": args.local_only,
            "offline": args.offline, "route": route,
            "project_dir": args.project_dir,
            "project_style_tokens": proj_style or [],
            "project_avoid_tokens": avoid or [],
            "limit": args.limit,
        },
        "count": len(results),
        "results": results,
        "warnings": meta["warnings"],
        "provider_errors": meta["provider_errors"],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f'Registry find: "{query}"')
        print(f"  过滤: type={types or 'any'} provider={provider or 'any'} "
              f"license={license_mode} local_only={args.local_only} offline={args.offline} "
              f"route={route or 'any'} limit={args.limit}")
        if proj_style:
            print(f"  项目风格: {proj_style}  avoid: {avoid}")
        if not results:
            print("  （无命中）")
            if args.offline:
                print("  离线模式：仅本地已缓存条目可用（§97），未缓存远端候选不假称可用。")
            if meta["provider_errors"]:
                print(f"  provider 失败隔离: {meta['provider_errors']}")
            return 0
        for i, c in enumerate(results, 1):
            print(f"[{i}] {c['resource_id']}")
            print(f"    {c['name']} ({c['type']} / {c['resource_nature']}) "
                  f"provider={c['provider']}")
            print(f"    why: {c['why_matched']}")
            print(f"    best_use: {c['best_use']}")
            print(f"    license: {c['license']} | size: {c['estimated_fetch_size']} "
                  f"| deps: {c['dependencies']}")
            print(f"    reuse: {c['reuse_recommendation']} (fit {c['fit']:.2f})")
            if c["potential_problem"] != "无明显风险":
                print(f"    potential_problem: {c['potential_problem']}")
        if meta["provider_errors"]:
            print(f"  provider 失败隔离: {meta['provider_errors']}")
    return 0


def cli_error(msg, json_out):
    if json_out:
        print(json.dumps({"error": msg, "exit_code": 1}, ensure_ascii=False, indent=2))
    else:
        print(f"ERROR: {msg}")
    return 1


# ---------------------------------------------------------------------------
# detail / preview / fetch
# ---------------------------------------------------------------------------

def build_l1(r):
    """Level 1 Detail（§47 懒加载：只读单条目完整内容）。缺失字段标 未知/无，不编造。"""
    ts = r.get("type_specific") or {}
    lic = r.get("license") or {}
    desc = r.get("description") or r.get("summary") or "（无描述）"
    note = r.get("resource_type_note") or ""
    deps = r.get("dependencies") or {}

    def f3d(key):
        return ts.get("3d", {}).get(key) if isinstance(ts.get("3d"), dict) else None

    return {
        "resource_id": r["id"],
        "name": r.get("name"),
        "type": r.get("type"),
        "resource_nature": r.get("resource_nature"),
        "provider": r.get("provider"),
        "description": desc,
        "parameters": ts if ts else (note or "未知"),
        "dependencies": deps or "无",
        "compatibility": {
            k: v for k, v in deps.items()
            if k in ("remotion_compat", "react_compat", "threejs_requirements")
        } or "无",
        "technical_requirements": note or "未知",
        "formats": f3d("formats") or (
            ts.get("soundfont", {}).get("format")
            if isinstance(ts.get("soundfont"), dict) else None) or "未知",
        "resolution_options": f3d("texture_resolutions") or
        (ts.get("texture", {}).get("resolution") if isinstance(ts.get("texture"), dict) else None) or "未知",
        "size": estimate_size_text(r),
        "license": lic,
        "commercial_use": lic.get("commercial_use"),
        "attribution_required": lic.get("attribution_required"),
        "attribution": "需署名" if lic.get("attribution_required") else "无需署名",
        "limitations": "；".join(r.get("avoid_when") or []) or "无记录",
        "usage_notes": r.get("resource_type_note") or r.get("summary") or "无",
        "tags": r.get("tags"),
        "best_for": r.get("best_for"),
        "style": r.get("style"),
        "source_url": r.get("source_url"),
        "last_verified": r.get("last_verified"),
        "verification_status": r.get("verification_status"),
        "availability": r.get("availability"),
        "metadata_version": r.get("metadata_version"),
        "added_by": r.get("added_by"),
        "added_at": r.get("added_at"),
        "discovery_source": r.get("discovery_source"),
        "local_state": r.get("local_state"),
        "preview": r.get("preview"),
    }


def run_detail(args, store):
    r = store.resolve_id(args.resource_id)
    if r is None:
        return cli_error(f"resource 不存在: {args.resource_id}", args.json)
    l1 = build_l1(r)
    if args.json:
        print(json.dumps({"command": "detail", "resource_id": r["id"], "level": "L1",
                          "detail": l1}, ensure_ascii=False, indent=2))
    else:
        print(f"detail L1 — {r['id']}")
        print(f"  name: {r.get('name')}  type: {r.get('type')}  nature: {r.get('resource_nature')}")
        print(f"  description: {l1['description']}")
        print(f"  parameters: {json.dumps(l1['parameters'], ensure_ascii=False)}")
        print(f"  dependencies: {deps_summary(r)}")
        print(f"  compatibility: {json.dumps(l1['compatibility'], ensure_ascii=False)}")
        print(f"  technical_requirements: {l1['technical_requirements']}")
        print(f"  formats: {l1['formats']}  resolution_options: {l1['resolution_options']}")
        print(f"  size: {l1['size']}  verification: {r.get('verification_status')} "
              f"last_verified: {r.get('last_verified')}")
        print(f"  license: {license_summary(r)}")
        print(f"  commercial_use: {l1['commercial_use']}  attribution: {l1['attribution']}")
        print(f"  limitations: {l1['limitations']}")
        print(f"  source_url: {r.get('source_url')}")
    return 0


def run_preview(args, store):
    r = store.resolve_id(args.resource_id)
    if r is None:
        return cli_error(f"resource 不存在: {args.resource_id}", args.json)
    pv = r.get("preview") or {"type": "none", "url": ""}
    ptype = pv.get("type")
    if ptype in (None, "none"):
        status = "not_available"
        out = {"resource_id": r["id"], "preview_status": status, "preview": None}
    else:
        status = "available"
        out = {"resource_id": r["id"], "preview_status": status, "preview": {
            "type": ptype, "url": pv.get("url") or "", "local_path": pv.get("local_path")}}
    if args.json:
        print(json.dumps({"command": "preview", **out}, ensure_ascii=False, indent=2))
    else:
        if status == "available":
            print(f"preview available — {r['id']}: {ptype} {pv.get('url') or ''}")
        else:
            print(f"preview not_available — {r['id']}（不假装存在，§50）")
    return 0


def safe_join(root, name):
    """path traversal 校验（§100）：name 不得含路径成分，结果必须落在 root 内。"""
    if not name or name in (".", ".."):
        raise ValueError(f"非法文件名 {name!r}")
    if any(ch in name for ch in ("/", "\\", "\x00")):
        raise ValueError(f"文件名含路径成分: {name!r}")
    root_r = root.resolve()
    p = (root / name).resolve()
    try:
        ok = p.is_relative_to(root_r)
    except AttributeError:  # pragma: no cover
        ok = str(p).startswith(str(root_r))
    if not ok:
        raise ValueError(f"目标路径逃出允许根目录: {p}（root={root_r}）")
    return p


def _slug_from_id(rid):
    parts = rid.split(":")
    if len(parts) != 3:
        return None
    slug = parts[2]
    if not slug or any(ch in slug for ch in ("/", "\\", "\x00", "..")):
        return None
    return slug


def run_fetch(args, store):
    r = store.resolve_id(args.resource_id)
    if r is None:
        return cli_error(f"resource 不存在: {args.resource_id}", args.json)
    if not ID_RE.match(r["id"]):
        return cli_error(f"resource id 非法: {r['id']}", args.json)
    slug = _slug_from_id(r["id"])
    if slug is None:
        return cli_error(f"resource id 无法提取安全 slug: {r['id']}", args.json)

    # 安全根目录：--project-dir 的项目目录 或 cache_dir
    roots = []
    if args.project_dir:
        roots.append(Path(args.project_dir).resolve())
    roots.append(store.cache_dir.resolve())
    dest = Path(args.dest).resolve() if args.dest else roots[0]
    if not any(dest == rt or (try_rel := _is_rel(dest, rt)) for rt in roots):
        return cli_error(
            f"--dest 逃出允许根目录（允许: {[str(r) for r in roots]}）: {dest}", args.json)

    fclass = fetch_classify(r)
    lic = r.get("license") or {}
    src = r.get("source_url") or ""
    ext = ""
    if src:
        ext = Path(urlparse(src).path).suffix if urlparse(src).path else ""
    fname = f"{slug}{ext}"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        local_path = safe_join(dest, fname)
    except ValueError as exc:
        return cli_error(f"安全校验失败: {exc}", args.json)

    nature = (r.get("resource_nature") or "").upper()
    if nature == "CODE":
        method = "copy-component"
    elif nature == "PACKAGE":
        method = "package-install"
    else:
        method = "single-file"

    snapshot = {
        "license_identifier": lic.get("license_type") or "UNKNOWN",
        "source_url": src,
        "date": now_iso(),
        "attribution": "需署名" if lic.get("attribution_required") else "无需署名",
    }
    attr_text = (f"需署名: {r.get('name')} — {lic.get('license_type')} ({src})"
                 if lic.get("attribution_required") else "无需署名")
    attr_url = lic.get("license_url") or ""

    if fclass in ("LARGE", "EXTERNAL_INSTALL"):
        # Approval Gate（§52-55）：Explain -> Size -> Why -> Alternatives -> Approval；不下载
        alternatives = []
        for c in _cheap_alternatives(store, r):
            alternatives.append(c["resource_id"])
        payload = {
            "command": "fetch",
            "resource_id": r["id"],
            "fetch_class": fclass,
            "approval_required": True,
            "dry_run": True,
            "approval": {
                "Explain": r.get("summary") or r.get("name"),
                "Size": estimate_size_text(r),
                "Why": f"fclass={fclass} 需审批；{r.get('summary') or ''}",
                "Alternatives": alternatives,
            },
            "fetch_method": method,
            "local_state": r.get("local_state"),
            "license_snapshot": snapshot,
            "attribution_text": attr_text,
            "attribution_url": attr_url,
            "security_warning": ("禁止自动执行任何脚本/安装步骤；EXTERNAL_INSTALL 必须先经人工审批"
                                 if fclass == "EXTERNAL_INSTALL" else
                                 "大文件获取需审批后再执行；本命令未执行任何下载（Phase 4 不真下载）"),
            "note": "Phase 4 不执行真实下载；审批通过后由 Phase 5+ adapter 完成。",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"fetch — {r['id']}  [分类: {fclass}]")
            print(f"  approval_required: True（Approval Gate）")
            print(f"  Explain: {payload['approval']['Explain']}")
            print(f"  Size: {payload['approval']['Size']}")
            print(f"  Why: {payload['approval']['Why']}")
            print(f"  Alternatives: {payload['approval']['Alternatives']}")
            print(f"  security_warning: {payload['security_warning']}")
            print(f"  未执行下载。")
        return 0

    # LIGHTWEIGHT / MEDIUM：--dry-run 外模拟 cache 状态推进（Phase 4 演示路径）
    if args.dry_run:
        payload = {
            "command": "fetch",
            "resource_id": r["id"],
            "fetch_class": fclass,
            "approval_required": False,
            "dry_run": True,
            "fetch_method": method,
            "plan": f"将 payload 复制到 {local_path}（模拟）并推进 cache_state -> PAYLOAD_CACHED + license snapshot 落盘",
            "license_snapshot": snapshot,
            "attribution_text": attr_text,
            "attribution_url": attr_url,
            "security_warning": "仅落盘，不自动执行任何脚本（§101）。",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"fetch (dry-run) — {r['id']}  [分类: {fclass}]")
            print(f"  plan: {payload['plan']}")
            print(f"  security_warning: {payload['security_warning']}")
        return 0

    # 模拟推进 cache 状态机：NOT_CACHED -> PAYLOAD_CACHED
    new_state = {
        "cache_state": "PAYLOAD_CACHED",
        "local_path": str(local_path),
        "downloaded_at": now_iso(),
        "license_snapshot": json.dumps(snapshot, ensure_ascii=False),
    }
    store._overlay[r["id"]] = new_state
    try:
        store.save_local_state()
    except FatalError as exc:
        return cli_error(str(exc), args.json)
    r["local_state"] = new_state
    payload = {
        "command": "fetch",
        "resource_id": r["id"],
        "fetch_class": fclass,
        "approval_required": False,
        "dry_run": False,
        "fetch_method": method,
        "local_state": new_state,
        "license_snapshot": snapshot,
        "attribution_text": attr_text,
        "attribution_url": attr_url,
        "credits_line": (f"{r.get('name')} — {lic.get('license_type')} — {src}"
                         if lic.get("attribution_required") else None),
        "security_warning": "仅模拟落盘；Phase 4 不真下载，不自动执行脚本（§101）。",
        "note": "模拟推进 cache_state -> PAYLOAD_CACHED（Phase 4 演示路径，§99）。",
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"fetch — {r['id']}  [分类: {fclass}]")
        print(f"  cache_state -> {new_state['cache_state']}  local_path: {new_state['local_path']}")
        print(f"  license_snapshot: {new_state['license_snapshot']}")
        print(f"  attribution_text: {attr_text}")
        print(f"  security_warning: {payload['security_warning']}")
    return 0


def _is_rel(p, root):
    try:
        return p.is_relative_to(root)
    except AttributeError:  # pragma: no cover
        return str(p).startswith(str(root))


def _cheap_alternatives(store, r, n=2):
    """为审批块生成替代候选（同 type 的其它条目）。"""
    out = []
    for o in store.resources:
        if o["id"] == r["id"] or o.get("type") != r.get("type"):
            continue
        out.append(candidate_dict(Candidate(o, store.provider(o.get("provider")) or {},
                                            0.0, {}, [], [], 0.0, "", "", set(), False),
                                  "any"))
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------------------
# add / update / validate
# ---------------------------------------------------------------------------

def run_add(args, store):
    if not args.file:
        return cli_error("add 需要 --file <json|yaml>", args.json)
    fpath = Path(args.file)
    if not fpath.is_file():
        return cli_error(f"文件不存在: {fpath}", args.json)
    data, err = load_json_or_yaml(fpath)
    if err is not None:
        return cli_error(err, args.json)
    if not isinstance(data, dict):
        return cli_error("add 文件顶层必须是 resource 对象", args.json)

    # schema 关键字段轻量校验
    missing = [k for k in RESOURCE_SCHEMA_REQUIRED if k not in data]
    if missing:
        return cli_error(f"缺少 schema 必填字段: {missing}", args.json)
    if not ID_RE.match(str(data.get("id") or "")):
        return cli_error(f"id 非法（应为 {{provider}}:{{type}}:{{slug}}）: {data.get('id')!r}", args.json)
    if norm_enum(data.get("type"), RESOURCE_TYPES) is None:
        return cli_error(f"type 非法: {data.get('type')!r}", args.json)
    lic = data.get("license")
    if not isinstance(lic, dict) or not lic.get("license_type"):
        return cli_error("license 对象缺失或 license_type 缺失（License 硬需求 §60-61）", args.json)

    new = normalize_resource(data)
    new["id"] = str(data["id"]).strip()

    # 重复检测（§74）
    dup = None
    for existing in store.resources:
        if existing["id"] == new["id"]:
            dup = f"id 相同: {existing['id']}"
            break
        if (existing.get("provider") == new["provider"]
                and (existing.get("source_url") or "").strip()
                and (existing.get("source_url") or "").strip() == (new.get("source_url") or "").strip()):
            dup = f"source_url 相同 (provider+source_url 视为重复): {existing['id']}"
            break
        if (existing.get("provider") == new["provider"]
                and (existing.get("name") or "").strip().lower()
                and (existing.get("name") or "").strip().lower() == (new.get("name") or "").strip().lower()):
            dup = f"provider+name 相同: {existing['id']}"
            break
    if dup:
        if args.json:
            print(json.dumps({"command": "add", "status": "duplicate", "reason": dup,
                              "resource_id": new["id"], "exit_code": 1},
                             ensure_ascii=False, indent=2))
        else:
            print(f"DUPLICATE — 拒绝写入: {dup}")
        return 1

    # 归一化写入（保留 aliases；记录 added_by / added_at / discovery_source）
    new.setdefault("aliases", [])
    new["metadata_version"] = new.get("metadata_version") or "1.0"
    new["added_by"] = args.source if args.source else "user"
    new["added_at"] = new.get("added_at") or now_iso()
    new["discovery_source"] = new.get("discovery_source") or "user-input"
    new["last_verified"] = new.get("last_verified") or new["added_at"]
    new["local_state"] = {"cache_state": "NOT_CACHED"}
    new["verification_status"] = norm_enum(new.get("verification_status"), VERIFICATION,
                                           default="UNKNOWN")

    try:
        resources = list(store.resources)
        resources.append(new)
        store.save_resources(resources)
        store.resources = resources
    except FatalError as exc:
        return cli_error(str(exc), args.json)

    if args.json:
        print(json.dumps({"command": "add", "status": "added", "resource_id": new["id"],
                          "index": str(store.resources_file), "exit_code": 0},
                         ensure_ascii=False, indent=2))
    else:
        print(f"ADDED — {new['id']} -> {store.resources_file}")
        print(f"  aliases: {new.get('aliases')}  added_by: {new['added_by']}  "
              f"added_at: {new['added_at']}  discovery_source: {new['discovery_source']}")
    return 0


def run_update(args, store):
    today = datetime.date.today()
    changes = []
    for r in store.resources:
        if args.provider and r.get("provider") != args.provider:
            continue
        vs = r.get("verification_status")
        if vs == "BROKEN":
            changes.append({"id": r["id"], "from": vs, "to": "BROKEN",
                            "note": "BROKEN 保留标记，需人工提供修复信息（§69）"})
            continue
        if vs == "UNKNOWN":
            changes.append({"id": r["id"], "from": vs, "to": "UNKNOWN",
                            "note": "UNKNOWN 保持，等待人工验证"})
            continue
        last = parse_date(r.get("last_verified"))
        if vs == "CURRENT" and last is not None and (today - last).days > STALE_WINDOW_DAYS:
            changes.append({"id": r["id"], "from": "CURRENT", "to": "STALE",
                            "note": f"last_verified {r.get('last_verified')} "
                                    f"> {STALE_WINDOW_DAYS} 天（§67）"})

    payload = {
        "command": "update",
        "provider": args.provider or "all",
        "window_days": STALE_WINDOW_DAYS,
        "change_count": len(changes),
        "changes": changes,
        "persisted": False,
        "note": "update 不发网络；默认 dry-run 不改 registry/ 数据。"
                "设 ZHOU_REGISTRY_INDEX_DIR 或 --apply 以写库。",
    }
    if changes and args.apply and store.writable:
        resources = list(store.resources)
        for ch in changes:
            for r in resources:
                if r["id"] == ch["id"]:
                    r["verification_status"] = ch["to"]
                    r["metadata_version"] = _bump_version(r.get("metadata_version"))
                    break
        try:
            store.save_resources(resources)
            store.resources = resources
            payload["persisted"] = True
        except FatalError as exc:
            return cli_error(str(exc), args.json)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"update — provider={payload['provider']} 变更 {payload['change_count']} 条")
        for ch in changes:
            print(f"  {ch['id']}: {ch['from']} -> {ch['to']}  ({ch['note']})")
        print(f"  {payload['note']}")
    return 0


def _bump_version(v):
    try:
        return f"{float(v) + 0.1:.1f}"
    except (TypeError, ValueError):
        return "1.1"


VALIDATE_CHECKS = [
    "id_unique", "provider_exists", "type_valid", "source_url_present",
    "license_fields", "preview_ref_format", "metadata_required",
]


def run_validate(args, store):
    checks = {cid: {"fail": 0, "messages": []} for cid in VALIDATE_CHECKS}
    ids = {}
    provider_ids = set(store.providers)

    # 用原始（未归一化）数据校验，确保非规范枚举 / 非法引用被真实捕获
    pairs = list(zip(store.resources, store.raw_resources)) if len(store.raw_resources) == \
        len(store.resources) else list(zip(store.resources, store.resources))
    for r, raw in pairs:
        rid = raw.get("id") or r.get("id") or ""
        # 1. id unique
        if rid in ids:
            checks["id_unique"]["fail"] += 1
            checks["id_unique"]["messages"].append(f"重复 id: {rid}")
        ids[rid] = True
        if not ID_VALIDATE_RE.match(rid):
            checks["id_unique"]["fail"] += 1
            checks["id_unique"]["messages"].append(f"id 格式非法: {rid}")

        # 2. provider exists
        prov = raw.get("provider") or r.get("provider")
        if prov not in provider_ids:
            checks["provider_exists"]["fail"] += 1
            checks["provider_exists"]["messages"].append(
                f"{rid}: provider {prov!r} 不在 providers.json")

        # 3. type valid（大小写不敏感）
        rtype = raw.get("type")
        if norm_enum(rtype, RESOURCE_TYPES) is None:
            checks["type_valid"]["fail"] += 1
            checks["type_valid"]["messages"].append(f"{rid}: type {rtype!r} 非法")

        # 4. source_url present
        su = raw.get("source_url")
        if not isinstance(su, str) or not su.strip():
            checks["source_url_present"]["fail"] += 1
            checks["source_url_present"]["messages"].append(f"{rid}: source_url 缺失")

        # 5. license fields（raw 层校验：必填键 + UNKNOWN 规则）
        lic = raw.get("license")
        if not isinstance(lic, dict):
            checks["license_fields"]["fail"] += 1
            checks["license_fields"]["messages"].append(f"{rid}: license 缺失")
        else:
            for k in ("license_type", "license_url", "commercial_use", "attribution_required",
                      "derivatives_allowed", "redistribution_allowed", "license_notes"):
                if k not in lic:
                    checks["license_fields"]["fail"] += 1
                    checks["license_fields"]["messages"].append(f"{rid}: license 缺字段 {k}")
            lt = (lic.get("license_type") or "UNKNOWN").upper()
            if lt == "UNKNOWN" and lic.get("license_review_required") is not True:
                checks["license_fields"]["fail"] += 1
                checks["license_fields"]["messages"].append(
                    f"{rid}: license_type=UNKNOWN 且 license_review_required 未置 true（§61）")

        # 6. preview reference format（raw 层校验：type 枚举 + url）
        pv = raw.get("preview")
        if not isinstance(pv, dict):
            checks["preview_ref_format"]["fail"] += 1
            checks["preview_ref_format"]["messages"].append(f"{rid}: preview 缺失")
        else:
            ptype = pv.get("type")
            if ptype not in PREVIEW_TYPE_SET:
                checks["preview_ref_format"]["fail"] += 1
                checks["preview_ref_format"]["messages"].append(
                    f"{rid}: preview.type {ptype!r} 非法")
            if "url" not in pv:
                checks["preview_ref_format"]["fail"] += 1
                checks["preview_ref_format"]["messages"].append(f"{rid}: preview 缺 url")
            elif ptype != "none" and not pv.get("url"):
                checks["preview_ref_format"]["fail"] += 1
                checks["preview_ref_format"]["messages"].append(
                    f"{rid}: preview.type={ptype} 但 url 为空")

        # 7. metadata schema 关键字段
        missing = [k for k in RESOURCE_SCHEMA_REQUIRED if k not in raw]
        if missing:
            checks["metadata_required"]["fail"] += 1
            checks["metadata_required"]["messages"].append(f"{rid}: 缺字段 {missing}")
        if not isinstance(raw.get("tags"), list) or len(raw.get("tags") or []) > 15:
            checks["metadata_required"]["fail"] += 1
            checks["metadata_required"]["messages"].append(f"{rid}: tags 数量非法")
        if len(raw.get("best_for") or []) > 10:
            checks["metadata_required"]["fail"] += 1
            checks["metadata_required"]["messages"].append(f"{rid}: best_for 超过 10")

    total_fail = sum(v["fail"] for v in checks.values())
    results = []
    for cid in VALIDATE_CHECKS:
        v = checks[cid]
        status = "pass" if v["fail"] == 0 else "fail"
        msg = f"{v['fail']} 处失败" if v["fail"] else "通过"
        if v["messages"]:
            msg += " | " + "; ".join(v["messages"][:3])
        results.append({"check": cid, "status": status, "message": msg,
                        "fail_count": v["fail"]})

    payload = {
        "command": "validate",
        "index": str(store.resources_file),
        "resource_count": len(store.resources),
        "exit_code": 1 if total_fail else 0,
        "checks": results,
        "warnings": store.warnings[:20],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Registry validate — {payload['index']}（{len(store.resources)} 条资源）")
        for r in results:
            print(f"  [{r['status'].upper():4}] {r['check']:<22} {r['message']}")
        if store.warnings:
            print("  warnings:")
            for w in store.warnings[:10]:
                print(f"    - {w}")
    return 1 if total_fail else 0


# ---------------------------------------------------------------------------
# Router -> Registry 桥（request 生成 §80-81 / §107 / §114-115）
# ---------------------------------------------------------------------------

def load_layer_list(layer_data):
    """归一化 layer 列表：dict 可能包着 'layers' key，或单 layer，或 list。"""
    if layer_data is None:
        return []
    if isinstance(layer_data, list):
        return [l for l in layer_data if isinstance(l, dict)]
    if isinstance(layer_data, dict):
        if isinstance(layer_data.get("layers"), list):
            return [l for l in layer_data["layers"] if isinstance(l, dict)]
        if "layer_id" in layer_data or "id" in layer_data:
            return [layer_data]
    return []


def load_layers_for_shot(layers_dir, shot_id):
    layers = []
    if not layers_dir.is_dir():
        return layers
    for f in sorted(layers_dir.iterdir()):
        if f.suffix.lower() not in (".yaml", ".yml", ".json"):
            continue
        data, err = load_json_or_yaml(f)
        if err is not None:
            continue
        for l in load_layer_list(data):
            sid = l.get("shot_id") or l.get("shot")
            if sid == shot_id or f.stem == shot_id:
                layers.append(l)
    return layers


def extract_audio_direction(project_dir):
    """从 AUDIO_DIRECTION.md 提取 music mood/energy/bpm（§45；无法确定标 UNKNOWN，不伪造）。"""
    info = {"mood": "UNKNOWN", "energy": "UNKNOWN", "bpm": "UNKNOWN",
            "narration_friendly": "UNKNOWN", "loopable": "UNKNOWN"}
    p = Path(project_dir) / "AUDIO_DIRECTION.md"
    if not p.is_file():
        return info
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return info
    m = re.search(r"BPM(?:\s*范围)?\s*[:：]\s*`?\s*(\d+)\s*[-–—]\s*(\d+)", text)
    if m:
        info["bpm"] = f"{m.group(1)}-{m.group(2)}"
    # 能量：Energy 相关行内 低/中/高 统计
    energy_sec = re.search(r"(?:Energy|能量)[^\n]*", text)
    if energy_sec:
        s = energy_sec.group(0)
        if "高" in s:
            info["energy"] = "HIGH" if "低" not in s else "MEDIUM"
        elif "中" in s:
            info["energy"] = "MEDIUM"
        elif "低" in s:
            info["energy"] = "LOW"
        else:
            info["energy"] = "MEDIUM"
    if "旁白" in text or "VO" in text:
        info["narration_friendly"] = True
    return info


def generate_requests(project_dir):
    """读 routing/S###.yaml + layers/S###.yaml + shots/S###.json + AUDIO_DIRECTION/VISUAL_BIBLE，
    生成 resource-request 列表（HYBRID 拆多个 request，§115）。"""
    pd = Path(project_dir)
    routing_dir = pd / "routing"
    layers_dir = pd / "layers"
    shots_dir = pd / "shots"
    if not routing_dir.is_dir():
        raise FatalError(f"routing 目录不存在: {routing_dir}")

    project_id = pd.name
    style_ctx = extract_project_style(pd)
    style_str = " ".join(style_ctx["style_tokens"])
    audio = extract_audio_direction(pd)
    reqs = []
    seq = [0]

    def new_id():
        seq[0] += 1
        return f"RR-{seq[0]:03d}"

    def add_req(types_, description, shot=None, layer=None, route=None, cont=None):
        if not types_ or not description:
            return None
        rid = new_id()
        rq = {
            "request_id": rid,
            "project_id": project_id,
            "resource_types": types_,
            "description": description[:500],
            "status": "OPEN",
            "scene_id": None,
            "shot_id": shot,
            "layer_id": layer,
            "style": style_str or None,
            "technical_requirements": None,
            "license_requirements": "CC0 或可商用",
            "size_preference": "ANY",
            "quality_preference": "ANY",
            "local_preferred": False,
            "provider_preferences": [],
            "avoid": [],
            "avoid_style_tokens": style_ctx["avoid_tokens"],  # 引擎扩展：VISUAL_BIBLE avoid 词
            "created_at": now_iso(),
            "route": route or "UNDECIDED",
            "bake_policy": None,
            "continuity_group": cont,
        }
        reqs.append(rq)
        return rq

    routing_files = sorted(routing_dir.glob("S*.yaml")) + sorted(routing_dir.glob("S*.yml"))
    if not routing_files:
        routing_files = sorted(routing_dir.glob("*.yaml")) + sorted(routing_dir.glob("*.yml"))
    if not routing_files:
        raise FatalError(f"routing 目录无路由文件: {routing_dir}")

    for rf in routing_files:
        data, err = load_json_or_yaml(rf)
        if err is not None:
            continue
        if not isinstance(data, dict):
            continue
        route = norm_enum(data.get("route"), ROUTES, default="UNDECIDED")
        shot_id = data.get("shot_id") or data.get("target_id") or rf.stem
        cont = data.get("continuity_group")
        decision = data.get("decision_summary") or ""

        shot = {}
        sp = shots_dir / f"{shot_id}.json"
        if sp.is_file():
            shot, _ = load_json_or_yaml(sp)
            if not isinstance(shot, dict):
                shot = {}
        sfx_list = []
        music_mode = None
        audio_obj = shot.get("audio") if isinstance(shot, dict) else None
        if isinstance(audio_obj, dict):
            sfx_list = audio_obj.get("sfx") or []
            if isinstance(sfx_list, str):
                sfx_list = [sfx_list]
            m = audio_obj.get("music")
            if isinstance(m, dict):
                music_mode = m.get("mode")
        editability = "MEDIUM"
        vd = shot.get("visual_direction") if isinstance(shot, dict) else None
        if isinstance(vd, dict) and isinstance(vd.get("editability"), str):
            editability = vd["editability"].upper()
        bake = "KEEP_EDITABLE" if editability == "HIGH" else None

        layers = load_layers_for_shot(layers_dir, shot_id)
        visual = ""
        if isinstance(shot, dict):
            visual = shot.get("visual_description") or shot.get("narrative_purpose") or ""
        on_text = shot.get("on_screen_text") if isinstance(shot, dict) else None

        if route == "HYBRID":
            # 按 layer role/route 拆多个 request（§115），不产模糊单 query
            groups = []
            if layers:
                three_d = [l for l in layers
                           if (l.get("role") in ("3D_OBJECT", "LIGHTING", "PARTICLE")
                               or l.get("type") == "3D_OBJECT"
                               or l.get("route") == "THREE_D")]
                remo = [l for l in layers
                        if l not in three_d and
                        (l.get("role") in ("TYPOGRAPHY", "UI", "DATA", "SUBTITLE",
                                           "FOREGROUND", "OVERLAY", "SUBJECT",
                                           "BACKGROUND", "DECORATION", "ATMOSPHERE")
                         or l.get("route") in (None, "REMOTION", "JY_NATIVE", "UNDECIDED"))]
                foot = [l for l in layers
                        if l not in three_d and l not in remo and
                        l.get("role") in ("FOOTAGE", "IMAGE")]
                if three_d:
                    groups.append(("THREE_D", ["THREE_D_MODEL", "TEXTURE", "HDRI"], three_d))
                if remo:
                    groups.append(("REMOTION", ["MOTION_EFFECT", "TRANSITION", "REMOTION_COMPONENT"],
                                   remo))
                if foot:
                    groups.append(("REAL_FOOTAGE", ["FOOTAGE", "IMAGE"], foot))
            else:
                groups = [(rn, ts, []) for rn, ts in HYBRID_FALLBACK_GROUPS]
            for rname, types_, glayers in groups:
                if glayers:
                    for gl in glayers:
                        ldesc = gl.get("visual_description") or gl.get("name") or ""
                        lbake = norm_enum(gl.get("bake_policy"), BAKE_POLICIES) or bake
                        add_req(types_, f"{shot_id} {rname} 层: {ldesc}",
                                shot=shot_id, layer=gl.get("layer_id") or gl.get("id"),
                                route="THREE_D" if rname == "THREE_D" else "REMOTION",
                                cont=cont)
                        if lbake:
                            reqs[-1]["bake_policy"] = lbake
                else:
                    add_req(types_, f"{shot_id} HYBRID {rname} 组: {decision}",
                            shot=shot_id, route=rname, cont=cont)
        else:
            types_ = ROUTE_TYPE_MAP.get(route, ["MOTION_EFFECT", "TRANSITION",
                                                "REMOTION_COMPONENT"])
            desc_parts = [f"{shot_id}"]
            if visual:
                desc_parts.append(visual)
            if on_text:
                desc_parts.append(f"(屏文: {on_text})")
            if decision and not visual:
                desc_parts.append(decision)
            add_req(types_, " ".join(desc_parts), shot=shot_id, route=route, cont=cont)
            if bake:
                reqs[-1]["bake_policy"] = bake
                reqs[-1]["technical_requirements"] = "需要可编辑层（禁止 bake）"

        if sfx_list:
            add_req(["SFX"], f"{shot_id} SFX: {', '.join(sfx_list)}",
                    shot=shot_id, route=route, cont=cont)

    # 音乐请求（LIBRARY_MUSIC 路线，§45）
    if (pd / "AUDIO_DIRECTION.md").is_file():
        mdesc = (f"极简电子乐垫乐；mood={audio['mood']} energy={audio['energy']} "
                 f"bpm={audio['bpm']}；需适合旁白垫乐(narration_friendly="
                 f"{audio['narration_friendly']})")
        mreq = add_req(["MUSIC"], mdesc, route="REMOTION")
        if mreq:
            mreq["continuity_group"] = "MUSIC"
            mreq["style"] = (style_str + " music") if style_str else "music"
    return reqs


def write_requests(project_dir, reqs):
    out_dir = Path(project_dir) / "requests"
    out_dir.mkdir(parents=True, exist_ok=True)
    for rq in reqs:
        (out_dir / f"{rq['request_id']}.json").write_text(
            json.dumps(rq, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "requests.json").write_text(
        json.dumps(reqs, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_dir


def run_request(args, store):
    if not args.from_routing:
        return cli_error("request 需要 --from-routing <project_dir>", args.json)
    pd = Path(args.from_routing)
    if not pd.is_dir():
        return cli_error(f"项目目录不存在: {pd}", args.json)
    try:
        reqs = generate_requests(pd)
    except FatalError as exc:
        return cli_error(str(exc), args.json)
    if not reqs:
        return cli_error("未生成任何 request（routing 无有效条目）", args.json)
    out_dir = write_requests(pd, reqs)

    if args.json:
        print(json.dumps({"command": "request", "project_id": pd.name,
                          "project_dir": str(pd), "requests_dir": str(out_dir),
                          "count": len(reqs), "requests": reqs},
                         ensure_ascii=False, indent=2))
    else:
        print(f"request — {pd.name}: 生成 {len(reqs)} 个 request -> {out_dir}")
        from collections import Counter
        tc = Counter(t for rq in reqs for t in rq["resource_types"])
        print(f"  类型分布: {dict(tc)}")
        for rq in reqs:
            print(f"  {rq['request_id']} [{','.join(rq['resource_types'])}] "
                  f"{rq['description'][:70]}")
    return 0


# ---------------------------------------------------------------------------
# find --from-requests（§83 resource-selection 输出）
# ---------------------------------------------------------------------------

def load_requests(source):
    src = Path(source)
    reqs = []
    if src.is_dir():
        files = sorted(src.glob("RR-*.json"))
    elif src.is_file():
        files = [src]
    else:
        raise FatalError(f"requests 路径不存在: {source}")
    for f in files:
        data, err = load_json_or_yaml(f)
        if err is not None:
            continue
        if isinstance(data, list):
            for o in data:
                if isinstance(o, dict) and o.get("request_id"):
                    reqs.append(o)
        elif isinstance(data, dict):
            if data.get("request_id"):
                reqs.append(data)
            elif isinstance(data.get("requests"), list):
                for o in data["requests"]:
                    if isinstance(o, dict) and o.get("request_id"):
                        reqs.append(o)
    # 去重 + 稳定排序
    seen = set()
    out = []
    for rq in sorted(reqs, key=lambda r: r.get("request_id") or ""):
        if rq["request_id"] not in seen:
            seen.add(rq["request_id"])
            out.append(rq)
    return out


def build_selection(store, rq, n_alt=2):
    """对单个 request 生成 resource-selection（§83）。"""
    qtext = f"{rq.get('description') or ''}"
    style = rq.get("style")
    pstyle = None
    avoid = None
    if style:
        pstyle = [t for t in re.split(r"[_\-\s,/]+", style.lower()) if t in STYLE_VOCAB]
    av = rq.get("avoid_style_tokens")
    if av:
        avoid = [t.lower() for t in av if isinstance(t, str)]
    types_ = [t for t in (rq.get("resource_types") or []) if t in TYPE_SET] or None
    bake = norm_enum(rq.get("bake_policy"), BAKE_POLICIES)

    ranked, meta = search(
        store, qtext, types=types_, route=rq.get("route"), proj_style=pstyle,
        avoid_tokens=avoid, bake_policy=bake, license_mode="commercial"
        if (rq.get("license_requirements") or "").find("商用") >= 0 else "any",
        local_only=bool(rq.get("local_preferred")),
    )
    ranked = apply_family(ranked)
    ranked = apply_diversity(ranked, 3)
    if not ranked:
        return {
            "request_id": rq["request_id"],
            "selected_resource": None,
            "alternatives": [],
            "selection_reason": "无候选命中（匹配所有过滤后为空）",
            "approval": {"status": "pending", "required": False,
                         "reason": "无候选；如需生产建议 BUILD_NEW 并记录 why existing failed"},
            "fetch_status": {"state": "NOT_CACHED"},
        }
    top = candidate_dict(ranked[0], "commercial" if bake == "KEEP_EDITABLE" else "any")
    alts = []
    for c in ranked[1:1 + n_alt]:
        cd = candidate_dict(c, "any")
        alts.append({"resource_id": cd["resource_id"], "provider": cd["provider"],
                     "why_not_chosen": (f"综合得分 {cd['score']} < 首选 "
                                        f"{top['score']}；{cd['potential_problem']}"),
                     "score": cd["score"]})
    sel = store.resolve_id(top["resource_id"])
    fclass = fetch_classify(sel) if sel else "LIGHTWEIGHT"
    approval_required = fclass in ("LARGE", "EXTERNAL_INSTALL")
    if approval_required:
        approval = {"status": "pending", "required": True,
                    "reason": f"Explain->Size->Why->Alternatives: "
                              f"{top['estimated_fetch_size']}；{top['potential_problem']}；"
                              f"备选 {[a['resource_id'] for a in alts]}"}
    else:
        approval = {"status": "pending", "required": False,
                    "reason": f"无需审批（fetch 分类 {fclass}）"}
    fetch_state = {"state": (sel.get("local_state") or {}).get("cache_state", "NOT_CACHED")}
    if sel and (sel.get("local_state") or {}).get("local_path"):
        fetch_state["local_path"] = sel["local_state"]["local_path"]
    if sel and (sel.get("local_state") or {}).get("downloaded_at"):
        fetch_state["downloaded_at"] = sel["local_state"]["downloaded_at"]

    reuse = top["reuse_recommendation"]
    reason = (f"首选 {top['resource_id']}（fit {top['fit']:.2f}，why: {top['why_matched'][:160]}）")
    if reuse == "BUILD_NEW":
        reason += f"；{top['reuse_note']}"
    if alts:
        reason += f"；备选: {', '.join(a['resource_id'] for a in alts)}"
    if len(reason) > 500:
        reason = reason[:497] + "..."

    return {
        "request_id": rq["request_id"],
        "selected_resource": {
            "resource_id": top["resource_id"],
            "provider": top["provider"],
            "why_matched": top["why_matched"],
            "best_use": top["best_use"],
            "potential_problem": top["potential_problem"],
            "license": top["license"],
            "estimated_fetch_size": top["estimated_fetch_size"],
            "dependencies": top["dependencies"],
            "reuse_recommendation": reuse,
        },
        "alternatives": alts,
        "selection_reason": reason,
        "approval": approval,
        "fetch_status": fetch_state,
    }


def run_find_from_requests(args, store):
    try:
        reqs = load_requests(args.from_requests)
    except FatalError as exc:
        return cli_error(str(exc), args.json)
    if not reqs:
        return cli_error("requests 为空或无法解析", args.json)
    selections = [build_selection(store, rq) for rq in reqs]

    if args.write_selections:
        out_dir = Path(args.write_selections)
        out_dir.mkdir(parents=True, exist_ok=True)
        for sel in selections:
            (out_dir / f"{sel['request_id']}.json").write_text(
                json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "selections.json").write_text(
            json.dumps(selections, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps({"command": "find_from_requests", "request_count": len(reqs),
                          "selections": selections}, ensure_ascii=False, indent=2))
    else:
        print(f"find --from-requests: {len(reqs)} 个 request 的 selection plan")
        for sel in selections:
            s = sel["selected_resource"]
            if s is None:
                print(f"  {sel['request_id']}: 无候选")
                continue
            print(f"  {sel['request_id']}: -> {s['resource_id']} "
                  f"(reuse={s['reuse_recommendation']}) approval="
                  f"{'required' if sel['approval']['required'] else 'no'}")
            print(f"    why: {s['why_matched'][:120]}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(
        prog="registry.py",
        description="ZHOU_Videodirector Phase 4 Resource Registry engine (Metadata First, "
                    "Payload Later).",
    )
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in self test (temp fixtures + real Phase-3 e2e copy)")
    sub = ap.add_subparsers(dest="command")

    p = sub.add_parser("find", help="search + 8-factor ranking + explainable results (§39-46)")
    p.add_argument("query", nargs="*")
    p.add_argument("--type")
    p.add_argument("--provider")
    p.add_argument("--tags")
    p.add_argument("--style")
    p.add_argument("--best-for")
    p.add_argument("--license", choices=["commercial", "any"], default="any")
    p.add_argument("--local-only", action="store_true")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.add_argument("--project-dir")
    p.add_argument("--route")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--from-requests", help="requests 文件或目录 -> 输出 resource-selection plan")
    p.add_argument("--write-selections")

    p = sub.add_parser("detail", help="single-entry Level 1 lazy detail (§47)")
    p.add_argument("resource_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("preview", help="preview ref; not_available if none (§48-51)")
    p.add_argument("resource_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("fetch", help="fetch gate (approval + security; no real download)")
    p.add_argument("resource_id")
    p.add_argument("--dest")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--project-dir")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("add", help="add new resource (schema check + duplicate detection §72-75)")
    p.add_argument("--file", required=True)
    p.add_argument("--source", choices=["manual", "adapter", "discovered"], default="manual")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("update", help="refresh metadata status; no network (§68-71)")
    p.add_argument("--provider")
    p.add_argument("--apply", action="store_true",
                   help="persist changes (默认 dry-run；需显式设置 ZHOU_REGISTRY_INDEX_DIR 才能写库)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("validate", help="seven checks (§67)")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("request", help="Router -> Registry bridge: generate resource-requests (§114-115)")
    p.add_argument("--from-routing", required=True)
    p.add_argument("--json", action="store_true")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.selftest:
        code, out = run_selftest()
        print(out)
        return code
    if not args.command:
        build_parser().print_help()
        return 2

    store = open_store()
    if args.command == "find":
        if args.from_requests:
            return run_find_from_requests(args, store)
        return run_find(args, store)
    if args.command == "detail":
        return run_detail(args, store)
    if args.command == "preview":
        return run_preview(args, store)
    if args.command == "fetch":
        return run_fetch(args, store)
    if args.command == "add":
        return run_add(args, store)
    if args.command == "update":
        return run_update(args, store)
    if args.command == "validate":
        return run_validate(args, store)
    if args.command == "request":
        return run_request(args, store)
    build_parser().print_help()
    return 2


# ---------------------------------------------------------------------------
# --selftest（临时目录 fixture + 真实 Phase-3 e2e 副本）
# ---------------------------------------------------------------------------

def _mk_providers():
    return {
        "$schema": "schemas/provider.schema.json",
        "version": "1.0.0",
        "count": 4,
        "providers": [
            {"id": "fakebits", "name": "Fake Bits", "type": "GITHUB",
             "url": "https://example.com/fakebits", "integration_mode": "PROVIDER",
             "search_capability": True, "detail_capability": True,
             "preview_capability": True, "fetch_capability": True,
             "authentication": "NONE", "license_model": "MIT", "local_cache": True,
             "status": "ACTIVE", "priority": 8, "notes": "selftest fixture"},
            {"id": "fakeharbor", "name": "Fake Harbor", "type": "API",
             "url": "https://example.com/fakeharbor", "integration_mode": "RESOURCE_PROVIDER",
             "search_capability": True, "detail_capability": True,
             "preview_capability": True, "fetch_capability": "manual_or_semiautomatic",
             "authentication": "NONE", "license_model": "MIXED", "local_cache": True,
             "status": "ACTIVE", "priority": 5, "notes": "selftest fixture"},
            {"id": "fakepkg", "name": "Fake Pkg", "type": "PACKAGE",
             "url": "https://example.com/fakepkg", "integration_mode": "RESOURCE_PROVIDER",
             "search_capability": True, "detail_capability": True,
             "preview_capability": True, "fetch_capability": True,
             "authentication": "NONE", "license_model": "MIT", "local_cache": True,
             "status": "ACTIVE", "priority": 6, "notes": "selftest fixture"},
            {"id": "fakebroken", "name": "Fake Broken", "type": "WEBSITE",
             "url": "https://example.com/fakebroken", "integration_mode": "RESOURCE_PROVIDER",
             "search_capability": False, "detail_capability": False,
             "preview_capability": False, "fetch_capability": False,
             "authentication": "NONE", "license_model": "UNKNOWN", "local_cache": False,
             "status": "BROKEN", "priority": 1, "notes": "selftest fixture（失败隔离）"},
        ],
    }


def _mk_tags():
    return {
        "motion": ["minimal", "spatial", "kinetic", "cinematic", "glitch", "soft", "tech"],
        "sfx": ["sfx", "digital", "premium", "sharp", "soft"],
        "three_d": ["3d", "photoreal", "product", "interior"],
    }


def _mk_resources():
    base_lic = {"license_url": "https://example.com/license", "attribution_required": False,
                "derivatives_allowed": True, "redistribution_allowed": True,
                "license_notes": "selftest fixture"}
    lic_mit = {"license_type": "MIT", "commercial_use": True, **base_lic}
    lic_cc0 = {"license_type": "CC0", "commercial_use": True, **base_lic}
    lic_by = {"license_type": "CC-BY-4.0", "commercial_use": True, "attribution_required": True,
              "derivatives_allowed": True, "redistribution_allowed": True,
              "license_notes": "需署名", "license_url": "https://example.com/license"}
    lic_unk = {"license_type": "UNKNOWN", "commercial_use": True, "license_review_required": True,
               "license_url": "", "attribution_required": False, "derivatives_allowed": None,
               "redistribution_allowed": None, "license_notes": "无法确认"}

    def R(rid, typ, name, prov, src, summary, tags, best, style, lic, **kw):
        d = {
            "id": rid, "type": typ, "name": name, "provider": prov, "source_url": src,
            "summary": summary, "resource_nature": kw.pop("resource_nature",
                                                          "MEDIA" if typ in
                                                          ("SFX", "MUSIC", "HDRI", "IMAGE")
                                                          else "CODE"),
            "tags": tags, "best_for": best, "avoid_when": [], "style": style,
            "status": "active", "availability": kw.pop("availability", "remote"),
            "verification_status": kw.pop("verification_status", "CURRENT"),
            "preview": kw.pop("preview", {"type": "external_url",
                                          "url": "https://example.com/prev"}),
            "license": lic, "local_state": kw.pop("local_state", {"cache_state": "NOT_CACHED"}),
            "metadata_version": "1.0", "last_verified": kw.pop("last_verified", "2026-08-13"),
            "family_id": kw.pop("family_id", None), "aliases": kw.pop("aliases", []),
            "added_by": "selftest", "added_at": "2026-08-13", "discovery_source": "fixture",
        }
        d.update(kw)
        return d

    rs = [
        R("fakebits:motion_effect:minimal-fade", "MOTION_EFFECT", "Minimal Fade",
          "fakebits", "https://example.com/fakebits/minimal-fade.tsx",
          "minimal text fade-in", ["motion", "minimal"], ["Simple text reveals",
                                                          "minimal title cards"],
          ["minimal", "soft"], lic_mit, family_id="fade-family",
          aliases=["legacy:motion:fade-minimal"], estimated_size_bytes=50000,
          dependencies={"npm_packages": ["@remotion/core"], "remotion_compat": ">=4.0.0"},
          description="L1 test description: minimal fade with configurable duration."),
        R("fakebits:transition:spatial-wipe", "TRANSITION", "Spatial Wipe",
          "fakebits", "https://example.com/fakebits/spatial-wipe.tsx",
          "spatial wipe transition", ["motion", "spatial"], ["Spatial scene transitions"],
          ["spatial", "minimal"], lic_mit, estimated_size_bytes=120000),
        R("fakebits:transition:glitch-slice", "TRANSITION", "Glitch Slice",
          "fakebits", "https://example.com/fakebits/glitch-slice.tsx",
          "glitch slice transition", ["motion", "glitch"], ["Glitch transitions"],
          ["glitch", "neon"], lic_mit, estimated_size_bytes=90000),
        R("fakebits:sfx:ui-tick", "SFX", "UI Tick", "fakebits",
          "https://example.com/fakebits/ui-tick.wav", "soft digital UI tick",
          ["sfx", "digital"], ["UI accents"], ["digital"], lic_mit,
          local_state={"cache_state": "PAYLOAD_CACHED", "local_path": "/tmp/ui-tick.wav",
                       "downloaded_at": "2026-08-01",
                       "license_snapshot": '{"license_identifier":"MIT"}'},
          estimated_size_bytes=20000),
        R("fakeharbor:three_d_model:hero-cube", "THREE_D_MODEL", "Hero Cube",
          "fakeharbor", "https://example.com/fakeharbor/hero-cube.glb",
          "product hero cube model", ["3d", "product"], ["Product hero shots"],
          ["photoreal", "product"], lic_by, estimated_size_bytes=800_000_000,
          type_specific={"3d": {"category": "product", "formats": ["glb", "fbx"],
                                "texture_resolutions": ["2k", "4k"], "realism": "photoreal"}}),
        R("fakeharbor:hdri:studio-8k", "HDRI", "Studio 8K", "fakeharbor",
          "https://example.com/fakeharbor/studio-8k.hdr",
          "8K studio HDRI environment", ["3d", "hdri"], ["Environment lighting"],
          ["photoreal"], lic_cc0, estimated_size_bytes=400_000_000,
          type_specific={"hdri": {"environment_type": "studio", "indoor_outdoor": "INDOOR"}}),
        R("fakeharbor:sfx:premium-whoosh", "SFX", "Premium Whoosh", "fakeharbor",
          "https://example.com/fakeharbor/whoosh.wav", "premium whoosh", ["sfx", "premium"],
          ["Motion accents"], ["premium"], lic_unk, estimated_size_bytes=150000),
        R("fakeharbor:music:calm-pad", "MUSIC", "Calm Pad", "fakeharbor",
          "https://example.com/fakeharbor/calm-pad.mp3", "calm ambient pad",
          ["music", "ambient"], ["Background music"], ["soft", "ambient"], lic_cc0,
          estimated_size_bytes=6_000_000,
          type_specific={"music": {"mood": "calm", "energy": "LOW", "bpm": 90,
                                   "narration_friendly": True, "loopable": True}}),
        R("fakepkg:font:display-font", "FONT", "Display Font", "fakepkg",
          "https://example.com/fakepkg/display-font.zip", "display font family",
          ["typography"], ["Title sequences"], ["editorial"], lic_mit,
          resource_nature="PACKAGE", estimated_size_bytes=800_000),
        R("fakebits:motion_effect:fade-family-b", "MOTION_EFFECT", "Fade Family B",
          "fakebits", "https://example.com/fakebits/fade-family-b.tsx",
          "minimal fade variant B", ["motion", "minimal"], ["Simple text reveals"],
          ["minimal"], lic_mit, family_id="fade-family", preview={"type": "none", "url": ""},
          last_verified="2025-01-01", estimated_size_bytes=45000),
        R("fakebroken:image:broken-cover", "IMAGE", "Broken Cover", "fakebroken",
          "https://example.com/fakebroken/cover.jpg", "broken provider cover image",
          ["image"], ["b-roll"], ["minimal"], lic_cc0, estimated_size_bytes=100000),
    ]
    return rs


def _write_index(index_dir, resources, providers, tags):
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "resources.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in resources) + "\n",
        encoding="utf-8")
    (index_dir / "providers.json").write_text(
        json.dumps(providers, ensure_ascii=False, indent=2), encoding="utf-8")
    (index_dir / "tags.json").write_text(
        json.dumps(tags, ensure_ascii=False, indent=2), encoding="utf-8")


def _mk_style_project(proj):
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "PROJECT_BRIEF.md").write_text(
        "# PROJECT BRIEF — selftest\nTarget Duration: 30\n", encoding="utf-8")
    (proj / "VISUAL_BIBLE.md").write_text(
        "# VISUAL_BIBLE — selftest\n\n# 1. Style 声明\n- **Style Name**: minimal_spatial_tech\n"
        "# 6. Effect Philosophy\n\n# Avoid List\n避免 strong glitch；避免高频转场；避免高饱和暖色\n",
        encoding="utf-8")


def _mk_hybrid_project(proj):
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "routing").mkdir()
    (proj / "layers").mkdir()
    (proj / "shots").mkdir()
    (proj / "routing" / "S101.yaml").write_text(
        "shot_id: S101\nroute: HYBRID\nconfidence: 0.9\n"
        "decision_summary: HYBRID shot with 3D turntable + typography overlay\n"
        "continuity_group: CG101\n", encoding="utf-8")
    (proj / "layers" / "S101.yaml").write_text(
        "- layer_id: S101-L01\n  shot_id: S101\n  name: product-3d\n  role: 3D_OBJECT\n"
        "  route: THREE_D\n  visual_description: product turntable on dark background\n"
        "  bake_policy: KEEP_EDITABLE\n"
        "- layer_id: S101-L02\n  shot_id: S101\n  name: headline\n  role: TYPOGRAPHY\n"
        "  route: REMOTION\n  visual_description: minimal headline entrance\n"
        "  bake_policy: KEEP_EDITABLE\n", encoding="utf-8")
    (proj / "shots" / "S101.json").write_text(
        json.dumps({"id": "S101",
                    "audio": {"sfx": ["soft whoosh"], "music": {"mode": "cue"}},
                    "visual_direction": {"editability": "HIGH"}}, ensure_ascii=False),
        encoding="utf-8")


def _mk_broken_index(index_dir):
    """七项校验全命中的破坏 fixture。"""
    index_dir.mkdir(parents=True, exist_ok=True)
    base = {"type": "MOTION_EFFECT", "name": "x", "provider": "ghost-provider",
            "source_url": "https://example.com/x", "summary": "s",
            "resource_nature": "CODE", "tags": [], "best_for": [], "avoid_when": [],
            "style": [], "status": "active", "availability": "remote",
            "verification_status": "CURRENT",
            "preview": {"type": "not-a-valid-type", "url": ""},
            "license": {}, "local_state": {"cache_state": "NOT_CACHED"},
            "added_by": "selftest", "discovery_source": "fixture"}
    # 故意缺 metadata_version / last_verified / added_at（metadata_required 必命中）
    r1 = dict(base, id="ghost:bad:id1")                     # id 格式 + provider 不存在 + license 空
    r2 = dict(base, id="ghost-provider:motion:bad-dup",
              provider="ghost-provider")                    # 同 id 重复（下一行）
    r3 = dict(base, id="ghost-provider:motion:bad-dup",
              provider="ghost-provider")                    # 重复 id
    r4 = dict(base, id="ghost-provider:notatype:bad", type="NOT_A_TYPE",
              provider="ghost-provider")                    # type 非法
    r5 = dict(base, id="ghost-provider:motion:no-url", provider="ghost-provider",
              source_url="")                                # source_url 空
    lines = [json.dumps(x, ensure_ascii=False) for x in (r1, r2, r3, r4, r5)]
    (index_dir / "resources.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (index_dir / "providers.json").write_text(
        json.dumps({"providers": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    (index_dir / "tags.json").write_text("{}", encoding="utf-8")


def _cli(args, index_dir, cache_dir, extra_env=None):
    env = dict(os.environ)
    env["ZHOU_REGISTRY_INDEX_DIR"] = str(index_dir)
    env["ZHOU_REGISTRY_CACHE_DIR"] = str(cache_dir)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, str(SCRIPT_DIR / "registry.py")] + args,
                          capture_output=True, text=True, env=env,
                          cwd=str(SKILL_ROOT))


def run_selftest():
    lines = ["SELF TEST — Registry engine (P4-2)", "-" * 76]
    bad = 0

    def check(name, ok, detail=""):
        nonlocal bad
        if not ok:
            bad += 1
        lines.append(f"[{'OK ' if ok else 'BAD'}] {name:<34} {detail}")

    with tempfile.TemporaryDirectory(prefix="registry_selftest_") as tmp:
        tmp = Path(tmp)
        index = tmp / "index"
        cache = tmp / "cache"
        style_proj = tmp / "proj"
        hybrid = tmp / "hybrid-proj"
        broken = tmp / "broken-index"

        _write_index(index, _mk_resources(), _mk_providers(), _mk_tags())
        _mk_style_project(style_proj)
        _mk_hybrid_project(hybrid)
        _mk_broken_index(broken)

        # -- find 基本搜索 ---------------------------------------------------
        r = _cli(["find", "minimal fade", "--json"], index, cache)
        check("find basic", r.returncode == 0 and "minimal-fade" in r.stdout,
              f"exit={r.returncode}")

        # -- find type 过滤 --------------------------------------------------
        r = _cli(["find", "", "--type", "SFX", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            res = json.loads(r.stdout).get("results") or []
            ok = res and all(x["type"] == "SFX" for x in res)
        check("find --type filter", ok, f"types={set(x['type'] for x in (json.loads(r.stdout).get('results') or [])) if r.returncode==0 else 'n/a'}")

        # -- find provider 过滤 ----------------------------------------------
        r = _cli(["find", "", "--provider", "fakeharbor", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            res = json.loads(r.stdout).get("results") or []
            ok = res and all(x["provider"] == "fakeharbor" for x in res)
        check("find --provider filter", ok, "")

        # -- project-aware style 加权 + avoid 降权 ----------------------------
        r = _cli(["find", "transition", "--project-dir", str(style_proj), "--json"],
                 index, cache)
        ok = r.returncode == 0
        rank = {}
        if ok:
            res = json.loads(r.stdout).get("results") or []
            for i, x in enumerate(res):
                rank[x["resource_id"]] = i
        sp = rank.get("fakebits:transition:spatial-wipe")
        gl = rank.get("fakebits:transition:glitch-slice")
        check("find style 加权 + avoid 降权",
              ok and sp is not None and gl is not None and sp < gl,
              f"spatial_wipe={sp} glitch_slice={gl}")
        if ok and gl is not None and sp is not None and sp < gl:
            cand = json.loads(r.stdout)["results"][gl]
            check("avoid 命中记录", "avoid" in cand["why_matched"].lower()
                  or "降权" in cand["why_matched"],
                  cand["why_matched"][:120])

        # -- license 商业过滤 -------------------------------------------------
        r = _cli(["find", "whoosh", "--license", "commercial", "--json"], index, cache)
        ok = r.returncode == 0 and "premium-whoosh" not in r.stdout
        check("license commercial 过滤 UNKNOWN", ok, "")

        # -- local-only ------------------------------------------------------
        r = _cli(["find", "", "--local-only", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            res = json.loads(r.stdout).get("results") or []
            ok = res and all(x["resource_id"] == "fakebits:sfx:ui-tick" for x in res)
        check("find --local-only", ok, f"count={len(res) if ok else 0}")

        # -- offline ---------------------------------------------------------
        r = _cli(["find", "", "--offline", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            res = json.loads(r.stdout).get("results") or []
            ok = res and all(x["resource_id"] == "fakebits:sfx:ui-tick" for x in res)
        check("find --offline 仅本地缓存", ok, "")

        # -- provider 失败隔离 -----------------------------------------------
        r = _cli(["find", "", "--json"], index, cache)
        ok = r.returncode == 0 and "fakebroken:image:broken-cover" not in r.stdout
        if ok:
            perr = json.loads(r.stdout).get("provider_errors") or {}
            ok = "fakebroken" in perr
        check("provider 失败隔离 (BROKEN 剔除)", ok, "")

        # -- detail 单条目 L1 -------------------------------------------------
        r = _cli(["detail", "fakebits:motion_effect:minimal-fade", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            d = json.loads(r.stdout)
            ok = (d.get("command") == "detail" and isinstance(d.get("detail"), dict)
                  and d["detail"].get("description", "").startswith("L1 test description"))
        check("detail 单条目 L1", ok, "")

        # -- preview 有 / 无 --------------------------------------------------
        r = _cli(["preview", "fakebits:motion_effect:minimal-fade", "--json"], index, cache)
        ok = r.returncode == 0 and '"preview_status": "available"' in r.stdout
        check("preview available", ok, "")
        r = _cli(["preview", "fakebits:motion_effect:fade-family-b", "--json"], index, cache)
        ok = r.returncode == 0 and '"preview_status": "not_available"' in r.stdout
        check("preview not_available（不假装）", ok, "")

        # -- fetch LIGHTWEIGHT 推进 cache + license snapshot ------------------
        r = _cli(["fetch", "fakebits:motion_effect:minimal-fade", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            d = json.loads(r.stdout)
            ls = d.get("local_state") or {}
            ok = (d.get("approval_required") is False
                  and ls.get("cache_state") == "PAYLOAD_CACHED"
                  and ls.get("license_snapshot") and ls.get("local_path"))
        check("fetch LIGHTWEIGHT 模拟推进 cache+snapshot", ok, "")
        ok = (cache / "local_state.json").is_file()
        check("local_state.json 落盘（~/.cache，不污染 skill 源码树）", ok, "")

        # -- fetch LARGE approval 不下载 --------------------------------------
        r = _cli(["fetch", "fakeharbor:three_d_model:hero-cube", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            d = json.loads(r.stdout)
            ok = d.get("approval_required") is True and d.get("dry_run") is True
        check("fetch LARGE approval_required 不下载", ok, "")

        # -- fetch EXTERNAL_INSTALL ------------------------------------------
        r = _cli(["fetch", "fakepkg:font:display-font", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            d = json.loads(r.stdout)
            ok = (d.get("fetch_class") == "EXTERNAL_INSTALL"
                  and d.get("approval_required") is True
                  and "禁止自动执行" in d.get("security_warning", ""))
        check("fetch EXTERNAL_INSTALL approval+no-exec", ok, "")

        # -- fetch path traversal 拒绝 ----------------------------------------
        r = _cli(["fetch", "fakebits:motion_effect:minimal-fade",
                  "--dest", str(tmp / "escape" / ".."), "--json"], index, cache)
        check("fetch path traversal 拒绝", r.returncode == 1
              and "逃出" in r.stdout, f"exit={r.returncode}")
        r = _cli(["fetch", "fakebits:../evil", "--json"], index, cache)
        check("fetch 非法 id 拒绝", r.returncode == 1, f"exit={r.returncode}")

        # -- add 重复检测 ------------------------------------------------------
        _ADD_BASE = {"metadata_version": "1.0", "last_verified": "2026-08-13",
                     "added_by": "selftest", "added_at": "2026-08-13",
                     "discovery_source": "fixture"}
        dup = index / "dup.json"
        dup_data = {
            "id": "fakebits:motion_effect:minimal-fade", "type": "MOTION_EFFECT",
            "name": "Minimal Fade", "provider": "fakebits",
            "source_url": "https://example.com/fakebits/minimal-fade.tsx",
            "summary": "dup", "resource_nature": "CODE", "tags": [],
            "best_for": [], "avoid_when": [], "style": [], "status": "active",
            "availability": "remote", "verification_status": "CURRENT",
            "preview": {"type": "none", "url": ""},
            "license": {"license_type": "MIT", "commercial_use": True,
                        "license_url": "https://example.com/license",
                        "attribution_required": False, "derivatives_allowed": True,
                        "redistribution_allowed": True, "license_notes": ""},
            "local_state": {"cache_state": "NOT_CACHED"}, **_ADD_BASE}
        dup.write_text(json.dumps(dup_data, ensure_ascii=False), encoding="utf-8")
        r = _cli(["add", "--file", str(dup), "--json"], index, cache)
        ok = r.returncode == 1 and "duplicate" in r.stdout.lower()
        check("add 重复检测拒绝", ok, f"exit={r.returncode}")
        newres = index / "new.json"
        new_data = {
            "id": "fakebits:sfx:new-click", "type": "SFX", "name": "New Click",
            "provider": "fakebits",
            "source_url": "https://example.com/fakebits/new-click.wav",
            "summary": "brand new click sfx", "resource_nature": "MEDIA",
            "tags": ["sfx", "soft"], "best_for": ["UI accents"],
            "avoid_when": [], "style": ["soft"], "status": "active",
            "availability": "remote", "verification_status": "CURRENT",
            "preview": {"type": "audio", "url": "https://example.com/fakebits/new-click.wav"},
            "license": {"license_type": "MIT", "commercial_use": True,
                        "license_url": "https://example.com/license",
                        "attribution_required": False, "derivatives_allowed": True,
                        "redistribution_allowed": True, "license_notes": ""},
            "local_state": {"cache_state": "NOT_CACHED"}, **_ADD_BASE}
        newres.write_text(json.dumps(new_data, ensure_ascii=False), encoding="utf-8")
        r = _cli(["add", "--file", str(newres), "--source", "adapter", "--json"], index, cache)
        ok = r.returncode == 0 and "new-click" in r.stdout
        check("add 合法条目写入", ok, f"exit={r.returncode}")

        # -- update 过期降级（dry-run + apply） --------------------------------
        r = _cli(["update", "--provider", "fakebits", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            d = json.loads(r.stdout)
            ok = any(ch["id"] == "fakebits:motion_effect:fade-family-b"
                     and ch["to"] == "STALE" for ch in d.get("changes", []))
            ok = ok and d.get("persisted") is False
        check("update dry-run 检测 STALE", ok, "")
        r = _cli(["update", "--provider", "fakebits", "--apply", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            d = json.loads(r.stdout)
            ok = d.get("persisted") is True
        check("update --apply 持久化", ok, "")

        # -- validate 七项（好 fixture 全过） ----------------------------------
        r = _cli(["validate", "--json"], index, cache)
        ok = r.returncode == 0
        if ok:
            checks = {c["check"]: c["status"] for c in json.loads(r.stdout)["checks"]}
            ok = all(checks.get(cid) == "pass" for cid in VALIDATE_CHECKS)
        check("validate 七项全过（好 fixture）", ok, "")

        # -- validate 破坏 fixture（七项全命中 fail） ---------------------------
        r = _cli(["validate", "--json"], broken, cache)
        ok = r.returncode == 1
        if ok:
            checks = {c["check"]: c["status"] for c in json.loads(r.stdout)["checks"]}
            ok = all(checks.get(cid) == "fail" for cid in VALIDATE_CHECKS)
        check("validate 破坏 fixture 七项全命中", ok, "")

        # -- request --from-routing：真实 Phase-3 e2e 副本 ----------------------
        if E2E_PROJECT.is_dir():
            e2e = tmp / "e2e-copy"
            shutil.copytree(E2E_PROJECT, e2e)
            r = _cli(["request", "--from-routing", str(e2e), "--json"], index, cache)
            ok = r.returncode == 0
            count = 0
            if ok:
                count = json.loads(r.stdout).get("count", 0)
                ok = count >= 3
                if ok:
                    rr = json.loads(r.stdout).get("requests") or []
                    ok = all(re.match(r"^RR-\d{3}$", x.get("request_id", "")) for x in rr)
                    ok = ok and all(x.get("resource_types") and x.get("description")
                                    and x.get("status") == "OPEN" for x in rr)
            check("request --from-routing e2e 副本生成 ≥3 requests", ok,
                  f"count={count}")
            if ok and (e2e / "requests" / "requests.json").is_file():
                # HYBRID 拆分验证（e2e 无 HYBRID shot，用合成 fixture 验证，见 notes）
                r = _cli(["request", "--from-routing", str(hybrid), "--json"], index, cache)
                ok = r.returncode == 0
                typesets = []
                if ok:
                    reqs = json.loads(r.stdout).get("requests") or []
                    typesets = [set(x["resource_types"]) for x in reqs]
                    ok = len(reqs) >= 3
                    ok = ok and any("THREE_D_MODEL" in t for t in typesets)
                    ok = ok and any("MOTION_EFFECT" in t for t in typesets)
                    ok = ok and any(t == {"SFX"} for t in typesets)
                check("HYBRID shot 拆多个 request（合成 fixture）", ok,
                      f"reqs={len(typesets)} typesets={sorted(map(sorted, typesets))}")
            # -- find --from-requests（selection plan） --------------------------
            r = _cli(["find", "--from-requests", str(e2e / "requests"), "--json"], index, cache)
            ok = r.returncode == 0
            if ok:
                sels = json.loads(r.stdout).get("selections") or []
                ok = len(sels) >= 3
                if ok:
                    ok = all(s.get("selected_resource") and s.get("selection_reason")
                             and s.get("approval") and s.get("fetch_status") for s in sels)
            check("find --from-requests 输出 selection plan", ok, f"sel={len(sels) if ok else 0}")
        else:
            check("request --from-routing e2e（真实项目缺失）", False,
                  f"E2E_PROJECT 不存在: {E2E_PROJECT}")

        # -- 真实索引 validate / find（读路径，不改数据） -----------------------
        try:
            real_store = Store()
            real_ok = True
            lines.append(f"[INFO] 真实索引: {real_store.resources_file} "
                         f"({len(real_store.resources)} 条资源, "
                         f"{len(real_store.providers)} 个 provider)")
        except FatalError as exc:
            real_ok = False
            lines.append(f"[INFO] 真实索引不可读: {exc}")

    lines.append("-" * 76)
    lines.append(f"SELF TEST {'PASS' if bad == 0 else 'FAIL'}（{bad} 断言失败）")
    return (0 if bad == 0 else 1), "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
