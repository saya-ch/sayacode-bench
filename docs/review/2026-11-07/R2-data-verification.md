# R2：全部对外数字与原始数据的一致性核验

> 核验日期：2026-11-07。核验对象：`docs/STATUS.md`、`docs/FORMAL-RESULTS-20261105-v3.md`、`docs/FORMAL-RESULTS-20261102-v2.md`、`docs/FORMAL-RESULTS-20261106-327.md`、`docs/PILOT-SWE-EVO-20261106.md`、`docs/DEEP-ANALYSIS-20261106.md`、`docs/RETROSPECTIVE-20261105.md`、`docs/archive/FORMAL-RESULTS-20261031.md`。
> 数据根：`C:\sb\hard\v2-325`、`C:\sb\hard\v4-327`、`C:\sb\newset\runs\pilot1`、`C:\sb\analysis`。全部数值由脚本从 JSON 复算，不引用文档数字作为输入；核验脚本见 §七。
> 判定：**一致** / **不一致** / **口径不同** / **无法核验**。

## 一、结论摘要

- 核心对外数字（四组 planned/observed/strict、task-macro、bootstrap CI、pass@2、McNemar、327 配对、PILOT 5/10、Claude Code 成本）**绝大多数可从原始数据复现**。
- 共发现 **7 处文档间/文档与同名数据文件不一致**、**5 处口径未显式标注**、**8 处无法从给定数据根核验**。
- 最严重的三条：① `FORMAL-RESULTS-20261105-v3.md` 的 mini-swe 行用的是 `FINAL-SUMMARY-V4.json`（68/80），不是同名的 `FINAL-SUMMARY-V3.json`（67/80）；② `RETROSPECTIVE §5.7` 声称 `STRICT-COMPARE.json` 已修到与 `FINAL-SUMMARY` 一致，但该文件当前仍是旧版（mini missing 2 vs 1、Codex missing 1 vs 0）；③ `STATUS.md` 表 2 用 3.2.7（SAYACODE 76.2%），而 §2.0 补跑表与 §3 制品身份仍写 3.2.5（78.8%），同文档内两个 SAYACODE 数字未标批次。

## 二、主对账表

### 2.1 分母、pass 计数、缺失

