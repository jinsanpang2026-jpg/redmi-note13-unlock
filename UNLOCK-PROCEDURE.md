# 解锁操作手册（自包含）

> 目标设备：Redmi Note 13 5G 国行 `2312DRAABC` / `gold` / MT6833 / `SERIAL_REDACTED`
> 方法：**非官方 MTK 芯片级**——物理 BROM 手势 → kamakiri2 exploit → preloader → stock DA → **清空 UFS RPMB 中的 8 字节小米解锁 magic**
> 效果：`fastboot getvar unlocked` = `yes`、`secure` = `no`、`oem lks` = `0`、LK `lock_state = 0x3`

**原理一句话**：LK 的 fastboot 锁定状态 getter 是
`final = (mi_get_lock_state() == 1) ? seccfg_lock_state : mi_get_lock_state()`；
`mi_get_lock_state()` 恰好在**读不到 RPMB 里的 magic `Jz8PNRUF`** 时返回 1；
于是 getter 回落到 seccfg 的 `lock_state=3` → 判定为已解锁。

---

## 0. 环境准备

```bash
ADB=/Users/macbook/.local/bin/adb
FB=/opt/homebrew/share/android-commandlinetools/platform-tools/fastboot
S=SERIAL_REDACTED
PY=/tmp/mtkwork/venv/bin/python
MTK=/tmp/mtkwork/src/mtkclient-main
```

mtkclient 源码位于 `$MTK`，以下补丁已打进现役源码（备份与 diff 见 `code/PATCHES.diff`）。

## 1. 前置：seccfg 必须已经是 `lock_state=3`

getter 的回落值来自 seccfg 分区。若 seccfg 不是 3，清掉 magic 也只会得到 `unlocked=no`。

```bash
# 写入 lock_state=3 / dm_verity=0 / sboot_runtime=0
cd $MTK && $PY mtk.py da seccfg unlock --outdir /tmp/mtkwork
# 读回校验（dump 后离线比对 seccfg 结构：offset 0 magic/ver/size/lock_state/...）
$FB -s $S oem chkmtklks      # 期望 (bootloader) seccfg_state is 3
```

> 本次实测：该命令返回 `seccfg_state is 3`，seccfg 已就位。

## 2. 装上 `da rpmbfix` 补丁

### 2.1 `mtkclient/Library/DA/mtk_da_handler.py`

新增模块级 helper：

```python
def _hexval(v):
    """Accept 0x.. / decimal strings or plain ints."""
    if isinstance(v, int):
        return v
    v = str(v).strip()
    return int(v, 0)
```

新增方法（挂在 DA handler 类里）：

