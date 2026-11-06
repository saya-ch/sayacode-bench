# RESULTS LEDGER：全部对外数字的唯一真相源

| 项 | 值 |
|---|---|
| 版本 | **v1.0（2026-11-07）**，建立于 2026-11-07 全面复盘之后 |
| 地位 | **本文件是全部评测数字的唯一权威来源**。其他任何文档（STATUS / README / HANDOFF / 复盘 / 结果报告）**只允许引用，不得复制数字** |
| 依据 | [review/2026-11-07/RETROSPECTIVE-20261107.md](review/2026-11-07/RETROSPECTIVE-20261107.md) |
| 更新规则 | 只有**新的正式批次跑完并复算通过**才能改本文件；改任何一格都必须同时更新 §6 的生成命令与 §7 的变更记录 |

> ⚠️ **本文件不包含 `strict` 口径。** 该口径的前提（"verifier 不重置 `__snapshots__`"）已被证伪：642/642 个 `tests/test.sh:97-105` 在判分前对 `*__snapshots__/*` 执行 `git checkout HEAD`，`:101` 的 `__NONE__` 哨兵使跳过分支永不触发。agent 对快照的修改在判分时已被还原。**任何再次出现的 `strict` 数字一律视为错误。**

---

## 1. 口径定义

| 口径 | 定义 | 用途 | 约束 |
|---|---|---|---|
| **`planned`** | 分母 = 题数 × 重复数（40×2 = 80）；任何缺失按失败计 | **主报**，对外唯一可用 | 必须同时给缺失数与分类 |
| **`observed`** | 只含有 reward 或显式终态的子集 | **辅助** | **每次出现必须标注「幸存者偏差，会高估」** |
| **`partial`** | `verifier/output.json` 中 required 测试的通过比例（0–1 连续量） | **辅助**，对小样本对比比 0/1 敏感得多 | 必须写明是 trial 级均值还是题级均值 |
| `touches_snap_pass` | patch 触碰 `.snap` 且 `reward=1` 的 trial 数 | **仅行为描述** | **不参与任何排名**；必须注明"这些快照在判分前已被还原，不影响结果" |

**`task_macro`**：先按题归约重复、再对题取平均。只算 `complete_tasks`（有全部重复的题），因此分母常小于 40 —— **引用时必须标明分母**。

---

## 2. 主表：四组（`planned` 主报 + `partial` 辅助）

### 2.1 v2-325 批次（结果根 `C:\sb\hard\v2-325`；SAYACODE 制品 3.2.5 本地 wheel；2026-11-02 ~ 11-05）

| agent | **planned** | 缺失 | `observed`（辅助） | **`partial` trial 级** | **`partial` 题级** | `partial` n | `task_macro` | 题级全通过 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SAYACODE 3.2.5 | **78.8%** (63/80) | 1 | 79.7% (63/79) | **99.2%** | **98.9%** | 73 | 80.8% | 29/39 = 74.4% |
| mini-swe-agent | **85.0%** (68/80) | 1 | 86.1% (68/79) | **98.5%** | **98.6%** | 77 | 87.2% | 30/39 = 76.9% |
| Claude Code | **77.5%** (62/80) | 1 | 78.5% (62/79) | **97.8%** | **98.0%** | 76 | 78.2% | 25/39 = 64.1% |
| OpenCode | **75.0%** (60/80) | 0 | 75.0% (60/80) | **94.4%** | **94.6%** | 77 | 75.0% | 23/40 = 57.5% |
| ~~Codex CLI~~ | ~~68.8%~~ | — | — | — | — | — | **整组作废，不参与任何排名** |

- `touches_snap_pass`（描述性）：SAYACODE **0** / mini-swe 4 / Claude Code 3 / OpenCode 6 / ~~Codex 3~~。**不影响上述任何数字。**
- Codex 作废理由：`unsupported call: apply_patch` 373 次（78/80 trial）+ `/v1/responses` websocket 405 960 次（80/80 trial）。见 `docs/CODEX-BASELINE-INVALID.md`。

### 2.2 v4-327 批次（结果根 `C:\sb\hard\v4-327`；制品 PyPI `sayacode-3.2.7`；2026-11-05 22:55 → 11-06 06:35）

| agent | **planned** | 缺失 | `observed`（辅助） | **`partial`（题级均值）** | `worst` 界 | `best` 界 |
|---|---:|---:|---:|---:|---:|---:|
| SAYACODE 3.2.7 | **76.2%** (61/80) | 1 | 77.2% (61/79) | **97.8%** | 76.25% | 77.5% |

- 缺失 1：`vuls-4b680b99606 r1`，类别 `empty_patch`。
- `task_macro` 76.9%（39 题）、题级全通过 24/39 = 61.5%、`pass@2` 36/39 = 92.3%。
  **分母说明**：`task_macro` / `pass@2` / 题级全通过的分母是 `complete_tasks = 39`；若按全部 40 题算，`pass@2` 是 **37/40**（vuls 的 r2 通过、r1 空 patch）。**引用时必须说明用的是哪个分母。**
