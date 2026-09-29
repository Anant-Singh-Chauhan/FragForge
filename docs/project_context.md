# LocalYt — Local AI Pipeline for Gaming YouTube Shorts

**Purpose of this document**: full context for continuing this project in a new AI session (or for the project owner returning after a break). It captures the problem, all architectural decisions and why they were made, current implementation state, known issues, and the remaining roadmap. Read this fully before making changes — several early approaches were tried and deliberately abandoned; don't re-suggest them without re-reading the "Rejected Approaches" section.

---

## 1. Problem Statement

The project owner runs a beginner YouTube channel focused on Valorant and CS2 gameplay. They have a large backlog of raw gameplay clips but no time to manually edit them into YouTube Shorts (vertical 9:16, ≤60s, engaging pacing). The goal is a **fully local, automated pipeline** that takes raw clips and produces upload-ready Shorts with zero manual editing — detecting highlight moments, trimming dead time, formatting for vertical, and compiling multiple clips together.

**Non-negotiable constraints:**
- Runs entirely locally — no cloud APIs, no per-use cost
- Trigger-based, not always-on — should not consume system resources when not actively processing
- Never use malicious/risky software; always explain tools/commands as they're introduced (standing user preference)

---

## 2. Current Goals (as of this document)

The project has evolved from "automate the editing" to also becoming a shareable open-source tool:

1. **Personal use**: a one-click local GUI app the owner runs daily
2. **Public release**: a GitHub repository other Valorant/CS2 creators can clone, configure, and use themselves

---

## 3. Environment

