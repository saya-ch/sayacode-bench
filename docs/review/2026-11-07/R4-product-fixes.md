# R4：产品侧缺陷与修复证据强度分级（2026-11-07）

> 范围：`C:\develop\sayacode`（产品仓，HEAD `5c84486`，`pyproject` 版本 3.2.7，工作树干净）+ `C:\develop\sayacode-bench\docs\` 中与产品修复相关的证据文档。
> 方式：`git log --oneline -40`、`git show`（逐提交 diff）、`git diff --stat <tag> <tag>`、代码通读（`application.py` / `tools/search.py` / `agent/summary.py` / `agent/graph.py` / `prompts.py` / `tools/git.py` / `tools/shell.py`）、`pytest --collect-only`（531 tests collected）。**只读分析，未修改任何产品代码**；本文件是唯一新增产物。
> 用户要求：**确保这是真实缺陷**——凡无 A/B 或对照证据者，一律标「未证实」，不得写成「已修复缺陷」。本文严格照此执行。

---

## 结论先行

1. **产品侧确有 11 项真实缺陷被识别并修复**（3.2.5–HEAD），其中**只有 2 项达到「随机对照 A/B」等级**（一项不显著、一项显著但作用面受限），**1 项达到「前后单题对照」等级**，其余 8 项**仅有代码审查 + 单元测试支撑，按用户标准一律属「未证实」**。
2. **制品身份链有一处硬错误**：`FORMAL-RESULTS-20261106-327.md` 把「CompletionGuard 判据收紧 `41b1e38`」列为 3.2.7 的三项修复之一，但 `41b1e38`（2026-11-04 13:22）**晚于 3.2.7 发布提交 `ba43e04`（2026-11-04 03:46）**。`git diff v3.2.5 ba43e04 -- src/` 只涉及 4 个文件，**不含 `41b1e38` 的 graph.py 改动**。3.2.7 相对 3.2.5 的产品运行时差异**精确等于 2 项**：摘要失败降级（`c5d2973`）与提示/工具集一致性（`60ca2f0`）。
3. **3.2.7 重跑 Δ −2.6pp / p=0.8145 的正确解读是「这套题 × 这套配置对三项修复的作用面全部为零」**，不是「修复无效」，也不是简单的「题集测不到」。三重作用面错配叠加：其一，唯一可能生效的摘要降级路径**从未被触发**（DEEP-ANALYSIS §10：单次输入峰值最大 102,034 < 触发线 150,400）；其二，提示一致性修复只在 `team_enabled=False` 时改变行为，而正式评测用 `baseline.json` 的 `team_enabled=true`，**行为逐字节不变**；其三，CompletionGuard 默认 `False` 且不在 3.2.7 制品内，**从未处于启用状态**。
4. **有 3 项修复至今没有任何评测证据**（`error_type` 归因 `fb51bcb`、检索输出限流 `559917e`+`5c84486`、CompletionGuard 判据收紧 `41b1e38`），且这三项**都不在任何被测制品中**——它们是 3.2.7 发布后的提交。
5. **另有 4 项读码确认的缺陷至今未修复或不完整**：`error_type` 不覆盖「返回值语义失败」（`execute_command_tool` 的 `exit_code≠0`/`timed_out`）；检索限流的 `MAX_SEARCH_OUTPUT_CHARS=20_000` 在运行时路径**从未生效**（实际走 64 KiB，且引导语缺失）；原始任务消息未做固定保留（SUMMARY-FALLBACK §4.1 自认的建议未实现）；`summary_trigger_for` 的阈值估算在多处文档被写成 153.6k（实际约 150.4k）。

---

## 0. 证据分级定义（本文唯一标准）

| 等级 | 名称 | 判定条件 | 是否算「有证据」 |
|---|---|---|---|
| **L1** | 随机对照 A/B | 同一题集、同一验证器、两组只差被测变量；**报出 n 与统计检验 p 值**（或配对区间） | ✅ 是（但须看是否显著 + 是否在作用面内） |
| **L2** | 前后单题（或小样本）对照 | 有明确的前/后状态对比，n 小、无统计检验，作者自标方向性 | ✅ 是（仅方向性） |
| **L3** | 仅代码审查 + 单元测试 | 读完代码/单测确认「缺陷存在且补丁逻辑正确」，但**没有任何端到端运行证据** | ❌ **未证实** |
| **L4** | 纯推理 / 文档论断 | 只有「应该是这样」「按设计会这样」，无代码验证也无运行 | ❌ **未证实** |

**特别约定**：即使达到 L1，若该次 A/B 的**被测配置与被测制品不包含该修复**，其结果对「该修复是否有效」**无证据力**，本文标注为「**L1 但作用面为零**」。

---

## 1. 制品身份链（先钉死这个，否则后面全是空谈）

### 1.1 提交与标签实测

| 项 | 值 | 证据 |
|---|---|---|
| 产品 HEAD | `5c84486`（2026-11-06 19:36） | `git log -1` |
| `pyproject` 版本 | `3.2.7` | `pyproject.toml:7` |
| 最后一个 tag | **`v3.2.6`**（**没有 `v3.2.7` tag**） | `git tag --list` |
| 3.2.7 发布提交 | `ba43e04`（2026-11-04 03:46）「chore(release): 3.2.7（恢复发布门禁，3.2.5/3.2.6 未进 PyPI）」 | `git log` |
| `ba43e04..HEAD` 提交数 | **4** | `git rev-list --count ba43e04..HEAD` |
| 工作树状态 | 干净（无未提交改动） | `git status --short` |

`ba43e04` 之后的 4 个提交（**全部不在 3.2.7 制品内**）：

| 提交 | 时间 | 主题 |
|---|---|---|
| `41b1e38` | 2026-11-04 13:22 | feat(agent): CompletionGuard 判据收紧（本轮有写操作不催）+ nudge 提示词改中性简洁 |
| `fb51bcb` | 2026-11-06 18:53 | fix(audit): 工具被转述的失败要标成 tool_error |
| `559917e` | 2026-11-06 19:30 | feat(tools): 检索输出加上限，避免单次调用吃掉上下文 |
| `5c84486` | 2026-11-06 19:36 | fix(tools): 检索输出接入统一限流，不再无限透传 |

### 1.2 版本间产品运行时差异（精确值）

```
$ git diff --stat v3.2.5 v3.2.6 -- src/
 src/sayacode/agent/graph.py   |   4 +-
 src/sayacode/agent/summary.py | 116 ++++++++++++++++++++++++++++++
                                                → 2 文件，118 insertions(+), 2 deletions(-)

