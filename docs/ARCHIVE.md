# ARCHIVE：docs 腐朽内容清单（2026-11-11）

> **用途**：登记 `docs/` 下「结论已过时、已被推翻、或已被取代」的文档，避免后来者继续引用旧数字。
> **本轮不删除、不移动任何文件**——只出清单。后续可按本表把对应文档移入 `docs/archive/`（或加「已作废」横幅）。
> **判定规则**：
> - **已推翻**：文档的核心结论被证据推翻（整篇不能再用）。
> - **部分推翻**：核心结论部分成立、部分被推翻（引用时必须逐条看）。
> - **已被取代**：结论方向仍成立，但数字/口径已被更新的文档取代（用新文档）。
> - **有效**：当前仍可引用（数字需按各自口径）。
> - **未复核**：本次未逐条重算其数字，不敢判定（引用前需自行复核）。
> **证据**：只引用可复算的产物路径；不确定的一律标「未复核」，不猜。

## 0. 一句话统计

`docs/` 在册 **57** 份 Markdown（不含 `docs/archive/` 的 20 份历史文档、不含 `docs/review/` 的复盘报告）。

| 状态 | 份数 | 说明 |
|---|---:|---|
| **已推翻** | **9** | 整篇核心结论不成立，必须停止引用 |
| **部分推翻** | **6** | 部分结论不成立，引用需逐条核对 |
| **已被取代** | **4** | 方向仍对，但数字/口径用新文档 |
| **有效** | **30** | 当前可引用（按各自口径） |
| **未复核** | **8** | 本次未逐条重算，引用前需复核 |
| 合计 | 57 | |

> 「已推翻 + 部分推翻」共 **15** 份；若只算「整篇已推翻」是 **9** 份。

---

## 1. 已推翻（9 份，停止引用）

| # | 文档 | 日期 | 核心结论（旧） | 被什么推翻（证据） |
|---:|---|---|---|---|
| 1 | `FORMAL-RESULTS-20261102-v2.md` | 2026-11-02 | 三 agent：SAYACODE 78.8% / mini-swe 70.0% / Codex 68.8%（planned）；「strict 65.0/65.0」 | `strict` 前提被 642/642 个 `tests/test.sh:97-105` 证伪（`C:\sb\tmp\audit\challenge\CHALLENGE.md` §0、`docs/review/2026-11-07/RETROSPECTIVE-20261107.md` §四.1）；Codex 组整组作废（`CODEX-BASELINE-INVALID.md`）；结论已被 v3/v4 取代 |
| 2 | `FORMAL-RESULTS-20261105-v3.md` | 2026-11-05 | 四组 planned 78.8/85.0/77.5/75.0、**strict 78.8/80.0/73.8/67.5**、三种口径三种排名、「可写进简历」 | ① strict 前提证伪（同上，642/642 `test.sh:97-105`）；② 四组跨两个批次（SAYACODE 来自 v4-327、三基线来自 v2-325，`STATUS.md:24` 自认）；③ 简历口径未走冻结签收（`PROTOCOL-V2 §1`）。见 R1 §四.1–§四.2 |
| 3 | `FORMAL-RESULTS-20261106-327.md` | 2026-11-06 | 3.2.7 planned/strict 76.2%；「3.2.6/3.2.7 含三项修复（含 `41b1e38`）」；「修复没有可测收益」 | `41b1e38`（11-04 13:22）晚于发布提交 `ba43e04`（11-04 03:46），且 PyPI 3.2.7 无 git tag；`git diff --stat v3.2.5 ba43e04 -- src/` 只含两项修复（摘要降级 + 提示一致性）→ 见 `docs/review/2026-11-07/RETROSPECTIVE-20261107.md` §摘要第 4/5 条、R4 §2；「无效果」改为「未检出 / 作用面为零」 |
| 4 | `TEST-EDIT-ANALYSIS-20261102.md` | 2026-11-02（11-06 加更正横幅） | 「`__snapshots__/*.snap` 不被 verifier 重置，改快照对 reward 有效」；「靠改快照通过」计数 mini 4 / Codex 3 | 642/642 个 `test.sh:97-105` 对 `*__snapshots__/*` 执行 `git checkout HEAD`；`:101` 的 `__NONE__` 哨兵使跳过分支不可达（`C:\sb\tmp\audit\challenge\CHALLENGE.md` §0/§2.3）。**注意：文中「测试代码被重置」这半仍然成立**，见 §2 |
| 5 | `DEEP-DIVE-20261102.md` | 2026-11-02 | 语义 diff 的「top 1–3 是改测试/快照后通过」；一过一败 2 随机/3 系统性 | ① 「改快照通过」随 `.snap` 重置证伪（同上）；② 方差/成本部分仍有效，但「snap pass」相关计数全废。见 `docs/review/2026-11-07/RETROSPECTIVE-20261107.md` §四.1 |
| 6 | `HARDWARE-ASSESSMENT-20261103.md` | 2026-11-03 | 「100 题扩样 ❌ 不可行（磁盘不够，需 +55GB）」 | 同日 `SCALE-WITHOUT-UPGRADE.md` 更正：保留 40 题镜像 + 内部 49GB 空闲 + 每片 20 题滚动 → **✅ 可行约 4 天**（`SCALE-WITHOUT-UPGRADE.md` §六） |
| 7 | `METHOD-TEST-LEVEL-METRICS.md` | 2026-11-09 | F2P/P2P 指标 +7.36pp / +2.21pp | **文档自标「数字已被 V2 取代」**：受作者自己的匹配 bug 影响（`METHOD-TEST-LEVEL-METRICS.md` 顶部横幅；修正版见 `METHOD-TEST-LEVEL-METRICS-V2.md`）|
| 8 | `RETROSPECTIVE-20261105.md` | 2026-11-05 | 「四组同量级、strict 排名、检测 10pp 需 330 题」等 | 部分：strict 前提证伪、四组跨批次、「330 题在 bench 内无推导（产品仓有）」→ 见 `docs/review/2026-11-07/RETROSPECTIVE-20261107.md` §三（A/B/C 三分法）、§五 §六。**作为历史演进记录仍可读，但引数字前必须看 R1** |
| 9 | `RESULT-PROV2-4AGENTS-FINAL.md`（旧版，commit `5d9dd3d`） | 2026-11-11 17:40 | 「有效通过率」claude 83.3 / mini 82.4 / sayacode 75.9 / opencode 75.7；「sayacode 与 opencode 持平」 | 已由**本文同目录的新版**（2026-11-11 重写）取代：长跑零产出被当基建失败，分母 29→34，通过率 75.9%→64.71%，「持平」不成立。新版见 [RESULT-PROV2-4AGENTS-FINAL.md](RESULT-PROV2-4AGENTS-FINAL.md) §0；旧版内容留在 git `5d9dd3d` |

