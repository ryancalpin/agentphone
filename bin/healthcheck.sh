#!/bin/bash
# AgentPhone health check — verifies emulator, backend, and streaming.
# Set AGENTPHONE_HOME to override default ~/agentphone.

HOME_DIR="${AGENTPHONE_HOME:-$HOME/agentphone}"
TS="${TAILSCALE_HOST:-}"  # set to your Tailscale hostname
ADB="${ANDROID_HOME:-$HOME_DIR/android-sdk}/platform-tools/adb"
FAILS=0
fail() { echo "FAIL: $1"; FAILS=$((FAILS+1)); }

$ADB devices 2>/dev/null | grep -q 'device' || fail "Emulator not connected via ADB"
curl -sf http://127.0.0.1:3008/api/health >/dev/null || fail "Backend health check failed"
curl -sf http://127.0.0.1:3008/api/status >/dev/null || fail "Backend status failed"

if [ -n "$TS" ]; then
    curl -sf "$TS/android/api/health" >/dev/null || fail "Tailscale health check failed"
fi

if [ -f "$HOME_DIR/bin/webrtc-smoke.py" ]; then
    python3 "$HOME_DIR/bin/webrtc-smoke.py" "http://127.0.0.1:3008/api/webrtc/offer" >/dev/null || fail "WebRTC video failed"
fi

if [ $FAILS -eq 0 ]; then
    echo "✓ All checks passed"
    exit 0
else
    echo "$FAILS check(s) failed"
    exit 1
fi
