# SAYACODE Bench

公开任务、固定输入、真实 Agent 执行、官方验证与可追溯调优。

Harbor 管理任务环境、资源、执行与官方验证器；SAYACODE 继续运行生产应用里的 LangChain / LangGraph 图、工具、检查点与异步子任务。两者用独立 Python 环境，避免评测依赖覆盖产品依赖。

**当前状态：四个独立批次，互相不可合成一张对照表。**

| 批次 | 制品 | planned | 说明 |
|---|---|---|---|
| **v2-325**（11-02~05）| SAYACODE **3.2.5**（本地 wheel，PyPI 未发布）| **78.8%** | 同批次还跑了三个基线：mini-swe **85.0%**、Claude Code **77.5%**、OpenCode **75.0%** |
| **v4-327**（11-06）| SAYACODE **3.2.7**（PyPI 可获取）| **76.2%** | 本批次**只跑了 SAYACODE**，没有基线 |
| **prov2-40x4**（11-10~11）| SAYACODE **3.3.0** | **55.0%**（effective **64.71%**）| 新题集 40 题 × **1 重复** × 4 agent；六对不显著（最小 p=0.1094），MDE ≈ 22pp |
| **prov2-100x4**（11-11~16）| SAYACODE **3.3.0** | — | 100 题 × 1 × 4，**暂停在 74/100**；effective 48/62 = **77.42%**，六对不显著（最小 p=0.4545），MDE ≈ 16.3pp |

**prov2 两批关系（本轮最重要的发现）**：100x4 的前 40 题与 40x4 **是同一批题**，构成两次独立执行。逐题对齐后实测**翻转率 24%–29%**——同一道题、同一个 agent、同一个验证器，换一次执行就有近三成概率给出相反裁决。同一批 40 题两次跑批的最优 agent 也不同（A 轮 claude-code 81.08%，B 轮 sayacode 70.59%）。**这是「不能排名」的直接证据，不再是「样本量不够」的统计学推断。** 详见 [RESULT-PROV2-100X4](docs/RESULT-PROV2-100X4.md) §3。

两批制品、served 分布、并发、网络修复状态全不同，**组间差异与批次效应完全混淆，不能排名、不能互相比较**。3.2.7 与 3.2.5 的配对对比：Δ −2.6pp、McNemar p = 0.8145（不显著）。

**prov2-40x4 只能用于内部调优方向，不能排名/对外**：40 题 × 1 重复，flaky 13–35%（外部估计），单跑噪声 SD 约 10pp；且旧版「有效通过率 sayacode 75.9% 与 opencode 75.7% 持平」是**分母口径错误**（把两条长跑零产出当基础设施失败删掉，分母 29 vs 应为 34），已更正为 **22/34 = 64.71%**。详见 [RESULT-PROV2-4AGENTS-FINAL](docs/RESULT-PROV2-4AGENTS-FINAL.md) §0 与 [ARCHIVE](docs/ARCHIVE.md) §1 #9。

**唯一能说的一致结论**：在 v2-325 批次内，SAYACODE 3.2.5 与三个基线的题级差异**未检出统计显著性**（6 对比较，最小 p = 0.070 出现在 OpenCode vs SAYACODE，Bonferroni α/6 ≈ 0.0083 下全部未达）。**不能声称谁更强，也不能声称谁更差。** 注意 p = 0.070 属于 **3.2.5**，**不是** 3.2.7——3.2.7 与基线之间从未做过同批次配对。

Codex 组因适配缺陷**整组作废**；`task_count` 全 0，本批不能评价多 agent；v1 结论仍作废（见 [archive](docs/archive/README.md)）。**全部数字的唯一权威来源：[RESULTS-LEDGER](docs/RESULTS-LEDGER.md)。**

> ⚠️ **`strict` 口径已废除（2026-11-07）**。该口径假设"verifier 不重置 `__snapshots__`"，实测为假：642/642 个 `tests/test.sh:97-105` 在判分前对测试数据面（含快照）执行 `git checkout HEAD`。因此 `strict` 列（80.0 / 73.8 / 67.5 / 78.8）及其衍生的"三种口径三种排名"叙事**全部作废**。现行口径为 `planned`（主报）+ `observed`（辅助，须标幸存者偏差）+ `partial`（新增，见 [DEEP-ANALYSIS](docs/DEEP-ANALYSIS-20261106.md)）。

