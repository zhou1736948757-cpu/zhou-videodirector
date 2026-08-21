#!/usr/bin/env python3
"""manifest.py — PRODUCTION_MANIFEST + ASSET_PACKAGE_MANIFEST（Phase-5 §75-79 / §114；P5-2）.

JSON 持久化到 `<project>/production/manifest.json`（§75 字段：request_id / asset_id /
producer / status / dependencies / input_resources / output / approval / version /
validation）。

职责：
- 请求生命周期（§76 状态机由 planner.can_transition 约束）
- 资产版本化（§71）：`register_asset` 生成 asset_id + version（v1/v2/v3 **不覆盖**，
  `A018_v1.mov` 命名约定）；`current_version(asset_id)` 查最新版本
- 增量生产（§77-79）：`mark_dirty` / `rebuild_needed`（spec hash 变化或依赖资产版本变化）
- ASSET_PACKAGE_MANIFEST（§114）：`export_package()` 汇总 motion/3D/music/sfx/ambience/
  sources/previews/licenses/versions/timeline_hints
- **Phase-6 §105/§132 扩展**（P6-07）：`export_package()` 追加 generative_video_assets /
  real_footage_assets / proxies / source_files / prompt_packets / provenance_entries /
  license_summary 七个新 section（全部可选，缺省空数组；旧 Phase 5 manifest 只增不改，
  向后兼容）。生成逻辑从资产目录按 type / origin / source_type 确定性自动分类。

全部确定性，无 LLM、无随机。stdlib + 可选 PyYAML（仅用于读 yaml，本模块 JSON 持久化
不依赖 PyYAML）。
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional

from .planner import (
    PRODUCTION_STATUSES,
    REQUEST_ID_RE,
    ASSET_ID_RE,
    can_transition,
    now_iso,
    spec_content,
    spec_hash,
)

MANIFEST_FILENAME = "production/manifest.json"

# 资产类型分类（§114 export_package 分组；枚举来自 asset.schema.json）
MOTION_ASSET_TYPES = {
    "MOTION_CLIP", "TRANSPARENT_OVERLAY", "ANIMATED_TEXT", "TRANSITION_ASSET",
    "INFOGRAPHIC", "UI_COMPONENT", "DECORATIVE_ELEMENT", "PARTICLE_LAYER",
    "FULL_SCENE",
}
THREE_D_ASSET_TYPES = {"3D_ELEMENT"}
SOURCE_TYPES = {"VOICEOVER", "FOOTAGE", "IMAGE", "SOUNDFONT"}
SOURCE_PRODUCERS = {"FLUIDSYNTH", "PROCEDURAL_MUSIC", "CUSTOM_MUSIC"}

_VERSION_RE = re.compile(r"^v(\d+)$")


def _version_number(version: str) -> int:
    m = _VERSION_RE.match(str(version))
    return int(m.group(1)) if m else 0


class ProductionManifest:
    """PRODUCTION_MANIFEST 的 JSON 持久化实现。"""

    def __init__(self, project_dir: str | Path, filename: str = MANIFEST_FILENAME):
        self.root = Path(project_dir)
        self.path = self.root / filename
        self.data = self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if not self.path.is_file():
            now = now_iso()
            return {
                "schema": "PRODUCTION_MANIFEST",
                "schema_version": "1.0",
                "project_id": self.root.name,
                "requests": {},
                "assets": {},
                "created_at": now,
                "updated_at": now,
            }
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"PRODUCTION_MANIFEST 损坏/不可读 {self.path}: {exc}") from exc
        if not isinstance(raw, dict) or "requests" not in raw:
            raise ValueError(f"PRODUCTION_MANIFEST 结构非法 {self.path}")
        raw.setdefault("assets", {})
        raw.setdefault("schema_version", "1.0")
        return raw

    def _persist(self) -> None:
        self.data["updated_at"] = now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # 请求 CRUD
    # ------------------------------------------------------------------

    def add(self, request: dict) -> dict:
        """登记新 Production Request；request_id 已存在则拒绝（不静默覆盖）。"""
        if not isinstance(request, dict):
            raise ValueError("add() 需要 ProductionRequest dict")
        rid = request.get("request_id")
        if not REQUEST_ID_RE.match(str(rid)):
            raise ValueError(f"request_id 必须匹配 PR-###，得到 {rid!r}")
        if rid in self.data["requests"]:
            raise ValueError(f"request {rid} 已存在，请用 update() 修改")
        req = deepcopy(request)
        req["status"] = str(req.get("status") or "PLANNED").upper()
        if req["status"] not in PRODUCTION_STATUSES:
            raise ValueError(f"未知 production status={req['status']!r}")
        req.setdefault("version", "v1")
        req.setdefault("dirty", False)
        now = now_iso()
        req.setdefault("created_at", now)
        req.setdefault("updated_at", now)
        self._refresh_spec_hash(req)
        self._refresh_dep_versions(req)
        self.data["requests"][rid] = req
        self._persist()
        return deepcopy(req)

    def update(self, request_id: str, **changes) -> dict:
        """按字段更新请求。状态迁移受 §76 状态机约束；spec 变化自动重算 spec_hash。"""
        req = self.data["requests"].get(request_id)
        if req is None:
            raise KeyError(f"request {request_id} 不存在")
        if "request_id" in changes:
            raise ValueError("request_id 不可修改")
        if "status" in changes:
            new = str(changes["status"]).upper()
            if new not in PRODUCTION_STATUSES:
                raise ValueError(f"未知 production status={new!r}")
            old = req.get("status")
            if old in PRODUCTION_STATUSES and not can_transition(old, new):
                raise ValueError(
                    f"非法状态迁移 {old} → {new}（§76）；可从 {old} 到 "
                    f"{sorted(_ANY_FROM_REPR(old))} 或 REVISION_REQUESTED/FAILED/BLOCKED"
                )
            changes["status"] = new
        for key, value in changes.items():
            req[key] = value
        self._refresh_spec_hash(req)
        self._refresh_dep_versions(req)
        req["updated_at"] = now_iso()
        self._persist()
        return deepcopy(req)

    def get(self, request_id: str) -> Optional[dict]:
        """返回请求副本（修改不影响持久化数据；改完用 update 落盘）。"""
        req = self.data["requests"].get(request_id)
        return deepcopy(req) if req is not None else None

    # ------------------------------------------------------------------
    # 增量生产（§77-79）
    # ------------------------------------------------------------------

    def mark_dirty(self, request_id: str) -> dict:
        """标记请求待重建（§77 dirty detection）。"""
        req = self.data["requests"].get(request_id)
        if req is None:
            raise KeyError(f"request {request_id} 不存在")
        req["dirty"] = True
        req["updated_at"] = now_iso()
        self._persist()
        return deepcopy(req)

    def rebuild_needed(self, request_id: str) -> bool:
        """§77-79：需要重建 ⇐ 显式 dirty、spec hash 漂移（外部改动）、
        依赖资产版本变化、或最后一次产出与当前 spec 不匹配。"""
        req = self.get(request_id)
        if req is None:
            return False
        if req.get("dirty") is True:
            return True
        # spec hash 漂移：当前内容 hash ≠ 记录的 spec_hash（未经 update() 的外部改动）
        if req.get("spec_hash") is not None \
                and spec_hash(spec_content(req)) != req["spec_hash"]:
            return True
        # 依赖资产版本变化（§78）
        stored_deps = req.get("_dep_versions") or {}
        if self._compute_dep_versions(req) != stored_deps:
            return True
        # 最后一次产出的 asset 不是当前 spec 产出的
        asset_id = self._asset_id_for_request(request_id, None)
        if asset_id is not None:
            rec = self.data["assets"].get(asset_id)
            if rec and rec["versions"] and rec["versions"][-1].get("spec_hash") \
                    and rec["versions"][-1]["spec_hash"] != req["spec_hash"]:
                return True
        return False

    # ------------------------------------------------------------------
    # 资产版本（§71）
    # ------------------------------------------------------------------

    def register_asset(
        self,
        request_id: str,
        asset_meta: dict,
        asset_id: Optional[str] = None,
    ) -> dict:
        """登记/更新资产版本。

        - 同一 (request_id, slot) 再次调用 → 同一 asset_id，version 递增（v1/v2/v3，
          已有版本不覆盖，仅追加）。
        - `slot` 用于同一请求需要多个不同资产（如 motion + music）。
        - `asset_id` 可显式指定（A###）；与已有记录冲突则报错。
        - 命名约定：`{asset_id}_{version}.{ext}`（如 A018_v1.mov）。
        """
        if not REQUEST_ID_RE.match(str(request_id)):
            raise ValueError(f"request_id 必须匹配 PR-###，得到 {request_id!r}")
        if request_id not in self.data["requests"]:
            raise ValueError(f"request {request_id} 未登记，先 add() 再 register_asset")
        meta = dict(asset_meta or {})
        slot = meta.get("slot")

        if asset_id is not None:
            if not ASSET_ID_RE.match(str(asset_id)):
                raise ValueError(f"asset_id 必须匹配 A###，得到 {asset_id!r}")
            rec = self.data["assets"].get(asset_id)
            if rec is not None and rec["request_id"] != request_id:
                raise ValueError(
                    f"asset {asset_id} 已属于 {rec['request_id']}，不能挂到 {request_id}"
                )
        else:
            asset_id = self._asset_id_for_request(request_id, slot)
            if asset_id is None:
                asset_id = self._next_asset_id()

        rec = self.data["assets"].get(asset_id)
        if rec is None:
            rec = {
                "asset_id": asset_id,
                "request_id": request_id,
                "slot": slot,
                "versions": [],
            }
            self.data["assets"][asset_id] = rec
        elif rec["request_id"] != request_id or rec.get("slot") != slot:
            raise ValueError(
                f"asset {asset_id} 键位 (request={rec['request_id']}, "
                f"slot={rec.get('slot')}) 与 (request={request_id}, slot={slot}) 冲突"
            )

        version = f"v{len(rec['versions']) + 1}"
        ext = str(meta.get("format") or "mov").lstrip(".")
        req_spec_hash = self.data["requests"].get(request_id, {}).get("spec_hash")
        entry = {
            "asset_id": asset_id,
            "request_id": request_id,
            "version": version,
            "local_path": f"{asset_id}_{version}.{ext}",
            "created_at": now_iso(),
            # §77-79：记录本次产出对应的 spec hash（rebuild_needed 以此为基线比对）。
            "spec_hash": req_spec_hash,
        }
        for key, value in meta.items():
            if key not in ("asset_id", "slot", "request_id"):
                entry[key] = value
        # asset.schema Phase-5 增补字段对齐：editability 缺省继承请求 editability_policy；
        # registry_resources 缺省继承请求 selected_resources（§22 全链可追溯）。
        if "editability" not in entry:
            req = self.data["requests"].get(request_id) or {}
            if req.get("editability_policy"):
                entry["editability"] = req["editability_policy"]
        if "registry_resources" not in entry:
            req = self.data["requests"].get(request_id) or {}
            if req.get("selected_resources"):
                entry["registry_resources"] = list(req["selected_resources"])
        rec["versions"].append(entry)
        self._persist()
        return deepcopy(entry)

    def current_version(self, asset_id: str) -> Optional[str]:
        """§71：资产当前（最新）版本，如 'v2'；不存在 → None。"""
        rec = self.data["assets"].get(asset_id)
        if not rec or not rec["versions"]:
            return None
        return rec["versions"][-1]["version"]

    def list_assets(self) -> list:
        """列出各资产当前版本条目（含 asset_id/request_id/version/local_path + 元数据）。"""
        out = []
        for asset_id in sorted(self.data["assets"]):
            rec = self.data["assets"][asset_id]
            if not rec["versions"]:
                continue
            out.append(deepcopy(rec["versions"][-1]))
        return out

    # ------------------------------------------------------------------
    # ASSET_PACKAGE_MANIFEST（§114）
    # ------------------------------------------------------------------

    def export_package(self) -> dict:
        """§114/§105/§132：导出资产包清单（motion/three_d/music/sfx/ambience/sources/
        previews/licenses/versions/timeline_hints + Phase-6 §105 新增：
        generative_video_assets/real_footage_assets/proxies/source_files/
        prompt_packets/provenance_entries/license_summary）。

        全确定性（按 asset_id+version 排序）；Phase-6 新增 section 全部可选，
        旧 manifest 无新字段 → 生成时给空数组（向后兼容，§105 只增不改）。
        """
        items = []
        for asset_id in sorted(self.data["assets"]):
            rec = self.data["assets"][asset_id]
            for entry in rec["versions"]:
                item = dict(entry)
                item["asset_id"] = asset_id
                item["request_id"] = rec["request_id"]
                items.append(item)
        items.sort(key=lambda i: (i["asset_id"], _version_number(i["version"])))

        motion, three_d, music, sfx, ambience, other = [], [], [], [], [], []
        for it in items:
            kind = self._kind(it)
            bucket = {"motion": motion, "three_d": three_d, "music": music,
                      "sfx": sfx, "ambience": ambience}.get(kind, other)
            bucket.append(it)

        sources = [it for it in items
                   if it.get("source")
                   or it.get("type") in SOURCE_TYPES
                   or str(it.get("producer") or "").upper() in SOURCE_PRODUCERS]
        previews = [it for it in items
                    if it.get("preview")
                    or ("_preview" in str(it.get("local_path") or ""))]

        licenses = self._collect_licenses(items)
        versions = {aid: self.current_version(aid)
                    for aid in sorted(self.data["assets"])
                    if self.data["assets"][aid]["versions"]}
        hints = []
        for it in items:
            hint = it.get("timeline_hint")
            if isinstance(hint, dict) or it.get("timeline_start") is not None:
                hints.append({
                    "asset_id": it["asset_id"],
                    "request_id": it["request_id"],
                    "version": it["version"],
                    "hint": hint if isinstance(hint, dict) else {
                        "timeline_start": it.get("timeline_start"),
                        "duration": it.get("duration"),
                        "timeline_usage": it.get("timeline_usage"),
                    },
                })

        return {
            "schema": "ASSET_PACKAGE_MANIFEST",
            "schema_version": "1.0",
            "project_id": self.data.get("project_id"),
            "generated_at": now_iso(),
            "motion_assets": motion,
            "three_d_assets": three_d,
            "music": music,
            "sfx": sfx,
            "ambience": ambience,
            "sources": sources,
            "previews": previews,
            "licenses": licenses,
            "versions": versions,
            "timeline_hints": hints,
            # —— Phase-6 §105/§132 新增 section（全部可选，缺省空数组）——
            "generative_video_assets": self._package_generative_video(items),
            "real_footage_assets": self._package_real_footage(items),
            "proxies": self._package_proxies(items),
            "source_files": self._package_source_files(items),
            "prompt_packets": self._package_prompt_packets(items),
            "provenance_entries": self._package_provenance_entries(items),
            "license_summary": self._package_license_summary(items),
        }

    # ------------------------------------------------------------------
    # Phase-6 §105/§132 新增 section 生成（确定性分类，只增不改）
    # ------------------------------------------------------------------

    @staticmethod
    def _phase6_origin(item: dict) -> str:
        """§98 origin：GENERATED / REAL_FOOTAGE / USER_PROVIDED（缺省 ''）。"""
        o = str(item.get("origin") or "").upper()
        if o in ("GENERATED", "REAL_FOOTAGE", "USER_PROVIDED"):
            return o
        st = str(item.get("source_type") or "").upper()
        if st in ("API_GENERATED", "WEB_GENERATED", "EXTERNAL_TOOL"):
            return "GENERATED"
        if st == "FOOTAGE_DOWNLOAD":
            return "REAL_FOOTAGE"
        if st == "USER_UPLOAD":
            return "USER_PROVIDED"
        return ""

    def _package_generative_video(self, items: list) -> list:
        """§105 Generative Video Assets：type=GENERATIVE_VIDEO 或 origin=GENERATED
        （或 source_type 属 API/WEB/EXTERNAL_TOOL 生成方式）。"""
        out = [it for it in items
               if str(it.get("type") or "").upper() == "GENERATIVE_VIDEO"
               or self._phase6_origin(it) == "GENERATED"]
        out.sort(key=lambda i: (i["asset_id"], _version_number(i["version"])))
        return out

    def _package_real_footage(self, items: list) -> list:
        """§105 Real Footage Assets：origin=REAL_FOOTAGE 或 source_type=FOOTAGE_DOWNLOAD。"""
        out = [it for it in items
               if self._phase6_origin(it) == "REAL_FOOTAGE"
               or str(it.get("source_type") or "").upper() == "FOOTAGE_DOWNLOAD"]
        out.sort(key=lambda i: (i["asset_id"], _version_number(i["version"])))
        return out

    def _package_proxies(self, items: list) -> list:
        """§105/§46 Proxies：含 proxy_path / preview 或 local_path 含 _proxy。"""
        out = [it for it in items
               if it.get("proxy_path")
               or it.get("preview")
               or "_proxy" in str(it.get("local_path") or "")]
        out.sort(key=lambda i: (i["asset_id"], _version_number(i["version"])))
        return out

    def _package_source_files(self, items: list) -> list:
        """§105/§47 Source Files：含 original_path（原始文件始终保留）。"""
        out = [it for it in items if it.get("original_path")]
        out.sort(key=lambda i: (i["asset_id"], _version_number(i["version"])))
        return out

    def _package_prompt_packets(self, items: list) -> list:
        """§105/§132 Prompt Packets：引用到的 GV-### 生产包（去重，含引用资产列表）。"""
        by_pid: dict = {}
        for it in items:
            pid = it.get("prompt_packet_id")
            if not pid:
                continue
            rec = by_pid.setdefault(str(pid), {"prompt_packet_id": str(pid),
                                               "assets": []})
            ref = f"{it['asset_id']}_{it['version']}"
            if ref not in rec["assets"]:
                rec["assets"].append(ref)
        out = list(by_pid.values())
        out.sort(key=lambda r: r["prompt_packet_id"])
        return out

    def _package_provenance_entries(self, items: list) -> list:
        """§105/§132 Provenance：asset.provenance_ref（PV-###）回链汇总（去重）。"""
        by_pv: dict = {}
        for it in items:
            pv = it.get("provenance_ref")
            if not pv:
                continue
            rec = by_pv.setdefault(str(pv), {"provenance_ref": str(pv),
                                             "assets": []})
            ref = f"{it['asset_id']}_{it['version']}"
            if ref not in rec["assets"]:
                rec["assets"].append(ref)
        out = list(by_pv.values())
        out.sort(key=lambda r: r["provenance_ref"])
        return out

    def _package_license_summary(self, items: list) -> list:
        """§105/§132 License Summary：按 license 汇总（数量 + 商用标志 + 引用资产）。

        与既有 `licenses`（逐条 license 记录）互补：这里给每个 license 的
        聚合统计（count / commercial_use / attribution_required / assets）。
        """
        by_key: dict = {}
        for it in items:
            lic = it.get("license")
            url = it.get("license_url")
            key = f"{lic}|{url}"
            rec = by_key.setdefault(key, {
                "license": lic,
                "license_url": url,
                "count": 0,
                "commercial_use": bool(it.get("commercial_use")),
                "attribution_required": bool(it.get("attribution_required")),
                "assets": [],
            })
            rec["count"] += 1
            ref = f"{it['asset_id']}_{it['version']}"
            if ref not in rec["assets"]:
                rec["assets"].append(ref)
            if it.get("commercial_use"):
                rec["commercial_use"] = True
            if it.get("attribution_required"):
                rec["attribution_required"] = True
        out = list(by_key.values())
        out.sort(key=lambda r: str(r["license"] or "") + "|" + str(r["license_url"] or ""))
        return out

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _kind(self, item: dict) -> str:
        atype = str(item.get("type") or item.get("asset_type") or "").upper()
        producer = str(item.get("producer") or "").upper()
        if atype == "MUSIC":
            return "music"
        if atype == "SFX":
            return "sfx"
        if atype == "AMBIENCE":
            return "ambience"
        if atype in THREE_D_ASSET_TYPES or producer == "THREE_D":
            return "three_d"
        if atype in MOTION_ASSET_TYPES or producer == "REMOTION":
            return "motion"
        return "sources"

    def _collect_licenses(self, items: list) -> list:
        by_key = {}
        for it in items:
            lic = it.get("license")
            url = it.get("license_url")
            key = f"{lic}|{url}"
            rec = by_key.setdefault(key, {
                "license": lic, "license_url": url,
                "attribution_required": it.get("attribution_required"),
                "assets": [],
            })
            rec["assets"].append(f"{it['asset_id']}_{it['version']}")
        out = list(by_key.values())
        out.sort(key=lambda r: str(r["license"] or "") + "|" + str(r["license_url"] or ""))
        return out

    def _asset_id_for_request(self, request_id: str, slot) -> Optional[str]:
        for aid in sorted(self.data["assets"]):
            rec = self.data["assets"][aid]
            if rec["request_id"] == request_id and rec.get("slot") == slot:
                return aid
        return None

    def _next_asset_id(self) -> str:
        used = set()
        for a in self.data["assets"]:
            mm = re.match(r"^A(\d{3})$", a)
            if mm is not None:
                used.add(int(mm.group(1)))
        n = 1
        while n in used:
            n += 1
        return f"A{n:03d}"

    def _iter_dep_refs(self, req: dict):
        deps = req.get("dependencies") or []
        if isinstance(deps, list):
            for d in deps:
                if isinstance(d, str):
                    yield d
                elif isinstance(d, dict):
                    t = d.get("target_id") or d.get("request_id")
                    if t:
                        yield str(t)
        elif isinstance(deps, dict):
            for v in deps.values():
                if isinstance(v, list):
                    for t in v:
                        if isinstance(t, str):
                            yield t
                elif isinstance(v, str):
                    yield v

    def _refresh_spec_hash(self, req: dict) -> None:
        """§79：spec = 设计引用 + 资源引用 + 参数 + 版本（spec_content，排除运行态字段）。"""
        content = spec_content(req)
        req["spec_hash"] = spec_hash(content) if content else None

    def _refresh_dep_versions(self, req: dict) -> None:
        if req.get("dependencies"):
            req["_dep_versions"] = self._compute_dep_versions(req)
        else:
            req["_dep_versions"] = {}

    def _compute_dep_versions(self, req: dict) -> dict:
        """依赖资产版本快照：{PR-### 或 A###: 当前版本}，用于 §78 依赖变化检测。"""
        snap = {}
        for ref in self._iter_dep_refs(req):
            if ASSET_ID_RE.match(ref):
                snap[ref] = self.current_version(ref)
            elif REQUEST_ID_RE.match(ref):
                aid = self._asset_id_for_request(ref, None)
                snap[ref] = self.current_version(aid) if aid else None
        return snap


