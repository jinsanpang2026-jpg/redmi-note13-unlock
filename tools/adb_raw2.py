#!/usr/bin/env python3
"""Raw adb handshake that reassembles multi-packet replies."""
import binascii
import struct
import sys
import time

import usb.core
import usb.util
import usb.backend.libusb1


def msg(cmd, arg0, arg1, payload=b""):
    h = cmd.encode() + struct.pack("<III", arg0, arg1, len(payload))
    h += struct.pack("<I", binascii.crc32(payload) & 0xFFFFFFFF)
    h += struct.pack("<I", (binascii.crc32(h) & 0xFFFFFFFF) ^ 0xFFFFFFFF)
    return h + payload


def read_message(dev, ep, timeout_ms=4000):
    """Read adb packets until one complete message is assembled."""
    buf = b""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            data = bytes(dev.read(ep.bEndpointAddress, 4096, timeout=1500))
        except Exception as e:
            return None, f"read exc {e}"
        if not data:
            continue
        buf += data
        while len(buf) >= 24:
            cmd = buf[0:4]
            length = struct.unpack("<I", buf[12:16])[0]
            total = 24 + length
            if len(buf) < total:
                break
            payload = buf[24:total]
            buf = buf[total:]
            return (cmd, payload), None
    return None, "timeout"


def main():
    backend = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")
    devs = [d for d in usb.core.find(find_all=True, backend=backend)
            if d.idVendor == 0x18D1 and d.idProduct == 0xD00D]
    if not devs:
        print("no adb device")
        return 1
    dev = devs[0]
    cfg = dev.get_active_configuration()
    ep_in = ep_out = None
    for itf in cfg:
        for ep in itf:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                ep_in = ep
            else:
                ep_out = ep

    try:
        usb.util.claim_interface(dev, 0)
        print("claimed interface 0")
    except Exception as e:
        print("claim failed:", e)

    banner = b"host::features=cmd,shell_v2,exec_v2,abb_exec\x00"
    dev.write(ep_out.bEndpointAddress, msg("CNXN", 0x01000000, 4096, banner), timeout=3000)
    print("CNXN sent")

    for i in range(6):
        m, err = read_message(dev, ep_in)
        if err:
            print("recv:", err)
            break
        cmd, payload = m
        print(f"reply[{i}] cmd={cmd!r} payload={payload!r}")
        if cmd == b"CNXN":
            print("  banner:", payload.decode("utf-8", "replace"))
            break
        if cmd == b"AUTH":
            print("  AUTH token:", payload[:32].hex())
    return 0


sys.exit(main())
