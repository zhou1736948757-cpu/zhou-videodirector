#!/usr/bin/env python3
"""continuity.py — 连续性档案引擎（Phase-6 Prompt §85-89 / §122-127；P6-2）.

Character / Environment 连续性档案、Visual Family、Scene Pack 与 Reference Frame Bank：
多个 Generative Shot 通过共享档案保持一致（§122-124），生成成功的 approved 帧进入
Reference Frame Bank 供后续同场景生成（§125-127）。本模块只产出档案元数据，不产生
资产文件、不自行抽帧（抽帧归 P6-04）。

能力（字段对齐 P6-01 continuity-profile.schema.json 的 kind 结构）：
- CharacterProfile(§86)：CP-CHAR-###（appearance/hair/clothing/age/body_type/
  accessories/color_palette/reference_assets）
- EnvironmentProfile(§87)：CP-ENV-###（architecture/materials/lighting/time/layout/
  signature_objects/reference_frames）
- VisualFamily(§85)：VF-###（color/lighting/camera/environment/character/style_reference）
  —— 多个 GV shot 共享
- ScenePack(§123-124)：SP-###（environment_profile_ref + lighting + style +
  shots[{shot_id, type: ESTABLISHING|MEDIUM|DETAIL|TRANSITION}]）；同一环境的
  wide/medium/close 用同一 profile（§122）
- ReferenceFrameBank(§125-127)：RFB-### 容器，帧 RF-###（HERO/START/END/CONTINUITY）；
  只接受 approved 视频/approved 帧（§126）；从 packet/资产记录提取元数据，不自行抽帧
- product_warning(§88-89)：真实产品/品牌/Logo/精确工业设计 → 建议 real asset/3D/
  Remotion overlay，并禁止把精确产品外观写进生成描述

技术约束：Python 3 stdlib only；json 文件读写；无 LLM、无随机、无联网；确定性
（同输入同输出；created_at 仅在调用方显式传入时写入）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量（P6-01 continuity-profile.schema.json / PHASE6_PROMPT §85-87 / §123-127）
# ---------------------------------------------------------------------------

CHAR_PROFILE_RE = re.compile(r"^CP-CHAR-\d{3}$")
ENV_PROFILE_RE = re.compile(r"^CP-ENV-\d{3}$")
VF_RE = re.compile(r"^VF-\d{3}$")
SP_RE = re.compile(r"^SP-\d{3}$")
RFB_RE = re.compile(r"^RFB-\d{3}$")
FRAME_RE = re.compile(r"^RF-\d{3}$")

PROFILE_KINDS = (
    "CHARACTER_PROFILE", "ENVIRONMENT_PROFILE", "VISUAL_FAMILY",
    "SCENE_PACK", "REFERENCE_FRAME_BANK",
)
SHOT_TYPES = ("ESTABLISHING", "MEDIUM", "DETAIL", "TRANSITION")
FRAME_KINDS = ("HERO", "START", "END", "CONTINUITY")
ACCEPTED_APPROVAL = ("approved", "APPROVED", "READY_FOR_TIMELINE", "SELECTED")


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _require_id(profile_id: str, pattern: re.Pattern, label: str) -> str:
    if not pattern.match(str(profile_id)):
        raise ValueError("%s 必须匹配 %s，得到 %r" % (label, pattern.pattern, profile_id))
    return str(profile_id)


def _default(profile: dict, key: str, value: Any = None) -> None:
    if key not in profile:
        profile[key] = value


def _strip_none(value: Any) -> Any:
    """递归省略值为 None 的键（FR-018：character 缺省 None 字段不输出，schema 不收 null）。

    学 packet_builder._strip_none / P6-04 "可选空值省略键"：dict 中值为 None 的键省略；
    list 元素保留；非容器原样返回。
    """
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value]
    return value


def _style_ref_list(value: Any) -> list:
    """style_reference 归一为 list of strings（F4/R5：schema 契约 array of strings，§85
    语义"多个风格参考"）。字符串 → 单元素列表；list/tuple → 逐项 str；None → []。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out = []
        for v in value:
            s = v if isinstance(v, str) else str(v)
            if s.strip():
                out.append(s)
        return out
    return [str(value)]