- `partial` 从 `C:\sb\analysis\dataset.json` 的 `sayacode/3.2.7` 子集算（**不能**从 `FINAL-SUMMARY-327.json` 直接取，见 §5.1）。
- served：`hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572；零 `hy3-x`、零 deepseek。

### 2.3 ⚠️ 两个批次不可合并排名

- 制品不同（3.2.5 本地 wheel vs PyPI 3.2.7）、时间不同（11-02~05 vs 11-06）、served 分布不同（约 14.3% `hy3-x` vs 零）、并发不同（2–4 vs 4/1）、网络修复状态不同。
- **任何跨这两张表的排名、差值、p 值都是批次效应与处理效应的混合物，不得使用。**
- `STATUS.md` 历史上出现过三行跨批次 McNemar（`327 vs mini` / `vs Claude` / `vs OpenCode`），经复算**无法重现**（common 写 40 而实测 38/39；OpenCode 行 p=0.791 实测 1.0），已从本 ledger 移除。

---

## 3. 配对比较（只在同一批次内）

### 3.1 v2-325 批次内六对（题级全通过，`complete` 题交集，McNemar exact）

| 对比 | 共同题 | a 独过 / b 独过 | p |
|---|---:|---:|---:|
| Claude Code vs mini-swe | 38 | 3 / 7 | 0.344 |
| Claude Code vs SAYACODE 3.2.5 | 38 | 4 / 7 | 0.549 |
| Claude Code vs OpenCode | 39 | 9 / 6 | 0.607 |
| mini-swe vs SAYACODE 3.2.5 | 38 | 6 / 5 | 1.000 |
| mini-swe vs OpenCode | 39 | 11 / 4 | 0.118 |
| OpenCode vs SAYACODE 3.2.5 | 39 | **1 / 7** | **0.070** |

- **全部不显著。** 四组共 6 对比较，Bonferroni α/6 ≈ 0.0083；即使按三组口径 α/3 ≈ 0.0167 也全部未达。
- 最小 p = 0.070（OpenCode vs SAYACODE），未过任何一个校正阈值。

### 3.2 3.2.7 vs 3.2.5（同制品族，78 个配对 trial）

| 项 | 值 |
|---|---|
| 通过 | 3.2.5：63/78 = 80.8% → 3.2.7：61/78 = 78.2% |
| Δ | **−2.6pp** |
| McNemar exact p | **0.8145**（不显著） |
| 题块 bootstrap CI95 | **[−12.5, +6.2] pp**（跨零） |
| 翻转 | 18 个 trial（3.2.5 独过 10、3.2.7 独过 8） |

**正确表述**：3.2.7 与 3.2.5 **未检出可测差异**。
**禁止表述**：「修复无效」——这套题 × 这套配置对三项修复的作用面为零（三重错配，见 §5.2），Δ 的信息量为零。

---

## 4. 新题库（SWE-EVO）状态

| 项 | 值 |
|---|---|
| 试点 | 5 题 × 2 重复 = 10 trial，`C:\sb\newset\runs\pilot1` |
| `planned` | **50.0%** (5/10) |
| 缺失 | 0 |
| `partial` | **不适用**（pilot 的 `partial` 字段为 `null`，verifier 输出未采集） |
| 逐题 | dask 2022.9.2 **0/2**（50 文件/1525 行）、dvc 1.11.12 1/2、dvc 2.21.1 **2/2**（1 文件/4 行）、dvc 2.58.1 0/2、dvc 3.15.0 **2/2**（1 文件/2 行） |

> ⚠️ **这份 50% 不能支撑「新题库更难」，也不能与 SWE-bench Pro V2 的 76.2% 比较。**
> 原因：`C:\sb\analysis\swe-evo-baseline.json` 只有 **4 条** `usable`，全是 dvc 的 **1–2 文件 / 2–21 行**小改动题；第 5 题（dask）是 `--include` 强制纳入的重题，实测 0/2。机制是：大改动题 p2p 多（dask 那题 2861 个）、镜像大 → 基线验证失败率高 → 被剔除 → **`usable` 集系统性偏向小改动题**。
> 扩样必须先按 gold 改动量分层抽样，不能用 `usable` 全集。详见 `docs/NEW-BENCHMARK-ONBOARDING.md` §5。

---

## 5. 已知数据缺陷（引用本 ledger 前必读）

### 5.1 `partial` 的数据源不唯一

`FINAL-SUMMARY-V4.json` 的 `trials[].partial` **字段覆盖极不完整**：`sayacode` **0/80**、`mini-swe` 13/80、`claude-code` 79/80、`opencode` 80/80。若直接对该文件求 partial 均值，SAYACODE 会得到空值。

**本 ledger 的 `partial` 一律取自 `C:\sb\analysis\dataset.json`**（391 行，`agent` + `tag` 区分批次），覆盖：sayacode/3.2.5 73/77、sayacode/3.2.7 72/77、mini-swe 77/78、claude-code 76/79、opencode 77/80。

**待修**：应让汇总脚本一次产出完整 `partial`，而不是依赖二次构建的 `dataset.json`。

### 5.2 Δ −2.6pp 的三重作用面错配

| # | 错配 | 证据 |
|---|---|---|
| 1 | 摘要降级路径**从未触发** | 单次输入峰值最大 127,369 < 触发线 **150,400**（`min(160000−9600, 192000×0.8)`，不是文档常写的 153,600） |
| 2 | 提示一致性修复**不改变行为** | `60ca2f0` 只在 `team_enabled=False` 生效；正式评测用 `studies/baseline.json` 的 `team_enabled=true` → 系统提示逐字节不变 |
| 3 | CompletionGuard **从未装配** | `completion_guard` 默认 `False`，`baseline.json` 的 `profile_overrides={}`；且 `41b1e38` 不在 3.2.7 制品内 |

### 5.3 3.2.7 制品实际只含两项修复

```
git diff --stat v3.2.5 ba43e04 -- src/
  src/sayacode/agent/graph.py    |   4 +-
  src/sayacode/agent/summary.py  | 116 ++++++++++++++
  src/sayacode/application.py    |   1 +
  src/sayacode/prompts.py        |  26 +++++
