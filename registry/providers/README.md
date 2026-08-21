# ZHOU_Videodirector — Provider Adapter 接口规范

> 对应文件：[registry/index/providers.json](../index/providers.json)（11 个 Provider 的注册与能力矩阵）。
> 本文档只定义 **Adapter 接口契约**，不实现任何真实网络/下载代码（Phase 4 不构建网络调度系统，见总设计 v0.2 §99 语义）。实现由 Phase 5+ 完成。
> 关联：`docs/reuse-map.md`（v0.2 §68 外部参考表）、`schemas/resource.schema.json`（P4-1，L0/L1 字段）、`docs/registry.md`（P4-1，Registry 宪法）。

---

## 1. Adapter 是什么

**Provider Adapter 是 Provider 与 Registry 核心之间的薄层（thin layer）。**

Registry 核心（`scripts/registry.py`，P4-2）只认识**统一接口**，不认识任何具体 Provider：

```text
Registry 核心 (find / detail / preview / fetch)
        │  只调用统一接口
        ▼
ProviderAdapter (每个 provider 一个实现)
        │
        ▼
具体来源 (GitHub / Poly Haven API / Freesound API / npm 包 / 静态索引 ...)
```

规则：

- 核心不 import 任何 provider 专属库、不解析任何 provider 专属数据格式。
- Provider 的所有差异（URL、鉴权、解析、限流、下载方式）都封闭在 adapter 内部。
- Adapter 输出**必须归一化**（见 §3），核心只处理归一化后的结构。
- 新增 Provider = 新增一个 adapter + 注册一行，**不修改核心代码**。

---

## 2. 接口规范（Python 伪接口）

Phase 5+ 实现时的最小契约。核心只会调用这四个方法 + 读取两个元数据属性。

```python
class ProviderAdapter:
    """Provider 与 Registry 核心之间的薄层。每个 provider 一个实现。"""

    id: str                      # 必须等于 providers.json 中的 provider id（kebab-case）
    capabilities: dict           # {"search": ..., "detail": ..., "preview": ..., "fetch": ...}
                                 # 值枚举: true | false | partial | manual_or_semiautomatic | requires_authentication

    def search(self, query: dict, offline: bool) -> list[dict]:
        """返回归一化 L0 条目列表。

        query 典型键: query / type / tags / license_filter / local_only / top_k
        offline=True 时禁止发任何网络请求 -> 直接返回 [] 并在结果里标记 unavailable（见 §6）。
        单个 provider 抛异常必须被核心捕获，不影响其他 provider（见 §8）。
        """

    def detail(self, resource_id: str) -> dict:
        """返回单条资源的 L1 详情（含 license / parameters / deps / compatibility / usage / limitations）。"""

    def preview(self, resource_id: str) -> dict:
        """返回 preview ref：{"type": ..., "ref": ...}。
        type 枚举 8 种: image | gif | video | audio | waveform | external_url | generated_preview | none
        """

    def fetch(self, resource_id: str, dest: str) -> dict:
        """L2：把 payload 取到 dest。

        返回 {license_snapshot, cache_state, fetch_class, warning}，必须包含 license snapshot 落盘。
        fetch_class 枚举 4 种: LIGHTWEIGHT | MEDIUM | LARGE | EXTERNAL_INSTALL
        - LIGHTWEIGHT 可走引擎内演示路径（缓存状态机推进）。
        - MEDIUM / LARGE / EXTERNAL_INSTALL 由核心判定 approval_required=True，adapter 不得自行绕过。
        - 安全红线见 §9（path traversal / 不自动执行 / archive 白名单）。
        """
```

约定：

- `resource_id` 使用共享契约 `{provider}:{type}:{slug}`（如 `remotion-bits:REMOTION_COMPONENT:animated-text`）。
- 任何方法**不得**在内部做"大决策"（是否下载、是否商业可用）——决策权在核心的 Approval Gate 与 License 政策。
- `capabilities` 必须与 `providers.json` 中该 provider 的四项 capability 一致，不一致视为 bug。

---

## 3. 归一化要求（adapter 输出 → resource.schema.json）

任何 adapter 的输出必须映射到 `resource.schema.json` 的 **L0 / L1** 字段（Metadata First 的 Registry 版实现；对应 v0.2 §70 与 §41-43 三级加载）。

- **L0 Catalog 字段**：`id / name / type / provider / tags / summary / best_for / avoid_when / style / preview_ref / license_summary / availability`
- **L1 Detail 字段**：`description / parameters / deps / compat / tech_req / formats / resolution / size / license / commercial / attribution / limitations / usage / source_url / last_verified`

强制规则：

