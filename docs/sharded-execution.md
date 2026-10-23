# 正式研究的执行与恢复

本页解释已经接入的分片与资格入口。代码、离线验证、真实容器 smoke 和正式模型成绩是四种不同证据；实际运行进度见 [状态记录](STATUS.md)。当前固定两题校准的授权不扩展为完整正式研究。

## 职责

| 组件 | 职责 |
| --- | --- |
| Harbor | 环境、单次任务、超时与官方 verifier |
| SAYACODE 生产 wheel | LangChain／LangGraph Agent、工具、后台任务与检查点 |
| `study.PhaseContinuation` | 在原阶段执行函数中保留全局顺序、历史与累计止损 |
| `shards.py` | 冻结完整计划、执行单片、重验原生工件、严格归并 |
| `qualify_fixtures.py` | 固定三次参考解与一次空解、实际资源资格、机械替补与分批 |
| `generate_sharded_workflow.py` | 将冻结 schedule 转为 GitHub 原生串行 DAG，恢复和归档完整证据 |
| `study_resume.py` | 冻结显式完整前缀声明，逐 run/job 核验历史与归档归属 |
| 私有工作流 | 当前 VM 的输入、网络、宿主镜像、时间与磁盘门禁；显式注入和清理本片凭据 |

没有另一个 Agent 循环、评分器、常驻 worker 或自动重跑服务。分片只改变物理执行位置，研究的任务、配置、重复编号和分母不变。

## 完整计划与物理分片

主要开发阶段保持 `8 × 3 × 2 = 48` 次模型试验。选择新候选后，最终阶段为 `24 × 2 × 2 = 96`；保留 baseline 时则是独立的 `24 × 1 × 2 = 48` 次 validation，不制造基线自身对照。

逻辑配对块是 `task × repeat`。每个物理 job 只完成其中一个配置的 source 和独立 pristine replay，沿用一次生成的全局顺序。不能为每片另写小 manifest、重置 repeat 或重新随机排序。

每片执行前预留其官方 `build + agent + verifier` 的两倍，加安装与归档余量。GitHub job 上限为六小时，模板从首次守卫记录 330 分钟软截止；余量不足时保存未启动状态，不缩短官方任务时限。实际执行超时则保留已有 source、用量和原生现场，禁止自动重放。

跨 VM 的原生起止时间保留在原始结果中。时间间隔作为运行条件报告，不根据事后成绩或间隔剔除已经完成的配对。宿主镜像 cohort 漂移会阻止后续派发，剩余计划仍是 missing，不缩小分母。

## 固定 Linux 布局

```text
/tmp/sayacode-studies/<study-id>/
  inputs/
  cache/
  qualifications/
  shards/<shard-id>/
  orchestration/
  merged/<master-sha256>/prefix-NNNN/
  merged/<master-sha256>/final/

/tmp/sayacode-private/<study-id>/
```

实际资格输出目录由调用时固定，后续恢复须保持相同绝对位置。原始 JobConfig、source 路径和请求身份不重写。私有连接文件位于 bundle 外，本片创建的原 profile 和 gateway 副本结束时清理；完整 bundle 不包含这些文件。

可以将下载的 Linux bundle 映射到 Windows 本地进行只读审阅和 DAG 生成。正式计划及原始路径仍由 Linux 执行环境固定，不能用 Windows 路径替换原 JSON 后冒充同一次执行。

同 study 的 SWE dev、holdout 和 Terminal 补充阶段使用同一 bundle，按完整 master SHA 隔离归并目录。前阶段 source、receipt、候选签收和金融 prior 的原绝对路径持续有效，不因后阶段的 `prefix-0001` 或 `final` 冲突而搬家。

## 资格检查

资格入口以原始完整候选池、seed、修复组规则和固定上限进行选样。只有固定三次 oracle 和一次 nop 都原生收尾、实际镜像／平台／CPU／内存／swap 有效，才允许把不通过的任务标为 fixture 失败并机械替补。

无模型资格批次仅在公开 `saya-ch/sayacode-bench` 的标准 Linux runner 执行，不读取供应商 Secret、私有生产工件、用户数据或模型轨迹。公开归档包含官方公开 MIT 任务、固定选择、oracle／nop 日志及资源与宿主元数据。首批核对完整 Actions 历史；已有同 study 的记录，即使失败，也必须显式恢复完整前序 artifact，不能忘传历史后重新开始。