---

## 2. 部分推翻（6 份，引用需逐条核对）

| # | 文档 | 日期 | 仍成立的部分 | 已被推翻/降级的结论 | 证据 |
|---:|---|---|---|---|---|
| 10 | `DEEP-ANALYSIS-20261106.md` | 2026-11-06 | 0/1 口径丢失信息、部分得分连续量、40 题从未触发上下文摘要（峰值 102k–127k < 触发线 150.4k）| 「部分得分 94–99% 说明基本做对」降级为描述性（B 类）；饱和题 **26 vs 28** 两套阈值矛盾；token 字段与 `behavior.json` 差 16.2% | `docs/review/2026-11-07/RETROSPECTIVE-20261107.md` §三（B 类）、§四.2 数据层 #4/#5 |
| 11 | `TASKCOUNT-ATTRIBUTION.md` | 2026-11-03 | `task_count=0` 不是工具坏了；是「任务规模 + 触发条件 + 模型选择单干」 | 「SWE-bench 这批题不触发协作」被 `VERIFY-20261103.md` 部分修正：显式分工题 `task_count=2`；且验证用的是 deepseek 64K，非 hy3 192K | `docs/TASKCOUNT-ATTRIBUTION.md` §一；`C:\develop\sayacode\docs\VERIFY-20261103.md` §3 |
| 12 | `COLLABORATION-CHECK-20261102.md` | 2026-11-02 | single 变体不派发、方向性验证 | 「team 变体 0 派发」被 TASKCOUNT 的显式分工 `task_count=2` 修正；用 `deepseek-v4.1-flash` 65536 ctx（非 hy3 192k）| `docs/COLLABORATION-CHECK-20261102.md` §一；同 #11 |
| 13 | `FAILURE-ANALYSIS-MISSED-FILES.md` | 2026-11-08 | 「漏改」是当时 14 条失败里的主要类型（8/14）；「验证不是主要矛盾」 | 「影响面清单能提升通过率」被 `EXPERIMENT-IMPACT-CHECKLIST.md` 证伪：覆盖率 +6.7pp，但通过率 +2.5pp、p=1.0 | `docs/EXPERIMENT-IMPACT-CHECKLIST.md` 顶部结论 |
| 14 | `COMPLETION-GUARD-RESULT.md` | 2026-11-04 | guard 确实触发（90%）、token +53%；「不默认开启」 | 来源产品 3.2.6、20 题，结论仅方向性；「+10pp」不显著（p≈0.29）不得当收益 | `docs/COMPLETION-GUARD-RESULT.md` §一/§三 |
| 15 | `ANALYSIS-VERIFICATION-IS-NOT-THE-BOTTLENECK.md` | 2026-11-09 | 「验证行为不是瓶颈」有命令级证据（通过/失败跑 build 比例 70% vs 69%）| 其中引用的「三轮干预」结论依赖 `EXPERIMENT-*` 的旧数字，需按各自文档看 | 本文 §2；`docs/EXPERIMENT-IMPACT-CHECKLIST.md` |

