"""
Stage 2: Game-Aware Kill-Feed OCR Detection
-------------------------------------------
Uses normalized crop coordinates from game profiles and converts them
to source pixel bounds on any resolution.
"""

from pathlib import Path
from typing import List, Tuple
import cv2

from profiles import get_profile

OCR_SAMPLE_INTERVAL_SECONDS = 0.5
MIN_EVENT_GAP_SECONDS = 1.0


def get_ocr_reader():
    import easyocr
    print("Loading OCR model...")
    try:
        reader = easyocr.Reader(["en"], gpu=True)
        print("  Using GPU.")
    except Exception:
        print("  GPU init failed, falling back to CPU (slower).")
        reader = easyocr.Reader(["en"], gpu=False)
    return reader


def detect_killfeed_peaks(reader, video_path: Path, profile: dict) -> Tuple[List[float], float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"Error opening {video_path}")
        return [], 0.0

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0.0
    step = max(1, int(fps * OCR_SAMPLE_INTERVAL_SECONDS))

    # Convert normalized profile coordinates to clip pixels
    kx1_n, ky1_n, kx2_n, ky2_n = profile["killfeed_crop"]
    kx1, ky1 = int(kx1_n * width), int(ky1_n * height)
    kx2, ky2 = int(kx2_n * width), int(ky2_n * height)

    name_regex = profile["name_regex"]
    latency = profile["latency_offset"]

    last_count = 0
    peaks = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            t = frame_idx / fps
            region = frame[ky1:ky2, kx1:kx2]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)

            results = reader.readtext(gray, detail=0)
            full_text = " ".join(results).lower()
            current_count = len(name_regex.findall(full_text))

            if current_count > last_count:
                new_hits = current_count - last_count
                calibrated_t = max(0.0, t - latency)
                for _ in range(new_hits):
                    if not peaks or (calibrated_t - peaks[-1]) >= MIN_EVENT_GAP_SECONDS:
                        peaks.append(calibrated_t)
                        print(f"    [{profile['name']}] Kill peak at {calibrated_t:.1f}s (raw {t:.1f}s: '{' '.join(results)}')")

            last_count = current_count

        frame_idx += 1

    cap.release()
    return peaks, duration