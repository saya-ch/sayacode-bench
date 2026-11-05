# PROTOCOL-V2：正式评测协议 v2（现行）

> 更新：2026-11-02。状态：**现行正式协议（统计 / 缺失 / 补跑 / 冻结签收部分）**。
> 关系：本文件取代 [protocol.md](protocol.md) 中与统计口径、缺失分类、补跑规则、冻结签收相关的条款；[protocol.md](protocol.md) 作为 v1 预注册保留（研究问题、数据来源、模型连接、评分器校准、预算与交付边界继续有效）。两者冲突时，以本文件为准，且仅限上述四类条款。
> 依据：v2 开发期 240-trial 重跑（[FORMAL-RESULTS-20261102-v2.md](FORMAL-RESULTS-20261102-v2.md)）与真实踩坑记录（[LESSONS-20261102-v2.md](LESSONS-20261102-v2.md)）。

## 0. 一句话

**统一 planned 80 分母；题级 Wilson + 任务块 bootstrap；题级 McNemar；缺失必须分类并给 worst/best 界；环境类可补、timeout 不补；冻结签收后才算对外成绩。** 开发期诊断数字一律不对外。

## 1. 开发期诊断 vs 对外正式成绩（硬边界）

| 维度 | 开发期诊断（本仓库 docs、`C:\sb\hard\*`） | 对外正式成绩（冻结后） |
|---|---|---|
| 目的 | 找方向、定位失败模式、迭代 harness | 报告可对外引用的完成率与成本 |
| 数据 | 40 题开发迭代集，允许复用缓存题 | 冻结的 manifest（题 ID、seed、实现哈希）|
| 分母 | 可 observed/task_macro 辅助，但必须同时给 planned | **以 planned 为主**，缺失按失败 |
| 缺失 | 分类记录，用于诊断 | 冻结前补齐或按 worst 计入，不接受「删掉失败」|
| 身份 | 不对外，不作模型强弱证据 | 签收单 + 报告模板 + 实现身份 |
| 变更 | 可反复重跑 | 签收后不得改分母/换题/改补跑规则 |

**规则**：开发期跑出的任何数字（包括 v2 的 78.8% / 70.0% / 68.8%）都是**开发期诊断**，不得写成对外正式成绩，也不得据此宣称「SAYACODE 更强/更弱」。对外结论必须走 §7 冻结签收。

## 2. 分母：planned / observed / task_macro

同一批数据必须同时给三个口径，**主报 planned**：

| 口径 | 定义 | 用途 |
|---|---|---|
| **planned** | 设计的所有 trial（40 题 × 2 重复 = 每 agent 80）；任何缺失按失败计 | **主报**，对外唯一可用分母 |
| observed | 有 reward / 终态的子集 | 辅助；必须显式标注幸存者偏差 |
| task_macro | 先对每题重复求均值、再对题求均值 | 辅助；与 trial 级 pass@1 并列时说明差异 |

**反例（v2 实测）**：mini-swe observed 84.8%，但 planned 只有 70.0%（56/80，只有 66 条终态）。**只报 observed 会把 70.0% 说成 84.8%**，是典型高估。任何表格缺 planned 列即不合格。

## 3. 缺失分类（互斥、逐条可核）

每一条缺失必须落到下面一类，并附证据：

| 分类 | 含义 | 判定证据 | 是否可补 |
|---|---|---|---|
| `infra` | 环境/网络/安装失败（TLS exit≠0、apt 502、代理 gaierror、容器崩溃、镜像缺失）| job.log / exception.txt / curl 实测 | **可补** |
| `no_job` | 有 trial 目录但没有可执行 job 记录 | jobs 目录 + normalized.json 缺失 | **可补** |
| `timeout` | agent 在官方时间预算内未完成 | trajectory 尾部、时间戳 | **不补**（能力/行为）|
| `empty_patch` | agent 正常完成但 `model.patch` 为 0 字节 | patch 字节数 + verified + reward | **不补**（能力）|
| `model_fault` | 真 API 故障（ECONNRESET、5xx 连续） | model_failures 字段 | 可补（同一 condition，需记录）|
| `unverified` | 有 patch 但未完成独立验证 | verify/jobs 缺失或 ValueError | **可补**（重跑验证）|

- **`empty_patch` ≠ `model_fault`**：v1 tutanota 两条 `completed + verified + reward=0` 是空 patch，曾被误报为模型故障；只有 ECONNRESET 才是真故障（v1 仅 1 条）。分类错误会系统性冤枉模型（LESSONS §3.4）。
- **`timeout` 归行为类**：mini-swe 的 vuls 死循环（`sleep 29` 撞 30s 工具超时）是轮询逻辑问题，不能算 infra，也不能用 SWE-bench timeout 直接评价其能力（LESSONS §3.1）。
- 报告必须给「每条缺失的 agent / 题 / repeat / 分类」明细表，不能只给总数。

