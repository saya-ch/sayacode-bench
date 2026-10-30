# SAYACODE Bench

公开任务、固定输入、真实 Agent 执行、官方验证与可追溯调优。

Harbor 管理任务环境、资源、执行与官方验证器；SAYACODE 继续运行生产应用里的 LangChain / LangGraph 图、工具、检查点与异步子任务。两者用独立 Python 环境，避免评测依赖覆盖产品依赖。

**当前状态：开发期内部调优。** 尚无对外正式成绩或已证实的调优收益。早期探索性数字因「上下文配置错误 + 模型路由漂移」已**作废**，见 [历史教训](docs/EXPLORATORY-20261029.md)。正式对外研究的预注册见 [protocol](docs/protocol.md)。

## 评测方案（先读这个）

| 文档 | 内容 |
|---|---|
| **[评测方案](docs/EVALUATION-PLAN-20261030.md)** | 总纲：目标 / 基准 / 题集 / 模型 / 指标 / 方法 / 三 agent |
| [调优迭代工作流](docs/ITERATION-WORKFLOW.md) | 三层金字塔、指标体系、Go/No-Go、跑前汇报配置 |
| [路由漂移](docs/ROUTING-DRIFT-20261029.md) | 同一别名 40% 落到 glm 的实测与固定来源方法 |
| [方法核对](docs/EVALUATION-METHOD-REVIEW.md) | 与 pass^k / EDD / 统计严谨性等业界主线对照 |
| [历史教训](docs/EXPLORATORY-20261029.md) | 哪些旧数字作废、为什么、仍成立的教训 |
| [预注册协议](docs/protocol.md) · [工作计划](docs/WORK_PLAN.md) · [验证状态](docs/STATUS.md) | 正式对外研究的协议与状态 |

## 固定基准

只用 **[SWE-bench Pro V2](https://github.com/scaleapi/SWE-bench_Pro-os/tree/main/v2)**（public set 642 题，11 仓库，`66f92766bba642462d4bbe5479e83f91f9211862`）。

- 排除 123 题 musl（gravitational / protonmail，产品栈缺 musllinux wheel）→ **519 可评测**。
- 全部 medium/debugging、四语言（python/go/ts/js）；靠**按仓库分层抽样**保证覆盖。
- **暂不使用 Terminal-Bench**（题池小、与产品主战场偏离）。
- 权威性与局限（含 Epoch AI 的 "Flawed" 评级）见 [方法核对](docs/EVALUATION-METHOD-REVIEW.md)；因此必须用 gold patch 筛坏题。

## 模型

**暂定只用 hy3**（`auto-hy3` 组，同模型多额度池），上下文按实际 192,000 配置。禁用以会漂移的 `auto/...` 泛指别名；每个 trial 记录实际 `served`/`provider`。详见 [路由漂移](docs/ROUTING-DRIFT-20261029.md)。

## 架构与目录

```text
src/sayacode_bench/
  sources.py       上游 Git blob、官方校验和轻量目录
  selection.py     元数据分层抽样与排除记录
  network.py       本地阶段网络与固定模型网关（chat / messages / responses 三路上游）
  adapter.py       Harbor InstalledAgent 扩展（薄适配，不代替模型改代码）
  worker.py        生产应用装配、任务族收尾、原生证据和补丁采集（含测试保护）
  execution.py     官方执行与逐次独立重判
  locking.py       候选签收与最终任务泄漏检查
  study.py         冻结阶段的薄调度
  shards.py        全局顺序、累计账本、单片执行与严格归并
  analysis.py      任务块统计、完整性检查与开发选择
  gates.py         数据、实现、真实探针与评分门禁
  connections.py   私有连接与规范模型身份
scripts/           开发迭代工具（见下）
studies/           配置、假设、抽样清单与冻结清单
tests/             行为测试与显式启用的真实 Docker 探针
docs/              协议、记录格式、评测方案与教训
```

基准源码、镜像缓存、原始轨迹与私有连接放在仓库外，不打入生产 wheel。

## 安装与检查

需要 Python 3.12–3.13、uv 与运行 Linux 容器的 Docker。实际任务资源以官方 `task.toml` 为准。Windows 建议短路径（如 `C:\sb\s` 存固定源、`C:\sb\r` 存原始结果）。

```powershell
uv sync --frozen
uv run --no-sync sayacode-bench --help
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync mypy
```

普通测试不调用付费模型。真实网络探针需显式启用（访问本地 mock，验证公网/宿主阻断与清理），未通过不冻结正式研究。当前本地网络实现只支持无自定义 Compose 的单个 Linux 容器。

## 开发迭代工具（scripts/）

| 用途 | 命令 |
|---|---|
| 题集清单 | `studies/sample-40.json`（40 题分层抽样，可复现）|
| 跑批 | `run_holdout.py` / `run_regression.py`（支持 `--skip-existing --concurrency`）|
| 指标记分卡 | `analyze_trials.py`（pass@1 / partial / cost-per-success / reward hacking / bloat / 方差）|
| 配对统计 | `compare_trials.py`（McNemar + risk difference）|
| 配置汇报 | `profile_summary.py`（跑前必看：模型/上下文/触发点）|
| served 记录 | `annotate_served.py` |

横向对比：SAYACODE vs mini-swe-agent vs Codex CLI（同 hy3）。

## 证据与结果原则

- 官方验证器的实际交付为主指标；开发用于诊断与选择，最终任务独立封存。
- 失败、未知用量和未执行任务**全部保留**，不用改小分母美化成绩。
- 每次试验一个补丁、一轮干净环境重判，避免重复试验串补丁。
- 主差值与区间用任务块配对统计（bootstrap / McNemar），重复跟随任务抽样。
- 过程指标（步数/token/改测试）是**诊断**，不作为「模型更强」的证据；partial 必须与 reward hacking 同报（防刷）。
- 轨迹保存不等于已完成工具语义质量评分；没有实际子任务时不声称协作收益。
- Linux 容器结果不代替原生 Windows/PowerShell 验证。

字段与来源见 [记录格式](docs/record-schema.md)。完整性检查不等于样本充分、第三方认证或已证明因果效应。
