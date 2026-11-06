# R3：评测基建缺陷台账与存活缺陷排查

| 项 | 值 |
|---|---|
| 版本 | v1.0（2026-11-07） |
| 范围 | `C:\develop\sayacode-bench` 仓库 + `C:\sb` 运行环境，2026-10-29 ~ 2026-11-06 |
| 方法 | 只读代码核验（`read`/`grep`/`git log -S`）+ 3 次只读复现脚本；不修改代码与数据 |
| 结论 | 台账收录 31 条缺陷：**完全修复 24 条、部分修复 5 条、未修复 2 条**；另单列 **15 条仍存活缺陷**（S1–S15，含部分修复的未清残留，其中 P0 级 3 条） |
| 证据 | 每条存活缺陷附 `文件:行号` 与可复现命令；复现脚本见 §8 |

---

## 0. 摘要

10-29 以来的工程缺陷可按"是否已被新题库接入暴露"分为两波：第一波（v1→v2，10-29~11-02）集中在**分母与缺失分类口径**，第二波（v3→v4→SWE-EVO，11-04~11-06）集中在**硬编码假设与静默失败**。第一波基本已修且有回归测试；第二波修复不完整——SWE-EVO 接入时修掉了 4 处 `instance_` 前缀假设，但**同一假设在至少 15 个位置仍然存活**，其中 `run_formal_240.py` 的归档判据会在 SWE-EVO 上把已完成 job 判为"无结果"（实测 10/10），`execution.py` 的重判与身份哈希对 SWE-EVO 完全失效。

**最重要的三个判断**：

1. **`instance_` 前缀假设未消除**（P0）。全仓仍有 5 处 `glob("instance_*")`/`startswith("instance_")` 位于**执行/汇总/体检**主链路；commit `46f57f0` 只修了 4 处且**无回归测试**。
2. **`MISSING_CLASSES` 与 PROTOCOL-V2 §3 仍不一致**（P0）。代码 7 类、协议 6 类；且 `timeout` 是**不可达类**——`classify_missing` 没有任何分支返回它，超时 trial 被记成 `empty_patch`/`unverified`，直接违反"timeout 不补"条款。
3. **`CANONICAL_MODEL` 两处仍不一致**（P1）。`src/` 两处为 `DeepSeek-V4.1-Flash`，`scripts/locked_agents.py` 为 `auto-hy3`；两条执行链路写出的 `canonical_model` 不同，`analysis.py` 的 `model_mismatch` 会把合法记录判成不一致。

---

## 1. 方法与口径

- **代码级核验**：所有"已修/未修"结论均来自当前 HEAD（`46f57f0`，2026-11-06 20:18）的源码，不采信文档自述；文档只用于确定"首次暴露时间"与"症状"。
- **修复判定**：同时满足 ① 代码路径已无缺陷 ② 有可执行回归测试 ③ 在当前数据上复跑不复发，才算"已修"。缺 ② 记"部分修复"。
- **只读复现**：`C:\sb\tmp\explore\trajectory\prove_surviving_defects.py`（宿主 `.venv` Python，harbor 0.24.0），输出见 §8.2。复现只读目录、不写仓库、不调模型、不跑 Docker。
- **分母口径**：本报告不评价模型能力，只评价工具链；涉及的 trial 数据仅用于证明"判据会误判"。

---

## 2. 缺陷台账主表

> 列说明：「首次暴露」取最早有记录的日期；「根因」给当前代码行号（若已修，给修复后仍可定位的位置）；「回归测试」列出覆盖该缺陷的 `tests/` 文件；「复发风险」指同类问题再次出现的可能性。

### 2.1 硬编码假设

| ID | 缺陷 | 首次暴露 | 症状 | 根因（代码级） | 已修 | 回归测试 | 复发风险 |
|---|---|---|---|---|---|---|---|
| R3-01 | `instance_` 前缀假设（4 处主链路） | 11-06 SWE-EVO 接入 | 阶段2「待验证 0 个」；重判 `no source patch` 全 0 分；汇总全落 `empty_patch`/`no_job` | `verify_patches.py:34-49`、`locked_agents.py:487-499`、`formal.py:350-364`、`formal.py:319-331` | ⚠️ 部分 `46f57f0`（4 处已修，15 处未，见 S1–S6） | ❌ 无新增测试（`test_formal.py` 合成数据仍用 `instance_`） | **高**（同类假设仍有 15 处存活，见 S1–S6） |
| R3-02 | `PRODUCT_VERSION` 硬编码 `3.2.4` | 10-31 装 3.2.5 | 安装后版本校验失败 | 原 `installation.py:24` 常量 | ✅ `a1e51d3`（从 wheel 文件名推断） | ❌ | 低 |
| R3-03 | 三 agent 输出预算不一致（16000/32000） | 10-31 | 长任务收尾过早、组间不可比 | 原 `locked_agents.py` 各 agent 配置 | ✅ `f393346`（统一 32000） | ❌ | 中 |
| R3-04 | profile `context_length` 配小（65536） | 10-29 | 长任务提前摘要 | 运行配置（非代码） | ✅ 配置修正 + `profile_summary.py` 跑前汇报 | ❌（脚本无断言） | 中 |
| R3-05 | 仓外依赖 `C:\sb\hard\test_agent.py` 等 | 10-31 | 换机/清目录后跑批直接不可用 | 原 `run_formal_240.py:19,24` | ✅ `ab3a4b7`（收编进 `scripts/locked_agents.py`） | ✅ `test_locked_agents.py` | 低 |
| R3-06 | SWE-EVO task 目录名过长/非法 | 11-06 | Harbor slug 化后 `-__` 拼接，Docker `invalid reference format` | 转换器命名 | ✅ `21b2701` + `rename_tasks_short.py` | ❌ | 中 |

