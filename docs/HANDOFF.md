# HANDOFF：SAYACODE Bench 交接（2026-11-07）

> 接手者必读。本文件说明**当前进度、关键事实、环境、坑、下一步**。
> **数字与口径以 [2026-11-07 复盘](review/2026-11-07/RETROSPECTIVE-20261107.md) 为准**；本文件已按其结论修订，`strict` 口径已废除。
> 配套：[STATUS](STATUS.md)（状态）、[PROTOCOL-V2](PROTOCOL-V2.md)（协议）、[四组结果](FORMAL-RESULTS-20261105-v3.md)（strict 部分作废）、[踩坑](LESSONS-20261102-v2.md)。

## 1. 当前进度（一句话）

**v4 已完成：40 题 × 2 重复 × 4 个可用基线，`planned` 口径（分母 80、缺失按失败）——SAYACODE 3.2.7（PyPI）76.2%、3.2.5（本地 wheel）78.8%；mini-swe 85.0%、Claude Code 77.5%、OpenCode 75.0%。SAYACODE 与三个基线的题级差异未检出统计显著性（p ≥ 0.070）。`strict` 口径已废除；四组混两个批次，跨批次只能做描述性对照。Codex 组整组作废。v1 结论仍作废。**

| agent | planned | observed | 缺失 | 批次 | 备注 |
|---|---|---|---|---|---|
| SAYACODE 3.2.7 | **76.2%** (61/80) | 77.2% | 1 | v4-327（11-06）| PyPI 可获取制品；served 零 `hy3-x` |
| SAYACODE 3.2.5 | **78.8%** (63/80) | 79.7% | 1 | v2-325（11-02）| 本地 wheel，PyPI 未发布 |
| mini-swe | 85.0% (68/80) | 86.1% | 1 | v2-325 | 含补跑 12 条（补跑前 70.0%）|
| Claude Code | 77.5% (62/80) | 78.5% | 1 | v2-325 | Anthropic 自家调优 |
| OpenCode | 75.0% (60/80) | 75.0% | **0** | v2-325 | provider-agnostic 开源 |
| ~~Codex~~ | 68.8% | 69.6% | — | v2-325 | **整组不可比** |

> `strict` 列（80.0 / 73.8 / 67.5 / 78.8）与 snap pass（4/3/6/0）**已于 2026-11-07 全部废除**：verifier 判分前会重置测试数据面（含 `__snapshots__`），"靠改快照通过"是错误归因。详见 [复盘 §四.1](review/2026-11-07/RETROSPECTIVE-20261107.md)。

## 2. 接手先读（按顺序）

1. **[2026-11-07 复盘](review/2026-11-07/RETROSPECTIVE-20261107.md)**：必须撤回的五件事、三分法结论账本、五类缺陷、P0/P1/P2。**与它冲突的旧文档以它为准。**
2. [STATUS](STATUS.md)：当前数字、制品身份、局限、下一步。
3. [PROTOCOL-V2](PROTOCOL-V2.md)：planned 分母、缺失分类、补跑规则（口径条款待按复盘修正）。
4. [FORMAL-RESULTS-20261105-v3](FORMAL-RESULTS-20261105-v3.md)：四组 planned/observed、六组 McNemar；**strict 部分作废**。
5. [LESSONS-20261102-v2](LESSONS-20261102-v2.md)：真实踩过的坑（现象/根因/处置/预防）。

## 3. 关键事实（别搞错）