def _require_enum(value: Any, allowed: tuple, label: str) -> str:
    s = str(value).upper().replace(" ", "_").replace("-", "_")
    if s not in allowed:
        raise ValueError("%s 必须属于 %s，得到 %r" % (label, allowed, value))
    return s


# ---------------------------------------------------------------------------
# §86 CharacterProfile → CP-CHAR-###
# ---------------------------------------------------------------------------

def create_character_profile(
    profile_id: str,
    *,
    name: Optional[str] = None,
    appearance: Optional[str] = None,
    hair: Optional[str] = None,
    clothing: Optional[str] = None,
    age: Optional[str] = None,
    body_type: Optional[str] = None,
    accessories: Optional[str] = None,
    color_palette: Optional[str] = None,
    reference_assets: Optional[list] = None,
    created_at: Optional[str] = None,
) -> dict:
    """§86 Character Continuity Profile：跨 shot 共享的人物外观档案。

    返回 dict（kind=CHARACTER_PROFILE），结构对齐 P6-01 continuity-profile.schema.json。
    created_at 仅在显式传入时写入（保证确定性）。
    """
    profile_id = _require_id(profile_id, CHAR_PROFILE_RE, "CP-CHAR profile_id")
    profile: dict = {
        "profile_id": profile_id,
        "kind": "CHARACTER_PROFILE",
        "character": _strip_none({
            "name": name,
            "appearance": appearance,
            "hair": hair,
            "clothing": clothing,
            "age": age,
            "body_type": body_type,
            "accessories": accessories,
            "color_palette": color_palette,
            "reference_assets": list(reference_assets) if reference_assets else [],
        }),
    }
    if created_at is not None:
        profile["created_at"] = created_at
    return profile


# ---------------------------------------------------------------------------
# §87 EnvironmentProfile → CP-ENV-###
# ---------------------------------------------------------------------------

def create_environment_profile(
    profile_id: str,
    *,
    architecture: Optional[str] = None,
    materials: Optional[str] = None,
    lighting: Optional[str] = None,
    time: Optional[str] = None,
    layout: Optional[str] = None,
    signature_objects: Optional[list] = None,
    reference_frames: Optional[list] = None,
    created_at: Optional[str] = None,
) -> dict:
    """§87 Environment Continuity Profile：同一地点的环境档案（§122 多 shot 共享）。"""
    profile_id = _require_id(profile_id, ENV_PROFILE_RE, "CP-ENV profile_id")
    profile: dict = {
        "profile_id": profile_id,
        "kind": "ENVIRONMENT_PROFILE",
        "environment": _strip_none({
            "architecture": architecture,
            "materials": materials,
            "lighting": lighting,
            "time": time,
            "layout": layout,
            "signature_objects": list(signature_objects) if signature_objects else [],
            "reference_frames": list(reference_frames) if reference_frames else [],
        }),
    }
    if created_at is not None:
        profile["created_at"] = created_at
    return profile


# ---------------------------------------------------------------------------
# §85 VisualFamily → VF-###
# ---------------------------------------------------------------------------

def create_visual_family(
    family_id: str,
    *,
    color: Optional[str] = None,
    lighting: Optional[str] = None,
    camera: Optional[str] = None,
    environment: Optional[str] = None,
    character: Optional[str] = None,
    style_reference: Optional[list] = None,
    created_at: Optional[str] = None,
) -> dict:
    """§85 Visual Asset Family：多个 GV shot 共享的视觉家族（color/lighting/camera/
    environment/character/style reference）。"""
    family_id = _require_id(family_id, VF_RE, "VF family_id")
    profile: dict = {
        "profile_id": family_id,
        "kind": "VISUAL_FAMILY",
        "visual_family": _strip_none({
            "color": color,
            "lighting": lighting,
            "camera": camera,
            "environment": environment,
            "character": character,
            "style_reference": _style_ref_list(style_reference),
        }),
    }
    if created_at is not None:
        profile["created_at"] = created_at
    return profile


# ---------------------------------------------------------------------------
# §123-124 ScenePack → SP-###
# ---------------------------------------------------------------------------

