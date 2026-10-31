# STATUS：当前真实状态

更新：2026-10-31。**当前处于开发期重建中：v1 跑批的结论已作废，正在按修正后的口径重跑。**

本文件只写**当前有效**的事实。历史快照与作废结论见 [docs/archive/](archive/README.md)；交接与坑清单见 [HANDOFF](HANDOFF.md)。

## 1. 一句话状态

v1 的 240 trial（3 agent × 40 题 × 2 重复）已收尾但**不完整**：221/240 完整，19 条缺口。v1 的三 agent 对比结论（68.8% vs 86.2% vs 86.2%）**作废**——分母三套、改测试口径混用、坏题率描述不成立。正在按统一口径重跑（输出到 `C:\sb\hard\v2`，`max_output_tokens=32000`）。

## 2. 已核实的数字（写文档以此为准）

### 2.1 旧结果的三套分母（v1，不可并列比较）

| agent | 有效 trial | 原始分母结果 | 统一 80 分母 |
|---|---|---|---|
| SAYACODE | 80 | 55/80 = 68.8% | 55/80 = 68.8% |
| mini-swe-agent | 80 | 69/80 = 86.2% | 69/80 = 86.2% |
| Codex CLI | 65 | **56/65 = 86.2%** | **56/80 = 70.0%** |

- **17.4pp 差距是分母假象**：Codex 只有 65 条有效 trial（15 条缺口），86.2% 是 56/65；若统一到 80 分母是 70.0%。
- 因此「SAYACODE 68.8% 对 对手 86.2%」**不成立**，不能作为对比结论。

### 2.2 改测试：两个口径，不可跨 agent 比

| 口径 | SAYACODE | mini-swe-agent | Codex CLI |
|---|---|---|---|
| 产品侧**检测率**（改测试被验证器发现并恢复）| **39/80 = 48.8%** | 未按此口径统计 | 未按此口径统计 |
| **patch 含测试文件**（最终提交里含测试改动）| **0%** | **70.9%** | **54.2%** |

- 48.8% 是「SAYACODE 尝试改测试、被 `restore_existing_test_files` 恢复」的比例，**不是作弊成功**，也不是「patch 含测试」。
- 70.9% / 54.2% 是最终 patch 里含测试文件的比例，口径不同，**不能与 48.8% 比大小**。
- 三者（检测率 vs patch 内容）**不可跨 agent 直接比较**；任何报告必须写清是哪个口径。

### 2.3 模型故障：只有 1 条真 API 故障

- 真 API 故障 **1 条**：`vuls-f6cc8c-r1`（ECONNRESET）。
- 2 条 tutao（`tutao-51818218` r1/r2）**不是模型故障**：`completed + verified + reward=0` 的**空 patch**，是 agent 正常完成但没产出。
- **严格剔除后：55/79 = 69.6%**（只剔除那 1 条真故障）。旧文档的「3 条故障、71.4%」口径不成立。

### 2.4 坏题：gold-check 实际 36 good / 1 bad / 3 null

- 40 题 gold-check 的真实结果是 **36 good / 1 bad / 3 null**；**bad 题不在最终 40 题内**。
- 「40 题全绿」**不成立**——3 个 null 表示未取得有效 gold 结论，不能当「通过」。
- 坏题率不能简单写成 1/40；口径是「1 bad 已剔除、3 null 待补」。

### 2.5 19 条缺口（v1，240 目标 vs 221 完整）

| 类别 | 条数 | 明细 |
|---|---|---|
| 无目录 | 4 | Codex 侧 4 条：缺 trial 目录（无 job 记录）|
| 空 patch | 4 | 有 trial 目录但 patch 为空 |
| 有 patch 未验证 | 7 | Codex「有 patch 无 reward」中待阶段2 验证的部分 |
| 小计（Codex）| 15 | Codex 65/80 |
| SAYACODE | 3 | tutao r1/r2（空 patch）+ vuls-f6cc8c r1（ECONNRESET）|
| mini-swe | 1 | ansible-de5858xx r1（有 reward 无 patch）|
| **合计** | **19** | 221/240 完整 |

