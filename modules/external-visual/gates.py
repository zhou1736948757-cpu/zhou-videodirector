#!/usr/bin/env python3
"""gates.py — Approval Gates（Phase-6 Prompt §31-32/§64/§111/§115-116；P6-06）.

Phase 6 审批门禁与执行模式层。所有需要用户批准的动作（§111 全清单）统一产出
`approval.schema.json` 形状的审批记录（AP-###，§Approval System）：

- §31 cost_gate              付费生成（六要素齐全才可提交）
- §32 privacy_gate           隐私上传（先识别上传内容 + provider + 目的 → 请求批准；
                               引擎侧硬规则：无批准记录时任何 upload 动作必须 BLOCKED）
- §64 paid_stock_gate        付费素材购买
- §111 large_download_gate   大文件下载（阈值判定）
- §78-79 route_change_gate   路由变更（只提案，状态机不允许直接改 routing 文件）
- §111 prompt_strategy_change_gate  重大 prompt 策略变更
- §111 character_ref_upload_gate    角色参考图上传（隐私类）
- §115-116 automation_level  MANUAL / ASSISTED / AUTOMATED 三档判定（默认绝不假设 AUTOMATED）

审批记录落盘：`append_approval(project_dir, record)` 追加到项目 `approvals.yaml` 的
`approvals:` 列表（docs/approval-system.md §F；append-only，不删除历史）。

技术约束：**Python3 stdlib only**；无 LLM；无联网；确定性。YAML 写出用 stdlib 手写
emitter（对齐 scripts/registry.py 可解析的 YAML 子集）。
代码风格照抄 modules/production/planner.py（中文 docstring 带 §出处、常量表、selftest）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 常量（§111/§115-116；P6-01 契约）
# ---------------------------------------------------------------------------

#: require_approval 允许的 gate scope（§111 全清单）
GATE_SCOPES = (
    "cost", "privacy", "paid_stock", "large_download", "route_change",
    "prompt_strategy_change", "character_ref_upload",
)

APPROVAL_STATUSES = ("pending", "approved", "rejected", "revision_requested", "superseded")

#: 审批记录 source_stage 枚举（approval.schema.json / state-machine：资产获取 / 生产）
SOURCE_STAGES = ("ASSET_ACQUISITION", "ASSET_PRODUCTION")

#: 自动化三档（§115）
AUTOMATION_LEVELS = ("MANUAL", "ASSISTED", "AUTOMATED")
_AUTOMATION_RANK = {"MANUAL": 0, "ASSISTED": 1, "AUTOMATED": 2}

_AP_ID_RE = re.compile(r"^AP-(\d{3})$")


class UploadBlockedError(RuntimeError):
    """隐私门禁硬规则（§32）：无批准记录时的上传动作必须抛 BLOCKED。"""


def now_iso() -> str:
    """UTC ISO 8601 时间戳（秒精度，用于记录 created_at）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# AP-### 审批记录生成
# ---------------------------------------------------------------------------

def _collect_ap_numbers(text: str) -> set:
    """从文本中收集全部 AP-### 编号（正则；确定性；多行文本用 \b 边界而非 ^$）。"""
    return {int(m) for m in re.findall(r"\bAP-(\d{3})\b", text)}


def next_approval_id(project_dir: Optional[str | Path] = None,
                     filename: str = "approvals.yaml",
                     existing: Optional[list] = None) -> str:
    """下一个 AP-###（全局递增，永不复用；approval-system.md §E）。

    编号来源：existing 记录（优先）+ 项目 approvals.yaml 文本；取 max+1。
    无任何记录 → AP-001。
    """
    nums: set = set()
    if isinstance(existing, list):
        for r in existing:
            if isinstance(r, dict) and r.get("approval_id"):
                m = _AP_ID_RE.match(str(r["approval_id"]))
                if m:
                    nums.add(int(m.group(1)))
    if project_dir is not None:
        p = Path(project_dir) / filename
        if p.is_file():
            try:
                nums |= _collect_ap_numbers(p.read_text(encoding="utf-8"))
            except OSError:  # pragma: no cover
                pass
    return f"AP-{max(nums) + 1 if nums else 1:03d}"


