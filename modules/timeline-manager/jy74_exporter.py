#!/usr/bin/env python3
"""modules/timeline-manager/jy74_exporter.py — 明文 7.4.0 草稿导出器（Phase-7 R4-P7）.

背景（chief 实测，2026-08-16）：剪映专业版 7.4.0 接受**明文 draft_info.json**——
内容 schema 与 5.9.0 同构（version=360000，顶层键集一致），``new_version`` 需为
``"75.0.0"``；草稿文件夹需在 ``~/Movies/JianyingPro/User Data/Projects/
com.lveditor.draft/`` 下并注册进 ``root_meta_info.json``；素材路径必须为**本机绝对
路径**（相对路径会报媒体丢失）。格式范本 = ``ZHOU-P7-TEST/draft_info.json``
（chief 手工修复版：31 顶层键 = pyJianYingDraft 28 键 + is_drop_frame_timecode/
lyrics_effects/path；platform 块为空块，来自真实模板 ``8月15日/template.tmp``）。

本模块职责（只做导出一步，不重跑 E2E pipeline）：
  1) 按项目 roots 约束构建 asset map（禁止 basename 全仓 glob，禁止跨项目误配）；
  2) 复用 R3 已装配的 draft_content.json（create_project+add_*+export_draft 产物），
     变换为 7.4.0 明文 draft_info.json（name/new_version='75.0.0'/id=uuid4/platform
     块取自真实模板/create_time+update_time/全部素材 path=绝对路径且逐条验证存在）；
  3) 写 ``{draft_root}/{draft_name}/`` 草稿文件夹（draft_info.json +
     draft_meta_info.json + 标准骨架文件），使其"看起来像本机自建"；
  4) 备份并追加注册 ``root_meta_info.json``（用户 "8月15日" 条目原样保留；
     ``draft_ids`` 语义按现文件实际——非简单 count，手工注册不改变它）。

诚实边界（§96）：只生成可打开的 Draft；打开剪映 / 检查 / 导出 由人类完成。
macOS 无 jianying_controller，本模块不做 GUI 自动化。

运行环境：stdlib only（无需 pyJianYingDraft）。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
TEMPLATE_DEFAULT_ID = "BC69C7CD-7C5E-4185-B284-AF3E1047A664"
NEW_VERSION = "75.0.0"
VERSION = 360000

# pyJianYingDraft draft_content 缺、但 7.4.0 格式范本有的 3 个顶层键
EXTRA_TOP_KEYS: Dict[str, Any] = {
    "is_drop_frame_timecode": False,
    "lyrics_effects": [],
    "path": "",
}

# 草稿文件夹内的标准空子目录（让草稿"看起来像本机自建"）
SKELETON_DIRS = [
    "adjust_mask", "matting", "qr_upload", "Resources", "smart_crop", "subdraft",
]

# 从格式范本文件夹复制的小型静态骨架文件
SKELETON_FILES = [
    "attachment_pc_common.json",
    "draft_agency_config.json",
    "draft_biz_config.json",
    "draft.extra",
]
SKELETON_COMMON_ATTACHMENT = [
    "coperate_create.json",
    "attachment_script_video.json",
]


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent="\t")


def _new_uuid() -> str:
    return str(uuid.uuid4()).upper()


def _now_us() -> int:
    return int(time.time() * 1_000_000)


def _is_uuid4(value: str) -> bool:
    return (isinstance(value, str) and len(value) == 36
            and value.count("-") == 4 and value != TEMPLATE_DEFAULT_ID)


# ---------------------------------------------------------------------------
# 1) Asset map（按项目 roots 约束；禁止跨项目 glob 误配）
# ---------------------------------------------------------------------------
def build_asset_map(
    manifest: Dict[str, Any],
    snapshot_assets: Dict[str, Any],
    project_roots: List[str],
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, str]]]:
    """按项目 roots 约束构建 asset_id → {path, kind}。

    - 主源：``manifest_v1.json`` 的 assets 索引（绝对路径，逐条验证存在）。
    - 次源：``timeline_v1.json`` 的 asset_links[].source（绝对路径）。
    - 约束：解析出的绝对路径必须位于 ``project_roots`` 之一内（禁止跨项目）。
      禁止 basename 全仓 glob —— 本函数从不按文件名全仓搜索。
    - 解析不到 / 不存在 → 进 MISSING 清单（不静默）。
    - ``A000`` 等 SUBTITLE 占位 asset（kind=text、无 path）→ 非媒体，不进 MISSING。
    """
    asset_map: Dict[str, Dict[str, Any]] = {}
    missing: List[Dict[str, str]] = []

    # 1) manifest 的 asset_links
    for link in manifest.get("asset_links") or []:
        if not isinstance(link, dict):
            continue
        aid = link.get("asset_id")
        if not aid:
            continue
        src = link.get("source")
        if src:
            asset_map.setdefault(aid, {"path": str(src), "kind": link.get("kind")})

    # 2) snapshot assets 索引（绝对路径，权威）
    for aid, ainfo in (snapshot_assets or {}).items():
        if not isinstance(ainfo, dict):
            continue
        p = ainfo.get("path")
        if p:
            asset_map[aid] = {"path": str(p), "kind": ainfo.get("kind")}
        elif ainfo.get("kind") == "text":
            # SUBTITLE/text 占位 asset：无媒体文件属正常，保留 kind 不进 MISSING
            asset_map.setdefault(aid, {"path": "", "kind": "text"})

    # 3) 逐条验证存在性 + 项目 roots 约束
    for aid, ainfo in asset_map.items():
        p = ainfo.get("path")
        if not p:
            continue
        if not os.path.isabs(p):
            missing.append({"asset_id": aid, "path": p, "reason": "NOT_ABSOLUTE"})
            continue
        if not os.path.exists(p):
            missing.append({"asset_id": aid, "path": p, "reason": "FILE_MISSING"})
            continue
        if not any(p.startswith(root + os.sep) for root in project_roots):
            missing.append({"asset_id": aid, "path": p, "reason": "OUTSIDE_PROJECT_ROOTS"})

    return asset_map, missing


# ---------------------------------------------------------------------------
# 2) 变换：draft_content → 7.4.0 明文 draft_info
# ---------------------------------------------------------------------------
def to_plaintext_74(
    draft_content: Dict[str, Any],
    *,
    name: str,
    new_version: str,
    draft_id: str,
    platform: Dict[str, Any],
    last_modified_platform: Dict[str, Any],
    create_time: int = 0,
    update_time: int = 0,
) -> Dict[str, Any]:
    """把 pyJianYingDraft 装配出的 draft_content 变换为 7.4.0 明文 draft_info。

    - 补齐 3 个顶层键（is_drop_frame_timecode / lyrics_effects / path）；
    - 设置 name / new_version='75.0.0' / id=uuid4 / create_time+update_time；
    - platform / last_modified_platform 块取自真实模板（8月15日/template.tmp）；
    - canvas_config 补 ``background: null``（与格式范本一致）；
    - 其余（materials/tracks/keyframes/config 等）原样保留。
    """
    out = copy.deepcopy(draft_content)
    for k, v in EXTRA_TOP_KEYS.items():
        out.setdefault(k, v)
    out["name"] = name
    out["new_version"] = new_version
    out["id"] = draft_id
    out["create_time"] = create_time
    out["update_time"] = update_time
    out["platform"] = copy.deepcopy(platform)
    out["last_modified_platform"] = copy.deepcopy(last_modified_platform)
    cc = dict(out.get("canvas_config") or {})
    cc.setdefault("background", None)
    out["canvas_config"] = cc
    return out


# ---------------------------------------------------------------------------
# 3) 素材路径：绝对化 + 逐条验证存在 + 项目 roots 约束
# ---------------------------------------------------------------------------
def resolve_material_paths(
    draft_info: Dict[str, Any],
    content_base: str,
    project_roots: List[str],
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """把所有 video/audio 素材 path 改写为绝对路径并验证。

    - draft_content 的素材 path 是相对 ``content_base``（导出时的 output_dir）
      的路径（§117 project-relative）；在此按 content_base 解析为绝对路径。
    - 逐条验证 ``os.path.exists``；不存在 → MISSING（不静默）。
    - 项目 roots 约束：绝对路径必须位于 project_roots 之一内 → 否则判 MISCONFIG
      （跨项目误配）。
    - 返回 (missing, misconfig)。
    """
    missing: List[Dict[str, str]] = []
    misconfig: List[Dict[str, str]] = []

    def _abs(base: str, p: str) -> str:
        return p if os.path.isabs(p) else os.path.abspath(os.path.join(base, p))

    for bucket in ("videos", "audios"):
        for mat in draft_info.get("materials", {}).get(bucket, []):
            p = mat.get("path")
            if not p:
                continue
            abs_p = _abs(content_base, p)
            if not os.path.exists(abs_p):
                missing.append({"bucket": bucket, "id": mat.get("id"),
                                "name": mat.get("material_name") or mat.get("name"),
                                "path": abs_p})
            elif not any(abs_p.startswith(root + os.sep) for root in project_roots):
                misconfig.append({"bucket": bucket, "id": mat.get("id"),
                                  "name": mat.get("material_name") or mat.get("name"),
                                  "path": abs_p})
            mat["path"] = abs_p
    return missing, misconfig


# ---------------------------------------------------------------------------
# 4) draft_meta_info.json（draft_id/draft_name/fold/json_file + 格式范本全套键）
# ---------------------------------------------------------------------------
def build_draft_meta(
    draft_id: str,
    draft_name: str,
    fold_path: str,
    json_file: str,
    root_path: str,
    new_version: str,
    info_size: int,
) -> Dict[str, Any]:
    """构造 draft_meta_info.json（模型 = ZHOU-P7-TEST/draft_meta_info.json）。"""
    now_us = _now_us()
    return {
        "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "",
        "draft_cloud_last_action_download": False,
        "draft_cloud_materials": [],
        "draft_cloud_package_type": "",
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": "draft_cover.jpg",
        "draft_deeplink_url": "",
        "draft_enterprise_info": {
            "draft_enterprise_extra": "",
            "draft_enterprise_id": "",
            "draft_enterprise_name": "",
            "enterprise_material": [],
        },
        "draft_fold_path": fold_path,
        "draft_id": draft_id,
        "draft_is_ae_produce": False,
        "draft_is_ai_packaging_used": False,
        "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False,
        "draft_is_article_video_draft": False,
        "draft_is_from_deeplink": "false",
        "draft_is_invisible": False,
        "draft_materials": [],
        "draft_materials_copied_info": [],
        "draft_name": draft_name,
        "draft_need_rename_folder": False,
        "draft_new_version": new_version,
        "draft_removable_storage_device": "",
        "draft_root_path": root_path,
        "draft_segment_extra_info": [],
        "draft_timeline_materials_size_": info_size,
        "draft_type": "",
        "draft_json_file": json_file,
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": 0,
    }


# ---------------------------------------------------------------------------
# 5) root_meta_info.json 条目 + 注册
# ---------------------------------------------------------------------------
def build_root_meta_entry(
    draft_id: str,
    draft_name: str,
    fold_path: str,
    json_file: str,
    root_path: str,
    new_version: str,
    info_size: int,
) -> Dict[str, Any]:
    """构造 root_meta_info.json all_draft_store 的一条（模型 = ZHOU-P7-TEST 条目）。"""
    now_us = _now_us()
    return {
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": os.path.join(fold_path, "draft_cover.jpg"),
        "draft_fold_path": fold_path,
        "draft_id": draft_id,
        "draft_is_ai_shorts": False,
        "draft_is_invisible": False,
        "draft_json_file": json_file,
        "draft_name": draft_name,
        "draft_new_version": new_version,
        "draft_root_path": root_path,
        "draft_timeline_materials_size": info_size,
        "draft_type": "",
        "tm_draft_cloud_completed": "",
        "tm_draft_cloud_modified": 0,
        "tm_draft_create": now_us,
        "tm_draft_modified": now_us,
        "tm_draft_removed": 0,
        "tm_duration": 0,
    }


def register_root_meta(
    root_meta_path: str,
    new_entries: List[Dict[str, Any]],
    backup_dir: str,
) -> Dict[str, Any]:
    """备份 root_meta_info.json → append 新条目 → 写回。

    - 先复制原文件到 ``backup_dir``（时间戳命名），不动原文件直到备份成功。
    - ``all_draft_store`` 保留既有条目**原样**（用户 "8月15日" 条目字节一致）。
    - ``draft_ids`` 语义按现文件实际：现文件 draft_ids=1 而 store 已有 2 条
      （ZHOU-P7-TEST 为手工注册，未改变 draft_ids）→ 手工注册不改变 draft_ids
      （以"不破坏 app 语义"为准）。
    - 返回 {ok, backup_path, draft_ids, store_count, appended_ids}。
    """
    if not os.path.exists(root_meta_path):
        return {"ok": False, "error": "ROOT_META_NOT_FOUND", "path": root_meta_path}
    root = _load_json(root_meta_path)
    if not isinstance(root, dict) or not isinstance(root.get("all_draft_store"), list):
        return {"ok": False, "error": "ROOT_META_INVALID", "path": root_meta_path}

    os.makedirs(backup_dir, exist_ok=True)
    backup_name = "root_meta_info.json.%s.bak" % time.strftime("%Y%m%d%H%M%S")
    backup_path = os.path.join(backup_dir, backup_name)
    shutil.copy2(root_meta_path, backup_path)

    store = root["all_draft_store"]
    existing_ids = {e.get("draft_id") for e in store if isinstance(e, dict)}
    appended: List[str] = []
    for entry in new_entries:
        eid = entry.get("draft_id")
        if eid in existing_ids:
            continue  # 幂等：不重复注册
        store.append(entry)
        existing_ids.add(eid)
        appended.append(str(eid))

    _write_json(root_meta_path, root)
    return {
        "ok": True,
        "backup_path": backup_path,
        "draft_ids": root.get("draft_ids"),  # 原样保留
        "store_count": len(store),
        "appended_ids": appended,
    }


# ---------------------------------------------------------------------------
# 6) 草稿文件夹写入
# ---------------------------------------------------------------------------
def write_draft_folder(
    draft_root: str,
    draft_name: str,
    draft_info: Dict[str, Any],
    draft_meta: Dict[str, Any],
    skeleton_src: Optional[str] = None,
    template_content: Optional[Dict[str, Any]] = None,
    template_src: Optional[str] = None,
) -> str:
    """创建 ``{draft_root}/{draft_name}/`` 并写入文件。

    - draft_info.json / draft_meta_info.json（必写）。
    - 骨架：标准空子目录 + 从 ``skeleton_src``（格式范本 ZHOU-P7-TEST）复制的
      小型静态文件 + 生成的 draft_settings。
    - template.tmp：优先用 ``template_content``（真实模板 8月15日/template.tmp
      的明文块，id 换新 uuid）；无则从 ``template_src`` 复制。
    """
    folder = os.path.join(draft_root, draft_name)
    if os.path.exists(folder):
        raise FileExistsError("draft folder already exists: %s" % folder)
    os.makedirs(folder)

    # 必写文件
    _write_json(os.path.join(folder, "draft_info.json"), draft_info)
    _write_json(os.path.join(folder, "draft_meta_info.json"), draft_meta)

    # 标准空子目录
    for d in SKELETON_DIRS:
        os.makedirs(os.path.join(folder, d), exist_ok=True)

    # 小型静态骨架文件（来自格式范本文件夹）
    if skeleton_src and os.path.isdir(skeleton_src):
        for fn in SKELETON_FILES:
            src = os.path.join(skeleton_src, fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(folder, fn))
        ca_dir = os.path.join(folder, "common_attachment")
        os.makedirs(ca_dir, exist_ok=True)
        for fn in SKELETON_COMMON_ATTACHMENT:
            src = os.path.join(skeleton_src, "common_attachment", fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(ca_dir, fn))

    # template.tmp
    if template_content is not None:
        tpl = copy.deepcopy(template_content)
        tpl["id"] = _new_uuid()  # 每个草稿独立 template id（与格式范本一致）
        with open(os.path.join(folder, "template.tmp"), "w", encoding="utf-8") as f:
            json.dump(tpl, f, ensure_ascii=False)
    elif template_src and os.path.exists(template_src):
        shutil.copy2(template_src, os.path.join(folder, "template.tmp"))

    # draft_settings（生成）
    now_s = int(time.time())
    settings = (
        "[General]\n"
        "cloud_last_modify_platform=mac\n"
        "draft_create_time=%d\n"
        "draft_last_edit_time=%d\n"
        "real_edit_keys=1\n"
        "real_edit_seconds=0\n" % (now_s, now_s)
    )
    with open(os.path.join(folder, "draft_settings"), "w", encoding="utf-8") as f:
        f.write(settings)

    return folder


# ---------------------------------------------------------------------------
# 7) 单项目导出编排（只做导出一步）
# ---------------------------------------------------------------------------
def export_project(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """导出单个项目到 JY 草稿根并注册。

    cfg 键：
      project_key / project_name / project_dir（e2e 项目根，素材相对路径基准）
      manifest_path（timeline_v1.json） / snapshot_path（manifest_v1.json）
      assembled_content_path（R3 draft_content.json）
      draft_root / draft_name
      real_template_path（8月15日/template.tmp）
      project_roots（phase5/6/7 + 同项目名的根，用于约束与验证）
      root_meta_path / backup_dir / skeleton_src
    """
    manifest = _load_json(cfg["manifest_path"])
    snapshot = _load_json(cfg["snapshot_path"])
    snapshot_assets = snapshot.get("assets") or {}
    content = _load_json(cfg["assembled_content_path"])

    # 1) asset map（项目 roots 约束）
    asset_map, asset_missing = build_asset_map(
        manifest, snapshot_assets, cfg["project_roots"])

    # 2) 真实模板 platform 块 + template 全文
    real_template = _load_json(cfg["real_template_path"])
    platform = real_template.get("platform") or {
        "app_id": 0, "app_source": "", "app_version": "",
        "device_id": "", "hard_disk_id": "", "mac_address": "", "os": "",
        "os_version": "",
    }
    lmp = real_template.get("last_modified_platform") or copy.deepcopy(platform)

    # 3) 变换为 7.4.0 明文 draft_info
    draft_id = _new_uuid()
    draft_info = to_plaintext_74(
        content, name=cfg["draft_name"], new_version=NEW_VERSION,
        draft_id=draft_id, platform=platform, last_modified_platform=lmp)

    # 4) 素材路径绝对化 + 逐条验证 + roots 约束
    content_base = cfg["project_dir"]
    mat_missing, mat_misconfig = resolve_material_paths(
        draft_info, content_base, cfg["project_roots"])

    # 5) 写草稿文件夹
    info_bytes = len(json.dumps(draft_info, ensure_ascii=False))
    fold_path = os.path.join(cfg["draft_root"], cfg["draft_name"])
    json_file = os.path.join(fold_path, "draft_info.json")
    draft_meta = build_draft_meta(
        draft_id, cfg["draft_name"], fold_path, json_file,
        cfg["draft_root"], NEW_VERSION, info_bytes)
    folder = write_draft_folder(
        cfg["draft_root"], cfg["draft_name"], draft_info, draft_meta,
        skeleton_src=cfg.get("skeleton_src"), template_content=real_template)

    # 6) root_meta 注册
    root_entry = build_root_meta_entry(
        draft_id, cfg["draft_name"], fold_path, json_file,
        cfg["draft_root"], NEW_VERSION, info_bytes)
    reg = register_root_meta(
        cfg["root_meta_path"], [root_entry], cfg["backup_dir"])

    return {
        "project_key": cfg["project_key"],
        "draft_name": cfg["draft_name"],
        "folder": folder,
        "draft_info_path": json_file,
        "draft_id": draft_id,
        "materials": {
            "videos": len(draft_info.get("materials", {}).get("videos", [])),
            "audios": len(draft_info.get("materials", {}).get("audios", [])),
            "texts": len(draft_info.get("materials", {}).get("texts", [])),
        },
        "asset_map_count": len(asset_map),
        "asset_missing": asset_missing,
        "material_missing": mat_missing,
        "material_misconfig": mat_misconfig,
        "root_meta": reg,
        "ok": bool(reg.get("ok") and not mat_missing and not mat_misconfig),
    }


# ---------------------------------------------------------------------------
# 8) 自测（≥6 断言）
# ---------------------------------------------------------------------------
def selftest(tmp: Optional[str] = None) -> int:
    """自带自测：≥6 断言。返回退出码（0=全绿）。"""
    base = tmp or os.path.join(
        os.path.expanduser("~"), ".zcode", "workspace", "default",
        "zhou-videodirector-phase7", "work", "p7-9", "selftest_tmp")
    os.makedirs(base, exist_ok=True)

    # --- 构造最小合成数据（不触碰真实草稿/资产）---
    fake_asset = os.path.join(base, "fake_media.mp4")
    with open(fake_asset, "wb") as f:
        f.write(b"\x00" * 16)

    fake_manifest = {
        "timeline_id": "TL-001", "fps": 30,
        "duration_frames": 900, "canvas": {"w": 1920, "h": 1080},
        "asset_links": [{"asset_id": "A001", "source": fake_asset,
                         "track": "V2_BROLL", "manual_edit_safe": False,
                         "producer": "TEST"},
                        {"asset_id": "A000", "track": "SUB", "source": "",
                         "manual_edit_safe": False, "producer": "TEST"}],
        "tracks": [], "clips": [],
    }
    fake_snapshot_assets = {"A001": {"path": fake_asset, "kind": "video"},
                            "A000": {"path": "", "kind": "text"}}
    fake_content = {
        "version": 360000, "name": "", "new_version": "110.0.0",
        "id": TEMPLATE_DEFAULT_ID, "fps": 30, "duration": 30_000_000,
        "canvas_config": {"width": 1920, "height": 1080, "ratio": "original"},
        "config": {}, "tracks": [], "keyframes": {},
        "materials": {
            "videos": [{"id": "m1", "material_id": "m1",
                        "material_name": "fake_media.mp4",
                        "path": os.path.relpath(fake_asset, base),
                        "type": "video", "width": 1920, "height": 1080,
                        "duration": 30_000_000}],
            "audios": [], "texts": [], "speeds": [],
        },
    }
    fake_template = {
        "name": "", "new_version": "75.0.0", "version": 360000,
        "id": "A3842400-1BF9-4B13-B5E8-FE5F84F53A4D",
        "platform": {"app_id": 0, "app_source": "", "app_version": "",
                     "device_id": "", "hard_disk_id": "", "mac_address": "",
                     "os": "", "os_version": ""},
        "last_modified_platform": {"app_id": 0, "app_source": "",
                                    "app_version": "", "device_id": "",
                                    "hard_disk_id": "", "mac_address": "",
                                    "os": "", "os_version": ""},
        "materials": {}, "tracks": [],
    }
    tmp_template = os.path.join(base, "template.tmp")
    _write_json(tmp_template, fake_template)

    # --- 断言 1: to_plaintext_74 补 3 键 + new_version/id/platform ---
    did = _new_uuid()
    di = to_plaintext_74(
        copy.deepcopy(fake_content), name="ZHOU-TEST-74",
        new_version=NEW_VERSION, draft_id=did,
        platform=fake_template["platform"],
        last_modified_platform=fake_template["last_modified_platform"])
    assert di["new_version"] == "75.0.0", "new_version 必须为 75.0.0"
    assert di["is_drop_frame_timecode"] is False
    assert di["lyrics_effects"] == []
    assert di["path"] == ""
    assert di["name"] == "ZHOU-TEST-74"
    assert di["canvas_config"].get("background") is None

    # --- 断言 2: uuid 唯一 + 非模板默认 ---
    d2 = _new_uuid()
    assert _is_uuid4(did) and _is_uuid4(d2) and did != d2, "uuid 互不相同且非模板默认"
    assert did != TEMPLATE_DEFAULT_ID and d2 != TEMPLATE_DEFAULT_ID

    # --- 断言 3: 素材路径绝对化 + 存在 + roots 约束（0 missing/misconfig）---
    missing, misconfig = resolve_material_paths(di, base, [base])
    assert missing == [], "素材路径缺失应报 MISSING（不静默），got %r" % missing
    assert misconfig == [], "跨项目误配应报 MISCONFIG，got %r" % misconfig
    resolved = di["materials"]["videos"][0]["path"]
    assert os.path.isabs(resolved) and os.path.exists(resolved)

    # --- 断言 4: 缺失路径被报 MISSING ---
    bad_content = copy.deepcopy(fake_content)
    bad_content["materials"]["videos"][0]["path"] = "no_such_file.mp4"
    bad_di = to_plaintext_74(
        bad_content, name="ZHOU-BAD", new_version=NEW_VERSION,
        draft_id=_new_uuid(), platform=fake_template["platform"],
        last_modified_platform=fake_template["last_modified_platform"])
    bad_missing, _ = resolve_material_paths(bad_di, base, [base])
    assert len(bad_missing) == 1 and bad_missing[0]["path"].endswith(
        "no_such_file.mp4"), "缺失素材必须进 MISSING 清单"

    # --- 断言 5: asset map 按项目 roots 约束（越界 → MISSING）---
    am, am_missing = build_asset_map(
        fake_manifest, fake_snapshot_assets, [base])
    assert am["A001"]["path"] == fake_asset
    assert am["A000"]["kind"] == "text"  # 非媒体占位，不进 MISSING
    assert all(m["asset_id"] != "A000" for m in am_missing)
    am2, am2_missing = build_asset_map(
        fake_manifest, {"A001": {"path": fake_asset, "kind": "video"}},
        [os.path.join(base, "other_root")])
    assert am2_missing and am2_missing[0]["reason"] == "OUTSIDE_PROJECT_ROOTS", \
        "越界 asset 必须报 OUTSIDE_PROJECT_ROOTS"

    # --- 断言 6: root_meta 注册保留既有条目 + draft_ids 原样 + 幂等 ---
    root_meta_path = os.path.join(base, "root_meta_info.json")
    fake_existing_entry = {
        "draft_cloud_last_action_download": False,
        "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": os.path.join(base, "8月15日", "draft_cover.jpg"),
        "draft_fold_path": os.path.join(base, "8月15日"),
        "draft_id": "92681740-3A43-4074-A352-F04DC6D3B062",
        "draft_is_ai_shorts": False, "draft_is_invisible": False,
        "draft_json_file": os.path.join(base, "8月15日", "draft_info.json"),
        "draft_name": "8月15日", "draft_new_version": "",
        "draft_root_path": base, "draft_timeline_materials_size": 3628,
        "draft_type": "",
        "tm_draft_cloud_completed": "", "tm_draft_cloud_modified": 0,
        "tm_draft_create": 1786805376408403, "tm_draft_modified": 1786805761585695,
        "tm_draft_removed": 0, "tm_duration": 0,
    }
    _write_json(root_meta_path,
                {"all_draft_store": [copy.deepcopy(fake_existing_entry)],
                 "draft_ids": 1,
                 "root_path": base})
    new_entry = build_root_meta_entry(
        did, "ZHOU-TEST-74", os.path.join(base, "ZHOU-TEST-74"),
        os.path.join(base, "ZHOU-TEST-74", "draft_info.json"),
        base, NEW_VERSION, 1234)
    reg = register_root_meta(root_meta_path, [new_entry, new_entry], base)
    assert reg["ok"] is True
    assert reg["draft_ids"] == 1, "draft_ids 语义按现文件实际，手工注册不改变"
    assert reg["store_count"] == 2, "append 且不重复"
    assert reg["appended_ids"] == [did], "幂等：重复条目只注册一次"
    after_root = _load_json(root_meta_path)
    kept = after_root["all_draft_store"][0]
    assert kept == fake_existing_entry, "既有条目（8月15日）必须原样保留"
    assert os.path.exists(reg["backup_path"]), "必须先备份"

    # --- 断言 7: 写草稿文件夹（含骨架 + template.tmp id 换新）---
    meta = build_draft_meta(
        did, "ZHOU-TEST-74", os.path.join(base, "ZHOU-TEST-74"),
        os.path.join(base, "ZHOU-TEST-74", "draft_info.json"),
        base, NEW_VERSION, 1234)
    folder = write_draft_folder(
        base, "ZHOU-TEST-74", di, meta,
        skeleton_src=None, template_content=fake_template)
    assert os.path.exists(os.path.join(folder, "draft_info.json"))
    assert os.path.exists(os.path.join(folder, "draft_meta_info.json"))
    assert os.path.exists(os.path.join(folder, "draft_settings"))
    assert os.path.exists(os.path.join(folder, "template.tmp"))
    tpl = _load_json(os.path.join(folder, "template.tmp"))
    assert tpl["new_version"] == "75.0.0"
    assert tpl["id"] != fake_template["id"], "template.tmp id 需换新 uuid"
    assert meta["draft_id"] == did and meta["draft_name"] == "ZHOU-TEST-74"
    assert meta["draft_fold_path"] == os.path.join(base, "ZHOU-TEST-74")
    assert meta["draft_json_file"] == os.path.join(
        base, "ZHOU-TEST-74", "draft_info.json")

    return 0


def main() -> int:
    try:
        rc = selftest()
    except Exception as exc:  # noqa: BLE001 — 自测失败给出可读退出码
        print("SELFTEST FAILED: %r" % exc)
        return 1
    print("jy74_exporter selftest: ALL GREEN (>=6 assertions)")
    return rc


if __name__ == "__main__":
    sys.exit(main())
