# SAYACODE Bench

公开任务、固定输入、真实 Agent 执行、官方验证与可追溯调优。

Harbor 管理任务环境、资源、执行和官方验证器；SAYACODE 继续运行现有 LangChain / LangGraph 图、工具、检查点与异步子任务。两者使用独立 Python 环境，避免评测依赖覆盖产品依赖。

**当前处于基础设施门禁与资源校准，尚无公开基准成绩或已证实的调优收益。** 已执行和待完成项目见 [验证状态](docs/STATUS.md)。研究方法见 [预注册协议](docs/protocol.md)，执行顺序见 [工作计划](docs/WORK_PLAN.md)。

固定的跨宿主诊断发现判分不一致：同一份 qutebrowser 交付在独立 Linux 三次通过，Ansible 交付三次未通过且参考解稳定通过。独立 Ubuntu Engine、固定失败种子和 WSL 3.0.3 升级诊断均已完成并单独保留；升级后参考解仍未全部通过，本轮本地平台配置试验已结束，不反复更换版本到通过，也不唯一归因内核或硬件。原分与全部诊断未混入正式效果统计。[校准证据](docs/calibration.md) · [WSL 诊断](docs/wsl-diagnostic.md) · [Linux 执行手册](docs/linux-execution.md)

## 研究目标

在相同模型、任务、工具和资源预算下，检验经开发集选择的一项改进是否改变编程任务完成率和资源消耗。

- 官方验证的实际交付为主指标；开发用于诊断和选择，最终任务独立封存。
- 每个任务块固定连接并随机配置顺序，重复不当成独立任务。
- 所有失败、未知用量和未执行任务保留，不通过改小计划分母美化成绩。
- 没有候选胜出时保留基线，并进行单组最终验收。

## 固定公开基准

