# ZHOU_Videodirector — Resource Registry 宪法参考（Registry Constitution）

本文件是 `ZHOU_Videodirector` Phase 4（Resource Registry）的宪法级参考文档，回答「Registry 是什么、为什么、边界在哪、规则是什么」。实现细节以四个 schema 与引擎为准。

- 来源：Phase-4 Prompt §1-§124（重点 §1-§15 / §20 / §25 / §39-§46 / §52-§64 / §67-§75 / §76-§83 / §84-§86 / §97-§101 / §105-§111 / §118-§121），总设计 v0.2 相关章节。
- 配套：机器可读契约 `schemas/resource.schema.json`、`schemas/provider.schema.json`、`schemas/resource-request.schema.json`、`schemas/resource-selection.schema.json`；引擎 `scripts/registry.py`（P4-2 将建）；工作流 `workflows/resource-planning.md`。
- 相关政策：外部能力接入见 [external-capability-policy.md](external-capability-policy.md)（Integration Mode 语义与 Copy Everything 禁止）；复用清单见 [reuse-map.md](reuse-map.md)；顶层宪法见 [constitution.md](constitution.md)。

---

## 1. 定位与唯一目标（§1）

Registry 的两种工作方式对比：

| | 反面方式：下载优先 | 正确方式：Metadata First |
|---|---|---|
| 启动 | 先 clone 各组件库 / 下载音色库 | 先建元数据索引（JSONL + provider 条目） |
| 搜索 | 遍历本地文件，或必须在线逐个看 | 查索引，秒级返回（离线也可搜已缓存元数据） |
| 详情 | 打开整个 repo / 下载整个文件再看 | 按需取 Level 1 Detail |
| 使用 | 用前必须已下载 | 用前才 fetch（Level 2） |
| 风险 | 磁盘爆炸、License 未审先入库、第三方整库搬入 | 全部经 License 门与 Approval 门 |
| 网络 | 断网即瘫痪 | 断网可搜、可看已缓存预览 |

**唯一目标**：让「这个视觉用什么现成资源」这个问题被**快速、合规、可审计**地回答，而不是「把外部资源都搬回家」。

## 2. Metadata First, Payload Later（§2 宪法条文）

> 先索引 → 搜索 → 预览 → 最后才下载（fetch）。

本条是 Registry 的最高操作序，任何流程不得颠倒：

1. 搜索命中前不下载；
2. 预览不满足前不下载；
3. 下载前必须过 License 门（§60）与 Approval 门（§52）；
4. 本地只累积「用过的」资源，不累积「可能用到的」资源。

可检查性：`registry.py` 的 `find` 命令不得触发任何下载；`fetch` 命令必须记录审批。

## 3. 三级加载（§3）

| 级别 | 加载内容 | 代表字段 | 何时触发 |
|---|---|---|---|
| **LEVEL 0 Catalog** | 一行可展示的摘要信息 | id / name / type / provider / tags / summary / best_for / avoid_when / style / preview_ref / license_summary / availability | 搜索 / 列表 |
| **LEVEL 1 Detail** | 使用所需的完整元数据 | description / parameters / dependencies / compat / tech_req / formats / resolution / size / license（全量）/ commercial / attribution / limitations / usage / source_url / last_verified | `detail` 命令 / 候选评审 |
| **LEVEL 2 Payload** | 资源本体 | 文件 / 组件源码 / 安装包 | `fetch` 命令（受审批与 License 约束） |

对应宪法原则 15（Progressive Resource Disclosure）：禁止在 Level 0 阶段执行 clone / install / 大文件下载。

## 4. Registry 架构与目录（§5 结构图）

```text
registry/
├── index/
│   ├── resources.jsonl     # 所有资源条目的唯一真源（JSONL，追加式）
│   ├── providers.json      # Provider 条目（首批 10 个，见 §8）
│   └── tags.json           # Tag Taxonomy 基础词表（三类，见 §19）
├── cache/                  # 本地缓存（不污染 Skill Core，见 §11）
└── providers/              # Provider adapter 接口规范（README，P4-3 产出）
```