def create_scene_pack(
    pack_id: str,
    *,
    name: Optional[str] = None,
    environment_profile_ref: Optional[str] = None,
    lighting: Optional[str] = None,
    style: Optional[str] = None,
    shots: Optional[list] = None,
    created_at: Optional[str] = None,
) -> dict:
    """§123-124 GENERATIVE_SCENE_PACK：同一环境的一组 shot（Establishing/Medium/Detail/
    Transition），共享 Environment Profile / Lighting / Style（§122 wide/medium/close
    用同一 profile）。"""
    pack_id = _require_id(pack_id, SP_RE, "SP pack_id")
    norm_shots: list = []
    for shot in shots or []:
        if not isinstance(shot, dict):
            raise ValueError("ScenePack.shots 元素必须是 dict {shot_id, type}")
        shot_id = shot.get("shot_id")
        if not shot_id:
            raise ValueError("ScenePack.shots 元素缺少 shot_id")
        shot_type = _require_enum(
            shot.get("type") or "MEDIUM", SHOT_TYPES, "ScenePack.shot.type")
        norm_shots.append({"shot_id": str(shot_id), "type": shot_type})
    profile: dict = {
        "profile_id": pack_id,
        "kind": "SCENE_PACK",
        "scene_pack": _strip_none({
            "name": name,
            "environment_profile_ref": environment_profile_ref,
            "lighting": lighting,
            "style": style,
            "shots": norm_shots,
        }),
        "continuity_note": "同一环境 wide/medium/close 共享同一 environment_profile_ref（§122）",
    }
    if created_at is not None:
        profile["created_at"] = created_at
    return profile


# ---------------------------------------------------------------------------
# §125-127 ReferenceFrameBank → RFB-###（帧 RF-###，只接受 approved）
# ---------------------------------------------------------------------------

def create_reference_frame_bank(
    bank_id: str,
    *,
    frames: Optional[list] = None,
    created_at: Optional[str] = None,
) -> dict:
    """§125 Reference Frame Bank：存放 approved 帧元数据（RF-###，kind=HERO/START/
    END/CONTINUITY）。只接受 approved 帧（§126）；抽帧归 P6-04。"""
    bank_id = _require_id(bank_id, RFB_RE, "RFB bank_id")
    norm_frames = [add_frame({}, frame_id=f.get("frame_id"),
                             asset_ref=f.get("asset_ref"),
                             variant_id=f.get("variant_id"),
                             kind=f.get("kind"),
                             purpose=f.get("purpose"),
                             approved=f.get("approved", True))
                   for f in (frames or [])]
    profile: dict = {
        "profile_id": bank_id,
        "kind": "REFERENCE_FRAME_BANK",
        "reference_frame_bank": {
            "bank_id": bank_id,
            "frames": norm_frames,
        },
        "continuity_note": "只保存 approved 视频/approved 帧（§126）；实际抽帧由 P6-04 执行",
    }
    if created_at is not None:
        profile["created_at"] = created_at
    return profile


def add_frame(bank: dict, *, frame_id: str, asset_ref: Optional[str] = None,
              variant_id: Optional[str] = None, kind: str = "CONTINUITY",
              purpose: Optional[str] = None, approved: Any = False,
              created_at: Optional[str] = None) -> dict:
    """往 RFB 里加一帧。非 approved（§126）→ raise ValueError（确定性拒绝）。"""
    frame_id = _require_id(frame_id, FRAME_RE, "RF frame_id")
    kind = _require_enum(kind, FRAME_KINDS, "frame.kind")
    approved_flag = approved in (True, "true", "True", "1", "yes") or \
        str(approved).lower() in ACCEPTED_APPROVAL
    if not approved_flag:
        raise ValueError(
            "Reference Frame Bank 只接受 approved 帧（§126），%r 未批准" % frame_id)
    if bank is None or not isinstance(bank, dict) or bank.get("kind") != "REFERENCE_FRAME_BANK":
        raise TypeError("add_frame 需要一个 REFERENCE_FRAME_BANK profile dict")
    frames = bank.setdefault("reference_frame_bank", {}).setdefault("frames", [])
    if any(f.get("frame_id") == frame_id for f in frames):
        raise ValueError("frame_id %r 已存在（不重复积累，§126）" % frame_id)
    entry = {
        "frame_id": frame_id,
        "asset_ref": asset_ref,
        "variant_id": variant_id,
        "kind": kind,
        "purpose": purpose or ("参考帧 %s（%s）" % (frame_id, kind)),
    }
    if created_at is not None:
        entry["created_at"] = created_at
    frames.append(entry)
    return bank


