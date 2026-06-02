#!/usr/bin/env bash
set -euo pipefail

HOME_DIR="/home/ryancalpin/agentphone"
SNAP_DIR="$HOME_DIR/snapshots"
AVD_DIR="$HOME_DIR/avd"
ADB="$HOME_DIR/android-sdk/platform-tools/adb"
STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$SNAP_DIR/agentphone-avd-$STAMP.tar.zst"

mkdir -p "$SNAP_DIR"

printf 'Stopping emulator for clean snapshot...\n'
systemctl --user stop agentphone-backend.service >/dev/null 2>&1 || true
systemctl --user stop agentphone-emulator.service >/dev/null 2>&1 || true
"$ADB" emu kill >/dev/null 2>&1 || true
sleep 10

printf 'Creating snapshot: %s\n' "$ARCHIVE"
if command -v zstd >/dev/null 2>&1; then
  tar --zstd -cf "$ARCHIVE" -C "$HOME_DIR" avd state/approvals.json state/approval_screenshots 2>/dev/null || tar --zstd -cf "$ARCHIVE" -C "$HOME_DIR" avd
else
  ARCHIVE="$SNAP_DIR/agentphone-avd-$STAMP.tar.gz"
  tar -czf "$ARCHIVE" -C "$HOME_DIR" avd state/approvals.json state/approval_screenshots 2>/dev/null || tar -czf "$ARCHIVE" -C "$HOME_DIR" avd
fi

printf 'Restarting emulator service...\n'
systemctl --user start agentphone-emulator.service || true
systemctl --user start agentphone-backend.service || true

printf 'Pruning old snapshots, keeping latest 7...\n'
ls -1t "$SNAP_DIR"/agentphone-avd-* 2>/dev/null | tail -n +8 | xargs -r rm -f

printf 'Snapshot complete: %s\n' "$ARCHIVE"
