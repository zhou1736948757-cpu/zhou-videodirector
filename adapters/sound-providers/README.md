# Sound Providers（声音资源适配层）

> Phase 5（§87）· 定位：把各个声音 Provider 的产出**统一归一化为 Project Asset**，
> 让 Sound Engine 只面对一种契约，不感知每个 Provider 的差异。

## 1. 统一输出契约（归一化 Project Asset）

任何 Provider 产出的声音素材，在进入 Asset Registry 前必须归一化为以下字段
（对齐 `schemas/asset.schema.json` 最小增补 + `resource.schema.json` 的 license 块）：

```yaml
asset_id:          A###                     # 由 Manifest register_asset 分配
name:              <资源名>
type:              SFX | MUSIC | AMBIENCE | VOICEOVER | SOUNDFONT   # asset 18 枚举
producer:          REMOTION | LIBRARY_MUSIC | FLUIDSYNTH | ...      # 谁产出
request_id:        PR-###                    # 关联 production request
source_provider:   remotion-sfx | freesound | mixkit | local | cc0-music | ...
source_url:        <原始 URL / 包内路径>
local_path:        <本地缓存/产出路径>
format:            wav | mp3 | ogg | mid | sf2 | ...
duration:          <秒>
editability:       KEEP_EDITABLE | ASSET_REPLACEABLE | BAKE
registry_resources: [{resource_id, provider, fetched}]            # 引用来源条目
license:           <许可证>
license_url:       <链接>
attribution_required: <bool>
commercial_use:    <bool>
cached:            <bool>
timeline_hint:     {preferred_start, preferred_duration, track_hint, audio_sync_point}
```

**License metadata 继承 Phase 4（§69）**：素材级 license 以 Registry 落盘为准
（`resources.jsonl` 的 `license` 块：`license_type/license_url/commercial_use/
attribution_required/derivatives_allowed/redistribution_allowed/license_review_required`）。
fetch 时必须做 license 过滤与逐条核对；许可不满足项目 `license_requirement`
（如 commercial use）时禁止入库。

## 2. SFX 搜索 Tier 顺序（§43）

搜索必须按 Tier 从高到低，命中即停；**不得跳过 Tier 0 直接搜全网**：

| Tier | Provider | 集成方式 | 认证 | 说明 |
|---|---|---|---|---|
| **0** | `@remotion/sfx` | 本地包式（PACKAGE，`npx remotion add @remotion/sfx`） | 无 | 官方即取即用，音量统一归一 -3dB peak，免署名；单条音效各自带 license（fetch 时逐条落 snapshot，license_model 标 MIXED） |
| **1** | Local / Cached Registry | LOCAL（registry `index/resources.jsonl` 种子 + 本地缓存） | 无 | 已索引/已缓存的本地 SFX，速度最快、可离线 |
| **2** | Freesound | 认证式（API，OAuth2/API_KEY） | **API_KEY** | 官方 API 搜索 + license 过滤 + 逐条核对；禁止爬站绕过认证 |
| **3** | Mixkit | WEBSITE（手动/半自动） | 无 | Stock SFX/Music，需人工触发下载，遵守 license terms |
| **4** | Generated SFX | Sony Woosh（PROVIDER / **EXPERIMENTAL**） | 无 | 兜底生成路线；见 `woosh_policy()`（§68）——**不作为默认**，License/commercial 不满足时禁用于商业项目 |

> 已有 Registry 条目（P5-5 核盘）：SFX 32 条（`remotion-sfx:sfx:*`，MIT，全 ACTIVE）、
> MUSIC 16 条（`cc0-music:music:*` CC0-1.0 + `openverse:music:*` CC0）、SOUNDFONT 1 条
> （`generaluser-gs:soundfont:generaluser-gs`，FREE_CUSTOM）。

## 3. Provider 类型与接入方式

### 3.1 `@remotion/sfx`（本地包式）
- 包级安装 `@remotion/sfx`（npm，Phase 5 已批准），URL 直读或包内引用。
- `fetch_capability=true`，对应 LIGHTWEIGHT 包级安装。
- 每条 SFX 独立 license：官网详情页逐条标注，fetch 时必须把单条 license snapshot 落盘。
- 归一化后 `producer=REMOTION`（声音资产），`source_provider=remotion-sfx`。

### 3.2 Freesound（认证式）
- 全部能力 `requires_authentication`：search / detail / preview / fetch 均需 API key（OAuth2）。
- **不绕过官方授权**：禁止爬站、禁止绕过认证获取下载。
- license 逐条混合（CC0 / CC-BY …），fetch 前必须 license 过滤与逐条核对。
- 需用户配置 key；未配置时该 Tier 输出 `requires_authentication` 并跳到下一 Tier。

### 3.3 Local SFX（本地 / 已缓存）
- 直接读 Registry 索引或本地缓存文件，秒级返回，可离线。
- 仅积累「用过的」资源（Registry 宪法 §2：本地不积累「可能用到的」）。

### 3.4 Mixkit（网站式，手动/半自动）
- Stock SFX / Music，web 页面试听 + 手动触发下载，遵守 license terms。

## 4. 与 Sound Engine 的衔接

- `modules/production/sound.py::sfx_search_plan()` 按上表 Tier 顺序产出搜索计划；
- 每个 Tier 的命中结果归一化为 Project Asset 后进 Manifest / Asset Registry；
- 素材的 `timeline_hint.audio_sync_point` 保留 Spec 的 sync 信息（frame/timestamp），
  供 Phase 7 时间线装配使用（引擎不直接碰时间线，§88）。
