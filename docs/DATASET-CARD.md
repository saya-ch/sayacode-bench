# DATASET-CARD：题集卡片与口径定义（2026-11-07）

> 本文件是「题库饱和 / 难度 / 区分度 / broken」的**唯一口径来源**。其他文档只允许引用本卡，不得各自维护数字。
> 统计脚本：`scripts/dataset_stats.py`（参数化、可复现）；健康度脚本：`scripts/benchmark_health.py`（health.md 的生成器）。
> 数据：`C:\sb\analysis\dataset.json`（391 trial，5 组：SAYACODE 3.2.5 / 3.2.7、mini-swe、Claude Code、OpenCode）+ 原始 `verifier/output.json` / `gold_patch.diff` / `model.patch`。

---

## 1. 两套题集卡片

### 1.1 SWE-bench Pro V2 · 40 题（开发迭代集）

| 项 | 值 | 证据 |
|---|---|---|
| 文件 | `studies/sample-40-final.json`，sha256 `b2f1643567f55abe04a054c7fc88e946315c47cb39dfa284445f5e483f35fe96` | 与 `FINAL-SUMMARY-V4/327` 的 `sample.sha256` 一致 |
| 规模 | 40 题（9 仓库） | ansible 6、internetarchive 6、qutebrowser 6、flipt-io 5、element-hq 4、future-architect 4、navidrome 4、NodeBB 3、tutao 2 |
| 性质 | **开发迭代集**，不是 holdout；SAYACODE 的提示词规则 R1–R5 从这套题的失败个案调出 | `PROMPT-OVERFIT-RISK.md` |
| gold 校验 | **36 good / 1 bad / 3 null**（bad = `element-hq__element-web-923ad4323b20`，**不在 40 题内**） | `C:\sb\hard\gold-check\gold-summary.json` |
| 难度（gold patch） | 中位 **3 文件 / 70 行**（精确中位 70.5，按向下取整记 70）；均值 132.5 行；最大 881 行 / 12 文件 | `solution/gold_patch.diff`，line = additions+deletions |
| 难度（agent patch，全部 agent） | 中位 **3 文件 / 72 行**（n=477） | `agent/model.patch` |
| 难度（agent patch，仅 SAYACODE） | 中位 **2 文件 / 64 行**（n=158） | 同上 |
| 饱和 | 见 §2（25–29/40，取决于组数与阈值） | — |
| broken | 见 §3 | — |

### 1.2 SWE-EVO · 48 题（新题库）

