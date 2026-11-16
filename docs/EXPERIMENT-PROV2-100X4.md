# pro-v2 100 题 × 1 repeat × 4 agent：执行记录（2026-11-11 启动）

> 状态：**2026-11-16 15:00 暂停在 74/100 题**（用户要求）。已记录 287/400 条 trial。
> 本文只记录配置、执行过程、被修复的基建缺陷与已知解读边界。
> 结果与复现性实测见 [RESULT-PROV2-100X4](RESULT-PROV2-100X4.md)。

## 1. 为什么要重跑

`prov2-40x4`（40 题 × 4 agent = 160 trial）跑完后暴露出**四处会污染结论的评测缺陷**
（commit `c8dba0e` / `d6530ea`），其中两处直接影响通过率：

| 缺陷 | 影响 |
|---|---|
| 网关缺 `/v1` 无人拦 | 白跑 32 个 trial（本次 20 分钟内暴露，已修）|
| job 收尾 `OSError` 吞掉已通过的 trial | 实测 2 条假阴性（mini-swe）|
| 内部 timeout 退出码 124 记成 infrastructure | 3 条本应算 timeout 的被排除出分母 |
| **musl/Alpine 镜像** | claude/opencode/sayacode 在 protonmail 题全灭、mini-swe 独活 |

同时 40 题的口径被证明算错：把「长跑零产出」当成基建失败从分母删掉，把 sayacode
从 64.71% 虚高到 75.86%，并造出「与 opencode 持平」的假结论。详见
[RESULT-PROV2-4AGENTS-FINAL.md](RESULT-PROV2-4AGENTS-FINAL.md) 的结论更正。

按「先把基建修好，再完整重跑」的原则，40 题那批数据**作废**（保留作缺陷取证），
重跑 100 题。

## 2. 运行配置

| 项 | 值 |
|---|---|
| 题集 | `studies/large-sample-v1-pro-v2-100.json`（100 题）|
| agent | sayacode 3.3.0 / mini-swe / claude-code / opencode |
| 重复 | **1**（100×1×4 = 400 trial）|
| 分批 | **4 题一批，共 25 批**（原计划 5 题 20 批，实际按 4 题切）|
| 并发 | **每 agent 1 起步**，后按内存余量提到 2（WSL 上限 7 GB；容器实测 0.2–1.3 GB each）|
| 代码 | `d6530ea` 起，执行期间持续修复（见 §7）|
| 输出 | `C:\sb\hard\ab-ctx\prov2-100x4` |
| 实际耗时 | 2026-11-11 起至 11-16 暂停，**跑完 74 题，未达 100**（原估 40 小时）|

> **实际进度远低于预计，原因是宿主环境而不是题量**：Docker Desktop 平均每 40–60
> 分钟崩一次（§6），每次恢复要 10–20 分钟，叠加镜像反复重拉。把「预计 40 小时」
> 当成可靠数字是错的，这条已保留在此作为教训。

### 题集构成

前 40 题与 `large-sample-v1-pro-v2.json` **逐字段一致**（仅 `memory_mb` 由历史占位符 0
归一为真实值 4096，该字段不参与执行——`run_formal_240` 只读 `task_id`，容器内存由
Harbor 从 `task.toml` 解析）。新增 60 题全部来自干净池，逐条断言与任何历史实验零重叠。

stratum 分布：ansible 13 / openlibrary 13 / flipt 12 / qutebrowser 11 / teleport 11 /
vuls 9 / element 8 / navidrome 8 / webclients 8 / NodeBB 6 / tutanota 1。

> 干净池是 **564** 不是 602：`holdout-candidates.json` 的 `clean=602` 里混着 38 个
> 已跑过的题（`polluted` 是 40 条计数，与历史 40 题只有 2 条重合）。候选池取
> `clean − 已用40 = 564`。

## 3. 为什么 repeats=1

用户指定 100 × 1 × 4。但必须明确：**单次重复无法估计题内方差**。

从历史 `v2-325` 的 r1/r2 实测同题翻转率 12.8%–35.0%，
在 25% 翻转下 100 题对 20pp 差异的**检验功效只有约 9%**，10pp 约 2%。
所以本次 100 题结果：

