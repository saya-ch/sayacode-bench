# pro-v2 四 agent 对比：结论更正与重算（2026-11-11）

> 本文**取代** commit `5d9dd3d` 的旧版《pro-v2 四 agent 对比：最终结果》。
> 旧版的核心结论「sayacode 与 opencode 在有效通过率上持平」**已被推翻**；原因不是算术错误，而是**分母口径错误**：把「模型长跑后零产出」当成基础设施失败并从分母里删掉。
> 本文保留旧版错误供追溯（§0），给出可复算的正确数字（§1–§3），并明确这些数字能用来做什么、不能用来做什么（§4–§6）。
> 所有数字可由 `C:\sb\tmp\run100\analyze.py` 复算；写作本文时已独立重跑一遍，输出与 `RESULT-40.md` **逐字一致（diff 0）**。

---

## 0. 结论更正

### 0.1 旧版说了什么

旧版 §1 的「有效通过率」表与 §2.2 的结论：

| agent | 旧版有效分母 | 旧版有效通过率 |
|---|---:|---:|
| claude-code | 36 | 83.3% |
| mini-swe | 34 | 82.4% |
| sayacode 3.3.0 | 29 | 75.9% |
| opencode | 37 | 75.7% |

> 「sayacode 75.9% / opencode 75.7%，差 0.2pp，配对 3-9 但 p=0.1460」
> 「有效通过率上 sayacode 与 opencode 持平」
> 「原始通过率 55.0% vs 有效通过率 75.9%，差 20.9pp 全部来自安装失败」

### 0.2 错因一：把「模型长跑后零产出」当成了基础设施失败

sayacode 的 11 条「基础设施失败」里，有两条**不是**基建失败：

| 任务 | 运行时长 | `normalized.json` 状态 | `model.patch` | `reward.txt` | verifier 是否执行 |
|---|---:|---|---:|---:|---|
| `sayacode-internetarchive__openlibrary-427f1-r1` | **2476 s** | `status=completed`、`original_reward=0`、`verified=true`、`harbor_exception_type` **为空** | **0 字节** | `0` | **是**（`test-stdout.txt` 含 `Required tests:`）|
| `sayacode-gravitational__teleport-b5d8169fc0-r1` | **1332 s** | 同上 | **0 字节** | `0` | **是** |

这两条的特征完全一致：**没有异常、verifier 正常跑完、reward=0、只是 patch 为空**。模型跑了 22–41 分钟后没有产出任何改动。按 [PROTOCOL-V2 §3/§6](PROTOCOL-V2.md)，这属于 `empty_patch`（能力/行为类，**不补**），必须留在分母里；把它们删掉等于把模型的两道失败题从分母里抹掉。

**后果**：旧版把 11 条都算作 infrastructure，sayacode 的分母从 34 压到 **29**，通过率从 **22/34 = 64.71%** 虚高到 **22/29 = 75.86%**（+11.15pp），并凭空造出「与 opencode 持平」。

### 0.3 分母是怎么一步步变小的

sayacode 的 11 条非通过 trial 实际由四类构成（逐条核实，见 §7 证据）：

| 类别 | 条数 | 判定 | 是否应排除 |
|---|---:|---|---|
| 真基础设施失败（30–74 秒内 `NonZeroAgentExitCodeError` / `RuntimeError`，无 reward） | 6 | `infra` | **应排除** |
| 启动后异常退出（172 s / 138 s，有 verifier 输出 reward=0，异常 `NonZeroAgentExitCodeError`） | 2 | 边界（见下） | 待定 |
| 超时（3101 s，`AgentTimeoutError`） | 1 | `timeout` | **不排除**（能力/预算类） |
| 长跑零产出（2476 s / 1332 s，无异常、空 patch） | 2 | `empty_patch` | **不排除**（能力/行为类） |

按不同排除规则得到的 sayacode 通过率：

