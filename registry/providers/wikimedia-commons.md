# Provider — wikimedia-commons（Wikimedia Commons）

> 对应文件：[registry/index/providers.json](../index/providers.json) 的 `wikimedia-commons` 条目
> （P6-03 追加，仅追加不改既有 provider）。
> 本文件为 Provider 接入说明，不是 adapter 实现。

## 基本信息

| 字段 | 值 |
|---|---|
| id | `wikimedia-commons` |
| name | Wikimedia Commons |
| type | API |
| url | https://commons.wikimedia.org/ |
| integration_mode | RESOURCE_PROVIDER |
| search_capability | partial（本阶段只对本地种子索引生效；live MediaWiki API 查询 Phase 5+ 接入） |
| detail_capability | partial |
| preview_capability | true |
| fetch_capability | manual_or_semiautomatic（无真实下载，只产门禁记录） |
| authentication | NONE |
| license_model | per-file 授权（CC0/CC-BY/PD 混合），commercial_use 按文件 |

## API 与能力语义

- API: `https://commons.wikimedia.org/w/api.php`（MediaWiki API，公开）。
- 搜索为人工网页检索 + 本地种子索引；本索引为**元数据快照**（Level 0/1，不下载实体文件）。

## License 注意事项（§62-63）

- **per-file 授权**：Commons 每个文件的授权独立（CC0 / CC-BY / CC-BY-SA / PD 混合），
  `commercial_use` 必须按**单个文件**实际授权写。
- CC-BY 系文件必须记录 `attribution_required=true` 并把 attribution 写入 asset 元数据（§63）。
- 未知授权文件写 `license_type=UNKNOWN` 且 `license_review_required=true`（§61）。

## Fetch Gate

- `fetch_capability=manual_or_semiautomatic`：Commons 文件页提供原文件与预览，但引擎
  不实现下载（Phase-6 §66 只产门禁记录）。
- 大文件（>500MB 或 4K）走 `preview → selection → download`（§65-66）。

## 关联种子

`wikimedia-commons:footage:*`（Blender 开放电影等 CC-BY 素材：Big Buck Bunny / Sintel /
Tears of Steel）。
