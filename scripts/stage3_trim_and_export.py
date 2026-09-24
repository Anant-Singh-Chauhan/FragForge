"""
Stage 3: Trim (Kill-Feed Detection) + Vertical Crop + Kill-Feed Overlay
-----------------------------------------------------------------------
Single-clip processing with OCR detection and killfeed overlay rendering.
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

# --- Kill-Feed Overlay Configuration ---
KF_CROP_X = 1350
KF_CROP_Y = 90          # Shifted up by 10px to capture upper card margin
KF_CROP_W = 560
KF_CROP_H = 200         # Expanded height by 10px so bottom cutoff point stays identical
KF_OVERLAY_X = "W-w-24" # 24px padding from right edge
KF_OVERLAY_Y = "300"    # Moved 100px lower to sit at 300px from top
KF_SCALE_W = 480

LEAD_BUFFER_SECONDS = 5.0
TRAIL_BUFFER_SECONDS = 2.0


def get_timestamped_path(target_dir: Path, base_name: str, ext: str = ".mp4") -> Path:
    """
    Generates a datetime-stamped filename: <base_name>_<YYYYMMDD_HHMMSS><ext>
    Falls back to collision naming: <base_name>_<YYYYMMDD_HHMMSS>_1<ext>, _2, etc.
    """
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

    kf_scale = f",scale={KF_SCALE_W}:-1" if KF_SCALE_W else ""
    vf = (
        f"split=2[main][kf];"
        f"[main]crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black[bg];"
        f"[kf]crop={KF_CROP_W}:{KF_CROP_H}:{KF_CROP_X}:{KF_CROP_Y}{kf_scale}[feed];"
        f"[bg][feed]overlay={KF_OVERLAY_X}:{KF_OVERLAY_Y}"
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