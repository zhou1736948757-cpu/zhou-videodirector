# adapter — three-production（R3F / Drei / Remotion Three 接入规范）

```text
name:    three-production
adapter: remotion-three
phase:   5 (P5-4)
route:   THREE_D
owner:   modules/production/threed.py
```

## 1. 定位（Phase-5 §85）

本 adapter 是 `THREE_D` 路由的执行层，负责把 **THREE_D_SPEC**（由
`modules/production/threed.py` 生成）翻译成可渲染的 React Three Fiber 场景，
最终产出**归一化 3D Asset**。

```text
THREE_D_SPEC ──► R3F / @remotion/three 场景 ──► 渲染 ──► 归一化 Asset
   （决策）          （实现）                    （执行）      （Asset Contract）
```

边界（本 adapter 不做）：

- 不做导演决策（spec 由 threed.py / Production Planner 产出，本层只执行）。
- 不做建模软件 / Blender 资产制作；模型一律走 Registry（Poly Haven / Kenney 等）。
- 不做物理引擎编排以外的模拟（organic/chaotic 模拟 → `PRODUCTION_CONFLICT`，
  见 `modules/production/threed.py::physics_conflict_check`）。
- 不做 AI 生成视频（GENERATIVE_VIDEO 是独立路由）。
- 不做最终时间线装配（那是 Phase 7 pyJianYingDraft 的事）。
- 不重造 Helper：相机控制、Environment、OrbitControls、gltf loader 全部用
  R3F / Drei / gltfjsx 现成能力（总设计 §37「已有 Motion 能力尽量复用」）。

## 2. 技术栈与依赖清单（npm，已批准安装）

| 包 | 用途 | 状态 |
|---|---|---|
| `@remotion/three` | 将 Three.js 场景接入 Remotion 渲染（`ThreeCanvas`） | 已批准 |
| `three` | 3D 渲染核心 | 已批准 |
| `@react-three/fiber` | React 声明式 Three.js（场景 JSX） | 已批准 |
| `drei` | R3F 高层 Helper（`Environment`/`ContactShadows`/`OrbitControls`/`useGLTF`…） | 已批准 |
| `@react-three/postprocessing` | 后处理（bloom / DoF / vignette / CA） | 随 `postprocessing_plan` 按需启用 |

模型转换工具：

| 工具 | 用途 |
|---|---|
| `npx gltfjsx` | 把 GLTF/GLB 转成可复用 `<Model/>` React 组件（pmndrs/gltfjsx，PROVIDER） |

依赖接入方式遵循总设计 §68 / Reuse Map：`@remotion/three`、`three`、R3F、Drei、
gltfjsx 均为 `PROVIDER` 复用，**禁止重写渲染核心 / 相机控制 / gltf 加载器**。

## 3. 模型管线（Phase-5 §32）

```text
Registry FIND (THREE_D_MODEL / TEXTURE / HDRI)
   │
   ▼
Registry FETCH（approved，按 License / 体积）
   │
   ▼
复杂度判定（§32：视复杂度）
   ├── 简单模型（primitive 可拼，一次性）→ 直接 R3F JSX 拼装，不建长期框架
   └── 复杂模型（产品模型 / 爆炸图）→ npx gltfjsx 转 <Model/> 组件
   │
   ▼
材质 / 纹理 / HDRI 装配（spec.material / spec.texture / spec.hdri）
   │
   ▼
R3F 场景 + @remotion/three ThreeCanvas
   │
   ▼
Preview First（§39/§89-91）→ 批准 → 高质量渲染
```

**关键规则（§32）**：

- 一次性简单模型（立方体 / 球体 / 圆柱 + 简单材质即可满足 shot）**不建长期框架**：
  直接 primitives 拼装，不引入 gltfjsx、不创建可复用组件目录。
- 只有可能被多 shot / 多项目复用的模型才走 gltfjsx 转组件并进入 Registry 索引。
- `BUILD_NEW`（自建模型）必须记录 `build_reason`（现有资源为何不满足），
  并经过 Execution Approval（总设计 §50：3D 构建需先说明再执行）。

## 4. THREE_D_SPEC → R3F 映射

spec 字段（§29 全字段）由 `modules/production/threed.py::build_threed_spec` 产出，
本 adapter 负责逐字段落到 React 组件：

| THREE_D_SPEC 字段 | R3F 落地 |
|---|---|
| `model.source` / `model.reuse_mode` | `useGLTF`（drei）或 primitives 拼装 |
| `scale` / `position` / `rotation` | `<group scale position rotation>` |
| `material` | `<meshStandardMaterial>` / `<meshPhysicalMaterial>`（metalness / roughness / clearcoat） |
| `texture` | `useTexture`（drei），分辨率见 `texture_resolution` |
| `lighting` | `<directionalLight key/fill/rim>`（intensity / position / color，温度用 color 换算） |
| `hdri` | `<Environment preset or files>`（drei Environment） |
| `camera`（position/target/fov/lens/movement/duration/easing） | `@remotion/three ThreeCanvas camera` + 帧驱动相机动画 |
| `camera_path` | 关键帧路径（frame-driven，不用 wall-clock） |
| `animation` | 帧驱动（`useCurrentFrame()`），seeded 噪声/粒子 |
| `depth_of_field` | `@react-three/postprocessing DepthOfField` |
| `postprocessing` | `EffectComposer` + Bloom / Vignette / ChromaticAberration（按 `postprocessing_plan` 开关） |
| `background` / `alpha` | `gl={{ alpha: spec.alpha, preserveDrawingBuffer: true }}`，alpha 时背景透明 |
| `performance_budget` | LOD 切换 / 纹理分级（`texture_resolution`） |
| `lod` | 距离/相机缩放驱动的降级（远距用低模） |
| `audio_sync_points` | `useCurrentFrame` 处触发动画节奏（帧换算，保证可编辑同步） |