### 2.2 口径不一致

| ID | 缺陷 | 首次暴露 | 症状 | 根因（代码级） | 已修 | 回归测试 | 复发风险 |
|---|---|---|---|---|---|---|---|
| R3-07 | 分母三套并列（55/80 vs 69/80 vs 56/65） | 10-29 v1 | 制造 17.4pp 假差距 | 旧 `final_summary.py` 只统计 observed | ✅ `ab3a4b7` + `formal.py`（planned/observed/task_macro） | ✅ `test_formal.py` | 低 |
| R3-08 | 缺失分类无 `infra`/`timeout`，只看 `patch_bytes` | 11-05 | mini-swe 8 条安装失败被记成 `empty_patch`（能力类、不补） | `formal.py:464-476` | ⚠️ 部分：`infra` 已加，`timeout` 仍不可达（S8） | ✅ `test_formal.py:182-222`（仅 infra） | **高** |
| R3-09 | `strict_compare` 不读 `terminal.json` | 11-05 | 同一批数据两工具 missing 数不同 | 原 `strict_compare.py:_collect` | ✅ `6ffe7f5`（`_read_terminal`，`:59-73`） | ✅ `test_strict_compare.py` | 中（另有两处新缺陷 S11） |
| R3-10 | 「patch 含测试文件」当作弊指标 | 11-02 | 把会被 verifier 重置的改动当作弊 | 分析口径 | ✅ `a651d45`/`TEST-EDIT-ANALYSIS`（改 `__snapshots__` 口径） | ❌ | 中 |
| R3-11 | `CANONICAL_MODEL` 两处常量不一致 | 11-05（§5.5.3） | `canonical_model` 字段两值混用 | `connections.py:11` / `execution.py:25` = `DeepSeek-V4.1-Flash`；`locked_agents.py:38` = `auto-hy3` | ❌ **未修**（S7） | ❌ | **高** |
| R3-12 | `task_count=0` 被当作协作能力证据 | 11-02 | 误判"协作不可用" | 评测题不触发派发 | ✅ `3b97c1e`/`d9ecb36`/`TASKCOUNT-ATTRIBUTION`（结论更正） | ❌ | 低 |
| R3-13 | 补跑前后未同表并报（v3 报告） | 11-05 | 读者无法判断领先是否来自环境修复 | 报告口径 | ✅ `6ffe7f5`（文档更正） | ❌ | 中 |

### 2.3 幂等性与续跑

| ID | 缺陷 | 首次暴露 | 症状 | 根因（代码级） | 已修 | 回归测试 | 复发风险 |
|---|---|---|---|---|---|---|---|
| R3-14 | 安装证据目录 `mkdir(exist_ok=False)` | 10-31 | 重跑 smoke 直接 `FileExistsError` | 原 `installation.py` 证据目录 | ✅ `5c59126` | ❌ | 低 |
| R3-15 | 阶段1 跳过验证器时无 reward/terminal | 10-31 | skip 判据不跳过 → 重跑撞 `ValueError` | 原 `run_formal_240.py` skip 判据 | ✅ `5f8b138`（认 `normalized.json:record_complete`） | ❌ | 中（新题库上仍因 `instance_` 判据失效，S1） |
| R3-16 | 空 patch 永久 pending | 11-03 | 阶段2 反复排队空 patch | 原 `verify_patches.py:73` 静默 `return` | ✅ `ab3a4b7`（`terminal.json:skipped_empty_patch`） | ✅ `test_formal.py:115-126` | 低 |
| R3-17 | `collect_pending` 只认 stage1 reward | 11-05 | 重跑 verify 把已验证 trial 再排队 | 原 `verify_patches.py:collect_pending` | ✅ `c4a552e`（同时认 `verify/jobs`） | ✅ `test_verify_patches.py`（6 例） | 低 |
| R3-18 | 归档清单与 retry sample 不同源 | 11-02 | 归档 28 个、sample 只覆盖 8 题 → 22 条 `no_job` | 编排流程（非单一代码） | ✅ 流程修正（LESSONS §2.6） | ❌ | 中 |

### 2.4 编码、换行与平台

| ID | 缺陷 | 首次暴露 | 症状 | 根因（代码级） | 已修 | 回归测试 | 复发风险 |
|---|---|---|---|---|---|---|---|
| R3-19 | Windows `write_text` 默认 CRLF | 11-06 SWE-EVO | bash `syntax error: unexpected end of file` | `convert_swe_evo.py:277-302` 缺 `newline="\n"` | ✅ `21b2701`（全部显式 `newline="\n"`） | ❌ | 中 |
| R3-20 | PowerShell 输出编码（cp1252/GBK） | 10-31 | 中文/emoji 崩溃、help 乱码 | CLI 输出 | ✅ `dfd1fc4`（`sys.stdout.reconfigure`）+ `test_cli_shards.py` | ✅ | 低 |
| R3-21 | 镜像内 Python 3.8 不支持 PEP 585 | 11-06 | `TypeError: 'type' object is not subscriptable` | `convert_swe_evo.py:134-215`（PARSER 用 `dict[str,str]` 会炸） | ✅ 已写成无注解版本 | ❌ | 中 |

### 2.5 容器、网络与资源