| 排除规则 | 分母 | 通过率 | 说明 |
|---|---:|---:|---|
| **只排除 6 条真 infra**（本文采用） | **34** | **64.71%** | `analyze.py` 的 `effective` 口径 |
| 再加 2 条「启动后异常退出」 | 32 | 68.75% | 这两条的异常类型像 harness 失败，但 verifier 已给出 reward=0；属口径边界 |
| 再加 1 条 timeout | 31 | 70.97% | 排除超时违反「timeout 不补」原则 |
| 再加 2 条空 patch（旧版做法） | **29** | **75.86%** | **错误**：把模型失败当基建失败 |

> 口径核对：旧版原文写的分母是 **29**；任务简报里提到的「34 变成 31」对应的是「再排除 2 条空 patch + 1 条 timeout」的中间口径（70.97%）。本文以可复算的 **34 / 64.71%** 为准。

### 0.4 旧版里正确的是哪一半：`reward` 优先

旧版有一条规则是对的，本文保留：

> Harbor 在 job 收尾时用 `infrastructure_error` 覆盖已通过的 trial，所以分类必须 **`reward` 优先**。

`analyze.py` 的规则（文件头注释原文）：

1. `verifier/reward.txt` 是 ground truth，不是 `normalized.json.status`；
2. 只有「verifier **完全没有**产出 reward **且** 异常来自 harness」才算出 `infrastructure`；
3. 超时留在分母（是 agent 的失败，不是我们的失败）；
4. 同一 `(agent, task)` 多条记录去重，优先有裁决的。

旧版的错误不是「用了 reward 优先」，而是**只用了 reward==1 优先、没把 reward==0 留在分母**：它把「有 reward=0 但 status 是 infrastructure_error」也归成了基建失败。

### 0.5 更正后的一句话

**「sayacode 与 opencode 持平」不成立。** 按统一口径，effective 通过率是 **claude-code 81.08% > mini-swe 75.68% > opencode 73.68% > sayacode 64.71%**；planned 通过率是 **75.0% / 70.0% / 70.0% / 55.0%**。六对 McNemar **全部不显著**（最小 p=0.1094），MDE 约 22pp——**因此这份结果不能用于排名**。

---

## 1. 正确数字（三口径）

> 来源：`C:\sb\tmp\run100\analyze.py` 对 `C:\sb\hard\ab-ctx\prov2-40x4` 的复算；输出 `RESULT-40.md` / `RESULT-40.json`。
> 40 题 × 1 repeat × 4 agent = 160 trial；题集 `studies/large-sample-v1-pro-v2.json`（与旧开发集零重叠）。

| agent | ok | model | timeout | infra | **all（40）** | **effective（排除 infra）** | **complete-case（29 题）** |
|---|---:|---:|---:|---:|---:|---:|---:|
| sayacode 3.3.0 | 22 | 11 | 1 | 6 | 55.0% | **64.71%（22/34）** | 62.1%（18/29） |
| mini-swe-agent | 28 | 9 | 0 | 3 | 70.0% | **75.68%（28/37）** | 75.9%（22/29） |
| claude-code | 30 | 7 | 0 | 3 | 75.0% | **81.08%（30/37）** | 86.2%（25/29） |
| opencode | 28 | 10 | 0 | 2 | 70.0% | **73.68%（28/38）** | 69.0%（20/29） |

口径定义：

- **all**：分母 = 40，infra / timeout 都按失败计（最保守，适合对外报「实际完成率」）。
- **effective**：分母 = 40 − infra（**timeout 留在分母**）。这是「排除我们跑不起来的部分」后的能力对照。
- **complete-case**：只用四家都没有 infra/timeout 的 29 题（同一分母），排除「题目本身在这个环境里坏掉」的影响。

三口径给出**两种排序**：

| 口径 | 排序 |
|---|---|
| all | claude 75.0% > mini-swe 70.0% = opencode 70.0% > sayacode 55.0% |
| effective | claude 81.08% > mini-swe 75.68% > opencode 73.68% > sayacode 64.71% |
| complete-case | claude 86.2% > mini-swe 75.9% > opencode 69.0% > sayacode 62.1% |

共同点：**sayacode 在三种口径下都是最后一名**；opencode 与 mini-swe 在 all 口径并列。旧版「sayacode 与 opencode 持平」在任何口径下都不成立。

