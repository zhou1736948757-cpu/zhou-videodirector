# ZHOU_Videodirector — 复用地图（Reuse Map）

本文件是 `ZHOU_Videodirector` 的"外部参考实现 + 本机已装能力"总清单，与 `dependencies.yaml` 配对使用。

- 来源：总设计 v0.2 §68 / §69 / §70，Phase-1 Prompt §32 / §33。
- 信条：**Reuse → Adapt → Compose → Build Last**。开发任何主要模块之前，必须先查本文件（见 [external-capability-policy.md](external-capability-policy.md) 的 Major Capability Before Build Check，以及 [constitution.md](constitution.md) 原则 16）。
- `integration_mode` 只使用共享枚举：`EXTERNAL_SKILL | PROVIDER | KNOWLEDGE_ADAPTER | ARCHITECTURE_REFERENCE | TIMELINE_BACKEND | RESOURCE_PROVIDER`。
  - 当一个参考同时承担多个角色时，`integration_mode` 写主模式，`secondary_mode` 写从枚举内选的次要模式；`EXPERIMENTAL` 作为独立 flag 标记，不是模式。
  - v0.2 §68 原表中 `REFERENCE` 后缀（如 `RESOURCE_PROVIDER / REFERENCE`）按语义归入 `KNOWLEDGE_ADAPTER`（吸收其方法）或 `ARCHITECTURE_REFERENCE`（参考其结构），并在 `notes` 中保留原始表述。

---

## A. 外部参考实现总表（v0.2 §68 完整收录）

### A.1 速查表