| ID | 缺陷 | 首次暴露 | 症状 | 根因 | 已修 | 回归测试 | 复发风险 |
|---|---|---|---|---|---|---|---|
| R3-22 | Docker 引擎崩溃（宿主内存压垮 WSL） | 10-31 | `docker info` 500、容器全消失 | 宿主 15.6GB / VM 无上限 | ⚠️ 运维缓解（`.wslconfig memory=7GB`、并发 2–4） | ❌ | **高** |
| R3-23 | Docker 网络池耗尽（每 trial 2 网络，池 ~17） | 10-30 | `all predefined address pools have been fully subnetted` | 架构（每 trial 独立网关网） | ⚠️ 运维（`network prune`、并发 ≤6） | ❌ | **高** |
| R3-24 | 代理注入导致内部主机名 `gaierror` | 11-01 | agent 请求网关失败、patch=0 | Docker CLI `proxies` + `NO_PROXY` 缺内部主机 | ✅ 移除代理/补 `NO_PROXY`（配置） | ❌ | 中 |
| R3-25 | Clash fake-ip 致 apt 502 | 11-01 | `apt-get update` 502 `[IP: 198.18.x.x]` | 网络规则（非代码） | ✅ Clash profile `prepend` 加 DIRECT | ❌ | 中 |
| R3-26 | astral.sh TLS exit=35 间歇失败 | 10-31 | 安装阶段随机失败 | 上游 TLS（非代码） | ✅ `0744741`/`352541d`（预置 uv installer + CPython tarball） | ❌ | 低 |
| R3-27 | nginx 拦截带 query 请求 | 11-04 | Claude Code `?beta=true` 首个请求 400，整组 0 通过 | 原 `network.py` `if ($args != "") return 400` | ✅ `55e922c`（精确路径白名单） | ✅ `test_network.py` | 中 |
| R3-28 | Docker vhdx 删镜像不缩容 | 11-03 | 删 14 镜像 C: 只涨 3.9GB | 存储机制 | ⚠️ 运维（`diskpart compact vdisk`） | ❌ | 中 |
| R3-29 | Codex 整组适配失效（apply_patch/websocket 405） | 11-04 | 78/80 `apply_patch` 不可用、80/80 405 | 上游契约不兼容 | ✅ 整组作废、换 Claude Code（`84bc815`/`55e922c`） | ❌ | 低 |

### 2.6 静默失败与判定

| ID | 缺陷 | 首次暴露 | 症状 | 根因（代码级） | 已修 | 回归测试 | 复发风险 |
|---|---|---|---|---|---|---|---|
| R3-30 | 只读 `exception.txt` 低估适配缺陷 | 11-04 | Codex 3 个 exception 掩盖 78/80 系统性缺陷 | 无全量轨迹审计 | ✅ `b7c42a8`（`audit_agent_traj.py`） | ❌ | 中 |
| R3-31 | 静默 `except`/读失败当缺失 | 全程 | 读文件异常 → 当 `empty_patch`/`unverified`/`unattributed` | `formal.py:205-253,277-285,557-559` 等（S9/S10/S12） | ❌ **未修** | ❌ | **高** |

**统计**：31 条中 ✅ 完全修复 24 条（R3-02~07、09、10、12~21、24~27、29、30）、⚠️ 部分修复 5 条（R3-01 只修 4/19 处、R3-08 缺 `timeout`、R3-22/23/28 仅运维缓解）、❌ 未修复 2 条（R3-11 `CANONICAL_MODEL`、R3-31 静默失败）。存活清单 S1–S15 是"部分修复的未清残留 + 未修复 + 排查中新发现"的并集。

---

## 3. 按根因分类归纳

### 3.1 硬编码假设（R3-01/02/03/05/06 + S1–S6）
**共性**：把"当前这批数据的命名/路径/版本"写成常量。修复方式总是"从产物推断"（wheel 文件名推断版本、内容识别 trial 目录、环境变量覆盖路径），但**修一处漏一片**：`instance_` 在 4 处主链路修了，执行/分析/体检的 15 处没修。教训：**同一假设一旦出现，必须全仓 grep 清除并加一条反例测试**（用非 `instance_` 的合成 trial 目录跑一遍）。

### 3.2 口径不一致（R3-07~13 + S7/S8/S11）
**共性**：同一事实存在多个消费者（`final_summary` / `formal` / `strict_compare` / `analysis`），各自实现一遍判定逻辑，然后分叉。R3-09 修好后，`strict_compare` 仍在 `patch 缺失 → 计通过` 与 `reward 字符串比较` 上偏离 `formal.py`。教训：**判定逻辑只应有一个实现**（`formal.classify_missing`/`Trial.observed`），其余工具 import 它，不要复制。

### 3.3 幂等性（R3-14~18）
**共性**：所有"重跑"路径都曾假设"目录不存在"或"产物只有一种"。已修的三处（安装证据目录、阶段1 skip、collect_pending）都采用了同一模式：**用"显式终态"代替"文件存在性"**。遗留：`run_formal_240` 的归档判据在新题库上仍会误归档（S1）。

### 3.4 编码与换行（R3-19~21）
**共性**：Windows 写脚本给 Linux 执行时必须显式 `newline="\n"`；镜像内 Python 版本决定可用语法；PowerShell 管道编码决定中文输出。三条都已修，但**没有一条有回归测试**（转换器无测试文件）。

### 3.5 Python 版本兼容（R3-21、R3-02）
**共性**：评测侧（3.13）与镜像侧（3.8）语言特性不同；产品版本号在生产端与评测端各有一个来源。处置分别是"不用新语法"和"从产物推断"。

