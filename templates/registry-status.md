# Registry Status

> Phase-4 §122 Registry 状态报告模板。本文件是**状态快照模板**：复制后按当前 Registry 实际状态填写，
> 或由脚本/人工从 `registry/index/providers.json`、`registry/index/resources.jsonl`、
> 缓存目录（`~/.cache/zhou-videodirector-registry`）聚合生成。凡未确认的字段写 `UNKNOWN`，禁止编造（§91）。
> 填表时间/填表人写在下方，状态会随更新命令（registry.py update）与缓存状态机演进。

- 生成时间：`YYYY-MM-DD HH:MM`（更新本报告时改为当前时间）
- 数据来源：`registry/index/providers.json`（providers）、`registry/index/resources.jsonl`（resources）、本地缓存 local_state
- 引擎：`scripts/registry.py`（validate 命令可复核七项检查，§67）

## Providers

> 逐条列出 Provider（来源 `registry/index/providers.json` 的 `providers[]`）。每行一个 provider。
> 状态值（4 枚举）：`ACTIVE`=正常；`DEGRADED`=部分能力受影响；`BROKEN`=不可用（从候选剔除）；`UNKNOWN`=未确认。
> priority 为 0-100 搜索优先级（越高越优先，进入 provider_priority 排序因子）。

| id | type | search | detail | preview | fetch | license_model | status | priority |
|---|---|---|---|---|---|---|---|---|
| remotion-bits | GITHUB | true | true | true | true | MIT | ACTIVE | 9 |
| polyhaven | API | true | true | true | requires_authentication | CC0 为主 | ACTIVE | 0 |
| freesound | API | true | true | partial | requires_authentication | 各条目自带 | ACTIVE | 0 |
| ...（其余 provider 照此格式） | | | | | | | | |

- 说明列（capabilities）：`true`/`false`/`partial`/`manual_or_semiautomatic`/`requires_authentication`（§7）。
- 填表方式：`registry.py validate --json` 可复核；也可 `python3 -c` 读 providers.json 统计。

## Capabilities

> 汇总四项能力矩阵的健康度：按 capability（search/detail/preview/fetch）统计各取值的 provider 数。
> 用途：一眼看出哪项能力缺失（如多数 provider 的 fetch 需要认证或人工介入，则资源获取路径受限）。

| capability | true | partial | manual_or_semiautomatic | requires_authentication | false |
|---|---|---|---|---|---|
| search | 11 | 0 | 0 | 0 | 0 |
| detail | ... | ... | ... | ... | ... |
| preview | ... | ... | ... | ... | ... |
| fetch | ... | ... | ... | ... | ... |

- 填表方式：遍历 `providers.json` 的四项 `*_capability` 字段计数。
- 任何 capability 全为 `false`/缺失时，在 Known Limitations 中说明影响。

## Indexed Resources

> 按资源类型（15 枚举）统计 `registry/index/resources.jsonl` 的条目数。对照 §90 Seed 目标数量表
> （motion/transition 30-50、shot recipe 15-25、3d/hdri/texture 15-25、sfx 30-40、music 10-20、soundfont 1-2）
> 判断索引覆盖率是否达标。

| type | count | 备注 |
|---|---|---|
| MOTION_EFFECT | 0 | |
| TRANSITION | 0 | |
| SHOT_RECIPE | 0 | |
| REMOTION_COMPONENT | 0 | |
| THREE_D_MODEL | 0 | |
| TEXTURE | 0 | |
| HDRI | 0 | |
| FOOTAGE | 0 | |
| IMAGE | 0 | |
| SFX | 0 | |
| MUSIC | 0 | |
| SOUNDFONT | 0 | |
| FONT | 0 | |
| REFERENCE | 0 | |
| OTHER | 0 | |
| **合计** | **0** | |

- 填表方式：`grep -c '"type": "MOTION_EFFECT"' registry/index/resources.jsonl` 逐类计数，或脚本聚合。
- 条目真实性：全部应来自真实可验证来源（source_url 可验证）；`verification_status=UNKNOWN` 的条目在备注列出（§91）。

## Federated Providers

> Federated Provider（polyhaven / freesound / openverse 等）：只建 provider 条目 + query adapter 接口定义，
> 不实现真实网络调用（§90 / §99）。本节记录其 adapter 接口状态与真实调用可行性。

| provider | type | adapter 接口 | 真实网络调用 | 备注 |
|---|---|---|---|---|
| polyhaven | API | registry/providers/README.md | 未实现（Phase 5+，§99） | 需 API_KEY |
| freesound | API | 同上 | 未实现（Phase 5+，§99） | 需 API_KEY |
| openverse | API | 同上 | 未实现（Phase 5+，§99） | 需 API_KEY |

