#!/usr/bin/env python3
"""review.py — Candidate Review & QA（Phase-6 Prompt §35-41 / §100-104 / §117；P6-05）.

Generative Video / 外部素材候选的"质量关"：候选不能"第一条直接用"（§35）。本模块建立
GENERATIVE_VIDEO_REVIEW 与外部素材验收：

- §36 18 维评审（prompt_adherence … overall_production_value），每维 0-10 且必须带
  evidence 来源（machine | human | vision_model | packet_diff | adjacent_data | UNKNOWN）
- §37 13 类 AI 伪影检测（face/hand deformation … temporal melting）
- §38 0-100 分 + PASS / PASS_WITH_ISSUES / REGENERATE / REJECT 判定
- §39-40 针对性重生成诊断（6 类失败：composition/motion/identity/camera/physics/
  prompt_overload；overload → 简化建议而非加词）
- §100 技术质量校验：机器可测项用 ffmpeg 实测 —— flicker（帧亮度序列信号统计）、
  freeze / 黑帧（抽帧比对）、temporal_coherence（相邻抽帧差值方差）、composition
  （overlay 静区亮度/复杂度，仅作弱证据）
- §102 editorial usability 五项清单（serves_narration / usable_duration_match /
  clean_entry_exit / overlay_space_sufficient / adjacent_camera_direction）
- §103-104 验收状态机（CANDIDATE→SELECTED→APPROVED/…→NORMALIZED→READY_FOR_TIMELINE，
  READY_FOR_TIMELINE 四前置条件，不满足抛非法迁移并说明缺哪项）
- §92-93 多候选 rank / select / reject（rejected 保 metadata 不保 payload）

引擎确定性铁律：**本模块不会"看"视频**。能机器测的项用 ffmpeg 实测；需视觉判断的
维度（anatomy / physics / 各类伪影等）只能依据调用方传入的 evidence（human /
vision_model / packet_diff / adjacent_data）聚合判定。evidence 缺失 → 该维度记
NEEDS_EVIDENCE（score 按 0 处理，verdict 不得 PASS）；禁止把"需视觉判断"伪装成
"已机器判定"。

技术约束：Python3 stdlib + subprocess(ffmpeg/ffprobe)；不联网、无 LLM、确定性。
与 P6-04 adapters/external-visual/probe.py 互不依赖：本单自带最小 ffprobe 桥
（_probe_video / _sample_frames），P6-04 落盘后可去重（对齐点见 P6-05 REPORT）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 共享契约常量（字段/枚举与 P6-01 video-review.schema.json 定义对齐；
# schema 尚未落盘前以本文件为准，P6-01 落盘后按 schema 复核，见 REPORT）
# ---------------------------------------------------------------------------

REVIEW_ID_RE = re.compile(r"^RV-\d{3}$")

VERDICTS = ("PASS", "PASS_WITH_ISSUES", "REGENERATE", "REJECT")          # §38
_VERDICT_ORDER = {"REJECT": 0, "REGENERATE": 1, "PASS_WITH_ISSUES": 2, "PASS": 3}

EVIDENCE_SOURCES = ("machine", "human", "vision_model", "packet_diff", "adjacent_data", "UNKNOWN")

# §36 18 维度（名称与 P6-01 字段表逐字一致）。权重 §38：prompt_adherence×2、
# composition×1.5、motion/camera/temporal×1.5、其余×1。
DIMENSIONS = (
    ("prompt_adherence", 2.0),
    ("composition", 1.5),
    ("subject_consistency", 1.0),
    ("motion_quality", 1.5),
    ("camera_quality", 1.5),
    ("temporal_coherence", 1.5),
    ("anatomy", 1.0),
    ("physics", 1.0),
    ("lighting", 1.0),
    ("continuity", 1.0),
    ("visual_bible_fit", 1.0),
    ("text_artifacts", 1.0),
    ("unwanted_logos", 1.0),
    ("flicker", 1.0),
    ("warping", 1.0),
    ("usability_for_overlays", 1.0),
    ("editability", 1.0),
    ("overall_production_value", 1.0),
)
DIMENSION_NAMES = tuple(n for n, _ in DIMENSIONS)
DIMENSION_WEIGHTS = dict(DIMENSIONS)
TOTAL_WEIGHT = sum(DIMENSION_WEIGHTS.values())  # 21.0

# §37 13 类 AI 伪影（与 P6-01 字段表逐字一致）
ARTIFACTS = (
    "face_deformation", "hand_deformation", "object_morphing", "background_instability",
    "texture_crawling", "flicker", "camera_jump", "identity_drift", "lighting_inconsistency",
    "impossible_geometry", "text_garbage", "logo_garbage", "temporal_melting",
)
ARTIFACT_NAMES = tuple(ARTIFACTS)

# §37 硬伪影：任何 detected=true 的 hard 类 → verdict 最高 PASS_WITH_ISSUES，
# 且 §37 语义要求不得 APPROVED（Test 8 / AC-2）。
HARD_ARTIFACTS = ("face_deformation", "hand_deformation", "text_garbage",
                  "logo_garbage", "identity_drift", "impossible_geometry")

# §103 验收状态机（显式允许迁移；REJECTED / READY_FOR_TIMELINE 为终态）
ACCEPTANCE_STATES = ("CANDIDATE", "SELECTED", "APPROVED", "REJECTED",
                     "REVISION_REQUIRED", "NORMALIZED", "READY_FOR_TIMELINE")
_TRANSITIONS = {
    "CANDIDATE": {"SELECTED", "REJECTED", "REVISION_REQUIRED"},
    "SELECTED": {"APPROVED", "REJECTED", "REVISION_REQUIRED"},
    "APPROVED": {"NORMALIZED", "REJECTED", "REVISION_REQUIRED"},
    "REVISION_REQUIRED": {"CANDIDATE", "REJECTED"},
    "NORMALIZED": {"READY_FOR_TIMELINE", "REJECTED", "REVISION_REQUIRED"},
    "REJECTED": set(),
    "READY_FOR_TIMELINE": set(),
}
_FORWARD = {  # 自动推进（advance_acceptance target=None 时用）
    "CANDIDATE": "SELECTED", "SELECTED": "APPROVED", "APPROVED": "NORMALIZED",
    "NORMALIZED": "READY_FOR_TIMELINE", "REVISION_REQUIRED": "CANDIDATE",
    "REJECTED": None, "READY_FOR_TIMELINE": None,
}

# §39 失败分类 6 类
FAILURE_CLASSES = ("composition", "motion", "identity", "camera", "physics", "prompt_overload")

# §117 失败恢复阶梯：attempt 1→prompt refinement；2→reduce complexity；
# 3→alternative strategy；>3→BLOCKED + 建议清单（全部 approval_required）。
# 字符串与 P6-06 workflow.py RETRY_STEPS 逐字一致（以 PHASE6_PROMPT §117 原词为准）。
NEXT_STEP_BY_ATTEMPT = {1: "prompt_refinement", 2: "reduce_complexity", 3: "alternative_strategy"}
BLOCKED_ALTERNATIVES = ("split_shot", "use_3D", "use_footage", "use_hybrid")

# §102 editorial usability 五项
EDITORIAL_ITEMS = ("serves_narration", "usable_duration_match", "clean_entry_exit",
                   "overlay_space_sufficient", "adjacent_camera_direction")

# ---------------------------------------------------------------------------
# 机器检测阈值（确定性常量，全部写死并在 docstring 注明依据）
# ---------------------------------------------------------------------------
SAMPLE_WIDTH = 320                 # 抽帧统计用宽度（缩放到 320x180，纯 Python 统计）
SAMPLE_HEIGHT = 180
SAMPLE_TARGET = 24                 # 目标采样帧数
SAMPLE_MAX_FRAMES = 64             # 单次采样帧数上限
SAMPLE_MAX_FPS = 4.0               # 采样最高 fps（避免超短视频帧数爆炸）

FLICKER_AMP_THRESHOLD = 15.0       # 帧平均亮度峰谷差（0-255）低于该值不算 flicker
FLICKER_OSC_RATIO = 0.5            # 相邻亮度差符号翻转比例阈值（高频振荡特征）
FREEZE_DIFF_THRESHOLD = 1.5        # 相邻采样帧平均绝对像素差（0-255）低于该值视为"相同"
FREEZE_MIN_DURATION_S = 1.2        # 连续相同帧时长阈值（§100 freeze issue）。
                                  # 帧数↔间隔数换算：best_run 计"连续相同帧间隔数"（diffs 条数），
                                  # 时长 = 间隔数 × 采样间隔；run==0 → 0.0（E2E B：无冻结不误报）。
BLACK_LUMA_THRESHOLD = 18.0        # 平均亮度低于该值视为黑帧
BLACK_MIN_RUN_S = 0.5              # 连续黑帧时长阈值（§100 black frame issue）。
                                  # 帧数↔间隔数换算：black_best 计"连续黑帧数"（帧数），
                                  # 时长 = max(0, 帧数-1) × 采样间隔；无黑帧 → 0.0（E2E B）。
QUIET_REGION_STD_THRESHOLD = 8.0   # overlay 静区平均 luma 标准差阈值（§13/§14 静区）
COMPLEXITY_HINT_THRESHOLD = 40.0   # 全局复杂度（平均 luma 标准差）高 → text 伪影 hint

_FFPROBE_TIMEOUT = 60
_FFMPEG_TIMEOUT = 120


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def now_iso() -> str:
    """UTC 时间戳（ISO 8601，秒精度）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(cmd: list, timeout: int = _FFMPEG_TIMEOUT):
    """subprocess 包装：捕获 stdout/stderr，超时与缺失命令优雅降级（不抛崩）。"""
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as exc:
        return -1, b"", f"command not found: {cmd[0]}".encode("utf-8")
    except subprocess.TimeoutExpired as exc:
        return -1, b"", f"timeout after {timeout}s".encode("utf-8")
    except OSError as exc:  # pragma: no cover
        return -1, b"", str(exc).encode("utf-8")


