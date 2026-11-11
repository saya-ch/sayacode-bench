# pro-v2 100 题 × 1 repeat × 4 agent：执行记录（2026-11-11 启动）

> 状态：**运行中**。本文只记录启动时的配置、为什么这样配、以及已知的解读边界。
> 结果另文（结题后写 `RESULT-PROV2-100X4.md`）。

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
| 并发 | 2（WSL 7GB 上限；容器实测约 0.8–1.0GB each）|
| 分批 | 5 题一批，共 20 批 |
| 代码 | `d6530ea`（含四处缺陷修复 + musl 修复）|
| 输出 | `C:\sb\hard\ab-ctx\prov2-100x4` |
| 预计 | 约 40 小时 |

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

复算脚本：`C:\sb\tmp\run100\analyze.py`。

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
