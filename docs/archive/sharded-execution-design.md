# 正式研究的分片执行设计

状态：**编码前的设计快照**。下文保留当时的拟议接口和验收约束；后续已经接入的代码、实际入口与证据边界见 [分片执行与恢复](sharded-execution.md) 和 [状态记录](../STATUS.md)。本文不表示正式模型试验已经开始，也不赋予额外执行权限。

设计承接 [研究协议](../protocol.md)、[固定规模](../../studies/design-20261022-v1.json)、[v6 统计与资源身份](../../studies/archive/sensitivity-protocol-v6.json) 和 [云端校准](cloud-calibration.md)。当前实现已有单次官方试验、独立 pristine replay、费用估价、资源门禁与候选签收；尚无本文描述的正式分片、全局账本和严格归并入口。

## 目标与不变条件

- 主要研究保持 8 个开发任务、3 个配置、2 次重复，共 48 次模型试验。
- 选中不同候选时，最终 24 个任务、2 个配置、2 次重复，共 96 次；保留 baseline 时，改为独立单组 validation，共 48 次，不制造自身对照。
- 模型、生产 wheel、原始依赖、候选配置、任务与修复组划分、官方资源、顺序 seed 和统计方法均由正式清单固定。
- Harbor 继续承担环境、单次执行和官方验证，SAYACODE 继续运行生产 Agent。分片层不实现另一套 Agent 循环、评分器、常驻服务或通用 worker 框架。
- 原始失败、不完整执行和消耗保留。资源不足、费用不足或环境资格不足时，研究保持未完成，不缩小计划分母。

## 一、逻辑配对块与物理 job

逻辑块固定为 `task × repeat`，包含该任务、该重复编号的全部配置。块内连接、配置顺序和预定比较关系不变。

物理 micro-shard 只执行一个配置的一次 source 与其独立 pristine replay。两者在同一物理 job 内收尾，以减少有模型 source 已完成、原始工件尚未交付的恢复窗口。

| 阶段 | 逻辑块数 | 每块配置数 | 模型 micro-shard 数 |
| --- | ---: | ---: | ---: |
| 开发 | 16 | 3 | 48 |
| 双组 holdout | 48 | 2 | 96 |
| 单组 validation | 48 | 1 | 48 |

同一逻辑块可跨 fresh runner，必须串行维持固定顺序，使用相同连接和冻结 runner cohort，逐次记录实际宿主、镜像、资源及时间间隔。正式冻结前声明允许的间隔和漂移处置规则，不能在看到成绩后决定哪些配对仍有效。

### 六小时时限

