#!/usr/bin/env python3
"""adapters/generative-video — Generative Video Provider Adapter（Phase-6 Prompt §26-27；P6-06）.

Provider Adapter 抽象（§26 四步：normalize → capability_check → provider-specific
prompt → generation instructions）+ MANUAL_WEB 人工网页生成 adapter（§29 一等公民）+
Provider 配置加载（§28 配置化扩展，核心代码零硬编码模型名）。

模块导出：
    ProviderAdapter / TemplatePromptAdapter     （base.py，§26/§28）
    capability_check                            （capability.py，§27）
    export_packet / build_prompt_text           （manual_web.py，§29）
    load_providers / load_provider_file         （本文件，§28）

硬规则：本包不产生任何真实第三方生成 API 调用，不自动上传任何用户素材（§32）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

# 允许从 skill 根目录 import scripts.registry（stdlib YAML/JSON 桥，Phase-4 产物）。
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.registry import load_json_or_yaml  # noqa: E402  （stdlib 桥）

# 包目录含连字符（adapters/generative-video），Python 标识符禁止 '-'，
# 连字符包名只能 importlib 全名加载（base/capability/manual_web）。
_importlib = __import__("importlib")
_base_mod = _importlib.import_module("adapters.generative-video.base")
_cap_mod = _importlib.import_module("adapters.generative-video.capability")
_manual_mod = _importlib.import_module("adapters.generative-video.manual_web")
ProviderAdapter = _base_mod.ProviderAdapter
TemplatePromptAdapter = _base_mod.TemplatePromptAdapter
capability_check = _cap_mod.capability_check
export_packet = _manual_mod.export_packet
build_prompt_text = _manual_mod.build_prompt_text
build_instructions_md = _manual_mod.build_instructions_md

__all__ = [
    "ProviderAdapter",
    "TemplatePromptAdapter",
    "capability_check",
    "export_packet",
    "build_prompt_text",
    "build_instructions_md",
    "load_providers",
    "load_provider_file",
    "MANUAL_WEB_ADAPTER",
]

#: §27 / P6-01 schema 必需字段（generative-video-provider.schema.json）
REQUIRED_FIELDS = (
    "provider_id", "model", "text_to_video", "image_to_video", "first_last_frame",
    "reference_image", "character_reference", "camera_control", "duration_options",
    "resolution_options", "aspect_ratios", "audio_generation", "seed_control",
    "commercial_terms", "api_available", "manual_generation_supported",
)

#: MANUAL_WEB 内置档案 id（§29 一等公民；对应 providers/generative-video/manual-web.yaml）
MANUAL_WEB_ADAPTER = "manual-web"

_PROVIDER_ID_RE = re.compile(r"^[a-z0-9-]+$")


def _norm_capability(data: dict) -> dict:
    """归一 provider 档案：必需字段就位 + provider_id 模式校验（确定性）。"""
    if not isinstance(data, dict):
        raise ValueError("provider 配置必须是 dict")
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ValueError(f"provider 配置缺少必需字段: {missing}")
    pid = str(data["provider_id"])
    if not _PROVIDER_ID_RE.match(pid):
        raise ValueError(f"provider_id 必须匹配 ^[a-z0-9-]+$，得到 {pid!r}")
    cap = dict(data)
    cap.setdefault("negative_prompt_supported", False)
    cap.setdefault("max_prompt_length", None)
    cap.setdefault("notes", None)
    cap.setdefault("status", "unconfigured")
    return cap


def load_provider_file(path) -> dict:
    """读单个 provider 配置文件（*.yaml/*.yml/*.json，stdlib YAML 子集或 JSON）。

    解析失败 → 抛 ValueError（配置文件作者错误，确定性暴露）。
    """
    p = Path(path)
    data, err = load_json_or_yaml(p)
    if err is not None:
        raise ValueError(f"provider 配置解析失败 {p}: {err}")
    if not isinstance(data, dict):
        raise ValueError(f"provider 配置必须是 mapping: {p}")
    return _norm_capability(data)


def load_providers(config_dir) -> dict:
    """§28：读取 providers/generative-video/*.yaml(.yml/.json) → {provider_id: cap}。

    跳过 README / template（template.yaml 仍是合法配置，但如果提供方可使用；这里
    仅跳过非数据文件）。字段对齐 P6-01 generative-video-provider.schema.json。
    """
    cfg = Path(config_dir)
    if not cfg.is_dir():
        raise ValueError(f"provider 配置目录不存在: {cfg}")
    providers: dict = {}
    for p in sorted(cfg.iterdir()):
        if not p.is_file() or p.suffix.lower() not in (".yaml", ".yml", ".json"):
            continue
        if p.name.lower() in ("readme.md", "readme", "template.yaml", "template.yml"):
            continue
        cap = load_provider_file(p)
        providers[cap["provider_id"]] = cap
    return providers


def get_provider(config_dir, provider_id: str) -> Optional[dict]:
    """按 provider_id 取能力档案（未找到 → None，调用方自行降级）。"""
    return load_providers(config_dir).get(str(provider_id))


if __name__ == "__main__":  # pragma: no cover
    import os

    root = Path(__file__).resolve().parents[2]
    default_dir = root / "providers" / "generative-video"
    d = default_dir if default_dir.is_dir() else Path(os.getcwd())
    provs = load_providers(d)
    for pid, cap in sorted(provs.items()):
        print(f"{pid}: api_available={cap.get('api_available')} "
              f"manual={cap.get('manual_generation_supported')} "
              f"status={cap.get('status')}")
    print(f"loaded {len(provs)} provider(s) from {d}")
