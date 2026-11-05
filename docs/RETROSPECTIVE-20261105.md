# RETROSPECTIVE：从 v1 的假差距到四组同量级（2026-11-05）

> 目的：把这一轮评测工作**从起点到现在的全部主线、结论、作废项、遗留债**放在一处，避免后来者（或三个月后的自己）再被过期文档带偏。
> 原则：只写有证据的事实；每条结论标注**证据位置**与**当前是否有效**；无法证实的写「未验证」。
> 状态：本文件是最新权威复盘，**与它冲突的旧文档以本文件为准**（冲突清单见 §6）。

## 0. 一句话

我们从一个**假的 17.4pp 差距**（v1：SAYACODE 68.8% vs 基线 86.2%）出发，重建了评测基建、重跑了两批正式试验、换掉了整组失效的基线，最终得到**四组压缩在 67.5%–80.0%（strict）且两两 McNemar 全部不显著（p ≥ 0.070）**的结果；这个结论**推翻了起点**，同时暴露出题集**没有判别力**——这是当前真正的问题，不是"谁更强"。

## 1. 六个阶段

### 阶段 0：v1（2026-10-29 ~ 10-31）—— 产出结论，然后全部作废

- 做法：40 题 × 2 重复 × 3 agent（SAYACODE / mini-swe / Codex）= 240 trial，输出 `C:\sb\hard\formal-240`。
- 当时结论：SAYACODE **68.8%**、mini-swe **86.2%**、Codex **86.2%** → 声称"落后 17.4pp"。
- 作废原因（`docs/archive/FORMAL-RESULTS-20261031.md`、[AGENTS.md:32](../AGENTS.md)）：
  1. **三套分母并列**：SAYACODE 55/80、mini-swe 69/80、Codex **56/65**。统一 80 分母后 Codex 是 **70.0%**，差距从 17.4pp 缩到 1.2pp。
  2. **"改测试率 49%/73%/42%"口径错误**：49% 是产品侧检测率（39/80），patch 含测试比例是另一回事（SAYACODE 0% / mini-swe 70.9% / Codex 54.2%）。
  3. **"3 条模型故障"只有 1 条真**（`vuls-f6cc8c-r1` ECONNRESET）；"40 题 gold 全绿"实为 36 good / 1 bad / 3 null。
- 连带作废：基于这套误读做的 **v2-tuned 调优实验**（`192f106` 标记作废）。
- **教训**：分母不统一能让结论反向；报数字前先对齐分母，是唯一不能省的一步。

### 阶段 1：v2 重建（11-01 ~ 11-02）—— 基建优先，重跑 240 trial

- 修 3 个真实基建 bug（都有 commit）：安装证据目录不幂等 `5c59126`、产品版本硬编码 `a1e51d3`、阶段1 续跑判据不认 `normalized.json` `5f8b138`。
- 终版：SAYACODE **78.8%** / mini-swe **70.0%** / Codex **68.8%**（planned 80 分母），缺失 15 条已分类（`docs/FORMAL-RESULTS-20261102-v2.md`）。
- **关键发现：补跑效应巨大**——SAYACODE 67.5%→78.8%（+11.3pp）、mini-swe 47.5%→70.0%（+22.5pp）。环境失败系统性惩罚某些 agent，**补跑前数字不能当能力**。
- 三 agent 经 Bonferroni 校正后**均不显著**。
- **教训**：环境噪声项的量级（±10~20pp）大于被比较的效应量级（1~10pp）时，任何对比都得先修环境。

### 阶段 2：严格口径与归因深挖（11-02）

四个同时成立的结论，构成后续所有报告的方法论基础：

| 文档 | 结论 | 影响 |
|---|---|---|
| `PROTOCOL-V2.md` | planned / observed / task_macro *三口径必须同报* | 只报 observed 会高估（mini-swe 84.8% 只覆盖 66/80）|
| `TEST-EDIT-ANALYSIS-20261102.md` | verifier 只重置**测试代码**，`__snapshots__/*.snap` **不重置**；只有改 `.snap` 才有效 | 「patch 含测试文件」不能当作弊指标 |
| `TASKCOUNT-ATTRIBUTION.md` | `task_count=0` 不是团队工具坏了；显式分工题可触发 `task_count=2` | SWE-bench 这批题**不触发协作**，不能用它评价多 agent |
| `DEEP-DIVE-20261102.md` | 一过一败的 5 题里 2 题随机 / 3 题系统性；**重复 2 次不足以消除系统性方差** | 报告必须带 pass@2、pass^2，不能只报 pass@1 |

