#!/usr/bin/env python3
"""解析 LK 镜像里的 PC 相对字符串引用。

MTK LK 用的是 GCC 的 -mslow-flash-data 风格寻址:
    ldr  rX, [pc, #imm]      ; rX = 相对量
    add  rX, pc              ; rX += (pc+4)&~3
最终得到字符串的绝对(文件)偏移。
"""
import struct
import sys

import capstone

d = open("fu_lk_a.bin", "rb").read()
md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB | capstone.CS_MODE_LITTLE_ENDIAN)
md.detail = True
md.skipdata = True

insns = [i for i in md.disasm(d[0x80:0x170000], 0x80) if i.id != 0]
print("insns:", len(insns), file=sys.stderr)

MEM = capstone.arm.ARM_OP_MEM
REG = capstone.arm.ARM_OP_REG
PC = capstone.arm.ARM_REG_PC


def cstr(v, n=80):
    if not (0 < v < len(d)):
        return None
    t = d[v:v + n].split(b"\x00")[0]
    if len(t) < 3:
        return None
    try:
        t = t.decode("utf-8")
    except UnicodeDecodeError:
        return None
    t = t.strip()
    if len(t) < 3:
        return None
    return t if all(32 <= ord(c) < 127 or c in '\t\n\r' for c in t) else None


refs = {}
for k, ins in enumerate(insns):
    ops = ins.operands
    if len(ops) < 2:
        continue
    # capstone 对 LDR 的顺序是: [目标寄存器, 内存操作数]
    if ops[0].type != REG or ops[1].type != MEM or ops[1].mem.base != PC:
        continue
    r1 = ops[0].reg
    ea = ((ins.address + 4) & ~3) + ops[1].mem.disp
    if not (0 <= ea <= len(d) - 4):
        continue
    v = struct.unpack_from("<I", d, ea)[0]
    for j in range(k + 1, min(k + 4, len(insns))):
        nx = insns[j]
        o2 = nx.operands
        if (len(o2) >= 2 and o2[0].type == REG and o2[0].reg == r1
                and o2[1].type == REG and o2[1].reg == PC):
            final = v + ((nx.address + 4) & ~3)
            t = cstr(final)
            if t:
                refs.setdefault(final, []).append((ins.address, nx.address, t))
            break

print("解析到字符串引用:", len(refs), file=sys.stderr)
if len(sys.argv) > 1 and sys.argv[1] == "--all":
    for a in sorted(refs):
        print("0x%06x  %s   <- 0x%06x" % (a, refs[a][0][2][:60], refs[a][0][0]))
else:
    for a in sys.argv[1:]:
        a = int(a, 0)
        r = refs.get(a)
        if r:
            print("0x%06x  %-30r  code@0x%06x  xrefs=%d" % (a, r[0][2], r[0][0], len(r)))
        else:
            print("0x%06x  未找到" % a)