| 数字 | 文档出处 | 声称值 | 原始数据文件 | 实测值 | 判定 | 备注 |
|---|---|---|---|---|---|---|
| v2 SAYACODE | `FORMAL-RESULTS-20261102-v2.md:11` | 80/79/63，planned 78.8% | `FINAL-SUMMARY.json` agents.sayacode | n=80，observed=79，pass=63，78.75% | 一致 | — |
| v2 mini-swe | 同上:12 | 80/66/56，planned 70.0% | 同上 agents.mini-swe | n=80，observed=66，pass=56，70.00% | 一致 | — |
| v2 Codex | 同上:13 | 80/80/55，planned 68.8% | 同上 agents.codex | n=80，observed=80，pass=55，68.75% | 一致 | — |
| v2 缺失 15 | 同上:25-31 | SAYACODE 1、mini 14、Codex 0 | 同上 trials 的 `reward is None` + `terminal` | 1/14/0（`terminal=skipped_empty_patch` 的 trial 记 observed 0 分） | 一致 | 若只按 `reward is None` 计：1/15/1，会多算；口径已在 totals 中隐式存在 |
| V3 SAYACODE | `FORMAL-RESULTS-20261105-v3.md:14` | 63/80、78.8% | `FINAL-SUMMARY-V3.json` agents.sayacode | 63/80、78.75% | 一致 | — |
| V3 mini-swe | 同上:15 | **68/80、85.0%** | **`FINAL-SUMMARY-V3.json` agents.mini-swe** | **67/80、83.75%，observed 77、missing 3** | **不一致** | 文档的 68/80 与 `FINAL-SUMMARY-V4.json`（68/80、79、1）一致；v3 文档实为 V4 数据 |
| V3 Claude Code | 同上:16 | 62/80、77.5% | `FINAL-SUMMARY-V4.json` agents.claude-code | 62/80、77.5%，observed 79 | 一致 | — |
| V3 OpenCode | 同上:17 | 60/80、75.0% | 同上 agents.opencode | 60/80、75.0%，observed 80 | 一致 | — |
| V3 Codex | 同上:18 | 68.8%、strict 65.0% | `STRICT-COMPARE.json` codex | 55/80=68.75%，strict 52/80=65.0% | 一致 | 明确标注不可比 |
| STATUS 表 2 SAYACODE 3.2.7 | `STATUS.md:13` | 61/80、76.2%、observed 77.2% | `FINAL-SUMMARY-327.json` | 61/80=76.25%，observed 79→77.2%（61/79） | 一致 | 文档的 77.2% 是 observed 口径（61/79） |
| STATUS 表 2 mini-swe | 同上:14 | 68/80、85.0%、observed 86.1%、缺失 1 | `FINAL-SUMMARY-V4.json` agents.mini-swe | 68/80、observed 79→86.08%、missing 1 | 一致 | — |
| STATUS 表 2 Claude Code | 同上:15 | 62/80、77.5%、78.5%、缺失 1 | 同上 claude-code | 62/80、62/79=78.48%、missing 1 | 一致 | — |
| STATUS 表 2 OpenCode | 同上:16 | 60/80、75.0%、缺失 0 | 同上 opencode | 60/80、missing 0 | 一致 | — |
| STATUS 表 2 Codex | 同上:17 | 68.8%、observed 69.6%、缺失 1 | `STRICT-COMPARE.json` codex | 55/80，observed 79→69.62%，missing 1 | 一致（对 STRICT） | **V4 的 agents 中没有 Codex**；该行数据只能来自旧 STRICT，表内来源与其余行不同 |
| 327 SAYACODE | `FORMAL-RESULTS-20261106-327.md:21-23` | 61/80、observed 61/79、strict 61/80 | `FINAL-SUMMARY-327.json` | 61/80=76.25%，observed 79，missing 1，strict 61、snap 0 | 一致 | 文档「缺失 1（vuls-4b680b r1）」与 trials 一致；另 2 条 `terminal=skipped_empty_patch` 按 0 分计入 observed |
| PILOT | `PILOT-SWE-EVO-20261106.md:9-13` | 5/10、50.0%，缺失 0 | `FINAL-SUMMARY-PILOT.json` | 5/10，observed 10，missing 0 | 一致 | — |

### 2.2 task-macro、bootstrap CI、pass@2、题级全通过

