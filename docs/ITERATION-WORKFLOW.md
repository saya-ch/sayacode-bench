# 调优迭代工作流（执行层）

日期：2026-10-29。状态：**执行层工具与流程说明；不产生正式成绩，不改变预注册协议**。

本文服务于开发期内部调优（原正式研究计划见 [WORK_PLAN 归档](archive/WORK_PLAN.md)），规定**日常调优怎么快速迭代、怎么量化、怎么判定**。它与 [protocol.md](protocol.md) 的关系：protocol 决定「研究什么、怎么统计」，本文决定「开发期怎么高频试错」。两者都不把开发期诊断结果计入正式分母。

## 0. 四条原则（承接 protocol 的证据观）

1. **护栏先行**：结果变好但过程护栏变差（改既有测试、回归破坏、空转）→ 不采纳。
2. **过程指标是诊断，不是效果证据**：步数、token、改测试次数只用来说明「为什么」，不作为「模型更强」的证据（同 protocol「机制未触发不讨论收益」）。
3. **免费杠杆优先**：同批数据多算指标 > 加重复 > 加题量。
4. **开发结果不入正式分母**：本工作流产出的数字是开发诊断，正式成绩仍按 protocol 冻结清单与配对重复产出。

## 1. 三层评测金字塔

| 层 | 内容 | 规模 | 反馈 | 工具 |
|---|---|---|---|---|
| **L1 能力诊断** | `evals/scenarios/*.jsonl`（协作、上下文等切片）+ 合成小场景 | 1–3 场景 | 秒–分 | `evals.run`（产品仓） |
| **L2 回归集** | `studies/regression-set.json`：历史失败题（验证修复）+ 稳定通过题（验证无回归） | 5–10 题 | 5–15 分 | `scripts/run_regression.py` |
| **L3 配对正式** | 开发/最终集按 protocol 冻结清单，配对重复 | 按 protocol | 小时 | `src/sayacode_bench` + `scripts/analyze_trials.py` + `scripts/compare_trials.py` |

## 2. 指标体系

| 层 | 指标 | 说明 |
|---|---|---|
| 结果 | pass@1、**partial credit**（通过必需测试/必需测试）、pass@k、**pass^k 一致率**、回归破坏率 | partial 与 pass^k 比 0/1 信息量大得多 |
| 过程（诊断） | 步数、重复读文件、**改既有测试次数**、**空转率(patch=0)**、首次编辑前探索步数、API 失败 | 用于定位原因，不作效果证据 |
| 效率 | token/成功、时长/成功 | 仅描述资源 |

## 3. 判定规则（开发期 Go/No-Go）

| 检查 | Go | No-Go |
|---|---|---|
| 护栏（一票否决） | 改既有测试=0；回归破坏=0；空转率≤基线 | 任一恶化 |
| 结果效应 | risk difference ≥ +15pp 且配对 95%CI 不跨 0（McNemar p<0.05） | CI 跨 0 或为负 |
| 稳定性 | pass^k 不下降 | 下降（一过一败加剧） |

护栏不过，效应量再好也回退。判定后把候选身份交 protocol 的冻结流程，而不是在开发集上反复看成绩调参。

## 4. 工具

| 用途 | 命令 |
|---|---|
| L2 回归 | `python scripts/run_regression.py --candidate <variant.json>` |
| 指标（结果+过程+护栏） | `python scripts/analyze_trials.py <jobs目录>...` |
| 配对 A/B | `python scripts/compare_trials.py <A_jobs> <B_jobs> --best-of` |

三者只读取已完成的 trial 工件（reward、验证器 stdout、events、patch），不调用模型，不建立新评分器。

## 5. 护栏的机制前提

过程护栏（尤其「改既有测试」）依赖 `worker.capture_patch` 的测试保护：
- `restore_existing_test_files`：恢复被改/删的既有测试；
- `strip_new_test_files`：剔除新增测试文件。
两者在补丁采集阶段生效，并在 trial 目录写 `restored-test-files.json` / `stripped-new-test-files.json` 供统计。

## 6. 诚实边界

- 本工作流的探索性结果（如 2026-10 的 holdout 探索，见 [EXPLORATORY 归档](archive/EXPLORATORY-20261029.md)）**不是正式成绩**，不写入公开子集分数。
- partial credit 可被「改测试」抬高，因此必须与护栏同报；只看 partial 会自欺。
- 当前 bench 处于「开发期重建中」：v1 跑批结论已作废，正按统一口径重跑 v2（见 [STATUS](STATUS.md)），本文不改变该状态。

## 7. 评测模型（暂定只用 hy3，2026-10-30 更新）

**暂定只用 hy3**（腾讯混元，`auto-hy3` 组）。选它的理由：能力低于前沿模型 → 天花板效应低、同一改进更易显现、区分度高；额度充足（`workbuddy-ai` Free plan）可支撑高频迭代。

> deepseek-v4.1-flash 仅作**可选**的最终确认手段，**尚未确认使用**，当前不纳入流程。

