# RESULTS LEDGER：全部对外数字的唯一真相源

| 项 | 值 |
|---|---|
| 版本 | **v1.0（2026-11-07）**，建立于 2026-11-07 全面复盘之后 |
| 地位 | **本文件是全部评测数字的唯一权威来源**。其他任何文档（STATUS / README / HANDOFF / 复盘 / 结果报告）**只允许引用，不得复制数字** |
| 依据 | [review/2026-11-07/RETROSPECTIVE-20261107.md](review/2026-11-07/RETROSPECTIVE-20261107.md) |
| 更新规则 | 只有**新的正式批次跑完并复算通过**才能改本文件；改任何一格都必须同时更新 §6 的生成命令与 §7 的变更记录 |

> ⚠️ **本文件不包含 `strict` 口径。** 该口径的前提（"verifier 不重置 `__snapshots__`"）已被证伪：642/642 个 `tests/test.sh:97-105` 在判分前对 `*__snapshots__/*` 执行 `git checkout HEAD`，`:101` 的 `__NONE__` 哨兵使跳过分支永不触发。agent 对快照的修改在判分时已被还原。**任何再次出现的 `strict` 数字一律视为错误。**

---

## 1. 口径定义

| 口径 | 定义 | 用途 | 约束 |
|---|---|---|---|
| **`planned`** | 分母 = 题数 × 重复数（40×2 = 80）；任何缺失按失败计 | **主报**，对外唯一可用 | 必须同时给缺失数与分类 |
| **`observed`** | 只含有 reward 或显式终态的子集 | **辅助** | **每次出现必须标注「幸存者偏差，会高估」** |
| **`partial`** | `verifier/output.json` 的 `tests[].status` 中 PASSED 占比（0–1 连续量） | **辅助**，对小样本对比比 0/1 敏感得多 | 必须写明是 trial 级均值还是题级均值；**不得用 `test-stdout.txt` 的 `Required tests` 口径**（见 §5.5） |
| `touches_snap_pass` | patch 触碰 `.snap` 且 `reward=1` 的 trial 数 | **仅行为描述** | **不参与任何排名**；必须注明"这些快照在判分前已被还原，不影响结果" |

**`task_macro`**：先按题归约重复、再对题取平均。只算 `complete_tasks`（有全部重复的题），因此分母常小于 40 —— **引用时必须标明分母**。

---

## 2. 主表：四组（`planned` 主报 + `partial` 辅助）

### 2.1 v2-325 批次（结果根 `C:\sb\hard\v2-325`；SAYACODE 制品 3.2.5 本地 wheel；2026-11-02 ~ 11-05）

| agent | **planned** | 缺失 | `observed`（辅助） | **`partial` trial 级** | **`partial` 题级** | `partial` n | `task_macro` | 题级全通过 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SAYACODE 3.2.5 | **78.8%** (63/80) | 1 | 79.7% (63/79) | **99.2%** | **98.9%** | 73 | 80.8% | 29/39 = 74.4% |
| mini-swe-agent | **85.0%** (68/80) | 1 | 86.1% (68/79) | **98.5%** | **98.6%** | 77 | 87.2% | 30/39 = 76.9% |
| Claude Code | **77.5%** (62/80) | 1 | 78.5% (62/79) | **97.8%** | **98.0%** | 76 | 78.2% | 25/39 = 64.1% |
| OpenCode | **75.0%** (60/80) | 0 | 75.0% (60/80) | **94.4%** | **94.6%** | 77 | 75.0% | 23/40 = 57.5% |
| ~~Codex CLI~~ | ~~68.8%~~ | — | — | — | — | — | **整组作废，不参与任何排名** |

- `touches_snap_pass`（描述性）：SAYACODE **0** / mini-swe 4 / Claude Code 3 / OpenCode 6 / ~~Codex 3~~。**不影响上述任何数字。**
- Codex 作废理由：`unsupported call: apply_patch` 373 次（78/80 trial）+ `/v1/responses` websocket 405 960 次（80/80 trial）。见 `docs/CODEX-BASELINE-INVALID.md`。

### 2.2 v4-327 批次（结果根 `C:\sb\hard\v4-327`；制品 PyPI `sayacode-3.2.7`；2026-11-05 22:55 → 11-06 06:35）