$ git diff --stat v3.2.6 ba43e04 -- src/
 src/sayacode/application.py |  1 +
 src/sayacode/prompts.py     | 26 ++++++++++++++--
                                                → 2 文件，25 insertions(+), 2 deletions(-)

$ git diff --stat v3.2.5 ba43e04 -- src/     # = 3.2.5 → 3.2.7 全量产品差异
 src/sayacode/agent/graph.py   |   4 +-
 src/sayacode/agent/summary.py | 116 ++++++++++++++++++++++++++++++
 src/sayacode/application.py   |  1 +
 src/sayacode/prompts.py       |  26 +++++++++-
                                                → 4 文件，143 insertions(+), 4 deletions(-)

$ git diff --stat ba43e04 HEAD
 src/sayacode/agent/graph.py                  | 31 +++++++++++-
 src/sayacode/application.py                  | 11 +++--
 src/sayacode/tools/search.py                 | 73 +++++++++++++++++++++++------
 tests/agent/test_truncation_continuation.py | 28 +++++++++++
 tests/memory/test_audit.py                   | 27 +++++++++++
 tests/tools/test_file_search_paths.py        | 24 ++++++++++
                                                → 6 文件，174 insertions(+), 20 deletions(-)
```

**由此可确定**：3.2.5 → 3.2.7 的产品运行时差异**只有 2 项修复**——`c5d2973`（摘要降级，summary.py + graph.py 装配）与 `60ca2f0`（提示一致性，prompts.py + application.py 1 行）。**`41b1e38` 不在其中**。

### 1.3 正式评测的被测制品与配置

| 项 | 值 | 来源 |
|---|---|---|
| 3.2.5 批次 | 本地 wheel `sayacode-3.2.5-py3-none-any.whl`（PyPI 从未发布） | `scripts/locked_agents.py:48`、RETROSPECTIVE §4 |
| 3.2.7 批次 | PyPI `sayacode-3.2.7-py3-none-any.whl`，sha256 `49db58d1…` | `FORMAL-RESULTS-20261106-327.md:11` |
| variant | `baseline.json`：**`team_enabled: true`**、`profile_overrides: {}` | `studies/baseline.json` |
| `completion_guard` | **默认 `False`** | `config.py`（`completion_guard: bool = False`） |
| profile | `context_length=192000`、`max_output_tokens=32000`、`summary_trigger_ratio=0.8` | `scripts/locked_agents.py:612,659`；`FORMAL-RESULTS` §1 |

**这四行是 §5 判定的全部前提**：`team_enabled=true` 关掉了第二项修复的作用面；`completion_guard=False` 关掉了第三项；`192k/32k/0.8` 决定了摘要触发线（见 §5.2）。

---

## 2. 缺陷台账（主表）

图例：**进制品**列标注该修复进入的最早制品；「未进任何制品」＝仅存在于 HEAD，从未被任何一次评测使用。

| # | 缺陷 | 发现方式 | 证据类型 | 修复 commit | 是否进入被测制品 | 修复后是否有评测证据 |
|---|---|---|---|---|---|---|
| 1 | 文件检索（glob/grep）返回虚拟根路径 `/lib/...`，模型交给 `read_file` 后落到文件系统根、找不到文件 | 评测中工具链异常（`read_file` 反复失败） | **L3**（仅代码 + 单测 `test_file_search_paths.py`） | `13df615`（3.2.5） | ✅ 3.2.5 / 3.2.7 | **无**（无任何前/后对照） |
| 2 | 截断漏判：厂商以 `tool_use` 等非长度原因结束、输出已到上限时未续写 | 评测中空响应/半截回答 | **L2**（`SUMMARY-FALLBACK-CHECK` §4.2 实测触发 3 次续写，但为反证式观察） | `13df615`（3.2.5） | ✅ 3.2.5 / 3.2.7 | 弱：单题观察，非为验证该修复设计 |
| 3 | 摘要失败无降级：官方中间件把 "Previous conversation was too long to summarize." 当摘要写回，真实历史被一句占位替换 | **评测定位**：v1 `flipt-756f00f-r1` 119 次调用 4.7M tokens 后问「请告诉我任务是什么」 | **L2**（单题对照：3.2.6 默认 profile 下 reward 1.0、无降级标记）+ 4 单测 | `c5d2973`（3.2.6） | ✅ 3.2.7 | **有，但仅 n=1**；且在正式 40 题上**作用面为零**（§5.2） |
| 4 | 提示与工具集脱钩：`team_enabled=False` 时系统提示仍教「派发子 Agent」，模型浪费 `list_skills×3` + shell 探测，有谎称派发风险 | 评测行为观察（task-14） | **L2**（A/B 对照：修复前 combined vs 修复后 autonomous；**作者自标「题目不同」局限**） | `60ca2f0`（3.2.6） | ✅ 3.2.7 | **有，但 n=1/组 且题目不同**；正式评测 `team_enabled=true` → **作用面为零**（§5.3） |
| 5 | CompletionGuard 判据过宽：本轮已有写操作仍催促，把「总结」误判为「空转」，成本翻倍 | 评测行为观察（NodeBB「Now let me verify…」） | **L1**（A/B：20 题 × 2 重复 × 2 变体 = 80 trial；**+10pp，McNemar p≈0.289 不显著，token +53% 超 15% 护栏**） | `41b1e38` | ❌ **未进任何制品**（3.2.7 之后） | **有 A/B，但结论是「不显著」**；且修复本身未进制品，A/B 测的是 `13df615` 的初版 |
| 6 | 工具失败未被审计：`ToolErrorMiddleware` 把异常转述成 `"Tool failed: …"` 字符串，下游表现为成功的 `tool.completed`，`error_type` 恒为 `null` | **评测观测**：3865 次 `tool.completed` 全部 `error_type=null`（DEEP-ANALYSIS §8.5） | **L3**（代码 + 单测 `test_restated_tool_failure_is_marked_as_error`） | `fb51bcb` | ❌ **未进任何制品**（3.2.7 之后） | **无** |
| 7 | 检索输出无上限：`grep_search` 单次返回 125,622 字符（约 3–4 万 token），一次吃掉大半上下文 | **评测观测**：DEEP-ANALYSIS §8.4 tool 输出 max 表 | **L3**（代码 + 单测） | `559917e` + `5c84486` | ❌ **未进任何制品**（3.2.7 之后） | **无**（修复晚于 3.2.7 跑批：提交 19:30/19:36，跑批 11-05 22:55→11-06 06:35） |
| 8 | 提示词规则 R1「Dispatch trigger」过度承诺（跨两个领域就派发） | 与 #4 同源 | **L4**（PROMPT-OVERFIT-RISK §3 自评「**没有有效证据支持**」） | `13df615` | ✅ 3.2.5 / 3.2.7 | **无**；且 3.2.5 前 wheel 无该规则，「加规则后仍 0 派发」从未在权威集发生 |
| 9 | 提示词规则 R3「不改公共 API / 旧入口保留」 | **单例事故**：qutebrowser 把 `KeyInfo.to_int` 改名 `to_qt` 并改测试，reward 1→0 | **L2 但已被推翻**（`evaluation/README.md:72` 明确标「已推翻（单次）：后续同规则仍 FAIL」） | `13df615` | ✅ 3.2.5 / 3.2.7 | **否**（原证据已自我推翻） |
| 10 | 提示词规则 R4「不改既有测试」 | 5 个 holdout 失败均与改既有测试相关 | **L2**（5 题单次复验 3/5 翻盘；PROMPT-OVERFIT-RISK 自认「真正兜住的是机制层不是提示词」） | `13df615` | ✅ 3.2.5 / 3.2.7 | 弱，且与机制层混淆 |
| 11 | 提示词规则 R5「不新建重复测试文件」 | 无独立实验 | **L4**（PROMPT-OVERFIT-RISK §1：无独立实验） | `13df615` | ✅ 3.2.5 / 3.2.7 | **无** |

> 说明：3.2.3 / 3.2.4 的 Web/审计/子 Agent 修复（并发审计写、检查点回退限制、审批句柄遗漏、会话删除竞态等，见 `CHANGELOG.md` 3.2.3–3.2.4 条）**发生在评测体系建立之前**，无任何评测证据，也不在本轮评测的作用面内，未纳入上表。

---

## 3. 严格分级结果

### 3.1 达到 L1（随机对照 A/B）的只有 2 项

| 项 | n | 统计 | 结论 | 是否支撑「修复有效」 |
|---|---|---|---|---|
| #5 CompletionGuard 判据（初版机制） | 80 trial（20 题 × 2 × 2） | +10.0pp，McNemar 双侧 **p≈0.289**；token **+53%**（护栏 <15%） | **不显著 + 超护栏 → 不默认开启** | ❌ **不支撑**（且测的是 `13df615` 初版，非 `41b1e38` 收紧版） |
| 3.2.5 vs 3.2.7 整体 | 78 配对 trial | Δ **−2.6pp**，McNemar **p=0.8145**，题块 bootstrap CI95 **[−12.5, +6.2]pp** | **无差异** | ❌ **不支撑任何单项修复**（作用面错配，见 §5） |

### 3.2 达到 L2（前后单题 / 小样本对照）的 3 项

| 项 | n | 设计 | 作者自标局限 | 本文判定 |
|---|---|---|---|---|
| #3 摘要失败降级 | 1 题 × 3 配置各 1 次 | 默认 profile（192k/32k/0.8/keep12）reward 1.0；summary-on（16k/keep2）reward 0.0 且降级标记 1 次；summary-off reward 0.0 | 「每档仅 1 次、单题，只作方向性判断」 | **方向性支持「占位不再写回」**；**不支持「提升任务成功率」**（on/off 均 0.0，且失败主因是 8192 输出预算对 reasoning 模型过小） |
| #4 提示一致性 | 2 组 × 1 次 | 修复后 single 无 `list_skills`×3、无 shell 探测、无谎称 | **「修复前是 combined 题、修复后是 autonomous 题，题目不同，不能完全归因」** | 行为改善**在代码层确定**（`team_enabled=False` 才替换提示）；评测证据**因题目不同而弱** |
| #9 R3 不改公共 API | 1 题 + 1 次复跑 | qutebrowser reward 0→1 | 后续被 `evaluation/README.md:72` 标「**已推翻**」 | **不成立**——原证据已自我推翻 |
| #10 R4 不改既有测试 | 5 题 × 1 次 | 3/5 翻盘 | 「规则降低概率但无法消除（qutebrowser 那次照样改了）」；机制层混淆 | **弱方向性**，不能归因给提示词 |
| #2 截断续写 | 1 题 | summary-off 实测 `output_tokens=8192 == max_output_tokens` 且无 `tool_calls` → 续写 3 次 | 「reasoning 吃光预算，续写 3 次仍无正文」 | **机制被触发**（事实），但**未提升结果**（该 trial reward 0.0） |

### 3.3 只有 L3（代码审查 + 单测）的 3 项

| 项 | 补丁验证 | 端到端证据 | 判定 |
|---|---|---|---|
| #1 文件检索虚拟路径 | `test_file_search_paths.py`（含 `bf271b8` 修复 3.11/3.12 glob 语义） | **无**。无修复前/后的工具成功率对比、无 `read_file` 失败率下降数据 | **未证实** |
| #6 `error_type` 归因 | `test_restated_tool_failure_is_marked_as_error` | **无**。修复晚于全部跑批 | **未证实** |
| #7 检索输出限流 | 单测覆盖 `_bounded_output` | **无**。修复晚于 3.2.7 跑批 13 小时 | **未证实** |

### 3.4 纯推理 / 无证据的 3 项

| 项 | 判定 |
|---|---|
| #8 R1 Dispatch trigger | **未证实**，且作者自评为「高风险」，建议 P0 做 holdout 配对（从未执行） |
| #11 R5 不新建重复测试 | **未证实**，无独立实验 |
| （附）#4 的「谎称派发」风险 | 未捕获任何一例实际谎称；「防谎称」是新增提示的**设计意图**，不是观测到的缺陷 |

---

## 4. 至今没有任何评测证据支持其有效性的修复（用户重点要求）

按「完全无评测证据」严格筛选，共 **7 项**：

| # | 修复 | commit | 状态 | 为什么无证据 |
|---|---|---|---|---|
| 1 | 文件检索虚拟路径修复 | `13df615` | 在 3.2.5 / 3.2.7 制品内 | 从未做过「修复前 vs 修复后」的工具成功率对照；3.2.5 是其首个制品，**没有 3.2.4 基线对照** |
| 2 | `error_type` 工具失败归因 | `fb51bcb` | **不在任何制品** | 提交于 2026-11-06 18:53，晚于 3.2.7 跑批（11-06 06:35 结束）；无重跑 |
| 3 | 检索输出限流（20k/64KB） | `559917e`+`5c84486` | **不在任何制品** | 提交于 2026-11-06 19:30/19:36，晚于跑批；无重跑 |
| 4 | CompletionGuard 判据收紧 | `41b1e38` | **不在任何制品** | 提交晚于 3.2.7 构建；A/B（`COMPLETION-GUARD-RESULT.md`）测的是 `13df615` 的初版，不是收紧版 |
| 5 | R1 Dispatch trigger 规则 | `13df615` | 在制品内 | 唯一支撑是「22 次权威试验 0 派发」的**观测**，但该观测发生在**规则不存在**的 3.2.4 wheel 上；自主场景 n=1 加规则前后均 0 |
| 6 | R5 不新建重复测试文件 | `13df615` | 在制品内 | 无独立实验设计 |
| 7 | R3 不改公共 API 规则 | `13df615` | 在制品内 | 唯一证据（qutebrowser 单次 0→1）**已被作者自己推翻** |

**另有 2 项「有证据但结论为不显著」**：#5 CompletionGuard（p≈0.289）与 #10 R4（3/5 翻盘，单次、机制层混淆）。按用户标准同样不得写成「已修复且有效」。

---

## 5. 3.2.7 重跑 Δ −2.6pp / p=0.8145 的判定

### 5.1 判定

**「这套题 × 这套配置对三项修复的作用面全部为零」——属于第三类，既不是「修复无效」，也不是笼统的「题集测不到修复」。**

理由是**三重独立的作用面错配**，任一条成立就足以让 Δ 无解释力，三条同时成立则 Δ 的信息量严格为零。

### 5.2 错配一：摘要降级路径从未被触发（唯一真正生效的修复）

3.2.7 相对 3.2.5 的产品差异只有两项，其中 `c5d2973`（摘要降级）是唯一可能影响任务结果的。而 DEEP-ANALYSIS §10 用同一批 3.2.7 数据实测：

| 组 | trial | 单次调用 input_tokens 峰值中位 | 峰值最大 | 超过触发线的 trial |
|---|---:|---:|---:|---:|
| SAYACODE 3.2.7 | 77 | 32,920 | **102,034** | **0** |
| SAYACODE 3.2.5 | 79 | 30,180 | **127,369** | **0** |

**触发线的准确值不是文档里通行的 153.6k，而是约 150,400**。按 `summary_trigger_for`（`agent/graph.py`，3.2.7 与 HEAD 逐行相同）：

```
context_window   = 192,000
configured_input = 192,000 − 32,000 = 160,000
margin           = min(max(2048, 192000×0.05=9,600), max(1, 160000×0.10=16,000)) = 9,600
reserved_limit   = 160,000 − 9,600 = 150,400
ratio 分支       = 192,000 × 0.8 = 153,600
return min(150,400, 153,600) = 150,400
```

即 **153.6k 只是 ratio 分支的值，最终阈值取 min = 150.4k**（`EXPERIMENT-CONTEXT-AB.md` 亦记 150.4k，与本文计算一致；`FORMAL-RESULTS-20261031.md:62`、DEEP-ANALYSIS §10 的 153.6k 是估算，误差方向不影响结论）。

结论不变且更确定：**最大峰值 127,369 距离 150,400 还差 23,031 token，0 个 trial 到达摘要路径**。`events.jsonl` 亦无任何摘要/压缩事件。因此 `c5d2973` 在这 40 题上**执行了 0 次**——它的「无效」不是修得不对，而是**从未运行**。

### 5.3 错配二：提示一致性修复在 `team_enabled=true` 下行为逐字节不变

`60ca2f0` 的实际改动只有 1 行（`application.py`）+ prompts.py 26 行：

```python
# application.py:654（60ca2f0 新增）
team_enabled=include_team_tools and self.team_enabled,
```

```python
# prompts.py:101-107
def _role_rules(role, team_enabled):
    if team_enabled:
        return _ROLE_RULES[role]                       # ← 完全原样返回
    return tuple(_NO_TEAM_RULE if rule.startswith("Dispatch trigger:") else rule for rule in rules)