> 缺口 job 已归档在 `C:\sb\hard\formal-240\abandoned-gaps\`，可重跑；但 v1 结论已作废，**不补跑 v1**，直接进 v2。

## 3. 已作废的结论（不得再引用）

| 曾声称 | 作废原因 |
|---|---|
| SAYACODE 68.8% 低于 mini-swe/Codex 的 86.2%（17.4pp 差距）| 三套分母并列；Codex 实为 56/65，统一分母 70.0% |
| 「SAYACODE 改测试率 49%（其余 0%）」| 49%≈48.8% 是**检测率**；patch 含测试比例是 SAYACODE 0% / mini-swe 70.9% / Codex 54.2% |
| 「mini-swe 改测试 73%、Codex 42%」| 旧口径错误，正确为 70.9% / 54.2% |
| 「3 条模型故障，剔除后 71.4%」| 只有 1 条真 API 故障；严格剔除后 55/79 = 69.6% |
| 「40 题 gold patch 全绿 / 坏题率 1/40」| 实际 36 good / 1 bad / 3 null；bad 不在 40 题内，null 不能算绿 |
| 「v2-tuned 调优有收益」| 规则基于误读，A/B 中止，见 [归档说明](archive/README.md) |
| 「正式模型试验为 0」| 已过时：v1 开发期跑批已执行 221 条完整 trial（但结论作废）|
| 早期探索数字（holdout 70%、token 降 82% 等）| 65536 配错 + 路由漂移，全部作废，见 [EXPLORATORY 归档](archive/EXPLORATORY-20261029.md) |

## 4. 基础设施当前事实

- **模型**：hy3（`auto-hy3` 组，同模型多额度池），context 192,000；**max_output_tokens 修正为 32,000**（v1 用 16,000，长任务收尾过早）。
- **基准**：SWE-bench Pro V2 public set，40 题开发迭代集（`studies/sample-40-final.json`）；不用 Terminal-Bench。
- **跑批入口**：`scripts/run_formal_240.py`（阶段1 解题，`--skip-verifier`）+ `scripts/verify_patches.py`（阶段2 PatchReplay 统一验证）+ `scripts/final_summary.py`（汇总）。
- **并发**：trial 并发 4–6，验证器限流 1（每 trial 占 2 个 Docker 网络，池约 17；并发 14 必爆）。
- **结果目录**：v1 在 `C:\sb\hard\formal-240`；v2 计划在 `C:\sb\hard\v2`。
- **测试与 CI**：本地 `uv run --no-sync pytest -q` 通过；具体计数以最近一次实际运行为准，不在本文写死（避免再次过期）。

## 5. 已知局限（必须随任何结论声明）

1. **样本小**：40 题 × 2 重复，95% CI 半宽约 ±14pp；不足以区分 10pp 量级差异。
2. **多重比较**：3 agent 两两比较需 Bonferroni α/3 = 0.0167。
3. **协议不同**：SAYACODE = Anthropic messages / mini-swe = OpenAI chat / Codex = OpenAI responses（同 Magpie、同 hy3）。
4. **上下文策略不同**：SAYACODE 摘要（触发 153.6k）/ mini-swe 输出截断 / Codex paginated + 截断。
5. **仅 hy3**：结论不外推到其他模型。
6. **v1 缺口未补**：19 条缺口使 v1 各 agent 分母不同；v2 必须以完整 240 条为前提。
7. **gold-check 3 个 null**：3 题未取得有效 gold 结论，v2 前需补齐或替换。

## 6. 下一步（按优先级）

1. **v2 重跑**：40 题 × 2 重复 × 3 agent = 240 trial，输出 `C:\sb\hard\v2`，`max_output_tokens=32000`，统一验证器口径。
2. **补齐 gold-check**：3 个 null 题重新跑 gold patch 或替换。
3. **v2 汇总按统一口径**：分母必须都是 80；改测试分「检测率」与「patch 含测试」两列；模型故障逐条列明。
4. **调优（暂缓）**：v2 结果出来前不做任何 prompt/规则调优；正确顺序是逐题对比找失败模式再设计规则。
5. **正式对外研究（未启动）**：protocol 预注册仍在，但需 v2 开发期结论稳定后再谈冻结。

## 7. 证据位置

| 内容 | 位置 |
|---|---|
| v1 逐 trial 明细 | `C:\sb\hard\formal-240\FINAL-SUMMARY.json` |
| v1 缺口 job | `C:\sb\hard\formal-240\abandoned-gaps\` |
| v1 异常审计 / 模型故障清单 | `C:\sb\hard\formal-240\AUDIT.json`、`MODEL-FAULTS.json` |
| 题集 | `studies/sample-40-final.json` |
| 任务缓存 | `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\v2\tasks` |
| 历史文档 | [docs/archive/](archive/README.md) |
