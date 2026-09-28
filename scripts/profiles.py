"""
Game Profiles & Media Configuration
-----------------------------------
Central configuration for all directory paths, game profiles, HUD coordinates,
and brand media assets (logo, intro, outro, music, glitch SFX).
"""

from pathlib import Path
import re
from typing import Optional

# =====================================================================
# Central Directory Paths
# =====================================================================
RAW_CLIPS_DIR = Path("raw_clips")
OUTPUT_DIR = Path("output")
TRIMMED_DIR = OUTPUT_DIR / "trimmed"
PROCESSED_DIR = RAW_CLIPS_DIR / "processed"
TEMP_DIR = Path("temp")

# =====================================================================
# Branding & Audio Assets
# =====================================================================
LOGO_PATH = Path("avlLogo_cropped.png")
BGM_PATH = Path("CM_03 Cruise.mp3")
GLITCH_SFX_PATH = Path("glitched_sound.mp3")

INTRO_DURATION = 1.5        # Reduced by 25% (was 2.0)
OUTRO_DURATION = 2.0
INTRO_START_ZOOM = 2.0      # Starts at 2.0x zoom and zooms out
GLITCH_VOLUME = 0.14        # Used for outro glitch sound

BGM_START_TIMESTAMP = 12.0  # Seek offset into the MP3 track
BGM_VOLUME = 0.075          # Background music volume underneath gameplay
BGM_FADE_DURATION = 1.5     # Fade in/out duration in seconds

# =====================================================================
# Game Profiles Configuration
# =====================================================================
PROFILES = {
    "valo": {
        "name": "VALO",
        "dir_name": "valo",
        "folder_aliases": ["valorant", "valo"],
        "player_name": "avalanche",
        "name_regex": re.compile(r"ava[l1|]anche", re.IGNORECASE),
        "latency_offset": 1.5,
        "lead_buffer": 5.0,
        "trail_buffer": 2.0,
        "killfeed_crop": (1350 / 1920, 90 / 1080, 1910 / 1920, 210 / 1080),
        "health_crop":   (525 / 1920, 1000 / 1080, 655 / 1920, 1050 / 1080),
        "ammo_crop":     (1267 / 1920, 1000 / 1080, 1397 / 1920, 1050 / 1080),
        "kf_overlay_w": 480,
        "hp_overlay_w": 220,
        "ammo_overlay_w": 220,
    },
    "cs2": {
        "name": "CS2",
        "dir_name": "cs2",
        "folder_aliases": ["cs2", "cs", "counter-strike", "counterstrike"],
        "player_name": "avalanche",
        "name_regex": re.compile(r"ava[l1|]anche", re.IGNORECASE),
        "latency_offset": 1.0,
        "lead_buffer": 5.0,
        "trail_buffer": 2.5,
        "killfeed_crop": (0.810, 0.050, 0.995, 0.160),
        "health_crop":   (0.315, 0.920, 0.395, 0.985),
        "ammo_crop":     (0.615, 0.920, 0.695, 0.985),
        "kf_overlay_w": 480,
        "hp_overlay_w": 220,
        "ammo_overlay_w": 220,
    },
}


def get_profile(game_key: str) -> dict:
    key = game_key.lower().strip()
    if key in PROFILES:
        return PROFILES[key]
    for k, prof in PROFILES.items():
        aliases = [prof.get("dir_name", k).lower()] + [a.lower() for a in prof.get("folder_aliases", [])]
        if key in aliases:
            return prof
    raise ValueError(f"Unknown game profile '{game_key}'. Available: {list(PROFILES.keys())}")


def identify_game(clip_path: Path) -> Optional[str]:
    parent_name = clip_path.parent.name.lower()
    stem = clip_path.stem.lower()

    for key, prof in PROFILES.items():
        aliases = {prof.get("dir_name", key).lower()}
        aliases.update(a.lower() for a in prof.get("folder_aliases", []))

        if parent_name in aliases:
            return key

        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", stem) or alias in stem:
                return key

    return None