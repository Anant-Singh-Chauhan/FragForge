# Automated Game-Clip Shorts Pipeline

An automated video compilation engine designed to transform widescreen 16:9 gameplay recordings (VALORANT and Counter-Strike 2) into vertical 9:16 YouTube Shorts. The pipeline features GPU-accelerated OCR killfeed scanning, dead-time speed-ramping, resolution-independent HUD re-mapping, dynamic branding transitions, and sync-locked audio mixing.

---

## Key Features

* **OCR-Driven Kill Detection:** Uses EasyOCR to scan the game killfeed frame-by-frame, applying UI latency compensation to isolate multikills and clutches accurately.
* **Vertical 9:16 Canvas Compositing:** Crops gameplay to a centered vertical frame overlaid on a blurred, dimmed widescreen background (`boxblur=25:5`).
* **Dynamic HUD Re-Mapping:** Crops the Killfeed, Health, and Ammo indicators from their native 16:9 locations and anchors them cleanly into mobile-viewable zones on the 9:16 canvas.
* **Smart Dead-Time Compression:** Automatically detects gaps between action windows greater than 10 seconds and speed-ramps them to **2X** (video `setpts` + audio `atempo`) with a visual overlay badge.
* **Branding & Transitions:**
  * **Intro (1.5s):** Logo zooms out from 2.0x to 1.0x with a snappy 0.2s fade-in from black.
  * **Logo Outro (2.0s):** Logo zooms out from 1.1x to 0.85x with an integer-scaled 36x64 chunky block glitch and synchronized SFX.
  * **End-Card Call-to-Action:** Stitches a standardized, muted `like_share_subs.mp4` clip directly to the end of the timeline.
* **Sync-Locked Audio Engine:** Unifies all cuts, crossfades, and background music into a single-pass filtergraph with normalized presentation timestamps (`PTS-STARTPTS`) to prevent audio drift.
* **Shorts Budget Guardrail:** Automatically evaluates clip lengths against a strict 54.39-second content budget to ensure the master assembly never exceeds YouTube Shorts' 60-second limit.

---

## Directory Structure

```text
├── avlLogo_cropped.png           # Channel branding logo
├── CM_03 Cruise.mp3              # Background music track
├── glitched_sound.mp3            # Outro digital glitch SFX
├── like_share_subs.mp4           # Final call-to-action end-card video
│
├── raw_clips/                    # Input gameplay footage
│   ├── cs2/                      # Counter-Strike 2 clips (shallow scan)
│   ├── valorant/                 # VALORANT clips (shallow scan)
│   └── processed/                # Archive target for completed clips
│       ├── cs2/
│       └── valo/
│
├── output/                       # Export destination
│   ├── trimmed/                  # Individual trimmed action segments
│   └── *_short_YYYYMMDD_HHMMSS.mp4  # Final compiled Shorts
│
├── temp/                         # Ephemeral workspace for piece concats
└── scripts/
    ├── profiles.py               # Game coordinates, timings, and paths
    ├── stage2_detect_peaks.py    # EasyOCR killfeed peak detection
    ├── stage3_trim_and_export.py # Single-clip standalone processor
    └── batch_compile.py          # Master batch orchestrator and compiler
```

---

## Prerequisites & Installation

### 1. System Requirements
* **FFmpeg & FFprobe:** Must be installed and added to your system `PATH`.
* **CUDA-compatible GPU:** Recommended for GPU-accelerated OCR text recognition.

Verify FFmpeg installation:
```bash
ffmpeg -version
ffprobe -version
```

### 2. Python Environment
Python 3.10+ is recommended. Install required packages:

```bash
pip install torch torchvision --index-url [https://download.pytorch.org/whl/cu118](https://download.pytorch.org/whl/cu118)
pip install easyocr pillow
```

---

## Configuration (`scripts/profiles.py`)