规则：
1. **每个 trial 必须记录 `served` / `provider`**（`scripts/annotate_served.py`，按 trial 时间窗从 Magpie usage 关联，且**只统计评测 agent**，排除对话 agent），以证明"实际测的是同一模型"。
2. hy3 的失败要区分「能力不足」与「agent 设计缺陷」——只有后者才是迭代目标。
3. 详见 [ROUTING-DRIFT](ROUTING-DRIFT-20261029.md) 第六节（hy3 组实测）与第二节（auto-deepseek 混 glm 的风险）。

### hy3 基线（⚠️ 已作废，2026-10-29，在 65536 错误配置下测得）

> 下表在 `context_length=65536`（触发点 52k）下产生，**配置错误，不得引用**，仅作历史记录。修正配置（192k）后的基线待重跑。

| 结果 | 题 |
|---|---|
| PASS（5） | ansible-de01、element-9bf、vuls-e52、openlibrary-3f7、navidrome-812 |
| FAIL（3） | element-d405（partial 40%）、openlibrary-fdbc（**partial 97%**，差一点）、tutao-518（**partial 0%，空转**） |

- pass@1 = 5/8 = 62.5%（95%CI 31–86%，n 小仅作基线）；平均 partial = 79.7%；平均步数 28（deepseek 同集为 61）。
- 改既有测试触发 3 次、空转 1 个 → 护栏有实际拦截对象。
- served 分布（194 次评测调用）：`hy3/workbuddy` 94 + `hy3/workbuddy-ai` 86 + `hy3-x/workbuddy` 14，**全部 hy3 系列、零 deepseek**，证明 profile 生效且权重在分摊额度。
- 与 deepseek 的回归集结果**互补**（hy3 救了 element-9bf、丢了 openlibrary-fdbc），因此**必须双基线**。

## 8. 跑前配置汇报（硬性流程，2026-10-30 起）

每次跑批（L1/L2/L3）**启动前必须**：

1. 执行 `python scripts/profile_summary.py <profile.json>`，确认：模型 id、协议、**上下文长度**、最大输出、**摘要触发点**、摘要保留消息、上下文编辑参数；
2. 把该摘要**汇报给用户并取得确认**；
3. 用户确认后才启动跑批。两个 runner（`run_holdout.py` / `run_regression.py`）也会在跑前自动把同一摘要写入日志。

### 为什么要立这条规矩

2026-10-30 发现 **context_length 被系统性配小**：

| 模型 | 实际 context | 曾配置 | 实际摘要触发点 | 曾触发点 |
|---|---|---|---|---|
| hy3 | 192,000 | 65,536 | 153,600 | 52,428 |
| deepseek-v4.1-flash | 1,000,000 | 65,536 | 720,000 | 52,428 |

后果：长任务（需要大量读文件的 element-web / qutebrowser / navidrome）在 52k 就被摘要压缩、丢失任务细节，容易草率收尾——这解释了 hy3 平均步数只有 28（deepseek 61）。**此前基于 65,536 配置的所有探索性结论均偏低，只作方向性参考。**

现行 profile（v2 起）：
- `magpie-hy3.json`：192000 / **32000** → 摘要触发 153,600（**当前唯一在用**；v1 用 16000，长任务收尾过早，v2 已修正）
- `magpie-deepseek.json`：900000 / 32000 → 触发点 720,000（**暂未使用**，仅备用）

## 9. 记分卡指标（每批自动产出，`analyze_trials.py`）

对齐 2026 主流 agent 评测（四层：结果/轨迹/效率/安全），在原有基础上补齐 5 项**零额外成本、抗刷**的指标：

| 指标 | 定义 | 来源 | 用途 |
|---|---|---|---|
| **cost-per-success** | 总 token ÷ 通过题数 | `agent_result` tokens | 决策核心：多花的钱换几个点 |
| **step-per-success** | 总步数 ÷ 通过题数 | `events.jsonl` | 抓"绕远路" |
| **reward hacking rate** | 改/删测试的 trial 比例 | `restored/stripped-test-files.json` | **防虚高**（partial 可被改测试刷高）；这是**产品侧检测率**，与「patch 含测试文件比例」是两个口径，不可混 |
| **bloat ratio** | model.patch ÷ gold_patch 大小（中位）| `model.patch` / `solution/gold_patch.diff` | 抓过度修改 |
| **重复方差** | 同题多次的通过率标准差 | 多次重复 | 显式量化 run-to-run 噪声 |

**报告格式**：`成功率(±CI) | partial | cost/成功 | step/成功 | 改测试率 | bloat | 空转 | 重复方差`

**不纳入**：tool schema/argument validity（SWE 工具少）、safety（无安全维度）、LLM-as-judge/rubric（引入偏置）、trajectory exact-match（无参考轨迹）。

**原则**：只加"可行动 + 抗刷 + 零成本"的指标；指标越多越易 Goodhart，故 partial 必须与 reward hacking 同报。
