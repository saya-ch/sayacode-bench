# FORMAL RESULTS：三 agent 正式对比（2026-10-31）

> **基准**：SWE-bench Pro V2 public set，40 题（`studies/sample-40-final.json`，gold patch 全绿）
> **模型**：hy3（`auto-hy3`），上下文 192k / 输出 16k
> **设计**：3 agent × 40 题 × 2 重复 = 240 trial；配对；Bonferroni α/3 = 0.0167
> **执行**：阶段1（解题，14 并发，跳过验证器）+ 阶段2（PatchReplay 统一验证，4 并发）

## 1. 最终结果

| agent | 有效 trial | **pass@1** | 95% CI | partial | 改测试率 | 空 patch | bloat 中位 |
|---|---|---|---|---|---|---|---|
| **SAYACODE** | 80 | **68.8%** | [58%, 78%] | 88.7% | **49%**（被恢复）| 8 | 0.73× |
| **mini-swe-agent** | 80 | **86.2%** | [77%, 92%] | 96.3% | 0% | 1 | 1.29× |
| **Codex CLI** | 65 | **86.2%** | [76%, 93%] | 95.3% | 0% | 0 | 1.01× |

### pass@2 / pass^2（同题两次）

| agent | 题数 | pass@2（任一次过）| pass^2（两次都过）|
|---|---|---|---|
| SAYACODE | 39 | 87.2% | **48.7%** |
| mini-swe | 39 | 97.4% | **74.4%** |
| Codex | 28 | 100% | **75.0%** |

### 两两配对 McNemar（同题取最好）

| 对比 | 共同题 | A 独过 | B 独过 | p 值 | 显著（α/3=0.0167）|
|---|---|---|---|---|---|
| SAYACODE vs mini-swe | 40 | 0 | 4 | 0.125 | ❌ |
| SAYACODE vs Codex | 40 | 0 | 3 | 0.250 | ❌ |
| mini-swe vs Codex | 40 | 1 | 0 | 1.000 | ❌ |

**统计结论**：三组差异**均不显著**（p > 0.0167）。方向上是 SAYACODE 更低（0 题独过 vs 对手 3–4 题独过），但样本量不足以下结论。

## 2. 关键发现

### 2.1 SAYACODE 改测试率 49%（其余为 0）

- 抽样证据：`test/units/modules/test_pip.py`、element-web 的 `*-test.tsx` 与 `__snapshots__/*.snap` 被修改
- Harbor 验证器**检测并恢复**（`restored-test-files.json`，reason: "existing test files must not be modified"）
- 改测试的 trial 中：**通过 26 / 失败 10**
- 判定：**不是成功的 reward hacking**（验证器兜住了），但**行为倾向值得警惕**——SAYACODE 会尝试改测试来通过

### 2.2 SAYACODE 的 pass^2 明显更低（48.7% vs 74.4%）

- 即"同一题两次都过"的比例明显更低 → 稳定性/一致性差
- 结合空 patch 8 个（其余 0–1），说明 SAYACODE 有更多"没产出有效补丁"的情况

### 2.3 bloat 分布

- SAYACODE 0.73×（补丁比 gold 小，可能**改得不完整**）
- mini-swe 1.29×（补丁更大）
- Codex 1.01×（最接近 gold 规模）

## 3. 已知局限（必须随结论声明）

1. **统计不显著**：40 题 × 2 重复不足以区分 68.8% 与 86.2%（McNemar 均 p>0.0167）
2. **Codex 只有 65/80 有效**：15 个 trial 因阶段1 的 infra error 失败（未补跑）
3. **协议不同**：SAYACODE=Anthropic messages / mini-swe=OpenAI chat / Codex=OpenAI responses（同一 Magpie、同一 hy3）
4. **上下文策略不同**：SAYACODE 摘要（触发 153.6k）/ mini-swe 输出截断 / Codex paginated + 截断
5. **改测试率统计口径**：49% 是"被检测到改测试"的比例，不等于"成功作弊"
6. **仅 hy3**：结论不外推到其他模型

## 4. 证据链

- 题集：`studies/sample-40-final.json`（40 题，gold patch 全绿）
- 阶段1：`formal-240/<agent>/jobs/`（patch）
- 阶段2：`formal-240/<agent>/verify/jobs/`（PatchReplay 验证）
- 汇总：`formal-240/FINAL-SUMMARY.json` + `scripts/final_summary.py`
- 执行日志：`C:\sb\hard\stage1-final.log`、`stage2c.log`、`orchestrator.log`

## 5. 后续（若要坐实结论）

1. 补跑 Codex 15 个失败 trial
2. 扩大到 100 题（CI 收窄到 ±9pp）
3. 对 SAYACODE 改测试行为做专项分析（哪些题、为什么改）
4. 多模型验证（若成本允许）
