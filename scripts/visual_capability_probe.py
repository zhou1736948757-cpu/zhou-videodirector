#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
visual_capability_probe.py — 运行时视觉能力探测（Runtime Visual Capability Probe）

设计出处：chief 方案 2026-08-16；本脚本与 workflows/reference-analysis.md「视觉能力探测（三档路由）」节
联动，并按 docs/external-capability-policy.md「运行时视觉能力探测」节定义。探测不是新的 Integration Mode，
是 EXTERNAL_SKILL / PROVIDER 既有组合之上的运行时前置检查。

用途：ZHOU_Videodirector 在 Phase 2 Reference Analysis / Phase 8 Full QA 入口调用本脚本，探测
【当前模型视觉能力 × 本机工具可用性】，按三档路由选择视觉通道，杜绝"假设能力可用"。

三档路由：
  A NATIVE_VISION            : 当前模型支持图片/视频输入 -> 当前 agent 直接看（video-analyst 抽帧可辅助）。
  B TEXT_WITH_VISION_BRIDGE  : 当前模型纯文本，且 ds-vision-skill（mimo-vision.sh）可用
                               -> 抽帧链（video-analyst CLI 可用则用它；否则 ffmpeg 抽帧 8.x）
                                  -> mimo-vision.sh（mimo-v2.5，OpenCode Go 视觉通道）看图
                                  -> 当前 agent 汇总，结果按 video-analyst 同名 schema 写回，再归一进 ZHOU。
  C TEXT_NO_VISION           : 当前模型纯文本，且 ds-vision 不可用/被拒
                               -> ASR（video-analyst 规格 ASR 可用则用；否则 ffprobe 音频元数据）
                                  + 字幕 + 降级分析，报告头如实标注 vision=degraded。

诚实原则：探测不到就询问用户，绝不假设能力可用。
- 模型名不在内置已知表时 model_vision=UNKNOWN，输出"请人工确认能否读视频/读图"。
- mimo-vision.sh 只检查存在性 / 可执行 / bash 语法（bash -n），不真跑图片、不发网络请求。

用法：
  python3 scripts/visual_capability_probe.py [--model <模型名>] [--json]
  模型名优先级：--model > 环境变量 PROBE_MODEL > 环境变量 MODEL > 默认 deepseek-v4-flash。
  确定性、纯 stdlib、无网络。--json 合法，退出码恒为 0。
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

# 内置已知模型视觉能力表（模型名 -> 视觉能力）。未知模型 -> UNKNOWN -> 请人工确认。
KNOWN_MODEL_VISION = {
    "deepseek-v4-pro": "TEXT",
    "deepseek-v4-flash": "TEXT",
    "minimax-m3": "TEXT",
    "mimo-v2.5": "IMAGE",
}

TIER_LABELS = {
    "A": "NATIVE_VISION",
    "B": "TEXT_WITH_VISION_BRIDGE",
    "C": "TEXT_NO_VISION",
    "UNKNOWN": "UNKNOWN",
}

MIMO_VISION_SH = os.path.expanduser("~/.agents/skills/ds-vision-skill/scripts/mimo-vision.sh")
YT_DLP_FIXED_PATHS = ["/Users/mac/skills/yt-dlp"]
VIDEO_ANALYST_SKILL_DIR = os.path.expanduser("~/.agents/skills/video-analyst")


def detect_video_analyst_cli():
    """video-analyst CLI：which video-analyst（~/.local/bin 入口）存在且可执行 → available。
    不存在 → UNINSTALLED_SKILL（如实上报，绝不因 SKILL.md 规格存在而误判为可用）。"""
    p = shutil.which("video-analyst")
    if p and os.path.isfile(p) and os.access(p, os.X_OK):
        return "available"
    return "UNINSTALLED_SKILL"