1. **分母统一 `planned` 80**（缺失按失败）= 主报口径；`observed` 只作辅助（**必须标注幸存者偏差**）；**`partial` 为新增口径**（`verifier/output.json` 的逐测试通过比例，已在 `FINAL-SUMMARY-327.json` 里，但尚未进主汇总管线）。**`strict` 已废除**。
2. **测试面只有一个事实**：verifier 判分前重置测试**代码**与测试**数据面**（`tests/`、`testdata/`、`fixtures/`、`__snapshots__/*.snap` 等，`tests/test.sh:97-105`，642/642 个任务一致）。因此任何 agent 改测试/快照都**不影响评分**；「snap pass」「strict 口径」全部作废，不要再引用。
3. **制品身份是双批次**：SAYACODE **3.2.7 = PyPI 可获取**（`C:\sb\hard\v4-327`，planned 76.2%）；**3.2.5 = 本地构建、PyPI 从未发布**（`C:\sb\hard\v2-325`，planned 78.8%）。两者 Δ −2.6pp、p=0.8145（不显著）。**不要再说"所有 SAYACODE 数字跑的是 3.2.5"**。
4. **40 题是开发迭代集**，不是 holdout；SAYACODE 的提示词规则从这套题的失败个案调出来 → 偏置方向对 SAYACODE 有利。**独立 holdout 从未执行；冻结签收（`lock_candidate`）也从未执行**——按 [PROTOCOL-V2](PROTOCOL-V2.md) §1，严格意义上尚无"对外正式成绩"。
5. **题集饱和是观测，不是结论**：饱和题 26/40（DEEP-ANALYSIS）或 28/40（`health.md`），有区分度 8 或 4 题；2–3 题环境性不可过。"题太浅导致无判别力"是**待检验假设**（`EXPERIMENT-CONTEXT-AB` 设计已就绪但**未跑**），不是已证事实。
6. **重复 2 次不足以消除系统性方差**（一过一败 5 题里 3 题系统性，patch 规模差 3.3×/7.3×/59×；每组另有 2–7 题 r1/r2 翻转）。
7. **`task_count` 全 0**：这批题不触发多 agent；交叉验证用 `evals/scenarios/collaboration-autonomous.jsonl`（已单题验证 team `task_count=2`）。
8. **补跑效应大**：SAYACODE 67.5%→78.8%（+11.3pp）、mini-swe 70.0%→85.0%（+15.0pp，v2 阶段另有 47.5%→70.0%）；补跑前数字不能当能力。
9. **SWE-EVO 试点有选择偏差**：usable 只有 4 条且全是 dvc 1–2 文件小题，唯一重题（dask，50 文件/1525 行）是强制纳入且 **0/2**；pilot 的 50%（5/10）**不能支撑"新题库更难"**。详见 [PILOT](PILOT-SWE-EVO-20261106.md) §5。
10. **跨批次不可比**：SAYACODE 行来自 v4-327、三基线来自 v2-325，served 分布（14.3% `hy3-x` vs 0%）、并发（2–4 vs 4/1）与网络修复状态都不同——只可描述性并列。

## 4. 作废（不要引用）

- v1 的 68.8 / 86.2 / 86.2（三套分母并列；Codex 实为 56/65 → 70.0%）。
- 「改测试率 49% / 73% / 42%」（两个口径混用：产品侧检测率 vs patch 含测试文件）；**以及任何"snap pass"计数**。
- **`strict` 口径全部数字**（80.0 / 73.8 / 67.5 / 78.8）及"三种口径三种排名"叙事——前提被证伪（2026-11-07）。
- **跨批次 McNemar 的 p 值**（`STATUS` §2.1 后三行）——批次效应混入，不可解释。
- 「3 条模型故障」（只有 1 条真：`vuls-f6cc8c-r1` ECONNRESET）、「40 题 gold 全绿」（36 good / 1 bad / 3 null）。
- Codex 的 68.8% / 65.0%（整组适配失效，见 [CODEX-BASELINE-INVALID](CODEX-BASELINE-INVALID.md)）。
- 「OpenCode 有自家模型 / 模型错配」（事实错误，它是 provider-agnostic）。
- 「3.2.6/3.2.7 三项修复无效果」——作用面为零，Δ 没有信息量（见 [R4](review/2026-11-07/R4-product-fixes.md) §1–§3）。
- 「检测 10pp 需 330 题」——无出处，改为"未量化"。

完整清单见 [2026-11-07 复盘](review/2026-11-07/RETROSPECTIVE-20261107.md) §摘要。

## 5. 环境与路径

