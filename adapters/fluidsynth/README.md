# FluidSynth Adapter（适配器）

> Phase 5（§53-57 / §86）· 定位：**MIDI + SoundFont → WAV** 的真实渲染入口。
>
> 上游：MIDI Composer（Sound Engine）→ **本 adapter** → SoundFont → WAV → Project Asset。

## 1. 定位与边界

- **做什么**：检测 `fluidsynth` 是否存在、构建渲染命令行、执行渲染、记录每次渲染命令。
- **不做什么**：
  - **不自己实现 SoundFont Synthesizer / MIDI 播放器**（§54；reuse-map：fluidsynth
    `do_not: reimplement_synth_engine / reimplement_midi_renderer`）。FluidSynth 是外部
    `PROVIDER`，我们只做薄适配层。
  - **缺席时绝不伪造 WAV**：fluidsynth 不可用 → 返回 `DEPENDENCY_MISSING`
    （`required/installation/impact`，§95 报告格式），Procedural Music 标记
    `procedural music unavailable`，由上游走审批/降级，不产出假文件。
  - **不下载/管理 SoundFont**：SoundFont 走 Registry（`generaluser-gs:soundfont:generaluser-gs`）
    的 `fetch` 门（License + Approval），本 adapter 只消费本地 `.sf2` 路径。
  - 不做音频后期（EQ / reverb / ducking 是 Sound Engine 的 editing plan，见
    `modules/production/sound.py`）。

## 2. 依赖（已批准，见 dependencies.yaml）

| 依赖 | 来源 | 安装 | License | 用途 |
|---|---|---|---|---|
| FluidSynth | Homebrew（**已批准 brew 安装**） | `brew install fluidsynth` | LGPL | MIDI+SoundFont → WAV 渲染 |
| GeneralUser-GS v2.0.3 | GitHub mrbumpy409/GeneralUser-GS（**已批准下载**） | 单文件 `GeneralUser-GS.sf2`（约 30MB） | FREE_CUSTOM（license snapshot 下载时落盘；registry 标 FREE_CUSTOM / 原 Phase-4 曾标 UNKNOWN → **下载时记录 license snapshot**） | 默认 GM/GS 音色库（261 presets + 13 drum kits） |

> GeneralUser-GS 许可证：FREE_CUSTOM，`commercial_use=true, attribution_required=false,
> derivatives_allowed=true`（registry `resources.jsonl` 该条 `license` 块已落盘）。
> 引用依赖（`distribution`）注意 LGPL 分发约束与 `redistribute_soundfont_in_repo` 禁止项。

## 3. API（adapter.py，stdlib only）

```python
from adapters.fluidsynth.adapter import fluidsynth_available, render_midi

fluidsynth_available()  # -> bool    shutil.which("fluidsynth") 检测

render_midi("a.mid", "GeneralUser-GS.sf2", "a.wav",
            sample_rate=44100, dry_run=True, record_path="render.log.jsonl")
```

`render_midi` 返回 dict（节选）：

```json
{
  "status": "dry_run",                     // DEPENDENCY_MISSING | INPUT_MISSING | dry_run | ok | failed
  "command": ["fluidsynth", "-ni", "-F", "a.wav", "-r", "44100", "GeneralUser-GS.sf2", "a.mid"],
  "command_str": "fluidsynth -ni -F a.wav -r 44100 GeneralUser-GS.sf2 a.mid",
  "input": "a.mid", "output": "a.wav", "soundfont": "GeneralUser-GS.sf2",
  "sample_rate": 44100,
  "render_status": "pending",              // pending | ok | failed
  "record": { "command": ..., "input": ..., "output": ..., "soundfont": ..., "render_status": ..., "logged_at": ... }
}
```

- `dry_run=True`（默认）：只返回 command，**不执行、不产生任何文件**。
- `dry_run=False`：执行渲染；`render_status` 为 `ok` / `failed`，失败带 `returncode/stdout/stderr`。
- fluidsynth 缺席 → `{status:'DEPENDENCY_MISSING', required:'fluidsynth',
  installation:'brew install fluidsynth', impact:'procedural music unavailable'}`（§95）。
- 输入文件不存在 → `INPUT_MISSING`，不执行。
- 重试：单次尽力；失败由上游 `retry_policy`（3 次 → BLOCKED，§93-94）处理。

## 4. 命令记录契约（§86）

每次调用（无论 dry-run 与否）生成一条 `record`，包含固定五要素：

```text
command        实际构建的 argv（list）
input          MIDI 输入路径
output         WAV 输出路径
soundfont      SoundFont 路径
render_status  pending / ok / failed / DEPENDENCY_MISSING / INPUT_MISSING
```

- 传入 `record_path` 时，`record` 追加写入 JSONL（一行一条，可审计、可核盘）。
- 上游 Manifest 的资产 `sources` / 生产日志引用该记录，保证「这次渲染用了哪个
  SoundFont、哪个 MIDI」可追溯。

## 5. 接入流程

```text
MIDI Composer（Sound Engine，modules/production/sound.py）
        │  产出 .mid + 声明 soundfont registry id
        ▼
render_midi(midi, soundfont, out_wav, dry_run=True)   # 先干跑看命令
        │  批准后
        ▼
render_midi(..., dry_run=False, record_path=<project>/production/render.log.jsonl)
        ▼
WAV 进入 Project Asset（producer=FLUIDSYNTH，editability=KEEP_EDITABLE，MIDI 源保留）
```
