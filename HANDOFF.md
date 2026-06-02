# AgentPhone Handoff

AgentPhone is live.

## User URL

Open on iPhone Safari:

https://ryancalpin.gerbil-tritone.ts.net/android

Then use Share -> Add to Home Screen.

## What it does

- Runs a persistent Android Emulator named `AgentPhone`.
- Streams the Android screen to an iPhone-friendly PWA.
- Uses a continuous `/api/stream.mjpeg` screen stream by default, with `?poll=1` as a fallback.
- Supports tap, swipe, Back, Home, App Switch, screenshot refresh, and text entry.
- Provides an approval center with screenshot-backed approve/deny/edit flow.
- Exposes a helper script Hermes can call to pause for Ryan approval.

## Services

```bash
systemctl --user status agentphone-emulator.service
systemctl --user status agentphone-backend.service
```

Both should be active.

## Local backend

```text
http://127.0.0.1:3008
```

Important endpoints:

```text
GET  /api/health
GET  /api/status
GET  /api/screenshot.png
GET  /api/stream.mjpeg
POST /api/tap
POST /api/swipe
POST /api/type
POST /api/key
GET  /api/approvals
POST /api/approvals
POST /api/approvals/{id}/approve
POST /api/approvals/{id}/deny
POST /api/approvals/{id}/edit
```

## Files

```text
/home/ryancalpin/agentphone/
/home/ryancalpin/agentphone/backend/
/home/ryancalpin/agentphone/pwa/
/home/ryancalpin/agentphone/avd/
/home/ryancalpin/agentphone/snapshots/
/home/ryancalpin/agentphone/bin/healthcheck.sh
/home/ryancalpin/agentphone/bin/snapshot.sh
/home/ryancalpin/agentphone/bin/restore-latest.sh
/home/ryancalpin/agentphone/backend/wait_for_approval.py
```

## Healthcheck

Run:

```bash
/home/ryancalpin/agentphone/bin/healthcheck.sh
```

Expected output:

```text
✅ Backend health
✅ ADB connected
✅ Android booted
✅ Screenshot endpoint
✅ Tailscale /android
✅ Tailscale root still works
AgentPhone healthcheck passed.
```

## Snapshot

A clean baseline snapshot exists:

```text
/home/ryancalpin/agentphone/snapshots/agentphone-avd-20260601-175145.tar.zst
```

Create a new snapshot after Ryan logs into important apps:

```bash
/home/ryancalpin/agentphone/bin/snapshot.sh
```

Restore latest snapshot:

```bash
/home/ryancalpin/agentphone/bin/restore-latest.sh
```

## Approval helper

Example:

```bash
cd /home/ryancalpin/agentphone/backend
./wait_for_approval.py \
  --app Amazon \
  --risk high \
  --action "Approve checkout" \
  --message "Review the cart and approve if it looks right."
```

This prints an approval URL, waits, then exits:

- exit 0 = approved
- exit 2 = denied
- exit 3 = timed out

## Verified end-to-end

Verified on 2026-06-01:

- Port 3008 registered as `agentphone`.
- Android emulator boots headless.
- ADB connected and reports Android booted.
- Screenshot endpoint returns 1080x2400 PNG.
- PWA loads locally and over Tailscale `/android`.
- PWA uses a larger edge-to-edge phone layout with overlay controls.
- Continuous stream endpoint was verified with multiple PNG frames over one connection.
- Tailscale root `/` still works.
- Approval creation, screenshot, approve/deny API work.
- `wait_for_approval.py` unblocks after approval and exits 0.
- No pending/editing approvals remain after test cleanup.
