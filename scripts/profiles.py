"""
Game Profiles & Media Configuration
-----------------------------------
Loads configuration from config.json at project root. Provides path definitions,
dynamic player name regex compilation, and HUD coordinates.
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"

# =====================================================================
# Central Directory Paths
# =====================================================================
RAW_CLIPS_DIR = PROJECT_ROOT / "raw_clips"
OUTPUT_DIR = PROJECT_ROOT / "output"
TRIMMED_DIR = OUTPUT_DIR / "trimmed"
PROCESSED_DIR = RAW_CLIPS_DIR / "processed"
TEMP_DIR = PROJECT_ROOT / "temp"


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found at {CONFIG_PATH}. "
            f"Ensure config.json exists in the project root."
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_CONFIG = load_config()
_BRANDING = _CONFIG.get("branding", {})

# =====================================================================
# Branding & Audio Configuration
# =====================================================================
LOGO_PATH = PROJECT_ROOT / _BRANDING.get("logo_path", "assets/branding/avlLogo_cropped.png")
BGM_PATH = PROJECT_ROOT / _BRANDING.get("bgm_path", "assets/branding/CM_03 Cruise.mp3")
GLITCH_SFX_PATH = PROJECT_ROOT / _BRANDING.get("glitch_sfx_path", "assets/branding/glitched_sound.mp3")
SUBS_CLIP_PATH = PROJECT_ROOT / _BRANDING.get("subs_clip_path", "assets/branding/like_share_subs.mp4")

INTRO_DURATION = float(_BRANDING.get("intro_duration", 1.5))
LOGO_OUTRO_DURATION = float(_BRANDING.get("logo_outro_duration", 2.0))
INTRO_START_ZOOM = float(_BRANDING.get("intro_start_zoom", 2.0))
GLITCH_VOLUME = float(_BRANDING.get("glitch_volume", 0.14))

BGM_START_TIMESTAMP = float(_BRANDING.get("bgm_start_timestamp", 12.0))
BGM_VOLUME = float(_BRANDING.get("bgm_volume", 0.075))
BGM_FADE_DURATION = float(_BRANDING.get("bgm_fade_duration", 1.5))
CROSSFADE_SECONDS = float(_BRANDING.get("crossfade_seconds", 0.5))


# =====================================================================
# Dynamic Regex Generator
# =====================================================================
def build_name_regex(aliases: list[str]) -> re.Pattern:
    """
    Builds an OCR-tolerant regex pattern across all player aliases.
    Tolerates common OCR misreads (l -> 1 or |).
    """
    patterns = []
    for alias in aliases:
        escaped = re.escape(alias)
        fuzzy = re.sub(r"[l1|]", "[l1|]", escaped, flags=re.IGNORECASE)
        patterns.append(fuzzy)
    return re.compile("|".join(patterns), re.IGNORECASE)


# =====================================================================
# Game Profiles Compilation
# =====================================================================
PROFILES: Dict[str, dict] = {}

for key, pdata in _CONFIG.get("games", {}).items():
    player_aliases = pdata.get("player_aliases", ["avalanche"])
    PROFILES[key] = {
        "name": pdata.get("name", key.upper()),
        "dir_name": pdata.get("dir_name", key),
        "folder_aliases": pdata.get("folder_aliases", [key]),
        "player_aliases": player_aliases,
        "name_regex": build_name_regex(player_aliases),
        "latency_offset": float(pdata.get("latency_offset", 1.5)),
        "lead_buffer": float(pdata.get("lead_buffer", 5.0)),
        "trail_buffer": float(pdata.get("trail_buffer", 2.0)),
        "killfeed_crop": tuple(pdata.get("killfeed_crop")),
        "health_crop": tuple(pdata.get("health_crop")),
        "ammo_crop": tuple(pdata.get("ammo_crop")),
        "kf_overlay_w": int(pdata.get("kf_overlay_w", 480)),
        "hp_overlay_w": int(pdata.get("hp_overlay_w", 220)),
        "ammo_overlay_w": int(pdata.get("ammo_overlay_w", 220)),
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