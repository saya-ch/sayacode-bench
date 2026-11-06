# SAYACODE Bench

公开任务、固定输入、真实 Agent 执行、官方验证与可追溯调优。

Harbor 管理任务环境、资源、执行与官方验证器；SAYACODE 继续运行生产应用里的 LangChain / LangGraph 图、工具、检查点与异步子任务。两者用独立 Python 环境，避免评测依赖覆盖产品依赖。

**当前状态：两个批次已完成，但不可合成一张对照表。**

| 批次 | 制品 | planned | 说明 |
|---|---|---|---|
| **v2-325**（11-02~05）| SAYACODE **3.2.5**（本地 wheel，PyPI 未发布）| **78.8%** | 同批次还跑了三个基线：mini-swe **85.0%**、Claude Code **77.5%**、OpenCode **75.0%** |
| **v4-327**（11-06）| SAYACODE **3.2.7**（PyPI 可获取）| **76.2%** | 本批次**只跑了 SAYACODE**，没有基线 |

两批制品、served 分布、并发、网络修复状态全不同，**组间差异与批次效应完全混淆，不能排名、不能互相比较**。3.2.7 与 3.2.5 的配对对比：Δ −2.6pp、McNemar p = 0.8145（不显著）。

**唯一能说的一致结论**：在 v2-325 批次内，SAYACODE 3.2.5 与三个基线的题级差异**未检出统计显著性**（6 对比较，最小 p = 0.070 出现在 OpenCode vs SAYACODE，Bonferroni α/6 ≈ 0.0083 下全部未达）。**不能声称谁更强，也不能声称谁更差。** 注意 p = 0.070 属于 **3.2.5**，**不是** 3.2.7——3.2.7 与基线之间从未做过同批次配对。

Codex 组因适配缺陷**整组作废**；`task_count` 全 0，本批不能评价多 agent；v1 结论仍作废（见 [archive](docs/archive/README.md)）。**全部数字的唯一权威来源：[RESULTS-LEDGER](docs/RESULTS-LEDGER.md)。**

> ⚠️ **`strict` 口径已废除（2026-11-07）**。该口径假设"verifier 不重置 `__snapshots__`"，实测为假：642/642 个 `tests/test.sh:97-105` 在判分前对测试数据面（含快照）执行 `git checkout HEAD`。因此 `strict` 列（80.0 / 73.8 / 67.5 / 78.8）及其衍生的"三种口径三种排名"叙事**全部作废**。现行口径为 `planned`（主报）+ `observed`（辅助，须标幸存者偏差）+ `partial`（新增，见 [DEEP-ANALYSIS](docs/DEEP-ANALYSIS-20261106.md)）。

**三条必须随结论声明的事实**：
1. **制品身份是双批次**：3.2.7 来自 PyPI（`C:\sb\hard\v4-327`，2026-11-06），3.2.5 是**本地构建、PyPI 从未发布**的 wheel（`C:\sb\hard\v2-325`，2026-11-02）；两者 Δ = −2.6pp、p = 0.8145（不显著）。
2. **不是同批次实验**：三个基线只在 v2-325 批次里跑过，v4-327 批次没有基线。跨批次配对受批次效应污染，**不得做排名或配对检验**。
3. **40 题是开发迭代集**（gold patch 中位 3 文件 / 72 行；agent 实际 patch 中位 2 文件 / 64 行），SAYACODE 的提示词规则正是从这套题调出来的，**独立 holdout 从未执行**；且按 [PROTOCOL-V2](docs/PROTOCOL-V2.md) §7，**冻结签收流程从未执行**，因此严格意义上尚无"对外正式成绩"。

详见 **[RESULTS-LEDGER](docs/RESULTS-LEDGER.md)**（唯一权威数字源）、[最新复盘](docs/review/2026-11-07/RETROSPECTIVE-20261107.md)、[STATUS](docs/STATUS.md) §2。

## 文档索引（只列现行文档）