- **Registry = Metadata + Search Index + Preview + Provider Adapter + Cache 信息**（§4）。
- **Registry ≠ 素材仓库**：不保存素材全集；payload 状态枚举 `remote / cached / downloaded / installed / vendored / external`。
- **不造 10000 个 md**（§6）：不按资源建独立 md 文件，detail 要么在 JSONL 行内，要么在 provider-specific detail cache。
- **不做 SQLite**（§7）：当前规模 JSONL 足够，无意义不引数据库依赖。

## 5. 索引策略（§6-7）

- 主索引 `index/resources.jsonl`：每行一条资源，追加式维护，可 grep / 脚本处理，git 友好。
- 禁止「为每条资源建一个 md」：不造 10000 个 md；detail 数据走 JSONL 行内或 provider-specific detail cache。
- 不引入 SQLite / 数据库：当前规模 JSONL 足够（§7）。
- 查询过滤在内存 / 索引中完成；写入统一经 `add` / `update` 命令并过 `validate`（schema + 规则校验）。

## 6. Resource ID / Type / Nature（§9 / §10 / §20）

**Resource ID = `{provider}:{type}:{slug}`**（§9）

```text
pattern: ^[a-z0-9-]+:[a-z0-9_-]+:[a-z0-9._-]+$
示例：remotion-bits:motion_effect:gradient-text-shimmer
      polyhaven:hdr:studio_small_09
```

- provider 段 = provider.schema.json 的稳定 `id`（保留 provider 稳定 ID）；
- type 段 = Resource Type 枚举小写下划线形式；
- slug 段 = 条目唯一标识。

**Resource Type 15 枚举**（§10）：

```text
MOTION_EFFECT | TRANSITION | SHOT_RECIPE | REMOTION_COMPONENT | THREE_D_MODEL
| TEXTURE | HDRI | FOOTAGE | IMAGE | SFX | MUSIC | SOUNDFONT | FONT | REFERENCE | OTHER
```

**resource_nature 5 枚举**（§20）：`KNOWLEDGE | CODE | MEDIA | MODEL | PACKAGE`

- 类型与本质不是一一映射：同是 CODE 本质，`MOTION_EFFECT` 与 `REMOTION_COMPONENT` 是不同 type；同是 MEDIA 本质，`SFX` 与 `MUSIC` 是不同 type。
- resource 条目的 `type_specific` 扩展槽按 type 取对应键（motion / shot_recipe / 3d / texture / hdri / sfx / music / soundfont / font / footage / image / reference），避免顶层字段爆炸（§8）。

## 7. Provider 系统（§11-14）

Provider = 资源来源适配条目，**不是实现**。每条描述：类型（8）、集成模式（6）、四项能力、认证、License 模型、限流预留、优先级、状态。

**Capability 取值**（search / detail / preview / fetch 四项，oneOf boolean|string）：

```text
true | false | partial | manual_or_semiautomatic | requires_authentication
```

- `true` / `false`：明确支持 / 不支持；
- `partial`：能力有限不完整（如只能搜索预览、不能直接 fetch）；
- `manual_or_semiautomatic`：需人工或半自动介入（如复制粘贴组件）；
- `requires_authentication`：需要 API key / token 等认证。

**Provider Type 8 枚举**（§12）：`LOCAL | GITHUB | API | CLI | MCP | WEBSITE | PACKAGE | STATIC_INDEX`

**Integration Mode 6 枚举**（沿 Phase 1，精确定义见 external-capability-policy.md）：

```text
EXTERNAL_SKILL | PROVIDER | KNOWLEDGE_ADAPTER | ARCHITECTURE_REFERENCE
| TIMELINE_BACKEND | RESOURCE_PROVIDER
```

Registry 主要处理 `PROVIDER / RESOURCE_PROVIDER / KNOWLEDGE_ADAPTER` 的元数据；`EXTERNAL_SKILL / ARCHITECTURE_REFERENCE / TIMELINE_BACKEND` 归其它模块。

