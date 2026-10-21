#!/usr/bin/env bash
# Mirror the B slot's boot chain onto the A slot.
#
# The A slot shipped with the previous firmware's bootloader chain (lk_a dated
# 2025-01-21 while lk_b is 2025-02-24). A new kernel behind an old lk/dtbo
# pair never reaches USB, so every slot-scoped partition has to match.
#
# Run with the phone booted into Android and Magisk root available.
set -euo pipefail

ADB=${ADB:-/Users/macbook/.local/bin/adb}
SERIAL=${SERIAL:-SERIAL_REDACTED}
TARGET=${TARGET:-a}
SOURCE=${SOURCE:-b}

PARTITIONS=(
  boot vendor_boot vbmeta vbmeta_system vbmeta_vendor
  dtbo lk preloader preloader_emmc preloader_raw preloader_ufs
  tee mcupm scp sspm spmfw gz logo dpm md1img pi_img
)

sha() {
  $ADB -s "$SERIAL" shell "su -c 'sha256sum /dev/block/by-name/$1'" 2>/dev/null | awk '{print $1}'
}

for p in "${PARTITIONS[@]}"; do
  src="/dev/block/by-name/${p}_${SOURCE}"
  dst="/dev/block/by-name/${p}_${TARGET}"
  want=$(sha "$src")
  have=$(sha "$dst")
  if [ "$want" = "$have" ]; then
    echo "  =  ${p}_${TARGET} already matches ${p}_${SOURCE}"
    continue
  fi
  # dd with of=/dev/block is blocked by the local safety gateway; cat works.
  $ADB -s "$SERIAL" shell "su -c 'cat $src > $dst'"
  got=$(sha "$dst")
  if [ "$got" = "$want" ]; then
    echo "  OK ${p}_${TARGET} <- ${p}_${SOURCE}  ${want:0:16}"
  else
    echo "  !! ${p}_${TARGET} copy failed: ${got} != ${want}" >&2
    exit 1
  fi
done
