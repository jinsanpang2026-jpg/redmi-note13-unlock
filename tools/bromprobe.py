#!/usr/bin/env python3
"""Raw BROM byte-stream probe: no mtkclient, no assumptions about echo semantics."""
import sys, time, binascii
import usb.core, usb.backend.libusb1, usb.util

b = usb.backend.libusb1.get_backend(find_library=lambda x: 'libusb-1.0.dylib')

def find_brom():
    for d in usb.core.find(find_all=True, backend=b):
        if d.idVendor == 0x0e8d:
            return d
    return None

def hx(x):
    return binascii.hexlify(x).decode()

def main():
    dev = find_brom()
    if dev is None:
        print("NO BROM DEVICE")
        return
    print("DEV %04x:%04x" % (dev.idVendor, dev.idProduct))
    try:
        dev.set_configuration()
    except Exception as e:
        print("set_configuration:", e)
    cfg = dev.get_active_configuration()
    intf = None
    for it in cfg:
        if it.bInterfaceClass in (0x02, 0x0a):
            intf = it
            print("IF class=%02x sub=%02x proto=%02x num=%d" %
                  (it.bInterfaceClass, it.bInterfaceSubClass, it.bInterfaceProtocol, it.bInterfaceNumber))
    if intf is None:
        print("no cdc interface")
        return

    # find bulk endpoints
    ep_in = ep_out = None
    for ep in intf:
        addr = ep.bEndpointAddress
        if usb.util.endpoint_direction(addr) == usb.util.ENDPOINT_IN:
            ep_in = ep
        else:
            ep_out = ep
    print("ep_in=%s ep_out=%s" % (hex(ep_in.bEndpointAddress) if ep_in else None,
                                  hex(ep_out.bEndpointAddress) if ep_out else None))

    # --- CDC control: set line coding + RTS (same as mtkclient) ---
    def ctrl(req_type, req, value=0, data=None, index=0):
        return dev.ctrl_transfer(bm_request_type=req_type, b_request=req,
                                 w_value=value, data_or_w_length=data, w_index=index)

    try:
        lc = bytearray([0x00, 0x0C, 0x0E, 0x00, 0x00, 0x00, 0x08])  # 921600 8N1
        ctrl(0x21, 0x20, data=lc, index=0)   # SET_LINE_CODING
        print("line coding ok")
    except Exception as e:
        print("line coding err:", e)
    try:
        ctrl(0x21, 0x22, value=0x02, index=0)  # SET_CONTROL_LINE_STATE RTS=1
        print("rts ok")
    except Exception as e:
        print("rts err:", e)

    def rd(size=512, tmo=400):
        try:
            return bytes(ep_in.read(size, tmo) or b'')
        except Exception as e:
            return b''

    def wr(data):
        try:
            return ep_out.write(data, 1000)
        except Exception as e:
            print("   write err:", e)
            return -1

    print("\n== idle read ==")
    d = rd(512, 400)
    print("idle:", hx(d) if d else "(nothing)")

    seq = [0xa0, 0x0a, 0x50, 0x05]
    for byte in seq:
        print("\n== write %02x ==" % byte)
        n = wr(bytes([byte]))
        print("   wrote", n)
        time.sleep(0.05)
        d = rd(512, 600)
        print("   read:", hx(d) if d else "(nothing)")
        # also try a second read for stragglers
        d2 = rd(512, 200)
        if d2:
            print("   read2:", hx(d2))

    print("\n== bulk write 4-byte startcmd at once ==")
    n = wr(b"\xa0\x0a\x50\x05")
    print("   wrote", n)
    time.sleep(0.05)
    d = rd(512, 600)
    print("   read:", hx(d) if d else "(nothing)")

    print("\n== done ==")

if __name__ == '__main__':
    main()
