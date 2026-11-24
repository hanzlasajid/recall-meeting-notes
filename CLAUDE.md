# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

**Recall**: a cross-platform (Windows + macOS) desktop tool that turns a recorded call (usually a screen-shared Teams/Zoom meeting) into:

1. subtitles (`.srt`) and a timestamped transcript, made **locally** with Whisper
2. key screenshots, one per distinct screen, matched to what was said
3. a written meeting report, made by Claude through the Anthropic API (or, with no API key, by a local vision model in Ollama), as `report.md` and a self-contained `report.html`

Users start it by dragging a video onto a launcher icon, or by double-clicking the icon and using a file picker. A Tk settings window shows the detected hardware and the recommended Whisper model, which the user can override.

## Pipeline (`recall/__main__.py` → `process()`)

```
detect hardware → choose model → transcribe → extract frames → (Claude report | local Ollama report | prompt file) → render HTML
```

Output goes to `<video stem>_notes/` next to the video:
`transcript.txt|json`, `subtitles.srt` (a copy is also saved next to the video), `frames/`, `frames.json|md`, `analysis_prompt.md`, `report.md`, `report.html`.

`reuse=True` skips transcription and frame extraction if `transcript.json` / `frames.json` already exist. Screenshots the user deleted from `frames/` are dropped before the report step.

## Layout

| Path | Role |
| --- | --- |
| `recall/hardware.py` | CPU/RAM/GPU detection (`detect()`), model options + recommendation (`choices()`), `explain()` |
| `recall/transcribe.py` | `prepare_environment()` (CUDA DLL dirs, PyAV patch), faster-whisper / mlx-whisper backends, GPU→CPU fallback, subtitle cue builder, outputs |
| `recall/frames.py` | screen-change detection with PyAV + numpy, screenshot grabbing, transcript alignment |
| `recall/analyze.py` | prompt building, image selection/encoding, streaming Claude call, manual prompt file |
| `recall/local_llm.py` | no-key fallback: `recommend(hw)` picks a Qwen3-VL size, `missing()`, installs Ollama (winget / Homebrew cask), starts `ollama serve`, pulls, streams the report over `127.0.0.1:11434` (stdlib only) |
| `recall/report_prompt.md` | **the report format spec** (system prompt). Edit this to change the report |
| `recall/render.py` | Markdown → HTML (tables, task lists, Mermaid, inlined images, captions) |
| `recall/ui.py` | Tk file picker + settings window, console fallbacks, opening the result |
| `recall/config.py` | `~/.recall/config.json` (API key only if "remember", language, vocabulary, report model, `local_model` override); reads the old `~/.meetingnotes/config.json` once |
| `Recall.bat`, `setup_windows.bat` | Windows launcher (drag-drop via `%*`) and setup (Python via winget, `.venv`, CUDA libs, desktop shortcut) |
| `Recall.command`, `setup_mac.command`, `mac/Recall.applescript` | macOS launcher, setup (builds `Recall.app` with `osacompile`), droplet source |
| `tests/` | offline tests; `tests/fake_anthropic_pkg/` stubs the Anthropic API, `_FakeOllama` in `run_tests.py` stubs Ollama's HTTP API |

## Commands

```bash
python -m recall --hardware                 # detection + recommendation only
python -m recall VIDEO [--no-gui] [--model cuda:large-v3-turbo|mlx:large-v3-turbo|cpu:small]
                             [--report sonnet|opus|local|none] [--language en] [--fresh]
python tests/run_tests.py                          # offline tests (no GPU, no API key, no video needed)
```

## Model recommendation rules (`hardware.choices`)

- NVIDIA and CUDA usable: VRAM ≥ 10 GB → `large-v3`; ≥ 2.5 GB (or unknown) → `large-v3-turbo`; otherwise `small`. Compute type `float16` if VRAM ≥ 4.5 GB, else `int8_float16`.
- Apple Silicon with `mlx_whisper` installed: RAM ≥ 8 GB → `mlx-community/whisper-large-v3-turbo`, else small.
- CPU only (`int8`): RAM ≥ 16 GB and cores ≥ 8 → `medium`; RAM ≥ 8 GB and cores ≥ 4 → `small`; else `base`.
- CPU options are always listed as fallbacks.

Reference point, measured on the author's laptop (Core Ultra 7 356H, 16 cores, 31.5 GB, RTX PRO 1000 Blackwell 8 GB): a 47-minute call took about 4 min with `large-v3-turbo` on CUDA, and 9 min with `small` on the CPU. Screenshot extraction took about 1 min.

## Local report (no API key)

- With no key, Start asks: Yes = local AI, No = prompt file only, Cancel = back. Choosing "Local AI" directly asks before installing anything. `--no-gui` never installs unless `--report local` is passed.
- `local_llm.recommend`: Apple Silicon uses 70 % of RAM as the budget (≥ 28 GB → 30b-a3b, ≥ 10 → 8b, ≥ 5 → 4b, else 2b); NVIDIA: VRAM ≥ 24 → 30b-a3b, ≥ 6 with RAM ≥ 16 → 8b, ≥ 4 → 4b; processor only: RAM ≥ 16 → 4b, else 2b. Always the `-instruct` tags, which answer directly (the `-thinking` variants add a reasoning pass first).
- Screenshots sent: 6/8/12/16 for 2b/4b/8b/30b, resized to 1024 px. `num_ctx` is sized from the prompt (16k-64k).
- If Recall started `ollama serve`, it stops it afterwards to free memory. The model stays downloaded in `~/.ollama/models`.

## Gotchas (learned the hard way, keep these)

