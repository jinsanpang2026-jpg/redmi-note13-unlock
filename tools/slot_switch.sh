#!/usr/bin/env bash
# Switch the active slot.
#
# Only works from fastboot. LK's set_active_slot() writes
# suffix=<slot>, current slot byte 0x7F, other slot priority 15 -> 14.
# Doing the same edit from Android is pointless: the userspace boot control
# daemon rewrites misc and restores the running slot's priority to 15.
#
# fastboot's "current-slot" getter does not refresh inside one session, so the
# result has to be read back with ro.boot.slot_suffix after the reboot.
set -euo pipefail

ADB=${ADB:-/Users/macbook/.local/bin/adb}
FB=${FB:-/opt/homebrew/share/android-commandlinetools/platform-tools/fastboot}
SERIAL=${SERIAL:-SERIAL_REDACTED}
SLOT=${1:?usage: slot_switch.sh a|b}

case "$SLOT" in
  a|b) ;;
  *) echo "slot must be a or b" >&2; exit 1 ;;
esac

$ADB -s "$SERIAL" reboot bootloader
for _ in $(seq 1 30); do
  sleep 2
  $FB -s "$SERIAL" getvar product >/dev/null 2>&1 && break
done

$FB -s "$SERIAL" --set-active="$SLOT"
$FB -s "$SERIAL" reboot

for _ in $(seq 1 48); do
  sleep 5
  state=$($ADB -s "$SERIAL" get-state 2>&1 | head -1)
  [ "$state" = "device" ] && break
done

echo "booted slot: $($ADB -s "$SERIAL" shell 'getprop ro.boot.slot_suffix' 2>&1)"
echo "magisk:      $($ADB -s "$SERIAL" shell "su -c 'magisk -v'" 2>&1 | head -1)"
