"""
Batch Compile: Multi-Game (Valorant & CS2) Dynamic Compiler
------------------------------------------------------------
Automatically detects game profile from folder (raw_clips/valorant or raw_clips/cs2),
scales normalized crops to any source resolution, renders blurred video background,
and composites HUD overlays.
"""

from datetime import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

from profiles import get_profile
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

VIDEO_BOTTOM_Y = 1795  # Active video boundary
BOTTOM_PADDING = 36    # Margin above video edge

KF_OVERLAY_X = "W-w-24"
KF_OVERLAY_Y = "300"

GAP_SPEEDUP_THRESHOLD_SECONDS = 10.0
SPEEDUP_FACTOR = 2.0
SPEEDUP_EDGE_BUFFER_SECONDS = 2.0

CONTENT_BUDGET_SECONDS = 60.0 - 2.0 - 2.0  # 56s content allowance
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


def resolve_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        print(f"Tool not found on PATH: {name}")
        sys.exit(1)
    return path


def get_video_info(ffprobe_exe: str, path: Path) -> Tuple[int, int, float]:
    cmd = [
        ffprobe_exe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "csv=s=x:p=0", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    parts = result.stdout.strip().split("x")
    width = int(parts[0])
    height = int(parts[1].split()[0])
    
    cmd_dur = [
        ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    res_dur = subprocess.run(cmd_dur, capture_output=True, text=True)
    duration = float(res_dur.stdout.strip())
    return width, height, duration


def build_action_blocks(peaks: List[float], duration: float, lead: float, trail: float):
    if not peaks:
        return [(0.0, duration)]

    windows = [(max(0.0, p - lead), min(duration, p + trail)) for p in peaks]
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


def get_filtergraph(profile: dict, src_w: int, src_h: int) -> str:
    # Scale normalized fractions to exact source pixels
    def to_rect(norm_box):
        x1, y1, x2, y2 = norm_box
        return int(x1 * src_w), int(y1 * src_h), int((x2 - x1) * src_w), int((y2 - y1) * src_h)

    kfx, kfy, kfw, kfh = to_rect(profile["killfeed_crop"])
    hpx, hpy, hpw, hph = to_rect(profile["health_crop"])
    amx, amy, amw, amh = to_rect(profile["ammo_crop"])

    hp_y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"
    ammo_y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"

    return (
        f"split=5[bg_in][main][kf][hp][ammo];"
        f"[bg_in]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},boxblur=25:5,eq=brightness=-0.1[bg];"
        f"[main]crop=ih*9/16*{ZOOM_OUT_FACTOR}:ih,scale={TARGET_WIDTH}:-2[vid];"
        f"[kf]crop={kfw}:{kfh}:{kfx}:{kfy},scale={profile['kf_overlay_w']}:-2[feed];"
        f"[hp]crop={hpw}:{hph}:{hpx}:{hpy},scale={profile['hp_overlay_w']}:-2[health];"
        f"[ammo]crop={amw}:{amh}:{amx}:{amy},scale={profile['ammo_overlay_w']}:-2[ammunition];"
        f"[bg][vid]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base][feed]overlay={KF_OVERLAY_X}:{KF_OVERLAY_Y}[v1];"
        f"[v1][health]overlay=0:{hp_y}[v2];"
        f"[v2][ammunition]overlay=W-w:{ammo_y}"
    )


def export_segment(ffmpeg_exe: str, clip: Path, start: float, end: float, vf: str, out_path: Path) -> bool:
    cmd = [
        ffmpeg_exe, "-ss", str(start), "-to", str(end), "-i", str(clip),
        "-vf", vf, "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def export_sped_segment(ffmpeg_exe: str, clip: Path, start: float, end: float, vf: str, out_path: Path) -> bool:
    sped_vf = (
        f"{vf},"
        f"setpts={1/SPEEDUP_FACTOR}*PTS,"
        f"drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='2X':fontcolor=white:fontsize=48:"
        f"box=1:boxcolor=black@0.6:boxborderw=12:x=w-tw-40:y=40"
    )
    cmd = [
        ffmpeg_exe, "-ss", str(start), "-to", str(end), "-i", str(clip),
        "-vf", sped_vf, "-af", f"atempo={SPEEDUP_FACTOR}", "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def concat_pieces(ffmpeg_exe: str, piece_paths: List[Path], output_path: Path) -> bool:
    filelist_path = TEMP_DIR / f"concat_list_{output_path.stem}.txt"
    with open(filelist_path, "w") as f:
        for p in piece_paths:
            f.write(f"file '{p.resolve().as_posix()}'\n")

    cmd = [ffmpeg_exe, "-f", "concat", "-safe", "0", "-i", str(filelist_path), "-c", "copy", "-y", str(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    filelist_path.unlink(missing_ok=True)
    return result.returncode == 0


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

    cmd = [
        ffmpeg_exe, *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{prev_video_label}]", "-map", f"[{prev_audio_label}]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def identify_game(clip_path: Path) -> str:
    parent = clip_path.parent.name.lower()
    if "cs2" in parent or "counter" in parent:
        return "cs2"
    if "val" in parent:
        return "valorant"
    # Fallback to clip name search
    name = clip_path.name.lower()
    if "cs2" in name or "counter" in name:
        return "cs2"
    return "valorant"


def process_clip(ffmpeg_exe: str, ffprobe_exe: str, reader, clip: Path, output_path: Path) -> bool:
    game_key = identify_game(clip)
    profile = get_profile(game_key)
    src_w, src_h, duration = get_video_info(ffprobe_exe, clip)

    print(f"\nProcessing {clip.name} [{profile['name']} - {src_w}x{src_h}]...")
    peaks, _ = detect_killfeed_peaks(reader, clip, profile)

    if not peaks:
        print("  No kills detected - skipping clip.")
        return False

    action_blocks = build_action_blocks(peaks, duration, profile["lead_buffer"], profile["trail_buffer"])
    pieces = build_pieces(action_blocks)
    vf = get_filtergraph(profile, src_w, src_h)

    print(f"  {len(pieces)} piece(s) generated after gap analysis:")
    for kind, s, e in pieces:
        tag = "SPED 2x" if kind == "sped" else "normal"
        print(f"    [{s:.2f}s - {e:.2f}s] {tag}")

    if len(pieces) == 1:
        _, start, end = pieces[0]
        return export_segment(ffmpeg_exe, clip, start, end, vf, output_path)

    temp_paths = []
    for i, (kind, s, e) in enumerate(pieces):
        temp_path = TEMP_DIR / f"{clip.stem}_piece{i}.mp4"
        exporter = export_sped_segment if kind == "sped" else export_segment
        if not exporter(ffmpeg_exe, clip, s, e, vf, temp_path):
            return False
        temp_paths.append(temp_path)

    ok = concat_pieces(ffmpeg_exe, temp_paths, output_path)
    for t in temp_paths:
        t.unlink(missing_ok=True)

    return ok


def main():
    ffmpeg_exe = resolve_tool("ffmpeg")
    ffprobe_exe = resolve_tool("ffprobe")

    OUTPUT_DIR.mkdir(exist_ok=True)
    TRIMMED_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    # Automatically scan root raw_clips, raw_clips/valorant, and raw_clips/cs2
    exts = {".mp4", ".mkv", ".mov"}
    search_dirs = [RAW_CLIPS_DIR, RAW_CLIPS_DIR / "valorant", RAW_CLIPS_DIR / "cs2"]
    raw_clips = []
    for d in search_dirs:
        if d.exists():
            raw_clips.extend([f for f in d.iterdir() if f.is_file() and f.suffix.lower() in exts])

    if not raw_clips:
        print(f"No video files found in {RAW_CLIPS_DIR} (checked valorant/ and cs2/ subfolders).")
        sys.exit(0)

    print(f"Found {len(raw_clips)} clip(s) to process:")
    for c in raw_clips:
        print(f"  [{identify_game(c).upper()}] {c.name}")

    reader = get_ocr_reader()

    stage_outputs = []
    successful_clips = []

    for clip in raw_clips:
        out_path = get_timestamped_path(TRIMMED_DIR, base_name="trim")
        if process_clip(ffmpeg_exe, ffprobe_exe, reader, clip, out_path):
            stage_outputs.append(out_path)
            successful_clips.append(clip)

    if not stage_outputs:
        print("\nNo clips were successfully processed. Stopping.")
        sys.exit(1)

    durations = [get_video_info(ffprobe_exe, p)[2] for p in stage_outputs]
    total_duration = sum(durations)
    print(f"\nTotal combined duration: {total_duration:.1f}s (budget: {CONTENT_BUDGET_SECONDS:.0f}s)")

    if total_duration > CONTENT_BUDGET_SECONDS:
        print(f"WARNING: clips total {total_duration:.1f}s, over budget ({CONTENT_BUDGET_SECONDS:.0f}s).")

    final_output = get_timestamped_path(OUTPUT_DIR, base_name="short")
    if len(stage_outputs) == 1:
        shutil.copy(stage_outputs[0], final_output)
        print(f"Single clip - copied directly to {final_output.name}")
    else:
        if not concat_with_crossfade(ffmpeg_exe, stage_outputs, durations, final_output):
            sys.exit(1)

    for clip in successful_clips:
        dest = PROCESSED_DIR / clip.name
        shutil.move(str(clip), str(dest))

    print(f"\nArchived {len(successful_clips)} clip(s) to {PROCESSED_DIR}")
    print(f"Done: {final_output}")


if __name__ == "__main__":
    main()