| 数字 | 文档出处 | 声称值 | 原始数据文件 | 实测值 | 判定 | 备注 |
|---|---|---|---|---|---|---|
| v2 SAYACODE macro/CI | `v2.md:11` | 80.8%、[69.2,91.0] | `FINAL-SUMMARY.json` stats.agents.sayacode | mean 0.8077、bootstrap [0.6923,0.9103] | 一致 | task_macro 只算 complete_tasks=39，不含缺失题 |
| v2 mini macro/CI | 同上:12 | 84.8%、[75.8,92.4] | 同上 | 0.8485、[0.7576,0.9242] | 一致 | complete=33 |
| v2 Codex macro/CI | 同上:13 | 68.8%、[57.5,80.0] | 同上 | 0.6875、[0.575,0.8] | 一致 | complete=40 |
| v2 pass@2 | 同上:11-13 | 87.2% / 97.0% / 85.0% | 同上 pass_at_k.pass_at_2 | 0.8718 / 0.9697 / 0.85 | 一致 | — |
| V3 mini macro/CI | `v3.md:15` | 87.2%、[79.5,94.9] | `FINAL-SUMMARY-V3.json` | 0.8684、[0.7895,0.9342] | **不一致** | 与 V4（0.8718、[0.7949,0.9487]）一致；再次证明 v3 文档用的是 V4 数据 |
| V3 Claude macro/CI | 同上:16 | 78.2%、[67.9,88.5] | V4 | 0.7821、[0.6795,0.8846] | 一致 | 67.95 被截断为 67.9 |
| V3 OpenCode macro/CI | 同上:17 | 75.0%、[65.0,83.8] | V4 | 0.75、[0.65,0.8375] | 一致 | — |
| STATUS 表 2 macro/CI | `STATUS.md:13-16` | 76.9%[66.7,85.9]、87.2%[79.5,94.9]、78.2%[67.9,88.5]、75.0%[65.0,83.8] | 327/V4 | 0.7692[0.6667,0.8590]、0.8718[0.7949,0.9487]、0.7821[0.6795,0.8846]、0.75[0.65,0.8375] | 一致 | — |
| 题级全通过 | `STATUS.md:13-16` | 24/39、30/39、25/39、23/40 | 同上 wilson_task_level | k/n = 24/39、30/39、25/39、23/40 | 一致 | — |
| 327 macro/CI/全通过/pass@2 | `327.md:27` | 76.9%、[66.7,85.9]、24/39=61.5%、36/39=92.3% | `FINAL-SUMMARY-327.json` | 0.7692、[0.6667,0.8590]、24/39、0.9231 | 一致 | — |
| PILOT macro/pass@2 | `PILOT.md:9-13` | 50.0% | `FINAL-SUMMARY-PILOT.json` | macro 0.5、题级全通过 2/5、pass@2 3/5=60% | 一致 | 文档未报 pass@2；数据存在 |

### 2.3 McNemar（题级全通过，complete 题交集）

| 数字 | 文档出处 | 声称值 | 实测值（complete 交集） | 判定 |
|---|---|---|---|---|
| v2 mini vs SAYACODE | `v2.md:21` | 32 题、+1.6%、p=0.727 | common 32、a_only/b_only=5/3、delta_macro −1.56%（即 mini 高 1.6%）、p=0.7266 | 一致 |
| v2 Codex vs SAYACODE | 同上:22 | 39 题、−10.3%、p=0.021 | common 39、9/1、delta +10.26%（Codex 低 10.3%）、p=0.0215 | 一致 |
| v2 Codex vs mini | 同上:23 | 33 题、−15.2%、p=0.065 | common 33、9/2、delta +15.15%（Codex 低 15.2%）、p=0.0654 | 一致 |
| V4 Claude vs mini | `v3.md:24` | 38、−7.9%、3/7、0.344 | common 38、3/7、delta_macro −7.89%、p=0.3438 | 一致 |
| V4 Claude vs SAYACODE | 同上:25 | 38、0.0%、4/7、0.549 | common 38、4/7、0.0、p=0.5488 | 一致 |
| V4 Claude vs OpenCode | 同上:26 | 39、+3.8%、9/6、0.607 | common 39、9/6、+3.85%、p=0.6072 | 一致 |
| V4 mini vs SAYACODE | 同上:27 | 38、+7.9%、6/5、1.000 | common 38、6/5、+7.89%、p=1.0 | 一致 |
| V4 mini vs OpenCode | 同上:28 | 39、+11.5%、11/4、0.118 | common 39、11/4、+11.54%、p=0.1185 | 一致 |
| V4 OpenCode vs SAYACODE | 同上:29 | 39、−3.8%、1/7、0.070 | common 39、1/7、−3.85%、p=0.0703 | 一致 |
| STATUS 表 2.1 后三行：327 vs mini | `STATUS.md:46` | **40 题**、−12.5%、3/8、0.227 | complete 交集 38 题、3/8、−9.21%、p=0.2266；按 40 题全交集为 3/9、p=0.1460 | **口径不同/部分不一致**：common=40 与前三行（38/39）不一致；delta −12.5% 我无法复现（complete 交集 −9.2%，全交集 −15.0%） |
| STATUS 后三行：327 vs Claude | 同上:47 | 40 题、−2.5%、5/6、1.000 | complete 交集 38 题、4/5、−2.63%、p=1.0 | **不一致**：b_only 文档 6 vs 实测 5；common 40 vs 38 |
| STATUS 后三行：327 vs OpenCode | 同上:48 | 40 题、+5.0%、8/6、0.791 | complete 交集 39 题、7/6、+1.28%、p=1.0 | **不一致**：a_only 8 vs 7、p 0.791 无法复现（实测 1.0）、delta +5.0% vs +1.3% |

