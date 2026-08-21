#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZHOU_Videodirector — FluidSynth Adapter (P5-5)

定位 (§53-57 / §86): MIDI + SoundFont -> WAV 的真实渲染入口。

本 adapter 只做「存在性检测 + 命令行构建 + 执行 + 记录」，**不自己实现
SoundFont Synthesizer / MIDI 播放器**（§54: FluidSynth 是外部 PROVIDER，
reuse-map 明示 do_not: reimplement_synth_engine）。

规则:
  - fluidsynth 缺席时绝不伪造 WAV，返回 DEPENDENCY_MISSING（§95 格式）。
  - dry_run=True 只构建并返回 command，不执行、不产生任何文件。
  - 每次调用记录 command/input/output/soundfont/render status（§86 命令记录契约）。
  - 失败重试由上游 retry_policy 处理（3 次 -> BLOCKED，§93-94），本模块单次尽力。

Python 3 stdlib only。无第三方依赖。
"""

import json
import os
import shlex
import shutil
import subprocess
from datetime import datetime, timezone

#: FluidSynth CLI 可执行名（brew 安装后为 fluidsynth）
FLUIDSYNTH_BIN = "fluidsynth"

#: 默认 GeneralUser-GS SoundFont 的 registry id（registry/index/resources.jsonl 中
#: generaluser-gs:soundfont:generaluser-gs）；本地缓存路径由上游/用户提供。
DEFAULT_SOUNDFONT_PROVIDER = "generaluser-gs"

#: §86 命令记录契约的固定字段顺序
RENDER_RECORD_FIELDS = [
    "command",      # 实际构建的 argv（list）
    "input",        # MIDI 输入路径
    "output",       # WAV 输出路径
    "soundfont",    # SoundFont 路径
    "render_status",  # pending / ok / failed / DEPENDENCY_MISSING / INPUT_MISSING
]


def _now_iso() -> str:
    """返回 UTC ISO 8601 时间戳（用于记录）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fluidsynth_available() -> bool:
    """检测 fluidsynth 是否可执行（shutil.which）。"""
    return shutil.which(FLUIDSYNTH_BIN) is not None


def build_command(midi_path, soundfont_path, out_wav, sample_rate=44100):
    """构建 fluidsynth 命令行（list 形式）。

    fluidsynth -ni -F <out.wav> -r <sample_rate> <soundfont> <midi>

    - -n  no shell 模式；-i  no interactive 模式；-F  渲染到 WAV 文件；
    - -r  采样率（Hz）。
    """
    return [
        FLUIDSYNTH_BIN,
        "-ni",
        "-F", str(out_wav),
        "-r", str(sample_rate),
        str(soundfont_path),
        str(midi_path),
    ]


def _dependency_missing_record(midi_path, out_wav, soundfont_path, sample_rate):
    """构造 DEPENDENCY_MISSING 报告（§95 格式：required/installation/impact）。"""
    return {
        "status": "DEPENDENCY_MISSING",
        "required": FLUIDSYNTH_BIN,
        "installation": "brew install fluidsynth",
        "impact": "procedural music unavailable",
        "record": {
            "command": None,
            "command_str": None,
            "input": str(midi_path),
            "output": str(out_wav),
            "soundfont": str(soundfont_path),
            "sample_rate": sample_rate,
            "render_status": "DEPENDENCY_MISSING",
            "logged_at": _now_iso(),
        },
    }