## 5. 归一化输出契约

每次渲染产出必须携带完整 **Asset Contract** 元数据（总设计 §32 / asset.schema.json
Phase-5 增补），AI 与剪映都能理解「这是什么、何时用、可否替换」：

```yaml
asset_id: A###            # 由 Production Planner / Asset Manager 分配
type:     3D_ELEMENT      # 或 TRANSPARENT_OVERLAY / BACKGROUND / PARTICLE_LAYER
producer: THREE_D
request_id: PR-###
shot_id:   S###
layer_id:  S###-L##
purpose:   3D product orbit reveal
format:    mov              # (alpha) / mp4 / webm；GLB 源单独保留
alpha:     true|false
fps:       30
resolution: 1920x1080       # 按 Render Profile
duration:  5.0
timeline_start: 00:00:00.000
replaceable: true           # THREE_D 默认 ASSET_REPLACEABLE
version:  v1
render_profile: STANDARD    # PREVIEW | STANDARD | HIGH | FINAL
source_kept: true           # R3F 工程 / GLB / spec 必须保留（可重新渲染）
```

### Render Profile（4 级，Phase-5 §99）

| Profile | 分辨率 | 用途 | Phase 5 内可用 |
|---|---|---|---|
| `PREVIEW` | 1280×720 | Preview First 低清确认 | 是 |
| `STANDARD` | 1920×1080 | 默认生产 | 是 |
| `HIGH` | 项目分辨率 | 高质量产出 | 是（Phase 5 最高到 HIGH） |
| `FINAL` | 项目分辨率 | 交付级 | 否（Phase 5 禁止） |

Preview 与 final **文件分离**（`A###_preview.mp4` vs `A###_v1.mov`），互不覆盖。

### Editability（3 级）

`BAKE` / `KEEP_EDITABLE` / `ASSET_REPLACEABLE`。THREE_D 默认
`ASSET_REPLACEABLE`（渲染结果整体可重渲替换）；同 continuity_group 连续运动
建议 `BAKE` 为单一资产（总设计 §31）。

### Reuse Mode（4 级）

`USE_AS_IS` / `ADAPT` / `COMPOSE` / `BUILD_NEW`（Registry resource-selection
契约）。`BUILD_NEW` 必须附 `build_reason`。

## 6. 确定性（Phase-5 §33-34）

- 所有动画 **frame-driven**：用 `useCurrentFrame()`，禁止 wall-clock / `Date.now()` /
  `performance.now()`。
- 粒子 / 噪声 / 抖动必须 **seeded**：`seeded_random(seed, n)`（threed.py），
  重复 render 逐帧一致。
- 渲染前跑 `determinism_check(scene_desc)`，有任何未 seed 随机源即告警并阻塞。
- 种子写入 THREE_D_SPEC 的 `animation.seed`，版本化保存。

## 7. QA 钩子（Phase-5 §101 / §98）

渲染后由 `modules/production/threed.py` 提供检查清单：

- `performance_budget_check(model_meta, budget)`：poly 数 / 纹理体积 / 内存 /
  单帧渲染时间 / 缺纹理 / shader 错误 / 相机 near-far 裁剪 / z-fighting /
  锯齿 / 帧稳定性。
- `determinism_check(scene_desc)`：非确定性来源检测。
- `physics_conflict_check(spec)`：organic/chaotic 模拟 → `PRODUCTION_CONFLICT`，
  建议转 GENERATIVE_VIDEO / HYBRID（§35，不偷偷改设计）。

## 8. 参考实现（总设计 §68）

| 能力 | 参考 | 接入方式 | 借用 |
|---|---|---|---|
| 3D 渲染核心 | pmndrs/react-three-fiber + Remotion Three | PROVIDER | React/Three.js 渲染基础 |
| 3D Helpers | pmndrs/drei | PROVIDER | Environment / OrbitControls / useGLTF / useTexture |
| GLTF → React | pmndrs/gltfjsx | PROVIDER | GLTF/GLB → JSX 组件 |
| 模型 / HDRI / 纹理 | Poly Haven（CC0）、Kenney（CC0） | RESOURCE_PROVIDER | THREE_D_MODEL / HDRI / TEXTURE 按需下载 |

Registry 资源 id 约定（scripts/registry.py + registry/index/resources.jsonl）：

```text
polyhaven:three-d-model:<Slug>    # 3D 模型
polyhaven:hdri:<slug>             # HDRI 环境（studio_small_01 等）
polyhaven:texture:<slug>          # PBR 纹理
kenney:pack:<slug>                # Kenney CC0 资产包
```

## 9. 不做什么（Avoid List）

- 不默认最高质量（2K/4K/8K 按 shot 推荐 + Approval Gate，禁止「8K=always better」，
  见 `recommend_texture_resolution`）。
- 不为普通镜头过度工程（简单模型不建组件框架）。
- 不做无 seed 的随机、不做 wall-clock 动画。
- 不越过 `PRODUCTION_CONFLICT` 偷偷改设计。
- 渲染失败 3 次（normal fix → targeted fix → alternative approach）即
  `BLOCKED` 上报，不无限循环（Phase-5 §93-94）。