### 1.1 逐题矩阵

见 `RESULT-40.md` 的逐题矩阵（`1`=通过、`0`=模型失败、`T`=超时、`I`=基础设施失败）。按 repo 的细分（effective 分母）也在同文件。

---

## 2. 配对检验与检验效能

### 2.1 六对 McNemar（精确二项，双侧）

只用双方都有裁决、且都不是 infra 的题；timeout 记为失败。

| 对比 | 共同题 | 仅 A 过 | 仅 B 过 | 率差 | p | Bonferroni 0.0083 |
|---|---:|---:|---:|---:|---:|---|
| sayacode vs mini-swe | 31 | 3 | 7 | −12.9pp | 0.3438 | 否 |
| sayacode vs claude-code | 33 | 2 | 8 | **−18.2pp** | **0.1094** | 否 |
| sayacode vs opencode | 34 | 3 | 5 | −5.9pp | 0.7266 | 否 |
| mini-swe vs claude-code | 34 | 1 | 4 | −8.8pp | 0.3750 | 否 |
| mini-swe vs opencode | 35 | 5 | 4 | +2.9pp | 1.0000 | 否 |
| claude-code vs opencode | 37 | 7 | 4 | +8.1pp | 0.5488 | 否 |

**6 对全部不显著（Bonferroni 0.0083，最小 p=0.1094）。**

> 与旧版的差异：旧版给的是 40 对全配对（infra 记失败）的 p=0.0574（3 vs 11，−20.0pp）；本文用「双方都可评估」的 33 对（2 vs 8，−18.2pp，p=0.1094）。两种算法都不显著，但**不能用旧版的 p=0.0574 说「接近显著」**——它把 sayacode 跑不起来的题算成了它输。

### 2.2 MDE：不显著不能读成「没有差异」

- `analyze.py` 明确输出：**40 题、25% 不一致率下，双侧 α=0.05、power=0.8 可检出的最小差异约 22.1pp**。
- 也就是说：**小于约 22pp 的真实差异，本设计测不出来**。「p 值不显著」只说明「没有证据表明有差异」，不能反推「两者一样」或「持平」。
- 本文观测到的最大差距是 sayacode vs claude-code 的 −18.2pp，**仍在 MDE 之内**——方向可能有参考价值，但不满足任何预注册显著性标准。

---

## 3. flaky：13–35%（**外部估计，未在 prov2 上直接测**）

### 3.1 数据来源与数值

从 `C:\sb\hard\v2-325` 的 r1/r2 同题两次运行的 reward 不一致率（独立复算）：

| agent | 可配对题 | 不一致题 | **flaky rate** |
|---|---:|---:|---:|
| sayacode | 39 | 5 | **12.8%** |
| mini-swe | 32 | 7 | **21.9%** |
| claude-code | 39 | 11 | **28.2%** |
| opencode | 40 | 14 | **35.0%** |

### 3.2 这个估计的边界（必须随数字一起引用）

- **是外部估计**：来自 `v2-325`（不同题集、不同产品版本、不同时间窗），**不是 prov2-40x4 直接测出来的**。
- 两次运行跨时间，不一致率里混有「跨时间漂移」，不纯是采样随机性——这会让估计**偏保守**（真实单跑噪声不会更低）。
- 要得到 prov2 自己的 flaky，必须对 prov2 的题做 ≥2 次重复；本次没有做。
- 若同一题两次运行高度相关（同一 agent 行为相似），真实 flaky 可能低于该估计，MDE 会更乐观——这个假设无法用现有数据验证。

### 3.3 它意味着什么

