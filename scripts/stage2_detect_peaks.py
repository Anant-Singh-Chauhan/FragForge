"""
Stage 2: Kill-Feed OCR Detection (shared module)
-----------------------------------------------------
Watches the top-2 kill-feed slots for your player name and returns
calibrated peak timestamps - the actual kill/death moments, latency-
corrected for the kill-feed's render delay.

Imported by batch_compile.py and stage3_trim_and_export.py rather than run
directly, so the detection logic lives in one place.
"""

import cv2

KILLFEED_CROP_X1, KILLFEED_CROP_Y1 = 1350, 120
KILLFEED_CROP_X2, KILLFEED_CROP_Y2 = 1910, 210  # top ~2 slots
PLAYER_NAME = "avalanche"  # matched case-insensitively

OCR_SAMPLE_INTERVAL_SECONDS = 0.5
MIN_EVENT_GAP_SECONDS = 1.0

# Kill-feed text doesn't render instantly at the moment of the kill - there's
# a short UI delay before it appears. This shifts detected timestamps back
# to better match the actual crosshair-engagement moment, so exported clips
# don't start mid-firefight.
KILLFEED_LATENCY_OFFSET = 1.5


def get_ocr_reader():
    """
    Load the EasyOCR model once. Reuse the returned reader across every clip
    in a batch - reloading model weights per clip wastes significant time.
    """
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
    """
    Scan the clip's kill-feed crop region for PLAYER_NAME. Tracks how many
    times the name currently appears in the crop (not just whether it's
    visible at all), so back-to-back kills that stack in the feed at the
    same time are each counted rather than collapsed into one event.

    Returns (peaks, duration). Peaks are latency-corrected timestamps.
    """
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
            current_count = full_text.count(PLAYER_NAME)

            if current_count > last_count:
                new_hits = current_count - last_count
                calibrated_t = max(0.0, t - KILLFEED_LATENCY_OFFSET)
                for _ in range(new_hits):
                    if not peaks or (calibrated_t - peaks[-1]) >= MIN_EVENT_GAP_SECONDS:
                        peaks.append(calibrated_t)
                        print(f"    Kill-feed peak at {calibrated_t:.1f}s (raw detection {t:.1f}s)")

            last_count = current_count

        frame_idx += 1

    cap.release()
    return peaks, duration