> 口径说明：V4 `stats.pairwise` 的 `task_macro_delta` 是「共同题内 task_macro 差」，不是文档表头写的「题级全通过率差」；a_only/b_only 才对应表头。文档 delta 一列与表头定义不符，但数字与 `stats.pairwise` 自洽。

### 2.4 strict 与 snap pass

| 数字 | 文档出处 | 声称值 | 原始数据文件 | 实测值 | 判定 |
|---|---|---|---|---|---|
| 四组 strict | `v3.md:14-17`、`STATUS.md:13-16` | SAYACODE 78.8%（3.2.5）/76.2%（3.2.7）、mini 80.0%、Claude 73.8%、OpenCode 67.5% | `STRICT-COMPARE.json` | 63/80、64/80=80.0%、59/80=73.75%、54/80=67.5% | 一致（SAYACODE 两个值分属两批次） |
| snap pass | 同上:52-55 | SAYACODE 0、mini 4、Claude 3、OpenCode 6、Codex 3 | 同上 `snap_passes` | 0/4/3/6/3 | 一致 |
| Codex strict | `v3.md:18` | 65.0% | 同上 codex | 52/80=65.0% | 一致 |
| v2 strict | `v2.md:15` | SAYACODE 78.8、mini 65.0、Codex 65.0 | 当前 `STRICT-COMPARE.json`（V4 时期：mini 80.0） | **无法复现 v2 的 65.0** | **无法核验**（v2 时期 STRICT 快照未保留；当前文件是补跑后的 V4 数据） |
| strict missing | `RETROSPECTIVE §5.7` | 修复后与 FINAL 完全一致 | `STRICT-COMPARE.json` vs `FINAL-SUMMARY-V4.json` | **STRICT：mini missing 2、Codex missing 1；FINAL：mini 1、Codex 0** | **不一致**：文件未按声称重新生成（详见 §五） |

### 2.5 成本

| 数字 | 文档出处 | 声称值 | 原始数据 | 实测值 | 判定 |
|---|---|---|---|---|---|
| Claude Code 每 trial 成本 | `DEEP-ANALYSIS:176` | $2.27（中位 $1.19），77 trial 合计 $174.61 | `v2-325/claude-code/jobs/*/instance_*/result.json` 的 `agent_result.cost_usd` | n=77、sum $174.61、mean $2.27、median $1.19 | 一致 |
| SAYACODE 单任务 tokens | `RETROSPECTIVE:91`、`v3.md:136` | 1.43M tokens | v2-325 的 v2 逐 trial tokens | 90.1M/63 ≈ 1.43M（3.2.5 批次） | 一致（**口径不同**：该数属 3.2.5；3.2.7 按 behavior 均值约 77.9M/61≈1.28M） |
| 行为 token 均值 | `DEEP-ANALYSIS:114-118` | 3.2.7 960,348；3.2.5 961,560 | `C:\sb\analysis\behavior.json` | 3.2.7 998,762；3.2.5 **1,117,106** | **不一致**：3.2.5 差 16.2%，3.2.7 差 4.0%；其余行为量（tools/explore/edit/exec）完全一致 |

### 2.6 SWE-EVO pilot

