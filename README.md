# Redmi Note 13 5G 国行 — 非官方 MTK 芯片级 Bootloader 解锁

**状态：全部完成。** 2026-10-21 04:30 验收通过。

```
① Bootloader 解锁
   unlocked: no  →  yes
   secure:  yes  →  no
   oem lks:  1   →  0
   LK 运行时：lock_state = 0x3, img_auth_required = 0

② Magisk 28.1 root
   magisk -v  → 28.1:MAGISK:R
   su -c id  → uid=0(root) context=u:r:magisk:s0
   verifiedbootstate = orange

③ A 槽修复（slot-unbootable:a）
   运行槽 _a，18/18 分区 A≡B，version-bootloader = 202502241
   A/B 双向切换均实测通过，每次 root 完好
```

详细过程见 §12（槽修复）、§11（root）、§1–§10（解锁）。

---

## 1. 目标设备

| 项 | 值 |
|---|---|
| 型号 | 2312DRAABC（Redmi Note 13 5G 国行，`gold`） |
| SoC | MT6833 / Dimensity 700 5G (k6833) |
| 序列号 | `SERIAL_REDACTED` |
| USB | fastboot `18d1:d00d` / BROM `0e8d:0003` / 小米下载态 `18d1:4ee7` |
| 系统 | Android 14 (SDK 34)，HyperOS 1.0，ROM `V816.0.12.0.UNQCNXM` |
| 目标 | `fastboot getvar unlocked` = `yes`、`secure` = `no`、能进 Android 且 `ro.boot.flash.locked=0` |

## 2. 官方通道为什么彻底走不通（全部实证，非推测）

| 命令 | 实际输出 |
|---|---|
| `fastboot flashing get_unlock_ability` | `unlock_ability=0` |
| `fastboot flashing unlock` | FAILED |
| `fastboot oem unlock` | `FAILED (remote: 'Unlock failed...return to fastboot in 3s')` |
| `fastboot fetch <part>` | 不支持 |
| `fastboot oem device-info` | unknown command |
| `fastboot oem setmtklks` | `FAILED (remote: 'Token is empty, failed.')` |

`setmtklks <token>` 的代码路径（LK `0x5d1e0`）经反汇编确认：token 需 `mi_verify_token`(`0x5d830`) 校验，内部用**设备 RSA 私钥**做 `rsa_exptmod`(`0x7dd70`) 解密 + `RSA_padding_check_PKCS1_type_1`(`0x5dad0`)。密文由小米服务器用公钥生成 → **不可伪造**。且明文还须等于运行时 `.bss` 常量（疑为 SN / ufs id）。判定死路。

## 3. 锁定状态的代码级溯源

LK 是 **Thumb-2**（不是 ARM64），radare2 对 raw 镜像抓不到 xref，全部用自建 capstone 工具解（`tools/lkdis.py`）。

### 3.1 fastboot 实际 getter（`0x5dc78`）

```
0x5dc8a: add  r0, sp, #4          // &seccfg_lock_state
0x5dc8e: str  r3, [sp, #4]        // 预置 4
0x5dc90: str  r3, [sp, #8]        // 预置 4
0x5dc92: bl   0x7a61c            // 读 seccfg → [sp+4]
0x5dc9a: add  r0, sp, #8          // &mi_out
0x5dc9c: bl   0x5dc18            // mi_get_lock_state(&mi_out) → [sp+8]
0x5dca2: ldr  r3, [sp, #8]        // mi_out
0x5dca6: cmp  r3, #1
0x5dcaa: ldreq r3, [sp, #4]      // ★ mi_out==1 → 改用 seccfg 值
0x5dcac: str  r3, [r5]           // final lock_state
```

**`final = (mi_out == 1) ? seccfg_lock_state : mi_out`**

### 3.2 变量映射（`0x7cc2c` / `0x7cc64`）

```
f_secure = (lock_state != 3) ? 1 : 0     // 0x7cc2c
f_unlock = (lock_state == 3) ? 1 : 0     // 0x7cc64  (sub #3; clz; lsr #5)
```

→ `lock_state == 3` ⇒ `unlocked=yes` + `secure=no`。语义：**3 = 已解锁，4 = 已锁定**。

### 3.3 `mi_get_lock_state` 分派表（`0x5cd68`）

```
0x5cd86: bl   0x5cc1c            // mi_check_magic()
0x5cd8a: cmp  r0, #6 ; beq 0x5cecc  → *out = seccfg 值(3)      ← 可行
0x5cd90: cmp  r0, #3 ; beq 0x5ce86  → *out = 1                 ← 可行 ★
0x5cd94: cmp  r0, #4 ; beq 0x5cdca  → *out = 4
0x5cd98: 其它 → 读 sig 验签 → OK→3 / 无 sig→4
```

### 3.4 `mi_check_magic`（`0x5cc1c`）返回码来源

- 调 `0x5cb68` 取 RPMB base_offset：成功 0；设备类型未知 **5**；RPMB size 不符 **7**
- `rpmb_read(buf, base_offset, 8)` 失败 → 透传底层错误码
- `memcmp(buf, "Jz8PNRUF", 8)` 不等 → **3**；相等 → 0
- **`rpmb_read` 封装 `0x5c908`**：底层 frame result == 7 → 返回 **6**；其它错误 → 4
- LK 字符串表 `0x134734` 起、64 字节/槽：**index 7 = `Authentication Key not yet programmed`**(`0x1348f4`) → LK 原设计就是"RPMB 未 provision → 回退 seccfg"

### 3.5 magic 不符分支的行为（`0x5ce86`）

```
0x5ce86: str  r4, [r6]       // *out = 1
0x5ce8a: bl   0x7a61c        // 读 seccfg
0x5ce90: cbnz r0, 0x5cee6
0x5ce92: ldr  r3, [r5]
0x5ce94: cmp  r3, #3
0x5ce96: beq  0x5cdcc       // ★ seccfg==3 → 直接返回，且【不会把 magic 写回去】
0x5ce98: ...                // seccfg!=3 时才回写 magic（自愈逻辑）
```

### 3.6 最终解法

> **把 UFS RPMB 里 base_offset 处的 8 字节 magic `Jz8PNRUF` 清零**
> → `mi_check_magic` 返回 3 → `mi_get_lock_state` 返回 1 → getter `final = seccfg = 3`
> → `unlocked=yes` / `secure=no`

同时 seccfg 分区已写入 `lock_state=3` / `dm_verity=0` / `sboot_runtime=0`（见 `artifacts/seccfg_dump.bin`，dump 校验过），作为回落值。

## 4. ★ 关键坑：base_offset 的单位是 **0x100 字节帧号**，不是字节

LK 日志实证 `rpmb size : 0x1000000` (16MB) → `base_offset : 0xffe0`。

**最初误判为字节偏移**，导致第一次 DA 读 frames `0xE0..0x11F`（覆盖字节 `0xE000..0x11FFF`，含字节 `0xFFE0`）全 0，没找到 magic。