公开标准宿主为 4 CPU／16 GiB，私有模型宿主为 2 CPU／8 GiB。二者不是同一实体硬件；任务容器仍采用官方 CPU、内存和 swap 原值，并逐次核验。公开资格的宿主镜像 cohort 随正式清单保存，与模型 runner 的三个 cohort 字段核对。公开标准 runner 的计算不消耗私有分钟，但工件存储和平台条款仍需分别管理。

未执行、基础设施错误、缺失原生证据、评分未知或资源不符，均是 incomplete。此时停止 cohort，不排除修复组。批次达到 `--max-new-controls` 也只是正常暂停，不等于任务失败。

```bash
python scripts/qualify_fixtures.py --help
```

每次 control 派发前保存固定 attempt 身份。已有完整结果只读复核；有未确认的 native 现场时，不通过换名字或追加调用补跑。即便第一条 oracle 的 reward 为 0，只要执行事实有效，也会完成预定三加一，再按原规则判断资格。

## 冻结宿主与授权

GitHub 编排需要在 `runner_policy.json` 固定：

```json
{
  "platform": "linux",
  "architecture": "amd64",
  "job_timeout_seconds": 21600,
  "public_source_sha": "<已审阅的完整公开源码提交>",
  "executor_workflow_sha256": "<run-study-shard.yml 的真实 SHA256>",
  "evidence_release": {
    "repository": "saya-ch/sayacode-bench-runs",
    "release_id": 420920737,
    "release_tag": "research-evidence-20261022"
  },
  "host_cohort": {
    "ImageOS": "ubuntu24",
    "ImageVersion": "<实际准备记录中的固定版本>",
    "RUNNER_ARCH": "X64"
  }
}
```

每个 fresh runner 的准备记录须通过，准备脚本 SHA 须与固定源码一致，三个实际 cohort 字段须完全相同。这里只实施宿主镜像 cohort，不保证同一实体 CPU、内核身份或供应商模型权重不可变；这些限制应随结果披露。

阶段授权文件绑定实际 master SHA。下面是**尚未授权的结构示例**：

```json
{
  "authorized": false,
  "phase": "dev",
  "master_manifest_sha256": "<完整 master 的真实 SHA256>"
}
```

文件是用户执行范围声明，不是独立认证。生成器不会替用户获得授权；也不会根据本地存在校准 Secret 就授权正式阶段。

## CLI 与生成工作流

资格、完整 master、工件和金融政策均固定后：

```bash
sayacode-bench plan-shards \
  --manifest "$BUNDLE/inputs/master.json" \
  --runner-policy "$BUNDLE/inputs/runner_policy.json" \
  --authorization "$BUNDLE/inputs/authorization.json" \
  --bundle-root "$BUNDLE" \
  --output "$BUNDLE/plan.json"
```

额外的跨阶段费用记录通过 `--paid-records` 显式绑定，不能用它替换 master 冻结的 prior，也不能把同范围内校准费用删掉重新获得预算。

将完整 seed tar 通过 `release_evidence.upload_archive()` 上传到 runner policy 指定的既有私有 draft Release。核对每片服务端 digest、ID、大小和完整归档 SHA 后，将适配器返回的小型 manifest 保存为 JSON，生成待审阅 DAG：

```bash
python -m scripts.generate_sharded_workflow generate \
  --plan "$LOCAL_BUNDLE/plan.json" \
  --bundle-directory "$LOCAL_BUNDLE" \
  --output reviewed-study.yml \
  --seed-manifest "$LOCAL_SEED_MANIFEST"
```

这是唯一的正式 seed 入口，不将大型 tar 提交到 Git，也不保留 Actions artifact 的另一套正式引导路径。生成文件绑定 plan、schedule、public source、静态模板、生成器、Release manifest 和完整 seed SHA；所有 job 使用显式 `needs`，不借 matrix 的并发限制推断顺序。Release 在派发前由用户侧准备，工作流不能自行创建或改为公开。

三个派发确认项默认都为 false：实际执行、完整阶段 scope、Actions 额度。正式密钥使用单独的 `STUDY_CONNECTION_KEYS_JSON`，按冻结连接别名映射；不会暗中复用仅获两题授权的 `SILICONFLOW_API_KEY`。凭据只进入实际执行步骤和 bundle 外的临时 profile。