**Capability Matrix 示例结构**（首批 10 个 provider 见 §8；`providers.json` 记录全量矩阵 + rate_limit 预留）：

| provider | type | search | detail | preview | fetch | auth | integration |
|---|---|---|---|---|---|---|---|
| remotion-bits | GITHUB | true | true | partial | manual_or_semiautomatic | NONE | PROVIDER |
| polyhaven | API | true | true | true | requires_authentication | API_KEY | RESOURCE_PROVIDER |
| freesound | API | true | true | partial | requires_authentication | API_KEY | RESOURCE_PROVIDER |
| generaluser-gs | GITHUB | partial | true | none | manual_or_semiautomatic | NONE | RESOURCE_PROVIDER |

（上表为结构示例，具体取值以 P4-3 `providers.json` 为准。）

Provider 状态 4 枚举：`ACTIVE | DEGRADED | BROKEN | UNKNOWN`；搜索优先级 `priority`（0-100）进入排序因子。

## 8. 第一批 Provider 清单（§15 + §90）

**首批 10 个 Provider**（§15，来源 reuse-map 与 Phase-4 §15）：

```text
remotion-bits | onda | remotionui | shotcraft | polyhaven
| remotion-sfx | freesound | cc0-music | openverse | generaluser-gs
```

每个 provider 条目含四项能力矩阵 + rate_limit 预留（`providers.json`，P4-3）。Federated Provider（polyhaven / freesound / openverse）只建 provider 条目 + query adapter 接口定义，不实现真实网络调用（§90 / §99）。

**§90 Seed 目标数量表**（`index/resources.jsonl` 首批种子规模）：

| 资源类 | 目标条目数 |
|---|---|
| motion / transition | 30-50 |
| shot recipe | 15-25 |
| 3d / hdri / texture | 15-25 |
| sfx | 30-40 |
| music | 10-20 |
| soundfont | 1-2 |

**不伪造资源**（§91）：Seed Registry 只放真实存在且验证过的条目（source_url 真实可验证）；不可验证字段标 `UNKNOWN` 而非猜测；测试 fixture 才允许 fake。

## 9. License 政策（§60-64）

1. **硬需求**：每条 resource 必须有 `license` 子对象（resource.schema 的 required）。
2. **UNKNOWN 规则**（§61）：`license_type` 未知 → 写 `"UNKNOWN"`，且 `license_review_required: true`；禁止猜测 `commercial_safe` / 商用友好。
3. **商业过滤**（§62）：项目商用 → 搜索过滤掉 `commercial_use=false` 或 `license_type=UNKNOWN` 的资源，除非用户显式确认。
4. **署名**（§63）：`attribution_required=true` 的资源必须记录 attribution，并写入 asset 元数据。
5. **license_snapshot**（§64）：fetch 时把当时的 license 原文 / URL 快照落盘（`local_state.license_snapshot`），防止以后链接失效。
6. **复合 / 双许可**：`license_notes` 写清提供方原文与适用条件。

## 10. Fetch 政策（§52-56）

**Approval Gate**：fetch 按四分类分级，`LARGE` / `EXTERNAL_INSTALL` 必须走 **Explain → Size → Why → Alternatives → Approval**。

**Fetch 分类 4 枚举**：

| 分类 | 判据 | 是否需审批 |
|---|---|---|
| `LIGHTWEIGHT` | 纯元数据 / 极小文件 | 否 |
| `MEDIUM` | 常规单文件资源 | 否 / 轻量记录 |
| `LARGE` | 大文件 / 成批 | 必须：Explain→Size→Why→Alternatives→Approval |
| `EXTERNAL_INSTALL` | 需要系统级安装 | 必须：同上 + 安装影响说明 |

**其他规则**：

