#!/usr/bin/env python3
"""Soft-reset the phone's USB interface and re-probe fastboot.

A truncated/half-finished fastboot session can leave the device's command
parser stuck. A USB reset re-enumerates the interface and clears it.
"""
import sys
import time

import usb.core
import usb.backend.libusb1
import usb.util

BACKEND = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")


def find_phone():
    for d in usb.core.find(find_all=True, backend=BACKEND):
        if d.idVendor == 0x18D1 and d.idProduct == 0xD00D:
            return d
    return None


def probe(dev, cmd="getvar:unlocked", timeout=3000):
    cfg = dev.get_active_configuration()
    itf = None
    for i in cfg:
        if (i.bInterfaceClass == 0xFF and i.bInterfaceSubClass == 0x42
                and i.bInterfaceProtocol in (0x01, 0x03)):
            itf = i
            break
    if itf is None:
        return "NO_IFACE", b""
    out_ep = in_ep = None
    for ep in itf:
        if ep.bEndpointAddress & 0x80:
            in_ep = ep
        else:
            out_ep = ep
    try:
        usb.util.claim_interface(dev, itf.bInterfaceNumber)
    except Exception as e:
        return "CLAIM_ERR:%s" % e, b""
    for _ in range(8):
        try:
            dev.read(in_ep, 4096, 200)
        except Exception:
            break
    try:
        dev.write(out_ep, cmd.encode(), 10000)
    except Exception as e:
        return "WRITE_ERR:%s" % e, b""
    buf = b""
    deadline = time.time() + timeout / 1000.0
    while time.time() < deadline and len(buf) < 4:
        try:
            c = bytes(dev.read(in_ep, 4096, 400))
        except Exception:
            break
        if c:
            buf += c
    if len(buf) < 4:
        return "TIMEOUT", buf
    return buf[:4].decode(errors="replace"), buf[4:]


def main():
    dev = find_phone()
    if not dev:
        print("phone not found on USB")
        return 1
    st, data = probe(dev)
    print("before reset: status=%r payload=%r" % (st, data))
    if st == "OKAY":
        print("already responsive")
        return 0

    print("--- trying libusb reset ---")
    try:
        dev.reset()
        print("dev.reset() ok")
    except Exception as e:
        print("dev.reset() failed: %s" % e)
    time.sleep(2)

    dev = find_phone()
    if not dev:
        print("phone vanished after reset (needs cable replug)")
        return 2
    st, data = probe(dev)
    print("after reset: status=%r payload=%r" % (st, data))
    return 0 if st == "OKAY" else 3


if __name__ == "__main__":
    sys.exit(main())