### 3.6 容器与网络（R3-22~29）
**共性**：绝大多数是**环境噪声伪装成模型能力**。代码侧的修复只有两处（nginx query 白名单、代理/NO_PROXY），其余靠运维规程。这类缺陷的复发风险最高，且最难在单次跑批中觉察。

### 3.7 并发与资源（R3-22/23/28）
**共性**：每 trial 2 个网络 + 2.26GB 验证器峰值 + WSL 7GB 上限，三者共同把并发压到 2–4。代码里没有资源感知调度（`AdaptiveSemaphore` 只在 `run_formal_240` 里，且阈值写死 6000/7000MB，见 S12 相关）。

### 3.8 静默失败（R3-30/31 + S9/S10/S12）
**共性**：`except (OSError, ValueError): return None` 是仓库里最普遍的写法，本意是"不让单个坏文件中断汇总"，实际后果是**坏文件被当作"没有证据"**，进而落入 `empty_patch`（= 失败）或 `unattributed`（= 不进分母）。两个方向都会扭曲结论，且日志里没有任何告警。

---

## 4. 仍存活的缺陷（重点）

> 每条含：判定、代码证据、只读复现、影响、建议、优先级。P0 = 会静默破坏数据或直接违反协议；P1 = 会产生错误结论；P2 = 诊断工具失效或可维护性风险。

### S1【P0】`run_formal_240` 的归档/skip 判据仍按 `instance_*` glob

- **代码**：`scripts/run_formal_240.py:196-198`（归档）、`:224-225`（skip）。
  ```python
  has_reward = list(job_dir.glob("instance_*/verifier/reward.txt"))
  has_terminal = list(job_dir.glob("instance_*/verifier/terminal.json"))
  has_patch = list(job_dir.glob("instance_*/agent/model.patch"))
  ```
- **复现**（只读，已执行）：
  ```
  pilot1 jobs=10  instance_* 判据命中(不会归档)=0  */ 判据命中=10
  → 用 run_formal_240.py 的现行判据：10/10 个已完成 job 会被判「无结果」
  ```
- **影响**：SWE-EVO 的 trial 目录是 `sweevo-...__<random>`，三个 glob 全空 → ① 加 `--skip-existing` 时**不跳过**，已完成 trial 被重跑（重复花费、撞 `request_sha256` 冲突）；② 不加时**归档分支把它们移进 `abandoned-<ts>/`**，等于把有效结果从统计目录删掉。`run_formal_240.py:309` 明确接受 `--sample` 任意题集，缺陷可触发。
- **建议**：改用 `_inner_dir` 式内容识别（同 `verify_patches.py:34-49`），并补一条用 `sweevo-*` 目录的测试。

### S2【P1】`execution._request_identity` 的 `source_job` 输入仍按 `instance_*` glob

- **代码**：`src/sayacode_bench/execution.py:326-333`。
- **复现**：对 pilot1 任取一 job 计算同样的字典 → `{}`（而 `*/` 版能得到 `result.json` 与 `model.patch` 两项）。
- **影响**：`request_sha256` 的 `input_artifacts.source_job` 恒为空 → **补丁内容不参与幂等身份**。同一目录补丁被改动后再跑，哈希不变 → 直接返回旧记录（违反"输入身份变化不得自动重跑"的注释约定）。对 SWE-bench 有 `instance_*` 命中而不显现，属**新题库才暴露的潜伏缺陷**。
- **建议**：复用内容识别；补测"同目录不同补丁 → 哈希不同"。

### S3【P0】`execution.replay_official_trial` 仍按 `instance_*` 找源 trial

- **代码**：`execution.py:487`（`raw_trials = list(source_job.glob("instance_*/result.json"))`）；`:506-507` 的报错文案也写死 "instance trial"。
- **复现**：同一 job → `raw_trials == []` → 函数走 `:494-505` 返回 `replay_status="missing_source_trial"`、`verified=False`。
- **影响**：任何**非 `instance_` 前缀**题集（SWE-EVO、ProMax 的 `promax/...`）若走库的 `replay_official_trial`（即 `study.run_phase` 的 SWE 强制重判链路），**永远无法通过独立重判**，`success` 恒为 None/False。当前正式跑批用 `locked_agents:PatchReplayAgent`（已修）绕开，但库路径未修，属于"两条链路一条好一条坏"。
- **建议**：与 S1 同步改为 `glob("*/result.json")`，并对"恰好一个"的约束保留；补单测。

### S4【P2】`artifact_replay` 仍按 `instance_*` 找便携工件

- **代码**：`src/sayacode_bench/artifact_replay.py:19`（`root.glob("instance_*/source.json")`）。
- **影响**：便携补丁工件（`ArtifactReplayAgent`）对非 `instance_` 题集找不到来源 → 抛"必须且只能包含一份真实来源说明"。
- **建议**：同 S1。

### S5【P1】`benchmark_health` 仍按 `instance_` 定位 trial

- **代码**：`scripts/benchmark_health.py:64-69`（`p.name.startswith("instance_")`）。
- **复现**：对 pilot1 10 个 job 执行同样语义 → `inner=None 10 / 找到 0`。
- **影响**：该脚本正是为"新题库选题/评级"写的（`c5f592f`），对新题库**输出空报告**而不报错 → 可能被误读为"没有可评估题目"。
- **建议**：改为内容识别，并在 `inner is None` 时显式 `print` 计数。

### S6【P2】12 个分析/工具脚本仍按 `instance_` glob

