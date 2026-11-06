# R5：文档债与全仓口径一致性审计（2026-11-07）

> 范围：`sayacode-bench/docs/*.md`（35 份在册）、`docs/archive/*.md`（20 份）、`README.md`、`AGENTS.md`，以及产品仓 `sayacode/docs/` 中与评测相关的 4 份（`PROMPT-OVERFIT-RISK.md`、`VERIFY-20261103.md`、`SUMMARY-FALLBACK-CHECK.md`、`COMPLETION-GUARD-AB.md`）。
> 方式：全量读取 + 关键词交叉（grep）+ 相对链接逐个解析 + [RETROSPECTIVE-20261105](../../RETROSPECTIVE-20261105.md) §6 十条逐条复检。**只读审计，未修改任何现有文档**；本文件是唯一新增产物。
> 结论先行：**死链 0，但口径冲突 22 条、孤儿文档 4 份、索引漏项 7 份、RETROSPECTIVE §6 十条中仅 3 条真正还清。** 最严重的是「SAYACODE 主数字两套（78.8% / 76.2%）并存」与「制品身份（3.2.5 / 3.2.7）在两份权威文档里互相否定」。

## 0. 范围清点（与任务描述的差异先记一条）

| 项 | 任务描述 | 实际 | 差异 |
|---|---|---|---|
| docs 在册 | 38 | **35** | −3（可能把 `docs/review/` 或已归档项算入）|
| docs/archive | 25 | **20** | −5 |
| 仓库根 | README、AGENTS | README、AGENTS | 一致 |
| 产品侧评测相关 | PROMPT-OVERFIT-RISK 等 | 4 份 + `docs/evaluation/` 19 份历史 | 需明确是否纳入 |

`docs/review/` 在本次审计前不存在（本文件是首份）。产品仓 `docs/evaluation/` 存在 19 份历史报告，未被 bench 任何文档索引——属跨仓孤儿。

## 1. 全量清单表

定位含义：**权威**＝当前结论以它为准；**证据**＝专项分析/一次性实验记录；**参考**＝方法/方案，不产生当前数字；**历史**＝已被取代但保留说明；**作废**＝不得引用。

### 1.1 docs 在册（35）