1. **40 题单跑，题级通过数的噪声 SD 约 4 题（约 10pp）**。任何小于 10pp 的排名差异都是噪声级别；旧版的「75.9% vs 75.7%（差 0.2pp）」「83.3% vs 82.4%（差 0.9pp）」**完全在噪声范围内**。
2. **「不显著」与「持平」是两句话**：本设计连 22pp 以下都测不出，把「不显著」写成「持平」是双重错误。
3. **加题救不了这件事**。本次复算的模拟（模型：真实能力 + 单题独立翻转；α/6=0.0083；2000 次/格）：

   | 场景 | 40 题 | 100 题 | 160 题 | 240 题 |
   |---|---:|---:|---:|---:|
   | flaky=25%，真实差 20pp | 2.2% | 9.8% | 17.9% | **34.5%** |
   | flaky=25%，真实差 10pp | 0.7% | — | — | **5.2%** |
   | flaky=12.8%，真实差 20pp | 8.2% | 32.0% | — | 83.3% |

   读法：在 25% 翻转下，**即使每组扩到 240 题，20pp 差异的检出率也只有约 35%（远低于 80%）**；10pp 差异在 240 题仍只有约 5%。**「扩到 100 题就能解决显著性」的说法不成立**（100 题对 20pp 只有约 10% power）。
4. **同一份数据里，flaky 越低的组越容易被检出**（12.8% 时 240 题对 20pp 有 83% power，25% 时只有 35%）。这意味着组间 flaky 差异本身会扭曲比较——见 §3.4。

### 3.4 推断：flaky 不同会制造「假持平」（推断，未直接验证）

若把单题观测近似为「真实结果以概率 f 翻转」，则观测通过率会被拉向 50%：
`观测 = 真实 × (1−f) + (1−真实) × f`。

用这组数字演示：真实 55% 的组（f=12.8%）→ 观测 53.7%；真实 70% 的组（f=35%）→ 观测 56%。**15pp 的真实差距被压到约 2pp**。这与旧版「75.9% vs 75.7%」的假象方向一致——当然旧版的主因是分母，这里只是说明 flaky 差异会额外放大「持平」错觉。

> 这是**推断**，不是观测：翻转率与真实能力可能相关（强模型表现更稳定），实际压缩效应需要设计实验确认。

### 3.5 结论：降 flaky 比加题重要

- 翻转集中在少数题（`element-web`、`flipt`、`qutebrowser`、`openlibrary` 居多）——先查这些题为什么两次结果不同（测试不稳定？快照？并发？），把 flaky 压到 5% 以下，比把 40 题扩到 240 题更划算。
- 在当前 flaky 下，**40 题结果只能用于找方向，不能用于排名**（见 §4）。

---

## 4. 已被独立证实的另外三件事

### 4.1 判分口径可靠：108 条 `reward=1` 全部有验证器实跑证据

- 160 条 trial 中 **108 条 `reward=1`**；逐条检查 `verifier/test-stdout.txt` 是否含 `Required tests:` / `RESULT: PASSED`：**108/108 有证据，0 例外**（本次独立复核）。
- `normalized.json` 与 `reward.txt` 冲突的记录共 **3 例**（claude-code `element-web-fe14847bb9`、mini-swe `qutebrowser-ff1c025ad`、mini-swe `teleport-db89206db6`），全部是 `reward=1` 而 `normalized` 记 `infrastructure_error`/`timeout`；按「reward 优先」判为真通过，与 `test-stdout` 一致（后两例 `reward.txt` 与 `test-stdout.txt` 的 mtime 相差 0.02 秒，是同一次验证写出）。
- 旧版说「4 个误判」，本次独立核对只确认 **3 个**；第 4 个在现有产物中找不到对应证据（**未复核**）。

### 4.2 题集抽样无偏

40 题的 repo 分布与 642 题池的比例基本一致（如 ansible 5/40 vs 池 12.8%、flipt 5/40 vs 12.1%、qutebrowser 4/40 vs 11.4%），**不是「偏袒某一家」**。

但有两个限制必须标注：

- `tutao` 只有 1 题、`protonmail` 只有 3 题，且 protonmail 的 infra 率极高（claude 2/3、opencode 2/3、sayacode 2/3）——这两个 repo 的结论不可用。
- 真正有区分力的题约 10–12 题（vuls 4/4 全过、tutao 1/1 全过），与 flaky 叠加后进一步压缩功效。

### 4.3 sayacode 的基础设施失败率确实高——但「20.9pp 全部来自安装失败」是错误归因

