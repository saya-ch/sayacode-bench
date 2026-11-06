# M2 环境考古：`C:\sb` 37GB 构成与污染债清理方案

- 通道：第二轮复盘 M2（环境考古）
- 调查时间：2026-11-06 23:39 — 2026-11-07 00:20（UTC+8）
- 调查方式：**只读**（`Get-ChildItem` / `Measure-Object` / `docker system df` / `wsl -d ... -e sh -c`），未删除、未移动任何文件
- 执行人：env-runner

> 🛑 **2026-11-07 Lead 更正：本报告对 `v4-327` 的完成度判断有误。**
> 报告多处（§18、§72、§137、§147、§164、§344）称 `hard\v4-327`「实验未完成，阶段 2 仅 33/79」。
> **实测：`v4-327` 已完整跑完 80/80**——
> - `sayacode\jobs` 80 个 job（阶段 1，`--skip-verifier`，不产生 reward，**这是"33/79"误判的来源**：数阶段 1 目录里没有 reward）；
> - `sayacode\verify\jobs` **77 个 job，77 个 `reward.txt`**（阶段 2）；
> - `FINAL-SUMMARY-327.json` 的 trials 为 `verify 77 + native 2 + 缺 1 = 80`，`observed=79`、`missing=1`、`passes=61`（76.2%），与 ledger 完全一致；
> - 那 2 条 native 是 `terminal=skipped_empty_patch`（`vuls-dc496468b9e r1`、`qutebrowser-3e21c8214a r1`），缺的 1 条是 `vuls-4b680b99606 r1`。
> **"不可删"的结论不变**（它是 3.2.7 批次的唯一原始产物），但理由要改为「已完成的唯一原始产物」，不是「未完成」。
> 本报告其余结论（`C:\sb` 非主矛盾、55.4% 是 checkpoints、8 项唯一副本、可回收量三档）**经复核均成立**。

---

## 0. 结论先行

### 0.1 三个必须知道的结论

| # | 结论 | 影响 |
|---|---|---|
| 1 | **`C:\sb` 不是磁盘主矛盾**。C: 已用 892.63GB，`C:\sb` 仅 37.21GB（占 4.2%）。真正的大头是 `C:\Users\20655`（538.67GB，含 `docker_data.vhdx` 185.15GB）与 Docker 镜像（147.7GB） | 只清 `C:\sb` 最多回收十几 GB；若目标是"为 P2 腾空间"，必须同时处理 Docker 镜像 |
| 2 | **`C:\sb` 内部 55.4% 是 `checkpoints.sqlite3`**：395 个文件、**20.62GB**。这是 LangGraph 的会话持久化文件，**不是实验结论本身**（结论在 `reward.txt` / `exception.txt` / `rows.json` / `FINAL-SUMMARY.json`） | 这是 `C:\sb` 内唯一的大杠杆；但有"轨迹审计"取舍，见 §5 |
| 3 | **唯一副本共 3 类，绝对不可删**：① `archive\formal-240-v1-20261031.zip`（v1 formal-240 唯一完整副本，原始目录已不存在）；② 40 个 `abandoned-*`（失败证据，约 415MB）；③ `hard\v4-327`（实验未完成，阶段 2 仅 33/79） | 见 §4 |

### 0.2 对 Lead 三个具体问题的回答

| 问题 | 答案 |
|---|---|
| `abandoned-*` 里是否藏着唯一失败证据？ | **是**。`hard\v2-325\mini-swe` 下 114 条 `exception.txt`，其中 `abandoned-retry-20261102-165011` 单目录含 20 条网络/TLS 失败（`curl (35) SSL_ERROR_SYSCALL ... astral.sh:443`）+ 8 条 apt-get 失败。这是"补跑是否合规"结论的**唯一物证**，全部合计仅约 3.5MB |
| `C:\sb\archive` 是打包好的还是半成品？ | **已完整打包**。`formal-240-v1-20261031.zip` 995.93MB、**39,147 个条目**，含 `formal-240/FINAL-SUMMARY.json`（193KB）、`FINAL-SUMMARY.legacy.json`（51KB）、`AUDIT.json`（77KB）、`MODEL-FAULTS.json`，以及 `sayacode/` `mini-swe/` `codex/` 三个 agent 的 jobs+verify+abandoned。**且 `C:\sb\hard` 下已无 v1 formal-240 原始目录** → 此 zip 为唯一副本 |
| `C:\sb\wsl` 13.38GB 是什么，能不能压？ | 是 **WSL2 发行版 `sayacode-bench` 的 `ext4.vhdx`**（不是备份）。`wsl -l -v` 显示该发行版 **Stopped**，Docker 已改用 `docker-desktop` 发行版。其内部 `df -h /` 显示 **13G 已用 / 63G 容量**，与 vhdx 的 13.38GB 基本一致 → **几乎没有空洞可压**。但内部 `/var` 占 11G（疑似 Docker 数据或 apt 缓存），若能清理可回收大部分，见 §6.2 |

