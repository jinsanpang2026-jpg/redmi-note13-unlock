#!/usr/bin/env python3
"""Low-level BROM probe: find out exactly where interface 0 blocks us.

Runs inside the ~3s BROM window, so it only does USB-level work, no handshake.
"""
import array
import sys
from binascii import hexlify

import usb.core
import usb.backend.libusb1
import usb.util

BACKEND = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")


def open_brom():
    for d in usb.core.find(find_all=True, backend=BACKEND):
        if d.idVendor == 0x0E8D and d.idProduct == 0x0003:
            return d
    return None


def show(label, fn):
    try:
        r = fn()
        if isinstance(r, (bytes, bytearray, array.array)):
            r = hexlify(bytes(r)).decode()
        print(f"{label}: OK {r}", flush=True)
        return r
    except Exception as e:
        print(f"{label}: FAIL {type(e).__name__}: {e}", flush=True)
        return None


def main():
    dev = open_brom()
    if dev is None:
        print("NO-BROM-DEVICE")
        return 1
    print("BROM device found", flush=True)

    try:
        cfg = dev.get_active_configuration()
        if cfg is None:
            dev.set_configuration()
            cfg = dev.get_active_configuration()
    except Exception as e:
        print("config:", e, flush=True)
        cfg = None
    if cfg is not None:
        print("interfaces:", cfg.bNumInterfaces, flush=True)

    for i in (0, 1):
        show(f"kernel_driver_active({i})", lambda i=i: dev.is_kernel_driver_active(i))

    show("claim_iface0", lambda: usb.util.claim_interface(dev, 0))
    show("claim_iface1", lambda: usb.util.claim_interface(dev, 1))

    show("ctrl_A1_0x25", lambda: dev.ctrl_transfer(0xA1, 0x25, 0, 0, 8))
    show("ctrl_C1_0x25", lambda: dev.ctrl_transfer(0xC1, 0x25, 0, 0, 8))
    show("ctrl_A1_0x21", lambda: dev.ctrl_transfer(0xA1, 0x21, 0, 0, 7))

    ctx = dev._ctx
    orig = ctx.managed_claim_interface

    def _claim(d, intf):
        idx = intf.bInterfaceNumber if hasattr(intf, "bInterfaceNumber") else intf
        if idx == 0:
            return None
        return orig(d, intf)

    ctx.managed_claim_interface = _claim
    show("relax_ctrl_A1_0x25", lambda: dev.ctrl_transfer(0xA1, 0x25, 0, 0, 8))
    show("relax_ctrl_A1_0x21", lambda: dev.ctrl_transfer(0xA1, 0x21, 0, 0, 7))
    show("relax_ctrl_A0_0x25", lambda: dev.ctrl_transfer(0xA0, 0x25, 0, 0, 8))
    show("relax_ctrl_C1_0x25", lambda: dev.ctrl_transfer(0xC1, 0x25, 0, 0, 8))
    return 0


sys.exit(main())