def frames_from_packet(packet: dict, *, asset_ref: Optional[str] = None,
                       variant_id: Optional[str] = None,
                       approved: Any = True) -> list:
    """从 GV Packet 提取可入 Bank 的帧元数据（§127 从 packet 记录提取，不自行抽帧）。

    START 帧 ← packet.start_frame.state；END 帧 ← packet.end_frame.state；
    两状态一致时只产一帧（CONTINUITY）。approved 由调用方决定（默认 True）。
    """
    if not isinstance(packet, dict):
        return []
    approved_flag = approved in (True, "true", "True", "1", "yes") or \
        str(approved).lower() in ACCEPTED_APPROVAL
    if not approved_flag:
        return []
    start = packet.get("start_frame") or {}
    end = packet.get("end_frame") or {}
    start_state = str(start.get("state") or "")
    end_state = str(end.get("state") or "")
    shot_id = packet.get("shot_id") or "?"
    frames: list = []
    if start_state:
        if start_state == end_state:
            frames.append({
                "frame_id": _frame_id_for(packet, "CONT"),
                "asset_ref": asset_ref,
                "variant_id": variant_id,
                "kind": "CONTINUITY",
                "purpose": "shot %s 起止一致帧（packet.start_frame=end_frame）" % shot_id,
            })
        else:
            frames.append({
                "frame_id": _frame_id_for(packet, "ST"),
                "asset_ref": asset_ref,
                "variant_id": variant_id,
                "kind": "START",
                "purpose": "shot %s 首帧：%s" % (shot_id, start_state),
            })
    if end_state and end_state != start_state:
        frames.append({
            "frame_id": _frame_id_for(packet, "END"),
            "asset_ref": asset_ref,
            "variant_id": variant_id,
            "kind": "END",
            "purpose": "shot %s 尾帧：%s" % (shot_id, end_state),
        })
    return frames


def _frame_id_for(packet: dict, tag: str) -> str:
    """确定性 RF-###：由 packet_id 数字 + 序号派生（GV-001 → RF-001/002…）。"""
    digits = re.sub(r"\D", "", str(packet.get("packet_id") or "0"))
    n = int(digits[-3:]) if digits else 0
    if tag == "CONT":
        return "RF-%03d" % (n * 10 + 1)
    if tag == "ST":
        return "RF-%03d" % (n * 10 + 1)
    return "RF-%03d" % (n * 10 + 2)


# ---------------------------------------------------------------------------
# §88-89 product_warning
# ---------------------------------------------------------------------------

def product_warning(
    *,
    description: Optional[str] = None,
    real_product: bool = False,
    brand: Optional[str] = None,
    has_logo: bool = False,
    exact_industrial_design: bool = False,
    forbidden_tokens: Optional[list] = None,
) -> dict:
    """§88-89：真实产品 / 品牌 / Logo / 精确工业设计 → 返回建议，并禁止把精确产品外观
    写进生成描述。

    推荐路径：real asset / 3D / Remotion overlay（§89：不要依赖纯生成）。
    """
    triggers: list = []
    if real_product:
        triggers.append("真实产品")
    if has_logo:
        triggers.append("品牌/Logo")
    if exact_industrial_design:
        triggers.append("精确工业设计")
    if brand:
        triggers.append("品牌 %r" % brand)
    guard = None
    if description:
        guard = str(description)
        if brand:
            guard = re.sub(re.escape(str(brand)), "[brand]", guard, flags=re.IGNORECASE)
        guard = re.sub(r'["\u201c\u201d]([^"\u201c\u201d]{1,80})["\u201c\u201d]',
                       "［精确产品外观/文字由 3D 或 overlay 承载］", guard)
        for token in (forbidden_tokens or []):
            guard = re.sub(re.escape(str(token)), "[product-detail]", guard,
                           flags=re.IGNORECASE)
    return {
        "warning": "出现真实产品/品牌/Logo/精确工业设计：生成式视频会随机改变产品设计，"
                   "精确外观不适合由纯生成承担（§88-89）",
        "triggers": triggers,
        "recommended_approaches": ["real_asset", "3D", "remotion_overlay"],
        "generation_restriction": "禁止在 model_ready_prompt / subject / environment 中写入"
                                  "精确产品外观、品牌名与 Logo 图案；产品本体以 3D / 真实资产"
                                  "/ Remotion overlay 承载",
        "guarded_description": guard,
        "strict": bool(triggers),
    }