| 文档 | 内容 |
|---|---|
| **★[RESULTS-LEDGER](docs/RESULTS-LEDGER.md)** | **全部对外数字的唯一权威来源**：两批次分表、口径定义（planned/observed/partial）、配对比较、已知数据缺陷。**其他文档只引用，不复制数字。** |
| **★[最新复盘（权威）](docs/review/2026-11-07/RETROSPECTIVE-20261107.md)** | **2026-11-07 全面复盘**：五类缺陷 78 条、必须撤回的五件事、三分法结论账本、P0/P1/P2 计划。**与它冲突的旧文档以它为准**；子报告见 [R1 方法论](docs/review/2026-11-07/R1-methodology.md) / [R2 数据](docs/review/2026-11-07/R2-data-verification.md) / [R3 基建](docs/review/2026-11-07/R3-infrastructure.md) / [R4 产品](docs/review/2026-11-07/R4-product-fixes.md) / [R5 文档债](docs/review/2026-11-07/R5-doc-debt.md) |
| [历史全景（部分已被推翻）](docs/RETROSPECTIVE-20261105.md) | v1→v4 六阶段演进、结论账本、文档债；其中 strict 口径、跨批次结论已被上一行推翻 |
| **[STATUS](docs/STATUS.md)** | **当前真实状态**：四组终版数字、制品身份、作废结论、已知局限、下一步 |
| **[HANDOFF](docs/HANDOFF.md)** | **接手必读**：进度、关键事实、环境、坑、下一步 |
| **[评测方案](docs/EVALUATION-PLAN-20261030.md)** | 总纲：目标 / 基准 / 题集 / 模型 / 指标 / 方法 / 三 agent |
| [实验设计](docs/EXPERIMENT-DESIGN-20261030.md) | 从研究问题到执行协议的完整设计 |
| [调优迭代工作流](docs/ITERATION-WORKFLOW.md) | 三层金字塔、指标体系、Go/No-Go、跑前汇报配置 |
| [方法核对](docs/EVALUATION-METHOD-REVIEW.md) | 与 pass^k / EDD / 统计严谨性等业界主线对照 |
| [路由漂移](docs/ROUTING-DRIFT-20261029.md) | 同一别名 40% 落到 glm 的实测与固定来源方法 |
| [记录格式](docs/record-schema.md) | 字段、来源与预算边界 |
| [环境资格门禁](docs/fixture-gates.md) | 正式模型运行前的三加一资格（**当前开发期未使用**）|
| [预注册协议](docs/protocol.md) | v1 预注册（保留历史；现行口径见 PROTOCOL-V2）|
| **[PROTOCOL-V2](docs/PROTOCOL-V2.md)** | **现行正式协议**：planned 分母、缺失分类、bootstrap、补跑与签收 |
| [多模型扩展](docs/MULTI-MODEL-PLAN.md) | 第二模型设计：协议对齐、路由固定、成本、模型×harness 矩阵 |
| [归档索引](docs/archive/README.md) | 已作废/过期/一次性文档，逐份说明能否引用 |
| [真实踩坑与教训](docs/LESSONS-20261102-v2.md) | v2 重跑遇到的环境/管线/agent/统计问题与处置（现象/根因/预防）|
| **[v2 完整重跑结果](docs/FORMAL-RESULTS-20261102-v2.md)** | 三 agent 终版五指标、McNemar、缺失分类、补跑效应与边界 |
| [报告模板](docs/REPORT-TEMPLATE.md) | 出 `FORMAL-RESULTS-<批次>.md` 的固定版式与不可声称清单 |
| [改测试真相（结论已更正）](docs/TEST-EDIT-ANALYSIS-20261102.md) | **原文的"仅 `.snap` 有效"结论已被证伪**：verifier 同时重置测试代码与测试数据面（含 `__snapshots__`），因此"改快照换 pass"不成立、`strict` 口径废除。保留作历史 |
| [协作场景验证](docs/COLLABORATION-CHECK-20261102.md) | team/single 小样本；autonomous 题 task_count=0 的原因 |
| [task_count 归因](docs/TASKCOUNT-ATTRIBUTION.md) | 团队工具链完好；显式分工题下 task_count=2，及提示/开关一致性 bug |
| [v2 深挖分析](docs/DEEP-DIVE-20261102.md) | 方差轨迹、element-hq 归因、语义 diff、成本-部分相关、磁盘盘点 |
| **[深度分析（部分得分/题库体检）](docs/DEEP-ANALYSIS-20261106.md)** | 391 trial 的连续部分得分、26/40 饱和题、2 题环境性不可过、翻转率、**40 题从未触发上下文摘要** |
| **[v4 四组结果（strict 部分作废）](docs/FORMAL-RESULTS-20261105-v3.md)** | 四组 planned/observed、六组 McNemar、适配健康度；**其中 `strict` 列与"三口径排名"已作废**，见最新复盘 |
| **[SAYACODE 3.2.7 结果](docs/FORMAL-RESULTS-20261106-327.md)** | PyPI 制品复现：planned 76.2%、与 3.2.5 的配对 Δ −2.6pp（p=0.8145）；**其"三项修复"表述有一项事实错误**，见 [R4](docs/review/2026-11-07/R4-product-fixes.md) |
| [Codex 组作废](docs/CODEX-BASELINE-INVALID.md) | 整组不可比的证据：apply_patch 不可用 373 次、websocket 405 960 次 |
| [Claude Code 基线](docs/CLAUDE-CODE-BASELINE.md) | 第三基线接入：`/v1/messages` 原生协议、nginx `?beta=true` 拦截修复、结果 |
| [OpenCode 基线](docs/OPENCODE-BASELINE.md) | 第四基线接入：provider-agnostic 说明（无自家模型）、预置二进制、结果 |
| [预算方案](docs/BUDGET-50-PLAN.md) | ¥50 上限下能做什么：本地免费跑 + 云小样本验证 |
| [云成本估算](docs/CLOUD-COST-ESTIMATE.md) | 机器 vs 模型 token 的成本拆解（结论：付费 API 方案超预算）|
| [硬件评估](docs/HARDWARE-ASSESSMENT-20261103.md) | CPU 过剩、内存/磁盘限制扩样与并发 |
| [不升级硬件的扩样](docs/SCALE-WITHOUT-UPGRADE.md) | 保留 40 题镜像 + 每片 20 题滚动的可行路径 |
| **[大评测集设计（未开跑）](docs/LARGE-EVAL-SET.md)** | 100 题 × 1 重复、四题库分层（pro-v2 / promax / swe-evo / tb21）；**注意：1 重复会丢掉题内方差估计，见 [R1 §6](docs/review/2026-11-07/R1-methodology.md)** |
| **[长上下文受控 A/B（未开跑）](docs/EXPERIMENT-CONTEXT-AB.md)** | 12 题 × 2 噪声档 × 4 组；**当前唯一能检验摘要修复路径的实验**（40 题的上下文峰值到不了触发线）；噪声钩子尚未注入 |
| **[CompletionGuard 判据 A/B](docs/COMPLETION-GUARD-RESULT.md)** | 开/关 +10pp 但 p 不显著、token +53% 超护栏，**不默认开启** |
| **[新题库接入指南](docs/NEW-BENCHMARK-ONBOARDING.md)** | SWE-EVO 接入流程、六个工程坑、准入清单；**§5 已补"全量基线 + 分层抽样"两条硬规则** |
| **[SWE-EVO 试点（有选择偏差）](docs/PILOT-SWE-EVO-20261106.md)** | 5 题 × 2 = 50%；**usable 只有 4 条且全是 1–2 文件小题，唯一重题 0/2，50% 不能支撑"新题库更难"** |