| 文档 | 定位 | 最后更新 | 是否过时 | 与谁冲突 | 处置建议 |
|---|---|---|---|---|---|
| RETROSPECTIVE-20261105.md | 权威（历史全景+文档债） | 11-06 | 部分 | §1 表仍是 3.2.5 的 78.8；§6 状态标记滞后 | 保留，补 3.2.7 行、刷新 §6 |
| STATUS.md | 权威（当前状态） | 11-05（§9 为 11-06 追加）| **是（内部）** | 与 HANDOFF/README/v3 的数字与制品冲突（C1–C5）；§1 p 值与 §2.1 冲突（C3）| **改写**（P0）|
| README.md（根）| 权威（入口/索引）| 11-05 | 是 | SAYACODE 78.8/3.2.5 未同步 3.2.7；索引漏 7 份 | 改写（P0）|
| HANDOFF.md | 权威（交接）| 11-05 | **是** | 78.8/3.2.5；「下一步用 3.2.7 重跑」已完成；并发 ≤6 与 AGENTS 2–4 冲突 | 改写（P0）|
| AGENTS.md（根）| 权威（维护规则+坑）| 11-05/06 | 部分 | 「所有 SAYACODE 数字=3.2.5」未同步；坑 23 仍是 v2 数字 | 改写（P1）|
| PROTOCOL-V2.md | 权威（协议）| 11-05 | 部分 | §5.1 表 SAYACODE 78.8（3.2.5）；§6.2 mini 70.0 未含 v4 85.0；§7.3 checklist 漏 strict；§0/§2「planned 唯一主报」与 §5.1「strict 必须同表」张力 | 改写（P0）|
| FORMAL-RESULTS-20261105-v3.md | 权威（四组结果）| 11-05 | 部分是 | SAYACODE 78.8/3.2.5；未含 3.2.7；mini-swe 补跑前 70.0 未在正文（仅表）| 保留为「3.2.5 批次报告」，加 3.2.7 指针 |
| FORMAL-RESULTS-20261106-327.md | 权威（3.2.7 结果）| 11-06 | 否 | 与 STATUS/HANDOFF/README/v3 的主数字冲突（C1/C2）；未进 README 索引 | 保留，提升为「当前 SAYACODE 结果」 |
| FORMAL-RESULTS-20261102-v2.md | 历史（v2 三组）| 11-02 | 是（被 v3/v4 取代）| 78.8/70.0/68.8 与现行四组并存（C4/C5）；严格口径 65/65 已过期 | 归档或顶部加「被 v3/v4 取代」横幅 |
| DEEP-ANALYSIS-20261106.md | 证据（部分得分/饱和）| 11-06 | 新 | 0/1 口径 81.9%（n=72）与 planned 76.2%（80）不同，未标口径；§8/§10/§9 章节顺序错乱 | 保留，补口径注、修章节序 |
| LESSONS-20261102-v2.md | 证据（踩坑）| 11-05 | 部分 | §2.4「已修」vs §六「仍未修」；§0 68.8 / §四 70.0 / §四.5 72.5→78.8 三套补跑数字 | 改写（P0）|
| DEEP-DIVE-20261102.md | 证据（v2 深挖）| 11-03 | 部分 | 「中位 2 文件/64 行」与 NEW-BENCHMARK「3 文件/70 行」冲突（C21）| 保留，标数据源 |
| TEST-EDIT-ANALYSIS-20261102.md | 证据（.snap）| 11-03 | 否（结论仍有效）| 严格口径的 Codex 65.0 与「Codex 整组作废」并存，需注明不参与排名 | 保留 |
| TASKCOUNT-ATTRIBUTION.md | 证据（task_count 归因）| 11-03 | 部分 | 验证用 `deepseek-v4.1-flash` 64K，bench 结论用 hy3 192K；引用处未标（C16）| 保留，加模型/上下文声明 |
| COLLABORATION-CHECK-20261102.md | 证据（协作场景）| 11-03 | 部分 | 同上（deepseek 64K）；「team 也 0 派发」与 TASKCOUNT「显式分工=2」需并列读 | 保留，加声明 |
| COMPLETION-GUARD-RESULT.md | 证据（guard A/B）| 11-04 | 否 | **孤儿（refs=0）**；引用 `evaluation/2026-10-29-task-count-power.md` 为跨仓路径，bench 内不可解析 | 进索引（P1）|
| EXPERIMENT-CONTEXT-AB.md | 参考（P1 设计）| 11-05 | 部分 | 「待 P0 完成后执行」——P0 已完成；摘要触发点写 150.4k，他处 153.6k（C14）| 保留，更新状态 |
| BUDGET-50-PLAN.md | 参考（预算）| 11-03 | 是 | 基于 v2 三 agent 成本；100 题 3.8 天与 SCALE 的 4 天口径不同 | 保留，标注基准批次 |
| CLOUD-COST-ESTIMATE.md | 参考（云成本）| 11-03 | 是 | 312M tokens 是 v1/含 Codex；单 trial 12.8 分钟/并发 2 | 保留，标注批次 |
| HARDWARE-ASSESSMENT-20261103.md | 参考（硬件）| 11-03 | **是** | 与 SCALE 互斥（C11）；磁盘 61.3GB 与 LARGE 28GB/ONBOARDING 30GB 冲突（C10）| 改写或加「已被 SCALE 更正」 |
| SCALE-WITHOUT-UPGRADE.md | 参考（扩样方案）| 11-03 | 部分 | 结论「100 题可行」与 HARDWARE「不可行」互斥；与 LARGE-EVAL（100 题新方案）关系未说明 | 保留，合并进 LARGE-EVAL |
| LARGE-EVAL-SET.md | 参考（大评测集方案）| 11-05 | 新 | **孤儿（refs=0）**；`studies/large-sample-v1*` 已冻结但无索引；磁盘 28GB | 进索引（P1），与 SCALE 合并 |
| NEW-BENCHMARK-ONBOARDING.md | 参考（新题库接入）| 11-06 | 新 | **孤儿（refs=0）**；难度画像「3 文件/70 行」与 DEEP-ANALYSIS「2/64」冲突（C21）；磁盘 30GB | 进索引（P1）|
| PILOT-SWE-EVO-20261106.md | 证据（SWE-EVO 试点）| 11-06 | 新 | **孤儿（refs=0）**；50% 与 LARGE-EVAL 的 swe-evo 15 题配额无交叉引用 | 进索引（P1）|
| CODEX-BASELINE-INVALID.md | 证据（整组作废）| 11-05 | 否 | 无（但 v1 报告仍把 Codex 当有效）| 保留 |
| CLAUDE-CODE-BASELINE.md | 证据（第三基线）| 11-05 | 部分 | 初版误标 DeepSeek 已更正；数字 77.5/73.8 与 STATUS 一致 | 保留 |
| OPENCODE-BASELINE.md | 证据（第四基线）| 11-05 | 部分 | 77.5/73.8/67.5 一致；「模型错配」旧说法已更正 | 保留 |
| EVALUATION-PLAN-20261030.md | 参考（总纲）| 11-02 | **是** | 三 agent（含 Codex）、α/3、题集 `sample-40.json`、§9 停在 v2（C15/C6/C12）| 改写（P1）|
| EXPERIMENT-DESIGN-20261030.md | 参考（设计）| 11-02 | **是** | 三 agent 表、α/3、并发 4–6、max_output 16k/32k 混、§11 停在 v2 | 改写（P1）|
| ITERATION-WORKFLOW.md | 参考（流程）| 10-31 | **是** | 「腾讯混元」推断（C8）；「开发期重建中」已过时；hy3 基线表已作废但仍在正文 | 改写（P1）|
| EVALUATION-METHOD-REVIEW.md | 参考（业界对照）| 10-29 | 否 | 无 | 保留 |
| ROUTING-DRIFT-20261029.md | 证据（路由漂移）| 10-29 | 部分 | 「腾讯 hy3」推断（C8）；`auto-hy3` 与 `deepseek` 关系已由 v3 更正 | 保留，删「腾讯」推断 |
| MULTI-MODEL-PLAN.md | 参考（多模型）| 11-02 | 部分 | 现状写「3 个 harness（含 Codex）」（C15）；第二模型 `DeepSeek-V4.1-Flash` 与 canonical 冲突（C8）| 改写（P2）|
| record-schema.md | 参考（字段）| 10-31 | **是** | `canonical_model=DeepSeek-V4.1-Flash`（C8）| 改写（P1）|
| protocol.md | 历史（v1 预注册）| 11-02 | 是（被 PROTOCOL-V2 取代统计口径）| 「规范模型 DeepSeek-V4.1-Flash」（C8）；开发期跑批不属于其范围 | 保留，顶部已注 |
| fixture-gates.md | 参考（资格门禁）| 10-31 | 部分是 | 正式研究未启动，门禁未使用；与当前 v4 无关 | 保留 |
| REPORT-TEMPLATE.md | 参考（报告版式）| 11-02 | 部分 | 示例仍是 3.2.5/78.8 三组；未含 strict 四组表 | 改写（P1）|

