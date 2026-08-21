# Provider — internet-archive（Internet Archive / Prelinger Archives）

> 对应文件：[registry/index/providers.json](../index/providers.json) 的 `internet-archive` 条目
> （P6-03 追加，仅追加不改既有 provider）。
> 本文件为 Provider 接入说明（人工网页检索型，Phase-4 registry/providers/README.md 契约的
> Provider 级补充），不是 adapter 实现。

## 基本信息

| 字段 | 值 |
|---|---|
| id | `internet-archive` |
| name | Internet Archive (Prelinger Archives) |
| type | WEBSITE |
| url | https://archive.org/details/prelinger |
| integration_mode | RESOURCE_PROVIDER |
| search_capability | manual_or_semiautomatic（人工网页检索；见下方「能力语义」） |
| detail_capability | true |
| preview_capability | true |
| fetch_capability | manual_or_semiautomatic（无真实下载，只产门禁记录） |
| authentication | NONE |
| license_model | 公共领域为主、条目注明 per-item 授权 |

## 能力语义（search_capability=manual_web）

- 搜索为**人工网页检索**：archive.org 详情页 + Prelinger 馆藏页（`archive.org/details/prelinger`），
  由人工/后续 adapter 逐条核验后登记为本地种子元数据快照。
- `provider.schema.json` 能力枚举不包含 `manual_web`，故按枚举记 `manual_or_semiautomatic`
  （语义等同 manual_web：需要人工网页检索步骤）。
- 本索引为**元数据快照**（Level 0/1），不下载实体文件（§59 只建索引，fetch 留门禁记录）。

## License 注意事项（§62-63）

- 馆藏以**公共领域**为主，但条目注明 **per-item 授权**：每条资源 fetch 前必须逐条核对
  archive.org 详情页的授权声明，不得假定全部 PD。
- 未知授权条目必须写 `license_type=UNKNOWN` 且 `license_review_required=true`、
  `commercial_use=false`，禁止猜测 commercial_safe。

## Fetch Gate

- `fetch_capability=manual_or_semiautomatic`：archive.org 详情页可提供原始文件下载链接，
  但引擎不实现下载（Phase-6 §66 只产出门禁记录：Explain → Size → Why → Alternatives → Approval）。
- 大文件（>500MB 或 4K）走 `preview → selection → download` 顺序（§65-66），禁止批量下载。

## 关联种子

`internet-archive:footage:*`（Prelinger 档案公共领域经典条目：城市 / 历史 / 工作场景）。
