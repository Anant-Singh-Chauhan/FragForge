# Base image with Python already set up
FROM python:3.12-slim

# Install ffmpeg (this environment controls its own version - no more
# Windows PATH headaches, since everything runs inside this container)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages first (separate layer = faster rebuilds when only
# script code changes, not dependencies)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy our pipeline scripts in
COPY scripts/ ./scripts/

# Default command: start the watcher, which watches /app/raw_clips (mounted
# from your host folder via docker-compose) and triggers Stage 3 on new files
CMD ["python", "scripts/watch_raw_clips.py"]