### 1.2 docs/archive（20）

均按 archive/README 的规则「不得直接引用」。问题集中在：**v2 报告的 78.8% 与现行 STATUS 的 76.2% 同屏出现**，以及 archive/README 里部分「为何归档」的描述已被后续事实覆盖（v2 已不再是「最新」）。

| 文档 | 定位 | 是否仍准确 | 处置 |
|---|---|---|---|
| FORMAL-RESULTS-20261031.md | 作废（v1）| 是 | 保留 |
| HANDOFF-20261031.md | 作废（旧交接）| 是 | 保留 |
| STATUS-20261023.md | 历史（基建期）| 是 | 保留 |
| EXPLORATORY-20261029.md | 历史（教训）| 是 | 保留 |
| TUNING-EXPERIMENT-20261031.md | 作废（v2-tuned）| 是 | 保留 |
| restart-v13 / wsl-diagnostic / host-diagnostics / linux-execution / cloud-calibration / calibration / physical-batch-resume / sharded-execution(-design) / terminal-supplement / sensitivity / billing / WORK_PLAN / hypotheses | 历史/一次 | 是 | 保留 |
| archive/README.md | 索引 | 部分：v2/v3/v4 演进未在索引中体现；「现行文档见 docs/」正确 | 补一行「v2 及以后见 docs/」 |

### 1.3 根与产品侧