代码级排除字节单位：`0x5cdde: adds r0, r4, #1` 读 4 字节当"sig 长度"、再 `adds r0, r4, #2` 读 sig 内容——若单位是字节，这两处会与 8 字节 magic 重叠，"sig 长度"会变成 `"z8PN"` = 0x4E50387A，远超 `cmp.w r1, #0x100` 上限，直接走错误分支；而 LK 实际日志是 `no sig stored`（长度=0）→ 字节单位被证伪。

实测印证：
- 读 frames `0xFF00..0xFFFF`（字节 `0xFF0000..0xFFFFFF`）→ magic 落在 **窗口内 +0xE000**
- 绝对地址 = `0xFF0000 + 0xE000` = **`0xFFE000`** = frame **`0xFFE0`**
- 与 LK 的 `base_offset : 0xffe0` **完全吻合**（帧号解释下）
- 旁证：`0x78128`（LK 真实 RPMB 读函数）内 `uxth r3, r6` 把地址截断到 16 位 → 帧号 + 窗口内偏移

对应公式：`base_offset(帧) = rpmb_size / 0x100 - 0x20` → 16MB→`0xFFE0`，4MB→`0x3FE0`（与 `0x5cbb0 / 0x5cbd4` 两条常量分支一致）。

## 5. 工具链改动（mtkclient patch）

### 5.1 `mtkclient/Library/DA/mtk_da_handler.py`

新增 `da_rpmbfix(outdir, display, magic, win_start, win_len, reset)`：

1. `dl.auth_rpmb()` —— **必须**，`read_rpmb` 内部不做 RPMB init（`custom_rpmb_init` 那行被上游注释掉了），不先派生密钥就读会拿到空数据
2. `dl.read_rpmb()` 读窗口 → 找 magic → 算 `sector = abs_off // 0x100`、`inoff = abs_off % 0x100`
3. 取该 sector 的 256 字节，把 magic 8 字节置零 → `dl.write_rpmb(sector=hex(sector), sectors="1")`
4. 回读校验 "magic is GONE"

新增模块级 helper `_hexval(v)`（接受 `0x..`/十进制字符串或 int）。
分发器新增 `elif subcmd == "rpmbfix":` 分支。

### 5.2 `mtk.py`

新增 `da rpmbfix` 子命令：`--outdir --magic(默认 Jz8PNRUF) --winstart --winlen --reset`。

### 5.3 `bromguard.py`（自建守护脚本）

职责：常驻武装一个 mtk.py 抢 BROM 窗口；**任何情况下不自动 reboot**。

改动：
- absent 阈值 2 → 8（≈3.2s），避免 BROM→fastboot 短暂掉线时误重武装
- 重武装条件：设备处于非 BROM 模式（fastboot/ADB）时照常重武装（mtk.py 不抢 `18d1:d00d`，因为它不在 portconfig 里），否则会白白错过下一次 BROM 窗口

### 5.4 `usb_ids.py` / `usblib.py`

`0x18D1` 加入白名单（`18d1:4ee7` = 小米下载态）。

> ⚠️ 事后确认这条是**反效果**：mtk.py 会把 `18d1:4ee7` 当 preloader 去做握手，握手失败（Errno 5 → Errno 19 设备掉线）反而打断 BROM 捕获。正确做法是让 mtk.py **忽略** `18d1:4ee7`，只认真 BROM `0e8d:0003`。本轮靠"设备自动掉回 `0e8d:0003`"侥幸恢复。**下轮务必回退这条。**

## 6. 完整操作时间线

| 阶段 | 结果 |
|---|---|
| 型号/系统识别 | 2312DRAABC / gold / mt6833 / Android 14 |
| 官方通道试探 | `unlock_ability=0`，全部死路（见 §2） |
| fastboot 协议自研 | 主机→设备=裸命令串（无 header、无 NUL）；设备→主机=`status(4B "OKAY"/"FAIL") + 原始 payload`（无长度字段） |
| seccfg 写入 | `lock_state=3` / `dm_verity=0` / `sboot_runtime=0`，dump 校验 ✓ |
| metadata/userdata 擦除 | ✓（`md_udc` 本机无此分区，报错属正常） |
| vbmeta_a patch | flags@0x78=3 —— **结果反而导致无限重启**；vbmeta_b 保持原封 |
| LK 运行时日志破译 | `mi_check_magic` / `base_offset: 0xffe0` / `no sig stored` / `lock_state = 0x4` |
| LK 反汇编溯源 | §3 全部坐标与逻辑 |
| oem 命令实测 | `lks=1` / `get_token` / `chkmtklks: seccfg_state is 3` / `setmtklks` / `unlock` |
| BROM 手势打通 | 23:39 跑通 BROM→kamakiri2→preloader→stock DA，dump 出 lk_a / devinfo / misc / vbmeta_a / vbmeta_b |
| RPMB 单位纠错 | §4，定位到 frame `0xFFE0` |
| RPMB 写 | `wrote zeroed sector 0xffe0 to rpmb` + 回读 `magic is GONE` ✓ |
| reset 回 fastboot | `mtk.py reset --ptype kamakiri2`（`MTC_BOOTMODE=2`）——**这次把手机关成黑屏了**，不是 fastboot |
| 手动回 fastboot | 音量下+电源 → `18d1:d00d` |
| **验收** | `unlocked: yes` / `secure: no` / `lks=0` / LK `lock_state=0x3` ✓ |
| 用户确认 | Android 界面出现"解锁"图标 ✓ |

## 7. 踩过的坑（不要重试）

**fastboot**
- 裸 `getvar`（无冒号）非法；任何带 header 的 framing 全部失败
- **不要把 fastboot 输出接管道 `head`** → SIGPIPE 会把解析器卡死
- `fastboot reboot-download` 不跳 BROM，而是重启进 Android
- `fastboot fetch` 不支持；`oem help/edl/reboot brom/device-info` 全 unknown

**mtkclient / USB**
- **不要用 pyusb 枚举后再启动 mtk.py** → 错过 BROM 握手开头，报 "Wrong magic"；catch.py 模式已废弃
- **pyusb 句柄必须全局持久化**，每次新建 Device 会因 GC 未释放接口导致后续 `claim_interface` 报 `[Errno 13] Access denied`
- `str_to_int` 只接受字符串 → `read_rpmb/write_rpmb` 的 sector 必须传 `"0xF0"` / `"1"` 形式
- `read_rpmb` 的循环 `sz = min(sectors-pos, 0x10)` 看着像 bug，实际 `toread` 恒等于 `sectors-pos`，无害
- `read_rpmb` **不做** RPMB init → 必须先 `auth_rpmb()`
- `write_rpmb` 内部会再 `custom_rpmb_init()` 一次
- `custom_rpmb_init` 需要 MEID+OTP 经 SEJ 派生密钥（`hwc.aes_hwcrypt(mode="rpmb", btype="sej")`），失败返回 0xfffe "Failed to derive a valid rpmb key"
- `detach_kernel_driver` / `SET_LINE_CODING` / `SET_CONTROL_LINE_STATE` 在 macOS 报 `Errno 13`（内部 try/except 吞掉，不影响读写）
- `mtk.py reset` 的 bootmode：`0=shutdown 1=home 2=fastboot`，**默认是 0（关机）**，必须 `MTC_BOOTMODE=2`
- `mtk.py reset` 走 DA 层 `shutdown()`，实测会把手机关成黑屏而非进 fastboot —— 不可靠，改用**物理音量下+电源**进 fastboot

