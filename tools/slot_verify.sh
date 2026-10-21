#!/usr/bin/env bash
# Slot / root health check.
set -euo pipefail

ADB=${ADB:-/Users/macbook/.local/bin/adb}
SERIAL=${SERIAL:-SERIAL_REDACTED}

PARTITIONS=(
  boot vendor_boot vbmeta vbmeta_system vbmeta_vendor
  dtbo lk preloader tee mcupm scp sspm spmfw gz logo dpm md1img pi_img
)

echo "== slot =="
$ADB -s "$SERIAL" shell "getprop ro.boot.slot_suffix; getprop ro.boot.slot; getprop ro.boot.verifiedbootstate"

echo "== root =="
$ADB -s "$SERIAL" shell "su -c 'magisk -v; id'"

echo "== BCB =="
$ADB -s "$SERIAL" shell "su -c 'cat /dev/block/by-name/misc' > /sdcard/bcb.bin"
sleep 1
$ADB -s "$SERIAL" pull /sdcard/bcb.bin /tmp/bcb.bin >/dev/null
python3 "$(dirname "$0")/bcb.py" /tmp/bcb.bin

echo "== A/B parity =="
fail=0
for p in "${PARTITIONS[@]}"; do
  a=$($ADB -s "$SERIAL" shell "su -c 'sha256sum /dev/block/by-name/${p}_a'" 2>/dev/null | awk '{print $1}')
  b=$($ADB -s "$SERIAL" shell "su -c 'sha256sum /dev/block/by-name/${p}_b'" 2>/dev/null | awk '{print $1}')
  if [ "$a" = "$b" ]; then
    echo "  OK   $p"
  else
    echo "  DIFF $p  a=${a:0:16} b=${b:0:16}"
    fail=1
  fi
done
exit $fail
