#!/usr/bin/env python3
"""project-validate.py - ZHOU_Videodirector Phase 1 lightweight project validator.

校验一个 ZHOU_Videodirector 项目目录的 16 项 Phase-1 契约（Phase-1 Prompt §41）。

预期项目结构（<project_dir>/）:
    PROJECT_STATE.md      必读，可解析（Current Truth；校验时提取 Current Stage / Approved Stages）
    DECISIONS.md          可选（历史决定，本版本只做可读性说明，不校验）
    approvals.yaml        必读（机器可读 Approval Current State，Phase-1 §20）
    scenes/*.json         可选；每个文件一个 scene 对象（或对象数组）
    shots/*.json          可选；每个文件一个 shot 对象（或对象数组）
    layers/*.json         可选；每个文件一个 layer 对象（或对象数组）
    assets/*.json         可选；每个文件一个 asset 对象（或对象数组）
    project.json          可选；delivery_mode 枚举校验
    timeline.json         可选；backend 枚举校验
    routing.json          可选；route 枚举校验

机器可读真源（相对本脚本 ../schemas/）:
    state-machine.json     31 个 stage + 每 stage allowed_next + 枚举
    {scene,shot,layer,asset}.schema.json   ID pattern 与 required 字段

用法:
    python3 scripts/project-validate.py <project_dir>          # 人类可读表格
    python3 scripts/project-validate.py <project_dir> --json   # 机器可读 JSON 报告
    python3 scripts/project-validate.py --selftest             # 内置自检（临时目录）

退出码: 0 = 全部 PASS; 1 = 存在 FAIL; 2 = 致命错误（目录缺失 / 真源缺失，无法继续）。

技术约束: Python 3 stdlib only。YAML 优先使用 PyYAML；不可用时退回内置最小 YAML
读取器（只覆盖本项目 YAML 子集；缩进对不齐必须 raise，不允许吞错）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
SCHEMAS_DIR = SKILL_ROOT / "schemas"
STATE_MACHINE_FILE = SCHEMAS_DIR / "state-machine.json"

ENTITY_DIRS = {"scene": "scenes", "shot": "shots", "layer": "layers", "asset": "assets"}
ENTITY_ID_FIELD = {"scene": "id", "shot": "id", "layer": "id", "asset": "asset_id"}
ENTITY_SCHEMA_FILE = {
    "scene": "scene.schema.json",
    "shot": "shot.schema.json",
    "layer": "layer.schema.json",
    "asset": "asset.schema.json",
}

DELIVERY_MODES = ["FINAL_VIDEO_ONLY", "EDITABLE_PROJECT", "BOTH"]
TIMELINE_BACKENDS = ["PYJIANYINGDRAFT", "VECTCUT", "PYCAPCUT", "FUTURE", "UNDECIDED"]
ROUTES = ["REMOTION", "THREE_D", "REAL_FOOTAGE", "GENERATIVE_VIDEO", "JY_NATIVE", "HYBRID", "UNDECIDED"]
ASSET_KEY_FIELDS = ["asset_id", "name", "type", "purpose", "source", "local_path", "license"]

# 10 个 requires_approval 阶段：approvals.yaml 的 project 子键 -> state-machine stage ID
KEY_TO_STAGE = {
    "project_brief": "PROJECT_BRIEF_REVIEW",
    "reference_analysis": "REFERENCE_REVIEW",
    "creative_direction": "CREATIVE_REVIEW",
    "visual_bible": "VISUAL_BIBLE_REVIEW",
    "audio_direction": "AUDIO_DIRECTION_REVIEW",
    "story_structure": "STORY_REVIEW",
    "storyboard": "STORYBOARD_REVIEW",
    "production_plan": "PRODUCTION_PLAN_REVIEW",
    "timeline_plan": "TIMELINE_REVIEW",
    "final_qa": "QA",
}
APPROVAL_KEYS = list(KEY_TO_STAGE.keys())

STAGE_LIKE = re.compile(r"^[A-Z][A-Z0-9_]*$")  # 只把"看起来像 stage ID"的 token 当作 stage 引用
HISTORY_KEYS = frozenset(
    ("history", "stage_history", "status_history", "change_history", "stage_log", "changelog", "stage_sequence")
)
STAGE_FIELD_KEYS = frozenset(("stage", "stage_id", "current_stage"))


class FatalError(Exception):
    """致命错误：无法继续校验（目录缺失 / 真源缺失）。"""


# 最小 YAML 读取器（仅当 PyYAML 不可用时使用；只覆盖本项目的 YAML 子集，本段 <= 80 行）。覆盖：mapping / list（- item）/ inline list（[a,b]）/ inline {}、引号字符串、整数、浮点、布尔、null、注释 #；缩进对不齐或重复 key 必须 raise。
class YamlError(Exception):
    pass
def _qi(s, ch):                     # 第一个不在引号内的目标字符下标；没有则 -1
    q1 = q2 = False
    for i, c in enumerate(s):
        if c == "'" and not q2: q1 = not q1
        elif c == '"' and not q1: q2 = not q2
        elif c == ch and not q1 and not q2: return i
    return -1
def _scom(s):                       # 去掉不在引号内的 # 注释
    i = _qi(s, '#'); return s[:i] if i >= 0 else s
def _kv(s):                         # 按第一个未加引号的 ':' 拆 key/value
    i = _qi(s, ':')
    return (s[:i].strip(), s[i+1:].strip()) if i >= 0 else (None, None)
def _sl(s):                         # 按未加引号的 ',' 拆 inline list
    out = []
    while True:
        i = _qi(s, ',')
        if i < 0: out.append(s); return out
        out.append(s[:i]); s = s[i+1:]
def _sc(s):                         # scalar 解析
    s = s.strip()
    if s in ('', 'null', '~'): return None
    if s in ('true', 'True'): return True
    if s in ('false', 'False'): return False
    if s == '{}': return {}
    if s[:1] == '[' and s[-1:] == ']':
        x = s[1:-1].strip()
        return [] if x == '' else [_sc(t) for t in _sl(x)]
    if len(s) >= 2 and s[0] in '"\'' and s[-1] == s[0]: return s[1:-1]
    if re.fullmatch(r'-?\d+', s): return int(s)
    if re.fullmatch(r'-?\d*\.\d+', s): return float(s)
    return s
def _block(L, i, ind):              # 分派 mapping / list 块
    if i >= len(L) or L[i][0] != ind: return None, i
    return _blist(L, i, ind) if L[i][1].startswith('- ') else _bmap(L, i, ind)
def _bmap(L, i, ind):
    o = {}
    while i < len(L):
        p, c, n = L[i]
        if p != ind or c.startswith('- '): break
        k, v = _kv(c)
        if k is None: raise YamlError(f"line {n}: expected 'key: value', got {c!r}")
        if k in o: raise YamlError(f"line {n}: duplicate key {k!r}")
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
        if p != ind or not c.startswith('- '): break
        v = c[2:].strip(); i += 1
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
        if not s.strip(): continue
        lead = len(s) - len(s.lstrip(' '))
        if '\t' in s[:lead]: raise YamlError(f"line {n}: tab indentation not allowed")
        L.append((lead, s.strip(), n))
    if not L: return {}
    v, i = _block(L, 0, L[0][0])
    if i != len(L): raise YamlError(f"line {L[i][2]}: indentation mismatch with parent block")
    return v


# ---------------------------------------------------------------------------
# YAML / JSON 读取
# ---------------------------------------------------------------------------

try:
    import yaml as _yaml  # PyYAML，允许

    def _load_yaml(text, source):
        try:
            data = _yaml.safe_load(text)
        except Exception as exc:
            raise YamlError(f"{source}: {exc}") from exc
        return data if data is not None else {}

    YAML_STRATEGY = "pyyaml"
except ImportError:  # pragma: no cover - 仅在无 PyYAML 环境走到
    YAML_STRATEGY = "minimal_reader"

    def _load_yaml(text, source):
        try:
            return minimal_load_yaml(text)
        except YamlError as exc:
            raise YamlError(f"{source}: {exc}") from exc


def _load_json_entity(path):
    """读取 JSON 文件；返回 (data, error)。error 为 None 表示成功。"""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, str(exc)


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# 最小 JSON Schema 校验器（stdlib 手写；只覆盖本项目 schema 用到的关键字）
# 覆盖: type / required / properties（递归）/ items（递归）/ pattern / enum /
#       oneOf / minimum / maximum。不强制 additionalProperties（数据文件可能带
#       额外工作流字段，如 stage_history），避免误报。
# ---------------------------------------------------------------------------

def _validate_schema(value, spec, path, errors):
    typ = spec.get("type")
    if typ == "object":
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object, got {type(value).__name__}")
            return
        for f in spec.get("required") or []:
            if f not in value:
                errors.append(f"{path}: missing required field '{f}'")
        props = spec.get("properties") or {}
        for k, v in value.items():
            if k in props:
                _validate_schema(v, props[k], f"{path}.{k}" if path else k, errors)
    elif typ == "array":
        if not isinstance(value, list):
            errors.append(f"{path}: expected array, got {type(value).__name__}")
            return
        for i, v in enumerate(value):
            _validate_schema(v, spec.get("items") or {}, f"{path}[{i}]", errors)
    elif typ == "string":
        if not isinstance(value, str):
            errors.append(f"{path}: expected string, got {type(value).__name__}")
            return
        pat = spec.get("pattern")
        if pat and not re.search(pat, value):
            errors.append(f"{path}: value {value!r} does not match pattern {pat!r}")
        enum = spec.get("enum")
        if enum and value not in enum:
            errors.append(f"{path}: value {value!r} not in enum {enum}")
    elif typ == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path}: expected integer, got {type(value).__name__}")
    elif typ == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{path}: expected number, got {type(value).__name__}")
    elif typ == "boolean":
        if not isinstance(value, bool):
            errors.append(f"{path}: expected boolean, got {type(value).__name__}")
    if "minimum" in spec and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < spec["minimum"]:
            errors.append(f"{path}: value {value} < minimum {spec['minimum']}")
    if "maximum" in spec and isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > spec["maximum"]:
            errors.append(f"{path}: value {value} > maximum {spec['maximum']}")
    if "oneOf" in spec:
        for branch in spec["oneOf"]:
            local = []
            _validate_schema(value, branch, path, local)
            if not local:
                break
        else:
            errors.append(f"{path}: does not satisfy any oneOf branch")


# ---------------------------------------------------------------------------
# 上下文构建
# ---------------------------------------------------------------------------

def _load_state_machine():
    try:
        data = json.loads(STATE_MACHINE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FatalError(f"cannot read state machine truth source {STATE_MACHINE_FILE}: {exc}")
    stage_ids = {s["id"] for s in data.get("stages", [])}
    allowed_next = {s["id"]: list(s.get("allowed_next") or []) for s in data.get("stages", [])}
    if len(stage_ids) != 31:
        raise FatalError(f"state machine must define exactly 31 stages, got {len(stage_ids)}")
    return stage_ids, allowed_next


def build_context(project_dir):
    stage_ids, allowed_next = _load_state_machine()
    ctx = {
        "project_dir": project_dir,
        "stage_ids": stage_ids,
        "allowed_next": allowed_next,
        "schemas": {},
        "id_patterns": {},
        "approvals": None,
        "approvals_err": None,
        "project_state_text": None,
        "entities": {"scene": [], "shot": [], "layer": [], "asset": []},
        "entity_ids": {"scene": [], "shot": [], "layer": [], "asset": []},
        "entity_files": {"scene": [], "shot": [], "layer": [], "asset": []},
        "entity_errors": {},
        "all_objects": [],
        "history_sequences": [],
        "project_json": None,
        "timeline_json": None,
        "routing_json": None,
        "project_json_err": None,
        "timeline_json_err": None,
        "routing_json_err": None,
        "yaml_strategy": YAML_STRATEGY,
    }

    for ent in ("scene", "shot", "layer", "asset"):
        spec = None
        try:
            spec = json.loads((SCHEMAS_DIR / ENTITY_SCHEMA_FILE[ent]).read_text(encoding="utf-8"))
        except Exception:
            spec = None
        ctx["schemas"][ent] = spec
        idf = ENTITY_ID_FIELD[ent]
        sub = ((spec or {}).get("properties") or {}).get(idf) or {}
        pat = sub.get("pattern")
        if pat:
            ctx["id_patterns"][ent] = re.compile(pat)

    # approvals.yaml
    app = project_dir / "approvals.yaml"
    if app.exists():
        text = _read_text(app)
        if text is None:
            ctx["approvals_err"] = "approvals.yaml exists but is not readable"
        else:
            try:
                ctx["approvals"] = _load_yaml(text, str(app))
            except YamlError as exc:
                ctx["approvals_err"] = str(exc)
    else:
        ctx["approvals_err"] = "approvals.yaml not found (required)"

    # PROJECT_STATE.md
    ps = project_dir / "PROJECT_STATE.md"
    if ps.exists():
        ctx["project_state_text"] = _read_text(ps)

    # entity JSON 数据文件
    for ent in ("scene", "shot", "layer", "asset"):
        d = project_dir / ENTITY_DIRS[ent]
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            ctx["entity_files"][ent].append(str(f))
            data, err = _load_json_entity(f)
            if err is not None:
                ctx["entity_errors"][str(f)] = err
                continue
            objs = data if isinstance(data, list) else [data]
            for o in objs:
                if isinstance(o, dict):
                    ctx["entities"][ent].append(o)
                    ctx["all_objects"].append(o)

    for ent in ("scene", "shot", "layer", "asset"):
        idf = ENTITY_ID_FIELD[ent]
        ctx["entity_ids"][ent] = [o.get(idf) for o in ctx["entities"][ent] if isinstance(o.get(idf), str)]

    # 可选单文件 JSON
    for key, fn in (("project_json", "project.json"), ("timeline_json", "timeline.json"), ("routing_json", "routing.json")):
        p = project_dir / fn
        if p.exists():
            data, err = _load_json_entity(p)
            ctx[key] = data
            ctx[key + "_err"] = err

    # stage history 序列（scene/shot/layer/asset 数据中的 history 型数组）
    def _collect(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in HISTORY_KEYS and isinstance(v, list):
                    ctx["history_sequences"].append(v)
                _collect(v)
        elif isinstance(obj, list):
            for i in obj:
                _collect(i)

    for o in ctx["all_objects"]:
        _collect(o)

    return ctx


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------

def _stage_token(value):
    """取一个 stage 引用 token；只保留"看起来像 stage ID"（全大写+下划线）的部分。"""
    if not isinstance(value, str):
        return None
    tok = value.strip()
    if not tok:
        return None
    m = re.match(r"[A-Za-z0-9_]+", tok)
    if not m:
        return None
    t = m.group(0)
    return t if STAGE_LIKE.match(t) else None


def _history_stage_ref(elem):
    """把 history 数组元素转成 stage 引用：字符串 -> token；dict -> (from,to) 或 stage。"""
    if isinstance(elem, str):
        return _stage_token(elem)
    if isinstance(elem, dict):
        f = elem.get("from") or elem.get("prev") or elem.get("previous")
        t = elem.get("to") or elem.get("next")
        if f and t:
            f2, t2 = _stage_token(f), _stage_token(t)
            if f2 and t2:
                return (f2, t2)
        for k in ("stage", "stage_id", "id"):
            if k in elem:
                v = _stage_token(elem[k])
                if v:
                    return v
    return None


def _field(text, name):
    m = re.search(rf"^#?\s*{re.escape(name)}:\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else None


def _bracket_list(s):
    m = re.search(r"\[(.*)\]", s, flags=re.S)
    if not m:
        return None
    inner = m.group(1)
    if not inner.strip():
        return []
    return [x.strip().strip('"\'') for x in inner.split(",") if x.strip()]


def _norm(name):
    return re.sub(r"[^a-z]", "", name.lower())


DISPLAY_TO_KEY = {}
for _k, _stage in KEY_TO_STAGE.items():
    DISPLAY_TO_KEY[_k] = _k
    DISPLAY_TO_KEY[_stage] = _k
    DISPLAY_TO_KEY[_norm(_k)] = _k
    DISPLAY_TO_KEY[_norm(_stage)] = _k
DISPLAY_TO_KEY["qa"] = "final_qa"
DISPLAY_TO_KEY["finalqa"] = "final_qa"


def _normalize_approval(name):
    return DISPLAY_TO_KEY.get(_norm(name))


# ---------------------------------------------------------------------------
# 16 项检查（check_<n>_<short_name>(ctx) -> (status, message[, details])）
# status: "pass" | "fail" | "na"
# ---------------------------------------------------------------------------

def check_01_project_state_exists(ctx):
    p = ctx["project_dir"] / "PROJECT_STATE.md"
    if not p.exists():
        return "fail", "PROJECT_STATE.md not found"
    if ctx.get("project_state_text") is None:
        return "fail", "PROJECT_STATE.md exists but is not readable"
    return "pass", "PROJECT_STATE.md exists and is readable"


def check_02_approvals_yaml_parses(ctx):
    p = ctx["project_dir"] / "approvals.yaml"
    if not p.exists():
        return "fail", "approvals.yaml not found (required)"
    if ctx.get("approvals_err"):
        return "fail", f"approvals.yaml failed to parse: {ctx['approvals_err']}"
    if not isinstance(ctx.get("approvals"), dict):
        return "fail", "approvals.yaml did not parse to a mapping"
    return "pass", "approvals.yaml parsed successfully"


def check_03_schema_files_valid(ctx):
    total = 0
    problems = []
    for ent in ("scene", "shot", "layer", "asset"):
        files = ctx["entity_files"][ent]
        total += len(files)
        spec = ctx["schemas"].get(ent)
        if not spec and files:
            problems.append(f"[{ent}] schema file missing, cannot validate")
            continue
        for o in ctx["entities"][ent]:
            errors = []
            _validate_schema(o, spec, ent, errors)
            problems.extend(f"[{ent}] {e}" for e in errors)
    for f, err in ctx["entity_errors"].items():
        total += 1
        problems.append(f"JSON parse error in {f}: {err}")
    if total == 0:
        return "na", "no scene/shot/layer/asset JSON data files present"
    if problems:
        return "fail", f"schema validation failed for {len(problems)} item(s)", problems
    return "pass", f"{total} data file(s) validated against schemas (ID pattern + required fields)"


def _check_unique(ctx, ent):
    idf = ENTITY_ID_FIELD[ent]
    ids = ctx["entity_ids"][ent]
    if not ids:
        return "na", f"no {ent}/*.json files found"
    seen = set()
    dups = []
    for v in ids:
        if v in seen:
            dups.append(v)
        seen.add(v)
    if dups:
        return "fail", f"duplicate {ent} {idf} value(s): {sorted(set(dups))}", sorted(set(dups))
    return "pass", f"{len(ids)} unique {ent} {idf} value(s)"


def check_04_scene_id_unique(ctx):
    return _check_unique(ctx, "scene")


def check_05_shot_id_unique(ctx):
    return _check_unique(ctx, "shot")


def check_06_layer_id_unique(ctx):
    return _check_unique(ctx, "layer")


def check_07_asset_id_unique(ctx):
    return _check_unique(ctx, "asset")


def check_08_stage_legal(ctx):
    refs = []
    text = ctx.get("project_state_text")
    if text:
        cs = _field(text, "Current Stage")
        tok = _stage_token(cs) if cs else None
        if tok:
            refs.append(tok)

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in STAGE_FIELD_KEYS:
                    t = _stage_token(v)
                    if t:
                        refs.append(t)
                _walk(v)
        elif isinstance(obj, list):
            for i in obj:
                _walk(i)

    for o in ctx["all_objects"]:
        _walk(o)
    for seq in ctx["history_sequences"]:
        for e in seq:
            r = _history_stage_ref(e)
            if isinstance(r, tuple):
                refs.extend(r)
            elif r:
                refs.append(r)

    refs = list(dict.fromkeys(refs))  # 去重保序
    if not refs:
        return "na", "no stage references found in PROJECT_STATE.md or JSON data files"
    bad = sorted(r for r in refs if r not in ctx["stage_ids"])
    if bad:
        return "fail", f"stage ID(s) not in the 31-stage enum: {bad}", bad
    return "pass", f"all {len(refs)} stage reference(s) are within the 31-stage enum"


def check_09_transition_legal(ctx):
    if not ctx["history_sequences"]:
        return "na", "no stage history arrays found in project data files"
    problems = []
    pairs = 0
    for seq in ctx["history_sequences"]:
        tokens = []
        for e in seq:
            r = _history_stage_ref(e)
            if isinstance(r, tuple):
                tokens.extend(r)
            elif r:
                tokens.append(r)
        for a, b in zip(tokens, tokens[1:]):
            if a not in ctx["stage_ids"] or b not in ctx["stage_ids"]:
                continue  # 非法 stage 已由 check_08 报告
            pairs += 1
            if b not in ctx["allowed_next"].get(a, []):
                problems.append(f"{a} -> {b} (not in allowed_next of {a})")
    if problems:
        return "fail", f"illegal stage transition(s): {problems}", problems
    return "pass", f"all {pairs} adjacent transition(s) are legal (incl. REVIEW revision and CHANGE_REVIEW exception)"


def check_10_current_stage_vs_approval_consistent(ctx):
    text = ctx.get("project_state_text")
    if not text:
        return "na", "PROJECT_STATE.md missing or unreadable (see check_01)"
    if ctx.get("approvals_err") or not isinstance(ctx.get("approvals"), dict):
        return "fail", "approvals.yaml unavailable — consistency cannot be verified"

    declared = set()
    explicit = False
    f = _field(text, "Approved Stages")
    if f is not None:
        explicit = True
        items = _bracket_list(f)
        if items is None:
            items = [x.strip() for x in f.split(",") if x.strip()]
        for it in items:
            k = _normalize_approval(it)
            if k:
                declared.add(k)
    # 行扫描：任何"<name> approved"的自然语言行也视为显式声明
    for line in text.split("\n"):
        if "approved" in line.lower():
            for disp, key in DISPLAY_TO_KEY.items():
                if re.search(rf"\b{re.escape(disp)}\b", line, re.I):
                    declared.add(key)
                    explicit = True

    actual = set()
    proj = ctx["approvals"].get("project")
    if isinstance(proj, dict):
        for key, v in proj.items():
            if isinstance(v, dict) and v.get("status") == "approved":
                actual.add(key)

    if not explicit:
        if actual:
            return "fail", (
                "approvals.yaml declares approved stage(s) "
                + f"{sorted(actual)} but PROJECT_STATE.md does not declare Approved Stages"
            )
        return "na", "PROJECT_STATE.md does not explicitly declare approved stages"

    missing_in_yaml = declared - actual
    missing_in_state = actual - declared
    problems = []
    if missing_in_yaml:
        problems.append(f"declared approved in PROJECT_STATE.md but not status:approved in approvals.yaml: {sorted(missing_in_yaml)}")
    if missing_in_state:
        problems.append(f"status:approved in approvals.yaml but not declared in PROJECT_STATE.md: {sorted(missing_in_state)}")
    if problems:
        return "fail", "; ".join(problems), problems
    return "pass", "PROJECT_STATE.md approved declarations match approvals.yaml statuses"


def check_11_scene_shot_references_resolve(ctx):
    scenes = ctx["entities"]["scene"]
    if not scenes:
        return "na", "no scene files present"
    shot_ids = set(ctx["entity_ids"]["shot"])
    missing, total = [], 0
    for sc in scenes:
        for item in sc.get("shots") or []:
            if not isinstance(item, dict):
                continue
            sid = item.get("shot_id")
            if not isinstance(sid, str):
                continue
            total += 1
            if sid not in shot_ids:
                missing.append(f"scene {sc.get('id', '?')}.shots[].shot_id={sid}")
    if missing:
        return "fail", f"scene->shot reference(s) do not resolve: {missing}", missing
    return "pass", f"all {total} scene->shot reference(s) resolve"


def check_12_shot_layer_references_resolve(ctx):
    shots = ctx["entities"]["shot"]
    if not shots:
        return "na", "no shot files present"
    layer_ids = set(ctx["entity_ids"]["layer"])
    missing, total = [], 0
    for sh in shots:
        for item in sh.get("layers") or []:
            if not isinstance(item, dict):
                continue
            lid = item.get("layer_id")
            if not isinstance(lid, str):
                continue
            total += 1
            if lid not in layer_ids:
                missing.append(f"shot {sh.get('id', '?')}.layers[].layer_id={lid}")
    if missing:
        return "fail", f"shot->layer reference(s) do not resolve: {missing}", missing
    return "pass", f"all {total} shot->layer reference(s) resolve"


def check_13_layer_asset_references_resolve(ctx):
    layers = ctx["entities"]["layer"]
    if not layers:
        return "na", "no layer files present"
    asset_ids = set(ctx["entity_ids"]["asset"])
    missing, total = [], 0
    for ly in layers:
        aid = ly.get("asset_id")
        if not isinstance(aid, str) or not aid:  # asset_id 可选，可为空
            continue
        total += 1
        if aid not in asset_ids:
            missing.append(f"layer {ly.get('id', '?')}.asset_id={aid}")
    if missing:
        return "fail", f"layer->asset reference(s) do not resolve: {missing}", missing
    return "pass", f"all {total} layer->asset reference(s) resolve"


def check_14_asset_metadata_complete(ctx):
    assets = ctx["entities"]["asset"]
    if not assets:
        return "na", "no asset files present"
    problems = []
    for a in assets:
        miss = [f for f in ASSET_KEY_FIELDS if f not in a or a[f] is None]
        if miss:
            problems.append(f"asset {a.get('asset_id', '?')} missing key field(s): {miss}")
    if problems:
        return "fail", f"asset metadata incomplete: {problems}", problems
    return "pass", f"all {len(assets)} asset(s) have complete key metadata (asset_id/name/type/purpose/source/local_path/license)"


def check_15_delivery_mode_valid(ctx):
    if ctx.get("project_json_err"):
        return "fail", f"project.json unreadable: {ctx['project_json_err']}"
    pj = ctx.get("project_json")
    if pj is None:
        return "na", "project.json not present"
    dm = pj.get("delivery_mode") if isinstance(pj, dict) else None
    if dm not in DELIVERY_MODES:
        return "fail", f"project.json delivery_mode={dm!r} not in {DELIVERY_MODES}"
    return "pass", f"delivery_mode={dm} is valid"


def check_16_timeline_backend_enum_valid(ctx):
    problems = []
    tj = ctx.get("timeline_json")
    if ctx.get("timeline_json_err"):
        problems.append(f"timeline.json unreadable: {ctx['timeline_json_err']}")
    if isinstance(tj, dict):
        b = tj.get("backend")
        if b not in TIMELINE_BACKENDS:
            problems.append(f"timeline.json backend={b!r} not in {TIMELINE_BACKENDS}")
    rj = ctx.get("routing_json")
    if ctx.get("routing_json_err"):
        problems.append(f"routing.json unreadable: {ctx['routing_json_err']}")
    if isinstance(rj, dict):
        r = rj.get("route")
        if r not in ROUTES:
            problems.append(f"routing.json route={r!r} not in {ROUTES}")
    if tj is None and rj is None and not ctx.get("timeline_json_err") and not ctx.get("routing_json_err"):
        return "na", "neither timeline.json nor routing.json present"
    if problems:
        return "fail", "; ".join(problems), problems
    return "pass", "timeline backend and routing route enums are valid"


CHECKLIST = [
    ("check_01_project_state_exists", "PROJECT_STATE.md exists and readable", check_01_project_state_exists),
    ("check_02_approvals_yaml_parses", "approvals.yaml parses", check_02_approvals_yaml_parses),
    ("check_03_schema_files_valid", "JSON data files match schemas (ID pattern + required)", check_03_schema_files_valid),
    ("check_04_scene_id_unique", "scene ids unique", check_04_scene_id_unique),
    ("check_05_shot_id_unique", "shot ids unique", check_05_shot_id_unique),
    ("check_06_layer_id_unique", "layer ids unique", check_06_layer_id_unique),
    ("check_07_asset_id_unique", "asset ids unique", check_07_asset_id_unique),
    ("check_08_stage_legal", "stage IDs within 31-stage enum", check_08_stage_legal),
    ("check_09_transition_legal", "adjacent stage transitions legal", check_09_transition_legal),
    ("check_10_current_stage_vs_approval_consistent", "approved stages consistent with approvals.yaml", check_10_current_stage_vs_approval_consistent),
    ("check_11_scene_shot_references_resolve", "scene->shot references resolve", check_11_scene_shot_references_resolve),
    ("check_12_shot_layer_references_resolve", "shot->layer references resolve", check_12_shot_layer_references_resolve),
    ("check_13_layer_asset_references_resolve", "layer->asset references resolve", check_13_layer_asset_references_resolve),
    ("check_14_asset_metadata_complete", "asset key metadata complete", check_14_asset_metadata_complete),
    ("check_15_delivery_mode_valid", "delivery_mode enum valid", check_15_delivery_mode_valid),
    ("check_16_timeline_backend_enum_valid", "timeline backend / routing route enums valid", check_16_timeline_backend_enum_valid),
]


# ---------------------------------------------------------------------------
# 运行与报告
# ---------------------------------------------------------------------------

def run_checks(ctx):
    results = []
    for cid, name, fn in CHECKLIST:
        try:
            res = fn(ctx)
        except Exception as exc:  # 检查函数自身异常 -> FAIL，不中断整体
            res = ("fail", f"internal error: {type(exc).__name__}: {exc}")
        if len(res) == 2:
            status, msg, details = res[0], res[1], []
        else:
            status, msg, details = res
        results.append({"id": cid, "name": name, "status": status, "message": msg, "details": details})
    return results


def render_human(project_dir, results, exit_code, yaml_strategy):
    lines = [f"ZHOU_Videodirector project validator — {project_dir}",
             f"YAML strategy: {yaml_strategy}", "-" * 74]
    for r in results:
        tag = {"pass": "PASS", "fail": "FAIL", "na": "N/A"}[r["status"]]
        lines.append(f"[{tag}] {r['id']:<44} {r['message']}")
        for d in (r["details"] or [])[:10]:
            lines.append(f"          - {d}")
    lines.append("-" * 74)
    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_na = sum(1 for r in results if r["status"] == "na")
    lines.append(f"Summary: {n_pass} passed, {n_fail} failed, {n_na} N/A")
    lines.append(f"Exit code: {exit_code}")
    return "\n".join(lines)


def render_json(results, ctx, exit_code):
    summary = {
        "total": len(results),
        "pass": sum(1 for r in results if r["status"] == "pass"),
        "fail": sum(1 for r in results if r["status"] == "fail"),
        "na": sum(1 for r in results if r["status"] == "na"),
    }
    return json.dumps(
        {
            "validator": "ZHOU_Videodirector/project-validate.py",
            "yaml_strategy": ctx["yaml_strategy"],
            "project_dir": str(ctx["project_dir"]),
            "exit_code": exit_code,
            "summary": summary,
            "checks": results,
        },
        indent=2,
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# 内置自检：构造一个覆盖全部 16 项检查（含失败路径）的临时项目目录
# ---------------------------------------------------------------------------

_SAMPLE_SCENE = {
    "id": "SC001", "chapter": "ch1", "order": 1, "title": "Opening",
    "narrative_role": "hook", "purpose": "grab attention", "target_duration": 10.0,
    "shots": [{"shot_id": "S001", "order": 1}, {"shot_id": "S999", "order": 2}],
    "visual_direction": "minimal", "audio_direction": "subtle",
    "approval": {"approval_id": "AP-001", "status": "approved"},
    "status": "approved", "notes": "ok",
}

_SAMPLE_SCENE2 = {
    "id": "SC001", "chapter": "ch1", "order": 2, "title": "Second",
    "narrative_role": "hook", "purpose": "x", "target_duration": 5.0, "shots": [],
    "visual_direction": "minimal", "audio_direction": "subtle",
    "approval": {"approval_id": "AP-002", "status": "pending"},
    "status": "in_progress", "notes": "",
}

_SAMPLE_SHOT_BASE = {
    "scene_id": "SC001", "order": 1, "duration": 5.0, "start_time": 0.0, "end_time": 5.0,
    "narrative_purpose": "intro", "voiceover": "", "on_screen_text": "",
    "visual_description": "minimal", "camera": "static", "motion": "none",
    "audio": {
        "music": {"mode": "calm", "cue": "start", "action": "rise"},
        "sfx": [], "ambience": [], "sync_points": [],
        "voiceover": {"present": False, "ducking": "none"}, "notes": "",
    },
    "transition_in": "cut", "transition_out": "cut",
    "route": "HYBRID", "continuity_group": "", "assets": [], "dependencies": [],
    "approval": {"approval_id": "AP-001", "status": "approved"},
    "implementation_status": "completed", "qa_status": "passed", "notes": "",
}

_SAMPLE_LAYER = {
    "shot_id": "S001", "name": "bg", "role": "BACKGROUND", "z_order": 1, "type": "BG",
    "visual_description": "dark", "route": "REMOTION", "producer": "remotion",
    "blend_mode": "normal", "alpha": True, "position": {"x": 0, "y": 0}, "scale": 1,
    "rotation": 0, "motion": "none", "audio_relation": "", "editable": True,
    "baked": False, "dependencies": [],
    "approval": {"approval_id": "AP-003", "status": "approved"}, "status": "approved",
}

_SAMPLE_ASSET = {
    "name": "overlay", "type": "TRANSPARENT_OVERLAY", "purpose": "glow",
    "producer": "REMOTION", "source": "https://example.com/a001", "local_path": "assets/a001.mov",
    "format": "mov", "resolution": {"w": 1920, "h": 1080}, "fps": 30, "duration": 3.0,
    "alpha": True, "version": "v1", "license": "CC0", "license_url": "",
    "attribution_required": False, "commercial_use": True, "preview": "", "cached": True,
    "replaceable": True, "timeline_usage": "overlay",
    "created_at": "2026-08-13T00:00:00Z", "modified_at": "2026-08-13T00:00:00Z", "status": "approved",
}

_SAMPLE_PROJECT_STATE = """# PROJECT_STATE — selftest

