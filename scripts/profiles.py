"""
Game Profiles & Media Configuration
-----------------------------------
Loads configuration from config.json at project root. Provides path definitions,
dynamic player name regex compilation, HUD coordinates, and missing-config guards.
"""

import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "config.example.json"

# =====================================================================
# Central Directory Paths
# =====================================================================
RAW_CLIPS_DIR = PROJECT_ROOT / "raw_clips"
OUTPUT_DIR = PROJECT_ROOT / "output"
TRIMMED_DIR = OUTPUT_DIR / "trimmed"
PROCESSED_DIR = RAW_CLIPS_DIR / "processed"
TEMP_DIR = PROJECT_ROOT / "temp"


def load_config() -> Dict[str, Any]:
    """
    Safely reads config.json. If missing or corrupted, directs the user
    to run setup.bat and consult faq.md rather than crashing abruptly.
    """
    if not CONFIG_PATH.exists():
        print("\n" + "=" * 65, file=sys.stderr)
        print(" [FragForge Configuration Error]", file=sys.stderr)
        print(" Missing required configuration file: config.json", file=sys.stderr)
        print("-" * 65, file=sys.stderr)
        print(" Resolution steps:", file=sys.stderr)
        print("  1. Run 'setup.bat' in the project root to generate config.json", file=sys.stderr)
        print("     automatically from config.example.json.", file=sys.stderr)
        print("  2. Or manually copy config.example.json to config.json:", file=sys.stderr)
        print("       copy config.example.json config.json", file=sys.stderr)
        print("  3. Consult 'faq.md' under 'Configuration Issues' for help.", file=sys.stderr)
        print("=" * 65 + "\n", file=sys.stderr)
        sys.exit(1)

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as err:
        print("\n" + "=" * 65, file=sys.stderr)
        print(" [FragForge Syntax Error in config.json]", file=sys.stderr)
        print(f" Failed to parse JSON on line {err.lineno}, column {err.colno}:", file=sys.stderr)
        print(f" Error: {err.msg}", file=sys.stderr)
        print("-" * 65, file=sys.stderr)
        print(" Fix the JSON formatting using the '⚙ Configuration' tab in", file=sys.stderr)
        print(" the desktop app, or consult 'faq.md' to reset to defaults.", file=sys.stderr)
        print("=" * 65 + "\n", file=sys.stderr)
        sys.exit(1)


_CONFIG = load_config()
_BRANDING = _CONFIG.get("branding", {})

# =====================================================================
# Branding & Audio Configuration
# =====================================================================
LOGO_PATH = PROJECT_ROOT / _BRANDING.get("logo_path", "assets/branding/logo.png")
BGM_PATH = PROJECT_ROOT / _BRANDING.get("bgm_path", "assets/branding/bgm.mp3")
GLITCH_SFX_PATH = PROJECT_ROOT / _BRANDING.get("glitch_sfx_path", "assets/branding/glitch.mp3")
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
    Tolerates common OCR letter substitutions (l -> 1 or |).
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
    player_aliases = pdata.get("player_aliases", ["player"])
    PROFILES[key] = {
        "name": pdata.get("name", key.upper()),
        "dir_name": pdata.get("dir_name", key),
        "folder_aliases": pdata.get("folder_aliases", [key]),
        "player_aliases": player_aliases,
        "name_regex": build_name_regex(player_aliases),
        "latency_offset": float(pdata.get("latency_offset", 1.5)),
        "lead_buffer": float(pdata.get("lead_buffer", 5.0)),
        "trail_buffer": float(pdata.get("trail_buffer", 2.0)),
        "killfeed_crop": tuple(pdata.get("killfeed_crop", [0.70, 0.08, 0.99, 0.20])),
        "health_crop": tuple(pdata.get("health_crop", [0.27, 0.92, 0.34, 0.97])),
        "ammo_crop": tuple(pdata.get("ammo_crop", [0.65, 0.92, 0.72, 0.97])),
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