### 0.3 可回收量总表（分三档）

| 档位 | 内容 | 可回收 | 风险 |
|---|---|---:|---|
| **① 立即可删（零风险）** | Docker build cache（58 项） | **5.57GB** | 无（可重建） |
| **② 归档后可删（需先提取/校验）** | `checkpoints.sqlite3` 中的非现行批次（`tmp\hard` 4.18 + `tmp\completion-guard` 5.67 + `hard\hy3-holdout` 0.54 + 杂项约 0.4） | **≈10.8GB** | 中（损失轨迹回放能力，不损失 reward 结论） |
| **② 归档后可删（Docker 侧，收益最大）** | Docker 未被引用的镜像（83% 可回收） | **123.5GB** | **高（需逐项确认 P2 是否要用）** |
| **② compact 回收（WSL）** | `docker_data.vhdx` 空洞（185.15GB 逻辑 vs 约 157GB 实际） | **≈28GB** | 低（`diskpart compact`，需停 Docker） |
| **② 归档后可删（WSL 残留）** | `sayacode-bench` 发行版内 `/var/lib/containerd` 8.3G + `/var/lib/docker-classic` 1.7G（Docker 残留，非环境本体） | **≈10GB** | 🟢 低（另可用 unregister 回收全部 13.38GB） |
| **③ 不可删** | archive zip / abandoned-* / v4-327 / newset / analysis / 正式结果汇总 | — | 删则永久失据 |

> 若要"C: 空闲从 31.46GB 提到可用水平"，**单靠 `C:\sb` 只够 10–16GB**；把 Docker 镜像 + vhdx compact 一起做，可到 **100GB+**。

---

## 1. C: 盘全局：`C:\sb` 的真实权重

```
C: 已用 892.63 GB / 924.09 GB，空闲 31.46 GB
```

| 一级目录 | 占用 | 占已用 |
|---|---:|---:|
| `C:\Users` | 539.00 GB | 60.4% |
| 　└ `20655`（当前用户） | 538.67 GB | 60.3% |
| 　　└ 其中 `docker_data.vhdx` | **185.15 GB** | 20.7% |
| `C:\develop` | 79.21 GB | 8.9% |
| `C:\Program Files (x86)` | 53.16 GB | 6.0% |
| `C:\Windows` | 48.09 GB | 5.4% |
| **`C:\sb`** | **37.21 GB** | **4.2%** |
| `C:\Program Files` | 27.85 GB | 3.1% |
| `C:\workspace` | 24.33 GB | 2.7% |
| `C:\MATLAB` | 21.33 GB | 2.4% |
| `C:\$Recycle.Bin` | 4.58 GB | 0.5% |

**判断**：`C:\sb` 清理是"必要但不充分"。P2 要滚动拉镜像（单镜像 1–3GB），Docker 侧 147.7GB 才是主要矛盾。

---

## 2. `C:\sb` 顶层目录用途考证