| 项 | 值 | 证据 |
|---|---|---|
| 任务目录 | `C:\sb\newset\swe-evo\tasks\`，48 个 | 目录计数 |
| 试点题集 | `sample-pilot.json`，5 题，sha256 `a31fa827e0c88ea56d76f0b877d7db31dd1ac71a2e9e9a896d2bebd437130a0e` | `FINAL-SUMMARY-PILOT.json.sample` |
| 仓库分布 | iterative 26、dask 8、psf 4、modin 3、pydantic 3、conan 2、scikit 2 | 任务目录名前缀 |
| 难度（gold patch） | 中位 **12 文件 / 189 行**（add+del；均值 610.0、最大 4096）；不含测试/CI 时 11 文件 / 185 行 | `dataset_stats.py` 复算 |
| 旧表数字 | `NEW-BENCHMARK-ONBOARDING` 旧表记 **12 文件 / 172 行**（均值 608.1、最大 4109） | **已裁决：旧表错，以 189 为准**。Lead 独立复算（`C:\sb\tmp\adjudicate_sweevo.py`）：48 题行数排序后为偶数，中位 = (170+208)/2 = **189**；均值 610.31。旧表的 172 既非 lower median(170) 也非 upper median(208)，属统计口径错误 |
| 基线验证 | `swe-evo-baseline.json` 只有 **4 条 usable**，全是 dvc 的 1–2 文件 / 2–21 行小改动题 | 选择偏差见 §5 |
| pilot | 5 题 × 2 = 10 trial，**5/10 可复算**（reward 在 `verify/jobs/`，10 个 reward.txt 值 0,0,0,1,1,1,0,0,1,1）；但**镜像已全丢**，无法重跑 | 🛑 **更正 M5 的结论**：M5 原称「trial 无 reward」，实为只查了 `jobs/` 未查 `verify/jobs/`（Lead 已核实）。正确分级是「**可重算、不可重跑**」，不是「不可复现」 |

---

## 2. 饱和：参数化的四组定义（不是「26 或 28」的问题）

**根因：组数不同 + 阈值不同 + 统计对象（题级均值 vs trial 级）不同。**

| 口径 | 定义 | 结果（/40） | 对应文档 |
|---|---|---|---|
| **S1a** | 5 组（3.2.5、3.2.7、mini、Claude、OpenCode）的**题级 partial 均值全部 == 1.0** | **25** | 本次统一口径（最严格） |
| **S1b** | 4 组（不含 3.2.7）题级均值全部 == 1.0 | **26** | `DEEP-ANALYSIS:35` 的 26 |
| **S2** | 题级所有观测均值 **>= 0.995**（`benchmark_health.py` 的 `SATURATED`） | **29**（脚本直接算）；`benchmark_health.py` 重跑得 **28** | `health.md` 的 28 |
| **S3** | 5 组题级均值全部 **>= 0.99** | **29** | 宽松近似口径 |

> **S2 的 28 vs 29 差 1**：`benchmark_health.py` 在题名匹配/`n>=3` 过滤上与本脚本略有不同（它把同一题按 34 字符短名合并、并跳过无法匹配的题）；`health.md` 的 28 可由 `benchmark_health.py --dataset C:\sb\analysis\dataset.json --out <tmp>` **完整复现**（本次实测 healthy=4/saturated=28/broken=3/flaky=2/weak=3/dead=0）。**引用 28 时请注明「benchmark_health.py 口径」**。

**统一建议**：正文引用 **S1a=25（5 组、严格）** 与 **S2=28（health 口径）** 两个数，并注明：「25 = 5 组全部 100% 部分得分；28 = 题级均值≥0.995」。不要只写「26/40」或「28/40」而不带口径。

---

## 3. 区分度：题级 vs trial 级、阈值 0.02/0.03/0.05

| 口径 | 定义 | 结果（/40） | 对应文档 |
|---|---|---|---|
| **D1** | 题级「组均值」的跨组 pstdev **>= 0.02** | **7** | 本次统一口径（题级） |
| **D2** | **trial 级** partial（含两 repeat）的跨组 pstdev >= 0.02 | **8** | `DEEP-ANALYSIS:39` 的 8 |
| **D3** | 题级组均值 pstdev >= 0.03 | **6** | `health.md` healthy 的 sd 阈值（另需 0.05<mean<0.99，最终 healthy=4） |
| **D4** | trial 级 pstdev >= 0.05 | **6** | — |

**根因**：DEEP 的 8 是 **trial 级 sd**（两 repeat 不平滑），题级口径只有 7；`health.md` 的 healthy=4 是「sd>=0.03 且 0.05<均值<0.99」的复合条件，不是同一指标。引用时必须写「trial 级 sd」或「题级 sd」。

---

## 4. broken：两种判据，两个都对

| 判据 | 定义 | 结果 | 题目 |
|---|---|---|---|
| **B1（health.md 的 broken）** | 同一测试在 **≥2 个不同 agent** 中各自**稳定失败 ≥2 次**（`benchmark_health.py` 判据） | **3 题** | `element-hq__element-web-772df30212`、`qutebrowser__qutebrowser-fec187c2c`、`tutao__tutanota-51818218c6ae33de00` |
| **B2（DEEP 的「环境性不可过」）** | 每 trial **恒只挂 1 个测试**（失败数 min==max==1，即 N-1/N 的单测试卡死） | **2 题** | `qutebrowser__qutebrowser-fec187c2c`、`tutao__tutanota-51818218c6ae33de00` |

**根因**：`element-hq__element-web-772df30212` 的失败测试 `test/utils/notifications-test.ts | createLocalNotification` 在 4 个 agent 中都有稳定失败（满足 B1），但它每 trial 的失败数在 **1–8 之间波动**（不是恒定单测试），所以不满足 B2。两者问的是不同问题：B1 = 「是否有跨 agent 共性失败」；B2 = 「是否被单个环境测试卡死」。

**统一建议**：broken 写 **3（B1，health 口径）**，并注明「其中 2 题是单测试环境卡死（B2）；element-772 是 1–8 个测试波动失败，属共性失败但非单测试卡死」。

---

## 5. 已知缺陷（必须随数字声明）

1. **gold-check 不是全绿**：36 good / 1 bad / 3 null；bad 题（element-923ad4323b20）不在 40 题内，3 null 未补齐。见 `gold-summary.json`。
2. **SWE-EVO 假题**：`pydantic 2.7.1` 的 f2p 在基线全过，是假题；`swe-evo-baseline.json` 只留 usable、无 broken/fake 逐题留档，剔除率不可复算。
3. **SWE-EVO p2p 基线失败**：dask 那题 2861 个 p2p 只有 1222 个基线通过（57% 失败）；`usable` 集系统性偏向小改动题（4 条全是 dvc 1–2 文件/2–21 行）。
4. **SWE-EVO 镜像**：`ghcr.io/epoch-research` 6 题镜像版本不匹配（`NEW-BENCHMARK-ONBOARDING` §6）；本地 sweevo/sweb.eval 镜像仅 8 个（M5），48 题未全拉。
5. **pilot 的镜像已全丢**（10 个 `docker image inspect` 全 rc=1，见 M5）→ **不可重跑**。但 **5/10 本身可复算**：10 个 `reward.txt` 都在 `verify/jobs/` 下（值 0,0,0,1,1,1,0,0,1,1）。所以正确分级是「可重算、不可重跑」，**不是**「不可复现」——M5 原报告的「trial 无 reward」是误判（只查了 `jobs/` 未查 `verify/jobs/`）。
6. **40 题是开发迭代集**：不是 holdout，提示词规则从这套题调出，偏置方向对 SAYACODE 有利；独立 holdout 从未执行。
7. **难度数字三口径**：gold=3/70、全 agent=3/72、SAYACODE=2/64——引用时必须写对象；把 72 当 gold 是**错误**（旧 `NEW-BENCHMARK` 的 2026-11-07 复核注就犯了这个错）。

---

## 6. 对「是否该换题库」的结论

**已证（有本次复算支持）：**
- 旧 40 题**高度饱和**：严格口径 25/40（5 组全部 100% 部分得分）、health 口径 28/40（≥0.995）；可区分题仅 **7–8/40**（取决于 sd 口径）。
- 旧 40 题**规模小**：gold 中位 3 文件 / 70 行，显著小于 SWE-EVO 的 12 文件 / 189 行（文件 4×、行数 2.7×）。
- 旧 40 题有 **3 题跨 agent 共性失败**（其中 2 题单测试环境卡死），应从对比中排除或单列。
- 因此「继续在 40 题上加重复」的边际信息量很低——饱和题加重复不会增加区分度。

**待验（不能写成已证）：**
- 「新题库一定能区分模型」——**未证**：pilot 仅 5 题、10 trial，且选择偏差（4 小 dvc 题 5/8 过、唯一重题 dask 0/2）；48 题镜像未全拉、基线验证只有 4 条 usable。
- 「旧 40 题四组 75–85% 是因为题太浅」——**待检验假设**：长上下文 A/B 未跑；已观测到的只是饱和与低区分度。
- 「换题库后分数会下降/上升」——无数据。

**可写进决策的表述**：旧题集饱和、区分度不足、规模偏小（已证）；换题库是合理方向（证据支持）；但新题库的判别力尚未验证（待验），需要 20–40 题、按 gold 改动量分层、先做基线验证与镜像对齐。

---

## 7. 口径定义表（核心）

| 指标 | 用什么算 | 分母 | 阈值 | 备注 |
|---|---|---|---|---|
| 题级 partial | `verifier/output.json` 的 `tests[].status`（PASSED 比例） | 每题有 output.json 的 trial | — | 不能再用 `test-stdout.txt`（见 ledger §5.1） |
| 饱和 S1a/S1b | 5 组 / 4 组的题级 partial 均值 | 40 题（≥3 组观测） | 每组均值 == 1.0（>=0.9995） | S1b 不含 3.2.7 |
| 饱和 S2 | 题级所有观测均值 | 40 题 | >= 0.995 | `benchmark_health.py` 的 SATURATED |
| 饱和 S3 | 5 组题级均值 | 40 题 | 每组 >= 0.99 | 宽松 |
| 区分度 D1/D2 | 题级组均值 / trial 级 partial 的跨组 pstdev | 40 题（≥3 组） | 0.02 / 0.03 / 0.05 | D1 题级=7、D2 trial 级=8 |
| broken B1 | 同一测试跨 ≥2 agent 各稳定失败 ≥2 次 | 每题（有 output.json 的 agent） | agent 数 ≥2、重复 ≥2 | health 口径 |
| env_impossible B2 | 每 trial 失败测试数 | 每题全部 trial | min==max==1 | DEEP 口径 |
| 难度（gold） | `solution/gold_patch.diff` | 40 题 / 48 题 | files、lines(+/-) | 含/不含 test/CI 两版 |
| 难度（agent） | `agent/model.patch` | 477（全 agent）/158（SAYACODE） | files、lines(+/-) | 引用必须写对象 |
| gold-check | `gold-summary.json` | 40 job | — | 36 good / 1 bad / 3 null |

---

## 8. 复算命令

```powershell
cd C:\develop\sayacode-bench

# 1) 全部指标（JSON 可保存）
python scripts\dataset_stats.py
python scripts\dataset_stats.py --json C:\sb\tmp\explore\m5\stats.json

# 2) health.md 口径（28 saturated / 3 broken / 4 healthy）——输出到 tmp，避免覆盖
$env:PYTHONPATH = 'C:\develop\sayacode-bench\src'
python scripts\benchmark_health.py --out C:\sb\tmp\explore\m5\health-recheck.md

# 3) 题集 sha256
python -c "import hashlib;print(hashlib.sha256(open(r'studies/sample-40-final.json','rb').read()).hexdigest())"
```

**一句话**：旧 40 题饱和（严格 25/40、health 口径 28/40）、可区分 7–8/40、3 题 broken（2 题单测试卡死）；gold 难度 3 文件/70 行，agent 全量 3/72、SAYACODE 2/64；SWE-EVO 规模 12/189 但判别力**未验证**。换题库方向有证据支持，「新题库能区分模型」仍是待验假设。
