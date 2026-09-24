"""
Batch Compile: Kill-Feed Detection + Trim + Speed-Ramp + Video-Locked HUD Overlays + Compile
--------------------------------------------------------------------------------------------
Workflow:
  1. Detects kill action via GPU OCR.
  2. Crops 9:16 vertical gameplay and pads to 1080x1920.
  3. Overlays Kill-Feed at Y=300.
  4. Overlays Health & Ammo inside the gameplay area with a 36px buffer above the bottom video edge.
  5. Exports per-clip cuts to output/trimmed/trim_YYYYMMDD_HHMMSS.mp4.
  6. Crossfade-compiles into output/short_YYYYMMDD_HHMMSS.mp4.
"""

from datetime import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

from stage2_detect_peaks import get_ocr_reader, detect_killfeed_peaks

RAW_CLIPS_DIR = Path("raw_clips")
PROCESSED_DIR = RAW_CLIPS_DIR / "processed"
OUTPUT_DIR = Path("output")
TRIMMED_DIR = OUTPUT_DIR / "trimmed"
TEMP_DIR = Path("temp")

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.15

# --- Canvas Geometry ---
VIDEO_BOTTOM_Y = 1795  # Lower edge of active gameplay footage (above bottom letterbox)
BOTTOM_PADDING = 36    # 36px padding above the video bottom boundary

# --- 1. Kill-Feed Overlay Configuration ---
KF_CROP_X = 1350
KF_CROP_Y = 90
KF_CROP_W = 560
KF_CROP_H = 120
KF_OVERLAY_X = "W-w-24"
KF_OVERLAY_Y = "300"
KF_SCALE_W = 480

# --- 2. Health HUD Configuration (Bottom-Left, inside video + 36px padding) ---
HP_CROP_X = 525
HP_CROP_Y = 1000
HP_CROP_W = 130
HP_CROP_H = 50
HP_OVERLAY_X = "0"
HP_OVERLAY_Y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"
HP_SCALE_W = 220

# --- 3. Ammo HUD Configuration (Bottom-Right, inside video + 36px padding) ---
AMMO_CROP_X = 1267
AMMO_CROP_Y = 1000
AMMO_CROP_W = 130
AMMO_CROP_H = 50
AMMO_OVERLAY_X = "W-w"
AMMO_OVERLAY_Y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"
AMMO_SCALE_W = 220

LEAD_BUFFER_SECONDS = 5.0
TRAIL_BUFFER_SECONDS = 2.0

GAP_SPEEDUP_THRESHOLD_SECONDS = 10.0
SPEEDUP_FACTOR = 2.0
SPEEDUP_EDGE_BUFFER_SECONDS = 2.0

CONTENT_BUDGET_SECONDS = 60.0 - 2.0 - 2.0  # 56s total allowance
CROSSFADE_SECONDS = 0.5


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
    kf_scale = f",scale={KF_SCALE_W}:-2" if KF_SCALE_W else ""
    hp_scale = f",scale={HP_SCALE_W}:-2" if HP_SCALE_W else ""
    ammo_scale = f",scale={AMMO_SCALE_W}:-2" if AMMO_SCALE_W else ""

    return (
        f"split=4[main][kf][hp][ammo];"
        f"[main]crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,"
        f"scale={TARGET_WIDTH}:-2,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black[bg];"
        f"[kf]crop={KF_CROP_W}:{KF_CROP_H}:{KF_CROP_X}:{KF_CROP_Y}{kf_scale}[feed];"
        f"[hp]crop={HP_CROP_W}:{HP_CROP_H}:{HP_CROP_X}:{HP_CROP_Y}{hp_scale}[health];"
        f"[ammo]crop={AMMO_CROP_W}:{AMMO_CROP_H}:{AMMO_CROP_X}:{AMMO_CROP_Y}{ammo_scale}[ammunition];"
        f"[bg][feed]overlay={KF_OVERLAY_X}:{KF_OVERLAY_Y}[v1];"
        f"[v1][health]overlay={HP_OVERLAY_X}:{HP_OVERLAY_Y}[v2];"
        f"[v2][ammunition]overlay={AMMO_OVERLAY_X}:{AMMO_OVERLAY_Y}"
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


def concat_pieces(ffmpeg_exe: str, piece_paths: List[Path], output_path: Path) -> bool:
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


def concat_with_crossfade(ffmpeg_exe: str, clips: List[Path], durations: List[float], output_path: Path) -> bool:
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
    TRIMMED_DIR.mkdir(parents=True, exist_ok=True)
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
        out_path = get_timestamped_path(TRIMMED_DIR, base_name="trim")
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

    final_output = get_timestamped_path(OUTPUT_DIR, base_name="short")
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