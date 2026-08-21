#!/usr/bin/env python3
"""manual_web.py — MANUAL_WEB Adapter（Phase-6 Prompt §29 一等公民；P6-06）.

用户可能选择自己去网页端生成（§29 流程）：

    ZHOU → Production Packet → 用户外部生成 → 用户返回文件 → Asset Ingestion

本 adapter 负责"导出"步骤：把 Provider-neutral Production Packet 落盘为

- `{packet_id}_prompt.txt`：model_ready_prompt + negative_prompt + 关键参数卡
- `{packet_id}_instructions.md`：网页端操作步骤（参数如何填、变体数量、返回文件
  命名建议 A###_v1.mp4，§90 版本化 + §92 variant-id）

并返回 `waiting_user` 状态记录（供 workflow.run_manual 落状态，本函数不阻塞等待、
不产生任何生成调用）。

技术约束：**Python3 stdlib only**；无 LLM；无联网；确定性（文件内容只依赖输入）。
代码风格照抄 modules/production/planner.py。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import importlib as _importlib

# 包目录含连字符（adapters/generative-video），import 语句无法写这段名——
# 按本包约定用 importlib 加载兄弟模块（base.py / capability.py）。
_base_mod = _importlib.import_module("adapters.generative-video.base")
ProviderAdapter = _base_mod.ProviderAdapter
merge_negative_constraints = _base_mod.merge_negative_constraints
overlay_safe_comment = _base_mod.overlay_safe_comment
_capability_mod = _importlib.import_module("adapters.generative-video.capability")
capability_check = _capability_mod.capability_check


def _params_card(packet: dict, provider_cap: dict) -> str:
    """关键参数卡（供 prompt.txt / instructions.md 共用，§9/§27 字段）。"""
    lines = []
    cap = provider_cap or {}
    lines.append(f"packet_id          : {packet.get('packet_id')}")
    lines.append(f"shot/layer         : {packet.get('shot_id')} / {packet.get('layer_id')}")
    lines.append(f"purpose            : {packet.get('purpose')}")
    lines.append(f"duration (s)       : {packet.get('duration')}")
    lines.append(f"aspect_ratio       : {packet.get('aspect_ratio')}")
    res = packet.get("resolution")
    if isinstance(res, dict):
        lines.append(f"resolution         : {res.get('w')}x{res.get('h')}")
    else:
        lines.append(f"resolution         : {res}")
    lines.append(f"fps                : {packet.get('fps')}")
    cam = packet.get("camera_movement") or packet.get("camera") or "STATIC"
    lines.append(f"camera_movement    : {cam}")
    lines.append(f"recommended variants: {packet.get('recommended_variant_count')}")
    lines.append(f"provider (cap 档案) : {cap.get('provider_id')} / model={cap.get('model')}")
    lines.append(f"provider api       : api_available={cap.get('api_available')} "
                 f"(本通道为人工网页生成，无 API)")
    return "\n".join(lines)


def build_prompt_text(packet: dict, provider_cap: Optional[dict] = None) -> str:
    """组装 {packet_id}_prompt.txt 的完整文本（含 model_ready_prompt，AC-4）。"""
    cap = provider_cap or {}
    adapter = ProviderAdapter(cap)
    built = adapter.build_provider_prompt(packet)
    prompt = built.get("model_ready_prompt") or packet.get("model_ready_prompt") or ""
    negative = built.get("negative_prompt") or merge_negative_constraints(packet, cap)
    safe = overlay_safe_comment(packet)
    lines = [
        f"# Prompt for packet {packet.get('packet_id')} (provider-neutral, §25)",
        f"# shot={packet.get('shot_id')} layer={packet.get('layer_id')}",
        "",
        "## model_ready_prompt",
        prompt,
        "",
        "## negative_prompt",
        negative,
        "",
        "## key parameters",
        _params_card(packet, cap),
    ]
    if safe:
        lines += ["", "## overlay safe note", safe]
    return "\n".join(lines)


def build_instructions_md(packet: dict, provider_cap: Optional[dict] = None) -> str:
    """组装 {packet_id}_instructions.md 网页端操作步骤（§29/§90/§92）。"""
    cap = provider_cap or {}
    check = capability_check(packet, cap)
    vid = str(packet.get("packet_id") or "GV-000").replace("GV-", "A")
    naming = f"{vid}_v1.mp4"
    lines = [
        f"# 人工网页生成操作说明（MANUAL_WEB，§29 一等公民）",
        "",
        f"packet: {packet.get('packet_id')}  shot: {packet.get('shot_id')}",
        "",
        "## 1) 打开生成网页（用户自选服务）",
        "   - 本通道不绑定任何具体服务；请使用您已订阅 / 已授权的视频生成服务。",
        "   - 无真实 API 凭据（api_available=false），一切由用户在网页端完成。",
        "",
        "## 2) 参数填写（对照同目录 prompt.txt 的 key parameters）",
        f"   - 时长：{packet.get('duration')} 秒（如网页只支持档位，取最接近档）",
        f"   - 分辨率：{packet.get('resolution')}",
        f"   - 长宽比：{packet.get('aspect_ratio')}",
        f"   - 运镜：{packet.get('camera_movement') or 'STATIC'}",
        f"   - 变体数量：{packet.get('recommended_variant_count')}（§33-34 按风险定，勿默认 10）",
        f"   - 首/尾帧要求：{packet.get('start_frame') or '无'} / {packet.get('end_frame') or '无'}（§21）",
        "   - 负向词：粘贴 prompt.txt 的 negative_prompt 全文",
        "",
        "## 3) 能力缺口提示（capability_check，§27）",
    ]
    if check["unsupported"]:
        for u in check["unsupported"]:
            lines.append(f"   - [unsupported] {u['item']}: {u['request']} → {u['suggestion']}")
    else:
        lines.append("   - 无能力缺口。")
    if check["warnings"]:
        for w in check["warnings"]:
            lines.append(f"   - [note] {w}")
    lines += [
        "",
        "## 4) 变体生成",
        "   - 生成推荐数量的变体（编号 variant-01 / variant-02 …，§92）。",
        "   - 不要为了省事只生成 1 条就用（§35 候选评审）。",
        "",
        "## 5) 返回文件命名建议（§90 版本化，勿覆盖）",
        f"   - 每个文件命名：`{naming}`（后续版本 v2/v3 递增）",
        "   - 同时提供 variant 编号：如 `A012_v1_variant-02.mp4`",
        "   - 文件放回工作区后交给 P6-04 Asset Ingestion（§42/§43）。",
        "",
        "## 6) 注意",
        "   - 生成视频不是最终画面：按 postproduction_plan 与 timeline_hint 处理（§49/§133）。",
        "   - 涉及上传私人素材时必须先过 privacy gate 并获批准（§32 硬规则，绝不自动上传）。",
    ]
    return "\n".join(lines)


def export_packet(packet: dict, provider_cap: dict, out_dir) -> dict:
    """§29 一等公民：export_packet → 落盘 prompt.txt + instructions.md。

    返回 waiting_user 状态记录（workflow.run_manual 使用）；本函数不阻塞等待外部文件，
    只落导出物与状态记录。确定性强校验：packet 需含 model_ready_prompt 或可推导内容。
    """
    if not isinstance(packet, dict) or not packet.get("packet_id"):
        raise ValueError("export_packet 需要含 packet_id 的 GV Packet")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    packet_id = str(packet["packet_id"])
    prompt_path = out / f"{packet_id}_prompt.txt"
    instr_path = out / f"{packet_id}_instructions.md"

    prompt_text = build_prompt_text(packet, provider_cap)
    instr_text = build_instructions_md(packet, provider_cap)
    prompt_path.write_text(prompt_text, encoding="utf-8")
    instr_path.write_text(instr_text, encoding="utf-8")

    return {
        "status": "WAITING_USER",
        "packet_id": packet_id,
        "provider_id": (provider_cap or {}).get("provider_id"),
        "exports": [str(prompt_path), str(instr_path)],
        "waiting_for": "external video file from user's web generation（§29）",
        "return_file_naming": f"{packet_id.replace('GV-', 'A')}_v1.mp4",
        "handoff_note": "用户返回文件后交给 P6-04 Asset Ingestion（§42）",
        "blocks_nothing": True,
    }