- 真 infra：sayacode **6/40 = 15%**，mini-swe 3/40 = 7.5%，claude-code 3/40 = 7.5%，opencode 2/40 = 5%。**这是真实的产品缺陷**：只有 sayacode 需要 `pip install` 完整产品 wheel，其他三个用内置运行时。
- 但旧版「原始通过率 55.0% vs 有效通过率 75.9%，差 20.9pp 全部来自安装失败」**不成立**：这是**分母从 40 缩到 29 的算术效应**，不是分数提升。若安装不失败，这 6 题也不会全过——按 sayacode 在这些 repo 的通过率（ansible 2/5、flipt 2/4、openlibrary 2/4）期望只能补约 2.4 题，约 **24.4/40 ≈ 61%**，仍低于 claude 的 75%。
- 更关键的是：这 6 条 infra 里有 **3 条是其他三家全过的题**（`ansible-185d…`、`flipt-756f0…`、`openlibrary-91efe…`）。把 sayacode 跑不起来的题从它分母里删掉、却保留其他家的得分，**两边都不公平**。

---

## 5. 这份结果能用来做什么、不能用来做什么

| 用途 | 能否 | 理由 |
|---|---|---|
| **内部调优方向**（sayacode 该修什么） | **能用，但要限定** | 「sayacode 安装链路失败率 15% vs 5–7.5%」是直接计数，不依赖统计模型；「sayacode 在 flipt（2/4 vs 对手 4–5/5）、internetarchive（2/4 vs 3–4/5）、gravitational（1/4）上弱」是跨多题的一致模式。这两个结论可以指导修复。 |
| **排名 / 「谁更强」** | **不能用** | flaky 13–35% + 40 题 + Bonferroni α/6 → 小于约 22pp 的差异都检不出；任何「持平/领先」都在噪声内。 |
| **对外宣称** | **不能用** | 同上，且按 `PROTOCOL-V2 §1`，未执行冻结签收的一律是开发期诊断，不是对外正式成绩。 |
| **effective 通过率的比较** | **只能用统一口径** | 必须写清分母规则（排除哪些、为什么），不能把旧版的 29 分母与新版 34 分母混用；旧版「与 opencode 持平」的表述**已作废**。 |

**一句话**：本结果可用于内部调优方向；**不可用于排名或对外**。要让它能用于排名，必须先降 flaky（把 25% 压到 5% 以下），再谈题量。

---

## 6. 产物与复算