```

= 摘要失败降级 `c5d2973` + 提示/工具集一致性 `60ca2f0`。`41b1e38`（11-04 13:22）**晚于**发布提交 `ba43e04`（11-04 03:46）。
另：**PyPI 3.2.7 没有对应的 git tag**（最后 tag 是 `v3.2.6`）；HEAD 在 `ba43e04` 之后还有 4 个提交（+174/−20），全部不在制品内。

### 5.4 其他已知问题

- `C:\sb\hard\v2-325\STRICT-COMPARE.json` 是**陈旧产物**（mtime 11-05 17:23，早于 11-06 的修复声明），其 `missing` 与 `FINAL-SUMMARY-V4.json` 不一致（mini 2 vs 1、Codex 1 vs 0）。**不要引用它的任何数字**，包括 `snap_passes`。
- `reward is None` ≠ 缺失（327 是 3 vs 1、v2 mini 是 15 vs 14）。统计缺失必须同时看 `terminal` 与 `reward`。
- 40 题是**开发迭代集**，SAYACODE 的提示词规则 R1–R5 正是从这套题的失败个案调出的，**偏置方向对 SAYACODE 有利**。
- **从未执行冻结签收**（`lock_candidate`），因此按 `PROTOCOL-V2 §1` 的定义，以上全部是"开发期诊断"，不是"对外正式成绩"。

---

## 6. 生成与复算

| 数字 | 来源 | 复算方式 |
|---|---|---|
| 四组 `planned` / 缺失 / `task_macro` / McNemar | `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json`（**不是** `FINAL-SUMMARY-V3.json`） | 读 `agents[].{planned,passes,missing}` 与 `stats.pairwise` |
| 327 | `C:\sb\hard\v4-327\FINAL-SUMMARY-327.json` | 读 `agents.sayacode`、`stats` |
| `partial` | `C:\sb\analysis\dataset.json` | 按 `agent`+`tag` 分组；先题内平均再题间平均 |
| `touches_snap_pass` | 同上 `dataset.json` 的 `touches_snap` 字段 | 计数；**仅描述性** |
| 327 vs 3.2.5 配对 | 两批 `FINAL-SUMMARY` 的 trial 级 `effective_reward` | 按 (task, repeat) 对齐取交集 |
| SWE-EVO pilot | `C:\sb\newset\runs\pilot1\FINAL-SUMMARY-PILOT.json` | 读 `agents.sayacode` |
| 快照重置行为 | `C:\sb\s\swe-bench-pro-v2-*\v2\tasks\*\tests\test.sh:97-105` | 全量扫描 642 个文件 |

复算脚本：`scripts/build_analysis_dataset.py`、`scripts/final_summary.py`、`scripts/strict_compare.py`（**仅用于历史排查，其 strict 输出不得引用**）。

---

## 7. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-07 | v1.0 | 建立。废除 `strict` 口径（前提被证伪）；新增 `partial`；移除三行跨批次 McNemar；标注 3.2.7 只含两项修复；标注 SWE-EVO pilot 的选择偏差 |

---

**维护规则**：任何文档需要引用数字时，写「见 `docs/RESULTS-LEDGER.md` §x」而不是复制。发现本文件与原始 JSON 不符时，**以原始 JSON 为准**并立即修正本文件。