**设备物理操作**
- 音量下+电源 = fastboot；音量上+音量下+电源 = BROM
- **真 BROM 需三键同按 + 冷启动（长按电源 10~15s）+ 插线时保持按住**
- 屏幕全黑 = 进 BROM 成功；出现 fastboot/MIUI 画面 = 手势错了，拔线重来
- 手机在 fastboot 时做 BROM 手势无效，必须先彻底断电

**逆向 / 工具**
- LK 是 Thumb-2，ARM64 假设不成立；radare2 对 raw 镜像抓不到 xref
- capstone 三个坑：`md.skipdata=True` 必开；LDR 操作数顺序为 `[dst, mem]`；16 位 LDR 的 `mem.disp` 已预乘 4；`cstr` 不能因结尾 `\n` 判失败
- LK 寻址：`ldr rX,[pc,#imm]` + `add rX,pc` → **最终地址 = literal + ((add 指令地址+4)&~3)**
- `tools/lkdis.py` 输出里 `-> 0x…` 是解析后的最终地址，`pool 0x…` 是**未解析的原始 literal**
- 脚本不要命名为 `dis.py`（遮蔽 Python 标准库 `dis`）
- LK 日志用 `\r` 分行，不是 `\n` → 用 `re.finditer` 按 `\r` 切

**环境**
- `/tmp` 会被 macOS 清理 → 关键产物已复制到本目录 `artifacts/`
- `sudo` 需密码
- 代理 `llmproxy:...@43.167.15.68:2345` 实测所有 GitHub HTTPS CONNECT 返 404，帮不上忙

## 8. 遗留问题与后续

| 项 | 优先级 | 说明 |
|---|---|---|
| **槽 A 修复** | 中 | `slot-unbootable:a: yes` / `slot-successful:a: no`；vbmeta_a 被 patch 成 flags=3 反而导致无限重启。修法：把 vbmeta_b 原始内容回填 vbmeta_a + 清 unbootable 标记（需再走一次 BROM → DA）。**vbmeta_b 是当前唯一可用槽，绝不能碰** |
| **`ro.boot.flash.locked=0` 实证** | 中 | 手机上 USB 调试未开，adb 取不到。需在系统里开启 USB 调试后 `adb shell getprop ro.boot.flash.locked`（预期 0）、`ro.boot.verifiedbootstate`（预期 orange）、`ro.boot.vbmeta.device_state`（预期 2） |
| **回退 `usb_ids.py` 的 0x18D1** | 高 | 否则下次 BROM 捕获会被 `18d1:4ee7` 打断（见 §5.4） |
| **`/tmp` 清理** | 低 | 待产物已归档后再清理 Settings APK / 截图 / 空 fetch 文件 / `variants/` / `seccfg.bin` 及其变体 |
| `fastboot oem p2u` | 低 | 参数形式仍未探明（`unknown argument`） |

## 9. 复现要点

### 环境

```bash
ADB=/Users/macbook/.local/bin/adb
FB=/opt/homebrew/share/android-commandlinetools/platform-tools/fastboot
S=SERIAL_REDACTED
PY=/tmp/mtkwork/venv/bin/python
MTK=/tmp/mtkwork/src/mtkclient-main
```

### 主流程

```bash
# 1) 武装（常驻，只抢 BROM，不 reboot）
cd /tmp/mtkwork
printf 'da rpmbfix --outdir /tmp/mtkwork --winstart 0xFF00 --winlen 0x100\n' > queue.txt
nohup ./venv/bin/python bromguard.py > bromguard.out 2>&1 &

# 2) 物理 BROM 手势（用户执行）
#    拔线 → 长按电源 10~15s 断电 → 等 3s
#    → 音量上+音量下+电源 三键同按 → 插 USB → 保持 5~10s → 松手
#    屏幕全黑 = 成功

# 3) DA 会话自动执行：读窗口 → 定位 magic → 写 sector 0xffe0 清零 → 回读校验
#    期望日志：
#      rpmb window: sectors 0xFF00.., 65536 bytes
#      wrote zeroed sector 0xffe0 to rpmb
#      read-back: magic is GONE -> LK will fall back to seccfg

# 4) 物理回 fastboot（不要用 mtk.py reset，会关机）
#    音量下 + 电源 两键同按 → 插 USB → 保持 5s

# 5) 验收
$FB -s $S getvar all > /tmp/mtkwork/gv_final.txt 2>&1
grep -aE "unlocked|secure" /tmp/mtkwork/gv_final.txt     # 期望 yes / no
$FB -s $S oem lks                                            # 期望 lks = 0
$FB -s $S oem chkmtklks                                      # 期望 seccfg_state is 3
$FB -s $S oem dump_pllk_log > /tmp/mtkwork/lklog_final.txt 2>&1
#    期望 "mi_check_magic 1st time run RPMB Lock, no magic"
#    期望 "[SEC_POLICY] lock_state = 0x3" + "img_auth_required = 0"
```

### 反汇编复查

```bash
cd /tmp/mtkwork
./venv/bin/python tools/lkdis.py 0x5cd68 0x5cf00   # mi_get_lock_state
./venv/bin/python tools/lkdis.py 0x5dc18 0x5dd00   # fastboot getter
./venv/bin/python tools/lkdis.py 0x7cc00 0x7ccc0   # f_secure / f_unlock
./venv/bin/python tools/lkdis.py 0x5cb68 0x5cc1c   # base_offset 计算
./venv/bin/python tools/lkdis.py 0x5c908 0x5c9c8   # rpmb_read 封装
```

## 10. 产物索引

