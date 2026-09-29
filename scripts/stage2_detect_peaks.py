"""
Stage 2: OCR Kill-Feed Peak Detection
-------------------------------------
Extracts killfeed crops frame-by-frame and scans for configured player names.
Dynamically falls back to CPU computation if an NVIDIA GPU / CUDA is not available.
"""

from pathlib import Path
import re
import sys
from typing import List, Tuple

import cv2
import easyocr
import numpy as np

# Force UTF-8 stdout/stderr on Windows to prevent charmap encoding errors
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def get_ocr_reader() -> easyocr.Reader:
    """
    Instantiates EasyOCR with dynamic CUDA/GPU detection.
    Falls back gracefully to CPU without throwing runtime errors.
    """
    use_cuda = False
    try:
        import torch
        if torch.cuda.is_available():
            use_cuda = True
            device_name = torch.cuda.get_device_name(0)
            print(f"[Hardware] GPU Acceleration Active: {device_name}", flush=True)
        else:
            print("[Hardware] No CUDA GPU detected. EasyOCR operating in CPU mode (slower).", flush=True)
    except ImportError:
        print("[Hardware] PyTorch CUDA bindings unavailable. Operating in CPU mode.", flush=True)

    return easyocr.Reader(["en"], gpu=use_cuda, verbose=False)


def preprocess_killfeed_region(frame: np.ndarray) -> np.ndarray:
    """
    Converts frame crop to grayscale, upscales 3x using cubic interpolation,
    and amplifies contrast to maximize OCR text edge clarity.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    upscaled = cv2.resize(gray, (0, 0), fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    boosted = cv2.convertScaleAbs(upscaled, alpha=1.5, beta=0)
    return boosted


def detect_killfeed_peaks(
    reader: easyocr.Reader,
    clip_path: Path,
    profile: dict,
    sample_interval_seconds: float = 0.5,
) -> Tuple[List[float], List[dict]]:
    """
    Scans a video clip at regular intervals for player kill events.
    Applies the profile's latency offset to align timestamps with actual eliminations.
    """
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        print(f"  [Error] Unable to open video file: {clip_path}", flush=True)
        return [], []

    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration = frame_count / fps

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    x1_norm, y1_norm, x2_norm, y2_norm = profile["killfeed_crop"]
    crop_x1 = int(x1_norm * width)
    crop_y1 = int(y1_norm * height)
    crop_x2 = int(x2_norm * width)
    crop_y2 = int(y2_norm * height)

    latency_offset = profile.get("latency_offset", 1.5)
    name_regex: re.Pattern = profile["name_regex"]

    peaks: List[float] = []
    events: List[dict] = []

    last_occurrence_count = 0
    step_frames = max(1, int(fps * sample_interval_seconds))
    current_frame = 0

    while current_frame < frame_count:
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame)
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        timestamp = current_frame / fps

        # Crop killfeed bounding box
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        processed = preprocess_killfeed_region(crop)

        # Run OCR
        results = reader.readtext(processed, detail=0, paragraph=True)
        combined_text = " ".join(results)

        # Count occurrences of player alias in the visible killfeed slots
        matches = name_regex.findall(combined_text)
        current_occurrences = len(matches)

        # Event occurs when a new killfeed entry mentioning the player appears
        if current_occurrences > last_occurrence_count:
            new_kills = current_occurrences - last_occurrence_count
            adjusted_timestamp = max(0.0, timestamp - latency_offset)

            for _ in range(new_kills):
                peaks.append(adjusted_timestamp)
                events.append({
                    "raw_time": timestamp,
                    "adjusted_time": adjusted_timestamp,
                    "text": combined_text,
                })
                print(f"  [+] Frag detected at {timestamp:.2f}s (offset aligned to {adjusted_timestamp:.2f}s)", flush=True)

        last_occurrence_count = current_occurrences
        current_frame += step_frames

    cap.release()
    return peaks, events