```python
def da_rpmbfix(self, outdir: str = "/tmp/mtkwork", display: bool = True,
               magic: str = "Jz8PNRUF", win_start: str = "0xF0",
               win_len: str = "0x20", reset: bool = False):
    """Wipe the Xiaomi MI-unlock magic out of the UFS RPMB.

    LK's fastboot lock state getter computes
        final = (mi_get_lock_state() == 1) ? seccfg_lock_state : mi_get_lock_state()
    and mi_get_lock_state() returns 1 exactly when mi_check_magic() does not
    find the 8 byte magic at the RPMB base offset.  The seccfg partition
    already carries lock_state=3, so dropping the magic makes the getter
    fall back to seccfg and report unlocked=yes / secure=no.
    """
    dl = self.mtk.daloader
    if dl.flashmode != DAmodes.XFLASH:
        self.error("Device is not in xflash mode")
        return False
    if not dl.auth_rpmb():
        self.error("auth_rpmb (rpmb key init) failed")
        return False
    rpath = os.path.join(outdir, "rpmb_win.bin")
    if not dl.read_rpmb(filename=rpath, sector=win_start, sectors=win_len):
        self.error("rpmb read failed")
        return False
    with open(rpath, "rb") as rf:
        data = rf.read()
    if display:
        self.info(f"rpmb window: sectors {win_start}.., {len(data)} bytes -> {rpath}")
    key = magic.encode()
    idx = data.find(key)
    if idx < 0:
        self.error(f"magic {key!r} not found in the scanned window - nothing written")
        return False
    abs_off = _hexval(win_start) * 0x100 + idx
    sector = abs_off // 0x100
    inoff = abs_off % 0x100
    if display:
        self.info(f"magic {key!r} at rpmb offset 0x{abs_off:x} "
                  f"(sector 0x{sector:x}, +0x{inoff:x})")
    start = idx - inoff
    chunk = bytearray(data[start:start + 0x100])
    if len(chunk) != 0x100:
        self.error("sector slice out of range")
        return False
    chunk[inoff:inoff + len(key)] = b"\x00" * len(key)
    cpath = os.path.join(outdir, "rpmb_sector.bin")
    with open(cpath, "wb") as wf:
        wf.write(chunk)
    if not dl.write_rpmb(filename=cpath, sector=hex(sector), sectors="1"):
        self.error("rpmb write failed")
        return False
    self.info(f"wrote zeroed sector 0x{sector:x} to rpmb")
    vpath = os.path.join(outdir, "rpmb_verify.bin")
    if dl.read_rpmb(filename=vpath, sector=str(sector), sectors="1"):
        with open(vpath, "rb") as rf:
            v = rf.read()
        if v.find(key) < 0:
            self.info("read-back: magic is GONE -> LK will fall back to seccfg")
        else:
            self.info(f"read-back: magic still present at +0x{v.find(key):x}")
    if reset:
        bootmode = int(os.environ.get("MTC_BOOTMODE", "2"))
        dl.shutdown(bootmode=bootmode)
        self.info(f"reset sent (bootmode={bootmode})")
    return True
```

分发器加一行（在 `elif subcmd == "rpmb":` 那一支之后）：

```python
elif subcmd == "rpmbfix":
    self.da_rpmbfix(outdir=args.outdir or "/tmp/mtkwork",
                    magic=args.magic, win_start=args.winstart,
                    win_len=args.winlen, reset=args.reset)
```

### 2.2 `mtk.py`

```python
da_rpmbfix = da_subs.add_parser("rpmbfix", parents=[base],
                                help="Wipe Xiaomi MI-unlock magic from UFS RPMB")
da_rpmbfix.add_argument('--outdir', type=str, help="Directory for the dumped rpmb window")
da_rpmbfix.add_argument('--magic', type=str, default="Jz8PNRUF", help="Magic bytes to remove")
da_rpmbfix.add_argument('--winstart', type=str, default="0xF0", help="First rpmb sector to scan")
da_rpmbfix.add_argument('--winlen', type=str, default="0x20", help="Number of sectors to scan")
da_rpmbfix.add_argument('--reset', action='store_true', help="Reset to fastboot afterwards")
```

### 2.3 `bromguard.py`（BROM 窗口守护，自建）

核心约束：**永远不自动 reboot**；任何物理跳转都由人做。

```python
PHONE_IDS = ((0x0e8d, 0x0003), (0x18d1, 0xd00d), (0x18d1, 0x4ee7))

def main():
    log("=== BROMGUARD START (ptype=%s) ===" % PTYPE)
    while True:
        pre = attached()
        cmd = queued_cmd()
        argv = cmd.split() + ["--ptype", PTYPE, "--debugmode"]
        log(">>> mtk.py " + " ".join(argv) + "   (pre-attached=%s)" % (pre or "none"))
        rc = subprocess.run([PY, "mtk.py"] + argv, cwd=MTK_DIR).returncode
        log("<<< mtk.py exited rc=%s" % rc)

        waited = 0
        absent = 0
        ids = []
        while True:
            ids = attached()
            if not ids:
                absent += 1
                if absent >= 8:      # 连续消失 ~3.2s 才重新武装
                    break
                time.sleep(0.4); waited += 1
                continue
            absent = 0
            brom_like = [i for i in ids if i.startswith("0e8d")]
            if not brom_like:
                # fastboot / adb 模式：mtk.py 不抢这些接口（18d1:d00d 不在 portconfig），
                # 照常重武装，避免错过下一次 BROM 窗口
                if waited >= 8:
                    break
            time.sleep(0.4); waited += 1
        log("re-arm window (waited %.1fs, mode=%s)" % (waited, ",".join(ids) if ids else "absent"))
        time.sleep(0.3)
```