## 固定基准

只用 **[SWE-bench Pro V2](https://github.com/scaleapi/SWE-bench_Pro-os/tree/main/v2)**（public set 642 题，11 仓库，`66f92766bba642462d4bbe5479e83f91f9211862`）。

- 排除 123 题 musl（gravitational / protonmail，产品栈缺 musllinux wheel）→ **519 可评测**。
- 全部 medium/debugging、四语言（python/go/ts/js）；靠**按仓库分层抽样**保证覆盖。
- **暂不使用 Terminal-Bench**（题池小、与产品主战场偏离）。
- 开发迭代集：`studies/sample-40-final.json`（40 题，按仓库分层，seed 可复现；gold-check 为 36 good / 1 bad / 3 null）。
- 权威性与局限（含 Epoch AI 的 "Flawed" 评级）见 [方法核对](docs/EVALUATION-METHOD-REVIEW.md)；因此必须用 gold patch 筛坏题。

## 模型

**暂定只用 hy3**（`auto-hy3` 组，同模型多额度池），上下文按实际 192,000 配置。v2 起 `max_output_tokens=32000`（v1 用 16000，长任务收尾过早）。禁用以会漂移的 `auto/...` 泛指别名；每个 trial 记录实际 `served`/`provider`。详见 [路由漂移](docs/ROUTING-DRIFT-20261029.md)。

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
scripts/           现行跑批/统计工具与历史工具（见 scripts/README.md）
studies/           现行配置、题集与协议（见 studies/README.md）
tests/             行为测试与显式启用的真实 Docker 探针
docs/              现行方案、协议、记录格式；作废文档在 docs/archive/
```

基准源码、镜像缓存、原始轨迹与私有连接放在仓库外，不打入生产 wheel。

## 安装与检查

需要 Python 3.12–3.13、uv 与运行 Linux 容器的 Docker。实际任务资源以官方 `task.toml` 为准。Windows 建议短路径（如 `C:\sb\s` 存固定源、`C:\sb\hard\v2-325` 存原始结果）。

```powershell
uv sync --frozen
uv run --no-sync sayacode-bench --help
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests
uv run --no-sync mypy
```

普通测试不调用付费模型。真实网络探针需显式启用（访问本地 mock，验证公网/宿主阻断与清理），未通过不冻结正式研究。当前本地网络实现只支持无自定义 Compose 的单个 Linux 容器。

## 开发期工具（scripts/）

| 用途 | 命令 |
|---|---|
| 题集清单 | `studies/sample-40-final.json`（40 题开发迭代集）|
| 阶段1 解题 | `python scripts/run_formal_240.py --out <dir> --repeats 2 --skip-verifier --concurrency 4` |
| 阶段2 验证 | `python scripts/verify_patches.py --out <dir> --agents sayacode mini-swe claude-code opencode --concurrency 4` |
| 三口径对比（strict 已废） | `python scripts/strict_compare.py`（planned / observed + 题级配对；**脚本内 `strict` 判定基于已被证伪的快照前提，输出仅供历史核对，不得引用**）|
| 轨迹适配审计 | `python scripts/audit_agent_traj.py`（全量轨迹，抓 unsupported call / API error / 协议缺陷）|
| 重题分片 | `python scripts/split_sample.py --heavy-repo future-architect`（vuls 单题 3.3GB，必须分片 + 并发 1）|
| 汇总 | `python scripts/final_summary.py` |
| 指标记分卡 | `python scripts/analyze_trials.py <jobs目录>` |
| 配对统计 | `python scripts/compare_trials.py <A_jobs> <B_jobs>` |
| 配置汇报 | `python scripts/profile_summary.py <profile>`（跑前必看）|
| served 记录 | `python scripts/annotate_served.py <jobs>` |
| 回归集 | `python scripts/run_regression.py` |
| holdout | `python scripts/run_holdout.py` |
| gold 筛题 | `python scripts/gold_patch_check.py` |

历史一次性工具与「被测试/代码身份绑定、不可移动」的脚本见 [scripts/README.md](scripts/README.md)。

横向对比：SAYACODE vs mini-swe-agent vs **Claude Code** vs **OpenCode**（同 hy3）。**分母统一为 `planned` 80**（缺失按失败，主报），`observed` 只作辅助并标注幸存者偏差，另报 `partial`（连续部分得分）。`strict` 口径**已废除**（前提被证伪，见开头的说明）。**不给单一排名**；四组混两个批次，跨批次对照只能描述性并列。Codex 组已作废，不参与对比。

## 证据与结果原则

- 官方验证器的实际交付为主指标；开发用于诊断与选择，最终任务独立封存。
- 失败、未知用量和未执行任务**全部保留**，不用改小分母美化成绩。
- 每次试验一个补丁、一轮干净环境重判，避免重复试验串补丁。
- 主差值与区间用任务块配对统计（bootstrap / McNemar），重复跟随任务抽样。
- 过程指标（步数/token/改测试）是**诊断**，不作为「模型更强」的证据；partial 必须与 reward hacking 同报（防刷）。
- **测试面只有一个事实**：verifier 在判分前重置测试代码与测试数据面（`tests/`、`testdata`、`fixtures`、`__snapshots__` 等），因此任何 agent 改测试/快照都**不影响评分**。不要再用「patch 含测试文件比例」或「snap pass」做能力或作弊判断（v1 的 49%/73%/42% 与 strict 口径均已作废）。
- 轨迹保存不等于已完成工具语义质量评分；没有实际子任务时不声称协作收益。
- Linux 容器结果不代替原生 Windows/PowerShell 验证。

字段与来源见 [记录格式](docs/record-schema.md)。完整性检查不等于样本充分、第三方认证或已证明因果效应。
