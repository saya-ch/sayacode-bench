# HANDOFF：SAYACODE Bench 交接（2026-11-02）

> 接手者必读。本文件说明**当前进度、关键事实、环境、坑、下一步**。
> 数字以 [STATUS](STATUS.md) 为准；协议见 [PROTOCOL-V2](PROTOCOL-V2.md)；v2 报告见 [FORMAL-RESULTS-20261102-v2](FORMAL-RESULTS-20261102-v2.md)；踩坑见 [LESSONS-20261102-v2](LESSONS-20261102-v2.md)。

## 1. 当前进度（一句话）

**v2 已完成：40 题 × 2 重复 × 3 agent = 240 trial 跑完并汇总（运行根 `C:\sb\hard\v2-325`），缺失 15 条已分类；v1 结论仍作废。**

| agent | planned | observed | task_macro | 缺失 |
|---|---|---|---|---|
| SAYACODE | **78.8%** | 79.7% | 80.8% | 1 |
| mini-swe | **70.0%** | 84.8% | 84.8% | 14 |
| Codex | **68.8%** | 68.8% | 68.8% | 0 |

- 缺失 15 条：SAYACODE 1（empty_patch）、mini-swe 14（empty_patch 8 + no_job 6）、Codex 0。
- 三 agent 校正后**均不显著**（Bonferroni α/3 = 0.0167）；不能下「谁更强」结论。

## 2. 接手先读

1. [STATUS](STATUS.md)：当前数字、局限、下一步。
2. [PROTOCOL-V2](PROTOCOL-V2.md)：planned 分母、缺失分类、worst/best、补跑规则、冻结签收。
3. [FORMAL-RESULTS-20261102-v2](FORMAL-RESULTS-20261102-v2.md)：v2 终版五指标与 McNemar。
4. [LESSONS-20261102-v2](LESSONS-20261102-v2.md)：v2 的真实坑（环境、管线、行为、统计）。

## 3. 关键事实（别搞错）

1. **分母统一 planned 80**：缺失按失败；observed 只是辅助，只报 observed 会高估（mini-swe 84.8% 只覆盖 66/80）。
2. **补跑效应巨大**：SAYACODE 67.5%→78.8%（+11.3pp）、mini-swe 47.5%→70.0%（+22.5pp）；补跑前数字不能当能力，补跑收益不能归因产品修复。
3. **缺失分类**：`infra`/`no_job`/`unverified` 可补；`timeout`/`empty_patch` 不补；`empty_patch ≠ model_fault`。
4. **统计题级**：Wilson n = 题数（40），McNemar 用题级 pass（不用 best-of-2）。
5. **`task_count` 全 0**：本批不触发多 agent，不能用 SWE-bench 评价协作。
6. **v2 未采集** partial / 轨迹 / 改测试两口径。

## 4. v1 已作废（不要引用）

- 68.8 / 86.2 / 86.2 是三套分母并列的假象（Codex 实为 56/65，统一 80 分母 70.0%）。
- 「改测试率 49% / 73% / 42%」口径错误：48.8% 是产品侧检测率（39/80），patch 含测试是 SAYACODE 0% / mini-swe 70.9% / Codex 54.2%，两口径不可混。
- 「3 条模型故障」只有 1 条真（vuls-f6cc8c-r1 ECONNRESET）；「40 题全绿」实为 36 good / 1 bad / 3 null。
- 完整 v1 记录在 [docs/archive/](archive/README.md)。

## 5. 环境与路径