### 阶段 3：产品侧修复（11-02 ~ 11-03）—— 每个都有 A/B 或单题对照

| # | 缺陷 | 证据强度 | 修复 |
|---|---|---|---|
| 1 | `team_enabled=False` 时系统提示仍教"派发子 Agent"（提示与工具集脱钩），模型浪费 `list_skills`×3 + shell 探测，有"谎称已派发"风险 | **A/B 对照**（修复前 combined vs 修复后 autonomous，`docs/VERIFY-20261103.md`；含题目不同这一局限标注）| `prompts.py` + `application.py`（`60ca2f0`），22 单测 |
| 2 | 上下文摘要失败后无降级，模型丢失任务目标（`flipt-756f00f-r1`，v1 119 次调用 4.7M tokens 后问"请告诉我任务是什么"）| **单题对照**：默认 profile 下 3.2.6 跑 flipt reward 1.0、无降级标记（`docs/SUMMARY-FALLBACK-CHECK.md`）| `summary.py` +116 行（`c5d2973`）|
| 3 | 纯文本收尾（模型说"现在让我验证…"然后结束，无工具调用）| **A/B 不显著**：completion_guard 开/关 +10pp 但 p 不显著、token +53% 超护栏 | `graph.py` 判据收紧（`41b1e38`），**不默认开启** |
| 4 | 摘要触发点/输出预算配置过小（v1 用 16k 输出 + 64k 上下文）| 实测（context 192k / max_output 64k）| 统一 32000 输出（`f393346`）|
| 5 | `task_count` 误读为"协作能力=0" | 归因实验（`TASKCOUNT-ATTRIBUTION`）| 文档纠正，非代码 |

> ⚠️ **这批修复的产品版本是 3.2.6/3.2.7，而本轮所有正式数字跑的是 3.2.5。** 见 §4。

### 阶段 4：v3 —— 踢掉整组失效的基线，换 Claude Code（11-04）

- **Codex 组整组作废**（`docs/CODEX-BASELINE-INVALID.md`）：`unsupported call: apply_patch` 373 次 / 78-80 trial；`/v1/responses` websocket 405 960 次 / 80-80 trial；模型统一 hy3 而 Codex 是 OpenAI 自家调优。→ 其 68.8% / 65.0% **不可比**。
- 换 **Claude Code**（Anthropic 原生 `/v1/messages` 协议 + 完整工具契约）：planned 77.5% / strict 73.8% / 缺失 1。
- 期间修的真实缺陷：nginx `if ($args != "") { return 400; }` 拦掉 Claude Code 的 `?beta=true`（`network.py`）；Clash fake-ip 的 CNAME 陷阱（`*.fastlydns.net` 只匹配一级子域，需 `+.fastlydns.net`）；Debian 12 PEP 668；uv 下 CPython 走 GitHub 超时（宿主预置 tarball）；vuls 单题 3.3GB × 并发 2 打爆 WSL 7GB（`split_sample.py` 分片）。
- 新增 `scripts/audit_agent_traj.py`：**只看 `exception.txt` 会低估适配缺陷**（Codex 案例）。Claude Code 全量轨迹 3468 tool_use / 3467 tool_result / 0 API error → 这组数据可用。

### 阶段 5：v4 —— 第四基线 OpenCode（11-05）

- OpenCode：planned 75.0% / strict 67.5% / **缺失 0** / **snap pass 6（四组最多）**。
- 归因修正（`0440422`）：OpenCode 是 **provider-agnostic 开源脚手架**，接 hy3 是常规用法，**不存在"自家模型错配"**；早前"它有自家模型"的说法是错的，已更正。它的低分更可能来自脚手架自身重量 + 6 个 snap pass 的行为倾向。
- 全量轨迹审计：2480 tool_use，0 API error，0 unsupported call。

### 阶段 6：四组对照定稿 + 方法批判（11-05）

**最终数字**（40 题 × 2 重复 = 80 trial/组，同一模型 `auto-hy3`，官方 Harbor 验证器，见 `FORMAL-RESULTS-20261105-v3.md`）：

