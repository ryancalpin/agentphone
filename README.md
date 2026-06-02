# AgentPhone

Persistent Android emulator with a PWA dashboard for remote control from any device — including iPhone.

Turn any Linux host into a "digital Android phone" that stays logged into your apps, controllable from your real phone via Tailscale.

## What It Does

- Runs a persistent Android emulator headlessly on your Linux server
- Streams the screen to a PWA (Progressive Web App) via WebRTC with H.264
- Supports touch, swipe, keyboard input, and Android key events from any browser
- Automatically switches to a text-based overlay for secure screens (passwords, banking)
- Built-in approval workflow for sensitive actions (requires manual confirmation)

## Architecture

```
┌─────────────┐     WebRTC/H.264      ┌──────────────┐
│  Android    │ ◄──────────────────► │  FastAPI      │
│  Emulator   │     ADB control       │  Backend      │
│  (headless) │ ◄──────────────────► │  (port 3008)  │
└─────────────┘                       └──────┬───────┘
                                             │
                                      Tailscale HTTPS
                                             │
                                      ┌──────┴───────┐
                                      │  PWA on any  │
                                      │  device      │
                                      │  (iPhone,    │
                                      │   desktop)   │
                                      └──────────────┘
```

## Quick Start

### Prerequisites

- Linux host with KVM support
- [Android SDK command-line tools](https://developer.android.com/studio#command-line-tools)
- Python 3.12+ with `uv`
- Tailscale (for secure remote access)

### Install

```bash
cd ~/agentphone

# Install backend dependencies
cd backend
uv sync

# Create an Android Virtual Device
# (this is usually pre-configured; see HANDOFF.md for setup steps)

# Start services
systemctl --user enable --now agentphone-emulator
systemctl --user enable --now agentphone-backend
```

### Access

Open `https://<your-tailscale-hostname>/android` in any browser.

Add to your iPhone Home Screen for a native-app experience.

## Project Structure

```
agentphone/
├── backend/           FastAPI backend
│   ├── app.py         API routes + WebRTC
│   ├── adbctl.py      ADB control wrapper
│   ├── approvals.py   Approval workflow
│   ├── scrcpy_native.py  Native scrcpy H.264 stream
│   └── pyproject.toml
├── pwa/               Progressive Web App
│   ├── index.html
│   ├── app.js         Main PWA logic
│   ├── styles.css
│   ├── sw.js          Service worker for offline caching
│   └── manifest.webmanifest
├── bin/               Utility scripts
│   ├── healthcheck.sh
│   ├── snapshot.sh
│   └── restore-latest.sh
└── HANDOFF.md         Detailed setup & maintenance guide
```

## Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Emulator health, screen size, secure state |
| `/api/ui` | GET | XML UI tree for secure screen overlay |
| `/api/tap` | POST | Tap at screen coordinates |
| `/api/swipe` | POST | Swipe gesture |
| `/api/type` | POST | Send text input |
| `/api/key` | POST | Send Android key event (BACK, HOME, ENTER, etc.) |
| `/api/webrtc/offer` | POST | WebRTC signaling for video stream |
| `/api/approvals` | GET/POST | List or create approval requests |

## License

MIT — see [LICENSE](LICENSE)
