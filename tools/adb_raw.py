#!/usr/bin/env python3
"""Raw adb (ADB protocol over USB) handshake test - bypasses the adb server."""
import binascii
import socket
import struct
import sys
import time

import usb.core
import usb.backend.libusb1
import usb.util

CMD = "CNXN"
VERSION = 0x01000000
MAXDATA = 4096


def make_message(cmd, arg0, arg1, payload=b""):
    header = cmd.encode("ascii")
    header += struct.pack("<III", arg0, arg1, len(payload))
    header += struct.pack("<I", binascii.crc32(payload) & 0xFFFFFFFF)
    header += struct.pack("<I", (binascii.crc32(header) & 0xFFFFFFFF) ^ 0xFFFFFFFF)
    return header + payload


def main():
    backend = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")
    dev = None
    for d in usb.core.find(find_all=True, backend=backend):
        if d.idVendor == 0x18D1 and d.idProduct == 0xD00D:
            dev = d
            break
    if dev is None:
        print("no adb device")
        return 1

    try:
        cfg = dev.get_active_configuration()
    except Exception as e:
        print("cfg err", e)
        return 1

    ep_in = ep_out = None
    for itf in cfg:
        for ep in itf:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                ep_in = ep
            else:
                ep_out = ep
    print("ep_in", ep_in and hex(ep_in.bEndpointAddress), "ep_out", ep_out and hex(ep_out.bEndpointAddress))

    try:
        usb.util.claim_interface(dev, 0)
        print("claimed interface 0")
    except Exception as e:
        print("claim failed:", e)

    banner = b"host::features=cmd,shell_v2,exec_v2\x00"
    msg = make_message(CMD, VERSION, MAXDATA, banner)
    print("sending CNXN", len(msg), "bytes")
    try:
        n = dev.write(ep_out.bEndpointAddress, msg, timeout=3000)
        print("wrote", n)
    except Exception as e:
        print("write failed:", type(e).__name__, e)
        return 1

    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            data = dev.read(ep_in.bEndpointAddress, 1024, timeout=3000)
            if data:
                print("got", len(data), "bytes:", data[:4], repr(data[24:200]))
                return 0
        except Exception as e:
            print("read failed:", type(e).__name__, e)
            break
    print("no reply")
    return 1


sys.exit(main())
