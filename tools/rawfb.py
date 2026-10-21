#!/usr/bin/env python3
"""Raw fastboot protocol client over pyusb.

The stock fastboot binary refuses some reboot targets client-side, so we speak
the protocol ourselves and can send whatever the bootloader accepts.
"""
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
                    and itf.bInterfaceProtocol == 0x03):
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

    def _write(self, data):
        self.dev.write(self.out_ep, data, 10000)

    def _read_all(self, timeout=4000):
        return bytes(self.dev.read(self.in_ep, 4096, timeout))

    def send(self, cmd, framing="len4"):
        payload = cmd.encode() if isinstance(cmd, str) else cmd
        if framing == "len4":
            self._write(struct.pack("<I", len(payload)) + payload)
        elif framing == "len4_nul":
            self._write(struct.pack("<I", len(payload) + 1) + payload + b"\x00")
        elif framing == "hdr8":
            self._write(struct.pack("<II", len(payload), 0) + payload)
        elif framing == "hdr8_nul":
            self._write(struct.pack("<II", len(payload) + 1, 0) + payload + b"\x00")

    def read_msg(self, timeout=4000):
        try:
            buf = self._read_all(timeout)
        except Exception as e:
            return ("TIMEOUT", b"", str(e))
        if len(buf) < 8:
            return ("SHORT", buf, "")
        status = buf[:4]
        length = struct.unpack("<I", buf[4:8])[0]
        data = buf[8:8 + length]
        return (status.decode(errors="replace"), data, "")

    def cmd(self, cmd, framing="len4", timeout=4000):
        self.send(cmd, framing)
        return self.read_msg(timeout)


def main():
    dev, itf = find_fastboot()
    if not dev:
        print("no fastboot interface found")
        return 1
    fb = FB(dev, itf)
    print(f"fastboot iface {itf.bInterfaceNumber} out_ep={fb.out_ep.bEndpointAddress:#x} "
          f"in_ep={fb.in_ep.bEndpointAddress:#x}")

    good = None
    for framing in ("len4", "len4_nul", "hdr8", "hdr8_nul"):
        try:
            st, data, err = fb.cmd("getvar:unlocked", framing, timeout=3000)
        except Exception as e:
            print(f"  framing {framing}: exception {e}")
            continue
        print(f"  framing {framing}: status={st!r} data={data[:60]!r} err={err}")
        if st in ("OKAY", "FAIL") and (b"unlocked" in data or st == "FAIL"):
            good = framing
            break
    if not good:
        print("!! could not calibrate framing")
        return 2
    print(f"framing = {good}")

    probes = sys.argv[1:] or [
        "reboot-download",
        "reboot download",
        "oem reboot download",
        "reboot-brom",
        "oem reboot-brom",
        "reboot emergency",
        "oem emergency",
    ]
    for p in probes:
        st, data, err = fb.cmd(p, good, timeout=5000)
        print(f">>> {p!r} -> status={st!r} data={data[:160]!r} err={err}")
        time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
