# Provider — nasa-images（NASA Image and Video Library）

> 对应文件：[registry/index/providers.json](../index/providers.json) 的 `nasa-images` 条目
> （P6-03 追加，仅追加不改既有 provider）。
> 本文件为 Provider 接入说明，不是 adapter 实现。

## 基本信息

| 字段 | 值 |
|---|---|
| id | `nasa-images` |
| name | NASA Image and Video Library |
| type | API |
| url | https://images.nasa.gov/ |
| integration_mode | RESOURCE_PROVIDER |
| search_capability | partial（本阶段只对本地种子索引生效；live API 查询 Phase 5+ 接入） |
| detail_capability | partial |
| preview_capability | true |
| fetch_capability | manual_or_semiautomatic（无真实下载，只产门禁记录） |
| authentication | NONE |
| license_model | 多数公共领域（非 logo 内容），需注明 NASA media guidelines |

## API 与能力语义

- API: `https://images-api.nasa.gov`（公开，无需 key；search/detail=partial 表示 Phase-4/6
  只对本地种子索引生效，live 查询留 Phase 5+ adapter）。
- 搜索为人工网页检索 + 本地种子索引；本索引为**元数据快照**（Level 0/1，不下载实体文件）。

## License 注意事项（§62-63）

- NASA 媒体大多**公共领域**（PD/CC0 语义），但以下除外，须遵守
  [NASA media usage guidelines](https://www.nasa.gov/multimedia/guidelines/index.html)：
  NASA logo、字体、NASA 特定商用限制内容；条目按实际授权写。
- 公共领域条目保留 `source` / `provenance` / `license`（§58/§63）。

## Fetch Gate

- `fetch_capability=manual_or_semiautomatic`：images.nasa.gov 详情页提供预览与下载入口，
  但引擎不实现下载（Phase-6 §66 只产门禁记录）。
- 4K 大文件走 `preview → selection → download`（§65-66），禁止批量下载。

## 关联种子

`nasa-images:footage:*`（Apollo 11 登月 / Goddard 档案 / 航天发射等公共领域素材）。