| 基准 | 版本与提交 | 用途 |
| --- | --- | --- |
| [SWE-bench Pro](https://github.com/scaleapi/SWE-bench_Pro-os/tree/main/v2) | V2，642 题；`66f92766bba642462d4bbe5479e83f91f9211862` | 真实仓库编程、官方测试与独立 pristine 补丁重判 |
| [Terminal-Bench](https://github.com/harbor-framework/terminal-bench-2-1) | 2.1，89 题；`7131e4375048a0e408a8fb404b5f499d726b695b` | 终端完整任务能力，按其官方验证方式单独报告 |

子集报告公开选择规则、全部 ID 和适用性排除，不写成完整榜单成绩。Terminal-Bench 2.1 是固定的历史版本，不与后续版本混算。第三方项目仍保留各自许可。

## 架构与目录

```text
Harbor 官方任务与环境
  └─ SAYACODE InstalledAgent 薄适配
       └─ SayacodeApp / LangChain / LangGraph / 原生工具与子任务
  └─ 官方验证器 / 独立 pristine 重判
       └─ 逐次结果、配对统计与候选签收
```

适配器不合并子 Agent 交付，不代替模型实施修改。Agent 循环保持在生产应用中。

```text
src/sayacode_bench/
  sources.py       上游 Git blob、官方文件校验和轻量目录
  selection.py     元数据分层抽样与排除记录
  network.py       本地阶段网络与固定模型网关
  adapter.py       Harbor InstalledAgent 扩展
  worker.py        生产应用装配、任务族收尾、原生证据和补丁
  execution.py     官方执行与逐次独立重判
  locking.py       开发候选签收与最终任务泄漏检查
  study.py         冻结阶段的薄调度
  shards.py        全局顺序、累计账本、单片执行与严格归并
  resources.py     官方声明、Docker 与 cgroup 资源核验
  analysis.py      任务块统计、完整性检查与开发选择
  gates.py         数据、实现、真实探针与评分门禁
  connections.py   私有连接与规范模型身份
  artifacts.py     文件身份、停止记录和报告边界
  budget.py        已报告用量的保守人民币估算与新派发止损
  publish.py       公开事实白名单，不复制凭据、轨迹与原始路径
  cli.py           准备、冻结、执行和报告入口
studies/           配置、假设和已冻结清单
tests/             行为测试与显式启用的真实 Docker 探针
docs/              协议、记录格式与验证范围
```

基准源码、镜像缓存、原始轨迹与私有连接放在仓库外，不打入生产 wheel。

## 安装与检查

需要 Python 3.12–3.13、uv，以及运行 Linux 容器的 Docker。实际任务资源以官方 task.toml 为准。

Windows 建议使用短路径，例如 `C:\sb\s` 保存固定源、`C:\sb\r` 保存原始结果。长任务 ID 叠加深层用户目录会超出部分进程工作目录接口的限制；路径调整不改变官方任务内容。

```powershell
uv sync --frozen
uv run --no-sync sayacode-bench --help
uv run --no-sync sayacode-bench doctor --output C:\develop\sayacode-evaluations\docker-doctor.json
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync mypy
```

普通测试不调用付费模型。真实网络探针必须显式启用，访问本地 mock，验证公网／宿主阻断、阶段恢复与清理：

```powershell
$env:SAYACODE_BENCH_DOCKER_TESTS = "1"
$env:SAYACODE_BENCH_PROBE_OUTPUT = "C:\develop\sayacode-evaluations\network-probe.json"
uv run --no-sync pytest tests/test_network.py::test_real_docker_network_isolation -q -s
```

探针未通过，不冻结正式研究。当前本地网络实现只支持无自定义 Compose 的单个 Linux 容器；不支持的任务在看模型成绩前排除。

本机校准发现官方参考解也会遇到测试库内部异常。相同不可变镜像在独立 Linux 对照中通过了固定的三次参考解与一次空解检查；本机资格批次已停止并标记失效，正式研究等待稳定执行资源。具体证据见 [宿主交叉验证](docs/host-diagnostics.md)。资格规则与机械替补见 [环境资格门禁](docs/fixture-gates.md)；通过资格检查的子集也不代表完整榜单。

## 正式工作流

1. `prepare` 固定公开源，依据预声明资源与语言范围抽样。
2. `sanity` 运行初始参考解与空解；正式任务使用 `scripts/qualify_fixtures.py` 的固定资格门禁，不调用模型。
3. 用独立校准题测量时间、接口稳定性与用量，核实路由和预算；固定规模不足以完成时保留 incomplete，不缩小计划。
4. `freeze --phase dev` 绑定任务、模型参数、生产 wheel、依赖、候选及评测实现身份。
5. `plan-shards` 冻结全局顺序；`run-shard`／`merge-shards` 在 fresh Linux runner 延续原阶段与账本。`run` 保留完整阶段入口。
6. `lock-candidate` 签收完整开发结果与唯一选择。
7. 新候选使用 `holdout`，保留基线时使用单组 `validation`；拒绝开发与最终任务或同修复组重叠。
8. `report` 继承中止／失效状态，只读汇总，不改原分。

完整参数使用各子命令的 `--help` 查看。已确定主要开发 48 次、候选胜出时最终 96 次、保留基线时独立 validation 48 次；任务资格、完整清单、执行实现与预算在正式派发前固定。代码入口存在不表示这些试验已经完成。

跨 runner 使用完整 bundle、原始绝对路径、哈希绑定的前序 receipt 和累计账本，不复制聊天状态或重建评分器。真实网络、官方资源、宿主镜像 cohort、剩余时间和磁盘均在本 runner 核验。固定三加一资格支持按 control 分批，未知基础设施状态不会被当成 fixture 失败而机械排除。详见 [分片执行与恢复](docs/sharded-execution.md)。

私有工作流默认不执行模型。两题校准 Secret 与正式研究 Secret 分开授权；完整 raw artifact 的增长、免费分钟与存储额度分别管理，不把 100 元 API 预算当成 Actions 费用授权。

## 连接、证据与结果

研究模型统一登记为 `DeepSeek-V4.1-Flash`。授权连接是访问配置，不作为提供商比较因素；同一配对块使用同一连接，切换保留记录。

私有 profile 保存在仓库外，包含协议、地址、密钥、模型 ID 和实验预算；上传到容器私有目录，不放进 Shell 参数或公开日志。Store 中的恢复密钥快照不导出。

原生审计统计全部已观测线程。缺失 usage 明确保留；报告 token 阈值只能停止新派发，不能保证完整账单上限。未知费用不填 0，回调次数不冒充全部 SDK／反代 HTTP 尝试。

- 运行结束、官方 reward 与任务验收分别记录。
- SWE 每次一个 source job、一份补丁、一轮干净环境重判，避免重复试验串补丁。
- 主差值与 bootstrap 使用任务块，重复跟随任务抽样。
- 缺记录、未知验收、输入变更、跨接口配对和中止事实会阻止正式比较。
- 服务故障保留，修复后的整对复验另列，不只补失败侧覆盖。
- 轨迹保存不等于已完成工具语义质量评分；没有实际子任务时不声称协作收益。
- Linux 容器结果不代替原生 Windows／PowerShell 验证。

字段与来源见 [记录格式](docs/record-schema.md)。完整性检查不等于样本充分、第三方认证或已经证明因果效应。

本轮生产运行包的精确源码和逐字节重建记录见 [生产基线重建](reproduction/README.md)。

真实校准的失败和止损事实见 [校准观察](docs/calibration.md)。模型运行结束不等于任务验收通过；开发、校准与最终结果分别标注。
