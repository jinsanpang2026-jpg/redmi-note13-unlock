#!/usr/bin/env python3
"""带 PC 相对字符串注释的 Thumb-2 反汇编器 (LK 镜像专用)。

usage: dis.py <start> <end> [start end ...]
"""
import struct
import sys

import capstone

d = open("fu_lk_a.bin", "rb").read()
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = True
md.skipdata = True

MEM = capstone.arm.ARM_OP_MEM
REG = capstone.arm.ARM_OP_REG
PC = capstone.arm.ARM_REG_PC


def cstr(v, n=70):
    if not (0 < v < len(d)):
        return ""
    t = d[v:v + n].split(b"\x00")[0]
    if len(t) < 2:
        return ""
    try:
        t = t.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    t = t.strip()
    if len(t) < 2:
        return ""
    return t if all(32 <= ord(c) < 127 or c in '\t\n\r' for c in t) else ""


def dis(a, b):
    insns = list(md.disasm(d[a:b], a))
    for k, ins in enumerate(insns):
        if ins.id == 0:
            continue
        note = ""
        ops = ins.operands
        if (len(ops) >= 2 and ops[0].type == REG and ops[1].type == MEM
                and ops[1].mem.base == PC):
            ea = ((ins.address + 4) & ~3) + ops[1].mem.disp
            if 0 <= ea <= len(d) - 4:
                v = struct.unpack_from("<I", d, ea)[0]
                r1 = ops[0].reg
                final = None
                for j in range(k + 1, min(k + 6, len(insns))):
                    nx = insns[j]
                    o2 = nx.operands
                    if (len(o2) >= 2 and o2[0].type == REG and o2[0].reg == r1
                            and o2[1].type == REG and o2[1].reg == PC):
                        final = v + ((nx.address + 4) & ~3)
                        break
                if final is None:
                    final = v
                t = cstr(final)
                if t:
                    note = "   ; -> 0x%06x %r" % (final, t[:52])
                else:
                    note = "   ; pool 0x%06x" % v
        print("0x%06x: %-9s%-28s%s" % (ins.address, ins.mnemonic, ins.op_str, note))


if __name__ == "__main__":
    args = [int(x, 0) for x in sys.argv[1:]]
    for i in range(0, len(args) - 1, 2):
        print("\n######## 0x%x - 0x%x ########" % (args[i], args[i + 1]))
        dis(args[i], args[i + 1])