| name | url | integration_mode | 主要借什么 | owner |
|---|---|---|---|---|
| watch-video-skill | https://github.com/Newuxtreme/watch-video-skill | EXTERNAL_SKILL | 视频下载/读取、抽帧、字幕与时间轴 | reference_analyzer |
| claude-video | https://github.com/bradautomates/claude-video | EXTERNAL_SKILL (+ARCHITECTURE_REFERENCE) | yt-dlp + ffmpeg + transcript + frames 轻量观看流程（备用） | reference_analyzer |
| remotion-video-director | https://github.com/BayramAnnakov/remotion-video-director | KNOWLEDGE_ADAPTER | 需求→Scenario→创意→Remotion Production 交互式导演流程 | creative_director |
| DirectorSKILL | https://github.com/wuwangzhang1216/DirectorSKILL | EXTERNAL_SKILL (+KNOWLEDGE_ADAPTER) | Beat、Blocking、Shot List、Camera、Keyframe/Video Prompt、Continuity、Edit Timeline | creative_director / video_prompt_builder |
| video-shotcraft | https://github.com/Vincentwei1021/video-shotcraft | KNOWLEDGE_ADAPTER | 产品视频 Shot Recipes、2.5D 运镜、节奏、Motion Preview、SFX/声音设计 | motion_design_layer |
| taste-skill | https://github.com/Leonxlnx/taste-skill | KNOWLEDGE_ADAPTER | Design Language、Motion Intensity、Density、反模板感规则 | style_director |
| OpenMontage | https://github.com/calesthio/OpenMontage | ARCHITECTURE_REFERENCE | Pipeline、Tool/Provider Registry、Agentic Video 能力编排 | architecture / subagent_coordinator |
| remotion-official | https://www.remotion.dev/docs/ai/skills | EXTERNAL_SKILL | 官方 Remotion Agent Skills 与 Best Practices | motion_engine |
| remotion-bits | https://github.com/av/remotion-bits | PROVIDER | Text、Transition、Particle、3D Scene 等组件与按需查找/获取模式 | motion_engine / registry-motion |
| onda | https://github.com/degueba/onda | PROVIDER | Copy-paste Remotion Motion Graphics | motion_engine / registry-motion |
| remotion-ui | https://github.com/riaz37/remotion-ui | PROVIDER | Caption、Scene、Transition、Composition 组件 | motion_engine / registry-motion |
| remocn | https://github.com/kapishdima/remocn | RESOURCE_PROVIDER | 可复制 Remotion Primitive 与确定性动画模式 | motion_engine / registry-motion |
| react-three-fiber | https://github.com/pmndrs/react-three-fiber | PROVIDER | React/Three.js 3D 渲染基础（+ Remotion Three） | three_d_layer |
| drei | https://github.com/pmndrs/drei | PROVIDER | React Three Fiber 高层 Helper | three_d_layer |
| gltfjsx | https://github.com/pmndrs/gltfjsx | PROVIDER | GLTF → React Three Fiber JSX Component | three_d_layer / registry-3d |
| poly-haven-api | https://github.com/Poly-Haven/Public-API | RESOURCE_PROVIDER | 3D/HDRI/Texture Asset Lists、Categories、单 Asset Metadata、按需下载 | registry-3d |
| pyJianYingDraft | https://github.com/GuanYixuan/pyJianYingDraft | TIMELINE_BACKEND | Python 生成剪映草稿、轨道、关键帧、字幕、音频 | timeline_manager |
| VectCutAPI | https://github.com/sun-guannan/VectCutAPI | TIMELINE_BACKEND (+ARCHITECTURE_REFERENCE) | Agent 视频编辑 API/Skills 与剪映/CapCut 草稿思路（备用/参考） | timeline_manager |
| pyCapCut | https://github.com/GuanYixuan/pyCapCut | TIMELINE_BACKEND | CapCut 草稿自动化方案（备用） | timeline_manager |
| remotion-sfx | https://www.remotion.dev/docs/sfx/ | RESOURCE_PROVIDER | 官方即取即用 SFX（Tier-0） | sound_design / registry-sfx |
| materia-sound-theme | https://github.com/nana-4/materia-sound-theme | RESOURCE_PROVIDER (+KNOWLEDGE_ADAPTER) | Google Material sound resources 的 UI / Product Sound Language | sound_design / registry-sfx |
| freesound-api | https://freesound.org/docs/api/resources_apiv2.html | RESOURCE_PROVIDER | API 搜索声音、Metadata、Tag、License | registry-sfx |
| mixkit | https://mixkit.co/ | RESOURCE_PROVIDER | Stock Video、Music、Sound Effects | resource_registry |
| openverse | https://github.com/WordPress/openverse | RESOURCE_PROVIDER | 开放授权图片与 Audio 聚合检索 | resource_registry |
| cc0-1.0-music | https://github.com/SoundSafari/CC0-1.0-Music | RESOURCE_PROVIDER | CC0/Public Domain 音乐集合（做索引，不整体 Clone） | registry-music |
| fluidsynth | https://github.com/FluidSynth/fluidsynth | PROVIDER | MIDI + SoundFont → Audio 渲染 | procedural_music_engine |
| generaluser-gs | https://github.com/mrbumpy409/GeneralUser-GS | RESOURCE_PROVIDER | GM/GS 通用音色库 | registry-soundfont |
| woosh | https://github.com/SonyResearch/Woosh | PROVIDER (+EXPERIMENTAL) | Text-to-Audio / Video-to-Audio SFX 生成（实验路线） | generative_sfx |
| ffmpeg / ffprobe | https://ffmpeg.org/ | PROVIDER | 视频 probe / 抽帧 / normalize / proxy / review 机器检测（Phase-6 运行时依赖，8.x homebrew） | external_visual |

### A.2 逐项明细（YAML 格式，与 `dependencies.yaml` 字段对应）