## 4. worst / best 界（缺失敏感性）

对任何有缺失的 agent，必须同时给：

- **worst = planned**（缺失全按失败，即主报值）；
- **best = 缺失全按成功**（上界）。

例（v2 mini-swe）：worst 56/80 = 70.0%，best (56+14)/80 = 87.5%。**两个数都给出**，读者才能判断缺失对结论的影响。只给一个界即为选择性报告。

## 5. 统计方法（题级，不是 trial 级）

1. **Wilson CI 用题级 n**：n = 题数（40），不是 trial 数（80）。每题的两次重复先合并成题级 pass 定义，再算 CI。
2. **任务块 bootstrap**：10,000 次、固定 seed（如 20261022），重复试验跟随其任务一起抽样；任务数 < 2 不生成区间。
3. **题级 McNemar**：用**题级 pass（不用 best-of-2）**做配对；两两比较 Bonferroni α/3 = 0.0167。
4. **仓库簇 bootstrap**（9 仓库）只作敏感性分析，不能独立证明生产泛化。
5. 区间跨零或 p 未过校正 → 写「证据不足 / 不显著」，不写「已证明提升」。v2 三 agent 校正后**均不显著**。

### 5.1 改快照通过（snapshot-modification pass，单列）

**verifier 的 reset 范围**（以 `tests/test.sh` 为准）：

- **测试代码**（`tests/`、`test`、`__tests__`、`spec`、`specs` 目录；`*_test.go`、`*.test.tsx`、`test_*.py` 等）→ 判分前 `git checkout HEAD -- <path>` **重置**，对 reward **无效**。
- **数据/快照目录**（`testdata`、`test_data`、`fixtures`、`fixture`、`mocks`、`mock`、**`__snapshots__`**）→ 命中则**排除、不重置**；因此修改 `__snapshots__/*.snap` 对 reward **有效**。

**结论：**「修改快照而后通过」是**有效但必须单列的类别**——它不是作弊（快照本就是允许更新的数据），也不能混进 pass@1 主表当作普通 pass。纯改测试代码（如 `test_pip.py`、`*_test.go`）会被重置，**不构成作弊**。

**严格口径（扣除靠改 `.snap` 通过）**：

| agent | 主表 planned | 改 `.snap` 通过的 pass | 严格 planned% |
|---|---|---|---|
| SAYACODE | 78.8% | 0 | **78.8%** |
| mini-swe | 85.0% | 4 | **80.0%** |
| Claude Code | 77.5% | 3 | **73.8%** |
| OpenCode | 75.0% | 6 | **67.5%** |
| ~~Codex~~ | 68.8% | 3 | 65.0% | **整组作废，不参与排名** |

- **主报口径始终是 planned**（缺失按失败）；**strict 必须同表给出**（不得只给 planned 而不给 strict，也不得只给 strict）。
- 允许在两套口径下分别排名，但必须并列展示，因为**三种口径给出三种排名**（planned 与 strict 下 mini-swe 对 SAYACODE 的领先从 6.2pp 缩到 1.2pp）。
- 依据与逐题明细：[TEST-EDIT-ANALYSIS-20261102.md](TEST-EDIT-ANALYSIS-20261102.md)、[FORMAL-RESULTS-20261105-v3.md](FORMAL-RESULTS-20261105-v3.md)。
- **报告要求**：每张成绩表附「改 `.snap` 通过的条数」与严格口径；**不得**用「patch 含测试文件」当作弊指标——它混入了大量会被 verifier 重置的无效改动。
- **多重比较**：四组共 6 对比较，Bonferroni 校正后 α/6 ≈ 0.0083（三组时为 α/3 ≈ 0.0167）。报告必须写清「几对比较 × 哪个 α」，不能混用。

## 6. 补跑规则（v2 最大教训）

