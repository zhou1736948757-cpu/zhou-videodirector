#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZHOU_Videodirector — Sound Engine (P5-5)

定位（Phase-5 §41-§69 / §102-§106）：生产管线中的声音引擎。

职责（只做 Spec / 计划 / QA 决策，不直接渲染）：
  - SFX_SPEC / MUSIC_SPEC 生成（§44 / §58），sync 精确到 frame/timestamp；
  - SFX 搜索计划（§43 Tier）、编辑计划（§49）；
  - 音乐策略（§50-§57：长片不默认 MIDI 整曲；procedural 只做短元素）；
  - Ducking / Ambience / Silence 策略（§65-§67）；
  - Sound QA（§102-§103）与审美复核（§104/§106）；
  - Woosh 实验策略（§68）。

铁律（本模块内联）:
  - **MIDI 不随机写音符**（§60）：音符事件一律按 AUDIO_DIRECTION + Beat Map +
    sync points 确定性推导（见 midi_note_events）；本模块不含任何 random。
  - Audio Direction 要求 silence 时不自动填满（§67）。
  - 不搞广播级 mastering（§103）：只保证 no clipping / reasonable gain /
    consistent level。
  - 只吃已批准设计：无法实现时由上层走 PRODUCTION_CONFLICT（本模块不私自改设计）。