```yaml
watch-video-skill:
  url: https://github.com/Newuxtreme/watch-video-skill
  integration_mode: EXTERNAL_SKILL
  reuse:
    - video_ingestion
    - transcript
    - frame_extraction
    - temporal_alignment
  do_not:
    - rewrite_video_ingestion_from_zero
    - fork_skill_source
  owner: reference_analyzer
  notes: 让 Agent 真正"看见视频"；"为什么好看"的理解仍由 ZHOU_Videodirector 负责

claude-video:
  url: https://github.com/bradautomates/claude-video
  integration_mode: EXTERNAL_SKILL
  secondary_mode: ARCHITECTURE_REFERENCE
  reuse:
    - yt_dlp_download_flow
    - ffmpeg_frame_extraction
    - transcript_timeline
  do_not:
    - duplicate_when_watch_video_available
    - copy_entire_repository
  owner: reference_analyzer
  notes: Reference Analyzer 备用方案，轻量观看流程参考

remotion-video-director:
  url: https://github.com/BayramAnnakov/remotion-video-director
  integration_mode: KNOWLEDGE_ADAPTER
  reuse:
    - requirement_to_scenario_flow
    - creative_proposal_structure
    - remotion_production_phases
  do_not:
    - copy_entire_repository
    - make_it_the_master_workflow
  owner: creative_director

DirectorSKILL:
  url: https://github.com/wuwangzhang1216/DirectorSKILL
  integration_mode: EXTERNAL_SKILL
  secondary_mode: KNOWLEDGE_ADAPTER
  reuse:
    - beat_structure
    - blocking
    - shot_list
    - camera_language
    - keyframe_prompt
    - video_prompt
    - continuity_rules
    - edit_timeline_approach
  do_not:
    - inline_entire_skill_body
    - bypass_our_approval_gate
  owner: creative_director / video_prompt_builder
  notes: 调用其流程，导演决策与审批仍走 ZHOU_Videodirector

video-shotcraft:
  url: https://github.com/Vincentwei1021/video-shotcraft
  integration_mode: KNOWLEDGE_ADAPTER
  reuse:
    - shot_recipe_taxonomy
    - motion_language
    - camera_patterns
    - product_video_structure
    - sound_design_patterns
    - aesthetic_qa
  do_not:
    - copy_entire_repository
    - make_it_the_master_workflow
  owner: motion_design_layer

taste-skill:
  url: https://github.com/Leonxlnx/taste-skill
  integration_mode: KNOWLEDGE_ADAPTER
  reuse:
    - design_language_rules
    - motion_intensity_levels
    - density_control
    - anti_template_rules
  do_not:
    - copy_entire_repository
    - bake_single_taste_as_default
  owner: style_director
  notes: 遵守 No Default Style 原则，taste 是规则来源而非默认风格

OpenMontage:
  url: https://github.com/calesthio/OpenMontage
  integration_mode: ARCHITECTURE_REFERENCE
  reuse:
    - pipeline_architecture
    - tool_provider_registry_design
    - agentic_video_production_pattern
    - capability_orchestration
  do_not:
    - copy_implementation_code
    - copy_entire_repository
  owner: architecture / subagent_coordinator

remotion-official:
  url: https://www.remotion.dev/docs/ai/skills
  integration_mode: EXTERNAL_SKILL
  reuse:
    - official_agent_skills
    - remotion_best_practices
  do_not:
    - replace_with_third_party_wrappers_when_official_exists
    - vendor_all_docs_into_repo
  owner: motion_engine

remotion-bits:
  url: https://github.com/av/remotion-bits
  integration_mode: PROVIDER
  reuse:
    - text_components
    - transition_components
    - particle_components
    - 3d_scene_components
    - find_inspect_fetch_pattern
  do_not:
    - bulk_clone_components
    - bake_provider_specific_code
  owner: motion_engine / registry-motion

onda:
  url: https://github.com/degueba/onda
  integration_mode: PROVIDER
  reuse:
    - copy_paste_motion_graphics
    - component_patterns
  do_not:
    - bulk_clone_repo
    - assume_license_free
  owner: motion_engine / registry-motion

remotion-ui:
  url: https://github.com/riaz37/remotion-ui
  integration_mode: PROVIDER
  reuse:
    - caption_components
    - scene_components
    - transition_components
    - composition_components
  do_not:
    - bulk_clone_repo
    - replace_own_architecture_with_ui_library
  owner: motion_engine / registry-motion

remocn:
  url: https://github.com/kapishdima/remocn
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - remotion_primitives
    - deterministic_animation_patterns
  do_not:
    - bulk_copy_primitives
    - ignore_provenance
  owner: motion_engine / registry-motion

react-three-fiber:
  url: https://github.com/pmndrs/react-three-fiber
  integration_mode: PROVIDER
  reuse:
    - react_three_rendering_base
    - remotion_three_integration
  do_not:
    - rewrite_3d_rendering_layer
    - fork_framework
  owner: three_d_layer

drei:
  url: https://github.com/pmndrs/drei
  integration_mode: PROVIDER
  reuse:
    - r3f_high_level_helpers
    - camera_controls
    - environment_helpers
  do_not:
    - reimplement_helpers
    - vendor_whole_repo
  owner: three_d_layer

gltfjsx:
  url: https://github.com/pmndrs/gltfjsx
  integration_mode: PROVIDER
  reuse:
    - gltf_to_r3f_jsx_conversion
  do_not:
    - write_manual_gltf_importers
  owner: three_d_layer / registry-3d

poly-haven-api:
  url: https://github.com/Poly-Haven/Public-API
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - asset_lists
    - asset_categories
    - single_asset_metadata
    - on_demand_download
  do_not:
    - bulk_download_assets
    - ignore_license
  owner: registry-3d
  notes: Registry 只存元数据索引，素材按需获取（Level 2）

pyJianYingDraft:
  url: https://github.com/GuanYixuan/pyJianYingDraft
  integration_mode: TIMELINE_BACKEND
  reuse:
    - draft_generation
    - timeline_tracks
    - media_placement
    - basic_keyframes
    - subtitles
    - audio_tracks
    - simple_effects
  do_not:
    - fork_and_rewrite_editor
    - write_draft_format_from_zero_without_backend
  owner: timeline_manager
  notes: 第一版主 Timeline Backend；结构决策（timeline 结构/资产边界/可编辑边界）由 ZHOU_Videodirector 负责

VectCutAPI:
  url: https://github.com/sun-guannan/VectCutAPI
  integration_mode: TIMELINE_BACKEND
  secondary_mode: ARCHITECTURE_REFERENCE
  reuse:
    - agent_video_editing_api
    - jianying_capcut_draft_approach
  do_not:
    - fork_repo
    - duplicate_when_pyjianyingdraft_sufficient
  owner: timeline_manager

pyCapCut:
  url: https://github.com/GuanYixuan/pyCapCut
  integration_mode: TIMELINE_BACKEND
  reuse:
    - capcut_draft_automation
  do_not:
    - fork_repo
    - use_when_target_is_jianying_not_capcut
  owner: timeline_manager

remotion-sfx:
  url: https://www.remotion.dev/docs/sfx/
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - tier0_ready_sfx
    - remotion_sfx_api
  do_not:
    - download_entire_sfx_library
    - reimplement_sfx
  owner: sound_design / registry-sfx

materia-sound-theme:
  url: https://github.com/nana-4/materia-sound-theme
  integration_mode: RESOURCE_PROVIDER
  secondary_mode: KNOWLEDGE_ADAPTER
  reuse:
    - ui_product_sound_language
    - material_sound_resources
  do_not:
    - copy_audio_files_into_repo
    - ignore_license
  owner: sound_design / registry-sfx
  notes: 原表为 RESOURCE_PROVIDER / REFERENCE；REFERENCE 归入 KNOWLEDGE_ADAPTER（吸收其 UI 声音语言）

freesound-api:
  url: https://freesound.org/docs/api/resources_apiv2.html
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - api_sound_search
    - sound_metadata
    - tags
    - license_filtering
  do_not:
    - scrape_site_without_api
    - bulk_download
    - ignore_attribution
  owner: registry-sfx

mixkit:
  url: https://mixkit.co/
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - stock_video
    - music
    - sound_effects
    - footage_broll        # Phase 6：Mixkit Free License 可商用 B-roll 素材源
  do_not:
    - bulk_download
    - ignore_license_terms
  owner: resource_registry

openverse:
  url: https://github.com/WordPress/openverse
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - open_license_image_search
    - open_license_audio_search
    - footage_still_fallback # Phase 6：无合格 footage 时 IMAGE 类候选作 still_fallback（§77）
  do_not:
    - bulk_scrape
    - ignore_license
  owner: resource_registry

cc0-1.0-music:
  url: https://github.com/SoundSafari/CC0-1.0-Music
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - cc0_public_domain_music_index
    - music_metadata
  do_not:
    - clone_entire_corpus
    - treat_unverified_cc0_as_free_without_check
  owner: registry-music
  notes: 适合做索引而不是整体 Clone

fluidsynth:
  url: https://github.com/FluidSynth/fluidsynth
  integration_mode: PROVIDER
  reuse:
    - midi_to_audio_render
    - soundfont_playback
  do_not:
    - reimplement_midi_renderer
    - use_without_soundfont
  owner: procedural_music_engine

generaluser-gs:
  url: https://github.com/mrbumpy409/GeneralUser-GS
  integration_mode: RESOURCE_PROVIDER
  reuse:
    - gm_gs_general_soundfont
    - default_instrumentation
  do_not:
    - redistribute_soundfont_in_repo
    - use_outside_license_scope
  owner: registry-soundfont

woosh:
  url: https://github.com/SonyResearch/Woosh
  integration_mode: PROVIDER
  reuse:
    - text_to_audio_sfx
    - video_to_audio_sfx
  do_not:
    - rely_as_default_sfx
    - use_without_license_check
    - treat_as_production_stable
  owner: generative_sfx
  flags: [EXPERIMENTAL]

ffmpeg-ffprobe:
  url: https://ffmpeg.org/
  integration_mode: PROVIDER
  reuse:
    - video_probe
    - video_frame_extraction
    - normalize_reencode
    - proxy_generation
    - review_machine_checks
  do_not:
    - reimplement_probe_from_zero
    - blind_reencode_without_need
  owner: external_visual
  notes: Phase 6 运行时依赖（8.x，homebrew）；ingestion/review/proxy/normalize 全部走
         subprocess 调用，不内嵌库；缺失时模块给可读错误而非崩溃
  required_phase: 6
```

