# 私有 GitHub 托管 Linux 两题校准

本路径用于确认真实生产 Agent 在托管 Linux 上能否稳定完成接口调用、工具执行、补丁捕获、独立重判与用量记录。它不产生正式 benchmark 比较结论，也不减少原定 48 次开发和最多 96 次最终试验。

## 当前状态与未执行事项

- 公开仓库提供 `scripts/calibrate_cloud.py`、离线测试及工作流模板。
- 主任务已建立私有执行仓库 `saya-ch/sayacode-bench-runs`，原始 requirements 已单独保留。
- 用户已授权密钥托管于指定私有仓库、以新起点计算后续 100 元、早期探针费用单列未知，并仅使用免费 Actions。授权不扩大为完整正式研究。
- 首轮私有工作流在工件 preflight 阶段失败，两个模型 job 被跳过，模型调用为零。原始日志和 artifact 已私有保存，见 [首轮最小失败事实](../reports/cloud-calibration-preflight-failure-20261022-v1.json)。
- 精确代码提交 `fa9d9894ad7fe0ae690145b887c8a657b76432a1` 已完成 Windows 实际无密钥预检，源码重建 wheel 与原始基线逐字节一致；本地 565 通过、3 项平台跳过，四环境 CI 通过。这不是云端 Linux 模型运行证据，最小记录见 [准备工件](../reports/cloud-calibration-preparation-20261022-v1.json)。
- GitHub API 凭据不能读取账户私有 Actions 余量；准备记录保留当时的未知状态。随后已通过本机登录页面只读核查实际免费额度与现有支出控制，并获得仅使用免费 Actions 的授权；账户财务详情仅留仓库外，未修改设置，不能将免费计划说明当作实际余量。
- 首轮云端生成 wheel 未被保存于原 artifact；不能宣称已经直接比较该云端 wheel。本机纯 Linux 复现发现同源码 wheel 与原件的 90 个条目内容、顺序及属性相同，字节差异仅为 ZIP `create_system`。下一 cohort 将保存本次云端的真实重建 wheel 和完整诊断，再依据实际证据决定放行。

相关协议见 [研究协议](protocol.md)、[Linux 执行说明](linux-execution.md) 和 [生产基线重建](../reproduction/README.md)。

## 两个仓库各自保存什么

| 位置 | 内容 |
| --- | --- |
| 公开评测仓库 | 校准脚本、测试、官方源 revision、固定题目、精确生产源码归档、实现与价格快照 |
| 私有执行仓库 | 工作流、原始 wheel／requirements、历史费用账本及人工预算范围声明 |
| 私有 Actions artifact | 全部原生 job、对话轨迹、事件、补丁、验证器日志、runtime、用量和清理证据 |
| runner 临时私有目录 | 本次独占连接目录；不属于上传前缀，结束时删除原 profile 及受限网络的网关副本 |

公开仓库中的 `.github/workflows/cloud-calibration.yml` 是复制模板。它只接受手动触发，执行前和上传前均用 GitHub API 检查实时仓库身份，要求名称正确且 `private=true`、`visibility=private`。公开或身份不明的仓库失败关闭，没有继续开关。

工作流先检出私有仓库到 `execution/`，再将公开仓库的完整小写 40 位提交 SHA 检出到 `bench/`。分支名和 tag 不接受。公开入口还检查实际 HEAD、工作区差异及提交中的脚本 blob；实现、脚本和私有工作流身份分别保存。所有外部 Actions 固定为实际 commit SHA，checkout 不保留 Git 凭据。

## 私有输入文件

```text
artifacts/
  product-baseline.whl
  product-baseline-requirements.txt
  prior-paid-records.jsonl
  prior-paid-records.receipt.json
```

原始 requirements 必须保持字节不变，Git 属性使用 `-text`。预期 SHA256：

```text
9eab06fb395d7b9bb84e14bfea83b79b4ab66d904c941c3b1606d39ed9712073
```

运行时显式指定私有仓库提供的原始 `product-baseline.whl`，严格核对冻结 SHA：

```text
7892afcd50bd0ee786ed3ea5ba73015af32da11cd3eeff5474ce7e64d039dffe
```

原件字节不同会停止，不以同版本号替代身份。输入名 `product-baseline.whl` 不是 pip 的规范 wheel 名，脚本仅将原件保字节复制为独占工件目录中的 `sayacode-3.2.4-py3-none-any.whl`，实际 Agent 始终安装该 SHA 的原件。

### 无模型重建诊断