| agent | planned | observed | **strict** | 缺失 | 题级 task-macro | bootstrap95 | snap pass |
|---|---|---|---|---|---|---|---|
| SAYACODE | 78.8% (63/80) | 79.7% | **78.8%** | 1 | 80.8% | [69.2, 91.0] | **0** |
| mini-swe | 85.0% (68/80) | 87.2% | **80.0%** | 2 | 87.2% | [79.5, 94.9] | 4 |
| Claude Code | 77.5% (62/80) | 78.5% | **73.8%** | 1 | 78.2% | [67.9, 88.5] | 3 |
| OpenCode | 75.0% (60/80) | 75.0% | **67.5%** | 0 | 75.0% | [65.0, 83.8] | 6 |
| ~~Codex~~ | 68.8% | 69.6% | 65.0% | 1 | — | — | 3 | **不可比** |

- **两两 McNemar 全部不显著**，最接近的 `OpenCode vs SAYACODE` p=0.070（未过 Bonferroni α/3≈0.017）。
- **三种口径三种排名**：planned 上 mini-swe 领先 6.2pp；strict 上缩到 1.2pp。谁"更强"完全取决于口径 → 报告必须三口径并列，不给单一排名。
- **方法批判**（本轮最重要的转向）：四组被压缩在 67.5–80.0% 的窄带里，且题集特征是中位 **2 个文件 / 64 行**的改动（SAYACODE 62% 的 trial 只碰 1–2 个文件）。作为对照：SWE-EVO 平均 21 文件、SWE-Bench ProMax 平均 11.4 文件/261.6 行。**这套题测不出差异**，是因为题本身太浅，不是模型都一样强。

## 2. 结论账本

### 2.1 现在可以说（有据）

1. SAYACODE 在 SWE-bench Pro V2 40 题上 pass@1 **78.8%（strict 同为 78.8%，0 个改快照通过）**。
2. 与 mini-swe-agent（80.0% strict）、Claude Code（73.8% strict）、OpenCode（67.5% strict）**同量级**，题级 McNemar **全部不显著（p ≥ 0.070）**。
3. 评测体系能区分**适配坏掉的组**（Codex 整组作废，靠轨迹级审计抓出来），但**区分不了四个可用组**。
4. 单任务成本约 **1.43M tokens**。
5. 补跑前数字不能当能力：同协议下 SAYACODE +11.3pp、mini-swe +22.5pp 的补跑效应都发生过。

### 2.2 现在不能说（红线）

- ❌ 不能说"优于 Codex / 优于 Claude Code / 优于 OpenCode / SOTA"。
- ❌ 不能拿 Codex 的 68.8% / 65.0% 参与任何排名（整组适配失效）。
- ❌ 不能用 `task_count=0` 说"多 agent 协作没用"（这批题根本不触发协作）。
- ❌ 不能把"patch 含测试文件"当改测试作弊率（测试代码被 verifier 重置）。
- ❌ 不能引用 v1 的 68.8% / 86.2% / 86.2% 及"改测试率 49/73/42"。
- ❌ 不能说"temperature=0 已固定"（hy3 不接受 temperature）。

### 2.3 已作废（不得引用）

| 曾声称 | 作废原因 | 归档位置 |
|---|---|---|
| SAYACODE 落后 17.4pp | 三套分母并列 | `docs/archive/FORMAL-RESULTS-20261031.md` |
| 改测试率 49%/73%/42% | 两个口径混用 | 同上 |
| 3 条模型故障 | 只有 1 条真 | 同上 |
| 40 题 gold 全绿 | 实为 36 good/1 bad/3 null | 同上 |
| v2-tuned 调优收益 | 基于误读证据 | `192f106` |
| OpenCode 有自家模型/模型错配 | 事实错误，它是 provider-agnostic | `0440422` |

## 3. 评测体系完备到哪一步

| 能力 | 状态 | 证据 |
|---|---|---|
| 统一分母 + 三口径（planned/observed/strict） | ✅ | `scripts/strict_compare.py`、`final_summary.py` |
| 缺失分类（6 类） | ✅ | `PROTOCOL-V2.md` §3–§6 |
| 题级 Wilson + 题块/仓库 cluster bootstrap（10k，seed 20261022） | ✅ | `analysis.py` |
| 题级 McNemar + Bonferroni | ✅ | v3 报告六组配对 |
| 快照改写敏感性口径（strict） | ✅ | `scripts/strict_compare.py` |
| 轨迹级适配健康审计 | ✅ | `scripts/audit_agent_traj.py`（抓出 Codex 整组） |
| 结果对账 / 指标 lint | ✅ | `reconcile_results.py` / `lint_metrics.py` |
| 分片执行（重题隔离） | ✅ | `scripts/split_sample.py` |
| 行为测试 | ✅ 1430 passed / 9 skipped（190s） | 本轮实测 |
| **独立 holdout** | ❌ **从未执行** | §5.1 |
| **多模型矩阵** | ❌ 只有 hy3 | `MULTI-MODEL-PLAN.md` |
| **扩展规模（≥100 题）** | ❌ 硬件卡住 | `SCALE-WITHOUT-UPGRADE.md` |
| **partial credit 采集** | ⚠️ 仅 DEEP-DIVE 里手工分析过 | — |

