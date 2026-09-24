"""
Stage 2: Kill-Feed OCR Detection (shared module)
-----------------------------------------------------
Watches the top-2 kill-feed slots for your player name and returns
calibrated peak timestamps - the actual kill/death moments, latency-
corrected for the kill-feed's render delay.
"""

import re
import cv2

# Set to exact kill-feed coordinates (1350, 90) -> (1910, 210)
KILLFEED_CROP_X1, KILLFEED_CROP_Y1 = 1350, 90
KILLFEED_CROP_X2, KILLFEED_CROP_Y2 = 1910, 210

PLAYER_NAME = "avalanche"
# Matches slight OCR character confusions like 'l' read as '1' or '|'
NAME_REGEX = re.compile(r"ava[l1|]anche", re.IGNORECASE)

OCR_SAMPLE_INTERVAL_SECONDS = 0.5
MIN_EVENT_GAP_SECONDS = 1.0
KILLFEED_LATENCY_OFFSET = 1.5


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


def detect_killfeed_peaks(reader, video_path):
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0.0
    step = max(1, int(fps * OCR_SAMPLE_INTERVAL_SECONDS))

    last_count = 0
    peaks = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            t = frame_idx / fps
            region = frame[KILLFEED_CROP_Y1:KILLFEED_CROP_Y2, KILLFEED_CROP_X1:KILLFEED_CROP_X2]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)

            results = reader.readtext(gray, detail=0)
            full_text = " ".join(results).lower()
            current_count = len(NAME_REGEX.findall(full_text))

            if current_count > last_count:
                new_hits = current_count - last_count
                calibrated_t = max(0.0, t - KILLFEED_LATENCY_OFFSET)
                for _ in range(new_hits):
                    if not peaks or (calibrated_t - peaks[-1]) >= MIN_EVENT_GAP_SECONDS:
                        peaks.append(calibrated_t)
                        print(f"    Kill-feed peak at {calibrated_t:.1f}s (raw detection {t:.1f}s: '{' '.join(results)}')")

            last_count = current_count

        frame_idx += 1

    cap.release()
    return peaks, duration