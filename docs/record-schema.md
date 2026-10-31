# 官方试验记录与恢复

`execution.run_official_trial` 使用 Harbor 0.24 的 `Job.create` 和 `Job.run`。每个任务、配置与重复编号使用独立 job，固定 `n_concurrent_trials=1`、`n_attempts=1`、`retry.max_retries=0`；不在本模块实现 Agent 循环、工具执行或评分器。

函数读取返回对象的 `trial_results`，不把 Harbor 磁盘上的精简 job 汇总误认为完整逐次结果。正式结果保存在 `<output>/<job_name>/normalized.json`。

## 执行和验收分别记录

- `status`：worker／官方执行终态；模型失败、超时、取消和环境失败不会被官方 reward 覆盖。
- `original_reward`：原环境官方 `reward`，仅在明确为 0 或 1 时可转换为布尔判分。
- `success`：适用协议下的端到端成功，未知为 null。
- `verified`：外部判分证据是否核实。SWE 使用 `require_replay=true` 时，原环境有 reward 仍不能当最终验收。
- `canonical_model`：统一规范模型 `DeepSeek-V4.1-Flash`。
- `endpoint`：`local`／`remote` 等非秘密连接别名；不写密钥或带凭据 URL。
- `raw_trial_result`、`raw_job_result`、`worker_result`：原始证据路径与 SHA256，不复制异常正文到汇总。
- `input_tokens/output_tokens/usage_complete`：报告用量及完整性；未知保持 null，费用不推测。

执行确实失败仍计入端到端分母。运行完成但缺 verifier reward、worker 证据损坏或独立重判未确认时，保持未知。原始 Harbor 日志可能包含第三方输出，分享前仍须独立脱敏。

## 私有完整工具输出

主线程与子线程的超限文件结果、Shell stdout／stderr 等共用产品状态下的 `outputs/`。从新增导出功能的实现版本起，正常收尾与停止确认后均保存普通文件到 trial 的私有 `sayacode/outputs/`，`outputs-manifest.json` 记录实际复制字节、SHA、跳过项与错误，覆盖记录标明采集阶段。导出不读取链接目标，不复制 Store 或模型配置，也不进入公开 artifact 白名单。

工具输出复制完整只证明保存了当时可读的文件，不表示生成它的工具执行成功。导出失败单独留证，不能改写原始 reward。图检查点只在应用正常关闭后导出；强制 kill 后不补采 SQLite，也不声称保存了全部在途状态。旧校准没有这些新增文件时不补造，原生消息预览与审计仍按原记录保留。

## SWE 独立重判

`replay_official_trial` 动态加载固定上游目录的 `patch_replay:PatchReplayAgent`，创建新 Harbor job 与新环境。它要求源 job 恰好一个 `instance_*` trial，避免上游按任务名寻找首个补丁时串用其他重复的交付。

重判记录包含：

- `source_job` 与源 `agent/model.patch` 的路径、SHA256。
- `official_tooling_sha256`、`replay_job_dir` 和重判原始结果身份。
- `apply_rc`、`replay_reward`、`replay_status`。
- 原始试验耗时与重判耗时分别保存；`duration_seconds` 保持原始试验耗时。

缺补丁、缺应用确认、应用失败或重判错误不能伪造 `verified=true`。存在但为零字节的补丁是有效的无修改交付，仍启动官方补丁重放与 pristine verifier；上游的 `patch=null` 证据表示无需应用，最终成功与否使用实际重判 reward，不根据空补丁猜分。补丁应用非零明确记录交付失败；证据不足保留未知。源补丁在重判期间变化则拒绝把重判当有效证据。

固定上游 `patch_replay.py` 依次尝试 `git apply`、`git apply --3way` 和 `patch --fuzz=3`。当前沿用该公开协议，并保存最终 `apply_rc`，未独立标注成功落在哪个分支。因此，“全新环境重判”不等于“只允许严格无模糊应用”，源补丁 SHA 不变也不单独证明最终文件树逐字相同；最终行为结论来自全新环境中的官方 verifier。

## 恢复与副作用

每个 job 保存 `request_sha256`，覆盖任务文件、官方配置、元数据与相关输入工件。已有完整记录且身份一致时直接返回，不重新调用模型。输入变化、只有未收尾目录或记录未完成时拒绝自动重跑；必须由控制器保留现场并显式作出恢复决定。

`paired_order(manifest)` 用固定 seed 随机块顺序和块内配置顺序，同一 `task × repeat` 连续执行。`remaining_order(manifest, records)` 只跳过明确 `record_complete=true` 的既有记录，包括失败和已完成但未判的记录，不因分数低而重跑。统计上的完整验收还需要所有成功／失败已知，不能仅靠 `record_complete` 判断。

本模块不决定批次停止阈值、切换连接或补跑规则；这些由冻结 manifest 与上层控制器统一管理。

## 原生调用、重试与计量边界

`usage.model_calls` 是 LangChain callback 观察到的模型调用数，汇总主线程、子线程和父线程后续唤醒；按原生 run ID 去重。它不是 HTTP 请求数。`reported_calls`、`missing_usage_calls` 和 `damaged_audit_lines` 分别记录有完整用量的回调、用量缺失和损坏审计行。中断前已报告的 tokens 仍保留，未知费用保持 null。

### 原生缓存旁证

`agent/sayacode/usage-details.json` 使用 `langchain_callback_usage_v1` 采集器。它通过 LangChain 官方可继承的 callback context hook 观察生产模型，与原产品审计并存，不读取 checkpoint 补造当前调用统计，也不改写产品图。逐次 run ID、线程、结束状态、原生总量和缓存数字仅留在私有原件。