def guard_product_text(text: str, forbidden_tokens: Optional[list] = None) -> str:
    """确定性清洗：把生成描述里的品牌名 / 引号字面量 / 自定义禁词替换为占位符。"""
    if not isinstance(text, str):
        return str(text)
    out = re.sub(r'["\u201c\u201d]([^"\u201c\u201d]{1,80})["\u201c\u201d]',
                 "［精确产品外观由 3D / overlay 承载，禁止写入生成描述］", text)
    for token in (forbidden_tokens or []):
        out = re.sub(re.escape(str(token)), "[brand]", out, flags=re.IGNORECASE)
    return out


# ---------------------------------------------------------------------------
# 档案存取（stdlib json；落盘到调用方指定目录，如 E2E 项目 continuity/ 子目录）
# ---------------------------------------------------------------------------

def save_profile(profile: dict, directory: str | Path, *, indent: int = 2) -> Path:
    """把档案写成 <directory>/<profile_id>.json。确定性输出（sort_keys）。"""
    if not isinstance(profile, dict) or not profile.get("profile_id"):
        raise ValueError("profile 必须是含 profile_id 的 dict")
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    path = d / ("%s.json" % profile["profile_id"])
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=indent,
                               sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_profiles(directory: str | Path) -> dict:
    """读取目录下全部档案 JSON → {profile_id: profile}（确定性排序键）。"""
    out: dict = {}
    d = Path(directory)
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("profile_id"):
            out[str(data["profile_id"])] = data
    return out


def list_profiles(directory: str | Path) -> list:
    """按 profile_id 排序列出目录中的档案。"""
    return sorted(load_profiles(directory).values(), key=lambda p: str(p.get("profile_id")))


def next_profile_id(directory: str | Path, prefix: str) -> str:
    """确定性分配下一个 ID：扫描目录内 prefix-### 档案取最大号 +1（如 CP-CHAR-002）。"""
    existing = [str(p.get("profile_id")) for p in list_profiles(directory)]
    nums = []
    pat = re.compile(r"^%s-(\d{3})$" % re.escape(prefix))
    for pid in existing:
        m = pat.match(pid)
        if m:
            nums.append(int(m.group(1)))
    return "%s-%03d" % (prefix, (max(nums) + 1 if nums else 1))


class ContinuityStore:
    """连续性档案存取门面：目录 = E2E 项目 continuity/ 子目录。"""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def save(self, profile: dict) -> Path:
        return save_profile(profile, self.directory)

    def load(self) -> dict:
        return load_profiles(self.directory)

    def list(self) -> list:
        return list_profiles(self.directory)

    def get(self, profile_id: str) -> Optional[dict]:
        return load_profiles(self.directory).get(profile_id)

    def next_id(self, prefix: str) -> str:
        return next_profile_id(self.directory, prefix)


# ---------------------------------------------------------------------------
# CLI：python3 -m modules.external-visual.continuity <subcommand>
# ---------------------------------------------------------------------------

def _parse_json_list(value: Optional[str], label: str) -> list:
    if value in (None, ""):
        return []
    try:
        data = json.loads(value)
    except ValueError as exc:
        raise ValueError("%s 必须是 JSON 数组，解析失败: %s" % (label, exc))
    if not isinstance(data, list):
        raise ValueError("%s 必须是 JSON 数组" % label)
    return data


def _sub_create_character(args) -> int:
    store = ContinuityStore(_resolve_dir(args))
    profile = create_character_profile(
        args.id or store.next_id("CP-CHAR"),
        name=args.name, appearance=args.appearance, hair=args.hair,
        clothing=args.clothing, age=args.age, body_type=args.body_type,
        accessories=args.accessories, color_palette=args.color_palette,
        reference_assets=_parse_json_list(args.reference_assets, "--reference-assets"),
    )
    path = store.save(profile)
    print("saved %s -> %s" % (profile["profile_id"], path))
    return 0