| 文档 | 定位 | 状态 | 处置 |
|---|---|---|---|
| README.md | 入口 | 见 1.1 | 改写 P0 |
| AGENTS.md | 维护规则+36 条坑 | 见 1.1 | 改写 P1 |
| sayacode/docs/PROMPT-OVERFIT-RISK.md | 证据（3.2.5 规则）| 准确，且是「开发集偏置」的核心证据 | 保留；bench 侧应在 STATUS 局限里链接它 |
| sayacode/docs/VERIFY-20261103.md | 证据（协作验证）| 准确；用的是 deepseek 64K，与 bench hy3 192K 不同 | 保留；bench 引用处补模型声明 |
| sayacode/docs/SUMMARY-FALLBACK-CHECK.md | 证据（摘要降级）| 未见冲突 | 保留 |
| sayacode/docs/COMPLETION-GUARD-AB.md | 证据（guard A/B 产品侧）| 与 bench 的 COMPLETION-GUARD-RESULT 同源，存在两份记录 | 保留；bench 侧引用 |
| sayacode/docs/evaluation/*（19 份）| 历史评测方法 | 未被 bench 索引 | 建议在 bench `docs/archive/README.md` 或 LESSONS 中加一条指针 |

## 2. 冲突矩阵（最重要产出）

编号 C1–C22。每条的「判定」是审计建议，不是既成事实。

| # | 事实 | 文档 A（值 / 位置）| 文档 B（值 / 位置）| 判定与建议 |
|---|---|---|---|---|
| **C1** | SAYACODE 主数字 | **76.2%**（STATUS §2 表、§9；v4-327 报告）| **78.8%**（v3 §一、HANDOFF §1、README 首段、RETROSPECTIVE §1 表、PROTOCOL §5.1 表、AGENTS 环境事实）| 78.8 是 3.2.5，76.2 是 3.2.7；**两套都在 tables 里当「当前」用**。建议：STATUS/v3/HANDOFF/README 统一写「当前 3.2.7 = 76.2%；历史 3.2.5 = 78.8%」并只保留一套主表 |
| **C2** | 制品身份 | 「所有 SAYACODE 正式数字跑的是 3.2.5 wheel」（STATUS §3、HANDOFF §3、AGENTS「评测制品身份」、RETROSPECTIVE §4）| 「SAYACODE 已换成 PyPI 3.2.7」（STATUS §1/§9、v4-327）| **直接互斥**。建议：STATUS §3 改为「3.2.5 批次=78.8%（本地 wheel）；3.2.7 批次=76.2%（PyPI）」；AGENTS/HANDOFF 同步 |
| **C3** | McNemar 最小 p | **p ≥ 0.2266**（STATUS §1）| **p ≥ 0.070**（STATUS §2.1 表、v3 §20 行、OPENCODE-BASELINE）| §1 用的是 3.2.7 三行新配对的最小值，§2.1 含四组旧配对；同一文件内部矛盾。建议 §1 写「旧四组 p≥0.070；3.2.7 跨批次 p≥0.227」|
| **C4** | mini-swe 补跑后 planned | **70.0%**（PROTOCOL §6.2、v2 报告、LESSONS §0/§四）| **85.0%**（STATUS §2、v3 §一、v4-327 §5）| v2 终版 70.0，v4 二次补跑后 85.0（+15pp，12 条 infra 重分类）。PROTOCOL/V2 报告未回填。建议：PROTOCOL §6.2 增「v4 二次补跑：70.0→85.0」|
| **C5** | mini-swe 补跑增量 | **+22.5pp**（RETROSPECTIVE §1、STATUS §6.9、HANDOFF §3.8）| **+15.0pp**（STATUS §2.0、v3 §一补跑表）| 22.5 是 47.5→70.0（v2），15.0 是 70.0→85.0（v4）。两段都真实但未标「哪一段」。建议分两行写 |
| **C6** | Bonferroni α | **α/3 = 0.0167**（PROTOCOL §5.3、STATUS §2.1 末、EVALUATION-PLAN §7、EXPERIMENT-DESIGN §4.4、RETROSPECTIVE §80）| **α/6 ≈ 0.0083**（PROTOCOL §5.1、v3 §31）| 三组时代 α/3，四组 6 对是 α/6；RETROSPECTIVE §6 自己列为未清。建议 PROTOCOL 主文统一「按对数定 α」并改 §5.3 |
| **C7** | 缺失分类数 | **6 类**（PROTOCOL §3 表：infra/no_job/timeout/empty_patch/model_fault/unverified）| **7 类**（RETROSPECTIVE §5.6、AGENTS 坑 33：多 `unattributed`；代码 `MISSING_CLASSES` 7 类）| 协议表缺 `unattributed`。建议 PROTOCOL §3 补第 7 类并写「与代码一致」|
| **C8** | 规范模型身份 | **DeepSeek-V4.1-Flash**（protocol.md:59、record-schema.md:13、MULTI-MODEL-PLAN:32）| **auto-hy3 / hy3（owned_by=workbuddy）**（v3 §五.6、STATUS §5.1、AGENTS:16、CODEX-BASELINE-INVALID:40）；ITERATION:65 与 ROUTING 又写「腾讯混元/腾讯 hy3」| 三套说法：旧规范名、实测网关名、未经证实的厂商归属。建议：canonical 改 `auto-hy3`，「腾讯」删掉或标「未验证」|
| **C9** | 并发 | **2–4，重题 1**（STATUS §5、AGENTS 环境事实、v4-327 §5）| **≤6**（HANDOFF 坑 5/6、MULTI-MODEL §9）；**4–6**（EXPERIMENT-DESIGN §8）；**2**（HARDWARE、SCALE、LESSONS、COMPLETION-GUARD）；**4**（LARGE-EVAL）| 六个值并存，且「≤6」与「2–4」直接矛盾（网络池上限 6 vs 内存上限 2）。建议写「轻题 2–4（内存）/ 网络池 6 为硬上限 / 重题 1」|
| **C10** | 磁盘余量 | **61.3GB**（HARDWARE §一）| **28GB**（LARGE-EVAL §5）；**30GB**（NEW-BENCHMARK §5）；**40GB 阈值**（LESSONS §1.3）；**142GB 可回收**（AGENTS）| 时间点不同但未标日期，读者无法判断。建议只保留一处「当前余量」，其余标「当时值」|
| **C11** | 100 题扩样可行性 | **❌ 不可行**（HARDWARE §五，需 +55GB）| **✅ 可行约 4 天**（SCALE §六，滚动镜像）| 同日两份结论互斥；SCALE 有「实测更正」更晚。建议 HARDWARE 顶部加「已被 SCALE 更正」并链过去 |
| **C12** | 题集文件名 | **`studies/sample-40.json`**（EVALUATION-PLAN §8、EXPERIMENT-DESIGN §3.3/§9、gold_patch_check 默认）| **`studies/sample-40-final.json`**（README、STATUS、HANDOFF、v3/v4 报告）| 实际跑批用 `-final`（换过 4 题）；`sample-40.json` 只是初版。建议 EVALUATION-PLAN/EXPERIMENT-DESIGN 改 `-final` 并注明差异 |
| **C13** | max_output | **16,000**（EXPERIMENT-DESIGN §5.2 mini-swe registry；REPORT-TEMPLATE 示例 3.2.5）| **32,000**（AGENTS、PROTOCOL、STATUS、README）；**64,000**（模型上限，AGENTS/v3）| 三个值对应「模型上限 / profile 配置 / 某 harness registry」，但多处不写主语。建议表格化「上限 64k / profile 32k / mini-swe registry 16k」|
| **C14** | 摘要触发点 | **153,600**（AGENTS、STATUS、v3、ITERATION §8）| **150,400**（EXPERIMENT-CONTEXT-AB §3「摘要触发点 150.4k」）| 150.4k 疑为 188k×0.8 或其他 profile；未标 profile。建议 EXPERIMENT-CONTEXT-AB 改 153.6k 或注明 profile |
| **C15** | 对照 agent 数 | **三 agent（含 Codex）**（EVALUATION-PLAN §7 标题、EXPERIMENT-DESIGN §3.4、MULTI-MODEL §1「3 个 harness」）| **四组（Claude Code/OpenCode，Codex 作废）**（v3/v4、STATUS、README）| 两份总纲仍停在 v4 之前。建议改四组并标 Codex 作废 |
| **C16** | task_count=0 的适用范围 | 「这批题不触发多 agent」（STATUS §6.6、LESSONS §3.5）| TASKCOUNT/COLLABORATION 用 **deepseek 64K** 验证「team 也 0 派发」，显式分工题 `task_count=2`（VERIFY-20261103）| 结论成立，但「0」是 hy3+SWE 题、「2」是 deepseek+显式场景，引用处未标模型。建议所有引用加「hy3/192k 与 deepseek/64k 不同」声明 |
| **C17** | 开发期 vs 对外成绩边界 | 「78.8/70.0/68.8 都是开发期诊断，不得对外」（PROTOCOL §1、README 首段）| v3 §六给出「可写进简历的口径」（78.8%、同量级、不显著），但未走 §7 冻结签收 | 简历口径可视为「对外」，与「未冻结」冲突。建议 v3 §六 加「仅描述性，非冻结成绩」或走签收 |
| **C18** | LESSONS 内部 | §2.4 标题「已修（2026-11-05）」+ 正文「已修」| §六 第 2 条「仍未修」；AGENTS 坑 18 也写「已修」| 同一文件自相矛盾。建议删 §六 的「仍未修」或改「已修」|
| **C19** | 补跑数字三套 | §0「mini 47.5→68.8（+21.3）」| §四.5「SAYACODE 72.5→78.8」；§四.1「mini 85.9%，64/80」| 68.8/72.5/85.9 均非终版（70.0/67.5→78.8/84.8）。建议整节标注「含定稿前中间值」|
| **C20** | 旧 40 题难度画像 | **中位 2 文件 / 64 行**（RETROSPECTIVE §82、AGENTS:20、DEEP-ANALYSIS §2、STATUS §6.2）| **中位 3 文件 / 70 行**（NEW-BENCHMARK §7 表）| 两个统计口径（是否含测试/CI 文件？）。建议注明统计脚本与是否含测试文件 |
| **C21** | 成本基数 | **312M tokens**（CLOUD-COST-ESTIMATE，v2 三 agent 含 Codex）| 四组/3.2.7 成本另算（DEEP-ANALYSIS §8.6 未给总成本；v3 单任务 1.43M tokens）| 成本文档未随四组更新。建议标「v2 三 agent 基数」|
| **C22** | v2 严格口径 | **SAYACODE 78.8 / mini 65.0 / Codex 65.0**（archive/FORMAL-RESULTS-20261102-v2、TEST-EDIT §三）| **v4 strict：78.8 / 80.0 / 73.8 / 67.5**（STATUS/v3）| 名称相同「strict」但批次不同；archive 的 v2 数字易被误当现行。建议 archive 顶部横幅标注「v2 批次，非现行」|

## 3. 孤儿文档与死链

### 3.1 死链：0

对 55 份 md（35 在册 + 20 归档）+ README + AGENTS 的全部 Markdown 相对链接逐个解析，**全部存在**（含 `docs/archive/` 的 `../` 与 `../../` 修正）。无失效相对路径。

**隐性路径问题（非 md 链接，但仍会误导）**：

- `COMPLETION-GUARD-RESULT.md:17` 写 `evaluation/2026-10-29-task-count-power.md`——该路径在 **bench 仓不存在**（在产品仓 `C:\develop\sayacode\docs\evaluation\` 下）。读者按 bench 相对路径找不到。
- `PILOT-SWE-EVO-20261106.md:74-75` 的脚本名（`grep_search` 输出上限等）未给路径；可接受但缺证据链接。

### 3.2 孤儿文档（refs=0，无任何文档引用）

| 文档 | 内容价值 | 是否被更新文档覆盖 | 处置 |
|---|---|---|---|
| COMPLETION-GUARD-RESULT.md | guard A/B 的唯一记录（+10pp p=0.289、token +53%）| 否 | **进 README 索引**（P1），非删除 |
| LARGE-EVAL-SET.md | 100 题大评测集方案（`studies/large-sample-v1*` 已冻结）| 否，是最新方案 | **进索引**并与 SCALE 合并（P1）|
| NEW-BENCHMARK-ONBOARDING.md | 新题库接入指南（SWE-EVO 实战）| 否 | **进索引**（P1）|
| PILOT-SWE-EVO-20261106.md | SWE-EVO 试点（50%，链路打通）| 否 | **进索引**；与 DEEP-ANALYSIS 的「换题库」叙事合并（P1）|

### 3.3 索引漏项（README 声明「只列现行文档」但未含）

`DEEP-ANALYSIS-20261106`、`FORMAL-RESULTS-20261106-327`、`EXPERIMENT-CONTEXT-AB`、`COMPLETION-GUARD-RESULT`、`LARGE-EVAL-SET`、`NEW-BENCHMARK-ONBOARDING`、`PILOT-SWE-EVO-20261106`（共 7 份）。README 索引 29 条，漏 7 条现行文档。

## 4. 同一事实多处重复维护

| 事实 | 维护位置 | 建议单一源 |
|---|---|---|
| 四组 planned/observed/strict/snap/缺失 | **7 处**：STATUS §2、RETROSPECTIVE §1 表、README 首段、HANDOFF §1、v3 §一、PROTOCOL §5.1、AGENTS 环境事实 | STATUS §2 为唯一主表；其余改写为「见 STATUS」 |
| 制品身份（3.2.5/3.2.7）| 5 处：STATUS §3/§9、HANDOFF §3、AGENTS、README、RETROSPECTIVE §4 | 新建 `docs/ARTIFACT-IDENTITY.md` 或 STATUS §3，其余引用 |
| 坑清单 | AGENTS（36 条）与 LESSONS（§二/§三）双维护；AGENTS 自己写「两份都要写」| LESSONS 为唯一坑库；AGENTS 只留「Top 10 + 链接」|
| 题集/难度画像 | EVALUATION-PLAN、EXPERIMENT-DESIGN、DEEP-ANALYSIS、NEW-BENCHMARK、RETROSPECTIVE、AGENTS | 新建 `docs/DATASET-CARD.md`（题集名/规模/中位改动/gold 结论）|
| 预算/成本/硬件 | BUDGET、CLOUD、HARDWARE、SCALE、LARGE-EVAL | 合并为 `docs/RESOURCE-BUDGET.md`，其余删除或标历史 |

## 5. RETROSPECTIVE §6 十条文档债的「真还清」核验

> 判定标准：打开当前文件，确认「旧问题消失」且「没有产生新的同类问题」。不信 ✅。

| # | §6 原问题 | 当前实际（证据）| 是否还清 | 残留 |
|---|---|---|---|---|
| 1 | STATUS 停在 v2 三 agent、Codex 68.8 当有效 | STATUS 已四组三口径、Codex 标注作废（STATUS:17、56）| **大部分** | 3.2.7 与 3.2.5 双数字未统一（C1/C2）；§1 p≥0.2266 自相矛盾（C3）|
| 2 | HANDOFF 写「v2 已完成」、19 缺口 | HANDOFF 已 v4（HANDOFF:8）| **否** | 仍写 78.8/3.2.5（HANDOFF:12、30）；「下一步用 3.2.7 重跑」已完成未更新（HANDOFF:85）；并发 ≤6（:68）|
| 3 | README 首段三 agent、索引缺 8 份 | README 已 v4、索引 29 条 | **部分** | 首段/「两个事实」仍 3.2.5（README:7、9）；索引漏 7 份现行（§3.3）|
| 4 | AGENTS 坑 24 写「主表仍 planned」、并发 4–6 过时 | 坑 24 已改 planned+strict（AGENTS:59）；并发 2–4/重题1（:27）| **大部分** | 「所有 SAYACODE 数字=3.2.5」（AGENTS:23）未同步；坑 23 仍是 v2 数字（:58）|
| 5 | LESSONS §6 已修未标记、内部数字冲突 | §6 已回填（:168-175）| **否** | §2.4「已修」vs §六「仍未修」；§0/§四 三套补跑数字（C18/C19）|
| 6 | PROTOCOL §3 分类代码没有、strict 口径冲突、α/3 | §5.1 已加 strict 表与 α/6；§6 加 infra 优先（:99）| **部分** | §5.1 表仍是 3.2.5 的 78.8；§6.2 mini 70.0 未含 85.0；§7.3 checklist 漏 strict；§0/§2「planned 唯一主报」与 §5.1 张力 |
| 7 | EVALUATION-PLAN/EXPERIMENT-DESIGN 三 agent、题集名、max_output 矛盾 | **未改**（EVALUATION-PLAN:49-53、EXPERIMENT-DESIGN:69、123、154）| **否** | 三 agent、α/3、`sample-40.json`、并发 4–6 |
| 8 | ROUTING/ITERATION「腾讯 hy3」与 DeepSeek 标注冲突 | **未改**（ITERATION:65「腾讯混元」、ROUTING 第六节）| **否** | 厂商归属未验证；与 v3 更正后的 `owned_by=workbuddy` 并存 |
| 9 | record-schema/protocol canonical_model 冲突 | **未改**（record-schema:13、protocol:59）| **否** | canonical 仍是 DeepSeek-V4.1-Flash |
| 10 | HARDWARE vs SCALE 磁盘/100 题结论互斥 | **未改**（HARDWARE:20/55 vs SCALE:65）| **否** | 两文件同日互斥，均未标「被更正」|

**合计：3 条大部分还清（1、4 及 3 的一半），3 条部分（3、6），4 条完全未还清（7、8、9、10）。** §6 把 #1–#4 标 ✅、#5 ✅，实际 #5 未还清、#2 引入了新债（3.2.7 未同步）。

## 6. 含糊表述 / 推断写成事实 / 缺证据链接（文件:行号）

| 位置 | 问题 | 类型 |
|---|---|---|
| `STATUS.md:7` | 「所有配对 McNemar 均不显著（p ≥ 0.2266）」与 `:38-48` 表中 p=0.070、0.118 矛盾 | 推断/数字错误 |
| `STATUS.md:3` | 顶部「更新 2026-11-05」，但 `:140-159` 是 11-06 的 P0 结果 | 元信息过时 |
| `STATUS.md:70-73` | §3「所有 SAYACODE 数字跑的是 3.2.5」与 §9「3.2.7 已重跑 76.2%」互斥 | 事实冲突 |
| `STATUS.md:120` | §7.2 仍把「用 3.2.7 重跑」列为下一步（已完成）| 过时 |
| `HANDOFF.md:1` | 标题 11-05，未含 11-06 批次 | 元信息过时 |
| `HANDOFF.md:85` | 「下一步：用 3.2.7 重跑」——已完成 | 过时 |
| `README.md:9` | 「两个必须随结论声明的事实：① SAYACODE 数字跑的是 3.2.5」——已不适用于 3.2.7 批次 | 过时 |
| `AGENTS.md:23` | 「所有 SAYACODE 正式数字跑的是 3.2.5」 | 过时 |
| `PROTOCOL-V2.md:83-87` | §5.1 表 SAYACODE 78.8（3.2.5）未标批次 | 口径缺失 |
| `PROTOCOL-V2.md:102` | §6.2 mini-swe 补跑后 70.0，未含 v4 的 85.0 | 过时 |
| `PROTOCOL-V2.md:128` | §7.3 checklist 只列 planned/observed/task_macro，漏 strict | 与 §5.1 不一致 |
| `PROTOCOL-V2.md:9` | §0「planned 唯一主报」与 §5.1「strict 必须同表」表述张力 | 含糊 |
| `EVALUATION-PLAN-20261030.md:49-53` | §7 标题仍「vs Codex CLI」，α/3，未提 Claude Code/OpenCode | 过时 |
| `EVALUATION-PLAN-20261030.md:59` | §8 题集写 `sample-40.json`（实际 `-final`）| 错误 |
| `EVALUATION-PLAN-20261030.md:73` | §9 状态停在 v2（78.8/70.0/68.8），未提 v3/v4 | 过时 |
| `EXPERIMENT-DESIGN-20261030.md:69-70` | α/3、18–20pp（三组假设）| 过时 |
| `EXPERIMENT-DESIGN-20261030.md:123` | 并发 4–6（与 STATUS 2–4 冲突）| 冲突 |
| `EXPERIMENT-DESIGN-20261030.md:154` | §11 仍写「v1 结论作废、v2 已完成」 | 过时 |
| `ITERATION-WORKFLOW.md:61` | 「当前 bench 处于开发期重建中……正重跑 v2」 | 过时 |
| `ITERATION-WORKFLOW.md:65` | 「hy3（腾讯混元）」——厂商归属未验证 | 推断当事实 |
| `ROUTING-DRIFT-20261029.md` 第六节 | 「腾讯 hy3」 | 推断当事实 |
| `protocol.md:59` / `record-schema.md:13` | `DeepSeek-V4.1-Flash` 作为规范模型 | 与实测冲突 |
| `LESSONS-20261102-v2.md:9,147,150` | 68.8% / +21.3pp / 72.5%→78.8% 三套补跑中间值 | 中间值未标 |
| `LESSONS-20261102-v2.md:99` vs `:171` | §2.4「已修」vs §六「仍未修」 | 自相矛盾 |
| `HARDWARE-ASSESSMENT-20261103.md:20,55` | 100 题「❌ 磁盘不够」 | 已被 SCALE 更正未标 |
| `NEW-BENCHMARK-ONBOARDING.md:95` | 旧 40 题「3 文件/70 行」 | 与 2/64 冲突未标口径 |
| `DEEP-ANALYSIS-20261106.md:11-12` | 81.9%/84.9% 用 n=72/73，与 planned 76.2%（80）不同分母 | 口径未标 |
| `DEEP-ANALYSIS-20261106.md` §8/§10/§9 | 章节顺序 1-6→8→10→9 | 格式 |
| `COMPLETION-GUARD-RESULT.md:17` | `evaluation/2026-10-29-task-count-power.md` 为跨仓路径 | 隐性死链 |
| `RETROSPECTIVE-20261105.md:80` | 「OpenCode vs SAYACODE p=0.070 未过 α/3≈0.017」——四组 6 对应 α/6 | 口径混用 |
| `COLLABORATION-CHECK/A TASKCOUNT` | 验证用 deepseek 64K，引用处未标 | 缺上下文 |
| `v3 §六` | 「可写进简历的口径」未注明「非冻结成绩」 | 边界含糊 |

## 7. 处置建议（按优先级）

### P0（会误导当前结论，1–2 小时内可改完）

1. **STATUS**：§1 p 值改「旧四组 ≥0.070 / 新配对 ≥0.227」；§2.0 补跑表标制品；§3 拆成「3.2.5 批次 78.8 / 3.2.7 批次 76.2」；§5「评测制品固定 3.2.5」改「双制品」；§7.2 删「用 3.2.7 重跑」；顶部更新日期改 11-06。
2. **HANDOFF**：主表改「3.2.7=76.2 / 3.2.5=78.8」；§3 制品；§7.2 删除；并发统一为「轻题 2–4 / 网络池上限 6 / 重题 1」；补 11-06 批次与 SWE-EVO 试点。
3. **README**：首段改「当前 3.2.7=76.2%，历史 3.2.5=78.8%」；「两个必须声明的事实」同步；索引补 7 份。
4. **PROTOCOL-V2**：§5.1 表加 3.2.7 行并标批次；§6.2 补 v4 二次补跑 70.0→85.0；§7.3 加 strict；§3 补 `unattributed`（7 类）；α 统一为「按对数定，4 组=α/6」。

### P1（口径统一，半天）

5. **AGENTS**：环境事实「所有数字 3.2.5」改双批次；坑 23 数字改 70.0/85.0；并发表与 STATUS 对齐。
6. **LESSONS**：删除 §0/§四 的三套中间值，统一为终版；§六 第 2 条改「已修」（与 §2.4/AGENTS:53 一致）。
7. **EVALUATION-PLAN / EXPERIMENT-DESIGN**：三 agent → 四组（Codex 作废）；α/3 → α/6；`sample-40.json` → `-final`；并发 4–6 → 2–4/重题 1；§9/§11 更新到 v4 + 3.2.7。
8. **record-schema / protocol / MULTI-MODEL**：canonical 统一 `auto-hy3`；删「腾讯」或标「未验证」。
9. **HARDWARE vs SCALE**：HARDWARE 顶部加「100 题结论已被 SCALE 更正（滚动镜像可行）」；磁盘数字统一标日期。
10. **孤儿入库**：README 补 7 份索引；`COMPLETION-GUARD` 的跨仓路径改绝对/产品仓路径。

### P2（结构性重构）

11. 建 `docs/RESULTS-LEDGER.md` 作为四组数字唯一源；STATUS/RETROSPECTIVE/README/HANDOFF/v3/PROTOCOL 全部改为引用。
12. 建 `docs/DATASET-CARD.md`（题集名/规模/中位改动/gold 结论/饱和率/区分度），替代散落在 6 份文档里的题集画像。
13. 建 `docs/RESOURCE-BUDGET.md`，合并 BUDGET/CLOUD/HARDWARE/SCALE/LARGE-EVAL，其余标历史。
14. 把产品仓 `docs/evaluation/`（19 份）纳入 bench 的 archive 指针，避免跨仓孤儿。

## 8. 审计方法与可复现

- 清点：`Get-ChildItem docs -File`（35）、`docs/archive`（20）、根 README/AGENTS、产品仓 `docs/{PROMPT-OVERFIT-RISK,VERIFY-20261103,SUMMARY-FALLBACK-CHECK,COMPLETION-GUARD-AB}.md`。
- 交叉核对：对「SAYACODE 数字 / 3.2.x / 模型身份 / 并发 / α / 缺失类 / 题集名 / max_output / 磁盘」逐主题 `Select-String` 全仓扫描，人工判读冲突。
- 死链：正则提取 Markdown 链接目标，跳过 `http(s)/mailto/#`，按文件所在目录解析相对路径并 `Test-Path`——55 份 md 全部通过。
- 引用度：对每份 docs 文件统计「其他 md 中出现其文件名」的次数（refs），refs=0 判孤儿。
- RETROSPECTIVE §6：逐条打开对应文件，核对「问题是否消失」+「是否产生新同类问题」。
- 本文件不修改任何现有文档；P0/P1 的执行由 Lead 决定。
