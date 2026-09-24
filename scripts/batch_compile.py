"""
Batch Compile: Combine Trimmed Clips into One Short
-------------------------------------------------------
One-shot batch script (not a continuous watcher).

Workflow per raw clip:
  1. Detect audio peaks (RMS energy spikes).
  2. Drop a trailing peak if it's clearly isolated from the real action
     cluster (e.g. a laugh/callout well after the round ends) - prevents
     chasing a stray peak into a long stretch of post-round talking.
  3. Merge peaks into action "segments" using buffers around each peak.
     If the gap between two segments is large (e.g. 26s of just rotating),
     they stay SEPARATE segments - the dead time between them gets cut out
     entirely (with a quick crossfade over the cut), instead of being kept
     as part of one continuous trim.
  4. If a clip only has one segment, export it directly. If multiple,
     export each segment then crossfade-concat them into one per-clip output.

Then across all clips: check total duration against the 60s budget (minus
2s intro + 2s outro reserved for later), compile with crossfades if multiple
clips, archive raw clips to raw_clips/processed/.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\batch_compile.py
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import librosa
import numpy as np

RAW_CLIPS_DIR = Path("raw_clips")
PROCESSED_DIR = RAW_CLIPS_DIR / "processed"
OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.15

PEAK_THRESHOLD_STD = 2.8
MIN_GAP_SECONDS = 3.0
LEAD_BUFFER_SECONDS = 2.0
TRAIL_BUFFER_SECONDS = 3.0

# If the gap between two action moments exceeds this, it's a "dead" stretch
# (e.g. rotating with no shooting) - instead of cutting it out, we keep it
# but speed up the middle portion so it reads as intentional pacing rather
# than an abrupt jump cut.
GAP_SPEEDUP_THRESHOLD_SECONDS = 10.0
SPEEDUP_FACTOR = 2.0
SPEEDUP_EDGE_BUFFER_SECONDS = 1.0  # kept at normal speed on each side of a sped-up gap, for a smooth transition

# If the LAST detected peak is separated from the one before it by more than
# this, treat it as noise (a laugh, a callout after the round ends) rather
# than real action, and drop it - prevents chasing a stray peak into 20s of
# post-round talking.
TRAILING_NOISE_GAP_SECONDS = 8.0

CONTENT_BUDGET_SECONDS = 60.0 - 2.0 - 2.0  # 60s target minus 2s intro + 2s outro
CROSSFADE_SECONDS = 0.5


def resolve_ffmpeg():
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        print("ffmpeg not found on PATH.")
        sys.exit(1)
    return ffmpeg_path


def resolve_ffprobe():
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        print("ffprobe not found on PATH (ships alongside ffmpeg).")
        sys.exit(1)
    return ffprobe_path


def get_duration(ffprobe_exe: str, path: Path) -> float:
    cmd = [
        ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def extract_audio(ffmpeg_exe: str, video_path: Path, audio_path: Path) -> bool:
    cmd = [ffmpeg_exe, "-i", str(video_path), "-vn", "-ac", "1", "-ar", "22050", "-y", str(audio_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Audio extraction FAILED: {video_path.name}")
        print(result.stderr[-500:])
        return False
    return True


def find_peaks(audio_path: Path):
    """
    Isolate the percussive component of the audio (sharp transient bursts,
    like gunfire) from the harmonic component (sustained tonal sound, like
    voice/comms) before measuring loudness. This filters out a good chunk
    of false positives from callouts, announcer lines, and chatter, which
    are harmonic-dominant rather than percussive-dominant.
    """
    y, sr = librosa.load(str(audio_path), sr=None)
    duration = librosa.get_duration(y=y, sr=sr)

    # margin=3.0 biases the separation more strongly toward isolating
    # percussive content - higher values are more aggressive about
    # excluding tonal/harmonic sound.
    y_percussive = librosa.effects.percussive(y, margin=3.0)

    hop_length = 512
    rms = librosa.feature.rms(y=y_percussive, hop_length=hop_length)[0]
    times = librosa.times_like(rms, sr=sr, hop_length=hop_length)
    mean, std = np.mean(rms), np.std(rms)
    threshold = mean + PEAK_THRESHOLD_STD * std
    candidate_times = times[rms > threshold]
    peaks = []
    for t in candidate_times:
        if not peaks or (t - peaks[-1]) >= MIN_GAP_SECONDS:
            peaks.append(t)
    return peaks, duration


def strip_isolated_trailing_peaks(peaks):
    """
    Drop trailing peaks that are clearly separated from the real action
    cluster - e.g. a laugh/callout picked up well after the last real
    gunfight, which would otherwise stretch the trim into post-round talk.
    """
    peaks = list(peaks)
    while len(peaks) > 1 and (peaks[-1] - peaks[-2]) > TRAILING_NOISE_GAP_SECONDS:
        print(f"    Dropping isolated trailing peak at {peaks[-1]:.1f}s (likely post-round noise)")
        peaks.pop()
    return peaks


def build_action_blocks(peaks, duration):
    """
    Turn peaks into buffered windows, then merge windows that are close
    together (gap <= GAP_SPEEDUP_THRESHOLD_SECONDS) into one continuous
    block. Windows separated by a larger gap stay as separate blocks - the
    dead time between them becomes a speed-ramped connector (see
    build_pieces), not a cut.
    """
    if not peaks:
        return [(0.0, duration)]

    windows = [
        (max(0.0, p - LEAD_BUFFER_SECONDS), min(duration, p + TRAIL_BUFFER_SECONDS))
        for p in peaks
    ]

    merged = [windows[0]]
    for start, end in windows[1:]:
        last_start, last_end = merged[-1]
        if start - last_end <= GAP_SPEEDUP_THRESHOLD_SECONDS:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def build_pieces(action_blocks):
    """
    Turn action blocks into an ordered list of pieces to export:
    ("normal", start, end) for real action / short gaps, and
    ("sped", start, end) for the speed-ramped middle of a long gap, bookended
    by short normal-speed edges for a smooth transition.
    """
    pieces = [("normal", *action_blocks[0])]

    for i in range(1, len(action_blocks)):
        gap_start = action_blocks[i - 1][1]
        gap_end = action_blocks[i][0]
        gap_len = gap_end - gap_start

        if gap_len > GAP_SPEEDUP_THRESHOLD_SECONDS:
            edge = SPEEDUP_EDGE_BUFFER_SECONDS
            pieces.append(("normal", gap_start, gap_start + edge))
            pieces.append(("sped", gap_start + edge, gap_end - edge))
            pieces.append(("normal", gap_end - edge, gap_end))
        else:
            # Small gap - just keep it as-is, part of continuous normal footage
            pieces.append(("normal", gap_start, gap_end))

        pieces.append(("normal", *action_blocks[i]))

    return pieces


def export_segment(ffmpeg_exe: str, clip: Path, start: float, end: float, out_path: Path) -> bool:
    """Trim [start, end] at normal speed, crop/zoom to vertical, export."""
    vf = (
        f"crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    cmd = [
        ffmpeg_exe, "-ss", str(start), "-to", str(end), "-i", str(clip),
        "-vf", vf, "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    FAILED exporting segment [{start:.2f}-{end:.2f}]: {result.stderr[-500:]}")
        return False
    return True


def export_sped_segment(ffmpeg_exe: str, clip: Path, start: float, end: float, out_path: Path) -> bool:
    """
    Trim [start, end], crop/zoom to vertical, speed up by SPEEDUP_FACTOR
    (setpts speeds up video, atempo speeds up audio to match), and overlay
    a small "2X" badge so the speed change reads as intentional pacing
    rather than a glitch.
    """
    vf = (
        f"crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setpts={1/SPEEDUP_FACTOR}*PTS,"
        f"drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='2X':fontcolor=white:fontsize=48:"
        f"box=1:boxcolor=black@0.6:boxborderw=12:x=w-tw-40:y=40"
    )
    af = f"atempo={SPEEDUP_FACTOR}"
    cmd = [
        ffmpeg_exe, "-ss", str(start), "-to", str(end), "-i", str(clip),
        "-vf", vf, "-af", af, "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    FAILED exporting sped segment [{start:.2f}-{end:.2f}]: {result.stderr[-500:]}")
        return False
    return True


def concat_pieces(ffmpeg_exe: str, piece_paths: list, output_path: Path) -> bool:
    """
    Stream-copy concat a list of already-encoded pieces (same codec/resolution/
    fps) into one file - fast, no re-encoding, no crossfade artifacts. Used for
    stitching normal/sped pieces within a single source clip.
    """
    filelist_path = TEMP_DIR / f"concat_list_{output_path.stem}.txt"
    with open(filelist_path, "w") as f:
        for p in piece_paths:
            f.write(f"file '{p.resolve().as_posix()}'\n")

    cmd = [ffmpeg_exe, "-f", "concat", "-safe", "0", "-i", str(filelist_path), "-c", "copy", "-y", str(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    filelist_path.unlink(missing_ok=True)

    if result.returncode != 0:
        print(f"    Concat FAILED: {result.stderr[-500:]}")
        return False
    return True


def concat_with_crossfade(ffmpeg_exe: str, clips: list, durations: list, output_path: Path) -> bool:
    """Crossfade-concat a list of clips (video + audio) into one output."""
    inputs = []
    for clip in clips:
        inputs += ["-i", str(clip)]

    filter_parts = []
    running_offset = 0.0
    prev_video_label = "0:v"
    prev_audio_label = "0:a"

    for i in range(1, len(clips)):
        running_offset += durations[i - 1] - CROSSFADE_SECONDS
        v_out, a_out = f"v{i}", f"a{i}"
        filter_parts.append(
            f"[{prev_video_label}][{i}:v]xfade=transition=fade:"
            f"duration={CROSSFADE_SECONDS}:offset={running_offset:.3f}[{v_out}]"
        )
        filter_parts.append(f"[{prev_audio_label}][{i}:a]acrossfade=d={CROSSFADE_SECONDS}[{a_out}]")
        prev_video_label, prev_audio_label = v_out, a_out

    filter_complex = ";".join(filter_parts)

    cmd = [
        ffmpeg_exe, *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev_video_label}]", "-map", f"[{prev_audio_label}]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Compile FAILED: {result.stderr[-800:]}")
        return False
    return True


def natural_sort_key(path: Path):
    match = re.match(r"^(\d+)", path.stem)
    return int(match.group(1)) if match else float("inf")


def run_stage3_on_clip(ffmpeg_exe: str, clip: Path, output_path: Path) -> bool:
    audio_path = TEMP_DIR / f"{clip.stem}.wav"
    if not extract_audio(ffmpeg_exe, clip, audio_path):
        return False

    peaks, duration = find_peaks(audio_path)
    peaks = strip_isolated_trailing_peaks(peaks)

    print(f"    Raw peaks after noise filtering: {[f'{p:.1f}s' for p in peaks]}")

    action_blocks = build_action_blocks(peaks, duration)
    pieces = build_pieces(action_blocks)

    print(f"  {clip.name}: {len(pieces)} piece(s) after gap analysis")
    for kind, s, e in pieces:
        tag = "SPED 2x" if kind == "sped" else "normal"
        print(f"    [{s:.2f}s - {e:.2f}s] {tag}")

    if len(pieces) == 1:
        _, start, end = pieces[0]
        return export_segment(ffmpeg_exe, clip, start, end, output_path)

    temp_paths = []
    for i, (kind, s, e) in enumerate(pieces):
        temp_path = TEMP_DIR / f"{clip.stem}_piece{i}.mp4"
        exporter = export_sped_segment if kind == "sped" else export_segment
        if not exporter(ffmpeg_exe, clip, s, e, temp_path):
            return False
        temp_paths.append(temp_path)

    ok = concat_pieces(ffmpeg_exe, temp_paths, output_path)

    for t in temp_paths:
        t.unlink(missing_ok=True)

    return ok


def main():
    ffmpeg_exe = resolve_ffmpeg()
    ffprobe_exe = resolve_ffprobe()

    if not RAW_CLIPS_DIR.exists():
        print(f"Input folder not found: {RAW_CLIPS_DIR}.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    exts = {".mp4", ".mkv", ".mov"}
    raw_clips = sorted(
        [f for f in RAW_CLIPS_DIR.iterdir() if f.is_file() and f.suffix.lower() in exts],
        key=natural_sort_key,
    )

    if not raw_clips:
        print(f"No video files found in {RAW_CLIPS_DIR}.")
        sys.exit(0)

    print(f"Found {len(raw_clips)} clip(s), processing in order:")
    for c in raw_clips:
        print(f"  {c.name}")

    stage3_outputs = []
    for clip in raw_clips:
        print(f"\nProcessing {clip.name}...")
        out_path = OUTPUT_DIR / f"{clip.stem}_vertical.mp4"
        if run_stage3_on_clip(ffmpeg_exe, clip, out_path):
            stage3_outputs.append(out_path)

    if not stage3_outputs:
        print("No clips were successfully processed. Stopping.")
        sys.exit(1)

    durations = [get_duration(ffprobe_exe, p) for p in stage3_outputs]
    total_duration = sum(durations)

    print(f"\nTotal combined duration: {total_duration:.1f}s (budget: {CONTENT_BUDGET_SECONDS:.0f}s)")

    if total_duration > CONTENT_BUDGET_SECONDS:
        print(
            f"WARNING: clips total {total_duration:.1f}s, over your "
            f"{CONTENT_BUDGET_SECONDS:.0f}s content budget. Stopping without "
            f"compiling - trim a clip or remove one from raw_clips/ and re-run."
        )
        sys.exit(1)

    final_output = OUTPUT_DIR / "compiled_short.mp4"
    if len(stage3_outputs) == 1:
        shutil.copy(stage3_outputs[0], final_output)
        print(f"Single clip - copied directly to {final_output.name}")
    else:
        if not concat_with_crossfade(ffmpeg_exe, stage3_outputs, durations, final_output):
            sys.exit(1)

    for clip in raw_clips:
        shutil.move(str(clip), str(PROCESSED_DIR / clip.name))
    print(f"\nArchived {len(raw_clips)} raw clip(s) to {PROCESSED_DIR}")
    print(f"Done: {final_output}")


if __name__ == "__main__":
    main()