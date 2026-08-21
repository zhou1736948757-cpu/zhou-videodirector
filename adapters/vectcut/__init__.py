#!/usr/bin/env python3
"""adapters/vectcut — VectCutAPI Backend Adapter（Phase-7 §143；P7-1）.

**status: planned** —— Phase 7 不实现本后端，仅预留接口（§143：capability probe +
adapter interface + planned status，不双维护完整后端）。

- VectCutAPI（https://github.com/sun-guannan/VectCutAPI）：Agent 视频编辑 API /
  Skills 与剪映/CapCut 草稿思路，reuse-map 中 integration_mode =
  TIMELINE_BACKEND（+ARCHITECTURE_REFERENCE），owner timeline_manager。
- 本机**未安装**该包，以下能力描述仅来自仓库文档级公开信息，标注 **UNVERIFIED**，
  待 P7-6+ 真正接入时以读包源码 + 探针为准（§3 不假设 Backend 能力）。
- 接入点：实现 ``modules/timeline-manager/backend/base.py`` 的
  ``TimelineBackend`` 13 方法（§141），并在 ``preferred_timeline_backend``
  枚举中加入 ``VECTCUT``（§145）。

本包只保留接口占位，不引入任何依赖、不写草稿、不联网。
"""

from __future__ import annotations

# 预留：未来在此实现 VectCutBackend(TimelineBackend) 的 13 方法（§141）与
# TIMELINE_BACKEND_CAPABILITIES 能力矩阵（§43 同构）。


def probe_backend() -> dict:
    """VectCut 能力探针占位。

    当前未安装包，无法实测。返回固定结构并标注 UNVERIFIED；接入前必须按
    §3 先验证再报告（不假设能力）。
    """
    return {
        "backend": "VectCutAPI",
        "installed": False,
        "status": "planned",
        "verified": False,
        "note": "本机未安装 VectCutAPI；能力数据 UNVERIFIED，待 P7-6+ 接入后补探针",
    }


__all__ = ["probe_backend"]