- **PyAV ≥ 15 removed `metadata_errors`**, which faster-whisper 1.2.x still passes to `av.open()` → `TypeError`. `prepare_environment()` monkeypatches `av.open` to drop it. Call `prepare_environment()` before importing faster_whisper or using av.
- **Windows CUDA:** ctranslate2 4.x needs cuBLAS 12 + cuDNN 9. Install them with `pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"`, then add every `site-packages/nvidia/*/bin` with `os.add_dll_directory` **and** prepend it to `PATH` (cuDNN is loaded lazily).
- **faster-whisper `segments` is a generator**: transcription (and CUDA errors) happen while iterating, so the GPU→CPU fallback must wrap the iteration.
- **mlx-whisper needs ffmpeg** for file input, so we decode with `faster_whisper.audio.decode_audio` (PyAV) and pass a numpy array.
- **Windows Store `python` stub:** `where python` finds a fake alias that opens the Store. Probe with `py -3.x --version`, or a known path. Paths contain spaces (`C:\Users\first last\...`), so quote them: `set PY="..."`.
- **Line endings:** `.bat` must be CRLF and `.command`/`.applescript` must be LF (see `.gitattributes`). Uploading through the GitHub web UI loses exec bits, so the docs say to run `bash setup_mac.command` once (it `chmod +x`'s), and the droplet calls `bash ./Recall.command`.
- **HF Hub on Windows:** symlink warnings are harmless; `HF_HUB_DISABLE_SYMLINKS_WARNING=1`.
- The Tk file picker uses `~/Videos` on Windows and `~/Movies` on macOS.
- **Homebrew 7 "ask mode"** stops `brew install` at a `[y/n]` prompt in the Terminal. Use `HOMEBREW_NO_ASK=1` (older brews ignore it; `--yes` would error there). Install the `ollama-app` cask: the `ollama` formula pulls in python@3.15 + mlx.
- **winget** prompts for source agreements on first use; pass `--accept-source-agreements --accept-package-agreements` when the user already agreed in our dialog.
- **Tk windows started from Terminal / a .bat open behind it.** `ui._bring_forward` lifts and focuses them. After closing, `ui._close` runs `root.update()` before `destroy()`, or the window stays painted (frozen) for the whole run.
- **macOS asks once "Recall wants to control Terminal"** the first time a file is dropped on the droplet. Only the user can allow it.
- **Terminal drag-and-drop** pastes paths with backslash-escaped spaces; `ui.clean_typed_path` handles it (shlex on macOS, quotes only on Windows).

## Report format contract

`report_prompt.md` defines the sections, in this order: Title, info line, Summary, TL;DR, System diagram (Mermaid, only if relevant), Context (tables where useful), Action items (per participant, `- [ ]` with timestamps), Requirements & details, Walkthrough (`### mm:ss-mm:ss · title` + at most one screenshot per phase, using exact `frames/...` paths), Glossary (table), Open questions.

`render.py` relies on: fenced ```mermaid blocks, `- [ ]`/`- [x]` items, `![caption](frames/...)` images. If you change the format, keep these or update `render.py`.

Report models: `analyze.REPORT_MODELS` maps `sonnet` → `claude-sonnet-5-5` and `opus` → `claude-opus-5-5`. Streaming, `max_tokens=16000`, up to `max_images` (default 40) screenshots, evenly sampled, resized to 1280 px JPEG.

## Status

Tested:
- hardware recommendations for 7 simulated machines, local-model picks for 7 machines
- the cue builder
- the report path end to end, with a stubbed API and real screenshots (40 images sent, HTML with Mermaid, tasks, inlined images)
- the local report path against a fake Ollama server (model, system prompt, image count, context size, CLI `--report local`, no-key hint)
- the CLI `--no-gui` flow with reuse; deleted screenshots being excluded
- the transcription and frame code: it ran on Windows + CUDA in an earlier single-file version
- **macOS, Apple Silicon (M4 Pro, 24 GB, Homebrew Python 3.12 + python-tk), 24 Nov 2026:** `setup_mac.command`, building `Recall.app`, dropping a video on it (Terminal opens), the Tk settings window, the no-key dialog → Ollama cask install → `qwen3-vl:8b-instruct` download → local report (17 s clip: 6.5 min total incl. 232 MB app + 6.2 GB model; report itself 0.6 min), mlx-whisper (all `MLX_REPOS` resolve, word timestamps), the `cpu:` path, the console fallback without Tk

**Not yet tested on a real machine:**
1. anything on Windows: `setup_windows.bat` / `Recall.bat` (drag-drop, desktop shortcut), the Tk window, the winget Ollama install and local report on NVIDIA
2. a real Anthropic API call (model IDs, image limits, token usage)
3. a local report on a long (45 min) call: speed and quality

## Ideas / next steps

- Speaker diarization (e.g. pyannote) so action items don't depend on the model inferring who spoke.
- A "review screenshots" step in the UI before sending (thumbnail grid with checkboxes).
- Package as a signed app (PyInstaller / py2app) so users don't need Python.
- CI on GitHub Actions running `tests/run_tests.py` on windows-latest and macos-latest.

## Conventions

- User-facing text: plain English, short sentences, says what to click.
- **Every feature must work on both Windows and macOS.** If something can only exist on one (e.g. mlx on Apple Silicon, CUDA on NVIDIA), say so to the user.
- Keep launchers thin; put logic in Python.
- No secrets in the repo. The API key comes from `ANTHROPIC_API_KEY` or `~/.recall/config.json` (chmod 600).
- `handoff/` holds private session notes and is gitignored. Never commit it.