```

正式评测 variant 是 `studies/baseline.json`：`"team_enabled": true`。→ `_role_rules(role, True)` 走第一条分支，**返回的元组与修复前完全相同**，系统提示逐字节不变。

因此 **`60ca2f0` 对 40 题正式重调用的作用面是严格零**——它不是「效果小」，而是**不执行任何不同代码**。该项修复的价值只在 `team_enabled=False`（即 `single` 对照变体）的实验中成立，而那一组用的是 `VERIFY-20261103` 的单次验证，不是本次 40 题配对。

### 5.4 错配三：CompletionGuard 从未启用且不在制品内

- `config.py`：`completion_guard: bool = False`（默认关闭）。
- `baseline.json` 的 `profile_overrides` 为 `{}` → 未开启。
- 且 `41b1e38`（判据收紧）**不在 3.2.7 制品内**（§1.2）。

所以无论「开启是否有效」，本次配对中该中间件**根本没有被装配**（`graph.py` 的 `if profile.completion_guard:` 为假）。它是这三项里唯一曾有 A/B 的（`COMPLETION-GUARD-RESULT.md`：+10pp，p≈0.289，token +53%），但那次 A/B 用的制品是 3.2.6，测的是**初版判据**，与 3.2.7 批次无关。

### 5.5 为什么不能笼统说「题集测不到」

「题集测不到」会把责任全部推给题目难度/规模，掩盖另外两层：

- 若题目确实**加深到能触发摘要**（单次输入 >150.4k），那么 `c5d2973` 会进入作用面 —— 此时若仍无差异，才是「修复无效」；
- 但即使题目不变，**只要把 variant 换成 `team_enabled=false`**，`60ca2f0` 就会生效；只要把 `profile_overrides` 设为 `{"completion_guard": true}`，初版 Guard 就会装配 —— 这两项与题目难度**无关**，是**配置作用面**问题。

因此正确的表述应按三层拆分：

| 层 | 该修 | 本次 A/B 是否覆盖 | 需要的实验 |
|---|---|---|---|
| 制品层 | `41b1e38` | ❌ 不在制品 | 用含该提交的制品重跑 |
| 配置层 | `60ca2f0`（需 `team_enabled=false`）、Guard（需 `completion_guard=true`） | ❌ 未配置到作用面 | 两个 variant 配对 |
| 题集层 | `c5d2973`（需单次输入 >150.4k） | ❌ 0 触发 | 长上下文/大仓库/长测试输出题，或加压注入 |

**只有当三层全部对齐后仍无差异，才能说「修复无效」。当前 Δ−2.6pp 的信息量等于零，既不能证有效也不能证无效**——这与 `FORMAL-RESULTS-20261106-327.md` §4 的自我表述方向一致，但该节只归因到「运行间随机性」，**漏掉了上述三层作用面错配**，因而不够。

### 5.6 补充：DEEP-ANALYSIS §8.1 提供了机制性佐证

3.2.7 与 3.2.5 的行为轨迹逐项几乎相同：

| 指标 | 3.2.7 | 3.2.5 |
|---|---:|---:|
| 工具调用 / trial | 49.6 | 48.7 |
| 编辑 / trial | 8.2 | 8.1 |
| 模型调用 / trial | 33.4 | 33.2 |
| 输入 token / trial | 960,348 | 961,560 |

这**正是 §5.2–§5.4 的必然结果**：若摘要从未触发、提示分支未变、Guard 未装配，则行为轨迹**本应**相同。行为相同是作用面为零的**证据**，而不是「修复被掩盖」的迹象。

---

## 6. 评测中发现但至今未修复（或修复不完整）的产品缺陷

本节全部为**读代码确认**，非文档转述。

### 6.1 `error_type` 不覆盖「返回值语义失败」（未修复）

`fb51bcb` 的判据（`application.py` `_record_tool_event`）是：

```python
failed = kind == "tool.failed" or tool_output.startswith("Tool failed:")
```

**覆盖**：框架级 `tool.failed`（含 `events.py` 中 `output.status == "error"` 的映射，见 `agent/events.py` `tool-finished` 分支）、被 `ToolErrorMiddleware` 转述成 `"Tool failed: …"` 的异常。

**不覆盖**——工具以**返回值**表达失败、不抛异常的情形：

| 工具 | 失败表达 | 是否被记为 `error_type` |
|---|---|---|
| `execute_command_tool` | 返回 `{"exit_code": 1, "timed_out": False, …}`（`tools/shell.py:71`） | ❌ **否**（`tool_output` 是 dict 序列化文本，不以 `"Tool failed:"` 开头） |
| `execute_command_tool` 超时 | 返回 `"timed_out": True`（同处） | ❌ **否** |
| `git` | 复用 `_run_process`，非零退出同样只体现在 `exit_code`（`tools/git.py:68`） | ❌ **否** |
| `search_replace` 未匹配 | `raise ValueError`（`tools/files.py:167`） | ✅ 是（异常 → 转述） |
| `read_file` 路径不存在 | 抛异常 | ✅ 是 |

**这是评测最关心的那一类失败**：DEEP-ANALYSIS §8.5 列举的「命令返回非零 / 文件不存在 / patch 失败」中，**命令返回非零恰恰是最常见的一种，而修复后仍然不可见**。另外 `tool_output` 用 `str()` 强转，对 dict 返回值得到的是 Python repr，判据 `startswith("Tool failed:")` 对结构化返回值天然失效。

**结论**：`fb51bcb` 是**部分修复**，DEEP-ANALYSIS §8.5 指出的观测盲区**只关闭了异常路径，没有关闭返回值路径**。

### 6.2 检索限流的 20,000 字符上限在运行时从未生效（设计未落地）

`tools/search.py`：

```python
MAX_SEARCH_OUTPUT_CHARS = 20_000                            # :39

