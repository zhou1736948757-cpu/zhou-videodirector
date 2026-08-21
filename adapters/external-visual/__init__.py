#!/usr/bin/env python3
"""adapters/external-visual — 外部视频摄取/标准化适配层（Phase-6 §42-51 / §69 /
§90-95 / §98-100 / §106；P6-04）.

统一处理任意来源（API / 网页生成 / 用户上传 / 外部工具 / 素材下载）外部视频的：
probe（ffprobe 技术探针，§69）→ validate（技术校验，§100）→ audio_decision
（音频行为决策，§83-84）→ normalize（按需标准化，§44-45）→ proxy（代理，§46）
→ storage（布局与存储策略，§90-95）→ color（色彩元数据记录，§48）。

只导出本包内容（与 P6-02 modules/external-visual 同规则：不导入其他 Phase 的适配器）。

注意：包名含连字符，外部统一用 ``importlib.import_module("adapters.external-visual.xxx")``
导入；本文件内相对导入不受影响。
"""

from .probe import probe_video, simplify_fps, detect_rotation
from .validate import technical_validate
from .audio_decision import decide_audio, decide_audio_detailed, AUDIO_MODES
from .color import color_metadata
from .normalize import normalize, plan_normalize, DEFAULT_TARGET
from .proxy import make_proxy, proxy_needed
from .storage import (
    asset_dir,
    list_versions,
    next_version,
    version_files,
    apply_storage_policy,
    record_rejected_variant,
    read_rejected_variants,
    STORAGE_POLICIES,
    DEFAULT_STORAGE_POLICY,
)

__all__ = [
    "probe_video", "simplify_fps", "detect_rotation",
    "technical_validate",
    "decide_audio", "decide_audio_detailed", "AUDIO_MODES",
    "color_metadata",
    "normalize", "plan_normalize", "DEFAULT_TARGET",
    "make_proxy", "proxy_needed",
    "asset_dir", "list_versions", "next_version", "version_files",
    "apply_storage_policy", "record_rejected_variant", "read_rejected_variants",
    "STORAGE_POLICIES", "DEFAULT_STORAGE_POLICY",
]
