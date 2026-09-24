"""
Batch Compile: Kill-Feed Detection + Trim + Speed-Ramp + Overlay + Compile
--------------------------------------------------------------------------
Extracts kill events via GPU OCR, crops gameplay to vertical 9:16,
and re-lays the original top-right killfeed as an overlay ~200px below
the top-right corner.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

from stage2_detect_peaks import get_ocr_reader, detect_killfeed_peaks

RAW_CLIPS_DIR = Path("raw_clips")
PROCESSED_DIR = RAW_CLIPS_DIR / "processed"
OUTPUT_DIR = Path("output")
TEMP_DIR = Path("temp")

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.15


# --- Kill-Feed Overlay Configuration ---
# Source coordinates on 1920x1080 canvas
KF_CROP_X = 1350
KF_CROP_Y = 90          # Shifted up by 10px (was 100) to capture 10px more headroom at the top
KF_CROP_W = 560
KF_CROP_H = 200         # Expanded height by 10px (was 190) so bottom cutoff point stays identical

# Position on final 1080x1920 vertical canvas
KF_OVERLAY_X = "W-w-24" # 24px padding from right edge
KF_OVERLAY_Y = "300"    # Moved 100px lower (was 200) to sit at 300px from top
KF_SCALE_W = 480

LEAD_BUFFER_SECONDS = 5.0
TRAIL_BUFFER_SECONDS = 2.0

GAP_SPEEDUP_THRESHOLD_SECONDS = 10.0
SPEEDUP_FACTOR = 2.0
SPEEDUP_EDGE_BUFFER_SECONDS = 2.0

CONTENT_BUDGET_SECONDS = 60.0 - 2.0 - 2.0  # 56s total allowance
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


def build_action_blocks(peaks, duration):
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
            pieces.append(("normal", gap_start, gap_end))

        pieces.append(("normal", *action_blocks[i]))

    return pieces


def get_base_filtergraph() -> str:
    kf_scale = f",scale={KF_SCALE_W}:-1" if KF_SCALE_W else ""
    return (
        f"split=2[main][kf];"
        f"[main]crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black[bg];"
        f"[kf]crop={KF_CROP_W}:{KF_CROP_H}:{KF_CROP_X}:{KF_CROP_Y}{kf_scale}[feed];"
        f"[bg][feed]overlay={KF_OVERLAY_X}:{KF_OVERLAY_Y}"
    )


def export_segment(ffmpeg_exe: str, clip: Path, start: float, end: float, out_path: Path) -> bool:
    vf = get_base_filtergraph()
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
    base_vf = get_base_filtergraph()
    vf = (
        f"{base_vf},"
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


def process_clip(ffmpeg_exe: str, reader, clip: Path, output_path: Path) -> bool:
    print(f"  Scanning kill-feed for {clip.name}...")
    peaks, duration = detect_killfeed_peaks(reader, clip)

    if not peaks:
        print("    No kills detected - exporting full clip as fallback.")

    action_blocks = build_action_blocks(peaks, duration)
    pieces = build_pieces(action_blocks)

    print(f"  {len(pieces)} piece(s) after gap analysis:")
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

    reader = get_ocr_reader()

    stage_outputs = []
    for clip in raw_clips:
        print(f"\nProcessing {clip.name}...")
        out_path = OUTPUT_DIR / f"{clip.stem}_vertical.mp4"
        if process_clip(ffmpeg_exe, reader, clip, out_path):
            stage_outputs.append(out_path)

    if not stage_outputs:
        print("No clips were successfully processed. Stopping.")
        sys.exit(1)

    durations = [get_duration(ffprobe_exe, p) for p in stage_outputs]
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
    if len(stage_outputs) == 1:
        shutil.copy(stage_outputs[0], final_output)
        print(f"Single clip - copied directly to {final_output.name}")
    else:
        if not concat_with_crossfade(ffmpeg_exe, stage_outputs, durations, final_output):
            sys.exit(1)

    for clip in raw_clips:
        shutil.move(str(clip), str(PROCESSED_DIR / clip.name))
    print(f"\nArchived {len(raw_clips)} raw clip(s) to {PROCESSED_DIR}")
    print(f"Done: {final_output}")


if __name__ == "__main__":
    main()