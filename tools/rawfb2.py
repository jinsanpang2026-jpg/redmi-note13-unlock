#!/usr/bin/env python3
"""Raw fastboot client, corrected calibration.

Previous attempt calibrated with a bare "getvar" and got FAIL +
"unknown command" for all six framings -> wrongly concluded every framing
was wrong. The stock client only ever sends "getvar:<name>"; MTK's fastboot
rejects a bare "getvar", so "unknown command" was the device correctly
rejecting a bogus command, not a framing failure.

Calibration now uses "getvar:unlocked" and requires the response to contain
"unlocked". Responses are accumulated over multiple USB reads because a
single read can come back short.
"""
import struct
import sys
import time

import usb.core
import usb.backend.libusb1
import usb.util

BACKEND = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")

FRAMINGS = {
    "len4":       lambda p: struct.pack("<I", len(p)) + p,
    "hdr8_zero":  lambda p: struct.pack("<II", len(p), 0) + p,
    "magic8":     lambda p: struct.pack("<II", 0x6E667265, len(p)) + p,
    "len4_nul":   lambda p: struct.pack("<I", len(p) + 1) + p + b"\x00",
    "hdr8_nul":   lambda p: struct.pack("<II", len(p) + 1, 0) + p + b"\x00",
    "raw":        lambda p: p,
}


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


class FB:
    def __init__(self, dev, itf):
        self.dev = dev
        self.itf = itf
        self.out_ep = None
        self.in_ep = None
        for ep in itf:
            if ep.bEndpointAddress & 0x80:
                self.in_ep = ep
            else:
                self.out_ep = ep
        try:
            usb.util.claim_interface(dev, itf.bInterfaceNumber)
        except Exception as e:
            print(f"  claim iface {itf.bInterfaceNumber}: {e}")

    def drain(self, rounds=8):
        for _ in range(rounds):
            try:
                self.dev.read(self.in_ep, 4096, 200)
            except Exception:
                return

    def _read_frame(self, timeout):
        buf = b""
        deadline = time.time() + timeout / 1000.0
        while time.time() < deadline:
            try:
                chunk = bytes(self.dev.read(self.in_ep, 4096, 500))
            except Exception:
                if len(buf) >= 8:
                    break
                continue
            if not chunk:
                continue
            buf += chunk
            if len(buf) >= 8:
                size = struct.unpack("<I", buf[4:8])[0]
                if len(buf) >= 8 + size:
                    break
        return buf

    def cmd(self, cmd, framing, timeout=4000):
        payload = cmd.encode()
        try:
            self.dev.write(self.out_ep, FRAMINGS[framing](payload), 10000)
        except Exception as e:
            return ("WRITE_ERR", b"", str(e))
        buf = self._read_frame(timeout)
        if len(buf) < 8:
            return ("SHORT", buf, "")
        status = buf[:4].decode(errors="replace")
        length = struct.unpack("<I", buf[4:8])[0]
        return (status, buf[8:8 + length], "")


def main():
    dev, itf = find_fastboot()
    if not dev:
        print("no fastboot interface found")
        return 1
    fb = FB(dev, itf)
    print(f"iface {itf.bInterfaceNumber} out={fb.out_ep.bEndpointAddress:#x} "
          f"in={fb.in_ep.bEndpointAddress:#x} proto={itf.bInterfaceProtocol}")

    good = None
    for name in FRAMINGS:
        fb.drain()
        st, data, err = fb.cmd("getvar:unlocked", name, timeout=4000)
        text = data.decode(errors="replace")
        print(f"  {name:11s} -> status={st!r} data={text[:70]!r} err={err}")
        if st == "OKAY" and "unlocked" in text:
            good = name
            break
    if not good:
        print("!! no framing answered getvar:unlocked")
        return 2
    print(f"CALIBRATED framing = {good}\n")

    probes = sys.argv[1:] or [
        "reboot-download",
        "reboot download",
        "reboot-brom",
        "reboot-preloader",
        "oem reboot-brom",
        "oem reboot-preloader",
        "oem download",
        "continue",
    ]
    for p in probes:
        fb.drain()
        st, data, err = fb.cmd(p, good, timeout=6000)
        print(f">>> {p!r} -> status={st!r} data={data[:220]!r} err={err}")
        time.sleep(2.0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
