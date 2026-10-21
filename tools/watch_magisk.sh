#!/bin/bash
# Wait for Magisk to finish patching on the phone, then pull the result back.
ADB=/Users/macbook/.local/bin/adb
S=SERIAL_REDACTED
OUT=/tmp/mtkwork/magisk_patched.img
LOG=/tmp/mtkwork/watch_magisk.log

for i in $(seq 1 400); do
  f=$($ADB -s $S shell "ls /sdcard/Download/magisk_patched*.img 2>/dev/null" 2>/dev/null | tr -d '\r' | head -1)
  if [ -n "$f" ]; then
    s1=$($ADB -s $S shell "stat -c %s '$f' 2>/dev/null" 2>/dev/null | tr -d '\r')
    sleep 4
    s2=$($ADB -s $S shell "stat -c %s '$f' 2>/dev/null" 2>/dev/null | tr -d '\r')
    echo "[$(date +%H:%M:%S)] found $f size=$s1/$s2" >> $LOG
    if [ -n "$s1" ] && [ "$s1" = "$s2" ] && [ "$s1" -gt 1000000 ]; then
      if $ADB -s $S pull "$f" "$OUT" >> $LOG 2>&1; then
        echo "[$(date +%H:%M:%S)] PULLED -> $OUT" >> $LOG
        shasum -a 256 "$OUT" >> $LOG 2>&1
        ls -l "$OUT" >> $LOG
        echo DONE >> $LOG
        exit 0
      fi
    fi
  fi
  sleep 2
done
echo TIMEOUT >> $LOG
exit 1