def _sub_create_environment(args) -> int:
    store = ContinuityStore(_resolve_dir(args))
    profile = create_environment_profile(
        args.id or store.next_id("CP-ENV"),
        architecture=args.architecture, materials=args.materials,
        lighting=args.lighting, time=args.time, layout=args.layout,
        signature_objects=_parse_json_list(args.signature_objects, "--signature-objects"),
        reference_frames=_parse_json_list(args.reference_frames, "--reference-frames"),
    )
    path = store.save(profile)
    print("saved %s -> %s" % (profile["profile_id"], path))
    return 0


def _sub_create_family(args) -> int:
    store = ContinuityStore(_resolve_dir(args))
    profile = create_visual_family(
        args.id or store.next_id("VF"),
        color=args.color, lighting=args.lighting, camera=args.camera,
        environment=args.environment, character=args.character,
        style_reference=_parse_json_list(args.style_reference, "--style-reference"),
    )
    path = store.save(profile)
    print("saved %s -> %s" % (profile["profile_id"], path))
    return 0


def _sub_create_scene_pack(args) -> int:
    store = ContinuityStore(_resolve_dir(args))
    profile = create_scene_pack(
        args.id or store.next_id("SP"),
        name=args.name, environment_profile_ref=args.environment_profile_ref,
        lighting=args.lighting, style=args.style,
        shots=_parse_json_list(args.shots, "--shots"),
    )
    path = store.save(profile)
    print("saved %s -> %s" % (profile["profile_id"], path))
    return 0


def _sub_add_frame(args) -> int:
    bank = load_profiles(_resolve_dir(args)).get(args.bank)
    if bank is None:
        raise FileNotFoundError("找不到 bank %r，目录 %s" % (args.bank, _resolve_dir(args)))
    add_frame(bank, frame_id=args.frame_id, asset_ref=args.asset_ref,
              variant_id=args.variant_id, kind=args.kind, purpose=args.purpose,
              approved=args.approved)
    save_profile(bank, _resolve_dir(args))
    print("added %s to %s" % (args.frame_id, args.bank))
    return 0


def _sub_list(args) -> int:
    for p in list_profiles(_resolve_dir(args)):
        print("%s  %s  %s" % (p.get("profile_id"), p.get("kind"),
                              p.get("created_at") or "-"))
    return 0


def _resolve_dir(args) -> str:
    """解析 --dir：可在子命令前或后给出；缺省 ./continuity。
    SUPPRESS 默认值保证子解析器不会用默认值覆盖主解析器已解析的值。"""
    return getattr(args, "dir", "continuity")