| 数字 | 文档出处 | 声称值 | 原始数据 | 实测值 | 判定 |
|---|---|---|---|---|---|
| 总通过 | `PILOT.md:11` | 5/10 = 50.0% | `FINAL-SUMMARY-PILOT.json` | 5/10、observed 10 | 一致 |
| 逐题 | 同上:17-23 | dask 0/2、dvc1.11 1/2、dvc2.21 2/2、dvc2.58 0/2、dvc3.15 2/2 | `PREDICT-VS-ACTUAL.json` | 完全一致（actual 与 reward 两两对应） | 一致 |
| 预测矩阵 | 同上:34 | TP=4 TN=2 FP=3 FN=1，60% | 同上 | TP=4（2.21×2、3.15×2）、TN=2（dask r1、dvc1.11 r1）、FP=3（dask r2、2.58×2）、FN=1（dvc1.11 r2），6/10=60% | 一致 |
| 版本文件假设 | 同上:49-55 | r1 reward 0、r2 reward 1，agent_touched 均 false | `VERSION-HYPOTHESIS.json` | 与文档一致（假设只符合 1/2） | 一致 |
| 「48 题有假题、p2p 基线失败 dask 57%、6 个 ghcr 镜像不匹配」 | 同上:80-81 | — | `C:\sb\analysis\swe-evo-baseline.json` | 只有 4 条 `usable` 记录，无 48 题全量统计 | **无法核验** |

### 2.7 行为、轨迹、健康度

| 数字 | 文档出处 | 声称值 | 原始数据 | 实测值 | 判定 |
|---|---|---|---|---|---|
| partial 均值 | `DEEP-ANALYSIS:11-15` | 97.6/99.2/98.5/97.8/94.4% | `C:\sb\analysis\dataset.json` | 0.9761/0.9920/0.9854/0.9785/0.9439 | 一致 |
| 各组 n | 同上:11-15 | 72/73/77/76/77 | 同上（partial 非空） | 72/73/77/76/77 | 一致 |
| 饱和题 | 同上:35 | 26/40 = 65% | 同上（全组 partial=1.0） | 26/40 | 一致（**但与 `health.md` 的 28 矛盾**，见 §三） |
| 同题翻转 | 同上:73-77 | 5/2/3/5/7 | 同上 | 需按 r1/r2 配对复算；翻转题数与 dataset 一致（3.2.7=5、3.2.5=2、mini=3、Claude=5、Open=7 可复现） | 一致 |
| 工具均值 | 同上:114-118 | 49.6/48.7/57.3/43.0/30.9 | `C:\sb\analysis\behavior.json` | 49.55/48.73/57.33/42.99/30.94 | 一致 |
| Claude tool_use/result | `v3.md:63-64`、`STATUS.md:64-65` | 3468/3467、OpenCode 2480 | `TRAJ-AUDIT-claude-code.json`、`TRAJ-AUDIT-opencode.json` | 3468/3467、2480（trials 80） | 一致 |
| Codex 960/373 | `v3.md:65`、`STATUS.md:66` | 960 次 405、373 次 unsupported | 无 `TRAJ-AUDIT-codex.json` | — | **无法核验**（数据根无对应审计文件） |
| DEEP §10 峰值 token | `DEEP-ANALYSIS:186-187` | 峰值中位 32,920/30,180、max 102,034/127,369 | behavior.json 无单次峰值；抽样 audit.jsonl 解析失败 | — | **无法核验**（需逐调用 `events.jsonl`/`audit.jsonl`，本次未成功解析） |
| 行为测试 | `STATUS.md:100` | 1430 passed / 9 skipped | — | — | **无法核验**（需运行 pytest） |
| usage 42681 / served 分布 | `STATUS.md:94`、`v3.md:120-131` | 42681 条、各组 hy3/hy3-x 占比 | 源不在给定数据根 | — | **无法核验** |

## 三、文档间矛盾（同一指标不同文档不同值）

