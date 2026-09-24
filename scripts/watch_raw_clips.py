"""
Watcher: Auto-trigger Stage 3 when a new clip is dropped in raw_clips/
------------------------------------------------------------------------
Runs continuously in the background. When a new video file appears in
raw_clips/, waits until the file has finished copying (size stops changing),
then runs the full stage3_trim_and_export.py pipeline on it.

Optionally notifies an n8n webhook when a Short is ready, so n8n can handle
whatever happens next (Discord ping, logging, etc.) - keeping n8n focused on
integrations rather than local file/OS automation.

Usage:
    (venv) PS D:\\Personal\\LocalYt> python scripts\\watch_raw_clips.py
    (leave this running in its own terminal window; Ctrl+C to stop)
"""

import subprocess
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

RAW_CLIPS_DIR = Path("raw_clips")
STAGE3_SCRIPT = Path("scripts") / "stage3_trim_and_export.py"

# How long a file's size must stay unchanged before we consider it
# "done copying" and safe to process.
SETTLE_CHECK_INTERVAL = 1.0  # seconds between size checks
SETTLE_CHECKS_REQUIRED = 3    # consecutive stable checks needed

# Set this to your n8n webhook URL once you've created one (Settings below).
# Leave as None to skip notifications entirely.
N8N_WEBHOOK_URL = None  # e.g. "http://localhost:5678/webhook/short-ready"


def wait_for_file_to_settle(path: Path):
    """Block until the file's size stops changing - i.e. copying is finished."""
    stable_count = 0
    last_size = -1

    while stable_count < SETTLE_CHECKS_REQUIRED:
        time.sleep(SETTLE_CHECK_INTERVAL)
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False  # file disappeared/was renamed mid-copy

        if size == last_size:
            stable_count += 1
        else:
            stable_count = 0
        last_size = size

    return True


def notify_n8n(clip_name: str):
    if not N8N_WEBHOOK_URL:
        return
    try:
        import requests
        requests.post(N8N_WEBHOOK_URL, json={"clip": clip_name}, timeout=5)
    except Exception as e:
        print(f"  (n8n notification failed, continuing anyway: {e})")


class NewClipHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        path = Path(event.src_path)
        if path.suffix.lower() not in {".mp4", ".mkv", ".mov"}:
            return

        print(f"\nNew clip detected: {path.name}")
        print("  Waiting for file to finish copying...")

        if not wait_for_file_to_settle(path):
            print("  File disappeared before settling - skipping.")
            return

        print("  File ready. Running Stage 3 pipeline...")
        result = subprocess.run(
            [sys.executable, str(STAGE3_SCRIPT)],
            capture_output=True, text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr[-500:])
        else:
            notify_n8n(path.name)


def main():
    if not RAW_CLIPS_DIR.exists():
        print(f"Input folder not found: {RAW_CLIPS_DIR}.")
        sys.exit(1)

    print(f"Watching {RAW_CLIPS_DIR.resolve()} for new clips... (Ctrl+C to stop)")

    handler = NewClipHandler()
    observer = Observer()
    observer.schedule(handler, str(RAW_CLIPS_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()