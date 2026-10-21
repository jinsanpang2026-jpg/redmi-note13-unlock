#!/usr/bin/env python3
"""MTK boot_control block (BCB) in the misc partition.

Layout (verified byte-level on gold/2312DRAABC):
    misc+0x800  slot_suffix[4]   "_a"/"_b" + NUL NUL
    misc+0x804  magic "BCAB"
    misc+0x808  version = 1
    misc+0x809  bitfield, bit[1:0] = nb_slot
    misc+0x80C  slot A metadata byte
    misc+0x80E  slot B metadata byte
    misc+0x81C  u32 timestamp

Slot byte:
    bit[3:0] priority        bit[6:4] tries_remaining   bit[7] successful
"""
import argparse
import sys

OFFSET = 0x800
A_OFF = 0x80C
B_OFF = 0x80E
MAGIC = b"BCAB"


def decode(byte):
    return {
        "raw": byte,
        "priority": byte & 0x0F,
        "tries": (byte >> 4) & 0x07,
        "successful": (byte >> 7) & 0x01,
    }


def encode(priority=0, tries=7, successful=0):
    return (priority & 0x0F) | ((tries & 0x07) << 4) | ((successful & 0x01) << 7)


def describe(buf):
    out = []
    suffix = buf[OFFSET:OFFSET + 4]
    magic = buf[OFFSET + 4:OFFSET + 8]
    a = decode(buf[A_OFF])
    b = decode(buf[B_OFF])
    out.append("magic     = %r %s" % (magic, "OK" if magic == MAGIC else "MISMATCH"))
    out.append("version   = %d" % buf[OFFSET + 8])
    out.append("nb_slot   = %d" % (buf[OFFSET + 9] & 0x03))
    out.append("suffix    = %r" % suffix.decode("latin1"))
    for name, s in (("A", a), ("B", b)):
        out.append(
            "slot %s    = 0x%02X  priority=%-2d tries=%d successful=%d"
            % (name, s["raw"], s["priority"], s["tries"], s["successful"])
        )
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image", help="misc partition image (512 KiB)")
    ap.add_argument("--set-suffix", choices=["_a", "_b"])
    ap.add_argument("--set-a", type=lambda v: int(v, 0), help="slot A byte")
    ap.add_argument("--set-b", type=lambda v: int(v, 0), help="slot B byte")
    ap.add_argument("--output", help="write patched image here (default: in place)")
    args = ap.parse_args()

    with open(args.image, "rb") as f:
        buf = bytearray(f.read())

    if args.set_suffix:
        buf[OFFSET:OFFSET + 4] = args.set_suffix.encode() + b"\x00\x00"
    if args.set_a is not None:
        buf[A_OFF] = args.set_a
    if args.set_b is not None:
        buf[B_OFF] = args.set_b

    dest = args.output or args.image
    with open(dest, "wb") as f:
        f.write(bytes(buf))

    sys.stdout.write(describe(buf) + "\n")


if __name__ == "__main__":
    main()