| 目录 | 大小 | 创建 | 最后修改 | 用途（证据） | 是否现行 | 处置建议 |
|---|---:|---|---|---|---|---|
| `wsl` | **13.38 GB** | 10-22 19:24 | 11-06 23:25 | 仅含 `sayacode-bench\ext4.vhdx`（WSL2 发行版磁盘）+ `shortcut.ico` | **存疑**：发行版 Stopped，Docker 已走 `docker-desktop` | 见 §6.2；需 Lead 确认是否仍用该发行版 |
| `hard` | **10.80 GB** | 10-29 19:31 | 11-06 06:09 | 正式跑批结果根：`v2-325`（5.22GB，3.2.5 批次）、`v4-327`（4.31GB，**3.2.7 批次，未完成**）、`hy3-holdout`、`formal-tuned`、`archive`、`hy3-regression`、`gold-check*`、`collab-*` | **是**（v4-327 阶段 2 进行中） | 不可删；仅 `archive\v2-3.2.4-preview` 可考虑归档 |
| `tmp` | **10.68 GB** | 10-27 22:31 | 11-06 23:39 | `completion-guard`（5.78GB，第二轮 A/B 实验）、`hard`（4.80GB，10-28/29 早期实验 36 个批次）、`smoke-327`、`benchmarks`、`mut`、`explore` | **部分**：`mut`/`explore`/`benchmarks` 活跃（11-06 当晚），`completion-guard`/`hard` 已完成 | `tmp\hard` 可归档；`completion-guard` 的 sqlite 可归档 |
| `newset` | 0.99 GB | 11-06 17:31 | 11-06 20:03 | **P2 现行**：`swe-evo\tasks`（48 个 SWE-EVO 任务，7.7MB）、`runs\pilot1\sayacode`（pilot 运行结果） | **是（P2 核心）** | 不可删 |
| `archive` | 0.97 GB | 10-29 19:06 | 11-03 01:40 | `formal-240-v1-20261031.zip`（995.93MB，39,147 条目）+ `scripts-20261029`（约 200 个 10-28/29 的临时脚本，几百 KB） | **否**（v1 已归档） | **不可删**（唯一副本） |
| `s` | 0.29 GB | 10-22 13:42 | 10-22 22:45 | 数据集缓存：`swe-bench-pro-v2-*`（run_scripts）、`terminal-bench-2.1-*`、`cloud-cold-inputs-v1`、`source-q0ya4x0b` | 否（但重拉成本高） | 保留；如需回收可先确认上游可重拉 |
| `magpie-export` | 73.81 MB | 10-29 18:40 | 10-29 18:40 | `config\`（Magpie 导出配置） | 低 | 保留（小） |
| `tools` | 8.51 MB | 10-22 21:08 | 10-22 21:08 | `actionlint-1.7.12` | 低 | 保留（小） |
| `a` | 5.53 MB | 10-22 21:16 | 10-22 21:44 | `cloud-calibration-dry-v1` / `-v2`（校准 dry-run） | 否 | 可归档（小） |
| `build` | 2.51 MB | 10-22 13:52 | 10-22 13:52 | `baseline-source-v1`、`baseline-wheel-v1` | 否 | 可归档（小） |
| `bp-tmp` | 1.24 MB | 10-31 15:38 | 11-06 22:39 | `smoke-out`、`smoke2`、若干 check 脚本、`du_sb.ps1` | 低 | 可清（小） |
| `mihomo-iso` | 1.29 MB | 10-27 23:56 | 10-27 23:57 | Clash/mihomo 相关：`ruleset`、`config.yaml`、`cache.db`、`stdout.log`（297KB） | 否 | **保留**（代理配置，重配成本高） |
| `analysis` | 0.25 MB | 11-06 14:45 | 11-06 17:57 | **第二轮复盘产出**：`health.md`（题库体检：broken 3 / saturated 28 / healthy 4）、`behavior.json`、`dataset.json`、`swe-evo-baseline.json` | **是** | 不可删 |
| `pipelines` | 0.06 MB | 10-28 13:36 | 10-29 18:54 | 分析脚本：`analyze_eval.py`、`compare_ab.py`、`reconcile.py` 等 | 部分 | 保留（小） |

---

## 3. `abandoned-*` 失败证据清点

### 3.1 总量

全 `C:\sb` 共 **40 个** `abandoned-*` 目录，合计约 **415MB**。分布：

| 位置 | 数量 | 合计 | 说明 |
|---|---:|---:|---|
| `hard\v2-325\sayacode` | 12 | 约 168MB | 其中 `abandoned-retry-20261102-154511` 单目录 390MB（含 284MB 的 flipt checkpoints.sqlite3） |
| `hard\v2-325\mini-swe` | 17 | 约 3.5MB | **失败证据最密集** |
| `hard\v2-325\claude-code` | 2 | 约 0.62MB | |
| `hard\v4-327\sayacode` | 4 | 约 18.1MB | `abandoned-1793890535` 17.43MB |
| `hard\archive\v2-3.2.4-preview` | 3 | 约 1.44MB | |
| `hard\formal-tuned` | 1 | 0.38MB | |
| `tmp\completion-guard\off` | 1 | 0.32MB | 第二轮 A/B 的 10 个失败 job |

### 3.2 失败原因谱系（`abandoned-*` 内 `exception.txt` 末行归类）

| 失败类型 | 条数 | 典型文本 |
|---|---:|---|
| apt-get 失败（exit 100/137） | 38 | `NonZeroAgentExitCodeError: Command failed (exit 100): apt-get update && apt-get i...` |
| uv TLS 下载失败 | 28 | `RuntimeError: uv TLS 下载失败，curl exit=35` |
| astral.sh SSL 中断 | 15 + 11 | `curl: (35) OpenSSL SSL_connect: SSL_ERROR_SYSCALL in connection to astral.sh:443` |
| 命令超时（600s） | 12 | `RuntimeError: Command timed out after 600 seconds` |
| Docker compose 失败 | 约 20 | `Docker compose command failed for environment instance_...` |
| Agent setup 超时（1800s） | 8 | `AgentSetupTimeoutError: Agent setup timed out after 1800.0 seconds` |
| Docker 网络异常 | 4 | `Docker 网络操作失败：request returned 500` / `no such object` |

### 3.3 mini-swe 失败证据的精确分布（Lead 关注的"12 条网络失败"）

| 目录 | exception 总数 | 网络/TLS | apt | 超时 | 其他 |
|---|---:|---:|---:|---:|---:|
| `abandoned-retry-20261102-165011` | **28** | **20** | 8 | 0 | 0 |
| `abandoned-1793772376` | 14 | 0 | 0 | 0 | 14 |
| `abandoned-1793536849` | 13 | 1 | 2 | 0 | 10 |
| `abandoned-final-20261102-211019` | 10 | 2 | 8 | 0 | 0 |
| `abandoned-1793772288` | 8 | 0 | 8 | 0 | 0 |
| `abandoned-1793609425` | 6 | 0 | 0 | 6 | 0 |
| 其余 11 个目录 | 35 | 4 | 2 | 10 | 19 |
| **合计** | **114** | **27** | **33** | **20** | **34** |

> 说明：Lead 记忆中的"12 条网络失败"对应的是某一轮补跑的批次口径；全量 `abandoned-*` 内网络/TLS 类共 27 条。**无论口径如何，这些 `exception.txt` 是"网络失败导致缺样本"的唯一物证，且总体积不足 4MB，保留成本可忽略。**

### 3.4 处置建议

| 对象 | 建议 | 理由 |
|---|---|---|
| `hard\v2-325\mini-swe\abandoned-*`（17 个，3.5MB） | **保留** | 唯一失败证据，体积可忽略 |
| `hard\v2-325\sayacode\abandoned-*`（12 个，168MB） | **保留元数据，可删其中 checkpoints.sqlite3** | 其中 390MB 目录的绝大部分是 `checkpoints.sqlite3`（284MB），异常文本本身很小 |
| `hard\v4-327\sayacode\abandoned-1793890535`（17.43MB） | 保留 | v4-327 未完成，可能是阶段 2 证据 |

---

## 4. 唯一副本风险清单（**禁止删除**）

| # | 路径 | 大小 | 为何是唯一副本 | 风险等级 |
|---|---|---:|---|---|
| **U1** | `C:\sb\archive\formal-240-v1-20261031.zip` | **995.93 MB** | v1 formal-240 全部结果的**唯一完整副本**（39,147 条目，含三 agent 的 jobs/verify/abandoned 与 FINAL-SUMMARY）。`C:\sb\hard` 下**已无 v1 原始目录** | 🔴 极高 |
| **U2** | `C:\sb\hard\v2-325\...\abandoned-*` 全部 `exception.txt` | ≈ 3–4 MB | 网络/TLS/apt 失败的**唯一失败证据**，不可从代码或日志重生成 | 🔴 极高 |
| **U3** | `C:\sb\hard\v4-327`（整个） | **4.31 GB** | 3.2.7 批次实验**未完成**（阶段 2 仅 33/79），阶段 1 的 80 个 trial 轨迹是后续验证与汇总的唯一输入 | 🔴 极高 |
| **U4** | `C:\sb\newset`（整个） | 0.99 GB | **P2 现行工作产物**：48 个 SWE-EVO 任务定义 + pilot1 运行结果，来自上游的一次性拉取/构造 | 🔴 极高 |
| **U5** | `C:\sb\analysis` | 0.25 MB | 第二轮题库体检结论（broken/saturated/healthy 分级），是 P2 选题依据 | 🟠 高 |
| **U6** | `C:\sb\hard\v2-325\{sayacode,claude-code,codex,mini-swe,opencode}\rows.json` 与各 `*-summary.json` | <1 MB | 3.2.5 批次三口径汇总的原始输入 | 🟠 高 |
| **U7** | `C:\sb\tmp\completion-guard\*` 的 `checkpoints.sqlite3` | 5.67 GB | **`guard_trigger_rate = 90%` 的唯一物证**（`events.jsonl` 不含 message 内容，只有 checkpoints 里才有 `sayacode_continue_nudge` 标记）。若要删，**必须先导出 nudge 布尔矩阵** | 🟠 高（可降级，见 §5.3） |
| **U8** | `C:\sb\mihomo-iso\config.yaml` / `cache.db` / `ruleset` | 1.3 MB | 代理配置，重配成本高（且与 Clash TUN 环境耦合） | 🟡 中 |

---

## 5. `checkpoints.sqlite3`：`C:\sb` 内最大的可回收项

### 5.1 全量分布（395 个 / **20.62 GB**）

| 位置 | 文件数 | 合计 | 属于 | 可回收性 |
|---|---:|---:|---|---|
| `tmp\completion-guard` | 82 | **5.67 GB** | 第二轮 A/B（已完成） | 🟡 需先导出 nudge 证据（U7） |
| `hard\v2-325` | 85 | **4.35 GB** | 3.2.5 批次（已完成） | 🟢 可归档后删 |
| `hard\v4-327` | 79 | **4.28 GB** | 3.2.7 批次（**未完成**） | 🔴 不可删 |
| `tmp\hard` | 89 | **4.18 GB** | 10-28/29 早期实验（36 个批次） | 🟢 可归档后删 |
| `newset\runs` | 10 | 0.97 GB | P2 pilot | 🔴 不可删 |
| `hard\hy3-holdout` | 20 | 0.54 GB | 10-29 holdout | 🟢 可归档后删 |
| `hard\formal-tuned` | 7 | 0.18 GB | 10-31 调优 | 🟢 可归档后删 |
| `hard\archive` | 5 | 0.14 GB | v2-3.2.4 预览 | 🟢 可归档后删 |
| `hard\hy3-regression` | 8 | 0.13 GB | 10-29 回归 | 🟢 可归档后删 |
| 其余（`v2-325-smoke`、`tmp\smoke-327`、`hard\agent-verify` 等） | 10 | ≈0.19 GB | 冒烟/校验 | 🟢 |

### 5.2 单个 `jobs` 目录中 checkpoints 的占比（证明它是唯一大头）

| 目录 | jobs 总量 | checkpoints | 占比 |
|---|---:|---:|---:|
| `hard\v2-325\sayacode\jobs` | 4.048 GB | 3.973 GB（79 个） | **98.1%** |
| `hard\v4-327\sayacode\jobs` | 4.287 GB | 4.259 GB（78 个） | **99.3%** |
| `tmp\hard\ab-condensed` | 1.13 GB | 1.08 GB（15 个） | **95.6%** |

> 即：这些 `jobs` 目录的"体积"几乎全部由 `checkpoints.sqlite3` 构成，去掉它之后 `jobs` 只剩约 2%。

### 5.3 取舍建议

`checkpoints.sqlite3` 是 LangGraph 的**会话状态持久化**，作用是"轨迹可回放/可审计"。它**不承载实验结论**：

- 结论载体：`verifier/reward.txt`、`exception.txt`、`rows.json`、`FINAL-SUMMARY.json`、`AUDIT.json`
- 轨迹载体：`agent/sayacode/events.jsonl`、`audit.jsonl`（体积是 checkpoints 的约 2%）
- 唯一例外：**`sayacode_continue_nudge` 只存在于 checkpoints 的 message 序列化数据中**，`events.jsonl` 里没有（这也是 `analyze_ab.py` 曾误报 `guard_trigger_rate=0%` 的原因）

因此建议流程：

1. 先跑 `guard_rate.py`（已存在于 `C:\sb\tmp\completion-guard\guard_rate.py`），导出 `{job → 是否含 nudge}` 布尔矩阵为 JSON（约 40 行，几 KB）；
2. 将矩阵与 `AB-RESULT.md` 一同归档；
3. 归档后再删 `tmp\completion-guard` 的 checkpoints（5.67GB）；
4. `hard\v2-325` 的 checkpoints 可直接归档后删（**该批次结论已固化**）。

**保守估算**：`tmp\completion-guard`（5.67）+ `tmp\hard`（4.18）+ `hard\hy3-holdout`（0.54）+ `formal-tuned`（0.18）+ `hy3-regression`（0.13）+ `hard\archive`（0.14）+ 零碎（0.19）≈ **11.0GB 可回收**；`hard\v2-325` 的 4.35GB 若 Lead 确认 3.2.5 结论已固化，可再加 → **约 15.4GB**。

---

## 6. WSL / Docker 侧

### 6.1 Docker（C: 盘最大杠杆）

```
TYPE            TOTAL   ACTIVE   SIZE      RECLAIMABLE
Images          68      2        147.7GB   123.5GB (83%)
Containers      3       3        6.091MB   0B (0%)
Local Volumes   5       1        3.655GB   3.476GB (95%)
Build Cache     58      0        5.565GB   24.58kB
```

| 项 | 现状 | 对比第一轮 | 建议 |
|---|---|---|---|
| 镜像 | **68 个 / 147.7GB**，仅 2 个被引用 | 第一轮为 38 个 / 78.65GB | 清理未被引用的镜像可回收 **123.5GB**，但**必须逐项确认 P2 是否要用**（P2 要滚动拉镜像，与本批 20 题镜像可能重叠） |
| 卷 | 5 个 / 3.655GB，95% 可回收 | 与第一轮一致 | 之前记录为"用户卷，不动"，**维持不动** |
| 构建缓存 | 58 项 / 5.565GB | 第一轮 1.008GB | `docker builder prune -f` **零风险回收 5.57GB** |

### 6.2 `C:\sb\wsl` 13.38GB：WSL 发行版磁盘

```
$ wsl -l -v
  NAME              STATE      VERSION