**三条必须随结论声明的事实**：
1. **制品身份是双批次**：3.2.7 来自 PyPI（`C:\sb\hard\v4-327`，2026-11-06），3.2.5 是**本地构建、PyPI 从未发布**的 wheel（`C:\sb\hard\v2-325`，2026-11-02）；两者 Δ = −2.6pp、p = 0.8145（不显著）。
2. **不是同批次实验**：三个基线只在 v2-325 批次里跑过，v4-327 批次没有基线。跨批次配对受批次效应污染，**不得做排名或配对检验**。
3. **40 题是开发迭代集**（gold patch 中位 **3 文件 / 70.5 行**；全部 agent 的 patch 中位 3 文件 / 72 行、SAYACODE 单独 2 文件 / 64 行——三套口径见 [DATASET-CARD](docs/DATASET-CARD.md)），SAYACODE 的提示词规则正是从这套题调出来的，**独立 holdout 从未执行**；且按 [PROTOCOL-V2](docs/PROTOCOL-V2.md) §7，**冻结签收流程从未执行**，因此严格意义上尚无"对外正式成绩"。

详见 **[RESULTS-LEDGER](docs/RESULTS-LEDGER.md)**（唯一权威数字源）、[最新复盘](docs/review/2026-11-07/RETROSPECTIVE-20261107.md)、[STATUS](docs/STATUS.md) §2。

## 文档索引

文档分三层，**引用前先确认在哪一层**：

| 层 | 位置 | 含义 |
|---|---|---|
| **现行** | `docs/*.md` | 可直接引用（各按自己的口径）|
| **部分作废** | `docs/*.md` 顶部带 `⚠️ 部分作废` 横幅 | 部分结论仍成立，引用必须逐条核对 |
| **已归档** | [`docs/archive/`](docs/archive/README.md) | 整篇作废，**停止引用**，仅作取证 |

层与层之间的判定与逐条证据在 **[ARCHIVE](docs/ARCHIVE.md)**（含 2026-11-16 的实际归档动作）。全部链接已校验可解析。

### 现行文档

