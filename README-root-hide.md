# Root 隐藏 / 反检测配置手册

设备：Redmi Note 13 5G 国行（2312DRAABC / gold / MT6833 / Android 14 / HyperOS V816.0.12.0.UNQCNXM）
Magisk 28.1 (28100)，A 槽，bootloader 已解锁，root 有效。

---

## 1. 能防什么、不能防什么（先看这个）

| 检测类型 | 手段 | 本机可行性 |
|---|---|---|
| App 自己扫 su / magisk 文件 / `/proc/mounts` 残留 | Zygisk + DenyList | ✅ 能挡（本机已配） |
| App 读 `ro.build.type` / `ro.debuggable` / `ro.build.tags` | 系统属性 | ✅ 本来就干净（`user` / `0` / `release-keys`） |
| App 检测 Zygisk 框架本身存在 | Shamiko 模块 | ⚠️ 可选，需装第三方模块 |
| Google **Play Integrity basic / device** | Play Integrity Fix (PIF) 模块 | ⚠️ 可选，spoof 设备指纹 |
| Google **Play Integrity strong** | 硬件 key attestation | ❌ **无解**，bootloader 已解锁，信任链在硬件层断了 |
| Netflix / DRM L1 | Widevine 硬件级 | ❌ 同上，只能 L3 / 720p |

> strong integrity 与 Widevine L1 是**同一个根因**：解锁 bootloader 破坏了硬件级信任。
> 软件层任何隐藏都绕不过硬件 attestation。

## 2. 当前已配置（2026-10-21 14:31 修正后写入，待重启生效）

> ⚠️ **开关位置在数据库，不在文件。**
> Magisk 24+ 把 Zygisk / Enforce DenyList 开关放进 `magisk.db` 的 `settings` 表。
> 写 `/data/adb/magisk/zygisk` / `/data/adb/magisk/denylist` 文件是 **MagiskHide 时代的老机制，Magisk 28 根本不读**
> （2026-10-21 第一次踩过，重启后 `settings.zygisk` 仍是 0，白重启一次）。

```bash
magisk --sqlite "INSERT OR REPLACE INTO settings (key,value) VALUES ('zygisk',1)"
magisk --sqlite "INSERT OR REPLACE INTO settings (key,value) VALUES ('denylist',1)"
magisk --sqlite "INSERT OR REPLACE INTO settings (key,value) VALUES ('enforce_denylist',1)"

# 校验（必须看到 zygisk=1 denylist=1）
magisk --sqlite "SELECT key,value FROM settings"
```

**目标列表在另一张表**（`denylist` 表，package_name + process），持久化，41 个包：

```bash
magisk --sqlite "SELECT count(*) FROM denylist"          # → 43 条（41 包 + 2 条 process 变体）
magisk --sqlite "SELECT package_name FROM denylist"
```

> ⚠️ **第二条坑（更要命）：条目必须用官方 CLI 注册，不能直接写 db。**
> `magiskd` 靠 **uid 映射表**决定对哪些进程隐藏。直接 `INSERT INTO denylist`
> 只是写进了 db，**magiskd 没有对应的 uid 记录 → 完全不生效**（2026-10-21 第一次重启白费的原因）。
> 必须走 `magisk --denylist add <pkg>`，由 magiskd 当场解析包名→uid 并写进内存。
> 好处：`add` 是**运行时立即生效**的，被 deny 的 App 只要重启进程就生效，不用重启手机。

```bash
magisk --denylist add <pkg>      # 插入两条：(PKG,"") 和 (PKG,PKG)
                                  # 后者=该包所有子进程（多进程 App 也能藏）
magisk --denylist rm  <pkg>
magisk --denylist ls             # 当前列表
magisk --denylist status         # → "Denylist is enforced"
magisk --denylist exec <cmd>     # 在隔离 mount ns 里跑命令并做全部 unmount（自测用）
```

**DenyList 已加入的 41 个第三方 App**（全量），**排除 3 个**：

| 排除 | 原因 |
|---|---|
| `com.topjohnwu.magisk` | Magisk 自身 |
| `com.termux` | 需要 root 跑命令 |
| `com.v2ray.ang` | 需要 root 跑 TUN（排除后代理不���受影响） |

> 注：DenyList 是**白名单式**——只有**被勾选**的 App 看不到 root。
> 所以必须逐个加入；未加入的 App 仍能发现 su。

## 3. 重启（必须手动执行）

脚本**永远不会自动 reboot**。手动重启后 Zygisk 与 DenyList 才生效。

```bash
# 由用户手动执行，或在手机上直接重启
adb -s SERIAL_REDACTED reboot
```