- **OS**: Windows 10/11
- **Hardware**: NVIDIA RTX 3050 Laptop GPU (4GB VRAM)
- **Python**: 3.14.3, in a venv at `D:\Personal\LocalYt\venv`
- **Key dependencies**: `opencv-python`, `easyocr`, PyTorch 2.14 (CUDA 12.6 build — install via `--index-url https://download.pytorch.org/whl/cu126`, NOT plain `pip install torch`, or it silently installs CPU-only), `torchvision` (must match the same CUDA index), `numpy`, `watchdog`, `requests`
- **ffmpeg**: Gyan.FFmpeg build via `winget install Gyan.FFmpeg` — this build includes `--enable-cuda-llvm`, `--enable-nvenc`, hardware acceleration available
- **Project root**: `D:\Personal\LocalYt\` (git initialized)
- **In-game names to match**: Valorant = "Avalanche"; CS2 = "Avalanche" or "avalance981"

**Windows-specific gotchas already solved (don't re-debug these):**
- PATH updates to a running terminal don't take effect — VS Code's integrated terminal needs the *entire app* restarted, not just a new terminal tab, to pick up PATH changes
- `subprocess.run(["ffmpeg", ...])` can fail to find ffmpeg on PATH even when the same shell's direct `ffmpeg -version` works — fixed by resolving the full path via `shutil.which("ffmpeg")` once at startup rather than trusting subprocess's own PATH search
- ffmpeg's `drawtext` filter with `font=Arial` fails with a fontconfig error on Windows (no fontconfig config file present) — must use `fontfile='C\\:/Windows/Fonts/arialbd.ttf'` instead (note the escaped colon — required because `:` is a filter-syntax special character)
- Docker Desktop on Windows does not give containers easy GPU passthrough for EasyOCR/PyTorch CUDA — **Docker was explored and reverted** for the OCR-dependent parts of the pipeline; native venv execution is used instead. (Docker Compose files for n8n orchestration may still exist from earlier exploration but are not the active execution path for detection/compile.)

---

## 4. Architecture & Current Implementation State

### 4.1 High-level pipeline flow

```
raw_clips/<game>/*.mp4
  → [OCR kill detection] → peak timestamps
  → [build action blocks + speed-ramp pieces]
  → [per-clip ffmpeg export: trim, vertical crop, blurred bg, HUD overlay]
  → output/trimmed/trim_YYYYMMDD_HHMMSS.mp4 (per clip)
  → [crossfade compile across clips in a batch]
  → output/short_YYYYMMDD_HHMMSS.mp4 (final, ≤60s)
  → raw_clips/<game>/processed/ (originals archived, not deleted)
```

### 4.2 Detection: Kill-feed OCR (NOT audio)

**Current approach**: GPU-accelerated EasyOCR reads a cropped region of each frame watching for the player's name in the kill-feed.

- Crop region (Valorant, 1920x1080 source): `x: 1350–1910, y: 90–210` (top ~2 kill-feed slots)
- Sampling interval: every 0.5s of video
- Preprocessing before OCR: grayscale → 3x cubic upscale → contrast boost (`convertScaleAbs(alpha=1.5)`)
- Name matching uses a regex tolerant of OCR misreads: `re.compile(r"ava[l1|]anche", re.IGNORECASE)` — handles cases where OCR misreads "l" as "1" or "|"
- **Multi-kill counting**: tracks *count* of name occurrences in the current OCR text, not just presence/absence — so back-to-back kills that stack simultaneously in the two visible slots are each counted, not collapsed into one event
- **Detection is "first appearance in either slot"**, not "wait until it reaches the top slot" — because if the kill-feed was empty, a new kill appears directly in slot 1; if not, it enters at slot 2. Either way, first appearance = the real event, so no positional offset calibration is needed for queue depth.
- **Latency offset**: kill-feed text doesn't render instantly at the moment of the kill (~1.5s UI delay observed). `KILLFEED_LATENCY_OFFSET = 1.5` is subtracted from every detected timestamp to align with the actual crosshair-engagement moment.
- OCR model (`easyocr.Reader`) is loaded **once** per batch run and reused across all clips — reloading per clip wastes significant time.

**Multi-game support**: `profiles.py` maps game-specific crop coordinates, buffer timings, and folder-scanning rules for Valorant vs CS2 independently. CS2's kill-feed is laid out differently (top-right, different entry duration/styling — see the CS2 screenshot referenced during development, which shows kill-feed entries as `PlayerName [weapon icon] skull VictimName` in a yellow/red bordered box, entries involving the player appear highlighted).

### 4.3 Pacing & trimming logic

- **Buffers around each detected kill**: `LEAD_BUFFER_SECONDS = 5.0` (normal-pace setup time before a kill — increased from an initial 2.0s because 2s felt too abrupt/rushed), `TRAIL_BUFFER_SECONDS = 2.0`
- **Action block merging**: kill windows within `GAP_SPEEDUP_THRESHOLD_SECONDS = 10.0` of each other are merged into one continuous block
- **Speed-ramping dead time**: gaps between action blocks longer than the threshold are NOT cut — they're kept but sped up 2x in the middle (`SPEEDUP_FACTOR = 2.0`), with `SPEEDUP_EDGE_BUFFER_SECONDS = 2.0` of normal-speed footage bookending each side of the sped section for a smooth transition (not an abrupt speed change)
- A "2X" badge (`drawtext` filter) is overlaid during sped sections so the pacing change reads as intentional, not a glitch
- **This was a deliberate design choice over hard-cutting dead time**: an earlier version cut gaps entirely, but this felt jarring; speed-ramping preserves context/continuity while still compressing time

### 4.4 Vertical formatting & HUD re-composition

- Target output: 1080x1920 @ 60fps (YouTube Shorts spec)
- Gameplay is cropped from the 16:9 source at `crop=ih*9/16*ZOOM_OUT_FACTOR:ih` (ZOOM_OUT_FACTOR=1.15, i.e. shows ~15% more horizontal FOV than a tight crop) then scaled to fit
- **Aspect ratio bug (fixed)**: an early version scaled the wider crop directly to exact 1080x1920, which silently stretched/distorted the image horizontally. Fixed by scaling to width while preserving aspect ratio (`scale=1080:-2`) then padding the remaining height with letterbox bars, rather than forcing the exact target dimensions.
- **Blurred background fill (current)**: rather than plain black letterbox bars, empty vertical space is filled with a scaled, cropped, blurred (`boxblur=25:5`), darkened (`eq=brightness=-0.1`) copy of the same gameplay frame — built via an ffmpeg `split` into parallel filter chains recombined with `overlay`
- **HUD re-composition**: since the vertical crop cuts off the sides of the original frame (where kill-feed/HUD elements live), those elements are separately cropped from the *original* source frame and re-overlaid on top of the final vertical canvas:
  - Kill-feed: overlaid top-right at Y=300
  - Health: bottom-left, anchored with a 36px buffer above the video's bottom edge
  - Ammo: bottom-right, same vertical anchor
- All of this happens in one `filter_complex` graph per export for efficiency (not multiple sequential ffmpeg passes)

### 4.5 Multi-clip compilation

- Clip order controlled by numbered filename prefixes (e.g. `1_ace_ascent.mp4`, `2_clutch_bind.mp4`) — sorted via regex extracting the leading number
- Clips are crossfaded together (`xfade`/`acrossfade` filters, `CROSSFADE_SECONDS = 0.5`)
- **pix_fmt bug (fixed)**: crossfaded/sped outputs occasionally failed to play ("unsupported encoding") in default Windows video apps. Fixed by explicitly forcing `-pix_fmt yuv420p` on every export — without it, ffmpeg can output a pixel format some players don't support by default.
- **Content budget guardrail**: 60s total target minus reserved intro/outro time = dynamically calculated gameplay allowance (currently 54.39s after accounting for a 1.5s intro + 2.0s logo outro + 2.11s subscribe end-card). If trimmed clips exceed this budget, the script warns and prompts an interactive 30-second timeout rather than silently producing an over-length or malformed output.
- Individual per-clip exports go to `output/trimmed/trim_YYYYMMDD_HHMMSS.mp4`; the final compiled batch goes to `output/short_YYYYMMDD_HHMMSS.mp4`. Timestamped filenames with a collision-safe counter suffix prevent overwrites.
- Raw clips are **moved** (archived) to `raw_clips/<game>/processed/` after successful processing — never deleted, as a safety net against pipeline failures losing source footage.

### 4.6 Intro/outro (built)

- **Intro (1.5s)**: channel logo zooms out from 2.0x to 1.0x, with a 0.2s fade-in from black, silent
- **Outro, two stages**:
  1. **Logo glitch (2.0s)**: logo zooms out 1.1x → 0.85x with an integer-scaled 36×64 nearest-neighbor "chunky block glitch" effect, softened `glitched_sound.mp3`, fades to black
  2. **Subscribe end-card (~2.11s)**: `like_share_subs.mp4` standardized to 1080x1920 @ 60fps, muted, appended immediately after the logo outro
- **Background music**: `CM_03 Cruise.mp3` seeks to its 12-second mark, fades in over 1.5s under the intro, sits under gameplay audio at volume `0.075`, persists through both outro stages, fades out over the final 1.5s
- **Assembly**: originally sequential crossfading steps caused audio/video drift across transitions. Fixed by replacing with a **single unified master filtergraph** with strict timestamp resets (`PTS-STARTPTS`, `aresample`) applied across every segment — eliminates cumulative drift.

### 4.7 Folder scanning

- Uses **shallow** `iterdir()`, not recursive scanning — clips inside subfolders like `dump/` or `comp pistols/` are intentionally excluded; only loose clips directly in a game's raw folder are picked up. This was a deliberate fix (an earlier version's recursive scan pulled in unwanted footage).

### 4.8 Trigger-based execution (not always-on)

- Explicit design requirement: the pipeline must not run continuously in the background consuming resources
- An earlier `watchdog`-based file-watcher (auto-triggering on new file drop) was built and **abandoned** in favor of a one-shot batch script the user runs on demand — matches the "start it, it runs, it stops" model better than a persistent watcher process
- Docker Compose was explored as an on/off container-based trigger mechanism but reverted specifically for the OCR/GPU-dependent stages due to GPU passthrough friction on Windows

---

## 5. Rejected Approaches (do not re-suggest without new information)

| Approach | Why rejected |
|---|---|
| Audio RMS loudness peak detection | Cannot distinguish player's own gunfire from voice comms, footsteps, announcer lines, or distant/other-player combat bleeding through positional audio. Produced both false positives (loud non-kill sounds) and false negatives. |
| Audio harmonic-percussive separation (`librosa.effects.percussive`) as a detection refinement | Still audio-based; removed a good highlight portion of a clip while still missing real dead time in testing. Diminishing returns. |
| Audio-activity "safety net" gate before allowing speed-ramp (hybrid audio+OCR) | Caused unintentional long normal-paced gaps (too conservative — any loud ambient sound blocked speed-ramping even when nothing relevant was happening). Reverted. |
| Fixed bottom-band crop for "newest kill-feed entry" | Broke because the kill-feed queue can hold 0 to n existing items — the newest entry's screen position isn't fixed, it depends on current queue depth. Replaced with dynamic bottommost-detected-line logic, then further replaced with the "first appearance in either of the top 2 slots" model. |
| Hard-cutting large dead-time gaps entirely | Felt jarring/abrupt. Replaced with 2x speed-ramping (keeps context, compresses time) instead of removal. |
| Docker for the OCR/GPU pipeline stages | GPU passthrough to containers on Windows Docker Desktop is not straightforward; native venv execution was simpler and reliable. |
| PyInstaller-style single-exe distribution for public release | Bundling PyTorch+CUDA (multiple GB) into a single executable is fragile and bloated. Public distribution instead targets a normal GitHub repo + setup script (Python + pip install), which is standard practice for ML/CV tools and far more maintainable. |

---

## 6. File Structure (current, approximate)

```
D:\Personal\LocalYt\
├── raw_clips/
│   ├── valorant/
│   │   └── processed/       (archived originals)
│   └── cs2/
│       └── processed/
├── output/
│   ├── trimmed/              (per-clip exports)
│   └── (final compiled shorts, timestamped)
├── temp/                     (scratch files, concat lists, etc.)
├── scripts/
│   ├── stage2_detect_peaks.py   (shared kill-feed OCR detection module)
│   ├── batch_compile.py          (main pipeline: detect → trim → speed-ramp → HUD → compile)
│   ├── stage3_trim_and_export.py (lighter single-clip variant, no multi-clip compile)
│   ├── profiles.py               (per-game crop/buffer/folder config — Valorant vs CS2)
│   └── calibrate_killfeed.py     (visual crop-region calibration helper)
├── venv/
├── .gitignore
└── (docker-compose.yml, Dockerfile — legacy from earlier n8n exploration, not on the active execution path)
```

---

## 7. Remaining Roadmap

### 7.1 In progress / next up — Standalone App

Goal: (a) one-click local launcher for personal daily use, (b) public GitHub release others can clone and configure.

1. **Move hardcoded settings into a user-editable config** (`config.yaml`/`config.json`) — player name(s), per-game crop/buffer values currently in `profiles.py`, paths to branding assets. Necessary before this is usable by anyone but the owner.
2. **Separate personal branding from the core tool** — channel logo, glitch sound, `like_share_subs.mp4` should not be the default for other users. Move to `config/branding/`, ship placeholders publicly, gitignore/exclude the owner's real assets.
3. **Refactor for GUI consumption** — keep pipeline scripts CLI-runnable as-is; GUI launches them as a subprocess with unbuffered output (`python -u batch_compile.py`) and streams stdout into a log box via a background thread. Avoids a risky rewrite of working logic.
4. **Build GUI with Tkinter** (ships with Python — zero extra install burden) + `tkinterdnd2` for real drag-and-drop. Layout: drop zone, "Auto-detect raw clips" button (reuses existing shallow-scan logic), game selector dropdown, Run button, live log, "Open output folder" button.
5. **Wire drag/drop and auto-detect** to route clips into the correct `raw_clips/<game>/` folder based on dropdown selection or source folder.
6. **One-click local launcher**: `run_gui.bat` activates venv, launches `pythonw gui.py` (no console window).
7. **Prepare repo for public GitHub release**: README (prerequisites, setup, first-run config), `setup.bat`/`setup.sh` (creates venv + installs requirements, with explicit documented step for the CUDA-specific PyTorch install since it can't go in a normal requirements.txt), MIT LICENSE, `.gitignore` hygiene.

**Open questions flagged for this phase:**
- CPU fallback path (no NVIDIA GPU) needs to be confirmed solid — public users will hit this often
- A visual "click the corners on a screenshot" calibration UI (rather than asking users to hand-edit pixel coordinates) would meaningfully improve public usability — treated as a fast-follow, not a blocker for first release

### 7.2 Further out

- **Captions** via `faster-whisper` (local, no cloud) — only relevant if the creator talks over clips; confirm this is actually wanted before building
- **AI-assisted clip ranking/titling** via a local LLM through Ollama — given the 4GB VRAM constraint, a small model (`llama3.2:3b` or `qwen2.5:3b`) is the right size, not larger models originally suggested before hardware constraints were known. Should run as a separate pass after OCR/export finishes, not concurrently (VRAM contention).
- **n8n integration** for notifications (Discord/Telegram ping when a Short is ready) — deferred until the core pipeline and GUI are stable; Docker Compose scaffolding for this exists from earlier exploration but is not wired up
- **YouTube auto-upload**: investigated and **deprioritized** — videos uploaded via the YouTube Data API from unverified API projects created after July 2020 are locked to private until the project passes Google's compliance audit, which is a poor fit for a solo/small-scale tool. Current recommendation: pipeline outputs the video plus a ready-to-paste title/description text file; manual upload via YouTube Studio.

---

## 8. Standing User Preferences (apply throughout)

- Explain tools/commands as they're introduced — don't assume prior familiarity, even for things like `ffmpeg`, `venv`, or PowerShell PATH mechanics
- Never suggest malicious or risky software
- Prefer local/offline solutions over cloud dependencies
- Build and validate incrementally, one stage at a time, rather than large speculative builds
- When resuming after a break, prefers concise, to-the-point answers over lengthy re-explanation

---

## 9. How to Continue in a New Session

1. Read this document fully first.
2. Ask the user for current file contents if picking up mid-feature — files have been hand-edited outside AI sessions multiple times during this project, so assume this document's code-level details may already be slightly stale even though the architecture/decisions remain accurate. **This document describes decisions and architecture reliably; for exact current code, always ask for the live files.**
3. Check the "Rejected Approaches" table before proposing a detection or pacing strategy — several intuitive-seeming approaches have already been tried and found wanting for specific, documented reasons.
4. Continue from section 7.1's numbered list unless the user directs otherwise.