| 项 | 路径 |
|---|---|
| 结果数据根 | `C:\sb\hard\ab-ctx\prov2-40x4` |
| 复算脚本 | `C:\sb\tmp\run100\analyze.py` |
| 复算输出 | `C:\sb\tmp\run100\RESULT-40.md`、`RESULT-40.json` |
| 对抗复核（flaky/MDE/分母审计） | `C:\sb\tmp\audit\challenge\CHALLENGE.md` 及同目录脚本 |
| 数字独立重算 | `C:\sb\tmp\audit\numbers\NUMBERS.md`、`recompute_prov2.py` |
| 基建失败取证 | `C:\sb\tmp\audit\infra\`（`ROOTCAUSE.md`、`evidence.txt`） |

复现：

```powershell
cd C:\sb\tmp\run100
python analyze.py --root C:\sb\hard\ab-ctx\prov2-40x4 --out C:\sb\tmp\run100\RESULT-40.md
```

---

## 7. 证据明细：sayacode 的 11 条非通过 trial 逐条登记

> 用于支撑 §0.3 的四类拆分。`duration` 与 `exception` 取自各 trial 的 `normalized.json`；`reward` 取自 trial 子目录的 `verifier/reward.txt`。

| # | 任务 | duration | `harbor_exception_type` | reward | `model.patch` | 分类 |
|---:|---|---:|---|---:|---:|---|
| 1 | `ansible-185d41031660a676c` | 34 s | `NonZeroAgentExitCodeError` | — | — | 真 infra |
| 2 | `element-web-880428ab94` | 39 s | `NonZeroAgentExitCodeError` | — | — | 真 infra |
| 3 | `flipt-756f00f79ba8abf9fe` | 36 s | `RuntimeError` | — | — | 真 infra |
| 4 | `openlibrary-91efee627df01e32007abf2d6` | 31 s | `NonZeroAgentExitCodeError` | — | — | 真 infra |
| 5 | `protonmail-webclients-09fcf0dbdb8` | 68 s | `NonZeroAgentExitCodeError` | — | — | 真 infra |
| 6 | `protonmail-webclients-e7f3f20c8ad` | 74 s | `NonZeroAgentExitCodeError` | — | — | 真 infra |
| 7 | `flipt-6fe76d024ee0c50ddb` | 172 s | `NonZeroAgentExitCodeError` | 0 | 0 | 边界（启动后异常退出） |
| 8 | `teleport-78b0d8c72637df1129` | 138 s | `NonZeroAgentExitCodeError` | 0 | 0 | 边界（启动后异常退出） |
| 9 | `ansible-40ade1f84b8bb10a6` | **3101 s** | `AgentTimeoutError` | 0 | 0 | timeout |
| 10 | `openlibrary-427f1f4eddfc54735ca451779d` | **2476 s** | **（空）** | 0 | **0 字节** | **empty_patch（模型失败）** |
| 11 | `teleport-b5d8169fc0a5e43fee2616c905` | **1332 s** | **（空）** | 0 | **0 字节** | **empty_patch（模型失败）** |

第 10、11 条是本次更正的核心：`status=completed`、`verified=true`、`exception` 为空、`test-stdout.txt` 含 `Required tests:`、`model.patch` 0 字节。**这是模型跑了 20–41 分钟后零产出的能力失败，不是基础设施失败。**

---

## 8. 仍然不确定的（不要当成已知）

1. **flaky 13–35% 是外部估计**（来自 `v2-325`，不同题集/版本/时间），**未在 prov2-40x4 上直接测**；要精确必须对 prov2 做 ≥2 次重复。
2. **两条空 patch 的成因未确认**：`audit.jsonl` 的 schema 与现有解析器不匹配，无法确认模型是「写了又撤销」还是「采集失败」。只能确认「无异常、verifier 跑完、patch 为空」。
3. **第 7、8 条「启动后异常退出」的分类是口径边界**：它们的异常类型像 harness 失败，但 verifier 已给出 reward=0。本文按 `analyze.py` 归为 `model`；若归 `infra`，sayacode 分母变 32、通过率 68.75%（见 §0.3 敏感性表）。**这是本报告最大的口径不确定性。**
4. **旧版「4 个误判」只确认 3 个**，第 4 个未找到证据。
5. **MDE 模拟依赖「单题独立翻转」假设**；若两次运行相关，真实 flaky 更低、MDE 更乐观。模拟不是精确功效计算。
6. **F2P/partial 未纳入本文**：`partial` 的数据源不统一（`output.json` vs `test-stdout` 差 2.4–6.8pp，见 [RESULTS-LEDGER §5.5](RESULTS-LEDGER.md)），旧版的 F2P 表（86.83% 等）来自旧算法，**未复核**，不应引用。
7. **模型版本**：本次 SAYACODE 为 3.3.0；与历史 `v2-325`（3.2.5）的对照只记录、不做因果解释（见下）。

---

## 9. 与历史批次的对照（只记录，不解释）

| agent | 历史 `v2-325` planned | 本次 effective | 差异 |
|---|---:|---:|---:|
| mini-swe | 85.0% | 75.68% | −9.3pp |
| sayacode | 78.8%（3.2.5） | 64.71%（3.3.0） | −14.1pp |
| claude-code | 77.5% | 81.08% | +3.6pp |
| opencode | 75.0% | 73.68% | −1.3pp |

**不要读这张表**：两边是不同题集（`sample-40-final` vs `large-sample-v1-pro-v2`）、不同制品（3.2.5 vs 3.3.0）、不同重复设计（2 repeat vs 1）、不同分母口径（planned vs effective）。它只能说明「跨批次比较必须先对齐这五项」，不能用于任何排名或因果判断。