## 4. 重启后验证

```bash
ADB=/Users/macbook/.local/bin/adb; S=SERIAL_REDACTED

# ① 开关真的开了（关键：看 settings 表，不是文件）
$ADB -s $S shell "su -c 'magisk --sqlite \"SELECT key,value FROM settings\"'"
#   期望：zygisk=1 / denylist=1 / enforce_denylist=1

# ② Zygisk 注入痕迹（最硬的判据）
$ADB -s $S shell "su -c 'cat /proc/\$(pidof zygote64)/maps | grep libzygisk'"
#   期望出现 /system/lib64/libzygisk.so
#   补充：全局 mount 里应有 "magisk on /system/lib64/libzygisk.so type tmpfs"

# ③ DenyList 状态
$ADB -s $S shell "su -c 'magisk --denylist status'"     # → Denylist is enforced
$ADB -s $S shell "su -c 'magisk --denylist ls'"         # → 43 条

# ④ 【决定性】某个被 deny 的 App 进程内是否还看得到 su
$ADB -s $S shell "su -c 'ls /proc/<pid>/root/system/bin/ | grep -cE \"^(su|magisk)$\"'"
#   被 deny 的 App → 0（看不到 root）
#   没被 deny 的 App → 2（能看到 root）
#   注意：进程必须是在 add 之后启动的，老进程不生效

# ⑤ root 仍可用（排除名单没被误伤）
$ADB -s $S shell "su -c id"

# ⑥ Magisk App 里的显示：设置 → Zygisk = 开，排除列表 = 开且列表有内容
```

**App 侧自查**：装个 root 检测类 App（如「Magisk Hide」/「RootBeer」），在 DenyList 内的 App 里应显示无 root。

## 5. 回滚 / 救砖（Zygisk 万一导致 bootloop）

Zygisk 在 Android 14 上 bootloop 概率极低，但保险先备好。

### 5.1 先试软恢复
- **安全模式**：开机时连续按 7 次电源键 → Magisk 禁用所有第三方模块（Zygisk 不是模块，可能仍会起）
- 强制重启后进 `fastboot`：`adb reboot bootloader`

### 5.2 fastboot 刷回可启动的 boot 镜像
```bash
FB=/opt/homebrew/share/android-commandlinetools/platform-tools/fastboot
A=/Users/macbook/.minimax/workspace/redmi-note13-unlock/artifacts

$FB flash boot $A/parts/magisk_patched.img   # 64MB，Magisk 已 patch 的 boot，能开机
$FB reboot
```
> `magisk_patched.img` 是**开启 Zygisk 之前**的版本，刷回去等于关掉 Zygisk 回到已知可启动状态。
> 备选：`parts/boot_b.bin`（原厂）、`parts/vendor_boot_b.bin`。

### 5.3 不想开机时直接关掉 Zygisk
```bash
$ADB -s $S shell "su -c 'rm -f /data/adb/magisk/zygisk'"    # 或写 0
```
（手机得能开机才能执行；若已 bootloop 用 5.2。）

## 6. 更强伪装：Shamiko（可选，**需要用户点头**）

- Shamiko 1.2.5，LSPosed 团队，**闭源**，只发预编译 zip
- 作用：比 DenyList 更激进，还隐藏 **Zygisk 框架本身**和残留挂载
- 用法：装模块 → **把 Enforce DenyList 关掉**（Shamiko 读 Magisk 的 DenyList 列表，但要求 Enforce OFF）→ 重启
- 白名单模式：`/data/adb/shamiko/whitelist` 建空文件
- **风险**：闭源 + 官方仓库已改名/迁移，社区镜像存在供应链风险
- **不解决 Play Integrity**

## 7. Play Integrity Fix（PIF，可选）

- 主流：`Pixel-Props/sensitive-props`（★414）、`Kolass2004/Play-integrity-fix-magisk`
- 作用：spoof 设备指纹，骗过 basic / device 级完整性检查
- 同样**不能**给 strong integrity
- 检测工具：`IR0NBYTE/playIntegrityFixDetector`

## 8. 文件位置

| 用途 | 路径 |
|---|---|
| 存档根目录 | `/Users/macbook/.minimax/workspace/redmi-note13-unlock/` |
| 分区镜像 | `artifacts/parts/`（boot_b / vendor_boot_b / vbmeta_* / lk_* …） |
| 补存镜像 | `artifacts/parts_extra/`（vbmeta_a/b、vboot_a/b） |
| 解锁/刷机记录 | `artifacts/*.txt`、`artifacts/misc/` |
| 代理配置 | `/Users/macbook/.minimax/workspace/proxy-setup/README-vless-reality.md` |
