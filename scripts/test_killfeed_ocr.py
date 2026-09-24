"""
Test: Kill-Feed OCR Detection (name-filtered, top-2-slot crop)
-------------------------------------------------------------------
Crops just the TOP TWO kill-feed slots (narrower than the full feed, and
positioned to avoid the FPS/performance overlay). Watches for your player
name ("Avalanche") appearing in EITHER slot.

Why either slot, not just the top one: if the feed was empty, a new kill
appears directly in slot 1 - that instant is the real event. If something
was already there, your kill enters at slot 2 first - that instant is
ALSO the real event, just entering lower rather than at the very top. So
"first appearance in either slot" always corresponds to the actual kill/
death moment - no timing offset needed.

A peak is logged on the transition from "name not visible" to "name
visible" - not on every frame it remains on screen while scrolling.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\test_killfeed_ocr.py "raw_clips\\your_clip.mp4"
"""

import sys
from pathlib import Path

import cv2

# Kill-feed crop region - adjust Y2 to cover only the top ~2 slots.
# Narrow this away from any FPS/performance overlay if they're close together.
CROP_X1, CROP_Y1 = 1350, 130
CROP_X2, CROP_Y2 = 1910, 210  # narrowed from 250 -> roughly top 2 lines only

PLAYER_NAME = "avalanche"  # lowercase, matched case-insensitively

SAMPLE_INTERVAL_SECONDS = 0.5
MIN_EVENT_GAP_SECONDS = 1.0


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts\\test_killfeed_ocr.py <path_to_clip>")
        sys.exit(1)

    clip_path = Path(sys.argv[1])
    if not clip_path.exists():
        print(f"File not found: {clip_path}")
        sys.exit(1)

    import easyocr
    print("Loading OCR model...")
    try:
        reader = easyocr.Reader(["en"], gpu=True)
    except Exception:
        print("GPU init failed, falling back to CPU (slower).")
        reader = easyocr.Reader(["en"], gpu=False)

    cap = cv2.VideoCapture(str(clip_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps
    step = max(1, int(fps * SAMPLE_INTERVAL_SECONDS))

    print(f"Clip duration: {duration:.1f}s, sampling every {SAMPLE_INTERVAL_SECONDS}s\n")

    name_visible_last_frame = False
    events = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            t = frame_idx / fps
            region = frame[CROP_Y1:CROP_Y2, CROP_X1:CROP_X2]
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)

            results = reader.readtext(gray, detail=0)
            full_text = " ".join(results).lower()
            name_visible_now = PLAYER_NAME in full_text

            if name_visible_now and not name_visible_last_frame:
                if not events or (t - events[-1]) >= MIN_EVENT_GAP_SECONDS:
                    events.append(t)
                    print(f"  Peak at {t:.1f}s (detected text: '{' '.join(results)}')")

            name_visible_last_frame = name_visible_now

        frame_idx += 1

    cap.release()

    print(f"\nTotal peaks detected: {len(events)}")


if __name__ == "__main__":
    main()