| 项 | 路径/值 |
|---|---|
| 仓库 | `C:\develop\sayacode-bench`（remote: `saya-ch/sayacode-bench`）|
| 结果根（3.2.5 期）| `C:\sb\hard\v2-325\`（三基线 + SAYACODE 3.2.5：`FINAL-SUMMARY-V4.json`、`STRICT-COMPARE.json`［strict 已废］、`TRAJ-AUDIT-*.json`、`logs\`）|
| 结果根（3.2.7）| `C:\sb\hard\v4-327\`（`FINAL-SUMMARY-327.json`、`STRICT-COMPARE-327.json`［strict 已废］）|
| v1 结果（历史）| `C:\sb\hard\formal-240\` |
| SWE-EVO 试点 | `C:\sb\newset\runs\pilot1\`（10 trial）|
| 题集 | `studies/sample-40-final.json`（40 题开发迭代集）；新题库 `studies/large-sample-v1.json`（100 题，未开跑）|
| 任务缓存 | `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\v2\tasks`（642 题）|
| 评测制品 | 3.2.7：PyPI `sayacode-3.2.7-py3-none-any.whl`；3.2.5：`C:\sb\tmp\hard\wheel-release-3.2.5\out\sayacode-3.2.5-py3-none-any.whl`（`scripts/locked_agents.py:48`）|
| 产品仓库 | `C:\develop\sayacode`（HEAD `41b1e38`；PyPI 最新 3.2.7，但 **3.2.7 无对应 git tag**）|
| 模型 | hy3（`auto-hy3`），Magpie `127.0.0.1:3425/v1`，容器内 `saya-model-gateway:8080` |
| 上下文 / 输出 | 192k；`max_output_tokens=32000`；**SAYACODE 摘要触发约 150.4k**（`min(160000−9600, 192000×0.8)`，不是文档常写的 153.6k）|
| 并发 | 轻题 **2–4**（内存约束）/ 网络池上限 **6** / 重题（vuls）**1** |
| 关键脚本 | `run_formal_240.py`（stage1）、`verify_patches.py`（verify）、`strict_compare.py`（**仅 planned/observed 可用**）、`audit_agent_traj.py`（轨迹审计）、`split_sample.py`（重题分片）、`final_summary.py`（汇总）、`verify_task_baseline.py`（新题库基线验证）|

## 6. 坑清单（逐条都踩过）

1. **stage1 与 verify 不要并行**：验证器峰值 2.26GB，并行会互相挤内存、留未收尾 job。
2. **续跑判据必须对齐产物**：stage1 `--skip-verifier` 阶段没有 reward，skip 要认 `normalized.json` 的 `record_complete=True`（已修 `5f8b138`）。
3. **归档清单 = retry sample 同源**：先列 job → 生成 sample → 归档，核对数量。
4. **`verify_patches.collect_pending` 曾只认 stage1 reward**（已修 2026-11-05）：现在同时认 `verify/jobs/verify-<job>` 的 `reward.txt` / `terminal.json`，回归见 `tests/test_verify_patches.py`。但**非 `instance_` 命名的题库仍未覆盖**（见坑 18）。
5. **Docker 网络池耗尽**：每 trial 占 2 个网络，池约 17；跑前 `docker network prune -f`。**并发按"轻题 2–4（内存约束）/ 网络池上限 6 / 重题 1"执行**，不要再单独写"≤6"。
6. **Docker 崩溃 / WSL OOM**：宿主 15.6GB、`.wslconfig` 7GB。**vuls 单题 3.3GB，并发 2 会静默 OOM（日志只剩心跳）** → 用 `split_sample.py` 分片 + 重题并发 1。
7. **vhdx 不自动收缩**：删镜像 C: 不会立刻变空；约 53GB 需 `diskpart` 的 `compact vdisk`。
8. **代理注入破坏内部网关**：`HTTP(S)_PROXY` 注入容器导致 `saya-model-gateway` 解析失败（gaierror）；`NO_PROXY` 必须含内部主机名与私网段，或直接移除代理让容器直连。
9. **apt 502 / DNS 假 IP**：Clash TUN + fake-ip 让 apt 源走代理返回 502；profile 的 `prepend` 加 `DOMAIN-SUFFIX,debian.org,DIRECT` 等（Merge.yaml 的 `prepend-rules` 不生效）。**另有 CNAME 陷阱：`deb.debian.org → debian.map.fastlydns.net`，`*.fastlydns.net` 只匹配一级子域，必须写 `+.fastlydns.net`。**
10. **nginx 精确路径白名单曾拦 `?args`**：`if ($args != "") { return 400; }` 让 Claude Code 的 `?beta=true` 首个请求即 400（全组 0 通过）→ 已从 `network.py` 移除。
11. **Debian 12 PEP 668**：`pip3 install` 被拒，需 `--break-system-packages`。
12. **uv 下 CPython 3.12 走 GitHub 会超时**：宿主预下载 tarball，上传解压到 `/opt/uv-python`。
13. **别用会漂移的 `auto/...` 别名**：40% 落到 glm；用 `auto-hy3` 并逐 trial 记录 served/provider。
14. **别把 context_length 配小**：hy3 实际 192k；曾误配 65536 导致长任务早摘要。
15. **报告 pass@1 必须带 Wilson CI、样本量与分母口径**；只说「通过率 x%」会误导。
16. **只看 `exception.txt` 会低估适配缺陷**：必须全量轨迹审计（`audit_agent_traj.py`）——Codex 组就是靠它才判出整组失效。
17. **PowerShell 引号地狱 / 进程自杀**：复杂 `python -c` 写成 .py；`Where-Object` 匹配 watchdog 会匹配自己，用 `-like '*watchdog.ps1*' -and $_.ProcessId -ne $PID`。
18. **`instance_` 前缀假设仍有 15 处存活**（`src/` 4 个文件 15 行；`scripts/` 约 60 行命中）：`run_formal_240.py:196-198,224-225` 的归档/skip 判据、`execution.py:487` 的重判、`benchmark_health.py:65` 的体检、`artifact_replay.py:19` 等。**换非 `instance_` 命名的题库（SWE-EVO / ProMax）会静默丢数据或判 `no_job`**；SWE-EVO 实测 10/10 个已完成 job 被判"无结果"。`46f57f0` 只修了 4 处且无回归测试。
19. **新题库基线验证会系统性偏向小题**：大改动题 p2p 多、镜像大 → 基线失败概率高 → 被判 `broken`/`fake` 剔除 → usable 集偏向小改动题。**选样必须按 gold 改动量分层，不能用 usable 全集**（见 [ONBOARDING](NEW-BENCHMARK-ONBOARDING.md) §5）。

## 7. 下一步（按 2026-11-07 复盘 §七）

> 排序原则：**先止血（撤回错误结论）→ 再修工具 → 最后才扩样（生产新数字）**。**P0 完成前不启动任何新跑批。**

### P0｜止血（1–2 天，纯文档与口径，不跑模型）

1. **撤回 `strict` 口径**：`STATUS` / `v3` / `PROTOCOL-V2 §5.1` / `TEST-EDIT-ANALYSIS` 全部改为"verifier 重置测试面（含快照）；`strict` 因前提错误作废"。若要保留描述列，改名 `touches_snap_pass` 并明确它不是能力指标。
2. **口径体系**：`planned`（主报）+ `observed`（辅助，标幸存者偏差）+ **新增 `partial`**（逐测试通过比例，数据已在 `FINAL-SUMMARY-327.json`）。
3. **撤回/修正五条对外表述**（复盘摘要表），特别是 `v3.md:136` 的简历口径：加"开发集、非冻结、跨批次不可比"三重限定，或改用 `planned` 并删排名。
4. **建立单一真相源** `docs/RESULTS-LEDGER.md`，其余文档改为引用。
5. **补齐 327 报告三处硬错误**：三项修复 → 两项；`41b1e38` 移出制品清单；补 worst/best 界。

### P1｜修工具（2–3 天，不跑模型）

6. **修三个 P0 存活缺陷**：抽象 `find_trial_dir()` 收敛 15 处 `instance_` 假设；给 `classify_missing` 加 `timeout` 分支；统一 `CANONICAL_MODEL`。**每项都要补非 `instance_` 命名的合成测试**。
7. 修 `strict_compare.py:132-136`（找不到 patch 即计为通过，方向反了）。
8. 给所有汇总产物写入生成元数据（脚本 SHA + 数据根 mtime），`STRICT-COMPARE.json` 重新生成。
9. 补 v3 的补跑前后同表（327 报告写"无补跑"）。
10. 修 4 项产品存活缺陷（`error_type` 覆盖 `exit_code≠0`/`timed_out`、检索限流 20k 真正生效、保留原始任务消息、文档 153.6k → 150.4k）。

### P2｜生产新证据（需跑模型）

11. **SWE-EVO 扩到 20 题，但先解决选择偏差**：42 个非 ghcr 题**全部**跑基线；按 gold 改动量分层抽样（1–2 / 3–5 / 6–10 / 11+ 文件），不用 usable 全集；记录每题剔除原因与规模。
12. **长上下文 A/B**（`EXPERIMENT-CONTEXT-AB` 设计就绪、工具已写、钩子未注入）：当前**唯一**能检验摘要修复路径的实验。
13. P0/P1 完成后再决定是否重跑旧 40 题；当前不建议（饱和 + 测量面与产品改动不重叠）。

**明确不做**：补跑 Codex、在 40 题上加重复、跨批次排名、在冻结签收执行前输出"对外正式成绩"。

## 8. 结果文件清单

| 文件 | 内容 |
|---|---|
| `C:\sb\hard\v4-327\FINAL-SUMMARY-327.json` | **SAYACODE 3.2.7（PyPI）** 逐 trial 汇总（当前权威）|
| `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json` | 三基线 + SAYACODE 3.2.5 逐 trial 汇总 |
| `C:\sb\hard\v2-325\STRICT-COMPARE.json` | **strict 列已废**，仅 planned/observed 可用 |
| `C:\sb\hard\v2-325\TRAJ-AUDIT-{claude-code,opencode}.json` | 轨迹级适配审计 |
| `C:\sb\hard\v2-325\FINAL-SUMMARY.json` | v2 三组历史明细 |
| `C:\sb\hard\formal-240\` | v1 历史结果（不补跑，不引用）|
| `C:\sb\newset\runs\pilot1\` | SWE-EVO 试点（10 trial，有选择偏差）|

## 9. 一句话交接

**四组都跑完了：planned 下 3.2.7 = 76.2%、3.2.5 = 78.8%、mini-swe 85.0%、Claude Code 77.5%、OpenCode 75.0%，两两不显著；`strict` 口径已因前提被证伪而废除，四组还混两个批次。真正的问题不是"谁更强"，而是：题集饱和（26–28/40 饱和）、制品双批次、没有 holdout、冻结签收从未执行。下一步严格按复盘 P0 → P1 → P2 走，P0 完成前不跑新批。**
