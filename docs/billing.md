# 费用观测与预算停止

本研究区分供应商账单、已报告用量的标价估算，以及未被观察到的费用。`budget.py` 只对第二项计算，并在任务边界决定是否继续派发。它不建设账本服务，也不承诺严格人民币上限。

## 固定价格与证据

首轮使用[2026-10-22 价格快照](../studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json)。快照记录官方来源、抓取时间与 HTML 内容哈希，不把整页 HTML、凭据或账户余额提交进仓库。

硅基流动 `deepseek-ai/DeepSeek-V4.1-Flash` 当日标价，单位均为人民币／百万 tokens：

| 官网显示时段 | 普通输入 | 输出 | 缓存命中输入 |
|---|---:|---:|---:|
| 0点～2点／8点～24点 | 2 | 8 | 0.04 |
| 2点～8点 | 1 | 4 | 0.02 |

价格行没有单独标明时区。北京时间来自中国站与该平台旧 Flash 公告惯例的推断；本轮估价全天采用较高一档，不依赖该推断，也不计缓存优惠。官网未单列本模型的缓存写入价格。[官方价格页](https://www.siliconflow.cn/pricing)

官方还声明 2026-10-21 起，相同模型 ID 已提供 `DeepSeek-V4.1-Flash-1017`。记录固定 ID 不能证明服务版本永久不变，应保留提供方声明与运行日期。[官方更新公告](https://api-docs.siliconflow.cn/docs/release-notes/overview)

## 估价接口

```python
from sayacode_bench.budget import estimate_paid_usage, budget_reason

estimate = estimate_paid_usage(
    records,
    paid_endpoints=("remote",),
    input_cny_per_million=2,
    output_cny_per_million=8,
)
reason = budget_reason(
    records,
    prior_records,
    limit_cny=100,
    stop_fraction=0.8,
)
```

默认公式：

```text
已知标价估算 = (已报告付费输入 tokens × 2 + 已报告付费输出 tokens × 8) / 1,000,000
```

金额在内部使用 `Decimal` 比较，避免浮点舍入使临界值判断漂移；导出的数值仍是可序列化的普通 JSON。忽略缓存折扣对已知用量是一种保守标价估算；存在未知用量时，它不是总费用上界。

完整用量需要 `usage_complete=true`、输入输出 tokens，以及 `usage.model_calls/reported_calls/missing_usage_calls/damaged_audit_lines` 四项审计计数共同支持。计数缺失、损坏或覆盖不齐时，即使历史记录带了完整标记也会停止；未知计数不补成零。

| 输出字段 | 含义 |
|---|---|
| `known_estimate_cny` | 已报告付费 tokens 的已知标价估算；部分用量缺失时保留已知贡献 |
| `usage_complete` | 声明为付费连接的记录是否都具有完整用量；不代表供应商账单已核对 |
| `incomplete_paid_records` | 用量不完整的付费试验记录数 |
| `missing_usage_calls` | 已知缺失调用数；无法知道缺多少时为 null，不虚构为 1 或 0 |
| `paid_model_calls` | 回调层已观测调用数；不能当成底层 HTTP 请求数 |
| `unpriced_endpoints` | 没有在本轮按次标价的连接，例如本地套餐反代 |
| `local_cost_cny`、`total_bill_cny` | 始终为 null；本模块没有账户账单与套餐分摊证据 |

没有记录时，`known_estimate_cny=0` 表示尚无已观测消耗。它不表示账户账单为零。只有本地记录时，本地成本仍为未知；不会把本地反代视为免费，也不会因本地未计价而伪造付费连接用量缺失。

## 原始与重判记录去重

每次原始执行必须含 `source_job`、`job_dir` 或 `request_sha256` 中至少一个身份字段。源 job、原始 job 路径和请求哈希作为同一次执行的别名处理：

- 原始试验和继承源用量的 pristine 重判记录只计一次。
- Windows 路径的斜杠与大小写写法会规范化；不访问路径上的文件或解析文件系统链接。
- 同身份的端点、用量、完整性、调用计数或任务配置事实不一致，直接拒绝，不选择较小金额。
- 同一路径对应不同请求哈希也拒绝。
- 判分结果、重判状态、原始／重判耗时的变化不增加模型费用。
- 若两个已独立计量的身份被一条记录桥接，拒绝含混合并。

这里统计的是原始模型试验及继承其用量的重判结果。验证器独立 job 的执行时间、容器资源费用不冒充模型 tokens；未带源身份与源用量的验证器原始记录不能当作计费凭据混入。

## 跨阶段停止规则

上层控制器固定价格快照、`prior_records` 文件内容哈希与实验输入身份，将开发、验收和终端专题的历史记录与当前记录一同传入。

CLI 冻结示例：

```powershell
sayacode-bench freeze --phase dev `
  --selection selection.json --sanity sanity.json --network-probe network-probe.json `
  --seed study-v1 --repeats 2 --reported-token-limit 20000000 `
  --variant baseline=baseline.json --variant candidate=candidate.json `
  --connection remote=private-remote.json --wheel product.whl --requirements requirements.txt `
  --paid-limit-cny 100 --paid-stop-fraction 0.8 `
  --paid-price-snapshot studies/prices/siliconflow-deepseek-v4.1-flash-20261022.json `
  --prior-records earlier-dev/records.jsonl --prior-records earlier-holdout/records.jsonl `
  --output frozen-study.json
```

示例金额用于说明参数，不代表本项目替用户授权预算。`--prior-records` 可以重复，必须包括需要累计的全部先前阶段；首次阶段没有历史时不传。可以用 `--paid-endpoint` 明确声明其他付费连接别名，默认读取价格快照中的 `remote`。历史文件只冻结路径与 SHA256，内容用于估价但不会复制进公开清单。

冻结清单的 `paid_budget` 包含金额、停止比例、最高分档费率、付费连接别名、价格快照身份和所有历史记录身份。`run` 只接受清单，没有临时修改预算的参数；变更需要新冻结清单与新结果目录。未声明 `--paid-limit-cny` 时不会生成该字段，已有无人民币门禁的校准流程保持原行为。

运行前和每次派发边界都会校验价格／历史文件哈希；历史文件变化会以 `paid_budget_evidence_changed` 停止，不能把新内容偷偷加入旧实验。当前阶段的活动 `records.jsonl` 不能同时充当自己的冻结历史输入。

1. 付费记录用量不完整：返回 `paid_usage_incomplete`，立即停止新付费任务派发。
2. 完整已知估算达到或超过 `limit_cny × stop_fraction`：返回 `paid_estimate_stop_fraction_reached`。
3. 其余情况返回 null。

默认停止比例为 80%。20% 预留只是操作余量，不能证明在途任务、重试或长输出一定落在余量内。`limit_cny=0` 会在尚无用量时阻止新付费任务；负金额、无效比例和异常 token 值会被拒绝。

控制器在派发前检查累计估算，在每次逻辑试验完成后更新 `budget.json` 与 `summary.json` 的 `paid_budget`。SWE 的官方 pristine 重判不调用模型，仍为已发生消耗的当前试验完成验收；继承源用量的重判结果不会再计费。触发停止时保留原始记录和剩余任务，`abort.json` 保存原因。最后一条计划试验恰好达到阈值时，没有后续任务需要中止，汇总仍显示停止条件已达到。

`report` 命令与运行期复用费用汇总逻辑。文件缺失、冲突或证据改变时不补造金额，报告 `evidence_valid=false`，同时取消比较、单配置验证和最终结果的正式资格；本地连接仍显示未知成本。上述检查只控制冻结研究的新派发，不创建新的账户服务或修改私有连接文件。

运行目录中的汇总是本地工作材料，仍保留 `price_snapshot.path` 和 `prior_records.path` 这些本机路径。它不含私有连接正文，但不能因此直接当作公开产物；发布流程应保留来源哈希并剥离本机路径，再进行独立脱敏检查。

这个接口不改变生产 Agent 的工具调用或模型轮次限制，不取消已在途的请求，也不因单题消耗大而改写官方任务预算。正式批次未完成时必须报告中止和剩余任务，不把预算停止包装成完整实验。

## 当前无法自动观测的部分

官方公告说明 `/user/info` 于 2026-08-14 停用。当前公开 API 导航和文档没有找到其替代余额／账单接口；不依赖仍可被搜索到的旧页面，也不猜测私有账户端点。[停用公告](https://api-docs.siliconflow.cn/docs/release-notes/overview)

Messages 文档提供 `usage.input_tokens`、`output_tokens` 和 `x-siliconcloud-trace-id`，没有承诺每请求人民币金额。其 `max_tokens` 描述还明确不含思考过程，不能简单用该参数乘输出单价证明单请求费用上限。[Messages 文档](https://docs.siliconflow.cn/docs/api/messages-post)

SDK 重试、连接中断、失败调用、流未完整接收、在途请求、优惠和代金券均可能造成标价估计与账单差异。因此，严格人民币额度需要经过验证的供应商端预算／预付费机制，或在运行阶段进行人工账单核对。本地估算阈值本身无法提供该保证。
