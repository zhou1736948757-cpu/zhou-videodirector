#!/usr/bin/env python3
"""validate.py — 外部视频技术校验（Phase-6 §100 / §69；P6-04）.

对探针结果与文件本身做确定性技术校验，输出 ``{ok, issues[], warnings[],
checks{...}}``。只报告不修改，绝不删除/覆盖任何输入文件。

校验项（§100 清单）：
1. file readable —— 文件存在、可读、体积 > 0
2. duration valid —— 时长 > 0
3. frame count    —— 帧数 ≈ duration×fps，容差 ±2 帧
4. corruption     —— `ffmpeg -v error -i <path> -f null -` 解码全程，捕获任何
                     错误输出 / 非零退出码
5. black frame    —— `blackdetect` 采样：单段黑帧 ≥3s 或黑帧总时长占比 >50% → issue
6. freeze         —— `freezedetect` 采样：连续冻结 ≥2s → issue

所有阈值写死为本模块常量（docstring 语义随 §100 对齐），保证确定性：
同一文件在任何机器上得到相同判定。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from .probe import probe_video, DEFAULT_TIMEOUT

FFMPEG = "/opt/homebrew/bin/ffmpeg"

# ---------------------------------------------------------------------------
# 确定性阈值（§100；写死，禁止运行时更改）
# ---------------------------------------------------------------------------
MIN_DURATION_SECONDS = 0.05         # duration 必须 > 50ms
FRAME_COUNT_TOLERANCE = 2           # 帧数允许误差 ±2 帧
BLACKDETECT_MIN_DURATION = 0.5      # blackdetect 最小黑段（d 参数，秒）
BLACKDETECT_PIX_TH = 0.10           # blackdetect 像素阈值（pix_th，0-1）
BLACK_SINGLE_MAX = 3.0              # 单段黑帧 ≥3s → black_frame issue
BLACK_COVERAGE_MAX = 0.5            # 黑帧总时长占比 >50% → black_frame issue
FREEZEDETECT_NOISE = "-60dB"        # freezedetect 噪声阈值（n 参数）
FREEZEDETECT_MIN_DURATION = 1.0     # freezedetect 最小检测段（d 参数，秒）
FREEZE_SINGLE_MAX = 2.0             # 连续冻结 ≥2s → freeze issue
DECODE_TIMEOUT = DEFAULT_TIMEOUT    # 所有 ffmpeg 调用超时（默认 120s）

_BLACK_DURATION_RE = re.compile(r"black_duration:\s*([0-9.]+)")
_FREEZE_DURATION_RE = re.compile(r"freeze_duration:\s*([0-9.]+)")
_FRAME_STATS_RE = re.compile(r"frame=\s*(\d+)")


def _run_ffmpeg(args: list, timeout: int = DECODE_TIMEOUT) -> dict:
    """运行 ffmpeg，返回 {returncode, stdout, stderr}；调用失败也返回 dict 不抛崩。"""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"ffmpeg 调用失败: {exc}"}
    return {"returncode": proc.returncode, "stdout": proc.stdout or "",
            "stderr": proc.stderr or ""}


def _decode_pass(path: str, extra_vf: Optional[str] = None,
                 timeout: int = DECODE_TIMEOUT) -> dict:
    """一次解码全程（-f null -）；`extra_vf` 叠加检测滤镜（blackdetect/freezedetect）。

    返回 {returncode, stderr, errors, frames}；errors 为 stderr 中的错误行列表。
    默认 log level 下 `frame=` 进度行可用于回退帧计数。
    """
    args = [FFMPEG, "-i", str(path)]
    if extra_vf:
        args += ["-vf", extra_vf, "-an"]
    args += ["-f", "null", "-"]
    out = _run_ffmpeg(args, timeout=timeout)
    errors = [ln for ln in out["stderr"].splitlines()
              if re.search(r"(?i)\berror\b|invalid data|corrupt", ln)]
    frames = [int(m) for m in _FRAME_STATS_RE.findall(out["stderr"])]
    return {
        "returncode": out["returncode"],
        "stderr": out["stderr"],
        "errors": errors,
        "frames": max(frames) if frames else None,
    }


def _black_segments(path: str, duration: float,
                    timeout: int = DECODE_TIMEOUT) -> list:
    """blackdetect 采样；返回检测到的黑段时长列表（秒）。"""
    vf = f"blackdetect=d={BLACKDETECT_MIN_DURATION}:pix_th={BLACKDETECT_PIX_TH}"
    out = _run_ffmpeg([FFMPEG, "-i", str(path), "-vf", vf, "-an", "-f", "null", "-"],
                      timeout=timeout)
    segs = [float(m) for m in _BLACK_DURATION_RE.findall(out["stderr"])]
    return segs


def _freeze_segments(path: str, timeout: int = DECODE_TIMEOUT) -> list:
    """freezedetect 采样；返回已结束冻结段的时长列表（秒）。

    冻结持续到 EOF 时 ffmpeg 只打印 freeze_start（无 duration），此时保守处理：
    不判 freeze（无法确定时长），避免误报。
    """
    vf = (f"freezedetect=n={FREEZEDETECT_NOISE}:"
          f"d={FREEZEDETECT_MIN_DURATION}")
    out = _run_ffmpeg([FFMPEG, "-i", str(path), "-vf", vf, "-an", "-f", "null", "-"],
                      timeout=timeout)
    return [float(m) for m in _FREEZE_DURATION_RE.findall(out["stderr"])]


def _fallback_frame_count(path: str, timeout: int = DECODE_TIMEOUT) -> Optional[int]:
    """nb_frames 缺失时从解码进度行提取实际帧数（一次解码，慢但准确）。"""
    out = _run_ffmpeg([FFMPEG, "-i", str(path), "-f", "null", "-"],
                      timeout=timeout)
    frames = [int(m) for m in _FRAME_STATS_RE.findall(out["stderr"])]
    return max(frames) if frames else None


def technical_validate(path, probe: Optional[dict] = None,
                       timeout: int = DECODE_TIMEOUT) -> dict:
    """技术校验入口（§100）。

    `probe` 可复用外部已探针结果（省一次 ffprobe）；缺省自动探针。
    返回 ``{ok, issues[], warnings[], checks{...}}``，不抛异常。
    """
    p = Path(path)
    issues: list = []
    warnings: list = []
    checks: dict[str, Any] = {}

    # 1) 文件可读（§100 file readable）
    readable = (p.is_file() and os.access(p, os.R_OK)
                and p.stat().st_size > 0 if p.exists() else False)
    checks["file_readable"] = bool(readable)
    if not readable:
        issues.append(f"file_readable: 文件不可读/不存在/空文件 {p}")

    # 2) 探针
    if probe is None:
        probe = probe_video(str(p), timeout=timeout)
    checks["probe_ok"] = bool(probe.get("ok"))
    if not probe.get("ok"):
        issues.append(f"probe failed: {probe.get('error')}")

    duration = probe.get("duration")
    checks["duration"] = duration
    if duration is None or duration <= MIN_DURATION_SECONDS:
        issues.append(f"duration invalid: 时长={duration}（需 > {MIN_DURATION_SECONDS}s）")

    # 3) 帧数 ≈ duration×fps（±2）
    fps = (probe.get("video") or {}).get("fps")
    nb_frames = (probe.get("video") or {}).get("nb_frames")
    if duration and fps:
        expected = int(round(duration * fps))
        actual = nb_frames
        if actual is None:
            actual = _fallback_frame_count(str(p), timeout=timeout)
            if actual is None:
                warnings.append("frame count: 无法获取实际帧数（nb_frames 缺失且解码计数失败），跳过帧数校验")
        checks["expected_frames"] = expected
        checks["actual_frames"] = actual
        if actual is not None and abs(actual - expected) > FRAME_COUNT_TOLERANCE:
            issues.append(
                f"frame count: 实际 {actual} 帧 ≠ 期望 {expected} 帧"
                f"（duration {duration:.3f}s × fps {fps}，容差 ±{FRAME_COUNT_TOLERANCE}）")
        checks["frame_count_ok"] = actual is None or abs(actual - expected) <= FRAME_COUNT_TOLERANCE
    else:
        checks["frame_count_ok"] = None
        warnings.append("frame count: 缺 duration 或 fps，无法校验帧数")

    # 4) corruption（ffmpeg -v error 解码全程）
    decode = _decode_pass(str(p), timeout=timeout)
    corruption_errors = list(decode["errors"])
    checks["corruption_errors"] = corruption_errors
    if decode["returncode"] != 0 or corruption_errors:
        # 打开即失败也属于 corruption；保留前几行便于追溯
        first_lines = (corruption_errors or decode["stderr"].splitlines())[:5]
        issues.append("corruption: 解码报告错误 → " + " | ".join(first_lines))
    checks["corruption_ok"] = not (decode["returncode"] != 0 or corruption_errors)

    # 5) black frame
    black_segs = _black_segments(str(p), duration or 0.0, timeout=timeout) \
        if probe.get("ok") and duration else []
    checks["black_segments"] = black_segs
    if black_segs:
        worst = max(black_segs)
        if worst >= BLACK_SINGLE_MAX:
            issues.append(f"black_frame: 单段黑帧 {worst:.2f}s ≥ {BLACK_SINGLE_MAX}s")
        if duration and duration > 0:
            coverage = sum(black_segs) / duration
            if coverage > BLACK_COVERAGE_MAX:
                issues.append(
                    f"black_frame: 黑帧总占比 {coverage:.0%} > {BLACK_COVERAGE_MAX:.0%}")

    # 6) freeze
    freeze_segs = _freeze_segments(str(p), timeout=timeout) \
        if probe.get("ok") else []
    checks["freeze_segments"] = freeze_segs
    if freeze_segs and max(freeze_segs) >= FREEZE_SINGLE_MAX:
        issues.append(f"freeze: 连续冻结 {max(freeze_segs):.2f}s ≥ {FREEZE_SINGLE_MAX}s")

    checks["audio_streams"] = probe.get("audio_streams")
    checks["codec"] = (probe.get("video") or {}).get("codec")
    checks["resolution"] = {
        "w": (probe.get("video") or {}).get("width"),
        "h": (probe.get("video") or {}).get("height"),
    }
    checks["fps"] = fps

    return {
        "ok": not issues,
        "issues": issues,
        "warnings": warnings,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    assert BLACK_SINGLE_MAX == 3.0
    assert FRAME_COUNT_TOLERANCE == 2
    r = technical_validate("/nonexistent/file.mp4")
    assert r["ok"] is False and r["issues"]
    print("external-visual/validate selftest OK")


if __name__ == "__main__":
    selftest()