| agent | **planned** | 缺失 | `observed`（辅助） | **`partial`（题级均值）** | `worst` 界 | `best` 界 |
|---|---:|---:|---:|---:|---:|---:|
| SAYACODE 3.2.7 | **76.2%** (61/80) | 1 | 77.2% (61/79) | **97.8%** | 76.25% | 77.5% |

- 缺失 1：`vuls-4b680b99606 r1`，类别 `empty_patch`。
- `task_macro` 76.9%（39 题）、题级全通过 24/39 = 61.5%、`pass@2` 36/39 = 92.3%。
  **分母说明**：`task_macro` / `pass@2` / 题级全通过的分母是 `complete_tasks = 39`；若按全部 40 题算，`pass@2` 是 **37/40**（vuls 的 r2 通过、r1 空 patch）。**引用时必须说明用的是哪个分母。**
- `partial` 从 `C:\sb\analysis\dataset.json` 的 `sayacode/3.2.7` 子集算（**不能**从 `FINAL-SUMMARY-327.json` 直接取，见 §5.1）。
- served：按已有记录为 `hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572，零 `hy3-x`、零 deepseek。⚠️ **该记录的数据源已不在本机，未复核**——见 §5.6。

### 2.3 ⚠️ 两个批次不可合并排名

- 制品不同（3.2.5 本地 wheel vs PyPI 3.2.7）、时间不同（11-02~05 vs 11-06）、served 分布不同（按记录前者约 14.3% `hy3-x`、后者为零，**两者均未复核**，见 §5.6）、并发不同（2–4 vs 4/1）、网络修复状态不同。
- **任何跨这两张表的排名、差值、p 值都是批次效应与处理效应的混合物，不得使用。**
- `STATUS.md` 历史上出现过三行跨批次 McNemar（`327 vs mini` / `vs Claude` / `vs OpenCode`），经复算**无法重现**（common 写 40 而实测 38/39；OpenCode 行 p=0.791 实测 1.0），已从本 ledger 移除。

---

## 3. 配对比较（只在同一批次内）

### 3.1 v2-325 批次内六对（题级全通过，`complete` 题交集，McNemar exact）

| 对比 | 共同题 | a 独过 / b 独过 | p |
|---|---:|---:|---:|
| Claude Code vs mini-swe | 38 | 3 / 7 | 0.344 |
| Claude Code vs SAYACODE 3.2.5 | 38 | 4 / 7 | 0.549 |
| Claude Code vs OpenCode | 39 | 9 / 6 | 0.607 |
| mini-swe vs SAYACODE 3.2.5 | 38 | 6 / 5 | 1.000 |
| mini-swe vs OpenCode | 39 | 11 / 4 | 0.118 |
| OpenCode vs SAYACODE 3.2.5 | 39 | **1 / 7** | **0.070** |

- **全部不显著。** 四组共 6 对比较，Bonferroni α/6 ≈ 0.0083；即使按三组口径 α/3 ≈ 0.0167 也全部未达。
- 最小 p = 0.070（OpenCode vs SAYACODE），未过任何一个校正阈值。

### 3.2 3.2.7 vs 3.2.5（同制品族，78 个配对 trial）

| 项 | 值 |
|---|---|
| 通过 | 3.2.5：63/78 = 80.8% → 3.2.7：61/78 = 78.2% |
| Δ | **−2.6pp** |
| McNemar exact p | **0.8145**（不显著） |
| 题块 bootstrap CI95 | **[−12.5, +6.2] pp**（跨零） |
| 翻转 | 18 个 trial（3.2.5 独过 10、3.2.7 独过 8） |

**正确表述**：3.2.7 与 3.2.5 **未检出可测差异**。
**禁止表述**：「修复无效」——这套题 × 这套配置对三项修复的作用面为零（三重错配，见 §5.2），Δ 的信息量为零。

---

## 3.5 成本与机时（2026-11-07 第二轮复盘实测）

> 来源：[review/round2/M6-cost-ledger.md](review/round2/M6-cost-ledger.md)。**引用成本必须带口径**——同一批数据按不同分母能差近 2 倍。

| 口径 | SAYACODE 3.2.5（v2-325）| 说明 |
|---|---:|---|
| 每**成功任务** | **1.53M** tokens | 96.2M / 63 成功。历史文档常引「1.43M」，差 7%、同量级 |
| 每 planned 任务（80）| 1.20M | 缺失按失败计 |
| 每实际 job（119）| 0.81M | 含未跑完的 |

**历史「1.43M tokens/任务」的正确读法**：它是**每成功任务**口径，且属 SAYACODE **3.2.5 / v2-325 批次**。不得写成「SAYACODE 单任务成本」而不带批次与制品。

**批次机时总账**：有 duration 记录的 862 个 job，机时合计 **185.8h**、token **975.8M**（in 953.3 + out 22.5，含缓存重复，非计费量）。

**返工比例（关键）**：合计废弃 **1389/2263 = 61.4%**，**有效 : 返工 = 1 : 1.59**。分批次：v1 83.8%（66 轮 stage1 重试风暴）、v2 24.3%、v4 12.9%、SWE-EVO 14.3%。
**平均并发仅 1.6–2.0**（配置 4 也跑不满）。

→ **瓶颈是返工率与并发利用率，不是题量。** 任何「扩到 100 题要多久」的估算，若按理想并发算会低估 3–5 倍。

---

## 3.6 长上下文 A/B（2026-11-07 首次检出强差异）

> 完整报告：[EXPERIMENT-CONTEXT-AB-RESULT.md](EXPERIMENT-CONTEXT-AB-RESULT.md)。这是**本项目第一次检出统计上强、方向单向的差异**。

| 组 | 通过 | 通过率 |
|---|---|---:|
| clean（v4-327，无噪声） | 12/12 | **100.0%** |
| noise-100k（追加 ≈100k tokens 无关材料） | 7/12 | **58.3%** |
| **Δ** | — | **41.7 pp** |

- 配对：**clean-only 5 / noise-only 0**（完全单向），McNemar p=0.062，题块 CI95 **[+8.3, +83.3]** 不含 0。
- 逐题：**3/6 题退化**（flipt-io 0/2、navidrome 0/2、NodeBB 1/2），3/6 完全不受影响。
- 失败形态：**2 个空 patch**（放弃）+ **3 个有 patch 但没改对**。
- 机制已核验：单次 `input_tokens` 峰值 **95,645**（clean 常见 30–35k），**未越摘要线 150,400**（差 54,755）→ 测的是抗干扰，不是摘要。
- 环境已排除：5 个失败中 4 个 `record_complete=True` 且无异常；仅 navidrome r1 有 `NonZeroAgentExitCodeError`（判 infra，但仍按失败计入 planned）。`best` 界 8/12 = 66.7%，Δ = 33.3pp。

**红线**：
1. **只有 SAYACODE 一组，无基线对照** → **不能**说"抗干扰能力比基线差"。原因不是设计选择，而是**三条传参通道各有各的长度限制**：mini-swe 走 argv 撞 Linux `E2BIG`（128KB）、Claude Code 走环境变量撞 Windows 命令行（32KB）、只有 SAYACODE 走 variant 文件不受限。诊断见报告 §7。要跑通基线须两组都改成「容器内文件 + 提示读取」并重跑 SAYACODE。
2. n=6，p=0.062 未过 0.05（功效不足，非效应不存在）。
3. 噪声是"其他项目的 instruction 原文"，形态仍是编程任务描述 → **无法区分**「被无关内容干扰」与「被同类任务描述混淆」（见报告 §4.3）。

**噪声身份**：`C:\sb\hard\ab-ctx\noise-unified\unified-noise-100000.txt`，350,946 字符，sha256 `4ffb2924…`，排除 6 个目标仓库且经目标仓库名泄漏检查。

---

## 3.7 探索预算护栏验证（2026-11-07，第一个「评测→改进→验证」闭环）

> 完整报告：[EXPERIMENT-EXPLORE-GUARD-RESULT.md](EXPERIMENT-EXPLORE-GUARD-RESULT.md)。
> 失效模式诊断：[FAILURE-MODE-EXPLORE-ONLY-20261107.md](FAILURE-MODE-EXPLORE-ONLY-20261107.md)。

**背景**：长上下文 A/B（§3.6）里 12 个 trial 中 2 个**从未编辑过**（46/13 次只读后产 0 字节 patch），3 个到第 29–42 个动作才首次落笔。诊断为产品缺少收敛机制，实现 `ExploreBudgetMiddleware`（产品 `f3e283f`，默认关闭）。

**设计**：完整 6 题 × 2 重复 = 12 trial/组，同版本三组对照（排除 3.2.8 其它改动）：

| 组 | 通过 | 通过率 | 空 patch | 有编辑的 trial |
|---|---:|---:|---:|---:|
| clean（v4-327，无噪声）| 12/12 | **100.0%** | 0/12 | — |
| **guard**（3.2.8 + `explore_read_budget=12`）| **10/12** | **83.3%** | **0/12** | **12/12** |
| noguard（3.2.8，关闭）| 8/12 | 66.7% | 2/12 | 10/12 |
| hist（3.2.7，无此功能）| 7/12 | 58.3% | 2/12 | 10/12 |

**同版本对照**（唯一变量是护栏）：双方通过 7、**护栏修好 3**（NodeBB r1 / flipt-io r1 / navidrome r2）、**护栏搞坏 1**（tutao r2）、双方失败 1。**Δ = +16.7 pp**。

**护栏能救「改错型」**：flipt-io r1 无护栏时改错（5857B patch 但失败），有护栏时通过（6146B）——此前的「护栏对改错型无效」预判被推翻。

**红线**：
1. **统计不显著**：同版本 McNemar **p = 0.625**（不一致对仅 4 个，3:1）；相对历史 +25.0pp、p = 0.375。**效果量大但样本量远不足以检出**。
2. **不是无害的**：把 tutao r2 从通过变失败（真实干扰，1 例）。
3. **噪声退化未消除**：guard 仍 2/12 未通过（flipt-io r2 改错、tutao r2 被干扰），相对 clean 仍差 16.7pp。
4. **成本**：12 trial 挂钟 103 分钟 vs 90 分钟，单 trial 最长 **51.3 分钟**（含 1 次重试）。
5. **3.2.8 本身无可检出退化**：noguard 66.7% vs hist 58.3%，配对只差 1 个 trial，McNemar 1:0、p=1.0。

**未解决**：tutao r2 型干扰（需「探索:编辑比」健康度判断）、flipt-io r2 型改错（护栏到极限）、`12` 预算是拍的（未做剂量扫描）、51 分钟长尾（需空转收敛）、n=12 功效不足（要检出 +16.7pp 需 50–80 配对 trial）。

---

## 3.8 TodoList 提示压缩：成本优化（2026-11-07）

> 完整报告：[EXPERIMENT-TODO-COMPRESSION.md](EXPERIMENT-TODO-COMPRESSION.md)。产品变更 `3d45472`，版本 3.3.0。

**改动**：TodoList 两段提示 6,502 → **1,148 字符（-82%）**。量清楚后发现 81% 是 LangChain 框架默认文案，我们只追加 1,259。按 OpenCode 的 `todowrite.txt`（512 字符）重写，删的是重复说教（「简单任务别用」说了 5 次、「完成后标记」说了 6 次），**所有行为约束全部保留**。

**设计**：单变量对照，同 6 题 × 2 重复、同 noise-100k、同 profile。

| 指标 | 3.2.8（6,502 字符）| **3.3.0（1,148 字符）** | 变化 |
|---|---:|---:|---:|
| 通过率 | 8/12 = 66.7% | **8/12 = 66.7%** | **持平**（Δ=0，p=1.0）|
| **模型调用合计** | 489 | **342** | **-30.1%** |
| **input tokens 总量** | 27,563,182 | **23,253,792** | **-15.6%** |
| **耗时中位** | 13.0 分钟 | **7.7 分钟** | **-40%** |
| 工具调用合计 | 744 | 576 | -22.6% |
| 编辑合计 | 100 | 65 | -35% |
| 空 patch | 2/12 | 2/12 | 持平 |

**这是成功的成本优化，不是失败的实验**：同等质量下 tokens -15.6%、调用 -30%、时间 -40%。节省不只来自「每轮少 1,530 tokens」，更来自**调用次数少了 30%**——压缩后的提示不再让模型花轮次维护清单。

**但同时证伪了一个假设**：曾假设「todo 提示臃肿 → 模型过度规划、不敢下手」。压缩 82% 后**空 patch 仍是 2/12**（只是位置从 NodeBB r1 + navidrome r2 变成 flipt-io r1 + navidrome r1）。所以 **「不敢下手」与 todo 提示规模无关**；那段提示的规划引导实际上在推动行动（删掉后编辑 -35%），只是对通过率没有净贡献。

**已排除的两个假设**：①缺运行时提醒（middleware，已删）②todo 提示臃肿（本轮，压缩后持平但成本赚）。
**未测**：系统提示 **3,031 字符**（`build_system_prompt` 默认参数下的实测长度；早前写的 3,489 是未提交的临时状态，已作废）。

---

## 3.9 系统提示精简实验：负面结果（2026-11-07/08）

> 完整报告：[EXPERIMENT-PROMPT-SCALING.md](EXPERIMENT-PROMPT-SCALING.md)。实验分支 `exp/minimal-prompt`（`8c0b95d`），**不合并**。

**改动**：删 Role contract（645 字符）+ Communication contract（452 字符）+ 3 条执行契约，系统提示 3,031 → **1,261 字符（-58%）**。硬约束全部保留。

**设计**：单变量对照，todo 都是 1,148 字符，其余全同。

| 指标 | 3.3.0（提示 3,031）| **3.4.0-exp（提示 1,261）** | 变化 |
|---|---:|---:|---:|
| 通过率 | 8/12 = 66.7% | **7/12 = 58.3%** | **-8.4 pp** |
| 空 patch | 2/12 | **3/12** | +1 |
| 模型调用 | 342 | 365 | +6.7% |
| input tokens | 23,253,792 | 24,493,648 | **+5.3%** |

**四项指标全部变差。** 配对：变差 1（NodeBB r2）、变好 0，Δ = -8.3pp，McNemar p = 1.0（不一致对仅 1 个，不显著）。

**结论：「提示词越短越好」不成立。** 被删掉的内容里有实质东西——尤其 Communication contract 的「最终回复要说明改了什么、为什么、怎么验证」实际上在要求模型产出可交付的变更；Role contract 的「Own the user's objective end to end」定义做到底的态度。删掉后模型更容易只给分析不给改动，且**成本也上升**（不是省 token，是费 token）。

**与 §3.8 合起来看，区分了「该删的」和「不该删的」**：

| 变更 | 通过率 | 成本 | 判定 |
|---|---|---|---|
| todo 压缩 82%（3.2.8→3.3.0）| 持平 | **-40% 时间 / -15.6% tokens** | ✅ 保留 |
| 系统提示精简 58%（3.3.0→3.4.0-exp）| **-8.4pp** | **+5.3% tokens** | ❌ 回退 |

**局限**：n=12 不显著；只测一档（未做中间档）；一次删 5 块无法分离具体哪条有害；单次运行。

**下一步**：产品保留 3.3.0。「不敢下手」仍未解决（空 patch 2/12），而删「要求交付」的表述会让它更糟 → 应该**加强**而非删减，例如在 Communication contract 里明确要求「先落一个小改动再继续调查」。

---

## 3.10 系统提示 v2：精简做对了就有效（2026-11-08）

> ## ⚠️ 本节结论已被推翻
>
> 20 题配对验证（[EXPERIMENT-PROMPT-V2-SCALED.md](EXPERIMENT-PROMPT-V2-SCALED.md)）：
> v2 与 main **都是 13/20 = 65.0%，Δ = 0.0pp，p = 1.0**，空 patch 都是 2/20。
> 成本反而 +16.9% 调用 / +13.4% tokens。**v2 不上产品，产品停在 3.3.0。**
>
> 下面的 +8.3pp 和「空 patch 归零」都是 12 trial 的小样本噪声。
> 保留原文是为了记录「把不显著的正向摆动写成结论」这个教训。

> 完整报告：[EXPERIMENT-PROMPT-V2.md](EXPERIMENT-PROMPT-V2.md)。实验分支 `exp/prompt-v2`（`ba2ff08`），制品 3.4.1。

**背景**：§3.9 的 v1 精简（3,031 → 1,262）变差了。用户质疑「**也有可能是你精简的不够好**」——查证属实，v1 把字符砍到 42% 却一个 `never` 没减，约束密度反而上升，还删掉了唯一的交付要求。于是重写 v2。

**v2 的关键差异**（不是长度，是取向）：

| 指标 | main | v1（变差）| **v2（变好）** |
|---|---:|---:|---:|
| 字符数 | 3,031 | 1,262 | **1,115** |
| `never` | 5 | **5** | **0** |
| 有目标陈述 | 无 | 无 | **有** |
| 有交付要求 | 有 | **无** | **有** |
| 有「该动手」驱动 | 无 | 无 | **有** |

**结果**：

| 组 | 通过 | 通过率 | **空 patch** | 模型调用 | input tokens |
|---|---:|---:|---:|---:|---:|
| clean（无噪声）| 12/12 | 100.0% | 0/12 | — | — |
| **v2（1,115）** | **9/12** | **75.0%** | **0/12** | 491 | 26,448,202 |
| main（3,031）| 8/12 | 66.7% | 2/12 | 342 | 23,253,792 |
| v1（1,262）| 7/12 | 58.3% | 3/12 | 365 | 24,493,648 |

配对 vs main：**+8.3pp**（变好 2 / 变差 1，p=1.0）；vs v1：**+16.7pp**（变好 2 / 变差 0，p=0.5）。

**v2 是三轮里唯一 0/12 空 patch 的组** —— 这是之前加 `ExploreBudgetMiddleware` 想解决、但带来 tutao r2 干扰和 51 分钟长尾的问题。v2 用更简单的手段达到：**在提示词里直接写「知道该改哪个文件就动手」**，无需任何运行时机制。

**代价**：模型调用 +43.6%（342 → 491），input tokens +13.7%。

**红线**：① 统计不显著（n=12，p≥0.5）② 成本更高 ③ NodeBB r2 从 PASS 变 fail，不是无损 ④ 单次运行。

**顺带发现独立缺陷**：v2 的 flipt-io r2 产出 **24.2MB patch**，其中 25,396,314 字符是 **Go 编译产物 `flipt`**（真实代码改动只有 4,344 字符）。patch 采集应该排除未跟踪的构建产物——与提示词无关，是采集口径问题。

---

## 4. 新题库（SWE-EVO）状态
| 项 | 值 |
|---|---|
| 试点 | 5 题 × 2 重复 = 10 trial，`C:\sb\newset\runs\pilot1` |
| `planned` | **50.0%** (5/10) |
| 缺失 | 0 |
| `partial` | **不适用**（pilot 的 `partial` 字段为 `null`，verifier 输出未采集） |
| 逐题 | dask 2022.9.2 **0/2**（50 文件/1525 行）、dvc 1.11.12 1/2、dvc 2.21.1 **2/2**（1 文件/4 行）、dvc 2.58.1 0/2、dvc 3.15.0 **2/2**（1 文件/2 行） |

> ⚠️ **这份 50% 不能支撑「新题库更难」，也不能与 SWE-bench Pro V2 的 76.2% 比较。**
> 原因：`C:\sb\analysis\swe-evo-baseline.json` 只有 **4 条** `usable`，全是 dvc 的 **1–2 文件 / 2–21 行**小改动题；第 5 题（dask）是 `--include` 强制纳入的重题，实测 0/2。机制是：大改动题 p2p 多（dask 那题 2861 个）、镜像大 → 基线验证失败率高 → 被剔除 → **`usable` 集系统性偏向小改动题**。
> 扩样必须先按 gold 改动量分层抽样，不能用 `usable` 全集。详见 `docs/NEW-BENCHMARK-ONBOARDING.md` §5。

---

## 5. 已知数据缺陷（引用本 ledger 前必读）

### 5.1 `partial` 的数据源不唯一

`FINAL-SUMMARY-V4.json` 的 `trials[].partial` **字段覆盖极不完整**：`sayacode` **0/80**、`mini-swe` 13/80、`claude-code` 79/80、`opencode` 80/80。若直接对该文件求 partial 均值，SAYACODE 会得到空值。

**本 ledger 的 `partial` 一律取自 `C:\sb\analysis\dataset.json`**（391 行，`agent` + `tag` 区分批次），覆盖：sayacode/3.2.5 73/77、sayacode/3.2.7 72/77、mini-swe 77/78、claude-code 76/79、opencode 77/80。

**待修**：应让汇总脚本一次产出完整 `partial`，而不是依赖二次构建的 `dataset.json`。

### 5.5 `partial` 的两个数据源不可混用（2026-11-07 第二轮复盘实测）

同一批 trial，两种算法差 **2.4–6.8pp**：

| agent | `output.json`（**本 ledger 采用**）| `test-stdout.txt` | 差 |
|---|---:|---:|---:|
| SAYACODE 3.2.5 | **99.2%** (n=73) | 92.4% (n=77) | +6.8pp |
| mini-swe | **98.5%** (n=77) | 96.2% (n=78) | +2.4pp |
| Claude Code | **97.8%** (n=76) | 91.2% (n=79) | +6.6pp |
| OpenCode | **94.4%** (n=77) | 87.7% (n=80) | +6.7pp |

根因是**分母不同**：`output.json` 的 `tests` 集合与 verifier 判定 `reward` 所用集合一致；`test-stdout.txt` 的 `Required tests` 范围更大（同一 trial 上见过 6/6 vs 7/6 这类差异）。

**采用 `output.json` 的理由**：它与 reward 同源。若换成 `test-stdout`，partial 会与 planned 产生内部矛盾（plan 判通过而 partial < 100%）。

复算脚本：`C:\sb\tmp\verify_partial_source.py`。

### 5.2 Δ −2.6pp 的三重作用面错配

| # | 错配 | 证据 |
|---|---|---|
| 1 | 摘要降级路径**从未触发** | 单次输入峰值最大 127,369 < 触发线 **150,400**（`min(160000−9600, 192000×0.8)`，不是文档常写的 153,600） |
| 2 | 提示一致性修复**不改变行为** | `60ca2f0` 只在 `team_enabled=False` 生效；正式评测用 `studies/baseline.json` 的 `team_enabled=true` → 系统提示逐字节不变 |
| 3 | CompletionGuard **从未装配** | `completion_guard` 默认 `False`，`baseline.json` 的 `profile_overrides={}`；且 `41b1e38` 不在 3.2.7 制品内 |

### 5.3 3.2.7 制品实际只含两项修复

```
git diff --stat v3.2.5 ba43e04 -- src/
  src/sayacode/agent/graph.py    |   4 +-
  src/sayacode/agent/summary.py  | 116 ++++++++++++++
  src/sayacode/application.py    |   1 +
  src/sayacode/prompts.py        |  26 +++++
