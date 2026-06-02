# AgentPhone

A persistent Android emulator you control from any device — including iPhone.

Runs headless on Linux, streams via MJPEG through Tailscale, feels like a remote digital phone.

## Architecture

```
┌─────────────────┐    gRPC RGBA capture     ┌──────────────┐    MJPEG     ┌──────┐
│  Emulator       │ ◄──────────────────────► │  FastAPI      │ ◄──────────► │ PWA  │
│  (NVIDIA GPU)   │    35ms per frame        │  Backend      │  18fps HJPG │      │
│  540×1200 MJPG  │                          │  :3008        │             │      │
└─────────────────┘                          └──────────────┘             └──────┘
                                                     │
                                              Tailscale HTTPS
                                                     │
                                              iPhone / iPad / desktop
```

**Performance (balanced):** 18fps at ~55ms per frame, 28KB JPEG frames

## Quick Start

### Requirements
- Linux with NVIDIA GPU + KVM
- Python 3.12+ with `uv`
- [Android SDK command-line tools](https://developer.android.com/studio#command-line-tools)
- Tailscale

### Install

```bash
git clone https://github.com/ryancalpin/agentphone.git
cd agentphone

# Generate protobuf stubs from emulator
cd backend
uv sync
uv run python -m grpc_tools.protoc \
  -I ~/agentphone/android-sdk/emulator/lib \
  -I .venv/lib/python3.*/site-packages/grpc_tools/_proto \
  --python_out=. --grpc_python_out=. \
  ~/agentphone/android-sdk/emulator/lib/emulator_controller.proto \
  ~/agentphone/android-sdk/emulator/lib/rtc_service_v2.proto \
  ~/agentphone/android-sdk/emulator/lib/ice_config.proto

# Create the emulator
~/android-sdk/cmdline-tools/latest/bin/avdmanager create avd \
  -n AgentPhone -k "system-images;android-35;google_apis_playstore;x86_64"

# Install systemd services
cp ../systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agentphone-emulator agentphone-backend
```

### Access
`https://<your-tailscale-hostname>/android` — add to iPhone Home Screen for native feel.

## Streaming

The backend serves MJPEG at `/api/stream.mjpeg` using emulator gRPC RGBA capture (~35ms) → resize 540p → JPEG. No H.264 pipeline delay, no double-encoding.

For WebRTC (if preferred): add `?webrtc=1` to the URL.

## Project Structure

```
agentphone/
├── backend/              FastAPI backend
│   ├── app.py            API routes + WebRTC + MJPEG
│   ├── adbctl.py         ADB control wrapper
│   ├── approvals.py      Approval workflow for sensitive actions
│   ├── mjpeg_fast.py     Low-latency MJPEG stream engine
│   ├── scrcpy_native.py  scrcpy-server H.264 fallback
│   └── pyproject.toml
├── pwa/                  Progressive Web App
│   ├── index.html
│   ├── app.js            PWA logic with MJPEG/video/touch
│   ├── styles.css        Dark theme, iPhone-optimized
│   ├── sw.js             Service worker (network-first)
│   └── manifest.webmanifest
├── bin/                  Utility scripts
├── systemd/              Systemd service files
└── README.md
```

## License

MIT — see [LICENSE](LICENSE)