1. adapter 输出缺字段 → 填 `null` 或 `UNKNOWN`，**禁止编造**。
2. `license` 无法从来源确认 → `UNKNOWN` + `license_review_required: true`，**禁止猜 commercial_safe**（License 硬需求）。
3. `preview_ref` 必须来自可验证来源（如仓库 preview gif、官方 CDN 直链）；无法提供则 `preview: none`。
4. 每条产出必须带 `source_url`（可回源验证），`verification_status` 按 CURRENT / STALE / BROKEN / UNKNOWN 标注。

---

## 4. 能力矩阵（providers.json 摘要）

| provider id | type | integration_mode | search | detail | preview | fetch | auth | license_model | priority | status |
|---|---|---|---|---|---|---|---|---|---|---|
| remotion-bits | GITHUB | PROVIDER | true | true | true | true | none | MIT | 9 | ACTIVE |
| onda | GITHUB | PROVIDER | true | true | true | true | none | MIT | 9 | ACTIVE |
| remotion-ui | GITHUB | PROVIDER | partial | true | true | manual_or_semiautomatic | none | MIT | 7 | ACTIVE |
| shotcraft | GITHUB | KNOWLEDGE_ADAPTER | true | true | false | true | none | Apache-2.0 | 8 | ACTIVE |
| polyhaven | API | RESOURCE_PROVIDER | partial | partial | true | manual_or_semiautomatic | none | CC0-1.0 | 8 | ACTIVE |
| remotion-sfx | PACKAGE | RESOURCE_PROVIDER | true | true | true | true | none | MIXED | 10 | ACTIVE |
| freesound | API | RESOURCE_PROVIDER | requires_authentication | requires_authentication | requires_authentication | requires_authentication | api_key | MIXED | 5 | ACTIVE |
| cc0-music | GITHUB | RESOURCE_PROVIDER | true | true | true | manual_or_semiautomatic | none | CC0-1.0 | 6 | ACTIVE |
| openverse | API | RESOURCE_PROVIDER | true | true | true | manual_or_semiautomatic | none | MIXED | 5 | ACTIVE |
| generaluser-gs | WEBSITE | RESOURCE_PROVIDER | true | true | false | true | none | UNKNOWN | 7 | ACTIVE |
| kenney | WEBSITE | RESOURCE_PROVIDER | true | true | true | manual_or_semiautomatic | none | CC0-1.0 | 6 | ACTIVE |

Capability 值语义：

- `true`：Phase 5+ adapter 可实现该能力（Phase 4 只在本地种子索引上演示）。
- `false`：该 Provider 不提供此能力（如 shotcraft/generaluser-gs 无媒体 preview）。
- `partial`：只覆盖部分范围（如 remotion-ui 仅 README 索引；polyhaven 仅本地种子子集）。
- `manual_or_semiautomatic`：需要人工步骤（如 `npx remotion-ui add ...`、粘贴 CDN 链接）。
- `requires_authentication`：必须先获得凭据（key/oauth），未配置凭据时该能力不可用。

Provider Type（8）：`LOCAL | GITHUB | API | CLI | MCP | WEBSITE | PACKAGE | STATIC_INDEX`。
Integration Mode（沿用 Phase 1，6 种）：`EXTERNAL_SKILL | PROVIDER | KNOWLEDGE_ADAPTER | ARCHITECTURE_REFERENCE | TIMELINE_BACKEND | RESOURCE_PROVIDER`；Registry 处理其中 `PROVIDER / RESOURCE_PROVIDER / KNOWLEDGE_ADAPTER`。

---

## 5. Rate limit / retry / cache 预留约定（§99 语义）

- 每个 provider 条目保留 `rate_limit` 字段（providers.json），Phase 4 **不实现任何调度**（不做队列、不做全局限流器）。
- Phase 5+ 实现规则：
  - adapter 内部声明自己的 `rate_limit`（如 GitHub 未认证 60 req/h、Freesound token 配额）。
  - 网络错误按**指数退避重试**（默认最多 3 次，可被核心配置覆盖）；`429/403/5xx` 应留给核心可观察的日志。
  - 命中限流时 adapter 返回 `throttled: true`，核心据此降级（走缓存或跳过该 provider），不阻塞整体 search。
- `providers.json` 中的 `local_cache` 为**布尔值**（`true`=本地缓存其条目元数据，对应 provider-specific detail cache；`false`=无本地种子，需 live 查询）。这是 provider 条目的静态声明，由 P4-1 `provider.schema.json` 定义。
- 资源条目的运行期缓存由**资源级 Cache 状态机**（Cache 状态 5：`NOT_CACHED → METADATA_CACHED → PREVIEW_CACHED → PAYLOAD_CACHED → INSTALLED`）管理，核心推进状态机，adapter 只上报当前结果对应的状态。
- 本地优先：`local_only=True` 时核心只查询 `local_cache == true` 的 provider。