```

= 摘要失败降级 `c5d2973` + 提示/工具集一致性 `60ca2f0`。`41b1e38`（11-04 13:22）**晚于**发布提交 `ba43e04`（11-04 03:46）。
另：**PyPI 3.2.7 没有对应的 git tag**（最后 tag 是 `v3.2.6`）；HEAD 在 `ba43e04` 之后还有 4 个提交（+174/−20），全部不在制品内。

### 5.4 其他已知问题

- **「served 零 deepseek」当前不可复核（2026-11-07 降级）**。详细见 §5.6。
- `C:\sb\hard\v2-325\STRICT-COMPARE.json` 是**陈旧产物**（mtime 11-05 17:23，早于 11-06 的修复声明），其 `missing` 与 `FINAL-SUMMARY-V4.json` 不一致（mini 2 vs 1、Codex 1 vs 0）。**不要引用它的任何数字**，包括 `snap_passes`。
- `reward is None` ≠ 缺失（327 是 3 vs 1、v2 mini 是 15 vs 14）。统计缺失必须同时看 `terminal` 与 `reward`。
- 40 题是**开发迭代集**，SAYACODE 的提示词规则 R1–R5 正是从这套题的失败个案调出的，**偏置方向对 SAYACODE 有利**。
- **从未执行冻结签收**（`lock_candidate`），因此按 `PROTOCOL-V2 §1` 的定义，以上全部是"开发期诊断"，不是"对外正式成绩"。
- **trial 布局有四套不同结构**（v2 saya/mini 在 `verify/jobs`；v2 claude/opencode 内联在 `jobs`；v4 `jobs` 无 reward；pilot 不以 `instance_` 开头）。读取一律走 `sayacode_bench.trialdir`，不要自己 glob。

### 5.6 「四组 served 全是 hy3、零 deepseek」——**不可复核**（2026-11-07 新发现）

**原有声称**：评测窗口（10-31~11-05）内 42681 条 Magpie usage，四组基线 `served` 全是 `hy3`/`hy3-x`，零 `deepseek-v4.1-flash`。这条支撑了"四组统一模型"这个前提。

**复查结果**（`scripts/audit_served.py`，按 `User-Agent` 精确过滤并排除本机 DSH）：

| 项 | 结果 |
|---|---|
| 本地唯一数据源 | `C:\sb\magpie-export\config\routing`，**只有 2026-10-26 ~ 10-29 四个文件** |
| 记录数 | **13,332 条**（排除 DSH 6,005 条后 7,327 条）——**无法复现 42681** |
| 该窗口 SAYACODE 的 served | **deepseek 3,646 + glm 1,451**，**不是 hy3** |
| 10-30 之后的 routing 日志 | **本地不存在**（已搜 `C:\sb\` 全盘 jsonl、`AppData\Local\magpie`、`Programs\magpie`） |

**结论**：该声称**在当前机器上不可复核**。
- **不能**据此推翻它：可见窗口（10-26~10-29）早于 hy3 评测期（10-31 起），两者不重叠，而 10-26~10-29 那批用的确实是 deepseek/glm（与产品 evals 期的模型一致）。
- **也**不能再把它当"已验证事实"引用：支撑它的 42681 条数据不在本机，重跑不出同样的数。

**处置**：引用"四组统一模型"时，必须写成「按已有记录为 hy3/hy3-x；该记录的数据源已不在本机，**未复核**」，不能说"已验证零 deepseek"。
产物：`docs/evidence/served-distribution-20261107.json`（含 `comparison` 差异说明）。

---

## 6. 生成与复算

| 数字 | 来源 | 复算方式 |
|---|---|---|
| 四组 `planned` / 缺失 / `task_macro` / McNemar | `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json`（**不是** `FINAL-SUMMARY-V3.json`） | 读 `agents[].{planned,passes,missing}` 与 `stats.pairwise` |
| 327 | `C:\sb\hard\v4-327\FINAL-SUMMARY-327.json` | 读 `agents.sayacode`、`stats` |
| `partial` | `C:\sb\analysis\dataset.json` | 按 `agent`+`tag` 分组；先题内平均再题间平均 |
| `touches_snap_pass` | 同上 `dataset.json` 的 `touches_snap` 字段 | 计数；**仅描述性** |
| 327 vs 3.2.5 配对 | 两批 `FINAL-SUMMARY` 的 trial 级 `effective_reward` | 按 (task, repeat) 对齐取交集 |
| SWE-EVO pilot | `C:\sb\newset\runs\pilot1\FINAL-SUMMARY-PILOT.json`；reward 在 `sayacode\verify\jobs\*\*__*\verifier\reward.txt`（10 个） | 读 `agents.sayacode`；5/10 可复算（镜像已丢，不可重跑） |
| served 分布 | `C:\sb\magpie-export\config\routing`（**仅 10-26~10-29**） | `scripts/audit_served.py --since ... --until ...`；**无法复现 42681 条**，见 §5.6 |
| 快照重置行为 | `C:\sb\s\swe-bench-pro-v2-*\v2\tasks\*\tests\test.sh:97-105` | 全量扫描 642 个文件 |

复算脚本：`scripts/build_analysis_dataset.py`、`scripts/final_summary.py`、`scripts/strict_compare.py`（**仅用于历史排查，其 strict 输出不得引用**）。

---

## 7. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-07 | v1.0 | 建立。废除 `strict` 口径（前提被证伪）；新增 `partial`；移除三行跨批次 McNemar；标注 3.2.7 只含两项修复；标注 SWE-EVO pilot 的选择偏差 |
| 2026-11-07 | v1.1 | **第二轮复盘**：① 修正 Claude Code 的 trial 级 partial（97.9%→97.8%）；② 明确 `partial` 用 `output.json` 而非 `test-stdout.txt`（差 2.4–6.8pp，见 §5.5）；③ 新增 §3.5 成本与机时（返工 61.4%、并发 1.6–2.0）；④ STATUS/README/HANDOFF 按批次拆表 |
| 2026-11-07 | v1.2 | 第三轮：① 新增 §5.6——「served 零 deepseek」**不可复核**（数据源只到 10-29，42681 条无法复现），相关表述全部降级；② §6 补 `partial`/`served`/pilot 的精确复算路径；③ 「重建 ledger」端到端打通（`docs/REBUILD-LEDGER.md`，三条命令与本文逐项一致） |

---

**维护规则**：任何文档需要引用数字时，写「见 `docs/RESULTS-LEDGER.md` §x」而不是复制。发现本文件与原始 JSON 不符时，**以原始 JSON 为准**并立即修正本文件。