规范化记录新增 `usage_details` 文件路径／SHA 与 `cache_usage` 汇总。宿主、分片恢复和费用发布都会重读旁证，并核对审计 SHA、逐次身份、调用覆盖与输入／输出／总量；不能只信汇总中的 `complete`。缺文件或原生字段时为 `unavailable`，冲突或非法计数时为 `invalid`。原始 `usage` 三项总数保持原义，不因缺缓存数字而补零或覆盖旧记录。

Anthropic 原生输入不包含缓存读取／创建，LangChain 归一化总输入已包含它们。预算只从总输入中减去已确认的缓存读取，不能再把缓存叠加到总量。缓存创建包含普通及 TTL 字段；无已核单价的正创建量阻止新付费派发。失败请求没有 usage 时仍未知，callback 次数也不等于 SDK 内部 HTTP 尝试次数。[计价规则](archive/billing.md)

公开记录只导出白名单缓存摘要与文件哈希，不导出旁证路径、逐次调用、COT 或 checkpoint。费用与正式资格先在原件上复核，再脱敏；不能因发布层丢掉文件路径而重新计算出另一份成本。

本次 Messages 接入由生产 `init_chat_model` 构造官方 `ChatAnthropic`，未另外实现接入协议。Profile 的 `model_retries` 只设置官方 `ModelRetryMiddleware`；固定 `langchain-anthropic==1.7.2` 中，模型客户端另有默认 `max_retries=2`。因此，配置 `model_retries=1` 时，部分可重试故障理论上可形成两次中间件调用、每次最多三次 SDK HTTP 尝试，合计最多六次。并非每类错误都会重试，反代内部行为也不包含在此上界内。当前没有精确 HTTP 请求计数或完整计费账本，不能据此声称“只请求了 N 次 API”或“重试完全关闭”。

批次 `reported_token_limit` 只在派发下一个完整任务之前检查已经报告的 tokens。一个正在运行的任务可以超过该阈值，缺失用量也未被补造，所以它不是单任务硬上限或完整费用上限。任务时间上限仍由官方 Harbor 任务配置控制。

`task_count` 从本次全新原生任务 Store 查询已创建的子任务，包含失败和停止的任务，取消路径同样收集；无法读取时为 null 并记录 `task_metadata_error`。当前子 Agent 不再向下派发团队任务，因此该计数覆盖本产品本次任务族，不能把模型调用数当成 Agent 数。`unapplied_deliveries` 表示未标记应用的 builder worktree 数，不证明每个 worktree 都有非空修改。

## 实际镜像与资源证据

从新增资源记录的实验版本开始，本地环境在主容器启动后直接写入 host trial 根目录的 `runtime.json`，与 `network-isolation.json` 并列。参考解、空解、补丁重放与真实模型均使用同一观察点，不依赖 Agent 日志同步。它只选择 Docker 容器／镜像的公开身份和资源字段，不复制 `Config.Env` 或凭据。记录包含任务声明、实际 image ID、RepoDigests、架构、工作目录、HostConfig CPU／memory／swap／storage 参数，以及可读取的 cgroup v2 值。查询失败明确写 `available=false`，不能据此声明资源限制已经核实。旧实验不会回填或覆盖。

本地 Harbor Docker 0.24 实际支持 CPU 和内存限制。校准中已观察到 `NanoCpus=1000000000`、`cpu.max=100000 100000` 和 `memory.max=4294967296`，即主任务容器 1 CPU、4 GiB RAM 的限制生效。但该容器同时允许额外 4 GiB swap：`MemorySwap=8589934592` 为 RAM 加 swap 合计 8 GiB，`memory.swap.max=4294967296`。不能将此说成与无 swap 的 4 GiB 云环境完全等价。

官方任务的 `storage_mb=10240` 仍记录在声明中，但本地 Docker 后端没有实现对应磁盘硬配额，实际 `StorageOpt` 为空。因此，10 GiB 只表示官方任务要求，不能声称已经限制。资源记录明确标注 `storage_hard_limit_supported=false`。模型网关另有独立的 0.25 CPU／128 MiB 限制，不包含在主任务容器的上述限额内。

任务配置保留上游镜像 tag；`runtime.json` 记录实际 image ID／RepoDigest。云端资格第一次解析 tag 后保存唯一 RepoDigest，续批及正式 runner 按该 digest 拉取并核 image ID、平台，不修改官方任务文件。SWE source／pristine 的实际资源仍分别核对。历史单阶段入口没有这套云端准备合同，不能因 tag 名相同就宣称跨机器没有漂移。

云端 sanity 还携带 `qualification_host_cohort` 与 `qualification_host_scope`。后者记录公开仓库、固定源码、cloud-plan SHA 和宿主证据边界。CLI 冻结保留这些字段，分片冻结、恢复和生成器均核对正式 runner 的 `ImageOS / ImageVersion / RUNNER_ARCH`；已知云端 bundle 或已声明的云端字段缺损、漂移时，不能悄悄当作非云流程忽略。没有云端来源字段的既有非云记录不补造宿主信息。公开与私有宿主的总 CPU／内存不同，也不保证同一实体 CPU 或内核，官方容器限额照常核验。[执行合同](archive/sharded-execution.md)

本地网络实现、磁盘配额、swap 和网关开销均与官方云环境存在边界，不宣称官方完整榜单的严格环境等价。
