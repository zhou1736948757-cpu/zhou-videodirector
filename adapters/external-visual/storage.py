#!/usr/bin/env python3
"""storage.py — 外部视觉资产存储布局与策略（Phase-6 §90-95；P6-04）.

存储布局（§90-95）：
    <project>/assets/external-visual/{asset_id}/
        {asset_id}_v{n}_original.{ext}   原始文件（永不覆盖/删除，§47/§90）
        {asset_id}_v{n}_norm.mp4         标准化产物（按需生成）
        {asset_id}_v{n}_proxy.mp4        代理（按需生成）
        {asset_id}_v{n}_audio.wav        EXTRACT 抽取音轨（按需生成）
        {asset_id}_v{n}_asset.json       该版本元数据
        rejected_variants.json           被拒变体（只保 metadata+reason，§93）

版本策略（§90）：同 asset_id 二次摄取 → v2，v1 不覆盖；``next_version()`` 扫描
已有 ``_v{n}_original`` 取 max+1。

storage_policy 四档（§94）：
    KEEP_ALL                      —— 全部保留，不产生删除清单
    KEEP_SELECTED                 —— 只保留 selected 版本的完整文件
    KEEP_SELECTED_AND_PREVIEWS    —— selected 完整 + 所有版本的 proxy（预览）；默认（§95）
    CUSTOM                        —— 调用方自定义；未传参时按 KEEP_SELECTED_AND_PREVIEWS

``apply_storage_policy()`` **只列出待删除清单，不实际删除**（§93/§95：删除由调用方
/用户在批准后执行）。``record_rejected_variant()`` 只写 metadata+reason，不保留
被拒变体的 payload 文件（§93）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

STORAGE_POLICIES = ("KEEP_ALL", "KEEP_SELECTED", "KEEP_SELECTED_AND_PREVIEWS", "CUSTOM")
DEFAULT_STORAGE_POLICY = "KEEP_SELECTED_AND_PREVIEWS"

ASSETS_REL = "assets/external-visual"
REJECTED_JSON_NAME = "rejected_variants.json"

_VERSION_ORIGINAL_RE = re.compile(r"^(.+)_v(\d+)_original\.([^.]+)$")
_VERSION_NORM_RE = re.compile(r"^(.+)_v(\d+)_norm\.mp4$")
_VERSION_PROXY_RE = re.compile(r"^(.+)_v(\d+)_proxy\.mp4$")
_VERSION_AUDIO_RE = re.compile(r"^(.+)_v(\d+)_audio\.wav$")
_VERSION_ASSET_JSON_RE = re.compile(r"^(.+)_v(\d+)_asset\.json$")


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 布局
# ---------------------------------------------------------------------------

def asset_dir(project_dir, asset_id: str) -> Path:
    """`<project>/assets/external-visual/{asset_id}` 目录（不存在则返回路径不创建）。"""
    return Path(project_dir) / ASSETS_REL / str(asset_id)


def list_versions(asset_dir_p) -> list:
    """扫描目录，返回已有版本号列表（int，升序）；目录不存在 → []。"""
    p = Path(asset_dir_p)
    versions: set = set()
    if not p.is_dir():
        return []
    for name in p.iterdir():
        m = _VERSION_ORIGINAL_RE.match(name.name)
        if m:
            versions.add(int(m.group(2)))
    return sorted(versions)


def next_version(project_dir, asset_id: str) -> int:
    """下一个版本号 = max(已有)+1；无 → 1（§90 版本递增不覆盖）。"""
    versions = list_versions(asset_dir(project_dir, asset_id))
    return (versions[-1] + 1) if versions else 1


def version_files(project_dir, asset_id: str, version: int,
                  source_suffix: str = ".mp4") -> dict:
    """该版本候选文件路径（可能不存在）：original/norm/proxy/audio/asset_json。"""
    d = asset_dir(project_dir, asset_id)
    return {
        "original": d / f"{asset_id}_v{version}_original{source_suffix}",
        "norm": d / f"{asset_id}_v{version}_norm.mp4",
        "proxy": d / f"{asset_id}_v{version}_proxy.mp4",
        "audio": d / f"{asset_id}_v{version}_audio.wav",
        "asset_json": d / f"{asset_id}_v{version}_asset.json",
    }


# ---------------------------------------------------------------------------
# 存储策略（§94-95）—— 只列清单，不实际删除
# ---------------------------------------------------------------------------

def apply_storage_policy(asset_dir_p, policy: str = DEFAULT_STORAGE_POLICY,
                         selected=None, opts: Optional[dict] = None) -> dict:
    """返回待删除清单 ``{policy, selected, items[{path, reason}], rationale}``。

    - ``selected``：保留版本号列表（int）；缺省 = 最新版本。
    - **只列清单**：本函数不删除任何文件；删除动作由调用方/用户在批准后执行。
    - 文件分类按命名约定（_original/_norm/_proxy/_audio/_asset.json）。
    """
    d = Path(asset_dir_p)
    pol = str(policy or DEFAULT_STORAGE_POLICY).upper()
    if pol not in STORAGE_POLICIES:
        pol = DEFAULT_STORAGE_POLICY
    versions = list_versions(d)
    if not versions:
        return {"policy": pol, "selected": [], "items": [],
                "rationale": "目录为空或无版本文件，无删除项"}
    sel = sorted({int(v) for v in (selected or [versions[-1]])} & set(versions)) or [versions[-1]]

    files = _classify_files(d)
    items: list = []
    for version in versions:
        if version in sel:
            continue
        entry = files.get(version)
        if not entry:
            continue
        for kind, path in entry.items():
            if pol == "KEEP_ALL":
                continue
            if pol == "KEEP_SELECTED":
                items.append({"path": str(path),
                              "reason": f"非 selected 版本 v{version} 的 {kind}（KEEP_SELECTED）"})
            elif pol in ("KEEP_SELECTED_AND_PREVIEWS", "CUSTOM"):
                # 预览（proxy）全部保留；original/norm/audio 只留 selected 版本
                if kind != "proxy":
                    items.append({"path": str(path),
                                  "reason": f"非 selected 版本 v{version} 的 {kind}（{pol}：保留 proxy）"})

    rationale = {
        "KEEP_ALL": "KEEP_ALL：全部保留，无删除项（§94）",
        "KEEP_SELECTED": f"KEEP_SELECTED：仅保留 selected 版本 {sel} 的全部文件（§94）",
        "KEEP_SELECTED_AND_PREVIEWS":
            f"KEEP_SELECTED_AND_PREVIEWS（默认 §95）：保留 selected 版本 {sel} 全部文件"
            " + 所有版本的 proxy 预览；其余删除",
        "CUSTOM": f"CUSTOM：调用方自定义；默认按 KEEP_SELECTED_AND_PREVIEWS 处理（selected={sel}）",
    }[pol]

    return {"policy": pol, "selected": sel, "items": items, "rationale": rationale}


def _classify_files(d: Path) -> dict:
    """{version: {kind: path}} 按命名约定分类目录内文件。"""
    out: dict[int, dict] = {}
    if not d.is_dir():
        return out
    for child in sorted(d.iterdir()):
        if not child.is_file():
            continue
        for regex, kind in ((_VERSION_ORIGINAL_RE, "original"),
                            (_VERSION_NORM_RE, "norm"),
                            (_VERSION_PROXY_RE, "proxy"),
                            (_VERSION_AUDIO_RE, "audio")):
            m = regex.match(child.name)
            if m:
                out.setdefault(int(m.group(2)), {})[kind] = child
                break
    return out


# ---------------------------------------------------------------------------
# 被拒变体（§93：只保 metadata+reason，不保留 payload）
# ---------------------------------------------------------------------------

def rejected_variants_path(asset_dir_p) -> Path:
    return Path(asset_dir_p) / REJECTED_JSON_NAME


def record_rejected_variant(asset_dir_p, asset_id: str, variant_id: str,
                            reason: str, metadata: Optional[dict] = None) -> dict:
    """记录被拒变体（§93）。追加到 ``rejected_variants.json``（新建/追加，不覆盖）。

    返回新写入的条目。payload 文件是否保留由 storage_policy 决定（默认不保留）。
    """
    d = Path(asset_dir_p)
    d.mkdir(parents=True, exist_ok=True)
    path = rejected_variants_path(d)
    entries: list = []
    if path.is_file():
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = []
    entry = {
        "asset_id": str(asset_id),
        "variant_id": str(variant_id),
        "reason": str(reason),
        "metadata": dict(metadata or {}),
        "recorded_at": now_iso(),
    }
    entries.append(entry)
    entries.sort(key=lambda e: (str(e.get("variant_id") or ""),
                                str(e.get("recorded_at") or "")))
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return entry


def read_rejected_variants(asset_dir_p) -> list:
    """读被拒变体记录；无 → []。"""
    path = rejected_variants_path(Path(asset_dir_p))
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def selftest() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "assets/external-visual/A001"
        d.mkdir(parents=True)
        (d / "A001_v1_original.mp4").write_text("x")
        (d / "A001_v1_norm.mp4").write_text("x")
        (d / "A001_v1_proxy.mp4").write_text("x")
        (d / "A001_v2_original.mp4").write_text("x")
        (d / "A001_v2_norm.mp4").write_text("x")
        (d / "A001_v2_proxy.mp4").write_text("x")
        assert list_versions(d) == [1, 2]
        assert next_version(tmp, "A001") == 3
        keep_all = apply_storage_policy(d, "KEEP_ALL")
        assert keep_all["items"] == []
        sel2 = apply_storage_policy(d, "KEEP_SELECTED", selected=[2])
        assert {i["path"].split("/")[-1] for i in sel2["items"]} == {
            "A001_v1_original.mp4", "A001_v1_norm.mp4", "A001_v1_proxy.mp4"}
        keep_pv = apply_storage_policy(d, "KEEP_SELECTED_AND_PREVIEWS", selected=[2])
        kinds = {i["path"].split("/")[-1] for i in keep_pv["items"]}
        assert kinds == {"A001_v1_original.mp4", "A001_v1_norm.mp4"}
        # 只列清单不删
        assert (d / "A001_v1_original.mp4").exists()
        # 被拒变体
        e = record_rejected_variant(d, "A001", "variant-02", "脸崩")
        assert e["reason"] == "脸崩"
        assert len(read_rejected_variants(d)) == 1
    print("external-visual/storage selftest OK")


if __name__ == "__main__":
    selftest()