| 项 | 路径/值 |
|---|---|
| 仓库 | `C:\develop\sayacode-bench`（remote: `saya-ch/sayacode-bench`）|
| v2 结果 | `C:\sb\hard\v2-325\`（`FINAL-SUMMARY.json`、`logs\final\`）|
| v1 结果（历史）| `C:\sb\hard\formal-240\` |
| 题集 | `studies/sample-40-final.json` |
| 任务缓存 | `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\v2\tasks`（642 题）|
| 产品 | SAYACODE 3.2.5（`13df615` / `v3.2.5`）已发布 |
| 模型 | hy3（`auto-hy3`），Magpie `127.0.0.1:3425/v1`，容器内 `saya-model-gateway:8080` |
| 上下文 | 192k；`max_output_tokens=32000`；SAYACODE 摘要触发 153.6k |
| 关键脚本 | `scripts/run_formal_240.py`（stage1）、`scripts/verify_patches.py`（verify）、`scripts/final_summary.py`（汇总）|

## 6. 坑清单（逐条都踩过）

1. **stage1 与 verify 不要并行**：验证器峰值 2.26GB，并行会互相挤内存、留未收尾 job。
2. **续跑判据必须对齐产物**：stage1 `--skip-verifier` 阶段没有 reward，skip 要认 `normalized.json` 的 `record_complete=True`（已修 `5f8b138`）；否则重复撞 `ValueError`。
3. **归档清单 = retry sample 同源**：先列 job → 生成 sample → 归档，核对数量（曾出现归档 28 个但 sample 只覆盖 8 题）。
4. **`verify_patches.collect_pending` 只认 stage1 reward（未修）**：verify 产物在 `verify/jobs/`，重跑会报冲突；临时做法是把 `verify/jobs/*/verifier/reward.txt` 同步回 stage1。
5. **Docker 网络池耗尽**：每 trial 占 2 个网络，池约 17；跑前 `docker network prune -f`，并发 ≤6。
6. **Docker 崩溃**：宿主 15.6GB 被 Docker VM + 桌面应用吃满；`.wslconfig` 设 `memory=7GB/swap=2GB`（**合并写入**，勿覆盖 mirrored/dnsTunneling/firewall/autoProxy）；崩溃后 `wsl --shutdown` + 重启 Docker + `--skip-existing`。
7. **vhdx 不自动收缩**：删镜像 C: 不会立刻变空；约 53GB 需 `diskpart` 的 `compact vdisk`。
8. **代理注入破坏内部网关**：`HTTP(S)_PROXY` 注入容器导致 `saya-model-gateway` 解析失败（gaierror）；`NO_PROXY` 必须含内部主机名与私网段，或直接移除代理让容器直连。
9. **apt 502（fake-ip）**：Clash 的 TUN + fake-ip 让 apt 源走代理返回 502；在 profile 的 `prepend` 加 `DOMAIN-SUFFIX,debian.org,DIRECT` 等（Merge.yaml 的 `prepend-rules` 不生效）。
10. **astral.sh TLS exit=35（未根因修复）**：间歇性 SSL connect error，靠补跑；下一步预置 uv installer 到镜像。
11. **别用会漂移的 `auto/...` 别名**：40% 落到 glm；用 `auto-hy3` 并逐 trial 记录 served/provider。
12. **别把 context_length 配小**：hy3 实际 192k；曾误配 65536 导致长任务早摘要。
13. **报告 pass@1 必须带 Wilson CI、样本量与分母口径**；只说「通过率 x%」会误导。
14. **PowerShell 引号地狱 / 进程自杀**：复杂 `python -c` 写成 .py；`Where-Object` 匹配 watchdog 会匹配自己，用 `-like '*watchdog.ps1*' -and $_.ProcessId -ne $PID`。

## 7. 下一步（按优先级）

1. TLS 预置 installer（消除最大环境噪声）。
2. partial / 轨迹 / 改测试两口径采集。
3. 扩样 100 题（CI 收窄到 ±9pp）。
4. 多 agent 场景（`evals/scenarios/collaboration-autonomous.jsonl`）。
5. compact vhdx 回收约 53GB。
6. 第二模型按 [MULTI-MODEL-PLAN](MULTI-MODEL-PLAN.md) 执行。

## 8. 结果文件清单

| 文件 | 内容 |
|---|---|
| `C:\sb\hard\v2-325\FINAL-SUMMARY.json` | v2 逐 trial 明细（240 条）|
| `C:\sb\hard\v2-325\logs\final\` | 终版统计（final-summary / final-stats / stats-four / final-classify）|
| `C:\sb\hard\formal-240\` | v1 历史结果（不补跑）|
| `docs/FORMAL-RESULTS-20261102-v2.md` | v2 终版报告 |

## 9. 一句话交接

**v2 已跑完：planned 78.8% / 70.0% / 68.8%，缺失 15 条已分类，校正后不显著；不要引用 v1 的 68.8/86.2/86.2 和 49%/73%/42%，下一步先消除 TLS 环境噪声、补 partial/轨迹、再扩样 100 题。**
