#!/usr/bin/env python3
"""Full BROM characterisation.

A) reset, then READ ONLY  -> does the device speak first?
B) apply SET_LINE_CODING(921600 8N1) + SET_CONTROL_LINE_STATE(RTS=1), read only
C) write 0xA0 -> read (expect complement 0x5F if real BROM)
D) write complement 0x5F 0xF5 0xAF 0xFA -> read (role-reversed hypothesis)
"""
import time, sys, binascii
import usb.core, usb.backend.libusb1, usb.util

b = usb.backend.libusb1.get_backend(find_library=lambda x: 'libusb-1.0.dylib')

def find_brom():
    for d in usb.core.find(find_all=True, backend=b):
        if d.idVendor == 0x0e8d:
            return d
    return None

def hx(x): return binascii.hexlify(x).decode()

dev = find_brom()
if dev is None:
    raise SystemExit("NO 0e8d DEVICE")

try:
    dev.reset(); print("USB reset issued")
except Exception as e:
    print("reset err:", e)
try: usb.util.dispose_resources(dev)
except Exception: pass
del dev
time.sleep(1.5)
for _ in range(25):
    dev = find_brom()
    if dev is not None: break
    time.sleep(0.3)
if dev is None:
    raise SystemExit("device vanished after reset")
print("re-enumerated\n")

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

def rd(size=512, tmo=300):
    try: return bytes(ep_in.read(size, tmo) or b'')
    except Exception: return b''
def wr(data):
    try: return ep_out.write(data, 2000)
    except Exception as e:
        print("   write err:", e); return -1

print("=== A) READ ONLY x12 (no CDC control, no write) ===")
allA = b''
for i in range(12):
    d = rd(512, 250)
    if d:
        print("  r%-2d %s" % (i, hx(d)))
        allA += d
print("  A total:", hx(allA) or "(nothing)")

print("\n=== B) SET_LINE_CODING + SET_CONTROL_LINE_STATE(RTS) then read ===")
def ctrl(rt, req, value=0, data=None, index=0):
    return dev.ctrl_transfer(bmRequestType=rt, bRequest=req, wValue=value,
                             data_or_wLength=data, wIndex=index)
try:
    lc = bytearray([0x00, 0x0C, 0x0E, 0x00, 0x00, 0x00, 0x08])
    ctrl(0x21, 0x20, data=lc, index=0)
    print("  SET_LINE_CODING ok")
except Exception as e:
    print("  SET_LINE_CODING err:", e)
try:
    ctrl(0x21, 0x22, value=0x02, index=0)
    print("  SET_CONTROL_LINE_STATE(RTS=1) ok")
except Exception as e:
    print("  RTS err:", e)
time.sleep(0.2)
allB = b''
for i in range(8):
    d = rd(512, 250)
    if d:
        print("  r%-2d %s" % (i, hx(d)))
        allB += d
print("  B total:", hx(allB) or "(nothing)")

print("\n=== C) write 0xA0 -> read ===")
n = wr(b"\xa0"); time.sleep(0.1)
d = rd(512, 600)
print("  wrote=%s read=%s" % (n, hx(d) if d else "(nothing)"))
for i in range(4):
    d = rd(512, 200)
    if d: print("   extra r%d %s" % (i, hx(d)))

print("\n=== D) write complement seq 5f f5 af fa -> read ===")
n = wr(b"\x5f\xf5\xaf\xfa"); time.sleep(0.1)
d = rd(512, 600)
print("  wrote=%s read=%s" % (n, hx(d) if d else "(nothing)"))
for i in range(4):
    d = rd(512, 200)
    if d: print("   extra r%d %s" % (i, hx(d)))

print("\n=== E) write 0x01 (preloader hello) -> read ===")
n = wr(b"\x01"); time.sleep(0.1)
d = rd(512, 600)
print("  wrote=%s read=%s" % (n, hx(d) if d else "(nothing)"))
for i in range(4):
    d = rd(512, 200)
    if d: print("   extra r%d %s" % (i, hx(d)))

print("\n=== done ===")
