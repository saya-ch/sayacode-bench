# R1｜评测方法论与统计方法审计（批判性）

> **审计对象**：2026-10-29 至 2026-11-06 期间 SAYACODE Bench 的全部评测实验（v1 → v2 → v3 → v4 → 新题库试点）。
> **审计性质**：设计与统计层的独立复核。只读代码、文档与落盘产物；未重跑任何 trial、未调用模型。
> **审计立场**：本文件不承担"平衡叙述"的义务。**已被证伪的结论直接判死**；证据不足的断言标记为"未验证"而不写成"可能有局限"；每一条批评都给出可复核的位置。
> **写作日期**：2026-11-07。
> **与现有文档的关系**：不修改任何既有文档；本文件对既有文档的结论做第三方判定，冲突处以证据为准。

---

## 目录

- [0. 执行摘要：七条判死](#0-执行摘要七条判死)
- [1. 审计范围、证据等级与判定规则](#1-审计范围证据等级与判定规则)
- [2. 缺陷总表](#2-缺陷总表)
- [3. 逐条缺陷详情](#3-逐条缺陷详情)
  - [3.1 分母与口径（D01–D05）](#31-分母与口径d01d05)
  - [3.2 测试面与 strict 口径（D06–D09，核心）](#32-测试面与-strict-口径d06d09核心)
  - [3.3 缺失分类、补跑与对账（D10–D15）](#33-缺失分类补跑与对账d10d15)
  - [3.4 统计方法（D16–D21）](#34-统计方法d16d21)
  - [3.5 重复与方差（D22–D24）](#35-重复与方差d22d24)
  - [3.6 开发集、制品身份与模型身份（D25–D28）](#36-开发集制品身份与模型身份d25d28)
  - [3.7 跨批次与混杂（D29–D32）](#37-跨批次与混杂d29d32)
  - [3.8 指标采集与题库判别力（D33–D36）](#38-指标采集与题库判别力d33d36)
- [4. 三分法：站得住 / 描述性 / 推理冒充证据](#4-三分法站得住--描述性--推理冒充证据)
- [5. 三状态总表](#5-三状态总表)
- [6. 如果重做一遍：实验设计](#6-如果重做一遍实验设计)
- [7. 对现有对外表述的逐句修法](#7-对现有对外表述的逐句修法)
- [8. 证据索引](#8-证据索引)

---

## 0. 执行摘要：七条判死

以下七条不是"需要注意的局限"，而是**当前结论链上的断点**。在修复或重跑之前，任何建立在其上的数字都不应对外使用。

1. **strict 口径（"扣除靠改 `.snap` 通过的 pass"）的理论前提是错的，整列数字作废。**
   `PROTOCOL-V2 §5.1`、`TEST-EDIT-ANALYSIS`、`strict_compare.py` 与 v3 报告都断言"verifier 不重置 `__snapshots__`"。实测 642/642 个 `tests/test.sh` 在判分前对 `*__snapshots__/*` 执行 `git checkout HEAD`（`test.sh:97-105`），且该段的 `__NONE__` 哨兵使跳过分支永不触发。因此 agent 对已跟踪快照的修改在判分时**已被还原**，strict 扣除的 4/3/6 个 pass 属于**错误归因**。详见 [D06](#d06strict-口径的理论前提被证伪p0)。

2. **"改快照通过"与"删掉快照修改后能否通过"从未做过反事实检验。**
   `strict_compare.py:138-141` 的判据是"patch 中出现 `.snap` 路径"，这是**相关性**，不是因果。即使快照真的不被重置，也不能据此断言该 trial 的通过依赖快照。详见 [D08](#d08strict-口径用相关性替代因果p1)。

3. **四组正式结果不是同批次实验，却被当作一张对照表使用。**
   SAYACODE 行来自 `v4-327`（11-06，PyPI 3.2.7，served 零 `hy3-x`），三个基线来自 `v2-325`（11-02~11-04，served 约 14.3% `hy3-x`），并发、网络修复状态、缺失构成均不同。`STATUS.md:24` 自己承认"只可做描述性对照"，但同文件 `:7` 仍以"四组对照"陈述结论，且 §2.1 给出了跨批次 McNemar 的 p 值。详见 [D29](#d29四组正式表混用两个批次p0)。

4. **"检测 10pp 差异需约 330 题"没有出处。**
   `STATUS.md:114`、`LARGE-EVAL-SET.md:14` 反复引用 330，但唯一的设计文档 `MULTI-MODEL-PLAN.md:98-106` 只给出"≥100 题、CI 约 ±9pp"，从未推导 330。这个数字支撑了"扩样到 100 题仍不足"的判断，而它本身不可追溯。详见 [D18](#d18330-题功效数字无出处p1)。

5. **`timeout` 是声明了但代码永远返回不到的分类。**
   `formal.py:35` 的 `MISSING_CLASSES` 含 `timeout`，但 `formal.py:464-476` 的 `classify_missing` 没有 timeout 分支。一个超时但有部分 patch 的 trial 会落到 `unverified`（协议规定**可补**），而协议 `PROTOCOL-V2 §6` 明确 `timeout` **不补**——直接违反自己的补跑纪律。详见 [D12](#d12timeout-分类声明但不可达p0)。

6. **开发集分数被当作能力分数使用，且偏置方向对被测对象有利。**
   40 题在 `README.md:41`、`AGENTS.md:20` 被定义为开发迭代集，`protocol.md:157` 明确禁止把开发期数字当正式成绩。SAYACODE 的提示词规则 R1–R5 正是从这 40 题的失败个案调出。`RETROSPECTIVE §5.1` 承认了这一点，但 `FORMAL-RESULTS-20261105-v3.md:136` 的"可写进简历的口径"仍直接写 78.8%，没有附偏置声明。详见 [D25](#d25开发集当正式成绩已承认但仍在对外使用p0)。

7. **同一批数据在不同工具里给出不同的通过数与缺失数，且陈旧产物未重生成。**
   `claude-code` 在 `FINAL-SUMMARY-V4.json` 是 62 pass、在 `dataset.json` 的 `partial==1.0` 是 65；`mini-swe` 缺失数在 `STRICT-COMPARE.json` 是 2、在 `FINAL-SUMMARY-V4.json` 是 1；`mini-swe` 的 `touches_snap` 在 `dataset.json` 是 0、在 `STRICT-COMPARE.json` 的 `snap_passes` 是 4。详见 [D14](#d14同一批数据多工具结果不一致p0)。

**一句话结论**：这套评测的**基建与轨迹审计是同类工作中偏强的**（独立 pristine 重放、适配健康审计、三口径分母、缺失分类、对账与 lint 工具都已建成），但**统计叙事层建立在两个错误前提（snap 不重置、四组同批次）和一个未验证数字（330 题）之上**。当前可以对外说的只有"未检出显著差异"，其余排名、差距、口径敏感性结论一律需要重跑或撤回。

---

## 1. 审计范围、证据等级与判定规则

### 1.1 范围

| 批次 | 内容 | 结果根 | 状态 |
|---|---|---|---|
| v1（10-29~10-31） | 40 题 × 2 × 3 agent = 240 trial | `C:\sb\hard\formal-240` | 全部作废 |
| v2（11-01~11-02） | 同设计重跑，产品 3.2.5 | `C:\sb\hard\v2-325` | 三 agent 历史结果 |
| v3（11-04） | 换 Claude Code 作第三基线 | `C:\sb\hard\v2-325` | 四组 |
| v4（11-05~11-06） | 加 OpenCode；SAYACODE 换 3.2.7 | `C:\sb\hard\v2-325`、`C:\sb\hard\v4-327` | 四组（混批次） |
| 新题库试点（11-06） | SWE-EVO 5 题 × 2 | `C:\sb\newset\runs\pilot1` | 链路验证 |
| 大评测集（11-05） | 100 题 × 1 重复设计 | `studies/large-sample-v1.json` | **未开跑** |
| 上下文 A/B（11-05） | 12 题 × 2 档 × 4 组设计 | — | **未开跑** |

### 1.2 证据等级（本审计的判定依据，从强到弱）

| 等级 | 含义 | 示例 |
|---|---|---|
| **E1 代码可执行语义** | 直接读源码/脚本，结论可由代码路径唯一确定 | `test.sh` 的 `git checkout` 分支；`classify_missing` 的分支覆盖 |
| **E2 产物可核对** | 结果目录里的 JSON/reward/patch 可逐条重算 | `STRICT-COMPARE.json`、`dataset.json`、`FINAL-SUMMARY-V4.json` |
| **E3 文档陈述** | 只在文档里写过，无产物或代码支撑 | "330 题"、部分"修复已生效"的声明 |

**判定规则**：
- E1 与 E3 冲突 → 判 E1 胜，文档结论作废；
- E2 与 E3 冲突 → 以产物为准并标注产物时间戳（陈旧产物的声明不算已修复）；
- 只有 E3 支撑的结论 → 标记"未验证"，不得进入三分法的"站得住"。

### 1.3 三状态定义（全文统一）

| 状态 | 定义 | 判定门槛 |
|---|---|---|
| **已验证** | 有 E1 或 E2 证据，且可被第三方按文档复算 | 至少一条 E1/E2 |
| **未验证** | 只有 E3 陈述，或证据不足以排除替代解释 | 无 E1/E2，或只有间接 E2 |
| **已证伪** | 有 E1/E2 证据与命题直接矛盾 | 至少一条 E1/E2 且方向相反 |

---

## 2. 缺陷总表

> 严重度：**P0** = 会改变对外结论；**P1** = 会改变结论的置信度；**P2** = 影响可复现性/可读性，不改变结论。
> 状态：❌ 未修复 · ⚠️ 部分修复 · ✅ 已修复（含证据）

| ID | 缺陷 | 严重度 | 状态 |
|---|---|---|---|
| D01 | v1 三套分母并列（80/80/65）导致虚假 17.4pp | P0 | ✅ 已修复 |
| D02 | observed 口径幸存者偏差（只报 observed 会高估） | P0 | ✅ 已修复 |
| D03 | "planned 主报"与"strict 排名"自相矛盾 | P0 | ❌ 未修复 |
| D04 | planned 字段双轨（`strict_compare` 的 `planned` 与 `--planned` 参数不一致） | P2 | ❌ 未修复 |
| D05 | v2 用"共同题"做 McNemar，缺失非随机导致选择性排除 | P1 | ✅ 已被 v3 取代 |
| D06 | **strict 口径的理论前提被证伪** | **P0** | ❌ 未修复 |
| D07 | **"verifier 不重置 `__snapshots__`"是事实错误** | **P0** | ❌ 未修复 |
| D08 | strict 口径用相关性替代因果（无反事实检验） | P1 | ❌ 未修复 |
| D09 | strict 判定依赖正则，且 `missing_patches` 时保守计通过 | P2 | ❌ 未修复 |
| D10 | 缺失分类 6 类 / 7 类 / 6 类三套并存 | P1 | ❌ 未修复 |
| D11 | `empty_patch` 与 `infra` 的历史错分（mini-swe 8 条） | P0 | ✅ 已修复（代码） |
| D12 | `timeout` 分类声明但不可达 | P0 | ❌ 未修复 |
| D13 | 补跑选择性：补哪些由分类决定，分类有改写历史 | P1 | ⚠️ 部分 |
| D14 | 同一批数据多工具结果不一致（pass/missing/snap） | P0 | ❌ 未修复 |
| D15 | 陈旧产物未重生成（`STRICT-COMPARE.json` 早于修复声明） | P1 | ❌ 未修复 |
| D16 | McNemar 二值定义（all_repeats_pass）与主表 pass@1 不同口径，未在表头声明 | P1 | ⚠️ 部分 |
| D17 | Bonferroni 的 α 在 α/3 与 α/6 间混用，主假设未预注册 | P1 | ❌ 未修复 |
| D18 | "330 题"功效数字无出处 | P1 | ❌ 未修复 |
| D19 | Wilson CI 在部分报告中缺席（v3 只给 bootstrap） | P2 | ❌ 未修复 |
| D20 | bootstrap 的题级单位实现正确，但"仓库簇"只在敏感性脚本，未被主报告使用 | P2 | ⚠️ 部分 |
| D21 | pass^2 / pass@2 无区间，被当作点估计引用 | P1 | ❌ 未修复 |
| D22 | 重复 2 次无法分离系统性方差与随机方差 | P1 | ❌ 未修复 |
| D23 | pass^2 在 n=2 时估计极不稳定，未给不确定性 | P1 | ❌ 未修复 |
| D24 | `DEEP-DIVE` 与 `DEEP-ANALYSIS` 对"翻转题"给出不同处方（加重复 vs 减重复） | P1 | ❌ 未修复 |
| D25 | 开发集当正式成绩（已承认，仍在外宣使用） | P0 | ❌ 未修复 |
| D26 | 制品身份断链（78.8% 对应未发布 wheel） | P1 | ✅ 已修复（3.2.7 重跑） |
| D27 | 两套 `CANONICAL_MODEL` 常量不一致 | P2 | ❌ 未修复 |
| D28 | 模型身份曾被误标（`auto-hy3` 写成 DeepSeek） | P0 | ✅ 已修复 |
| D29 | 四组正式表混用两个批次 | P0 | ❌ 未修复 |
| D30 | `hy3-x` 额度池占比组间差 6 倍，被断言"不构成混杂"但未检验 | P1 | ❌ 未修复 |
| D31 | 跨批次配对的 McNemar 把批次效应算进"组间差异" | P1 | ❌ 未修复 |
| D32 | 并发数跨批次不同（2–4 vs 4/1），未做敏感性分析 | P2 | ❌ 未修复 |
| D33 | partial credit 未进采集管线，只用事后脚本补算 | P1 | ⚠️ 部分 |
| D34 | "部分得分 94–99% 说明基本做对了"是推理冒充证据 | P1 | ❌ 未修复 |
| D35 | 题库体检两套结论（26 饱和/8 区分 vs 28 饱和/4 healthy） | P1 | ❌ 未修复 |
| D36 | PILOT 的"静态预测 60% ≈ 随机"在 n=10 下未给区间 | P2 | ⚠️ 部分 |

---

## 3. 逐条缺陷详情

### 3.1 分母与口径（D01–D05）

#### D01｜v1 三套分母并列导致虚假 17.4pp（P0，✅ 已修复）

**缺陷**：v1 报告把 SAYACODE 55/80、mini-swe 69/80、Codex 56/65 并列成一张表，并据此宣称"落后 17.4pp"。前两者缺失按失败计入分母，Codex 的 15 个 infra 缺口因无 `reward.txt` 被排除出分母。

**证据**：
- `docs/archive/FORMAL-RESULTS-20261031.md:10-14`（三套分母并列）；
- `scripts/final_summary.py:155`（`trials = [t for t in lst if t["reward"] is not None]`，分母 = 有 reward 的 trial）；
- `C:\sb\hard\formal-240\FINAL-SUMMARY.json`（sayacode n=80/pass=55、mini-swe n=80/pass=69、codex n=65/pass=56）；
- 统一 80 分母后 Codex = 56/80 = 70.0%。

**后果**：把 1.2pp 的观测差放大成 17.4pp 的"能力差"，并触发了后续整套 v2 重建（虽然重建本身带来了基建进步，但起点结论是假的）。

**状态**：✅ 已修复。v2 起统一 planned=80 分母（`PROTOCOL-V2.md:26-34`），并有 `lint_metrics.py` 检查"各 agent planned 分母必须相同"。

**补救**：无。但需注意：v1 的作废是**结论作废**，不是数据作废；`formal-240` 原始产物仍可用于复盘归因（本审计的第 1 节即用了它）。

---

#### D02｜observed 口径的幸存者偏差（P0，✅ 已修复）

**缺陷**：v2 时期一度只报 observed 通过率，而 observed 是"有 reward/终态的子集"，天然排除环境失败的 trial。

**证据**：
- `PROTOCOL-V2.md:34`：「mini-swe observed 84.8%，但 planned 只有 70.0%（56/80，只有 66 条终态）」；
- `FORMAL-RESULTS-20261102-v2.md:44`：「mini-swe 的 observed 84.8% 存在幸存者偏差（66/80，task_macro 仅 33/40）」。

**后果**：若只报 observed，mini-swe 会被高估约 15pp——这不是小偏差，足以反转排名。

**状态**：✅ 已修复。三口径（planned/observed/task_macro）同报成为硬规则（`PROTOCOL-V2.md:30`、§7.3 检查清单）。

**补救**：无。

---

#### D03｜"planned 主报"与"strict 排名"自相矛盾（P0，❌ 未修复）

**缺陷**：协议规定 planned 是唯一可对外使用的分母、strict 只作敏感性；但 v3 报告的标题结论、`STATUS.md` 的"一句话状态"、`RETROSPECTIVE` 的核心结论、以及简历口径全部用 strict 排名。

**证据**：
- `PROTOCOL-V2.md:30`：「**主报 planned**，对外唯一可用分母」；`:89`：「**主报口径始终是 planned**」；
- `FORMAL-RESULTS-20261105-v3.md:6`：把 strict 写进标题级口径；`:44-55`：三口径三种排名；
- `STATUS.md:7`：「strict **80.0% / 76.2% / 73.8% / 67.5%**……两种口径名次不同」；
- `RETROSPECTIVE-20261105.md:230` 自认：「§87 说 planned 是主报、strict 只作敏感性，与 v3 用 strict 排名冲突」。

**后果**：同一份数据有两个"主结论"：
- 按 planned：mini-swe 85.0% > SAYACODE 76.2%（差 8.8pp）；
- 按 strict：mini-swe 80.0% > SAYACODE 76.2%（差 3.8pp）。

对外受众无法知道该引用哪一个。更严重的是，strict 本身无效（见 [D06](#d06strict-口径的理论前提被证伪p0)），所以"strict 下差距缩到 3.8pp"这个叙事**建立在错误口径上**。

**状态**：❌ 未修复。文档冲突被记录在 `RETROSPECTIVE §6` 第 6 条，但未改。

**补救**：
1. 若 strict 被证伪（本审计结论），删除 strict 列，只保留 planned + observed；
2. 若坚持保留 strict 作为敏感性，必须在**每张表头**写"主报口径 = planned，strict 仅敏感性，不用于排名"；
3. 对外表述统一到 planned，并在同一句给出 observed 与缺失数。

---

#### D04｜`planned` 字段双轨（P2，❌ 未修复）

**缺陷**：`strict_compare.py` 的 `planned` 有两个来源——`_collect()` 返回的 `planned = len(trials)`（实际发现的 trial 目录数），与 `analyse(agent_dir, planned_total)` 用的 `--planned` 参数（默认 80）。`pass_rate_planned` 用参数，`planned` 字段用实测值。

**证据**：`scripts/strict_compare.py:108`（`planned = len(trials)`）、`:143`（`"planned": planned_total`）、`:148`（`"missing": planned_total - observed`）、`:172`（`analyse(agent_dir, args.planned)`）。

**后果**：当某 agent 的 trial 目录数 ≠ 80（v2 的 mini-swe 77 个、v4 的 79 个）时，输出里 `planned` 显示实测值，但百分比按 80 算。读者会看到 `planned=78` 而 `planned%=85.0` 这种自相矛盾的组合。

**状态**：❌ 未修复。`STRICT-COMPARE.json` 里所有 agent 的 `planned` 都是 80（因为目录数恰好补齐），所以尚未暴露；一旦有缺失目录就会暴露。

**补救**：把 `planned` 字段改为 `planned_total`，另设 `discovered` 字段记录实测目录数；或在 `_collect` 里断言 `len(trials) == planned_total`。

---

#### D05｜"共同题"McNemar 的选择性排除（P1，✅ 已被 v3 取代）

**缺陷**：v2 的 McNemar 用"两组都有数据的题"（共同题）做配对。v2 时 mini-swe 缺失 14 条（qutebrowser `setup_timeout` 等），共同题只剩 32/40，而这些被排除的题恰恰是 mini-swe 环境失败的题。

**证据**：
- `FORMAL-RESULTS-20261102-v2.md:21-23`：mini-swe vs SAYACODE 共同题 **32**、delta +1.6%、p=0.727；
- 同批 planned 口径：mini-swe 70.0% vs SAYACODE 78.8%（SAYACODE 高 8.8pp）；
- `formal_stats.py:185-186`（`common = sorted(set(rates_a) & set(rates_b))`）。

**后果**：**McNemar 的方向与 planned 口径相反**——配对检验说 mini-swe 略高（+1.6%），planned 说 SAYACODE 高 8.8pp。原因是缺失非随机：共同题集随 agent 的缺失而变化，配对的可比性被破坏。

**状态**：✅ 已被 v3 取代（v3 的共同题 38–39/40，且缺失大幅减少）。但**这个逻辑缺陷没有被写进协议**——`PROTOCOL-V2` 没有规定"缺失非随机时共同题 McNemar 不可用"。

**补救**：在协议中新增一条：**共同题数 < planned 题数时，必须在表内同时给出被排除题在两侧的通过情况**；若排除题两侧缺失不对称，McNemar 只作敏感性、不作主检验。

---

### 3.2 测试面与 strict 口径（D06–D09，核心）

> 这一节是本审计的核心。**strict 口径是四组排名与"差距缩窄"叙事的唯一支撑，而它的前提是错的。**

#### D06｜strict 口径的理论前提被证伪（P0）

**缺陷**：strict 口径的定义是"扣除靠改 `__snapshots__/*.snap` 通过的 pass"（`PROTOCOL-V2.md:79-87`、`FORMAL-RESULTS-20261105-v3.md:6`）。该定义成立的前提是"verifier 在判分前不重置快照目录"。这个前提与代码事实直接矛盾。

**证据（E1，代码语义）**：全部 642 个任务的 `tests/test.sh` 都包含同一段重置逻辑，且对快照目录执行 `git checkout HEAD`：

```
.../v2/tasks/instance_*//tests/test.sh
L37: CODE_DIRS = {'tests', 'test', '__tests__', 'spec', 'specs'}
L38: DATA_DIRS = {'testdata', 'test_data', 'fixtures', 'fixture', 'mocks', 'mock', '__snapshots__'}
L43: if any(s in DATA_DIRS for s in parents):   → return False（不算测试代码）
L71: T) git checkout HEAD -- "$path"            → 重置测试代码
L82-94: v5 段：对 test_patch 涉及的已跟踪路径 git checkout HEAD
L97: git diff --name-only HEAD -- > /tmp/v6_modified.txt
L100: *testdata/*|*test_data/*|*fixtures/*|*fixture/*|*mocks/*|*mock/*|*__snapshots__/*)
L101: echo "$p" | grep -qE '(__NONE__)' && continue
L102: git checkout HEAD -- "$p"                  → 重置快照/数据目录
L108: git apply --verbose /tests/test_patch.patch
```

`L101` 的 `__NONE__` 是一个永不匹配的哨兵：正常路径不包含该字符串，`grep -q` 返回非零，`&&` 短路，`continue` **不会执行**，因此 `L102` 的 `git checkout HEAD` **总是执行**。

`TEST-EDIT-ANALYSIS-20261102.md:10` 引用的是 `test.sh:38,43`——它只读了 `is_test_code()` 的 DATA_DIRS 排除分支，**漏掉了 `test.sh:97-105` 的 v6 段**，这是典型的"部分代码阅读导致结论翻转"。

**证据（E2，逐 trial 核对）**：以被扣分的 `mini-swe-element-hq__element-web-9bf77963ee-r1` 为例：
- patch 修改两个文件：`src/components/views/settings/devices/DeviceDetails.tsx`、`.../DeviceVerificationStatusCard.tsx`，以及两个快照 `__snapshots__/CurrentDeviceSection-test.tsx.snap`、`__snapshots__/DeviceDetails-test.tsx.snap`；
- 这两个快照**恰好是官方 `test_patch.patch` 要更新的路径**（`tests/test_patch.patch` 里 `+++ b/test/components/views/settings/devices/__snapshots__/...`）；
- 因此 agent 的快照修改会先被 v5 段（`test.sh:82-94`）还原、再被 v6 段（`test.sh:97-105`）还原，最后被官方 `test_patch` 覆盖。

**后果**：
1. **strict 列（80.0 / 73.8 / 67.5 / 76.2）整体无效**；
2. "OpenCode 的 6 个 snap pass 是四组最多、所以被 strict 拖累 7.5pp"（`RETROSPECTIVE:65`、`v3:53,110`）**不成立**；
3. "SAYACODE snap=0、所以 strict 下更干净"（`v3:54`、`STATUS:7`）**不成立**——SAYACODE 的 patch 里没有 `.snap` 是因为产品侧 `restore_existing_test_files` 先清理了，而不是因为它没有可改的快照；
4. "planned 上 mini-swe 领先 6.2pp、strict 上缩到 1.2pp"（`RETROSPECTIVE:81`）这个"缩窄"是**错误归因制造出来的**。

**状态**：❌ 未修复。`strict_compare.py:3-5` 的注释仍写"verifier 不重置快照目录"；`PROTOCOL-V2 §5.1`、`TEST-EDIT-ANALYSIS`、`STATUS:22`、`RETROSPECTIVE:39` 均未更正。

**补救（按优先级）**：
1. **立即**：在所有报告与对外材料中删除 strict 列，或明确标注"该口径前提已证伪，数字不可用"；
2. **短期**：写一个最小复现——取一个被标为 snap pass 的 trial，在干净镜像里重放时**强制 `git checkout HEAD -- '**/*.snap'`**，看 reward 是否仍为 1。如果仍为 1，则"靠快照通过"被直接证伪；
3. **中期**：如果确实存在"快照可被利用"的题（例如 untracked 的新建 `.snap`），用 `git status --porcelain` 精确区分 tracked/untracked，而不是用路径正则；
4. **长期**：把"测试面一致性"放到 verifier 侧解决（对所有 agent 统一还原数据/快照目录），而不是在分析侧做事后扣除。

---

#### D07｜"verifier 不重置 `__snapshots__`"是事实错误（P0）

**缺陷**：这是 D06 的命题形式。以下四份文档把它当作既定事实：

| 位置 | 原文 |
|---|---|
| `PROTOCOL-V2.md:74-77` | "数据/快照目录……命中则**排除、不重置**；因此修改 `__snapshots__/*.snap` 对 reward **有效**" |
| `TEST-EDIT-ANALYSIS-20261102.md:10` | "DATA_DIRS……**命中则排除，不重置**（`test.sh:38,43`）" |
| `DEEP-DIVE-20261102.md:52` | "只有含 `.snap` 的 trial 有效（`.snap` 不被 verifier 重置）" |
| `STATUS.md:22` | "`tests/test.sh` 只重置测试**代码**，`.snap` 不重置" |

**证据**：同 D06（`test.sh:97-105`）。

**后果**：这四份文档构成一条**自洽但不真实的证据链**——后来者读任何一份都会被强化，不会去读第二遍 `test.sh` 的后半段。

**状态**：❌ 未修复。

**补救**：四份文档各加一条"2026-11-07 更正"；`TEST-EDIT-ANALYSIS` 的标题与结论需重写（"改测试通过"的真正结论是"测试代码与快照都被重置，patch 含测试文件不构成作弊，也不构成能力差异"）。

---

#### D08｜strict 口径用相关性替代因果（P1）

**缺陷**：`strict_compare.py:138-141` 的判据是"pass trial 的 patch 是否修改了 `.snap` 文件"。这是**该 trial 的一个属性**，不是"该 trial 的通过原因"。报告把它当作"靠快照通过"，跳过了反事实检验。

**证据**：
- `scripts/strict_compare.py:23`（`SNAP_RE = re.compile(r"(__snapshots__/.*\.snap$|\.snap$)", re.IGNORECASE)`）、`:137-141`；
- `TEST-EDIT-ANALYSIS-20261102.md:25`：唯一给出的"证据"是列举了哪些 trial 改了 snap，**没有一个"不改也会失败"的对照**。

**后果**：即使 D06/D07 不成立（即快照确实可改），strict 仍然会**错误扣除**"改了快照但通过靠源码"的 trial。反过来，它也会**漏掉**"没改快照但通过靠其他测试面漏洞"的 trial。

**状态**：❌ 未修复。

**补救**：反事实检验（同 D06 补救 2）。若成本不允许，至少把该列改名为 `touches_snap_pass`（"patch 触碰快照且通过"），而不是 `strict`（暗示"严格判定"）。

---

#### D09｜strict 判定的两个实现细节（P2）

**缺陷 1**：`_patch_files()` 只解析 `+++ b/` 行（`strict_compare.py:33-39`）。删除文件（`+++ /dev/null`）与重命名（`rename to`）不会进入文件集，因此"删除快照"不会被计为 snap pass。

**缺陷 2**：`missing_passes`（有 pass 但找不到 patch）时"保守计入通过"（`strict_compare.py:133-136`）。这在方向上是保守的（不冤枉），但会**系统性低估** snap pass——而低估的方向恰好有利于"snap pass 很少"的叙事。

**证据**：`strict_compare.py:33-39`、`:132-136`。

**后果**：影响幅度小（v2/v3 里 `missing_passes` 未报告），但属于"未披露的判定细节"。

**状态**：❌ 未修复。

**补救**：报告 `missing_passes` 计数；把删除/重命名纳入文件集。

---

### 3.3 缺失分类、补跑与对账（D10–D15）

#### D10｜缺失分类 6 类 / 7 类 / 6 类三套并存（P1）

**缺陷**：同一套缺失分类存在三个版本：

| 位置 | 类别数 | 集合 |
|---|---|---|
| `PROTOCOL-V2.md:40-47` | **6** | `infra / no_job / timeout / empty_patch / model_fault / unverified` |
| `src/sayacode_bench/formal.py:35` | **7** | 上述 6 类 + `unattributed` |
| `scripts/reconcile_results.py`（`ALLOWED_MISSING`） | **6** | 上述 6 类（**无** `unattributed`） |

**证据**：见上表行号。

**后果**：
- 若 `formal.py` 产出 `unattributed`（job 存在但映射不到冻结题集），`reconcile_results.py` 会把它判为**非法分类**，对账工具报错或漏检；
- 协议文档无法指导实现者写出正确分类；
- `RETROSPECTIVE:230` 承认"§3 有 infra/timeout 类，代码里没有"——那是修复前的状态；修复后变成"文档 6 类、代码 7 类、对账 6 类"，**不一致只是换了个方向，没有消失**。

**状态**：❌ 未修复。

**补救**：以 `formal.py:35` 为唯一真源，更新 `PROTOCOL-V2 §3` 与 `reconcile_results.ALLOWED_MISSING`；并加一个单测断言三处集合相等。

---

#### D11｜`empty_patch` 与 `infra` 的历史错分（P0，✅ 已修复代码）

**缺陷**：v2 把 mini-swe 的 8 条"agent 安装阶段网络失败"错分为 `empty_patch`（不补），导致"违反协议补跑"的假象。

**证据**：
- `RETROSPECTIVE-20261105.md:192-213` 完整复盘；
- `formal.py:38-50`（`INFRA_EXCEPTIONS`）、`:469-471`（优先判 infra）；
- 原始证据 `C:\sb\hard\v2-325\mini-swe\abandoned-retry-20261102-165011\`（28 个 job 的 `exception.txt`：`NonZeroAgentExitCodeError` + `apt-get exit 100` 撞 Clash fake-ip `198.18.0.17`）。

**后果**：mini-swe 的 70.0% → 85.0% 这 +15pp 一度看起来像"retry-until-pass"。修复分类后，补跑在**实质上**合规，但报告的呈现仍需同时给出补跑前后数字（`v3:33-42` 做到了）。

**状态**：✅ 代码已修复；⚠️ 报告呈现部分（v3 有补跑前后表，但摘要仍以 85.0% 为主）。

**补救**：无代码补救；报告层要求"补跑前后同表"已经成为协议（`PROTOCOL-V2 §6`），需继续执行。

---

#### D12｜`timeout` 分类声明但不可达（P0，❌ 未修复）

**缺陷**：`MISSING_CLASSES` 声明了 `timeout`（`formal.py:35`），但 `classify_missing`（`formal.py:464-476`）的分支是：

```python
if trial is not None and trial.observed: return None
if trial is None: return "no_job"
if trial.exception_type in INFRA_EXCEPTIONS: return "infra"
if trial.faults: return "model_fault"
if trial.patch_bytes is None or trial.patch_bytes == 0: return "empty_patch"
return "unverified"
```

**没有任何分支返回 `"timeout"`。**

**后果（方向性错误）**：
- 超时且 `patch_bytes == 0` → 判 `empty_patch`（**不补**），符合协议；
- 超时且 `patch_bytes > 0` → 判 `unverified`（**可补**），**违反** `PROTOCOL-V2:98`「`timeout` / `empty_patch` 属能力或行为，补跑等于给某 agent 额外机会」。
- 也就是说：**越接近完成（有部分 patch）的超时，越会被补跑**——这正是协议要防止的选择性补偿。

**证据**：`formal.py:35`、`:464-476`、`PROTOCOL-V2.md:44,98`。

**后果的实证风险**：`LESSONS-20261102-v2.md:119-123` 记录 mini-swe 在 vuls 题上因 `sleep 29` 撞 30s 工具超时而死循环，这类 trial 很可能产出部分 patch → 被判 `unverified` → 补跑。谁被补跑、补跑几次，直接决定了 85.0% 这个数字。

**状态**：❌ 未修复。

**补救**：
1. `classify_missing` 增加超时判定：`if trial.status == "timeout" or trial.exception_type in TIMEOUT_EXCEPTIONS: return "timeout"`；
2. 在 `reconcile_results` 里校验：`timeout` 类必须出现在缺失清单中（若从未出现，说明判定未生效）；
3. 对历史批次回溯：重新分类 v2/v3/v4 的 `unverified` 条目，检查其中有多少实际是超时。**这是一项必须做的回溯**，否则 85.0% / 80.0% 的可比性无法确认。

---

#### D13｜补跑的选择性（P1，⚠️ 部分修复）

**缺陷**：补跑哪些 trial 完全由缺失分类决定，而分类规则在 11-05 被**事后修改**（mini-swe 8 条从 `empty_patch` 改判 `infra`）。这意味着同一批数据在分类规则变化前后会得到不同的补跑集合，而补跑会改变通过率。

**证据**：
- `RETROSPECTIVE:192-213`（分类修改的完整过程）；
- `v3:33-42`（补跑前后：mini-swe 70.0% → 85.0%，+15.0pp）；
- `PROTOCOL-V2.md:99`（`empty_patch` 必须先排除 infra）——这条规则是 11-05 才加入的。

**后果**：
- "补跑 12/12 全部转正"（`RETROSPECTIVE:197`）在统计上并不异常（若该 agent 平均通过率 85%，12 连过的概率约 14%），但它**证明补跑的 12 条与其余 68 条同分布**——这一点没有被检验；
- 若补跑集合偏向"更容易的题"（例如安装失败发生在轻题上更快），85.0% 会被高估；
- 协议没有要求"补跑条目的通过率与未补跑条目对比"，因此无法排除选择效应。

**状态**：⚠️ 部分修复（分类代码已修，但选择效应的检验缺失）。

**补救**：
1. 报告补跑条目的**独立通过率**（12/12 = 100%）与未补跑条目的通过率（56/68 = 82.4%），并做 Fisher 精确检验。若差异显著，说明补跑条目更容易，需要在结论中标注；
2. 在协议中增加"补跑条目与未补跑条目的基线特征对比"（题目难度分层、patch 规模）；
3. 长期：补跑应**整题**补（同一题的两个重复都补），而不是只补失败的那个 repeat，避免"补到通过为止"的观感。

---

#### D14｜同一批数据多工具结果不一致（P0，❌ 未修复）

**缺陷**：三个独立工具（`FINAL-SUMMARY-V4.json`、`STRICT-COMPARE.json`、`dataset.json`）对同一批 v2-325 数据给出不同的通过数、缺失数与 snap 判定。

**证据（E2，逐字段核对）**：

| 指标 | `FINAL-SUMMARY-V4.json` | `STRICT-COMPARE.json` | `dataset.json`（`partial==1.0`） |
|---|---|---|---|
| sayacode passes | 63 | 63 | 62（n=77） |
| mini-swe passes | 68 | 68 | 67（n=78） |
| claude-code passes | **62** | 62 | **65**（n=79） |
| opencode passes | **60** | 60 | **62**（n=80） |
| mini-swe missing | **1** | **2** | — |
| mini-swe snap_passes | — | **4** | **0**（`touches_snap=0`） |
| claude-code snap | — | 3 | 4（其中 partial=1 有 2） |

**后果**：
1. **claude-code 的通过数差 3 个**（62 vs 65）。这不是舍入，而是两个指标定义不同：`partial==1.0` 是"required tests 全过"，`effective_reward==1.0` 是"官方 reward=1"。SWE-bench Pro 的 `config.json` 含 `pass_to_pass` 字段，若某题 p2p 非空且失败，partial 仍可为 1.0 而 reward=0。**报告从未说明这个差异**，而 `DEEP-ANALYSIS` 的"0/1 通过率"表用的正是 `partial==1.0`。
2. **mini-swe 的 snap 判定差 4 个**（0 vs 4）。`build_analysis_dataset.py` 的 `touches_snap` 与 `strict_compare.py` 的 `SNAP_RE` 是两个不同实现，前者漏判了 mini-swe 的全部 4 个。`DEEP-ANALYSIS` 的"snap 倾向"分析（如果用了 `touches_snap`）会得出与 v3 相反的结论。
3. **mini-swe 的缺失数差 1**（1 vs 2）。`RETROSPECTIVE §5.7` 声称"已修（加 `_read_terminal`），修后两工具在 5 组上完全一致"——但 `STRICT-COMPARE.json` 的时间戳是 11-05 17:23，早于修复声明 11-06 14:12，**产物没有重新生成**。

**状态**：❌ 未修复（缺一个跨工具的强制对账）。

**补救**：
1. 把 `reconcile_results.py` 扩展为"多源对账"：`FINAL-SUMMARY-V4` ↔ `STRICT-COMPARE` ↔ `dataset.json` 三方交叉，任何字段不一致即 fail；
2. 明确 `partial==1.0` 与 `reward==1.0` 的关系：在 `dataset.json` 里同时记录 `reward`，并在报告里统一用 reward 作为 0/1 定义；
3. 所有引用 `strict_compare` 的报告必须附上产物时间戳与脚本 commit，避免"声明已修、产物未重生成"。

---

#### D15｜陈旧产物未重生成（P1，❌ 未修复）

**缺陷**：`RETROSPECTIVE §5.7` 声称 strict_compare 的 missing 口径已修并"两工具在 5 组上完全一致"，但 `C:\sb\hard\v2-325\STRICT-COMPARE.json` 仍是修复前版本（mini-swe missing=2），且 `STATUS.md`/`v3` 的表格用的是 `FINAL-SUMMARY-V4` 的 missing=1。

**证据**：`STRICT-COMPARE.json` mtime 2026-11-05 17:23；`RETROSPECTIVE-20261105.md` mtime 2026-11-06 14:12；`RETROSPECTIVE:214-217`。

**后果**：读者若按 `STATUS §8` 的证据索引去核对 `STRICT-COMPARE.json`，会看到与正文不一致的 missing 数，进而怀疑整张表。

**状态**：❌ 未修复。

**补救**：重生成 `STRICT-COMPARE.json`；在 `STATUS §8` 每项证据后标注产物时间戳与对应脚本 commit。

---

### 3.4 统计方法（D16–D21）

#### D16｜McNemar 二值定义与主表 pass@1 不同口径（P1，⚠️ 部分修复）

**缺陷**：主表用 trial 级 pass@1（63/80），McNemar 用**题级全通过**（all_repeats_pass：两次都过才算 1）。两者不是同一个量，但并列展示时没有在表头说明。

**证据**：
- `FORMAL-RESULTS-20261105-v3.md:20`（"题级全通过，McNemar exact"）；
- `formal_stats.py:172-184`（`definition` 默认 `all_repeats_pass`；也支持 `any_repeat_pass`）；
- `PROTOCOL-V2.md:66`（"用**题级 pass（不用 best-of-2）**"——但"题级 pass"没有定义，代码默认是 all_repeats_pass）；
- `STATUS.md:36-48`（9 行 McNemar 表，未标二值定义）。

**后果**：
- all_repeats_pass 等价于 **pass^2**，测的是"稳定性"；主表 pass@1 测的是"平均完成率"。两者的不显著**不能互相替代**；
- 用 all_repeats_pass 会丢弃"一过一败"的翻转题（每组 2–7 题，`DEEP-ANALYSIS:69-77`），**降低功效**——这正是"全都不显著"的部分机械原因；
- 若改用 any_repeat_pass（pass@2），功效会提高，可能有些对比会变显著。报告**没有给出 any_repeat_pass 的结果**，而 `formal_stats.py:265-267` 明明同时计算了它。

**状态**：⚠️ 部分（代码支持两种，报告只报一种且未解释选择）。

**补救**：
1. 表头写明二值定义；
2. **同时报告 all_repeats_pass 与 any_repeat_pass 的 p 值**，并说明选择 all_repeats_pass 的理由（更严格、抗翻转）；
3. 若两者结论不一致，说明结论对二值定义敏感，需在正文标注。

---

#### D17｜Bonferroni 的 α 混用（P1，❌ 未修复）

**缺陷**：`PROTOCOL-V2.md:66` 写死 α/3 = 0.0167（对应三组 3 对比较）；`:93` 又说四组 6 对用 α/6 ≈ 0.0083。v2 用 α/3，v3 用 α/6，`STATUS.md:52` 在**9 行比较**的表下写"Bonferroni α/3 ≈ 0.0167（三组两两为上限口径）"。

**证据**：`PROTOCOL-V2.md:66`、`:93`；`FORMAL-RESULTS-20261105-v3.md:31`；`STATUS.md:52`。

**后果**：
- 9 对比较（6 对四组 + 3 对跨批次）用 α/3 是**欠校正**；用 α/9 才对应实际比较数；
- 更根本的问题：**主假设从未预注册**。如果主假设是"SAYACODE vs 三个基线"（3 对），α/3 是对的；如果是对四组做全配对（6 对），α/6；如果连跨批次也算（9 对），α/9。三种都合理，但必须在看数据前定死。
- 实际影响：最小 p = 0.070，在 α/3、α/6、α/9 下都不显著，**结论不变**。所以这是流程缺陷，不是结论缺陷——但它让"p=0.070 最接近显著"这种表述具有误导性。

**状态**：❌ 未修复。

**补救**：在 `PROTOCOL-V2` 里预注册主假设族（建议：3 对 SAYACODE-vs-基线，α/3），把其余比较标为"探索性、不校正、仅供描述"；报告分两张表。

---

#### D18｜"330 题"功效数字无出处（P1，❌ 未修复）

**缺陷**：`STATUS.md:114`、`LARGE-EVAL-SET.md:14`、`RETROSPECTIVE:169` 都引用"检测 10pp 差异需约 330 题"，但没有任何文档给出推导。

**证据**：
- `MULTI-MODEL-PLAN.md:98-106` 只写"≥100 题（CI 收窄到约 ±9pp）"、"40 题只能检出 >15pp"，**没有 330**；
- 检索全仓库，330 只出现在结论性引用处，无计算过程。

**后果**：这个数字支撑了"100 题仍然不足"的判断，进而支撑"扩样也无意义、必须换题库"的转向（`DEEP-ANALYSIS §6`、`LARGE-EVAL-SET:14`）。如果 330 是错的（例如基于两独立比例检验而非配对 McNemar，或假设了不现实的 discordant 率），整个"换题库"决策的依据会松动。

**状态**：❌ 未修复（数字仍在用）。

**补救**：
1. 给出功效计算的完整参数：α、power、双侧/单侧、配对比例、discordant 率、基线通过率；
2. 用项目自己的数据重算：v3 的 6 对里 discordant 数 4–15，若取 discordant 率 20%、目标 10pp 差异，配对 McNemar 所需 n 约 100–150（取决于假设），**未必是 330**；
3. 在得到可复算的数字前，把"330"改为"未量化（≥100 题 CI 约 ±9pp）"。

---

#### D19｜Wilson CI 在部分报告中缺席（P2，❌ 未修复）

**缺陷**：`PROTOCOL-V2 §5.1` 要求"Wilson CI 用题级 n"。`FORMAL-RESULTS-20261105-v3.md:12-18` 的主表给了 `bootstrap95`，**没有给 Wilson CI**。

**证据**：`v3:12-18`；`formal_stats.py:226-232`（Wilson 已计算，含 `wilson_task_level`）；`PROTOCOL-V2.md:64`。

**后果**：bootstrap 区间是**均值**的区间（task_macro），Wilson 是**全通过率**的区间，两者含义不同。只给 bootstrap 会让读者把"80.8% [69.2, 91.0]"误读成"全通过率的区间"。

**状态**：❌ 未修复（代码有，报告未用）。

**补救**：主表同时给 `task_macro ± bootstrap` 与 `全通过率 ± Wilson`，各占一列并写明定义。

---

#### D20｜仓库簇 bootstrap 只在敏感性脚本（P2，⚠️ 部分）

**缺陷**：`formal_stats.py:82-127` 实现了仓库簇 bootstrap（9 个仓库为簇），但 v3 主报告没有使用；只有 `analyze_sensitivity.py`（v1 时代的正式资格管线）使用，而那条管线与当前 240-trial 数据不连通。

**证据**：`formal_stats.py:82-127`、`:234`；`v3:12-18`（无仓库簇列）。

**后果**：9 个仓库内的题高度相关（例如 element-web 3 题、flipt 5 题），题级 bootstrap 会低估方差。仓库簇区间会明显更宽——这是"不显著"的另一个支持证据，但报告没用上。

**状态**：⚠️ 部分（代码有，主报告未用）。

**补救**：主表加一列"仓库簇 bootstrap 95%"，并注明"簇数仅 9，仅作敏感性"。

---

#### D21｜pass@2 / pass^2 无区间（P1，❌ 未修复）

**缺陷**：`v3:14-17` 的"题级全通过"列写 74.4% / 76.9% / 64.1% / 57.5%，没有区间。n=39–40，二项比例的 95% CI 半宽约 14–16pp。

**证据**：`v3:12-18`；`formal_stats.py:137-169`（`pass_at_k` 已计算 Wilson 与 bootstrap，但报告只引用了点估计）。

**后果**：
- `SAYACODE 74.4% vs mini-swe 76.9%` 的 2.5pp 差异，在 ±15pp 的区间下毫无意义；
- 更危险的是 `OpenCode 57.5%` 被当作"明显更低"引用（`RETROSPECTIVE:89` 的"同量级"判断），但 57.5% 的区间约 [41%, 73%]，与 74.4% 的 [58%, 87%] 大幅重叠。

**状态**：❌ 未修复。

**补救**：所有比例必须带区间；n<100 的比例一律标"点估计，区间宽 ±14pp 以上"。

---

### 3.5 重复与方差（D22–D24）

#### D22｜重复 2 次无法分离系统性方差与随机方差（P1，❌ 未修复）

**缺陷**：每题只跑 2 次。2 个观测**无法**估计题内方差（样本方差需要 ≥2 个自由度，而 n=2 只有 1 个），更无法分离"运行间随机抖动"与"系统性差异"（例如 patch 规模差异导致的稳定性差异）。

**证据**：
- `DEEP-DIVE-20261102.md:11-23`：5 题一过一败里 3 题判为"系统性"（patch 规模 3.3× / 7.3× / 59×）——但这是**人工判读**，不是方差分解；
- `DEEP-ANALYSIS-20261106.md:69-83`：每组 2–7 题翻转；
- `v3:14-17`：题级全通过率 57.5%–76.9%。

**后果**：
- `pass^2` 的估计在 n=2 时极不稳定：若真实单次通过率 p=0.8，pass^2 = 0.64，但 n=2 的估计方差极大（每次观测只有 0/1/2 三种结果）；
- "系统性方差"的判定依赖人工看 patch 大小，没有统计检验；
- 报告用 pass^2 的差异（74.4% vs 57.5%）暗示"稳定性差异"，但从未给出该差异的置信区间。

**状态**：❌ 未修复。

**补救**：
1. **至少 3 次重复**才能估计题内方差（2 个自由度）；
2. 报告方差分解：题间方差 vs 题内方差（用混合效应模型或 ANOVA），给出 ICC；
3. 若坚持 2 次，把 pass^2 标为"诊断指标，区间宽到不可用于比较"。

---

#### D23｜pass^2 在 n=2 时的不确定性（P1，❌ 未修复）

同 D22。补充：`formal_stats.py:162-168` 计算了 pass^2 的 Wilson 与 bootstrap，但 `v3` 与 `STATUS` 只引用了点估计。

**补救**：同 D21。

---

#### D24｜两份深挖文档对"翻转题"给出相反处方（P1，❌ 未修复）

**缺陷**：
- `DEEP-DIVE-20261102.md:23`：「重复 2 次不足以消除系统性方差；报告 pass@2 / pass^2」→ 隐含处方是**增加重复**；
- `LARGE-EVAL-SET.md:17`：「统计不显著的根因是题量，不是重复次数」→ 处方是**减到 1 重复、加到 100 题**。

**证据**：`DEEP-DIVE:23`、`DEEP-ANALYSIS:51-52`（"继续在 40 题上加重复也救不回来"）、`LARGE-EVAL-SET:11-17`。

**后果**：两份文档都没给出**方差分解**的证据来支持自己的处方。DEEP-ANALYSIS 的论据是"26/40 饱和题，加重复只是给饱和题加重复"——这个论据成立，但它证明的是"加重复在饱和题上无信息"，不等于"题内方差可忽略"。LARGE-EVAL-SET 的论据是"题级 n 从 40 到 100，CI 收窄一半"——但**降到 1 重复后，题内方差完全无法估计**，且 pass@2/pass^2 不可计算。

**状态**：❌ 未修复（两个设计都已写出，未合并）。

**补救**：
1. 先做**方差分解**（用现有 5 组 × 2 重复的数据估 ICC），再决定资源分配：若 ICC 高（题内方差小），加题；若 ICC 低（题内方差大），加重复；
2. 100 题的设计建议改为 **100 题 × 2 重复**（200 trial/组），或 **60 题 × 3 重复**（180 trial/组）——后者能估计题内方差且保留 pass^2；
3. 不要在同一份设计里既降重复又声称"配 McNemar 仍成立"——配对 McNemar 在 1 重复时退化为普通二项检验，失去配对优势。

---

### 3.6 开发集、制品身份与模型身份（D25–D28）

#### D25｜开发集当正式成绩（P0，❌ 未修复）

**缺陷**：40 题是开发迭代集（`README.md:41`、`AGENTS.md:20`），且 SAYACODE 的提示词规则 R1–R5 是从这套题的失败个案调出来的（`C:\develop\sayacode\docs\PROMPT-OVERFIT-RISK.md §1`）。`protocol.md:157` 明确禁止把开发期数字当正式成绩。但 `v3:136` 的"可写进简历的口径"、`STATUS §1`、`RETROSPECTIVE §2.1` 都直接使用这些数字。

**证据**：`RETROSPECTIVE:159-164` 自认；`STATUS:109`（局限 3）；`v3:117`（"未做的对照：同题集上的 holdout 提示词检验"）。

**后果**：
1. 数字对 SAYACODE **有偏**（方向有利）；
2. 偏置量未知——没有 holdout，无法估计；
3. "结论仍不显著"不能作为"偏置无害"的证据：如果偏置是 +5pp 而不显著是因为样本小，那么真实差距可能更大；
4. 对外使用时，"78.8%"会被读成"能力"，而不是"在有偏开发集上的表现"。

**状态**：❌ 未修复（承认但未停止使用）。

**补救**：
1. **对外表述必须附一句**："该数字来自开发迭代集，SAYACODE 的提示词规则由该题集的失败个案调出，存在对 SAYACODE 有利的偏置；独立 holdout 未执行。"
2. 若要报"能力"，必须做 holdout：从 519 题里排除 40 题及同 fix 组，抽 ≥40 题，不对 SAYACODE 做任何基于结果的调参；
3. 在此之前，所有数字降级为"开发期诊断"（`PROTOCOL-V2 §1` 本来就这么规定，只是执行层没遵守）。

---

#### D26｜制品身份断链（P1，✅ 已修复）

**缺陷**：v2/v3 的 SAYACODE 数字对应本地构建的 3.2.5 wheel，而 PyPI 上没有 3.2.5/3.2.6（只有 3.2.3/3.2.4/3.2.7），第三方无法复现；且阶段 3 的产品修复（`summary.py` +116 等）没有进入被测制品。

**证据**：`RETROSPECTIVE:137-147`；`STATUS:70-73`；`v4-327` 已用 PyPI 3.2.7 重跑（76.2%）。

**后果**：78.8% 一度不可复现；"修复有效性"没有评测证据。

**状态**：✅ 已修复（3.2.7 重跑，`FORMAL-RESULTS-20261106-327.md`）。但注意：3.2.7 的 76.2% 与 3.2.5 的 78.8% 是**跨批次**比较（见 D29）。

---

#### D27｜两套 `CANONICAL_MODEL` 常量不一致（P2，❌ 未修复）

**缺陷**：`src/sayacode_bench/{connections,execution}.py` 的 `CANONICAL_MODEL = "DeepSeek-V4.1-Flash"`（v1 SiliconFlow 时代），`scripts/locked_agents.py` 用 `auto-hy3`。两条路径不通用。

**证据**：`STATUS:97`、`RETROSPECTIVE:190`。

**后果**：若将来走 `study.py` 的 freeze 路径，会因 model_id 校验直接失败；或更糟——静默把 hy3 的结果标成 DeepSeek。

**状态**：❌ 未修复。

**补救**：统一为一个常量源（从 profile 读），加单测断言两处一致。

---

#### D28｜模型身份误标（P0，✅ 已修复）

**缺陷**：v3 初版、Codex/Claude Code 基线文档把 `auto-hy3` 写成 `DeepSeek-V4.1-Flash`。实测网关是两条独立记录（`auto/hy3` owned_by workbuddy 192k/64k；`auto/deepseek-v4.1-flash` owned_by opencode-zen 1M/200k），且评测窗口 42681 条 usage 里四组基线 served 全是 `hy3`/`hy3-x`。

**证据**：`v3:8`（更正声明）、`STATUS:93-96`、`RETROSPECTIVE:182-190`。

**后果**：曾存在"用 deepseek 名头报 hy3 成绩"的风险。已更正。

**状态**：✅ 已修复。

**补救**：无。但需注意：`canonical_model` 字段本身写的是 `auto-hy3`（正确），所以**记录级数据没被污染**——这是值得肯定的一点。

---

### 3.7 跨批次与混杂（D29–D32）

#### D29｜四组正式表混用两个批次（P0，❌ 未修复）

**缺陷**：`STATUS §2` 的"四组终版数字"里，SAYACODE 行来自 `v4-327`（2026-11-05 22:55 → 11-06 06:35，PyPI 3.2.7，served 零 `hy3-x`，并发 4/1），三个基线来自 `v2-325`（11-02~11-04，served 约 14.3% `hy3-x`，并发 2–4，部分网络修复前）。

**证据**：
- `STATUS.md:24`（自认"不是同批次同跑，只可做描述性对照"）；
- `FORMAL-RESULTS-20261106-327.md:64-71`（跨批次差异表）；
- `STATUS.md:46-48`（跨批次 McNemar：SAYACODE 3.2.7 vs mini-swe p=0.227 等）。

**后果**：
1. 表格视觉上是"四组对照"，但**组间差异与批次差异完全混淆**；
2. 跨批次配对 McNemar 把"时间/网络/并发/served 分布"的差异算成了"组间差异"；
3. `STATUS:7` 的"两种口径名次不同"（planned 下 Claude 反超 SAYACODE）可能是批次效应，不是口径效应。

**状态**：❌ 未修复。

**补救**：
1. **重新跑四组同批**（同一时间窗、同一 served 策略、同一并发），这是唯一干净的解法；
2. 若成本不允许，把表拆成"v2-325 批次（3 基线 + 3.2.5）"与"v4-327 批次（SAYACODE 3.2.7）"两张表，**不做跨批次 McNemar**；
3. 跨批次比较只能作为"同一题集上的历史观测并列"，不能作为配对检验。

---

#### D30｜`hy3-x` 额度池占比差 6 倍，被断言"不构成混杂"（P1，❌ 未修复）

**缺陷**：`v3:122-131` 给出 served 分布：`hy3-x` 占比 mini-swe 35.2% / SAYACODE 14.3% / Claude Code 9.6% / OpenCode 5.3%。报告断言"只是额度池分摊，不影响四组统一模型这个前提"。

**证据**：`v3:120-131`、`RETROSPECTIVE:189`、`STATUS:95`。

**反驳证据（同批数据）**：`FORMAL-RESULTS-20261106-327.md:77-79` 记录：为"固定 provider"把请求全 pin 到 `workbuddy/hy3` 单池，触发该池频率限制（`WorkBuddy: 使用量已超出频率限制`），**4 个 trial 挂起 15 分钟**。

**后果**：即使 `hy3` 与 `hy3-x` 是同一模型权重，**不同池的限流行为不同**。`hy3-x` 占比高的组（mini-swe 35.2%）会经历不同的限流暴露 → 不同的超时/重试/失败率。这不是"模型能力混杂"，而是"**服务可用性混杂**"，同样影响通过率。

**状态**：❌ 未修复（断言未被检验）。

**补救**：
1. 做一次**池内敏感性分析**：分别统计 `hy3` 与 `hy3-x` 请求的失败率、平均延迟、平均 token；
2. 在 v4 已有"零 `hy3-x`"的批次上，与 v2 的"14.3% `hy3-x`"批次对比，看通过率差异是否与池相关；
3. 若无法排除，结论必须写"组间 served 分布不同，服务可用性差异未控制"。

---

#### D31｜跨批次配对把批次效应算进组间差异（P1，❌ 未修复）

**缺陷**：`STATUS:46-48` 的三行跨批次 McNemar（共同题 40）把 11-06 的 SAYACODE 3.2.7 与 11-02 的基线配对。配对 McNemar 的前提是"同一条件、同一时间、只有处理不同"；跨批次时前提不成立。

**证据**：`STATUS:46-48`；`FORMAL-RESULTS-20261106-327.md:64-71`（差异表）。

**后果**：p 值不可解释——它混合了"产品版本差异"、"批次时间差异"、"served 池差异"、"并发差异"。

**状态**：❌ 未修复。

**补救**：删除这三行，或改名为"描述性并列（非配对检验）"，不给 p 值。

---

#### D32｜并发数跨批次不同（P2，❌ 未修复）

**缺陷**：v2-325 用并发 2–4（`STATUS:99`），v4-327 用 4（轻题）/1（vuls）（`FORMAL-RESULTS-20261106-327.md:68`）。并发影响容器资源竞争、网络池压力、超时概率。

**证据**：`STATUS:99`、`FORMAL-327:68`。

**后果**：同上，属批次效应的一部分。

**状态**：❌ 未修复。

**补救**：同 D29（同批重跑）；若要保留跨批次比较，至少记录并报告"并发 × 通过率"的相关性。

---

### 3.8 指标采集与题库判别力（D33–D36）

#### D33｜partial credit 未进采集管线（P1，⚠️ 部分）

**缺陷**：partial credit 是协议规定的指标（`PROTOCOL-V2` 要求三口径，`ITERATION-WORKFLOW` 早期就列了 partial），但主报告从未采集；只在 `DEEP-ANALYSIS` 里用事后脚本从 `verifier/output.json` 补算。

**证据**：`RETROSPECTIVE:131`（"partial credit 采集：⚠️ 仅 DEEP-DIVE 里手工分析过"）；`DEEP-ANALYSIS:9-15`（事后补算表）；`scripts/analyze_partial_scores.py`（独立脚本，不在主汇总链路）。

**后果**：
1. 主表丢失了"差一个测试"的信息（`DEEP-ANALYSIS:17-27`）；
2. 事后补算的 partial 与 reward 口径不一致（见 D14：claude 65 vs 62）；
3. partial 不能作为预注册指标使用——它是事后指标，存在"看到数据后再选指标"的风险。

**状态**：⚠️ 部分（有分析无管线）。

**补救**：把 `required/passed/partial` 写入 `formal.py` 的 Trial 与 `FINAL-SUMMARY`，作为与 reward 并列的一等字段；在协议里预注册 partial 的分析方式。

---

#### D34｜"部分得分 94–99% 说明基本做对了"是推理冒充证据（P1，❌ 未修复）

**缺陷**：`DEEP-ANALYSIS:26`：「这些题 agent 其实基本都做对了，只是卡在最后一个断言的边角上」；`:27`：「0/1 通过率把这个『99% 对』压缩成 0」。

**问题**：这是从"部分得分高"推出"做对了"的**语义跳跃**。部分得分高只说明"required tests 的通过比例高"，不说明：
- 修改的语义是否正确（测试可能弱、可能只覆盖表面行为）；
- 是否通过改测试/快照获得（虽然被重置，但可能改了 untracked 文件）；
- p2p 是否回归（如果 p2p 失败，partial 仍可能高）。

**证据**：`DEEP-ANALYSIS:17-27`；`health.md` 的 `broken` 判定（`element-web-772df30212` 部分得分 97.4% 但 0/1 通过 0%）——**部分得分高但完全不可过**，正是"高 partial ≠ 做对了"的反例。

**后果**："部分得分 94–99%"被用来论证"题太浅、agent 都差不多"，但这个论证需要的是"能力分布"，而不是"测试通过比例"。

**状态**：❌ 未修复。

**补救**：把部分得分定位为"测试覆盖度的度量"，不要用它推断"能力"；若要推断能力，需要人工审阅 patch 或引入更强的测试。

---

#### D35｜题库体检两套结论（P1，❌ 未修复）

**缺陷**：同一天（2026-11-06）产出的两份分析给出不同的题库健康结论：

| 指标 | `DEEP-ANALYSIS-20261106.md`（15:29） | `C:\sb\analysis\health.md`（15:46） |
|---|---|---|
| 饱和题 | **26/40 = 65%** | **28** |
| 有区分度 | **8/40** | **4 healthy** |
| 环境性不可过 | **2 题**（qutebrowser-fec1、tutanota-518） | **3 题**（+ element-web-772d） |
| 建议 | 换题库 | 保留 4、排除 3、**替换 33** |

**证据**：`DEEP-ANALYSIS:35-39`、`:56-61`；`C:\sb\analysis\health.md`（benchmark_health.py 产出）。

**后果**：
- "饱和 26 还是 28"、"8 题还是 4 题有区分度"直接决定"是否需要换题库"的紧迫性；
- `element-web-772df30212` 在 health.md 里是 `broken`（0% 通过、部分得分 97.4%），但在 `DEEP-ANALYSIS` 里没有被列为环境性不可过——而它恰恰是 snap pass 最集中的题（mini-swe/Claude/OpenCode 都有）；
- 两套阈值不同（`benchmark_health.py` 用 `SATURATED = 0.995`、`healthy: sd≥0.03`；`analyze_partial_scores.py` 用 `partial==1.0`、`sd>0.02`），但报告没有说明阈值差异。

**状态**：❌ 未修复。

**补救**：统一为一个体检器，把阈值写入报告；两套结论合并前必须解释差异。

---

#### D36｜PILOT 的"静态预测 60% ≈ 随机"在 n=10 下未给区间（P2，⚠️ 部分）

**缺陷**：`PILOT-SWE-EVO-20261106.md:28-41` 用混淆矩阵 TP=4 TN=2 FP=3 FN=1 得出"准确率 6/10 = 60%（≈随机）"。

**问题**：n=10 时 60% 的 95% CI 约 [26%, 88%]，与 50% 大幅重叠，"≈随机"是正确的**保守**表述；但报告也没有说明"若真实准确率是 80%，n=10 只有 ~38% 概率观测到 ≥8/10"——即**功效不足**。

**证据**：`PILOT:33-35`。

**后果**：结论方向正确（不能靠静态预测），但"60%"这个数字容易被误读为"接近随机但略好"。

**状态**：⚠️ 部分（结论保守，但缺区间）。

**补救**：加 Wilson 区间；明确写"n=10 不足以区分 60% 与 50%"。

---

## 4. 三分法：站得住 / 描述性 / 推理冒充证据

> 这是本审计最重要的分类。**只有第一类可以写进对外材料。**

### 4.1 统计上站得住（A 类）

| # | 结论 | 为什么站得住 | 边界 |
|---|---|---|---|
| A1 | 四组之间**未检出**统计显著差异（p ≥ 0.070，Bonferroni α/3、α/6 下均不显著） | 精确 McNemar，题级配对，代码实现正确（`formal_stats.py:172-208`），且 6 对/9 对比较全部不显著 | 这是"未检出"，**不是"无差异"**；功效不足，不能反推等价 |
| A2 | SAYACODE 3.2.7 与 3.2.5 的差异不显著（Δ −2.6pp，McNemar p=0.8145，bootstrap CI [−12.5, +6.2] 跨 0） | 同制品族、同题集、78 个配对 trial，区间跨零（`FORMAL-327:31-45`） | 只能证"没有可测差异"，不能证"修复无效"——报告自己也这么说（`:59`），这点是对的 |
| A3 | 题内翻转普遍存在（每组 2–7 题在 r1/r2 间翻转） | 直接计数（`DEEP-ANALYSIS:69-77`），不依赖推断 | 翻转率本身是观测；"翻转导致不显著"是解释 |
| A4 | 补跑显著抬高了通过率（SAYACODE +11.3pp、mini-swe +15.0pp） | 补跑前后同表（`v3:33-42`），且补跑条目的根因有 `exception.txt` 证据 | "环境失败系统性惩罚某些 agent"是合理推断，但具体偏置量未知 |
| A5 | verifier 会重置测试代码（`tests/`、`*_test.py`、`*_test.go` 等） | 642/642 个 `test.sh` 的 `CODE_DIRS` 分支 + `git checkout HEAD`（`test.sh:71`） | ✅ 已验证；这是 D07 的另一半，正确的一半 |
| A6 | 测试面**同时**会重置 `__snapshots__` 等数据目录 | 642/642 个 `test.sh` 的 v6 段（`:97-105`）；`__NONE__` 哨兵使跳过分支不可达 | ✅ 已验证；**这是对 D06/D07 的证伪** |
| A7 | 40 题样本的题级 CI 宽约 ±12–15pp | 二项区间可直接计算；三份文档数值接近（`MULTI-MODEL-PLAN:100`、`STATUS:114`、`LARGE-EVAL-SET:13`） | 具体宽度取决于 p 与 n；"±12"与"±15"的差异来自 p 的取值 |
| A8 | 四组基线 served 全是 `hy3`/`hy3-x`，零 `deepseek-v4.1-flash` | 42681 条 usage 逐条统计（`v3:120-128`） | ✅ 已验证；模型身份混淆已排除 |
| A9 | Codex 组整组适配失效（373 次 unsupported call、960 次 405） | 轨迹级审计（`v3:57-67`、`CODEX-BASELINE-INVALID.md`） | ✅ 已验证；这是本项目最扎实的单项工作之一 |
| A10 | 这批题从未触发上下文摘要（峰值 input 102–127k < 153.6k 触发线） | 逐 trial 峰值统计（`DEEP-ANALYSIS:179-202`） | ✅ 已验证；推论"3.2.6/3.2.7 的摘要修复不可能在这批题上生效"是**演绎**，成立 |

### 4.2 只是描述性观察（B 类，不可用于排名或因果）

| # | 观察 | 为什么只能描述 |
|---|---|---|
| B1 | planned 通过率 85.0 / 77.5 / 76.2 / 75.0 | 分母统一但混批次（D29）、补跑差异（D13）、开发集偏置（D25） |
| B2 | strict 通过率 80.0 / 73.8 / 67.5 / 76.2 | **前提已证伪**（D06），数字无效 |
| B3 | observed 通过率 86.1 / 78.5 / 77.2 / 75.0 | 幸存者偏差（D02），只作辅助 |
| B4 | task_macro 87.2 / 78.2 / 76.9 / 75.0 | 与 planned 差异来自缺失处理，不能替代 |
| B5 | 题级全通过 76.9 / 64.1 / 61.5 / 57.5 | n=39–40，无区间（D21）；且受题集饱和影响 |
| B6 | 补跑前后增量 +11.3pp / +15.0pp | 观测本身可报，但不能归因为"修复有效" |
| B7 | 每组翻转 2–7 题 | 计数可报，但不能据此说"噪声大于效应"（需要方差分解） |
| B8 | 部分得分 94–99% | 是测试覆盖度，不是能力（D34） |
| B9 | 26 或 28 题饱和、4 或 8 题有区分度 | 两套阈值、两套结论（D35） |
| B10 | 成本 1.43M tokens/任务 | 依赖协议的 usage 统计，未与现金对齐 |
| B11 | 探索:编辑比 2.9 vs 1.1 | 行为描述，无因果 |
| B12 | 工具失败 `error_type` 全 null | **观测缺失**（`DEEP-ANALYSIS:167-172`），不是"没有失败" |
| B13 | SWE-EVO 试点 50%（5/10） | 样本太小，作者自己也说只作链路证据 |
| B14 | 静态预测准确率 60%（6/10） | n=10，CI [26%, 88%] |

### 4.3 推理冒充证据（C 类，必须降级为"假设"或删除）

| # | 被当作证据的推理 | 缺什么 | 处置建议 |
|---|---|---|---|
| C1 | "strict 扣除后差距缩窄 → SAYACODE 更干净" | strict 前提被证伪（D06/D07）；且 snap=0 是产品侧清理的结果，不是能力 | **删除**该结论 |
| C2 | "OpenCode 低分来自脚手架重量 + 6 个 snap pass 的行为倾向" | 无脚手架复杂度对照；snap pass 前提错误 | **降级为假设**，去掉 snap 部分 |
| C3 | "题集太浅（2 文件/64 行）导致无判别力" | "浅"与"饱和"是两个变量；没有对难度的操纵检验（`EXPERIMENT-CONTEXT-AB` 未执行） | 拆成两个假设，分别检验 |
| C4 | "SAYACODE 越失败越不编辑 → 卡在理解" | `error_type` 全 null，无法区分"探索多"是原因还是结果 | **降级为观察**，不做因果 |
| C5 | "3.2.6/3.2.7 修复无效" | 接受零假设需要功效分析；报告自己也说"证不了有效也证不了无效" | 改为"未检出效果"，不给"无效" |
| C6 | "mini-swe 85.0% 是能力" | 含补跑 +15pp；补跑条目与未补跑条目的分布未比较（D13） | 必须并列 70.0% |
| C7 | "hy3-x 占比不构成混杂" | 未检验池间限流差异（D30），且有单池 429 的直接证据 | 改为"未控制的服务可用性差异" |
| C8 | "检测 10pp 需 330 题" | 无推导（D18） | 改为"未量化" |
| C9 | "坏题率 2.5%，远低于 Epoch AI 的 30%"（v1） | 单次 oracle、非随机子集、非同口径 | 已作废，不应再出现 |
| C10 | "部分得分 99% 说明基本做对了" | 高 partial 但 0/1 为 0 的反例存在（health.md 的 broken 题） | 改为"测试覆盖比例高" |
| C11 | "四组压缩在窄带 → 模型能力趋同" | 窄带可由题集饱和 + 天花板效应解释，不必是能力趋同 | 改为"题集在该批次上无区分度" |
| C12 | "跨批次 McNemar p=0.227 说明 SAYACODE 3.2.7 与 mini-swe 无差异" | 批次效应混入（D29/D31） | 删除该 p 值 |

---

## 5. 三状态总表

### 5.1 已验证（有 E1/E2 证据，可复算）

| 编号 | 事实 | 证据等级 |
|---|---|---|
| V1 | verifier 重置测试代码（`tests/`、`*_test.py`、`*_test.go` 等） | E1（642/642 `test.sh:37,45,71`） |
| V2 | verifier **同样重置** `__snapshots__`、`fixtures`、`mocks`、`testdata` 等数据目录 | E1（642/642 `test.sh:38,100-102`） |
| V3 | 因此"patch 含 `.snap` → 靠改快照通过"不成立；strict 口径无效 | E1 + E2（逐 trial 核对 test_patch 路径） |
| V4 | `timeout` 分类在 `classify_missing` 中不可达 | E1（`formal.py:464-476`） |
| V5 | 缺失分类三处集合不一致（6/7/6） | E1（`PROTOCOL-V2:40-47`、`formal.py:35`、`reconcile_results.ALLOWED_MISSING`） |
| V6 | 同一批数据多工具通过数/缺失数/snap 判定不一致 | E2（三份产物逐字段对比） |
| V7 | v1 三套分母导致虚假 17.4pp；统一后 Codex = 56/80 = 70.0% | E2（`FINAL-SUMMARY.json` 重算） |
| V8 | 补跑显著抬高通过率（SAYACODE +11.3pp、mini-swe +15.0pp） | E2（补跑前后产物 + `exception.txt`） |
| V9 | 四组两两 McNemar 不显著（p ≥ 0.070） | E2（`formal_stats.py` 实现正确，可复算） |
| V10 | 四组基线 served 全是 hy3/hy3-x，零 deepseek | E2（42681 条 usage 统计） |
| V11 | Codex 组整组适配失效（373/960 次协议错误） | E2（轨迹审计） |
| V12 | 40 题从未触发上下文摘要（峰值 < 153.6k） | E2（逐 trial 峰值统计） |
| V13 | 每组 2–7 题在 r1/r2 间翻转 | E2（`DEEP-ANALYSIS:69-77`） |
| V14 | 3.2.7 vs 3.2.5 的 Δ −2.6pp 不显著（p=0.8145，CI 跨 0） | E2（配对 78 trial） |

### 5.2 未验证（只有 E3 或证据不足）

| 编号 | 断言 | 缺什么 |
|---|---|---|
| U1 | "检测 10pp 需约 330 题" | 推导与参数；见 D18 |
| U2 | "hy3-x 占比差异不构成混杂" | 池间限流/失败率对比；见 D30 |
| U3 | "补跑 12/12 全过不影响结论" | 补跑条目与未补跑条目的分布比较；见 D13 |
| U4 | "题集太浅导致无判别力" | 难度操纵检验（`EXPERIMENT-CONTEXT-AB` 未跑） |
| U5 | "3.2.6/3.2.7 三项修复无效" | 功效分析；当前只能说"未检出" |
| U6 | "开发集偏置的方向与量级" | holdout 从未执行；只有方向性推断 |
| U7 | "OpenCode 低分来自脚手架重量" | 无复杂度对照 |
| U8 | "SAYACODE 探索多是因为卡在理解" | `error_type` 全 null；无过程级对照 |
| U9 | 100 题设计的功效（±9pp） | 计算依据未给；且 1 重复的方差结构未知 |
| U10 | 3.2.7 的 76.2% 与基线的可比性 | 跨批次（D29） |

### 5.3 已证伪（有 E1/E2 与命题矛盾）

| 编号 | 曾有过的结论 | 证伪证据 |
|---|---|---|
| F1 | "verifier 不重置 `__snapshots__`，改 snap 有效" | 642/642 `test.sh:97-105`；`__NONE__` 哨兵分析；test_patch 路径核对 |
| F2 | "strict 扣除的 4/3/6 个 pass 是靠改快照换来的" | 同上；且这些 `.snap` 正是官方 test_patch 要更新的文件 |
| F3 | "SAYACODE 改测试率 49% → 会尝试改测试作弊" | 官方 verifier 重置测试面；改测试对分数无效 |
| F4 | "SAYACODE 落后 17.4pp" | 三套分母；统一后 1.2pp |
| F5 | "3 条模型故障，剔除后 71.4%" | 只有 1 条真 API 故障（ECONNRESET）；另 2 条是空 patch |
| F6 | "40 题 gold patch 全绿" | 实为 36 good / 1 bad / 3 null |
| F7 | "auto-hy3 = DeepSeek-V4.1-Flash" | 网关两条独立记录；usage 零 deepseek |
| F8 | "OpenCode 有自家模型 / 模型错配" | 它是 provider-agnostic（`RETROSPECTIVE:112`） |
| F9 | "v2-tuned 调优有收益" | 基于误读证据；规则 1 无效、规则 5 有害 |
| F10 | "hy3-x 是降配变体" | 用户确认三成员同模型 |
| F11 | "PLAN/dispatch trigger 提示语带来收益"（R1） | `RETROSPECTIVE:173` 自认"没有任何有效证据" |

---

## 6. 如果重做一遍：实验设计

> 前提：目标是回答"SAYACODE 的脚手架设计相对标准 harness 的净收益"，且结论要能对外。以下数字按"能在 40–60 分钟内跑完一个 agent 的可行性"估算。

### 6.1 样本量与结构

| 项 | 现值 | 建议值 | 理由 |
|---|---|---|---|
| 题数 | 40 | **≥100**（从 519 题分层抽） | 题级 n 决定检验功效；40 题 CI ±14pp，100 题约 ±9pp |
| 重复 | 2 | **≥3**（若题数降到 60）或 **2**（若保持 100） | ≥3 才能估计题内方差；2 次只能观测不能估计 |
| trial 数/组 | 80 | **200**（100×2）或 **180**（60×3） | 4 组 × 200 = 800 trial，按本地 8–13 分钟/题、并发 2–4 估约 40–60 小时 |
| 题集来源 | sample-40（开发集） | **holdout**：排除 40 题及同 fix 组后抽取 | 关掉 D25 的偏置洞 |
| 分层 | 9 仓库 | 9 仓库 × 难度档（用 `health.md` 的 sd/饱和指标分层） | 避免 65% 饱和题浪费样本 |
| 排除 | gold 单次 | **三次 oracle + 一次 nop**（`fixture-gates` 标准） | 单次 oracle 不足以排除坏题 |

### 6.2 配对结构

- **配对块 = `task × repeat`**，同题同 repeat 的四个配置在同一时间窗内交错执行（`protocol.md:104` 已规定，但 v2/v3/v4 实际是"分 agent 串行"，违反交错原则）；
- **同批次**：四组在同一批次内完成，不跨天、不跨网络修复节点；
- **同 served 策略**：要么全部 pin 到同一池（接受 429 风险并重试），要么全部用 `auto-hy3` 并记录每 trial 的池分布；不允许组间分布差 6 倍；
- **同并发**：全组同一并发配置。

### 6.3 预注册指标（看数据前写死）

| 层 | 指标 | 定义 | 主/辅 |
|---|---|---|---|
| 结果主 | planned pass@1 | 成功 trial / planned trial（缺失按失败） | **主** |
| 结果辅 | observed、task_macro | 见 `PROTOCOL-V2 §2` | 辅 |
| 结果辅 | 题级全通过率 + Wilson | n = 题数 | 辅，带区间 |
| 稳定性 | pass@2、pass^2 | 见 `formal_stats.py:137-169`，**必须带区间** | 辅 |
| 连续 | partial（required 通过比例） | 从 `verifier/output.json` 采集，写入主汇总 | 辅（预注册） |
| 检验 | 配对 McNemar（题级，二值定义预注册） | 主假设 3 对：SAYACODE vs 每个基线 | **主** |
| 校正 | Bonferroni α/3 | 仅主假设族 | — |
| 区间 | 任务块 bootstrap（10k，seed 固定）+ 仓库簇 bootstrap | 题级单位；簇数 9 仅敏感性 | 辅 |
| 护栏 | 空 patch 率、适配健康（API error / unsupported call） | 一票否决：适配失效的组不参与排名 | **门禁** |
| 成本 | token/成功、现金/成功（若可计价） | 只描述资源 | 辅 |

### 6.4 缺失与补跑（预注册，不事后改）

1. **分类顺序固定**：`no_job → infra → timeout → model_fault → empty_patch → unverified`，每类有判定证据（`exception_type` / `terminal.json` / patch 字节数）；代码必须能返回全部类别（修 D12）。
2. **补跑规则固定**：只补 `infra` / `no_job` / `unverified`；`timeout` / `empty_patch` 不补；**补跑在冻结前一次性完成**，不边跑边看。
3. **补跑前后同表**：必报补跑条目的独立通过率与未补跑条目的通过率（D13）。
4. **对账门禁**：`reconcile_results` + `lint_metrics` + 多源交叉（D14）在出报告前必须全绿。

### 6.5 执行与文档

- 每次跑批前 `profile_summary.py` 输出上下文/输出预算并留档；
- 每 trial 记录 `served` / `provider` / 耗时 / token / `usage_complete`；
- 结果目录带 manifest（题集 SHA、脚本 commit、wheel SHA、并发、时间窗）；
- 报告模板固定：planned + observed + 缺失分类表 + worst/best + 题级 Wilson + McNemar（含二值定义）+ 补跑前后 + 适配健康 + 局限。

### 6.6 成本与取舍

若预算/时间只够做一件事，优先级是：

1. **修 strict 口径与文档更正**（0 成本，防止错误结论扩散）；
2. **同批重跑四组**（约 20–30 小时本地，解决 D29）；
3. **扩到 100 题 × 2 重复**（约 40–60 小时，解决功效）；
4. **holdout 提示词检验**（需新题，解决 D25）；
5. 多模型矩阵（需付费 API，可延后）。

---

## 7. 对现有对外表述的逐句修法

| 现表述 | 出处 | 问题 | 建议改法 |
|---|---|---|---|
| "四组压缩在 67.5%–80.0%（strict），两两 McNemar 全部不显著" | `RETROSPECTIVE:9` | strict 列无效（D06） | "四组 planned 76.2%–85.0%，题级 McNemar 全部不显著（p ≥ 0.070）；strict 口径因 verifier 快照重置行为被误判，数字已撤回" |
| "strict 下 SAYACODE 第 2，planned 下被 Claude Code 反超到第 3" | `STATUS:7` | strict 无效；且跨批次（D29） | 删除 strict 排名；四组分层为两个批次并列 |
| "SAYACODE 78.8%（strict 同为 78.8%，0 个改快照通过）" | `v3:136` | 78.8% 是 3.2.5 旧制品；strict 无效；开发集偏置 | "SAYACODE 3.2.5（本地 wheel，非 PyPI）在 40 题开发集上 pass@1 78.8%；3.2.7（PyPI）为 76.2%。两者差异不显著（p=0.8145）。该题集为开发迭代集，存在对 SAYACODE 有利的调优偏置" |
| "检测 10pp 差异需约 330 题" | `STATUS:114` | 无出处（D18） | "40 题 CI 约 ±14pp（题级）、±12pp（trial 级），不足以检出 10pp 差异；所需样本量未量化" |
| "mini-swe 85.0% planned / 80.0% strict" | `STATUS:14` | 含补跑 +15pp；strict 无效 | "mini-swe 85.0%（补跑 12 条后；补跑前 70.0%）" |
| "OpenCode 的 6 个 snap pass 最多，被 strict 拖累 7.5pp" | `v3:53` | 前提错误（D06） | 删除 |
| "改测试率 49%"（若仍在任何材料中） | v1 系列 | 已作废 | 不再使用；若需讨论测试面，用"verifier 重置测试面"这一事实 |
| "四组同量级、不能说谁更强" | `RETROSPECTIVE:89` | 方向正确，但支撑它的 strict 与跨批次不可靠 | 保留结论，换支撑：planned 下 McNemar 不显著 + 适配健康审计 |

---

## 8. 证据索引

### 8.1 仓库内文档

| 文件 | 关键行 | 用途 |
|---|---|---|
| `docs/PROTOCOL-V2.md` | 22, 26-34, 36-47, 62-68, 72-77, 79-93, 95-105, 107-135 | 协议本体（D03/D06/D07/D10/D12/D16/D17） |
| `docs/RETROSPECTIVE-20261105.md` | 9, 17-22, 28, 80-82, 88-113, 159-164, 178-180, 192-213, 214-217, 219-234 | 自认缺陷的来源（D11/D13/D15/D25） |
| `docs/STATUS.md` | 7, 13-24, 26-34, 36-52, 70-73, 93-99, 107-115 | 当前权威状态（D03/D15/D29/D30） |
| `docs/FORMAL-RESULTS-20261105-v3.md` | 6, 12-18, 20-31, 33-42, 44-55, 57-67, 105-117, 136 | 四组结果（D06/D16/D21/D29） |
| `docs/FORMAL-RESULTS-20261106-327.md` | 19-27, 29-45, 47-60, 62-71, 73-81 | 3.2.7 结果（D26/D29） |
| `docs/TEST-EDIT-ANALYSIS-20261102.md` | 8-13, 15-25, 27-36, 38-41, 43-50 | 错误前提的源头（D06/D07） |
| `docs/DEEP-ANALYSIS-20261106.md` | 9-27, 29-52, 54-65, 67-83, 85-104, 106-172, 174-202 | 部分得分与题库（D33/D34/D35） |
| `docs/DEEP-DIVE-20261102.md` | 11-23, 45-54, 56-73, 89-94 | 翻转题与成本（D22/D24） |
| `docs/FORMAL-RESULTS-20261102-v2.md` | 9-15, 17-23, 25-31, 33-39, 41-48 | v2 历史（D05/D11） |
| `docs/LESSONS-20261102-v2.md` | 7-9, 79-113, 144-150, 166-175 | 基建坑（D11/D14） |
| `docs/TASKCOUNT-ATTRIBUTION.md` | 10-21, 125-144 | 协作归因（方法论正例） |
| `docs/LARGE-EVAL-SET.md` | 7-17, 19-32, 57-68 | 100 题设计（D18/D24） |
| `docs/MULTI-MODEL-PLAN.md` | 18-26, 39-53, 98-106 | 多模型与功效（D18） |
| `docs/EXPERIMENT-CONTEXT-AB.md` | 25-52, 74-94, 96-119 | 上下文 A/B 设计（U4） |
| `docs/PILOT-SWE-EVO-20261106.md` | 7-27, 28-41, 60-72, 77-84 | 新题库试点（D36） |
| `docs/CODEX-BASELINE-INVALID.md` | 全文 | 整组作废证据（A9） |

### 8.2 代码

| 位置 | 用途 |
|---|---|
| `src/sayacode_bench/formal.py:35,42-50,464-476` | 缺失分类（D10/D12） |
| `src/sayacode_bench/formal_stats.py:39-49,52-70,82-127,137-169,172-208` | 统计实现（A1/A2/D16/D20/D21） |
| `src/sayacode_bench/analysis.py:48-71` | 题级 bootstrap（D20） |
| `scripts/strict_compare.py:3-5,23,33-39,108,132-141,143-153` | strict 口径（D06/D08/D09/D04） |
| `scripts/reconcile_results.py`（`ALLOWED_MISSING`） | 对账（D10） |
| `scripts/lint_metrics.py` | 口径 lint（D01 的防线） |
| `scripts/benchmark_health.py:22-33` | 题库体检阈值（D35） |
| `scripts/analyze_partial_scores.py` | 事后 partial（D33/D34） |

### 8.3 产物

| 路径 | 用途 |
|---|---|
| `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json` | 四组 planned/observed/passes/missing |
| `C:\sb\hard\v2-325\STRICT-COMPARE.json` | strict/snap 明细（陈旧） |
| `C:\sb\hard\v4-327\FINAL-SUMMARY-327.json`、`STRICT-COMPARE-327.json` | 3.2.7 |
| `C:\sb\analysis\dataset.json` | 391 trial 的部分得分/行为（D14/D35） |
| `C:\sb\analysis\health.md` | 题库体检（D35） |
| `C:\sb\newset\runs\pilot1\*` | SWE-EVO 试点（D36） |
| `C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766.../v2/tasks/*/tests/test.sh` | verifier 重置逻辑（A5/A6/F1/F2） |

### 8.4 关键实测命令（可复现本审计的核心判定）

```powershell
# 1) 642/642 test.sh 都含快照重置段
$tasks = "C:\sb\tmp\hard\cache\swe-bench-pro-v2-66f92766bba642462d4bbe5479e83f91f9211862\v2\tasks"
(Get-ChildItem $tasks -Recurse -Filter test.sh).Count                    # 642
(Get-ChildItem $tasks -Recurse -Filter test.sh |
  Where-Object { (Get-Content $_.FullName -Raw) -match "v6_modified" }).Count  # 642

# 2) 一个 snap pass 的 patch 里，.snap 正是官方 test_patch 的路径
Select-String -Path "...\instance_element-hq__element-web-9bf77963ee...\tests\test_patch.patch" -Pattern "^\+\+\+ b/.*snap"
Select-String -Path "C:\sb\hard\v2-325\mini-swe\jobs\mini-swe-...-9bf77963ee-r1\...\agent\model.patch" -Pattern "^\+\+\+ b/"

# 3) 三工具通过数不一致
#    FINAL-SUMMARY-V4: claude-code passes=62；dataset.json: partial==1.0 计 65
```

---

## 附：本审计未覆盖的部分（诚实边界）

1. **未重跑任何 trial**，因此"补跑条目与未补跑条目同分布"（D13）只能指出缺口，不能给出结论；
2. **未审产品仓代码**（`C:\develop\sayacode`），因此 SAYACODE 侧的 `restore_existing_test_files` / `strip_new_test_files` 只按文档描述对待；
3. **未核对每个 trial 的 `exception.txt`**（数量大），因此 `timeout` 不可达（D12）的实际影响面只是推断；
4. **未验证 `330` 的替代值**，只指出无出处（D18）；
5. **未审计费用/预算链路**（`billing.md` 等），本审计聚焦设计与统计。