- **位置**（`grep -n "instance_" scripts/` 实证）：
  `analyze_trials.py:41`、`compare_trials.py:28`、`annotate_served.py:49`、`reconcile_results.py:60`、`reproduce_hypothesis_seed.py:100`、`verify_calibration_stability.py:27`、`diagnose_fixtures.py:175`、`regrade_calibration_patches.py:237,259`、`build_analysis_dataset.py:156`、`analyze_behavior.py:155`、`analyze_repeat_consistency.py:54`、`scripts/archive/summarize_formal.py:37`。
- **影响**：对旧题集正常，对新题集静默返回空/0。属诊断工具，不影响主成绩，但会让"新题库分析"得到错误结论。
- **建议**：抽一个 `find_trial_dir(job)` 公共函数（放 `locked_agents.py`），全部脚本 import 它；一次性清掉。

### S7【P1】`CANONICAL_MODEL` 两处仍不一致

- **代码**：`src/sayacode_bench/connections.py:11` 与 `execution.py:25` = `"DeepSeek-V4.1-Flash"`；`scripts/locked_agents.py:38` = `os.environ.get(..., "auto-hy3")`（`tests/test_locked_agents.py:28` 断言后者为 `auto-hy3`）。
- **复现**（已执行）：`connections.CANONICAL_MODEL=DeepSeek-V4.1-Flash`、`execution.CANONICAL_MODEL=DeepSeek-V4.1-Flash`、`locked_agents.CANONICAL_MODEL=auto-hy3`。
- **影响**：`run_formal_240.py:242` 显式传 `auto-hy3` → `normalized.json:canonical_model="auto-hy3"`；`study.run_phase` 不传 → 走 `execution.py:365` 默认 `"DeepSeek-V4.1-Flash"`。同一仓库两条链路产出**两种模型身份**，`analysis.py:201` 的 `model_mismatch` 会把它们判成不一致；按 `study` 冻结路径跑时还会因 `manifest.canonical_model` 校验直接失败（RETROSPECTIVE §5.5.3 已预警，至今未修）。
- **建议**：删掉 `src/` 两处常量，改为从 profile/manifest 注入；或在 `execution.py` 顶部 import `connections.CANONICAL_MODEL` 并统一为 `auto-hy3`，同时更新 `docs/record-schema.md`。

### S8【P0】`MISSING_CLASSES` 与 PROTOCOL-V2 §3 不一致，且 `timeout` 不可达

- **代码**：`formal.py:35`
  ```python
  MISSING_CLASSES = ("no_job", "infra", "timeout", "empty_patch", "unverified", "model_fault", "unattributed")
  ```
  协议 `docs/PROTOCOL-V2.md` §3 表格为 6 类：`infra / no_job / timeout / empty_patch / model_fault / unverified`（无 `unattributed`）。
- **复现**（已执行）：
  - `timeout` 在元组里，但 `classify_missing`（`formal.py:464-476`）的返回分支只有 `no_job / infra / model_fault / empty_patch / unverified`；
  - `classify_missing(patch=None, exception_type="AgentTimeoutError")` → **`empty_patch`**；
  - `classify_missing(patch=100, exception_type="AgentTimeoutError")` → **`unverified`**；
  - `INFRA_EXCEPTIONS`（`:42-50`）不含 `AgentTimeoutError`/`CancelledError`。
- **影响**：直接违反协议"`timeout` 不补"条款——超时被记成可补的 `unverified`（有 patch）或不可补但归因错误的 `empty_patch`（无 patch）。同时 `unattributed` 是文档中没有的第 7 类。
- **建议**：① `classify_missing` 增加 `exception_type in {"AgentTimeoutError", "CancelledError"} → "timeout"`（或读 `normalized.json:status=="timeout"`）；② 协议与代码二选一：要么把 `unattributed` 写进 §3（注明"不进分母"），要么从 `MISSING_CLASSES` 移除；③ 补 `test_formal.py` 的 timeout 用例。

### S9【P1】读文件失败 → 静默当缺失（无告警）

- **代码**（`formal.py`）：
  | 函数 | 行号 | 失败返回 | 后果 |
  |---|---|---|---|
  | `_read_reward` | 205-212 | `None` | 有 reward 的 trial 被当无 reward → `unverified`/`empty_patch` |
  | `_read_exception_type` | 215-227 | `None` | `normalized.json` 损坏时 infra 判定失效 → 环境失败记成能力缺失 |
  | `_read_terminal` | 230-239 | `None` | 显式终态丢失 → 记成 `unverified`（可补） |
  | `_read_partial` | 242-253 | `None` | partial 静默丢失 |
  | `_read_inner_result` | 277-285 | `{}` | task 归不到计划项 → `unattributed` → 不进分母 |
  | `load_faults` | 187-202 | `{}` | `MODEL-FAULTS.json` 路径错/缺失 → 所有 `model_fault` 静默消失 |
- **影响**：与 S10 叠加时，**一个损坏文件可以让 trial 从分母消失或从"环境失败"变成"模型失败"**，且汇总里没有任何 `damaged` 计数（对比 `worker.py:640-720` 的审计有 `damaged_audit_lines`，`formal.py` 没有）。
- **建议**：每个读取函数返回 `(value, damaged: bool)` 或在 `summarize` 里累计 `unreadable_files` 计数并写进 `summary`；至少对 `json.JSONDecodeError` 不静默。

### S10【P1】`unattributed` 不进任何分母（违反"缺失按失败"）