def main(argv: Optional[list] = None) -> int:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--dir", default=argparse.SUPPRESS,
                        help="档案目录（缺省 ./continuity，E2E 项目用其 continuity/ 子目录）")
    ap = argparse.ArgumentParser(
        prog="python3 -m modules.external-visual.continuity",
        description="连续性档案引擎（CP-CHAR/CP-ENV/VF/SP/RFB；P6-2 §85-89/§122-127）",
        parents=[parent])
    sub = ap.add_subparsers(dest="subcommand", required=True)

    p_c = sub.add_parser("create-character", parents=[parent], help="§86 创建人物档案 CP-CHAR-###")
    p_c.add_argument("--id", default=None)
    p_c.add_argument("--name", dest="name", default=None, help="人物姓名")
    p_c.add_argument("--appearance", default=None)
    p_c.add_argument("--hair", default=None)
    p_c.add_argument("--clothing", default=None)
    p_c.add_argument("--age", default=None)
    p_c.add_argument("--body-type", dest="body_type", default=None)
    p_c.add_argument("--accessories", default=None)
    p_c.add_argument("--color-palette", dest="color_palette", default=None)
    p_c.add_argument("--reference-assets", dest="reference_assets", default=None,
                     help="JSON 数组：参考资产路径列表")
    p_c.set_defaults(func=_sub_create_character)

    p_e = sub.add_parser("create-environment", parents=[parent],
                         help="§87 创建环境档案 CP-ENV-###")
    p_e.add_argument("--id", default=None)
    p_e.add_argument("--architecture", default=None)
    p_e.add_argument("--materials", default=None)
    p_e.add_argument("--lighting", default=None)
    p_e.add_argument("--time", default=None)
    p_e.add_argument("--layout", default=None)
    p_e.add_argument("--signature-objects", dest="signature_objects", default=None,
                     help="JSON 数组")
    p_e.add_argument("--reference-frames", dest="reference_frames", default=None,
                     help="JSON 数组")
    p_e.set_defaults(func=_sub_create_environment)

    p_f = sub.add_parser("create-family", parents=[parent],
                         help="§85 创建 Visual Family VF-###")
    p_f.add_argument("--id", default=None)
    p_f.add_argument("--color", default=None)
    p_f.add_argument("--lighting", default=None)
    p_f.add_argument("--camera", default=None)
    p_f.add_argument("--environment", default=None)
    p_f.add_argument("--character", default=None)
    p_f.add_argument("--style-reference", dest="style_reference", default=None,
                     help="JSON 数组")
    p_f.set_defaults(func=_sub_create_family)

    p_s = sub.add_parser("create-scene-pack", parents=[parent],
                         help="§123-124 创建 Scene Pack SP-###")
    p_s.add_argument("--id", default=None)
    p_s.add_argument("--name", default=None)
    p_s.add_argument("--environment-profile-ref", dest="environment_profile_ref",
                     default=None)
    p_s.add_argument("--lighting", default=None)
    p_s.add_argument("--style", default=None)
    p_s.add_argument("--shots", default=None,
                     help='JSON 数组，如 [{"shot_id":"S025","type":"ESTABLISHING"}]')
    p_s.set_defaults(func=_sub_create_scene_pack)

    p_fr = sub.add_parser("add-frame", parents=[parent],
                          help="§125-127 向 RFB 添加 approved 帧")
    p_fr.add_argument("--bank", required=True, help="RFB-###")
    p_fr.add_argument("--frame-id", dest="frame_id", required=True, help="RF-###")
    p_fr.add_argument("--asset-ref", dest="asset_ref", default=None)
    p_fr.add_argument("--variant-id", dest="variant_id", default=None)
    p_fr.add_argument("--kind", default="CONTINUITY",
                      choices=FRAME_KINDS)
    p_fr.add_argument("--purpose", default=None)
    p_fr.add_argument("--approved", default=True,
                      help="非 approved 帧被拒绝（§126）；传 false 测试拒绝路径")
    p_fr.set_defaults(func=_sub_add_frame)

    p_l = sub.add_parser("list", parents=[parent], help="列出目录内档案")
    p_l.set_defaults(func=_sub_list)

    args = ap.parse_args(argv)
    return args.func(args)


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    ch = create_character_profile("CP-CHAR-001", name="林", hair="gray",
                                  clothing="trench coat", age="60s")
    env = create_environment_profile("CP-ENV-001", architecture="museum hall",
                                     lighting="soft warm", layout="open hall")
    fam = create_visual_family("VF-001", color="desaturated warm",
                               camera="restrained push-in")
    sp = create_scene_pack("SP-001", name="Memory Museum",
                           environment_profile_ref="CP-ENV-001",
                           shots=[{"shot_id": "S025", "type": "ESTABLISHING"},
                                  {"shot_id": "S026", "type": "MEDIUM"},
                                  {"shot_id": "S027", "type": "DETAIL"}])
    bank = create_reference_frame_bank("RFB-001")
    add_frame(bank, frame_id="RF-001", asset_ref="A001", kind="START",
              purpose="hero frame", approved=True)
    pw = product_warning(real_product=True, brand="Acme", has_logo=True)
    checks = [
        ch["kind"] == "CHARACTER_PROFILE" and ch["character"]["hair"] == "gray",
        env["kind"] == "ENVIRONMENT_PROFILE",
        fam["kind"] == "VISUAL_FAMILY",
        sp["scene_pack"]["shots"][0]["type"] == "ESTABLISHING",
        bank["reference_frame_bank"]["frames"][0]["frame_id"] == "RF-001",
        "3D" in pw["recommended_approaches"] and pw["strict"] is True,
        "no watermark" in pw.get("generation_restriction", "") or "禁止" in pw["generation_restriction"],
        next_profile_id(".", "CP-CHAR") == "CP-CHAR-001",
    ]
    for i, ok in enumerate(checks, 1):
        if not ok:
            raise AssertionError("continuity selftest check #%d failed" % i)
    print("continuity selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        sys.exit(main())