- 填表方式：对照 `registry/providers/README.md` 的 adapter 接口规范与 providers.json 的 integration_mode。
- 真实网络调用 = 引擎当前仅做 gate 判定与提示，不实际下载（§99）；如已实现，改注实际状态。

## Cache

> 缓存状态：cache 状态机 5 枚举 `NOT_CACHED | METADATA_CACHED | PREVIEW_CACHED | PAYLOAD_CACHED | INSTALLED`（§57-58）。
> 缓存目录：`~/.cache/zhou-videodirector-registry`（环境变量 `ZHOU_REGISTRY_CACHE_DIR` 可覆盖），
> 运行期状态存 `local_state.json`。缓存不放进 skill 源码树（§59）。

| cache_state | 条目数 | 说明 |
|---|---|---|
| NOT_CACHED | 0 | 未缓存任何内容 |
| METADATA_CACHED | 0 | 只有 Level 0/1 元数据 |
| PREVIEW_CACHED | 0 | 预览已缓存 |
| PAYLOAD_CACHED | 0 | 资源本体已缓存 |
| INSTALLED | 0 | 已安装（如 SoundFont 装入 FluidSynth 路径） |

- 填表方式：读 `cache/local_state.json`（或资源条目的 `local_state.cache_state`）计数。
- 本地缓存记录字段：`cache_state / local_path / checksum / version / downloaded_at / license_snapshot`（§64）。
- 注意：本地只累积「用过的」资源，不累积「可能用到的」资源（§2）。

## License Coverage

> License 覆盖：评估每条资源的 license 判定完整度（§60-64）。重点：
> 1. 每条 resource 必须有 license 子对象（schema required）；
> 2. `license_type=UNKNOWN` 的条目必须 `license_review_required=true`（§61，禁止猜测 commercial_safe）；
> 3. `attribution_required=true` 的资源必须记录 attribution 并写入 asset 元数据（§63）。

| 类别 | 条目数 | 说明 |
|---|---|---|
| license_type 已知（MIT/CC0-1.0/CC-BY-4.0/...） | 0 | |
| license_type=UNKNOWN（需复核，§61） | 0 | |
| license_review_required=true | 0 | 与 UNKNOWN 类对应 |
| commercial_use=true | 0 | 可商用 |
| commercial_use=false / 未知 | 0 | 商用项目搜索会被过滤（§62） |
| attribution_required=true | 0 | 须记录署名 |

- 填表方式：逐条读 resources.jsonl 的 `license` 子对象计数。
- 若存在 `license_review_required=true` 的条目进入生产候选，必须在 Known Limitations 中列出并走人工复核。

## Preview Coverage

> 预览覆盖：有可展示预览（`preview.type` 非 none）的资源比例（preview 排序因子，§39-46 因子 8）。

| 指标 | 值 |
|---|---|
| 有预览条目数 | 0 |
| 预览类型分布 | （如 image / video / audio / html / none） |
| 预览 URL 总数 | 0 |

- 填表方式：读 resources.jsonl 的 `preview` 子对象（`type` / `url` / `local_path`）统计。
- 预览缓存（PREVIEW_CACHED）数在 Cache 节记录；此节记录**可预览覆盖率**。

## Known Limitations

> 已知限制清单（当前实现阶段下的事实，不粉饰）：
> - 真实下载未实现：Phase-4 引擎只做 fetch gate 判定与 LIGHTWEIGHT 本地可演示路径；真实下载留 Phase 5+（§99）。
> - Federated Provider 不实现真实网络调用（§90 / §99）。
> - 验证有效期：`verification_status` 超过 90 天未复验将降为 `STALE`（§67-69）。
> - 许可待复核条目：凡 `license_review_required=true` 的条目，人工确认前不可用于生产。
> - （其它按现状追加，每条注明原因/影响/缓解。）

## Broken Providers

> 不可用 Provider（status=BROKEN）清单。BROKEN 从候选剔除（不参与推荐，除非显式查询，§98）；
> 单个 provider 失败不影响其它 provider（§98 失败隔离）。

| provider | status | 故障表现 | 影响范围 | 恢复/处理 |
|---|---|---|---|---|
| （如无则写「无」） | BROKEN | （如 404 / 网络不可达 / 认证失效） | （影响的资源/能力） | （待 update 复验 / 联系提供方） |

- 填表方式：对照 providers.json 的 `status`；DEGRADED 的 provider 也在此说明受影响能力。
- 若某 provider 的 `verification_status` 资源全部为 BROKEN，记录对应 `last_verified` 与复验计划。