# Project: selftest
# Production Mode: PRODUCT_TECH_SHORT
# Delivery Mode: BOTH
# Current Stage: VISUAL_BIBLE_REVIEW
# Current Scene: SC001
# Current Shot: S001
# Approved Stages: [project_brief]
visual_bible approved
# Pending Decisions: []
# Blocked Items: []
# Next Action: n/a
# Last Updated: 2026-08-13T00:00:00Z
"""

_SAMPLE_APPROVALS = """# approvals.yaml — selftest
project:
  project_brief:
    status: approved
  reference_analysis:
    status: not_started
  creative_direction:
    status: not_started
  visual_bible:
    status: pending
  audio_direction:
    status: not_started
  story_structure:
    status: not_started
  storyboard:
    status: not_started
  production_plan:
    status: not_started
  timeline_plan:
    status: not_started
  final_qa:
    status: not_started
scenes: {}
shots: {}
assets: {}
"""


def _write_selftest_project(proj):
    (proj / "scenes").mkdir()
    (proj / "shots").mkdir()
    (proj / "layers").mkdir()
    (proj / "assets").mkdir()
    (proj / "PROJECT_STATE.md").write_text(_SAMPLE_PROJECT_STATE, encoding="utf-8")
    (proj / "approvals.yaml").write_text(_SAMPLE_APPROVALS, encoding="utf-8")

    (proj / "scenes" / "SC001.json").write_text(json.dumps(_SAMPLE_SCENE, ensure_ascii=False), encoding="utf-8")
    (proj / "scenes" / "SC002.json").write_text(json.dumps(_SAMPLE_SCENE2, ensure_ascii=False), encoding="utf-8")

    shot1 = dict(_SAMPLE_SHOT_BASE, id="S001",
                 layers=[{"layer_id": "L001", "z_order": 1}],
                 stage_history=["INIT", "PROJECT_INTAKE", "PROJECT_BRIEF_REVIEW", "REFERENCE_ANALYSIS"],
                 status_history=["PROJECT_INTAKE", "COMPLETE"])
    shot2 = dict(_SAMPLE_SHOT_BASE, id="S002", layers=[], stage="SUPER_COOL_VIDEO_STAGE")
    (proj / "shots" / "S001.json").write_text(json.dumps(shot1, ensure_ascii=False), encoding="utf-8")
    (proj / "shots" / "S002.json").write_text(json.dumps(shot2, ensure_ascii=False), encoding="utf-8")

    (proj / "layers" / "L001.json").write_text(json.dumps(dict(_SAMPLE_LAYER, id="L001", asset_id="A001"), ensure_ascii=False), encoding="utf-8")
    (proj / "layers" / "L002.json").write_text(json.dumps(dict(_SAMPLE_LAYER, id="L002", asset_id="A999"), ensure_ascii=False), encoding="utf-8")

    (proj / "assets" / "A001.json").write_text(json.dumps(dict(_SAMPLE_ASSET, asset_id="A001"), ensure_ascii=False), encoding="utf-8")
    asset2 = dict(_SAMPLE_ASSET, asset_id="A002")
    asset2.pop("producer")  # -> check_03 fail
    asset2.pop("license")   # -> check_03 + check_14 fail
    (proj / "assets" / "A002.json").write_text(json.dumps(asset2, ensure_ascii=False), encoding="utf-8")

    (proj / "project.json").write_text(json.dumps({
        "title": "T", "production_mode": "PRODUCT_TECH_SHORT", "delivery_mode": "WRONG",
        "platform": "youtube", "aspect_ratio": "16:9", "resolution": {"width": 1920, "height": 1080},
        "fps": 30, "target_duration": 90, "audience": "devs", "primary_goal": "intro",
        "core_message": "x", "language": "en", "voiceover": True, "reference_sources": [],
        "available_assets": [], "brand_constraints": [], "style_preferences": [],
        "style_avoidances": [], "ai_video_allowed": True, "real_footage_allowed": False,
        "3d_allowed": False, "editable_timeline_required": True, "budget_priority": "medium",
        "quality_priority": "high", "time_priority": "medium", "user_notes": "",
    }, ensure_ascii=False), encoding="utf-8")

    (proj / "timeline.json").write_text(json.dumps({
        "backend": "BADBACKEND", "project_path": "", "canvas": {"w": 1920, "h": 1080}, "fps": 30,
        "resolution": {"w": 1920, "h": 1080}, "tracks": [], "clips": [], "text_items": [],
        "subtitle_items": [], "audio_tracks": [], "sfx_tracks": [], "music_tracks": [],
        "overlays": [], "keyframes": [], "transitions": [], "asset_links": [],
        "replaceable_assets": [], "manual_edit_safe": True, "version": "v0", "status": "in_progress",
    }, ensure_ascii=False), encoding="utf-8")

    (proj / "routing.json").write_text(json.dumps({
        "target_type": "shot", "target_id": "S001", "route": "BADROUTE", "confidence": 0.8,
        "scores": {k: 0.5 for k in (
            "structural_precision", "photorealism", "organic_motion", "scene_entropy",
            "text_accuracy", "data_accuracy", "revision_requirement", "timing_precision",
            "atmosphere_requirement", "physical_complexity", "camera_complexity",
            "editability_requirement")},
        "decision_summary": "ok", "fallback": "REMOTION", "prototype_required": False,
        "approval": {"approval_id": "AP-005", "status": "approved"},
    }, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 内置自检：构造多个 fixture 互补覆盖每条 check 的 pass 与 fail 两条路径
#   dirty  fixture: 故意制造多数 check 失败的脏项目（原单 fixture，保留）
#   clean  fixture: 全部合法的干净项目，让每条 check 都触发 pass
#   broken fixture: 最小破项目，补上 dirty 中为 pass 的 check 的 fail 路径
# ---------------------------------------------------------------------------

_CLEAN_PROJECT_STATE = """# PROJECT_STATE — selftest clean

