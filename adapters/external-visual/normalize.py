#!/usr/bin/env python3
"""normalize.py — VIDEO_NORMALIZATION（Phase-6 §44-45 / §83-84；P6-04）.

对已摄取的外部视频执行**按需**标准化（§45：不无脑重编码）：

- 仅当目标不满足时才做对应变换：
  container（默认 mp4）、codec（默认 H.264）、fps、resolution、orientation
  （rotation 元数据纠正）、audio（KEEP/MUTE/USE_AS_AMBIENCE/EXTRACT/REPLACE）。
- 全部满足 → ``changed=[]`` 且 ``output_path`` = 原路径（**不重编码**）。
- 输出命名 ``{stem}_norm.mp4``（默认 stem = 源文件名去扩展名）；原文件永不删除
  （§47 Original Preservation）。
- EXTRACT：额外产出 ``{stem}_audio.wav``（pcm_s16le），视频静音。
- REPLACE：需要调用方提供 ``target.audio_file``；未提供则保留原音轨并记录说明。

确定性：同一输入 + 同一 target → 同一输出（滤镜顺序、编码参数全部写死常量）。
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

from .probe import probe_video, DEFAULT_TIMEOUT
from .audio_decision import AUDIO_MODES

FFMPEG = "/opt/homebrew/bin/ffmpeg"

# 标准化目标常量（§44-45；确定性，写死）
CONTAINER_TARGET = "mp4"
CODEC_TARGET = "h264"
PIX_FMT_TARGET = "yuv420p"
X264_PRESET = "medium"
X264_CRF = 23
AUDIO_CODEC = "aac"
AUDIO_BITRATE = "128k"
FPS_TOLERANCE = 0.01            # fps 判定容差（±0.01fps）
NORM_SUFFIX = "_norm.mp4"
AUDIO_WAV_SUFFIX = "_audio.wav"

DEFAULT_TARGET: dict = {
    "container": CONTAINER_TARGET,
    "codec": CODEC_TARGET,
    "fps": None,                # None = 保持源 fps（不强制统一）
    "resolution": None,         # None = 保持源分辨率；dict{w,h} = 精确目标
    "orientation": "correct",   # correct = 纠正 rotation 元数据（rot90/180/270 时转置）
    "audio_mode": "KEEP",       # KEEP/MUTE/USE_AS_AMBIENCE/EXTRACT/REPLACE
    "audio_file": None,         # REPLACE 用外部音频文件（可选）
}

# rotation 元数据 → ffmpeg transpose 滤镜（确定性映射；§44 orientation）
_ROTATION_TRANSPOSE = {
    90: "transpose=1",          # 顺时针 90°
    180: "vflip,hflip",         # 翻转
    270: "transpose=2",         # 逆时针 90°
}


def _run_ffmpeg(args: list, timeout: int = DEFAULT_TIMEOUT) -> dict:
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"ffmpeg 调用失败: {exc}"}
    return {"returncode": proc.returncode, "stdout": proc.stdout or "",
            "stderr": proc.stderr or ""}


def _display_size(video: dict) -> tuple:
    """考虑 rotation 后的显示尺寸（rot 90/270 → 宽高互换）。"""
    w = video.get("width")
    h = video.get("height")
    rot = video.get("rotation")
    if w is None or h is None:
        return (w, h)
    if rot in (90, 270):
        return (h, w)
    return (w, h)


def _audio_codec_ok(probe: dict) -> bool:
    audios = probe.get("audio") or []
    return all((a.get("codec") or "").lower() in ("aac", "mp3") for a in audios)


def plan_normalize(probe: dict, target: dict) -> dict:
    """决策表：计算需要哪些变换（确定性，不改文件）。返回 {changed, need_encode,
    need_remux, vf_list, audio_map, notes}。"""
    changed: list = []
    notes: list = []
    video = probe.get("video") or {}
    has_audio = bool(probe.get("has_audio"))
    fmt_name = str(probe.get("format_name") or "")
    container_ok = "mp4" in fmt_name or "mov" in fmt_name
    codec = str(video.get("codec") or "").lower()
    fps = video.get("fps")
    disp_w, disp_h = _display_size(video)
    rotation = video.get("rotation")
    audio_mode = str(target.get("audio_mode") or "KEEP").upper()
    if audio_mode not in AUDIO_MODES:
        audio_mode = "KEEP"
        notes.append(f"未知 audio_mode={target.get('audio_mode')!r}，回落 KEEP")

    need_video_encode = False
    need_remux = False
    vf_list: list = []

    # container（§44 container normalization）
    t_container = str(target.get("container") or CONTAINER_TARGET).lower()
    if t_container == "mp4" and not container_ok:
        changed.append(f"container: {probe.get('format_name')} → mp4")
        need_remux = True

    # codec（§45 wrong codec 才 Normalize）
    t_codec = str(target.get("codec") or CODEC_TARGET).lower()
    if t_codec == "h264" and codec != "h264":
        changed.append(f"codec: {codec or '?'} → h264")
        need_video_encode = True

    # fps（§44-45 wrong fps 才改）
    t_fps = target.get("fps")
    if t_fps is not None and fps is not None and abs(fps - float(t_fps)) > FPS_TOLERANCE:
        changed.append(f"fps: {fps} → {float(t_fps)}")
        need_video_encode = True

    # resolution（§44-45 wrong resolution 才改；scale+pad 保持画面完整）
    t_res = target.get("resolution")
    if isinstance(t_res, dict) and t_res.get("w") and t_res.get("h"):
        tw, th = int(t_res["w"]), int(t_res["h"])
        if (disp_w, disp_h) != (tw, th):
            changed.append(f"resolution: {disp_w}x{disp_h} → {tw}x{th}")
            need_video_encode = True
            vf_list.append(
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2"
            )

    # orientation（rotation 元数据纠正；§44 orientation）
    t_orient = str(target.get("orientation") or "correct").lower()
    if t_orient == "correct" and rotation in _ROTATION_TRANSPOSE:
        changed.append(f"rotation: {rotation}° 纠正（transpose）")
        need_video_encode = True
        vf_list.append(_ROTATION_TRANSPOSE[rotation])

    # audio（§83-84）
    audio_map = {"mode": audio_mode, "has_audio": has_audio, "extract": False,
                 "replace_file": None}
    if audio_mode == "MUTE" and has_audio:
        changed.append("audio: MUTE（移除原音轨）")
        audio_map["remove"] = True
    elif audio_mode == "EXTRACT" and has_audio:
        changed.append("audio: EXTRACT（导出 wav + 视频静音）")
        audio_map["extract"] = True
        audio_map["remove"] = True
    elif audio_mode == "REPLACE":
        af = target.get("audio_file")
        if af and Path(af).is_file():
            changed.append(f"audio: REPLACE（替换为 {Path(af).name}）")
            audio_map["replace_file"] = str(af)
        else:
            notes.append("audio: REPLACE 未提供有效 audio_file，保留原音轨")
    elif audio_mode in ("KEEP", "USE_AS_AMBIENCE"):
        if has_audio and not _audio_codec_ok(probe):
            changed.append("audio: 编码转 aac（原音轨非 aac/mp3）")
            audio_map["reencode_audio"] = True

    need_video_encode = need_video_encode or bool(vf_list)
    need_remux = need_remux and not need_video_encode

    return {
        "changed": changed,
        "notes": notes,
        "need_video_encode": need_video_encode,
        "need_remux": need_remux,
        "vf_list": vf_list,
        "audio_map": audio_map,
        "effective_mode": audio_mode,
    }


def _build_encode_cmd(path: str, plan: dict, target: dict,
                      t_fps, out_path: str) -> list:
    args = [FFMPEG, "-y", "-v", "error", "-i", str(path)]
    amap = plan["audio_map"]
    if amap.get("replace_file"):
        args += ["-i", amap["replace_file"]]
    vf = ",".join(plan["vf_list"])
    if vf:
        args += ["-vf", vf]
    args += ["-c:v", "libx264", "-preset", X264_PRESET, "-crf", str(X264_CRF),
             "-pix_fmt", PIX_FMT_TARGET]
    if t_fps is not None:
        args += ["-r", str(t_fps)]
    # audio 映射
    if amap.get("replace_file"):
        args += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", AUDIO_CODEC,
                 "-b:a", AUDIO_BITRATE]
    elif amap.get("remove"):
        args += ["-an"]
    elif amap.get("has_audio"):
        args += ["-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE]
    args += ["-f", "mp4", "-movflags", "+faststart", str(out_path)]
    return args


def normalize(path, probe: Optional[dict] = None, target: Optional[dict] = None,
              out_dir=None, out_stem: Optional[str] = None,
              timeout: int = DEFAULT_TIMEOUT) -> dict:
    """标准化入口。

    参数：
        path      源视频路径（**永不修改/删除**）
        probe     可选复用 probe_video() 结果
        target    目标（merge DEFAULT_TARGET）
        out_dir   输出目录（默认源文件所在目录）
        out_stem  输出名干（不含扩展名；默认 ``{源名}_norm``）

    返回 {output_path, changed[], notes[], reencoded, audio_mode, audio_artifact,
          target}。
    """
    src = Path(path)
    if probe is None:
        probe = probe_video(str(src), timeout=timeout)
    if not probe.get("ok"):
        return {"output_path": str(src), "changed": [],
                "notes": [f"probe 失败：{probe.get('error')}"],
                "reencoded": False, "audio_mode": None,
                "audio_artifact": None, "target": dict(target or {})}

    effective = dict(DEFAULT_TARGET)
    if isinstance(target, dict):
        effective.update({k: v for k, v in target.items() if v is not None})

    plan = plan_normalize(probe, effective)
    t_fps = effective.get("fps")

    if not plan["changed"]:
        # §45：已满足要求 → 不重编码
        return {"output_path": str(src), "changed": [], "notes": plan["notes"],
                "reencoded": False, "audio_mode": plan["effective_mode"],
                "audio_artifact": None, "target": effective}

    out_dir_p = Path(out_dir) if out_dir else src.parent
    stem = out_stem if out_stem else src.stem
    out_path = out_dir_p / f"{stem}{NORM_SUFFIX}"
    out_dir_p.mkdir(parents=True, exist_ok=True)

    audio_artifact = None
    if plan["audio_map"].get("extract"):
        wav_path = out_dir_p / f"{stem}{AUDIO_WAV_SUFFIX}"
        wav_cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src),
                   "-vn", "-acodec", "pcm_s16le", str(wav_path)]
        res = _run_ffmpeg(wav_cmd, timeout=timeout)
        if res["returncode"] != 0:
            plan["notes"].append(f"音频抽取失败：{res['stderr'][-300:]}")
        else:
            audio_artifact = str(wav_path)

    if plan["need_remux"]:
        cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src),
               "-c", "copy", "-f", "mp4", "-movflags", "+faststart",
               str(out_path)]
    elif not plan["need_video_encode"]:
        # 仅音频变换：视频 stream copy（§45 不无脑重编码；只处理音轨）
        amap = plan["audio_map"]
        cmd = [FFMPEG, "-y", "-v", "error", "-i", str(src)]
        if amap.get("replace_file"):
            cmd += ["-i", amap["replace_file"], "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE]
        elif amap.get("remove"):
            cmd += ["-map", "0:v:0", "-c:v", "copy", "-an"]
        else:  # KEEP / USE_AS_AMBIENCE（音频转 aac）
            cmd += ["-map", "0:v:0", "-c:v", "copy",
                    "-c:a", AUDIO_CODEC, "-b:a", AUDIO_BITRATE]
        cmd += ["-f", "mp4", "-movflags", "+faststart", str(out_path)]
    else:
        cmd = _build_encode_cmd(str(src), plan, effective, t_fps, str(out_path))

    res = _run_ffmpeg(cmd, timeout=timeout)
    if res["returncode"] != 0:
        return {"output_path": str(src), "changed": [],
                "notes": plan["notes"] + [f"normalize 编码失败：{res['stderr'][-500:]}"],
                "reencoded": False, "audio_mode": plan["effective_mode"],
                "audio_artifact": audio_artifact, "target": effective,
                "error": res["stderr"][-500:]}

    return {"output_path": str(out_path), "changed": plan["changed"],
            "notes": plan["notes"], "reencoded": True,
            "audio_mode": plan["effective_mode"],
            "audio_artifact": audio_artifact, "target": effective}


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    probe_ok = {
        "ok": True, "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "has_audio": True,
        "video": {"codec": "h264", "width": 1920, "height": 1080,
                  "fps": 30.0, "rotation": None},
        "audio": [{"codec": "aac"}],
    }
    # 已满足 → 不重编码
    plan = plan_normalize(probe_ok, dict(DEFAULT_TARGET))
    assert plan["changed"] == [] and not plan["need_video_encode"]
    # fps 不符 → 重编码
    plan2 = plan_normalize(probe_ok, {"fps": 25})
    assert any(c.startswith("fps:") for c in plan2["changed"])
    # 分辨率不符
    plan3 = plan_normalize(probe_ok, {"resolution": {"w": 1280, "h": 720}})
    assert any(c.startswith("resolution:") for c in plan3["changed"])
    # 容器不符（webm）+ 重编码
    probe_webm = dict(probe_ok, format_name="matroska,webm",
                      video=dict(probe_ok["video"], codec="vp9"))
    plan4 = plan_normalize(probe_webm, dict(DEFAULT_TARGET))
    assert any(c.startswith("codec:") for c in plan4["changed"])
    # MUTE 有音轨 → 移除
    plan5 = plan_normalize(probe_ok, {"audio_mode": "MUTE"})
    assert plan5["audio_map"].get("remove")
    print("external-visual/normalize selftest OK")


if __name__ == "__main__":
    selftest()