* docker-desktop    Running    2
  sayacode-bench    Stopped    2

C:\sb\wsl\sayacode-bench\ext4.vhdx   13.378 GB   （非稀疏）
$ wsl -d sayacode-bench -e df -h /
/dev/sdf   63G   13G   47G   22% /
$ wsl -d sayacode-bench -e du -sh /usr /var /root /opt
9.5G  /usr     11G  /var     470M  /root     237M  /opt
```

**进一步定位（本次已补查）**：

```
$ wsl -d sayacode-bench -e du -sh /var/lib/*
8.3G  /var/lib/containerd          ← Docker 数据残留
1.7G  /var/lib/docker-classic      ← 经典 dockerd 数据残留
205M  /var/lib/apt
19M   /var/lib/dpkg
其余 <10M
```

```
$ ls -la /opt/sayacode-bench/
drwxr-xr-x ... Oct 22 19:39 .        ← 全部为 10-22 的文件
drwxr-xr-x ... Oct 22 19:38 .venv
$ find /opt/sayacode-bench -newermt "2026-11-01"   → 无结果
```

**判断（已修正）**：
1. 这 13.38GB **不是备份**，是 WSL2 发行版实际磁盘；
2. 但**其中约 10GB（8.3G containerd + 1.7G docker-classic）是该发行版内的 Docker 数据残留**，与"bench 环境"本身无关；
3. `/opt/sayacode-bench` 全部文件停留在 **10-22**，11-01 之后**无任何写入** → 该发行版自建立起从未在 11 月承担跑批，当前跑批全部走 Docker Desktop（`docker-desktop` 发行版）；
4. 因此该发行版**极可能已废弃**，13.38GB 中约 10GB 属"容器数据残留"，剩余约 3.4GB 才是系统+代码。

**建议（需 Lead 决策，三选一）**：
- **方案 A（彻底，回收 13.38GB）**：确认 `sayacode-bench` 发行版不再需要 → `wsl --unregister sayacode-bench`（**不可恢复**，会连带删除 `/opt/sayacode-bench` 的 10-22 代码副本）；
- **方案 B（保守，回收约 10GB）**：仅清理发行版内的 Docker 残留，保留系统与代码：
  ```bash
  wsl -d sayacode-bench -e sh -c 'rm -rf /var/lib/containerd /var/lib/docker-classic /var/cache/apt /var/log/*'
  wsl --shutdown
  # 再 diskpart compact 回收空洞
  ```
- **方案 C（最保守）**：只做 `wsl --shutdown` + `diskpart compact vdisk`（因为内部已用 13G ≈ vhdx 13.38GB，**几乎榨不出空间**，实质无收益，不推荐）。

### 6.3 `docker_data.vhdx` 空洞

```
逻辑 185.15 GB（非稀疏）
Docker 内部实际：镜像 147.7 + 卷 3.655 + 缓存 5.565 + 容器 0.006 ≈ 157 GB
→ 估计空洞 ≈ 28 GB
```

**建议**：在完成镜像清理后执行（顺序不能颠倒，先删镜像再 compact 才有效）：

```powershell
# 1) 清理（需 Lead 授权具体清单）
docker builder prune -f
docker image prune -a -f          # ⚠️ 会删除所有未被容器引用的镜像，需先确认 P2 镜像清单
# 2) 停 Docker Desktop / WSL
wsl --shutdown
# 3) 压缩 vhdx（管理员权限）
diskpart
  select vdisk file="C:\Users\20655\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
  attach vdisk readonly
  compact vdisk
  detach vdisk
  exit
```

> 注意：之前记录提到 `docker_data.vhdx` 位于 `%LOCALAPPDATA%\Docker\wsl\disk\`，与 `C:\sb` 无关；但它是 C: 盘第一大单文件（185GB），对"腾空间"的贡献远大于 `C:\sb`。

### 6.4 `C:\$Recycle.Bin` 4.58GB

回收站占用 4.58GB，属 C: 盘层面的低风险回收项（清空前建议 `Get-ChildItem` 确认无用户需要找回的文件）。

---

## 7. 重复产物识别

| 疑似重复 | 核查结果 | 结论 |
|---|---|---|
| `tmp\hard`（36 个批次） vs `hard\`（17 个目录） | **无同名交集** | 不是副本，`tmp\hard` 是 10-28/29 的独立早期实验，可独立处置 |
| `har\archive\v2-3.2.4-preview` vs `hard\v2-325` | 不同版本（3.2.4 预览 vs 3.2.5 正式） | 非重复 |
| `archive\formal-240-v1-...zip` vs `hard\` | v1 原始目录已不存在 | zip 是唯一副本，**不是重复** |
| `tmp\completion-guard\{off,on}` vs `hard\v2-325` | 不同实验（A/B guard 实验 vs 3.2.5 正式批次） | 非重复 |
| `tmp\hard\wheel-release*` 多个（3.2.5/3.2.6/3.2.7/v2/optimized/condensed/final/check/keep8） | 均为**很小的构建输出目录**（合计 <0.01GB） | 无需处理 |
| `C:\sb\s\swe-bench-pro-v2-*` vs `newset\swe-evo\tasks` | 不同数据集（SWE-bench Pro vs SWE-EVO） | 非重复，均保留 |

> **结论：`C:\sb` 内没有值得动手的大体积重复副本。**体积几乎全部由 `checkpoints.sqlite3`（20.62GB）+ WSL vhdx（13.38GB）构成，二者都不是"重复"而是"单份但可裁"。

---

## 8. 三档清理方案（供 Lead 决策）

### ① 立即可删（零风险，可随时重建）

| 项 | 回收 | 命令/操作 |
|---|---:|---|
| Docker build cache | **5.57 GB** | `docker builder prune -f` |
| 空 `abandoned-*` 壳目录（仅空目录，保留其中任何文件） | ≈0 GB | 可选 |
| **小计** | **≈5.6 GB** | |

### ② 归档后可删（需先提取证据 / 校验 zip）

| 项 | 回收 | 前置条件 | 风险 |
|---|---:|---|---|
| `tmp\completion-guard` 的 checkpoints（82 个） | 5.67 GB | 先跑 `guard_rate.py` 导出 nudge 布尔矩阵 | 🟡 |
| `tmp\hard` 全部（36 个早期批次，含 checkpoints） | 4.80 GB | 确认 10-28/29 实验结果已被后续批次取代或结论已固化 | 🟡 |
| `hard\hy3-holdout` + `formal-tuned` + `hy3-regression` + `hard\archive` 的 checkpoints | 0.99 GB | 结论已固化 | 🟢 |
| `hard\v2-325` 的 checkpoints（85 个） | 4.35 GB | Lead 确认 3.2.5 三口径结论已固化 | 🟠 |
| `C:\sb\s`（数据集缓存） | 0.29 GB | 确认上游可重拉 | 🟡 |
| **小计（保守，不含 v2-325）** | **≈11.5 GB** | | |
| **小计（含 v2-325）** | **≈15.8 GB** | | |

### ③ 不可删（唯一副本 / 现行工作）

| 项 | 大小 | 原因 |
|---|---:|---|
| `archive\formal-240-v1-20261031.zip` | 0.97 GB | U1 唯一副本 |
| `hard\v4-327`（含 4.28GB checkpoints） | 4.31 GB | U3 未完成实验 |
| `newset`（含 0.97GB checkpoints） | 0.99 GB | U4 P2 现行 |
| `hard\v2-325` 的 `rows.json`/`verify`/`abandoned-*` 文本 | ≈0.02 GB | U2/U6 证据 |
| `analysis` | 0.25 MB | U5 |
| `mihomo-iso` | 1.29 MB | U8 |
| **小计** | **≈6.3 GB** | |

### ④ Docker / WSL 侧（收益最大，需单独授权）

| 项 | 潜在回收 | 风险 |
|---|---:|---|
| 未被引用的 Docker 镜像（123.5GB 可回收，需逐项确认） | 最高 **123.5 GB** | 🔴 高，须先列出 P2 保留清单 |
| `docker_data.vhdx` compact | ≈28 GB | 🟡 中，需停 Docker |
| `sayacode-bench` 发行版内 Docker 残留清理（方案 B） | **≈10 GB** | 🟢 低（保留系统与代码） |
| `sayacode-bench` 发行版 unregister（方案 A） | **13.38 GB** | 🔴 高，不可恢复（需确认废弃） |
| `C:\$Recycle.Bin` 清空 | 4.58 GB | 🟢 低 |
| **小计** | **最高约 169 GB** | |

---

## 9. 建议执行顺序

1. **先做零风险项**：`docker builder prune -f`（+5.57GB），观察 P2 是否受影响。
2. **导出 guard 证据**：跑 `guard_rate.py`，把 nudge 布尔矩阵写入 `docs/review/round2/`，完成 U7 降级。
3. **确认三件事再动归档**：
   - `sayacode-bench` WSL 发行版是否还需要（决定 13.38GB）；
   - `hard\v2-325` 的 3.2.5 结论是否已固化（决定 4.35GB）；
   - `tmp\hard` 的早期实验是否已被取代（决定 4.80GB）。
4. **Docker 镜像清理**：先 `docker images` 导出清单 → 与 P2 需要的 SWE-EVO 镜像比对 → 只删确定无关的。
5. **最后 compact**：镜像清理完成后 `wsl --shutdown` + `diskpart compact`（≈28GB）。
6. 全程避免在 v4-327 阶段 2 跑批期间操作 Docker（会中断验证）。

---

## 10. 附：本次调查的局限

| 项 | 说明 |
|---|---|
| `C:\Users\20655` 下二级明细 | 全量扫描耗时过长（539GB），仅确认其中 `docker_data.vhdx` = 185.15GB；未逐一列出用户数据 |
| `tmp\hard` 36 个批次的逐批结论归属 | 仅按目录名与时间判断为"早期实验"，未逐批核对是否已被后续批次取代 |
| 镜像逐个用途 | 仅统计总量与可回收量，未逐镜像判定 P2 相关性（需 Lead 提供保留清单） |
| `sayacode-bench` 发行版内 `/opt/sayacode-bench-data`（186MB）内容 | 已知体积，未逐个文件核对是否含唯一数据；执行方案 A（unregister）前建议补查 |
| `hard\formal-tuned` / `hy3-regression` / `gold-check*` / `collab-*` 的结论状态 | 按目录名推断为已完成的历史批次，未逐个打开核对 |

### 关于调查期间磁盘变化

本通道**全程只读**，唯一的写操作是产出本文件（24.4KB，位于 `C:\develop`，不在 `C:\sb`）。但测量显示：

| 时点 | `C:\sb` | C: 空闲 |
|---|---:|---:|
| 调查开始（23:39） | 37.21 GB | 31.46 GB |
| 调查结束（00:30） | 37.37 GB | **27.45 GB** |

即 C: 空闲在约 50 分钟内减少约 4GB，`C:\sb` 微增 0.16GB。**该变化不是本通道造成的**（本通道未写 `C:\sb`），可能来自其他并发通道的文件写入、Docker 镜像拉取或系统日志增长。若需归因，建议对照同期的其他通道记录。