def render_midi(midi_path, soundfont_path, out_wav, sample_rate=44100, dry_run=True,
                record_path=None, **extra):
    """渲染 MIDI -> WAV。

    参数:
      midi_path       : MIDI 输入文件路径
      soundfont_path  : SoundFont (.sf2) 路径
      out_wav         : 输出 WAV 路径
      sample_rate     : 采样率（默认 44100）
      dry_run         : True 只返回 command 不执行（默认 True，安全）
      record_path     : 可选 JSONL 记录文件；给定则把 §86 记录追加写入

    返回 dict:
      - status: 'DEPENDENCY_MISSING' | 'INPUT_MISSING' | 'dry_run'
                | 'ok' | 'failed'
      - command / command_str / input / output / soundfont / sample_rate
      - render_status: pending / ok / failed / DEPENDENCY_MISSING / INPUT_MISSING
      - record: §86 记录（command/input/output/soundfont/render status + 时间戳）
      - DEPENDENCY_MISSING 时附 required/installation/impact（§95）
    """
    if not fluidsynth_available():
        rec = _dependency_missing_record(midi_path, out_wav, soundfont_path, sample_rate)
        _append_record(rec["record"], record_path)
        return rec

    # 输入存在性校验（缺席不执行、不伪造）
    missing = []
    if not os.path.isfile(str(midi_path)):
        missing.append(str(midi_path))
    if not os.path.isfile(str(soundfont_path)):
        missing.append(str(soundfont_path))
    if missing:
        rec = {
            "status": "INPUT_MISSING",
            "required": ", ".join(missing),
            "installation": "check path / fetch via registry (fetch gate: approval+license)",
            "impact": "render skipped",
            "record": {
                "command": None,
                "command_str": None,
                "input": str(midi_path),
                "output": str(out_wav),
                "soundfont": str(soundfont_path),
                "sample_rate": sample_rate,
                "render_status": "INPUT_MISSING",
                "logged_at": _now_iso(),
            },
        }
        _append_record(rec["record"], record_path)
        return rec

    command = build_command(midi_path, soundfont_path, out_wav, sample_rate)
    base = {
        "command": command,
        "command_str": shlex.join(command),
        "input": str(midi_path),
        "output": str(out_wav),
        "soundfont": str(soundfont_path),
        "sample_rate": sample_rate,
    }

    if dry_run:
        record = dict(base, render_status="pending", logged_at=_now_iso())
        _append_record(record, record_path)
        return {
            "status": "dry_run",
            "render_status": "pending",
            "command": command,
            "command_str": base["command_str"],
            "input": base["input"],
            "output": base["output"],
            "soundfont": base["soundfont"],
            "sample_rate": sample_rate,
            "record": record,
        }

    # 真实渲染（非 dry_run）
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=extra.get("timeout", 600),
            check=False,
        )
        success = proc.returncode == 0 and os.path.isfile(str(out_wav))
        render_status = "ok" if success else "failed"
        record = dict(base, render_status=render_status, logged_at=_now_iso())
        _append_record(record, record_path)
        return {
            "status": render_status,
            "render_status": render_status,
            "command": command,
            "command_str": base["command_str"],
            "input": base["input"],
            "output": base["output"],
            "soundfont": base["soundfont"],
            "sample_rate": sample_rate,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
            "record": record,
        }
    except subprocess.TimeoutExpired:
        record = dict(base, render_status="failed", logged_at=_now_iso(),
                      error="timeout after %ss" % extra.get("timeout", 600))
        _append_record(record, record_path)
        return {
            "status": "failed",
            "render_status": "failed",
            "command": command,
            "command_str": base["command_str"],
            "input": base["input"],
            "output": base["output"],
            "soundfont": base["soundfont"],
            "sample_rate": sample_rate,
            "error": record["error"],
            "record": record,
        }
    except OSError as exc:
        record = dict(base, render_status="failed", logged_at=_now_iso(),
                      error="OSError: %s" % exc)
        _append_record(record, record_path)
        return {
            "status": "failed",
            "render_status": "failed",
            "command": command,
            "command_str": base["command_str"],
            "input": base["input"],
            "output": base["output"],
            "soundfont": base["soundfont"],
            "sample_rate": sample_rate,
            "error": record["error"],
            "record": record,
        }


def _append_record(record, record_path):
    """把 §86 命令记录追加写入 JSONL（record_path 为空则跳过）。

    只写 record 本身（command/input/output/soundfont/render_status），
    不写整棵返回 dict，保持记录契约最小化。
    """
    if not record_path:
        return
    try:
        os.makedirs(os.path.dirname(os.path.abspath(record_path)), exist_ok=True)
        with open(record_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # 记录失败不影响渲染结果；上层可自行核盘
        pass


# ---- CLI（供人工/脚本调用） ----
def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description="FluidSynth adapter: MIDI+SoundFont -> WAV")
    ap.add_argument("midi")
    ap.add_argument("soundfont")
    ap.add_argument("out_wav")
    ap.add_argument("-r", "--sample-rate", type=int, default=44100)
    ap.add_argument("--execute", action="store_true", help="真正执行渲染（默认 dry-run）")
    ap.add_argument("--record", default=None, help="§86 记录 JSONL 路径")
    args = ap.parse_args(argv)

    print(json.dumps(
        render_midi(args.midi, args.soundfont, args.out_wav,
                    sample_rate=args.sample_rate, dry_run=not args.execute,
                    record_path=args.record),
        indent=2, ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
