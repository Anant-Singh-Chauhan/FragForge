"""
Batch Compile: Multi-Game Dynamic Compiler with Intro, Outro & Sync-Locked BGM
------------------------------------------------------------------------------
Accepts optional CLI arguments:
  --game {valo,cs2,all}  : Limit batch compile to a specific game (default: all)
  --yes, -y              : Automatically approve compilation if over budget
"""

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Tuple

from profiles import (
    RAW_CLIPS_DIR,
    OUTPUT_DIR,
    TRIMMED_DIR,
    PROCESSED_DIR,
    TEMP_DIR,
    LOGO_PATH,
    BGM_PATH,
    GLITCH_SFX_PATH,
    SUBS_CLIP_PATH,
    INTRO_DURATION,
    LOGO_OUTRO_DURATION,
    INTRO_START_ZOOM,
    GLITCH_VOLUME,
    BGM_START_TIMESTAMP,
    BGM_VOLUME,
    BGM_FADE_DURATION,
    CROSSFADE_SECONDS,
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

# Suppress console windows on Windows for child FFmpeg/FFprobe processes
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def run_quiet_process(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run that suppresses pop-up console windows on Windows."""
    return subprocess.run(cmd, creationflags=NO_WINDOW, **kwargs)


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
        print(f"Tool not found on PATH: {name}", flush=True)
        sys.exit(1)
    return path


def get_video_info(ffprobe_exe: str, path: Path) -> Tuple[int, int, float]:
    cmd = [
        ffprobe_exe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", str(path),
    ]
    parts = run_quiet_process(cmd, capture_output=True, text=True).stdout.strip().split("x")
    width, height = int(parts[0]), int(parts[1])

    cmd_dur = [
        ffprobe_exe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    duration = float(run_quiet_process(cmd_dur, capture_output=True, text=True).stdout.strip())
    return width, height, duration


def discover_clips_by_game(filter_game: str = "all") -> Dict[str, List[Path]]:
    exts = {".mp4", ".mkv", ".mov"}
    clips_by_game: Dict[str, List[Path]] = {k: [] for k in PROFILES}

    if not RAW_CLIPS_DIR.exists():
        return clips_by_game

    for key, prof in PROFILES.items():
        if filter_game != "all" and key != filter_game:
            continue
        folder_names = {prof.get("dir_name", key)}
        folder_names.update(prof.get("folder_aliases", []))

        for fname in folder_names:
            subfolder = RAW_CLIPS_DIR / fname
            if subfolder.exists() and subfolder.is_dir():
                for f in subfolder.iterdir():
                    if f.is_file() and f.suffix.lower() in exts:
                        if f not in clips_by_game[key]:
                            clips_by_game[key].append(f)

    for f in RAW_CLIPS_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in exts:
            game_key = identify_game(f)
            if game_key and (filter_game == "all" or game_key == filter_game):
                if f not in clips_by_game[game_key]:
                    clips_by_game[game_key].append(f)

    return clips_by_game


def render_intro_segment(ffmpeg_exe: str, output_path: Path) -> bool:
    if not LOGO_PATH.exists():
        print(f"Warning: Logo not found at {LOGO_PATH}. Skipping intro card.", flush=True)
        return False

    zoom_diff = INTRO_START_ZOOM - 1.0
    vf = (
        f"color=c=black:s={TARGET_WIDTH}x{TARGET_HEIGHT}:d={INTRO_DURATION}:r={TARGET_FPS}[bg];"
        f"[0:v]scale=eval=frame:w='2*trunc(360*({INTRO_START_ZOOM}-({zoom_diff}*t/{INTRO_DURATION})))':h=-2[logo];"
        f"[bg][logo]overlay=(W-w)/2:(H-h)/2[centered];"
        f"[centered]fade=t=in:st=0:d=0.2[vout]"
    )

    audio_inputs = ["-f", "lavfi", "-t", str(INTRO_DURATION), "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000:d={INTRO_DURATION}"]
    
    cmd = [
        ffmpeg_exe, "-loop", "1", "-t", str(INTRO_DURATION), "-i", str(LOGO_PATH),
        *audio_inputs,
        "-filter_complex", vf,
        "-map", "[vout]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-y", str(output_path),
    ]
    result = run_quiet_process(cmd, capture_output=True, text=True)
    return result.returncode == 0


def render_logo_outro_segment(ffmpeg_exe: str, output_path: Path) -> bool:
    if not LOGO_PATH.exists():
        print(f"Warning: Logo not found at {LOGO_PATH}. Skipping logo outro card.", flush=True)
        return False

    vf = (
        f"color=c=black:s={TARGET_WIDTH}x{TARGET_HEIGHT}:d={LOGO_OUTRO_DURATION}:r={TARGET_FPS}[bg];"
        f"[0:v]scale=eval=frame:w='2*trunc(360*(1.1-0.25*t/{LOGO_OUTRO_DURATION}))':h=-2[logo];"
        f"[bg][logo]overlay=(W-w)/2:(H-h)/2[clean];"
        f"[clean]split[c1][c2];"
        f"[c2]scale=36:64,scale={TARGET_WIDTH}:{TARGET_HEIGHT}:flags=neighbor,rgbashift=rh=35:bv=-35,noise=alls=25:allf=t+u[glitched];"
        f"[c1][glitched]overlay=enable='between(t,1.05,1.15)+between(t,1.3,1.42)+gte(t,1.6)'[gvid];"
        f"[gvid]fade=t=out:st=1.6:d=0.4[vout]"
    )

    if GLITCH_SFX_PATH.exists():
        audio_inputs = ["-t", str(LOGO_OUTRO_DURATION), "-i", str(GLITCH_SFX_PATH)]
        audio_filter = (
            f"[1:a]volume={GLITCH_VOLUME},"
            f"afade=t=out:st=1.5:d=0.5,"
            f"apad,atrim=0:{LOGO_OUTRO_DURATION}[aout]"
        )
        audio_map = "[aout]"
    else:
        audio_inputs = ["-f", "lavfi", "-t", str(LOGO_OUTRO_DURATION), "-i", f"anoisesrc=d={LOGO_OUTRO_DURATION}:c=white:r=48000"]
        audio_filter = (
            f"[1:a]volume={GLITCH_VOLUME * 0.8},highpass=f=600,lowpass=f=4000,"
            f"volume=enable='between(t,1.05,1.15)+between(t,1.3,1.42)+gte(t,1.6)':volume=1,"
            f"volume=enable='not(between(t,1.05,1.15)+between(t,1.3,1.42)+gte(t,1.6))':volume=0,"
            f"afade=t=out:st=1.5:d=0.5,apad,atrim=0:{LOGO_OUTRO_DURATION}[aout]"
        )
        audio_map = "[aout]"

    cmd = [
        ffmpeg_exe, "-loop", "1", "-t", str(LOGO_OUTRO_DURATION), "-i", str(LOGO_PATH),
        *audio_inputs,
        "-filter_complex", f"{vf};{audio_filter}",
        "-map", "[vout]", "-map", audio_map,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-y", str(output_path),
    ]
    result = run_quiet_process(cmd, capture_output=True, text=True)
    return result.returncode == 0


def prepare_subs_segment(ffmpeg_exe: str, ffprobe_exe: str, output_path: Path) -> Tuple[bool, float]:
    if not SUBS_CLIP_PATH.exists():
        print(f"Notice: {SUBS_CLIP_PATH.name} not found. Skipping subs outro.", flush=True)
        return False, 0.0

    _, _, duration = get_video_info(ffprobe_exe, SUBS_CLIP_PATH)

    vf = (
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )

    cmd = [
        ffmpeg_exe, "-i", str(SUBS_CLIP_PATH),
        "-f", "lavfi", "-t", str(duration), "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration}",
        "-vf", vf, "-r", str(TARGET_FPS),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
        "-y", str(output_path),
    ]
    result = run_quiet_process(cmd, capture_output=True, text=True)
    return result.returncode == 0, duration


def compile_master_sequence(ffmpeg_exe: str, clips: List[Path], durations: List[float], output_path: Path) -> bool:
    inputs = []
    for clip in clips:
        inputs.extend(["-i", str(clip)])
    
    has_bgm = BGM_PATH.exists()
    if has_bgm:
        inputs.extend(["-ss", str(BGM_START_TIMESTAMP), "-i", str(BGM_PATH)])
    
    bgm_idx = len(clips)
    filter_parts = []

    for i in range(len(clips)):
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v_n{i}]")
        filter_parts.append(f"[{i}:a]asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0[a_n{i}]")
    
    running_offset = 0.0
    prev_v = "v_n0"
    prev_a = "a_n0"
    
    for i in range(1, len(clips)):
        running_offset += durations[i - 1] - CROSSFADE_SECONDS
        v_out, a_out = f"v_xf{i}", f"a_xf{i}"
        
        filter_parts.append(
            f"[{prev_v}][v_n{i}]xfade=transition=fade:"
            f"duration={CROSSFADE_SECONDS}:offset={running_offset:.3f}[{v_out}]"
        )
        filter_parts.append(f"[{prev_a}][a_n{i}]acrossfade=d={CROSSFADE_SECONDS}[{a_out}]")
        
        prev_v = v_out
        prev_a = a_out
        
    final_v = prev_v
    final_a = prev_a
    master_dur = running_offset + durations[-1]
    
    if has_bgm:
        fade_out_start = max(0.0, master_dur - BGM_FADE_DURATION)
        filter_parts.append(
            f"[{bgm_idx}:a]volume={BGM_VOLUME},"
            f"afade=t=in:st=0:d={BGM_FADE_DURATION},"
            f"afade=t=out:st={fade_out_start:.3f}:d={BGM_FADE_DURATION}[bgm_faded]"
        )
        filter_parts.append(
            f"[{final_a}][bgm_faded]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixed_a]"
        )
        final_a = "mixed_a"

    cmd = [
        ffmpeg_exe, *inputs,
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{final_v}]", "-map", f"[{final_a}]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-y", str(output_path),
    ]
    
    result = run_quiet_process(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Compile FAILED: {result.stderr[-800:]}", flush=True)
        return False
    return True


def prompt_user_timeout(prompt: str, auto_yes: bool = False, timeout: int = 30) -> bool:
    if auto_yes:
        print(f"\n{prompt}\n[Auto-Confirmed via flag] Compiling master Short anyway...", flush=True)
        return True

    print(f"\n{prompt}", flush=True)
    print(f"Compile master Short anyway? (y/n) [Auto-skip in {timeout}s]: ", end="", flush=True)

    if sys.platform == "win32":
        try:
            import msvcrt
            start_time = time.time()
            while time.time() - start_time < timeout:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch().lower()
                    print(ch, flush=True)
                    return ch == "y"
                time.sleep(0.05)
            print(f"\n[Timeout] {timeout}s elapsed without input. Proceeding with trimmed clips only.", flush=True)
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
        print(f"\n[Timeout] {timeout}s elapsed without input. Proceeding with trimmed clips only.", flush=True)
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
    result = run_quiet_process(cmd, capture_output=True, text=True)
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
    result = run_quiet_process(cmd, capture_output=True, text=True)
    return result.returncode == 0


def concat_pieces(ffmpeg_exe: str, piece_paths: List[Path], output_path: Path) -> bool:
    filelist_path = TEMP_DIR / f"concat_list_{output_path.stem}.txt"
    with open(filelist_path, "w") as f:
        for p in piece_paths:
            f.write(f"file '{p.resolve().as_posix()}'\n")

    cmd = [ffmpeg_exe, "-f", "concat", "-safe", "0", "-i", str(filelist_path), "-c", "copy", "-y", str(output_path)]
    result = run_quiet_process(cmd, capture_output=True, text=True)
    filelist_path.unlink(missing_ok=True)
    return result.returncode == 0


def process_clip(ffmpeg_exe: str, ffprobe_exe: str, reader, clip: Path, output_path: Path, profile: dict) -> bool:
    src_w, src_h, duration = get_video_info(ffprobe_exe, clip)
    print(f"\nScanning kill-feed: {clip.name} [{profile['name']} - {src_w}x{src_h}]...", flush=True)
    peaks, _ = detect_killfeed_peaks(reader, clip, profile)

    if not peaks:
        print("  [Notice] No kills detected via OCR - exporting full clip as fallback.", flush=True)
        action_blocks = [(0.0, duration)]
    else:
        action_blocks = build_action_blocks(peaks, duration, profile["lead_buffer"], profile["trail_buffer"])

    pieces = build_pieces(action_blocks)
    vf = get_filtergraph(profile, src_w, src_h)

    print(f"  {len(pieces)} piece(s) generated after gap analysis:", flush=True)
    for kind, s, e in pieces:
        tag = "SPED 2x" if kind == "sped" else "normal"
        print(f"    [{s:.2f}s - {e:.2f}s] {tag}", flush=True)

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


def parse_args():
    parser = argparse.ArgumentParser(description="FragForge Batch Compiler")
    parser.add_argument(
        "--game",
        type=str,
        default="all",
        choices=["all", "valo", "cs2"],
        help="Select game to process (default: all)",
    )
    parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Auto-confirm over-budget timeout warnings",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    ffmpeg_exe = resolve_tool("ffmpeg")
    ffprobe_exe = resolve_tool("ffprobe")

    OUTPUT_DIR.mkdir(exist_ok=True)
    TRIMMED_DIR.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)

    clips_by_game = discover_clips_by_game(filter_game=args.game)
    total_found = sum(len(c) for c in clips_by_game.values())

    if total_found == 0:
        print(f"No video files found in configured game directories under {RAW_CLIPS_DIR}.", flush=True)
        return

    print(f"Found {total_found} clip(s) to process:", flush=True)
    for game_key, clips in clips_by_game.items():
        if clips:
            print(f"  [{game_key.upper()}]: {len(clips)} clip(s)", flush=True)
            clips.sort(key=natural_sort_key)

    reader = get_ocr_reader()

    subs_dur_probe = 0.0
    if SUBS_CLIP_PATH.exists():
        try:
            subs_dur_probe = get_video_info(ffprobe_exe, SUBS_CLIP_PATH)[2]
        except Exception:
            subs_dur_probe = 0.0

    content_budget_seconds = 60.0 - INTRO_DURATION - LOGO_OUTRO_DURATION - subs_dur_probe

    for game_key, clips in clips_by_game.items():
        if not clips:
            continue

        profile = get_profile(game_key)
        game_dir_name = profile.get("dir_name", game_key)

        print(f"\n=======================================================", flush=True)
        print(f"  PROCESSING BATCH: {profile['name']} ({len(clips)} clip(s))", flush=True)
        print(f"=======================================================", flush=True)

        stage_outputs = []
        successful_clips = []

        for clip in clips:
            out_path = get_timestamped_path(TRIMMED_DIR, base_name=f"{game_dir_name}_trim")
            if process_clip(ffmpeg_exe, ffprobe_exe, reader, clip, out_path, profile):
                stage_outputs.append(out_path)
                successful_clips.append(clip)

        if not stage_outputs:
            print(f"No clips were successfully processed for {profile['name']}. Moving to next game.", flush=True)
            continue

        durations = [get_video_info(ffprobe_exe, p)[2] for p in stage_outputs]
        total_duration = sum(durations)
        print(f"\n[{profile['name']}] Total clips duration: {total_duration:.1f}s (Budget: {content_budget_seconds:.0f}s)", flush=True)

        should_compile = True
        if total_duration > content_budget_seconds:
            warn_msg = (
                f"WARNING: [{profile['name']}] Combined clip duration ({total_duration:.1f}s) "
                f"exceeds your {content_budget_seconds:.0f}s allowance (leaving room for intro/outros)!"
            )
            should_compile = prompt_user_timeout(warn_msg, auto_yes=args.yes, timeout=30)

        if should_compile:
            print(f"\nRendering branding cards & out-cards...", flush=True)
            intro_path = TEMP_DIR / f"{game_dir_name}_intro.mp4"
            logo_outro_path = TEMP_DIR / f"{game_dir_name}_logo_outro.mp4"
            subs_outro_path = TEMP_DIR / f"{game_dir_name}_subs_outro.mp4"

            has_intro = render_intro_segment(ffmpeg_exe, intro_path)
            has_logo_outro = render_logo_outro_segment(ffmpeg_exe, logo_outro_path)
            has_subs_outro, subs_duration = prepare_subs_segment(ffmpeg_exe, ffprobe_exe, subs_outro_path)

            full_sequence = []
            full_durations = []

            if has_intro:
                full_sequence.append(intro_path)
                full_durations.append(INTRO_DURATION)

            full_sequence.extend(stage_outputs)
            full_durations.extend(durations)

            if has_logo_outro:
                full_sequence.append(logo_outro_path)
                full_durations.append(LOGO_OUTRO_DURATION)

            if has_subs_outro:
                full_sequence.append(subs_outro_path)
                full_durations.append(subs_duration)

            final_output = get_timestamped_path(OUTPUT_DIR, base_name=f"{game_dir_name}_short")
            
            print(f"Stitching {len(full_sequence)} segments and syncing background music ({BGM_PATH.name})...", flush=True)
            if compile_master_sequence(ffmpeg_exe, full_sequence, full_durations, final_output):
                print(f"Done [{profile['name']} Short]: {final_output.resolve()}", flush=True)
            else:
                print(f"Failed compiling master sequence for {profile['name']}.", flush=True)

            if has_intro:
                intro_path.unlink(missing_ok=True)
            if has_logo_outro:
                logo_outro_path.unlink(missing_ok=True)
            if has_subs_outro:
                subs_outro_path.unlink(missing_ok=True)
        else:
            print(f"[{profile['name']}] Skipping master compiled short. Preserving individual trimmed clips in {TRIMMED_DIR}.", flush=True)

        game_archive_dir = PROCESSED_DIR / game_dir_name
        game_archive_dir.mkdir(parents=True, exist_ok=True)
        for clip in successful_clips:
            dest = game_archive_dir / clip.name
            shutil.move(str(clip), str(dest))

        print(f"Archived {len(successful_clips)} {profile['name']} clip(s) to {game_archive_dir}", flush=True)

    print("\nAll batches completed.", flush=True)


if __name__ == "__main__":
    main()