- **代码**：`formal.py:557-559`（注释"只报告，不进入任何分母"）；`:489-493` 把 `task_id is None` 或 `repeat < 1` 的 trial 归入 `unattributed`。
- **影响**：协议 §2 要求"任何缺失按失败计入 planned"。无法映射的 job 既不进 planned（不在 `plan` 里）也不进 observed → 相当于**从统计中删除**。若归因逻辑出错（S9 的 `_read_inner_result` 返回 `{}`），整批数据会静默缩水。
- **建议**：`unattributed` 数量 >0 时置 `validity_issue` 并使 `final_result_eligible=False`；或把它们按任务名 best-effort 归入计划项后再判定。

### S11【P2】`strict_compare` 两处口径缺陷

- **代码**：
  - `scripts/strict_compare.py:132-136`：`patch is None` 时 `strict += 1`（**计为通过**）。严格口径应扣掉无法证明未改 snap 的 pass，这里方向相反，会**高估 strict**；
  - `:129`：`if reward not in ("1", "1.0")` → `reward.txt` 写 `1.00` 会被当失败；
  - `:86`：`job.rglob("reward.txt")` 递归任意深度，可能误取 agent 自己产物的同名文件。
- **影响**：strict 与 planned 的差值（snap 扣减）本应是"严格口径"的核心，此处误差方向系统性偏乐观。
- **建议**：`patch is None` 时判 `unknown` 并从 strict 分子分母同时剔除（或计为失败），并在报告里单列；reward 用 `float()` 解析。

### S12【P2】17 处裸 `except` / `except Exception:`（其中 2 处真吞）

- **位置**（`src/` + `scripts/`，本文 §8.3 全量列表）：
  - `src/sayacode_bench/network.py:142,228,327,424`：`except BaseException:` 后**重新 raise**（清理路径，可接受）；`:473` 记录 `cleanup_failed` 后继续（可接受但静默）；`:250` 记录错误后聚合抛出（可接受）。
  - **真吞**：`scripts/run_formal_240.py:48`（`container_mem_mb` → `return 0.0`，监控把"取不到内存"当"内存为 0"，可能误升并发）；`:162`（`mem_supervisor` 的 `except Exception: pass`，监控线程死掉无日志）。
  - 汇总/分析工具：`analyze_trials.py:34,76,96`、`annotate_served.py:26,35,57`、`compare_trials.py:34`、`diagnose_fixtures.py:320`、`regrade_calibration_patches.py:525`、`reproduce_hypothesis_seed.py:303`（多为"读坏行跳过"，静默但可接受）。
- **影响**：`:48` 的 0.0 会进入 EMA，若 `docker stats` 持续失败，并发会被拉到 `max_limit`；`:162` 的 pass 会让"内存护栏失效"不可见。
- **建议**：`container_mem_mb` 返回 `None` 并让调用方跳过该轮；`mem_supervisor` 用 `logger.warning` 至少记录一次。

### S13【P1】新题库路径无回归测试

- **证据**：`tests/test_formal.py:19-23` 的 `TASKS` 全部是 `instance_*`；`make_job`（`:53`）也造 `instance_` 目录。`46f57f0` 的 `git show --stat` 显示 **test-lines=0**。
- **影响**：S1–S6 这类回归无法被 CI 捕获；下次改判定逻辑会再次静默失败。
- **建议**：在 `test_formal.py`/`test_verify_patches.py` 各加一个 `sweevo-demo__x1` 目录的用例（formal 的 `_inner_dir`/`_match_task_by_job_name`；verify_patches 的 `_inner_dir`/`collect_pending`），并给 `run_formal_240` 的归档判据抽函数后单测。

### S14【P3】文档状态自相矛盾（LESSONS §六）

- **证据**：`docs/LESSONS-20261102-v2.md:171` 写「`verify_patches.collect_pending` 只认 stage1 reward。→ **仍未修**」，而同一文件 `:99` 与 `AGENTS.md:53` 写「已修（2026-11-05）」，代码 `verify_patches.py:110,120-122` 确实已修并有 `tests/test_verify_patches.py`。
- **影响**：接手者按 §六 会被误导去"再修一遍"。
- **建议**：删除 `:171` 的"仍未修"，改为"已修 `c4a552e`"。

### S15【P2】`run_formal_240.py` 的内存阈值与机器绑定

- **代码**：`scripts/run_formal_240.py:121-122`（`TARGET_MEM_MB=6000`、`HARD_CEIL_MB=7000`）、`:139-150`（3000/4000/5000 三档）。
- **影响**：换机器（8GB/16GB/32GB VM）后阈值全错；结合 S12 的 `except → 0.0`，可能出现过早降并发或护栏失效。
- **建议**：从 `docker info` 读 MemTotal 按比例算，或参数化并经 `FormalPaths` 注入。

---

## 5. 硬性检查项逐项结论