首片还核对指定私有仓库的原生 Actions 历史与固定 master 身份。再次 dispatch 是新的 run，即使 attempt 仍为 1，也不能从最初 seed 重置试验和费用。已有同 master 的执行、历史缺失或身份不确定时拒绝新首批。

正常分批可使用 `generate --through-sequence K`，仅限制本次物理片终点，保留完整 schedule 与研究分母。K<N 时停在完整片及 prefix 归并之后，不运行 final merge；`physical_batch_complete` 不表示研究完成。下一批使用 `freeze-resume` 冻结不可变声明，再以 `generate --resume-receipt` 从原序号 k+1 生成剩余 DAG，不能任意选择起点。

恢复 review 在无模型 Secret 的 Linux runner 按原路径恢复完整 Release bundle，重新枚举全部同 master runs/jobs，并复用原生 receipt 与累计止损核验。历史集合变化、非 terminal run、失败或未知已启动 job、缺原件、上传未知及剩余片已有现场均拒绝。暂停后有其他 master 正式派发时，冻结 prior 无法续入新消耗，V1 保守拒绝，不重置 100 元。详细命令和仅归并边界见 [物理批次与显式恢复](physical-batch-resume.md)。

## 账本、失效与候选签收

每片 receipt 绑定前序 receipt、前后 ledger 与原生 source／replay。恢复会重新读取哈希绑定的官方 `TrialResult`、用量、补丁和实际资源，不能只相信 `complete` 或 `continuation_allowed` 旗标。

同阶段完整 prefix 用于累计 token、连接故障窗口和阶段事实；金额计算还包括冻结 prior 与额外跨阶段费用。既有身份去重和冲突检查持续生效，不能每片重发 100 元预算。估价止损仍是派发门禁，不能当作供应商人民币硬封顶。

相同 receipt 可幂等读取；冲突版本、复用 source、篡改原生工件、账本分叉或实现漂移会拒绝。完成的成功和失败均不重跑，缺片不补造失败。

每片保存严格的 `merged/<master-sha256>/prefix-NNNN`。中途停止时审阅最后可用 prefix；只有完整末片成功后，独立最终 merge 才写入该 master 的 `final`。归并保留全 master 的 missing，并将原片异常传入派生 manifest 和 `invalid.json`，候选签收不能绕过这些事实。

完整末片刚好触及后续派发阈值时，该片仍可成功收尾与归并；原生 CLI 非零或 receipt 不完整时，工作流会失败，不以“后续 job 全跳过”伪装整个阶段已完成。

## 原始证据与免费配额

完整 raw bundle 每片累积，通过固定私有 draft Release 传递；每个文件按不超过 1 GiB 切片，使用 SHA 命名并核实服务端 digest，不覆盖已有 asset。Release 身份、私有性或完整 SHA 不符时停止，下载后仍由原恢复入口校验 tar 与冻结路径。

Release 上传确认成功后，Actions 只保存小型 host、manifest、receipt 和汇总；上传失败或结果未知时，收尾仍保存当片原始现场。Actions 工件默认保留三天，代码不裁剪原始对话、不自动删除云 artifact。Release assets 当前未列入 Actions artifacts／Packages 存储池，但这不是永久免费承诺；计算分钟与平台条款继续受限。原始 COT、配置和会话轨迹不进入公开报告。

应及时下载原始 ZIP，核对服务提供的 artifact digest，再核验解包文件。只有原始证据已实际保全并核实后，才单独管理旧 artifact 生命周期。API 预算与 Actions 费用分别受限，账户支出上限维持零美元；任何未知费用、未知用量和缺片都保留为未知。固定 100 元授权范围已发生的消耗持续累计，不能因切换存储或派发位置重新获得预算。

## 完成标准

离线行为回归用于验证状态、身份、费用和失败语义；真实 Docker／HTTP 替身用于验证生产运行链与工件合同；公开任务的真实模型试验才用于评估成功率、成本和调优收益。前两者不能替代原定开发、候选签收和最终验收。

正式分析沿用固定任务宏平均、10,000 次任务块 bootstrap、固定 seed 与预定仓库簇敏感性分析。代码修订在正式 trial 前另行冻结实现身份，保留旧协议历史，不更改方法以追求更有利的结果。
