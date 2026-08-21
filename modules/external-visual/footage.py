#!/usr/bin/env python3
"""footage.py — ZHOU_Videodirector Phase 6 Real Footage Pipeline (P6-03).

负责 REAL_FOOTAGE 分支的完整研究管线（Phase-6 Prompt §52-84 / §118-121）：

    EV(route=REAL_FOOTAGE) → build_request → FR-###（Footage Request）
        → search（经 Phase-4 Registry find，不自建搜索系统 §59）
        → rank（10 因子加权 §61）
        → select（License 硬门槛 §62-63 / 付费门禁 §64 / STRICT 真实性 §56-57）
        → plan_use（可用区间 §71 / Timeline Hint §72 / Treatment §75-76 /
                    Mask/Tracking 规划 §81 / Stabilization §82 / Audio §83）

关键边界（§52-84）：
    - search 必须经 scripts/registry.py find --type FOOTAGE --json（§59），失败退回 import 桥；
    - License 是硬门槛：未知授权绝不标 commercial_safe（§62-63）；
    - 历史事件 STRICT authenticity 只留 era/time_period 匹配且来源明确的候选（§56-57）；
    - 付费 / 大文件 / 路由变更只产提案与 approval 要求，绝不私改路由（§64 / §78-79 / §111）；
    - 本模块全部确定性纯函数；无 LLM；无联网；fetch 只产门禁记录，不真实下载。

共享契约：FR 字段见 footage-request 语义（§54）；candidate 形状对齐 registry.py find
的 candidate_dict + detail 的 L1（license 全量 / type_specific.footage）。

技术约束：Python 3 stdlib only；无 LLM；无联网；确定性。
代码风格照抄 modules/production/motion.py（中文 docstring 带 §出处、subprocess registry 桥、
__all__ + __main__ 冒烟）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PY = SKILL_ROOT / "scripts" / "registry.py"
PROVIDERS_JSON = SKILL_ROOT / "registry" / "index" / "providers.json"

# ---------------------------------------------------------------------------
# 共享枚举（Phase-6 Prompt §54-56 / §61 / §72 / §83）
# ---------------------------------------------------------------------------

AUTHENTICITY_REQUIREMENTS = ["STRICT", "PREFERRED", "NOT_REQUIRED"]
AUDIO_BEHAVIORS = ["KEEP", "MUTE", "USE_AS_AMBIENCE", "EXTRACT", "REPLACE"]
SOURCE_TIERS = [
    "USER_PROVIDED", "PUBLIC_DOMAIN", "INSTITUTIONAL_ARCHIVE",
    "OPEN_LICENSE", "STOCK_FREE", "STOCK_PAID",
]
# §55 默认来源优先级（可被项目配置 source_priority_override 覆盖）
DEFAULT_SOURCE_PRIORITY = list(SOURCE_TIERS)
_TIER_RANK = {t: i for i, t in enumerate(SOURCE_TIERS)}

# 历史事件 / 年代关键词（build_request 判定 STRICT authenticity，§56-57）
_HISTORY_KEYWORDS = (
    "war", "战争", "revolution", "革命", "dynasty", "王朝", "帝国", "empire",
    "world war", "世界大战", "wwi", "wwii", "civil war", "内战", "cold war",
    "冷战", "depression", "大萧条", "renaissance", "文艺复兴", "moon landing",
    "登月", "apollo", "space race", "太空竞赛", "victorian", "维多利亚",
    "edwardian", "prohibition", "禁酒", "industrial revolution", "工业革命",
    "civil rights", "民权", "民国", "清代", "明治", "古代", "中世纪", "罗马",
    "ancient", "medieval", "rome", "roman", "gold rush", "淘金", "殖民",
    "colonial", "帝国时代", "朝代",
)
# 具体年代/世纪形态：1920s / 1969 / 1906年 / 19th century / 二十世纪 等
_HISTORIC_ERA_RE = re.compile(
    r"(\b(1[4-9]\d{2}|20[0-2]\d)\b\s*s?)"          # 1400-2029 + 可选 s
    r"|(\d{3,4}\s*年)"
    r"|((1[0-9]|20)(th|st|nd|rd)\s*century)"
    r"|(century|世纪)"
    r"|((十八|十九|二十|二十一)世纪)"
)

# 10 因子权重（§61，总和 1.0）
RANK_WEIGHTS = {
    "semantic_relevance": 0.18,
    "authenticity": 0.15,
    "visual_quality": 0.08,
    "camera_suitability": 0.08,
    "duration": 0.10,
    "resolution": 0.05,
    "license": 0.10,
    "visual_bible_fit": 0.14,
    "editability": 0.06,
    "download_cost": 0.06,
}

# 候选文本关键词 → 编辑性/质量属性（确定性关键字匹配）
_WATERMARK_TOKENS = ("watermark", "水印", "logo", "品牌", "caption burnt", "时间码")
_DEGRADE_TOKENS = ("damaged", "scratch", "划痕", "噪声大", "heavily degraded", "破损", "抖动", "shaky", "shake", "handheld")
_CAMERA_POSITIVE = ("pan", "摇", "tilt", "俯", "aerial", "航拍", "static", "固定", "push in", "推", "timelapse", "延时", "slow motion", "慢动作", "tracking", "跟拍", "orbit", "环绕")

# registry.py find 的 8 因子 score 偏保守，语义因子取 0.4 权重并入（确定性输入 → 确定性输出）
_REGISTRY_SCORE_WEIGHT = 0.4

_LARGE_BYTES = 500 * 1024 * 1024   # >500MB 视为大文件（§65）
_4K_TOKENS = ("4k", "4k uhd", "2160", "uhd")

_PAID_TOKENS = ("paid", "付费", "premium", "purchase", "buy", "credit")

# 候选「合格」下限（§118 失败恢复语义）：registry find 的 8 因子评分带 route 类型基线噪声
# （无实质命中时 rel≈0.25 纯基线），低于下限视为无合格 footage → 走 still_fallback /
# 路由提案，禁止把基线噪声候选当真实素材选中。
MIN_RANK_SCORE = 0.25
MIN_SEMANTIC_RELEVANCE = 0.12

# 默认 b-roll 密度约束（无 editorial_direction 时的兜底：每 60s 最多 3 个）
DEFAULT_B_ROLL_PER_MINUTE = 3

# 时间戳格式
def _fmt_ts(seconds):
    """秒 -> 'mm:ss.d'（确定性）。"""
    try:
        sec = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return "00:00.0"
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:04.1f}"


def _norm(value, enum_list, default=None):
    """大小写/连字符变体 -> 规范大写枚举；失败返回 default。"""
    if value is None:
        return default
    if isinstance(value, str):
        up = value.strip().upper().replace("-", "_")
        for e in enum_list:
            if up == e or e in up:
                return e
    return default


def _tokens(text):
    """文本 -> 小写 token 集合（确定性）。"""
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


def _get(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Registry 桥（subprocess find / detail；失败退回 import；§59）
# ---------------------------------------------------------------------------

def _env_for_index(registry_index):
    """registry_index 指定时通过 ZHOU_REGISTRY_INDEX_DIR 传给 registry.py（含 import 桥）。"""
    env = dict(os.environ)
    if registry_index:
        env["ZHOU_REGISTRY_INDEX_DIR"] = str(registry_index)
    return env


def _registry_find(query, single_type="FOOTAGE", limit=8, provider=None,
                   route=None, registry_index=None, timeout=30):
    """调 scripts/registry.py find --json；失败退回 import 复用；再失败抛异常。

    参数与输出键名已在读 scripts/registry.py run_find/candidate_dict 后确认：
        find <query...> --type <TYPE> [--provider P] [--route R] [--limit N] --json
        -> {results: [{resource_id, name, provider, type, why_matched, score,
                       factors, fit, preview_url, source_url, license, ...}]}
    """
    cmd = [sys.executable, str(REGISTRY_PY), "find", query or "", "--json",
           "--limit", str(limit)]
    if single_type:
        cmd += ["--type", single_type]
    if provider:
        cmd += ["--provider", provider]
    if route:
        cmd += ["--route", route]
    env = _env_for_index(registry_index)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=str(SKILL_ROOT), env=env)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            return data.get("results") or []
    except Exception:  # noqa: BLE001
        pass  # 退回 import 复用（registry.py 有 __main__ 保护，可安全 import）
    try:
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        import registry as _reg  # noqa: PLC0415

        store = _reg.Store(index_dir=registry_index) if registry_index else _reg.Store()
        types = [single_type] if single_type else None
        ranked, _meta = _reg.search(store, query or "", types=types,
                                    provider=provider, route=route)
        ranked = _reg.apply_family(ranked)
        ranked = _reg.apply_diversity(ranked, limit)
        return [_reg.candidate_dict(c, "any") for c in ranked]
    except Exception:  # noqa: BLE001
        raise


def _registry_detail(resource_id, registry_index=None, timeout=30):
    """调 scripts/registry.py detail --json 取 L1 全量（license 全量 + type_specific.footage）。

    失败退回 import 桥 Store.resolve_id + build_l1。
    """
    cmd = [sys.executable, str(REGISTRY_PY), "detail", resource_id, "--json"]
    env = _env_for_index(registry_index)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=str(SKILL_ROOT), env=env)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            return data.get("detail") or {}
    except Exception:  # noqa: BLE001
        pass
    try:
        sys.path.insert(0, str(SKILL_ROOT / "scripts"))
        import registry as _reg  # noqa: PLC0415

        store = _reg.Store(index_dir=registry_index) if registry_index else _reg.Store()
        r = store.resolve_id(resource_id)
        if r is None:
            return {}
        return _reg.build_l1(r)
    except Exception:  # noqa: BLE001
        return {}


def load_providers():
    """读 registry/index/providers.json -> {id: provider}（Provider 只以数据存在，不写死分支）。"""
    try:
        data = json.loads(PROVIDERS_JSON.read_text(encoding="utf-8"))
        return {p["id"]: p for p in (data.get("providers") or []) if isinstance(p, dict)}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# source_priority（§55）：来源分级（provider 只以数据存在，tier 由 license_model/
# license_type/license_notes 文本关键字确定性推导，可被项目配置 source_priority_override 覆盖）
# ---------------------------------------------------------------------------

#: license 文本关键字 -> source tier
_SOURCE_TIER_KEYWORDS = (
    ("user", "USER_PROVIDED"),
    ("cc0", "PUBLIC_DOMAIN"),
    ("public domain", "PUBLIC_DOMAIN"),
    ("public-domain", "PUBLIC_DOMAIN"),
    ("pd", "PUBLIC_DOMAIN"),
    ("archive", "INSTITUTIONAL_ARCHIVE"),
    ("institution", "INSTITUTIONAL_ARCHIVE"),
    ("per-file", "OPEN_LICENSE"),
    ("per file", "OPEN_LICENSE"),
    ("cc-by", "OPEN_LICENSE"),
    ("cc by", "OPEN_LICENSE"),
    ("open license", "OPEN_LICENSE"),
    ("attribution", "OPEN_LICENSE"),
    ("paid", "STOCK_PAID"),
    ("premium", "STOCK_PAID"),
    ("purchase", "STOCK_PAID"),
    ("pexels", "STOCK_FREE"),
    ("pixabay", "STOCK_FREE"),
    ("mixkit", "STOCK_FREE"),
    ("free commercial", "STOCK_FREE"),
    ("免费商用", "STOCK_FREE"),
)


def source_tier_for(candidate, providers=None, source_priority_override=None):
    """确定性推导候选的来源层级（§55）。

    Override 优先（项目配置，如 {"internet-archive": "INSTITUTIONAL_ARCHIVE"}）；
    否则按 license_model / license_type / license_notes 关键字推导；未知 -> STOCK_FREE 保守层。
    """
    provs = providers if providers is not None else load_providers()
    pid = _get(candidate, "provider", "provider_id") or ""
    if source_priority_override and pid in source_priority_override:
        return source_priority_override[pid]
    if pid in provs:
        p = provs[pid]
        lm = str(_get(p, "license_model") or "")
        pn = str(_get(p, "notes") or "")
        for kw, tier in _SOURCE_TIER_KEYWORDS:
            if kw in lm.lower() or kw in pn.lower():
                return tier
    lic = _get(candidate, "license", "license_full") or {}
    lic_text = " ".join([
        str(lic.get("license_type") or ""),
        str(lic.get("license_notes") or ""),
    ]).lower()
    for kw, tier in _SOURCE_TIER_KEYWORDS:
        if kw in lic_text:
            return tier
    return "STOCK_FREE"


def source_priority_list(ft_request):
    """返回当前生效的来源优先级列表（项目配置覆盖默认，§55）。"""
    ov = _get(ft_request, "source_priority_override", "source_priority") or {}
    if isinstance(ov, dict) and ov:
        # 字典形态：{tier: [provider...]} 或 {provider: tier}；都归并为顺序
        ordered = _get(ft_request, "source_priority_order")
        if isinstance(ordered, list) and ordered:
            return ordered
    base = list(DEFAULT_SOURCE_PRIORITY)
    return base


# ---------------------------------------------------------------------------
# build_request —— EV → FR-###（§54 / §56-57）
# ---------------------------------------------------------------------------

# F1/R5：字符串分辨率 → 像素 写死解析表（确定性映射；未知兜底 1080p 保守下限）
_RESOLUTION_TOKENS = (
    ("3840x2160", 3840, 2160),
    ("4k", 3840, 2160),
    ("2160", 3840, 2160),
    ("uhd", 3840, 2160),
    ("1920x1080", 1920, 1080),
    ("1080p", 1920, 1080),
    ("fullhd", 1920, 1080),
    ("fhd", 1920, 1080),
    ("1280x720", 1280, 720),
    ("720p", 1280, 720),
    ("854x480", 854, 480),
    ("480p", 854, 480),
    ("640x480", 640, 480),
    ("sd", 640, 480),
)

# F1/R5：search_depth int → string 映射表（写死；§119：basic/standard/deep）
SEARCH_DEPTH_STR = {1: "basic", 2: "standard", 3: "deep"}
_DEPTH_TO_INT = {v: k for k, v in SEARCH_DEPTH_STR.items()}


def _norm_search_depth(value, default=1):
    """search_depth 归一为 int（search() 消费；build_request 输出 string）。"""
    if isinstance(value, str):
        return _DEPTH_TO_INT.get(value.strip().lower(), default)
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _min_resolution(ev):
    """F1/R5：minimum_resolution → {w, h} 对象。

    优先取 ev.resolution / ev.minimum_resolution 的 dict {w,h}；字符串经
    _RESOLUTION_TOKENS 写死解析表映射（1080p→1920x1080、720p→1280x720、
    4k→3840x2160）；无法解析 → 保守兜底 1920x1080（对齐 schema 对象形状）。
    """
    res = _get(ev, "minimum_resolution", "resolution")
    if isinstance(res, dict):
        w = res.get("w") or res.get("width")
        h = res.get("h") or res.get("height")
        if w and h:
            return {"w": int(w), "h": int(h)}
    s = re.sub(r"\s+", "", str(res or "").lower())
    w = h = None
    m = re.search(r"(\d{3,4})x(\d{3,4})", s)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    else:
        for token, tw, th in _RESOLUTION_TOKENS:
            if token in s:
                w, h = tw, th
                break
    if w is None or h is None:
        w, h = 1920, 1080  # 缺省保守下限 1080p
    return {"w": w, "h": h}


def _license_requirement(ev):
    """F1/R5：license_requirement → 对象 {commercial_use, attribution_allowed,
    derivatives_allowed, redistribution_allowed}（§62 四项硬门槛）。

    来源优先级：ev 顶层显式布尔（展平键 commercial_use/attribution_allowed 等移入
    对象）> ev.license_requirements/ev.license_requirement dict > 字符串关键字推导。
    缺省保守（§62 License 是硬门槛，未知绝不标可商用）：commercial_use=false +
    attribution_allowed=true + derivatives_allowed=false + redistribution_allowed=false；
    commercial_safe 由 select 的 license_gate 判定（§63 LICENSE_REVIEW_REQUIRED）。

    语义依据（§62 四项硬门槛）：attribution_allowed = 「是否允许署名」。
    "no attribution required"/"attribution-free"/"无需署名" 这类表述只表示「不强制署名」，
    不强制 ≠ 禁止 → 不把 attribution_allowed 改为 false，保持缺省 true（允许署名只是可选）。
    """
    out = {
        "commercial_use": False,
        "attribution_allowed": True,
        "derivatives_allowed": False,
        "redistribution_allowed": False,
    }
    for key in out:
        if ev.get(key) is not None:
            out[key] = bool(ev.get(key))
    src = _get(ev, "license_requirements", "license_requirement")
    if isinstance(src, dict):
        for key in out:
            if src.get(key) is not None:
                out[key] = bool(src[key])
    elif isinstance(src, str) and src.strip():
        s = src.strip().lower()
        if ("commercial" in s or "商用" in s or "cc0" in s or "public domain" in s
                or "cc-by" in s or "免费商用" in s or "royalty" in s):
            out["commercial_use"] = True
        if "derivative" in s or "衍生" in s or "二次创作" in s:
            out["derivatives_allowed"] = True
        if "redistribut" in s or "再分发" in s or "重新分发" in s:
            out["redistribution_allowed"] = True
    return out


def _overlay_requirements(ev):
    """F1/R5：overlay_requirements 归一为 array of strings（schema 契约）；
    字符串 → 单元素列表；list → 逐项 str（dict 元素 JSON 序列化）；缺失 → []。"""
    v = _get(ev, "overlay_requirements")
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        out = []
        for item in v:
            s = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            if s and str(s).strip():
                out.append(str(s).strip())
        return out
    return [str(v)]


def _resolution_label(value):
    """minimum_resolution（{w,h} 对象或字符串）→ 评分标签（1080p/720p/4k）。"""
    if isinstance(value, dict):
        w = int(value.get("w") or 0)
        h = int(value.get("h") or 0)
        if (w, h) == (3840, 2160):
            return "4k"
        if (w, h) == (1280, 720):
            return "720p"
        return "1080p"  # 1920x1080 及未知对象一律按 1080p 下限
    return str(value or "1080p")


def _is_concrete_historical(ev):
    """era/time_period/event 是否为「具体历史」（§56-57 判定 STRICT 的前提）。"""
    for key in ("era", "time_period", "event"):
        val = ev.get(key)
        if not val:
            continue
        s = str(val).strip()
        low = s.lower()
        if _HISTORIC_ERA_RE.search(low):
            return True
        for kw in _HISTORY_KEYWORDS:
            if kw in low:
                return True
    return False


def _authenticity_for(ev):
    """§56：历史事件 → STRICT；默认 PREFERRED。"""
    if _is_concrete_historical(ev):
        return "STRICT"
    return "PREFERRED"


def _fr_id(ev, seq=1):
    """FR-###：shot_id 为 ^S\\d{3}$ 时取 shot 序号（FR-###），否则确定性递增 FR-<seq>
    （F1/R5：FR-S### → FR-###，对齐 footage-request.schema.json ^FR-\\d{3}$；
    shot_id 字段在 build_request 输出中保留完整溯源，§54）。"""
    sid = _get(ev, "shot_id", "shotId") or ""
    if sid:
        m = re.fullmatch(r"S(\d{3})", str(sid).strip())
        if m:
            return f"FR-{m.group(1)}"
    return f"FR-{int(seq):03d}"


def _norm_search_budget(sb):
    """search_budget 归一化（§119）：candidate_limit 默认 8 / provider_limit 默认 3
    （F1/R5：缺省 ≥1，§119 禁止无限搜索）/ search_depth int→string（1→basic、
    2→standard、3→deep，映射表写死）；min_rank_score 默认 0.25 /
    min_semantic_relevance 默认 0.12（§118 相关性下限，可配置化，缺省值不变——
    FR-001/裁决）。"""
    if not isinstance(sb, dict):
        sb = {}
    depth = _norm_search_depth(_get(sb, "search_depth"), 1)
    return {
        "candidate_limit": int(_get(sb, "candidate_limit", default=8)),
        "provider_limit": int(_get(sb, "provider_limit", default=3)),
        "search_depth": SEARCH_DEPTH_STR.get(depth, "deep"),
        "min_rank_score": _num(_get(sb, "min_rank_score"), MIN_RANK_SCORE),
        "min_semantic_relevance": _num(_get(sb, "min_semantic_relevance"),
                                       MIN_SEMANTIC_RELEVANCE),
    }


def build_request(ev, editorial_direction=None):
    """从 EV（route=REAL_FOOTAGE）映射 Footage Request 字段（§54）。

    Args:
        ev: dict，含 shot_id/layer_id/purpose/subject/location/time_period/era/event/
            action/shot_type/camera/duration/audio_requirement/orientation/overlay_
            requirements/visual_requirements 等（Phase-6 §5 External Visual Request）。
        editorial_direction: dict|None，AUDIO_DIRECTION / b-roll 密度等编辑方向。

    Returns:
        dict：FR-### 全字段。authenticity_requirement 默认 PREFERRED，历史事件类 → STRICT，
        STRICT 时 provenance_requirements.required=true（§56-57）。输出对齐
        footage-request.schema.json 契约（F1/R5）：request_id=FR-###、minimum_resolution
        {w,h}、license_requirement 对象（顶层不再有 commercial_use/attribution_allowed
        展平键）、status=draft（后续由 search 等流转）、search_depth string、
        provenance_requirements {required,note}、overlay_requirements array of strings。
    """
    ev = ev or {}
    ed = editorial_direction or {}
    duration = _num(_get(ev, "duration", "duration_needed"), 0.0)
    duration = duration if duration > 0 else _num(_get(ed, "duration_needed"), 4.0)
    auth = _authenticity_for(ev)
    fr = {
        "request_id": _fr_id(ev),
        "shot_id": _get(ev, "shot_id") or "UNKNOWN",
        "layer_id": _get(ev, "layer_id") or "UNKNOWN",
        "purpose": _get(ev, "purpose", "visual_requirements", "visual_description") or "",
        "subject": _get(ev, "subject") or "",
        "location": _get(ev, "location", "environment") or "",
        "time_period": _get(ev, "time_period") or "",
        "era": _get(ev, "era") or "",
        "event": _get(ev, "event") or "",
        "action": _get(ev, "action") or "",
        "shot_type": _get(ev, "shot_type") or "b-roll",
        "camera": _get(ev, "camera", "camera_movement") or "",
        "duration_needed": round(duration, 3),
        "minimum_resolution": _min_resolution(ev),
        "minimum_fps": _get(ev, "minimum_fps") or 24,
        "orientation": _get(ev, "orientation") or "landscape",
        "style": _get(ev, "style", "mood") or "",
        "authenticity_requirement": auth,
        "license_requirement": _license_requirement(ev),
        "source_preferences": _get(ev, "source_preferences", "source_preferences") or [],
        "avoid": _get(ev, "avoid", "avoid_list") or [],
        "audio_requirement": _get(ev, "audio_requirement") or "",
        "overlay_requirements": _overlay_requirements(ev),
        "search_key": "",
        "search_budget": _norm_search_budget(_get(ev, "search_budget") or {}),
        "provenance_requirements": {
            "required": auth == "STRICT",
            "note": ("STRICT 历史请求：存档素材需记录 source institution / original page / "
                     "creator / date / retrieval date（§56-58）"
                     if auth == "STRICT" else "常规溯源记录：source/license/creator 随素材保留（§58）"),
        },
        "route": _get(ev, "route", "route") or "REAL_FOOTAGE",
        "editorial_direction_ref": (str(ed.get("source") or "")
                                    if isinstance(ed, dict) else ""),
        "status": "draft",
    }
    fr["search_key"] = build_search_key(fr)
    return fr


def build_search_key(fr):
    """相似请求 batch 合并用 search_key（§120）：subject+location 归一化。"""
    subject = re.sub(r"[^a-z0-9]+", " ", str(_get(fr, "subject") or "").lower()).strip()
    location = re.sub(r"[^a-z0-9]+", " ", str(_get(fr, "location") or "").lower()).strip()
    return f"{subject}|{location}"


def _build_query(fr):
    """query = subject + location + era 模板拼接（§59）。"""
    parts = [str(fr.get("subject") or "").strip(),
             str(fr.get("location") or "").strip(),
             str(fr.get("era") or "").strip()]
    return " ".join([p for p in parts if p]) or str(fr.get("shot_id") or "")


# ---------------------------------------------------------------------------
# search —— 经 Registry find（§59）+ 预算（§119）+ batch（§120）
# ---------------------------------------------------------------------------

def _enrich(candidate, registry_index=None, providers=None):
    """用 detail L1 补齐 license 全量 + type_specific.footage + provenance（§58/§60）。"""
    out = dict(candidate or {})
    rid = out.get("resource_id") or out.get("id") or ""
    detail = _registry_detail(rid, registry_index=registry_index) if rid else {}
    if detail:
        lic = detail.get("license")
        if isinstance(lic, dict):
            out["license_full"] = lic
        params = detail.get("parameters")
        if isinstance(params, dict) and params.get("footage") is not None:
            out["footage"] = params["footage"]
        if not out.get("description") and detail.get("description"):
            out["description"] = detail["description"]
        if not out.get("source_url"):
            out["source_url"] = detail.get("source_url") or ""
    out.setdefault("license_full", out.get("license") or {})
    out.setdefault("footage", {})
    out["provenance"] = build_provenance(out, providers=providers)
    return out


def build_provenance(candidate, providers=None):
    """Archive Provenance 块（§58）：source_institution/original_page/creator/date/
    description/license/retrieval_date；未知字段标 UNKNOWN，不编造。"""
    provs = providers if providers is not None else load_providers()
    pid = _get(candidate, "provider", "provider_id") or ""
    pname = provs.get(pid, {}).get("name") if provs.get(pid) else None
    lic = _get(candidate, "license_full", "license") or {}
    return {
        "source_institution": pname or "UNKNOWN",
        "original_page": _get(candidate, "source_url", "original_page") or "UNKNOWN",
        "creator": _get(candidate, "creator") or "UNKNOWN",
        "date": _get(candidate, "added_at", "date") or "UNKNOWN",
        "description": _get(candidate, "description", "summary") or "UNKNOWN",
        "license": lic.get("license_type") or "UNKNOWN",
        "retrieval_date": _get(candidate, "last_verified", "retrieval_date") or "UNKNOWN",
    }


def search(ft_request, registry_index=None):
    """经 Registry find 搜索 FOOTAGE 候选（§59/§119）。

    Args:
        ft_request: build_request 产物（含 search_budget / search_key / source_preferences）。
        registry_index: 可选，覆盖 Registry 索引目录路径。

    Returns:
        dict：{request_id, query, candidates:[...enriched...], image_fallback_candidates,
        budget_used, notes, route_optimization_proposal}。fetch 一律只产门禁记录，不真实下载。
    """
    fr = ft_request or {}
    budget = fr.get("search_budget") or {}
    candidate_limit = int(budget.get("candidate_limit") or 8)
    provider_limit = int(budget.get("provider_limit") or 0)
    search_depth = _norm_search_depth(budget.get("search_depth"), 1)
    query = _build_query(fr)
    provs = load_providers()
    notes = []
    providers_queried = []

    prefs = fr.get("source_preferences") or []
    if isinstance(prefs, str):
        prefs = [p.strip() for p in prefs.split(",") if p.strip()]
    if provider_limit > 0 and prefs:
        prefs = prefs[:provider_limit]

    results = []
    # 有 source_preferences 时按偏好 provider 逐个查询（provider_limit 封顶），否则单次全库查询
    if prefs:
        for pid in prefs:
            r = _registry_find(query, single_type="FOOTAGE", limit=candidate_limit,
                               provider=pid, registry_index=registry_index)
            providers_queried.append(pid)
            results.extend(r)
            if len(providers_queried) >= provider_limit:
                break
    else:
        results = _registry_find(query, single_type="FOOTAGE", limit=candidate_limit,
                                 registry_index=registry_index)
        providers_queried.append("all")

    # search_depth：首轮无果时逐步放宽查询（§118 broaden query），至多 depth 轮
    attempts = 1
    while not results and attempts < search_depth:
        attempts += 1
        broader = _broader_query(fr, attempts)
        if broader == query:
            break
        query = broader
        results = _registry_find(query, single_type="FOOTAGE", limit=candidate_limit,
                                 registry_index=registry_index)
        notes.append(f"首轮无命中，放宽为 {attempts} 轮：{query}（§118）")

    seen = set()
    uniq = []
    for r in results:
        rid = r.get("resource_id") or r.get("id") or ""
        if rid in seen:
            continue
        seen.add(rid)
        uniq.append(r)
    candidates = [_enrich(r, registry_index=registry_index, providers=provs) for r in uniq]
    if candidate_limit > 0:
        candidates = candidates[:candidate_limit]

    image_fallback = []
    if not candidates:
        # 无合格 footage 时备查 IMAGE 类候选（§77 still_fallback 前提）
        image_fallback = _registry_find(query, single_type="IMAGE", limit=candidate_limit,
                                        registry_index=registry_index)
        image_fallback = [_enrich(r, registry_index=registry_index, providers=provs)
                          for r in image_fallback]
        notes.append("FOOTAGE 无合格候选，已查 IMAGE 类作为 still_fallback 备选（§77）")

    proposal = None
    if _get(fr, "route") == "GENERATIVE_VIDEO" and candidates:
        proposal = _route_optimization_proposal(fr, query, candidates)

    return {
        "request_id": fr.get("request_id") or "FR-000",
        "query": query,
        "candidates": candidates,
        "image_fallback_candidates": image_fallback,
        "budget_used": {
            "candidate_limit": candidate_limit,
            "provider_limit": provider_limit,
            "search_depth": search_depth,
            "providers_queried": providers_queried,
            "attempts": attempts,
        },
        "notes": notes,
        "route_optimization_proposal": proposal,
    }


def _broader_query(fr, attempt):
    """§118 放宽策略（确定性）：第 2 轮去 era，第 3 轮只留 subject。"""
    if attempt == 2:
        parts = [str(fr.get("subject") or "").strip(),
                 str(fr.get("location") or "").strip()]
    elif attempt >= 3:
        parts = [str(fr.get("subject") or "").strip()]
    else:
        return _build_query(fr)
    return " ".join([p for p in parts if p]) or _build_query(fr)


def batch_search(ft_requests, registry_index=None):
    """§120：同 search_key 相似请求合并为一次 Registry 查询（subject+location 相同）。

    Args:
        ft_requests: list[dict]，多个 FR。
    Returns:
        list[dict]：每个 FR 一个结果（同 key 共享 candidates，避免重复查询）。
    """
    groups = {}
    for fr in ft_requests or []:
        key = build_search_key(fr)
        groups.setdefault(key, []).append(fr)
    out = []
    for key, frs in groups.items():
        primary = frs[0]
        result = search(primary, registry_index=registry_index)
        for fr in frs:
            merged = dict(result)
            merged["request_id"] = fr.get("request_id") or merged.get("request_id")
            merged["batched_with"] = [f.get("request_id") for f in frs if f.get("request_id")]
            out.append(merged)
    return out


# ---------------------------------------------------------------------------
# rank —— 10 因子加权（§61 / §74 / §60 why_it_fits）
# ---------------------------------------------------------------------------

def _factor_semantic_relevance(candidate, fr):
    """语义相关度：query token（subject/location/era/event/action/style）与候选文本重叠
    （0.6）＋ registry find score（0.4）。"""
    qtext = " ".join([str(fr.get(k) or "") for k in
                      ("subject", "location", "era", "event", "action", "style")])
    qt = _tokens(qtext)
    footage = candidate.get("footage") or {}
    ctext = " ".join([str(candidate.get("name") or ""),
                      str(candidate.get("summary") or ""),
                      " ".join(candidate.get("tags") or []),
                      str(candidate.get("description") or ""),
                      str(footage.get("subject") or ""),
                      str(footage.get("location") or ""),
                      str(footage.get("era") or "")])
    ct = _tokens(ctext)
    overlap = len(qt & ct) / len(qt) if qt else 0.0
    reg = min(1.0, _num(candidate.get("score"), 0.0))
    return round(0.6 * overlap + 0.4 * reg, 3)


def _era_matches(candidate, fr):
    """候选 era 与请求 era/time_period 是否匹配（STRICT 门槛，§56-57）。"""
    req_era = " ".join([str(fr.get("era") or ""), str(fr.get("time_period") or "")]).strip().lower()
    if not req_era:
        return None  # 请求无年代要求
    footage = candidate.get("footage") or {}
    cand_era = str(footage.get("era") or candidate.get("era") or "").lower()
    if not cand_era:
        return False
    rt = _tokens(req_era)
    ct = _tokens(cand_era)
    if rt & ct:
        return True
    # 数字年份（如 1969 vs 1960s）宽匹配
    rnums = set(re.findall(r"1[4-9]\d{2}|20[0-2]\d", req_era))
    cnums = set(re.findall(r"1[4-9]\d{2}|20[0-2]\d", cand_era))
    for rn in rnums:
        decade = rn[:3]
        for cn in cnums:
            if cn[:3] == decade:
                return True
    return False


def _factor_authenticity(candidate, fr):
    """真实性因子（§56-57）：STRICT 时 era 匹配为王；PREFERRED 时档案素材加分。"""
    footage = candidate.get("footage") or {}
    auth_str = str(footage.get("authenticity") or candidate.get("authenticity") or "").lower()
    arch = ("archiv" in auth_str) or ("real" in auth_str)
    em = _era_matches(candidate, fr)
    req = fr.get("authenticity_requirement") or "PREFERRED"
    if req == "STRICT":
        if em is True:
            return 1.0 if arch else 0.8
        if em is None:
            return 0.7
        return 0.0  # 不匹配：select 阶段剔除
    if req == "NOT_REQUIRED":
        return 0.6
    # PREFERRED
    if em is True:
        return 0.9 if arch else 0.75
    if em is False:
        return 0.5
    return 0.8 if arch else 0.55


def _resolution_score(res_text):
    """分辨率文本 -> 分数（1080p/4K/SD/UNKNOWN，确定性）。"""
    res = str(res_text or "").lower()
    if not res or res in ("unknown", "n/a"):
        return 0.5
    if any(k in res for k in _4K_TOKENS):
        return 1.0
    if "1080" in res or "full hd" in res or "fhd" in res:
        return 0.9
    if "720" in res or "hd" in res:
        return 0.7
    if "sd" in res or "480" in res or "576" in res:
        return 0.4
    return 0.5


def _factor_visual_quality(candidate, fr):
    """画质：分辨率 + verification CURRENT + 有预览。"""
    footage = candidate.get("footage") or {}
    res = footage.get("resolution") or candidate.get("resolution") or ""
    base = _resolution_score(res)
    ver = str(candidate.get("verification_status") or "").upper()
    if ver == "CURRENT":
        base += 0.15
    if (candidate.get("preview_type") or "") not in (None, "", "none"):
        base += 0.15
    return round(min(1.0, base), 3)


def _factor_camera_suitability(candidate, fr):
    """相机适配：请求 camera 词与候选描述/标签的关键字匹配。"""
    req_cam = str(fr.get("camera") or "").lower()
    ctext = " ".join([
        str(candidate.get("description") or ""),
        " ".join(candidate.get("tags") or []),
        str((candidate.get("footage") or {}).get("subject") or ""),
    ]).lower()
    if not req_cam:
        return 0.5  # 无要求 → 中性
    for kw in _CAMERA_POSITIVE:
        if kw in req_cam:
            return 1.0 if kw in ctext else 0.45
    return 0.5


def _factor_duration(candidate, fr):
    """时长：candidate >= duration_needed 可用；过短降分；未知中性。"""
    T = _num((candidate.get("footage") or {}).get("duration"), 0.0)
    D = _num(fr.get("duration_needed"), 4.0)
    if T <= 0:
        return 0.5
    if T < D:
        return 0.2  # 不足
    if D <= T <= D * 8:
        return 1.0
    return 0.85  # 过长需要裁剪区间（§71）


def _factor_resolution(candidate, fr):
    """分辨率门槛：>= minimum_resolution → 1.0。"""
    footage = candidate.get("footage") or {}
    res = footage.get("resolution") or candidate.get("resolution") or ""
    req = _resolution_label(fr.get("minimum_resolution")).lower()
    if not res:
        return 0.5
    rs, rr = _resolution_score(res), _resolution_score(req)
    if rs >= rr:
        return 1.0
    return 0.3


def _factor_license(candidate, fr):
    """License 因子（§62-63 硬门槛语义的软评分；硬门槛在 select 落地）。"""
    lic = candidate.get("license_full") or candidate.get("license") or {}
    commercial = lic.get("commercial_use")
    review = bool(lic.get("license_review_required"))
    if commercial is False:
        return 0.0
    if lic.get("license_type") == "UNKNOWN" or review:
        return 0.3
    score = 1.0
    if lic.get("attribution_required"):
        score = 0.9  # 需署名略降
    return score


def _visual_bible_style_tokens(vb):
    """Visual Bible -> 风格 token（确定性关键词）。"""
    if not isinstance(vb, dict):
        return []
    text = " ".join([
        str(vb.get("style") or ""),
        str(vb.get("style_name") or ""),
        str(vb.get("color") or ""),
        str(vb.get("color_direction") or ""),
        str(vb.get("tone") or ""),
    ]).lower()
    return list({t for t in re.findall(r"[a-z0-9]+", text)})


_ARCHIVAL_VB_TOKENS = ("desaturat", "monochrom", "archiv", "vintage", "retro",
                       "grain", "历史", "档案", "褪色", "黑白", "老")
_MODERN_VB_TOKENS = ("oversaturat", "vibrant", "modern", "saturated", "bright",
                     "饱和", "鲜艳", "现代", "高饱和")


def _vb_token_matches(token, stems):
    """VB token 与风格词干匹配（整词或前缀，避免 desaturated ⊃ saturated 误伤，§74）。"""
    t = str(token).lower()
    return any(t == s or t.startswith(s) for s in stems)


def _factor_visual_bible_fit(candidate, vb):
    """Visual Bible 匹配（§74 确定性属性匹配）：
    全片 desaturated archival vs oversaturated modern stock → 降分。"""
    if not vb:
        return 0.5
    tokens = _visual_bible_style_tokens(vb)
    if not tokens:
        return 0.5
    footage = candidate.get("footage") or {}
    arch = "archiv" in str(footage.get("authenticity") or "").lower()
    era = str(footage.get("era") or candidate.get("era") or "").lower()
    old = bool(re.search(r"1[4-9]\d{2}s?", era) or "archive" in era)
    cdesc = (str(candidate.get("description") or "") + " " + " ".join(candidate.get("style") or [])).lower()
    modern_stock = any(k in cdesc for k in ("modern stock", "stock footage", "oversaturat"))

    want_archival = any(_vb_token_matches(t, _ARCHIVAL_VB_TOKENS) for t in tokens)
    want_modern = any(_vb_token_matches(t, _MODERN_VB_TOKENS) for t in tokens)

    score = 0.5
    if want_archival:
        score += 0.3 if (arch or old) else -0.25
    if want_modern:
        score += 0.2 if modern_stock or (not arch and not old) else -0.2
    if not want_archival and not want_modern:
        score = 0.5
    return round(max(0.0, min(1.0, score)), 3)


def _factor_editability(candidate, fr):
    """可编辑性：水印 / 严重损伤 / 抖动手持 → 降分（§60 可编辑性）。"""
    text = " ".join([
        str(candidate.get("description") or ""),
        " ".join(candidate.get("tags") or []),
        str(candidate.get("summary") or ""),
    ]).lower()
    base = 0.7
    for t in _WATERMARK_TOKENS:
        if t in text:
            base -= 0.35
            break
    for t in _DEGRADE_TOKENS:
        if t in text:
            base -= 0.15
            break
    return round(max(0.0, min(1.0, base)), 3)


def _factor_download_cost(candidate, fr):
    """下载成本：estimated_size_bytes（越大越低）+ 4K/大文件 + 付费来源降权（§64）。"""
    size = 0.0
    est_bytes = _num(_get(candidate, "estimated_size_bytes"), 0.0)
    if est_bytes > 0:
        size = est_bytes
    else:
        size = _parse_size_text(candidate.get("estimated_fetch_size"))
    score = 0.5
    if size > 0:
        if size < 100 * 1024 * 1024:
            score = 1.0
        elif size < _LARGE_BYTES:
            score = 0.7
        else:
            score = 0.4
    res = str((candidate.get("footage") or {}).get("resolution") or "").lower()
    if any(k in res for k in _4K_TOKENS):
        score = min(score, 0.5)  # 4K 大文件 preview_first（§65）
    if source_tier_for(candidate) == "STOCK_PAID":
        score *= 0.4  # 付费默认排免费等价物之后（§64）
    return round(max(0.0, min(1.0, score)), 3)


def _parse_size_text(text):
    """'3.2 MB' / '1024 KB' 等文本 → bytes（确定性）。"""
    m = re.search(r"([\d.]+)\s*(KB|MB|GB)", str(text or ""), re.I)
    if not m:
        return 0.0
    n = _num(m.group(1), 0.0)
    unit = m.group(2).upper()
    return n * (1024 if unit == "KB" else 1024 ** 2 if unit == "MB" else 1024 ** 3)


def _why_it_fits(candidate, fr, factors, vb):
    """§60：每个候选一条 why_it_fits 解释（命中因子说明）。"""
    pts = []
    if factors.get("semantic_relevance", 0) >= 0.6:
        pts.append("语义命中")
    if factors.get("authenticity", 0) >= 0.8:
        pts.append("年代/真实性匹配")
    if factors.get("license", 0) >= 0.9:
        pts.append("授权可商用")
    elif factors.get("license", 0) < 0.4:
        pts.append("授权需复核")
    footage = candidate.get("footage") or {}
    if footage.get("resolution"):
        pts.append(f"{footage['resolution']}")
    if candidate.get("preview_url"):
        pts.append("有预览")
    if factors.get("visual_bible_fit", 0) >= 0.7:
        pts.append("符合视觉圣经")
    if factors.get("visual_bible_fit", 0) <= 0.3:
        pts.append("与视觉圣经冲突")
    tier = source_tier_for(candidate)
    pts.append(f"来源层级={tier}")
    prov = candidate.get("provider") or "?"
    return f"[{prov}] {candidate.get('name') or candidate.get('resource_id')}: " + "；".join(pts) if pts \
        else f"[{prov}] {candidate.get('name') or candidate.get('resource_id')}: 相关性一般"


def rank(candidates, ft_request, visual_bible=None):
    """10 因子加权排序（§61）。纯函数：输入候选列表 → 排序后列表。

    Args:
        candidates: search() 输出（已 enrich，含 license_full / footage / provenance）。
        ft_request: FR-###。
        visual_bible: dict|None，含 style/style_name/color_direction 等（§74）。

    Returns:
        list[dict]：每个候选附加 rank_score / factors / why_it_fits，按分降序。
    """
    fr = ft_request or {}
    out = []
    for c in candidates:
        factors = {
            "semantic_relevance": _factor_semantic_relevance(c, fr),
            "authenticity": _factor_authenticity(c, fr),
            "visual_quality": _factor_visual_quality(c, fr),
            "camera_suitability": _factor_camera_suitability(c, fr),
            "duration": _factor_duration(c, fr),
            "resolution": _factor_resolution(c, fr),
            "license": _factor_license(c, fr),
            "visual_bible_fit": _factor_visual_bible_fit(c, visual_bible),
            "editability": _factor_editability(c, fr),
            "download_cost": _factor_download_cost(c, fr),
        }
        total = sum(factors[k] * RANK_WEIGHTS[k] for k in RANK_WEIGHTS)
        # 付费候选默认排在免费等价物之后（§64）
        if source_tier_for(c) == "STOCK_PAID":
            total -= 0.15
        total = round(max(0.0, min(1.0, total)), 3)
        row = dict(c)
        row["rank_score"] = total
        row["factors"] = factors
        row["why_it_fits"] = _why_it_fits(c, fr, factors, visual_bible)
        out.append(row)
    out.sort(key=lambda r: (-r["rank_score"], r.get("resource_id") or ""))
    return out


# ---------------------------------------------------------------------------
# select —— License 硬门槛（§62-63）+ 付费门禁（§64）+ STRICT 真实性（§56-57）
# ---------------------------------------------------------------------------

def _license_gate_check(candidate):
    """单候选 License 硬门槛（§62-63）：缺 commercial_use/derivatives/redistribution
    任一信息 → commercial_safe=false + LICENSE_REVIEW_REQUIRED；绝不把未知授权标为可商用。"""
    lic = candidate.get("license_full") or candidate.get("license") or {}
    missing = [k for k in ("commercial_use", "derivatives_allowed", "redistribution_allowed")
               if k not in lic or lic.get(k) is None]
    commercial = lic.get("commercial_use")
    unknown = (lic.get("license_type") in (None, "", "UNKNOWN")) or bool(lic.get("license_review_required"))
    safe = commercial is True and not missing and not unknown
    flag = None
    if not safe:
        flag = "LICENSE_REVIEW_REQUIRED"
    return {
        "resource_id": candidate.get("resource_id") or candidate.get("id") or "",
        "license_type": lic.get("license_type") or "UNKNOWN",
        "commercial_use": commercial,
        "missing_fields": missing,
        "commercial_safe": safe,
        "flag": flag,
        "notes": "来源/授权必须保留（news/copyright 敏感内容 preserve source+license+flag，§63）",
    }


def _is_paid_candidate(candidate):
    """付费候选判定：license_notes / license_type / provider 含付费关键字（数据驱动）。"""
    lic = candidate.get("license_full") or candidate.get("license") or {}
    text = " ".join([str(lic.get("license_notes") or ""),
                     str(lic.get("license_type") or ""),
                     str(candidate.get("notes") or "")]).lower()
    for t in _PAID_TOKENS:
        if t in text:
            return True
    return False


def _is_large_candidate(candidate):
    """>500MB 或 4K → 大文件（§65 preview_first）。"""
    size = _num(_get(candidate, "estimated_size_bytes"), 0.0)
    res = str((candidate.get("footage") or {}).get("resolution") or "").lower()
    if size > _LARGE_BYTES:
        return True
    if any(k in res for k in _4K_TOKENS):
        return True
    return False


def _authenticity_gate(candidate, fr):
    """STRICT 请求 → 候选必须 era/time_period 匹配 + 来源机构明确，否则剔除并记 reason（§56-57）。"""
    if (fr.get("authenticity_requirement") or "PREFERRED") != "STRICT":
        return True, ""
    em = _era_matches(candidate, fr)
    if em is not True:
        return False, f"STRICT 历史请求剔除 {candidate.get('resource_id')}：era/time_period 不匹配（§56）"
    prov = candidate.get("provenance") or {}
    inst = prov.get("source_institution")
    if not inst or inst == "UNKNOWN":
        return False, f"STRICT 历史请求剔除 {candidate.get('resource_id')}：来源机构不明确（§57）"
    return True, ""


def select(ranked, ft_request, approvals=None):
    """从排序候选中选择（§60/§62-64/§65-66）。

    Args:
        ranked: rank() 输出（按 rank_score 降序）。
        ft_request: FR-###。
        approvals: dict，已获批准的 gate 集合（如 {"paid_stock": True,
            "large_download": True, "license_review": True, "route_change": True}）。

    Returns:
        dict：{request_id, selected|None, license_gate, approval_required, proposal, notes}。
        selected 为 None 时 notes 说明原因（无合格 / 审批未过 / 已建议 still_fallback）。
    """
    fr = ft_request or {}
    approvals = approvals or {}
    notes = []
    gate_issues = []
    overall_safe = True

    for c in ranked:
        lg = _license_gate_check(c)
        if not lg["commercial_safe"]:
            overall_safe = False
            gate_issues.append(lg)

    # STRICT 真实性过滤（§56-57）
    kept = []
    for c in ranked:
        ok, reason = _authenticity_gate(c, fr)
        if ok:
            kept.append(c)
        else:
            notes.append(reason)

    selected = None
    approval_required = []
    # 相关性下限可配置（§118）：search_budget.min_rank_score / min_semantic_relevance，
    # 缺省用模块常量（MIN_RANK_SCORE=0.25 / MIN_SEMANTIC_RELEVANCE=0.12，FR-001）。
    _budget = fr.get("search_budget") or {}
    min_rank_score = _num(_budget.get("min_rank_score"), MIN_RANK_SCORE)
    min_semantic_relevance = _num(_budget.get("min_semantic_relevance"),
                                  MIN_SEMANTIC_RELEVANCE)
    for c in kept:
        # 相关性下限：低于下限视为无合格 footage（§118），后续更低分候选同样不取
        score = float(c.get("rank_score") or 0.0)
        sem = float((c.get("factors") or {}).get("semantic_relevance") or 0.0)
        if score < min_rank_score or sem < min_semantic_relevance:
            notes.append(f"{c.get('resource_id')} 相关性不足（rank_score={score:.2f} "
                         f"semantic={sem:.2f}），视为无合格 footage（§118，阈值 "
                         f"rank>={min_rank_score:.2f}/sem>={min_semantic_relevance:.2f}）")
            break
        lic = c.get("license_full") or c.get("license") or {}
        needs = []
        paid = _is_paid_candidate(c)
        large = _is_large_candidate(c)
        unknown_lic = lic.get("license_type") in (None, "", "UNKNOWN") or bool(lic.get("license_review_required"))
        if paid:
            needs.append("paid_stock")
        if large:
            needs.append("large_download")
        if unknown_lic:
            needs.append("license_review")
        blocked = [g for g in needs if not approvals.get(g)]
        if blocked:
            approval_required.append({
                "gate": ",".join(blocked),
                "resource_id": c.get("resource_id") or c.get("id") or "",
                "kind": "footage_selection",
                "details": _approval_details(c, ranked, fr),
            })
            notes.append(f"{c.get('resource_id')} 需审批 {blocked} 未批准，跳过（§64/§111）")
            continue
        selected = c
        break

    proposal = None
    if selected is None and _get(fr, "route") == "REAL_FOOTAGE":
        proposal = _fallback_proposal(fr, ranked)

    return {
        "request_id": fr.get("request_id") or "FR-000",
        "selected": selected,
        "license_gate": {
            "commercial_safe": overall_safe,
            "flag": None if overall_safe else "LICENSE_REVIEW_REQUIRED",
            "issues": gate_issues,
            "note": "未知授权绝不标为可商用（§62-63）",
        },
        "approval_required": approval_required,
        "proposal": proposal,
        "notes": notes,
    }


def _approval_details(candidate, ranked, fr):
    """§64 付费门禁细节：{price, license_type, why_recommended, free_alternatives}。"""
    lic = candidate.get("license_full") or candidate.get("license") or {}
    paid = _is_paid_candidate(candidate)
    free_alts = []
    for r in ranked:
        if r.get("resource_id") == candidate.get("resource_id"):
            continue
        if not _is_paid_candidate(r):
            free_alts.append({
                "resource_id": r.get("resource_id"),
                "name": r.get("name"),
                "rank_score": r.get("rank_score"),
                "source_url": r.get("source_url"),
            })
    return {
        "price": _get(candidate, "price", "estimated_price") or "UNKNOWN",
        "license_type": lic.get("license_type") or "UNKNOWN",
        "why_recommended": candidate.get("why_it_fits") or "",
        "free_alternatives": free_alts[:5],
        "paid": paid,
        "large": _is_large_candidate(candidate),
        "preview": candidate.get("preview_url") or "",
        "preview_first_note": "preview→selection→download，禁止批量下载（§65-66）" if _is_large_candidate(candidate) else "",
    }


def _fallback_proposal(fr, ranked):
    """无合格 footage：FOOTAGE_ALTERNATIVE: IMAGE + JY_NATIVE/REMOTION 提案（§77），
    或建议 GENERATIVE_VIDEO（§79）——只提案不改路由，approval_required=true。"""
    sid = str(fr.get("shot_id") or "000")
    if ranked:
        top = ranked[0]
        return {
            "proposal_id": f"RO-{sid}",
            "kind": "FOOTAGE_ALTERNATIVE",
            "current": "REAL_FOOTAGE",
            "found": {
                "reason": "无合格 footage 候选（全部被 License/真实性门槛或审批拦截）",
                "top_candidate": top.get("resource_id") if isinstance(top, dict) else None,
            },
            "recommendation": "IMAGE + JY_NATIVE/REMOTION（§77 still_fallback，仅提案）",
            "evidence": [n for n in (fr.get("request_id"),) if n],
            "approval_required": True,
        }
    return {
        "proposal_id": f"RO-{sid}",
        "kind": "ROUTE_OPTIMIZATION",
        "current": "REAL_FOOTAGE",
        "found": {"reason": "Registry 无任何 FOOTAGE/IMAGE 候选"},
        "recommendation": "GENERATIVE_VIDEO（§79 反向提案，仅提案不改路由）",
        "evidence": [],
        "approval_required": True,
    }


def _route_optimization_proposal(fr, query, candidates):
    """§78：GENERATIVE_VIDEO shot 经搜索发现更优真实素材 → ROUTE_OPTIMIZATION_PROPOSAL(RO-###)。
    只提案不改路由。"""
    sid = str(fr.get("shot_id") or "000")
    best = candidates[0] if candidates else None
    return {
        "proposal_id": f"RO-{sid}",
        "kind": "ROUTE_OPTIMIZATION",
        "current": "GENERATIVE_VIDEO",
        "found": {
            "query": query,
            "top_candidate": (best or {}).get("resource_id"),
            "evidence": (best or {}).get("why_matched") or (best or {}).get("summary") or "",
        },
        "recommendation": "Switch to REAL_FOOTAGE（真实素材更优，§78）",
        "approval_required": True,
    }


def route_optimization(ev, ft_request, search_result, current_route):
    """§78-79 双向 Route Optimization Proposal（只提案，不改路由）。

    Args:
        ev: 原 EV（含 allow_generative_fallback 等）。
        ft_request: FR-###。
        search_result: search() 输出。
        current_route: 当前路由（GENERATIVE_VIDEO / REAL_FOOTAGE）。

    Returns:
        dict|None：RO-### 提案（approval_required=true）或 None。
    """
    fr = ft_request or {}
    sr = search_result or {}
    candidates = sr.get("candidates") or []
    sid = str(fr.get("shot_id") or "000")

    if current_route == "GENERATIVE_VIDEO":
        if candidates:
            return _route_optimization_proposal(fr, sr.get("query") or "", candidates)
        return None

    if current_route == "REAL_FOOTAGE":
        allowed = bool(_get(ev, "allow_generative_fallback", default=True))
        if not candidates and not (sr.get("image_fallback_candidates") or []) and allowed:
            return {
                "proposal_id": f"RO-{sid}",
                "kind": "ROUTE_OPTIMIZATION",
                "current": "REAL_FOOTAGE",
                "found": {"reason": "Registry 无任何可用 FOOTAGE 候选（含 IMAGE fallback）"},
                "recommendation": "GENERATIVE_VIDEO（§79，仅提案）",
                "evidence": sr.get("notes") or [],
                "approval_required": True,
            }
    return None


# ---------------------------------------------------------------------------
# plan_use —— 可用区间（§71）+ Timeline Hint（§72）+ Treatment（§75-76）+
# Mask/Tracking（§81）+ Stabilization（§82）+ Audio（§83）+ B-roll 密度（§73）
# ---------------------------------------------------------------------------

def _range_for(fr, candidate):
    """§71：由 duration_needed 与候选 duration 确定性推导 recommended_in/out。

    规则：素材不足 → 整段；素材充足 → 从 30% 处取 D 秒窗口（避开片头 slate/淡入），
    越界则回退到末尾。示例：30s 素材 / 4s 需求 → in=00:09.0 out=00:13.0。
    """
    D = max(0.0, _num(fr.get("duration_needed"), 4.0))
    T = _num((candidate.get("footage") or {}).get("duration"), 0.0)
    if T <= 0:
        return {"recommended_in": 0.0, "recommended_out": D, "basis": "duration UNKNOWN，按需求长度"}
    if T <= D * 1.05:
        return {"recommended_in": 0.0, "recommended_out": T, "basis": "素材不足/接近，整段使用"}
    start = T * 0.3
    if start + D > T:
        start = max(0.0, T - D)
    return {"recommended_in": round(start, 3), "recommended_out": round(start + D, 3),
            "basis": "从素材 30% 处取需求长度窗口（§71）"}


def _audio_behavior(fr, editorial_direction=None):
    """§83：依据 AUDIO_DIRECTION 或 ev.audio_requirement 映射
    KEEP/MUTE/USE_AS_AMBIENCE/EXTRACT/REPLACE；默认 MUTE（真实素材原声不默认直接进时间线）。"""
    candidates = [
        _get(fr, "audio_requirement", "audio_behavior"),
        _get(fr, "audio", default=None),
    ]
    ed = editorial_direction or {}
    for key in ("AUDIO_DIRECTION", "audio_direction", "audio"):
        v = ed.get(key)
        if v is not None:
            candidates.append(v)
    for src in candidates:
        if isinstance(src, dict):
            for k in ("footage_audio", "original_audio", "behavior", "mode"):
                if src.get(k):
                    candidates.append(src[k])
        elif isinstance(src, str):
            s = src.strip().upper()
            m = _norm(s, AUDIO_BEHAVIORS)
            if m:
                return m
            if "MUTE" in s:
                return "MUTE"
            if "AMBIENCE" in s or "AMB" in s:
                return "USE_AS_AMBIENCE"
            if "EXTRACT" in s:
                return "EXTRACT"
            if "REPLACE" in s:
                return "REPLACE"
            if "KEEP" in s:
                return "KEEP"
    return "MUTE"


def _b_roll_density(editorial_direction, duration_needed, cuts_proposed=1):
    """§73：读取 editorial_direction 的密度约束 → 合规检查。

    支持结构字段 max_cuts_per_minute / (max_cuts_per_window + window_seconds)，
    以及自由文本「每 N 秒最多 M 个」「不逐句换画面」。
    """
    ed = editorial_direction or {}
    rule = None
    rule_text = ""
    for k in ("max_cuts_per_minute", "b_roll_max_cuts_per_minute"):
        if isinstance(ed.get(k), (int, float)):
            rule = {"type": "per_minute", "max": float(ed[k]), "window": 60.0,
                    "source": k}
    if ed.get("max_cuts_per_window") is not None and ed.get("window_seconds") is not None:
        rule = {"type": "per_window", "max": float(ed["max_cuts_per_window"]),
                "window": float(ed["window_seconds"]), "source": "max_cuts_per_window"}
    for k in ("b_roll_density", "b_roll", "density_rule", "editorial_rule"):
        v = ed.get(k)
        if isinstance(v, str):
            rule_text += " " + v
    m = re.search(r"每\s*(\d+(?:\.\d+)?)\s*秒最多\s*(\d+)\s*个", rule_text)
    if m:
        rule = {"type": "per_window", "max": float(m.group(2)), "window": float(m.group(1)),
                "source": "free_text:每N秒最多M个"}
    if rule is None:
        if "不逐句换画面" in rule_text or "not per sentence" in rule_text.lower():
            rule = {"type": "per_window", "max": 1.0, "window": 999999.0,
                    "source": "free_text:不逐句换画面"}
        else:
            rule = {"type": "per_minute", "max": float(DEFAULT_B_ROLL_PER_MINUTE),
                    "window": 60.0, "source": "default"}

    D = max(0.0, _num(duration_needed, 4.0))
    rtype = rule["type"]
    if rtype == "per_minute":
        allowed = (D * rule["max"]) / rule["window"]
    else:
        if D <= rule["window"]:
            allowed = rule["max"]
        else:
            allowed = (D / rule["window"]) * rule["max"] + rule["max"]
    compliant = cuts_proposed <= max(1.0, allowed)
    return {
        "rule": rule,
        "duration_needed": round(D, 3),
        "cuts_proposed": cuts_proposed,
        "allowed_cuts_estimate": round(max(0.0, allowed), 3),
        "compliant": bool(compliant),
        "note": "合规" if compliant else "超出 b-roll 密度约束，建议合并/删减（§73）",
    }


def _treatment_plan(fr, candidate, archival):
    """§75-76 treatment_plan + archive 处理（只规划，不实现）。"""
    footage = candidate.get("footage") or {}
    orientation = str(fr.get("orientation") or "landscape").lower()
    res = str(footage.get("resolution") or "").lower()
    preferred_crop = "none"
    if orientation in ("portrait", "vertical", "9:16"):
        preferred_crop = "9:16 center crop"
    elif orientation in ("square", "1:1"):
        preferred_crop = "1:1 center crop"
    plan = {
        "crop": preferred_crop,
        "reframe": "none",
        "color_treatment": "as-is（Phase 6 不做最终 Grade，§48）",
        "grain": "preserve" if archival else "none",
        "blur": "none",
        "speed": 1.0,
        "mask": "none",
        "overlay": str(fr.get("overlay_requirements") or "none"),
    }
    archive_treatment = None
    if archival:
        letterbox = bool(re.search(r"(4:3|sd|480|576|720\b)", res) or not res)
        archive_treatment = {
            "grain_preserve": True,
            "letterbox": letterbox,
            "caption": True,
            "date_label": str(footage.get("era") or candidate.get("era") or "UNKNOWN"),
            "ken_burns": "subtle（仅规划，§76）",
            "note": "由 JianYing / Remotion 实现（§76），Phase 6 只规划不实现",
        }
    return {"treatment_plan": plan, "archive_treatment": archive_treatment}


def _stabilization(candidate):
    """§82：素材含手持/抖动描述 → stabilization 规划 true。"""
    text = " ".join([
        str(candidate.get("description") or ""),
        str(candidate.get("summary") or ""),
    ]).lower()
    for t in ("handheld", "shaky", "shake", "抖动", "手持"):
        if t in text:
            return True
    return False


def plan_use(selected, ft_request, adjacent_shots=None, editorial_direction=None):
    """生成素材使用计划（§71-76 / §81-83 / §73）。

    Args:
        selected: select() 的 selected 候选（含 license_full/footage/provenance）。
        ft_request: FR-###。
        adjacent_shots: list|None，相邻镜头（用于 camera 方向 / 复用判断）。
        editorial_direction: dict|None，AUDIO_DIRECTION / b-roll 密度。

    Returns:
        dict：{request_id, recommended_in/out, timeline_hint, treatment_plan,
        archive_treatment, masking_tracking, stabilization, audio_behavior,
        b_roll_density, reuse, still_fallback, route_optimization_proposal, notes}。
    """
    fr = ft_request or {}
    if not selected:
        return {
            "request_id": fr.get("request_id") or "FR-000",
            "selected": None,
            "recommended_in": None,
            "recommended_out": None,
            "timeline_hint": None,
            "treatment_plan": None,
            "archive_treatment": None,
            "masking_tracking": None,
            "stabilization": None,
            "audio_behavior": _audio_behavior(fr, editorial_direction),
            "b_roll_density": _b_roll_density(editorial_direction, fr.get("duration_needed")),
            "reuse": None,
            "still_fallback": None,
            "route_optimization_proposal": None,
            "notes": ["未选中素材，无使用计划（§118 建议放宽搜索 / 图片 fallback / AI 生成提案）"],
        }

    footage = selected.get("footage") or {}
    arch = "archiv" in str(footage.get("authenticity") or "").lower()
    rng = _range_for(fr, selected)
    r_in, r_out = rng["recommended_in"], rng["recommended_out"]
    D = max(0.0, _num(fr.get("duration_needed"), r_out - r_in))

    timeline_hint = {
        "suggested_duration": round(D, 3),
        "preferred_crop": "9:16 center crop" if str(fr.get("orientation") or "landscape").lower() in ("portrait", "vertical", "9:16") else "16:9 full",
        "speed": 1.0,
        "in": _fmt_ts(r_in),
        "out": _fmt_ts(r_out),
        "track": _get(fr, "preferred_track", "track", default="V1"),
        "overlay_safe_area": _get(fr, "overlay_requirements") or "none",
    }

    tp = _treatment_plan(fr, selected, arch)

    # §81 masking/tracking 只记不实现：overlay 存在且素材有运镜时建议 tracking
    tracking_needed = False
    if timeline_hint["overlay_safe_area"] not in (None, "", "none"):
        cam_text = (str(fr.get("camera") or "") + " " +
                    str(selected.get("description") or "")).lower()
        tracking_needed = any(k in cam_text for k in _CAMERA_POSITIVE)
    masking_tracking = {
        "tracking_needed": tracking_needed,
        "mask_needed": False,
        "rotoscope_needed": False,
        "note": "仅规划标记，不实现 Tracking/Mask 引擎（§81）",
    }

    return {
        "request_id": fr.get("request_id") or "FR-000",
        "selected": selected.get("resource_id") or selected.get("id"),
        "recommended_in": r_in,
        "recommended_out": r_out,
        "range_basis": rng["basis"],
        "timeline_hint": timeline_hint,
        "treatment_plan": tp["treatment_plan"],
        "archive_treatment": tp["archive_treatment"],
        "masking_tracking": masking_tracking,
        "stabilization": _stabilization(selected),
        "audio_behavior": _audio_behavior(fr, editorial_direction),
        "b_roll_density": _b_roll_density(editorial_direction, fr.get("duration_needed")),
        "reuse": check_reuse(selected.get("resource_id") or "", _get(fr, "prior_uses") or []),
        "still_fallback": _get(fr, "image_fallback_candidates") or None,
        "route_optimization_proposal": None,
        "notes": ["License/Provenance 已随 selected 保留（§58/§63）"],
    }


# ---------------------------------------------------------------------------
# reuse（§121）+ 路由提案辅助
# ---------------------------------------------------------------------------

def check_reuse(resource_id, prior_uses):
    """§121：同一 footage 复用计数；超过 2 处明显重复 → note 提醒。

    Args:
        resource_id: 候选 resource_id。
        prior_uses: list[str] 或 dict{resource_id: count}（既有使用记录）。
    """
    if isinstance(prior_uses, dict):
        count = int(prior_uses.get(resource_id, 0)) + 1
    else:
        prior = list(prior_uses or [])
        count = sum(1 for u in prior if u == resource_id) + 1
    note = None
    if count > 2:
        note = f"{resource_id} 已在 {count - 1} 处使用，本次为第 {count} 处——明显重复，提醒复用（§121）"
    return {"resource_id": resource_id, "usage_count": count,
            "note": note or f"{resource_id} 复用计数 {count}（≤2，可接受）"}


# ---------------------------------------------------------------------------
# CLI：python3 -m modules.external-visual.footage <build|search|rank|select|plan> ...
# ---------------------------------------------------------------------------

def _load_json_arg(value):
    """CLI 参数：'{"..."}' 内联 JSON 或文件路径 → dict/list。"""
    s = str(value).strip()
    if s.startswith(("{", "[")):
        return json.loads(s)
    return json.loads(Path(s).read_text(encoding="utf-8"))


def build_cli():
    ap = argparse.ArgumentParser(
        prog="python -m modules.external-visual.footage",
        description="ZHOU_Videodirector Phase 6 Real Footage Pipeline (P6-03).",
    )
    ap.add_argument("--selftest", action="store_true",
                    help="run built-in smoke selftest")
    sub = ap.add_subparsers(dest="command")

    p = sub.add_parser("build", help="EV(route=REAL_FOOTAGE) → FR-###（§54/§56-57）")
    p.add_argument("--ev", default="{}", help="EV JSON 或文件路径")
    p.add_argument("--editorial", default="{}", help="editorial_direction JSON 或文件路径")

    p = sub.add_parser("search", help="经 Registry find 搜索 FOOTAGE 候选（§59/§119）")
    p.add_argument("--request", required=True, help="FR JSON 或文件路径")
    p.add_argument("--index", default=None, help="Registry 索引目录（可选，覆盖）")

    p = sub.add_parser("rank", help="10 因子加权排序（§61/§74）")
    p.add_argument("--request", required=True, help="FR JSON 或文件路径")
    p.add_argument("--candidates", required=True, help="candidates JSON 或文件路径（search 输出或候选列表）")
    p.add_argument("--bible", default=None, help="visual_bible JSON 或文件路径（可选）")

    p = sub.add_parser("select", help="License 硬门槛 + 审批（§62-64）")
    p.add_argument("--request", required=True, help="FR JSON 或文件路径")
    p.add_argument("--ranked", required=True, help="ranked candidates JSON 或文件路径")
    p.add_argument("--approvals", default="{}", help="已批准 gate JSON（可选）")

    p = sub.add_parser("plan", help="可用区间 + Timeline Hint + Treatment（§71-76）")
    p.add_argument("--request", required=True, help="FR JSON 或文件路径")
    p.add_argument("--selected", required=True, help="selected candidate JSON 或文件路径")
    p.add_argument("--adjacent", default=None, help="adjacent_shots JSON（可选）")
    p.add_argument("--editorial", default="{}", help="editorial_direction JSON 或文件路径")
    return ap


def _cmd_build(args):
    ev = _load_json_arg(args.ev)
    ed = _load_json_arg(args.editorial)
    print(json.dumps(build_request(ev, ed), ensure_ascii=False, indent=2))


def _cmd_search(args):
    fr = _load_json_arg(args.request)
    out = search(fr, registry_index=args.index)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


def _cmd_rank(args):
    fr = _load_json_arg(args.request)
    cand = _load_json_arg(args.candidates)
    if isinstance(cand, dict) and "candidates" in cand:
        cand = cand["candidates"]
    bible = _load_json_arg(args.bible) if args.bible else None
    print(json.dumps(rank(cand, fr, bible), ensure_ascii=False, indent=2, default=str))


def _cmd_select(args):
    fr = _load_json_arg(args.request)
    ranked = _load_json_arg(args.ranked)
    if isinstance(ranked, dict) and "ranked" in ranked:
        ranked = ranked["ranked"]
    approvals = _load_json_arg(args.approvals)
    print(json.dumps(select(ranked, fr, approvals), ensure_ascii=False, indent=2, default=str))


def _cmd_plan(args):
    fr = _load_json_arg(args.request)
    sel = _load_json_arg(args.selected)
    if isinstance(sel, list):
        sel = sel[0] if sel else None
    if isinstance(sel, dict) and "selected" in sel and "license_gate" in sel:
        # select() 输出直接传入时解包 selected 候选
        sel = sel.get("selected")
    adj = _load_json_arg(args.adjacent) if args.adjacent else None
    ed = _load_json_arg(args.editorial)
    print(json.dumps(plan_use(sel, fr, adj, ed), ensure_ascii=False, indent=2, default=str))


def _selftest():
    """内置冒烟（不改库）：验证主链路可跑通。"""
    ev = {"shot_id": "S030", "route": "REAL_FOOTAGE", "subject": "city street",
          "location": "San Francisco", "era": "1906", "event": "post-earthquake",
          "duration": 4.0, "audio_requirement": "MUTE"}
    fr = build_request(ev)
    assert fr["authenticity_requirement"] == "STRICT", fr
    assert fr["provenance_requirements"]["required"] is True, fr
    assert fr["search_key"], fr
    res = search(fr)
    assert "candidates" in res and "budget_used" in res, res.keys()
    ranked = rank(res["candidates"], fr, {"style": "desaturated archival"})
    for r in ranked:
        assert "rank_score" in r and "factors" in r and "why_it_fits" in r
    sel = select(ranked, fr, {"paid_stock": True, "large_download": True})
    assert "selected" in sel and "license_gate" in sel and "approval_required" in sel
    plan = plan_use(sel["selected"], fr, None, {"AUDIO_DIRECTION": "MUTE"}) if sel["selected"] else None
    print("footage selftest OK (FR:", fr["request_id"], "auth:", fr["authenticity_requirement"],
          "candidates:", len(res["candidates"]), ")")
    return 0


def main(argv=None):
    args = build_cli().parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.command:
        build_cli().print_help()
        return 2
    if args.command == "build":
        _cmd_build(args)
    elif args.command == "search":
        _cmd_search(args)
    elif args.command == "rank":
        _cmd_rank(args)
    elif args.command == "select":
        _cmd_select(args)
    elif args.command == "plan":
        _cmd_plan(args)
    else:
        build_cli().print_help()
        return 2
    return 0


__all__ = [
    "build_request", "search", "batch_search", "rank", "select", "plan_use",
    "route_optimization", "check_reuse", "build_search_key", "build_provenance",
    "source_tier_for", "AUTHENTICITY_REQUIREMENTS", "AUDIO_BEHAVIORS",
    "SOURCE_TIERS", "DEFAULT_SOURCE_PRIORITY", "RANK_WEIGHTS",
]

if __name__ == "__main__":
    sys.exit(main())
