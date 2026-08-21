#!/usr/bin/env python3
"""probe.py — 外部视频技术探针（Phase-6 §69 / §48 / §100；P6-04）.

对任意外部视频文件运行 `ffprobe` 并提取结构化技术信息：
duration / resolution / fps / codec / bitrate / audio_streams / aspect_ratio /
rotation / color 元数据，供 validate / normalize / proxy / ingest 各环节消费。

设计约束（对齐 implementation_constraints）：
- **stdlib only** + subprocess 调 ffprobe；所有调用带超时（默认 120s）。
- **优雅降级**：ffprobe 失败返回 ``{"ok": False, "error": ...}``，不抛异常不崩。
- **确定性**：同一文件 → 相同 probe 输出（fps 用 ``r_frame_rate`` 分数化简；
  旋转优先读 ``side_data`` 的 Display Matrix rotation，其次读流/容器 tags 的
  rotate/ROTATE 键；全部输出字典按稳定顺序组织）。

返回 dict 顶层键（全部存在，值为 None 表示不可得）：
    ok / path / format_name / format_long_name / duration / size_bytes /
    bitrate / streams / video{...} / audio[...] / audio_streams / has_audio
"""

from __future__ import annotations

import json
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any, Optional

FFPROBE = "/opt/homebrew/bin/ffprobe"
DEFAULT_TIMEOUT = 120


def _run_ffprobe(path: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """运行 ffprobe 输出 JSON；任何失败返回 {'error': ...}（不抛崩）。"""
    cmd = [
        FFPROBE, "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": f"ffprobe 调用失败: {exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {"error": f"ffprobe 退出码 {proc.returncode}: {detail}"}
    try:
        data = json.loads(proc.stdout)
    except ValueError as exc:
        return {"error": f"ffprobe 输出非 JSON: {exc}"}
    if not isinstance(data, dict):
        return {"error": "ffprobe 输出结构非法"}
    return data


def simplify_fps(r_frame_rate: Optional[str]) -> Optional[float]:
    """把 r_frame_rate（如 '30000/1001' / '30/1'）化简为 float；不可解析 → None。"""
    if not r_frame_rate:
        return None
    text = str(r_frame_rate).strip()
    try:
        if "/" in text:
            num, _, den = text.partition("/")
            frac = Fraction(int(num), int(den) if int(den) else 1)
        else:
            frac = Fraction(int(text), 1)
    except (ValueError, ZeroDivisionError):
        return None
    if frac <= 0:
        return None
    return float(frac.numerator) / float(frac.denominator)


def _to_float(value) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def detect_rotation(stream: dict) -> Optional[int]:
    """旋转检测（§69）：优先 side_data Display Matrix rotation；其次 tags rotate/ROTATE。

    返回 0/90/180/270 或 None（未知）。
    """
    for item in stream.get("side_data_list") or []:
        if isinstance(item, dict) and "rotation" in item:
            try:
                rot = int(round(float(item["rotation"])))
            except (TypeError, ValueError):
                continue
            if rot in (0, 90, 180, 270):
                return rot
    tags = stream.get("tags") or {}
    for key, value in tags.items():
        if str(key).lower() in ("rotate", "rotation"):
            try:
                rot = int(str(value).strip())
            except (TypeError, ValueError):
                continue
            if rot in (0, 90, 180, 270):
                return rot
    return None


def _aspect_ratio(stream: dict) -> Optional[str]:
    dar = stream.get("display_aspect_ratio")
    if dar:
        return str(dar)
    w = _to_int(stream.get("width"))
    h = _to_int(stream.get("height"))
    if w and h:
        g = _gcd(w, h)
        return f"{w // g}:{h // g}"
    return None


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a or 1


def probe_video(path, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """探针入口：path（str/Path）→ 结构化技术信息 dict。

    失败（文件缺失 / ffprobe 报错）→ ``{"ok": False, "error": ..., "path": ...}``。
    """
    p = Path(path)
    result: dict[str, Any] = {
        "ok": True,
        "path": str(p),
        "format_name": None,
        "format_long_name": None,
        "duration": None,
        "size_bytes": None,
        "bitrate": None,
        "streams": 0,
        "video": None,
        "audio": [],
        "audio_streams": 0,
        "has_audio": False,
    }
    if not p.is_file():
        return {"ok": False, "path": str(p), "error": f"文件不存在: {p}"}

    raw = _run_ffprobe(str(p), timeout=timeout)
    if "error" in raw:
        result.update({"ok": False, "error": raw["error"]})
        return result

    fmt = raw.get("format") or {}
    result["format_name"] = fmt.get("format_name")
    result["format_long_name"] = fmt.get("format_long_name")
    result["duration"] = _to_float(fmt.get("duration"))
    result["size_bytes"] = _to_int(fmt.get("size"))
    result["bitrate"] = _to_int(fmt.get("bit_rate"))
    result["streams"] = len(raw.get("streams") or [])

    video = None
    audio_streams = []
    for stream in raw.get("streams") or []:
        ctype = stream.get("codec_type")
        if ctype == "video" and video is None:
            video = {
                "codec": stream.get("codec_name"),
                "codec_long_name": stream.get("codec_long_name"),
                "profile": stream.get("profile"),
                "width": _to_int(stream.get("width")),
                "height": _to_int(stream.get("height")),
                "fps": simplify_fps(stream.get("r_frame_rate")),
                "avg_fps": simplify_fps(stream.get("avg_frame_rate")),
                "nb_frames": _to_int(stream.get("nb_frames")),
                "pix_fmt": stream.get("pix_fmt"),
                "aspect_ratio": _aspect_ratio(stream),
                "rotation": detect_rotation(stream),
                "bitrate": _to_int(stream.get("bit_rate")),
                "color_space": stream.get("color_space"),
                "color_transfer": stream.get("color_transfer"),
                "color_primaries": stream.get("color_primaries"),
                "color_range": stream.get("color_range"),
                "tags": dict(stream.get("tags") or {}),
            }
        elif ctype == "audio":
            audio_streams.append({
                "codec": stream.get("codec_name"),
                "codec_long_name": stream.get("codec_long_name"),
                "channels": _to_int(stream.get("channels")),
                "sample_rate": _to_int(stream.get("sample_rate")),
                "duration": _to_float(stream.get("duration")),
                "bit_rate": _to_int(stream.get("bit_rate")),
            })
    result["video"] = video
    result["audio"] = audio_streams
    result["audio_streams"] = len(audio_streams)
    result["has_audio"] = len(audio_streams) > 0
    return result


# ---------------------------------------------------------------------------
# 自检（确定性断言）
# ---------------------------------------------------------------------------

def selftest() -> None:
    assert simplify_fps("30/1") == 30.0
    assert abs(simplify_fps("30000/1001") - 29.97002997002997) < 1e-9
    assert simplify_fps("25") == 25.0
    assert simplify_fps("0/0") is None
    assert simplify_fps(None) is None
    assert detect_rotation({"side_data_list": [{"rotation": 90}]}) == 90
    assert detect_rotation({"tags": {"ROTATE": "270"}}) == 270
    assert detect_rotation({"tags": {}}) is None
    r = probe_video("/nonexistent/file.mp4")
    assert r["ok"] is False and "error" in r
    print("external-visual/probe selftest OK")


if __name__ == "__main__":
    selftest()