def require_approval(gate: str, context: dict) -> dict:
    """§111/§Approval System：生成一条审批记录（approval.schema.json 形状）。

    `gate` ∈ GATE_SCOPES；`context` 需含 `summary`（decision.summary 必需字段），
    可选：details / target{type,id} / user_feedback / source_stage /
    approval_id / created_at。返回 status=pending 的 AP-### 记录。
    """
    gate = str(gate).strip()
    if gate not in GATE_SCOPES:
        raise ValueError(f"未知 gate={gate!r}；允许 {sorted(GATE_SCOPES)}")
    if not isinstance(context, dict):
        raise ValueError("require_approval 的 context 必须是 dict")
    summary = context.get("summary")
    if not summary or not str(summary).strip():
        raise ValueError("require_approval 需要 context.summary（decision.summary 为必需字段）")

    target = context.get("target")
    if not isinstance(target, dict) or not target.get("type") or not target.get("id"):
        raise ValueError("require_approval 需要 context.target{type, id}（approval.schema 必需）")
    source_stage = str(context.get("source_stage") or "ASSET_ACQUISITION")
    if source_stage not in SOURCE_STAGES:
        raise ValueError(f"source_stage 必须是 {SOURCE_STAGES} 之一，得到 {source_stage!r}")

    record: dict = {
        "approval_id": context.get("approval_id") or next_approval_id(
            context.get("project_dir"), context.get("filename", "approvals.yaml")),
        "scope": gate,
        "target": {
            "type": str(target.get("type")),
            "id": str(target.get("id")),
        },
        "status": "pending",
        "decision": {"summary": str(summary)},
        "user_feedback": [str(f) for f in (context.get("user_feedback") or [])],
        "created_at": context.get("created_at") or now_iso(),
        "supersedes": [],
        "source_stage": source_stage,
    }
    if context.get("details"):
        record["decision"]["details"] = str(context["details"])
    return record


# ---------------------------------------------------------------------------
# 审批记录落盘（approvals.yaml 追加；append-only）
# ---------------------------------------------------------------------------

def _yaml_scalar(value: Any) -> str:
    """YAML 标量渲染（子集）：字符串按需加引号，其余原样。"""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    needs_quote = (
        s == "" or s != s.strip()
        or any(c in s for c in (":", "#", "[", "]", "{", "}", ","))
        or s[0] in "'\"-?&*!|>%@`"
    )
    if needs_quote:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _emit_mapping(mapping: dict, indent: int, first_prefix: str, out: list) -> None:
    """递归渲染 mapping（YAML 子集，2 空格缩进；first_prefix 为 '' 或 '- '）。"""
    n = len(first_prefix)
    for i, (k, v) in enumerate(mapping.items()):
        pre = first_prefix if i == 0 else " " * n
        head = f"{' ' * indent}{pre}{k}:"
        if isinstance(v, dict):
            out.append(head)
            _emit_mapping(v, indent + n + 2, "", out)
        elif isinstance(v, list):
            if not v:
                out.append(f"{head} []")
            else:
                out.append(head)
                _emit_list(v, indent + n + 2, out)
        else:
            out.append(f"{head} {_yaml_scalar(v)}")


def _emit_list(items: list, indent: int, out: list) -> None:
    for it in items:
        if isinstance(it, dict):
            _emit_mapping(it, indent, "- ", out)
        else:
            out.append(f"{' ' * indent}- {_yaml_scalar(it)}")


def _record_block_lines(record: dict) -> list:
    """审批记录 → approvals 列表项行（首行 '  - approval_id: …'，2 空格缩进）。"""
    out: list = []
    _emit_mapping(record, 2, "- ", out)
    return out


def _insert_approval_entry(text: str, entry_lines: list) -> str:
    """把审批记录列表项插入现有 approvals.yaml 的顶层 approvals: 列表（追加）。"""
    lines = text.split("\n")
    idxs = [i for i, l in enumerate(lines)
            if l and not l[0].isspace() and l.lstrip().startswith("approvals:")]
    if idxs:
        insert_at = len(lines)
        for i in range(idxs[-1] + 1, len(lines)):
            if lines[i] and not lines[i][0].isspace():
                insert_at = i
                break
        lines[insert_at:insert_at] = entry_lines
    else:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("approvals:")
        lines.extend(entry_lines)
    body = "\n".join(lines).rstrip("\n") + "\n"
    return body