- **可补**：`infra` / `no_job` / `unverified`——这些与模型能力无关，是环境噪声。
- **不补**：`timeout` / `empty_patch`——属能力或行为，补跑等于给某 agent 额外机会，破坏可比性。
- **`empty_patch` 必须先排除 infra**（2026-11-05 修正）：agent 安装失败（apt 撞 fake-ip、`NetworkConnectError`）时 patch 同样是 0 字节，但根因是环境，**必须判 `infra` 而不是 `empty_patch`**。判定方式是 job 级 `normalized.json` 的 `harbor_exception_type`；`formal.py:classify_missing` 已按此优先判 `infra`。v2 的 mini-swe 8 条曾因此被错分类（证据：[RETROSPECTIVE §5.6](RETROSPECTIVE-20261105.md)）。
- **补跑纪律**（LESSONS §2.6、§四）：
  1. 归档清单与 retry sample 必须**由同一份数据生成**（先列 job → 生成 sample → 归档），并核对数量，否则会出现「归档 28 个但 sample 只覆盖 8 题」。
  2. 补跑前后数字**同表并报**。v2 初始缺失 24 条（16 条环境/TLS/apt + 8 条 timeout），补跑后剩 **15 条**（SAYACODE 1 + mini-swe 14 + Codex 0）。补跑前后以**终版** [FORMAL-RESULTS-20261102-v2](FORMAL-RESULTS-20261102-v2.md) 为准：SAYACODE 67.5%→78.8%，mini-swe 47.5%→70.0%。（LESSONS §四 的「+21.3pp / +6pp」是定稿前的中间值，与终版 70.0% 略有差异，引用时以终版为准。）
  3. 补跑使任何 agent 数字变化 **>1pp 必须更新报告并说明来源**；补跑收益不能归因于产品修复。
  4. 补跑**不改变 planned 分母**，只改变终态覆盖；补跑次数与时间窗在 manifest 冻结。
- **环境失败会系统性惩罚某些 agent**：不能把补跑前数字当能力（LESSONS §0）。

## 7. 冻结与签收

### 7.1 冻结 manifest 必填

在 v1 [protocol.md](protocol.md)「规范化统计接口」字段基础上，新增：

- `planned_rows`：每 agent 的 planned trial 数（如 80），缺失按失败；
- `missing_policy`：§3 的分类规则与 `worst/best` 计算方式；
- `retry_policy`：§6 的可补/不补清单与补跑窗口；
- `statistics`：`n_level=task`、bootstrap 次数与 seed、McNemar 校正方式；
- `implementation`：分析脚本 SHA（含 `scripts/analyze_sensitivity.py` 等身份文件）。

### 7.2 签收流程

1. 开发批次完整收尾（全部 planned trial 有终态或已分类）；
2. `lock_candidate(...)` 保存不可覆盖签收单（原始 manifest、记录哈希、任务/修复组、wheel、依赖、候选配置、planned 分母快照、缺失分类快照）；
3. 冻结前 `validate_candidate_receipt(...)` 重读开发来源，核对最终 wheel/依赖/配置一致、任务 ID 与修复组不跨集重叠、阶段正确；
4. 签收后**不得**改分母、换题、改补跑规则；任何变更都是新的实验身份。

### 7.3 签收前检查清单

- [ ] 三口径（planned/observed/task_macro）齐全，主报 planned
- [ ] 每条缺失有分类 + 证据，无 `unverified` 遗留
- [ ] worst/best 两界都给出
- [ ] Wilson n = 题数；McNemar 用题级 pass
- [ ] 补跑清单与归档同源，补跑前后同表
- [ ] 实现身份（wheel / 分析脚本 SHA）冻结
- [ ] `task_count` 与多 agent 声明一致（见 §8）
- [ ] 报告字段符合 `docs/REPORT-TEMPLATE.md`

## 8. 必须遵守的 v2 坑（引用 LESSONS-20261102-v2.md）

1. **分母必须统一**：planned/observed/task_macro 同报，只报 observed 会高估（§四.1）。
2. **补跑效应巨大**：环境失败系统性惩罚某些 agent，补跑前数字不能当能力（§0、§四.2）。
3. **Wilson 用题级 n，McNemar 用题级 pass**，不用 trial 数或 best-of-2（§四.3）。
4. **聚类 bootstrap 仅敏感性**（§四.4）。
5. **补跑后变化 >1pp 必须更新报告**（§四.5）。
6. **`task_count=0` 不能评价多 agent 协作**：v2 的 240 trial `task_count` 全 0，本批是单点/单文件调试，协作能力须另用 `evals/scenarios/collaboration-autonomous.jsonl`（§3.5）。
7. **环境坑会伪装成模型能力**：Docker 崩溃、代理 gaierror、apt 502、astral.sh TLS、网络池耗尽都有明确处置（LESSONS §一、§二），跑批前按 checklist 预检。

## 9. 报告与协调

- 报告的**字段与版式**由 `docs/REPORT-TEMPLATE.md` 统一定义（另一队友维护）；本协议只规定口径，不重复模板内容。
- 每张成绩表至少包含：planned / observed / task_macro、缺失分类表、worst/best、Wilson CI、McNemar p 与校正、补跑前后对照。
- 对外发布前核对：模型身份、harness 版本、题集与 seed、实现哈希、缺失处理，全部可追溯。

## 10. 尚待冻结项

- 第二模型（见 [MULTI-MODEL-PLAN.md](MULTI-MODEL-PLAN.md)）的协议对齐项与样本量。
- 扩样到 100 题的具体清单与预算。
- gold-check 3 个 null 题的补齐或替换结果。
- 正式对外 stage（`holdout` / `validation`）的最终 manifest 与预算。
