"""
Stage 3: Trim (Kill-Feed Detection) + Crop to Vertical + Export
--------------------------------------------------------------------
Simpler single-clip tool (no multi-clip compile, no speed-ramping) - trims
each raw clip from 2s before the first detected kill to 2s after the last,
crops/zooms to vertical, and exports. For the full pipeline (speed-ramped
gaps, multi-clip compile, budget checks, archiving), use batch_compile.py
instead - this is a lighter option for quick one-off processing.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\stage3_trim_and_export.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

from stage2_detect_peaks import get_ocr_reader, detect_killfeed_peaks

RAW_CLIPS_DIR = Path("raw_clips")
OUTPUT_DIR = Path("output")

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.15

LEAD_BUFFER_SECONDS = 2.0
TRAIL_BUFFER_SECONDS = 2.0


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

    vf = (
        f"crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black"
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

    exts = {".mp4", ".mkv", ".mov"}
    clips = [f for f in RAW_CLIPS_DIR.iterdir() if f.is_file() and f.suffix.lower() in exts]

    if not clips:
        print(f"No video files found in {RAW_CLIPS_DIR}.")
        sys.exit(0)

    print(f"Found {len(clips)} clip(s) to process.\n")

    reader = get_ocr_reader()  # loaded once, reused for every clip below

    for clip in clips:
        print(f"\n{clip.name}")
        output_path = OUTPUT_DIR / f"{clip.stem}_vertical.mp4"
        process_clip(ffmpeg_exe, reader, clip, output_path)


if __name__ == "__main__":
    main()