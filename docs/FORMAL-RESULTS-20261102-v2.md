# v2 完整重跑结果（2026-11-02）

> 运行根：`C:\sb\hard\v2-325`；设计 40 题 × 2 重复 × 3 agent = 240 trial。
> 产品 SAYACODE 3.2.5（`13df615` / `v3.2.5`）；评测实现 `dfe2fd8`。
> 口径：planned = 80 分母（缺失按失败）；observed = 有 reward/终态；task_macro = 题级宏平均。

## 一、终版五指标

| agent | planned | observed | pass | planned% | observed% | task_macro | CI95 | complete | task_level | pass@2 |
|---|---|---|---|---|---|---|---|---|---|---|
| SAYACODE | 80 | 79 | 63 | **78.8%** | 79.7% | 80.8% | [69.2, 91.0] | 39/40 | 74.4% | 87.2% |
| mini-swe | 80 | 66 | 56 | **70.0%** | 84.8% | 84.8% | [75.8, 92.4] | 33/40 | 72.7% | 97.0% |
| Codex | 80 | 80 | 55 | **68.8%** | 68.8% | 68.8% | [57.5, 80.0] | 40/40 | 52.5% | 85.0% |

> **严格口径（扣除「靠改 `.snap` 快照通过」）**：SAYACODE **78.8%** / mini-swe **65.0%** / Codex **65.0%**（mini −4、Codex −3 个 pass）。verifier 会重置测试代码（`tests/`、`*_test.go`）但**不重置 `__snapshots__/*.snap`**；主表仍用 planned，快照项作敏感性分析。详见 [TEST-EDIT-ANALYSIS](TEST-EDIT-ANALYSIS-20261102.md)。

## 二、题级 McNemar（任务块）

| 对比 | 共同题 | delta | p | 结论 |
|---|---|---|---|---|
| mini-swe vs SAYACODE | 32 | +1.6% | 0.727 | 不显著 |
| Codex vs SAYACODE | 39 | −10.3% | 0.021 | 未过 Bonferroni α/3=0.0167 |
| Codex vs mini-swe | 33 | −15.2% | 0.065 | 不显著 |

## 三、缺失（15 条）

| agent | 缺失 | 分类 |
|---|---|---|
| SAYACODE | 1 | empty_patch（tutanota-5181821-r1） |
| mini-swe | 14 | empty_patch 8 + no_job 6（qutebrowser setup_timeout） |
| Codex | 0 | — |

## 四、补跑效应

| agent | 初始 planned% | 终版 planned% | 增量 |
|---|---|---|---|
| SAYACODE | 67.5% | 78.8% | +11.3pp |
| mini-swe | 47.5% | 70.0% | +22.5pp |
| Codex | 68.8% | 68.8% | 0 |

## 五、必须同读的边界

1. 三者校正后**不显著**，不能下「谁更强」的结论。
2. mini-swe 的 observed 84.8% 存在幸存者偏差（66/80，task_macro 仅 33/40）。
3. Codex 是唯一零缺失（40/40），其数字最可信；task_level 52.5% 最低。
4. SAYACODE 的 +11.3pp 主要来自补跑，不能归因于 3.2.5 的两个 bug 修复。
5. 240 trial 的 `task_count` 全 0，本批不能评价多 agent 协作。
6. 仅 hy3；40 题 CI ±11–15pp，不足以区分 <10pp 差异。

## 六、产物

- 逐 trial：`C:\sb\hard\v2-325\FINAL-SUMMARY.json`（含 task/task_id/repo/repeat）
- 统计：`C:\sb\hard\v2-325\logs\final\`（final-summary.txt / final-stats.txt / stats-four.txt / final-classify.json）
- 教训：`docs/LESSONS-20261102-v2.md`