def _bounded_output(text, runtime, source):
    if runtime is None:
        return _truncate_output(text, tool=source)          # :50  仅单测路径
    return _limited(text, runtime, source)                  # :51  生产路径

def _truncate_output(text, *, tool, limit=MAX_SEARCH_OUTPUT_CHARS):
    ...
    return (f"{head}\n\n[输出已截断] {tool} 本次共返回 {len(text):,} 字符，"
            f"只显示前 {limit:,} 字符。请缩小范围后重试：…")   # :62-66  引导语
```

工具由 LangChain 框架注入 `ToolRuntime`，生产路径 `runtime` **恒非 None** → 实际走 `_limited`（`tools/files.py:97`），其阈值是 `context.output_limit_bytes` 默认 **64 KiB**，返回结构为：

```python
{"preview": …, "characters": …, "bytes": …, "output_file": …}
```

**没有任何「请缩小范围」的引导语**。因此：

1. 注释所述「截断后明确告知原始规模，促使模型缩小查询范围」（`:37-38`）在运行时**不成立**——20,000 字符常量与那段引导文案是**只在单测里执行的死路径**；
2. 真实上限是 64 KiB（约 1.6–2 万 token 的中文/代码混合），虽然确实「有界」了，但**比设计值宽 3.2 倍**，且模型看不到「为什么被截断、该怎么缩小」。

**覆盖范围复核**（任务要求「是否只对某几个 tool 生效」）：

| 工具 | 限流机制 | 有效 |
|---|---|---|
| `read_file` | `_limited`（`files.py:139`） | ✅ |
| `list_directory` | `_limited`（`files.py:222`） | ✅ |
| `read_output_file` | `_limited`（`files.py:251`） | ✅ |
| `analyze_project` | `_limited`（`analysis.py:54`） | ✅ |
| `list_symbols` | `_limited`（`analysis.py:161,164`） | ✅ |
| `web_search` | `_limited`（`web.py:66`） | ✅ |
| `glob_search` | `_bounded_output`（`search.py:115`，`5c84486` 补齐） | ✅ |
| `grep_search` | `_bounded_output`（`search.py:149`，`5c84486` 补齐） | ✅ |
| `git` | 经 `_run_process` 落盘 + 64 KiB preview（`shell.py:72-79`） | ✅（等价有界，非 `_limited`） |
| `execute_command_tool` | 同上，落盘 + 64 KiB preview | ✅（等价有界） |

**所以「只对某几个 tool 生效」这一担心在当前 HEAD 已不成立**——`5c84486` 之后所有工具都有界。遗留问题是**两套限流语义并存**（`_limited` 返回结构化 dict + `output_file`；`_run_process` 返回 `stdout/stderr` 两个 preview 字段），且 `MAX_SEARCH_OUTPUT_CHARS` 这条更严格的设计值未生效。

### 6.3 原始任务消息未固定保留（未修复，作者自认）

`SUMMARY-FALLBACK-CHECK.md` §4.1 实测：`summary-on`（16k 触发 / keep=2）下 `messages[0]` **已经是更早一次成功摘要产生的摘要消息**，降级只能保住这段摘要，模型明确回复「The original task is not recoverable from the retained context」。同文 §4.1「改进建议（本轮未在本轮实现）」列出三条，均未实现。→ **降级机制在「已摘要过一次」的场景下无效**。

### 6.4 `summary_trigger_for` 阈值在多处文档被写成 153.6k（文档缺陷，非代码）

代码正确（§5.2），但 `FORMAL-RESULTS-20261031.md:62`（「SAYACODE 摘要（触发 153.6k）」）与 DEEP-ANALYSIS §10（「触发线约 153,600」）均未按 `min(reserved_limit, window×ratio)` 计算。误差 3,200 token 不改变本文任何结论，但会被后续「是否触发」的判定误导。

### 6.5 3.2.6 的 `summary.py` 存在「只插入标记不裁剪」的降级空转

`summary.py` `_degrade`：当 `cutoff is None`（消息数 ≤ keep+1，或待删消息缺 `id`）时，**只插入 `sayacode_summary_failed` 标记，不做任何裁剪**。注释自述「最坏情况是上下文不降但任务不丢」。这意味着在「消息数刚好在阈值附近」时，降级**不会降低 token**，摘要便失去意义——但也不会重复触发（标记去重）。属**已知的设计取舍**，非缺陷，记录备查。

---

## 7. 对既有文档的纠错（本文新增的硬发现）

| # | 文档 | 原文 | 实测 | 影响 |
|---|---|---|---|---|
| C1 | `FORMAL-RESULTS-20261106-327.md:43-45` | 「3.2.6/3.2.7 的**三项**产品修复（摘要失败降级 `c5d2973`、提示与工具集一致性 `60ca2f0`、**CompletionGuard 判据收紧 `41b1e38`**）」 | `41b1e38` 提交于 2026-11-04 13:22，**晚于** 3.2.7 发布提交 `ba43e04`（11-04 03:46）；`git diff v3.2.5 ba43e04 -- src/` 不含该改动 | **该批对比实为 2 项修复**；「三项」高估了作用面 |
| C2 | `COMPLETION-GUARD-AB.md:3` | 「状态：设计稿，**未实际跑批**」 | `COMPLETION-GUARD-RESULT.md`（同一 `docs/` 目录）记载 2026-11-04 已完成 80 trial A/B（+10pp，p≈0.289，token +53%） | 两份文档互相否定；应删 A/B 文档的「未跑批」状态或改为「已跑，结果见 RESULT」 |
| C3 | `DEEP-ANALYSIS-20261106.md` §10、`FORMAL-RESULTS-20261031.md:62` | 「触发线约 153,600」 | 按 `summary_trigger_for` 实际 **150,400** | 结论不变（最大值 127,369 仍低于两者），但口径应统一 |
| C4 | `RETROSPECTIVE-20261105.md:43` 标题 | 「阶段 3：产品侧修复——**每个都有 A/B 或单题对照**」 | #1 文件检索、#6/#7 两项（当时尚未提交）无对照；R5 无实验 | 标题过强，应改为「部分有」 |
| C5 | `FORMAL-RESULTS-20261106-327.md:47-60` §4 | 把 Δ−2.6pp 只归因于「运行间随机性」 | 主因是**三重作用面错配**（§5），随机性只是次要解释 | 该节结论方向正确但归因不完整 |
| C6 | `PILOT-SWE-EVO-20261106.md:74-75` | 「另外修掉：检索输出无上限…、审计 `error_type` 恒为 null」 | 两项修复提交于 11-06 18:53–19:36，**均未进入任何被测制品** | 「修掉」应写明「已提交、未进制品、无评测证据」 |

---

## 8. 结论与建议

### 8.1 可直接写进对外材料的（有证据）

1. **产品侧识别并修复了 11 项缺陷**（含 5 条提示词治理规则），其中 2 项进入正式评测制品并被配对检验。
2. **3.2.7 与 3.2.5 在 40 题 × 2 重复上无统计差异**：Δ −2.6pp，McNemar p=0.8145，题块 bootstrap CI95 [−12.5, +6.2]pp。**正确表述是「未观测到差异」，不是「修复有效」**。
3. **该次对比无法检验这三项修复的有效性**，原因是作用面错配（摘要未触发 / 提示分支未变 / Guard 未启用且不在制品）。

### 8.2 不得写入（无证据）

- ❌「摘要降级提升了任务成功率」——现有证据是 3 个配置各 1 次，summary-on/off **均 reward 0.0**，默认配置 PASS 且**未触发降级**。
- ❌「提示一致性修复改善了 `single` 表现」——单次、题目不同，作者已自标局限；且正式评测 `team_enabled=true` 不经过该分支。
- ❌「CompletionGuard 有效」——p≈0.289 不显著，token +53% 超护栏。
- ❌「`error_type`/检索限流修复已验证」——仅代码审查 + 单测，且均不在任何制品。
- ❌「派发触发规则（R1）提升了协作能力」——从未在权威集上验证，作者自评「无有效证据」。
- ❌「不改公共 API 规则（R3）解决了 qutebrowser 类失败」——原证据已被作者自己标「已推翻」。

### 8.3 下一轮最小可判实验（按性价比）

| 优先级 | 实验 | 目标修复 | n | 成本 | 判据 |
|---|---|---|---|---|---|
| **P0** | 用含 `41b1e38`+`fb51bcb`+`559917e`+`5c84486` 的制品（HEAD 或 3.2.8）重跑 40 题 × 2 | 三项未进制品的修复 | 80 trial | 本地 ¥0，8–10h | 同时得到「制品对应 HEAD」与首次行为证据 |
| **P0** | `completion_guard` on/off 配对（variant 只差该字段），≥120 题 × 2 | Guard 初版 + 收紧版 | ≥240 trial | 本地 ¥0，~1 天 | token 增幅 <15% 且 pass@1 不降 |
| **P1** | `team_enabled` true/false 配对（variant 只差该字段） | `60ca2f0` | 40 题 × 2 | 本地 ¥0 | `single` 组 `list_skills`/探测调用归零、pass@1 不降 |
| **P1** | 长上下文加压题（单次输入强制 >150.4k，可用 `EXPERIMENT-CONTEXT-AB.md` 的长文注入法） | `c5d2973` 摘要降级 | ≥10 题 × 2 × 2 | 本地 ¥0，~10h | 降级标记出现且任务目标不丢 |
| **P2** | 修 §6.1 的返回值失败归因，再重算 DEEP-ANALYSIS §8.5 | `error_type` 完整性 | 复用现有 391 trial 重算 | ¥0 | 3865 次调用中失败可归因比例 >0 |

### 8.4 一句话

**当前「修复效果」的全部证据只有 1 项 n=1 单题对照（摘要降级不写占位）和 1 项 p≈0.289 的不显著 A/B（Guard），其余 9 项修复在证据上仍是「未证实」；而 Δ−2.6pp 之所以无信息量，是因为三项修复与这批题、这套配置的作用面完全不相交。**

---

## 9. 引用索引

### 产品仓（`C:\develop\sayacode`）

| 内容 | 位置 |
|---|---|
| 版本 | `pyproject.toml:7` |
| 3.2.5 / 3.2.6 / 3.2.7 / 3.2.4 条目 | `CHANGELOG.md`（头部 4 节） |
| 摘要阈值计算 | `src/sayacode/agent/graph.py`（`summary_trigger_for`，3.2.7 与 HEAD 相同） |
| 摘要降级 | `src/sayacode/agent/summary.py`（`_require_usable` / `_degrade` / `_safe_degrade_cutoff`） |
| CompletionGuard | `src/sayacode/agent/graph.py`（`CompletionGuardMiddleware`、`_has_write_activity`、`_NUDGE_PROMPT`） |
| `completion_guard` 默认值 | `src/sayacode/config.py`（`completion_guard: bool = False`） |
| 提示与工具集一致 | `src/sayacode/prompts.py:94-107,116-122,146`；`src/sayacode/application.py:654` |
| 工具失败归因 | `src/sayacode/application.py`（`_record_tool_event`） |
| 工具事件投影 | `src/sayacode/agent/events.py`（`tool-finished` → `tool.failed` 当 `output.status == "error"`） |
| 检索限流 | `src/sayacode/tools/search.py:39-66,115-119,149-163`；`src/sayacode/tools/files.py:97-119` |
| Shell 失败返回值 | `src/sayacode/tools/shell.py:71,72-79` |
| Git 工具（复用 `_run_process`） | `src/sayacode/tools/git.py:68` |
| 评测文档 | `docs/PROMPT-OVERFIT-RISK.md`、`docs/VERIFY-20261103.md`、`docs/SUMMARY-FALLBACK-CHECK.md`、`docs/COMPLETION-GUARD-AB.md` |
| 历史实验台账 | `docs/evaluation/README.md:72`（qutebrowser 结论「已推翻」）、`:81`（`context_edit_keep` 与 4 个 pre-existing 失败） |

### 评测仓（`C:\develop\sayacode-bench`）

| 内容 | 位置 |
|---|---|
| 3.2.7 正式结果与配对 | `docs/FORMAL-RESULTS-20261106-327.md`（§3 Δ、§4 翻转、§5 批次差异）|
| 制品身份断链与解决 | `docs/RETROSPECTIVE-20261105.md` §4（含 11-06 更新）|
| 阶段 3 修复清单 | `docs/RETROSPECTIVE-20261105.md:43-53` |
| CompletionGuard A/B 结果 | `docs/COMPLETION-GUARD-RESULT.md`（全 58 行；§一 结果、§二 成本、§三 能说/不能说）|
| 深度分析（部分得分/饱和/行为/§10 摘要未触发） | `docs/DEEP-ANALYSIS-20261106.md` §1–§6、§8、§10 |
| variant 配置 | `studies/baseline.json`（`team_enabled: true`）|
| profile 预算 | `scripts/locked_agents.py:612,659`（192k / 32k）|
| 当前状态 | `docs/STATUS.md`（§72 制品差异描述）|
| 提示词过拟合风险 | `..\sayacode\docs\PROMPT-OVERFIT-RISK.md` §1、§3、§3.5、§4 |

---

*本文所有行号基于产品仓 `HEAD = 5c84486`（工作树干净）；制品相关内容已用 `git diff --stat <tag> <tag> -- src/` 逐版本核验。*