## 4. 制品身份断链（本轮新发现，最该先处理）

**事实**（2026-11-05 核实）：

1. 所有 SAYACODE 正式数字跑的是 `C:\sb\tmp\hard\wheel-release-3.2.5\out\sayacode-3.2.5-py3-none-any.whl`（`scripts/locked_agents.py:48`）。
2. PyPI 上 `sayacode` 的版本序列是 `… 3.2.3, 3.2.4, 3.2.7`——**没有 3.2.5，也没有 3.2.6**（`ba43e04` 提交说明自己写了"3.2.5/3.2.6 未进 PyPI"）。
3. 产品 HEAD（`41b1e38`）相对 `v3.2.5` 又有实质改动：`summary.py` +116、`graph.py` +35、`prompts.py` +26、`application.py` +1。

**后果**：

- 78.8% 对应的**具体制品第三方拿不到**（`pip install sayacode` 得到的是 3.2.7）。可复现性缺口。
- **阶段 3 修的产品缺陷，一行都没进被测制品**。所以"修了 5 个缺陷"是对的，"修复带来提升"**没有评测证据**——修复的效果只在单题/小样本上验过。
- 简历写"PyPI 发布"成立（3.2.7 在 PyPI），但"78.8% 是 PyPI 版本的分数"**不成立**，必须写成"本地构建的 3.2.5 wheel"。

**处置选项**（按性价比）：

| 选项 | 成本 | 收益 |
|---|---|---|
| 用 3.2.7 wheel 重跑 40 题×2×1 组（SAYACODE 单组） | 本地 ¥0，约 8–10 小时 | 把"修复有效性"从推断变成证据；让数字对应可获取制品 |
| 补发 3.2.5/3.2.6 到 PyPI | 不可行（版本号已跳） | — |
| 打一个 3.2.8 = HEAD，发布后重跑 | 需要发布流程 | 数字与 HEAD 一致 |

## 5. 方法论未闭合的四个洞

### 5.1 拿开发迭代集当正式成绩（最严重）

- `studies/sample-40-final.json` 在本仓库的定位是**开发迭代集**（`README.md:41`、`AGENTS.md:20`）；`protocol.md:157` 明确要求"字段未补齐并冻结时，不运行最终 holdout，不将开发或基础设施调试包装为最终研究成绩"；`README.md:108` 也写"开发用于诊断与选择，最终任务独立封存"。
- 但 v2/v3/v4 的"正式结果"全部来自这 40 题，而 SAYACODE 的提示词规则（R1–R5）**正是从这套题上的失败个案里调出来的**（`C:\develop\sayacode\docs\PROMPT-OVERFIT-RISK.md` §1）。
- → 这套分数对 SAYACODE **有开发集调优偏置**，对基线没有。偏置方向对 SAYACODE 有利，结果仍然不显著——这反而**加强**了"题集无判别力"的判断，但它**不能**当作"SAYACODE 真实能力"。
- v3 文档自己也承认："未做的对照：同题集上的 holdout 提示词检验"（`FORMAL-RESULTS-20261105-v3.md:104`）。

### 5.2 题集判别力不足

- 题面太小（中位 2 文件/64 行），四个可用 agent 压在 67.5–80.0%。
- 检测 10pp 差异需约 **330 题**（`MULTI-MODEL-PLAN.md` 口径）；当前 40 题 CI 宽 ±12pp。

### 5.3 提示词规则未做配对验证

- R1（dispatch trigger）**没有任何有效证据**支持，且引入成本风险；
- R3（不改公共 API）来源是 n=1 个案；
- R4（不改既有测试）真正兜住的是机制层，不是提示词。
- `PROMPT-OVERFIT-RISK.md` §4 已给出 P0/P1 的 holdout 验证清单，**从未执行**。

