# providers/generative-video/ — Generative Video Provider 配置目录（§28）

> 视频模型变化非常快，因此 Provider 能力通过**配置**扩展，而不是在核心代码里
> `if model == "XYZ"` 写几十个分支（§28）。本目录即该配置层。

## 目录内容

| 文件 | 用途 |
|---|---|
| `template.yaml` | 可复制模板（全字段 + 注释），新增 Provider 时复制本文件 |
| `manual-web.yaml` | 通用人工网页生成通道（§29 一等公民）：`api_available:false` + `manual_generation_supported:true`，通用参数范围，不接具体服务 |
| `provider-t2v-cinematic.yaml` | 示例能力档（高能力档：t2v + i2v + 首尾帧 + 角色参考 + 相机 + 种子），`api_available:false` + `status:unconfigured`，仅能力档案 |
| `provider-i2v-studio.yaml` | 示例能力档（低能力档：仅 i2v、5s/1080p、无相机/种子控制），同上，用于演示 capability_check 的 unsupported 判定 |

## 读取方式

`adapters/generative-video/__init__.py` 的 `load_providers(config_dir)` 读取本目录全部
`*.yaml / *.yml / *.json`（跳过 README），用 stdlib YAML 子集解析（对齐 P6-01
`generative-video-provider.schema.json` 字段），返回 `{provider_id: capability_dict}`。

## 字段对齐（§27 / P6-01）

`provider_id`（`^[a-z0-9-]+$`）/ `model` / `text_to_video` / `image_to_video` /
`first_last_frame` / `reference_image` / `character_reference` / `camera_control` /
`duration_options[]` / `resolution_options[]` / `aspect_ratios[]` / `audio_generation` /
`seed_control` / `commercial_terms` / `api_available` / `manual_generation_supported`，
可选：`negative_prompt_supported` / `max_prompt_length` / `notes` / `status(active|unconfigured|deprecated)`。

## 硬规则

- **禁止编造 API endpoint / key 占位**：本阶段无真实凭据，`api_available` 一律 `false`；
  真实接入由用户/后续阶段提供凭据后另行配置。
- 模型名**可以**出现在本配置层（§103 允许），但核心代码（gates/workflow/adapters）
  **禁止**出现具体模型名。
- 本目录只描述"能力档案"，不产生任何真实调用；AUTOMATED 路径在无凭据时一律
  `BLOCKED_NOT_CONFIGURED`（§116）。

## 新增 Provider 的步骤

1. 复制 `template.yaml` → `provider-<slug>.yaml`。
2. 修改 `provider_id`（小写连字符）与各能力字段（如实填写，不编造）。
3. `api_available` 保持 `false`、`status` 写 `unconfigured`，直到用户提供真实凭据。
4. 用 `python3 -m adapters.generative_video` 的自检或 `work/p6-06/test_self.py` 验证可加载。
