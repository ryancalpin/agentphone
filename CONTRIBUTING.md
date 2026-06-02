# Contributing

AgentPhone is open source and welcomes contributions.

## Setup

See [README.md](README.md) for installation instructions.

## Architecture Decisions

- **MJPEG over WebRTC**: JPEG frames via HTTP multipart have lower latency than H.264 WebRTC for remote phone control. Each frame is independent — no GOP, no B-frames, no decoder buffering.

- **gRPC RGBA capture over ADB**: The emulator's gRPC endpoint delivers raw RGBA frames in ~35ms vs ADB's ~440ms.

- **NVIDIA GPU required**: The emulator runs with `-gpu host` for hardware-accelerated rendering on the host GPU.

## Adding Features

1. Keep the capture pipeline in `mjpeg_fast.py` — it's the performance-critical path
2. New API routes go in `app.py`
3. PWA changes go in `pwa/` (HTML/CSS/JS)

## Performance Targets

- gRPC capture: <40ms per frame
- Total pipeline: <60ms per frame
- MJPEG output: >15fps at 540p

Run `uv run python -c "from mjpeg_fast import fast_jpeg_stream; ..."` to benchmark locally.
