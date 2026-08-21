# Provider — pixabay（Pixabay Videos）

> 对应文件：[registry/index/providers.json](../index/providers.json) 的 `pixabay` 条目
> （P6-03 追加，仅追加不改既有 provider）。
> 本文件为 Provider 接入说明，不是 adapter 实现。

## 基本信息

| 字段 | 值 |
|---|---|
| id | `pixabay` |
| name | Pixabay Videos |
| type | WEBSITE |
| url | https://pixabay.com/videos/ |
| integration_mode | RESOURCE_PROVIDER |
| search_capability | manual_or_semiautomatic（人工网页检索） |
| detail_capability | true |
| preview_capability | true |
| fetch_capability | manual_or_semiautomatic（无真实下载，只产门禁记录） |
| authentication | NONE |
| license_model | Pixabay Content License（免费商用） |

## 能力语义（search_capability=manual_web）

- 搜索为**人工网页检索**（pixabay.com/videos 详情页）+ 本地种子索引；本索引为
  **元数据快照**（Level 0/1，不下载实体文件）。
- 种子条目的 source_url 为按 provider URL 惯例构造的详情页；P6-03 阶段 **scope 禁联网**，
  未做回源核验，条目以 `verification_status` 如实标注（见各条目），后续阶段需联网复核。

## License 注意事项（§62-63）

- **Pixabay Content License**：免费商用、无需署名；允许编辑修改；**不允许**原样再分发
  原始文件（`redistribution_allowed=false`）。
- 逐条按 Pixabay Content License 写 `commercial_use=true`（§62）。

## Fetch Gate

- `fetch_capability=manual_or_semiautomatic`：详情页提供预览与下载入口，但引擎不实现下载
  （Phase-6 §66 只产门禁记录）。
- 大文件（>500MB 或 4K）走 `preview → selection → download`（§65-66），禁止批量下载。

## 关联种子

`pixabay:footage:*`（城市夜景 / 自然 / 工作 / 科技场景）。
