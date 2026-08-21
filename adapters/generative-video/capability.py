#!/usr/bin/env python3
"""capability.py — Generative Video Provider Capability Check（Phase-6 Prompt §27；P6-06）.

capability_check(packet, provider_cap) 把 Provider-neutral Production Packet（GV-###，
§25）逐项对照 provider 能力档案（§27：duration_options / resolution_options /
aspect_ratios / text_to_video / image_to_video / first_last_frame / reference_image /
character_reference / camera_control / audio_generation / seed_control），返回：

    {ok: bool, unsupported: [{item, request, supported, suggestion}], warnings: [...]}

- 不支持的项必须列出并给出替代建议（§27/§26 语义），例如 first_last_frame 不支持 →
  建议改用 image_to_video 或拆 shot。
- 当 provider_cap.manual_generation_supported=true 时，在 warnings 中降级为
  "人工网页生成"提示（§29 一等公民路径），但仍如实报告能力缺口。
- 判定全部确定性：给定 packet + provider_cap → 相同结果，无随机、无 LLM。
- 硬规则：本模块只做"能力对照 + 建议"，不产生任何真实 API 调用。

技术约束：**Python3 stdlib only**。代码风格照抄 modules/production/planner.py
（中文 docstring 带 §出处、纯函数、常量表）。
"""

from __future__ import annotations

from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量（§17/§16/§24 枚举；与 P6-01 contract 对齐）
# ---------------------------------------------------------------------------

CAMERA_MOVEMENTS = (
    "STATIC", "PUSH_IN", "PULL_OUT", "PAN", "TILT", "ORBIT", "DOLLY",
    "TRACKING", "CRANE", "HANDHELD", "POV", "COMPLEX", "CUSTOM",
)

# §24 七类参考输入 → 需要的 provider 能力字段
REFERENCE_CAPABILITY = {
    "reference_image": "reference_image",
    "style_frame": "reference_image",
    "character_reference": "character_reference",
    "environment_reference": "reference_image",
    "product_reference": "reference_image",
    "previous_generated_frame": "reference_image",
}

# 能力布尔字段清单（§27；值为 true/false/partial 的字段）
_BOOLEAN_CAPABILITIES = (
    "text_to_video", "image_to_video", "first_last_frame", "reference_image",
    "character_reference", "camera_control", "audio_generation", "seed_control",
)


def _cap_bool(provider_cap: dict, field: str) -> bool:
    """能力字段 → 是否支持（true=支持；partial/manual_or_semiautomatic=部分支持按支持算）。

    与 P6-01 generative-video-provider.schema.json 的能力五值枚举对齐（FR-001/FR-028，
    风格同 provider.schema.json capability_value）：五值 = true | false | partial |
    manual_or_semiautomatic | requires_authentication（亦可用 none|basic|partial|full|
    unknown 风格表达）。宽容规则：显式 true 或 partial/full/basic/
    manual_or_semiautomatic/requires_authentication 均视为"可用"（partial 在五值枚举中
    合法，语义为"部分支持，按支持处理"）；false/none/unknown/缺失/None 视为不支持。
    """
    v = provider_cap.get(field) if isinstance(provider_cap, dict) else None
    if v is True or str(v).lower() in ("partial", "full", "basic",
                                       "manual_or_semiautomatic",
                                       "requires_authentication"):
        return True
    return False