1. **SAYACODE 最终值**：`FORMAL-RESULTS-20261105-v3.md:14` 与 `RETROSPECTIVE:74` 写 **78.8%（63/80，3.2.5）**；`STATUS.md:13` 写 **76.2%（61/80，3.2.7）**。两份都称「最终数字」，未在同一处并列两批次。
2. **SAYACODE 制品**：`STATUS.md:70-73`（§3）说「所有 SAYACODE 数字跑的是本地 3.2.5 wheel」；同文件 `:13` 表 2 却是 3.2.7（v4-327）。**同文档自相矛盾**。
3. **补跑前 mini-swe 基线**：`v2.md:38` 写「47.5% → 70.0%（+22.5pp）」；`v3.md:38` 与 `STATUS.md:31` 写「70.0% → 85.0%（+15.0pp）」。前者是「首版→v2 终版」，后者是「v2 终版→V4」，两处都叫「补跑前/后」，易被读成同一组。
4. **饱和题数**：`DEEP-ANALYSIS:35` 写 **26/40**（定义：所有组部分得分=1.0）；`health.md:9` 写 **saturated 28**（定义：全组≈满分）。同一批数据两个数。
5. **环境性不可过题数**：`DEEP-ANALYSIS:54-64` 写 **2 题**（qutebrowser-fec187c2、tutanota-51818218）；`health.md:7` 写 **broken 3**（多出 element-web-772df30212）。
6. **v3 文档与 V3 数据文件**：`v3.md:15` 的 mini-swe 85.0%（68/80）、87.2%、[79.5,94.9] 对应 `FINAL-SUMMARY-V4.json`；`FINAL-SUMMARY-V3.json` 实际是 83.75%（67/80）、86.84%、[78.95,93.42]。
7. **`RETROSPECTIVE:212`** 称「v3 报告没做到补跑前后同表」——事实错误：`FORMAL-RESULTS-20261105-v3.md:33-42` 有完整的「补跑前后同表」。

## 四、原始数据不支持的声称

1. **`STATUS.md:46-48` 后三行 McNemar**：common 写 40，但 3.2.7 只有 39 个完整题（`FINAL-SUMMARY-327.json` complete=39），40 只能是「全题集合」；同表前三行 common 是 38/39（complete 交集）。后三行的 a_only/b_only/p 中，Claude 行 b_only 5 vs 文档 6、OpenCode 行 a_only 7 vs 文档 8、p=0.791 vs 实测 1.0，**无法从任一合理口径复现**。
2. **`DEEP-ANALYSIS:114-118` 的 3.2.5 输入 token 961,560**：`behavior.json` 实测均值 1,117,106，差 16.2%。其余行为量精确一致，唯独 token 不符，且文档未说明 token 口径（是否去缓存）。
3. **`DEEP-ANALYSIS:176` 的 $2.27/$174.61** 可从原始 `result.json` 精确复现（不是问题）；但同节说「SAYACODE 960K/trial 是 Claude Code 的 59%」——用 behavior 实测 998,762/1,620,979=61.6%，且 3.2.5 为 1,117,106/1,620,979=68.9%，与 59% 不符（依赖上面错误的 token 均值）。
4. **`v3.md:38` 与 `STATUS.md:34`** 称 mini-swe 补跑 12 条「全部是安装期网络失败（apt-get exit 100 撞 Clash fake-ip、NetworkConnectError）」：`v2-325/mini-swe/abandoned-retry-20261102-165011/` 的 28 个 `exception.txt` 实测为 `NetworkConnectionError`（20 条，类名多一个 "ion"）与 `NonZeroAgentExitCodeError`（8 条）。**「NetworkConnectError」类名与原始异常不符**（小笔误）；「12 条」与 28 个重试 job 的关系也未说明（28 是尝试数，非转正数）。
5. **`PILOT.md:80-81`** 的「48 题里有假题（pydantic 2.7.1）、p2p 大面积基线失败（dask 57%）、6 个 ghcr 镜像版本不匹配」：`swe-evo-baseline.json` 只有 4 条 `usable` 记录，无 48 题全量，**数据不支持**。

## 五、文档写对但数据/工具有问题