- **Fetch ≠ clone 整仓**：组件库按条目 fetch（find → inspect → fetch 模式，§外部政策），禁止 bulk clone；禁止把第三方整库搬进本地（§外部政策 C）。
- 本地只累积「用过的」资源。
- Phase 4 引擎只做 gate 判定与提示 + LIGHTWEIGHT 本地可演示路径（cache 状态机 + license snapshot 落盘）；真实下载留 Phase 5+（§99）。

## 11. Cache 系统（§57-59）

**Cache 状态 5 枚举**：

```text
NOT_CACHED | METADATA_CACHED | PREVIEW_CACHED | PAYLOAD_CACHED | INSTALLED
```

- `NOT_CACHED`：未缓存任何内容；
- `METADATA_CACHED`：只有 Level 0/1 元数据；
- `PREVIEW_CACHED`：预览已缓存；
- `PAYLOAD_CACHED`：资源本体已缓存；
- `INSTALLED`：已安装（如 SoundFont 装入 FluidSynth 路径）。

**本地缓存记录**：`resource.local_state` = `{ cache_state / local_path / checksum / version / downloaded_at / license_snapshot }`。

**不污染 Skill Core**（§59）：缓存放项目目录或 `~/.cache`，不放进 `ZHOU_Videodirector` skill 源码树，避免把素材 / 依赖带进 skill 仓库。

## 12. 安全（§100-101）

- **path traversal**：`local_path` / 解压路径必须校验，禁止逃出缓存根目录。
- **危险解压**：zip 解压前检查条目路径（zip-slip），拒绝 `..` 与绝对路径条目。
- **可执行文件**：缓存 / 安装可执行物需白名单与确认；禁止自动执行任意脚本（§101）。
- **不自动执行**：fetch / install 只落盘，不运行安装脚本（除非 `EXTERNAL_INSTALL` 且经审批）。
- **不伪造资源**（§91）：无法验证的条目标 `verification_status=UNKNOWN` 并注明验证途径，绝不编造。

## 13. 搜索与排序（§39-46）

**排序 8 因子**（`registry.py` find 排序依据，与规格一致）：

| # | 因子 | 说明 |
|---|---|---|
| 1 | `relevance` | query / resource_types 命中相关度 |
| 2 | `best_for` | best_for / tags 与 query 语义重叠 |
| 3 | `style` | style 与项目 style 重叠 |
| 4 | `provider_priority` | provider.priority（0-100） |
| 5 | `license` | 满足 license 过滤后的合规加分 |
| 6 | `local_availability` | 本地已缓存（cache_state）加分 |
| 7 | `dependency` | 依赖越少得分越高（规格新增） |
| 8 | `preview` | 有预览（preview.type != none）得分高（规格新增） |

- **verification 为 tie-break 次级键**：`verification`（CURRENT > STALE > UNKNOWN > BROKEN）不参与主 score 的 8 因子权重；同分时先比 `provider_priority`，再比 `verification` 可信度。
- 体积大小因子已从评分移除，不再参与排序（`estimated_size_bytes` 仅用于 Fetch 分类提示）。

**可解释结果**（§46）：每条候选输出命中因子分解（哪些因子得分、为什么选中 / 落选），禁止黑盒分数。

**候选多样化**（§105-106）：默认 Top 5-10，且覆盖不同 provider / type，禁止全来自同一 provider；同 family 只返回 leader + 成员列表（§22）。

**过滤链**：type → provider → style → best_for → license（商业过滤）→ local_only。

## 14. Project / Route / Audio-aware Search（§43-45）

- **Project-aware**（§43）：读 VISUAL_BIBLE 风格标签 → `style` 因子加权。
- **Route-aware**（§44）：读 routing 输出（request.route）→ 影响候选类型与权重：

```text
REMOTION          → MOTION_EFFECT / TRANSITION / REMOTION_COMPONENT 优先
THREE_D           → THREE_D_MODEL / TEXTURE / HDRI 优先
REAL_FOOTAGE      → FOOTAGE / IMAGE 优先
JY_NATIVE         → TRANSITION / IMAGE / SFX（剪映原生可用）优先
GENERATIVE_VIDEO  → 通常不推荐 Registry 素材（除非作参考）
HYBRID            → 按 Layer 拆请求，各 Layer 按自身 route 加权
```

