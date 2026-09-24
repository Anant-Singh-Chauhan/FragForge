"""
Stage 2: Detect Highlight Candidates via Audio Peaks
------------------------------------------------------
For each raw clip, extracts the audio track and finds moments where volume
spikes sharply above the surrounding baseline - a cheap, reliable proxy for
"something happened" (gunfire, a kill sound, a callout) in Valorant/CS2 footage.

This does NOT cut anything yet - it just prints candidate timestamps so you
can sanity-check them against clips you already know are good, before we
wire this into automatic extraction.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\stage2_detect_peaks.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np

RAW_CLIPS_DIR = Path("raw_clips")
TEMP_AUDIO_DIR = Path("temp")

# How far above the average volume a moment must be to count as a "peak"
# Higher = fewer, more confident peaks. Lower = more (possibly noisier) peaks.
PEAK_THRESHOLD_STD = 2.0

# Minimum gap between two peaks (seconds) - avoids flagging the same gunfight
# multiple times a fraction of a second apart.
MIN_GAP_SECONDS = 3.0


def resolve_ffmpeg():
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        print("ffmpeg not found on PATH. Open a fresh terminal and try again.")
        sys.exit(1)
    return ffmpeg_path


def extract_audio(ffmpeg_exe: str, video_path: Path, audio_path: Path):
    """Pull just the audio track out of the clip as a .wav file for analysis."""
    cmd = [
        ffmpeg_exe,
        "-i", str(video_path),
        "-vn",              # no video
        "-ac", "1",         # mono - simpler for volume analysis
        "-ar", "22050",     # standard sample rate for audio analysis
        "-y",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Audio extraction FAILED: {video_path.name}")
        print(result.stderr[-500:])
        return False
    return True


def find_peaks(audio_path: Path):
    """
    Load the audio and find timestamps where volume (RMS energy) spikes
    well above the clip's own average - these are our highlight candidates.
    """
    y, sr = librosa.load(str(audio_path), sr=None)

    # RMS = root-mean-square energy, a standard measure of loudness over time
    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    times = librosa.times_like(rms, sr=sr, hop_length=hop_length)

    mean, std = np.mean(rms), np.std(rms)
    threshold = mean + PEAK_THRESHOLD_STD * std

    candidate_times = times[rms > threshold]

    # Collapse candidates that are too close together into single peaks
    peaks = []
    for t in candidate_times:
        if not peaks or (t - peaks[-1]) >= MIN_GAP_SECONDS:
            peaks.append(t)

    return peaks


def main():
    ffmpeg_exe = resolve_ffmpeg()

    if not RAW_CLIPS_DIR.exists():
        print(f"Input folder not found: {RAW_CLIPS_DIR}.")
        sys.exit(1)

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

        peaks = find_peaks(audio_path)

        if not peaks:
            print("  No strong peaks found - try lowering PEAK_THRESHOLD_STD.")
        else:
            print(f"  Found {len(peaks)} candidate moment(s):")
            for t in peaks:
                minutes, seconds = divmod(t, 60)
                print(f"    {int(minutes):02d}:{seconds:05.2f}")


if __name__ == "__main__":
    main()