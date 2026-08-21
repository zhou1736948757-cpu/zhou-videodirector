#!/usr/bin/env python3
"""base.py — Generative Video Provider Adapter 抽象（Phase-6 Prompt §26-27；P6-06）.

Provider-neutral Packet（GV-###，§25）→ Provider Adapter 四步接口（§26）：

    normalize(packet)
      → capability_check(packet, provider_cap)          # §27（capability.py）
      → build_provider_prompt(packet)                   # provider-specific prompt
      → generation_instructions(packet, provider_cap)   # 生成说明

本文件实现**与 provider 无关**的基类部分：

- overlay_safe 注释：把 packet.overlay_safe_area / text_safe_area（§14/§50）追加进
  prompt，提醒保留后期叠加空间。
- negative_constraints 合并：packet.negative_constraints + negative_prompt + provider
  基础项（no text/no watermark/no logo 等，§26/§28）确定性合并。
- text-safe 段转换：prompt 中的精确信息（§7 硬规则：exact text/UI/logo/data）不进入
  生成描述，改为"此区域保持视觉安静"的占位说明（§51 安全构图）。

provider-specific 部分（模型特有的 prompt 语气 / 参数命名）由子类或配置模板完成：
`TemplatePromptAdapter` 从 provider 配置文件读取 `prompt_style` / `prompt_template`
字段注入，无需在核心代码硬编码任何模型名（§28）。

技术约束：**Python3 stdlib only**；本模块不产生任何真实 API 调用。
代码风格照抄 modules/production/planner.py。
"""

from __future__ import annotations

from typing import Any, Optional

import importlib as _importlib

# 包目录含连字符（adapters/generative-video），import 语句无法写这段名——
# 按本包约定用 importlib 加载兄弟模块（capability.py，§27）。
_capability_mod = _importlib.import_module("adapters.generative-video.capability")
capability_check = _capability_mod.capability_check

# §7 硬规则：精确信息类（不进入生成描述，改由 overlay 层承担）
VERBATIM_CLASSES = ("EXACT_UI", "EXACT_TEXT", "EXACT_NUMBER", "LOGO", "DATA", "LABEL")

# §26 基础 negative 约束（当 packet 未显式给出时兜底）
BASE_NEGATIVE_TERMS = (
    "no text", "no watermark", "no logo", "no subtitles", "no timestamp",
    "no extra limbs", "no morphing",
)


