#!/usr/bin/env python3
"""modules/timeline-manager/backend/base.py — TimelineBackend 抽象接口（Phase-7 §141-147；P7-1）.

定义：

1. ``TimelineBackend``：Backend-neutral 的抽象基类，13 个抽象方法（§141）。所有方法
   返回 ``dict`` 契约，见各方法 docstring。子类（如 PyJianYingDraftBackend）负责
   Manifest → 具体 Backend 草稿的翻译；本接口禁止 Backend 特有类型泄漏到上层（§13）。
2. ``BACKEND_COMPATIBILITY_REPORT``：兼容性报告结构（§95），由各 Backend 在探测阶段
   填写，供 ``export_draft`` 的返回结果与 Phase-7 验收（Test 26 Backend Version）引用。

设计约束（来自 Phase-7 Prompt）：
- §6 Human Must Be Able to Take Over：任何自动产物都必须尽量允许人工继续编辑。
- §90 Adapter 不能拥有导演权：Adapter 只翻译意图为 Backend 操作，不改 Shot 顺序/音乐/Style。
- §92 不支持的能力不能静默丢掉：必须产生 BACKEND_FALLBACK_REPORT。
- §99-108 Human Edit Preservation：replace_asset 优先于重建全量草稿；人类编辑优先。

技术约束：Python 3 stdlib only；无 LLM、无联网、确定性。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


# ---------------------------------------------------------------------------
# §95 Backend Compatibility Report 结构
# ---------------------------------------------------------------------------
BACKEND_COMPATIBILITY_REPORT = {
    "tested_backend_version": "str — 实际探测的 Backend 版本（如 'pyJianYingDraft 0.3.0'）",
    "tested_editor_version": "str — 实际探测的编辑器版本；本机无编辑器时为 'UNKNOWN'（§3 不假设）",
    "supported_features": "list[str] — 探测确认支持的 Timelinet 能力（对应 TIMELINE_BACKEND_CAPABILITIES 键名）",
    "known_limitations": "list[str] — 探测确认不支持的项与 fallback 说明（§44 不假装支持不存在的功能）",
    "probe_date": "str — 探测日期，ISO 格式（如 '2026-08-15'），用于版本漂移追踪",
}

# 结构字段顺序（固定，便于机器解析）：
BACKEND_COMPATIBILITY_REPORT_KEYS = [
    "tested_backend_version",
    "tested_editor_version",
    "supported_features",
    "known_limitations",
    "probe_date",
]


class TimelineBackend(ABC):
    """Backend-neutral 的时间线后端抽象接口（§141-147）。

    Timeline Manifest 是系统真相来源（§12）；本接口把 Manifest 的语义翻译成具体
    Backend（pyJianYingDraft / VectCut / pyCapCut）操作。方法返回统一 ``dict`` 契约：

    - 成功：``{"ok": True, "result": <方法特定结构>}``
    - 失败：``{"ok": False, "error": "<错误码>", "message": "<可读描述>",
      "fallback": "<BACKEND_FALLBACK_REPORT 摘要或建议方案>"}``

    不允许静默丢能力（§92）：任何 Backend 不支持的能力都必须体现在 ``fallback`` 中。
    """

    # ------------------------------------------------------------------ §141
    @abstractmethod
    def capabilities(self) -> Dict[str, Any]:
        """返回 Backend 能力矩阵（§43 TIMELINE_BACKEND_CAPABILITIES 子集或超集）。

        返回值契约::

            {"ok": True,
             "result": {
                 "<capability_key>": {
                     "supported": true | false | "partial",
                     "fallback": "str — supported 非 true 时的替代方案（§44/§147）",
                     "evidence": "str — 包源码文件:行 证据",
                 },
                 ...  # 全部能力键
             }}

        各键为 §43 的 17 项能力名（basic_video/multi_track/text/subtitle/
        position_keyframe/scale_keyframe/rotation_keyframe/opacity_keyframe/
        volume_keyframe/transition/filter/mask/blend_mode/
        effect_parameter_keyframe/bezier_easing/custom_motion_path/template_import）。
        """
        ...

    @abstractmethod
    def validate_manifest(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """在生成草稿前校验 Timeline Manifest（§109-115：无负时长/无缺失素材/轨道映射合法/
        字幕与音频 timing 合法/关键帧 timing 合法/continuity group 完整）。

        返回值契约::

            {"ok": True,
             "result": {"valid": true,
                        "issues": []}}            # 全部通过
            {"ok": True,
             "result": {"valid": false,
                        "issues": [{"level": "ERROR|WARNING", "code": "<ISSUE_CODE>",
                                    "message": "str", "clip_id": "str|None"}]}}
        """
        ...

    @abstractmethod
    def create_project(self, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """创建时间线项目（对应 Backend 的工程/草稿容器，如 pyJianYingDraft 的
        DraftFolder.create_draft / ScriptFile 构造，§89）。

        返回值契约::

            {"ok": True,
             "result": {"project_id": "str", "backend": "str",
                        "backend_version": "str",
                        "canvas": {"width": int, "height": int},
                        "fps": int, "duration_us": int}}
        """
        ...

    @abstractmethod
    def add_track(self, project_id: str, track_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加轨道（§14-16 / §132-133：track_type/name/order/mute）。

        返回值契约::

            {"ok": True,
             "result": {"track_id": "str", "track_ref": "str — 公开引用句柄",
                        "track_type": "str", "name": "str", "order": int}}
        """
        ...

    @abstractmethod
    def add_clip(self, project_id: str, track_ref: str, clip_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加视频/图片片段（§29 Clip Schema：asset_id/shot_id/时间范围/source 范围/
        position/scale/rotation/opacity/crop/blend_mode/mask/audio_behavior）。

        返回值契约::

            {"ok": True,
             "result": {"clip_id": "str", "track_id": "str",
                        "start_us": int, "duration_us": int,
                        "source_in_us": int, "source_out_us": int,
                        "material_id": "str"}}
        """
        ...

    @abstractmethod
    def add_text(self, project_id: str, track_ref: str, text_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加文本片段（§53-57：text/style_id/start_frame/end_frame/position 等）。

        返回值契约::

            {"ok": True,
             "result": {"text_id": "str", "track_id": "str",
                        "start_us": int, "duration_us": int,
                        "text": "str"}}
        """
        ...

    @abstractmethod
    def add_subtitle(self, project_id: str, track_ref: str, subtitle_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加字幕片段（§53-57 Subtitle System，默认 KEEP_EDITABLE）。

        Backend 无原生字幕轨时（如 pyJianYingDraft 只有 text 轨 + auto_wrapping 标志），
        实现必须用文本轨模拟并在 ``result`` 标注 ``"mechanism": "text_track"``。

        返回值契约::

            {"ok": True,
             "result": {"subtitle_id": "str", "track_id": "str",
                        "start_us": int, "duration_us": int,
                        "text": "str", "mechanism": "text_track|native"}}
        """
        ...

    @abstractmethod
    def add_audio(self, project_id: str, track_ref: str, audio_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加音频片段（§58-71：VO/Music/SFX/Ambience，volume/fade/ducking 关联）。

        返回值契约::

            {"ok": True,
             "result": {"audio_id": "str", "track_id": "str",
                        "start_us": int, "duration_us": int,
                        "volume": float,
                        "fade_in_us": int, "fade_out_us": int}}
        """
        ...

    @abstractmethod
    def add_keyframes(self, project_id: str, clip_id: str,
                      keyframes_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加关键帧（§45-51：property/from/to/easing/sampling 策略）。

        Backend 不支持原生曲线（如 pyJianYingDraft 只有 curveType=Line）时，实现负责
        按 §47-48 采样离散关键帧，并在 ``result`` 标注 ``"sampled": true`` 与采样点数。

        返回值契约::

            {"ok": True,
             "result": {"clip_id": "str",
                        "applied": [{"property": "position_x|scale_x|...",
                                     "keyframes": [{"time_offset_us": int, "value": float}],
                                     "sampled": bool, "sample_count": int}],
                        "keyframe_budget": int}}
        """
        ...

    @abstractmethod
    def add_transition(self, project_id: str, clip_id: str,
                       transition_spec: Dict[str, Any]) -> Dict[str, Any]:
        """添加转场（§72-74：transition 应加在**前一个**片段上；cut 是合法且常用转场）。

        返回值契约::

            {"ok": True,
             "result": {"clip_id": "str", "transition_id": "str",
                        "transition_type": "str", "duration_us": int,
                        "is_overlap": bool}}
        """
        ...

    @abstractmethod
    def replace_asset(self, project_id: str, clip_id: str, asset_slot_id: str,
                      new_asset: Dict[str, Any]) -> Dict[str, Any]:
        """按 Asset Slot 替换素材（§33-36 / §102 replace_asset 优先于重建；§35 保留
        timing/track/transform/兼容 keyframes）。

        §36 Replacement Safety：新素材时长/分辨率/宽高比/alpha 显著变化时不得静默替换，
        必须返回 ``ASSET_REPLACEMENT_CONFLICT``。

        返回值契约::

            {"ok": True,
             "result": {"clip_id": "str", "asset_slot_id": "str",
                        "new_material_id": "str",
                        "preserved": {"timing": bool, "track": bool,
                                      "transform": bool, "keyframes": bool}}}
            {"ok": False, "error": "ASSET_REPLACEMENT_CONFLICT",
             "message": "str", "fallback": "str"}
        """
        ...

    @abstractmethod
    def export_draft(self, project_id: str, output_dir: str,
                     options: Dict[str, Any]) -> Dict[str, Any]:
        """导出/生成草稿文件（§89-92 / §96）。

        §96：不得宣传"自动打开/导出剪映成片"，只能生成草稿并明确
        "Draft generated. Human opens JianYing for inspection/export."

        返回值契约::

            {"ok": True,
             "result": {"backend": "str", "backend_version": "str",
                        "draft_path": "str", "generated_at": "str",
                        "manifest_version": "str",
                        "warnings": ["str"],
                        "unsupported_features": [{"feature": "str",
                                                  "fallback": "str"}],
                        "fallbacks": ["str"],
                        "compatibility_report": BACKEND_COMPATIBILITY_REPORT}}
        """
        ...

    @abstractmethod
    def validate_draft(self, project_id: str, draft_path: str) -> Dict[str, Any]:
        """验证已生成草稿（§109-115：素材存在/片段在界内/无负时长/无非法重叠/
        无缺失素材/asset link 解析/轨道映射合法）。

        返回值契约::

            {"ok": True,
             "result": {"valid": bool,
                        "issues": [{"level": "ERROR|WARNING", "code": "<ISSUE_CODE>",
                                    "message": "str", "clip_id": "str|None"}]}}
        """
        ...
