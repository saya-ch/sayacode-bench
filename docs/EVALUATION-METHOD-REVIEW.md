# 评测方法核对：与业界主线对照（2026-10-29）

> 目的：核对本仓库 [调优迭代工作流](ITERATION-WORKFLOW.md) 与当前业界 Agent 评测方法的一致性，指出缺口。来源为公开资料，结论以本仓库协议为准。

## 一、业界共识（带来源）

1. **pass@k 与 pass^k 是互补的两个指标**。pass@k（Chen et al. 2021，Codex）＝k 次至少一次成功（能力上限）；pass^k（τ-bench，Sierra，[arXiv:2406.12045](https://arxiv.org/pdf/2406.12045)）＝k 次全部成功（**可靠性**）。τ-bench 的实证：即便强模型 pass^8 在零售域 <25%——"[pass@k flatters your agent; pass^k tells you whether to ship it](https://qaskills.sh/blog/tau-bench-agent-evaluation-guide-2026)"。
2. **结果 grader 决定是否发布，轨迹用于定位原因**。Eval-Driven Development 的典型流程是"[Outcome gates, trajectory debugs](https://www.tmls.nyc/research/eval-driven-development)"：结果分决定 ship，出错时看轨迹定位。
3. **统计不确定性被普遍低估**。EDD 综述指出"the field routinely under-reports uncertainty"，并主张带形式保证的估计程序（如配对 bootstrap）。
4. **harness 设置必须随分数报告**。HF 分析：同一 LLaMA-65B 在 MMLU 上按 lm-eval-harness 得 0.488、按 HELM 得 0.637——"模型 × harness 不能拆开看"。
5. **温度=0 / 固定种子用于可复现**。SWE-Bench 实践建议"[temperature set 0 是为了评测可复现](https://blog.csdn.net/weixin_42581003/article/details/169337933)"。
6. **早停节省时间与 API 花费**。lm-evaluation-harness/MLflow 实践："[early stopping ... saves both time and API spend](https://mlflow.org/articles/llm-evaluation-harness)"。
7. **记录完整轨迹**（transcripts + tool-call traces），不只最终输出。
8. **grader 分型**：code-based（确定性）、model-based（LLM judge）、human。code-based 最客观，但 LLM-judge 有已知偏置。

## 二、我们的工作流已对齐的部分

| 业界实践 | 本仓库对应 | 状态 |
|---|---|---|
| pass^k 可靠性 | 工作流指标表含 pass^k 一致率 | ✅ 已定义 |
| outcome gate + trajectory debug | 结果指标定 Go/No-Go，过程指标定位 | ✅ 三层指标 |
| 统计不确定性 | pass@1 + Wilson 95%CI；`compare_trials.py` 配对 McNemar | ✅ |
| 配对 bootstrap | bench `protocol`/`sensitivity` 已声明 paired task bootstrap | ✅ 正式协议已含 |
| 早停 | 工作流「空转/token 陡增 → 早停」 | ✅ |
| 完整轨迹记录 | `events.jsonl` / `audit.jsonl` / 工具输出 | ✅ |
| code-based 客观评分 | 官方 Harbor 验证器（非 LLM judge） | ✅ 规避 judge 偏置 |
| harness 可追溯 | 记录 wheel/profile/镜像/超时/变体 | ✅ |

**结论：主线方法一致，没有方向性错误。**

## 三、发现的缺口（建议补）

| 缺口 | 影响 | 建议 |
|---|---|---|
| **温度/采样未显式固定** | 可复现性；可能放大同题方差 | 在 profile 增加并记录 `temperature=0`（若上游支持）；不支持的模型在报告中注明 |
| **轨迹评测偏统计、缺结构化评分** | 只看步数/改测试，未评"路径是否合理" | 可选：对轨迹加轻量规则 grader（是否先读后改、是否验证、是否改测试） |
| **partial credit 可被"改测试"抬高** | 结果虚高 | 已用护栏（改测试次数、回归破坏）对冲；必须同报 |
| **样本量与功效** | 小样本 CI 宽 | 已给功效表；正式结论按 protocol 冻结规模执行 |

## 四、对当前工作的意义

- 我们的指标体系（partial + pass^k + 过程护栏 + 配对统计）**与 τ-bench / EDD / HELM 主线一致**，不是自创。
- 最值得立刻补的是**温度固定**（低成本、影响可复现性），以及在报告中显式写"harness 设置"（模型、wheel、镜像、超时、温度）。
- 轨迹结构化评分是可选增强，非阻塞。

## 五、参考

- τ-bench / pass^k：[arXiv:2406.12045](https://arxiv.org/pdf/2406.12045)、[Sierra](https://sierra.ai/blog/tau-bench-shaping-development-evaluation-agents)
- Eval-Driven Development：[TMLS](https://www.tmls.nyc/research/eval-driven-development)、[arXiv:2411.13768](https://arxiv.org/html/2411.13768v2)
- Eval harness：[MLflow](https://mlflow.org/articles/llm-evaluation-harness)、[Arize](https://arize.com/blog/what-is-an-evaluation-harness)