def _listify(value: Any) -> list:
    """字符串/列表 → 列表（None → []）。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def overlay_safe_comment(packet: dict) -> str:
    """§14/§50：由 text_safe_area / overlay_safe_area 生成中文提示段（无要求 → ""）。"""
    notes = []
    tsa = packet.get("text_safe_area")
    if tsa:
        notes.append(f"text_safe_area: {tsa}")
    osa = packet.get("overlay_safe_area")
    if osa:
        notes.append(f"overlay_safe_area: {osa}")
    if not notes:
        return ""
    return "NOTE (keep safe): " + " ; ".join(notes) + " — keep these areas visually quiet."


def merge_negative_constraints(packet: dict, provider_cap: Optional[dict] = None) -> str:
    """§26/§28：合并 negative 约束（packet.negative_constraints + negative_prompt + 基础项）。

    去重保序；返回可直接写进网页 negative prompt 框的单行文本。
    """
    parts: list = []
    seen: set = set()

    def add(term: str):
        t = term.strip()
        if t and t not in seen:
            seen.add(t)
            parts.append(t)

    for c in _listify(packet.get("negative_constraints")):
        add(c)
    np = packet.get("negative_prompt")
    if isinstance(np, str) and np.strip():
        for c in np.replace("\n", ",").split(","):
            add(c)
    if isinstance(provider_cap, dict):
        for c in _listify(provider_cap.get("negative_constraints")):
            add(c)
    for t in BASE_NEGATIVE_TERMS:
        add(t)
    return ", ".join(parts)


def text_safe_conversion(prompt: str, packet: dict) -> str:
    """§7/§51：text-safe 段转换。

    当 packet 存在 verbatim 类 overlay 要求或 text_safe_area 时，在 prompt 末尾追加
    "此区域保持视觉安静、不生成精确文字"的说明；核心 prompt 文字本身不被改写（由
    packet_builder 已保证不含精确文字，§7 硬规则）。
    """
    safe_hint = overlay_safe_comment(packet)
    verbatim = [str(v) for v in _listify(packet.get("overlay_requirements"))
                if str(v).upper() in VERBATIM_CLASSES]
    extras = []
    if verbatim:
        extras.append("do not generate exact text, UI, logos, numbers or data "
                      "in this shot — those layers are added in post-production (§7)")
    if safe_hint:
        extras.append(safe_hint)
    if not extras:
        return prompt
    sep = "\n\n" if prompt.strip() else ""
    return f"{prompt}{sep}" + "\n".join(extras)


class ProviderAdapter:
    """§26 Provider Adapter 抽象（四步接口）。

    基类实现 provider-neutral 部分；子类/配置模板覆盖 provider-specific 部分
    （`build_provider_prompt` 的模型特有语气与参数命名）。核心代码不出现模型名。
    """

    provider_id: str = "generic"

    def __init__(self, provider_cap: Optional[dict] = None):
        self.provider_cap = dict(provider_cap) if isinstance(provider_cap, dict) else {}
        if self.provider_cap.get("provider_id"):
            self.provider_id = str(self.provider_cap["provider_id"])

    # -- 四步接口（§26） ----------------------------------------------------

    def normalize(self, packet: dict) -> dict:
        """Step 1：normalize packet → 统一字段（provider-neutral，§25）。

        返回一个规范化 dict：packet_id / purpose / duration / resolution /
        aspect_ratio / fps / camera_movement / audio_requirement / seed /
        reference_inputs / overlay_safe_area / text_safe_area /
        model_ready_prompt / negative_prompt。缺省字段不编造。
        """
        if not isinstance(packet, dict):
            raise ValueError("normalize 需要 GV Packet dict")
        out = {
            "packet_id": packet.get("packet_id"),
            "purpose": packet.get("purpose"),
            "duration": packet.get("duration"),
            "resolution": packet.get("resolution"),
            "aspect_ratio": packet.get("aspect_ratio"),
            "fps": packet.get("fps"),
            "camera_movement": packet.get("camera_movement"),
            "audio_requirement": packet.get("audio_requirement"),
            "seed": packet.get("seed"),
            "reference_inputs": packet.get("reference_inputs") or [],
            "overlay_safe_area": packet.get("overlay_safe_area"),
            "text_safe_area": packet.get("text_safe_area"),
            "model_ready_prompt": packet.get("model_ready_prompt"),
            "negative_prompt": merge_negative_constraints(packet, self.provider_cap),
        }
        return out

    def capability_check(self, packet: dict, provider_cap: Optional[dict] = None) -> dict:
        """Step 2：capability check（§27；委托 capability.py，见其 docstring）。"""
        cap = provider_cap if isinstance(provider_cap, dict) else self.provider_cap
        return capability_check(packet, cap)

    def build_provider_prompt(self, packet: dict) -> dict:
        """Step 3：provider-specific prompt（基类 = provider-neutral 部分）。

        返回 {model_ready_prompt, negative_prompt, prompt_hash? 占位}。
        子类可覆盖以注入模型特有语气/参数命名；基类保证 §7/§14/§26 中性规则。
        """
        norm = self.normalize(packet)
        base_prompt = str(norm.get("model_ready_prompt") or packet.get("model_ready_prompt") or "")
        prompt = text_safe_conversion(base_prompt, packet)
        negative = merge_negative_constraints(packet, self.provider_cap)
        return {
            "provider_id": self.provider_id,
            "model_ready_prompt": prompt,
            "negative_prompt": negative,
        }

    def generation_instructions(self, packet: dict,
                                provider_cap: Optional[dict] = None) -> dict:
        """Step 4：generation instructions（生成说明；不调用任何 API）。

        输出参数卡：duration / resolution / aspect_ratio / camera / seed / audio /
        variants，均按 provider 能力档取值（不支持项给出"不支持/缺省"说明）。
        """
        cap = provider_cap if isinstance(provider_cap, dict) else self.provider_cap
        check = capability_check(packet, cap)
        norm = self.normalize(packet)

        duration = norm.get("duration")
        resolution = norm.get("resolution")
        aspect = norm.get("aspect_ratio")
        if check["unsupported"]:
            for u in check["unsupported"]:
                if u["item"] == "duration":
                    duration = f"{duration} (不支持，{u['suggestion']})"
                elif u["item"] == "resolution":
                    resolution = f"{resolution} (不支持，{u['suggestion']})"
                elif u["item"] == "aspect_ratios":
                    aspect = f"{aspect} (不支持，{u['suggestion']})"

        cam = str(norm.get("camera_movement") or "STATIC").upper()
        if cam and cam != "STATIC" and not self._cap_bool(cap, "camera_control"):
            cam = f"{cam} (provider 不支持相机控制，按 STATIC 处理，§17)"

        instructions = {
            "provider_id": self.provider_id,
            "mode": "generation_instructions",
            "params": {
                "duration_seconds": duration,
                "resolution": resolution,
                "aspect_ratio": aspect,
                "fps": norm.get("fps"),
                "camera_movement": cam,
                "seed": norm.get("seed") if self._cap_bool(cap, "seed_control")
                        else ("provider 不支持种子控制" if norm.get("seed") is not None else None),
                "audio_generation": bool(self._cap_bool(cap, "audio_generation")),
                "recommended_variant_count": packet.get("recommended_variant_count"),
            },
            "capability_ok": check["ok"],
            "unsupported": check["unsupported"],
            "warnings": check["warnings"],
            "note": "本模块只生成'生成说明'，不调用任何第三方生成 API（P6-06 硬规则）。",
        }
        return instructions

    # -- 工具 ----------------------------------------------------------------

    @staticmethod
    def _cap_bool(provider_cap: dict, field: str) -> bool:
        v = provider_cap.get(field) if isinstance(provider_cap, dict) else None
        if v is True or str(v).lower() in ("partial", "manual_or_semiautomatic",
                                           "requires_authentication"):
            return True
        return False


class TemplatePromptAdapter(ProviderAdapter):
    """配置模板驱动子类（§28 配置层扩展，无需改代码）。

    从 provider 配置文件读取 `prompt_style`（生成 prompt 语气前缀）与
    `prompt_template`（prompt 组装模板，用 {model_ready_prompt} / {negative_prompt}
    占位符），覆盖 build_provider_prompt 的 provider-specific 部分。
    任何 provider 配置文件都可写这些字段；缺省时回退基类实现。
    """

    def __init__(self, provider_cap: Optional[dict] = None):
        super().__init__(provider_cap)
        self.prompt_style = self.provider_cap.get("prompt_style")
        self.prompt_template = self.provider_cap.get("prompt_template")

    def build_provider_prompt(self, packet: dict) -> dict:
        base = super().build_provider_prompt(packet)
        prompt = str(base.get("model_ready_prompt") or "")
        style = self.prompt_style
        if isinstance(style, str) and style.strip() and style.strip() not in prompt:
            prompt = f"{style.strip()} {prompt}".strip()
        tpl = self.prompt_template
        if isinstance(tpl, str) and tpl.strip():
            prompt = (tpl.replace("{model_ready_prompt}", prompt)
                         .replace("{negative_prompt}", base.get("negative_prompt") or ""))
        base["model_ready_prompt"] = prompt
        return base
