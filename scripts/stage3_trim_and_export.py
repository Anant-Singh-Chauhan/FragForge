"""
Stage 3: Trim Dead Air + Crop to Vertical + Export
-----------------------------------------------------
Combines what we built in Stage 1 and Stage 2:
  1. Detect audio peaks (same logic as stage2_detect_peaks.py)
  2. Trim the clip so it starts just before the FIRST peak and ends just
     after the LAST peak - cutting the idle "walking around" dead air at
     the start/end, while keeping everything in between untouched and
     continuous (no internal jump cuts)
  3. Center-crop to vertical with the zoom-out factor, scale to Shorts spec,
     and export - same as Stage 1

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\stage3_trim_and_export.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np

RAW_CLIPS_DIR = Path("raw_clips")
OUTPUT_DIR = Path("output")
TEMP_AUDIO_DIR = Path("temp")

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.25

PEAK_THRESHOLD_STD = 2.0
MIN_GAP_SECONDS = 3.0

# How much buffer to keep before the first peak / after the last peak,
# so the cut doesn't feel like it starts/ends mid-action.
LEAD_BUFFER_SECONDS = 2.0
TRAIL_BUFFER_SECONDS = 3.0


def resolve_ffmpeg():
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        print("ffmpeg not found on PATH. Open a fresh terminal and try again.")
        sys.exit(1)
    return ffmpeg_path


def extract_audio(ffmpeg_exe: str, video_path: Path, audio_path: Path):
    cmd = [
        ffmpeg_exe, "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "22050", "-y", str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Audio extraction FAILED: {video_path.name}")
        print(result.stderr[-500:])
        return False
    return True


def find_peaks(audio_path: Path):
    y, sr = librosa.load(str(audio_path), sr=None)
    duration = librosa.get_duration(y=y, sr=sr)

    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.times_like(rms, sr=sr, hop_length=hop_length)

    mean, std = np.mean(rms), np.std(rms)
    threshold = mean + PEAK_THRESHOLD_STD * std
    candidate_times = times[rms > threshold]

    peaks = []
    for t in candidate_times:
        if not peaks or (t - peaks[-1]) >= MIN_GAP_SECONDS:
            peaks.append(t)

    return peaks, duration


def process_clip(ffmpeg_exe: str, input_path: Path, output_path: Path, start: float, end: float):
    """
    Trim to [start, end], crop/zoom to vertical, scale to target size, export.
    -ss before -i seeks fast (less precise); since we don't need frame-exact
    trimming here, this keeps processing quick.

    Filter chain (-vf):
      crop=(ih*9/16*ZOOM):ih   crop a wider-than-tight region (ZOOM_OUT_FACTOR
                               controls how much extra width is kept), centered,
                               full height
      scale=W:-2               scale to target width, height auto-computed to
                               PRESERVE aspect ratio (no stretching/distortion)
      pad=W:H:...:black        add black letterbox bars top/bottom to fill the
                               remaining height up to the exact Shorts target -
                               this is what creates the "zoomed out" look
                               without squishing the image
    """
    vf = (
        f"crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black"
    )

    cmd = [
        ffmpeg_exe,
        "-ss", str(start),
        "-to", str(end),
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

    print(f"Processing: {input_path.name} [{start:.2f}s - {end:.2f}s] -> {output_path.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  FAILED: {input_path.name}")
        print(result.stderr[-500:])
    else:
        print(f"  Done: {output_path.name}")


def main():
    ffmpeg_exe = resolve_ffmpeg()

    if not RAW_CLIPS_DIR.exists():
        print(f"Input folder not found: {RAW_CLIPS_DIR}.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_AUDIO_DIR.mkdir(exist_ok=True)

    exts = {".mp4", ".mkv", ".mov"}
    clips = [f for f in RAW_CLIPS_DIR.iterdir() if f.suffix.lower() in exts]

    if not clips:
        print(f"No video files found in {RAW_CLIPS_DIR}.")
        sys.exit(0)

    for clip in clips:
        print(f"\n{clip.name}")
        audio_path = TEMP_AUDIO_DIR / f"{clip.stem}.wav"

        if not extract_audio(ffmpeg_exe, clip, audio_path):
            continue

        peaks, duration = find_peaks(audio_path)

        if not peaks:
            print("  No peaks found - skipping trim, exporting full clip.")
            start, end = 0.0, duration
        else:
            start = max(0.0, peaks[0] - LEAD_BUFFER_SECONDS)
            end = min(duration, peaks[-1] + TRAIL_BUFFER_SECONDS)

        output_path = OUTPUT_DIR / f"{clip.stem}_vertical.mp4"
        process_clip(ffmpeg_exe, clip, output_path, start, end)


if __name__ == "__main__":
    main()