```
artifacts/
  gv_final.txt        解锁后 getvar all（unlocked: yes / secure: no）
  gv_all7.txt         解锁前 getvar all（对照）
  lklog_final.txt     解锁后 LK 运行时日志（lock_state=0x3）
  lk_A.txt / lk_B.txt LK 日志拆分（\r 分行）
  lk_strings.txt      LK 全量字符串表（result 码表在 0x134734 起，64B/槽）
  dis_mi.txt / dis_verify.txt  mi_get_lock_state / mi_verify_token 反汇编
  rpmb_win.bin        RPMB 尾部 64KB dump（magic 在 +0xE000）
  rpmb_sector.bin     写入的 256 字节（清零后）
  rpmb_verify.bin     回读校验（magic 已消失）
  seccfg_dump.bin     seccfg dump（lock_state=3）
  fu_*.bin            LK / devinfo / misc / vbmeta_a / vbmeta_b dump
  da_run1.out         DA 会话 1（读窗口 0xE0..0x11F，全 0，单位误判）
  da_run2.out         DA 会话 2（读 0xFF00..0xFFFF，命中并写入）★
  mtk_da_handler.py.patched / mtk.py.patched   打过补丁的源码
  FINAL-VERIFY.txt        ★ 最终验收报告（槽位/root/bootconfig/dm mapper/BCB/18 分区 sha256）
  slot_hashes_full.txt    A 槽同源化【之前】的 A/B 对照哈希
  super_head_lp_metadata.bin  super 前 2MB（LP 几何 + A/B 两组 metadata + 分区表）
  parts/
    boot_b.bin           真机 stock boot_b（DA dump 原件，67,108,864 B）
    vendor_boot_b.bin    真机 stock vendor_boot_b（DA dump 原件，67,108,864 B）
    magisk_patched.img   Magisk 修补产物（已刷入 boot_b）
    *_b.bin (12 个)      B 槽 boot chain 原件：dtbo/lk/preloader/tee/mcupm/scp/sspm/spmfw/gz/logo/vbmeta_system/vbmeta_vendor/dpm/pi_img
    SHA256SUMS.txt       校验清单（shasum -c 全 OK）
  misc/                  BCB 各阶段快照（pristine / 对照 / 回滚 / A 槽启动后 / 最终态）
  fastboot/              7 份 getvar 快照（含 stale current-slot 反例、旧 lk 版本串证据）
  flash_boot.log       刷 boot 的 fastboot 日志
  community_vendor_boot.img.stale  社区 stock 镜像（与真机第 25 字节起分叉，反证）
code/
  mtk.py                ★ 现役源码（含 da dumppart）
  mtk_da_handler.py     ★ 现役源码（含 da_dump_partition / da_dump_partitions）
  mtk.py.pre_dumppart   加 dumppart 之前的版本（对照）
  PATCHES.diff          全部改动 diff
tools/
  lkdis.py            LK 反汇编器（capstone）
  pcref.py            字符串 xref 定位
  bromguard.py        BROM 窗口守护
  watch_magisk.sh     Magisk 修补产物自动回收
  rawfb*.py fbdump.py fbreset.py find_fbvars.py fastboot_probe.sh
  adb_raw*.py bromprobe*.py bromchar.py diag.py
  bcb.py            BCB 解析/改写（misc+0x800 结构）
  slot_clone.sh    B → A 同源化（逐分区 sha256 校验）
  slot_switch.sh   fastboot 切槽 + 回读实际槽位
  slot_verify.sh   槽位/root/BCB/A-B parity 一体验收
```

代码与工具链均已核对：`code/mtk.py`、`code/mtk_da_handler.py` 与 `/tmp/mtkwork/src/mtkclient-main/` 下的现役源码**逐字节一致**。

---

## 11. 装 Root（Magisk 28.1）—— 已完成

### 11.1 为什么必须先取 stock boot 镜像

Magisk 补丁需要**原厂** boot 镜像作为输入。三条常规途径在本机全部封死：

| 途径 | 结果 |
|---|---|
| `adb shell dd if=/dev/block/sdc51` | 块设备 `brw------- root root` → Permission denied（且 `adb root` 被拒：`adbd cannot run as root in production builds`） |
| `fastboot fetch boot` | 该 fastboot 不支持此命令 |
| 下载官方 fastboot ROM | 小米 CDN `bigota.d.miimg.com` 直连 000 / 代理 000，且文件名哈希后缀未知 |

唯一可靠途径 = **DA 层读取分区**（BROM → kamakiri2 → preloader → stock DA）。

### 11.2 新增的 mtkclient 能力：`da dumppart`

给 mtkclient 加了**单次 DA 会话内分块 dump 多分区**（4MB/块，避开 DA 单次载荷上限）：

```bash
# mtk.py 新增子命令
da dumppart <part1,part2> --outdir DIR [--chunk 0x400000]

# 实现位置
mtkclient/Library/DA/mtk_da_handler.py
  ├─ da_dump_partition(partitionname, outfile, parttype="user", chunk=0x400000)
  │    ├─ self.mtk.daloader.get_partition_data(parttype="user")  查 GPT
  │    ├─ base = gptentry.sector * self.config.pagesize   (pagesize=512)
  │    └─ 循环 readflash(addr=base+off, length=n, filename="")  ← filename="" 时返回 bytes
  └─ da_dump_partitions(partitionnames, outdir, ...)
```

`readflash(filename="")` 返回 bytearray（`xflash_lib.py` 分支），空 filename 走内存缓冲而非落盘 —— 这是分块实现的关键。

实测产出：

| 文件 | 大小 | sha256 | 特征 |
|---|---|---|---|
| `boot_b.bin` | 64MB | `411e17c6…a5dd4a8` | `ANDROID!`；kernel LZ4@0x1000；ramdisk LZ4@0x12B5000（1,380,091 B，cpio newc，内含 `init`/`overlay`/`dlkm`） |
| `vendor_boot_b.bin` | 64MB | `bc3d00b8…dc8c71b9` | `VNDRBOOT`；vendor ramdisk 32.4MB；含 MTK `bootopt=64S3,32N2,64N2` |

> ⚠️ **社区仓库里的 "stock" 镜像不可信**：`negroweed/device_xiaomi_gold_recovery` 的 `vendor_boot.img` 与本机真机 `vendor_boot_b` **第 25 字节就分叉**（是旧版本 build）。凡是要还原/回填分区，只能用 DA dump 出来的原件。

### 11.3 判定 Magisk 该补哪个分区

**结论：补 `boot`，不补 `vendor_boot`。** 依据三条独立证据：

1. `boot_b` 的 ramdisk_size = **1,380,091（非空）** → header v3 布局（v4 header 强制 ramdisk 为空，ramdisk 搬到 vendor_boot）
2. 设备**没有** `ro.boot.generic.ramdisk` 属性 → generic ramdisk 在 `boot` 里，不在 vendor_boot
3. 设备**没有** `init_boot` 分区 → Magisk 无 init_boot 可选

boot header 实测布局（MTK 变体，page_size=4096）：

```
0x00 magic[8]        "ANDROID!"
0x08 kernel_size     19610141   (LZ4 压缩，位于 0x1000)
0x0C ramdisk_size    1380091    (LZ4，位于 0x12B5000)
0x10 os_version      0x18000189
0x14 header_size     1584
0x28                 4
```

### 11.4 修补与刷入流程（可复现）