def _norm_duration(value: Any) -> Optional[float]:
    """把时长值规整为 float（None/非法 → None）。"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _duration_ranges(provider_cap: dict) -> list:
    """把 duration_options 规整为 [min, max] 区间列表。

    支持三种形态：数字列表 [5, 8]（每项 = 精确档位）；区间 dict 列表
    [{min, max}]；字符串数字列表。确定性归一。
    """
    opts = provider_cap.get("duration_options") if isinstance(provider_cap, dict) else None
    ranges: list = []
    if isinstance(opts, list):
        for o in opts:
            if isinstance(o, dict):
                lo = _norm_duration(o.get("min"))
                hi = _norm_duration(o.get("max"))
                if lo is not None or hi is not None:
                    ranges.append([lo if lo is not None else hi,
                                   hi if hi is not None else lo])
            else:
                d = _norm_duration(o)
                if d is not None:
                    ranges.append([d, d])
    return ranges


def _resolution_options(provider_cap: dict) -> list:
    """把 resolution_options 规整为 (w, h) 元组列表（字符串 "WxH" / dict / 数字高度）。"""
    opts = provider_cap.get("resolution_options") if isinstance(provider_cap, dict) else None
    out: list = []
    if isinstance(opts, list):
        for o in opts:
            t = _parse_resolution(o)
            if t is not None:
                out.append(t)
    return out


def _parse_resolution(value: Any):
    """单个分辨率值 → (w, h) 或 None。

    "1920x1080" / {"width":1920,"height":1080} / {"w":..,"h":..} / {"label":"1080p"} 中的
    label 按常见命名解析（720p/1080p/2160p/4K）。无法解析 → None（确定性跳过）。
    """
    if isinstance(value, str):
        v = value.strip().lower().replace(" ", "")
        m = v.split("x")
        if len(m) == 2:
            try:
                return (int(m[0]), int(m[1]))
            except ValueError:
                return None
        label = {"720p": (1280, 720), "1080p": (1920, 1080), "2160p": (3840, 2160),
                 "4k": (3840, 2160), "1440p": (2560, 1440)}
        if v in label:
            return label[v]
        return None
    if isinstance(value, dict):
        w = value.get("w", value.get("width"))
        h = value.get("h", value.get("height"))
        try:
            return (int(w), int(h))
        except (TypeError, ValueError):
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None  # 单数字高度不足以确定宽，跳过
    return None


def _norm_aspect(aspect: Any) -> str:
    """长宽比归一："16:9" / "16 / 9" / 1.778 → "16:9"（字符串直通，数字转分数比例）。"""
    if isinstance(aspect, (int, float)) and not isinstance(aspect, bool):
        try:
            from fractions import Fraction
            f = Fraction(aspect).limit_denominator(100)
            return f"{f.numerator}:{f.denominator}"
        except Exception:  # noqa: BLE001
            return str(aspect)
    s = str(aspect or "").strip().replace(" ", "").replace("/", ":")
    return s


def _packet_resolution(packet: dict):
    """packet 分辨率 → (w, h) 或 None（支持 dict 或字符串）。"""
    res = packet.get("resolution")
    return _parse_resolution(res)


def _find_closest(items, target):
    """在可比较列表里找最接近 target 的项（确定性；空列表 → None）。"""
    if not items:
        return None
    try:
        return min(items, key=lambda x: abs(x - target))
    except TypeError:
        return None


def _suggest_resolution(resolution_options: list, req_w: int, req_h: int) -> str:
    if not resolution_options:
        return "请确认 provider 支持的分辨率"
    best = min(resolution_options, key=lambda t: (t[0] - req_w) ** 2 + (t[1] - req_h) ** 2)
    return f"建议改用 provider 支持的分辨率 {best[0]}x{best[1]}"


def _suggest_duration(ranges: list, req: float) -> str:
    if not ranges:
        return "请确认 provider 支持的时长档位"
    best = min(ranges, key=lambda r: abs((r[0] + r[1]) / 2.0 - req))
    if best[0] == best[1]:
        return f"建议改用 provider 支持的时长 {best[0]}s（或拆分镜头）"
    return f"建议改用 provider 支持的时长区间 {best[0]}-{best[1]}s"


def _capability_bool_issues(packet: dict, provider_cap: dict) -> tuple:
    """布尔能力逐项对照：返回 (unsupported 列表, warnings 列表)。"""
    unsupported: list = []
    warnings: list = []

    # 请求类型（§27 text_to_video / image_to_video）
    refs = packet.get("reference_inputs")
    has_ref_image = isinstance(refs, list) and any(
        isinstance(r, dict) and r.get("ref_id") and
        _REFERENCE_KIND_TO_KEY(str(r.get("kind") or r.get("type") or "")) == "reference_image"
        for r in refs
    )
    if has_ref_image and not _cap_bool(provider_cap, "image_to_video"):
        unsupported.append({
            "item": "image_to_video",
            "request": "packet.reference_inputs 含参考图，需要图→视频能力",
            "supported": provider_cap.get("image_to_video"),
            "suggestion": "改用 text-to-video 或去掉参考图",
        })
    if not has_ref_image and not _cap_bool(provider_cap, "text_to_video"):
        unsupported.append({
            "item": "text_to_video",
            "request": "packet 无参考图，走文本→视频路径",
            "supported": provider_cap.get("text_to_video"),
            "suggestion": "改用 image-to-video 或人工网页生成",
        })

    # 首尾帧（§21）：有 start/end_frame 要求时，需要 first_last_frame 或 image_to_video
    has_start_end = bool(packet.get("start_frame")) or bool(packet.get("end_frame"))
    if has_start_end and not _cap_bool(provider_cap, "first_last_frame"):
        if _cap_bool(provider_cap, "image_to_video"):
            suggestion = ("建议改用 image_to_video（把首帧作为参考图）或拆分镜头"
                          "（shot split 需批准，§41）")
        else:
            suggestion = ("建议改用 image_to_video 或拆分镜头（shot split 需批准，§41）")
        unsupported.append({
            "item": "first_last_frame",
            "request": "packet.start_frame/end_frame 需要首尾帧一致性（§21）",
            "supported": provider_cap.get("first_last_frame"),
            "suggestion": suggestion,
        })

    # 相机控制（§15-17）：非 STATIC 运镜需要 camera_control
    cam = str(packet.get("camera_movement") or packet.get("camera") or "").upper()
    if cam and cam not in ("STATIC", "CUSTOM") and not _cap_bool(provider_cap, "camera_control"):
        unsupported.append({
            "item": "camera_control",
            "request": f"packet.camera_movement={cam} 需要相机控制（§17）",
            "supported": provider_cap.get("camera_control"),
            "suggestion": "改用 STATIC 运镜，或后期在 Remotion/JianYing 做 camera（§50）",
        })

    # 音频生成（§83-84）：packet 声明 audio_requirement 时检查
    if packet.get("audio_requirement") and not _cap_bool(provider_cap, "audio_generation"):
        warnings.append(
            "audio_generation 不支持：packet.audio_requirement 需音频，但 provider 不支持 "
            "生成音频——返回文件后按 audio_behavior（KEEP/MUTE/EXTRACT/REPLACE，§83-84）处理"
        )

    # 种子控制（§17 确定性）：packet 带 seed 时检查
    if packet.get("seed") is not None and not _cap_bool(provider_cap, "seed_control"):
        warnings.append(
            "seed_control 不支持：packet.seed 无法在 provider 侧复现；同批次一致性依赖连续性档案（§85-87）"
        )

    # 参考输入（§24）：7 类 → 能力字段
    if isinstance(refs, list):
        for r in refs:
            if not isinstance(r, dict):
                continue
            kind = str(r.get("kind") or r.get("type") or "").strip()
            key = _REFERENCE_KIND_TO_KEY(kind)
            if key and not _cap_bool(provider_cap, key):
                unsupported.append({
                    "item": key,
                    "request": f"reference_inputs kind={kind or '?'} 需要 {key}（§24）",
                    "supported": provider_cap.get(key),
                    "suggestion": "移除该参考类型，或改用 character/environment 连续性档案（§86-87）",
                })

    return unsupported, warnings


def _REFERENCE_KIND_TO_KEY(kind: str) -> str:
    return REFERENCE_CAPABILITY.get(kind.strip(), "")


def capability_check(packet: dict, provider_cap: dict) -> dict:
    """§27 Provider Capability Check：Packet ↔ Provider 能力逐项对照。

    packet 为 Provider-neutral Production Packet（GV-###，§25）；provider_cap 为
    providers/generative-video/*.yaml 加载的能力档案（对齐 P6-01 schema）。

    返回：
        {ok, unsupported: [{item, request, supported, suggestion}], warnings: [...]}
    ok = unsupported 为空。warnings 仅为建议（不影响 ok）。

    确定性：纯函数，无随机、无 LLM；相同输入 → 相同输出。
    """
    if not isinstance(packet, dict):
        raise ValueError("packet 必须是 dict（GV Packet）")
    if not isinstance(provider_cap, dict):
        raise ValueError("provider_cap 必须是 dict（Provider Capability）")

    unsupported: list = []
    warnings: list = []

    # —— 数值/几何项 ——
    duration = _norm_duration(packet.get("duration"))
    ranges = _duration_ranges(provider_cap)
    if duration is not None:
        if not ranges:
            warnings.append("provider 未声明 duration_options，无法校验时长")
        elif not any(lo <= duration <= hi for lo, hi in ranges):
            unsupported.append({
                "item": "duration",
                "request": f"packet.duration={duration}s（§9）",
                "supported": provider_cap.get("duration_options"),
                "suggestion": _suggest_duration(ranges, duration),
            })
    else:
        warnings.append("packet 未声明 duration，跳过时长校验")

    res_t = _packet_resolution(packet)
    res_opts = _resolution_options(provider_cap)
    if res_t is not None:
        if not res_opts:
            warnings.append("provider 未声明 resolution_options，无法校验分辨率")
        elif res_t not in res_opts:
            unsupported.append({
                "item": "resolution",
                "request": f"packet.resolution={res_t[0]}x{res_t[1]}（§9）",
                "supported": provider_cap.get("resolution_options"),
                "suggestion": _suggest_resolution(res_opts, res_t[0], res_t[1]),
            })
    else:
        warnings.append("packet 未声明 resolution，跳过分辨率校验")

    aspect = _norm_aspect(packet.get("aspect_ratio"))
    aspect_opts = [_norm_aspect(a) for a in
                   (provider_cap.get("aspect_ratios") or []) if a]
    if aspect and aspect_opts and aspect not in aspect_opts:
        unsupported.append({
            "item": "aspect_ratios",
            "request": f"packet.aspect_ratio={aspect}（§9）",
            "supported": provider_cap.get("aspect_ratios"),
            "suggestion": "建议改用 provider 支持的长宽比之一："
                          + ", ".join(provider_cap.get("aspect_ratios") or []),
        })

    # —— 布尔能力逐项 ——
    b_unsupported, b_warnings = _capability_bool_issues(packet, provider_cap)
    unsupported.extend(b_unsupported)
    warnings.extend(b_warnings)

    # —— §27 人工网页生成降级提示（§29 一等公民）——
    if provider_cap.get("manual_generation_supported") is True:
        warnings.append(
            "manual_generation_supported=true：能力缺口可降级为'人工网页生成'流程"
            "（run_manual，§29）——用户自行在网页端生成并返回文件"
        )
    if not provider_cap.get("api_available"):
        warnings.append(
            "api_available=false：当前无可用 API（未配置凭据），只能走人工生成/配置拦截（§116）"
        )

    # —— 去重保序 ——
    seen: set = set()
    out_u: list = []
    for u in unsupported:
        k = (u["item"], u["request"])
        if k not in seen:
            seen.add(k)
            out_u.append(u)
    seen = set()
    out_w: list = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            out_w.append(w)

    return {
        "ok": not out_u,
        "unsupported": out_u,
        "warnings": out_w,
    }
