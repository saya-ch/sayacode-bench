# 私有 GitHub 托管 Linux 两题校准

本路径用于确认真实生产 Agent 在托管 Linux 上能否稳定完成接口调用、工具执行、补丁捕获、独立重判与用量记录。它不产生正式 benchmark 比较结论，也不减少原定 48 次开发和最多 96 次最终试验。

## 当前状态与未执行事项

- 公开仓库提供 `scripts/calibrate_cloud.py`、离线测试及工作流模板。
- 主任务已建立私有执行仓库 `saya-ch/sayacode-bench-runs`，原始 requirements 已单独保留。
- 新模板尚未触发；没有通过本工作流调用模型或上传模型密钥。
- 精确代码提交 `fa9d9894ad7fe0ae690145b887c8a657b76432a1` 已完成 Windows 实际无密钥预检，源码重建 wheel 与原始基线逐字节一致；本地 565 通过、3 项平台跳过，四环境 CI 通过。这不是云端 Linux 模型运行证据，最小记录见 [准备工件](../reports/cloud-calibration-preparation-20261022-v1.json)。
- GitHub 当前登录凭据不能确认账户私有 Actions 余额；不能据免费计划说明推断本账户尚有免费分钟。
- 既有远端探针包含未保存的用量，历史预算范围尚未确认。因此当前必须保持模型派发阻断；无需密钥的工件预检仍可独立完成。

相关协议见 [研究协议](protocol.md)、[Linux 执行说明](linux-execution.md) 和 [生产基线重建](../reproduction/README.md)。

## 两个仓库各自保存什么

| 位置 | 内容 |
| --- | --- |
| 公开评测仓库 | 校准脚本、测试、官方源 revision、固定题目、精确生产源码归档、实现与价格快照 |
| 私有执行仓库 | 工作流、原始 requirements、历史费用账本及人工预算范围声明 |
| 私有 Actions artifact | 全部原生 job、对话轨迹、事件、补丁、验证器日志、runtime、用量和清理证据 |
| runner 临时私有目录 | 本次独占连接目录；不属于上传前缀，结束时删除原 profile 及受限网络的网关副本 |

公开仓库中的 `.github/workflows/cloud-calibration.yml` 是复制模板。它只接受手动触发，执行前和上传前均用 GitHub API 检查实时仓库身份，要求名称正确且 `private=true`、`visibility=private`。公开或身份不明的仓库失败关闭，没有继续开关。

工作流先检出私有仓库到 `execution/`，再将公开仓库的完整小写 40 位提交 SHA 检出到 `bench/`。分支名和 tag 不接受。公开入口还检查实际 HEAD、工作区差异及提交中的脚本 blob；实现、脚本和私有工作流身份分别保存。所有外部 Actions 固定为实际 commit SHA，checkout 不保留 Git 凭据。

## 私有输入文件

```text
artifacts/
  product-baseline-requirements.txt
  prior-paid-records.jsonl
  prior-paid-records.receipt.json
```

原始 requirements 必须保持字节不变，Git 属性使用 `-text`。预期 SHA256：

```text
9eab06fb395d7b9bb84e14bfea83b79b4ab66d904c941c3b1606d39ed9712073
```

脚本校验公开生产源码归档，使用固定 uv 重建 wheel，再严格核对原 wheel SHA：

```text
7892afcd50bd0ee786ed3ea5ba73015af32da11cd3eeff5474ce7e64d039dffe
```

不同字节会停止，不以同版本号替代身份，也不重新导出 requirements 冒充原文件。结果目录、公开源码、源缓存、生产工件和私有 profile 目录相互分离。

### 历史费用的已知缺口

2026-10-22 04:12 UTC 的远端 Chat 探针保留了输入 35／输出 11 tokens；04:16 UTC 的远端 Messages 工具往返探针没有保留用量。这些事实早于预算确认，但不自动意味着它们被排除于 100 元授权范围。模型调用已成功也不能推出费用为零。

现阶段不创建空账本，不补造 Messages 用量，不生成 `coverage_confirmed=true` 声明。

`prior-paid-records.receipt.json` 是人工核实的预算范围声明，**不是供应商账单证明**。它必须绑定实际账本 SHA，并列明这两个已知观察：

```json
{
  "records_sha256": "<实际账本 SHA256>",
  "coverage_confirmed": false,
  "budget_scope": "unconfirmed",
  "authorization_reference": "",
  "unresolved_in_scope_observations": [
    "remote-chat-20261022T0412Z",
    "remote-messages-20261022T0416Z"
  ],
  "historical_observations": [
    {"id": "remote-chat-20261022T0412Z", "disposition": "unconfirmed"},
    {"id": "remote-messages-20261022T0416Z", "disposition": "unconfirmed"}
  ]
}
```

这是阻断状态的结构示例，不是可派发模型的结算文件。后续有两种可审阅处理：

