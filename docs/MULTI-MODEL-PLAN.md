# MULTI-MODEL-PLAN：第二模型扩展设计（2026-11-02）

> 状态：**设计稿，未执行**。协议口径以 [PROTOCOL-V2.md](PROTOCOL-V2.md) 为准；路由事实见 [ROUTING-DRIFT-20261029.md](ROUTING-DRIFT-20261029.md)；方法边界见 [EVALUATION-METHOD-REVIEW.md](EVALUATION-METHOD-REVIEW.md)。

## 0. 一句话

在现有 hy3 之外增加第二个模型（首选 `deepseek-v4.1-flash`），必须走同一套 [PROTOCOL-V2](PROTOCOL-V2.md) 口径、固定路由、按「**模型 × harness**」成对报告。**模型 × harness 不可拆开看**：任何「某模型 xx%」的说法都必须同时说明跑在哪个 harness 上。

## 1. 现状与目标

- **现状**：只有 hy3（`auto-hy3` 组），3 个 harness（SAYACODE / mini-swe-agent / Codex CLI），40 题 × 2 重复的开发期矩阵（[FORMAL-RESULTS-20261102-v2.md](FORMAL-RESULTS-20261102-v2.md)）。
- **目标**：加入第二模型，回答两个可分离的问题：
  1. **固定 harness 换模型**差多少（控制 harness）；
  2. **固定模型换 harness**差多少（控制模型）；
  3. 两者的**交互项**（某模型是否特别适配某 harness）。
- **非目标**：不做「最强模型」总排名；不把不同模型/不同 harness 的分数合成一个总分。

## 2. 核心原则：模型 × harness 不可拆开看

- **实证依据**：HF 分析显示同一 LLaMA-65B 在 MMLU 上按 lm-eval-harness 得 0.488、按 HELM 得 0.637——「模型 × harness 不能拆开看」（[EVALUATION-METHOD-REVIEW](EVALUATION-METHOD-REVIEW.md) §一.4）。同一模型换 harness 可差 15pp，远大于多数模型间差异。
- **路由前提**：同一别名可能混入不同模型（`auto/deepseek...` 实测 40% 漂到 glm-5.3-flash）。模型身份不固定时，任何「模型对比」都是假的（[ROUTING-DRIFT](ROUTING-DRIFT-20261029.md)）。
- **报告规则**：
  - 跨**模型**比较：只在**同一 harness、同一协议、同一题集**下成立；
  - 跨 **harness** 比较：只在**同一模型**下成立；
  - 只有全因子设计（2 模型 × 3 harness）才能讨论交互项；
  - 单列「模型分数」或「harness 分数」都是误导。

## 3. 第二模型选择与固定路由

| 项 | 方案 |
|---|---|
| 首选模型 | `DeepSeek-V4.1-Flash`（[protocol.md](protocol.md) 的规范模型身份，开发期已有可选配置）|
| 备选 | 若额度/稳定性不足，记录原因后另选，但必须走同一协议；不得用会漂移的别名凑数 |
| **固定路由** | **禁** `auto/...`、`group/...` 泛指别名（40% 漂到 glm）；用 provider 前缀固定：**`workbuddy/deepseek-v4.1-flash`**（历史探测 2/2 稳定，可用）；`commandcode-plan/deepseek/...` 曾 HTTPError（需额外认证），暂不可用 |
| 路由门禁 | 跑前、跑后各探测 N 次（建议 ≥8），served 分布不唯一 → 本轮标「未固定来源，不可比」并中止 |
| 逐 trial 记录 | 用 `scripts/annotate_served.py` 记录 `served` / `provider`；`canonical_model` 写规范身份，实际 served 单列 |
| 身份限制 | 模型名称与接口字段不能证明上游权重完全相同，报告须注明 |

## 4. 协议对齐（与 PROTOCOL-V2 一致）

| 对齐项 | 要求 | 差异登记 |
|---|---|---|
| 题集 | 同 40 题（`studies/sample-40-final.json`）、同 seed；扩样时同清单 | — |
| 重复 | 每题 2 次；配对块 = `task × repeat` | — |
| 验证器 | 官方 Harbor + PatchReplay 统一验证；**stage1 与 verify 串行** | — |
| 分母 | planned 80 为主；缺失按 [PROTOCOL-V2 §3](PROTOCOL-V2.md) 分类；给 worst/best | — |
| 统计 | 题级 Wilson + 任务块 bootstrap + 题级 McNemar；多模型时按比较数校正 | — |
| 补跑 | 环境类（infra/no_job/unverified）可补；timeout / empty_patch 不补 | — |
| 权限 | 三个 harness 均完全权限，配置不变 | — |
| 上下文/输出 | 见 §5，逐项显式对齐并记录 | 差异必须写偏离 |
| 记录格式 | 按 [record-schema.md](record-schema.md) | — |

注意：**模型能力差异不算协议偏离**；但「某模型用 32k 输出、另一个用 16k」这种预算不一致**必须**记偏离，否则不可比。

## 5. 上下文 / 输出预算