| 文档 | 内容 |
|---|---|
| **★[RESULTS-LEDGER](docs/RESULTS-LEDGER.md)** | **全部对外数字的唯一权威来源**：两批次分表 + prov2 批次（不入主表）、口径定义（planned/observed/partial）、配对比较、成本与机时、已知数据缺陷。**其他文档只引用，不复制数字。** |
| **★[RESULT-PROV2-100X4](docs/RESULT-PROV2-100X4.md)** | **100 题 × 1 × 4（暂停在 74/100）**：三口径表 + **同题重跑翻转率实测 24%–29%** + 一个未解释的单向翻转成分 |
| **★[RESULT-PROV2-4AGENTS-FINAL](docs/RESULT-PROV2-4AGENTS-FINAL.md)** | 40 题 × 1 × 4：三口径表、六对 McNemar、MDE、flaky；**旧版"sayacode 与 opencode 持平"已作废**（分母 29→34、75.9%→64.71%）|
| **[EXPERIMENT-PROV2-100X4](docs/EXPERIMENT-PROV2-100X4.md)** | 100x4 执行记录：配置、**Docker 每 40–60 分钟崩一次**、vhdx 膨胀、代理配额耗尽、settled 机制、本轮 5 个代码修复 |
| **[EXPERIMENT-PROV2-4AGENTS](docs/EXPERIMENT-PROV2-4AGENTS.md)** | 40x4 运行配置、判分口径（reward 优先）、`c8dba0e` 四处修复、**未修的 musl 镜像偏差** |
| **★[ARCHIVE：docs 腐朽内容清单](docs/ARCHIVE.md)** | **57 份逐条登记**：已推翻 9、部分推翻 6、已被取代 4、有效 30、未复核 8；每条给日期、核心结论、推翻证据。**引用旧文档前先查这里。** |
| **★[第二轮复盘](docs/review/round2/RETROSPECTIVE-ROUND2.md)** | **证据层 + 运行层**：对第一轮复盘本身的审计、七通道并行、**返工率 61.4%**、磁盘真实瓶颈、可复现性分级 |
| **★[第一轮复盘](docs/review/2026-11-07/RETROSPECTIVE-20261107.md)** | **结论层**：五类缺陷 78 条、必须撤回的五件事、三分法结论账本 |
| **[STATUS](docs/STATUS.md)** | 当前真实状态：终版数字、制品身份、作废结论、已知局限 |
| **[HANDOFF](docs/HANDOFF.md)** | 接手必读：进度、关键事实、环境、坑、下一步 |
| **[PROTOCOL-V2](docs/PROTOCOL-V2.md)** | 现行正式协议：planned 分母、缺失分类、bootstrap、补跑与签收 |
| **[评测方案](docs/EVALUATION-PLAN-20261030.md)** | 总纲：目标 / 基准 / 题集 / 模型 / 指标 / 方法 |
| [实验设计](docs/EXPERIMENT-DESIGN-20261030.md) | 从研究问题到执行协议的完整设计 |
| [调优迭代工作流](docs/ITERATION-WORKFLOW.md) | 三层金字塔、指标体系、Go/No-Go、跑前汇报配置 |
| [方法核对](docs/EVALUATION-METHOD-REVIEW.md) | 与 pass^k / EDD / 统计严谨性等业界主线对照 |
| [路由漂移](docs/ROUTING-DRIFT-20261029.md) | 同一别名 40% 落到 glm 的实测与固定来源方法 |
| [记录格式](docs/record-schema.md) | 字段、来源与预算边界 |
| [不升级硬件的扩样](docs/SCALE-WITHOUT-UPGRADE.md) | 保留镜像 + 每片 20 题滚动的可行路径（推翻旧的硬件评估）|
| [归档索引](docs/archive/README.md) | 已作废/过期/一次性文档，逐份说明能否引用 |

### 部分作废（保留原位，顶部有横幅）

| 文档 | 仍成立 / 已推翻 |
|---|---|
| [改测试真相](docs/TEST-EDIT-ANALYSIS-20261102.md) | 「测试代码被重置」成立；「改快照能通过」被证伪 |
| [v2 深挖分析](docs/DEEP-DIVE-20261102.md) | 方差/成本成立；「snap pass」计数作废 |
| [历史全景](docs/RETROSPECTIVE-20261105.md) | 可作历史演进记录；数字须先看第一轮复盘 |
| [深度分析](docs/DEEP-ANALYSIS-20261106.md) | 口径丢失信息、40 题未触发摘要成立；部分得分结论降级为描述性 |
| [task_count 归因](docs/TASKCOUNT-ATTRIBUTION.md) | 团队工具链完好成立；「不触发协作」被部分修正 |
| [协作场景验证](docs/COLLABORATION-CHECK-20261102.md) | single 变体不派发成立；team 变体结论被修正 |
| [失败漏改分析](docs/FAILURE-ANALYSIS-MISSED-FILES.md) | 漏改是主要类型成立；「影响面清单提升通过率」被证伪 |
| [CompletionGuard 判据](docs/COMPLETION-GUARD-RESULT.md) | guard 确实触发成立；「+10pp」不显著不得当收益 |
| [验证不是瓶颈](docs/ANALYSIS-VERIFICATION-IS-NOT-THE-BOTTLENECK.md) | 命令级证据成立；「三轮干预」依赖旧数字 |

### 其余（现行，未逐条复核）

方法/参考类，多数仍有效，个别口径按 ARCHIVE §2/§3 处理：`EVALUATION-PLAN`、`EXPERIMENT-DESIGN`、`ITERATION-WORKFLOW`、`EVALUATION-METHOD-REVIEW`、`fixture-gates`、`ROUTING-DRIFT`、`MULTI-MODEL-PLAN`、`REPORT-TEMPLATE`、`record-schema`、`LESSONS-20261102-v2`、`protocol`。其中 `EVALUATION-PLAN` / `EXPERIMENT-DESIGN` 仍写「三 agent + Codex」，属**部分过时**，引用时以 STATUS / PROTOCOL-V2 为准。