## 3. 执行解锁

### 3.1 武装

```bash
cd /tmp/mtkwork
: > bromguard.out; : > bromguard.log
printf 'da rpmbfix --outdir /tmp/mtkwork --winstart 0xFF00 --winlen 0x100\n' > queue.txt
nohup ./venv/bin/python bromguard.py > bromguard.out 2>&1 &
echo $! > bromguard.pid
```

> **窗口参数 `--winstart 0xFF00 --winlen 0x100`**
> = 读 RPMB frames `0xFF00..0xFFFF`（字节 `0xFF0000..0xFFFFFF`），覆盖 magic 所在的 frame `0xFFE0`。
> 早期误用 `--winstart 0xE0 --winlen 0x20`（按"字节地址 0xFFE0"理解）→ 全 0，找不到 magic。**单位是帧号，不是字节。**

### 3.2 物理 BROM 手势（人做）

```
1. 拔掉 USB 线
2. 长按电源键 10~15 秒，强制断电（屏幕全黑）
3. 等 3 秒
4. 音量上 + 音量下 + 电源 三键同按不松
5. 保持按住的同时插上 USB 线
6. 继续按住 5~10 秒再松手
```

判定：**屏幕一直全黑 = 进 BROM 成功**。冒出 fastboot 小兔子或 MIUI 画面 = 手势做成了普通启动，拔线重来。

### 3.3 后台自动完成

`bromguard` 抓到 BROM → mtk.py 自动完成
`kamakiri2 exploit → preloader → stock DA → auth_rpmb → 读窗口 → 定位 magic → 写 sector 0xffe0 → 回读校验`

期望日志：

```
XFlashExt - Generating sej rpmbkey...
XFlashExt - Setting rpmbkey: ok
XFlashExt - Derived rpmb key: 9c52a64044874ed1ebb0aac79744d6da9d500a3cbad0289f01bcc1dbd4ca6eac
XFlashExt - Done reading rpmb to /tmp/mtkwork/rpmb_win.bin
DaHandler - rpmb window: sectors 0xFF00.., 65536 bytes -> /tmp/mtkwork/rpmb_win.bin
DaHandler - wrote zeroed sector 0xffe0 to rpmb
XFlashExt - Done reading rpmb to /tmp/mtkwork/rpmb_verify.bin
DaHandler - read-back: magic is GONE -> LK will fall back to seccfg
```

校验产物：

```bash
./venv/bin/python - <<'PY'
d=open('rpmb_win.bin','rb').read()
print("len",len(d),"nonzero",sum(1 for b in d if b),"magic@",hex(d.find(b'Jz8PNRUF')))
PY
# 期望: len 65536 nonzero 8 magic@ 0xe000   → 绝对地址 0xFF0000+0xE000 = 0xFFE000
```

### 3.4 回 fastboot

> ⚠️ **不要用 `mtk.py reset`**。DA 层 `shutdown(bootmode=2)` 实测会把手机关成黑屏，而不是进 fastboot。
> 用物理键：**音量下 + 电源** 两键同按 → 插 USB → 保持 5 秒 → fastboot 小兔子。

## 4. 验收

```bash
$FB -s $S getvar all > /tmp/mtkwork/gv_final.txt 2>&1
grep -aE "unlocked|secure" /tmp/mtkwork/gv_final.txt
#   (bootloader) unlocked: yes
#   (bootloader) secure: no

$FB -s $S oem lks
#   (bootloader) lks = 0          （解锁前是 1）

$FB -s $S oem chkmtklks
#   (bootloader) seccfg_state is 3

$FB -s $S oem dump_pllk_log > /tmp/mtkwork/lklog_final.txt 2>&1
```

LK 日志里应出现：

