#!/usr/bin/env python3
"""Locate the fastboot variable strings in the LK image and the code that
references them, so we can find how LK computes `unlocked`."""
import struct
import sys

path = sys.argv[1]
blob = open(path, "rb").read()
n = len(blob)

NEEDLES = [b"unlocked", b"secure", b"current-slot", b"slot-count",
           b"slot-successful", b"slot-unbootable", b"slot-retry-count",
           b"is-userspace", b"product", b"version-bootloader", b"off-mode-charge"]

occ = {}
for nd in NEEDLES:
    lst = []
    idx = 0
    while True:
        idx = blob.find(nd, idx)
        if idx < 0:
            break
        lst.append(idx)
        idx += 1
    occ[nd] = lst
    print("%-20r count=%-3d %s" % (nd, len(lst), [hex(x) for x in lst[:12]]))

print("\n=== literal-pool refs ===")
for nd, lst in occ.items():
    for off in lst:
        pat = struct.pack("<I", off)
        idx = 0
        while True:
            idx = blob.find(pat, idx)
            if idx < 0:
                break
            # make sure it is a whole aligned dword
            if idx % 4 == 0:
                print("  %-20r @0x%06x  <- pool value at 0x%06x" % (nd.decode(), off, idx))
            idx += 1