| # | 检查项 | 结论 | 证据 |
|---|---|---|---|
| 1 | 全仓 `instance_` 前缀假设是否消除 | **否**。`src/` 4 个文件 15 行、`scripts/` 约 30 个文件 60 行命中；其中 **5 处仍是硬假设**（S1/S2/S3/S4/S5），另有 12 个分析脚本仍 glob。`formal.py`/`verify_patches.py`/`locked_agents.py` 的主链路已改为内容识别并保留前缀作为回退 | `grep -n "instance_" src scripts`（§8.1）；pilot1 复现 10/10 误判（S1） |
| 2 | `CANONICAL_MODEL` 两处是否仍不一致 | **是**。`DeepSeek-V4.1-Flash`（`connections.py:11`、`execution.py:25`）vs `auto-hy3`（`locked_agents.py:38`） | 运行时打印（§8.2 D4） |
| 3 | `MISSING_CLASSES` 与 PROTOCOL-V2 §3 是否一致 | **否**。代码 7 类 vs 协议 6 类（多 `unattributed`）；且 `timeout` 不可达，`AgentTimeoutError` 被归成 `empty_patch`/`unverified` | 运行时 `classify_missing` 四种输入（§8.2 D3） |
| 4 | 是否仍有"读文件失败 → 静默当 0 分/missing" | **是**。`formal.py` 5 个读取函数 + `load_faults`；`strict_compare.py:86-92` 同样 | §S9/S11；行号表 |
| 5 | 裸 `except` / `except: pass` | **有 17 处**（`src` 6、`scripts` 11）；其中 `run_formal_240.py:48,162` 是真吞，其余多为"坏行跳过"或"清理后重抛" | §8.3 全量列表 |

---

## 6. 回归测试覆盖评估

| 缺陷组 | 测试文件 | 覆盖情况 |
|---|---|---|
| 三口径/缺失分类/terminal | `tests/test_formal.py`（8.8K） | ✅ infra/model_fault/terminal 有；❌ **timeout 无**、❌ 非 `instance_` 命名无 |
| strict vs planned 一致 | `tests/test_strict_compare.py`（4.1K） | ✅ 合并口径；❌ 未覆盖 S11 的三处 |
| verify 续跑幂等 | `tests/test_verify_patches.py`（3.5K，6 例） | ✅ collect_pending 全覆盖 |
| locked_agents/patch 定位 | `tests/test_locked_agents.py`（4.0K） | ⚠️ 仅断言 `CANONICAL_MODEL=="auto-hy3"`；❌ 无 `_find_patch` 非 `instance_` 用例 |
| SWE-EVO 转换器 | 无 | ❌ 完全未测（CRLF/Py3.8/CI patch/pytest 格式） |
| 归档/skip 判据 | 无 | ❌ `run_formal_240` 无测试（S1 正是此处） |
| 静默读取 | 无 | ❌ |
| 裸 except | 无 | ❌ |

**结论**：口径类缺陷（第一波）已有较好回归；**硬编码与静默失败类（第二波）几乎没有回归**，这正是存活缺陷集中在第二波的原因。

---

## 7. 建议的处理顺序

| 优先级 | 事项 | 理由 | 成本 |
|---|---|---|---|
| **P0-1** | 修 S1（`run_formal_240` 归档/skip 判据）+ S3（`replay_official_trial`）+ S8（`timeout` 分类） | 三者分别会**丢数据**、**让新题库无法重判**、**直接违反协议** | 各 5–20 行 + 1 个测试 |
| **P0-2** | 修 S2（`_request_identity` 补丁身份） | 幂等判据失效会让"补丁被换"不被发现 | 5 行 |
| **P1-1** | 统一 `CANONICAL_MODEL`（S7） | 两条链路模型身份分叉，`study` 路径直接失败 | 10 行 + 文档 |
| **P1-2** | 抽 `find_trial_dir()` 并替换 S4/S5/S6 的 15 处 | 一次性清掉 `instance_` 假设 | 30 行 + 脚本批量改 |
| **P1-3** | 给 `formal.py` 读取函数加 `damaged` 计数（S9）+ `unattributed` 置失效（S10） | 静默失败会让结论偏乐观 | 30 行 |
| **P1-4** | 补新题库命名回归测试（S13） | 防止再次回归 | 2 个用例 |
| **P2** | S11/S12/S15 与文档（S14） | 可维护性 | 各 10 分钟 |

---

## 8. 附录

### 8.1 `instance_` 全仓命中（`grep -n "instance_"`）

- **`src/sayacode_bench/`（4 文件 15 处）**：`artifact_replay.py:19`（硬假设）、`execution.py:330,487`（硬假设）、`formal.py:64,65,154,307,315,322,328,353,361`（说明/兼容/回退）、`pilot_carry.py:32`（固定历史路径）、`sources.py:279`（SWE-bench 解析正则，合理）。
- **`scripts/`（约 30 文件 60 处）**：硬假设见 S1/S2/S3/S5/S6；其余为 `task_id.replace("instance_","")` 之类的**兼容写法**（非假设，但依赖前缀才正确）。

### 8.2 只读复现脚本输出（`prove_surviving_defects.py`，宿主 `.venv` Python 3.13.12 + harbor 0.24.0）

```
=== D1/D2 instance_ 前缀假设（run_formal_240 归档/skip 判据）===
[job] sayacode-sweevo-dask-dask-2022-9-2-2022-10--r1
[instance_* 判据] {'reward': 0, 'terminal': 0, 'patch': 0}
[*/ 判据]         {'reward': 0, 'terminal': 0, 'patch': 1}
[_request_identity source_job inputs（instance_*）] {}
[_request_identity source_job inputs（*/）] {'sweevo-...__R2jYLdj\\result.json': 5481,
                                              'sweevo-...__R2jYLdj\\agent\\model.patch': 2595}
[replay_official_trial raw_trials（instance_*）] []

=== D3 MISSING_CLASSES vs PROTOCOL-V2 §3 ===
['no_job','infra','timeout','empty_patch','unverified','model_fault','unattributed']  (7)
INFRA_EXCEPTIONS = ['DockerError','EnvironmentSetupError','ImageNotFoundError',
                    'NetworkConnectError','NonZeroAgentExitCodeError']
classify_missing(无patch+AgentTimeoutError) = empty_patch
classify_missing(有patch+AgentTimeoutError) = unverified
classify_missing(无patch+NonZeroAgentExitCodeError) = infra
PROTOCOL-V2 §3 = ['infra','no_job','timeout','empty_patch','model_fault','unverified']  (6)
差集：代码有文档无 = ['unattributed']；文档有代码不可达 = ['timeout']

=== D4 CANONICAL_MODEL ===
connections.py:11 = DeepSeek-V4.1-Flash
execution.py:25   = DeepSeek-V4.1-Flash
locked_agents.py:38 = auto-hy3

=== D6 裸 except 计数 ===
src+scripts = 17（明细见 §8.3）

=== pilot1 全量归档判据 ===
pilot1 jobs=10  instance_* 命中=0  */ 命中=10
→ 10/10 已完成 job 会被现行判据判「无结果」
```

