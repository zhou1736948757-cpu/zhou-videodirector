#!/usr/bin/env python3
"""templates.py — Timeline 轨道预设模板（Phase-7 Prompt §17-20；P7-3）.

三个轨道模板（yaml/json 等价物，直接用 Python 字面量表达，全确定性）：

- ``ZHOU_JY_TEMPLATE_PRODUCT``（§16 短片 7 轨示例 + §18）：V1_MAIN / V2_MOTION /
  V3_OVERLAY / T1_TITLES / A1_VO / A2_MUSIC / A3_SFX。
- ``ZHOU_JY_TEMPLATE_EXPLAINER``（§16 长片 10 轨示例 + §19 增 Image/Archive）：V1_MAIN /
  V2_BROLL / V3_MOTION / V4_OVERLAY / V5_IMAGE / T1_TITLES / T2_SUBTITLES / A1_VO /
  A2_MUSIC / A3_SFX / A4_AMBIENCE。
- ``ZHOU_JY_TEMPLATE_DOCUMENTARY``（§20）：V1_ARCHIVE / V2_PHOTO / V3_MAP / T1_LABEL /
  T2_SUBTITLES / A1_VOICE / A2_MUSIC / A3_AMBIENCE。

轨道字段对齐 timeline.schema.json ``definitions.timeline_track`` 九键（§14）：
track_id/type/name/order/locked/visible/muted/purpose/backend_mapping。
``backend_mapping`` 默认 ``{}``（backend-neutral，具体后端映射由 P7-5 Adapter 填充）。

模板是辅助不是强制（§17/§94）：Planner 可自建轨道（§16 按项目规模动态），本文件只提供
预设；轨道命名遵循 §133（V1_MAIN/V2_BROLL/V3_MOTION/V4_OVERLAY/T1_TITLES/T2_SUBTITLES/
A1_VO/A2_MUSIC/A3_SFX/A4_AMBIENCE）。

技术约束：Python 3 stdlib only；无 LLM；无联网；确定性。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 轨道类型枚举（15 值，真源 = timeline.schema.json track_type，P7-2 契约）
# ---------------------------------------------------------------------------
TRACK_TYPE_ENUM = (
    "VIDEO_MAIN", "VIDEO_BROLL", "VIDEO_OVERLAY", "VIDEO_MOTION", "VIDEO_3D",
    "VIDEO_AI", "IMAGE", "TEXT", "SUBTITLE", "GRAPHIC", "VOICEOVER", "MUSIC",
    "SFX", "AMBIENCE", "UTILITY",
)


def _track(track_type: str, name: str, purpose: str, order: int) -> Dict[str, Any]:
    """构造一条九键齐备的轨道预设（§14）。"""
    return {
        "track_id": f"TR-{order:03d}",
        "type": track_type,
        "name": name,
        "order": order,
        "locked": False,
        "visible": True,
        "muted": False,
        "purpose": purpose,
        "backend_mapping": {},  # backend-neutral；P7-5 填充具体后端轨道引用
    }


# ---------------------------------------------------------------------------
# §18 Product 模板（短产品片；§16 短片 7 轨示例）
# ---------------------------------------------------------------------------
ZHOU_JY_TEMPLATE_PRODUCT: List[Dict[str, Any]] = [
    _track("VIDEO_MAIN", "V1_MAIN", "主画面：真实素材 / AI Video（§167）", 1),
    _track("VIDEO_MOTION", "V2_MOTION", "Remotion Motion Assets（§8 连续 Motion 整体）", 2),
    _track("VIDEO_OVERLAY", "V3_OVERLAY", "透明图形 / 3D Overlay（§80-81）", 3),
    _track("TEXT", "T1_TITLES", "标题 / 普通文字（§53-57）", 4),
    _track("VOICEOVER", "A1_VO", "旁白（§58-59）", 5),
    _track("MUSIC", "A2_MUSIC", "音乐（§64-67）", 6),
    _track("SFX", "A3_SFX", "音效（§63）", 7),
]

# ---------------------------------------------------------------------------
# §19 Explainer 模板（8 分钟编辑体科普；§16 长片示例 + Image/Archive）
# ---------------------------------------------------------------------------
ZHOU_JY_TEMPLATE_EXPLAINER: List[Dict[str, Any]] = [
    _track("VIDEO_MAIN", "V1_MAIN", "主画面：Footage / AI Video / VO 对齐的主轨（§167）", 1),
    _track("VIDEO_BROLL", "V2_BROLL", "补充素材（§75-76，密度规则）", 2),
    _track("VIDEO_MOTION", "V3_MOTION", "Motion Graphic / Remotion 资产（§8）", 3),
    _track("VIDEO_OVERLAY", "V4_OVERLAY", "透明图形 / 3D / Overlay（§80-83）", 4),
    _track("IMAGE", "V5_IMAGE", "图片 / 档案素材（§77-79，Ken Burns JY_NATIVE）", 5),
    _track("TEXT", "T1_TITLES", "标题 / 档案标注（§78 archive label 可编辑）", 6),
    _track("SUBTITLE", "T2_SUBTITLES", "可编辑字幕（§55 KEEP_EDITABLE，JY_NATIVE 文本轨）", 7),
    _track("VOICEOVER", "A1_VO", "旁白（§58-59；EXPLAINER 时 VO drives timing）", 8),
    _track("MUSIC", "A2_MUSIC", "音乐（§64-67；结构对齐 + Ducking）", 9),
    _track("SFX", "A3_SFX", "音效（§63 帧级对齐）", 10),
    _track("AMBIENCE", "A4_AMBIENCE", "环境声 region（§68-69 跨 Shot 连续）", 11),
]

# ---------------------------------------------------------------------------
# §20 Documentary 模板（档案纪录片）
# ---------------------------------------------------------------------------
ZHOU_JY_TEMPLATE_DOCUMENTARY: List[Dict[str, Any]] = [
    _track("VIDEO_MAIN", "V1_ARCHIVE", "档案影像主轨（历史素材，§77-78）", 1),
    _track("IMAGE", "V2_PHOTO", "历史照片（Ken Burns 克制缩放，§79）", 2),
    _track("GRAPHIC", "V3_MAP", "地图 / 图解（§20）", 3),
    _track("TEXT", "T1_LABEL", "引文 / 档案标注（date/location/source，§78）", 4),
    _track("SUBTITLE", "T2_SUBTITLES", "可编辑字幕（§55）", 5),
    _track("VOICEOVER", "A1_VOICE", "解说（§58-59）", 6),
    _track("MUSIC", "A2_MUSIC", "音乐（§64-67）", 7),
    _track("AMBIENCE", "A3_AMBIENCE", "环境声 region（§68-69）", 8),
]

TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "PRODUCT": ZHOU_JY_TEMPLATE_PRODUCT,
    "EXPLAINER": ZHOU_JY_TEMPLATE_EXPLAINER,
    "DOCUMENTARY": ZHOU_JY_TEMPLATE_DOCUMENTARY,
}

# §16 按项目规模自动选模板（纯时长启发，可被 config.template 覆盖）：
# <120s → PRODUCT；>=120s → EXPLAINER；DOCUMENTARY 需显式指定。
SHORT_FILM_MAX_SECONDS = 120.0


def resolve_template(template: Optional[str] = None,
                     total_seconds: Optional[float] = None) -> str:
    """确定性解析模板名。

    Args:
        template: config.template 值（PRODUCT/EXPLAINER/DOCUMENTARY；大小写不敏感）。
        total_seconds: 故事板总时长（秒），None 或缺失时按规模默认。

    Returns:
        模板名（大写）：PRODUCT / EXPLAINER / DOCUMENTARY。
    """
    if template is not None:
        t = str(template).strip().upper()
        if t in TEMPLATES:
            return t
        # 容错：完整名（如 "ZHOU_JY_TEMPLATE_EXPLAINER"）去前缀
        for key in TEMPLATES:
            if t.endswith(key):
                return key
    if total_seconds is not None:
        try:
            if float(total_seconds) < SHORT_FILM_MAX_SECONDS:
                return "PRODUCT"
        except (TypeError, ValueError):
            pass
        return "EXPLAINER"
    return "PRODUCT"


def build_tracks(template: str,
                 track_id_base: int = 0) -> List[Dict[str, Any]]:
    """从模板生成轨道列表，重新编号 TR-###（从 track_id_base+1 起，便于多模板合并）。"""
    preset = TEMPLATES[template]
    tracks = []
    for i, preset_track in enumerate(preset, 1):
        order = track_id_base + i
        t = dict(preset_track)
        t["track_id"] = f"TR-{order:03d}"
        t["order"] = order
        tracks.append(t)
    return tracks


