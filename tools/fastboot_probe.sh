#!/bin/bash
# Probe everything fastboot protocol mode still allows us on a locked device.
FB=/opt/homebrew/share/android-commandlinetools/platform-tools/fastboot
S=SERIAL_REDACTED
OUT=/tmp/mtkwork/fastboot_probe.log
: > "$OUT"
exec >> "$OUT" 2>&1

echo "=== fastboot probe start $(date) ==="
for i in $(seq 1 600); do
  if $FB devices 2>/dev/null | grep -q "$S"; then break; fi
  sleep 1
done
echo "[$i] fastboot device seen"

echo "--- getvar all ---"
timeout 20 $FB -s $S getvar all 2>&1 | head -60

echo "--- get_unlock_ability ---"
timeout 15 $FB -s $S flashing get_unlock_ability 2>&1

echo "--- flash seccfg (offline sw-generated unlock blob) ---"
timeout 60 $FB -s $S flash seccfg /tmp/mtkwork/seccfg.bin 2>&1
echo "rc=$?"

echo "--- reboot download (MTK preloader mode?) ---"
timeout 20 $FB -s $S reboot download 2>&1
echo "rc=$?"

echo "--- usb after reboot download ---"
for i in $(seq 1 20); do
  /tmp/mtkwork/venv/bin/python - <<'PY'
import usb.core, usb.backend.libusb1
b = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")
print(' '.join('%04x:%04x' % (d.idVendor, d.idProduct) for d in usb.core.find(find_all=True, backend=b)))
PY
  sleep 1
done

echo "=== fastboot probe end $(date) ==="