| 模型 | 实测 context | max_output（模型上限）| profile 配置（v2 起）| 摘要触发点 |
|---|---|---|---|---|
| hy3 | 192,000 | 64,000 | 32,000 | 153,600 |
| deepseek-v4.1-flash | 1,000,000（历史实测；须 `/v1/models` 复核）| 按 `/v1/models` 实测填写（**不得抄旧值 65,536**）| `magpie-deepseek.json` 曾配 900000 / 32000 | 720,000（配 900k 时）|

规则：

1. 两个模型都**必须**显式对齐 context 与 max_output 并记录；跑前用 `scripts/profile_summary.py` 汇报。
2. 输出预算统一 32,000；v1 hy3 用 16,000 导致长任务收尾过早（[LESSONS §3](LESSONS-20261102-v2.md)），deepseek 同理不得压到 16k。
3. 上下文窗口不同本身是模型/harness 配置差异，不构成偏离，但**必须记录**，且不得用「一方 192k、一方 1M」的窗口差异直接归因能力。
4. deepseek 的 max_output 上限须实测确认后再冻结，不凭旧文档假定。

## 6. 成本记录

- **必记**：`input_tokens` / `output_tokens` / `usage_complete`；费用未知写 `unknown`，不猜。
- **跨模型比 cost-per-success**（总 token ÷ 通过题数），不只比单价；同时报现金与 token（代金券抵扣 ≠ 零成本）。
- 缓存读取/创建按 [record-schema.md](record-schema.md) 的 `cache_usage` 规则；价格用 `studies/prices/*` 快照并记录采价时间。
- 记录 `provider`（workbuddy 等）与计价源；不同 provider 的同一模型不当作同一成本。

## 7. 对比矩阵（模型 × harness × 题集）

**全因子目标**：2 模型 × 3 harness × 40 题 × 2 重复 = **480 trial**。

分阶段降本：

| 阶段 | 规模 | 目的 |
|---|---|---|
| **A pilot** | 2 模型 × 1 harness（SAYACODE）× 5–10 题 × 1 重复 = 10–20 trial | 验证链路、路由固定、成本量级 |
| **B 全矩阵** | 2 模型 × 3 harness × 40 题 × 2 重复 = 480 trial | 正式开发期矩阵 |
| **C 扩样（可选）** | 100 题 × 2 模型 × 3 harness | 显著性检验所需 |

矩阵填法（每格）：

| | SAYACODE | mini-swe | Codex |
|---|---|---|---|
| **hy3** | planned% + CI + 缺失 | 同 | 同 |
| **deepseek-v4.1-flash** | planned% + CI + 缺失 | 同 | 同 |

- 每格给 `planned / observed / task_macro` 三口径 + 缺失数；**空缺格写 `not_run`，不填 0**。
- 不得用 pilot 的少数题结果替代全矩阵结论。

## 8. 样本量要求

- 40 题 × 2 重复的 CI 半宽约 **±11–15pp**（[FORMAL-RESULTS §五.6](FORMAL-RESULTS-20261102-v2.md)），只能检出 >15pp 差异。
- **多模型放大假设数**：2 模型 × 3 harness = 6 格，两两比较 15 对；Bonferroni α = 0.05/15 ≈ 0.0033，比现在的 α/3 = 0.0167 严格得多，40 题远远不够。
- **结论**：
  - 2 模型 × 3 harness 若做显著性检验，需 **≥100 题**（CI 收窄到约 ±9pp）；
  - 不足 100 题时，矩阵只作**描述性**报告，不下「某模型更强」结论；
  - 若只回答「固定 harness 换模型」一个问题（2 模型 × 1 harness × 2 重复，2 对比较，α/2 = 0.025），40 题仍只能检出大效应，需在报告中声明。
- 扩样：从 519 可评测题按仓库分层抽 100 题，seed 与排除规则预注册。

## 9. 执行顺序与风险

1. 固定路由探测（`workbuddy/deepseek-v4.1-flash` served 稳定）→ 记录探测结果。
2. 阶段 A pilot，确认链路/成本/上下文预算。
3. 阶段 B 全矩阵：stage1 与 verify **串行**，并发 ≤6，跑前 `docker network prune -f`，按 [LESSONS §五 checklist](LESSONS-20261102-v2.md)。
4. 按 [PROTOCOL-V2 §7](PROTOCOL-V2.md) 冻结签收，按 `docs/REPORT-TEMPLATE.md` 出报告。

**风险**：

- 额度/成本：两模型 480 trial 的 token 与现金需先估算并设止损。
- 路由漂移：deepseek 别名历史 40% 漂 glm，必须 pin + 探测。
- 上下文/输出预算不一致：必须逐项登记，不得静默。
- 协议差异：deepseek 走 chat/messages 的行为与 hy3 可能不同，记录不归因。
- timeout 行为差异：不同模型的轮询/收尾行为不同，timeout 归行为类，不补跑。

## 10. 与报告模板协调

- 矩阵版式、字段与图由 `docs/REPORT-TEMPLATE.md` 统一定义（另一队友维护），本文件**只定义设计原则与口径**，不重复模板内容。
- 报告须同时给出：模型身份（含 served）、harness 版本、上下文/输出预算、题集与 seed、缺失分类、worst/best、成本。