- **Audio-aware**（§45）：音乐 / SFX 请求读 AUDIO_DIRECTION 的 mood / energy / sync_points；energy 对齐 Music Energy 5 枚举；`loopable` / `narration_friendly` 按需过滤；未知字段标 `UNKNOWN` 不伪造。

## 15. Reuse Decision（§109-111）

**Reuse Decision 4 枚举**：`USE_AS_IS | ADAPT | COMPOSE | BUILD_NEW`

- 搜索命中 ≥90% fit → `reuse_recommendation: USE_AS_IS`（Reuse Before Build 落地）；
- `BUILD_NEW` 必须记录 **why existing failed**（哪个候选、为什么不行），禁止无理由自建；
- `ADAPT`：记录改动面；`COMPOSE`：记录组合边界（多个资源如何拼）。

## 16. Offline / Provider 失败（§97-98）

- **offline_mode**（§97）：无网络时仍可搜 METADATA_CACHED 的本地索引；远端候选标记「需在线验证」，不假称可用。
- **Provider 失败隔离**（§98）：单个 provider 失败不影响其它 provider；失败 provider 标记 `DEGRADED / BROKEN` 并从候选剔除，不阻塞整个搜索。
- **下载失败**：resource.availability=`REMOTE_OFFLINE`，从候选剔除并在报告中说明（对应 external-capability-policy 的 RESOURCE_PROVIDER 失败处理）。

## 17. 验证与过期（§67-69）

**verification_status 4 枚举**：`CURRENT | STALE | BROKEN | UNKNOWN`

- `last_verified`：每次验证更新；超过验证有效期（默认 90 天）→ `STALE`；
- 来源 404 / 网络不可达 → `BROKEN`；
- 从未验证 → `UNKNOWN`（Seed 阶段 WebFetch 失败保留条目并注明验证途径）；
- STALE / BROKEN 在排序中降权；BROKEN 默认不参与推荐（除非用户显式查询）。

## 18. Update / Add / Duplicate / Alias（§70-75）

- **Add**（§70-71）：走 `add` 命令，必须过 `validate`（id 唯一、required 字段、license 规则）；`metadata_version` 从 "1.0" 起步。
- **Update**（§72）：改字段不覆盖历史 id；`metadata_version` 递增；`last_verified` 更新。
- **Duplicate**（§73）：相同 `provider:type:source_url` → 视为重复，复用已有条目并记录 `aliases`，不建第二条。
- **Alias**（§75）：`aliases[]` 存旧 id / 常见别名；解析时指向主 id；alias 不改主 id。
- **不删旧记录**（与宪法原则 12 一致）：废弃条目置 `status=RETIRED`，保留历史。

## 19. Tag Taxonomy（§76-79 三类基础词表）

小写 kebab-case，每条目 ≤15 个，语义化优先；新标签先查 `tags.json`，缺失才增补。

**三类基础词表**（不过度设计）：

1. **用途类**（`best_for` 建议取值）：`product-demo / explainer / hero-opening / transition-bridge / b-roll / ui-demo / infographic / title-sequence / ambient-fill / documentary / ...`
2. **风格 / 视觉类**：`minimal / futuristic / tech / cinematic / paper-editorial / kinetic / organic / documentary / retro / luxury / ...`
3. **技术 / 领域类**：`2d / 2.5d / 3d / particle / glsl / svg / typography / data-viz / map / photoreal / toon / ...`

禁止自造无意义标签；`REFERENCE` 类型的 `best_lessons` 等语义标签可超出三类词表（吸收来源自由标注）。

## 20. Resource Router 与 Router 集成（§80-81 / §107）

**分工**：

