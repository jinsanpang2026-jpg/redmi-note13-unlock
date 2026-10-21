#!/usr/bin/env python3
"""Raw fastboot client, protocol confirmed against this device.

Wire format (MTK bootloader, NOT AOSP):
  host -> device : raw command string, no header, no NUL
  device -> host : status(4 bytes, "OKAY"/"FAIL") + raw payload, no length field

Confirmed with getvar:unlocked -> device replied "OKAYno" (6 bytes), which the
stock fastboot client renders as "unlocked: no".

Now used to send reboot targets the stock client refuses client-side
("unknown reboot target download" is Google's client, not the device).
"""
import struct
import sys
import time

import usb.core
import usb.backend.libusb1
import usb.util

BACKEND = usb.backend.libusb1.get_backend(find_library=lambda x: "libusb-1.0.dylib")
FB_PID = (0x18D1, 0xD00D)


def usb_ids():
    out = []
    try:
        for d in usb.core.find(find_all=True, backend=BACKEND):
            out.append((d.idVendor, d.idProduct))
    except Exception:
        pass
    return out


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

    def cmd(self, cmd, timeout=4000):
        try:
            self.dev.write(self.out_ep, cmd.encode(), 10000)
        except Exception as e:
            return ("WRITE_ERR", b"", str(e))
        buf = b""
        deadline = time.time() + timeout / 1000.0
        while time.time() < deadline:
            try:
                chunk = bytes(self.dev.read(self.in_ep, 4096, 500))
            except Exception:
                break
            if not chunk:
                continue
            buf += chunk
            # status + payload; payload usually arrives in the same packet
            if len(buf) >= 4:
                break
        if len(buf) < 4:
            return ("SHORT", buf, "")
        return (buf[:4].decode(errors="replace"), buf[4:], "")


def main():
    dev, itf = find_fastboot()
    if not dev:
        print("no fastboot interface found")
        return 1
    fb = FB(dev, itf)
    print(f"iface {itf.bInterfaceNumber} proto={itf.bInterfaceProtocol}")

    fb.drain()
    st, data, err = fb.cmd("getvar:unlocked")
    print(f"calibration: getvar:unlocked -> {st} {data!r}")
    if st != "OKAY":
        print("!! protocol calibration failed")
        return 2

    probes = sys.argv[1:] or [
        "reboot-download",
        "reboot-brom",
        "reboot download",
        "oem reboot-brom",
        "oem download",
        "reboot-preloader",
    ]
    for p in probes:
        fb.drain()
        st, data, err = fb.cmd(p, timeout=5000)
        print(f">>> {p!r} -> status={st!r} payload={data[:200]!r} err={err}")
        time.sleep(2.0)
        ids = usb_ids()
        print(f"    usb now: {['%04x:%04x' % t for t in ids]}")
        if FB_PID not in ids:
            print(f"    *** DEVICE LEFT FASTBOOT after {p!r} ***")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
