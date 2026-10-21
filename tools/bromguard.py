#!/usr/bin/env python3
"""BROM guard -- keeps exactly one armed mtk.py waiting for a fresh BROM window.

Rules enforced here:
  * ptype is pinned to kamakiri2.  kamakiri/amonet/carbonara corrupt this
    device's BROM USB stack (verified: after kamakiri the device degenerates
    into a 1:1 byte echo and can no longer complete the handshake).
  * mtk.py is never restarted while the device is still enumerated.  A
    restart detaches/re-attaches the USB interface and burns the window.
  * Nothing here ever reboots the phone.  Every mode transition is physical
    and done by the user.
"""
import os
import subprocess
import sys
import time

import usb.core
import usb.backend.libusb1

MTK_DIR = "/tmp/mtkwork/src/mtkclient-main"
PY = "/tmp/mtkwork/venv/bin/python"
QUEUE = "/tmp/mtkwork/queue.txt"
LOG = "/tmp/mtkwork/bromguard.log"
PTYPE = "kamakiri2"

# VID/PID pairs that count as "a phone is attached in some boot mode".
PHONE_IDS = ((0x0e8d, 0x0003), (0x18d1, 0xd00d), (0x18d1, 0x4ee7))


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def attached():
    """Return list of attached phone-mode USB ids."""
    try:
        b = usb.backend.libusb1.get_backend(
            find_library=lambda x: "libusb-1.0.dylib")
        found = []
        for d in usb.core.find(find_all=True, backend=b):
            for vid, pid in PHONE_IDS:
                if d.idVendor == vid and d.idProduct == pid:
                    found.append("%04x:%04x" % (vid, pid))
        return found
    except Exception:
        return []


def queued_cmd():
    try:
        with open(QUEUE) as f:
            for line in f:
                line = line.strip()
                if line:
                    return line
    except Exception:
        pass
    return "da fixunlock --vbmode 3 --outdir /tmp/mtkwork"


def main():
    log("=== BROMGUARD START (ptype=%s) ===" % PTYPE)
    while True:
        pre = attached()
        cmd = queued_cmd()
        argv = cmd.split() + ["--ptype", PTYPE, "--debugmode"]
        log(">>> mtk.py " + " ".join(argv) + "   (pre-attached=%s)" % (pre or "none"))
        try:
            p = subprocess.run([PY, "mtk.py"] + argv, cwd=MTK_DIR)
            rc = p.returncode
        except Exception as e:
            rc = -1
            log("mtk.py launch error: %s" % e)
        log("<<< mtk.py exited rc=%s" % rc)

        # Do not respawn while the phone is still plugged in: a fresh process
        # would fight the existing one for the USB handle and lose the window.
        # Require several consecutive "absent" polls so that a fast
        # unplug/replug cycle cannot slip through the gap, and so that the
        # short disconnect during a mode transition (BROM -> fastboot) does
        # not re-arm us while the device is coming back.
        waited = 0
        absent = 0
        ids = []
        while True:
            ids = attached()
            if not ids:
                absent += 1
                if absent >= 8:
                    break
                time.sleep(0.4)
                waited += 1
                continue
            absent = 0
            brom_like = [i for i in ids if i.startswith("0e8d")]
            if not brom_like:
                # The phone sits in fastboot / adb mode.  mtk.py never grabs
                # those interfaces (18d1:d00d is not in portconfig), so
                # re-arming is safe and keeps a listener alive for the next
                # BROM window instead of idling until an unplug happens.
                if waited >= 8:
                    break
            if waited == 0:
                log("device present (%s) -> %s" % (
                    ",".join(ids),
                    "holding off respawn" if brom_like else "re-arming (non-BROM mode)"))
            time.sleep(0.4)
            waited += 1
        log("re-arm window (waited %.1fs, mode=%s)" % (
            waited, ",".join(ids) if ids else "absent"))
        time.sleep(0.3)


if __name__ == "__main__":
    main()