1. `all_known_paid_activity`：将两次观察都纳入账本，每个 `historical_observation_id` 唯一、连接确为 `remote`，用量完整。任一未知仍停止。
2. 用户明确授权新的预算起点后，使用 `new_user_authorized_budget`，保存非空 `budget_start` 和 `authorization_reference`；早期两次观察标为 `prebudget_cost_unknown` 并继续单列未知费用。这种明确授权后的新范围可以使用空的新账本。

不能仅将已有行写成 `local`、只纳入有完整用量的一次探针、改动 SHA 或切换 scope 来自行消除缺口。

## 无需密钥预检

将模板放入私有执行仓库后，指定已审阅的公开完整 SHA：

- `acknowledge_actions_billing=false`：默认不执行 job，避免把 API 预算误作私有 Actions 费用授权。
- 用户确认 Actions 额度／费用后，可以设置为 true。
- `execute_models=false`：默认仅重建生产工件，生成 `preflight.json`；没有密钥、Docker 或模型调用。

该预检会安装锁定依赖、访问构建依赖源并写入独占临时目录，不是完全只读的文件系统操作。账本或声明缺失时，工件检查可以通过，但 `model_dispatch_ready=false`，明确记录 blocker；模型 job 不会启动。

模型密钥只使用私有仓库／环境 Secret `SILICONFLOW_API_KEY`。主任务尚未上传该 Secret，实际上传与托管 runner 使用仍需用户确认。密钥不是 workflow input，不出现在命令行、公开清单或 artifact 上传前缀。控制台不打印模型异常正文。

## 真实校准的固定顺序

在上述门禁和授权均满足后，`execute_models=true` 才允许：

1. qutebrowser job：在本次 fresh runner 执行真实网络探针与独立清理；按官方不可变镜像，固定运行三次 oracle 和一次 nop；门禁通过后只执行一次 baseline 和一次全新环境的官方 pristine replay。
2. Ansible job：只接收第一题已经确认的原始记录和 SHA，继承费用；在自己的 fresh runner 重做探针和三加一门禁，然后执行一次 baseline 和独立 replay。

题目固定来自既有 `studies/calibration.json`，不读取其他题目进行挑选。主 Agent 和子任务行为由原生产 baseline 决定，不另写 Agent 循环。`run_phase` 使用原 `run_official_trial` 和 `replay_official_trial`，原生试验一次尝试、单并发、框架重试零。

第一题 reward 为 0 时，只要执行、独立评分、用量和资源证据有效，仍继续第二题。不会换题、重跑到成功，或根据 reward 决定跳过。失败、缺失和未知记录均保留；工作流拒绝 GitHub 的自动 re-run attempt。

### 时间、资源和预算

- 每道模型题单独 job，上限 360 分钟；从最初守卫开始记录 330 分钟软截止。
- 模型开始前保留两次官方 `build + agent + verifier` 时间预算，再加 1,200 秒安装与 900 秒收尾余量。当前两题为 295 分钟，所以准备、探针与四次 control 超过可用余量时，不启动模型。
- 不缩短官方 3,000 秒 Agent／verifier 或其他官方资源参数；若无法在 6 小时内完成，明确记录未启动或未完成，不声称两题已完成。
- 每次 control 和模型派发检查至少 12 GiB 空闲；不自动 prune。私有 Ubuntu runner 的官方保证空间仅 14 GB，实际拉取镜像后仍可能触发停止。
- Oracle、source 和 replay 的实际镜像、平台、请求资源及 Docker 限制须相同；源与独立 replay 均校验，镜像 tag 相同不能代替实际身份。
- 全局 100 CNY、云端子预算 15 CNY；在 80% 估价阈值停止后续派发。第二题继承第一题与前序账本，不能各自获得新的 15／100 元。
- 费用按固定最高费率估算，不预支缓存优惠。**这些是派发止损，不是供应商人民币硬限**；在途请求、重试和缺失用量不能保证绝不超额。

源码、工件、参考解门禁、探针、用量、费用、镜像、资源或清理任一不确认，就保存原始证据并停止后续模型派发。清理观察失败时仍删除本次 profile 和网关凭据副本，保留已产生的模型记录与费用；已有私有目录不覆盖，不因记录未知而自动重放。

## GitHub 费用与后续研究

私有标准 Linux runner 规格和免费分钟受计划及实际剩余额度约束。新用户用量 API 为 `GET /users/{username}/settings/billing/usage`，汇总 API `/usage/summary` 仍为 public preview，需要用户级 `Plan: read`。普通 workflow 的 `GITHUB_TOKEN` 不提供该权限；当前查询失败不能解释为免费余额充足。计费读取凭据无需交给模型 runner。

参考：[GitHub runner 规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[Actions 限制](https://docs.github.com/en/actions/reference/limits)、[Billing usage API](https://docs.github.com/en/rest/billing/usage?apiVersion=2026-03-10)。

原始 artifact 仅上传私有仓库，默认保留三天，应及时下载并核验。完整两题校准之后，再按实际成本和稳定性决定正式执行路由；它不会自动启动完整研究。正式 48 dev／96 holdout 的分片与汇总仍需独立实现、验证和冻结，本次没有扩大执行器或改变预注册样本数。