- **Phase 3 Router 决定「这个视觉谁来做」**（route：REMOTION / THREE_D / REAL_FOOTAGE / GENERATIVE_VIDEO / JY_NATIVE / HYBRID）；
- **Phase 4 Registry 决定「用什么现成资源」**（从索引中找、评、选、取）。

**Request 生成**（§114-115）：引擎读 Phase-3 routing 输出（`routing/S###.yaml` + `layers/S###.yaml`）的 route / role / notes，按 Layer role + route 生成 `RESOURCE_REQUEST`；**HYBRID Shot 拆多个 request，不产模糊单 query**。

**bake 约束**（§107）：`request.bake_policy=KEEP_EDITABLE` 时不得推荐不可拆 Bake 的资源（须可拆为可编辑层 / Asset）。

**结果回写**：selection 经审批后回填 asset 生产计划（`asset_id` + `registry_resource_id`）。

## 21. Registry Resource ≠ Project Asset（§84-86）

- **Registry Resource**：外部世界的目录条目（`{provider}:{type}:{slug}`），与项目无关、跨项目共享，只存元数据。
- **Project Asset**：项目内的生产实体（`A###`，asset.schema.json），有本地路径、时间线用法、生产状态。
- **回链**（§85-86）：项目 asset 增加 `registry_resource_id` 字段指回 `{provider}:{type}:{slug}`；一个 registry resource 可被多个项目引用。
- **边界**：Registry 不持有素材全集；Asset 不直接改 Registry 条目（改走 `update` 命令 + 审批）。

## 22. Family 复用（§118-121）

- `family_id`（可选）：同系列变体共享家族（典型：SFX / Motion 家族——同一 UI 音效的多档音量 / 时长）。
- **收益**：跨 Shot 不重复搜索；家族内一次 fetch 可复用；license / source 家族内一致。
- **呈现**：搜索命中家族只返回 leader + 成员列表；同 family 候选去重。
- **约束**：`family_id` 只用于「真相关」（同源 / 同系列），不用于强行聚类；`continuity_group` 可进一步把同组请求导向同一家族（§44）。

## 23. 引用四 schema 与 scripts/registry.py

- `schemas/resource.schema.json`：统一资源格式（§8），字段负载见 §3 三级表与 §6 ID/Type/Nature。
- `schemas/provider.schema.json`：Provider 条目（§11-14），Capability oneOf 语义见 §7。
- `schemas/resource-request.schema.json`：检索输入（§82），Router 桥输入契约。
- `schemas/resource-selection.schema.json`：检索输出（§83），含审批与 fetch 状态。
- `scripts/registry.py`（**P4-2 将建**）：`find / detail / preview / fetch / add / update / validate` + 排序 8 因子 + 过滤链 + offline_mode + provider 失败隔离 + 缓存状态机 + 商业过滤 + reuse decision + family + Router→Registry 桥 + 可解释结果（§46）+ 安全校验 + `--selftest`。
- CLI 概念集（§102）：机器可读 `--json` + 人类可读摘要；默认 Top 5-10 且候选多样化。

---

## 附：本文档与其它文档的引用关系

- `docs/external-capability-policy.md`：Integration Mode 6 枚举精确定义；Copy Everything 禁止（`install / invoke / adapt / index / link / fetch-on-demand` 白名单）。
- `docs/reuse-map.md`：第一批 Provider 的来源（remotion-bits / onda / remotionui / remocn / poly-haven / remotion-sfx / freesound / mixkit / openverse / cc0-1.0-music / generaluser-gs 等）。
- `docs/constitution.md`：原则 15（Progressive Resource Disclosure）与本 Registry 三级加载一一对应；原则 2 / 16（Reuse Before Build / Before Build Check）。
- `docs/state-machine.md`：RESOURCE_REQUEST → RESOURCE_SELECTION → ASSET_PRODUCTION 状态推进。
- `schemas/asset.schema.json`：asset_id（A###）+ registry_resource_id 回链目标（§85-86）。
- `schemas/routing.schema.json`：route / bake_policy / layer role 来源（§80-81 / §107 / §114-115）。
