# Provider — pexels（Pexels Videos）

> 对应文件：[registry/index/providers.json](../index/providers.json) 的 `pexels` 条目
> （P6-03 追加，仅追加不改既有 provider）。
> 本文件为 Provider 接入说明，不是 adapter 实现。

## 基本信息

| 字段 | 值 |
|---|---|
| id | `pexels` |
| name | Pexels Videos |
| type | WEBSITE |
| url | https://www.pexels.com/videos/ |
| integration_mode | RESOURCE_PROVIDER |
| search_capability | manual_or_semiautomatic（人工网页检索；官方 API 需 key） |
| detail_capability | true |
| preview_capability | true |
| fetch_capability | manual_or_semiautomatic（无真实下载，只产门禁记录） |
| authentication | API_KEY |
| license_model | Pexels License（免费可商用，无需署名） |

## 能力语义（search_capability=manual_web）

- 网页浏览与预览**免费无需 key**；官方 API 需要 API key（`authentication=API_KEY` 对应 API 路径，
  未配置 key 时 API 能力不可用，网页人工检索不受影响）。
- 搜索为人工网页检索 + 本地种子索引；本索引为**元数据快照**（Level 0/1，不下载实体文件）。

## License 注意事项（§62-63）

- **Pexels License**：免费可商用、无需署名；允许编辑修改；**不允许**原样转售 /
  再分发原始文件（`redistribution_allowed=false`，`derivatives_allowed=true`）。
- 逐条按 Pexels License 写 `commercial_use=true`（§62）。

## Fetch Gate

- `fetch_capability=manual_or_semiautomatic`：pexels.com/video/ 详情页提供预览与下载，
  但引擎不实现下载（Phase-6 §66 只产门禁记录）。
- 4K 大文件走 `preview → selection → download`（§65-66），禁止批量下载。

## 关联种子

`pexels:footage:*`（城市航拍 / 自然 / 科技等现代氛围素材）。