def _canonical(value: Any) -> Any:
    """递归规范化（dict 键排序、tuple→list、整值 float→int），供确定性 hash。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return int(value) if isinstance(value, float) and value.is_integer() else value
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if value is None:
        return None
    return str(value)


def _clamp_score(x: Any, lo: int = 0, hi: int = 10) -> int:
    """证据分数收敛到 0-10 整数。"""
    try:
        v = int(round(float(x)))
    except (TypeError, ValueError):
        v = 0
    return max(lo, min(hi, v))


def _fraction_value(s: Any) -> Optional[float]:
    """解析 ffprobe r_frame_rate 分数串（"30000/1001"→29.97），失败返回 None。"""
    if s is None:
        return None
    text = str(s).strip()
    if "/" in text:
        a, _, b = text.partition("/")
        try:
            num, den = float(a), float(b)
            return num / den if den else None
        except (TypeError, ValueError):
            return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _dim_has_evidence(d) -> bool:
    """维度是否带有效 evidence（source 非 UNKNOWN）。"""
    if not isinstance(d, dict):
        return False
    evs = d.get("evidence") or []
    return any(isinstance(e, dict) and str(e.get("source") or "") not in ("", "UNKNOWN")
               for e in evs)


def _dim_score(dimensions, name: str) -> Optional[int]:
    d = dimensions.get(name) if isinstance(dimensions, dict) else None
    if isinstance(d, dict):
        return d.get("score")
    return None


def _artifact_detected(a) -> bool:
    return bool(isinstance(a, dict) and a.get("detected"))


def _artifact_note(a) -> str:
    if not isinstance(a, dict):
        return ""
    evs = a.get("evidence") or []
    for e in evs:
        if isinstance(e, dict) and e.get("note"):
            return str(e["note"])
    return ""


# ---------------------------------------------------------------------------
# 最小 ffprobe 桥（§69/§100；P6-04 adapters/external-visual/probe.py 落盘后可去重）
# ---------------------------------------------------------------------------

def _probe_video(video_path) -> dict:
    """ffprobe 探针：duration/resolution/fps/codec/bitrate/音频流/旋转。

    失败返回 {"error": ...}（不抛崩）。fps 用 r_frame_rate 分数化简；
    旋转读 side_data rotation。
    """
    path = str(video_path)
    if not os.path.isfile(path):
        return {"error": f"missing file {path}"}
    rc, out, err = _run(["ffprobe", "-v", "error", "-print_format", "json",
                         "-show_format", "-show_streams", path], timeout=_FFPROBE_TIMEOUT)
    if rc != 0:
        return {"error": (err.decode("utf-8", errors="replace") or "ffprobe 失败").strip()[:500]}
    try:
        data = json.loads(out.decode("utf-8"))
    except ValueError as exc:
        return {"error": f"ffprobe json 解析失败: {exc}"}
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    vs = next((s for s in streams if s.get("codec_type") == "video"), None)
    probe: dict = {}
    if vs is None:
        return {"error": "未找到视频流"}
    duration = None
    try:
        duration = float(fmt.get("duration") or vs.get("duration") or 0) or None
    except (TypeError, ValueError):
        duration = None
    probe["duration"] = duration
    probe["resolution"] = {"w": int(vs.get("width") or 0), "h": int(vs.get("height") or 0)}
    probe["fps"] = _fraction_value(vs.get("r_frame_rate"))
    probe["codec"] = vs.get("codec_name")
    probe["bitrate"] = int(vs.get("bit_rate") or fmt.get("bit_rate") or 0) or None
    probe["audio_streams"] = sum(1 for s in streams if s.get("codec_type") == "audio")
    probe["aspect_ratio"] = vs.get("display_aspect_ratio") or vs.get("sample_aspect_ratio")
    rot = None
    for sd in vs.get("side_data_list") or []:
        if sd.get("rotation") not in (None, 0):
            rot = sd.get("rotation")
    probe["rotation"] = rot
    probe["color_space"] = vs.get("color_space")
    probe["transfer"] = vs.get("color_transfer")
    probe["gamma"] = vs.get("color_primaries")
    return probe


# ---------------------------------------------------------------------------
# 帧采样与信号统计（§100 machine_checks 的底层；纯 Python，无 numpy）
# ---------------------------------------------------------------------------

def _sample_frames(video_path, probe: Optional[dict] = None):
    """等间隔抽帧为 320x180 灰度 rawvideo，返回 (frames, sample_rate, error)。

    frames: bytes 列表（每帧 SAMPLE_WIDTH*SAMPLE_HEIGHT 字节）。
    失败返回 (None, None, errstr)。
    """
    if probe is None:
        probe = _probe_video(video_path)
    if probe.get("error"):
        return None, None, str(probe["error"])
    duration = probe.get("duration") or 0
    if duration and duration > 0:
        sample_rate = min(SAMPLE_MAX_FPS, SAMPLE_TARGET / float(duration))
    else:
        sample_rate = SAMPLE_MAX_FPS
    vf = (f"fps={sample_rate:.6f},scale={SAMPLE_WIDTH}:{SAMPLE_HEIGHT},"
          f"format=gray")
    rc, out, err = _run(["ffmpeg", "-v", "error", "-i", str(video_path), "-vf", vf,
                         "-frames:v", str(SAMPLE_MAX_FRAMES), "-f", "rawvideo", "-"])
    if rc != 0 or not out:
        return None, None, (err.decode("utf-8", errors="replace") or "ffmpeg 抽帧失败").strip()[:300]
    n = SAMPLE_WIDTH * SAMPLE_HEIGHT
    frames = [out[i:i + n] for i in range(0, len(out) - n + 1, n)]
    if not frames:
        return None, None, "ffmpeg 未抽到帧"
    return frames, sample_rate, None


def _frame_luma(frames):
    """每帧平均亮度（0-255）。"""
    n = SAMPLE_WIDTH * SAMPLE_HEIGHT
    return [sum(fr) / n for fr in frames]


def _frame_std(frames):
    """每帧亮度标准差（复杂度，0-255）。"""
    n = SAMPLE_WIDTH * SAMPLE_HEIGHT
    out = []
    for fr in frames:
        m = sum(fr) / n
        out.append(math.sqrt(sum((p - m) ** 2 for p in fr) / n))
    return out


def _consec_diffs(frames):
    """相邻采样帧的平均绝对像素差序列（0-255）。"""
    n = SAMPLE_WIDTH * SAMPLE_HEIGHT
    diffs = []
    for i in range(1, len(frames)):
        diffs.append(sum(abs(a - b) for a, b in zip(frames[i - 1], frames[i])) / n)
    return diffs


def _region_std(frames, x_frac: float = 0.65, width_frac: float = 0.35):
    """overlay 静区（默认右侧 35%）逐帧 luma 标准差，返回均值。"""
    x0 = int(SAMPLE_WIDTH * x_frac)
    w = max(1, int(SAMPLE_WIDTH * width_frac))
    h = SAMPLE_HEIGHT
    n = w * h
    vals = []
    for fr in frames:
        pix = [fr[y * SAMPLE_WIDTH + x] for y in range(h) for x in range(x0, x0 + w)]
        m = sum(pix) / n
        vals.append(math.sqrt(sum((p - m) ** 2 for p in pix) / n))
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------------------
# §100 machine_checks —— ffmpeg 实测项（flicker / freeze / 黑帧 / temporal / 静区）
# ---------------------------------------------------------------------------

def machine_checks(video_path, probe: Optional[dict] = None) -> dict:
    """技术/信号级机器检测（§100），全部确定性阈值。

    返回 {probe, sampled_frames, sample_interval_s, flicker{detected,score,metric},
    freeze{...}, black_frames{...}, temporal_coherence{score,metric},
    composition{overlay_quiet,score,metric}, text_artifacts_hint{hint,note}, warnings}。
    探针/抽帧失败时各项带 error 而不抛崩。

    帧数与间隔数换算（E2E B 修复，R5）：freeze 的 best_run 记录"连续相同帧间隔数"
    （相邻抽帧差值条数），black 的 black_best 记录"连续黑帧数"（帧数）；时长换算：
      freeze_dur = best_run × interval（2 帧相同 = 1 个间隔）
      black_dur  = max(0, black_best - 1) × interval（N 帧黑段 = N-1 个间隔）
    无对应 run（best_run==0 / black_best==0）→ duration 0.0，杜绝"采样间隔 ≥ 阈值
    时无黑帧/无冻结仍误报 detected=true"的假阳性（≥12s 干净视频此前必 REGENERATE）。
    """
    probe = probe or _probe_video(video_path)
    if probe.get("error"):
        err = str(probe["error"])
        return {
            "probe": probe, "error": err,
            "sampled_frames": 0, "sample_interval_s": None,
            "flicker": {"detected": False, "score": 10,
                        "metric": {}, "evidence": [{"source": "machine", "note": f"探针失败: {err}"}]},
            "freeze": {"detected": False, "score": 10,
                       "metric": {}, "evidence": [{"source": "machine", "note": f"探针失败: {err}"}]},
            "black_frames": {"detected": False, "score": 10,
                             "metric": {}, "evidence": [{"source": "machine", "note": f"探针失败: {err}"}]},
            "temporal_coherence": {"score": 5, "metric": {},
                                   "evidence": [{"source": "machine", "note": f"探针失败: {err}"}]},
            "composition": {"overlay_quiet": False, "score": 5, "metric": {},
                            "evidence": [{"source": "machine", "note": f"探针失败: {err}"}]},
            "text_artifacts_hint": {"hint": False, "note": f"探针失败: {err}"},
            "warnings": [err],
        }
    frames, sample_rate, err = _sample_frames(video_path, probe)
    if frames is None:
        return {
            "probe": probe, "error": err,
            "sampled_frames": 0, "sample_interval_s": None,
            "flicker": {"detected": False, "score": 10, "metric": {},
                        "evidence": [{"source": "machine", "note": f"抽帧失败: {err}"}]},
            "freeze": {"detected": False, "score": 10, "metric": {},
                       "evidence": [{"source": "machine", "note": f"抽帧失败: {err}"}]},
            "black_frames": {"detected": False, "score": 10, "metric": {},
                             "evidence": [{"source": "machine", "note": f"抽帧失败: {err}"}]},
            "temporal_coherence": {"score": 5, "metric": {},
                                   "evidence": [{"source": "machine", "note": f"抽帧失败: {err}"}]},
            "composition": {"overlay_quiet": False, "score": 5, "metric": {},
                            "evidence": [{"source": "machine", "note": f"抽帧失败: {err}"}]},
            "text_artifacts_hint": {"hint": False, "note": str(err)},
            "warnings": [str(err)],
        }

    interval = 1.0 / sample_rate if sample_rate > 0 else 0.0
    luma = _frame_luma(frames)
    diffs = _consec_diffs(frames)
    comp_std = _frame_std(frames)

    # —— flicker：帧亮度均值序列信号统计（§37/§100）——
    n = len(luma)
    flick_detected, amp, osc = False, 0.0, 0.0
    if n >= 8:
        ld = [luma[i + 1] - luma[i] for i in range(n - 1)]
        nz = [d for d in ld if abs(d) > 1e-9]
        changes = sum(1 for i in range(len(nz) - 1) if nz[i] * nz[i + 1] < 0)
        osc = changes / max(1, len(nz) - 1) if len(nz) > 1 else 0.0
        amp = max(luma) - min(luma)
        # 要求：峰谷差 ≥ 阈值 且 非零差样本 ≥4 且 符号翻转 ≥3 且 翻转比例 ≥ 阈值
        # （稀疏信号如"黑帧段"只有 1-2 个非零差，不满足 nz≥4，不会误报 flicker）
        flick_detected = (len(nz) >= 4 and changes >= 3
                          and osc >= FLICKER_OSC_RATIO and amp >= FLICKER_AMP_THRESHOLD)
    flick_score = max(0, 10 - int(round(amp / 8.0))) if flick_detected else 10

    # —— freeze：连续"相同"采样帧时长（§100）——
    # 帧数↔间隔数：best_run 为连续相同帧的间隔数（diffs 条数），
    # 时长 = best_run × interval；run==0（无连续相同帧）→ 0.0，不误报（E2E B）。
    best_run, cur = 0, 0
    for d in diffs:
        if d < FREEZE_DIFF_THRESHOLD:
            cur += 1
            best_run = max(best_run, cur)
        else:
            cur = 0
    freeze_dur = (best_run * interval) if best_run > 0 else 0.0
    freeze_detected = freeze_dur >= FREEZE_MIN_DURATION_S

    # —— 黑帧：连续低亮度采样帧时长（§100）——
    # 帧数↔间隔数：black_best 为连续黑帧数（帧数），时长 = max(0, 帧数-1) × interval；
    # 无黑帧（black_best==0）→ 0.0，不误报（E2E B）。
    black_run, black_best, black_count = 0, 0, 0
    for v in luma:
        if v < BLACK_LUMA_THRESHOLD:
            black_run += 1
            black_count += 1
            black_best = max(black_best, black_run)
        else:
            black_run = 0
    black_dur = (max(0, black_best - 1) * interval) if black_best > 0 else 0.0
    black_detected = black_dur >= BLACK_MIN_RUN_S

    # —— temporal_coherence：相邻抽帧差值方差（§36 机器弱证据）——
    mean_diff = sum(diffs) / len(diffs) if diffs else 0.0
    std_diff = (math.sqrt(sum((d - mean_diff) ** 2 for d in diffs) / len(diffs))
                if diffs else 0.0)
    temporal_score = max(0, 10 - int(round(mean_diff / 20.0)) - int(round(std_diff / 30.0)))
    if freeze_detected:
        temporal_score = min(temporal_score, 3)
    if black_detected:
        temporal_score = min(temporal_score, 4)

    # —— composition：overlay 静区亮度复杂度（§13/§14，仅弱证据）——
    region_std_mean = _region_std(frames)
    quiet = region_std_mean < QUIET_REGION_STD_THRESHOLD
    comp_score = min(10, max(0, 10 - int(round(region_std_mean / 4.0))))

    # —— text_artifacts_hint：全局复杂度启发式（仅 hint，不作检出）——
    cmplx_mean = sum(comp_std) / len(comp_std) if comp_std else 0.0
    text_hint = cmplx_mean >= COMPLEXITY_HINT_THRESHOLD

    warnings = []
    if text_hint:
        warnings.append("高对比细节区域存在（复杂度高），可能是文字/logo 区域，"
                        "需 human/vision_model evidence 确认（引擎不假装会看）")

    return {
        "probe": probe,
        "sampled_frames": len(frames),
        "sample_interval_s": round(interval, 4),
        "flicker": {
            "detected": flick_detected, "score": flick_score,
            "metric": {"amplitude": round(amp, 2), "oscillation_ratio": round(osc, 3),
                       "luma_min": round(min(luma), 1), "luma_max": round(max(luma), 1)},
            "evidence": [{"source": "machine",
                          "note": "ffmpeg 抽帧亮度序列统计（帧平均亮度峰谷差与高频振荡）"}],
        },
        "freeze": {
            "detected": freeze_detected, "score": 0 if freeze_detected else 10,
            "metric": {"max_identical_run_frames": best_run + 1,
                       "run_duration_s": round(freeze_dur, 3)},
            "evidence": [{"source": "machine",
                          "note": "ffmpeg 抽帧比对：连续相同帧时长 ≥ 阈值判定 freeze（§100）"}],
        },
        "black_frames": {
            "detected": black_detected, "score": 0 if black_detected else 10,
            "metric": {"black_frame_count": black_count,
                       "max_black_run_s": round(black_dur, 3)},
            "evidence": [{"source": "machine",
                          "note": "ffmpeg 抽帧亮度统计：连续低亮度帧时长 ≥ 阈值判定黑帧（§100）"}],
        },
        "temporal_coherence": {
            "score": temporal_score,
            "metric": {"mean_diff": round(mean_diff, 3), "std_diff": round(std_diff, 3)},
            "evidence": [{"source": "machine",
                          "note": "相邻抽帧平均绝对像素差方差（机器弱证据）"}],
        },
        "composition": {
            "overlay_quiet": quiet, "score": comp_score,
            "metric": {"region_std_mean": round(region_std_mean, 3),
                       "region": "right 35%"},
            "evidence": [{"source": "machine",
                          "note": "overlay 静区亮度/复杂度检测（超阈值静区可加分，仅弱证据，§13/§14）"}],
        },
        "text_artifacts_hint": {"hint": text_hint,
                                "note": "复杂度启发式（不作检出）；文字伪影需 evidence"},
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# evidence 归一化与维度/伪影装配（§36/§37）
# ---------------------------------------------------------------------------

def _normalize_evidence(evidence):
    """evidence 输入归一化：接受 None / dict（值保留原样，调用方后续按形状分派）。"""
    if evidence is None:
        return {}
    if not isinstance(evidence, dict):
        return {}
    return {str(k): v for k, v in evidence.items()}


def _machine_dim_score(name: str, machine):
    """机器弱证据 → 维度分数；不可机器测 / 探针失败时返回 None（不伪造判定）。"""
    if not isinstance(machine, dict):
        return None
    if machine.get("error"):
        return None  # 探针/抽帧失败时机器没有可信读数，不给任何机器 evidence
    if name in ("flicker", "temporal_coherence", "composition"):
        key = {"flicker": "flicker", "temporal_coherence": "temporal_coherence",
               "composition": "composition"}[name]
        m = machine.get(key)
        if isinstance(m, dict) and "score" in m:
            note = "ffmpeg 实测（机器弱证据）"
            return m["score"], note
    if name == "motion_quality":
        fr = machine.get("freeze")
        if isinstance(fr, dict) and fr.get("detected"):
            return 3, "ffmpeg 实测 freeze 检出（§100）"
    if name == "lighting":
        bf = machine.get("black_frames")
        if isinstance(bf, dict) and bf.get("detected"):
            return 3, "ffmpeg 实测连续黑帧检出（§100）"
    if name == "usability_for_overlays":
        comp = machine.get("composition")
        if isinstance(comp, dict) and comp.get("overlay_quiet"):
            return max(5, int(comp.get("score") or 5)), "ffmpeg 静区检测：overlay 区域静（弱证据）"
    return None


def _assemble_dimensions(evidence, machine) -> dict:
    """18 维度装配：调用方 evidence 优先；机器弱证据次之；都没有 → NEEDS_EVIDENCE。

    NEEDS_EVIDENCE 维度 score 按 0 处理（§38：verdict 不得 PASS）。
    """
    dims: dict = {}
    for name, _w in DIMENSIONS:
        ev = evidence.get(name)
        if isinstance(ev, dict) and "score" in ev:
            src = str(ev.get("source") or "UNKNOWN")
            if src in EVIDENCE_SOURCES and src != "UNKNOWN":
                score = _clamp_score(ev["score"])
                note = str(ev["note"]) if ev.get("note") else None
                dims[name] = {"score": score,
                              "evidence": [{"source": src, "note": note}]}
                continue
        mscore = _machine_dim_score(name, machine)
        if mscore is not None:
            dims[name] = {"score": mscore[0],
                          "evidence": [{"source": "machine", "note": mscore[1]}]}
            continue
        dims[name] = {"score": 0,
                      "evidence": [{"source": "UNKNOWN",
                                    "note": "无 evidence，维度记 NEEDS_EVIDENCE"
                                            "（score 按 0，verdict 不得 PASS）"}]}
    return dims


def _assemble_artifacts(evidence, machine) -> dict:
    """13 伪影装配：flicker 用机器检测；其余 12 项只能由 evidence 声明。

    evidence 声明（human/vision_model 标记如 "hand_deformation@00:02.1"）→ detected；
    无 evidence → detected=false + source UNKNOWN（不声明，也不假装阴性）。
    """
    arts: dict = {}
    for name in ARTIFACT_NAMES:
        ev = evidence.get(name)
        detected = False
        note = None
        src = "UNKNOWN"
        if isinstance(ev, dict) and "detected" in ev:
            detected = bool(ev.get("detected"))
            src = str(ev.get("source") or "UNKNOWN")
            if src not in EVIDENCE_SOURCES:
                src = "UNKNOWN"
            note = ev.get("note")
        if name == "flicker":
            m = machine.get("flicker") if isinstance(machine, dict) else None
            if isinstance(m, dict) and m.get("detected"):
                detected = True
                src = "machine"
                note = note or "ffmpeg 亮度序列检测（机器实测）"
        if src == "UNKNOWN":
            note = note or "无 evidence，未声明检出（不伪造阴性）"
        arts[name] = {"detected": detected,
                      "evidence": [{"source": src, "note": note}]}
    return arts


# ---------------------------------------------------------------------------
# §38 aggregate —— 确定性加权打分 + 硬失败规则
# ---------------------------------------------------------------------------

def _collect_issues(dimensions, artifacts, machine, evidence_missing, hard_detected,
                    machine_fatal, low) -> list:
    issues: list = []
    for h in hard_detected:
        note = _artifact_note(artifacts.get(h))
        issues.append({"type": "hard_artifact", "name": h, "note": note})
    for k in machine_fatal:
        issues.append({"type": "machine", "name": k, "note": f"ffmpeg 实测 {k} 检出"})
    for n in evidence_missing:
        issues.append({"type": "needs_evidence", "name": n,
                       "note": "无 evidence，需补 human/vision_model 证据"})
    for n in low:
        issues.append({"type": "low_score", "name": n,
                       "score": _dim_score(dimensions, n)})
    return issues


def _build_summary(score, verdict, evidence_missing, hard_detected, machine_fatal,
                   issues) -> str:
    n_ev = len(DIMENSIONS) - len(evidence_missing)
    parts = [f"score={score}/100 verdict={verdict}",
             f"18 维度 {n_ev}/18 有 evidence"]
    if evidence_missing:
        parts.append(f"{len(evidence_missing)} 维 NEEDS_EVIDENCE（score 按 0）")
    if hard_detected:
        parts.append("hard 伪影: " + ",".join(hard_detected))
    if machine_fatal:
        parts.append("机器 fatal: " + ",".join(machine_fatal))
    if issues:
        parts.append(f"issues {len(issues)} 项已登记")
    return "；".join(parts)


def aggregate(dimensions, artifacts, machine=None) -> dict:
    """§38 确定性聚合：0-100 加权分 + verdict 判定。

    verdict 规则（优先级从高到低）：
      1) prompt_adherence<2（内容与请求根本不符）→ REJECT
      2) 机器检出 flicker/freeze/黑帧 或 prompt_adherence<5 → REGENERATE
      3) 任意 hard 伪影 → 最高 PASS_WITH_ISSUES（§37 不得 PASS/APPROVED）
      4) score≥80 且全部维度有证据且无 issues → PASS
      5) score 60-79 或 minor 问题 → PASS_WITH_ISSUES
      6) 其余 → REGENERATE
    """
    if not isinstance(dimensions, dict):
        dimensions = {}
    if not isinstance(artifacts, dict):
        artifacts = {}
    weighted = 0.0
    for name, w in DIMENSIONS:
        d = dimensions.get(name)
        weighted += (d.get("score", 0) if isinstance(d, dict) else 0) * w
    score = int(round(10.0 * weighted / TOTAL_WEIGHT))

    evidence_missing = [n for n, _ in DIMENSIONS if not _dim_has_evidence(dimensions.get(n))]
    hard_detected = [h for h in HARD_ARTIFACTS if _artifact_detected(artifacts.get(h))]
    machine_fatal: list = []
    if isinstance(machine, dict) and not machine.get("error"):
        for k in ("flicker", "freeze", "black_frames"):
            m = machine.get(k)
            if isinstance(m, dict) and m.get("detected"):
                machine_fatal.append(k)
    pa = _dim_score(dimensions, "prompt_adherence")
    pa_evidenced = _dim_has_evidence(dimensions.get("prompt_adherence"))
    low = [n for n, _ in DIMENSIONS
           if _dim_has_evidence(dimensions.get(n)) and (_dim_score(dimensions, n) < 6)]
    issues = _collect_issues(dimensions, artifacts, machine, evidence_missing,
                             hard_detected, machine_fatal, low)

    # 注意：prompt_adherence 的 REJECT/REGENERATE 规则只在"该维度有 evidence"时生效；
    # NEEDS_EVIDENCE（score 按 0）不代表"内容与请求根本不符"，不应据此 REJECT。
    if pa is not None and pa_evidenced and pa < 2:
        verdict = "REJECT"
    elif machine_fatal or (pa is not None and pa_evidenced and pa < 5):
        verdict = "REGENERATE"
    else:
        if score >= 80 and not evidence_missing and not issues:
            verdict = "PASS"
        elif score >= 60:
            verdict = "PASS_WITH_ISSUES"
        else:
            verdict = "REGENERATE"
        if hard_detected and verdict == "PASS":
            verdict = "PASS_WITH_ISSUES"   # hard 伪影最高 PASS_WITH_ISSUES（§37）

    summary = _build_summary(score, verdict, evidence_missing, hard_detected,
                             machine_fatal, issues)
    return {"score": score, "verdict": verdict, "summary": summary,
            "issues": issues, "evidence_missing": evidence_missing,
            "hard_detected": hard_detected, "machine_fatal": machine_fatal}


# ---------------------------------------------------------------------------
# §35 review_candidate —— 完整评审
# ---------------------------------------------------------------------------

def _make_review_id(packet, video_path) -> str:
    """确定性 review_id（RV-###）：由请求引用 + 文件基线名 hash 导出。

    相同输入 → 相同 ID（幂等重评审）；管线侧可用 review_id 覆盖。
    """
    seed = _canonical({
        "req": packet.get("request_id") or packet.get("packet_id") or packet.get("shot_id"),
        "asset": packet.get("asset_id"),
        "file": os.path.basename(str(video_path)),
    })
    h = hashlib.sha256(json.dumps(seed, ensure_ascii=False).encode("utf-8")).hexdigest()
    return f"RV-{int(h[:6], 16) % 1000:03d}"


def review_candidate(video_path, packet_or_request=None, evidence=None,
                     visual_bible=None, adjacent_shots=None, *,
                     review_id: Optional[str] = None) -> dict:
    """§35 候选评审：生成完整 RV dict（对齐 video-review.schema.json 字段表）。

    - packet_or_request：GV Production Packet 或 EV/FR 请求（含 shot_id / duration /
      purpose / overlay 要求 / camera 等）；缺省视为未知请求。
    - evidence：调用方（human / vision_model / packet_diff）提供的维度分与伪影声明。
    - visual_bible / adjacent_shots：供 visual_bible_fit / editorial 对照（可选）。
    - 视觉维度判定一律基于 evidence；缺失记 NEEDS_EVIDENCE，不伪造机器判定。
    """
    packet = packet_or_request if isinstance(packet_or_request, dict) else {}
    evidence = _normalize_evidence(evidence)
    probe = _probe_video(video_path)
    machine = machine_checks(video_path, probe=probe)

    dims = _assemble_dimensions(evidence, machine)
    arts = _assemble_artifacts(evidence, machine)
    agg = aggregate(dims, arts, machine=machine)

    review: dict = {
        "review_id": review_id if (review_id and REVIEW_ID_RE.match(str(review_id)))
        else _make_review_id(packet, video_path),
        "asset_ref": packet.get("asset_id") or evidence.get("asset_ref")
        or str(packet.get("shot_id") or "unknown"),
        "request_ref": packet.get("request_id") or packet.get("packet_id")
        or evidence.get("request_ref"),
        "variant_id": packet.get("variant_id") or evidence.get("variant_id"),
        "verdict": agg["verdict"],
        "score": agg["score"],
        "dimensions": dims,
        "artifacts": arts,
        "machine_checks": machine,
        "issues": agg["issues"],
        "summary": agg["summary"],
        "reviewed_at": now_iso(),
    }
    if evidence.get("failure_attempt") is not None:
        review["failure_attempt"] = int(evidence["failure_attempt"])
    for _key in ("prompt_overload", "overload"):
        marker = evidence.get(_key)
        if marker is True or (isinstance(marker, dict) and marker.get("detected")):
            review["overload_hint"] = True

    ed = editorial_usability(packet, probe, evidence, adjacent_shots, machine)
    if ed:
        review["editorial_usability"] = ed

    if agg["verdict"] in ("REGENERATE", "REJECT"):
        diag = diagnose_regeneration(review, packet)
        review["regeneration_diagnosis"] = diag["diagnosis"]
        review["revision_suggestions"] = diag["revision_suggestions"]
    return review


# ---------------------------------------------------------------------------
# §39-40 / §117 diagnose_regeneration —— 针对性重生成诊断
# ---------------------------------------------------------------------------

_DIAG_DIM_MAP = {
    "prompt_adherence": "composition", "composition": "composition",
    "visual_bible_fit": "composition", "lighting": "composition",
    "usability_for_overlays": "composition", "editability": "composition",
    "overall_production_value": "composition",
    "motion_quality": "motion", "temporal_coherence": "motion", "flicker": "motion",
    "camera_quality": "camera",
    "subject_consistency": "identity", "anatomy": "identity", "continuity": "identity",
    "physics": "physics", "warping": "physics",
    "text_artifacts": "prompt_overload", "unwanted_logos": "prompt_overload",
}

_REVISION_SUGGESTIONS = {
    "composition": [
        "调整 packet.composition.subject_placement 与 negative_space，重新分布前景/背景密度",
        "明确 safe zone 与 intended_overlay_area，降低前景元素拥挤度",
    ],
    "motion": [
        "简化 subject_action：去掉多段动作叠加，保留单一核心动作",
        "降低 environment_motion / 人群 / 布料等有机运动复杂度",
    ],
    "identity": [
        "强化 packet.continuity.subject_identity（外貌/服装/年龄/颜色）",
        "追加 character_reference 参考帧（§24 reference_inputs.character_reference）",
    ],
    "camera": [
        "收敛 camera_movement 为单一运镜（如 PUSH_IN）而非 COMPLEX 组合",
        "固定 movement_speed 与 stabilization 风格，降低手持抖动强度",
    ],
    "physics": [
        "移除 impossible_geometry / 不可能交互的描述，对齐物理合理性",
        "物理苛刻元素改走 3D 或真实素材（use_3D / use_footage）",
    ],
    "prompt_overload": [
        "§40 简化：删减非核心需求，保留主 Subject + Purpose（不追加词）",
        "split shot：拆成多个镜头（§41，属 Storyboard 修改，需 PRODUCTION_CONFLICT 批准）",
    ],
    "unknown": [
        "先补充 human/vision_model evidence 再诊断；当前无任何维度证据",
    ],
}


def diagnose_regeneration(review, packet=None, attempt=None) -> dict:
    """§39-40/§117：失败分类 + 针对性修改建议 + attempt 阶梯。

    诊断（确定性优先级）：显式 overload 标记 / ≥4 维低分 → prompt_overload；
    identity_drift / impossible_geometry / camera_jump 伪影覆盖；否则取
    "有 evidence 的最低分维度" 映射失败类。attempt>3 → BLOCKED + 建议清单
    （split_shot/use_3D/use_footage/use_hybrid，全部 approval_required）。
    """
    if not isinstance(review, dict):
        raise ValueError("diagnose_regeneration 需要 review dict")
    packet = packet if isinstance(packet, dict) else {}
    attempt = int(attempt if attempt is not None else (review.get("failure_attempt") or 1))
    dims = review.get("dimensions") or {}
    artifacts = review.get("artifacts") or {}

    low_evidenced = [n for n, _ in DIMENSIONS
                     if _dim_has_evidence(dims.get(n)) and (_dim_score(dims, n) < 6)]
    overload = bool(review.get("overload_hint") or review.get("prompt_overload")) \
        or len(low_evidenced) >= 4

    if _artifact_detected(artifacts.get("identity_drift")):
        diag = "identity"
    elif _artifact_detected(artifacts.get("impossible_geometry")):
        diag = "physics"
    elif _artifact_detected(artifacts.get("camera_jump")):
        diag = "camera"
    elif overload:
        diag = "prompt_overload"
    else:
        cand = [(n, _dim_score(dims, n)) for n, _ in DIMENSIONS
                if _dim_has_evidence(dims.get(n))]
        if not cand:
            diag = "unknown"
        else:
            cand.sort(key=lambda x: (x[1], DIMENSION_NAMES.index(x[0])))
            diag = _DIAG_DIM_MAP.get(cand[0][0], "composition")

    blocked = attempt > 3
    next_step = "BLOCKED" if blocked else NEXT_STEP_BY_ATTEMPT.get(attempt, "BLOCKED")
    rationale = (f"最低分维度（有 evidence）→ {diag} 类失败；attempt={attempt} "
                 f"→ next_step={next_step}")
    out = {
        "diagnosis": diag,
        "rationale": rationale,
        "revision_suggestions": list(_REVISION_SUGGESTIONS.get(diag, [])),
        "attempt": attempt,
        "next_step": next_step,
        "blocked": blocked,
        "approval_required": blocked,
    }
    if blocked:
        out["recommended_alternatives"] = list(BLOCKED_ALTERNATIVES)
    return out


# ---------------------------------------------------------------------------
# §102 editorial_usability —— 五项清单
# ---------------------------------------------------------------------------

def _direction_of(text: Any):
    """从文本提取画面方向（L2R / R2L），确定性启发式；无信息返回 None。"""
    if text is None:
        return None
    t = str(text).upper()
    out = []
    for tok in ("LEFT→RIGHT", "RIGHT→LEFT", "L2R", "R2L", "L→R", "R→L"):
        if tok in t:
            out.append({"L2R": "L2R" in tok or tok in ("LEFT→RIGHT", "L→R", "L2R"),
                        "R2L": "R2L" in tok or tok in ("RIGHT→LEFT", "R→L", "R2L"),
                        "raw": tok})
    if out:
        d = out[0]
        return "L2R" if d["L2R"] else ("R2L" if d["R2L"] else None)
    if "LEFT" in t and "RIGHT" in t:
        left_first = t.find("LEFT") < t.find("RIGHT")
        return "L2R" if left_first else "R2L"
    return None


def _ev_check(ev) -> dict:
    """evidence 型检查项输出（{status, note, evidence}）。"""
    ok = bool(ev.get("ok"))
    src = str(ev.get("source") or "human")
    return {
        "status": "ok" if ok else "fail",
        "note": str(ev.get("note") or ("通过" if ok else "未通过")),
        "evidence": [{"source": src, "note": ev.get("note")}],
    }


def editorial_usability(packet, probe=None, evidence=None, adjacent_shots=None,
                        machine=None) -> dict:
    """§102 五项 editorial usability 清单（输出 checklist dict）。

    机器可算项（usable_duration_match / overlay_space_sufficient 静区）用 ffmpeg
    实测；需视觉判断项（serves_narration / clean_entry_exit / adjacent_camera_direction）
    只基于 evidence / adjacent_data，缺省记 NEEDS_EVIDENCE。
    """
    packet = packet if isinstance(packet, dict) else {}
    evidence = evidence if isinstance(evidence, dict) else {}
    machine = machine if isinstance(machine, dict) else {}
    check: dict = {}

    # 1) serves_narration（与 shot purpose 对照）
    purpose = packet.get("purpose") or packet.get("narrative_purpose")
    ev = evidence.get("serves_narration")
    if isinstance(ev, dict):
        check["serves_narration"] = _ev_check(ev)
    elif purpose:
        check["serves_narration"] = {
            "status": "NEEDS_EVIDENCE",
            "note": f"需视觉判断：shot purpose『{purpose}』是否被画面服务",
            "evidence": [{"source": "UNKNOWN", "note": "无 evidence"}]}
    else:
        check["serves_narration"] = {
            "status": "not_applicable", "note": "无 purpose 要求可对照",
            "evidence": [{"source": "packet_diff", "note": "packet 无 purpose"}]}

    # 2) usable_duration_match（机器可算）
    req = packet.get("duration")
    actual = (probe or {}).get("duration")
    if isinstance(req, (int, float)) and req > 0 and isinstance(actual, (int, float)) and actual > 0:
        tol = req * 0.10
        ok = abs(actual - req) <= tol
        check["usable_duration_match"] = {
            "status": "ok" if ok else "fail",
            "note": f"实际 {actual:.2f}s vs 要求 {req:.2f}s（±10%）",
            "evidence": [{"source": "machine", "note": "ffprobe duration 对比"}]}
    elif isinstance(req, (int, float)) and req > 0:
        check["usable_duration_match"] = {
            "status": "NEEDS_EVIDENCE", "note": "有时长要求但无法探测实际时长",
            "evidence": [{"source": "UNKNOWN", "note": "probe 失败"}]}
    else:
        check["usable_duration_match"] = {
            "status": "not_applicable", "note": "无时长要求约束",
            "evidence": [{"source": "packet_diff", "note": "packet 无 duration"}]}

    # 3) clean_entry_exit（in/out 帧状态；只能由 evidence 判定，引擎不假装会看）
    ev = evidence.get("clean_entry_exit")
    if isinstance(ev, dict):
        check["clean_entry_exit"] = _ev_check(ev)
    else:
        check["clean_entry_exit"] = {
            "status": "NEEDS_EVIDENCE",
            "note": "需视觉判断 in/out 帧状态（首/末帧是否干净可剪）",
            "evidence": [{"source": "UNKNOWN", "note": "无 evidence"}]}

    # 4) overlay_space_sufficient（静区检测 + request 要求）
    overlay_req = (packet.get("overlay_requirements") or packet.get("text_safe_area")
                   or packet.get("overlay_safe_area"))
    if overlay_req:
        comp = machine.get("composition") or {}
        if comp.get("overlay_quiet"):
            check["overlay_space_sufficient"] = {
                "status": "ok", "note": "overlay 区域静（机器实测），满足静区要求",
                "evidence": [{"source": "machine", "note": "ffmpeg 静区检测"}]}
        else:
            ev = evidence.get("overlay_space_sufficient")
            if isinstance(ev, dict):
                check["overlay_space_sufficient"] = _ev_check(ev)
            else:
                check["overlay_space_sufficient"] = {
                    "status": "NEEDS_EVIDENCE",
                    "note": "overlay 区域非静且无 evidence，需视觉判断空间是否足够",
                    "evidence": [{"source": "UNKNOWN", "note": "无 evidence"}]}
    else:
        check["overlay_space_sufficient"] = {
            "status": "not_applicable", "note": "无 overlay 要求",
            "evidence": [{"source": "packet_diff", "note": "packet 无 overlay 要求"}]}

    # 5) adjacent_camera_direction（与 adjacent_shots 对照）
    ev = evidence.get("adjacent_camera_direction")
    if isinstance(ev, dict):
        check["adjacent_camera_direction"] = _ev_check(ev)
    else:
        this_dir = _direction_of(packet.get("camera")) or _direction_of(
            (packet.get("continuity") or {}).get("screen_direction")
            if isinstance(packet.get("continuity"), dict) else packet.get("continuity"))
        prev = None
        if isinstance(adjacent_shots, list) and adjacent_shots:
            prev = adjacent_shots[-1]
        prev_dir = None
        if isinstance(prev, dict):
            prev_dir = _direction_of(prev.get("camera")) or _direction_of(
                prev.get("motion") or prev.get("visual_description"))
        elif isinstance(prev, str):
            prev_dir = _direction_of(prev)
        if this_dir and prev_dir and this_dir != prev_dir:
            check["adjacent_camera_direction"] = {
                "status": "fail",
                "note": f"与相邻 shot 画面方向冲突（本 {this_dir} vs 相邻 {prev_dir}），"
                        "除非导演设计如此",
                "evidence": [{"source": "adjacent_data", "note": "adjacent_shots 对照"}]}
        elif adjacent_shots:
            check["adjacent_camera_direction"] = {
                "status": "ok", "note": "与相邻 shot 无方向冲突",
                "evidence": [{"source": "adjacent_data", "note": "adjacent_shots 对照"}]}
        else:
            check["adjacent_camera_direction"] = {
                "status": "NEEDS_EVIDENCE", "note": "无 adjacent_shots 数据，需补充",
                "evidence": [{"source": "UNKNOWN", "note": "无 adjacent_data"}]}
    return check


# ---------------------------------------------------------------------------
# §92-93 review_variants —— 多候选 rank / select / reject
# ---------------------------------------------------------------------------

def _variant_weighted_sum(v: dict) -> float:
    """维度权重和（tie-break 用）。"""
    dims = v.get("dimensions") if isinstance(v, dict) else None
    if not isinstance(dims, dict):
        return 0.0
    total = 0.0
    for name, w in DIMENSIONS:
        d = dims.get(name)
        total += (d.get("score", 0) if isinstance(d, dict) else 0) * w
    return total


def review_variants(variants: list) -> dict:
    """§92-93 多候选：按（score, 维度权重和）降序 rank，选第一，其余 rejected。

    rejected 条目保 {variant_id, reason, metadata_kept:true}，不保 payload
    （payload 保留决策归 P6-04 storage policy）。
    """
    if not isinstance(variants, list):
        raise ValueError("review_variants 需要 review 列表")
    if not variants:
        return {"ranked": [], "selected": None, "rejected": []}
    items = []
    for v in variants:
        if not isinstance(v, dict):
            raise ValueError("每个候选必须是 dict")
        vid = v.get("variant_id") or v.get("asset_ref") or "?"
        score = v.get("score")
        if not isinstance(score, (int, float)):
            raise ValueError(f"候选 {vid} 缺少 score")
        items.append({"variant_id": str(vid), "score": float(score),
                      "wsum": _variant_weighted_sum(v),
                      "verdict": str(v.get("verdict") or ""), "review": v})
    items.sort(key=lambda it: (-it["score"], -it["wsum"], str(it["variant_id"])))
    top = items[0]
    rejected = []
    for it in items[1:]:
        reason = _reject_reason(it, top)
        rejected.append({"variant_id": it["variant_id"], "reason": reason,
                         "metadata_kept": True})
    return {"ranked": [it["variant_id"] for it in items],
            "selected": top["review"],
            "rejected": rejected}


def _reject_reason(loser: dict, top: dict) -> str:
    """被拒原因（确定性）：verdict 差距 → 分数差距 → 硬伪影 → 默认。"""
    if loser["verdict"] and top["verdict"] and loser["verdict"] != top["verdict"]:
        return (f"verdict {loser['verdict']} 低于选中变体 {top['verdict']} "
                f"（score {loser['score']:.1f} vs {top['score']:.1f}）")
    if loser["score"] < top["score"]:
        return f"score {loser['score']:.1f} 低于选中变体 {top['score']:.1f}"
    hard = [h for h in HARD_ARTIFACTS
            if _artifact_detected((loser["review"].get("artifacts") or {}).get(h))]
    if hard:
        return f"检出 hard 伪影: {','.join(hard)}"
    return f"总分/维度权重分低于选中变体（score {loser['score']:.1f}）"


# ---------------------------------------------------------------------------
# §103-104 advance_acceptance —— 验收状态机
# ---------------------------------------------------------------------------

def _require_review(review) -> None:
    if not isinstance(review, dict):
        raise ValueError("该迁移需要 review 数据（review 缺失）")


def _ready_conditions(review, license_ok: bool, metadata_ok: bool) -> list:
    """§104 READY_FOR_TIMELINE 四前置条件：返回缺失项列表（空 = 全部满足）。"""
    missing: list = []
    if not isinstance(review, dict):
        missing.append("technical_qa(无 review)")
        missing.append("visual_qa(无 review)")
    else:
        m = review.get("machine_checks") or {}
        fatal = [k for k in ("flicker", "freeze", "black_frames")
                 if isinstance(m.get(k), dict) and m[k].get("detected")]
        probe_err = (m.get("probe") or {}).get("error")
        if probe_err or fatal:
            missing.append("technical_qa(" + ("probe 失败" if probe_err
                                              else f"机器问题 {fatal}") + ")")
        verdict = review.get("verdict")
        if verdict not in ("PASS", "PASS_WITH_ISSUES"):
            missing.append(f"visual_qa(verdict={verdict} 未通过)")
        elif verdict == "PASS_WITH_ISSUES" and not review.get("issues"):
            missing.append("visual_qa(PASS_WITH_ISSUES 需 issues 已登记)")
    if not license_ok:
        missing.append("license/provenance(商用许可缺失或未知)")
    if not metadata_ok:
        missing.append("asset metadata 不完整")
    return missing


def advance_acceptance(asset_meta, review, license_ok: bool, metadata_ok: bool,
                       target: Optional[str] = None) -> str:
    """§103-104 验收状态机推进。

    返回新 acceptance_status；非法迁移 / 前置条件不满足抛 ValueError 并说明原因
    （Test 24：READY_FOR_TIMELINE 前置四条件缺一即拒）。

    - target=None：按 review.verdict 自动推进（REJECT→REJECTED；REGENERATE→
      REVISION_REQUIRED；PASS/PASS_WITH_ISSUES→ 沿 _FORWARD 链下一步）。
    - 显式 target：须在状态机允许迁移表内，否则抛非法迁移。
    - 进入 APPROVED 额外要求：verdict ∈ {PASS, PASS_WITH_ISSUES}（后者 issues 已
      登记）且无 hard 伪影（§37 语义：hard 检出不得 APPROVED）。
    """
    if not isinstance(asset_meta, dict):
        raise ValueError("asset_meta 必须是 dict（至少含 acceptance_status）")
    current = str(asset_meta.get("acceptance_status") or "CANDIDATE").upper()
    if current not in ACCEPTANCE_STATES:
        raise ValueError(f"未知 acceptance_status={current!r}；"
                         f"允许 {sorted(ACCEPTANCE_STATES)}")

    if target is None:
        verdict = (review or {}).get("verdict") if isinstance(review, dict) else None
        if verdict == "REJECT":
            target = "REJECTED"
        elif verdict == "REGENERATE":
            target = "REVISION_REQUIRED"
        else:
            nxt = _FORWARD.get(current)
            if nxt is None:
                raise ValueError(f"{current} 无法自动推进（终态或无 verdict 信息），"
                                 "请显式指定 target")
            target = nxt
    target = str(target).upper()
    if target not in ACCEPTANCE_STATES:
        raise ValueError(f"未知 target={target!r}；允许 {sorted(ACCEPTANCE_STATES)}")
    allowed = _TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"非法迁移 {current}→{target}（状态机不允许；"
                         f"允许 {sorted(allowed) or '无（终态）'}）")

    if target == "SELECTED":
        _require_review(review)
        if review.get("verdict") not in ("PASS", "PASS_WITH_ISSUES"):
            raise ValueError("SELECTED 需要 verdict PASS/PASS_WITH_ISSUES"
                             f"（当前 {review.get('verdict')}）")

    if target == "APPROVED":
        _require_review(review)
        verdict = review.get("verdict")
        if verdict not in ("PASS", "PASS_WITH_ISSUES"):
            raise ValueError(f"APPROVED 需要 verdict PASS/PASS_WITH_ISSUES（当前 {verdict}）")
        if verdict == "PASS_WITH_ISSUES" and not review.get("issues"):
            raise ValueError("APPROVED 被拒：PASS_WITH_ISSUES 需 issues 已登记")
        hard = [h for h in HARD_ARTIFACTS
                if _artifact_detected((review.get("artifacts") or {}).get(h))]
        if hard:
            raise ValueError(f"APPROVED 被拒：hard 伪影已检出 {hard}（§37 不得 APPROVED）")

    if target == "READY_FOR_TIMELINE":
        missing = _ready_conditions(review, bool(license_ok), bool(metadata_ok))
        if missing:
            raise ValueError("READY_FOR_TIMELINE 前置条件缺失（§104）："
                             + "; ".join(missing))
    return target


# ---------------------------------------------------------------------------
# CLI（python3 -m modules.external-visual.review <cmd> …）
# ---------------------------------------------------------------------------

def _load_json_or_fail(path: str) -> Any:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"文件不存在: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"JSON 解析失败 {path}: {exc}")


def _cli_main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="review.py",
        description="Candidate Review & QA（P6-05，§35-41/§100-104/§117）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_machine = sub.add_parser("machine", help="ffmpeg 机器实测（flicker/freeze/黑帧/…）")
    p_machine.add_argument("video_path")
    p_machine.add_argument("--json", action="store_true", help="输出原始 JSON")

    p_review = sub.add_parser("review", help="完整候选评审（RV dict）")
    p_review.add_argument("video_path")
    p_review.add_argument("--packet", help="packet/request JSON 文件")
    p_review.add_argument("--evidence", help="evidence JSON 文件")
    p_review.add_argument("--bible", help="visual bible JSON 文件")
    p_review.add_argument("--adjacent", help="adjacent_shots JSON 文件")
    p_review.add_argument("--review-id")

    p_agg = sub.add_parser("aggregate", help="§38 聚合（需 dimensions/artifacts JSON）")
    p_agg.add_argument("--dimensions", required=True)
    p_agg.add_argument("--artifacts", required=True)
    p_agg.add_argument("--machine")

    p_diag = sub.add_parser("diagnose", help="§39-40 重生成诊断")
    p_diag.add_argument("--review", required=True)
    p_diag.add_argument("--packet")
    p_diag.add_argument("--attempt", type=int)

    p_adv = sub.add_parser("advance", help="§103-104 验收状态机推进")
    p_adv.add_argument("--asset", required=True, help="asset_meta JSON（含 acceptance_status）")
    p_adv.add_argument("--review")
    p_adv.add_argument("--license", default="0", choices=("0", "1"))
    p_adv.add_argument("--metadata", default="0", choices=("0", "1"))
    p_adv.add_argument("--target")

    p_var = sub.add_parser("variants", help="§92-93 多候选 rank/select/reject")
    p_var.add_argument("--reviews", nargs="+", required=True, help="review JSON 文件列表")

    args = parser.parse_args(argv)

    if args.cmd == "machine":
        out = machine_checks(args.video_path)
    elif args.cmd == "review":
        packet = _load_json_or_fail(args.packet) if args.packet else None
        evidence = _load_json_or_fail(args.evidence) if args.evidence else None
        bible = _load_json_or_fail(args.bible) if args.bible else None
        adjacent = _load_json_or_fail(args.adjacent) if args.adjacent else None
        out = review_candidate(args.video_path, packet, evidence, bible, adjacent,
                               review_id=args.review_id)
    elif args.cmd == "aggregate":
        machine = _load_json_or_fail(args.machine) if args.machine else None
        out = aggregate(_load_json_or_fail(args.dimensions),
                        _load_json_or_fail(args.artifacts), machine)
    elif args.cmd == "diagnose":
        packet = _load_json_or_fail(args.packet) if args.packet else None
        out = diagnose_regeneration(_load_json_or_fail(args.review), packet,
                                    attempt=args.attempt)
    elif args.cmd == "advance":
        review = _load_json_or_fail(args.review) if args.review else None
        out = {"new_acceptance_status": advance_acceptance(
            _load_json_or_fail(args.asset), review,
            args.license == "1", args.metadata == "1", target=args.target)}
    elif args.cmd == "variants":
        out = review_variants([_load_json_or_fail(f) for f in args.reviews])
    else:  # pragma: no cover
        parser.error(f"未知子命令: {args.cmd}")

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# ---------------------------------------------------------------------------
# 自检（纯逻辑，不依赖 ffmpeg）
# ---------------------------------------------------------------------------

def _fulldim(score: int = 8, skip: Optional[str] = None) -> dict:
    """构造 18 维全 evidence 输入（跳过 skip 维度），供自检用。"""
    d = {}
    for name, _w in DIMENSIONS:
        if name == skip:
            continue
        d[name] = {"score": score, "evidence": [{"source": "human"}]}
    return d


def selftest() -> None:
    """纯函数自检（aggregate / advance / diagnose / variants / 确定性）。"""
    checks = [
        # 全维度 evidence（缺 composition）→ 有 evidence 缺失 → 不得 PASS（PASS_WITH_ISSUES）
        aggregate(_fulldim(skip="composition"), {})["verdict"] == "PASS_WITH_ISSUES",
        # 全维度 evidence 且高分 → PASS
        aggregate(_fulldim(score=8), {})["verdict"] == "PASS",
        # 无 evidence → score 按 0 → REGENERATE（verdict 不得 PASS）
        aggregate({}, {})["verdict"] == "REGENERATE",
        aggregate({"prompt_adherence": {"score": 1, "evidence": [{"source": "human"}]}},
                  {})["verdict"] == "REJECT",
        aggregate(_fulldim(score=8),
                  {"hand_deformation": {"detected": True, "evidence": [{"source": "vision_model"}]}}
                  )["verdict"] == "PASS_WITH_ISSUES",  # hard 伪影 → 最高 PASS_WITH_ISSUES
        advance_acceptance({"acceptance_status": "CANDIDATE"},
                           {"verdict": "PASS"}, True, True) == "SELECTED",
        advance_acceptance({"acceptance_status": "CANDIDATE"},
                           {"verdict": "REGENERATE"}, True, True) == "REVISION_REQUIRED",
        advance_acceptance({"acceptance_status": "SELECTED"},
                           {"verdict": "PASS"}, True, True) == "APPROVED",
        not _TRANSITIONS.get("CANDIDATE", set()) & {"APPROVED", "NORMALIZED",
                                                    "READY_FOR_TIMELINE"},
    ]
    # 非法迁移
    try:
        advance_acceptance({"acceptance_status": "CANDIDATE"},
                           {"verdict": "PASS"}, True, True, target="READY_FOR_TIMELINE")
        checks.append(False)
    except ValueError:
        checks.append(True)
    # APPROVED 被 hard 伪影拒绝
    try:
        advance_acceptance({"acceptance_status": "SELECTED"},
                           {"verdict": "PASS_WITH_ISSUES", "issues": ["x"],
                            "artifacts": {"face_deformation": {"detected": True}}},
                           True, True, target="APPROVED")
        checks.append(False)
    except ValueError:
        checks.append(True)
    # READY_FOR_TIMELINE 缺 license
    try:
        advance_acceptance({"acceptance_status": "NORMALIZED"},
                           {"verdict": "PASS", "machine_checks": {"probe": {}},
                            "issues": []}, False, True, target="READY_FOR_TIMELINE")
        checks.append(False)
    except ValueError as exc:
        checks.append("license" in str(exc))
    # diagnose 阶梯
    checks.append(diagnose_regeneration({"dimensions": {}})["next_step"] == "prompt_refinement")
    checks.append(diagnose_regeneration({"dimensions": {}, "failure_attempt": 2})["next_step"]
                  == "reduce_complexity")
    blocked = diagnose_regeneration({"dimensions": {}}, attempt=4)
    checks.append(blocked["blocked"] is True and blocked["approval_required"] is True
                  and set(blocked["recommended_alternatives"]) == set(BLOCKED_ALTERNATIVES))
    # variants
    r = review_variants([
        {"variant_id": "v1", "score": 70, "verdict": "PASS_WITH_ISSUES"},
        {"variant_id": "v2", "score": 88, "verdict": "PASS"},
        {"variant_id": "v3", "score": 55, "verdict": "REGENERATE"},
    ])
    checks.append(r["ranked"] == ["v2", "v1", "v3"])
    checks.append(r["selected"]["variant_id"] == "v2")
    checks.append(len(r["rejected"]) == 2 and all(x["metadata_kept"] is True
                                                  and x["reason"] for x in r["rejected"]))
    # 确定性
    d1 = diagnose_regeneration({"dimensions": {"composition": {"score": 3,
                                                              "evidence": [{"source": "human"}]}}})
    d2 = diagnose_regeneration({"dimensions": {"composition": {"score": 3,
                                                              "evidence": [{"source": "human"}]}}})
    checks.append(d1 == d2)
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError(f"selftest check #{i} failed")
    print("review selftest OK")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        selftest()
    else:
        try:
            sys.exit(_cli_main())
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(1)