---

## B. 本机已装能力索引

以下为本机已存在、Phase 2+ 可直接调用的能力。Phase 1 只记账，不接入、不部署。

| 能力 | 路径 | 可用 Phase | integration_mode | 是否需部署 |
|---|---|---|---|---|
| remotion-best-practices | `~/.agents/skills/remotion-best-practices/SKILL.md` | Phase 5 起（Remotion 生产）+ Phase 2（技术方案评估可先参考） | EXTERNAL_SKILL | 否（已装） |
| Remotion 系列 skill（best-practices / captions / create / docs / interactivity / maps / markup / multimedia / render / saas / upgrade，共 11 个） | `~/.agents/skills/remotion-*/SKILL.md` | Phase 5 起 | EXTERNAL_SKILL | 否（已装） |
| video-analyst（本地视频分析：FFmpeg 预处理、ASR、抽帧、报告） | `~/.agents/skills/video-analyst/SKILL.md` | Phase 2（Reference Analysis）+ Phase 8（QA） | EXTERNAL_SKILL | SKILL.md 规格已装；CLI 脚本未安装（`video-analyst` 命令不可用，2026-08-16 核盘） |
| ds-vision-skill（视觉补盲：图片理解 / OCR / 文档解析） | `~/.agents/skills/ds-vision-skill/` | Phase 2（参考抽帧理解）+ Phase 6（AI Video 素材核验）+ Phase 8（Visual QA） | EXTERNAL_SKILL | 否（已装）；图片会上传云端服务，敏感内容需用户确认 |
| human-voice（TTS / voiceover） | `/Users/mac/skills/human-voice/` | Phase 5 起（Voice-over 资产制作） | EXTERNAL_SKILL | 否（已装） |
| yt-dlp 二进制 | `/Users/mac/skills/yt-dlp`（exec） | Phase 2（参考视频下载，配合 watch-video / claude-video 流程）+ Phase 6（真实素材获取） | PROVIDER | 否（已装） |
| computer-use（桌面窗口 / 桌面应用控制） | `~/.agents/skills/computer-use/SKILL.md` | Phase 7（剪映桌面端辅助编辑 / 验收）+ Phase 8（QA / E2E） | EXTERNAL_SKILL | 否（已装） |
| ffmpeg / ffprobe（8.x，homebrew） | `/opt/homebrew/bin/ffmpeg`、`/opt/homebrew/bin/ffprobe` | Phase 6 起（probe / normalize / proxy / review 机器检测） | PROVIDER | 否（已装） |