```
[1745] mi_check_magic 1st time run RPMB Lock, no magic      ← magic 已没了
[1698] [SEC_POLICY] sboot_state = 0x1
[1698] [SEC_POLICY] lock_state = 0x3                        ← 已解锁
[1698] img_auth_required = 0
```

## 5. 反汇编复查（自建工具）

```bash
cd /tmp/mtkwork
./venv/bin/python tools/lkdis.py 0x5cd68 0x5cf00   # mi_get_lock_state 分派
./venv/bin/python tools/lkdis.py 0x5dc18 0x5dd00   # fastboot getter
./venv/bin/python tools/lkdis.py 0x7cc00 0x7ccc0   # f_secure / f_unlock
./venv/bin/python tools/lkdis.py 0x5cb68 0x5cc1c   # base_offset 计算
./venv/bin/python tools/lkdis.py 0x5c908 0x5c9c8   # rpmb_read 封装
./venv/bin/python tools/lkdis.py 0x5d000 0x5d920   # mi_verify_token（官方 token 路径）
```

关键坐标：

```
0x5dc78   ★ fastboot getter: final = (mi_out==1) ? seccfg : mi_out
0x5cd68   mi_get_lock_state：ret6→seccfg / ret3→*out=1 / ret4→*out=4 / ret0→验签
0x5cc1c   mi_check_magic：magic 不符→3；rpmb_read 错误码透传
0x5cb68   base_offset：16MB→0xffe0，4MB→0x3fe0（★单位是 0x100 字节帧号）
0x5c908   rpmb_read 封装：底层 result==7→返回 6
0x7a61c   读 seccfg lock_state
0x12a150  "Jz8PNRUF"
```

## 6. 一键回滚（把 magic 写回去）

如果需要恢复原状，把 `rpmb_win.bin` 里 frame `0xFFE0` 的原始 8 字节写回即可（原始内容 = 当前全零帧 + `Jz8PNRUF` @ 帧内偏移 `0xE0`）：

```bash
cd /tmp/mtkwork && ./venv/bin/python - <<'PY'
d = bytearray(open('rpmb_win.bin','rb').read())
off = 0xE000                       # 窗口内偏移
d[off:off+8] = b'Jz8PNRUF'
open('rpmb_restore.bin','wb').write(bytes(d[off & ~0xFF:(off & ~0xFF)+0x100]))
print("restored frame at window+0x%x" % (off & ~0xFF))
PY
# 然后用 da rpmb w 写回 frame 0xffe0
cd $MTK && $PY mtk.py da rpmb w /tmp/mtkwork/rpmb_restore.bin --sector 0xffe0 --sectors 1
```

## 7. 硬性注意事项

| 约束 | 原因 |
|---|---|
| 后台脚本**绝不** reboot / 绝不把手机踢出 fastboot | 用户硬约束；所有物理跳转由人做 |
| `mtk.py reset` 默认 `MTC_BOOTMODE=0`（关机） | 必须显式 `MTC_BOOTMODE=2`，但实测仍不可靠，改用物理音量下+电源 |
| `ptype` 只允许 `kamakiri2` | `kamakiri`/`amonet`/`carbonara` 会破坏本机 BROM USB 协议栈（设备退化成 1:1 字节回显，须物理断电冷启动恢复） |
| **不要**用 pyusb 枚举后再启动 mtk.py | 错过 BROM 握手开头 → "Wrong magic" |
| **不要**把 fastboot 输出接管道 `head` | SIGPIPE 会把解析器卡死 |
| **不要**碰 `vbmeta_b` | 槽 B 是当前唯一可用槽 |
| `read_rpmb` 之前必须 `auth_rpmb()` | 上游 `read_rpmb` 不做 RPMB init，不派生密钥就读会拿到空数据 |
| `str_to_int` 只接受字符串 | `read_rpmb/write_rpmb` 的 sector 必须传 `"0xFF00"` / `"1"` 形式 |
| BROM 手势前必须彻底断电 | 手机在 fastboot 时做手势无效 |
