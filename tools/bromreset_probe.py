#!/usr/bin/env python3
"""Reset BROM USB port, then immediately try the standard 4-byte BROM handshake.
Detects: complement echo (0x5f/f5/af/fa = real BROM) vs 1:1 echo (dirty/preloader).
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

def main():
    do_reset = '--reset' in sys.argv
    dev = find_brom()
    if dev is None:
        print("NO 0e8d DEVICE")
        return
    print("found %04x:%04x" % (dev.idVendor, dev.idProduct))

    if do_reset:
        try:
            dev.reset()
            print("USB reset issued")
        except Exception as e:
            print("reset err:", e)
        # drop handle, wait for re-enumeration
        try: usb.util.dispose_resources(dev)
        except Exception: pass
        del dev
        time.sleep(1.5)
        for _ in range(20):
            dev = find_brom()
            if dev is not None:
                break
            time.sleep(0.3)
        if dev is None:
            print("device vanished after reset")
            return
        print("re-enumerated %04x:%04x" % (dev.idVendor, dev.idProduct))

    try:
        dev.set_configuration()
    except Exception as e:
        print("set_configuration err:", e)
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
    print("ep_in=%s ep_out=%s" % (hex(ep_in.bEndpointAddress), hex(ep_out.bEndpointAddress)))

    def rd(size=512, tmo=400):
        try: return bytes(ep_in.read(size, tmo) or b'')
        except Exception: return b''
    def wr(data):
        try: return ep_out.write(data, 2000)
        except Exception as e:
            print("   write err:", e); return -1

    # drain stale
    for _ in range(3):
        d = rd(512, 150)
        if d: print("drain:", hx(d))

    print("\n== standard BROM handshake byte-by-byte ==")
    expect = [0x5f, 0xf5, 0xaf, 0xfa]
    got = b''
    for i, byte in enumerate((0xa0, 0x0a, 0x50, 0x05)):
        n = wr(bytes([byte]))
        time.sleep(0.08)
        d = rd(512, 600)
        print("  wrote %02x -> wrote=%s read=%s" % (byte, n, hx(d) if d else "(nothing)"))
        got += d
    comp = bytes(~x & 0xFF for x in (0xa0, 0x0a, 0x50, 0x05))
    print("\n  total read:", hx(got))
    print("  expect complement:", hx(comp), " MATCH" if got == comp else " no")
    if got == (b"\xa0\x0a\x50\x05"):
        print("  -> 1:1 ECHO (dirty state)")
    elif got[:4] == comp:
        print("  -> REAL BROM HANDSHAKE OK")

if __name__ == '__main__':
    main()