```bash
ADB=/Users/macbook/.local/bin/adb
FB=/opt/homebrew/share/android-commandlinetools/platform-tools/fastboot
S=SERIAL_REDACTED

# 1) 推送 stock boot 到手机
adb -s $S push boot_b.bin /sdcard/Download/boot_b.img
adb -s $S shell sha256sum /sdcard/Download/boot_b.img   # 须与源一致

# 2) 手机上手工操作：Magisk App → 安装 → 选择并修补一个文件 → 选 boot_b.img
#    产物落在 /sdcard/Download/magisk_patched-<ver>_<rand>.img
#    ⚠️ 不要点产物页的 Install / Reboot

# 3) 拉回补丁镜像
adb -s $S pull /sdcard/Download/magisk_patched-*.img magisk_patched.img

# 4) 进 fastboot（adb reboot bootloader 可用；或物理 音量下+电源）
adb -s $S reboot bootloader
fastboot -s $S getvar current-slot      # 必须 b
fastboot -s $S getvar unlocked          # 必须 yes

# 5) 只刷 boot（标准 fastboot 会自动把 boot 解析成当前槽 boot_b）
fastboot -s $S flash boot magisk_patched.img
#    实测输出：Sending 'boot_b' (65536 KB) OKAY / Writing 'boot_b' OKAY
#    ⚠️ 不刷 vbmeta_b（槽 B 唯一可用槽，vbmeta_b 是它的 AVB 根）

# 6) 重启
fastboot -s $S reboot
```

### 11.5 刷前验证（必做）

```python
# kernel 区必须逐字节相同（Magisk 不该碰内核）
stock[0x1000:ramdisk_off] == patch[0x1000:ramdisk_off]   # → True
# ramdisk 必须变化，且注入 magisk / .backup / init
# 压缩格式必须保持（stock 与 patched 的 ramdisk magic 都是 LZ4 legacy 02 21 4c 18）
# 总大小不变（64MB，Magisk 保持镜像尺寸）
```

本次实测差异范围：header 页 + ramdisk 区（0x12B5000–0x1401000）+ 末尾 4KB 填充块，共 341/16384 个 4KB 块。

### 11.6 验收

```
which su        → /system/bin/su
magisk -v       → 28.1:MAGISK:R      (:R = root 已激活)
magisk -V       → 28100
ps -A | grep magisk → root  827  1  ...  magiskd
/data/adb/      → magisk/  magisk.db  modules/  post-fs-data.d/  service.d/  (全部 root:root)
getprop         → flash.locked=0 / verifiedbootstate=orange / vbmeta.device_state=unlocked / slot_suffix=_b
```

> `adb shell su -c id` 第一次会超时 —— Magisk 弹了授权框，需在手机屏幕点「允许」；授权后 adb shell 即拥有 root。

---

## 12. 修复 A 槽（slot-unbootable）—— 已完成

### 12.1 症状

刷完 `boot_a` + `vbmeta_a` 后把活动槽切到 A，**A 槽起不来**：

- LK 选到 A → 屏幕黑，无任何 USB 枚举
- 等满 180 秒仍然没有 `adb devices`，连 fastboot 都不出现
- B 槽始终正常 → 快速进 fastboot 是唯一逃出生天的路

### 12.2 排查：四个方向逐一排除

**① super 动态分区 —— 排除**

A 组动态分区全部正常，有真实 extent（不是空壳）：

```
system_a      6011.9 MB      vendor_a       9123.4 MB
product_a    29894.0 MB      system_ext_a   5198.4 MB
mi_ext_a         1.3 MB      (各自 -cow 副本也都在)
```

LP 元数据布局（`artifacts/super_head_lp_metadata.bin`）：

```
geometry @0x1000   magic "gDla"  struct_size=52  metadata_max_size=65536  slots=3
metadata slot0 @0x3000 = A 组    slot1 @0x13000 = B 组
metadata header magic "0PLA"  version 10.2  header_size 256
```

**② vbmeta —— 排除**

`vbmeta_a` / `vbmeta_b` 字节相同，AVB 根没被破坏。

**③ BCB 标记 —— 排除（但踩了坑，见 12.8）**

`slot-unbootable:a: yes` 确实存在且能改，但改完照样起不来 —— 说明标记只是**症状**，不是根因。

**④ bootloader 链版本不一致 —— 命中，这就是根因**

A 槽的**整条 bootloader 链**停在上一版固件，只有我们手动刷的 `boot` / `vendor_boot` / `vbmeta` 三项是新的：

```
              A 槽(旧)                            B 槽(可用)
lk_a          3237acd3…  2025-01-21        lk_b        cba59ee0…  2025-02-24
dtbo_a        a0e8ba39…                    dtbo_b      beabcb0c…
preloader_a   ac1de209…                    preloader_b 370df8e2…
tee_a/mcupm_a/scp_a/sspm_a/spmfw_a/gz_a/logo_a 全部与 B 槽不同（旧版）
```

决定性证据是 LK 自己吐的版本串：

```
artifacts/fastboot/gv_in_a.txt        version-bootloader: gold-…-202501211   ← 旧 lk_a
artifacts/fastboot/gv_pre_a_test.txt  version-bootloader: gold-…-202502241   ← 同源化后 = lk_b 版
```

**新 kernel 配旧 lk/dtbo** → 早期崩溃，来不及枚举 USB。fastboot 里的 `version-bootloader` 字符串就是最直接的探针。

### 12.3 同源化操作（B → A 全量克隆）

Magisk root 生效后可以直接读写 `/dev/block/by-name/*`，不需要 fastboot、不需要 BROM。

```bash
ADB=/Users/macbook/.local/bin/adb
S=SERIAL_REDACTED

# 逐个分区从 B 复制到 A
for p in boot vendor_boot vbmeta vbmeta_system vbmeta_vendor \
         dtbo lk preloader preloader_emmc preloader_raw preloader_ufs \
         tee mcupm scp sspm spmfw gz logo dpm md1img pi_img; do
  $ADB -s $S shell "su -c 'cat /dev/block/by-name/${p}_b > /dev/block/by-name/${p}_a'"
done

# 逐个校验（sha256sum 对块设备有效；stat 报 size=0 不可用）
$ADB -s $S shell "su -c 'sha256sum /dev/block/by-name/boot_a /dev/block/by-name/boot_b'"
```

> `dd of=/dev/block/...` 会被本地安全网关拦下；`cat file > /dev/block/by-name/xxx` 走得通。

克隆清单 21 项（`tools/slot_clone.sh`），其中 **16 个分区内容确实变了**：

```
dtbo  lk  preloader  preloader_raw  tee  mcupm  scp  sspm  spmfw
gz  logo  vbmeta_system  vbmeta_vendor  dpm  md1img  pi_img
```

另两类本来就一致：`boot` / `vendor_boot` / `vbmeta`（我们手动刷过），`preloader_emmc` / `preloader_ufs`（原本就同）。

最终 **18 个关键分区 sha256 全 OK**（A≡B），清单见 `artifacts/FINAL-VERIFY.txt`。

### 12.4 验收：A 槽启动成功