# §76 状态机校验的提示辅助（update 报错信息用）
def _ANY_FROM_REPR(status: str):
    from .planner import _EXPLICIT_TRANSITIONS  # noqa: PLC0415

    return _EXPLICIT_TRANSITIONS.get(status, set())


# ---------------------------------------------------------------------------
# 自检（对应派工单自检脚本）
# ---------------------------------------------------------------------------

def selftest() -> None:
    import tempfile  # noqa: PLC0415

    d = tempfile.mkdtemp()
    m = ProductionManifest(d)
    req = __import__("modules.production.planner", fromlist=["create_request"]).create_request(
        request_id="PR-001", shot_id="S001", layer_id="S001-L01",
        route="REMOTION", editability="ASSET_REPLACEABLE",
    )
    m.add(req)
    a1 = m.register_asset("PR-001", {"producer": "REMOTION", "format": "mov", "alpha": True})
    a2 = m.register_asset("PR-001", {"producer": "REMOTION", "format": "mov", "alpha": True})
    assert a1["version"] == "v1" and a2["version"] == "v2"
    assert a1["asset_id"] == a2["asset_id"]
    assert m.current_version(a1["asset_id"]) == "v2"
    assert spec_hash({"a": 1}) == spec_hash({"a": 1})
    assert spec_hash({"a": 1}) != spec_hash({"a": 2})
    # schema 对齐：editability 别名 → editability_policy
    assert m.get("PR-001")["editability_policy"] == "ASSET_REPLACEABLE"
    # asset.schema 增补字段继承
    assert a1["editability"] == "ASSET_REPLACEABLE"
    # spec hash 与 spec_content 口径一致
    assert m.get("PR-001")["spec_hash"] == spec_hash(spec_content(m.get("PR-001")))
    # 产出基线：注册资产后 spec 未变 → 不需重建；spec 变化 → 需要重建
    assert m.rebuild_needed("PR-001") is False
    m.update("PR-001", purpose="changed purpose")
    assert m.rebuild_needed("PR-001") is True
    m.register_asset("PR-001", {"producer": "REMOTION", "format": "mov", "alpha": True})
    assert m.rebuild_needed("PR-001") is False
    assert m.path.is_file()
    print("manifest selftest OK")


if __name__ == "__main__":
    selftest()