def detect_ffmpeg():
    """ffprobe 一并探测但并入 notes；抽帧依赖 ffmpeg。"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg and os.access(ffmpeg, os.X_OK):
        return "available"
    return "missing"


def detect_yt_dlp():
    """PATH 解析 + /Users/mac/skills/yt-dlp 固定路径兜底。"""
    found = shutil.which("yt-dlp")
    if found:
        return "available"
    for p in YT_DLP_FIXED_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return "available"
    return "missing"


def detect_mimo_vision():
    """mimo-vision.sh：存在性 + 可执行 + bash -n 语法检查。不执行脚本、不发网络、不跑图片。"""
    if not os.path.isfile(MIMO_VISION_SH):
        return "missing"
    if not os.access(MIMO_VISION_SH, os.X_OK):
        return "missing"
    try:
        r = subprocess.run(["bash", "-n", MIMO_VISION_SH], capture_output=True, timeout=10)
        if r.returncode != 0:
            return "missing"
    except Exception:
        return "missing"
    return "available"


def resolve_model(args):
    """模型名优先级：--model > PROBE_MODEL > MODEL > 默认 deepseek-v4-flash。"""
    if args.model:
        return args.model.strip()
    for env_key in ("PROBE_MODEL", "MODEL"):
        v = os.environ.get(env_key, "").strip()
        if v:
            return v
    return "deepseek-v4-flash"


def determine_tier(model_vision, mimo_available):
    if model_vision == "IMAGE":
        return "A"
    if model_vision == "TEXT":
        return "B" if mimo_available else "C"
    return "UNKNOWN"


def build_pipeline(tier, tools):
    va_cli = tools.get("video_analyst_cli")
    frame_tool = (
        "video-analyst CLI（可用则优先）"
        if va_cli == "available"
        else "ffmpeg 抽帧（8.x；video-analyst CLI 未安装）"
    )
    if tier == "A":
        return {
            "steps": [
                "当前模型原生支持图片/视频输入（NATIVE_VISION）",
                "直接把参考视频 / 抽帧图交给当前 agent 阅读分析",
                "video-analyst CLI 可用时也可用它抽帧做输入准备",
            ],
            "variables": {
                "vision_channel": "agent-native",
                "vision_status": "native",
                "frame_tool": "video-analyst CLI（可用则用）| ffmpeg 抽帧（8.x）",
            },
        }
    if tier == "B":
        return {
            "steps": [
                "抽帧：" + frame_tool + "；fps 1~15 按需",
                "抽出的帧经 mimo-vision.sh（mimo-v2.5，OpenCode Go 视觉通道）看图",
                "当前 agent 汇总视觉结果，写入 video-analyst 同名 schema（CoarseBatchAnalysis / "
                "VideoStructure / RefinementPlan / FineBatchAnalysis / temporal events），再归一进 ZHOU",
            ],
            "variables": {
                "vision_channel": "mimo-v2.5 via ds-vision-skill (mimo-vision.sh)",
                "vision_status": "bridged",
                "frame_tool": frame_tool,
                "cloud_notice": "图片会上传 OpenCode Go 云端；敏感内容需用户确认；用户拒绝则降级 Tier C",
            },
        }
    if tier == "C":
        return {
            "steps": [
                "无视觉通道：不猜测画面内容",
                "ASR：video-analyst 规格的 ASR 可用则用；否则 ffprobe 音频元数据兜底",
                "字幕：提取 / 激活字幕作为辅助上下文（非绝对事实）",
                "降级分析，REFERENCE_ANALYSIS.md / QA 报告头如实标注 vision=degraded",
            ],
            "variables": {
                "vision_channel": "none",
                "vision_status": "degraded",
                "audio_tool": "ASR（video-analyst，可用则用）| ffprobe 音频元数据",
                "subtitle_tool": "字幕提取（可用时）",
            },
        }
    return {
        "steps": [
            "模型视觉能力未知：请人工确认当前模型能否读视频 / 读图",
            "确认前不进入任何视觉依赖流水线，不假设能力可用",
        ],
        "variables": {
            "vision_channel": "unknown",
            "vision_status": "needs_human_confirmation",
        },
    }


def build_notes(tools, model_vision):
    notes = []
    if tools["video_analyst_cli"] == "UNINSTALLED_SKILL":
        notes.append(
            "video-analyst CLI 命令未安装（~/.local/bin 无 video-analyst 可执行入口）；"
            "probe 如实上报 UNINSTALLED_SKILL，不作为可用能力。"
        )
    if tools["ffmpeg"] == "available":
        ffprobe = shutil.which("ffprobe")
        notes.append("ffmpeg 可用（8.x）；" + ("ffprobe 可用。" if ffprobe else "ffprobe 未在 PATH，元数据兜底不可用。"))
    if tools["mimo_vision"] == "available":
        notes.append("mimo-vision.sh 存在且语法检查通过；运行时调用会将图片上传 OpenCode Go 云端，敏感内容需用户确认。")
    if model_vision == "UNKNOWN":
        notes.append("模型不在内置已知表（deepseek-v4-pro / deepseek-v4-flash / minimax-m3 / mimo-v2.5），"
                     "请人工确认能否读视频/读图。")
    return notes


def run_probe(args):
    model = resolve_model(args)
    model_key = model.lower()
    model_vision = KNOWN_MODEL_VISION.get(model_key, "UNKNOWN")

    tools = {
        "video_analyst_cli": detect_video_analyst_cli(),
        "ffmpeg": detect_ffmpeg(),
        "yt_dlp": detect_yt_dlp(),
        "mimo_vision": detect_mimo_vision(),
    }
    tier = determine_tier(model_vision, tools["mimo_vision"] == "available")
    pipeline = build_pipeline(tier, tools)
    notes = build_notes(tools, model_vision)

    result = {
        "probe_timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model,
        "model_vision": model_vision,
        "tools": tools,
        "detected_tier": tier,
        "tier_label": TIER_LABELS.get(tier, "UNKNOWN"),
        "pipeline": pipeline,
        "notes": notes,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description="Runtime Visual Capability Probe（三档路由）")
    parser.add_argument("--model", help="当前模型名；未知模型 -> UNKNOWN -> 请人工确认")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    result = run_probe(args)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("=== Runtime Visual Capability Probe ===")
        print(f"probe_timestamp : {result['probe_timestamp']}")
        print(f"model           : {result['model']}  (model_vision={result['model_vision']})")
        print(f"tools           : {json.dumps(result['tools'], ensure_ascii=False)}")
        print(f"detected_tier   : {result['detected_tier']}  ({result['tier_label']})")
        print(f"pipeline        : {json.dumps(result['pipeline'], ensure_ascii=False)}")
        for n in result["notes"]:
            print(f"note            : {n}")
        if result["model_vision"] == "UNKNOWN":
            print("HUMAN_ACTION_REQUIRED: 请人工确认当前模型能否读视频/读图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())