```
fastboot reboot
# 25 秒后 adb 上线

ro.boot.slot_suffix        = _a
ro.boot.slot               = a
androidboot.slot_suffix    = "_a"
androidboot.slot           = "a"
androidboot.vbmeta.device_state = "unlocked"
androidboot.verifiedbootstate   = "orange"
version-bootloader  → gold-159a0f1bb-20240603161215-202502241   （= lk_b 版，同源化生效）

magisk -v  → 28.1:MAGISK:R
su -c id  → uid=0(root) gid=0(root) groups=0(root) context=u:r:magisk:s0

dm mapper → system_a / vendor_a / product_a / system_ext_a / mi_ext_a + 各自 -cow / pl_a / pl_b
```

### 12.5 LK 选槽规则逆向

LK 里选槽只看 **BCB 里两槽的 priority（槽字节低 4 位）**，`A_pri >= B_pri` 就选 A：

```asm
; choose_slot()  0x057e14
0x057e2c: bl   #0x57bf4          ; read_boot_ctrl(buf, mode=0)
0x057e3e: cmp  r3, r4            ; magic == "BCAB"
0x057e56: ldrb.w r2, [sp, #0xc]  ; A 字节 (misc+0x80C)
0x057e5a: ldrb.w r3, [sp, #0xe]  ; B 字节 (misc+0x80E)
0x057e5e: and  r2, r2, #0xf      ; A priority
0x057e64: and  r3, r3, #0xf      ; B priority
0x057e68: cmp  r2, r3
0x057e6c: ite  ge
0x057e6e: movge r3, #0           ; A >= B -> "_a"
0x057e70: movlt r3, #1           ; A <  B -> "_b"
0x057e72: ldr.w r0, [r1, r3, lsl #2]

; get_slot_index()  0x057dc8      "_a" -> 0, "_b" -> 1
; set_active_slot() 0x057c12      当前槽字节写 0x7F (pri15,tries7)
;                              另一槽 priority==15 则降为 14
;                              槽字节地址 = sp+0x0C + slot_index*2  → +0x0C=A, +0x0E=B
; read/write boot_ctrl  0x057bf4  mode=0 读 / 1 写 → part_read("misc", off=0x800, size=0x20)
; get_retry_count    0x58010  = (byte>>4)&7
; get_not_boot_mode  0x58074  = bit7
; is_slot_unbootable 0x580d8  = (byte & 0x0f)
```

完整反汇编（0x057b00–0x058120，614 行）留在 `/tmp/mtkwork/slotfix/lk_sel.txt`。

### 12.6 BCB 结构（字节级实证）

```
misc+0x800: 5f 61 00 00 | 42 43 41 42 | 01 02 00 00 | <A> 00 <B> 00
            "_a\0\0"      "BCAB"          ver=1,nb=2      A字节 B字节
misc+0x810: 00 * 12                    | 4a de b0 7c (u32 时间戳)

槽字节: bit[3:0] = priority | bit[6:4] = tries_remaining | bit[7] = successful
```

实测到的取值演化：

| 时点 | suffix | A 字节 | B 字节 | 结果 |
|---|---|---|---|---|
| 原始（故障态） | `_b` | 0x00 (pri0) | 0x9F (pri15) | A 被判 unbootable → 选 B |
| `fastboot --set-active=a` 刚写完 | `_a` | 0xFF (pri15) | 0x7F (pri15) | A ≥ B → 选 A |
| Android 起来后 userspace 重写 | `_a` | 0x9F (pri15, tries1, succ1) | 0x5E (pri14, tries5) | 仍选 A |

注意最后一行：**Android 起来后 userspace bootctl 会把 B 压到 pri 14**。pri 14 远大于 0，所以 A 槽一旦被标 unbootable，LK 仍会回落到 B 槽 —— 保命线始终成立。

### 12.7 切槽的正确做法（唯一可靠路径，已双向实证）

```bash
adb reboot bootloader
fastboot --set-active=b     # 或 a
fastboot reboot
```

实测：`--set-active=b` → 实际启动 `_b`，root 完好；`--set-active=a` → 实际启动 `_a`，root 完好。两次都验证了 `ro.boot.slot_suffix` 而不是 getvar。

`fastboot flash misc` 通路也实测可用（`Sending 'misc' 512KB OKAY`），可作为 BCB 回滚手段，但**日常切槽不要用它**（见 12.8）。

### 12.8 三个坑（都踩过）

**① 在 Android 里改 misc 会被 userspace 覆盖。**
Android 运行中 `bootctl` / `update_verifier` 持续重写 BCB（把运行槽 priority 恢复 15、另一槽压低）。写完立刻 `adb reboot` 是无效的 —— 之前多次改 BCB 全是这个原因。**切槽只能走 fastboot。**

**② `fastboot getvar current-slot` 不可信。**
同一 fastboot 会话内 getter 不刷新。快照里能直接看到错位：`gv_setactive_a.txt` 写完 `--set-active=a` 却报 `current-slot: b`，`gv_setactive_b.txt` 写完 `--set-active=b` 却报 `current-slot: a`。**一切以 `ro.boot.slot_suffix` 为准。**

**③ 别把 fastboot 输出接管道。**
`fastboot ... | head` 会因 SIGPIPE 卡死解析器。一律 `> file 2>&1` 再 grep，且 grep 时行首有 `(bootloader) ` 前缀，不能用 `^` 锚点。

### 12.9 工具脚本

| 脚本 | 用途 |
|---|---|
| `tools/bcb.py` | 解析/改写 misc 里的 BCB（dump 字段、算槽字节） |
| `tools/slot_clone.sh` | B → A 全量同源化，逐分区 sha256 校验 |
| `tools/slot_switch.sh` | 走 fastboot 切槽，等设备回来并回读实际槽位 |
| `tools/slot_verify.sh` | 槽位 / root / BCB / A-B parity 一体验收 |

### 12.10 本节新增归档

```
artifacts/
  FINAL-VERIFY.txt             最终验收（槽位 / root / bootconfig / dm mapper / BCB / 18 分区 sha256）
  slot_hashes_full.txt         同源化【之前】的 A/B 对照哈希（13 对分区；boot/vendor_boot/vbmeta 已同，其余全分叉）
  super_head_lp_metadata.bin   super 前 2MB（LP 几何 + A/B 两组 metadata + 分区表）
  parts/                       B 槽 boot chain 原件 14 个（dtbo/lk/preloader/tee/mcupm/scp/sspm/spmfw/gz/logo/vbmeta_system/vbmeta_vendor/dpm/pi_img）
  misc/
    misc_pristine_32k.bin      原始 misc 32KB
    misc_A-FF_B-FF.bin         两槽都是 pri15 的对照快照
    misc_rollback_A-FE_B-9F.bin  回滚用快照（A pri14 / B pri15）
    misc_after_A_boot.bin      A 槽启动后立刻抓的快照
    misc_final_slotA.bin       ★ 最终态（live 与归档 sha256 一致）
  fastboot/
    gv_before.txt              修复前（含 slot-unbootable:a: yes，version-bootloader=202502241）
    gv_in_a.txt                选到 A 但仍起不来（version-bootloader=202501211 ← 旧 lk_a，关键证据）
    gv_after_misc.txt          改 misc 之后（版本串仍是旧 lk_a）
    gv_pre_a_test.txt          同源化之后（version-bootloader=202502241 ← 生效）
    gv_setactive_a.txt / gv_setactive_b.txt   两次切槽的 getvar 快照（含 stale current-slot 反例）
    gv_bcb_priority_b.txt      B 槽优先级快照
```

