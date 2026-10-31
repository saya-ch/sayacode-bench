# HANDOFF：SAYACODE Bench 交接（2026-10-31）

> 接手者必读。本文件说明**当前进度、缺口、关键发现、环境、坑、下一步**。
> 当前状态数字以 [STATUS](STATUS.md) 为准；历史与作废文档见 [docs/archive/](archive/README.md)。

## 1. 当前进度（一句话）

**v1 的 240 trial 已收尾但不完整：221/240 完整，19 条缺口；v1 结论全部作废，正在按统一口径重跑 v2。**

| agent | v1 完整 | v1 缺口 | 有效分母 |
|---|---|---|---|
| SAYACODE | 77/80 | 3（tutao r1/r2 空 patch、vuls-f6cc8c r1 ECONNRESET）| 80 |
| mini-swe-agent | 79/80 | 1（ansible-de5858 r1 有 reward 无 patch）| 80 |
| Codex CLI | 65/80 | 15（4 无目录 + 4 空 patch + 7 有 patch 未验证）| **65** |
| 合计 | 221/240 | 19 | — |

## 2. v1 的核心教训（不要重复踩）

### 2.1 分母三套，不能并列

- SAYACODE 55/80、mini-swe 69/80、Codex **56/65**。
- Codex 的 86.2% 是 56/65；**统一 80 分母是 70.0%**。旧报告把三者并列成 68.8% / 86.2% / 86.2%，制造了 17.4pp 的假差距。
- **规则：任何对比表，分母必须一致；不一致就分开写，不并排。**

### 2.2 改测试有两个口径，不能跨 agent 比

| 口径 | SAYACODE | mini-swe | Codex |
|---|---|---|---|
| 产品侧检测率（被验证器恢复）| **39/80 = 48.8%** | — | — |
| patch 含测试文件 | **0%** | **70.9%** | **54.2%** |

- 48.8% 是「尝试改测试并被恢复」，不是作弊成功；SAYACODE 最终 patch 里测试文件是 0。
- 旧文档的「mini-swe 73% / Codex 42%」已作废（正确 70.9% / 54.2%）；旧 HANDOFF 的「42%」不要再引用。

### 2.3 模型故障只有 1 条真的

- 真 API 故障：`vuls-f6cc8c-r1`（ECONNRESET）。
- tutao r1/r2 是 `completed + verified + reward=0` 的**空 patch**，不是模型故障。
- **严格剔除后 55/79 = 69.6%**；「3 条故障、71.4%」不成立。

### 2.4 坏题：36 good / 1 bad / 3 null

- bad 题不在最终 40 题内；3 个 null 表示**未取得有效 gold 结论**，不能当「全绿」。
- 「40 题全绿」「坏题率 1/40」的说法不成立。

## 3. 待办（按优先级）

### P0：v2 重跑（当前主线）

```powershell
# 1) 清网络池
docker network prune -f

# 2) 阶段1 解题（40 题 × 2 重复 × 3 agent，输出到 v2 目录）
python scripts\run_formal_240.py --out C:\sb\hard\v2 --repeats 2 `
  --concurrency 4 --skip-verifier

# 3) 阶段2 统一 PatchReplay 验证
python scripts\verify_patches.py --out C:\sb\hard\v2 `
  --agents sayacode mini-swe codex --concurrency 4

# 4) 汇总（必须按统一 80 分母）
python scripts\final_summary.py
```

- **修正项**：`max_output_tokens=32000`（v1 用 16000，长任务收尾过早）。
- 并发 ≤ 6（每 trial 占 2 个 Docker 网络，池约 17）。
- 先补 gold-check 的 3 个 null 题，或替换。

### P1：v2 汇总口径（写死在报告里）

1. 分母统一 80（缺一条就写 79/80，不换分母）。
2. 改测试**分两列**：产品侧检测率、patch 含测试文件比例；注明不可跨 agent 比。
3. 模型故障**逐条列明**，只剔除真 API 故障，并写剔除前后两个数。
4. 坏题写 36 good / 1 bad / 3 null，不写「全绿」。
5. 统计不显著就写不显著；McNemar + Bonferroni α/3 = 0.0167。

### P2：调优（v2 结果前不做）

