"""
Game Profiles Configuration
----------------------------
All crop coordinates are stored as normalized fractions (0.0 to 1.0)
relative to video width and height, enabling 1080p, 1440p, and 4K support.
"""

import re

PROFILES = {
    "valorant": {
        "name": "Valorant",
        "player_name": "avalanche",
        "name_regex": re.compile(r"ava[l1|]anche", re.IGNORECASE),
        "latency_offset": 1.5,
        "lead_buffer": 5.0,
        "trail_buffer": 2.0,
        # Normalized Crop Coordinates: (x1, y1, x2, y2)
        "killfeed_crop": (1350 / 1920, 90 / 1080, 1910 / 1920, 210 / 1080),
        "health_crop":   (525 / 1920, 1000 / 1080, 655 / 1920, 1050 / 1080),
        "ammo_crop":     (1267 / 1920, 1000 / 1080, 1397 / 1920, 1050 / 1080),
        # Final canvas overlay sizes
        "kf_overlay_w": 480,
        "hp_overlay_w": 220,
        "ammo_overlay_w": 220,
    },
    "cs2": {
        "name": "Counter-Strike 2",
        "player_name": "avalanche",
        "name_regex": re.compile(r"ava[l1|]anche", re.IGNORECASE),
        "latency_offset": 1.0,  # CS2 killfeed renders faster than Valorant
        "lead_buffer": 5.0,
        "trail_buffer": 2.5,
        # Normalized Crop Coordinates based on CS2 HUD layout
        "killfeed_crop": (0.810, 0.050, 0.995, 0.160),
        "health_crop":   (0.315, 0.920, 0.395, 0.985),
        "ammo_crop":     (0.615, 0.920, 0.695, 0.985),
        # Final canvas overlay sizes
        "kf_overlay_w": 480,
        "hp_overlay_w": 220,
        "ammo_overlay_w": 220,
    },
}


def get_profile(game_key: str) -> dict:
    key = game_key.lower().strip()
    if key in PROFILES:
        return PROFILES[key]
    raise ValueError(f"Unknown game profile '{game_key}'. Available: {list(PROFILES.keys())}")