### 5.4 重复 2 次不足以消除系统性方差

- 5 题一过一败里 3 题是系统性（patch 规模 3.3× / 7.3× / 59× 差异）。当前 2 重复的 pass@1 会把系统性方差当成能力差异。

## 6. 文档债（按危害排序）

> 这份清单是"现在会误导读者"的实况，逐项验收后才算还清。

| # | 文档 | 问题 | 危害 |
|---|---|---|---|
| **1** | `docs/STATUS.md`（11-02） | 通篇停在 v2 三 agent；主表把 `Codex 68.8%` 当有效基线；无 strict 口径、无四组、无 Codex 作废 | **最高**：接手者第一份读的就是它 |
| **2** | `docs/HANDOFF.md`（11-02） | 同上，且"当前进度"写"v2 已完成" | **最高** |
| **3** | `README.md` | 首段"三 agent 78.8/70.0/68.8"；索引缺 8 份新文档（v3 结果、三个基线文档、v3 报告、硬件/预算/扩样）；"横向对比 vs Codex CLI"过时 | 高：对外第一印象 |
| **4** | `AGENTS.md` | 坑 24 仍写"主表仍用 planned（78.8/70.0/68.8）"；缺 v3/v4 期间新增的 6 个坑（nginx `?args`、`+.fastlydns.net`、PEP668、uv CPython tarball、vuls OOM 分片、轨迹审计方法论） | 高：会重复踩 |
| **5** | `docs/LESSONS-20261102-v2.md` | §6"仍未修复"6 条里至少 2 条已修（uv installer 预置 `0744741`、摘要失败降级 `c5d2973`），未标记 | 中 |
| **6** | `docs/EVALUATION-METHOD-REVIEW.md` / `EVALUATION-PLAN` | 基准权威性讨论停在 10-29，未纳入 OpenAI 2026 审计（SWE-bench Pro 公开 split ~30% 坏题、Verified ~60% 缺陷测试）| 中 |

## 7. 下一步优先级

| 优先级 | 事项 | 理由 | 成本 |
|---|---|---|---|
| **P0** | 还文档债（本表 §6 六项） | 现在任何新人/新会话都会被 STATUS 带偏，等于白干 | 低，1–2 小时 |
| **P0** | 用 **3.2.7（或 HEAD 构建的 3.2.8）** 重跑 SAYACODE 单组 80 trial | 让数字对应可获取制品 + 首次给"修复有效性"证据 | 本地 ¥0，8–10h |
| **P1** | 注入长上下文/多文件压力做受控 A/B（干净 vs 加压，同题同验证器） | 直接检验"题太浅导致无判别力"这一假设，且能拉开组间差异 | 本地 ¥0，~10 题 × 2 变体 × 4 agent |
| **P2** | holdout 提示词配对（R1/R3 去留） | 关掉 §5.1 的偏置洞，是"能不能报成绩"的前置条件 | 需 100+ 题，受硬件限制 |
| **P3** | 扩样到 100 题 | CI ±12pp → ±9pp 才谈得上显著性 | 需磁盘/内存，见 `SCALE-WITHOUT-UPGRADE.md` |
| **P4** | 多模型矩阵 / 原生模型对照 | 超出 ¥50 预算 | 付费 API |

## 8. 证据索引

| 内容 | 位置 |
|---|---|
| 四组最终数字 | `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json`、`STRICT-COMPARE.json` |
| 轨迹健康审计 | `C:\sb\hard\v2-325\TRAJ-AUDIT-{claude-code,opencode}.json` |
| 正式报告 | `docs/FORMAL-RESULTS-20261105-v3.md`（四组）、`docs/FORMAL-RESULTS-20261102-v2.md`（三组历史） |
| 协议 | `docs/PROTOCOL-V2.md` |
| 基线适配 | `docs/{CODEX-BASELINE-INVALID,CLAUDE-CODE-BASELINE,OPENCODE-BASELINE}.md` |
| 产品侧验证 | `C:\develop\sayacode\docs\{VERIFY-20261103,SUMMARY-FALLBACK-CHECK,PROMPT-OVERFIT-RISK,COMPLETION-GUARD-AB}.md` |
| 作废历史 | `docs/archive/README.md` |

---

**维护规则**：本文件随结论变化更新；任何新结论先确认 §2.2 红线，再决定能否写入。