GitHub 托管 runner 的单个 job 最长运行六小时，到达限制后会被终止。[GitHub Actions 官方限制](https://docs.github.com/en/actions/reference/limits)

当前云端校准的保守单配置预留为：

```text
2 ×（官方 build timeout + agent timeout + verifier timeout）
+ 1,200 秒安装余量 + 900 秒收尾余量
= 17,700 秒，即 295 分钟
```

每个正式 shard 应按自己的官方任务配置重新计算，不能机械套用 295 分钟。一个开发逻辑块的三个配置，或 holdout 的两个配置，无法按当前官方最坏预算保证放入同一个六小时物理 job。

物理 job 启动 source 前核验实际剩余时间。准备、探针、镜像或控制阶段消耗过多时，保存明确的未启动状态。运行中异常超时则保存未完成与可能已消耗事实。不得缩短官方超时来迁就托管平台，也不得把“不保证完成”写成“已完成”。

## 二、不可变 master 与全局 schedule

正式 master manifest 保存完整阶段的任务、配置和重复次数。使用现有 `paired_order()` 一次生成全局顺序，并在首次正式模型调用前保存为不可覆盖文件。

不要为每个片重新生成只含单题、单配置或 `repeats=1` 的 phase manifest。这样会重新随机排序、重编号 repeat、改变按重复编号选择连接的结果，并破坏原定分母。

执行计划至少固定：

```text
study_id / phase / master_manifest_sha256
schedule_sha256 / source_commit / implementation_identity
runner_policy_sha256 / executor_workflow_sha256
authorization_scope_sha256 / financial_policy_sha256

blocks: block_id / task_id / repeat / endpoint / ordered_configurations
shards: shard_id / block_id / global_sequence / task_id / configuration / repeat
        official_time_reserve
```

统计 trial key 为 `master manifest 身份 + task_id + configuration + repeat`。物理执行 attempt、工作流 run 和人工基础设施复验另有身份，不能增加独立样本数。

## 三、最小实现接口

建议新增领域模块 `shards.py`；以下 API 均为拟议接口，当前不可调用。

```python
freeze_execution_plan(manifest_path, runner_policy_path, authorization_path, output_path)
run_shard(plan_path, shard_id, ledger_before_path, bindings, output)
merge_shards(plan_path, receipt_paths, output)
```

`freeze_execution_plan` 复用现有顺序函数，验证完整分片恰好覆盖所有计划 trial，没有重复或漏项，拒绝覆盖既有计划。

`run_shard` 验证计划、前序 receipt、账本与输入身份，再进入原 `run_phase`。最小执行入口扩展为：

- 受验证的全局 sequence 子集，维持原 job 编号、repeat 和连接。
- 已发生的同阶段记录，用于累计 token 与故障门禁。
- 已发生的全预算范围付费记录，用于累计费用门禁。

新入口复用原 `run_official_trial`、`replay_official_trial` 和资源校验，不复制单次执行循环。每片返回的是执行 receipt；不能以局部阶段缺失其余任务为由，伪造一个“完整的小研究”。

物理 shard 的正常收尾不以 reward 为 1 为条件。已确认的产品失败保留为 E2E `false`，继续其配对中的其他配置。服务故障、未知用量、资源冲突或清理未确认阻止后续派发。

## 四、全局费用与阶段用量不重置

金融政策不可变：预算起点、适用阶段、连接、价格快照、金额和派发停止比例正式冻结。初始记录包含同一预算范围内已经发生的校准消耗，不因进入开发或最终阶段重新发放 100 元。

每片执行 receipt 绑定：

```text
ledger_before_sha256
accepted_previous_receipt_sha256
source_record_sha256
ledger_after_sha256
```

账本逐片追加事实，使用现有 source/request 身份去重。全程单并发、唯一前序，拒绝账本分叉。不能修改 master 中已冻结的政策或初始证据 SHA 来追加费用；新增记录属于每片明确绑定的执行状态。

必须分开两份数据：

- **阶段统计记录**：本阶段计划 trial key，每个恰好一条，供分析与候选选择。
- **费用记录**：同预算范围内所有真实消耗，包括校准、失败、不完整 source 和另行标识的复验。

金额检查读取全局费用记录；阶段 token 阈值读取本阶段全部已发生记录。不能让任一阈值在每个物理 job 重置。

缺失用量不补零，失败消耗不删除。callback 已报告 token 的估价与派发止损不等于供应商账单或人民币硬封顶；在途请求和内部重试的边界继续披露。

## 五、固定 Linux bundle 与恢复

第一版采用明确的 Linux bundle 布局，避免重写现有绝对来源路径或引入通用工件注册服务：

```text
/tmp/sayacode-studies/<study_id>/
  inputs/
  state/
  shards/<shard_id>/
  merged/dev/
  merged/final/

/tmp/sayacode-private/<study_id>/
```

bundle 根路径属于该研究的输入约定。每个 runner 将前序已核验文件恢复到同一布局，逐字节确认来源。原始 JobConfig、source 路径和 request 身份保留，不通过改路径冒充同一次执行。私有 profile 目录位于归档前缀之外。

开发完整归并后，在 bundle 中调用原 `lock_candidate()`；最终冻结与执行时恢复其原始 dev manifest、records 和配置，再调用 `validate_candidate_receipt()`。阶段切换不重新选择候选，不复制聊天或 checkpoint。

已收尾成功和失败均不重跑。source 已确认完成而仅 replay 未完成时，可新增一个显式、可审阅的 verifier 恢复操作：校验唯一 source、patch、请求及原生结果身份，只执行新的 pristine verifier，保留旧未完成尝试，不再调用模型。

仍在执行、来源不确定、补丁未确认的 source 不自动恢复。服务故障后的整块复验使用新身份，原始 E2E 与稳定条件复验分表，不能用后来更高 reward 覆盖原记录。

## 六、严格归并与缺失分母

`merge_shards` 不是拼接 JSONL。归并前重验：

1. master、计划、实现、wheel、依赖、候选、授权和预算范围身份。
2. 每个 trial 是否属于原计划，sequence、repeat、配置与连接是否正确。
3. 原生 source、patch、replay、runtime 和其他引用工件是否存在且 SHA 一致。
4. 账本前序与累计关系，是否存在冲突、分叉或同一次 source 冒充两个试验。
5. 每片中止、失效、未知、服务故障、资源和清理事实是否完整继承。

同一 receipt、同一 SHA 的重复下载可以幂等接收；同一 trial key 的冲突版本必须拒绝，不能按 reward 选一份。

输出建议为：`records.jsonl`、`accounting-records.jsonl`、`merge-receipt.json`、`summary.json`、`missing.json`。首次归并和再次归并应得到相同结果。

计划但未执行的项由全局 schedule 产生 missing，不伪造失败记录。已启动且明确失败的产品试验保留在 E2E 分母。未确认评分、未知、未收尾、缺片或缺配对都阻止正式比较和候选签收，不因剩余记录已形成完整对子而减少原分母。

## 七、资格阶段允许分批，不允许挑分补跑

参考解、空解与模型阶段分开记账、归档。资格检查可按任务、甚至按单次 control 分散到物理 job，但必须保持预定的三次 oracle 与一次 nop，以及原始尝试身份和顺序。

- 单次 oracle 失败不能触发追加第四次或只重跑失败项；不能三次中挑最高分。
- 完整三加一均收尾后，才按已冻结规则判定资格；不因第一项失败擅自省略其余项。
- 预算、时间、磁盘或基础设施导致未执行，保持 incomplete，不能把未执行记成零并排除整组。
- 完整且失败的 fixture 按预注册规则排除整个 fix 组，再由原候选池、seed、过滤器和固定上限机械替补；所有失败与排除理由保留。
- 候选上限耗尽仍未满足 8／24 个任务时，保持未完成，不缩小 N。

最终报告明确适用于环境资格子集，不把过滤后的样本冒充原始全集的均匀抽样。资格成绩不得用于挑选更有利的产品配置。

## 八、继承 v6 资源与统计规则

分片和归并都必须调用 [resources.py](../../src/sayacode_bench/resources.py) 的现有规则，不另写字典相等比较：

- 请求资源须符合原官方任务声明。
- CPU 额度须由 Docker NanoCpus 或 quota/period 及 cgroup `cpu.max` 交叉确认，无限额不能算相同。
- 内存与 swap 须由 Docker 与 cgroup 交叉确认；缺证据与明确冲突分别保留为未知／失败。
- oracle、source、pristine 的镜像、平台及资源比较继续保留 `same_resources` 等明确状态；两个同样错误或无限额的环境不能算通过。
- 磁盘硬限制能力继续按实际证据披露，不能将官方请求量或空闲门槛写成硬隔离。

统计继续使用任务先对重复求均值、任务宏平均、固定 seed 的任务块主 bootstrap，以及预定仓库簇敏感性分析。重复和物理 job 数不增加独立任务数；敏感性区间不替换主结果。

v6 保存既有统计、验证、预算和资源源码身份。分片实现修改 `study` 或相关执行代码后，须在首个正式模型 trial 前另行冻结 **v7 实现身份**，保留 v6 历史记录。新身份不构成更改统计方法、样本数或按已见分数修改规则的理由。

## 九、GitHub 原生串行编排与授权

采用私有 reusable workflow 执行单片，再由冻结 schedule 机械生成显式 `needs` 串行 DAG。前序输出账本 receipt，后序验证其身份。不要仅以 matrix `max-parallel: 1` 推断科学执行顺序。

生成 DAG 时核对当时适用的平台限制；GitHub 文档中的 matrix 限制不能被当作任意固定 DAG 的总 job 硬上限。分片 job 的六小时时限仍逐项遵守，不因整个 workflow 可跨多日而失效。

原始证据只保存于已核实的私有执行仓库。每个 fresh runner 仍执行实际输入／网络检查，并在开始付费 source 前核对磁盘、时间、累计用量和免费 Actions 可用条件；不能用旧宿主探针代替当前事实。

**当前授权仅覆盖固定两题校准及其既定输入检查。** 正式 dev／holdout／validation 仍需单独确认执行 scope、路由和剩余预算；现存 Secret、新预算起点或本设计文档均不自动扩展为正式派发权限。不能假定完整研究可在剩余 100 元范围或免费分钟内完成。

## 十、正式前必须新增的验证

- 分片前后 trial key、全局顺序、repeat 和连接完全一致，48／96／48 分母不变。
- token、费用跨片累计，缺用量、最后一片服务故障及账本分叉均无法被归并消除。
- 重复 receipt 幂等；冲突、错片、复用 source、篡改工件或实现身份均拒绝。
- CPU／内存／swap、镜像或平台漂移继承 v6 门禁，不接受缺证据或同样无限额。
- source 完成、replay 前后中断的窗口不重放模型；不确定来源不能自动恢复。
- 部分归并不能锁候选或给出正式区间；完整归并与原统计函数的结果一致。
- 跨 runner 恢复后，候选、dev 来源、最终任务与修复组隔离仍可重验。
- 资格分批仍执行固定三加一，失败、未执行和机械替补的语义不变。
- 新私有 workflow 的顺序、时限、秘密隔离和失败归档经离线与无模型真实链路验证后，再冻结 v7 并申请正式 scope。

以上为实施与验收清单，尚未完成，不应写成已经可用的 CLI 或已经执行的正式研究。
