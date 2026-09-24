"""
Stage 1: Normalize + Crop to Vertical + Export
------------------------------------------------
Takes raw gameplay clips from raw_clips/, and for each one:
  1. Normalizes to a consistent fps/codec (so later stages don't have to
     deal with inconsistent inputs)
  2. Center-crops to 9:16 vertical (works well for Valorant/CS2 since the
     crosshair/action sits at screen center)
  3. Exports the result to output/ at Shorts spec (1080x1920)

This script only calls ffmpeg under the hood - no AI involved yet, on purpose.
Get the mechanical pipeline rock solid before layering AI decision-making on top.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\stage1_normalize_crop.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

# --- Config: adjust these as needed ---
RAW_CLIPS_DIR = Path("raw_clips")
OUTPUT_DIR = Path("output")
TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920  # Shorts spec: 1080x1920 (9:16)
ZOOM_OUT_FACTOR = 1.25  # >1.0 shows more of the original frame (zoomed out); 1.0 = tight center crop


def find_clips(folder: Path):
    """Return all video files in the given folder (mp4/mkv/mov)."""
    exts = {".mp4", ".mkv", ".mov"}
    return [f for f in folder.iterdir() if f.suffix.lower() in exts]


def process_clip(ffmpeg_exe: str, input_path: Path, output_path: Path):
    """
    Run a single ffmpeg command that does crop + normalize + export in one pass.

    ffmpeg flag breakdown:
      -i input_path       input file
      -vf "..."           video filter chain (crop, then scale - see below)
      -r TARGET_FPS        force a consistent frame rate across all clips
      -c:v libx264          encode video with H.264 (broadly compatible)
      -preset fast           encoding speed/quality tradeoff
      -crf 20                quality level (lower = better quality; 18-23 is typical)
      -c:a aac -b:a 128k       re-encode audio to AAC at a standard bitrate
      -y                    overwrite the output file if it already exists

    Filter chain (-vf):
      crop=(ih*9/16*ZOOM):ih  crop a wider-than-tight region (ZOOM_OUT_FACTOR
                              controls how much extra width is kept, i.e. how
                              zoomed-out the result looks), centered, full height
      scale=W:H               resize that region down to the exact Shorts
                              target resolution - this is what makes it look
                              "zoomed out" vs a tight crop
    """
    vf = f"crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,scale={TARGET_WIDTH}:{TARGET_HEIGHT}"

    cmd = [
        ffmpeg_exe,
        "-i", str(input_path),
        "-vf", vf,
        "-r", str(TARGET_FPS),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-y",
        str(output_path),
    ]

    print(f"Processing: {input_path.name} -> {output_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  FAILED: {input_path.name}")
        print(result.stderr[-500:])  # last 500 chars of ffmpeg's error output, usually the useful part
    else:
        print(f"  Done: {output_path.name}")


def resolve_ffmpeg():
    """
    Find ffmpeg's full path using Python's own PATH search (shutil.which),
    rather than letting subprocess try to find it at launch time. This avoids
    a known Windows quirk where a terminal's PATH works fine for direct
    commands but subprocess.run() still fails to locate the executable.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        print("ffmpeg not found on PATH.")
        print("Try: close this terminal, open a fresh one, and re-run.")
        print("If that doesn't fix it, re-check the PATH entry we added earlier.")
        sys.exit(1)
    return ffmpeg_path


def main():
    ffmpeg_exe = resolve_ffmpeg()
    print(f"Using ffmpeg at: {ffmpeg_exe}\n")

    if not RAW_CLIPS_DIR.exists():
        print(f"Input folder not found: {RAW_CLIPS_DIR}. Create it and drop clips in first.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)

    clips = find_clips(RAW_CLIPS_DIR)
    if not clips:
        print(f"No video files found in {RAW_CLIPS_DIR}. Drop some .mp4/.mkv/.mov files in and re-run.")
        sys.exit(0)

    print(f"Found {len(clips)} clip(s) to process.\n")

    for clip in clips:
        output_path = OUTPUT_DIR / f"{clip.stem}_vertical.mp4"
        process_clip(ffmpeg_exe, clip, output_path)


if __name__ == "__main__":
    main()