所有 workflow 入口均显式传入 `--wheel execution/artifacts/product-baseline.whl`。脚本同时从固定公开源码归档重建诊断 wheel，宿主 CPython 固定为 3.13.12，uv 为 0.12.5，构建后端由归档固定；任务镜像与其验证器依赖不变，source worker 的 Python 3.13.7 也不变。

`scripts/diagnose_wheel.py` 比较原件与实际重建件，记录条目数、名称与顺序、每个成员的内容及 ZIP 属性，并核验完整归档的差异字节位置。只有完全相同，或内容等全部相同且归档差异只在中央目录的 `create_system` 时才能继续。不能因为解压后源码相同就忽略其他压缩、时间、权限或附加数据差异。

实际重建 wheel 与 `rebuild-diagnostic.json` 均归档到私有 evidence 的 `rebuild/`，包括已拒绝的差异，不修正或重新打包这些字节。诊断件不被 Agent 安装，预期原件 SHA 也不改变。没有显式 `--wheel` 的旧 `dry` 方式仅保留严格逐字节重建检查；`controls/run` 必须显式提供原件，不自动回退。

已知工件失败通过安全的 `stage / reason` 枚举定位，例如 `artifact_preflight / original_wheel_hash_mismatch` 或 `wheel_rebuild_difference_rejected`；不会将任意模型异常或 HTTP 正文写入控制台。首轮失败目录保留；修复使用新源码 SHA 和新 cohort，不覆盖旧记录。

结果目录、公开源码、源缓存、生产工件和私有 profile 目录相互分离，requirements 不重新导出替代原件。

### 历史费用的已知缺口

2026-10-22 04:12 UTC 的远端 Chat 探针保留了输入 35／输出 11 tokens；04:16 UTC 的远端 Messages 工具往返探针没有保留用量。这些事实早于预算确认，但不自动意味着它们被排除于 100 元授权范围。模型调用已成功也不能推出费用为零。

最初未知状态未被补造成零。后续依据用户明确的新预算起点授权，新范围可采用空账本，早期 Messages 用量仍单列未知，不补造 token 或费用。

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

这是最初阻断状态的结构示例，不是可派发模型的结算文件。支持两种可审阅处理：

1. `all_known_paid_activity`：将两次观察都纳入账本，每个 `historical_observation_id` 唯一、连接确为 `remote`，用量完整。任一未知仍停止。
2. 用户明确授权新的预算起点后，使用 `new_user_authorized_budget`，保存非空 `budget_start` 和 `authorization_reference`；早期两次观察标为 `prebudget_cost_unknown` 并继续单列未知费用。这种明确授权后的新范围可以使用空的新账本。

不能仅将已有行写成 `local`、只纳入有完整用量的一次探针、改动 SHA 或切换 scope 来自行消除缺口。

## 无需密钥预检

将模板放入私有执行仓库后，指定已审阅的公开完整 SHA：

- `acknowledge_actions_billing=false`：默认不执行 job，避免把 API 预算误作私有 Actions 费用授权。
- 用户确认 Actions 额度／费用后，可以设置为 true。
- `execute_models=false`：默认仅重建生产工件，生成 `preflight.json`；没有密钥、Docker 或模型调用。

该预检会安装锁定依赖、访问构建依赖源并写入独占临时目录，不是完全只读的文件系统操作。账本或声明缺失时，工件检查可以通过，但 `model_dispatch_ready=false`，明确记录 blocker；模型 job 不会启动。

模型密钥只使用已授权私有仓库／环境 Secret `SILICONFLOW_API_KEY`。密钥不是 workflow input，不出现在命令行、公开清单或 artifact 上传前缀。控制台不打印模型异常正文。完整正式研究仍需另外确认执行范围，不能由两题授权自动扩展。

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

私有标准 Linux runner 规格和免费分钟受计划及实际剩余额度约束。新用户用量 API 为 `GET /users/{username}/settings/billing/usage`，汇总 API `/usage/summary` 仍为 public preview，需要用户级 `Plan: read`。普通 workflow 的 `GITHUB_TOKEN` 不提供该权限；初次 API 查询失败不能解释为免费余额充足，后来本机界面核查单独留证。计费读取凭据无需交给模型 runner。

参考：[GitHub runner 规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[Actions 限制](https://docs.github.com/en/actions/reference/limits)、[Billing usage API](https://docs.github.com/en/rest/billing/usage?apiVersion=2026-03-10)。

原始 artifact 仅上传私有仓库，默认保留三天，应及时下载并核验。完整两题校准之后，再按实际成本和稳定性决定正式执行路由；它不会自动启动完整研究。正式 48 dev／96 holdout 的分片与汇总仍需独立实现、验证和冻结，本次没有扩大执行器或改变预注册样本数。