Python 3 stdlib only。可选 PyYAML 不依赖。
"""

# ---------------------------------------------------------------------------
# 常量 / 共享契约
# ---------------------------------------------------------------------------

# §43 SFX 搜索 Tier（由高到低，命中即停）
SFX_SEARCH_TIERS = [
    {"tier": 0, "name": "@remotion/sfx", "provider_id": "remotion-sfx",
     "integration": "PACKAGE", "auth": "NONE", "priority": 10,
     "rationale": "Tier-0 官方即取即用；本地包式（npx remotion add @remotion/sfx），音量统一归一 -3dB peak"},
    {"tier": 1, "name": "Local/Cached Registry", "provider_id": "local",
     "integration": "LOCAL", "auth": "NONE", "priority": 9,
     "rationale": "已索引/已缓存本地 SFX，秒级返回、可离线（Registry 宪法 Metadata First）"},
    {"tier": 2, "name": "Freesound", "provider_id": "freesound",
     "integration": "API", "auth": "API_KEY", "priority": 5,
     "rationale": "官方 API 搜索 + license 过滤 + 逐条核对；禁止爬站绕过认证"},
    {"tier": 3, "name": "Mixkit", "provider_id": "mixkit",
     "integration": "WEBSITE", "auth": "NONE", "priority": 4,
     "rationale": "Stock SFX/Music，手动触发下载，遵守 license terms"},
    {"tier": 4, "name": "Generated SFX", "provider_id": "woosh",
     "integration": "PROVIDER", "auth": "NONE", "priority": 1,
     "rationale": "兜底生成（EXPERIMENTAL，§68）：不作为默认，License/commercial 不满足时禁用于商业项目"},
]

# §58 MUSIC_SPEC 全部字段
MUSIC_SPEC_FIELDS = [
    "purpose", "duration", "bpm", "key", "meter", "mood", "energy",
    "instrumentation", "rhythmic_density", "melodic_density", "harmonic_character",
    "structure", "sync_points", "voiceover_priority", "loop", "ending",
    "soundfont", "mix_target",
]

# §44 SFX_SPEC 全部字段
SFX_SPEC_FIELDS = [
    "shot_id", "sync_time", "purpose", "category", "character", "intensity",
    "duration", "frequency_character", "tail", "style", "license_requirement",
    "source_preference",
]

# §56 procedural music 允许产出的短元素（长片不做整曲 MIDI）
PROCEDURAL_SCOPE = [
    "Logo Sting", "Intro", "Outro", "Chapter Transition",
    "Short Bed", "Beat Sync", "Tonal Accent",
]

# §65 Ducking 参数
DUCK_BASE_LEVEL_DB = -12
DUCK_VS_VOICEOVER_DB = -4
DUCK_IMPORTANT_DB = -6
HERO_PAUSE_RETURN_GAP_SEC = 0.8


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------

def _first_non_none(*values):
    """返回第一个非 None 且非空的值；否则 None。"""
    for v in values:
        if v is not None and v != "" and v != []:
            return v
    return None


def _fps_of(audio_direction=None, production_request=None, default=30):
    for src in (production_request, audio_direction):
        if not src:
            continue
        fps = src.get("fps") or src.get("video_fps")
        if fps:
            return int(fps)
    return default


def _parse_bpm(bpm_range):
    """解析 bpm_range，如 '100-110' -> 105，'104' -> 104，缺省 -> 105。"""
    if not bpm_range:
        return 105
    text = str(bpm_range).strip()
    if "-" in text:
        try:
            lo, hi = text.split("-")
            lo, hi = float(lo), float(hi)
            return int(round((lo + hi) / 2.0))
        except (ValueError, TypeError):
            pass
    try:
        return int(round(float(text)))
    except (ValueError, TypeError):
        return 105


def _classify_sfx_category(requirements, family=None):
    """按关键词把音频需求分类到 SFX category 枚举。

    family 里已命中的键（click/confirm/error/transition/impact/hero）优先；
    其次按 audio_requirements 关键词。
    """
    if family:
        for key, cat in (("confirm", "UI"), ("click", "CLICK"), ("error", "ERROR"),
                         ("transition", "TRANSITION"), ("impact", "IMPACT"),
                         ("hero", "HERO"), ("whoosh", "WHOOSH")):
            if family.get(key):
                return cat
    text = ("%s" % (requirements or "")).lower()
    rules = [
        (("ui", "interface", "confirm", "confirmation", "notification",
          "select", "success", "menu"), "UI"),
        (("click", "tap", "button", "tick", "keypress"), "CLICK"),
        (("error", "fail", "wrong", "denied"), "ERROR"),
        (("whoosh", "swish", "air", "pass"), "WHOOSH"),
        (("transition", "swipe", "slide", "page", "flip", "whip"), "TRANSITION"),
        (("impact", "boom", "hit", "thud", "bass", "punch"), "IMPACT"),
        (("riser", "build", "sweep"), "RISER"),
        (("hero", "logo", "identity", "climax"), "HERO"),
    ]
    for words, cat in rules:
        if any(w in text for w in words):
            return cat
    return "UI" if "ui" in text else "SFX"


def _classify_intensity(requirements, sfx_language="", family=None):
    """intensity 枚举：LOW / MEDIUM / HIGH / HERO。"""
    if family and family.get("intensity"):
        return str(family["intensity"]).upper()
    text = ("%s %s" % (requirements or "", sfx_language or "")).lower()
    if any(w in text for w in ("hero", "climax", "major", "epic")):
        return "HERO"
    if any(w in text for w in ("impact", "boom", "heavy", "large", "strong", "big")):
        return "HIGH"
    if any(w in text for w in ("subtle", "minimal", "soft", "quiet", "gentle", "tiny")):
        return "LOW"
    return "MEDIUM"


def _infer_tail(category, character=""):
    char = ("%s %s" % (category or "", character or "")).lower()
    if any(w in char for w in ("click", "tick", "tap", "ui")):
        return "very short"
    if any(w in char for w in ("whoosh", "transition", "riser", "swish")):
        return "medium"
    if any(w in char for w in ("impact", "boom", "hero", "hit")):
        return "long"
    return "short"


def _infer_frequency_character(category, character=""):
    char = ("%s %s" % (category or "", character or "")).lower()
    if any(w in char for w in ("tick", "click", "shutter", "digital")):
        return "high transient"
    if any(w in char for w in ("soft", "quiet", "subtle", "pad")):
        return "low-mid soft"
    if any(w in char for w in ("boom", "impact", "sub", "heavy")):
        return "sub-heavy low"
    return "balanced"


def _license_requirement(production_request=None):
    req = (production_request or {}).get("license_requirement")
    if isinstance(req, dict):
        return req
    if req:
        return {"commercial_use": True, "license": str(req)}
    return {
        "commercial_use": True,
        "attribution_ok": True,
        "note": "商业项目默认要求可商用；具体以 Registry license 块逐条核对（Phase 4 §69）",
    }


# ---------------------------------------------------------------------------
# SFX Spec / 搜索 / 编辑
# ---------------------------------------------------------------------------

def build_sfx_spec(production_request, audio_direction, sfx_family):
    """生成 SFX_SPEC（§44 全字段），sync 精确到 frame/timestamp（§48）。

    production_request: {request_id, shot_id, duration, audio_requirements, ...}
    audio_direction   : AUDIO_DIRECTION（sfx_language 等）
    sfx_family        : SFX Family（P5-1 sfx-family.schema.json 字段：
                        style/click/confirm/error/transition/impact/hero/
                        character/frequency_profile/loudness_target/avoid）
    """
    request = production_request or {}
    audio_dir = audio_direction or {}
    family = sfx_family or {}
    requirements = request.get("audio_requirements") or ""

    fps = _fps_of(audio_dir, request)
    # sync_time：优先 request 内已定的 frame / audio_sync_point；否则锚定 shot start
    sync_frame = None
    sync_ref = "shot start (refine when timeline known)"
    asp = request.get("audio_sync_point")
    if isinstance(asp, dict):
        sync_frame = asp.get("frame") or asp.get("timestamp_frame")
        if asp.get("event"):
            sync_ref = "audio_sync_point: %s" % asp.get("event")
    elif asp is not None:
        sync_frame = asp
        sync_ref = "audio_sync_point"
    for key in ("sync_frame", "start_frame", "frame"):
        if key in request and request[key] is not None:
            sync_frame = int(request[key])
            sync_ref = "request.%s" % key
            break
    sync_time = {
        "frame": sync_frame,
        "timestamp": (round(sync_frame / float(fps), 3)
                      if sync_frame is not None else None),
        "fps": fps,
        "reference": sync_ref,
    }

    category = _classify_sfx_category(requirements, family)
    intensity = _classify_intensity(requirements,
                                    audio_dir.get("sfx_language", ""), family)
    character = _first_non_none(
        family.get("character"),
        family.get("name"),
        "soft" if "soft" in requirements.lower() else None,
        "neutral",
    )
    duration = request.get("duration")
    if duration is None:
        duration = 0.25 if category in ("CLICK", "UI") else 1.0

    family_key = {"UI": "confirm", "CLICK": "click", "ERROR": "error",
                  "TRANSITION": "transition", "IMPACT": "impact",
                  "HERO": "hero", "WHOOSH": "whoosh"}.get(category)

    return {
        "spec_type": "SFX_SPEC",
        "shot_id": request.get("shot_id"),
        "request_id": request.get("request_id"),
        "sync_time": sync_time,
        "purpose": requirements or family_key and family.get(family_key)
                   or "intentional audio for shot %s" % request.get("shot_id"),
        "category": category,
        "categories": [category],
        "character": character,
        "intensity": intensity,
        "duration": float(duration),
        "frequency_character": _first_non_none(
            family.get("frequency_profile"),
            _infer_frequency_character(category, character)),
        "tail": _infer_tail(category, character),
        "style": _first_non_none(
            family.get("style"),
            audio_dir.get("sfx_language"),
            "subtle"),
        "license_requirement": _license_requirement(request),
        "source_preference": [t["name"] for t in SFX_SEARCH_TIERS],
        "family": family.get("id") or family.get("name") or None,
        "sound_candidate": family.get(family_key) if family_key else None,
        "avoid": list(family.get("avoid") or audio_dir.get("avoid") or []),
    }


def sfx_search_plan(spec):
    """按 §43 Tier 顺序返回搜索计划（provider 优先级 + registry 查询）。"""
    spec = spec or {}
    query = " ".join(str(x) for x in
                     [spec.get("category"), spec.get("character"),
                      spec.get("purpose")] if x)
    tiers = []
    for t in SFX_SEARCH_TIERS:
        tier = dict(t)
        tier["registry_query"] = {
            "type": "SFX",
            "provider": t["provider_id"],
            "query": query.strip() or None,
            "tags": ([x for x in (spec.get("character"), spec.get("style")) if x]
                     or None),
        }
        tiers.append(tier)
    return {
        "spec_shot_id": spec.get("shot_id"),
        "category": spec.get("category"),
        "query": query.strip(),
        "tiers": tiers,
        "stop_on_first_hit": True,
        "note": "命中即停；Freesound 未配置 API key 时自动跳到 Mixkit（Tier 3）",
    }


def sfx_editing_plan(spec):
    """§49 SFX 编辑计划：trim/fade/gain/pitch/time stretch/EQ/basic reverb。

    只做 CLI/ffmpeg 级后期（不建 DAW）；默认最小处理。
    """
    spec = spec or {}
    duration = spec.get("duration") or 1.0
    steps = [
        {"step": "trim", "params": {"duration_sec": float(duration)},
         "tool": "ffmpeg -t", "reason": "匹配 shot 时长"},
        {"step": "fade", "params": {"fade_in_sec": 0.01, "fade_out_sec": 0.05},
         "tool": "ffmpeg afade", "reason": "消除爆点/突兀"},
        {"step": "gain", "params": {"target_peak_db": -3.0},
         "tool": "ffmpeg volume/loudnorm(reduce-only)",
         "reason": "音量归一（@remotion/sfx 统一 -3dB peak 约定）"},
        {"step": "pitch", "params": {"enabled": False, "semitones": 0,
                                     "mode": "asetrate+aresample"},
         "tool": "ffmpeg asetrate", "reason": "仅当 character 需要时启用"},
        {"step": "time_stretch", "params": {"enabled": False, "tempo": 1.0,
                                            "method": "atempo"},
         "tool": "ffmpeg atempo", "reason": "仅当节奏对不齐时启用"},
        {"step": "eq", "params": {"enabled": False,
                                  "high_pass_hz": 60, "low_pass_hz": 16000},
         "tool": "ffmpeg highpass/lowpass", "reason": "去亚声/高频噪"},
        {"step": "basic_reverb", "params": {"enabled": False, "dry_wet": 0.1,
                                            "decay": 0.3},
         "tool": "ffmpeg aecho (basic)", "reason": "仅 Hero/空间感需要时启用"},
    ]
    return {
        "spec_shot_id": spec.get("shot_id"),
        "duration_sec": float(duration),
        "steps": steps,
        "daw": False,
        "policy": "按需启用，默认最小处理（§49 不建 DAW）",
    }


# ---------------------------------------------------------------------------
# Music Spec / 策略
# ---------------------------------------------------------------------------

# D 自然小调音阶（§61 示例 104 BPM D minor）；degree -> 音名
D_MINOR_SCALE = ["D4", "E4", "F4", "G4", "A4", "Bb4", "C5"]
# purpose -> 音阶级数（确定性映射，非随机）
_PURPOSE_DEGREE = {
    "intro": 0, "hero reveal": 3, "hero": 3, "climax": 3,
    "transition": 5, "build": 6, "riser": 6, "outro": 4, "ending": 4,
    "pause": None, "rest": None,
}
_INTENSITY_VELOCITY = {"LOW": 64, "MEDIUM": 80, "HIGH": 96, "HERO": 112}


def midi_note_events(beat_map, key="D minor", bpm=105, fps=30, energy="MEDIUM"):
    """§60 确定性 MIDI 音符事件：按 Beat Map purpose 映射音阶音级。

    **不随机写音符**：每个 beat 按 purpose 查确定性映射表得出音符与力度，
    输出事件含秒级时间与 frame 级同步位。供 MIDI Composer 直接消费。
    """
    beats = (beat_map or {}).get("beats") or []
    velocity = _INTENSITY_VELOCITY.get(str(energy).upper(), 80)
    beat_sec = 60.0 / max(float(bpm), 1.0)
    events = []
    for i, beat in enumerate(beats):
        t = float(beat.get("t", 0))
        purpose = str(beat.get("purpose") or "beat")
        degree = None
        for word, deg in _PURPOSE_DEGREE.items():
            if word in purpose.lower():
                degree = deg
                break
        if degree is None:
            degree = i % len(D_MINOR_SCALE)
        events.append({
            "index": i,
            "time_sec": round(t, 3),
            "frame": int(round(t * float(fps))),
            "beat_sec": round(beat_sec, 3),
            "purpose": purpose,
            "note": D_MINOR_SCALE[degree % len(D_MINOR_SCALE)],
            "velocity": velocity,
            "channel": 0,
        })
    return events


def build_music_spec(audio_direction, beat_map, video_sync_points):
    """生成 MUSIC_SPEC（§58 全字段）。

    audio_direction  : AUDIO_DIRECTION（music_direction/bpm_range/mood/energy/
                       instrumentation/voiceover_priority/key/meter/...）
    beat_map         : {beats: [{t:秒, purpose}]}（视觉节奏）
    video_sync_points: [{frame, event}]（视频同步点，frame 精确）

    铁律 §60：MIDI 不随机写音符——note_plan 由
    AUDIO_DIRECTION + Beat Map + sync points 确定性推导（见 midi_note_events）。
    """
    audio_dir = audio_direction or {}
    beats = (beat_map or {}).get("beats") or []
    syncs = video_sync_points or []
    fps = _fps_of(audio_dir, None)
    bpm = _parse_bpm(audio_dir.get("bpm_range"))
    key = _first_non_none(audio_dir.get("key"),
                          audio_dir.get("harmonic_character"),
                          "D minor")          # §61 示例 104 BPM D minor
    meter = audio_dir.get("meter", "4/4")
    purpose = _first_non_none(
        audio_dir.get("music_direction"), audio_dir.get("music_purpose"),
        "background music bed")
    mood = audio_dir.get("mood") or "calm"
    energy = audio_dir.get("energy") or "low"
    voiceover_priority = audio_dir.get("voiceover_priority") or "high"
    soundfont = audio_dir.get("soundfont") or "generaluser-gs"

    # duration：max(最后 beat 秒, 最后 sync frame 时间) + 结尾余量
    last_time = max([float(b.get("t", 0)) for b in beats] or [0.0])
    for s in syncs:
        if s.get("frame") is not None:
            last_time = max(last_time, float(s["frame"]) / float(fps))
    duration = round(last_time + 4.0, 3)      # +1 小节尾巴

    # 乐器 / 密度由方向文本推导（确定性）
    direction_text = "%s %s %s" % (purpose, audio_dir.get("music_direction", ""),
                                   mood)
    dlow = direction_text.lower()
    if "tech" in dlow or "technology" in dlow:
        instrumentation = audio_dir.get("instrumentation") or "analog synth + soft pad + minimal percussion"
    elif "minimal" in dlow or "minimal" in str(mood).lower():
        instrumentation = audio_dir.get("instrumentation") or "soft pad + sparse piano/keys"
    else:
        instrumentation = audio_dir.get("instrumentation") or "soft pad + gentle rhythm"
    rhythmic_density = audio_dir.get("rhythmic_density") or (
        "sparse" if any(w in dlow for w in ("calm", "minimal", "soft", "quiet"))
        else "moderate")
    melodic_density = audio_dir.get("melodic_density") or (
        "low" if any(w in dlow for w in ("minimal", "calm")) else "moderate")
    harmonic_character = audio_dir.get("harmonic_character") or (
        "consonant, minimal movement" if any(w in dlow for w in ("calm", "minimal"))
        else "diatonic, gentle tension")

    # 结构（§61 例式：分段时间线）：由 beat purpose 与 sync 事件构造
    anchors = sorted(
        [{"time": 0.0, "kind": "start", "label": "start"}]
        + [{"time": float(b.get("t", 0)), "kind": "beat",
            "label": b.get("purpose") or "beat"} for b in beats]
        + [{"time": float(s["frame"]) / float(fps), "kind": "sync",
            "label": s.get("event") or "sync"} for s in syncs
           if s.get("frame") is not None],
        key=lambda a: a["time"])
    structure = []
    for i, anchor in enumerate(anchors):
        end_time = anchors[i + 1]["time"] if i + 1 < len(anchors) else duration
        if end_time <= anchor["time"]:
            continue
        structure.append({
            "segment": anchor["label"],
            "start_sec": round(anchor["time"], 3),
            "end_sec": round(end_time, 3),
            "kind": anchor["kind"],
            "description": "music event at %s (from %s)" % (
                anchor["label"], "Beat Map" if anchor["kind"] == "beat"
                else "video sync point" if anchor["kind"] == "sync" else "composition start"),
        })

    # sync_points：视频同步点 -> music event（§62：frame 120 product reveal）
    sync_points = []
    for s in syncs:
        frame = s.get("frame")
        if frame is None:
            continue
        sync_points.append({
            "frame": int(frame),
            "timestamp": round(int(frame) / float(fps), 3),
            "event": s.get("event") or "sync",
            "music_event": "musical accent / key-change aligned to '%s' (§62)" % (
                s.get("event") or "sync"),
        })
    for b in beats:
        sync_points.append({
            "frame": int(round(float(b.get("t", 0)) * fps)),
            "timestamp": float(b.get("t", 0)),
            "event": b.get("purpose") or "beat",
            "music_event": "beat-aligned event (Beat Map: %s)" % (
                b.get("purpose") or "beat"),
        })
    sync_points.sort(key=lambda p: p["frame"])

    loop = audio_dir.get("loop")
    if loop is None:
        loop = not any(w in purpose.lower() for w in
                       ("sting", "logo", "intro", "outro", "transition"))
    ending = _first_non_none(audio_dir.get("ending"),
                             "fade_out" if "calm" in str(mood).lower()
                             else "resolve_on_tonic")

    return {
        "spec_type": "MUSIC_SPEC",
        "purpose": purpose,
        "duration": duration,
        "bpm": bpm,
        "key": key,
        "meter": meter,
        "mood": mood,
        "energy": energy,
        "instrumentation": instrumentation,
        "rhythmic_density": rhythmic_density,
        "melodic_density": melodic_density,
        "harmonic_character": harmonic_character,
        "structure": structure,
        "sync_points": sync_points,
        "voiceover_priority": voiceover_priority,
        "loop": bool(loop),
        "ending": ending,
        "soundfont": soundfont,
        "mix_target": {
            "role": "bed" if loop else "featured",
            "level_dbfs": DUCK_BASE_LEVEL_DB,
            "duck_vs_voiceover_db": DUCK_VS_VOICEOVER_DB,
            "duck_important_db": DUCK_IMPORTANT_DB,
            "note": "music ducks -4dB under VO, -6dB under important sentence (§65)",
        },
        "note_plan": midi_note_events(
            beat_map or {}, key=key, bpm=bpm, fps=fps, energy=energy),
        "midi_policy": {
            "random_notes": False,
            "rule": "音符按 AUDIO_DIRECTION + Beat Map + sync points 确定性推导（§60），"
                    "不随机写音符",
            "producer": "FLUIDSYNTH" if soundfont else "LIBRARY_MUSIC",
        },
    }


def music_strategy(audio_direction, video_duration):
    """§52/§57 音乐策略。

    长片不默认 MIDI 整曲：Main Bed / Secondary Bed / Chapter Sting / Motif /
    Transition Music 结构；procedural 只做 Logo Sting / Intro / Outro /
    Chapter Transition / Short Bed / Beat Sync / Tonal Accent（§56）。
    """
    audio_dir = audio_direction or {}
    duration = float(video_duration or 0)
    direction = str(audio_dir.get("music_direction") or "").lower()

    if any(w in direction for w in ("procedural", "logo", "brand sting")):
        decision = "PROCEDURAL_MUSIC"
        reason = "方向明确要求定制/Logo 级 shot-sync 音乐；procedural 只做短元素（§56）"
    elif duration > 240:
        decision = "HYBRID_MUSIC"
        reason = "长片（>4min）：Library bed 垫底 + Procedural 做章节 Sting/Motif，不默认 MIDI 整曲（§52/§57）"
    else:
        decision = "LIBRARY_MUSIC"
        reason = "短片/中片：Library 主 Bed 效率最高；Procedural 仅用于 Logo Sting（sound-direction §Music Route）"

    if duration > 240:
        structure = [
            {"role": "main_bed", "source_route": "LIBRARY_MUSIC",
             "producer": "LIBRARY_MUSIC",
             "description": "贯穿全片的主背景乐（Library）"},
            {"role": "secondary_bed", "source_route": "LIBRARY_MUSIC",
             "producer": "LIBRARY_MUSIC",
             "description": "信息密集段/次章节的次级背景乐（Library）"},
            {"role": "chapter_sting", "source_route": "PROCEDURAL_MUSIC",
             "producer": "FLUIDSYNTH",
             "description": "章节进入/结束 Sting（MIDI+SoundFont）"},
            {"role": "motif", "source_route": "PROCEDURAL_MUSIC",
             "producer": "FLUIDSYNTH",
             "description": "Sonic Motif 短动机，品牌一致性"},
            {"role": "transition_music", "source_route": "PROCEDURAL_MUSIC",
             "producer": "FLUIDSYNTH",
             "description": "章节转场短音（Beat Sync / Tonal Accent）"},
        ]
    else:
        structure = [
            {"role": "main_bed", "source_route": "LIBRARY_MUSIC",
             "producer": "LIBRARY_MUSIC",
             "description": "主背景乐（Library）"},
            {"role": "logo_sting", "source_route": "PROCEDURAL_MUSIC",
             "producer": "FLUIDSYNTH",
             "description": "Logo/开头 Sting（MIDI+SoundFont）"},
        ]

    return {
        "decision": decision,
        "reason": reason,
        "video_duration_sec": duration,
        "structure": structure,
        "procedural_scope": list(PROCEDURAL_SCOPE),
        "full_track_procedural": False,
        "full_track_procedural_note": (
            "长片不默认 MIDI 整曲（§52/§57）：procedural 只做 Logo Sting / Intro / "
            "Outro / Chapter Transition / Short Bed / Beat Sync / Tonal Accent（§56）"),
    }


# ---------------------------------------------------------------------------
# Ducking / Ambience / Silence
# ---------------------------------------------------------------------------

def ducking_plan(audio_direction, storyboard_voiceover):
    """§65 Ducking 计划。

    - voice present -> music -4dB；
    - hero pause -> music 回到基础电平；
    - important sentence -> -6dB。

    storyboard_voiceover: [{start, end, text/sentence, important?}] 或空列表。
    """
    segments = storyboard_voiceover or []
    audio_dir = audio_direction or {}
    base_level = audio_dir.get("ducking_strategy") and (
        _parse_db(audio_dir.get("ducking_strategy")) or DUCK_BASE_LEVEL_DB) \
        or DUCK_BASE_LEVEL_DB

    events = []
    for seg in segments:
        start = float(seg.get("start", 0))
        end = float(seg.get("end", start + 1))
        text = " ".join(str(x) for x in
                        [seg.get("text"), seg.get("sentence")] if x)
        important = bool(seg.get("important")
                         or seg.get("importance") in ("high", "important")
                         or any(w in text.lower() for w in
                                ("important", "key", "critical", "remember",
                                 "核心", "关键", "注意")))
        events.append({
            "start": start,
            "end": end,
            "duck_db": DUCK_IMPORTANT_DB if important else DUCK_VS_VOICEOVER_DB,
            "reason": "important sentence (-6dB)" if important
                      else "voice present (-4dB)",
            "sentence": text[:120] or None,
        })

    # hero pause：VO 段间空隙 > 阈值 -> music 返回基础电平
    returns = []
    for i in range(len(segments) - 1):
        gap = float(segments[i + 1].get("start", 0)) - float(segments[i].get("end", 0))
        if gap > HERO_PAUSE_RETURN_GAP_SEC:
            returns.append({
                "start": float(segments[i].get("end", 0)),
                "end": float(segments[i + 1].get("start", 0)),
                "level_db": base_level,
                "reason": "hero pause -> music returns to base level (§65)",
            })

    return {
        "voice_present": bool(segments),
        "base_level_db": base_level,
        "duck_vs_voiceover_db": DUCK_VS_VOICEOVER_DB,
        "duck_important_db": DUCK_IMPORTANT_DB,
        "returns_on_hero_pause": bool(returns),
        "events": events,
        "returns": returns,
        "note": "no voiceover -> no ducking" if not segments else None,
    }


def _parse_db(text):
    """从字符串里抓 dB 数字，如 '-12dB' -> -12.0；失败 None。"""
    if not text:
        return None
    import re
    m = re.search(r"[-+]?\d+(\.\d+)?", str(text))
    return float(m.group(0)) if m else None


def ambience_plan(scene_context):
    """§66 Ambience 计划。

    scene_context: {setting, route, scene_type, ...}
    room tone / city / office / museum / nature；AI Video 场景 ambience 增强真实感。
    """
    ctx = scene_context or {}
    setting = str(ctx.get("setting") or "").lower()
    route = str(ctx.get("route") or "").lower()
    scene_type = str(ctx.get("scene_type") or "").lower()
    blob = "%s %s" % (setting, scene_type)

    mapping = [
        (("office", "work", "desk", "indoor workplace"), "office",
         "room tone + soft HVAC hum, keyboard ticks, distant chatter (subtle)",
         -24),
        (("city", "street", "urban", "traffic", "outdoor"), "city",
         "distant traffic low rumble + sparse crowd ambience", -18),
        (("museum", "gallery", "exhibition", "expo"), "museum",
         "quiet reverby room tone + footsteps + muffled voices", -26),
        (("nature", "forest", "park", "garden", "outdoor nature", "field"),
         "nature",
         "wind in leaves + birds + soft undergrowth texture", -20),
    ]
    ambience_type, elements, level = "room_tone", "room tone (neutral)", -22
    for words, atype, aelements, alevel in mapping:
        if any(w in blob for w in words):
            ambience_type, elements, level = atype, aelements, alevel
            break

    ai_video = route in ("ai_video", "generative_video") or "ai" in route
    return {
        "ambience_type": ambience_type,
        "level_db": level,
        "source": "AMBience registry/library; generated only as last resort",
        "elements": elements,
        "ai_video_reality_enhancement": {
            "enabled": ai_video,
            "note": ("AI Video 场景 ambience 用于增强真实感（§66）：给生成画面补 "
                     "room tone / 环境纹理，掩盖生成视频的声学空洞"),
        },
        "notes": ["持续低电平，不抢叙事；与 silence_policy 对齐"],
    }


def silence_check(shot_audio):
    """§67 Silence 检查：Audio Direction 要求 silence 时不自动填满。

    shot_audio: {shot_id, audio_requirements, requires_silence,
                 planned_audio|planned_sfx, ...}
    返回 (ok, notes)。
    """
    sa = shot_audio or {}
    requirements = str(sa.get("audio_requirements") or "").lower()
    silence_requested = bool(sa.get("requires_silence")) or any(
        w in requirements for w in
        ("silence", "silent", "pause", "quiet beat", "留白", "静音", "无声音"))
    planned = list(sa.get("planned_audio") or sa.get("planned_sfx") or [])
    notes = []
    if not silence_requested:
        notes.append("shot %s: 无 silence 要求，正常填充" % sa.get("shot_id"))
        return True, notes
    if planned:
        notes.append(
            "shot %s: Audio Direction 要求 silence，但存在计划音频 %r —— "
            "不得自动填满（§67），需移除或转 PRODUCTION_CONFLICT"
            % (sa.get("shot_id"), planned))
        return False, notes
    notes.append("shot %s: 保持 silence（beat before reveal），不要自动补音效"
                 % sa.get("shot_id"))
    return True, notes


# ---------------------------------------------------------------------------
# QA / Taste / Woosh
# ---------------------------------------------------------------------------

def sound_qa(spec, render_result):
    """§102 Sound QA 全项 + §103 loudness 规则。

    spec        : SFX_SPEC 或 MUSIC_SPEC
    render_result: {render_success, duration, sample_rate, channels,
                    peak_db, rms_db, silence_ratio, sync_offset_ms,
                    error, license, description}
    返回 (ok, checks[])。ok = 无 FAIL。
    """
    spec = spec or {}
    result = render_result or {}
    checks = []
    ok = True

    def _check(name, status, detail):
        nonlocal ok
        if status == "FAIL":
            ok = False
        checks.append({"check": name, "status": status, "detail": detail})

    # 1. 渲染成功 / 无错误
    if result.get("error"):
        _check("render_success", "FAIL", "render error: %s" % result["error"])
    elif result.get("render_success") is False:
        _check("render_success", "FAIL", "render reported failure")
    else:
        _check("render_success", "PASS", "no render errors")

    # 2. clipping（§103：no clipping）
    peak = result.get("peak_db")
    if peak is None:
        _check("clipping", "WARN", "peak_db 未提供，无法核验")
    elif peak >= -0.5:
        _check("clipping", "FAIL", "peak %.1f dBFS >= -0.5 -> clipping risk (§103)"
               % peak)
    elif peak >= -1.0:
        _check("clipping", "WARN", "peak %.1f dBFS 接近上限（headroom 偏小）" % peak)
    else:
        _check("clipping", "PASS", "peak %.1f dBFS, no clipping" % peak)

    # 3. silence errors（无意义静音）
    silence = result.get("silence_ratio")
    if silence is None:
        _check("silence_errors", "WARN", "silence_ratio 未提供，无法核验")
    elif silence > 0.9 and (result.get("duration") or 1) > 1.0:
        _check("silence_errors", "FAIL", "silence_ratio %.0f%% -> 疑似缺失音频" % (silence * 100))
    elif silence > 0.5:
        _check("silence_errors", "WARN", "silence_ratio %.0f%% 偏高" % (silence * 100))
    else:
        _check("silence_errors", "PASS", "silence_ratio %.0f%%" % (silence * 100))

    # 4. duration
    expected = spec.get("duration")
    actual = result.get("duration")
    if expected is None or actual is None:
        _check("duration", "WARN", "duration 信息不全，无法精确核验")
    else:
        diff = abs(float(actual) - float(expected)) / max(float(expected), 1e-6)
        if diff > 0.15:
            _check("duration", "FAIL",
                   "duration %.2fs vs spec %.2fs (off %.0f%%)" % (actual, expected, diff * 100))
        else:
            _check("duration", "PASS", "duration %.2fs matches spec" % actual)

    # 5. sync（frame/timestamp 精确；容差 1 帧 @30fps）
    offset = result.get("sync_offset_ms")
    if offset is None:
        _check("sync", "WARN", "sync_offset_ms 未提供，无法核验")
    elif offset > 100:
        _check("sync", "FAIL", "sync offset %.0fms > 100ms" % offset)
    elif offset > 33:
        _check("sync", "WARN", "sync offset %.0fms > 1 帧(33ms)（§48 frame 级同步）" % offset)
    else:
        _check("sync", "PASS", "sync offset %.0fms within 1 frame" % offset)

    # 6. sample rate（默认 44100）
    sr = result.get("sample_rate")
    if sr is None:
        _check("sample_rate", "WARN", "sample_rate 未提供")
    elif int(sr) != 44100:
        _check("sample_rate", "FAIL", "sample_rate %s != 44100" % sr)
    else:
        _check("sample_rate", "PASS", "sample_rate 44100 Hz")

    # 7. channel format（音乐立体声 / SFX 单声道默认）
    channels = result.get("channels")
    expected_chan = 2 if spec.get("spec_type") == "MUSIC_SPEC" else 1
    if channels is None:
        _check("channel_format", "WARN", "channels 未提供")
    elif int(channels) != expected_chan:
        _check("channel_format", "WARN",
               "channels=%s, 期望 %s（按 spec_type）" % (channels, expected_chan))
    else:
        _check("channel_format", "PASS", "channels=%s matches" % channels)

    # 8. excessive loudness（§103：reasonable gain / consistent level，
    #    不搞广播级 mastering——不强制 LUFS）
    rms = result.get("rms_db")
    lufs = result.get("lufs")
    if lufs is not None and lufs > -14:
        _check("excessive_loudness", "WARN", "loudness %.1f LUFS 偏高（合理增益即可，不做广播级 mastering）" % lufs)
    elif rms is not None and rms > -8:
        _check("excessive_loudness", "FAIL", "RMS %.1f dB 过高（excessive loudness）" % rms)
    elif peak is not None and peak >= -0.5:
        _check("excessive_loudness", "FAIL", "peak 触发 clipping，属于 excessive loudness")
    else:
        _check("excessive_loudness", "PASS", "gain reasonable, level consistent (§103)")

    # 9. license
    req = spec.get("license_requirement") or {}
    lic = result.get("license")
    if req.get("commercial_use"):
        if not lic:
            _check("license", "FAIL", "license metadata 缺失（Phase 4 §69 必须逐条落盘）")
        elif lic.get("commercial_use") is False:
            _check("license", "FAIL", "license 不允许商用：%s" % lic.get("license_type"))
        else:
            _check("license", "PASS", "license %s commercial_use ok" % lic.get("license_type"))
    else:
        _check("license", "PASS", "非商用项目，无 license 限制")

    # 10. style fit
    desc = str(result.get("description") or "")
    spec_style = str(spec.get("style") or spec.get("character") or "")
    if not desc:
        _check("style_fit", "WARN", "结果无 description，无法核验 style fit")
    else:
        mismatch = [w for w in (spec.get("avoid") or []) if w.lower() in desc.lower()]
        if mismatch:
            _check("style_fit", "FAIL", "结果描述命中 avoid 词 %r（style fit 不符）" % mismatch)
        elif spec_style and spec_style.lower() not in desc.lower():
            _check("style_fit", "WARN", "结果描述 %r 与 spec style %r 对不上" % (desc, spec_style))
        else:
            _check("style_fit", "PASS", "style matches")

    return ok, checks


def woosh_policy():
    """§68 Sony Woosh 实验策略。

    Woosh 标 EXPERIMENTAL；License/commercial 不满足时禁用于商业项目。
    """
    return {
        "status": "EXPERIMENTAL",
        "provider": "SonyResearch/Woosh",
        "role": "generative_sfx_experimental",
        "default_allowed": False,
        "commercial_rule": (
            "License/commercial 不满足时禁用于商业项目（§68）——"
            "使用前必须 license_review + commercial_use 核验"),
        "required_checks": ["license_review", "commercial_use_verification",
                            "project_approval"],
        "do_not": ["use_in_production_without_license_review",
                   "treat_as_production_stable", "rely_as_default_sfx"],
        "notes": "仅作为 SFX 搜索 Tier 4 兜底（§43），命中更早 Tier 时优先使用",
    }


def asset_taste_review(asset_desc, audio_direction):
    """§104/§106 审美复核：结果与 Audio Direction 冲突 -> REVISION_REQUESTED。

    例：AD=subtle 而结果 massive boom -> not ok。
    返回 (ok, notes[])。
    """
    desc = asset_desc or {}
    audio_dir = audio_direction or {}
    notes = []

    desc_text = " ".join(str(x) for x in [
        desc.get("character"), desc.get("name"), desc.get("description"),
        " ".join(desc.get("tags") or [])] if x).lower()

    # 1. 命中 Avoid 清单
    avoid = list(audio_dir.get("avoid") or [])
    hit = [w for w in avoid if w.lower() in desc_text]
    if hit:
        notes.append("REVISION_REQUESTED: 结果命中 Audio Direction avoid 词 %r"
                     % hit)
        return False, notes

    # 2. subtle 方向 vs 重型结果
    subtle_lang = str(audio_dir.get("sfx_language")
                      or audio_dir.get("music_direction") or "").lower()
    subtle = any(w in subtle_lang for w in ("subtle", "minimal", "soft", "quiet", "克制"))
    heavy_words = ("massive", "boom", "cinematic", "epic", "explosive", "huge",
                   "aggressive", "loud", "爆炸", "宏大")
    if subtle and any(w in desc_text for w in heavy_words):
        notes.append("REVISION_REQUESTED: Audio Direction=%s（subtle），"
                     "而结果 character=%r 为重型风格（§104/§106）"
                     % (subtle_lang, desc.get("character")))
        return False, notes

    notes.append("taste 核验通过：结果与 Audio Direction 一致")
    return True, notes


# ---------------------------------------------------------------------------
# CLI 自检入口
# ---------------------------------------------------------------------------

def main():
    """最小冒烟自检（对应 P5-5 自检脚本的纯逻辑部分）。"""
    sfx = build_sfx_spec(
        {"request_id": "PR-020", "shot_id": "S014", "duration": 2.0,
         "audio_requirements": "soft UI confirmation"},
        {"sfx_language": "subtle minimal"},
        {"click": "soft tick", "character": "soft"})
    assert sfx["category"] in ("UI", "CLICK") or "ui" in sfx["category"].lower()
    assert sfx["sync_time"] is not None

    mus = build_music_spec(
        {"music_direction": "minimal technology bed", "bpm_range": "100-110",
         "mood": "calm"},
        {"beats": [{"t": 0, "purpose": "intro"}, {"t": 34, "purpose": "hero reveal"}]},
        [{"frame": 120, "event": "product reveal"}])
    assert mus["bpm"] >= 100 and mus["structure"] != []
    assert any(p["frame"] == 120 for p in mus["sync_points"])

    ok, notes = asset_taste_review({"character": "massive cinematic boom"},
                                   {"avoid": ["boom", "cinematic"]})
    assert not ok
    print("SOUND ENGINE SELF-CHECK OK")


if __name__ == "__main__":
    main()
