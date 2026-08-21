#!/usr/bin/env python3
"""adapters/pycapcut — pyCapCut Backend Adapter（Phase-7 §144；P7-1）.

**status: planned** —— Phase 7 不实现本后端，仅预留接口（§144：保留接口，
用于未来 international CapCut workflow；不双维护完整后端）。

- pyCapCut（https://github.com/GuanYixuan/pyCapCut）：CapCut 草稿自动化方案，
  reuse-map 中 integration_mode = TIMELINE_BACKEND，owner timeline_manager；
  同一作者 GuanYixuan 的 pyJianYingDraft 的 CapCut 版。
- 本机**未安装**该包；无能力数据可探，全部标注 **UNVERIFIED**（§3 不假设能力）。
- 接入点：实现 ``TimelineBackend`` 13 方法（§141），并在
  ``preferred_timeline_backend`` 枚举中加入 ``PYCAPCUT``（§145）。

本包只保留接口占位，不引入任何依赖、不写草稿、不联网。
"""

from __future__ import annotations

# 预留：未来在此实现 PyCapCutBackend(TimelineBackend) 的 13 方法（§141）与
# TIMELINE_BACKEND_CAPABILITIES 能力矩阵（§43 同构）。


def probe_backend() -> dict:
    """pyCapCut 能力探针占位。

    当前未安装包，无法实测。返回固定结构并标注 UNVERIFIED；接入前必须按
    §3 先验证再报告（不假设能力）。
    """
    return {
        "backend": "pyCapCut",
        "installed": False,
        "status": "planned",
        "verified": False,
        "note": "本机未安装 pyCapCut；能力数据 UNVERIFIED，待 P7-6+ 接入后补探针",
    }


__all__ = ["probe_backend"]