- **可以**用来找改进方向（跨 repo 的强弱模式、失败模式分布）；
- **不可以**用来排名或对外宣称「谁更强」；
- 主跑结束后应先测 flaky（`C:\sb\tmp\audit\flaky\` 有现成脚本与 25 题子集），
  再决定是加题还是先降 flaky。**按现有证据，加题救不了排名。**

## 4. 判分口径（四条，必须照此解读）

1. **reward 优先**：`verifier/reward.txt` 是唯一真值。Harbor 会在 job 收尾时用
   `infrastructure_error` 覆盖**已通过**的 trial，只看 status 会产出假阴性。
2. **只有 verifier 完全没产出 reward 且异常来自基建，才算 infrastructure**。
   跑满 20–40 分钟、verifier 正常执行、只是 patch 为空 —— 那是 `empty_patch`，
   属模型失败，**留在分母**。
3. **timeout 留在分母**（用完时间预算是失败，不是基建问题）。
4. 三套分母分别报：`all` / `effective`（排除 infrastructure）/ `complete-case`
   （只用四家都干净跑完的题）。

复算脚本：`scripts/analyze_ab.py`（仓库内，非临时目录）：
`python scripts/analyze_ab.py --root <输出目录> --out <报告路径>`。

## 5. 已知的解读边界（必须和结果一起看）

1. **flaky 未在 prov2 上直接测过**。13%–35% 是从 `v2-325`（不同题集、不同代码版本）
   迁移的**外部估计**。主跑后需用 flaky 子集实测。
2. **musl 题仍是残差**。claude-code / opencode 已换 musl 原生构建修好；但
   sayacode 的 `sqlite-vec==0.1.9` 无 musllinux wheel 且无 sdist，在 musl 镜像上
   装不上。所以 musl 题上 sayacode 仍会 infra 失败 —— 分析时必须
   **单独标注 musl 题**，不能把它当能力差异，也不能只从 sayacode 的分母里删掉
   （那正是 40 题那批犯的错）。
3. **题集全为 pro-v2、difficulty 全 medium**。没有难度分层，结论不能外推到
   easy/hard 或其他题库。
4. **并发从 1 提到 2**。40 题那批是并发 1；若担心并发引入系统差异，可用
   `analyze.py` 按批次做敏感性检查（同 agent 前后批次通过率是否漂移）。

## 6. 运行期间的运维记录

镜像拉取一度完全卡死（4MB 镜像 150 秒零进展），排查结论：

- 宿主 `curl` 直连 registry 正常（2.7s），容器出网正常，**只有 Docker 守护进程的
  pull 走不通**；
- 真因：Docker Desktop 内置代理 `http.docker.internal:3128` 把 pull 走**直连**，
  而当前网络直连国际只有约 30KB/s；Clash 代理则是 1.4MB/s；
- 但 Docker 的 VM 到不了宿主的 `127.0.0.1:7897`（Clash `allow-lan: false`），
  直指 `host.docker.internal:7897` 报 `unexpected EOF`；
- 解法：`C:\sb\tmp\run100\relay.py` 在 `0.0.0.0:17897` 转发到 Clash 的 loopback，
  Docker 代理指向它。拉 4.4GB 镜像从"卡死"变成 4.1 分钟（约 18MB/s）。
- 期间 Clash 的数据面（`verge-mihomo`）死过一次，导致 pull 再次全部卡住。
  driver 现在每批开始前检查 7897/17897 端口，缺了就自动重启 Clash 与 relay。

### 6.1 Docker Desktop 反复崩溃（本轮的真正瓶颈）

服务约每 **40–60 分钟**崩一次，表现固定：Docker API 返回
`500 Internal Server Error ... v1.55`，进 WSL 只剩 `containerd-shim` 孤儿进程，
`dockerd` 本身消失。恢复必须 `wsl --shutdown` + 重启 Docker Desktop，耗时 10–20 分钟。

**已排查并排除的原因**：

| 猜测 | 实测 | 结论 |
|---|---|---|
| 内存不足（OOM）| 崩溃时刻 WSL 内 `free -m` 仍空闲 **5.8 GB / 7 GB**，`dmesg` 无 oom-kill | 排除 |
| 数据盘写满 | `/mnt/docker-desktop-disk` 挂载正常，926 GB 可用 | 排除 |
| 数据盘未挂载 | 初版 watchdog 只看 `docker info`，漏掉了这个态；后补「数据盘容量 > 10 GB」探测 | 已修 |

**根因未定位。** 诱因里最可疑的是每批「拉 4 个镜像 → 跑 → prune 掉旧镜像」造成的
vhdx 反复伸缩。把 `--disk-floor-gb` 从 80 降到 40（少触发 prune）之后崩溃频率没有
明显下降，所以这条也只是猜测。

**代价**：崩溃时正在跑的 trial 全部作废，容器被重建，agent 已完成的工作丢失，
但 trial 仍可能"跑完"并拿到 0 分。这与
[RESULT-PROV2-100X4](RESULT-PROV2-100X4.md) §3.2 里那个未解释的单向翻转高度可疑相关，
但**没有实证**。

### 6.2 磁盘：vhdx 膨胀与两次删除重建

`docker_data.vhdx` 一度涨到 **136.7 GB**，而内部实际只用了 **17.8 GB**。WSL 不支持
在线压缩，宿主无管理员权限跑不了 `diskpart compact vdisk`，`wsl --manage --set-sparse`
也不缩文件。最终两次直接删除该 vhdx 让 Docker 重建，各回收约 110–136 GB。

副作用：镜像缓存清零，需要重新从镜像站拉。**这在磁盘紧张的机器上是最有效的办法，
但它掩盖了真正的浪费源——prune 策略。** 早期的 prune 按「可回收容量」判定，
把整个共享层缓存每批清空一次，导致每批都要重拉十几 GB。

### 6.3 代理订阅配额耗尽

运行中期代理订阅 1 TB 配额用掉 **97.2%**（上传 294.1 GB + 下载 678.2 GB），64 个节点
全部探测失败。其中下载量主要是这一轮反复拉 4.4 GB 镜像造成的。恢复办法是改用
国内镜像站 `ghcr.nju.edu.cn` 直连（不走代理），并给 Docker 加代理排除列表
`OverrideProxyExclude=localhost,127.0.0.1,ghcr.nju.edu.cn,docker.nju.edu.cn`。

> 教训：**「Docker 全部走代理」是错的**。国内镜像站必须直连，Docker Hub 才需要代理。
> 两者要在同一个 Docker 里共存，只能用排除列表。

### 6.4 分批驱动器：同批反复重跑

驱动器原本的判定是「这一批四家不全就重试」，而某些题对某个 agent 是**持久性**失败
（例如 musl 题上 sayacode 装不上 `sqlite-vec`）。结果同一批题被反复重跑：批 3 单独
跑了**九次**，每次都重新拉四个镜像、跑十六个 trial，判定失败、进下一批——重启后又
从头来过。

修法：加 `settled-batches.json`，把「已判定为持久性失败」的 task_id 记下来，重启后
直接跳过。副作用是要留意：被 settle 的题如果后来环境变好了也不会再补，所以每次恢复
运行前应检查 `settled` 里有多少题缺记录。

## 7. 本轮新修复的基建缺陷（代码层）

全部在 `C:\develop\sayacode-bench`，均已提交：

| 提交 | 缺陷 | 症状 |
|---|---|---|
| `d6530ea` | musl/alpine 镜像按 libc 选原生二进制；worker 崩溃必留 traceback | claude/opencode 在 protonmail 题上全灭 |
| `d2b3f3f` | `uv tool install --python 3.12` 走 uv 的托管发现逻辑，忽略预置 tarball | mini-swe 每次安装都去 GitHub 下载，失败 |
| `d08d558` | sayacode 需要 CPython 3.13，`uv python install` 同样要 GitHub | sayacode 安装失败率极高 |
| `c8aef61` | 供应商侧 502 被记成模型失败 | sayacode 的 provider 中断混进能力统计 |
| `e0cd417` | 预置 CPython 是 glibc 构建，musl 镜像上可执行但跑不起来，`[ -x ]` 拦不住 | 白跑三次安装尝试才报错 |

补充说明：

- **musl 上 sayacode 仍然装不上**。`sqlite-vec==0.1.9` 既无 musllinux wheel 也无
  sdist，这是上游依赖的硬限制。分析时必须把 musl 题单独标注，**不能**把它当能力差异，
  也**不能**悄悄从 sayacode 的分母里删掉——那正是 40 题那批犯过的错。
- 驱动器侧新增：单实例锁（防两个 driver 抢同一 state）、按 agent 并发覆盖
  （`--agent-concurrency sayacode=2,mini-swe=2`）、按仓库交错重排题序
  （避免同类慢题扎堆导致批次耗时翻倍）、settled 机制（§6.4）。