```yaml
remotion-best-practices:
  path: ~/.agents/skills/remotion-best-practices/SKILL.md
  integration_mode: EXTERNAL_SKILL
  available_phases: [2, 5]
  deployment_required: false

remotion-skill-family:
  path: ~/.agents/skills/remotion-{best-practices,captions,create,docs,interactivity,maps,markup,multimedia,render,saas,upgrade}/SKILL.md
  integration_mode: EXTERNAL_SKILL
  available_phases: [5, 6, 7, 8]
  deployment_required: false
  notes: 共 11 个官方 Remotion 系列 skill

video-analyst:
  path: ~/.agents/skills/video-analyst/SKILL.md
  integration_mode: EXTERNAL_SKILL
  available_phases: [2, 8]
  deployment_required: true
  notes: SKILL.md 规格已装；CLI 脚本未安装（video-analyst 命令不可用，2026-08-16 核盘）。
         Runtime Visual Capability Probe 会如实报 video_analyst_cli=UNINSTALLED_SKILL；
         Tier B 下用 ffmpeg 抽帧 + mimo-vision.sh 视觉桥替代，使用前必须探测，不可假设 CLI 可用

ds-vision-skill:
  path: ~/.agents/skills/ds-vision-skill/
  integration_mode: EXTERNAL_SKILL
  available_phases: [2, 6, 8]
  deployment_required: false
  notes: 视觉补盲；图片内容会上传云端，敏感内容需用户确认

human-voice:
  path: /Users/mac/skills/human-voice/
  integration_mode: EXTERNAL_SKILL
  available_phases: [5, 6, 7]
  deployment_required: false
  notes: TTS / voiceover 资产制作

yt-dlp:
  path: /Users/mac/skills/yt-dlp
  integration_mode: PROVIDER
  available_phases: [2, 6]
  deployment_required: false
  notes: 二进制可执行文件；参考视频与素材下载

computer-use:
  path: ~/.agents/skills/computer-use/SKILL.md
  integration_mode: EXTERNAL_SKILL
  available_phases: [7, 8]
  deployment_required: false
  notes: 桌面应用控制；剪映桌面端辅助编辑与 QA

ffmpeg-ffprobe:
  path: /opt/homebrew/bin/ffmpeg + /opt/homebrew/bin/ffprobe
  integration_mode: PROVIDER
  available_phases: [6, 7, 8]
  deployment_required: false
  notes: Phase 6 运行时依赖（8.x，homebrew）；ingestion/review/proxy/normalize 的 probe
         与抽帧基础；详见 docs/external-visual.md §6/§11
```