---

## 3. 已被取代（4 份，方向对但数字/口径用新文档）

| # | 文档 | 日期 | 旧数字/口径 | 用哪份新文档 |
|---:|---|---|---|---|
| 16 | `RESULTS-LEDGER.md` 早期快照 | 2026-11-07 | 四组数字 | 以当前 `RESULTS-LEDGER.md`（2026-11-07 之后仍在更新）与 `REBUILD-LEDGER.md` 的最新重建为准；引用前先看 §5「已知数据缺陷」 |
| 17 | `RETROSPECTIVE-20261105.md`（作为数字源） | 2026-11-05 | 四组/补跑/330 题 | 数字用 `RESULTS-LEDGER.md`；结论演进用 `docs/review/2026-11-07/RETROSPECTIVE-20261107.md`（历史记录仍保留）|
| 18 | `EXPERIMENT-PROV2-4AGENTS.md`（旧版） | 2026-11-10 | 「运行中」+ 仅两条缺陷 | 已由本轮重写版取代（含 c8dba0e 四处缺陷与口径）|
| 19 | `STATUS.md`（2026-11-07 之前的快照） | 2026-11-07 | 四组 planned/strict | 以当前 `STATUS.md`（已按 11-07 复盘修正，strict 废除）为准；`strict` 不得引用 |

> 说明：#16/#17/#19 是「同一文件随版本演进」的情况，不是独立旧文件；登记在此是为了提醒「引用前确认版本/日期」。

---

## 4. 有效（30 份，当前可引用）

| 文档 | 一句话 |
|---|---|
| `PROTOCOL-V2.md` | 现行协议（planned/observed/partial、7 类缺失、strict 废除）|
| `protocol.md` | v1 预注册（历史，统计口径以 PROTOCOL-V2 为准）|
| `STATUS.md` | 当前状态（11-07 复盘修正版）|
| `RESULT-PROV2-4AGENTS-FINAL.md` | **本次重写**：pro-v2 40 题的正确口径与结论更正 |
| `EXPERIMENT-PROV2-4AGENTS.md` | **本次重写**：执行记录 + 已知缺陷（c8dba0e）|
| `RESULTS-LEDGER.md` | 对外数字唯一真相源（含 §5 数据缺陷）|
| `REBUILD-LEDGER.md` | 重建 ledger 的操作卡 |
| `DATASET-CARD.md` | 题集卡片与饱和/区分度口径 |
| `METHOD-TEST-LEVEL-METRICS-V2.md` | 修正版的 F2P/P2P 方法 |
| `AUDIT-RECOMPUTE.md` | impact-350 vs v2v-main 独立复核（20 题 × 2）|
| `ANALYSIS-LINE-LEVEL-DIFF.md` | 33 条失败的行级分类（被 ANALYSIS-VERIFICATION 引用）|
| `ANALYSIS-COST-OPPORTUNITIES.md` | 成本/延迟优化空间（原始 audit 解析）|
| `EXPERIMENT-CONTEXT-AB-RESULT.md` | 长上下文 A/B：clean 100% vs noise 58.3%（n=12）|
| `EXPERIMENT-EXPLORE-GUARD-RESULT.md` | 探索护栏闭环：58.3%→83.3%、空 patch 2/12→0/12 |
| `EXPERIMENT-IMPACT-CHECKLIST.md` | 影响面清单：覆盖率 +6.7pp、通过率 +2.5pp p=1.0 |
| `EXPERIMENT-PROMPT-SCALING.md` | 系统提示精简：负面结果 |
| `EXPERIMENT-PROMPT-V2.md` | 系统提示 v2：精简做对了就有效 |
| `EXPERIMENT-PROMPT-V2-SCALED.md` | v2 扩样本：优势消失（Δ=0，p=1.0）|
| `EXPERIMENT-TODO-COMPRESSION.md` | TodoList 压缩：成本优化（-40% 时间）|
| `EXPERIMENT-TOOL-BATCHING.md` | 工具并行度：无效、反而变差 |
| `EXPERIMENT-CONTEXT-AB.md` | 长上下文 A/B 设计（对应 RESULT 已跑）|
| `FAILURE-MODE-EXPLORE-ONLY-20261107.md` | 「只读不写」失效模式诊断（原始目标）|
| `PILOT-SWE-EVO-20261106.md` | SWE-EVO 试点：链路可用、静态预测 60% 不可靠（n=10）|
| `NEW-BENCHMARK-ONBOARDING.md` | 新题库接入指南（含选样偏差警告）|
| `LARGE-EVAL-SET.md` | 100 题大评测集设计（未开跑）|
| `CLAUDE-CODE-BASELINE.md` | 第三基线接入（协议/限制/复现）|
| `CODEX-BASELINE-INVALID.md` | Codex 整组作废的证据 |
| `OPENCODE-BASELINE.md` | 第四基线接入（provider-agnostic）|
| `MISJUDGMENTS-20261109.md` | 两次误判的更正记录（本身是更正，有效）|
| `SCALE-WITHOUT-UPGRADE.md` | 不升级硬件的扩样方案（推翻 HARDWARE 的 100 题结论）|
| `BUDGET-50-PLAN.md` / `CLOUD-COST-ESTIMATE.md` | 预算/成本估算（基于 v2 三 agent，引用需标基数）|