### 8.3 裸 `except` 全量位置

```
src/sayacode_bench/network.py:142,228,327,424   except BaseException:（清理后重抛，可接受）
src/sayacode_bench/network.py:250               except Exception as error:（聚合后 raise，不计入 17）
src/sayacode_bench/network.py:473               except Exception:（记 cleanup_failed，静默）
scripts/run_formal_240.py:48                    except Exception: return 0.0   ← 真吞
scripts/run_formal_240.py:162                   except Exception: pass         ← 真吞
scripts/analyze_trials.py:34,76,96              except Exception:（坏行跳过）
scripts/annotate_served.py:26,35,57             except Exception:（坏行跳过）
scripts/compare_trials.py:34                    except Exception:（坏行跳过）
scripts/diagnose_fixtures.py:320                except BaseException:（清理后重抛）
scripts/regrade_calibration_patches.py:525      except BaseException:（清理后重抛）
scripts/reproduce_hypothesis_seed.py:303        except BaseException:（清理后重抛）
```

> 精确匹配 `except Exception:` / `except BaseException:` / `except:` 的共 17 处；带 `as` 的 4 处（`network.py:250`、`execution.py:432`、`installation.py:245`、`worker.py` 若干）会记录类型后继续，未计入。

### 8.4 相关 commit 索引（`git log --since=2026-10-28`）

| commit | 日期 | 主题 | 触及缺陷 |
|---|---|---|---|
| `46f57f0` | 11-06 | SWE-EVO 试点跑通，修 4 处 `instance_` 假设 | R3-01（部分） |
| `c4a552e` | 11-05 | verify 重跑不再重排已完成 trial | R3-17 |
| `43f5c31` | 11-05 | 大评测集缩到 100 题 + 抽样死循环 | 新增（未入台账主表，属功能缺陷） |
| `6ffe7f5` | 11-05 | 三个真实口径缺陷 + 模型身份更正 | R3-08（部分）/R3-09/R3-13 |
| `c0b0cf6` | 11-04 | strict_compare 严格口径 | R3-09（引入） |
| `55e922c` | 11-04 | 换 Claude Code + 修 nginx query 400 | R3-27 |
| `84bc815` | 11-04 | Codex 组作废 + mini 安装链修复 | R3-29/R3-26 |
| `352541d` | 11-04 | 3.2.6 安装三坑 | R3-02/R3-26 |
| `14680d3` | 11-03 | 无 curl/wget 时 pip3 装 uv | R3-26 |
| `ab3a4b7` | 10-31 | 三口径分母/缺失分类/空 patch 终态/收编仓外依赖 | R3-07/R3-16/R3-05 |
| `5f8b138` | 10-31 | 阶段1 续跑认 normalized | R3-15 |
| `a1e51d3` | 10-31 | 版本从 wheel 文件名推断 | R3-02 |
| `5c59126` | 10-31 | 安装证据目录清空重建 | R3-14 |
| `f393346` | 10-31 | 三 agent 输出预算统一 32000 | R3-03 |
| `b7c42a8` | 11-05 | 全量轨迹适配审计 | R3-30 |
| `c5f592f` | 11-06 | 题库体检器 | S5（该脚本自身有缺陷） |
| `21b2701` | 11-06 | SWE-EVO 转换/基线/组题 | R3-06/R3-19/R3-21 |
| `7e8b42c` | 11-03 | reconcile_results + lint_metrics（16 测试） | 新工具 |
| `0744741` | 11-03 | 预置 uv installer | R3-26 |

### 8.5 证据文件

- 复现脚本：`C:\sb\tmp\explore\trajectory\prove_surviving_defects.py`（只读，可重复执行）
- 数据样本：`C:\sb\newset\runs\pilot1\sayacode\jobs`（SWE-EVO 10 trial，用于 S1/S2/S3/S5 复现）
- 旧数据：`C:\sb\hard\v2-325`（四组 240+ trial，用于 R3-07/08/09）
- 仓库：`C:\develop\sayacode-bench`，HEAD `46f57f0`

---

## 9. 结论

第一波（口径）缺陷的修复质量高：有回归测试、有实测证据、文档回填。第二波（硬编码与静默失败）修复呈现"**只见症状、未清同类**"的特征：SWE-EVO 接入时按症状修了 4 处，但同一假设仍在 15 处存活，且**无一条新增回归测试**。因此本报告的核心结论是：

> 评测基建当前的风险不在"已知缺陷"，而在"**同类的未知副本**"——建议按 §7 的 P0-2/P1-2 做一次全仓扫描与公共函数收敛，再用非 `instance_` 命名的合成数据补测试，把这类缺陷从"每次接新题库都要重新发现"变成"CI 能拦住"。