# Project: selftest_clean
# Production Mode: PRODUCT_TECH_SHORT
# Delivery Mode: BOTH
# Current Stage: VISUAL_BIBLE_REVIEW
# Current Scene: SC001
# Current Shot: S001
# Approved Stages: [project_brief, visual_bible]
project_brief approved
visual_bible approved
# Pending Decisions: []
# Blocked Items: []
# Next Action: n/a
# Last Updated: 2026-08-13T00:00:00Z
"""

_CLEAN_APPROVALS = """# approvals.yaml — selftest clean
project:
  project_brief:
    status: approved
  reference_analysis:
    status: not_started
  creative_direction:
    status: not_started
  visual_bible:
    status: approved
  audio_direction:
    status: not_started
  story_structure:
    status: not_started
  storyboard:
    status: not_started
  production_plan:
    status: not_started
  timeline_plan:
    status: not_started
  final_qa:
    status: not_started
scenes: {}
shots: {}
assets: {}
"""


def _write_selftest_project_clean(proj):
    """全合法 fixture：16 条 check 都应触发 pass（覆盖 fail 型 fixture 未命中的 pass 路径）。"""
    for sub in ("scenes", "shots", "layers", "assets"):
        (proj / sub).mkdir()
    (proj / "PROJECT_STATE.md").write_text(_CLEAN_PROJECT_STATE, encoding="utf-8")
    (proj / "approvals.yaml").write_text(_CLEAN_APPROVALS, encoding="utf-8")

    scene1 = dict(_SAMPLE_SCENE, id="SC001",
                  shots=[{"shot_id": "S001", "order": 1}, {"shot_id": "S002", "order": 2}])
    scene2 = dict(_SAMPLE_SCENE2, id="SC002", shots=[])
    (proj / "scenes" / "SC001.json").write_text(json.dumps(scene1, ensure_ascii=False), encoding="utf-8")
    (proj / "scenes" / "SC002.json").write_text(json.dumps(scene2, ensure_ascii=False), encoding="utf-8")

    shot1 = dict(_SAMPLE_SHOT_BASE, id="S001",
                 layers=[{"layer_id": "L001", "z_order": 1}],
                 stage_history=["PROJECT_INTAKE", "PROJECT_BRIEF_REVIEW", "REFERENCE_ANALYSIS"])
    shot2 = dict(_SAMPLE_SHOT_BASE, id="S002", layers=[{"layer_id": "L002", "z_order": 1}])
    (proj / "shots" / "S001.json").write_text(json.dumps(shot1, ensure_ascii=False), encoding="utf-8")
    (proj / "shots" / "S002.json").write_text(json.dumps(shot2, ensure_ascii=False), encoding="utf-8")

    (proj / "layers" / "L001.json").write_text(
        json.dumps(dict(_SAMPLE_LAYER, id="L001", shot_id="S001", asset_id="A001"), ensure_ascii=False), encoding="utf-8")
    (proj / "layers" / "L002.json").write_text(
        json.dumps(dict(_SAMPLE_LAYER, id="L002", shot_id="S002", asset_id="A002"), ensure_ascii=False), encoding="utf-8")

    (proj / "assets" / "A001.json").write_text(
        json.dumps(dict(_SAMPLE_ASSET, asset_id="A001"), ensure_ascii=False), encoding="utf-8")
    (proj / "assets" / "A002.json").write_text(
        json.dumps(dict(_SAMPLE_ASSET, asset_id="A002"), ensure_ascii=False), encoding="utf-8")

    (proj / "project.json").write_text(json.dumps({
        "title": "T", "production_mode": "PRODUCT_TECH_SHORT", "delivery_mode": "BOTH",
        "platform": "youtube", "aspect_ratio": "16:9", "resolution": {"width": 1920, "height": 1080},
        "fps": 30, "target_duration": 90, "audience": "devs", "primary_goal": "intro",
        "core_message": "x", "language": "en", "voiceover": True, "reference_sources": [],
        "available_assets": [], "brand_constraints": [], "style_preferences": [],
        "style_avoidances": [], "ai_video_allowed": True, "real_footage_allowed": False,
        "3d_allowed": False, "editable_timeline_required": True, "budget_priority": "medium",
        "quality_priority": "high", "time_priority": "medium", "user_notes": "",
    }, ensure_ascii=False), encoding="utf-8")

    (proj / "timeline.json").write_text(json.dumps({
        "backend": "PYJIANYINGDRAFT", "project_path": "", "canvas": {"w": 1920, "h": 1080}, "fps": 30,
        "resolution": {"w": 1920, "h": 1080}, "tracks": [], "clips": [], "text_items": [],
        "subtitle_items": [], "audio_tracks": [], "sfx_tracks": [], "music_tracks": [],
        "overlays": [], "keyframes": [], "transitions": [], "asset_links": [],
        "replaceable_assets": [], "manual_edit_safe": True, "version": "v0", "status": "in_progress",
    }, ensure_ascii=False), encoding="utf-8")

    (proj / "routing.json").write_text(json.dumps({
        "target_type": "shot", "target_id": "S001", "route": "REMOTION", "confidence": 0.8,
        "scores": {k: 0.5 for k in (
            "structural_precision", "photorealism", "organic_motion", "scene_entropy",
            "text_accuracy", "data_accuracy", "revision_requirement", "timing_precision",
            "atmosphere_requirement", "physical_complexity", "camera_complexity",
            "editability_requirement")},
        "decision_summary": "ok", "fallback": "HYBRID", "prototype_required": False,
        "approval": {"approval_id": "AP-005", "status": "approved"},
    }, ensure_ascii=False), encoding="utf-8")


def _write_selftest_project_broken(proj):
    """最小破 fixture：补上 dirty 中为 pass 的 check 的 fail 路径。
    故意缺失 PROJECT_STATE.md / approvals.yaml（check_01/02 fail），
    重复 shot/layer/asset id（check_05/06/07 fail），shot 引用不存在的 layer（check_12 fail）。
    其余 check 因缺少对应输入而为 N/A 或 pass（其双路径已由 dirty/clean 覆盖）。"""
    for sub in ("shots", "layers", "assets"):
        (proj / sub).mkdir()

    shot1 = dict(_SAMPLE_SHOT_BASE, id="S001", layers=[{"layer_id": "L001", "z_order": 1}])
    shot2 = dict(_SAMPLE_SHOT_BASE, id="S001", layers=[])                       # 重复 id -> check_05 fail
    shot3 = dict(_SAMPLE_SHOT_BASE, id="S002", layers=[{"layer_id": "L999", "z_order": 1}])  # L999 缺失 -> check_12 fail
    (proj / "shots" / "S001.json").write_text(json.dumps(shot1, ensure_ascii=False), encoding="utf-8")
    (proj / "shots" / "S001_dup.json").write_text(json.dumps(shot2, ensure_ascii=False), encoding="utf-8")
    (proj / "shots" / "S002.json").write_text(json.dumps(shot3, ensure_ascii=False), encoding="utf-8")

    (proj / "layers" / "L001.json").write_text(
        json.dumps(dict(_SAMPLE_LAYER, id="L001", shot_id="S001", asset_id="A001"), ensure_ascii=False), encoding="utf-8")
    (proj / "layers" / "L001_dup.json").write_text(
        json.dumps(dict(_SAMPLE_LAYER, id="L001", shot_id="S001", asset_id="A001"), ensure_ascii=False), encoding="utf-8")  # 重复 -> check_06 fail

    (proj / "assets" / "A001.json").write_text(
        json.dumps(dict(_SAMPLE_ASSET, asset_id="A001"), ensure_ascii=False), encoding="utf-8")
    (proj / "assets" / "A001_dup.json").write_text(
        json.dumps(dict(_SAMPLE_ASSET, asset_id="A001"), ensure_ascii=False), encoding="utf-8")  # 重复 -> check_07 fail


SELFTEST_EXPECTED = {
    "dirty": {
        "check_01_project_state_exists": "pass",
        "check_02_approvals_yaml_parses": "pass",
        "check_03_schema_files_valid": "fail",
        "check_04_scene_id_unique": "fail",
        "check_05_shot_id_unique": "pass",
        "check_06_layer_id_unique": "pass",
        "check_07_asset_id_unique": "pass",
        "check_08_stage_legal": "fail",
        "check_09_transition_legal": "fail",
        "check_10_current_stage_vs_approval_consistent": "fail",
        "check_11_scene_shot_references_resolve": "fail",
        "check_12_shot_layer_references_resolve": "pass",
        "check_13_layer_asset_references_resolve": "fail",
        "check_14_asset_metadata_complete": "fail",
        "check_15_delivery_mode_valid": "fail",
        "check_16_timeline_backend_enum_valid": "fail",
    },
    "clean": {
        "check_01_project_state_exists": "pass",
        "check_02_approvals_yaml_parses": "pass",
        "check_03_schema_files_valid": "pass",
        "check_04_scene_id_unique": "pass",
        "check_05_shot_id_unique": "pass",
        "check_06_layer_id_unique": "pass",
        "check_07_asset_id_unique": "pass",
        "check_08_stage_legal": "pass",
        "check_09_transition_legal": "pass",
        "check_10_current_stage_vs_approval_consistent": "pass",
        "check_11_scene_shot_references_resolve": "pass",
        "check_12_shot_layer_references_resolve": "pass",
        "check_13_layer_asset_references_resolve": "pass",
        "check_14_asset_metadata_complete": "pass",
        "check_15_delivery_mode_valid": "pass",
        "check_16_timeline_backend_enum_valid": "pass",
    },
    "broken": {
        "check_01_project_state_exists": "fail",
        "check_02_approvals_yaml_parses": "fail",
        "check_03_schema_files_valid": "pass",
        "check_04_scene_id_unique": "na",
        "check_05_shot_id_unique": "fail",
        "check_06_layer_id_unique": "fail",
        "check_07_asset_id_unique": "fail",
        "check_08_stage_legal": "na",
        "check_09_transition_legal": "na",
        "check_10_current_stage_vs_approval_consistent": "na",
        "check_11_scene_shot_references_resolve": "na",
        "check_12_shot_layer_references_resolve": "fail",
        "check_13_layer_asset_references_resolve": "pass",
        "check_14_asset_metadata_complete": "pass",
        "check_15_delivery_mode_valid": "na",
        "check_16_timeline_backend_enum_valid": "na",
    },
}

SELFTEST_FIXTURES = [
    ("dirty", "故意制造多数 check 失败的脏项目", _write_selftest_project),
    ("clean", "全部合法的干净项目", _write_selftest_project_clean),
    ("broken", "缺失必需文件 + 重复 id 的最小破项目", _write_selftest_project_broken),
]


def run_selftest():
    with tempfile.TemporaryDirectory(prefix="p5b_selftest_") as tmp:
        base = Path(tmp)
        rounds = []
        bad = 0
        out = ["SELF TEST — per-fixture expected vs actual status per check", "-" * 74]
        for name, desc, writer in SELFTEST_FIXTURES:
            proj = base / name
            proj.mkdir()
            writer(proj)
            ctx = build_context(proj)
            results = run_checks(ctx)
            rounds.append(results)
            expected = SELFTEST_EXPECTED[name]
            out.append(f"--- fixture [{name}] — {desc} (YAML: {ctx['yaml_strategy']}) ---")
            for r in results:
                exp = expected.get(r["id"], "?")
                ok = exp == r["status"]
                bad += 0 if ok else 1
                out.append(f"[{'OK ' if ok else 'BAD'}] {r['id']:<44} expected={exp:<5} actual={r['status']}")
                if r["status"] == "fail":
                    out.append(f"          {r['message']}")

        # 双路径覆盖断言：每条 check 在所有 fixture 中至少要命中一次 pass 和一次 fail
        covered = {}
        for results in rounds:
            for r in results:
                covered.setdefault(r["id"], set()).add(r["status"])
        out.append("-" * 74)
        out.append("Dual-path coverage: every check must hit both 'pass' and 'fail' across all fixtures")
        cov_bad = 0
        for cid in (r["id"] for r in rounds[0]):
            st = sorted(covered.get(cid, set()))
            ok = "pass" in st and "fail" in st
            cov_bad += 0 if ok else 1
            out.append(f"[{'OK ' if ok else 'BAD'}] {cid:<44} covered statuses={st}")
        out.append("-" * 74)
        ok_all = (bad == 0 and cov_bad == 0)
        out.append(
            f"SELF TEST {'PASS' if ok_all else 'FAIL'} ({bad} expectation mismatch(es), {cov_bad} coverage gap(s))"
        )
        return (0 if ok_all else 1), "\n".join(out)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="project-validate.py",
        description="ZHOU_Videodirector Phase 1 project validator (stdlib only).",
    )
    ap.add_argument("project_dir", nargs="?", help="project directory to validate")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    ap.add_argument("--selftest", action="store_true", help="run built-in self test against a temp project")
    args = ap.parse_args(argv)

    if args.selftest:
        code, out = run_selftest()
        print(out)
        return code
    if not args.project_dir:
        ap.error("project_dir is required")

    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        msg = f"FATAL: project directory does not exist or is not a directory: {project_dir}"
        if args.json:
            print(json.dumps({"fatal": msg, "exit_code": 2}, indent=2))
        else:
            print(msg)
        return 2

    try:
        ctx = build_context(project_dir)
    except FatalError as exc:
        msg = f"FATAL: {exc}"
        if args.json:
            print(json.dumps({"fatal": msg, "exit_code": 2}, indent=2))
        else:
            print(msg)
        return 2

    results = run_checks(ctx)
    exit_code = 1 if any(r["status"] == "fail" for r in results) else 0
    if args.json:
        print(render_json(results, ctx, exit_code))
    else:
        print(render_human(project_dir, results, exit_code, ctx["yaml_strategy"]))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
