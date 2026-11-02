# 评测报告模板

> 用法：复制本模板为 `docs/FORMAL-RESULTS-<批次>.md`，把 `<...>` 占位符替换为实际值。
> 文中带「示例」标注的数字来自 2026-11-02 的 v2 批次，只用于展示格式；替换前不得当作本批结论。
> 固定口径与不可声称清单是报告的一部分，禁止删除或改写为更有利的说法。

## 0. 元信息

| 字段 | 值 |
|---|---|
| 批次 ID | `<batch-id>` |
| 运行根 | `<C:\sb\hard\...>` |
| 日期 | `<YYYY-MM-DD>` |
| 产品版本 | `<SAYACODE x.y.z / commit>`（示例：SAYACODE 3.2.5 `13df615` / `v3.2.5`） |
| 评测实现 | `<commit>`（示例：`dfe2fd8`） |
| 冻结题集 | `studies/sample-40-final.json`，sha256 `<sha>` |
| 题数 / 仓库数 / 重复 | `<40> / <9> / <2>` |
| 规范模型 | `<auto-hy3>`（三 agent 统一；产品内部别名不算规范身份） |
| 口径版本 | `schema_version=<2>` |

## 1. 口径（三口径必须并列）

- **planned**：冻结题集每题 × 计划重复数，缺失一律按未通过计入。**对外只能引用这个分母。**
- **observed**：真正拿到 reward 或显式终态（`skipped_empty_patch`）的 trial 子集，含幸存者偏差。
- **task_macro**：先把同一题的重复归约成一个观察值，再对题取算术平均；重复次数不增加独立样本。
- **complete**：该 agent 拥有全部计划重复的题数（如 39/40），它决定 task_macro 是否代表整卷。

> 禁止：把 observed 当 planned；把 65/79 当 80；用 best-of-2 冒充 pass@1；删掉缺失只报告通过者。

### 五指标表（示例：v2 批次）

| agent | planned | observed | pass | planned% | observed% | task_macro | CI95 | complete | task_level | pass@2 |
|---|---|---|---|---|---|---|---|---|---|---|
| SAYACODE | 80 | 79 | 63 | **78.8%** | 79.7% | 80.8% | [69.2, 91.0] | 39/40 | 74.4% | 87.2% |
| mini-swe | 80 | 66 | 56 | **70.0%** | 84.8% | 84.8% | [75.8, 92.4] | 33/40 | 72.7% | 97.0% |
| Codex | 80 | 80 | 55 | **68.8%** | 68.8% | 68.8% | [57.5, 80.0] | 40/40 | 52.5% | 85.0% |

> 复算：`uv run --no-sync python scripts/final_summary.py --root <运行根>` 与
> `uv run --no-sync python scripts/final_stats.py --summary <运行根>\FINAL-SUMMARY.json`。

## 2. 缺失分类（必须逐条可解释）

| agent | 缺失合计 | no_job | empty_patch | unverified | model_fault |
|---|---|---|---|---|---|
| SAYACODE | 1 | 0 | 1 | 0 | 0 |
| mini-swe | 14 | 6 | 8 | 0 | 0 |
| Codex | 0 | 0 | 0 | 0 | 0 |

缺失明细（示例：v2 批次）：

- SAYACODE：`empty_patch`（tutanota-5181821-r1）
- mini-swe：`empty_patch` 8 条 + `no_job` 6 条（qutebrowser setup_timeout）

> 分类定义：`no_job` 磁盘无 job 目录；`empty_patch` 有 job 但 patch 缺失/0 字节；`unverified` 有非空
> patch 但无 reward/终态；`model_fault` 被 `MODEL-FAULTS.json` 归因且无 reward。若某条故障记录已归档成
> `no_job`，必须在明细里注明归因，不能静默消失。

## 3. 方差与不确定性

- 任务块 bootstrap：对题级观察值重抽 `samples=10000`、`seed=20261022`，取 2.5/97.5 分位。
- 仓库簇 bootstrap：以整个仓库为簇重抽，报告 `repositories` 与 `cluster_sizes`；仅作敏感性观察。
- pass@2 / pass^2：分别表示「至少一次通过」「所有重复都通过」，**都不是 pass@1**。
- 40 题的 95% 区间典型宽度约 ±11–15pp：不足以区分 <10pp 的差距。
- 全成或全败时经验 bootstrap 可能给零宽区间，这只说明样本内无变异，不能解读为总体概率确定。

## 4. 成本

- 报告 `input_tokens` / `output_tokens` / `usage_complete`；`cost_usd` 未知时写 `null`，不推测。
- 明确缓存读取与重试上界；没有完整计费账本时，不能声称「只请求 N 次 API」或「重试完全关闭」。
- 示例：v2 批次 `task_count` 全 0，本批不能评价多 agent 协作。

## 5. 显著性（题级 McNemar）

| 对比 | 共同题 | delta | p | 结论 |
|---|---|---|---|---|
| mini-swe vs SAYACODE | 32 | +1.6% | 0.727 | 不显著 |
| Codex vs SAYACODE | 39 | −10.3% | 0.021 | 未过 Bonferroni α/3=0.0167 |
| Codex vs mini-swe | 33 | −15.2% | 0.065 | 不显著 |

> 二值化定义必须标注（全重复通过 / 任一次通过）；不得把 best-of-2 当 pass@1 再算 McNemar。

## 6. 不可声称清单（必须逐条保留）

1. 三者校正后不显著时，**不能下「谁更强」的结论**。
2. `observed%` 存在幸存者偏差，**不能当总体成功率**（示例：mini-swe observed 84.8% 但 task_macro 仅 33/40）。
3. 补跑带来的增量**不能归因于产品改进**（示例：SAYACODE +11.3pp 主要来自补跑）。
4. `task_count=0` 时**不能评价多 agent 协作**。
5. 只测一个模型（hy3）时，**不能外推到其他模型或官方榜单**。
6. 任务可能被训练见过，**不能声称无污染**；本地环境与云端存在边界，**不能声称严格环境等价**。
7. CI 的 2 题 dry-run 冒烟**不是成绩**，只证明配置/题集/脚本可用。
8. 40 题、9 个仓库不足以支持 2–5 个百分点级别的细微收益宣称。

## 7. 产物与复现

- 逐 trial：`<运行根>\FINAL-SUMMARY.json`（含 `task/task_id/repo/repeat`、`restored_tests`、`stripped_tests`）。
- 统计：`final_stats.py` 的输出（题级 Wilson、bootstrap、pass@2/^2、McNemar）。
- 断点自愈：`uv run --no-sync python scripts/auto_resume.py --root <运行根>`（默认 dry-run，`--apply` 才移动）。
- 冒烟门禁：`uv run --no-sync python scripts/ci_smoke.py --dry-run`（不跑付费模型）；CI 见 `.github/workflows/eval-smoke.yml`。
- 续跑：`uv run --no-sync python scripts/run_formal_240.py --out <运行根> --skip-existing`，
  再 `uv run --no-sync python scripts/verify_patches.py --out <运行根> --tasks-root <v2/tasks>`。
