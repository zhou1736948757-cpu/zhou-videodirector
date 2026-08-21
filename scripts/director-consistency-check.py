#!/usr/bin/env python3
"""director-consistency-check.py - ZHOU_Videodirector Phase 2 Director Consistency Check（P2-7）.

对已生成 Storyboard 的项目目录执行 Phase-2 Prompt §64 的 9 项导演一致性检查，并在存在
参考素材时执行 §65 Reference Influence Check。量化验证 Scene/Shot 与 Creative / Visual /
Audio / Editorial 四份方向文档的一致性，以及 Hero Effect 密度、Motion 多样性、Audio
过载与 Editability 覆盖率等结构指标（量化结果供 STORYBOARD_REVIEW 提交摘要的 pre-result
字段使用，见 workflows/storyboard.md §64）。

预期项目结构（<project_dir>/）:
    PROJECT_BRIEF.md       必备：项目名与目标时长
    REFERENCE_ANALYSIS.md  可选：参考分析（reusable_rules 供 §65 检查）
    CREATIVE_DIRECTION.md  必备：Core Idea / Hook / Payoff（check 01 真源）
    VISUAL_BIBLE.md        必备：视觉系统关键词与 Avoid List（check 02 真源）
    AUDIO_DIRECTION.md     必备：Music Route / Ducking / Hero Sound Policy（check 03 真源）
    STORY_BEAT_MAP.md      必备：Beat 节奏表（check 04 时间真源）
    STORYBOARD.md          必备：分镜总表（STORYBOARD_REVIEW 提交载体）
    scenes/*.json          必备：场景对象（或对象数组，对齐 templates/scene.scene.json）
    shots/*.json           必备：镜头对象（或对象数组，对齐 templates/shot.shot.json）
    audio/                 可选：音频素材清单
    references/            可选：参考素材（非空时启用 §65 检查）

用法:
    python3 scripts/director-consistency-check.py <project_dir>          # 人类可读报告
    python3 scripts/director-consistency-check.py <project_dir> --json   # 机器可读 JSON
    python3 scripts/director-consistency-check.py --selftest             # 内置自检（临时目录）

退出码: 0 = 无 FAIL（pass/warn/na 均可）; 1 = 存在 FAIL; 2 = 致命错误（缺必备文件）。

技术约束: Python 3 stdlib only；LF 行尾；不修改 schemas 与其它 Phase 文件。
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
# 常量
# ---------------------------------------------------------------------------

REQUIRED_FILES = [
    "PROJECT_BRIEF.md",
    "CREATIVE_DIRECTION.md",
    "VISUAL_BIBLE.md",
    "AUDIO_DIRECTION.md",
    "STORY_BEAT_MAP.md",
    "STORYBOARD.md",
]

# check 01：CREATIVE_DIRECTION 中必须被 Scene/Shot 服务的创意锚点
CREATIVE_IDEA_FIELDS = ("Core Idea", "Hook", "Payoff")

# check 02：VISUAL_BIBLE 中抽取视觉关键词的字段
VISUAL_KEY_FIELDS = (
    "Style Name",
    "Style Mix",
    "Design Philosophy",
    "Color System",
    "Typography",
    "Composition",
    "Spacing",
    "Grid",
    "Depth",
    "Material",
    "Lighting",
    "Camera Language",
    "Motion Character",
    "Motion Intensity",
    "Micro-motion",
    "Transition Language",
    "Subtitle Style",
    "Graphic Elements",
    "Texture · Grain",
    "Level 1 — Invisible（大量）",
    "Level 2 — Narrative（按需）",
    "Level 3 — Hero（极少量）",
    "Hero Effect Policy",
)
AVOID_FIELD = "Avoid List"

# check 03：AUDIO_DIRECTION 的解析字段
HERO_SOUND_FIELD = "Hero Sound Policy"
DUCKING_FIELD = "Ducking Strategy"
SILENCE_FIELD = "Silence Policy"
MUSIC_MODES = ("continue", "cue", "silence")
EDITABILITY_VALUES = ("HIGH", "LOW", "MEDIUM")

CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
# 中文停用字：出现在 2-gram 中即过滤，避免"的/在/并"类虚词 2-gram 产生假阳性
STOP_CJK = frozenset("的了是在不有和我你他她它这那让要会能与并或及为所把被从对於就也都很只可更且而于之其个们该则")
FIELD_LINE_RE = re.compile(r"^\s*[-*]\s*\*{0,2}\s*([^*:：\n]{1,60}?)\s*\*{0,2}\s*[：:]\s*(.+?)\s*$")
CHECKBOX_RE = re.compile(r"^\s*-\s*\[[ xX✓]\]")
MUSIC_ROUTE_RE = re.compile(r"^\s*-\s*\[[xX✓]\s*\]\s*`?([A-Z_]{2,})`?", re.M)
TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–—~～]\s*(\d{1,2}):(\d{2})")
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*s")
BEAT_ROW_RE = re.compile(r"^(Beat\s*\d+|Ch\.?\s*\d+|第\s*\d+\s*章)")
NEG_MARKERS = ("避免", "禁止", "不得", "不要", "不用", "勿", "avoid", "never", "no ")
EDITABILITY_RE = re.compile(r"(?i)(?:editability|等级)\s*[:：]\s*(high|low|medium)")


class FatalError(Exception):
    """致命错误：缺必备文件 / 目录缺失 / JSON 无法解析（退出码 2）。"""


@dataclasses.dataclass
class CheckResult:
    id: str
    name: str
    status: str  # pass | fail | warn | na
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
class Context:
    project_dir: Path
    project_name: str
    brief_text: str
    creative_text: str
    visual_text: str
    audio_text: str
    beat_text: str
    storyboard_text: str
    ref_text: str
    has_refs: bool
    scenes: list
    shots: list


# ---------------------------------------------------------------------------
# 文本 / 解析辅助
# ---------------------------------------------------------------------------

def cjk_bigrams(text: str) -> set:
    """中文 2-gram 关键词集合（过滤含停用字的 bigram）。"""
    out = set()
    for run in CJK_RUN_RE.findall(text or ""):
        for i in range(len(run) - 1):
            bg = run[i:i + 2]
            if not (STOP_CJK & set(bg)):
                out.add(bg)
    return out


def english_tokens(text: str) -> set:
    """英文词 / HEX 色值 / 两位数以上数字关键词集合。"""
    toks = {t.lower() for t in re.findall(r"[A-Za-z][A-Za-z0-9_\-]{2,}", text or "")}
    toks |= {h.lower() for h in re.findall(r"#[0-9A-Fa-f]{3,8}", text or "")}
    toks |= set(re.findall(r"\d{2,}", text or ""))
    return toks


def keywords_of(*texts: str) -> set:
    kw = set()
    for t in texts:
        if t:
            kw |= cjk_bigrams(t) | english_tokens(t)
    return kw


def matches(text: str, keywords: set) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


def as_text(obj) -> str:
    """把 scene.visual_direction / shot.camera 等 dict|list|str 结构拍平成文本。"""
    if isinstance(obj, dict):
        return " ".join(as_text(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(as_text(v) for v in obj)
    return str(obj or "")


def parse_md_fields(text: str) -> dict:
    """解析 `- **Field**：value` 形式的字段行，返回 {field: [values]}。"""
    fields = {}
    for line in (text or "").splitlines():
        if CHECKBOX_RE.match(line):
            continue
        m = FIELD_LINE_RE.match(line)
        if m:
            fields.setdefault(m.group(1).strip(), []).append(m.group(2).strip())
    return fields


def parse_audio_route(text: str):
    """AUDIO_DIRECTION 的 '- [x] LIBRARY_MUSIC' 勾选路线。"""
    m = MUSIC_ROUTE_RE.search(text or "")
    return m.group(1) if m else None


def parse_hero_max(value: str):
    """Hero Sound Policy 里的频次上限（如 "全片 Hero Sound ≤ 2 次" → 2）。"""
    for v in (value or "",):
        m = re.search(r"[≤<]\s*(\d+)", v) or re.search(r"不超过\s*(\d+)", v)
        if not m:
            m = re.search(r"(\d+)\s*次", v)
        if m:
            return int(m.group(1))
    return None


def parse_avoid_items(value: str) -> list:
    """把 Avoid List 拆成具体条目（去"避免/禁止"前缀）。"""
    items = []
    for part in re.split(r"[；;/／\n]", value or ""):
        part = re.sub(r"^\s*(?:避免|禁止|不得|不要|不用|勿)\s*[:：]?\s*", "", part.strip())
        part = part.strip().strip("。，,、")
        if len(part) >= 2:
            items.append(part)
    return items


def is_chapter_row(head: str) -> bool:
    """Chapter Marker 行识别（Phase-2 Issue #2）：STORY_BEAT_MAP 中带 Ch. / Chapter /
    第 N 章 标记的行只作章节边界，不作为 Beat 计时。"""
    low = head.strip().lower()
    return bool(re.match(r"^(?:chapter\s*\d+|ch\.?\s*\d+|第\s*\d+\s*章)", low))


def parse_beats(text: str) -> list:
    """STORY_BEAT_MAP 节奏表：每行 [Beat N | Time Range | Duration | ...] 提取时长（秒）。
    排除 Chapter Marker 行（Ch./Chapter/第 N 章，即使带 Time Range 也不重复计时），
    只把 Beat 行计入 duration 合计。"""
    beats = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        head = cells[0].replace("*", "").strip()
        if not BEAT_ROW_RE.match(head) or is_chapter_row(head):
            continue
        duration = None
        m = DURATION_RE.search(cells[2])
        if m:
            duration = float(m.group(1))
        if duration is None:
            tr = TIME_RANGE_RE.search(cells[1])
            if tr:
                a = int(tr.group(1)) * 60 + int(tr.group(2))
                b = int(tr.group(3)) * 60 + int(tr.group(4))
                duration = float(max(0, b - a))
        if duration and duration > 0:
            beats.append(duration)
    return beats


def parse_reusable_rules(text: str) -> list:
    """REFERENCE_ANALYSIS.md 中 reusable / 可复用 章节下的规则条目。"""
    rules, in_section = [], False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            in_section = ("reusable" in s.lower()) or ("可复用" in s)
            continue
        if in_section and re.match(r"^[-*]\s+", s):
            rules.append(re.sub(r"^[-*]\s+", "", s))
    return rules


def parse_project_name(brief_text: str, fallback: str) -> str:
    m = re.search(r"^#\s*Project Name\s*[:：]\s*(.+?)\s*$", brief_text or "", re.M)
    return m.group(1).strip() if m else fallback


def load_json_dir(path: Path) -> list:
    """读取目录下所有 *.json（单对象或对象数组）。"""
    if not path.is_dir():
        raise FatalError(f"缺目录: {path}")
    objs = []
    for f in sorted(path.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FatalError(f"JSON 解析失败: {f} ({exc})")
        if isinstance(data, list):
            objs.extend(data)
        elif isinstance(data, dict):
            objs.append(data)
        else:
            raise FatalError(f"JSON 顶层类型异常（需对象或对象数组）: {f}")
    return objs


# ---------------------------------------------------------------------------
# Shot 级字段提取（兼容 dict 结构化写法与 schema 的 string 写法）
# ---------------------------------------------------------------------------

def motion_character(shot: dict) -> str:
    motion = shot.get("motion")
    if isinstance(motion, dict):
        return str(motion.get("character") or "").strip()
    if isinstance(motion, str):
        m = re.search(r"(?i)character\s*[:：]\s*([^;；]+)", motion)
        return m.group(1).strip() if m else motion.strip()
    return ""


def norm_character(shot: dict) -> str:
    v = re.sub(r"\s+", " ", motion_character(shot).lower()).strip()
    v = re.sub(r"[，,;；。]$", "", v)
    return v or "<empty>"


def is_hero_effect(shot: dict) -> bool:
    motion = shot.get("motion")
    if isinstance(motion, dict):
        return str(motion.get("intensity") or "").strip().lower() == "hero"
    if isinstance(motion, str):
        return bool(re.search(r"(?i)(intensity\s*[:：]\s*hero|\bhero\b)", motion))
    return False


def is_hero_audio(shot: dict) -> bool:
    audio = shot.get("audio")
    if not isinstance(audio, dict):
        return False
    blob = " ".join(str(x) for x in (audio.get("sfx") or [])) + " " + str(audio.get("notes") or "")
    return "hero" in blob.lower()


def editability_of(shot: dict):
    vd = shot.get("visual_direction")
    if isinstance(vd, dict):
        val = str(vd.get("editability") or "").strip()
        if val:
            return val.upper()
    for blob in (as_text(vd) if isinstance(vd, str) else "", str(shot.get("notes") or "")):
        m = EDITABILITY_RE.search(blob)
        if m:
            return m.group(1).upper()
    return None


def scene_text(scene: dict) -> str:
    parts = [scene.get("title"), scene.get("purpose"), scene.get("narrative_role"),
             as_text(scene.get("visual_direction")), as_text(scene.get("audio_direction"))]
    return " ".join(str(p) for p in parts if p)


def shot_text(shot: dict) -> str:
    parts = [shot.get("narrative_purpose"), shot.get("voiceover"), shot.get("on_screen_text"),
             shot.get("visual_description"), as_text(shot.get("camera")),
             as_text(shot.get("motion")), as_text(shot.get("notes"))]
    return " ".join(str(p) for p in parts if p)


def shot_durations(shots: list) -> list:
    out = []
    for sh in shots:
        dur = float(sh.get("duration") or 0)
        if dur <= 0:
            try:
                dur = max(0.0, float(sh.get("end_time") or 0) - float(sh.get("start_time") or 0))
            except (TypeError, ValueError):
                dur = 0.0
        out.append(dur)
    return out


# ---------------------------------------------------------------------------
# 9 项检查 + §65 Reference Influence Check
# ---------------------------------------------------------------------------

def _r(cid: str, name: str, status: str, details: str = "") -> CheckResult:
    return CheckResult(cid, name, status, details)


def check_01_creative(ctx: Context) -> CheckResult:
    """每个 Scene/Shot 是否服务 CREATIVE_DIRECTION 至少一条 Core Idea / Hook / Payoff。"""
    fields = parse_md_fields(ctx.creative_text)
    ideas = [v for k in CREATIVE_IDEA_FIELDS for v in fields.get(k, [])]
    if not ideas:
        return _r("01", "creative_consistency", "na",
                  "CREATIVE_DIRECTION 缺 Core Idea / Hook / Payoff，无法比对")
    if not ctx.scenes and not ctx.shots:
        return _r("01", "creative_consistency", "na", "无 Scene/Shot 数据")
    kw = keywords_of(*ideas)
    linked_sc = [s for s in ctx.scenes if matches(scene_text(s), kw)]
    linked_sh = [s for s in ctx.shots if matches(shot_text(s), kw)]
    sc_r = len(linked_sc) / len(ctx.scenes) if ctx.scenes else 1.0
    sh_r = len(linked_sh) / len(ctx.shots) if ctx.shots else 1.0
    details = f"Scene 关联 {len(linked_sc)}/{len(ctx.scenes)}, Shot 关联 {len(linked_sh)}/{len(ctx.shots)}"
    if sc_r == 1.0 and sh_r == 1.0:
        return _r("01", "creative_consistency", "pass", details + "，全部关联")
    if sc_r == 0 or sh_r == 0 or sc_r < 0.5 or sh_r < 0.5:
        unlinked = [s.get("id") for s in ctx.scenes if s not in linked_sc] \
            + [s.get("id") for s in ctx.shots if s not in linked_sh]
        return _r("01", "creative_consistency", "fail",
                  f"{details}；创意漂移，未关联: {', '.join(unlinked[:8])}")
    return _r("01", "creative_consistency", "warn", details + "，存在未关联 Scene/Shot")


def check_02_visual(ctx: Context) -> CheckResult:
    """Shot.visual_description 是否含 VISUAL_BIBLE 关键词（typography/color/motion 等），
    且不违反 Avoid List。"""
    fields = parse_md_fields(ctx.visual_text)
    sources = [v for k in VISUAL_KEY_FIELDS for v in fields.get(k, [])]
    kw = keywords_of(*sources)
    avoid = [item for v in fields.get(AVOID_FIELD, []) for item in parse_avoid_items(v)]
    if not ctx.shots:
        return _r("02", "visual_consistency", "na", "无 Shot 数据")
    if not kw and not avoid:
        return _r("02", "visual_consistency", "na", "VISUAL_BIBLE 无可解析的视觉关键词")
    linked, avoid_hits = [], []
    for sh in ctx.shots:
        desc = str(sh.get("visual_description") or "")
        if kw and matches(desc, kw):
            linked.append(sh)
        for item in avoid:
            if item.replace(" ", "") in desc.replace(" ", ""):
                avoid_hits.append((sh.get("id"), item))
    if avoid_hits:
        shown = "; ".join(f"{sid} 含'{item}'" for sid, item in avoid_hits[:5])
        return _r("02", "visual_consistency", "fail",
                  f"违反 VISUAL_BIBLE Avoid List: {shown}（关联 {len(linked)}/{len(ctx.shots)}）")
    if kw and not linked:
        return _r("02", "visual_consistency", "fail",
                  f"0/{len(ctx.shots)} 个 Shot 的 visual_description 含 VISUAL_BIBLE 关键词")
    if len(linked) < len(ctx.shots):
        missing = [s.get("id") for s in ctx.shots if s not in linked]
        return _r("02", "visual_consistency", "warn",
                  f"缺视觉关键词关联: {', '.join(missing[:8])}（{len(linked)}/{len(ctx.shots)}）")
    return _r("02", "visual_consistency", "pass",
              f"Shot 关联 {len(linked)}/{len(ctx.shots)}, Avoid List 命中 0")


def check_03_audio(ctx: Context) -> CheckResult:
    """Shot.audio 子结构是否遵守 AUDIO_DIRECTION（music mode / ducking / Hero Sound 上限）；
    缺失则 WARN，违反 Hero Sound Policy 上限或全部缺失则 FAIL。"""
    fields = parse_md_fields(ctx.audio_text)
    route = parse_audio_route(ctx.audio_text)
    hero_max = next((parse_hero_max(v) for v in fields.get(HERO_SOUND_FIELD, []) if parse_hero_max(v) is not None), None)
    has_silence_policy = bool(fields.get(SILENCE_FIELD))
    if not ctx.shots:
        return _r("03", "audio_consistency", "na", "无 Shot 数据")
    problems, missing, hero_audio, silence_shots = [], 0, 0, 0
    for sh in ctx.shots:
        audio = sh.get("audio")
        if not isinstance(audio, dict):
            missing += 1
            problems.append(f"{sh.get('id')} 缺 audio 子结构")
            continue
        music = audio.get("music") or {}
        mode = str(music.get("mode") or "").strip().lower()
        if mode not in MUSIC_MODES:
            problems.append(f"{sh.get('id')} music.mode 无效/缺失")
        if mode == "cue" and not str(music.get("cue") or "").strip():
            problems.append(f"{sh.get('id')} mode=cue 但缺 music.cue")
        if mode == "silence":
            silence_shots += 1
        vo = audio.get("voiceover") or {}
        present = bool(vo.get("present"))
        vo_text = str(sh.get("voiceover") or "").strip()
        if bool(vo_text) != present:
            problems.append(f"{sh.get('id')} voiceover 文案与 audio.voiceover.present 不一致")
        if present and not str(vo.get("ducking") or "").strip():
            problems.append(f"{sh.get('id')} 有 VO 但缺 ducking 策略")
        notes = str(audio.get("notes") or "")
        if any(w in notes for w in ("silence", "静音", "沉默")):
            silence_shots += 1
        if is_hero_audio(sh):
            hero_audio += 1
    route_note = f"music_route={route or '?'}"
    if hero_max is not None and hero_audio > hero_max:
        return _r("03", "audio_consistency", "fail",
                  f"Hero 音效 {hero_audio} 处 > AUDIO_DIRECTION 上限 {hero_max}（{route_note}）")
    if ctx.shots and missing == len(ctx.shots):
        return _r("03", "audio_consistency", "fail", f"全部 {missing} 个 Shot 缺 audio 子结构")
    if problems:
        return _r("03", "audio_consistency", "warn",
                  f"缺失/不一致 {len(problems)} 处（{route_note}）: {'; '.join(problems[:6])}")
    if has_silence_policy and silence_shots == 0:
        return _r("03", "audio_consistency", "warn",
                  "全片无 Silence/呼吸点（AUDIO_DIRECTION 声明了 Silence Policy）")
    return _r("03", "audio_consistency", "pass",
              f"{route_note}; hero 音效 {hero_audio}/{hero_max if hero_max is not None else '?'}; 呼吸点 {silence_shots}")


def check_04_editorial(ctx: Context) -> CheckResult:
    """Storyboard 镜头时间轴是否覆盖 STORY_BEAT_MAP 时间范围（无重大遗漏 / 大幅重叠）。"""
    beats = parse_beats(ctx.beat_text)
    if not beats:
        return _r("04", "editorial_consistency", "na", "STORY_BEAT_MAP 无节奏行")
    if not ctx.shots:
        return _r("04", "editorial_consistency", "na", "无 Shot 数据")
    beat_total = sum(beats)
    ordered = sorted(ctx.shots, key=lambda s: (float(s.get("start_time") or 0), str(s.get("id"))))
    shot_total = sum(shot_durations(ctx.shots))
    gap = overlap = 0.0
    prev_end = None
    for sh in ordered:
        start = float(sh.get("start_time") or 0)
        end = float(sh.get("end_time") or 0)
        if end < start:
            end = start + (shot_durations([sh])[0])
        if prev_end is not None:
            if start > prev_end + 1e-9:
                gap += start - prev_end
            elif start < prev_end - 1e-9:
                overlap += prev_end - start
        prev_end = max(prev_end if prev_end is not None else start, end)
    coverage = shot_total / beat_total if beat_total else 0.0
    details = (f"覆盖 {coverage * 100:.1f}%（{shot_total:.1f}s/{beat_total:.1f}s），"
               f"gap {gap:.1f}s, overlap {overlap:.1f}s")
    if coverage < 0.9 or coverage > 1.15 or gap > 1.0 or overlap > 1.0:
        return _r("04", "editorial_consistency", "fail", details + "，重大遗漏/重叠")
    if 0.95 <= coverage <= 1.05 and gap <= 0.3 and overlap <= 0.3:
        return _r("04", "editorial_consistency", "pass", details)
    return _r("04", "editorial_consistency", "warn", details)


def check_05_density(ctx: Context) -> CheckResult:
    """Shot 平均时长：长片（>120s）≥4s；短片 ≤120s ≥2s。"""
    if not ctx.shots:
        return _r("05", "density", "na", "无 Shot 数据")
    durations = shot_durations(ctx.shots)
    total = sum(durations)
    avg = total / len(durations)
    is_long = total > 120
    threshold = 4.0 if is_long else 2.0
    label = "长片>120s" if is_long else "短片"
    if avg >= threshold:
        return _r("05", "density", "pass", f"avg {avg:.2f}s ≥ {threshold:.1f}s（{label}）")
    return _r("05", "density", "fail", f"avg {avg:.2f}s < {threshold:.1f}s（{label}）")


def check_06_hero_density(ctx: Context) -> CheckResult:
    """Hero Effect Shot 占比：短片 ≤15%；长片 ≤8%。"""
    if not ctx.shots:
        return _r("06", "hero_effect_density", "na", "无 Shot 数据")
    total = sum(shot_durations(ctx.shots))
    hero = [s for s in ctx.shots if is_hero_effect(s)]
    ratio = len(hero) / len(ctx.shots) * 100
    threshold = 8.0 if total > 120 else 15.0
    if ratio <= threshold:
        return _r("06", "hero_effect_density", "pass", f"{ratio:.1f}% ≤ {threshold:.0f}%")
    return _r("06", "hero_effect_density", "fail", f"{ratio:.1f}% (阈值 {threshold:.0f}%)")


def check_07_motion_diversity(ctx: Context) -> CheckResult:
    """motion.character 至少 3 个不同取值。"""
    if not ctx.shots:
        return _r("07", "motion_diversity", "na", "无 Shot 数据")
    if len(ctx.shots) < 3:
        return _r("07", "motion_diversity", "na", f"Shot 数 {len(ctx.shots)} < 3，无法要求 3 种 Motion Character")
    chars = {norm_character(s) for s in ctx.shots}
    if len(chars) >= 3:
        return _r("07", "motion_diversity", "pass", f"{len(chars)} 种 Motion Character")
    return _r("07", "motion_diversity", "fail",
              f"仅 {len(chars)} 种 Motion Character: {', '.join(sorted(chars))}")


def check_08_audio_overload(ctx: Context) -> CheckResult:
    """每个 Shot 平均 sfx ≤3；含 Hero 音效 Shot ≤20%。"""
    if not ctx.shots:
        return _r("08", "audio_overload", "na", "无 Shot 数据")
    sfx_counts = []
    for sh in ctx.shots:
        audio = sh.get("audio")
        if isinstance(audio, dict):
            sfx_counts.append(len(audio.get("sfx") or []))
        else:
            sfx_counts.append(0)
    avg = sum(sfx_counts) / len(sfx_counts)
    hero_shots = [s for s in ctx.shots if is_hero_audio(s)]
    hero_ratio = len(hero_shots) / len(ctx.shots) * 100
    details = f"avg sfx {avg:.1f}/shot; hero 音效 Shot {hero_ratio:.1f}%"
    if avg <= 3 and hero_ratio <= 20:
        return _r("08", "audio_overload", "pass", details)
    return _r("08", "audio_overload", "fail", details + f"（阈值 3/20%）")


def check_09_editability(ctx: Context) -> CheckResult:
    """每个 Shot 标注 editability（HIGH/LOW/medium）+ 每个 Scene 至少 1 个 HIGH Shot。"""
    if not ctx.shots:
        return _r("09", "editability", "na", "无 Shot 数据")
    labels = {str(sh.get("id")): editability_of(sh) for sh in ctx.shots}
    labeled = [sid for sid, v in labels.items() if v in EDITABILITY_VALUES]
    unlabeled = [sid for sid, v in labels.items() if v not in EDITABILITY_VALUES]
    scene_problems = []
    for sc in ctx.scenes:
        entries = sc.get("shots") or []
        sids = [e.get("shot_id") if isinstance(e, dict) else e for e in entries]
        if not any(labels.get(str(sid)) == "HIGH" for sid in sids):
            scene_problems.append(str(sc.get("id")))
    if not unlabeled and not scene_problems:
        return _r("09", "editability", "pass",
                  f"标注 {len(labeled)}/{len(ctx.shots)}; 每个 Scene ≥1 个 HIGH Shot")
    parts = []
    if unlabeled:
        parts.append(f"未标注 editability: {', '.join(unlabeled[:8])}")
    if scene_problems:
        parts.append(f"无 HIGH Shot 的 Scene: {', '.join(scene_problems[:8])}")
    return _r("09", "editability", "fail", "；".join(parts))


def check_10_reference(ctx: Context) -> CheckResult:
    """§65 Reference Influence Check：若存在 references/，视觉描述与 reusable_rules
    直接矛盾则 WARN（学习原则 vs 复制镜头）。"""
    if not ctx.has_refs:
        return _r("10", "reference_influence", "na", "无 references/ 且无 REFERENCE_ANALYSIS.md")
    if not ctx.ref_text.strip():
        return _r("10", "reference_influence", "warn", "有 references/ 素材但缺 REFERENCE_ANALYSIS.md")
    rules = parse_reusable_rules(ctx.ref_text)
    if not rules:
        return _r("10", "reference_influence", "warn", "REFERENCE_ANALYSIS.md 无可解析的 reusable_rules")
    conflicts = []
    for rule in rules:
        low = rule.lower()
        marker = next((m for m in NEG_MARKERS if m in low), None)
        if marker is None:
            continue
        rest = rule[low.find(marker) + len(marker):]
        kw = cjk_bigrams(rest) | english_tokens(rest)
        if not kw:
            continue
        for sh in ctx.shots:
            desc = str(sh.get("visual_description") or "")
            bg_hits = sum(1 for k in cjk_bigrams(rest) if k in desc)
            en_hits = sum(1 for k in english_tokens(rest) if k in desc.lower())
            if bg_hits >= 2 or en_hits >= 1:
                conflicts.append(str(sh.get("id")))
    if conflicts:
        shown = ", ".join(sorted(set(conflicts))[:8])
        return _r("10", "reference_influence", "warn",
                  f"与 reusable_rules 可能矛盾（太接近 Reference 表述）: {shown}")
    return _r("10", "reference_influence", "pass", f"reusable_rules {len(rules)} 条，无矛盾")


CHECKS = [
    check_01_creative,
    check_02_visual,
    check_03_audio,
    check_04_editorial,
    check_05_density,
    check_06_hero_density,
    check_07_motion_diversity,
    check_08_audio_overload,
    check_09_editability,
    check_10_reference,
]


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_project(project_dir: str) -> Report:
    p = Path(project_dir)
    if not p.is_dir():
        raise FatalError(f"项目目录不存在: {p}")
    missing = [name for name in REQUIRED_FILES if not (p / name).is_file()]
    if missing:
        raise FatalError(f"缺必备文件: {', '.join(missing)}（目录 {p}）")
    scenes = load_json_dir(p / "scenes")
    shots = load_json_dir(p / "shots")
    if not scenes:
        raise FatalError(f"scenes/ 下没有可读取的场景 JSON（目录 {p}）")
    if not shots:
        raise FatalError(f"shots/ 下没有可读取的镜头 JSON（目录 {p}）")
    brief_text = (p / "PROJECT_BRIEF.md").read_text(encoding="utf-8")
    ref_file = p / "REFERENCE_ANALYSIS.md"
    refs_dir = p / "references"
    has_refs = (refs_dir.is_dir() and any(refs_dir.iterdir())) or ref_file.is_file()
    ctx = Context(
        project_dir=p,
        project_name=parse_project_name(brief_text, p.name),
        brief_text=brief_text,
        creative_text=(p / "CREATIVE_DIRECTION.md").read_text(encoding="utf-8"),
        visual_text=(p / "VISUAL_BIBLE.md").read_text(encoding="utf-8"),
        audio_text=(p / "AUDIO_DIRECTION.md").read_text(encoding="utf-8"),
        beat_text=(p / "STORY_BEAT_MAP.md").read_text(encoding="utf-8"),
        storyboard_text=(p / "STORYBOARD.md").read_text(encoding="utf-8"),
        ref_text=ref_file.read_text(encoding="utf-8") if ref_file.is_file() else "",
        has_refs=has_refs,
        scenes=scenes,
        shots=shots,
    )
    results = [fn(ctx) for fn in CHECKS]
    summary = {
        "passed": sum(1 for c in results if c.status == "pass"),
        "failed": sum(1 for c in results if c.status == "fail"),
        "na": sum(1 for c in results if c.status == "na"),
        "warnings": sum(1 for c in results if c.status == "warn"),
    }
    exit_code = 1 if summary["failed"] else 0
    return Report(project=ctx.project_name, checks=results, summary=summary, exit_code=exit_code)


def render_human(report: Report) -> str:
    tag = {"pass": "OK ", "fail": "FAIL", "warn": "WARN", "na": "N/A "}
    lines = [f"=== Director Consistency Check: {report.project} ==="]
    for c in report.checks:
        line = f"[{tag[c.status]}] check_{c.id}_{c.name}"
        if c.details and c.status in ("fail", "warn", "na"):
            line += f": {c.details}"
        lines.append(line)
    s = report.summary
    lines.append(f"Summary: {s['passed']} passed, {s['failed']} failed, {s['na']} N/A, {s['warnings']} warnings")
    return "\n".join(lines)


def render_fatal_json(project_name: str, message: str) -> str:
    return json.dumps({
        "project": project_name,
        "checks": [],
        "summary": {"passed": 0, "failed": 0, "na": 0, "warnings": 0},
        "exit_code": 2,
        "error": message,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 自检 fixtures（clean 全 pass / dirty 全 fail，覆盖 9 项检查的双路径）
# ---------------------------------------------------------------------------

def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _mk_shot(sid, scene_id, order, start, dur, **over):
    shot = {
        "id": sid, "scene_id": scene_id, "order": order,
        "duration": dur, "start_time": start, "end_time": start + dur,
        "narrative_purpose": "", "voiceover": "", "on_screen_text": "",
        "visual_description": "",
        "camera": {"movement": "static", "framing": "中景"},
        "motion": {"character": "", "intensity": "micro"},
        "audio": {
            "music": {"mode": "continue", "cue": "", "action": ""},
            "sfx": [], "ambience": [], "sync_points": [],
            "voiceover": {"present": False, "ducking": ""},
            "notes": "",
        },
        "transition_in": "cut", "transition_out": "cut",
        "layers": [{"layer_id": "L001", "z_order": 1}],
        "route": "UNDECIDED", "continuity_group": "",
        "assets": [], "dependencies": [],
        "approval": {"approval_id": "AP-001", "status": "pending"},
        "implementation_status": "not_started", "qa_status": "not_started",
        "notes": "Layer Intent: BG: 底; Editability: HIGH (文案参数化); Audio Intention: ...",
        "visual_direction": {"intent": "", "editability": "HIGH", "reason": "文案与节奏参数化"},
    }
    shot.update(over)
    return shot


def _mk_scene(sid, order, title, role, purpose, duration, shot_ids, **over):
    scene = {
        "id": sid, "chapter": f"Ch{order}", "order": order, "title": title,
        "narrative_role": role, "purpose": purpose, "target_duration": duration,
        "shots": [{"shot_id": s, "order": i + 1} for i, s in enumerate(shot_ids)],
        "visual_direction": {"summary": "低饱和冷色", "intensity": "medium", "tempo": "moderate"},
        "audio_direction": {"summary": "克制音效", "music_cue": "", "ambience": "room tone"},
        "approval": {"approval_id": "AP-001", "status": "pending"},
        "status": "not_started", "notes": "",
    }
    scene.update(over)
    return scene


def build_clean_fixture(root: Path) -> None:
    """clean fixture：150s 长片、12 Shot、0 Hero、12 种 Motion、全 Editability 标注——
    9 项检查 + §65 应全部 pass。"""
    (root / "scenes").mkdir(parents=True, exist_ok=True)
    (root / "shots").mkdir(parents=True, exist_ok=True)
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "PROJECT_BRIEF.md").write_text(
        "# Project Name: Clean Demo\n# Target Duration: 150\n", encoding="utf-8")
    (root / "CREATIVE_DIRECTION.md").write_text(
        "# CREATIVE_DIRECTION\n\n## 1. 创意核心\n\n"
        "- **Core Idea**：让观众理解并信任某AI笔记产品的记忆能力\n"
        "- **Hook**：开场一句反问加一屏倒计时\n"
        "- **Payoff**：产品把十年日记按主题重构的瞬间\n", encoding="utf-8")
    (root / "VISUAL_BIBLE.md").write_text(
        "# VISUAL_BIBLE\n\n## 1. Style 声明\n\n- **Style Name**：minimal_spatial_tech\n\n"
        "## 2. 视觉系统\n\n- **Color System**：黑白灰基底 单一强调蓝 #2D7FF9\n"
        "- **Typography**：标题 Sans-Serif 700 正文 400 数字等宽\n"
        "- **Composition**：三分法 安全边距 大量留白\n"
        "- **Motion Character**：基础 300ms ease-out 缓动\n\n"
        "## 6. Effect Philosophy\n\n- **Avoid List**：避免强 glitch；避免高饱和暖色；避免三维 logo 旋转\n",
        encoding="utf-8")
    (root / "AUDIO_DIRECTION.md").write_text(
        "# AUDIO_DIRECTION\n\n- [x] `LIBRARY_MUSIC` — 理由：短片旁白效率最高\n\n"
        "## 10. Ducking Strategy\n\n- **Ducking Strategy**：VO 进入时 music -8 dB\n\n"
        "## 18. Hero Sound Policy\n\n- **Hero Sound Policy**：全片 Hero Sound ≤ 2 次\n\n"
        "## 19. Silence Policy\n\n- **Silence Policy**：Climax 揭示前 0.5s 全静音\n",
        encoding="utf-8")
    (root / "STORY_BEAT_MAP.md").write_text(
        "# STORY_BEAT_MAP\n\n| Beat N | Time Range | Duration | Purpose |\n|---|---|---|---|\n"
        "| **Ch.1 · 悬念开场** | 00:00–00:50 | — | Chapter Marker |\n"
        "| Beat 01 | 00:00–00:20 | 20s | Hook |\n"
        "| Beat 02 | 00:20–00:50 | 30s | Context |\n"
        "| **Ch.2 · 展开** | 00:50–01:15 | — | Chapter Marker |\n"
        "| Beat 03 | 00:50–01:15 | 25s | Setup |\n"
        "| **Ch.3 · 推进** | 01:15–01:45 | — | Chapter Marker |\n"
        "| Beat 04 | 01:15–01:45 | 30s | Development |\n"
        "| **Ch.4 · 高潮** | 01:45–02:15 | — | Chapter Marker |\n"
        "| Beat 05 | 01:45–02:15 | 30s | Build |\n"
        "| **Ch.5 · 收尾** | 02:15–02:30 | — | Chapter Marker |\n"
        "| Beat 06 | 02:15–02:30 | 15s | Payoff |\n", encoding="utf-8")
    (root / "STORYBOARD.md").write_text(
        "# STORYBOARD\n\n| Scene ID | Title | Duration (s) | Shot Count |\n|---|---|---|---|\n"
        "| SC001 | 开场 | 50.0 | 4 |\n| SC002 | 揭晓 | 50.0 | 4 |\n| SC003 | 收尾 | 50.0 | 4 |\n"
        "| 合计 | — | 150.0 | 12 |\n", encoding="utf-8")
    (root / "REFERENCE_ANALYSIS.md").write_text(
        "# REFERENCE_ANALYSIS\n\n## Reusable Rules\n\n"
        "- 使用低饱和冷色调与大量留白构图（可复用）\n", encoding="utf-8")
    (root / "references" / "ref01.mp4").write_bytes(b"")
    chars = ["光标闪烁", "卡片逐张消隐", "卡片堆叠", "数据流动", "透视推镜", "光点脉冲",
             "分屏擦除", "标题逐字入场", "图表增长", "地图生长", "翻页", "渐变浮现"]
    dur_pat = [12, 13, 12, 13, 12, 13, 12, 13, 12, 13, 12, 13]
    high_edits = {0, 1, 4, 7, 8, 10}
    vo_shots = {0, 1, 2, 3, 8, 9, 10, 11}  # S001-S004、S009-S012 有 VO
    shots_by_scene = {"SC001": [], "SC002": [], "SC003": []}
    start = 0.0
    for i in range(12):
        sid = f"S{i + 1:03d}"
        scene_id = "SC001" if i < 4 else ("SC002" if i < 8 else "SC003")
        desc = (f"黑白灰界面，大留白构图，展示 AI 笔记产品的记忆能力，"
                f"等宽数字跳动，{chars[i]}，300ms ease-out 入场")
        has_vo = i in vo_shots
        audio = {
            "music": {"mode": "continue", "cue": "", "action": ""},
            "sfx": ["cursor tick", "soft whoosh"],
            "ambience": ["room tone -20dB"],
            "sync_points": [f"00:0{i % 10} 同步点"],
            "voiceover": {"present": has_vo, "ducking": "-3 dB" if has_vo else ""},
            "notes": "",
        }
        if sid == "S005":
            audio["music"] = {"mode": "cue", "cue": "主题进入 @00:50", "action": ""}
        if sid == "S012":
            audio["music"] = {"mode": "silence", "cue": "", "action": ""}
            audio["voiceover"] = {"present": True, "ducking": "none"}
            audio["notes"] = "结尾全静音"
        edit = "HIGH" if i in high_edits else "LOW"
        shot = _mk_shot(
            sid, scene_id, i % 4 + 1, start, float(dur_pat[i]),
            narrative_purpose=f"{chars[i]}镜头叙事目的，服务记忆产品主张",
            voiceover=f"这是第 {i + 1} 个镜头" if has_vo else "",
            on_screen_text="" if sid != "S005" else "MEMORY LAYERS",
            visual_description=desc,
            motion={"character": chars[i], "intensity": "micro" if i % 2 else "narrative"},
            audio=audio,
            notes=f"Layer Intent: BG: 底; Editability: {edit} (节奏参数化); Audio Intention: ...",
            visual_direction={"intent": "BG/CONCEPT/TYPO/ATMO/AUDIO", "editability": edit,
                              "reason": "节奏与文案参数化" if edit == "HIGH" else "连续 Motion 允许 bake"},
        )
        shots_by_scene[scene_id].append(sid)
        _write_json(root / "shots" / f"{sid}.json", shot)
        start += dur_pat[i]
    _write_json(root / "scenes" / "SC001.json",
                _mk_scene("SC001", 1, "开场：问题", "Hook",
                          "建立 AI 笔记产品的记忆能力日常痛点", 50.0, shots_by_scene["SC001"]))
    _write_json(root / "scenes" / "SC002.json",
                _mk_scene("SC002", 2, "揭晓：工作原理", "Development",
                          "用分镜讲清记忆分层与产品能力结构", 50.0, shots_by_scene["SC002"]))
    _write_json(root / "scenes" / "SC003.json",
                _mk_scene("SC003", 3, "收尾：价值", "Payoff",
                          "回到观众：从记得你到真正理解你，产品价值落地", 50.0, shots_by_scene["SC003"]))


def build_dirty_fixture(root: Path) -> None:
    """dirty fixture：60s 短片意图 vs 4s 烹饪短片——9 项检查全部 fail，§65 触发 warn。"""
    (root / "scenes").mkdir(parents=True, exist_ok=True)
    (root / "shots").mkdir(parents=True, exist_ok=True)
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "PROJECT_BRIEF.md").write_text(
        "# Project Name: Dirty Demo\n# Target Duration: 60\n", encoding="utf-8")
    (root / "CREATIVE_DIRECTION.md").write_text(
        "# CREATIVE_DIRECTION\n\n## 1. 创意核心\n\n"
        "- **Core Idea**：让观众理解并信任产品的记忆能力\n"
        "- **Hook**：开场一句反问\n"
        "- **Payoff**：十年日记重构瞬间\n", encoding="utf-8")
    (root / "VISUAL_BIBLE.md").write_text(
        "# VISUAL_BIBLE\n\n## 1. Style 声明\n\n- **Style Name**：minimal_spatial_tech\n\n"
        "## 2. 视觉系统\n\n- **Color System**：黑白灰基底 单一强调蓝 #2D7FF9\n"
        "- **Typography**：标题 Sans-Serif 700 正文 400 数字等宽\n"
        "- **Composition**：三分法 安全边距 大量留白\n"
        "- **Motion Character**：基础 300ms ease-out 缓动\n\n"
        "## 6. Effect Philosophy\n\n- **Avoid List**：避免强 glitch；避免高饱和暖色；避免三维 logo 旋转\n",
        encoding="utf-8")
    (root / "AUDIO_DIRECTION.md").write_text(
        "# AUDIO_DIRECTION\n\n- [x] `LIBRARY_MUSIC` — 理由：短片旁白效率最高\n\n"
        "## 10. Ducking Strategy\n\n- **Ducking Strategy**：VO 进入时 music -8 dB\n\n"
        "## 18. Hero Sound Policy\n\n- **Hero Sound Policy**：全片 Hero Sound ≤ 2 次\n\n"
        "## 19. Silence Policy\n\n- **Silence Policy**：Climax 揭示前 0.5s 全静音\n",
        encoding="utf-8")
    (root / "STORY_BEAT_MAP.md").write_text(
        "# STORY_BEAT_MAP\n\n| Beat N | Time Range | Duration | Purpose |\n|---|---|---|---|\n"
        "| **Ch.1 · 开场** | 00:00–00:30 | — | Chapter Marker |\n"
        "| Beat 01 | 00:00–00:10 | 10s | Hook |\n"
        "| Beat 02 | 00:10–00:20 | 10s | Setup |\n"
        "| Beat 03 | 00:20–00:30 | 10s | Feature |\n"
        "| Beat 04 | 00:30–00:40 | 10s | Feature |\n"
        "| Beat 05 | 00:40–00:50 | 10s | Hero Moment |\n"
        "| Beat 06 | 00:50–01:00 | 10s | CTA |\n", encoding="utf-8")
    (root / "STORYBOARD.md").write_text(
        "# STORYBOARD\n\n| Scene ID | Title | Duration (s) | Shot Count |\n|---|---|---|---|\n"
        "| SC001 | 烹饪教学 | 2.0 | 4 |\n| SC002 | 装盘出锅 | 2.0 | 4 |\n"
        "| 合计 | — | 4.0 | 8 |\n", encoding="utf-8")
    (root / "REFERENCE_ANALYSIS.md").write_text(
        "# REFERENCE_ANALYSIS\n\n## Reusable Rules\n\n"
        "- 避免使用高饱和暖色与强对比画面（可复用）\n", encoding="utf-8")
    (root / "references" / "ref01.mp4").write_bytes(b"")
    desc = "高饱和暖色的锅底翻炒洋葱与牛肉，大火爆炒3分钟，装盘出锅"
    shots_by_scene = {"SC001": [], "SC002": []}
    for i in range(8):
        sid = f"S{i + 1:03d}"
        scene_id = "SC001" if i < 4 else "SC002"
        over = dict(
            narrative_purpose="演示家常菜的做法步骤",
            voiceover="",
            visual_description=desc,
            motion={"character": "翻炒", "intensity": "hero" if i < 4 else "narrative"},
            notes="",
            visual_direction={"intent": "BG: 锅底"},
        )
        if i < 4:
            over["audio"] = {
                "music": {"mode": "continue", "cue": "", "action": ""},
                "sfx": (["boom", "sizzle", "clang", "whoosh"] + (["hero impact"] if i < 3 else [])),
                "ambience": [], "sync_points": [],
                "voiceover": {"present": False, "ducking": ""}, "notes": "",
            }
        shot = _mk_shot(sid, scene_id, i % 4 + 1, i * 0.5, 0.5, **over)
        if "audio" not in over:
            shot.pop("audio", None)
        shots_by_scene[scene_id].append(sid)
        _write_json(root / "shots" / f"{sid}.json", shot)
    _write_json(root / "scenes" / "SC001.json",
                _mk_scene("SC001", 1, "烹饪教学", "Setup",
                          "手把手教你做家常菜，掌握火候与调味", 2.0, shots_by_scene["SC001"]))
    _write_json(root / "scenes" / "SC002.json",
                _mk_scene("SC002", 2, "装盘出锅", "Payoff",
                          "摆盘上桌，色香味俱全", 2.0, shots_by_scene["SC002"]))


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def run_selftest() -> int:
    print("selftest: 开始（临时目录，双 fixture 双路径覆盖）")
    try:
        with tempfile.TemporaryDirectory(prefix="dcc-selftest-") as td:
            tdir = Path(td)
            clean_dir = tdir / "clean"
            build_clean_fixture(clean_dir)
            r_clean = run_project(str(clean_dir))
            for c in r_clean.checks:
                assert c.status == "pass", f"clean check_{c.id} 期望 pass, 实际 {c.status}: {c.details}"
            assert r_clean.exit_code == 0
            assert r_clean.summary == {"passed": 10, "failed": 0, "na": 0, "warnings": 0}, r_clean.summary
            print(f"selftest: clean fixture -> 10 pass / 0 fail / 0 na / 0 warn (exit 0) OK")

            # Phase-2 Issue #2 回归：Chapter 行（Ch./Chapter/第 N 章，即使带 Time Range）
            # 不作 Beat 重复计时，只把 Beat 行计入 duration 合计
            beat_lines = (
                "| **Ch.1 · 悬念开场** | 00:00–00:50 | — | Chapter Marker |\n"
                "| Beat 01 | 00:00–00:20 | 20s | Hook |\n"
                "| **Chapter 2** | 00:20–00:50 | — | Chapter Marker |\n"
                "| 第 3 章 · 收束 | 00:50–01:15 | 25s | Chapter Marker |\n"
                "| Beat 02 | 00:20–00:50 | 30s | Context |\n")
            parsed = parse_beats(beat_lines)
            assert parsed == [20.0, 30.0], f"Chapter 行被重复计时: {parsed}"
            print("selftest: Issue #2 回归（Chapter 行不计入 Beat 计时）OK")

            dirty_dir = tdir / "dirty"
            build_dirty_fixture(dirty_dir)
            r_dirty = run_project(str(dirty_dir))
            dirty_by = {c.id: c for c in r_dirty.checks}
            for cid in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
                c = dirty_by[cid]
                assert c.status == "fail", f"dirty check_{cid} 期望 fail, 实际 {c.status}: {c.details}"
            assert dirty_by["10"].status == "warn", f"dirty check_10 期望 warn, 实际 {dirty_by['10'].status}"
            assert r_dirty.exit_code == 1
            assert r_dirty.summary["failed"] == 9 and r_dirty.summary["warnings"] == 1, r_dirty.summary
            print("selftest: dirty fixture -> 9 fail + 1 warn (exit 1) OK")

            clean_by = {c.id: c for c in r_clean.checks}
            for cid in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
                assert clean_by[cid].status == "pass" and dirty_by[cid].status == "fail", \
                    f"check_{cid} 双路径覆盖失败（clean={clean_by[cid].status}, dirty={dirty_by[cid].status}）"
            print("selftest: 双路径覆盖 -> 9 项 check 各命中 pass(clean) + fail(dirty) OK")

            fatal_dir = tdir / "fatal"
            shutil.copytree(clean_dir, fatal_dir)
            (fatal_dir / "CREATIVE_DIRECTION.md").unlink()
            raised = False
            try:
                run_project(str(fatal_dir))
            except FatalError:
                raised = True
            assert raised, "缺必备文件应抛 FatalError（exit 2 路径）"
            print("selftest: 致命错误路径（缺必备文件）-> FatalError OK")

            human = render_human(r_clean)
            assert human.startswith("=== Director Consistency Check: Clean Demo ==="), human[:60]
            assert "Summary: 10 passed, 0 failed, 0 N/A, 0 warnings" in human
            human_dirty = render_human(r_dirty)
            assert "[FAIL] check_05_density" in human_dirty and "[WARN] check_10_reference_influence" in human_dirty
            data = json.loads(json.dumps(r_clean.as_dict(), ensure_ascii=False))
            assert data["project"] == "Clean Demo" and data["exit_code"] == 0
            assert len(data["checks"]) == 10 and data["checks"][0]["id"] == "01"
            fatal_json = json.loads(render_fatal_json("Fatal Demo", "缺必备文件: CREATIVE_DIRECTION.md"))
            assert fatal_json["exit_code"] == 2 and fatal_json["summary"]["failed"] == 0
            print("selftest: human / JSON 输出格式 OK")
        print("SELFTEST PASSED")
        return 0
    except AssertionError as exc:
        print(f"SELFTEST FAILED: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="director-consistency-check.py",
        description="ZHOU_Videodirector Phase 2 导演一致性检查（P2-7，§64 九项 + §65 Reference Influence）。")
    ap.add_argument("project_dir", nargs="?", help="ZHOU_Videodirector 项目目录")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--selftest", action="store_true",
                    help="运行内置自检（clean/dirty 两个 fixture，9 项检查双路径断言；exit 0=通过）")
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