1. **`STRICT-COMPARE.json` 未按 `RETROSPECTIVE §5.7` 的声称重新生成**。§5.7 说「已修（加 `_read_terminal`），修后两工具在 5 组上完全一致」；当前文件仍：mini `observed=78, missing=2`（`FINAL-SUMMARY-V4.json`：79/1）、Codex `missing=1`（`FINAL-SUMMARY.json`：0）。即**文档的「已修」与数据文件状态不符**（或修复只改了代码、未重跑产物）。
2. **`dataset.json` 的 `touches_snap` 只对 Claude Code（4）与 OpenCode（6）有值，mini-swe/Codex/SAYACODE 全为 `null`**。而 `STRICT-COMPARE.json` 给出 mini 4、Codex 3、SAYACODE 0 个 snap pass。两个「snap」指标来源不同、覆盖不同；用 `dataset.json` 做全组 snap 统计会漏掉三组。
3. **`dataset.json` 的 Claude Code `touches_snap`=4，而 `STRICT-COMPARE.json` 的 claude `snap_passes`=3**（差 `element-web-9bf77963ee-r1`）。同一 trial 在两个工具里判定不同（dataset 的 4 个：772df r1、9bf r1/r2、b7fe r2；STRICT 的 3 个：772df r1、9bf r2、b7fe r2）。
4. **`FINAL-SUMMARY*.json` 的 `reward=None` 不等于 missing**：327 有 3 条 `reward=None`，其中 2 条 `terminal=skipped_empty_patch` 是 observed 0 分，真正 missing 只有 1 条。文档写对了（327.md:25-26），但**任何直接按 `reward is None` 统计的脚本都会得到 3 而非 1**（v2 mini 同理：15 vs 14；Codex 1 vs 0）。`observed` 的定义只隐含在 totals 里，未在 schema 文档化。
5. **`health.md` 的 broken 题 `qutebrowser-fec187c2` 自身 0/1 通过=100%**（同一张表第 19 行），却被标「broken（跨 ≥2 agent 稳定失败同一测试）」。该表的「broken」与「0/1 通过」两列对这道题自相矛盾，需解释是「特定测试稳定失败但整体 reward 仍为 1」还是评级规则另有定义。
6. **`V3` 与 `V4` 两个汇总文件并存且对同一批次 mini-swe 给出不同结果**（67/80 vs 68/80，missing 3 vs 1）。文档 v3 名为 v3、实际用 V4；版本管理上应明确「v3 文件=中途快照，v4=终版」。

## 六、无法核验项

1. `STATUS.md:94` / `v3.md:120-131` 的 42681 条 usage 与各组 served 分布（hy3/hy3-x 占比）——源在 Magpie 网关日志，不在给定数据根。
2. `STATUS.md:100` 的「1430 passed / 9 skipped」——需运行 pytest。
3. `v3.md:65` / `STATUS.md:66` 的 Codex 960 次 405、373 次 unsupported call——数据根无 `TRAJ-AUDIT-codex.json`。
4. `DEEP-ANALYSIS:186-187` 的 SAYACODE 单次调用 input_tokens 峰值（32,920/102,034 等）——behavior.json 无逐调用峰值，抽样 audit.jsonl 解析未成功。
5. `PILOT.md:80-81` 的 48 题基线统计（假题、dask p2p 57%、6 个镜像不匹配）——`swe-evo-baseline.json` 只有 4 条 usable。
6. `v2.md:15` 的 v2 strict（mini 65.0、Codex 65.0）——v2 时期的 STRICT 快照未保留；当前 STRICT 文件是补跑后的 V4 数据（mini 80.0）。
7. `FORMAL-RESULTS-20261106-327.md:14,89` 的 served 分布 `hy3/workbuddy 6206 + workbuddy-ai 3572`——`served-distribution.json` 存在（79 个 trial），但结构未能聚合（本次读取结果为空，未进一步解析）。
8. `docs/archive/FORMAL-RESULTS-20261031.md` 为 **0 字节空文件**；`STATUS.md:84` 与 `RETROSPECTIVE:107` 将其作为 v1 作废证据引用，**引用目标无内容**（不构成数字错误，但使「可复核」落空）。

## 七、可复现脚本

核验脚本：`C:\sb\tmp\explore\review2\verify.py`、`verify2.py`（只读，未修改原始数据）。核心逻辑：

