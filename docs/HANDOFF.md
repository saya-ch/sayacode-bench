# HANDOFF：SAYACODE Bench 交接（2026-11-05）

> 接手者必读。本文件说明**当前进度、关键事实、环境、坑、下一步**。
> 数字以 [STATUS](STATUS.md) 为准；历史演进与作废清单见 [RETROSPECTIVE](RETROSPECTIVE-20261105.md)；协议见 [PROTOCOL-V2](PROTOCOL-V2.md)；四组结果见 [FORMAL-RESULTS-20261105-v3](FORMAL-RESULTS-20261105-v3.md)；踩坑见 [LESSONS-20261102-v2](LESSONS-20261102-v2.md)。

## 1. 当前进度（一句话）

**v4 已完成：40 题 × 2 重复 × 4 个可用基线（SAYACODE / mini-swe / Claude Code / OpenCode），同一运行根 `C:\sb\hard\v2-325`；planned 78.8% / 85.0% / 77.5% / 75.0%，strict 78.8% / 80.0% / 73.8% / 67.5%，两两 McNemar 全部不显著（p ≥ 0.070）。Codex 组整组作废。v1 结论仍作废。**

| agent | planned | strict | 缺失 | snap pass | 备注 |
|---|---|---|---|---|---|
| SAYACODE | **78.8%** (63/80) | **78.8%** | 1 | 0 | 本地 3.2.5 wheel |
| mini-swe | 85.0% (68/80) | 80.0% | 1 | 4 | 模型无关最简脚手架 |
| Claude Code | 77.5% (62/80) | 73.8% | 1 | 3 | Anthropic 自家调优 |
| OpenCode | 75.0% (60/80) | 67.5% | **0** | **6** | provider-agnostic 开源 |
| ~~Codex~~ | 68.8% | 65.0% | 1 | 3 | **整组不可比** |

## 2. 接手先读（按顺序）

1. [RETROSPECTIVE](RETROSPECTIVE-20261105.md)：六个阶段怎么走到这里，哪些结论作废了。
2. [STATUS](STATUS.md)：当前数字、制品身份、局限、下一步。
3. [PROTOCOL-V2](PROTOCOL-V2.md)：planned 分母、缺失分类、补跑规则。
4. [FORMAL-RESULTS-20261105-v3](FORMAL-RESULTS-20261105-v3.md)：四组三口径、六组 McNemar、适配健康度。
5. [LESSONS-20261102-v2](LESSONS-20261102-v2.md)：真实踩过的坑（现象/根因/处置/预防）。

## 3. 关键事实（别搞错）

1. **分母统一 planned 80**；**三口径必须同报**（planned / observed / strict），因为三种口径给出三种排名。不给单一排名。
2. **strict = planned 扣掉「改 `.snap` 快照换来的 pass」**：verifier 重置测试**代码**，但 `__snapshots__/*.snap` 不重置。snap pass：SAYACODE 0 / mini-swe 4 / Claude Code 3 / OpenCode 6。
3. **制品身份**：SAYACODE 数字跑的是**本地构建的 3.2.5 wheel**；PyPI 上是 3.2.4 → **3.2.7**（3.2.5/3.2.6 从未发布）。产品 HEAD 已含 3 个版本修复，**都未进被测制品**。
4. **40 题是开发迭代集**，不是 holdout；SAYACODE 的提示词规则从这套题的失败个案调出来 → 偏置方向对 SAYACODE 有利。**独立 holdout 从未执行。**
5. **题集太浅**：中位 2 文件 / 64 行；SWE-EVO 平均 21 文件、ProMax 11.4 文件/261.6 行。四组压在 67.5–80.0% 是题的问题，不是"模型都差不多"的证据。
6. **重复 2 次不足以消除系统性方差**（一过一败 5 题里 3 题系统性，patch 规模差 3.3×/7.3×/59×）。
7. **`task_count` 全 0**：这批题不触发多 agent；交叉验证用 `evals/scenarios/collaboration-autonomous.jsonl`（已单题验证 team `task_count=2`）。
8. **补跑效应大**：SAYACODE +11.3pp、mini-swe +22.5pp 都发生过；补跑前数字不能当能力。

## 4. 作废（不要引用）

- v1 的 68.8 / 86.2 / 86.2（三套分母并列；Codex 实为 56/65 → 70.0%）。
- 「改测试率 49% / 73% / 42%」（两个口径混用：产品侧检测率 vs patch 含测试文件）。
- 「3 条模型故障」（只有 1 条真：`vuls-f6cc8c-r1` ECONNRESET）、「40 题 gold 全绿」（36 good / 1 bad / 3 null）。
- Codex 的 68.8% / 65.0%（整组适配失效，见 [CODEX-BASELINE-INVALID](CODEX-BASELINE-INVALID.md)）。
- 「OpenCode 有自家模型 / 模型错配」（事实错误，它是 provider-agnostic）。

