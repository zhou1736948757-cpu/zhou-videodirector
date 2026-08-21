#!/usr/bin/env python3
"""color.py — 颜色/色彩元数据记录（Phase-6 §48；P6-04）.

Phase 6 不负责 Final Grade（§48），只**记录**可检测的颜色信息：
color_space / transfer / gamma / HDR·SDR / source_look。禁止擅自重度调色。

- gamma：由 transfer 按确定性映射表推导（bt709→2.2、bt2020→2.4、
  smpte2084→PQ、arib-std-b67→HLG…）；未知 transfer → None（不猜）。
- hdr：transfer ∈ {smpte2084, arib-std-b67} 或 color_space=bt2020nc → "HDR"；
  transfer 为 bt709/smpte170m 等 SDR 曲线 → "SDR"；完全未知 → None。
- source_look：仅当流/容器 tags 显式携带 look/lut/grade 类键时记录其值，
  否则 None（§48 "如果可检测"，不臆测）。
"""

from __future__ import annotations

from typing import Any, Optional

# transfer → gamma 的确定性映射（仅映射已知曲线；未知 → None）
_TRANSFER_GAMMA: dict = {
    "bt709": 2.2,
    "bt2020": 2.4,
    "smpte170m": 2.2,
    "smpte240m": 2.2,
    "linear": 1.0,
    "iec61966-2-1": 2.2,
    "iec61966-2-4": 1.96,
    "smpte2084": "PQ",
    "arib-std-b67": "HLG",
    "bt470bg": 2.2,
    "bt470m": 2.8,
}
# HDR 判定的 transfer / color_space 集合
_HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}
_HDR_COLOR_SPACES = {"bt2020nc", "bt2020"}
_SDR_TRANSFERS = {"bt709", "smpte170m", "smpte240m", "bt470bg", "bt470m",
                  "iec61966-2-1", "iec61966-2-4"}
# source_look 检测键（小写匹配）
_LOOK_KEYS = ("look", "lut", "grade", "grading", "colorgrade")


def _detect_source_look(video: dict, format_tags: dict) -> Optional[str]:
    stream_tags = (video or {}).get("tags") or {}
    for bucket in (stream_tags, format_tags or {}):
        for key, value in bucket.items():
            if str(key).lower() in _LOOK_KEYS and value:
                return str(value)
    return None


def color_metadata(probe: dict) -> dict:
    """从 probe 输出提取颜色元数据（§48；只记录，不做重度调色）。

    返回 dict 含：color_space / color_transfer / color_primaries / color_range /
    pix_fmt / gamma / hdr / source_look / recorded_only。
    """
    video = probe.get("video") or {}
    fmt = probe.get("format_name")
    # ffprobe 的 format 节点可能带 tags；probe_video 未保留，这里从 video.tags 兜底
    stream_tags = video.get("tags") or {}
    transfer = video.get("color_transfer")
    color_space = video.get("color_space")

    gamma = _TRANSFER_GAMMA.get(str(transfer)) if transfer else None

    hdr: Optional[str] = None
    if transfer and str(transfer).lower() in _HDR_TRANSFERS:
        hdr = "HDR"
    elif color_space and str(color_space).lower() in _HDR_COLOR_SPACES:
        hdr = "HDR"
    elif transfer and str(transfer).lower() in _SDR_TRANSFERS:
        hdr = "SDR"

    return {
        "color_space": color_space,
        "color_transfer": transfer,
        "color_primaries": video.get("color_primaries"),
        "color_range": video.get("color_range"),
        "pix_fmt": video.get("pix_fmt"),
        "gamma": gamma,
        "hdr": hdr,
        "source_look": _detect_source_look(video, None),
        "recorded_only": True,  # §48：本阶段只记录，不做重度调色
        "container_format": fmt,
    }


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    p = {"video": {"color_transfer": "bt709", "color_space": "bt709",
                   "color_primaries": "bt709", "pix_fmt": "yuv420p",
                   "tags": {"encoder": "libx264"}},
         "format_name": "mov,mp4"}
    c = color_metadata(p)
    assert c["gamma"] == 2.2 and c["hdr"] == "SDR" and c["source_look"] is None
    p2 = {"video": {"color_transfer": "smpte2084", "color_space": "bt2020nc",
                    "tags": {"look": "creative-lut-01"}}}
    c2 = color_metadata(p2)
    assert c2["hdr"] == "HDR" and c2["source_look"] == "creative-lut-01"
    p3 = {"video": {}}
    assert color_metadata(p3)["gamma"] is None
    print("external-visual/color selftest OK")


if __name__ == "__main__":
    selftest()
