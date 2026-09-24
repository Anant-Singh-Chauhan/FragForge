"""
Calibration: Check the Kill-Feed Crop Region
------------------------------------------------
Grabs one frame from a clip, crops it to our guessed kill-feed region, and
saves both the full frame (with the crop box drawn on it) and the cropped
region itself - so you can visually confirm the coordinates are right
before we run OCR across a whole clip.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\calibrate_killfeed.py "raw_clips\\your_clip.mp4"
"""

import sys
from pathlib import Path

import cv2

# Starting guess for Valorant's kill-feed region at 1920x1080 (top-right HUD
# area). Adjust these based on what the saved images show.
CROP_X1, CROP_Y1 = 1350, 90
CROP_X2, CROP_Y2 = 1910, 210

# Which second into the video to grab a sample frame from (pick a moment
# you know had a kill-feed entry visible, if possible)
SAMPLE_TIME_SECONDS = 20.0


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts\\calibrate_killfeed.py <path_to_clip>")
        sys.exit(1)

    clip_path = Path(sys.argv[1])
    if not clip_path.exists():
        print(f"File not found: {clip_path}")
        sys.exit(1)

    cap = cv2.VideoCapture(str(clip_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_number = int(SAMPLE_TIME_SECONDS * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("Could not read a frame - try a different SAMPLE_TIME_SECONDS.")
        sys.exit(1)

    h, w = frame.shape[:2]
    print(f"Frame size: {w}x{h}")

    # Draw the crop box on a copy of the full frame for visual reference
    annotated = frame.copy()
    cv2.rectangle(annotated, (CROP_X1, CROP_Y1), (CROP_X2, CROP_Y2), (0, 255, 0), 3)

    full_out = Path("temp") / "calibration_full_frame.png"
    crop_out = Path("temp") / "calibration_crop.png"
    Path("temp").mkdir(exist_ok=True)

    cv2.imwrite(str(full_out), annotated)
    cv2.imwrite(str(crop_out), frame[CROP_Y1:CROP_Y2, CROP_X1:CROP_X2])

    print(f"Saved: {full_out} (full frame with green crop box drawn on it)")
    print(f"Saved: {crop_out} (just the cropped region)")
    print("\nOpen both images. If the green box doesn't tightly frame the")
    print("kill-feed text, adjust CROP_X1/Y1/X2/Y2 in this script and re-run.")


if __name__ == "__main__":
    main()