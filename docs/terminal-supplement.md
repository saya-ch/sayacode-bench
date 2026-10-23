# Terminal-Bench 2.1 独立补充研究

本页承接 [固定设计](../studies/design-20261022-v1.json) 与 [原协议](protocol.md) 中已经声明的终端补充：12 道最终任务、每配置一次，复用主 SWE-bench Pro V2 开发阶段选中的唯一配置，不在 Terminal 上重新调参。公开入口首批在任何官方控制前因 catalog 身份不一致停止；已保全原件并修复目录指纹排序，尚无 Terminal 官方控制或模型成绩。

| 项目 | 固定值 |
| --- | --- |
| 上游 | `terminal-bench-2.1`，提交 `7131e4375048a0e408a8fb404b5f499d726b695b` |
| 全部任务与适用范围 | 89 道原始任务；按原范围筛选后 45 道 eligible |
| 初选 seed | `sayacode-tb-20261022-scope-v1` |
| 当前初选文件 | [terminal-selection-v2.json](../studies/terminal-selection-v2.json)；[v1 原件](../studies/terminal-selection-v1.json) 保留 |
| v2 文件 SHA256 | `d8e7f64170250886e806092913f637bb23249b62508ddd332cd4d9464757d65f` |
| v2 完整 catalog SHA256 | `4e60e1a92cc86e1aacd4daa06f439b2e890cad85ba441d473dbf859d95a0cf83` |
| 两组规模 | 2 道环境校准候选，12 道独立最终候选 |
| 资源范围 | 六个预声明类别、官方 RAM ≤4096 MB、官方 Agent timeout ≤1800 秒、无 GPU、无自定义 Compose |
| 最终模型 trial 数 | 选中新候选：12×2×1=24；保留 baseline：12×1×1=12 |

六个类别是 `software-engineering`、`debugging`、`system-administration`、`file-operations`、`data-processing`、`security`。已用固定本地 Git 快照重新核对原候选 metadata；seed、任务 ID 与全部排除原因和原先记录一致，目录指纹修订如下。只解析任务配置，题面和参考解只计算字节哈希，没有将正文用于选样。Terminal 上游没有提供本适配器可用的 `SHA256SUMS`，因此 catalog／task tree 哈希是本项目的复现身份，不冒充官方校验清单或独立认证。