def append_approval(project_dir, record: dict,
                    filename: str = "approvals.yaml") -> Path:
    """把审批记录追加到 <project>/approvals.yaml 的 approvals: 列表（§20/§F）。

    追加方式，不删除历史审批；被替代的记录由调用方显式写 supersedes（§E 规则 2）。
    AP-### 全局递增、永不复用（§E 规则 1）：若传入记录 id 与文件内已有 id 冲突，
    自动重分配为 next_approval_id（确定性）。
    """
    path = Path(project_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(record)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        existing = _collect_ap_numbers(text)
        m = _AP_ID_RE.match(str(entry.get("approval_id") or ""))
        if m and int(m.group(1)) in existing:
            entry["approval_id"] = next_approval_id(project_dir, filename)
        path.write_text(_insert_approval_entry(text, _record_block_lines(entry)),
                        encoding="utf-8")
    else:
        head = [
            "# approvals.yaml — 机器可读审批当前态（P6-06 gate 追加）",
            "# 结构：project / scenes / shots / assets 索引 + approvals 历史列表（AP-###，永久保留）",
            "project: {}",
            "scenes: {}",
            "shots: {}",
            "assets: {}",
            "approvals:",
        ]
        path.write_text("\n".join(head) + "\n" + "\n".join(_record_block_lines(entry)) + "\n",
                        encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# §31 付费生成 Cost Gate
# ---------------------------------------------------------------------------

def cost_gate(
    provider: str, model: str, variants: int, approx_cost: Any, resolution: str,
    duration: float, why: str, *,
    target: Optional[dict] = None, approval_id: Optional[str] = None,
    created_at: Optional[str] = None, project_dir: Optional[str | Path] = None,
) -> dict:
    """§31 付费生成 Gate：六要素齐全才可提交，产出 {approval_required:true, summary…}。

    六要素：Provider / Model / Number of variants / Approximate cost / Resolution /
    Duration / Why（§31）。任一缺失 → ValueError（禁止不完整提交）。
    """
    elements = {
        "provider": provider, "model": model, "variants": variants,
        "approx_cost": approx_cost, "resolution": resolution,
        "duration": duration, "why": why,
    }
    missing = [k for k, v in elements.items()
               if v is None or (isinstance(v, str) and not v.strip())]
    if missing:
        raise ValueError(f"cost_gate 六要素不齐全，缺少: {missing}（§31：六要素齐全才可提交）")

    summary = (
        f"Paid AI video generation（§31）：provider={provider}, model={model}, "
        f"variants={variants}, approx_cost={approx_cost}, resolution={resolution}, "
        f"duration={duration}s. why={why}。六要素齐全，等待批准。"
    )
    rec_target = target or {"type": "generation", "id": str(provider)}
    record = require_approval("cost", {
        "summary": summary,
        "details": "cost_gate 六要素摘要",
        "target": rec_target,
        "approval_id": approval_id,
        "created_at": created_at,
        "project_dir": project_dir,
        "source_stage": "ASSET_ACQUISITION",
    })
    return {
        "gate": "cost",
        "approval_required": True,
        **elements,
        "summary": summary,
        "record": record,
    }


# ---------------------------------------------------------------------------
# §32 隐私上传 Privacy Gate（硬规则：绝不自动上传）
# ---------------------------------------------------------------------------

def privacy_gate(
    upload_items, provider: str, purpose: str, *,
    target: Optional[dict] = None, approval_id: Optional[str] = None,
    created_at: Optional[str] = None, project_dir: Optional[str | Path] = None,
) -> dict:
    """§32 隐私上传 Gate：先识别上传内容 + provider + 目的 → 请求批准。

    返回 {approval_required:true, upload_identified[], provider, purpose, record}。
    硬规则（§32）：无批准记录时，任何 upload 动作函数必须 BLOCKED——
    本 gate 只产出 pending 记录；执行侧用 assert_upload_allowed 拦截。
    """
    if isinstance(upload_items, str):
        items = [upload_items]
    elif isinstance(upload_items, (list, tuple)):
        items = [str(i) for i in upload_items]
    else:
        items = []
    if not items:
        raise ValueError("privacy_gate 需要 upload_items（要上传的内容清单）")
    if not provider or not str(provider).strip():
        raise ValueError("privacy_gate 需要 provider")
    if not purpose or not str(purpose).strip():
        raise ValueError("privacy_gate 需要 purpose（上传目的）")

    summary = (
        f"Upload private/user media（§32）：将上传 {items} 到 provider={provider}，"
        f"目的={purpose}。先识别后批准；未经批准绝不自动上传。"
    )
    rec_target = target or {"type": "upload", "id": str(provider)}
    record = require_approval("privacy", {
        "summary": summary,
        "details": f"upload_identified={items}",
        "target": rec_target,
        "approval_id": approval_id,
        "created_at": created_at,
        "project_dir": project_dir,
        "source_stage": "ASSET_ACQUISITION",
    })
    return {
        "gate": "privacy",
        "approval_required": True,
        "upload_identified": items,
        "provider": provider,
        "purpose": purpose,
        "summary": summary,
        "record": record,
        "hard_rule": "无批准记录时任何 upload 动作必须 BLOCKED（§32）",
    }


def upload_allowed(records, *, scope: str = "privacy",
                   target_type: Optional[str] = None,
                   target_id: Optional[str] = None) -> bool:
    """检查是否存在匹配的 approved 审批记录（§32 硬规则）。

    `records` 为审批记录列表（status 含 approved）；匹配 scope 与
    target{type,id}（target_type/id 缺省时仅按 scope + id 匹配）。
    """
    if not isinstance(records, list):
        return False
    for r in records:
        if not isinstance(r, dict) or r.get("status") != "approved":
            continue
        if r.get("scope") != scope:
            continue
        t = r.get("target")
        if not isinstance(t, dict):
            continue
        if target_id is not None and t.get("id") != target_id:
            continue
        if target_type is not None and t.get("type") != target_type:
            continue
        return True
    return False


def assert_upload_allowed(records, *, scope: str = "privacy",
                          target_type: Optional[str] = None,
                          target_id: Optional[str] = None) -> None:
    """§32 硬规则：无批准记录 → 抛 UploadBlockedError（BLOCKED）。

    任何"上传动作"函数在真正上传前必须调用本函数；不满足即抛异常，绝不自动上传。
    """
    if not upload_allowed(records, scope=scope, target_type=target_type,
                          target_id=target_id):
        raise UploadBlockedError(
            f"privacy gate BLOCKED（§32）：无匹配的 approved 审批记录 "
            f"(scope={scope}, target_type={target_type}, target_id={target_id})，"
            f"禁止任何上传动作。"
        )


# ---------------------------------------------------------------------------
# §64 付费素材 Paid Stock Gate
# ---------------------------------------------------------------------------

def paid_stock_gate(candidate: dict, *,
                    approval_id: Optional[str] = None,
                    created_at: Optional[str] = None,
                    project_dir: Optional[str | Path] = None) -> dict:
    """§64 Paid Stock Gate：识别付费资源 → 等待用户决定。

    candidate 需含：title / source / price / license_type / why_recommended /
    free_alternatives（免费替代，可为空列表）。
    """
    if not isinstance(candidate, dict):
        raise ValueError("paid_stock_gate 需要 candidate dict")
    need = ("title", "source", "price", "license_type", "why_recommended")
    missing = [k for k in need if not str(candidate.get(k) or "").strip()]
    if missing:
        raise ValueError(f"paid_stock_gate 缺少候选字段: {missing}（§64）")
    free_alt = candidate.get("free_alternatives") or []
    if not isinstance(free_alt, list):
        free_alt = [free_alt]

    summary = (
        f"Paid stock purchase（§64）：title={candidate['title']}, source={candidate['source']}, "
        f"price={candidate.get('price')}, license_type={candidate.get('license_type')}, "
        f"why_recommended={candidate.get('why_recommended')}, "
        f"free_alternatives={free_alt}。等待用户决定是否购买。"
    )
    record = require_approval("paid_stock", {
        "summary": summary,
        "target": {"type": "asset", "id": str(candidate.get("title") or candidate.get("source"))},
        "approval_id": approval_id,
        "created_at": created_at,
        "project_dir": project_dir,
        "source_stage": "ASSET_ACQUISITION",
    })
    return {
        "gate": "paid_stock",
        "approval_required": True,
        "title": candidate["title"],
        "source": candidate["source"],
        "price": candidate.get("price"),
        "license_type": candidate.get("license_type"),
        "why_recommended": candidate.get("why_recommended"),
        "free_alternatives": free_alt,
        "summary": summary,
        "record": record,
    }


# ---------------------------------------------------------------------------
# §111 大下载 / 路由变更 / prompt 策略变更 / 角色参考上传
# ---------------------------------------------------------------------------

def large_download_gate(candidate: dict, threshold_mb: float, *,
                        approval_id: Optional[str] = None,
                        created_at: Optional[str] = None,
                        project_dir: Optional[str | Path] = None) -> dict:
    """§111/§65 Large Footage Download Gate：超过阈值 → 需批准（预览先行）。

    candidate：{title, source, size_mb|size_bytes, license, purpose}。
    size ≤ threshold → approval_required=false（低风险，可放行）；否则 true。
    """
    if not isinstance(candidate, dict):
        raise ValueError("large_download_gate 需要 candidate dict")
    size = candidate.get("size_mb")
    if size is None and candidate.get("size_bytes") is not None:
        size = float(candidate["size_bytes"]) / (1024 * 1024)
    try:
        size_mb = float(size)
    except (TypeError, ValueError):
        raise ValueError("large_download_gate 需要 candidate.size_mb 或 size_bytes")
    threshold = float(threshold_mb)
    if threshold <= 0:
        raise ValueError("threshold_mb 必须 > 0")
    exceeded = size_mb > threshold

    summary = (
        f"Large footage download（§111）：title={candidate.get('title')}, "
        f"source={candidate.get('source')}, size={size_mb:.1f}MB "
        f"(threshold={threshold:.0f}MB), license={candidate.get('license')}, "
        f"purpose={candidate.get('purpose')}。{'超过阈值，需批准（预览先行，§65）' if exceeded else '未超阈值，低风险可放行'}。"
    )
    record = None
    if exceeded:
        record = require_approval("large_download", {
            "summary": summary,
            "target": {"type": "asset", "id": str(candidate.get("title") or candidate.get("source"))},
            "approval_id": approval_id,
            "created_at": created_at,
            "project_dir": project_dir,
            "source_stage": "ASSET_ACQUISITION",
        })
    return {
        "gate": "large_download",
        "approval_required": exceeded,
        "size_mb": size_mb,
        "threshold_mb": threshold,
        "size_exceeded": exceeded,
        "title": candidate.get("title"),
        "source": candidate.get("source"),
        "summary": summary,
        "record": record,
    }


def route_change_gate(proposal: dict, *,
                      approval_id: Optional[str] = None,
                      created_at: Optional[str] = None,
                      project_dir: Optional[str | Path] = None) -> dict:
    """§78-79 Route Change Gate：只提案，状态机不允许直接改 routing 文件。

    proposal：{shot_id, current_route, proposed_route, reason, evidence}。
    """
    if not isinstance(proposal, dict):
        raise ValueError("route_change_gate 需要 proposal dict")
    need = ("shot_id", "current_route", "proposed_route", "reason")
    missing = [k for k in need if not str(proposal.get(k) or "").strip()]
    if missing:
        raise ValueError(f"route_change_gate 缺少字段: {missing}（§78）")

    summary = (
        f"Route change proposal（§78-79）：shot={proposal['shot_id']} "
        f"current_route={proposal['current_route']} → proposed_route={proposal['proposed_route']}, "
        f"reason={proposal['reason']}, evidence={proposal.get('evidence')}。"
        f"只提案；状态机不允许直接修改 routing 文件。"
    )
    record = require_approval("route_change", {
        "summary": summary,
        "target": {"type": "shot", "id": str(proposal["shot_id"])},
        "approval_id": approval_id,
        "created_at": created_at,
        "project_dir": project_dir,
        "source_stage": "ASSET_PRODUCTION",
    })
    return {
        "gate": "route_change",
        "approval_required": True,
        "proposal": proposal,
        "routing_files_modified": False,
        "summary": summary,
        "record": record,
    }


def prompt_strategy_change_gate(proposal: dict, *,
                                approval_id: Optional[str] = None,
                                created_at: Optional[str] = None,
                                project_dir: Optional[str | Path] = None) -> dict:
    """§111 Major Prompt Strategy Change Gate。

    proposal：{packet_id, old_strategy, new_strategy, reason}。
    """
    if not isinstance(proposal, dict):
        raise ValueError("prompt_strategy_change_gate 需要 proposal dict")
    need = ("packet_id", "old_strategy", "new_strategy", "reason")
    missing = [k for k in need if not str(proposal.get(k) or "").strip()]
    if missing:
        raise ValueError(f"prompt_strategy_change_gate 缺少字段: {missing}（§111）")

    summary = (
        f"Major prompt strategy change（§111）：packet={proposal['packet_id']}, "
        f"old={proposal['old_strategy']} → new={proposal['new_strategy']}, "
        f"reason={proposal['reason']}。需批准后才能改 prompt 策略。"
    )
    record = require_approval("prompt_strategy_change", {
        "summary": summary,
        "target": {"type": "packet", "id": str(proposal["packet_id"])},
        "approval_id": approval_id,
        "created_at": created_at,
        "project_dir": project_dir,
        "source_stage": "ASSET_PRODUCTION",
    })
    return {
        "gate": "prompt_strategy_change",
        "approval_required": True,
        "proposal": proposal,
        "summary": summary,
        "record": record,
    }


def character_ref_upload_gate(asset_ref: str, provider: str, purpose: str, *,
                              approval_id: Optional[str] = None,
                              created_at: Optional[str] = None,
                              project_dir: Optional[str | Path] = None) -> dict:
    """§111 Character Reference Upload Gate（角色参考图上传 = 隐私类动作）。

    与 privacy_gate 同一硬规则：无批准记录不得上传（§32）。
    """
    if not asset_ref or not str(asset_ref).strip():
        raise ValueError("character_ref_upload_gate 需要 asset_ref")
    if not provider or not str(provider).strip():
        raise ValueError("character_ref_upload_gate 需要 provider")
    if not purpose or not str(purpose).strip():
        raise ValueError("character_ref_upload_gate 需要 purpose")

    summary = (
        f"Character reference upload（§111/§32）：上传角色参考 {asset_ref} 到 "
        f"provider={provider}，目的={purpose}。未经批准不得上传。"
    )
    record = require_approval("character_ref_upload", {
        "summary": summary,
        "target": {"type": "asset", "id": str(asset_ref)},
        "approval_id": approval_id,
        "created_at": created_at,
        "project_dir": project_dir,
        "source_stage": "ASSET_PRODUCTION",
    })
    return {
        "gate": "character_ref_upload",
        "approval_required": True,
        "upload_identified": [str(asset_ref)],
        "provider": provider,
        "purpose": purpose,
        "summary": summary,
        "record": record,
    }


# ---------------------------------------------------------------------------
# §115-116 自动化程度
# ---------------------------------------------------------------------------

def _provider_missing_elements(provider_id: str, cfg: dict) -> tuple:
    """单 provider 的自动化缺口 → (level, missing[], note)。确定性。"""
    configured = bool(cfg.get("configured"))
    if not configured:
        return ("MANUAL", ["provider 未配置（configured=false）"],
                f"provider={provider_id} 未配置（§116：无配置 → MANUAL）")
    authorized = bool(cfg.get("authorized"))
    cost_rules = cfg.get("cost_rules")
    cost_ok = cost_rules is True or isinstance(cost_rules, dict) and bool(cost_rules)
    missing = []
    if not authorized:
        missing.append("authorized 未授权")
    if not cost_ok:
        missing.append("cost_rules 成本规则缺失")
    if not missing:
        return ("AUTOMATED", [],
                f"provider={provider_id} 已配置 + 已授权 + 成本规则齐备（§115）")
    return "ASSISTED", missing, f"provider={provider_id} 有配置但缺 {'、'.join(missing)}"


def automation_level(project_config: Optional[dict]) -> dict:
    """§115-116：MANUAL / ASSISTED / AUTOMATED 判定。

    AUTOMATED 仅当 provider 已配置 + 已授权 + 成本规则三者齐备；缺任一 → 降级
    MANUAL/ASSISTED 并在输出注明（§116：默认绝不假设 AUTOMATED）。

    `project_config` 形态（兼容）：{"providers": {id: {configured, authorized,
    cost_rules}}, ...} 或直接 {id: {...}}。
    """
    if not isinstance(project_config, dict):
        return {
            "automation_level": "MANUAL", "provider_id": None,
            "reason": "无 project_config（§116：无配置 → MANUAL）",
            "missing": ["providers 配置"],
            "downgrade_hint": "使用 MANUAL（run_manual 人工网页生成）或先配置 provider",
        }
    raw = project_config.get("providers") if isinstance(
        project_config.get("providers"), dict) else project_config
    providers = {k: v for k, v in raw.items() if isinstance(v, dict)}
    if not providers:
        return {
            "automation_level": "MANUAL", "provider_id": None,
            "reason": "未配置任何 provider（§116：无配置 → MANUAL）",
            "missing": ["providers 配置"],
            "downgrade_hint": "使用 MANUAL（run_manual 人工网页生成）或先配置 provider",
        }

    best = "MANUAL"
    best_id: Optional[str] = None
    best_missing: list = []
    best_note = ""
    for pid, cfg in sorted(providers.items()):
        level, missing, note = _provider_missing_elements(pid, cfg)
        if _AUTOMATION_RANK[level] > _AUTOMATION_RANK[best]:
            best, best_id, best_missing, best_note = level, pid, missing, note

    hint = {
        "MANUAL": "使用 MANUAL（run_manual 人工网页生成），或先配置 provider",
        "ASSISTED": "使用 ASSISTED：ZHOU 完成 packet/search/metadata，生成/购买由用户执行（§30）",
        "AUTOMATED": "已满足 AUTOMATED 前提；实际调用仍需 api_available=true 与真实凭据（§115）",
    }[best]
    return {
        "automation_level": best,
        "provider_id": best_id,
        "reason": best_note or "无可用 provider",
        "missing": best_missing,
        "downgrade_hint": hint,
    }


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------

def _raises(fn, *args, **kwargs) -> bool:
    """辅助：fn 抛 ValueError → True（selftest 用）。"""
    try:
        fn(*args, **kwargs)
    except ValueError:
        return True
    return False


def selftest() -> None:
    checks = [
        # §31 cost_gate：六要素齐全 → approval_required=true，summary 含六要素
        (lambda: cost_gate("p", "m", 2, "$5", "1080p", 8, "needed")["approval_required"] is True),
        (lambda: "provider=p" in cost_gate("p", "m", 2, "$5", "1080p", 8, "needed")["summary"]),
        (lambda: _AP_ID_RE.match(cost_gate("p", "m", 2, "$5", "1080p", 8, "needed")["record"]["approval_id"]) is not None),
        (lambda: cost_gate("p", "m", 2, "$5", "1080p", 8, "needed")["record"]["status"] == "pending"),
        # §32 privacy_gate：upload_identified + provider + purpose + approval_required
        (lambda: privacy_gate(["user_photo.jpg"], "p", "character ref")["approval_required"] is True),
        (lambda: privacy_gate(["user_photo.jpg"], "p", "character ref")["upload_identified"] == ["user_photo.jpg"]),
        # §32 硬规则：无批准记录 → upload_allowed=False → assert 抛 BLOCKED
        (lambda: upload_allowed([], scope="privacy") is False),
        # §64 paid_stock / §111 各 gate
        (lambda: paid_stock_gate({"title": "t", "source": "s", "price": 10,
                                  "license_type": "royalty-free",
                                  "why_recommended": "w", "free_alternatives": []})["approval_required"] is True),
        (lambda: large_download_gate({"title": "t", "source": "s", "size_mb": 400,
                                      "license": "cc0", "purpose": "bg"}, 200)["approval_required"] is True),
        (lambda: large_download_gate({"title": "t", "source": "s", "size_mb": 50,
                                      "license": "cc0", "purpose": "bg"}, 200)["approval_required"] is False),
        (lambda: route_change_gate({"shot_id": "S001", "current_route": "GENERATIVE_VIDEO",
                                    "proposed_route": "REAL_FOOTAGE", "reason": "r",
                                    "evidence": "e"})["routing_files_modified"] is False),
        (lambda: prompt_strategy_change_gate({"packet_id": "GV-001", "old_strategy": "a",
                                              "new_strategy": "b", "reason": "r"})["approval_required"] is True),
        (lambda: character_ref_upload_gate("cp-char-01.png", "p", "continuity")["approval_required"] is True),
        # §115-116 automation_level 三档（AC-2）
        (lambda: automation_level(None)["automation_level"] == "MANUAL"),
        (lambda: automation_level({})["automation_level"] == "MANUAL"),
        (lambda: automation_level({"providers": {"x": {"configured": True, "authorized": False,
                                                      "cost_rules": {}}}})["automation_level"] == "ASSISTED"),
        (lambda: automation_level({"providers": {"x": {"configured": True, "authorized": True,
                                                      "cost_rules": {"max": 10}}}})["automation_level"] == "AUTOMATED"),
        # require_approval 需要 summary / target
        (lambda: _raises(require_approval, "cost", {"target": {"type": "a", "id": "b"}})),
        (lambda: _raises(require_approval, "cost", {})),
    ]
    for i, check in enumerate(checks, 1):
        try:
            ok = check()
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            raise AssertionError(f"gates selftest check #{i} failed")
    print("gates selftest OK")


if __name__ == "__main__":
    selftest()