---

## 6. 离线模式约定（§97 语义）

- `offline=True` 时，任何 adapter **不得发出任何网络请求**（禁 HTTP、禁 CLI 拉取、禁包下载）。
- 行为：`search` 直接返回 `[]` 且每项标记 `unavailable: true`（由核心在结果里标注）；`detail / preview / fetch` 返回 `{"unavailable": true}`。
- adapter 实现里网络调用必须集中在**可拦截的单一出口**（如 `_http_get()`），便于 offline 短路与 mock。
- 本地种子索引（`METADATA_CACHED`）在离线模式仍然可搜可读——离线不等于空 Registry。

---

## 7. Provider 失败隔离（§98 语义）

- 单个 provider 抛异常/超时/返回垃圾数据 → 核心**记录错误 + 继续其他 provider**，绝不让整个 search 崩掉。
- 核心输出中保留 `provider_errors: {provider_id: error_summary}`，用户可见（`--json` 里 `warnings`）。
- adapter 不应吞掉错误细节：把异常包装为带 `provider_id` 与 `stage` 的错误对象向上抛，由核心统一兜底。
- 排序/过滤逻辑不因某个 provider 失败而偏置（缺失 provider 的结果缺失，但不影响其余结果的正确排序）。

---

## 8. 安全红线（§100-101 语义）

1. **Path traversal 校验**：`fetch(resource_id, dest)` 中，resource_id / 文件名的任何路径成分不得包含 `..`、`/`、`\`、空字节；规范化后必须仍位于 `dest` 之内。核心与 adapter 双重校验。
2. **不自动执行**：fetch 得到的任何文件**不得自动执行**（不 exec、不 eval、不 npm install -g、不 shell 拼接）。`EXTERNAL_INSTALL` 必须先走 Approval Gate。
3. **Archive 白名单扩展名**：解压类操作只允许白名单扩展名（如 `.zip/.tar.gz/.tgz/.tar`），解压目标同样做 path traversal 校验；`.sf2` 等二进制只落盘不解压不执行。
4. **License snapshot**：fetch 必须同时落盘该条资源的 license snapshot（来源 + license 名称 + attribution 要求），禁止"先下再说"。
5. **不绕过授权**：`requires_authentication` 的 provider（如 freesound）不得爬站、不得绕过官方认证拿下载（对应派工单 §27 语义）。

---

## 9. 新 Provider 接入清单

接入一个全新 Provider 的步骤（Phase 5+ 也按此顺序）：

1. **确认来源真实**：WebFetch/curl 验证 url 可达；license 以官方仓库/站点为准，无法验证标 `UNKNOWN`（禁止编造）。
2. **加 providers.json 条目**：id（kebab-case）/ name / type（8 选 1）/ url / integration_mode（6 选 1）/ 四项 capability（5 值枚举）/ authentication / license_model / local_cache / status / priority / notes / rate_limit（预留）。
3. **写 adapter**：实现 `search / detail / preview / fetch` 四方法 + `id / capabilities` 属性；输出严格归一化到 L0/L1 字段；网络调用收敛到单一出口（offline 可短路）；遵守安全红线。
4. **注册到 registry.py**：在 adapter 工厂/注册表里把 provider_id 映射到实现类（核心不感知实现细节）。
5. **验证 3 条搜索**：用 3 个代表性 query 各跑一遍 `find`，确认：结果有 source_url 可回源、license 字段非猜、offline=True 不产生任何网络请求、单 provider 故障不影响其他 provider 结果。
6. **更新能力矩阵**：同步本文档 §4 表格与 providers.json 摘要。

---

## 附：与 providers.json 的一致性

- 本文档 §4 能力矩阵与 `providers.json` 同源；任何改动需两处同步（P4-6 集成校验会核对）。
- `providers.json` 已按 P4-1 落盘的 `schemas/provider.schema.json` 对齐：capability 为布尔或 `partial | manual_or_semiautomatic | requires_authentication` 字符串；`authentication` 用大写枚举 `NONE / API_KEY / OAUTH / TOKEN / CREDENTIALS / UNKNOWN`；`local_cache` 为布尔；`rate_limit` 仅用 `max_requests / window_seconds / retry_after`（数值为预留估算，非官方承诺，接入时以实际行为修正）。
- 第一批 11 个 provider 的 `status` 全部为 `ACTIVE`（2026-08-13 逐 url 验证可达）；`generaluser-gs` 的 license 为 `UNKNOWN`（见 providers.json notes，需 license_review_required）。
- 若后续 `schemas/provider.schema.json` 更新与本文件表述冲突，以 schema 为准并在本文件记录差异。