2026-10-23 的 [首批实际运行](https://github.com/saya-ch/sayacode-bench/actions/runs/39906586154) 使用 v1 与源码 `96d20591492c88ea1c378606c20414e8eb34371b`，原生 CLI 在检查完整 catalog 时抛错，随后外层读取尚不存在的 sanity 产生二次错误。主／host 原 ZIP 服务 SHA 和内部 tar SHA 已核验；attempt、新增控制、合格、拒绝、模型请求均为零，不能将这次基础设施失败算作 fixture 不通过。最小事实见 [失败记录](../reports/terminal-qualification-catalog-failure-20261023-v1.json)。

v2 修正 `tree_digest` 的平台依赖：旧 `sorted(Path)` 在 Windows 折叠大小写，新规范对相对路径 `parts` 元组逐组件、区分大小写排序，严格保持旧 Linux Path 顺序。不能改成按完整 POSIX 字符串排序，因为 `a/file` 与 `a.txt` 的先后会不同。原 seed、scope、14 个任务 ID、排除原因、资源、instruction／config 字节哈希均保持，只有受影响的 task tree、完整 catalog 和相应 selection 文件身份更新；v1 与失败 raw 不改写。

SourceSnapshot 的整树指纹也采用同一规范；它覆盖源码根目录，会因 README 等文件的排序修正旧 Windows 指纹，即使任务 catalog 不变。重算 SWE 642 题 catalog 仍为既有 `835f7b2f2f08973dc63f16fa2fd5921d4cbee8cf6c0a7245456db19421a12d33`，并重新通过官方 6,436 项 checksum，不更换主研究选择。官方 Git revision、原文件字节与上游 checksum 语义不受排序影响。旧缓存若保存了 Windows 旧指纹，应保留原件并从固定源建立新的缓存身份，不加入兼容错误排序的分支，也不手改旧缓存元数据。

`dev` 在此 selection 中只表示环境校准候选槽位，不能调用开发选型把 Terminal 结果作为候选来源。文件明确声明 `study_role=terminal_supplement`，该声明贯穿资格重选；冻结时忘传角色或使用 `generic` 均拒绝。环境资格阶段仍对全部两组执行固定三次 oracle、一次 nop、最多 64 个候选，失败按原 seed 和完整 catalog 机械替补。最终合格数量不足时保持 incomplete，不降低 N、不换 seed、不挑容易题。当前 2+12 是初选，最终 ID 仍由该资格流程产生。

## 公开无模型资格入口

复用 `scripts.qualify_cloud` 与 `qualify-study.yml`，新增 `study_kind=primary|terminal`，不增加另一套执行器。`terminal` 固定指向上述 JSON 和 SHA；不能通过该公开入口上传任意 selection。批次数、时间余量、磁盘门禁、真实镜像摘要、三加一规则、失败停止和完整 bundle 恢复语义沿用主研究。

先将包含本实现的源码提交为审阅后的完整 SHA，并将工作流模板固定到与该 SHA 完全一致的版本。下列命令是操作者获得基础设施执行授权后使用的派发模板；把尖括号替换为实际值：

```bash
gh workflow run qualify-study.yml --repo saya-ch/sayacode-bench \
  --ref '<包含本实现且模板匹配的不可变 ref>' \
  -f public_source_sha='<完整源码 SHA>' \
  -f study_kind=terminal -f study_id='<固定 Terminal study ID>' \
  -f image_os=ubuntu24 -f image_version='<冻结 ImageVersion>' \
  -f max_new_controls=4 -f acknowledge_execution=true
```

续批在同一命令上增加三个参数，并保留原 source、kind、study ID 和 host cohort：

```bash
  -f resume_run_id='<前序 run ID>' \
  -f resume_artifact='<前序完整 qualification artifact 名称>' \
  -f resume_sha256='<前序 bundle.tar.gz SHA256>'
```

每批最多推进一个任务的预定控制，不自动启动下一批。续批必须恢复完整旧 archive；不能只传 `selection.json` 或把旧结果改写到新位置。`cloud-plan.json` 与归档 manifest 都记录 `study_kind`、benchmark、source license；把 Terminal bundle 当 primary 恢复或归档会被拒绝。已经启动的旧主研究资格仍须使用其原冻结 source 和旧模板，不把本次源码混入旧计划。

固定版本的 SWE 数据仓库顶层许可为 MIT，Terminal 数据仓库顶层许可为 Apache-2.0。公开资格材料按实际来源分别标识；容器、镜像依赖和第三方文件继续遵守各自许可。公开归档仅包含固定公开任务及官方 oracle/nop 控制、资源、宿主信息；模型生产工件和私有模型轨迹属于后续私有阶段。

## 网络与官方资源

所选 Terminal 任务的官方 `environment.allow_internet=true` 原样保留。Harbor 的任务网络策略允许 Agent 使用 PUBLIC 网络，适配器使用既有 PUBLIC 分支，不把这些任务改为仅模型 endpoint 可达。现有网络探针验证适配器可切换和清理网络，不证明 Terminal 的 Agent 阶段只可访问模型服务。

两种基准的网络条件应分别披露。每题 CPU、RAM、swap、构建／Agent／verifier 时间均按官方任务配置保持；不把选择范围上限写成所有题的统一实际资源。实际容器和网络行为仍需后续真实控制及执行证据确认。存储硬配额等既有后端限制继续见 [记录契约](record-schema.md)。

## 候选签收与正式冻结

先完成并严格归并主 SWE 开发 8 道任务、三个配置 `baseline/diagnostic/focused`、R2 的完整原始结果，再通过既有 `lock-candidate` 生成一次不可覆盖的签收单。Terminal 不能以自己的开发结果重新选择候选。签收单仍会复核原始记录、费用已知性、同模型、生产 wheel、依赖及 variant 的字节身份。

以下 Linux 例子要求所有变量已经指向真实且已固定的文件；`PRIMARY_DEV` 必须是签收单中的原主开发 manifest 绝对路径。同一累计 bundle 的 `inputs` 使用各阶段不同文件名，例如 `primary-dev.json`、`primary-final.json`、`terminal-final.json`。阶段 bundle 必须携带原开发 manifest 和签收引用的原始 records／工件，并保持原路径，使实际运行时仍可重新核验。新阶段不得覆盖原主开发 manifest 或签收单。

SWE 与 Terminal 的公开资格归档分别恢复到各自 `cloud-plan.json` 冻结的原始绝对根目录。`TERMINAL_QUALIFICATION_ROOT` 指向独立的 Terminal 资格 bundle；不要搬写其原始 JSON 路径，也不要将其 `qualification` 覆盖到共享模型 bundle 的 SWE 资格目录。冻结时从这个旁边的只读目录读取 Terminal selection、sanity、cloud-plan，最终 master 仍写入共享模型 `BUNDLE/inputs`。当前冻结门禁复核 sanity 内的三加一状态、资源和原生结果哈希声明，不逐个重开原始 `TrialResult`／runtime 文件；完整资格原件的保全与审计不能由这一步代替。

```bash
PRIMARY_DEV="$BUNDLE/inputs/primary-dev.json"
TERMINAL_MASTER="$BUNDLE/inputs/terminal-final.json"
# 使用 Terminal 公开资格 cloud-plan.json 中的原 bundle_root；不是模型 BUNDLE。
TERMINAL_QUALIFICATION_ROOT="/tmp/sayacode-studies/<原 Terminal 资格 study ID>"

uv run --no-sync sayacode-bench freeze \
  --study-role terminal_supplement \
  --phase holdout --repeats 1 \
  --selection "$TERMINAL_QUALIFICATION_ROOT/qualification/selection.json" \
  --sanity "$TERMINAL_QUALIFICATION_ROOT/qualification/sanity.json" \
  --network-probe "$NETWORK_PROBE" \
  --candidate-lock "$PRIMARY_CANDIDATE_LOCK" \
  --primary-dev-manifest "$PRIMARY_DEV" \
  --variant "baseline=$BASELINE_VARIANT" --variant "$SELECTED=$SELECTED_VARIANT" \
  --connection "$CONNECTION_ALIAS=$PRIVATE_CONNECTION" \
  --wheel "$PRODUCT_WHEEL" --requirements "$REQUIREMENTS" \
  --seed "$FROZEN_TERMINAL_ORDER_SEED" \
  --reported-token-limit "$FROZEN_REPORTED_TOKEN_LIMIT" \
  --output "$TERMINAL_MASTER"
```

当前冻结实现把 selection／sanity 的 SHA、逐题官方任务配置、资格 runtime identity 和宿主 cohort 写入 master。`run`／`run-shard` 从 master 复核这些身份及当前实际资源，不再按原 sanity 路径打开资格文件，因此 Terminal 资格旁根是冻结与后续审计所需，不是每片模型 runner 的路径依赖。原资格 archive 仍须完整保全；主开发候选签收、其 dev manifest／records 和费用记录则继续按各自冻结的原绝对路径参与每片复核，不能混淆这两类依赖。

上述命令适用于主开发选出了不同候选。若主开发保留 baseline，则改为 `--phase validation` 并只传 `--variant baseline=...`，仍为 `--repeats 1`、12 道任务和相同主开发签收单；不能产生 baseline 自比。

付费连接还必须带上已授权的同一预算政策，例如 `--paid-limit-cny`、`--paid-stop-fraction`、`--paid-price-snapshot`、`--paid-endpoint`，并用可重复的 `--prior-records` 纳入此前属于同预算范围的全部校准及主研究记录。进入分片后继续使用同一累计账本，不能因更换基准重新获得 100 元预算。此处命令没有设置新的预算默认值。

`--study-role terminal_supplement` 强制绑定指定主 dev 文件路径与 SHA，并要求签收来源为固定版本 SWE V2 八题 R2、最终来源为固定版本 Terminal 2.1 十二题 R1。候选标签、阶段、wheel、依赖和实际 variant 文件继续沿用通用签收验证。该角色既在冻结时校验，也在 `run`／`run-shard` 复核签收时校验。`--phase dev`、Terminal 自己的 dev 来源、其他主 dev 路径、错误重复数和更换 variant 均拒绝。默认 `generic` 入口仍服务其他独立研究，不将本次设计限制施加给所有通用调用。

冻结后复用 [分片与恢复入口](sharded-execution.md) 的 `plan-shards`、DAG 生成、原始工件归档、`run-shard` 和严格归并。Terminal 使用其官方最终文件状态与 verifier 证据；现有执行分派不会强行把全部终端产物转成 SWE 补丁。公开资格成功不自动授权后续付费模型阶段。

## 独立报告与验收边界

用 Terminal 自己的 master 和归并记录生成报告，不拼接 SWE 记录：

```bash
uv run --no-sync sayacode-bench report \
  --manifest "$TERMINAL_MASTER" \
  --records "$TERMINAL_MERGED/records.jsonl" \
  --output "$TERMINAL_REPORT"
```

报告必须标明 Terminal-Bench 2.1 环境资格子集、计划 N=12、R1、实际完成／缺失、PUBLIC 网络、逐题资源、主研究候选来源及未重新调参。公开脱敏 manifest 保留 `study_role` 和 `primary_dev_manifest.sha256`，剥离原绝对路径，使来源关系可核对。结果不与 SWE 合并成功率，也不称完整排行榜成绩；保留 baseline 时只报告独立 validation 的绝对结果。

新增 `tests/test_terminal_supplement.py` 使用离线合成记录验收固定来源、跨 kind 恢复拒绝、真实来源许可、CLI 冻结和主 SWE R2→Terminal R1 候选约束。它与既有云端资格、locking、cohort 测试共同验证接线；未调用 Docker、GitHub 或模型，不证明真实三加一、生产 Agent 或官方成绩已经通过。
