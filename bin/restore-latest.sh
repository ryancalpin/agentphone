#!/usr/bin/env bash
set -euo pipefail

SNAP="${1:-}"
HOME_DIR="${AGENTPHONE_HOME:-$HOME/agentphone}"
if [ -z "$SNAP" ]; then
  SNAP=$(ls -1t "$HOME_DIR"/snapshots/agentphone-avd-* 2>/dev/null | head -n 1 || true)
fi
[ -n "$SNAP" ] || { echo "No snapshot found" >&2; exit 1; }
[ -f "$SNAP" ] || { echo "Snapshot not found: $SNAP" >&2; exit 1; }

printf 'Stopping AgentPhone services...\n'
systemctl --user stop agentphone-backend.service || true
systemctl --user stop agentphone-emulator.service || true
"$HOME_DIR/android-sdk/platform-tools/adb" emu kill >/dev/null 2>&1 || true
sleep 5

printf 'Backing up current AVD before restore...\n'
if [ -d "$HOME_DIR/avd" ]; then
  mv "$HOME_DIR/avd" "$HOME_DIR/avd.pre-restore.$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$HOME_DIR/avd"

printf 'Restoring %s...\n' "$SNAP"
case "$SNAP" in
  *.tar.zst) tar --zstd -xf "$SNAP" -C "$HOME_DIR" ;;
  *.tar.gz) tar -xzf "$SNAP" -C "$HOME_DIR" ;;
  *) echo "Unknown snapshot format" >&2; exit 1 ;;
esac

systemctl --user start agentphone-emulator.service
systemctl --user start agentphone-backend.service
printf 'Restore complete.\n'
