# FragForge — Frequently Asked Questions & Troubleshooting

This guide addresses common setup problems, hardware limitations, configuration errors, and rendering issues.

---

## Table of Contents
1. [GPU & Hardware Acceleration](#1-gpu--hardware-acceleration)
2. [Configuration Errors (`config.json`)](#2-configuration-errors-configjson)
3. [FFmpeg & PATH Errors](#3-ffmpeg--path-errors)
4. [Missing Branding Assets](#4-missing-branding-assets)
5. [OCR Detection & Pacing Calibration](#5-ocr-detection--pacing-calibration)
6. [Shorts Duration & The 54-Second Budget](#6-shorts-duration--the-54-second-budget)
7. [Windows Encoding & Audio Drift](#7-windows-encoding--audio-drift)

---

## 1. GPU & Hardware Acceleration

### Q: Does FragForge require an NVIDIA GPU?
**No.** FragForge runs on systems without an NVIDIA GPU:
* **With NVIDIA GPU (CUDA):** EasyOCR uses CUDA acceleration for fast scanning (~0.1s to 0.3s per frame).
* **Without NVIDIA GPU (CPU fallback):** PyTorch automatically falls back to CPU threads. The pipeline will work identically, but scanning will take 2x to 4x longer per clip.

### Q: Why does the console say "Operating in CPU mode" when I have an NVIDIA GPU?
Common causes:
1. **PyTorch installed without CUDA support:** Running a standard `pip install torch` downloads CPU-only wheels. Run `setup.bat` or reinstall the CUDA build manually:
   ```cmd
   pip install torch torchvision --index-url [https://download.pytorch.org/whl/cu126](https://download.pytorch.org/whl/cu126)
   ```
2. **Outdated NVIDIA Drivers:** Run `nvidia-smi` in PowerShell or Command Prompt. If it fails, update your GPU drivers via GeForce Experience or the NVIDIA Driver Downloads website.
3. **4GB VRAM Limit (RTX 3050 Laptop / GTX 1650):** If another game or heavy 3D app is running, CUDA may run out of memory. Close background games before starting a large batch compile.

---

## 2. Configuration Errors (`config.json`)

### Q: I get `[FragForge Configuration Error] Missing required configuration file: config.json`.
FragForge does not track private `config.json` files in Git to prevent personal names and paths from leaking. To create it:
1. Run `setup.bat` (it automatically copies `config.example.json` to `config.json`), **or**
2. Manually copy the example template in the project root:
   ```cmd
   copy config.example.json config.json
   ```

### Q: I get `[FragForge Syntax Error in config.json]` on boot.
This means there is a typo in your JSON syntax (such as a missing bracket `}`, a trailing comma `,`, or unescaped backslashes in file paths).
* Open the **⚙ Configuration** tab in the desktop app to inspect and correct the highlighted syntax error.
* Alternatively, replace `config.json` with a fresh copy of `config.example.json` and re-enter your player alias.

---

## 3. FFmpeg & PATH Errors

### Q: The console reports `Tool not found on PATH: ffmpeg` or `ffprobe`.
FFmpeg must be installed and registered on your Windows system PATH:
1. Open PowerShell and install Gyan's full FFmpeg build:
   ```powershell
   winget install Gyan.FFmpeg
   ```
2. **Crucial:** Restart VS Code or your terminal after installation so the refreshed PATH environment variable takes effect.

### Q: I see `Fontconfig error: Cannot load default config file` during video rendering.
On Windows, FFmpeg fails if filters use generic font names like `font=Arial`. FragForge bypasses Fontconfig by explicitly targeting the Windows system font file:
```text
fontfile='C\:/Windows/Fonts/arialbd.ttf'
```
Ensure `arialbd.ttf` (Arial Bold) is present in `C:\Windows\Fonts`.

---

## 4. Missing Branding Assets

### Q: What happens if I don't provide a logo or music?
The pipeline **will not crash**. Built-in fallbacks handle each missing file:
* **Missing Logo:** Intro and logo outro cards are skipped automatically; compilation starts directly on gameplay.
* **Missing Glitch SFX:** Falls back to an internal synthetic white-noise frequency burst (`anoisesrc`).
* **Missing Subscribe Video (`like_share_subs.mp4`):** Skipped. The allowable gameplay duration automatically expands from 54.39s to 56.5s.
* **Missing BGM:** Skips music mixing; compiles with pure gameplay audio.

To restore default branding, place your `.png` and `.mp3` assets in `assets/branding/` and confirm their filenames match `config.json`.

---

## 5. OCR Detection & Pacing Calibration

### Q: Why did the scan report `No kills detected via OCR` on a clip with frags?
1. **In-Game Name Misalignment:** Verify the `player_aliases` array in `config.json`. Add any nicknames, shortened tags, or smurf account names:
   ```json
   "player_aliases": ["Avalanche", "avalance981", "Ava"]
   ```
2. **Display Resolution / HUD Scaling:** FragForge's default crops expect a standard 16:9 native HUD layout (1920x1080 or 2560x1440). If your in-game killfeed scale or position is customized, update `killfeed_crop` coordinates in `config.json`.
3. **Regex OCR Substitutions:** FragForge automatically substitutes `l` with `[l1|]` to handle common OCR misreads. If your name uses unusual symbols, add those variations explicitly to `player_aliases`.

---

## 6. Shorts Duration & The 54-Second Budget

### Q: Why does FragForge limit gameplay to 54.39 seconds instead of 60.0 seconds?
YouTube Shorts strictly caps uploads at 60.0 seconds. FragForge dynamically reserves time for branding transitions:
```text
Max Gameplay = 60.0s - 1.5s (Intro) - 2.0s (Outro) - 2.11s (Subs) = 54.39 seconds
```
If your trimmed gameplay exceeds 54.39s, the app warns you to prevent generating a video that YouTube will classify as a regular long-form upload rather than a Short.

---

## 7. Windows Encoding & Audio Drift

### Q: Exported videos say "Unsupported encoding" or play audio with a black screen.
Default Windows Media Player requires `yuv420p` pixel format for hardware-accelerated H.264 playback. FragForge enforces `-pix_fmt yuv420p` across all exports. If you run into issues on older players, verify that your graphics drivers are current.

### Q: Why was audio drifting out of sync with video across crossfades?
Sequential ffmpeg crossfade passes can accumulate fractional timestamp offsets. FragForge prevents this by executing a single-pass master filtergraph with strict presentation timestamp resets:
```text
setpts=PTS-STARTPTS
asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0
```