All resolution-independent HUD crop boundaries, audio profiles, and timing buffers are managed centrally in `scripts/profiles.py`:

| Parameter | VALORANT | CS2 | Description |
| :--- | :--- | :--- | :--- |
| **Folder Aliases** | `valorant`, `valo` | `cs2`, `cs`, `counter-strike` | Folder names recognized during discovery |
| **Latency Offset** | `1.5s` | `1.0s` | Killfeed UI display delay subtracted from peak timestamps |
| **Lead Buffer** | `5.0s` | `5.0s` | Seconds captured prior to elimination |
| **Trail Buffer** | `2.0s` | `2.5s` | Seconds captured following elimination |
| **Killfeed Crop** | `(0.703, 0.083, 0.995, 0.194)` | `(0.810, 0.050, 0.995, 0.160)` | Normalized coordinates `(x1, y1, x2, y2)` |
| **Health Crop** | `(0.273, 0.926, 0.341, 0.972)` | `(0.315, 0.920, 0.395, 0.985)` | Normalized coordinates `(x1, y1, x2, y2)` |
| **Ammo Crop** | `(0.660, 0.926, 0.728, 0.972)` | `(0.615, 0.920, 0.695, 0.985)` | Normalized coordinates `(x1, y1, x2, y2)` |

### Global Branding & Audio Parameters

* `INTRO_DURATION = 1.5` — Duration of the zooming logo intro card.
* `LOGO_OUTRO_DURATION = 2.0` — Duration of the block-glitch logo outro.
* `BGM_START_TIMESTAMP = 12.0` — Seek offset into `CM_03 Cruise.mp3`.
* `BGM_VOLUME = 0.075` — Calibrated volume floor to sit cleanly beneath gameplay audio.
* `GLITCH_VOLUME = 0.14` — Volume level for the outro glitch SFX.
* `CROSSFADE_SECONDS = 0.5` — Transition overlap between consecutive scenes.

---

## Timing & YouTube Shorts Budget

YouTube Shorts rejects uploads longer than 60.0 seconds. The compiler tracks duration dynamically using `ffprobe`:

$$\text{Content Budget} = 60.0\text{s} - 1.5\text{s (Intro)} - 2.0\text{s (Logo Outro)} - \text{Subs Clip Duration}$$

Using the default 2.11s `like_share_subs.mp4` clip:

$$\text{Max Raw Gameplay Duration} = 60.0 - 1.5 - 2.0 - 2.11 = \mathbf{54.39\text{ seconds}}$$

* **Under Budget (<= 54.39s):** Pipeline compiles the master short automatically.
* **Over Budget (> 54.39s):** Prompts a **30-second interactive warning** in the terminal:
  * Press **`y`** to override and compile anyway.
  * Press **`n`** (or wait for the 30-second timeout) to skip master compilation while preserving all rendered individual clips in `output/trimmed/`.

---

## Execution

### Full Batch Compilation (Standard Workflow)
Place raw recordings inside `raw_clips/valorant/` or `raw_clips/cs2/` and run:

```bash
python scripts/batch_compile.py
```

**What happens:**
1. Executes a shallow directory scan (subfolders like `dump/` are safely ignored).
2. Identifies kills using OCR and partitions clips into action and speed-ramped pieces.
3. Renders 9:16 vertical HUD-composited segments to `output/trimmed/`.
4. Dynamically renders the Intro, Logo Outro, and formats `like_share_subs.mp4`.
5. Compiles all parts with crossfade transitions and background music into `output/<game>_short_YYYYMMDD_HHMMSS.mp4`.
6. Moves raw source videos to `raw_clips/processed/<game>/`.

### Single Clip Processing (Debug / Standalone Trim)
To process and export a single vertical gameplay clip without intro, outro, or BGM assembly:

```bash
python scripts/stage3_trim_and_export.py
```
Exports to: `output/trimmed/<game>_trim_YYYYMMDD_HHMMSS.mp4`.