完整清单见 [RETROSPECTIVE](RETROSPECTIVE-20261105.md) §2.3。

## 5. 环境与路径

| 项 | 路径/值 |
|---|---|
| 仓库 | `C:\develop\sayacode-bench`（remote: `saya-ch/sayacode-bench`）|
| 结果根 | `C:\sb\hard\v2-325\`（v2/v3/v4 同根：`FINAL-SUMMARY-V4.json`、`STRICT-COMPARE.json`、`TRAJ-AUDIT-*.json`、`logs\`）|
| v1 结果（历史）| `C:\sb\hard\formal-240\` |
| 题集 | `studies/sample-40-final.json`（40 题开发迭代集）|
| 任务缓存 | `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\v2\tasks`（642 题）|
| 评测制品 | `C:\sb\tmp\hard\wheel-release-3.2.5\out\sayacode-3.2.5-py3-none-any.whl`（`scripts/locked_agents.py:48`）|
| 产品仓库 | `C:\develop\sayacode`（HEAD `41b1e38`；PyPI 最新 3.2.7）|
| 模型 | hy3（`auto-hy3`），Magpie `127.0.0.1:3425/v1`，容器内 `saya-model-gateway:8080` |
| 上下文 | 192k；`max_output_tokens=32000`；SAYACODE 摘要触发 153.6k |
| 关键脚本 | `run_formal_240.py`（stage1）、`verify_patches.py`（verify）、`strict_compare.py`（三口径）、`audit_agent_traj.py`（轨迹审计）、`split_sample.py`（重题分片）、`final_summary.py`（汇总）|

## 6. 坑清单（逐条都踩过）

1. **stage1 与 verify 不要并行**：验证器峰值 2.26GB，并行会互相挤内存、留未收尾 job。
2. **续跑判据必须对齐产物**：stage1 `--skip-verifier` 阶段没有 reward，skip 要认 `normalized.json` 的 `record_complete=True`（已修 `5f8b138`）。
3. **归档清单 = retry sample 同源**：先列 job → 生成 sample → 归档，核对数量。
4. **`verify_patches.collect_pending` 只认 stage1 reward（仍未修）**：verify 产物在 `verify/jobs/`，重跑会报冲突；临时做法是把 `verify/jobs/*/verifier/reward.txt` 同步回 stage1。
5. **Docker 网络池耗尽**：每 trial 占 2 个网络，池约 17；跑前 `docker network prune -f`，并发 ≤6。
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

## 7. 下一步（按优先级）

1. **还文档债**：本轮已更新 STATUS / README / HANDOFF / RETROSPECTIVE；剩余见 [RETROSPECTIVE](RETROSPECTIVE-20261105.md) §6（AGENTS.md 坑表、LESSONS 已修项标记）。
2. **用 3.2.7（或 HEAD 构建的 3.2.8）重跑 SAYACODE 单组 80 trial**：让数字对应可获取制品 + 首次给"修复有效性"证据。本地 ¥0，约 8–10h。
3. **长上下文/多文件压力受控 A/B**：检验"题太浅导致无判别力"。
4. **holdout 提示词配对**（`PROMPT-OVERFIT-RISK.md` §4 的 P0/P1：R1 dispatch trigger、R3 不改公共 API）。
5. **扩样 ≥100 题**（CI ±12pp → ±9pp）；受硬件限制，路径见 [SCALE-WITHOUT-UPGRADE](SCALE-WITHOUT-UPGRADE.md)。
6. **compact vhdx** 回收约 53GB（需管理员）。
7. **多模型 / 原生模型对照**：超 ¥50 预算，暂不做。

## 8. 结果文件清单

| 文件 | 内容 |
|---|---|
| `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json` | 四组逐 trial 汇总（当前权威）|
| `C:\sb\hard\v2-325\STRICT-COMPARE.json` | 三口径 + 题级配对 |
| `C:\sb\hard\v2-325\TRAJ-AUDIT-{claude-code,opencode}.json` | 轨迹级适配审计 |
| `C:\sb\hard\v2-325\FINAL-SUMMARY.json` | v2 三组历史明细 |
| `C:\sb\hard\formal-240\` | v1 历史结果（不补跑，不引用）|

## 9. 一句话交接

**四组都跑完了：strict 78.8 / 80.0 / 73.8 / 67.5，两两不显著（p ≥ 0.070），Codex 组作废；不能再追"谁更强"，真问题是题集太浅（中位 2 文件/64 行）+ 制品断链（跑的是没发布的 3.2.5）+ 没有 holdout。下一步先修制品（用 3.2.7 重跑），再注入压力拉开差异。**
