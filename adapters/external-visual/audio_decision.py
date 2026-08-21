#!/usr/bin/env python3
"""audio_decision.py — 外部视频音频行为决策（Phase-6 §83-84；P6-04）.

决定素材音频的去向：``KEEP / MUTE / USE_AS_AMBIENCE / EXTRACT / REPLACE``。

规则（全部确定性，按优先级从上到下，命中即停）：
1. ``packet_audio_requirement`` 显式给出合法模式 → 采用之；但若 Audio Direction
   明确要求静音且要求是 KEEP/USE_AS_AMBIENCE/EXTRACT，则 Audio Direction 覆盖
   （§84：必须符合 Audio Direction）。
2. 无音轨 → ``MUTE``，语义记 ``none``（无音可保，§83）。
3. Audio Direction ``silence_policy`` 含静音标记 → ``MUTE``。
4. Audio Direction ``ambience`` 含保留标记 → ``USE_AS_AMBIENCE``。
5. AI 生成自带音频（``ai_generated=True``）且无显式要求 → ``MUTE``
   （§84：AI 生成自带音频不默认使用，必须符合 Audio Direction）。
6. 其余（真实素材 / 用户上传等）→ ``KEEP``（默认保留原音）。

阈值/标记词为模块常量（写死），保证同输入同输出。
"""

from __future__ import annotations

from typing import Optional

AUDIO_MODES = ("KEEP", "MUTE", "USE_AS_AMBIENCE", "EXTRACT", "REPLACE")

# Audio Direction 明确要求静音的标记（silence_policy 字段，小写匹配）
_SILENCE_MARKERS = (
    "mute", "muted", "silence", "silent", "silence_policy",
    "静音", "无声", "无音", "不用原音",
)
# Audio Direction 希望保留/使用素材原音的标记（ambience 字段，小写匹配）
_AMBIENCE_KEEP_MARKERS = (
    "keep", "use", "保留", "使用", "ambience", "环境声", "原音",
)


def _field_has_marker(value, markers: tuple) -> bool:
    if not value:
        return False
    text = str(value).lower()
    return any(mk.lower() in text for mk in markers)


def decide_audio(probe: dict, audio_direction=None,
                 packet_audio_requirement: Optional[str] = None, *,
                 ai_generated: bool = False, source_type: Optional[str] = None) -> str:
    """返回音频行为模式（KEEP/MUTE/USE_AS_AMBIENCE/EXTRACT/REPLACE）。

    probe：probe.py 的 probe_video() 输出；audio_direction：项目 Audio Direction
    dict（audio-direction.schema.json）；packet_audio_requirement：生成包显式要求。
    """
    return decide_audio_detailed(
        probe, audio_direction=audio_direction,
        packet_audio_requirement=packet_audio_requirement,
        ai_generated=ai_generated, source_type=source_type,
    )["mode"]


def decide_audio_detailed(probe: dict, audio_direction=None,
                          packet_audio_requirement: Optional[str] = None, *,
                          ai_generated: bool = False,
                          source_type: Optional[str] = None) -> dict:
    """同 decide_audio，但返回 ``{mode, reason, has_audio, ai_generated}``（供元数据）。"""
    has_audio = bool(probe and probe.get("audio_streams", 0) > 0)
    direction = audio_direction if isinstance(audio_direction, dict) else {}
    req = str(packet_audio_requirement or "").strip().upper()
    req_valid = req in AUDIO_MODES

    # 1) 显式 packet 要求（§84：须符合 Audio Direction，冲突时方向优先）
    if req_valid:
        direction_silence = _field_has_marker(direction.get("silence_policy"),
                                              _SILENCE_MARKERS)
        if direction_silence and req in ("KEEP", "USE_AS_AMBIENCE", "EXTRACT"):
            return {"mode": "MUTE",
                    "reason": ("packet_audio_requirement=%s 被 Audio Direction 覆盖："
                               "silence_policy 要求静音" % req),
                    "has_audio": has_audio, "ai_generated": bool(ai_generated)}
        return {"mode": req, "reason": "来自 packet_audio_requirement 显式要求",
                "has_audio": has_audio, "ai_generated": bool(ai_generated)}

    # 2) 无音轨 → MUTE（semantic none）
    if not has_audio:
        return {"mode": "MUTE", "reason": "无音轨（semantic: none）",
                "has_audio": False, "ai_generated": bool(ai_generated)}

    # 3) Audio Direction silence_policy 要求静音
    if _field_has_marker(direction.get("silence_policy"), _SILENCE_MARKERS):
        return {"mode": "MUTE", "reason": "Audio Direction silence_policy 要求静音",
                "has_audio": True, "ai_generated": bool(ai_generated)}

    # 4) Audio Direction ambience 希望保留原音作环境声
    if _field_has_marker(direction.get("ambience"), _AMBIENCE_KEEP_MARKERS):
        return {"mode": "USE_AS_AMBIENCE",
                "reason": "Audio Direction ambience 要求保留原音作环境声",
                "has_audio": True, "ai_generated": bool(ai_generated)}

    # 5) AI 生成自带音频不默认使用（§84）
    if ai_generated:
        return {"mode": "MUTE",
                "reason": "AI 生成自带音频，无 Audio Direction 指示，不默认使用（§84）",
                "has_audio": True, "ai_generated": True}

    # 6) 默认保留
    return {"mode": "KEEP", "reason": "真实素材/用户素材音频默认保留",
            "has_audio": True, "ai_generated": False}


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    no_audio = {"audio_streams": 0}
    with_audio = {"audio_streams": 1}
    # 无音轨 → MUTE none
    assert decide_audio(no_audio) == "MUTE"
    # 显式要求
    assert decide_audio(with_audio, packet_audio_requirement="EXTRACT") == "EXTRACT"
    assert decide_audio(with_audio, packet_audio_requirement="mute") == "MUTE"
    # Audio Direction 静音覆盖 EXTRACT
    d = {"silence_policy": "全程静音（mute），无环境声"}
    assert decide_audio(with_audio, audio_direction=d,
                        packet_audio_requirement="EXTRACT") == "MUTE"
    # ambience 保留
    d2 = {"ambience": "keep 原始环境声作为 ambience"}
    assert decide_audio(with_audio, audio_direction=d2) == "USE_AS_AMBIENCE"
    # AI 生成自带音频默认不适用
    assert decide_audio(with_audio, ai_generated=True) == "MUTE"
    # 真实素材默认保留
    assert decide_audio(with_audio) == "KEEP"
    detail = decide_audio_detailed(no_audio)
    assert detail["mode"] == "MUTE" and detail["reason"].startswith("无音轨")
    print("external-visual/audio_decision selftest OK")


if __name__ == "__main__":
    selftest()
