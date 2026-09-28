"""
Batch Compile: Multi-Game Dynamic Compiler
------------------------------------------
1. Discovers clips strictly from immediate game folders (raw_clips/valo/, raw_clips/cs2/).
2. Never enters nested subfolders (comp pistols, dump, etc.).
3. Renders trimmed clips with HUD overlays to TRIMMED_DIR/<game_dir>_trim_YYYYMMDD_HHMMSS.mp4.
4. Checks 56s Shorts budget per game with a 30s interactive timeout prompt.
5. Compiles each game into its own Short: OUTPUT_DIR/<game_dir>_short_YYYYMMDD_HHMMSS.mp4.
6. Archives source files to PROCESSED_DIR/<game_dir>/.
"""

from datetime import datetime
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

from profiles import (
    RAW_CLIPS_DIR,
    OUTPUT_DIR,
    TRIMMED_DIR,
    PROCESSED_DIR,
    TEMP_DIR,
    PROFILES,
    get_profile,
    identify_game,
)
from stage2_detect_peaks import get_ocr_reader, detect_killfeed_peaks

TARGET_FPS = 60
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
ZOOM_OUT_FACTOR = 1.15

VIDEO_BOTTOM_Y = 1795
BOTTOM_PADDING = 36

KF_OVERLAY_X = "W-w-24"
KF_OVERLAY_Y = "300"

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
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", str(path),
    ]
    parts = subprocess.run(cmd, capture_output=True, text=True).stdout.strip().split("x")
    width, height = int(parts[0]), int(parts[1])

    cmd_dur = [
        ffprobe_exe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    duration = float(subprocess.run(cmd_dur, capture_output=True, text=True).stdout.strip())
    return width, height, duration


def discover_clips_by_game() -> Dict[str, List[Path]]:
    """
    Shallow scan only. Inspects files directly inside raw_clips/<game>/
    and never descends into subdirectories.
    """
    exts = {".mp4", ".mkv", ".mov"}
    clips_by_game: Dict[str, List[Path]] = {k: [] for k in PROFILES}

    if not RAW_CLIPS_DIR.exists():
        return clips_by_game

    # 1. Scan direct game folders (non-recursive)
    for key, prof in PROFILES.items():
        folder_names = {prof.get("dir_name", key)}
        folder_names.update(prof.get("folder_aliases", []))

        for fname in folder_names:
            subfolder = RAW_CLIPS_DIR / fname
            if subfolder.exists() and subfolder.is_dir():
                for f in subfolder.iterdir():
                    # Strictly check is_file to ignore subfolders like dump/
                    if f.is_file() and f.suffix.lower() in exts:
                        if f not in clips_by_game[key]:
                            clips_by_game[key].append(f)

    # 2. Check root raw_clips/ directly (non-recursive)
    for f in RAW_CLIPS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in exts:
            game_key = identify_game(f)
            if game_key and f not in clips_by_game[game_key]:
                clips_by_game[game_key].append(f)

    return clips_by_game


def prompt_user_timeout(prompt: str, timeout: int = 30) -> bool:
    print(f"\n{prompt}")
    print(f"Compile master Short anyway? (y/n) [Auto-skip in {timeout}s]: ", end="", flush=True)

    if sys.platform == "win32":
        try:
            import msvcrt
            start_time = time.time()
            while time.time() - start_time < timeout:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch().lower()
                    print(ch)
                    return ch == "y"
                time.sleep(0.05)
            print(f"\n[Timeout] {timeout}s elapsed without input. Proceeding with trimmed clips only.")
            return False
        except Exception:
            pass

    import threading
    result = [False]

    def get_input():
        try:
            ans = input().strip().lower()
            result[0] = (ans == "y")
        except Exception:
            pass

    t = threading.Thread(target=get_input, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        print(f"\n[Timeout] {timeout}s elapsed without input. Proceeding with trimmed clips only.")
        return False

    return result[0]


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


def process_clip(ffmpeg_exe: str, ffprobe_exe: str, reader, clip: Path, output_path: Path, profile: dict) -> bool:
    src_w, src_h, duration = get_video_info(ffprobe_exe, clip)
    print(f"\nScanning kill-feed: {clip.name} [{profile['name']} - {src_w}x{src_h}]...")
    peaks, _ = detect_killfeed_peaks(reader, clip, profile)

    if not peaks:
        print("  [Notice] No kills detected via OCR - exporting full clip as fallback.")
        action_blocks = [(0.0, duration)]
    else:
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


def natural_sort_key(path: Path):
    match = re.match(r"^(\d+)", path.stem)
    return int(match.group(1)) if match else float("inf")


def main():
    ffmpeg_exe = resolve_tool("ffmpeg")
    ffprobe_exe = resolve_tool("ffprobe")

    OUTPUT_DIR.mkdir(exist_ok=True)
    TRIMMED_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    clips_by_game = discover_clips_by_game()
    total_found = sum(len(c) for c in clips_by_game.values())

    if total_found == 0:
        print(f"No video files found in configured game directories under {RAW_CLIPS_DIR}.")
        sys.exit(0)

    print(f"Found {total_found} clip(s) to process:")
    for game_key, clips in clips_by_game.items():
        if clips:
            print(f"  [{game_key.upper()}]: {len(clips)} clip(s)")
            clips.sort(key=natural_sort_key)

    reader = get_ocr_reader()

    for game_key, clips in clips_by_game.items():
        if not clips:
            continue

        profile = get_profile(game_key)
        game_dir_name = profile.get("dir_name", game_key)

        print(f"\n=======================================================")
        print(f"  PROCESSING BATCH: {profile['name']} ({len(clips)} clip(s))")
        print(f"=======================================================")

        stage_outputs = []
        successful_clips = []

        for clip in clips:
            out_path = get_timestamped_path(TRIMMED_DIR, base_name=f"{game_dir_name}_trim")
            if process_clip(ffmpeg_exe, ffprobe_exe, reader, clip, out_path, profile):
                stage_outputs.append(out_path)
                successful_clips.append(clip)

        if not stage_outputs:
            print(f"No clips were successfully processed for {profile['name']}. Moving to next game.")
            continue

        durations = [get_video_info(ffprobe_exe, p)[2] for p in stage_outputs]
        total_duration = sum(durations)
        print(f"\n[{profile['name']}] Total combined duration: {total_duration:.1f}s (Budget: {CONTENT_BUDGET_SECONDS:.0f}s)")

        should_compile = True
        if total_duration > CONTENT_BUDGET_SECONDS:
            warn_msg = (
                f"WARNING: [{profile['name']}] Combined duration ({total_duration:.1f}s) "
                f"exceeds your {CONTENT_BUDGET_SECONDS:.0f}s content budget!"
            )
            should_compile = prompt_user_timeout(warn_msg, timeout=30)

        if should_compile:
            final_output = get_timestamped_path(OUTPUT_DIR, base_name=f"{game_dir_name}_short")
            if len(stage_outputs) == 1:
                shutil.copy(stage_outputs[0], final_output)
                print(f"Single clip for {profile['name']} - copied directly to {final_output.name}")
            else:
                if not concat_with_crossfade(ffmpeg_exe, stage_outputs, durations, final_output):
                    print(f"Failed compiling {profile['name']} short.")
                    continue
            print(f"Done [{profile['name']} Short]: {final_output.resolve()}")
        else:
            print(f"[{profile['name']}] Skipping master compiled short. Preserving individual trimmed clips in {TRIMMED_DIR}.")

        game_archive_dir = PROCESSED_DIR / game_dir_name
        game_archive_dir.mkdir(parents=True, exist_ok=True)
        for clip in successful_clips:
            dest = game_archive_dir / clip.name
            shutil.move(str(clip), str(dest))

        print(f"Archived {len(successful_clips)} {profile['name']} clip(s) to {game_archive_dir}")

    print("\nAll batches completed.")


if __name__ == "__main__":
    main()