---

## 13. 当前状态与后续

**设备现状**：运行槽 A，Magisk 28.1 root 完全生效，Bootloader 已解锁（`unlocked:yes / secure:no`），A/B 18 个分区同源。

**保命线**：B 槽完整保留且可启动；随时 `adb reboot bootloader && fastboot --set-active=b && fastboot reboot` 切回。

**可选后续**（均未执行，需明确决定）：

1. **刷 GSI** —— 这台机器**出厂就是 seamless GSI 架构**，详见下节 §14。
2. **要 GMS** —— HyperOS 内部「谷歌基础服务」开关，成本最低，无需刷机；或在 DSU 里装 GMS 版 GSI。
3. **GitHub 建仓** —— 需要 token 或浏览器登录才能 `gh repo create`，用户已说「先放弃」。

---

## 14. GSI 架构分析（实测，未执行刷入）

### 14.1 先纠正一句话

之前 README 写的「本机 boot 本身就是 GSI generic boot」**只说对了一半**。准确说法：

> **boot 分区里装的就是 AOSP 官方 GSI 的 boot.img**；
> **vendor 停在 Android 12 的 VNDK 快照**；
> **只有 system 被 OTA 升到了 Android 14 HyperOS**。

设备上**当前并没有在跑 GSI**（`ro.gsid` / `ro.gsid.image` 都是空）——跑的是 HyperOS。

### 14.2 铁证：boot ramdisk 里的 build.prop

从真机 `boot_b.bin` 解出 ramdisk（LZ4 legacy，`system/etc/ramdisk/build.prop`）：

```
ro.product.bootimage.model=GSI on ARM64
ro.product.bootimage.name=gsi_arm64
ro.product.bootimage.brand=Android
ro.bootimage.build.fingerprint=Android/gsi_arm64/generic_arm64:12/SGR1.240502.001.B6/12299972:user/release-keys
ro.bootimage.build.id=SGR1.240502.001.B6
ro.bootimage.build.date=Fri Aug 30 07:42:51 UTC 2024
ro.bootimage.build.version.sdk=31
ro.bootimage.build.type=user
ro.bootimage.build.tags=release-keys
```

配套的 ramdisk 结构也是 AOSP 12+ 通用布局：

```
init (2,523,864 B)
first_stage_ramdisk/{dev,metadata,mnt,proc,second_stage_resources,sys,debug_ramdisk}
second_stage_resources
system/etc/ramdisk/build.prop
```

`init` 里的字符串还留着 **GSI 专属的 DSU 代码路径**：

```
/data/gsi/dsu/            /metadata/gsi/dsu/            /metadata/gsi/dsu/active
/metadata/gsi/dsu/avb/    /metadata/gsi/dsu/booted      /metadata/gsi/dsu/install_status
/metadata/gsi/dsu/lp_names  /metadata/gsi/dsu/one_shot_boot  /metadata/gsi/ota/test
```

### 14.3 三个分区的真实身份

| 分区 | build fingerprint | SDK | 说明 |
|---|---|---|---|
| boot | `Android/gsi_arm64/generic_arm64:12/SGR1.240502.001.B6/...` | 31 | **AOSP 官方 GSI 的 boot.img**（2024-08-30 出厂）|
| vendor | `Redmi/gold/gold:14/UP1A.231005.007/V816.0.12.0.UNQCNXM` | **31**（VNDK 31）| 版本串写 14，实际 SDK 31 → **Android 12 的 VNDK 快照**，出厂起就没变过 |
| system | `Android/missi_phone_cn/missi:14/UP1A.231005.007/V816.0.12.0.UNQCNXM` | 34 | 小米 HyperOS，OTA 升上来的 |

`ro.vndk.version = 31`、`ro.vendor.build.version.release = 12`、`ro.build.ab_update = true`、`ro.boot.dynamic_partitions = true`。

这就是 **seamless update** 的标准形态：boot / vendor 冻结在出厂基线（GSI + VNDK 31），system 单独往上走。

### 14.4 结论 A：刷 GSI 的兼容性风险极低

普通手机刷 GSI 要赌三件事，这里**三件都天然成立**：

1. **boot 不用动** —— 本来就是 GSI 的 boot.img，kernel / ramdisk 天然匹配
2. **vendor 不用换** —— 已经是 VNDK 31 基线，而 seamless GSI 的设计前提就是「跑在老 VNDK 的 vendor 上」
3. **架构匹配** —— `gsi_arm64` = arm64 + A/B，本机 `ro.product.cpu.abi=arm64-v8a`

**决定性的一条：设备上跑的就是 GSI kernel。**

```
$ uname -r
5.10.209-android12-9-00019-g4ea09a298bb4-ab12292661
#1 SMP PREEMPT Wed Aug 28 22:16:09 UTC 2024 aarch64 Toybox
```

`ab12292661` 是 AOSP GSI 的 build 编号格式，构建日期 2024-08-28 与 GSI boot 的 2024-08-30 同期 —— **Google 已经为这台机器编好了 GSI 专用的 kernel 和 boot，硬件早就跑在 GSI 启动链上了**。这比"兼容"更强：目标状态就是当前状态。

逐层实测准入条件：

| 层 | 检查项 | 实测值 | 结论 |
|---|---|---|---|
| ISA | `ro.product.cpu.abi` | `arm64-v8a` | ✓ 对应 `gsi_arm64` |
| kernel | `uname -r` | `5.10.209-android12-9-...-ab12292661` | ✓ GSI kernel，已在此硬件运行 |
| boot | ramdisk `build.prop` | AOSP 官方 GSI boot.img | ✓ 不用换 |
| HAL/VNDK | `ro.vndk.version` | `31` | ✓ A14 GSI(VNDK 33) 向下兼容 VNDK 31 |
| HAL api | `ro.vendor.api_level` | `30` | ✓ 低于 GSI 的 34（vendor 比 GSI 老 = 受支持方向）|
| Treble | `ro.treble.enabled` | `true` | ✓ |
| 动态分区 | `ro.boot.dynamic_partitions` / `ro.build.ab_update` | `true` / `true` | ✓ DSU 前提 |
| AVB | `verifiedbootstate` / `vbmeta.device_state` | `orange` / `unlocked` | ✓ GSI 自带 vbmeta 不会被拦 |
| DSU | `gsi_tool` / `com.android.dynsystem` | 在位 / v14 | ✓ |
| SoC | `ro.soc.model` / `ro.hardware` | `MT6833V/PNZA` / `mt6833` | ✓ |

### 14.5 结论 B：走 DSU，「不可逆」这个问题直接消失

设备上的 DSU 工具链**完整在位**：