# ---------------------------------------------------------------------------
# 轨道索引工具（Planner / timeline_map 共用）
# ---------------------------------------------------------------------------

def track_by_name(tracks: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    """按轨道名（大小写不敏感）查找轨道。"""
    needle = str(name).strip().upper()
    for t in tracks:
        if str(t.get("name") or "").strip().upper() == needle:
            return t
    return None


def track_by_type(tracks: List[Dict[str, Any]],
                  track_type: str) -> Optional[Dict[str, Any]]:
    """按轨道类型（大小写不敏感）查找第一条轨道。"""
    needle = str(track_type).strip().upper()
    for t in tracks:
        if str(t.get("type") or "").strip().upper() == needle:
            return t
    return None


# ---------------------------------------------------------------------------
# 自检（确定性，无第三方依赖）
# ---------------------------------------------------------------------------

def selftest() -> None:
    checks = [
        set(TEMPLATES) == {"PRODUCT", "EXPLAINER", "DOCUMENTARY"},
        len(ZHOU_JY_TEMPLATE_PRODUCT) == 7,       # §16 短片 7 轨示例
        len(ZHOU_JY_TEMPLATE_EXPLAINER) == 11,    # §16 长片 + §19 Image/Archive
        len(ZHOU_JY_TEMPLATE_DOCUMENTARY) == 8,   # §20
        all(len(t) == 9 and t["track_id"].startswith("TR-") for tpl in TEMPLATES.values()
            for t in tpl),                        # 九键全填（§14）
        all(t["type"] in TRACK_TYPE_ENUM for tpl in TEMPLATES.values() for t in tpl),
        resolve_template() == "PRODUCT",
        resolve_template("EXPLAINER") == "EXPLAINER",
        resolve_template("zhou_jy_template_documentary") == "DOCUMENTARY",
        resolve_template(None, 90.0) == "PRODUCT",
        resolve_template(None, 480.0) == "EXPLAINER",
        track_by_name(build_tracks("EXPLAINER"), "v2_broll")["type"] == "VIDEO_BROLL",
        track_by_type(build_tracks("PRODUCT"), "sfx")["name"] == "A3_SFX",
        build_tracks("PRODUCT")[0]["order"] == 1,
        build_tracks("EXPLAINER", track_id_base=20)[0]["track_id"] == "TR-021",
    ]
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"templates selftest check #{i} failed")
    print("templates selftest OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
    else:
        print("ZHOU_JY_TEMPLATE_PRODUCT:", [t["name"] for t in ZHOU_JY_TEMPLATE_PRODUCT])
        print("ZHOU_JY_TEMPLATE_EXPLAINER:", [t["name"] for t in ZHOU_JY_TEMPLATE_EXPLAINER])
        print("ZHOU_JY_TEMPLATE_DOCUMENTARY:", [t["name"] for t in ZHOU_JY_TEMPLATE_DOCUMENTARY])