<details>
<summary>其余文档一览（点击展开）</summary>

| 文档 | 内容 |
|---|---|
| [环境资格门禁](docs/fixture-gates.md) | 正式模型运行前的三加一资格（**当前开发期未使用**）|
| [预注册协议](docs/protocol.md) | v1 预注册（保留历史；现行口径见 PROTOCOL-V2）|
| [多模型扩展](docs/MULTI-MODEL-PLAN.md) | 第二模型设计：协议对齐、路由固定、成本、模型×harness 矩阵 |
| [真实踩坑与教训](docs/LESSONS-20261102-v2.md) | v2 重跑遇到的环境/管线/agent/统计问题与处置 |
| [报告模板](docs/REPORT-TEMPLATE.md) | 出 `FORMAL-RESULTS-<批次>.md` 的固定版式与不可声称清单 |
| [Codex 组作废](docs/CODEX-BASELINE-INVALID.md) | 整组不可比的证据：apply_patch 不可用 373 次、websocket 405 960 次 |
| [Claude Code 基线](docs/CLAUDE-CODE-BASELINE.md) | 第三基线接入：`/v1/messages` 原生协议、nginx `?beta=true` 拦截修复 |
| [OpenCode 基线](docs/OPENCODE-BASELINE.md) | 第四基线接入：provider-agnostic 说明、预置二进制 |
| [预算方案](docs/BUDGET-50-PLAN.md) | ¥50 上限下能做什么：本地免费跑 + 云小样本验证 |
| [云成本估算](docs/CLOUD-COST-ESTIMATE.md) | 机器 vs 模型 token 的成本拆解 |
| **[大评测集设计](docs/LARGE-EVAL-SET.md)** | 100 题 × 1 重复、四题库分层；**1 重复会丢掉题内方差估计** |
| **[长上下文受控 A/B](docs/EXPERIMENT-CONTEXT-AB.md)** | 12 题 × 2 噪声档 × 4 组；当前唯一能检验摘要修复路径的实验 |
| **[新题库接入指南](docs/NEW-BENCHMARK-ONBOARDING.md)** | SWE-EVO 接入流程、六个工程坑、准入清单 |
| **[SWE-EVO 试点（有选择偏差）](docs/PILOT-SWE-EVO-20261106.md)** | usable 只有 4 条且全是 1–2 文件小题，50% 不能支撑"新题库更难" |
| [成本优化空间](docs/ANALYSIS-COST-OPPORTUNITIES.md) | 3,091 次调用的成本/延迟解析（ARCHIVE 标「未复核」）|
| [行级 diff 分类](docs/ANALYSIS-LINE-LEVEL-DIFF.md) | 33 条失败的行级分类，被 ANALYSIS-VERIFICATION 引用（ARCHIVE 标「未复核」）|
| [独立复核](docs/AUDIT-RECOMPUTE.md) | impact-350 vs v2v-main 的 20 题 × 2 复核表（ARCHIVE 标「未复核」）|
| [影响面清单实验](docs/EXPERIMENT-IMPACT-CHECKLIST.md) | 覆盖率 +6.7pp、通过率仅 +2.5pp（p=1.0）——证伪了「清单能提分」|
| [工具并行度实验](docs/EXPERIMENT-TOOL-BATCHING.md) | 负面结果：并行化无效、反而变差 |
| [Ledger 重建操作卡](docs/REBUILD-LEDGER.md) | 重建 RESULTS-LEDGER 的步骤 |

</details>

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

横向对比：SAYACODE vs mini-swe-agent vs **Claude Code** vs **OpenCode**（同 hy3）。**分母统一为 `planned` 80**（缺失按失败，主报），`observed` 只作辅助并标注幸存者偏差，另报 `partial`（连续部分得分）。`strict` 口径**已废除**（前提被证伪，见开头的说明）。**不给单一排名**；v2-325/v4-327 四组混两个批次，跨批次对照只能描述性并列；prov2-40x4 是独立第三批（1 重复，只能内部调优）。Codex 组已作废，不参与对比。

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