- v2-tuned 已作废（基于误读的 49%）。见 [归档说明](archive/README.md)。
- 正确顺序：逐题对比找失败模式 → 设计规则 → A/B。旧失败模式线索（空 patch、改得太少、改数据文件）仍需在 v2 数据上重新确认。
- **不要**加「禁止改测试」（无效）、**不要**加「最小 diff」（会加剧改太少）。

## 4. 环境与路径

| 项 | 路径/值 |
|---|---|
| 仓库 | `C:\develop\sayacode-bench`（remote: `saya-ch/sayacode-bench`）|
| v1 结果 | `C:\sb\hard\formal-240\<agent>\jobs\`（阶段1）+ `\<agent>\verify\jobs\`（阶段2）|
| v2 结果（计划）| `C:\sb\hard\v2\<agent>\jobs\`、`\<agent>\verify\jobs\` |
| 题集 | `studies/sample-40-final.json` |
| 任务缓存 | `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\v2\tasks`（642 题）|
| 模型 | hy3（`auto-hy3`），Magpie `127.0.0.1:3425/v1`，容器内 `saya-model-gateway:8080` |
| 上下文 | 192k；max_output 32k（v2 起）；SAYACODE 摘要触发 153.6k |
| 关键脚本 | `scripts/run_formal_240.py`、`scripts/verify_patches.py`、`scripts/final_summary.py` |

## 5. 坑清单（血泪教训，逐条都踩过）

1. **Docker 网络池耗尽**：每 trial 占 2 个网络，默认池约 17。并发 14 时 28 个网络必爆。跑前 `docker network prune -f`，并发 ≤ 6。
2. **Docker 崩溃**：主机 15.6GB 物理内存被 Docker VM（提交 6.9GB）+ 桌面应用 + 系统吃满，提交冲到 53.6GB → WSL 后端被压垮。关掉 ChatGPT/WorkBuddy/codex 桌面应用（约释放 2.4GB）；崩溃后 `wsl --shutdown` + 重启 Docker + `--skip-existing` 续跑。
3. **阶段1 归档/skip-existing bug（已修）**：原按 `reward.txt` 判断，阶段1 跳过验证导致所有 patch 被归档或全量重跑。现改为「有 reward **或** 有 patch 都不归档/都跳过」。
4. **PatchReplayAgent source_job 必须传单个 trial 目录**（`jobs/<job_name>`），不是整个 jobs 目录，否则「no source patch」、全 0 分。
5. **对比脚本读错目录**：Codex 的 patch 在 `jobs/`，`verify/jobs/` 只有 `replay.json`；比 patch 大小必须读 `jobs/`。
6. **PowerShell 引号地狱**：复杂 `python -c` 一律写成 .py 文件再执行。
7. **进程自杀**：`Where-Object { $_.CommandLine -match 'watchdog' }` 会匹配到自己（命令行含该字符串），导致 exit 4294967295。用 `-like '*watchdog.ps1*' -and $_.ProcessId -ne $PID`。
8. **别用会漂移的 `auto/...` 泛指别名**：实测 40% 请求落到 glm。用 `auto-hy3` 并记录每个 trial 的 `served`/`provider`（见 [ROUTING-DRIFT](ROUTING-DRIFT-20261029.md)）。
9. **别把 context_length 配小**：hy3 实际 192k；曾误配 65536 导致长任务早摘要。
10. **报告 pass@1 必须带 Wilson CI 与样本量**；只说「通过率 x%」会误导。

## 6. 结果文件清单

| 文件 | 内容 |
|---|---|
| `C:\sb\hard\formal-240\FINAL-SUMMARY.json` | v1 逐 trial 明细（221 条）|
| `C:\sb\hard\formal-240\AUDIT.json` | v1 全 trial 异常审计 |
| `C:\sb\hard\formal-240\MODEL-FAULTS.json` | v1 模型故障清单（1 条真故障）|
| `C:\sb\hard\formal-240\abandoned-gaps\` | v1 缺口 job（不补跑，作历史）|
| `C:\sb\hard\v2\` | v2 输出目录（计划）|

## 7. 一句话交接

**不要引用 v1 的 68.8/86.2/86.2 和 49%/73%/42%，那些口径全错；先把 v2 的 240 条按统一 80 分母跑全并汇总，再谈任何对比结论。**
