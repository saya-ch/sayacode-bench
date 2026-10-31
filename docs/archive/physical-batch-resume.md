# 同 bundle 跨阶段与显式片间恢复

正式阶段继续使用同一个固定 Linux bundle。SWE dev、holdout 和 Terminal 补充阶段的
计划、source、原生 receipt、签收收据以及金融 prior 中的绝对路径均保留。
生成器将派生归并输出写入 `merged/<完整 master SHA256>/prefix-NNNN` 和
`merged/<完整 master SHA256>/final`。因此两个阶段可以各自归并 `prefix-0001`，
后阶段也可以按原路径核验前阶段证据。改变 bundle 根目录或重写原收据路径不是迁移办法。

## 正常物理批次

`generate --through-sequence K` 只限制本次派发的连续物理片，默认终点仍是全 schedule 的 N。
该选项不改变 master、schedule、repeat、全局序号或研究分母。K 小于 N 时，DAG 在第 K 片
已有的严格 prefix merge 和完整 Release 归档后结束，不创建全阶段 final merge。
dispatch/archive receipt 中的 `physical_batch_complete` 只表示本次物理批次收尾；
研究仍缺少后续试验，不能据此锁定候选或宣称完整阶段完成。

```powershell
uv run --no-sync python -m scripts.generate_sharded_workflow generate `
  --plan C:\download\study\dev-plan.json --bundle-directory C:\download\study `
  --seed-manifest C:\download\seed-manifest.json `
  --through-sequence 2 --output C:\review\dev-batch-1.yml
```

这些命令仅生成文件，不授权正式派发。runner policy、计划中的实现身份、模板和生成器仍须
按现有冻结流程事先绑定；原有冻结文件不能原地升级到新实现。

## 不可变恢复声明

先下载并保存最后完整片的 Release manifest、Actions `archive-receipt.json` 和完整 bundle。
人工只读收集执行仓库完整 Actions runs 分页，以及每个同 master 历史 run 的全部 jobs 分页：

```bash
gh api --paginate --slurp 'repos/saya-ch/sayacode-bench-runs/actions/runs?per_page=100' > history.json
# 对每个同 master 既有 run 执行一次；文件名必须为数字 run ID。
gh api --paginate --slurp 'repos/saya-ch/sayacode-bench-runs/actions/runs/123/jobs?filter=all&per_page=100' > jobs/123.json
```

只有完整连续前缀 1..k 可以申请恢复。没有任意 `--start` 或跳过某个低分试验的入口。

```powershell
uv run --no-sync python -m scripts.generate_sharded_workflow freeze-resume `
  --plan C:\download\study\dev-plan.json --bundle-directory C:\download\study `
  --prefix-length 2 --seed-manifest C:\download\evidence-manifest.json `
  --archive-receipt C:\download\archive-receipt.json `
  --history C:\download\history.json --jobs-directory C:\download\jobs `
  --output C:\review\resume-prefix-2.json

uv run --no-sync python -m scripts.generate_sharded_workflow generate `
  --plan C:\download\study\dev-plan.json --bundle-directory C:\download\study `
  --seed-manifest C:\download\evidence-manifest.json `
  --resume-receipt C:\review\resume-prefix-2.json --through-sequence 4 `
  --output C:\review\dev-batch-2.yml
```

`freeze-resume` 拒绝覆盖已有声明。它绑定原 plan/master/schedule/implementation、冻结的
paid budget 与 initial paid records、前缀长度、末原生 receipt/ledger SHA、固定 Release
manifest 与已完成传输的 archive receipt、全部同 master 既有 run IDs 和逐片 run/job 归属。
生成 DAG 内嵌声明及其规范 JSON SHA256；生成器另绑定恢复 helper 源文件 SHA。
Windows 只能映射文件核对绑定和生成待审阅声明，`native_validation_required` 始终为 true，
生成回执的 `native_resume_validation_performed` 为 false。

真正放行发生在无模型 Secret 的 Linux `review`：重新枚举实时 runs 与 jobs，按 Release
manifest 下载完整归档，使用原 `restore_archive` 恢复到原绝对路径，然后复用
`shards._load_plan`、`_read_receipt` 和 `_stop_reason` 核验全部原件及费用。首个剩余片的
无模型 Secret 步骤再次运行同一原生前缀核验；执行仍调用既有 `verify_previous` 和 `run_shard`。
生成工作流从原序号 k+1 开始，保留全 schedule。k=N 时仅 review 与 final merge，DAG
不引用模型 Secret。GitHub token 仅用于读取仓库历史及既有 Release 传输。
若本次从 k<N 继续完成到 N，final merge 核验完整 N 的原生前缀，并沿 previous receipt 链
确认它经过原冻结 k 收据；不再要求已经完成的 k+1..N 目录为空。

## V1 的拒绝边界

- 除当前 run 外，同 master run ID 集合必须与声明完全相同；所有历史 run 都已 terminal，
  且 run attempt 必须为 1。后来新增的失败、审查被拒或取消的正式 run 也会使旧声明失效。
- 每个已启动 shard job 必须成功，并恰好对应前缀中的一次 source；review 必须成功。
  未启动的 skipped jobs 可以保留；failed、未知已启动 job、缺 job 分页或缺 dispatch 归属均拒绝。
  旧版本没有 run/job 归属的历史证据不能补造身份后恢复。
- 完整前缀必须有真实 source/pristine 原件及清楚用量。0 分仍是已完成试验，不重跑。
  前缀额外 source、inflight、下一片及后续片任何 attempt/source/orchestration 现场均拒绝。
  503 用量未知、receipt/ledger 漂移、归档上传未知均不能恢复。k<N 时预算门禁已停止也拒绝。
  k=N 时只允许末片在完整用量与原件有效的情况下达到 `reported_token_threshold` 或
  `paid_estimate_stop_fraction_reached`：这时只能无模型 Secret 归并，仍独立重算全部 prior
  和本阶段用量完整性，不放行任何新 source，也不忽略其他停止原因。
- 冻结 prior 不能追加暂停后的其他阶段消耗。没有账户级状态服务，V1 保守要求执行仓库
  全部正式 `study <master SHA>` run 集合也不变；首个原运行之后有任何其他 master 正式派发，
  即便无法确认其是否消费，也拒绝恢复。不会重置 100 元，不会自行生成结算记录。
- 该历史核验覆盖指定执行仓库及这套正式 workflow 的记录。执行仓库外的付费活动不能从
  Actions 历史推断；已有财务授权与完整 prior 的真实性仍是既有研究边界。

本地回归使用合成 Harbor 原生 JSON 与真实临时文件，执行真实 receipt 校验及两阶段 merge，
并覆盖历史变化、已启动后续片、缺 source、未知用量、预算停止和仅 merge 的生成路径。
测试中的 Linux 平台声明由 fixture 控制，不能作为实际 Linux runner、Docker、模型调用、
Release 上传或云端恢复成功的证据；这些运行没有在本次修改中执行。