> 其余方法/参考文档（`EVALUATION-PLAN-20261030.md`、`EXPERIMENT-DESIGN-20261030.md`、`ITERATION-WORKFLOW.md`、`EVALUATION-METHOD-REVIEW.md`、`fixture-gates.md`、`ROUTING-DRIFT-20261029.md`、`MULTI-MODEL-PLAN.md`、`REPORT-TEMPLATE.md`、`record-schema.md`、`LESSONS-20261102-v2.md`、`HANDOFF.md`、`TASKCOUNT-ATTRIBUTION.md`）**多数仍有效**，但个别口径按 §2/§3 处理；其中 `EVALUATION-PLAN/EXPERIMENT-DESIGN` 仍写「三 agent + Codex」，属**部分过时**（未在本表单列，引用时以 STATUS/PROTOCOL-V2 为准）。

---

## 5. 未复核（8 份，本次未逐条重算）

| 文档 | 未复核的原因 | 建议 |
|---|---|---|
| `ANALYSIS-LINE-LEVEL-DIFF.md` | 24.5KB 行级分析，本次未逐条重算其 33 条分类 | 引用前用 `C:\sb\tmp` 的脚本复核 |
| `ANALYSIS-COST-OPPORTUNITIES.md` | 25.5KB 成本分析，未重算 3,091 次调用 | 同上 |
| `DATASET-CARD.md` | 口径源，但本次未重跑 `dataset_stats.py` | 引用前重跑脚本 |
| `AUDIT-RECOMPUTE.md` | 20 题 × 2 的复核表未重算 | 可用其 §6 脚本复现 |
| `DEEP-ANALYSIS-20261106.md` 的 §8 行为层 | token 字段与 `behavior.json` 不符（R1 §四.2 #4） | 引用行为数据前先核 `behavior.json` |
| `PILOT-SWE-EVO-20261106.md` 的难度画像 | 「4 倍文件/2.5 倍行数」只基于 gold 规模，未控制可解性 | 换题库决策前重算 usable 分布 |
| `NEW-BENCHMARK-ONBOARDING.md` 的难度画像 | 与 DEEP-ANALYSIS 的「2 文件/64 行」冲突（本文写 3 文件/70 行） | 统一统计口径（是否含测试/CI 文件）后重算 |
| `RESULTS-LEDGER.md` §3.5–§3.10 的实验小节 | 本次未逐条复算（成本/A-B/提示实验） | 用 `REBUILD-LEDGER.md` 重建主表；实验小节按各自来源文档 |

---

## 6. 已归档（`docs/archive/`，20 份）

`docs/archive/` 下的 20 份已在 [archive/README.md](archive/README.md) 逐份说明「为何归档、能否引用」。**本表不重复**；一句话：全部为 v1 及更早的作废/历史文档，**不得直接引用其数字**。

---

## 7. 处置建议（按优先级，待 Lead 决定）

1. **P0（立刻）**：把 §1 的 9 份「已推翻」文档移到 `docs/archive/`，或在顶部加「⛔ 已作废，见 ARCHIVE.md」横幅。它们现在仍在 `docs/` 根，最容易被误引用。
2. **P1**：§2 的 6 份「部分推翻」在顶部加「引用前读 ARCHIVE.md §2」提示。
3. **P1**：`EVALUATION-PLAN-20261030.md`、`EXPERIMENT-DESIGN-20261030.md` 的「三 agent + Codex」改为四组（Codex 作废）——这两份未进 §1，但口径过时。
4. **P2**：§5 的 8 份「未复核」逐份补一次复算，再定状态。
5. **长期**：把「结论状态」作为每份文档头部的必填字段（`status: 有效/部分推翻/已推翻/未复核` + 证据路径），并在 CI 检查「已推翻文档不得被 `docs/` 根文档链接」。

> **本轮边界**：只新增本清单，未移动/删除/改写任何现有文档（任务要求只登记）。`RESULT-PROV2-4AGENTS-FINAL.md` 与 `EXPERIMENT-PROV2-4AGENTS.md` 的改写是单独任务，已在各自 commit 完成。
