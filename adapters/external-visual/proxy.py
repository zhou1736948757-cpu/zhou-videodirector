#!/usr/bin/env python3
"""proxy.py — 代理文件生成（Phase-6 §46；P6-04）.

为大型 AI Video / Footage 生成 1080p H.264 代理，供剪映 Preview 使用；原始文件
永不动（§46 / §47）。

触发条件（§46 "4K/大文件"）：
- 分辨率 ≥ 3840×2160（4K 及以上），或
- 文件体积 ≥ 500MB（LARGE_FILE_BYTES）

未触发（小文件）→ ``proxy_path`` = 原文件路径（声明为 proxy），并记录 rationale。
生成命名：``{stem}_proxy.mp4``（默认 stem = 源文件名去扩展名），输出到 proxy_dir
（默认源文件所在目录）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .probe import probe_video, DEFAULT_TIMEOUT

FFMPEG = "/opt/homebrew/bin/ffmpeg"

# 确定性阈值（§46；写死）
PROXY_HEIGHT = 1080              # 代理高度
PROXY_TRIGGER_WIDTH = 3840       # 4K 触发宽度
PROXY_TRIGGER_HEIGHT = 2160      # 4K 触发高度
LARGE_FILE_BYTES = 500 * 1024 * 1024   # ≥500MB 视为大文件
PROXY_PRESET = "veryfast"
PROXY_CRF = 23
PROXY_SUFFIX = "_proxy.mp4"


def _run_ffmpeg(args: list, timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"ffmpeg 调用失败: {exc}"}
    return {"returncode": proc.returncode, "stdout": proc.stdout or "",
            "stderr": proc.stderr or ""}


def proxy_needed(probe: dict) -> tuple:
    """判定是否需要代理，返回 (needed: bool, rationale: str)。确定性。"""
    video = probe.get("video") or {}
    w = video.get("width")
    h = video.get("height")
    size = probe.get("size_bytes") or 0
    reasons = []
    if w is not None and h is not None:
        if w >= PROXY_TRIGGER_WIDTH or h >= PROXY_TRIGGER_HEIGHT:
            reasons.append(f"分辨率 {w}x{h} ≥ 4K（{PROXY_TRIGGER_WIDTH}x{PROXY_TRIGGER_HEIGHT}）")
    if size >= LARGE_FILE_BYTES:
        reasons.append(f"文件体积 {size / (1024 * 1024):.0f}MB ≥ 500MB")
    if reasons:
        return True, "；".join(reasons)
    return False, (
        f"源分辨率 {w or '?'}x{h or '?'} 未达 4K 且体积"
        f" {size / (1024 * 1024):.0f}MB < 500MB，直接用原文件作 proxy（§46 小文件）")


def make_proxy(path, probe: Optional[dict] = None, proxy_dir=None,
               out_stem: Optional[str] = None,
               timeout: int = DEFAULT_TIMEOUT) -> dict:
    """代理入口。

    返回 {proxy_path, generated, rationale, width, height}。
    - ``generated=False``：proxy = 原文件（声明式，§46 小文件路径）。
    - ``generated=True``：产出 ``{stem}_proxy.mp4``，原始文件不动。
    """
    src = Path(path)
    if probe is None:
        probe = probe_video(str(src), timeout=timeout)
    if not probe.get("ok"):
        return {"proxy_path": str(src), "generated": False,
                "rationale": f"probe 失败（{probe.get('error')}），无法生成代理，退回原文件"}

    needed, rationale = proxy_needed(probe)
    if not needed:
        return {"proxy_path": str(src), "generated": False,
                "rationale": rationale}

    out_dir_p = Path(proxy_dir) if proxy_dir else src.parent
    stem = out_stem if out_stem else src.stem
    out_path = out_dir_p / f"{stem}{PROXY_SUFFIX}"
    out_dir_p.mkdir(parents=True, exist_ok=True)

    vf = f"scale=-2:{PROXY_HEIGHT}"
    cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src),
           "-vf", vf, "-c:v", "libx264", "-preset", PROXY_PRESET,
           "-crf", str(PROXY_CRF), "-pix_fmt", "yuv420p", "-an",
           "-f", "mp4", "-movflags", "+faststart", str(out_path)]
    res = _run_ffmpeg(cmd, timeout=timeout)
    if res["returncode"] != 0:
        return {"proxy_path": str(src), "generated": False,
                "rationale": f"代理编码失败（{res['stderr'][-300:]}），退回原文件",
                "error": res["stderr"][-300:]}

    return {"proxy_path": str(out_path), "generated": True,
            "rationale": rationale,
            "width": "auto", "height": PROXY_HEIGHT}


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    small = {"ok": True, "size_bytes": 10 * 1024 * 1024,
             "video": {"width": 1920, "height": 1080}}
    needed, why = proxy_needed(small)
    assert not needed and "直接用原文件" in why
    big = {"ok": True, "size_bytes": 600 * 1024 * 1024,
           "video": {"width": 1920, "height": 1080}}
    needed2, _ = proxy_needed(big)
    assert needed2
    big4k = {"ok": True, "size_bytes": 10 * 1024 * 1024,
             "video": {"width": 3840, "height": 2160}}
    assert proxy_needed(big4k)[0]
    print("external-visual/proxy selftest OK")


if __name__ == "__main__":
    selftest()