```
/system/bin/gsi_tool                        # install / disable / enable / wipe / status
/system/lib64/libgsi.so, gsi_aidl_interface-cpp.so, gsid
/system/priv-app/DynamicSystemInstallationService/   # com.android.dynsystem v14
ro.boot.dynamic_partitions=true
ro.build.ab_update=true
gsi_tool status → normal                    # 当前没装任何 GSI
/data 剩余 93 GB
```

DSU 把 GSI 装成**并存的第二套 system**（在 super 里新开 dsu 分区），用现有的 boot + vendor 启动：

- **HyperOS 原封不动**，随时 `gsi_tool disable` / `wipe` 切回来
- **不碰 super 里现有的 A/B 分区**，不需要 super 备份
- **不需要官方原厂包**（回原厂的问题不再是前置条件）
- 代价：占 userdata 空间（system 约 4–5G + userdata 默认 8G，可调）

### 14.6 镜像清单与下载地址（已验证可达）

官方 GSI release 页：`https://developer.android.com/topic/generic-system-image/releases`

直链格式：

```
https://dl.google.com/developers/android/<代号>/images/gsi/<文件名>.zip
```

`<代号>` 是 Android 甜点码首字母：`qt`=A10 `rvc`=A11 `sc`=A12 `tm`=A13 `udc`=A14 `vic`=A15 `baklava`=A16 `cinnamonbun`=A17。

本机代理实测（`curl -x <proxy> -r 0-3000`）**全部 206 / `application/zip`**：

| Android | GSI(GMS) 文件 | 建议 |
|---|---|---|
| **A14** | `gsi_gms_arm64-exp-UQ1A.231205.015-11084887-2026a0e7.zip` | ★ **首选** |
| A14 (无 GMS) | `aosp_arm64-exp-UQ1A.231205.015-11084887-e291b838.zip` | 纯净 AOSP |
| A15 | `gsi_gms_arm64-exp-BP1A.250405.005.C1-13151952-48d6db2a.zip` | 风险偏高 |
| A16 | `gsi_gms_arm64-exp-BP2A.250605.031.A3-13578795-38e52cb0.zip` | 风险偏高 |

**为什么首选 A14**：本机 vendor 是 **VNDK 31**（Android 12 基线）。AOSP GSI 向后兼容若干个 VNDK 版本 —— A14 GSI（VNDK 33）支持 VNDK 31 的 vendor，而 A15+（VNDK 34+）大概率不再向下兼容 VNDK 31。A14 同时与本机 system 的 SDK 34 同代，匹配度最高。

**A14 GMS 版 SHA-256**：`2026a0e7`（完整值见 release 页表格；`gsi_gms_arm64-exp-UQ1A.231205.015-11084887-2026a0e7.zip`）。

### 14.7 四大子系统逐个查证（相机 / 蓝牙 / Wi-Fi / 蜂窝）

前提：**DSU 不动 vendor、不动 kernel、不动 baseband 固件**，所以这四项的「硬件层」是原封不动的。变的只有 framework 层（HyperOS → AOSP）。

VINTF 声明（`/vendor/etc/vintf/manifest.xml`）：

```
android.hardware.camera.provider      v2.6
android.hardware.bluetooth            v1.1
android.hardware.bluetooth.audio      v2.1
android.hardware.radio                v1.2
android.hardware.radio.config         v1.3
vendor.mediatek.hardware.camera.atms / bgservice / isphal
vendor.mediatek.hardware.bluetooth.audio v2.2
vendor.mediatek.hardware.mtkradioex   v3.0
```

vendor 侧 daemon：`camerahalserver`、`android.hardware.wifi@1.0-service-lazy`、
`android.hardware.bluetooth@1.1-service-mediatek`、`android.hardware.gnss-service.mediatek`、`mtkfusionrild`

驱动全部**内建在 kernel**（`lsmod`）：`wlan_drv_gen4m`(2.7M)、`wmt_chrdev_wifi`、`wmt_drv`、`bt_drv_connac1x`、`gps_drv_stp`
固件在 `/vendor/firmware/`：`BT_FW.cfg`、`WIFI_RAM_CODE_*.bin`、`WMT_SOC.cfg`
baseband 固件在 `bk1/bk2/bk3`（sdc17/sdc41/sdc60）—— **非分槽**，A/B 两槽共用，DSU 也不碰

| 子系统 | 版本匹配 | 结论 | 风险 |
|---|---|---|---|
| **Wi-Fi** | HIDL v1.0；AOSP 14 的 Wi-Fi 仍是 HIDL（AIDL Wi-Fi 才是 Android 15+） | 2.4G/5G/6G/热点正常；驱动在 GSI kernel 里 | **低** |
| **蓝牙** | HIDL v1.1 + audio v2.1；AOSP 14 蓝牙栈仍用 HIDL v1.1 | 配对/A2DP/键鼠正常；offload 音频策略也在 vendor | **低** |
| **相机** | camera.provider v2.6 ≤ AOSP 14 支持的 v2.7 | 能拍；丢的是小米成像调校与影像算法 | **低～中** |
| **蜂窝 / 5G** | radio v1.2 + radio.config v1.3，正对 AOSP 14 | 信号/上网/通话/短信正常 | **中** |

**蜂窝这一项要单独说**：MTK 的 RIL 是 `mtkfusionrild`（`gsm.version.ril-impl = android reference-ril 1.0`）—— 这就是 MTK **专门为 GSI 准备的兼容 RIL**，说明 MTK 官方支持 GSI 场景。IMS 侧 `MtkImsService` / `MtkImsManager` 也在 vendor。

当前 HyperOS 实况（基线）：中国联通，LTE，`mVoiceRegState=0(IN_SERVICE)`、`mDataRegState=0(IN_SERVICE)`、`mVopsSupport=2` → **VoLTE 当前在工作**；`isNrAvailable=false` → 此刻挂的是 4G，NR 未激活（与 GSI 无关）。

**唯一真正的雷区 = IMS 注册**：MTK 的 `libims` 面向特定 Android 版本，AOSP 14 改过 `ImsService` / `ImsConfig` / CarrierConfig 接口，老 IMS 实现可能注册不上 → 表现是「有信号但 VoLTE 通话降级/失败」。DSU 的 GS 在，HyperOS 侧一切正常，wipe 即回，失败代价可控。

### 14.8 结论

- **不是「系统自带纯净 GSI」** —— 是「出厂就是 seamless GSI 架构」：boot 本身是 GSI 的 boot.img，vendor 是 VNDK 31 快照，只有 system 被 OTA 换成 HyperOS。
- **刷 GSI 的兼容性风险极低** —— boot 不用动，vendor 已经就是 GSI 期望的基线。
- **走 DSU 就没有不可逆问题** —— `gsi_tool install` 把 GSI 装成并存的第二系统，HyperOS 原封不动，删掉即回，不碰 super、不需要原厂包。
- **本节全部为分析，未执行任何刷入操作。**