```python
import json, collections
from math import comb

def observed(r):
    # 关键：显式终态 skipped_empty_patch 算 observed 0 分，不算 missing
    return r.get("reward") is not None or r.get("terminal") == "skipped_empty_patch"

def mcnemar(b, c):
    n = b + c
    if n == 0: return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2 ** n))

def complete_tasks(recs):
    by = collections.defaultdict(list)
    for r in recs: by[r["task"]].append(r)
    return {t for t, v in by.items() if len(v) == 2 and all(observed(x) for x in v)}

def task_macro_complete(recs):
    ct = complete_tasks(recs)
    by = collections.defaultdict(list)
    for r in recs:
        if r["task"] in ct:
            by[r["task"]].append(1.0 if r.get("reward") == 1.0 else 0.0)
    vals = [sum(v) / len(v) for v in by.values()]
    return sum(vals) / len(vals), len(vals)
```

McNemar 复算（complete 交集）：

```python
def mcnemar_complete(ra, rb):
    common = complete_tasks(ra) & complete_tasks(rb)
    def full(recs):
        by = collections.defaultdict(list)
        for r in recs: by[r["task"]].append(r.get("reward"))
        return {t: (len(v) == 2 and all(x == 1.0 for x in v)) for t, v in by.items()}
    ta, tb = full(ra), full(rb)
    b = sum(1 for t in common if ta[t] and not tb[t])
    c = sum(1 for t in common if not ta[t] and tb[t])
    return len(common), b, c, mcnemar(b, c)
```

关键运行命令：

```powershell
cd C:\sb\tmp\explore\review2
python verify.py
python verify2.py
```

## 八、逐文档核对备注

- **`STATUS.md`**：表 2（`:13-17`）与 V4/STRICT/327 全部可复现；§2.0（`:30-31`）的 SAYACODE 78.8% 是 3.2.5、表 2 是 3.2.7，未标批次；§3（`:70-73`）「所有 SAYACODE 数字是 3.2.5」与表 2 冲突；§2.1 后三行（`:46-48`）common 40 与前三行口径不一致。
- **`FORMAL-RESULTS-20261105-v3.md`**：表一 SAYACODE/Claude/OpenCode/Codex 全部可复现；**mini-swe 行（`:15`）用 V4 而非 V3 数据**；六对 McNemar、snap、补跑前后表均可复现；§五.6 served 表无法核验。
- **`FORMAL-RESULTS-20261102-v2.md`**：三组分母/pass/缺失、macro、CI、pass@2、三对 McNemar 全部可复现；strict（`:15`）无法用当前文件复现（历史快照缺失）。
- **`FORMAL-RESULTS-20261106-327.md`**：三口径、缺失、macro/CI/全通过/pass@2、配对 78（63→61、Δ−2.56pp、p=0.8145、only 10/8）全部可复现；served 分布未核。
- **`PILOT-SWE-EVO-20261106.md`**：5/10、逐题、预测矩阵、版本假设全部可复现；48 题基线统计无法核验。
- **`DEEP-ANALYSIS-20261106.md`**：partial 均值/组 n/饱和 26/翻转/工具均值/Claude 成本全部可复现；**输入 token 均值与 behavior.json 不符**（3.2.5 差 16%）；饱和数与 health.md 矛盾；2 题 vs 3 题 broken 矛盾；峰值 token 无法核验。
- **`RETROSPECTIVE-20261105.md`**：四组表与 v3 文档一致；§5.6 的「补跑 12 条是 infra」有 exception.txt 支持（但类名是 `NetworkConnectionError`）；**§5.7「STRICT 已修到一致」与当前文件不符**；**§6 称「v3 报告没给补跑前后表」事实错误**。
- **`docs/archive/FORMAL-RESULTS-20261031.md`**：0 字节空文件，无法核对；v1 的 68.8/86.2/86.2、49/73/42、3 条故障、gold 36/1/3 等只能从 `formal-240` 历史数据复核（不在本轮数据根）。
