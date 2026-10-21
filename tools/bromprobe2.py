#!/usr/bin/env python3
"""Probe 2: identify whether 0e8d:0003 is in BROM or PRELOADER mode."""
import time, binascii
import usb.core, usb.backend.libusb1, usb.util

b = usb.backend.libusb1.get_backend(find_library=lambda x: 'libusb-1.0.dylib')
dev = None
for d in usb.core.find(find_all=True, backend=b):
    if d.idVendor == 0x0e8d:
        dev = d
        break
if dev is None:
    raise SystemExit("NO BROM/PRELOADER DEVICE")

dev.set_configuration()
cfg = dev.get_active_configuration()
intf = None
for it in cfg:
    if it.bInterfaceClass in (0x02, 0x0a):
        intf = it
ep_in = ep_out = None
for ep in intf:
    if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
        ep_in = ep
    else:
        ep_out = ep

def hx(x): return binascii.hexlify(x).decode()
def rd(size=512, tmo=400):
    try: return bytes(ep_in.read(size, tmo) or b'')
    except Exception: return b''
def wr(data):
    try: return ep_out.write(data, 1000)
    except Exception as e:
        print("   write err:", e); return -1

def show(tag, d):
    print("   %-14s %s" % (tag, hx(d) if d else "(nothing)"))
    return d

print("=== TEST 1: preloader hello 0x01 ===")
wr(b"\x01"); time.sleep(0.1)
show("after 0x01", rd(512, 600))
show("again", rd(512, 300))

print("\n=== TEST 2: BROM 4-byte batch a0 0a 50 05, read repeatedly ===")
wr(b"\xa0\x0a\x50\x05"); time.sleep(0.1)
for i in range(4):
    show("r%d" % i, rd(512, 300))

print("\n=== TEST 3: BROM byte-by-byte with delay ===")
for byte in (0xa0, 0x0a, 0x50, 0x05):
    wr(bytes([byte])); time.sleep(0.15)
    show("after %02x" % byte, rd(512, 500))

print("\n=== TEST 4: send 0x01 again after brom seq ===")
wr(b"\x01"); time.sleep(0.15)
show("after 0x01", rd(512, 600))
show("again", rd(512, 300))

print("\n=== TEST 5: single 0x0b / 0x0c probes (brom 'unknown' markers) ===")
for byte in (0x0b, 0x0c, 0xa1, 0x02):
    wr(bytes([byte])); time.sleep(0.1)
    show("after %02x" % byte, rd(512, 400))

print("\n=== done ===")
