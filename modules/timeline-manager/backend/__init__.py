#!/usr/bin/env python3
"""modules/timeline-manager/backend — Timeline Backend 抽象接口（Phase-7 §141-147；P7-1）.

定义 Backend-neutral 的 ``TimelineBackend`` 抽象基类（13 方法）与
``BACKEND_COMPATIBILITY_REPORT`` 兼容性报告结构（§95）。本包不实现任何具体
Backend 业务（P7-3..5 的活），只做接口与契约。

- ``base.TimelineBackend``：13 个抽象方法，中文 docstring + § 引用 + 返回值 dict 契约。
- ``base.BACKEND_COMPATIBILITY_REPORT``：兼容性报告结构（§95 五字段）。

约定（§13 Backend-neutral First）：
- Timeline Manifest 是系统真相来源，Backend Adapter 只做 Manifest → 具体草稿的翻译。
- 本接口只允许返回 ``dict`` 与内置类型；禁止 Backend 特有类型泄漏到上层。

技术约束：Python 3 stdlib only；无 LLM、无联网、确定性。
"""

from .base import TimelineBackend, BACKEND_COMPATIBILITY_REPORT

__all__ = ["TimelineBackend", "BACKEND_COMPATIBILITY_REPORT"]
