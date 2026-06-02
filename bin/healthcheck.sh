#!/usr/bin/env bash
set -euo pipefail

BASE="http://127.0.0.1:3008"
TS="https://ryancalpin.gerbil-tritone.ts.net"
ADB="/home/ryancalpin/agentphone/android-sdk/platform-tools/adb"
TMP="/tmp/agentphone-health-shot.png"

ok() { printf '✅ %s\n' "$*"; }
fail() { printf '❌ %s\n' "$*" >&2; exit 1; }

curl -fsS "$BASE/api/health" >/dev/null || fail "Backend health failed"
ok "Backend health"

"$ADB" devices | grep -q 'device$' || fail "ADB device missing"
ok "ADB connected"

boot=$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
[ "$boot" = "1" ] || fail "Android not booted"
ok "Android booted"

curl -fsS "$BASE/api/screenshot.png" -o "$TMP" || fail "Screenshot endpoint failed"
file "$TMP" | grep -q 'PNG image data' || fail "Screenshot is not PNG"
ok "Screenshot endpoint"

/home/ryancalpin/agentphone/bin/webrtc-smoke.py "$BASE/api/webrtc/offer" >/dev/null || fail "WebRTC video failed"
ok "WebRTC video"

code=$(curl -s -o /dev/null -w '%{http_code}' "$TS/android" || true)
[ "$code" = "200" ] || fail "Tailscale /android returned $code"
ok "Tailscale /android"

root=$(curl -s -o /dev/null -w '%{http_code}' "$TS/" || true)
[ "$root" = "200" ] || fail "Tailscale root returned $root"
ok "Tailscale root still works"

printf 'AgentPhone healthcheck passed.\n'
