<div align="center">

<img src="assets/public/appIcon.ico" alt="FragForge Logo" width="120" height="120" />

# FragForge
**Automated Tactical Shorts Engine for VALORANT & Counter-Strike 2**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform Windows](https://img.shields.io/badge/platform-Windows-0078d7.svg)](https://www.microsoft.com/windows)
[![CUDA 12.6 Supported](https://img.shields.io/badge/CUDA-12.6%20Supported-76b900.svg)](https://developer.nvidia.com/cuda-toolkit)
[![License MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

*Turn hours of raw gameplay into polished, portrait-format YouTube Shorts in minutes.*

</div>

---

## Overview

**FragForge** is a desktop workstation utility that automates the tedious parts of tactical FPS content creation. Using computer vision (OpenCV) and optical character recognition (EasyOCR), FragForge scans raw gameplay footage, identifies your in-game elimination events, trims the action, speeds through quiet dead-time, and composites a portrait (9:16) video with pinned HUD overlays, intro/outro cards, and sync-locked background music.

---

## Key Features

- **Automated Killfeed OCR Detection:** Scans the killfeed for your player aliases with fuzzy-matching logic to catch optical misreads (e.g., `l` vs `1` vs `|`).
- **Dynamic 9:16 Portrait Canvas:** Automatically centers gameplay with a dynamic blurred background and extracts real-time overlays for Killfeed, Health, and Ammo.
- **Smart Action Pacing & Gap Speedup:** Dead time between kills exceeding 10 seconds is automatically accelerated to 2X with smooth edge buffering.
- **Audio Sync & Broadcast Ducking:** Mixes gameplay audio with synced background music and sound effects, featuring crossfades and automated fade-outs.
- **Duration Budget Guard:** Automatically reserves space for intro cards and outro cards to guarantee your final video stays within YouTube's 60-second Shorts limit.
- **Unified CustomTkinter Desktop GUI:** Stage raw clips, monitor live OCR terminal logs, inspect exports, and edit configuration directly inside the app.
- **Hardware Fallbacks:** Built for NVIDIA CUDA acceleration with seamless automatic fallback to multi-threaded CPU execution.

---

## Pipeline Architecture

```text
[ Raw Footage (16:9) ]
         │
         ▼
[ Stage 1: File Ingestion & Metadata Probe ] ─── (FFprobe: resolution, duration, FPS)
         │
         ▼
[ Stage 2: OCR Killfeed Scanning ] ───────────── (EasyOCR + OpenCV: edge detection & regex)
         │
         ▼
[ Stage 3: Temporal Analysis & Pacing ] ──────── (Action blocks + 2X gap speed ramps)
         │
         ▼
[ Stage 4: Filtergraph Compositing ] ─────────── (9:16 canvas, blur backdrop, HUD overlays)
         │
         ▼
[ Stage 5: Branding & Audio Mastering ] ──────── (Intro zoom, glitch outro, BGM crossfade)
         │
         ▼
[ Final YouTube Short (1080x1920 @ 60fps) ]
```

---

## System Requirements

- **Operating System:** Windows 10 or Windows 11 (64-bit)
- **Python:** Python 3.10 to 3.12 (Python 3.14+ not recommended due to PyTorch wheel availability)
- **Media Engine:** FFmpeg & FFprobe registered on system PATH
- **GPU (Recommended):** NVIDIA GeForce GTX 1060 / RTX 2060 or higher (CUDA 12.6)
- **CPU (Fallback):** 4+ cores for CPU-only OCR and video encoding

---

## Quickstart Installation

### 1. Clone the Repository

```powershell
git clone [https://github.com/](https://github.com/)<YourUsername>/FragForge.git
cd FragForge
```

### 2. Verify Prerequisites

Install FFmpeg via Windows Package Manager if you do not already have it:

```powershell
winget install Gyan.FFmpeg
```
*(Restart your terminal or VS Code after installing FFmpeg to refresh your PATH).*

### 3. Run Automated Setup

Run the setup batch script in the root directory:

```powershell
.\setup.bat
```

`setup.bat` performs the following steps:
1. Validates Python and FFmpeg installations.
2. Checks for NVIDIA GPU hardware via `nvidia-smi`.
3. Creates a Python virtual environment (`.\venv`).
4. Installs PyTorch (CUDA 12.6 build if an NVIDIA GPU is found, standard CPU build otherwise).
5. Installs GUI, OpenCV, and EasyOCR dependencies from `requirements.txt`.
6. Generates `config.json` from `config.example.json` if missing.
7. Scaffolds required directories (`raw_clips/`, `output/`, `temp/`, `assets/`).

### 4. Launch the GUI

Launch the application using the launcher script:

```powershell
.\run_gui.bat
```

---

## Pipeline Architecture

```text
FragForge/
├── assets/
│   ├── branding/             # Private channel branding (logo, BGM, glitch SFX, outro)
│   └── public/               # Public application icons (appIcon.ico, appIcon.png)
├── output/                   # Final compiled master Shorts
│   └── trimmed/              # Individual processed clip segments
├── raw_clips/                # Staging directories for unprocessed clips
│   ├── cs2/                  # Counter-Strike 2 raw footage
│   ├── valo/                 # VALORANT raw footage
│   └── processed/            # Clips archived here after successful compilation
├── scripts/
│   ├── batch_compile.py      # Core video processing and FFmpeg filtergraph pipeline
│   ├── profiles.py           # Game coordinate profiles and configuration loader
│   └── stage2_detect_peaks.py# EasyOCR scanning and killfeed event detector
├── temp/                     # Ephemeral intermediate render segments
├── config.example.json       # Configuration template tracked in version control
├── config.json               # Local runtime configuration (gitignored)
├── faq.md                    # Hardware, encoding, and troubleshooting guide
├── gui.py                    # CustomTkinter desktop interface
├── requirements.txt          # Python package manifest
├── run_gui.bat               # Quiet desktop launcher
└── setup.bat                 # Automated installation and environment bootstrapper
```

---

## Configuration & HUD Calibration

Edit `config.json` directly or use the **Configuration** tab in the desktop application.

```json
{
  "branding": {
    "logo_path": "assets/branding/logo.png",
    "bgm_path": "assets/branding/bgm.mp3",
    "glitch_sfx_path": "assets/branding/glitch.mp3",
    "subs_clip_path": "assets/branding/like_share_subs.mp4",
    "intro_duration": 1.5,
    "logo_outro_duration": 2.0,
    "intro_start_zoom": 2.0,
    "glitch_volume": 0.14,
    "bgm_start_timestamp": 12.0,
    "bgm_volume": 0.075,
    "bgm_fade_duration": 1.5,
    "crossfade_seconds": 0.5
  },
  "games": {
    "valo": {
      "name": "VALO",
      "dir_name": "valo",
      "folder_aliases": ["valorant", "valo"],
      "player_aliases": ["YourPlayerName"],
      "latency_offset": 1.5,
      "lead_buffer": 5.0,
      "trail_buffer": 2.0,
      "killfeed_crop": [0.703125, 0.083333, 0.994791, 0.194444],
      "health_crop": [0.273437, 0.925925, 0.341145, 0.972222],
      "ammo_crop": [0.659895, 0.925925, 0.727604, 0.972222],
      "kf_overlay_w": 480,
      "hp_overlay_w": 220,
      "ammo_overlay_w": 220
    }
  }
}
```

### Key Parameters

| Field | Description |
| :--- | :--- |
| `player_aliases` | List of in-game names to scan for in the killfeed (case-insensitive). |
| `latency_offset` | Seconds subtracted from OCR detection to align with the actual kill moment. |
| `lead_buffer` | Seconds of gameplay retained before each frag. |
| `trail_buffer` | Seconds of gameplay retained after each frag. |
| `killfeed_crop` | Normalized bounding box coordinates `[x1, y1, x2, y2]` for the killfeed zone. |
| `health_crop` / `ammo_crop` | Normalized coordinates for health and ammunition HUD elements. |

---

## Troubleshooting & FAQ

For solutions regarding:
- GPU/CUDA detection and PyTorch issues
- Missing asset fallbacks
- FFmpeg PATH configuration
- YouTube Shorts duration limits
- Audio synchronization and encoding errors

Consult [faq.md](faq.md) for detailed diagnostics and solutions.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.