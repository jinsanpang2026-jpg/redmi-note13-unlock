#!/usr/bin/env python3
"""Hex-dump exactly what the device sends back, one USB read at a time."""
import struct
import sys
import time

import usb.core
import usb.backend.libusb1
import usb.util

BACKEND = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")


def find_fastboot():
    for d in usb.core.find(find_all=True, backend=BACKEND):
        try:
            cfg = d.get_active_configuration()
        except Exception:
            continue
        for itf in cfg:
            if (itf.bInterfaceClass == 0xFF and itf.bInterfaceSubClass == 0x42
                    and itf.bInterfaceProtocol in (0x01, 0x03)):
                return d, itf
    return None, None


def main():
    dev, itf = find_fastboot()
    if not dev:
        print("no fastboot interface found")
        return 1
    out_ep = in_ep = None
    for ep in itf:
        if ep.bEndpointAddress & 0x80:
            in_ep = ep
        else:
            out_ep = ep
    try:
        usb.util.claim_interface(dev, itf.bInterfaceNumber)
    except Exception as e:
        print("claim:", e)

    for _ in range(8):
        try:
            dev.read(in_ep, 4096, 200)
        except Exception:
            break

    cmd = sys.argv[1] if len(sys.argv) > 1 else "getvar:unlocked"
    print(f"--> {cmd!r}")
    dev.write(out_ep, cmd.encode(), 10000)
    total = b""
    for i in range(12):
        try:
            chunk = bytes(dev.read(in_ep, 4096, 600))
        except Exception as e:
            print(f"read {i}: {e}")
            break
        if not chunk:
            print(f"read {i}: <empty>")
            break
        print(f"read {i}: len={len(chunk)} hex={chunk.hex()}")
        print(f"        ascii={chunk.decode(errors='replace')!r}")
        total += chunk
        if len(total) >= 8:
            size = struct.unpack("<I", total[4:8])[0]
            if len(total) >= 8 + size:
                break
    print(f"\nTOTAL len={len(total)} hex={total.hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
