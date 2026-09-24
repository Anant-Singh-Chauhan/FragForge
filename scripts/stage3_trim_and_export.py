"""
Stage 3: Trim (Kill-Feed Detection) + Vertical Crop + Blurred BG + HUD Overlays
-------------------------------------------------------------------------------
Single-clip processing with OCR detection, blurred background padding, and 3 HUD overlays:
  1. Kill-Feed (Top-Right at Y=300)
  2. Health (Bottom-Left, inside video + 36px padding)
  3. Ammo (Bottom-Right, inside video + 36px padding)
Outputs individual trimmed clips to output/trimmed/trim_YYYYMMDD_HHMMSS.mp4.
"""

from datetime import datetime
import shutil
import subprocess
import sys
from pathlib import Path

from stage2_detect_peaks import get_ocr_reader, detect_killfeed_peaks

RAW_CLIPS_DIR = Path("raw_clips")
OUTPUT_DIR = Path("output")
TRIMMED_DIR = OUTPUT_DIR / "trimmed"

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.15

# --- Canvas Geometry ---
VIDEO_BOTTOM_Y = 1795  # Lower edge of active gameplay footage
BOTTOM_PADDING = 36    # 36px padding above the video bottom boundary

# --- 1. Kill-Feed Overlay Configuration ---
KF_CROP_X = 1350
KF_CROP_Y = 90
KF_CROP_W = 560
KF_CROP_H = 120
KF_OVERLAY_X = "W-w-24"
KF_OVERLAY_Y = "300"
KF_SCALE_W = 480

# --- 2. Health HUD Configuration (Bottom-Left) ---
HP_CROP_X = 525
HP_CROP_Y = 1000
HP_CROP_W = 130
HP_CROP_H = 50
HP_OVERLAY_X = "0"
HP_OVERLAY_Y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"
HP_SCALE_W = 220

# --- 3. Ammo HUD Configuration (Bottom-Right) ---
AMMO_CROP_X = 1267
AMMO_CROP_Y = 1000
AMMO_CROP_W = 130
AMMO_CROP_H = 50
AMMO_OVERLAY_X = "W-w"
AMMO_OVERLAY_Y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"
AMMO_SCALE_W = 220

LEAD_BUFFER_SECONDS = 5.0
TRAIL_BUFFER_SECONDS = 2.0


def get_timestamped_path(target_dir: Path, base_name: str, ext: str = ".mp4") -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = target_dir / f"{base_name}_{timestamp}{ext}"

    if not target.exists():
        return target

    counter = 1
    while True:
        target = target_dir / f"{base_name}_{timestamp}_{counter}{ext}"
        if not target.exists():
            return target
        counter += 1


def resolve_ffmpeg():
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        print("ffmpeg not found on PATH. Open a fresh terminal and try again.")
        sys.exit(1)
    return ffmpeg_path


def process_clip(ffmpeg_exe: str, reader, input_path: Path, output_path: Path):
    print(f"  Scanning kill-feed for {input_path.name}...")
    peaks, duration = detect_killfeed_peaks(reader, input_path)

    if not peaks:
        print("    No kills detected - exporting full clip as fallback.")
        start, end = 0.0, duration
    else:
        start = max(0.0, peaks[0] - LEAD_BUFFER_SECONDS)
        end = min(duration, peaks[-1] + TRAIL_BUFFER_SECONDS)

    kf_scale = f",scale={KF_SCALE_W}:-2" if KF_SCALE_W else ""
    hp_scale = f",scale={HP_SCALE_W}:-2" if HP_SCALE_W else ""
    ammo_scale = f",scale={AMMO_SCALE_W}:-2" if AMMO_SCALE_W else ""

    vf = (
        f"split=5[bg_in][main][kf][hp][ammo];"
        f"[bg_in]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},boxblur=25:5,eq=brightness=-0.1[bg];"
        f"[main]crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,scale={TARGET_WIDTH}:-2[vid];"
        f"[kf]crop={KF_CROP_W}:{KF_CROP_H}:{KF_CROP_X}:{KF_CROP_Y}{kf_scale}[feed];"
        f"[hp]crop={HP_CROP_W}:{HP_CROP_H}:{HP_CROP_X}:{HP_CROP_Y}{hp_scale}[health];"
        f"[ammo]crop={AMMO_CROP_W}:{AMMO_CROP_H}:{AMMO_CROP_X}:{AMMO_CROP_Y}{ammo_scale}[ammunition];"
        f"[bg][vid]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base][feed]overlay={KF_OVERLAY_X}:{KF_OVERLAY_Y}[v1];"
        f"[v1][health]overlay={HP_OVERLAY_X}:{HP_OVERLAY_Y}[v2];"
        f"[v2][ammunition]overlay={AMMO_OVERLAY_X}:{AMMO_OVERLAY_Y}"
    )

    cmd = [
        ffmpeg_exe, "-ss", str(start), "-to", str(end), "-i", str(input_path),
        "-vf", vf, "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(output_path),
    ]

    print(f"  Trimming [{start:.2f}s - {end:.2f}s] -> {output_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"    FAILED: {result.stderr[-500:]}")
    else:
        print(f"    Done: {output_path.name}")


def main():
    ffmpeg_exe = resolve_ffmpeg()

    if not RAW_CLIPS_DIR.exists():
        print(f"Input folder not found: {RAW_CLIPS_DIR}. Create it and drop clips in first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    TRIMMED_DIR.mkdir(parents=True, exist_ok=True)

    exts = {".mp4", ".mkv", ".mov"}
    clips = [f for f in RAW_CLIPS_DIR.iterdir() if f.is_file() and f.suffix.lower() in exts]

    if not clips:
        print(f"No video files found in {RAW_CLIPS_DIR}.")
        sys.exit(0)

    print(f"Found {len(clips)} clip(s) to process.\n")
    reader = get_ocr_reader()

    for clip in clips:
        print(f"\n{clip.name}")
        output_path = get_timestamped_path(TRIMMED_DIR, base_name="trim")
        process_clip(ffmpeg_exe, reader, clip, output_path)


if __name__ == "__main__":
    main()