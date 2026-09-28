"""
Stage 3: Single-Clip Multi-Game Processor
-----------------------------------------
Standalone runner for single clips. Shallow scan only (no subdirectories).
Outputs to: TRIMMED_DIR/<game_dir>_trim_YYYYMMDD_HHMMSS.mp4.
"""

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from profiles import (
    RAW_CLIPS_DIR,
    OUTPUT_DIR,
    TRIMMED_DIR,
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
        ffprobe_exe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path),
    ]
    parts = subprocess.run(cmd, capture_output=True, text=True).stdout.strip().split("x")
    width, height = int(parts[0]), int(parts[1])

    cmd_dur = [
        ffprobe_exe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    duration = float(subprocess.run(cmd_dur, capture_output=True, text=True).stdout.strip())
    return width, height, duration


def discover_clips_by_game() -> List[Path]:
    exts = {".mp4", ".mkv", ".mov"}
    clips = []

    if not RAW_CLIPS_DIR.exists():
        return clips

    for key, prof in PROFILES.items():
        folder_names = {prof.get("dir_name", key)}
        folder_names.update(prof.get("folder_aliases", []))

        for fname in folder_names:
            subfolder = RAW_CLIPS_DIR / fname
            if subfolder.exists() and subfolder.is_dir():
                for f in subfolder.iterdir():
                    if f.is_file() and f.suffix.lower() in exts and f not in clips:
                        clips.append(f)

    for f in RAW_CLIPS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in exts:
            if identify_game(f) and f not in clips:
                clips.append(f)

    return clips


def process_clip(ffmpeg_exe: str, ffprobe_exe: str, reader, input_path: Path, output_path: Path):
    game_key = identify_game(input_path)
    if not game_key:
        print(f"Skipping unassigned clip: {input_path.name}")
        return

    profile = get_profile(game_key)
    src_w, src_h, duration = get_video_info(ffprobe_exe, input_path)

    print(f"\nProcessing {input_path.name} [{profile['name']}]...")
    peaks, _ = detect_killfeed_peaks(reader, input_path, profile)

    if not peaks:
        print("  [Notice] No kills detected - exporting full clip as fallback.")
        start, end = 0.0, duration
    else:
        start = max(0.0, peaks[0] - profile["lead_buffer"])
        end = min(duration, peaks[-1] + profile["trail_buffer"])

    def to_rect(norm_box):
        x1, y1, x2, y2 = norm_box
        return int(x1 * src_w), int(y1 * src_h), int((x2 - x1) * src_w), int((y2 - y1) * src_h)

    kfx, kfy, kfw, kfh = to_rect(profile["killfeed_crop"])
    hpx, hpy, hpw, hph = to_rect(profile["health_crop"])
    amx, amy, amw, amh = to_rect(profile["ammo_crop"])

    hp_y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"
    ammo_y = f"{VIDEO_BOTTOM_Y}-h-{BOTTOM_PADDING}"

    vf = (
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

    cmd = [
        ffmpeg_exe, "-ss", str(start), "-to", str(end), "-i", str(input_path),
        "-vf", vf, "-r", str(TARGET_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-y", str(output_path),
    ]

    print(f"  Trimming [{start:.2f}s - {end:.2f}s] -> {output_path.name}")
    subprocess.run(cmd, check=True)
    print(f"  Done: {output_path.resolve()}")


def main():
    ffmpeg_exe = resolve_tool("ffmpeg")
    ffprobe_exe = resolve_tool("ffprobe")

    OUTPUT_DIR.mkdir(exist_ok=True)
    TRIMMED_DIR.mkdir(parents=True, exist_ok=True)

    clips = discover_clips_by_game()
    if not clips:
        print("No clips found in configured game directories.")
        sys.exit(0)

    reader = get_ocr_reader()
    for clip in clips:
        game_key = identify_game(clip)
        profile = get_profile(game_key)
        game_dir_name = profile.get("dir_name", game_key)
        out_path = get_timestamped_path(TRIMMED_DIR, base_name=f"{game_dir_name}_trim")
        process_clip(ffmpeg_exe, ffprobe_exe, reader, clip, out_path)


if __name__ == "__main__":
    main()