---

## C. Phase 2-8 路线图映射

简表：每个 Phase 使用哪些外部参考与本机能力。Phase 1 不接入任何外部能力，只建立结构（本文件即 Phase 1 产物之一）。

| Phase | 用途 | 外部参考（integration_mode） | 本机能力 |
|---|---|---|---|
| Phase 2 — Director Pipeline | Reference Analysis + Creative / Style / Sound / Editorial / Storyboard | watch-video-skill（EXTERNAL_SKILL）、claude-video（EXTERNAL_SKILL，备用）、remotion-video-director（KNOWLEDGE_ADAPTER）、DirectorSKILL（EXTERNAL_SKILL / KNOWLEDGE_ADAPTER）、video-shotcraft（KNOWLEDGE_ADAPTER）、taste-skill（KNOWLEDGE_ADAPTER） | video-analyst、ds-vision-skill、yt-dlp、remotion-docs |
| Phase 3 — Shot / Layer Router | 路由指标与 Layer 分解设计 | video-shotcraft（KNOWLEDGE_ADAPTER）、taste-skill（KNOWLEDGE_ADAPTER）、OpenMontage（ARCHITECTURE_REFERENCE） | 无新增（知识来自上述 Adapter） |
| Phase 4 — Resource Registry | Registry 元数据索引与 find/detail/preview/fetch | remotion-bits（PROVIDER）、onda（PROVIDER）、remotion-ui（PROVIDER）、remocn（RESOURCE_PROVIDER）、poly-haven-api（RESOURCE_PROVIDER）、remotion-sfx（RESOURCE_PROVIDER）、freesound-api（RESOURCE_PROVIDER）、mixkit（RESOURCE_PROVIDER）、openverse（RESOURCE_PROVIDER）、cc0-1.0-music（RESOURCE_PROVIDER）、generaluser-gs（RESOURCE_PROVIDER） | ds-vision-skill（素材预览核验） |
| Phase 5 — Motion / 3D / Sound Engine | 产出真正资产 | remotion-official（EXTERNAL_SKILL）、remotion-bits / onda / remotion-ui（PROVIDER）、video-shotcraft（KNOWLEDGE_ADAPTER）、react-three-fiber / drei / gltfjsx（PROVIDER）、fluidsynth（PROVIDER）、generaluser-gs（RESOURCE_PROVIDER）、materia-sound-theme（RESOURCE_PROVIDER） | remotion 系列 skill（11 个）、remotion-best-practices、human-voice |
| Phase 6 — Generative / Footage Pipeline | AI Video 与真实素材管线 | DirectorSKILL（KNOWLEDGE_ADAPTER，Video Prompt 部分）、mixkit / openverse / cc0-1.0-music（RESOURCE_PROVIDER） | yt-dlp、ds-vision-skill（素材视觉核验）、video-analyst、ffmpeg/ffprobe（8.x homebrew，probe/normalize/proxy/review 运行时依赖） |
| Phase 7 — Editable Timeline | 剪映可编辑草稿生成 | pyJianYingDraft（TIMELINE_BACKEND，主）、VectCutAPI（TIMELINE_BACKEND / ARCHITECTURE_REFERENCE，备用）、pyCapCut（TIMELINE_BACKEND，备用） | computer-use（剪映桌面端验收 / 辅助编辑） |
| Phase 8 — Subagents + QA + E2E | 并行生产与四层 QA | OpenMontage（ARCHITECTURE_REFERENCE）、woosh（PROVIDER / EXPERIMENTAL，实验性 SFX） | ds-vision-skill（Visual QA）、video-analyst（QA）、computer-use（E2E） |

---

## 附：文档一致性约定

- 本文件中的 `integration_mode` 与 [external-capability-policy.md](external-capability-policy.md) 的 6 种模式定义一一对应。
- `dependencies.yaml` 以机器可读形式保存同源数据（name / url / integration_mode / role / status / reuse / do_not / license_notes / required_phase），本文件是它的可读注释版。
- owner 字段对应总设计 v0.2 §61 工程结构中的模块（如 `reference_analyzer`、`timeline_manager`、`motion_design_layer`）。
