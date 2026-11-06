# M3：产品自有评测体系（`evals/`）与 `docs/evaluation/` 审计（2026-11-07）

> 范围：`C:\develop\sayacode\evals\`（11 个 Python 模块、32 题、16 个 fixture 家族、5 个 profile、3 个场景清单）、`C:\develop\sayacode\docs\evaluation\`（19 个文件）、`C:\sb\hard\collab-*` 产物；对照 `C:\develop\sayacode-bench\docs\RESULTS-LEDGER.md`（bench 权威口径）。
> 方式：全量读 `README.md` / `run.py` / `worker.py` / `graders.py` / `report.py` / `diagnose.py` / `catalog.py` / `docker_backend.py`，抽样读 `cases/`、`scenarios/`、`profiles/`；逐份读 19 份 docs 的头部与结论段；实读 6 个 collaboration 产物的 `worker-result.json` 与 `input.json`；`git log` 核对提交时序。**只读，未改任何代码与文档**；本文件是唯一新增产物。
> 结论先行：**两套评测不是"重复建设"，而是"一套已死、一套在跑"**。产品 `evals/` 的 32 题在 2026-10-28 饱和后已实质退役（`docs/evaluation/README.md:23` 自认「已弃用」），但 **`evals/README.md` 至今仍把它当有效任务集**，两份 README 结论方向相反。真正仍有独占价值的是 `scenarios/` 三个场景清单与 `docs/evaluation/2026-10-29-evaluation-methodology.md` 的方法论，其余应退役或归档。

---

## 1. 两套评测的关系图

### 1.1 各自测什么

| 维度 | 产品 `evals/` | bench 仓 |
|---|---|---|
| **定位** | 产品自带的「Agent 效果评估」工具与初始任务集 | 独立评测仓，对外数字的唯一来源 |
| **题集** | **自造 32 题**：8 dev + 24 holdout（20 自动编程 + 4 人工审查），**16 个 fixture 家族**（`evals/cases/catalog.md:18`） | **SWE-bench Pro V2** 真实仓库：`sample-40-final.json` 40 题（主报）、holdout 24 题（早期） |
| **题目规模** | 单文件到 3–6 文件，纯 Python 标准库，`> 0` 行级缺陷 | 真实 upstream 仓库 issue，中位 2 文件 / 64 行改动 |
| **grader** | `evals/graders.py`：`python` / `command` / `file_contains` / `response_contains` / `response_excludes` + `protected_paths` 指纹 | **官方 Harbor 0.24.0 verifier**，`reward` 0/1 + `output.json` 逐测试 PASSED/FAILED |
| **执行入口** | 容器内 `python /opt/evals/worker.py`，**直接 import `SayacodeApp`**（`worker.py:162-173`） | 容器内装 wheel，**官方 `SayacodeAgent` 适配器** |
| **隔离** | `docker run --read-only --cap-drop ALL --no-new-privileges`，仅挂 `/workspace` + `/state` | Harbor `IsolatedDockerEnvironment`，agent 网络 `no-network` |
| **口径** | `task_success_rate` / `judged_success_rate` / `pass^R` 稳定率；**无 partial** | `planned`（主报）/ `observed` / `partial` / `task_macro`（`RESULTS-LEDGER.md` §1） |
| **产物** | `<output>/trials/<case>--<variant>--<repeat>/` + `manifest.json` + `source.zip` + `report.md` + `summary.json` | Harbor job 目录 + `FINAL-SUMMARY*.json` + `STRICT-COMPARE*.json` |
| **规模** | 2 组 × 24 题 × 3 重复 = **144 trial**（已跑） | 5 组 × 40 题 × 2 重复 = **391 trial**（已跑） |
| **维护状态** | **2026-10-28 后无新批次**；3.2.5/3.2.6/3.2.7 全部只用 bench 验证 | 持续（v2→v3→v4→3.2.7 批次） |

### 1.2 重叠与互补

**重叠（真正的重复建设）**：

| 能力 | 产品 `evals/` | bench | 重复度 |
|---|---|---|---|
| Docker 容器生命周期 | `run.py:170-212` + `docker_backend.py` | Harbor | **高**（各有实现，各踩过坑） |
| 判分执行 | `graders.py:31-82` | 官方 verifier | **中**（机制不同，无法复用） |
| 报告汇总 | `report.py`（527 行） | `analysis.py` + `strict_compare.py` + `final_summary.py` | **高**（指标集合重叠） |
| 冻结与身份 | `cases/freeze.json` + `catalog.source_digest()` | `study.py` freeze + manifest | **高** |
| 单题预算/超时 | `case["timeout_seconds"]` | Harbor timeout | 中 |

**互补（产品侧独有的、bench 没有的）**：

| 资产 | 为什么 bench 不能替代 |
|---|---|
| `scenarios/collaboration.jsonl` + `collaboration-autonomous.jsonl` | bench 的 SWE-bench 题**不触发协作**（`task_count=0`），无法评价多 Agent；这是唯一能稳定触发 `task_count=2` 的资产 |
| `scenarios/context.jsonl` | 唯一能在**受控长上下文**下强制触发摘要的场景（但见 §4.3，实际未跑成） |
| `worker.py` 的 `summary_count` / `context_history` / `recover_context()` | bench 的适配器不返回摘要计数与逐轮上下文历史（DEEP-ANALYSIS 只能事后手工算） |
| `diagnose.py` 的 `protected_file_constraint` 分类 | 依赖 `protected_paths` 概念，bench 用 verifier 重置测试面，无对应物 |
| `docs/evaluation/2026-10-29-evaluation-methodology.md` | 过程护栏（改测试次数、空转率、首次编辑前探索步数）的方法论来源，bench 的 `RESULTS-LEDGER` 只采了 partial，未采过程指标 |

### 1.3 一句话关系

**产品 `evals/` 是 bench 的前身与能力切片实验室，不是它的竞争者。** 时间线：`2026-10-21` 产品自建评测跑 144 trial → `2026-10-28` 自造集饱和 100%，转用 SWE-bench Pro → `2026-10-31` 之后全部结论改由 bench 产出 → 产品 `evals/` 只剩 `scenarios/` 还在被引用（`docs/evaluation/2026-10-28-multi-agent-diagnosis.md`、bench `TASKCOUNT-ATTRIBUTION.md:168`）。

---

## 2. Grader 一致性：同一概念两套定义（共 6 处）

| 概念 | 产品 `evals/` 定义 | bench 定义 | 是否冲突 | 严重度 |
|---|---|---|---|---|
| **pass（单 trial）** | `automatic_passed = bool(checks) and all(check["passed"])` 且 `status == "completed"`；人工题为 `None`（`run.py:356-359`） | `reward == 1.0`（官方 verifier）；人工题不存在 | **不冲突**（都是全检查通过），但产品多了「人工题 → None」这一档 | 低 |
| **partial** | **不存在**。`report.py` 只有 `task_success_rate` / `judged_success_rate`（`report.py:42-55`），无逐测试通过比例 | `partial` = `verifier/output.json` 中 required 测试通过比例（`RESULTS-LEDGER.md` §1） | **概念缺失** | **高**：产品侧永远看不到「99% 对但 0 分」 |
| **超时** | `TimeoutExpired` → `status="timeout"` → 停容器 → **判为失败**（`run.py:285-288`，`report.py:35`） | Harbor timeout，按 `infra`/`timeout` 分类，planned 口径下计失败但**单独分类报告** | **口径不同**：产品把超时并入失败率，不单列 | 中 |
| **基础设施错误** | `status="infrastructure_error"` → 判失败 | `infra` 类，可在补跑时合规恢复 | **不同**：产品无「可补跑」概念 | 中 |
| **缺失分类** | `failure_category` 只有 `acceptance_failure` / `timeout` / `infrastructure_error` / `failed`（`run.py:377-379`） | 7 类：`no_job` / `infra` / `timeout` / `empty_patch` / `unverified` / `model_fault` / `unattributed` | **类目数 4 vs 7，不是同一套** | **高** |
| **改测试判定** | `protected_paths` 逐个 sha256 比对（`graders.py:73-81`） | verifier 在判分前对 `tests/` 执行 `git checkout HEAD`（重置测试面） | **机制不同，结论口径不同**：产品是「字节不变才算过」，bench 是「改了也会被还原」 | 中 |

### 2.1 产品侧另有一套更细的失败分类（仅在 `diagnose.py`）

`diagnose.py:13-48` 定义了 **11 类**：`timeout` / `infrastructure_error` / `model_rate_limit` / `model_connection` / `model_failure` / `runtime_failure_unclassified` / `human_review_pending` / `accepted` / `acceptance_failure` / `protected_file_constraint`。

**关键**：这套分类**只用于诊断输出**，不写回 `result.json` 的 `failure_category`，也不进入报告主表。所以产品 `evals/` 里同时存在**两套失败分类**：`run.py` 的 4 类（进报告）与 `diagnose.py` 的 11 类（不报告）。bench 是第 3 套（7 类）。

→ **同一概念（失败归因）在三处有三种定义**，且互不引用。

### 2.2 一个具体的判定差异（`protected_paths` 与 bench 的 `PASS_TO_PASS`）

产品题把 `README.md`、`tests/test_public.py` 列为受保护路径，要求**逐字节不变**（`graders.py:79`：`current.get(name) == initial[name]`）。

bench 的官方 verifier 的做法是**判分前重置整个测试面**（`RESULTS-LEDGER.md` 的 `strict` 口径废除说明：`tests/test.sh:97-105` 对 `*__snapshots__/*` 执行 `git checkout HEAD`）。

→ 两边都防「改测试作弊」，但产品是**拒绝**（改了就判失败），bench 是**还原**（改了当没改）。这导致同一模型行为在两侧的得分方向可能相反：产品侧会扣分，bench 侧不受影响。

---

## 3. `docs/evaluation/` 19 份逐份审计

### 3.1 总表

「被 bench 索引」列：bench 任何文档是否引用该文件。全部为**否**（除 `README.md` 被 R4/R5 复盘间接提及）。

| # | 文件 | 日期 | 内容 | 是否仍有效 | 与 bench 结论冲突 |
|---|---|---|---|---|---|
| 1 | `README.md`（113 行） | 10-29 | 主台账：评测体系、**当前权威基线 v3.2.4 = 14/20 = 70.0%**、17 条结论台账 | **部分** | **是（见 3.2 C1/C2）** |
| 2 | `WORKFLOW.md`（87 行） | 10-29 | PDCA 闭环、L1/L2/L3 金字塔、Go/No-Go 判定表 | **是（方法论）** | 无冲突，但 L2/L3 工具链指向 `C:\sb\pipelines\*`（未建） |
| 3 | `2026-10-21.md`（139 行） | 10-21 | 首轮 144 trial：single 65.0% / team 63.3%、53 次连接失败、摘要在配额中断 | **是（历史事实）** | **与台账冲突（见 3.2 C3）** |
| 4 | `results-2026-10-21.json`（202 行） | 10-21 | 上述批次的脱敏汇总：72+72 trial、`subtasks.created=0`、`pass^3` 仅 23.8%/28.6% | **是（唯一机器可读产物）** | 无 |
| 5 | `2026-10-28-iteration-01.md`（54 行） | 10-28 | dev 8/8、holdout 20/20 = 100%（**饱和的原始出处**） | **是** | 无（但见 3.2 C3） |
| 6 | `2026-10-28-authoritative-iteration-01.md`（67 行） | 10-28 | 转用官方 SWE-bench Pro；qutebrowser 单次 0→1 | **部分** | **qutebrowser 结论已自我推翻（`README.md:72`）** |
| 7 | `2026-10-28-dev-full-status.md`（45 行） | 10-28 | dev 8 题逐题状态 | 是 | 无（题集与 bench sample-40 不同） |
| 8 | `2026-10-28-ab-condensed.md`（34 行） | 10-28 | 提示词精简 A/B **失败**（token 13.7M→25.5M） | **是（证伪结论仍成立）** | 无 |
| 9 | `2026-10-28-release-baseline-ab.md`（36 行） | 10-28 | 3.2.4 vs 候选配对 | 部分 | 结论「候选 token +27.6%」已被后续 3.2.5 取代 |
| 10 | `2026-10-28-multi-agent-diagnosis.md`（42 行） | 10-28 | 22 次 0 派发；显式场景 task_count=2 | **是（唯一多 Agent 证据）** | **不冲突，且被 bench `TASKCOUNT-ATTRIBUTION` 引用** |
| 11 | `2026-10-29-holdout-baseline.md`（49 行） | 10-29 | **SWE-bench Pro holdout 24 题**，3.2.4 = 20 可评测 / 14 通过 | **是** | **是（题集名与 bench 撞车，见 3.2 C2）** |
| 12 | `2026-10-29-iteration-report.md`（61 行） | 10-29 | 5 个 FAIL 归因（全与改既有测试相关）+ 3/5 翻盘 + token 控制 -82% | 部分 | **navidrome「翻盘」已被 `README.md:93` 推翻** |
| 13 | `2026-10-29-token-tuning-and-repeats.md`（37 行） | 10-29 | keep=3→8 参数矩阵，**无一组参数同时保住三题** | **是** | 无（bench 未做过该矩阵） |
| 14 | `2026-10-29-final-full-report.md`（59 行） | 10-29 | token 调参、机制保护、TLS 补齐 | 部分 | 部分结论被 3.2.5+ 取代 |
| 15 | `2026-10-29-evaluation-methodology.md`（82 行） | 10-29 | **partial credit + pass^k + 过程指标 + McNemar** 方法论，含 Goodhart 自省 | **是（最有价值的一份）** | 无（bench 只落地了 partial，未落地过程指标） |
| 16 | `2026-10-29-task-count-power.md`（51 行） | 10-29 | 统计功效：检测 10/15/20pp 需 330/147/83 题 | **是** | 无（bench `MULTI-MODEL-PLAN` 引用同口径） |
| 17 | `2026-10-29-scaled-evaluation-assessment.md`（62 行） | 10-29 | 规模化：HARD-51、云 VM 可行 | 部分 | bench `SCALE-WITHOUT-UPGRADE` 有冲突（100 题可行 vs 不可行） |
| 18 | `2026-10-29-cloud-eval-cost-plan.md`（57 行） | 10-29 | ¥50 成本方案 | 是（估算） | 无 |
| 19 | `2026-10-29-c-stage-musl-assessment.md`（46 行） | 10-29 | musl 4/24 不可评测，**不实施** | **是** | **与 bench 一致**（RETROSPECTIVE 同样结论） |

### 3.2 与 bench 结论的具体冲突（4 条）

**C1（最严重）：两套「SAYACODE 成绩」并存且互不解释**

| 来源 | 制品 | 题集 | 数字 |
|---|---|---:|---|
| `docs/evaluation/README.md:50-58` | **v3.2.4**（`2afe5889`） | SWE-bench Pro **holdout 24 题**（20 可评测） | **14/20 = 70.0%** |
| bench `RESULTS-LEDGER.md` §2.1 | **3.2.5** 本地 wheel | **sample-40**（40 题 ×2） | **78.8%** (63/80) |
| bench `RESULTS-LEDGER.md` §2.2 | **3.2.7** PyPI | sample-40 | **76.2%** (61/80) |

三行都是「SAYACODE 在 SWE-bench Pro 上的 pass@1」，但**题集不同、制品不同、分母不同**，且**没有任何一份文档解释三者关系**。`docs/evaluation/README.md` 自称「当前权威基线」，bench `RESULTS-LEDGER.md` 自称「唯一权威来源」——**两个"权威"互相不知道对方存在**。

**C2：「holdout」一词在三处指三种东西**

| 用法 | 指代 |
|---|---|
| 产品 `evals/` 的 holdout | **自造 24 题**（20 自动 + 4 人工，`cases/holdout.jsonl`） |
| 产品 `docs/evaluation/` 的 holdout | **SWE-bench Pro 的 holdout split 24 题**（11 仓库） |
| bench 的 holdout | **`sample-40-final.json`**（从 SWE-bench Pro **dev** split 选的 40 题） |

第三个最反直觉：bench 自称的「40 题正式集」在 SWE-bench Pro 里其实是 **dev** 划分，而 `docs/evaluation/` 用的是真正的 **holdout** 划分。两者题目**不重叠**，但读者会以为「holdout 24 → 40」是扩容，实际是**换了一个划分**。

**C3：台账的引用与日期错位（证据链断裂）**

`docs/evaluation/README.md:70` 记：

```
| 10-21 | 自造 32 题评测集 | evals 32 | 1 | dev 8/8、holdout 20/20 饱和 | 强 | 2026-10-21.md |
```

实测：

- `2026-10-21.md` **全文不含**「8/8」「20/20」「饱和」；
- 该文记的是 **single 39/60 = 65.0%、team 38/60 = 63.3%**，且明确「43 次因连接类失败未完成」；
- `8/8、20/20` 的真实出处是 **`2026-10-28-iteration-01.md:23-24`** 与 **`2026-10-28-authoritative-iteration-01.md:14`**（相差 7 天）。

→ **日期错、引用错、且掩盖了「65% → 100% 的原因是从连接故障中恢复，不是能力提升」这一关键解释**。这条台账行不能作为「自造集饱和」的证据，尽管结论本身在 10-28 的文档里成立。

**C4：「自造集是否饱和」的两份 README 结论相反**

| 文档 | 措辞 | 含义 |
|---|---|---|
| `evals/README.md:5` | 「当前样本与服务波动**不足以支持**机制收益结论」 | **样本不足** → 应继续跑 |
| `docs/evaluation/README.md:23` | 「自造集**已弃用**：`evals/` 下 32 题**已饱和**」 | **样本过剩** → 不要再用 |

同一数据集、同一仓、两份现行 README，一份说不足一份说过剩。且 `evals/README.md` 至今仍在 §「运行前准备」给出完整的 32 题跑批命令（`:78-95`），没有任何「已退役」提示。

---

## 4. 产品评测的可信度

### 4.1 是否真跑过：跑过，但产物已缺失

| 批次 | 证据 | 产物状态 |
|---|---|---|
| 自造 32 题主批次（144 trial） | `docs/evaluation/2026-10-21.md` + `results-2026-10-21.json`（含 72+72 trial 的完整 `groups`、`diagnostic_counts`、`usage`） | **原始目录不存在**：`C:\develop\sayacode-evaluations`、`C:\sb\eval-results` 均无；`results-2026-10-21.json` 是脱敏汇总 |
| 自造 32 题饱和批（10-28，8/8 + 20/20） | `2026-10-28-iteration-01.md:23-24` | **无产物路径、无 manifest**，只有一行表 |
| collaboration（6 trial） | `C:\sb\hard\collab-{check,verify}-*` **存在**，已实读 | ✅ 完整（`worker-result.json` + `events.jsonl` + `audit.jsonl` + `checkpoints.sqlite3`） |
| context 摘要专题（12 trial） | `scenarios/README.md:73` 自认「遭遇接口五小时配额耗尽，未形成有效摘要收益比较」 | **无有效产物** |
| summary-pressure-4096 | `2026-10-21.md:107` 记「600 秒未完成、15 个摘要版本、139 检查点」 | 产物未在本机找到 |

→ **可信度分层**：只有 collaboration 6 trial 是「产物可核」的；144 trial 主批次只剩汇总；10-28 饱和批与摘要专题**不可复核**。

### 4.2 硬编码与跳过逻辑

| 检查项 | 结论 |
|---|---|
| 硬编码期望通过率 | **无**。`report.py` 全部由 `trials/*/result.json` 计算；`_verdict` 只读 `passed` 与 `status` |
| 跳过逻辑 | **有，但正当**：`fixture_only=True` 时 `status="completed"` 且不判分（`run.py:265-266`），仅用于 `check-fixtures` 自检；`case.get("human_review")` 为真时 `passed=None` 待人工（`run.py:359`） |
| 冻结校验 | **有且严格**：`catalog.py:21-25` 对 `freeze.json` 里 60 个文件的 sha256 逐一校验，任一不符即抛错 |
| **`hard/hard-v1.jsonl` 不在冻结内** | ⚠️ `freeze.json` 的 `sha256` 只列 `cases/dev.jsonl`、`cases/holdout.jsonl` 与 16 个 fixture 的文件；**`cases/hard/hard-v1.jsonl`（6 题）既不在 `sha256`、也不在 `task_counts`**。它只能通过 `--catalog` 显式指定，默认 `load_cases`（`catalog.py:26` glob `cases/*.jsonl`）**读不到它**。→ 6 道 hard 题**从未进入任何冻结身份**，可被随意修改而不报错 |
| 自评 | **无**。`report.py` 明确「正常结束不能代替任务验收」（`:34`），`run.py:356` 用 check 结果而非模型自述 |

### 4.3 `profiles/` 是否仍成立：语法成立，语义部分失效

当前 `Profile` 默认值（`config.py:68-76`）：`summary_trigger_ratio=0.8`、`summary_trigger_tokens=None`、`summary_keep_messages=12`、`context_edit_trigger=None`、`context_edit_keep=3`、`completion_guard=False`。

| profile | trigger 配置 | 按当前 `summary_trigger_for` 的**实际阈值** | 是否仍有效 |
|---|---|---:|---|
| `commandcode.json` / `magpie-deepseek.json` | ratio=0.8, tokens=null | `min(57344−3277, 65536×0.8) = min(54067, 52428) = **52,428**` | ✅ 有效（但注释/文档常写成 52.4k，实际由 min 决定） |
| `summary-on.json` | ratio=null, tokens=**16384**, keep=2 | `min(54067, 16384) = **16,384**` | ✅ 有效，能强制摘要 |
| `summary-off.json` | ratio=null, tokens=null | `summary_trigger_for` 返回 **None** → 不装配摘要中间件 | ✅ 有效（但 `keep=2` 此时无意义） |
| `summary-pressure-4096.json` | tokens=**4096** | `4,096` | ✅ 语法有效；**实测已失败**（600s 未完成） |

**四个语义问题**：

1. **全部 5 个 profile 都缺 `context_edit_keep` 与 `completion_guard` 字段**。`Profile.from_dict`（`config.py:148-166`）只校验「未知字段拒绝 + 7 个必填」，缺失的可选字段静默取默认值——所以**不会报错**，但意味着这些 profile 从 3.2.5/3.2.7 起就**无法表达**这两个新参数。想测 `context_edit_keep` 或 `completion_guard` 必须手工改 profile。
2. **`max_output_tokens=8192` 已被实测证伪**：`SUMMARY-FALLBACK-CHECK.md` §4.3 记「两个 evals profile 都因 `max_output_tokens=8192` 对 reasoning 模型过小而失败——`summary-off` 尤其明显：reasoning 吃光预算 → 续写 3 次 → `final.response=""`]。**当前仍是 8192**。
3. **`context_length=65536` 是「统一实验预算」而非测得窗口**（`evals/README.md:62` 已声明）；64K 下摘要阈值 52.4k，距 8192 输出预算只剩 44k 可用——**极易触发摘要，与 bench 的 192k 场景完全不同**。这是两套评测不可比的根本原因之一。
4. **端点存活未验证**：`commandcode.json` → `host.docker.internal:8787`（`SUMMARY-FALLBACK-CHECK.md:128` 记该端点曾 404）；`magpie-deepseek.json` → `:3425`（collaboration 6 trial 用的就是它，当时可用）。

### 4.4 `docker_backend.py`：一次真实的跨环境缺陷修复

`LESSONS-20261102-v2.md:1.9` 记录：DSH 沙箱内 `evals/run.py:149` 用 `subprocess.run(["docker",...])` 调 CLI 被 named pipe 权限拦死（`permission denied ... npipe:////./pipe/dockerDesktopLinuxEngine`），而 bench 的 Harbor 走 Docker SDK 不受影响。

→ 已由 `ff5822c`（`feat(evals): Docker SDK 后端（+CLI 回退）`）修复：`docker_backend.py` 237 行，`run.py:144-159` 惰性创建后端、`:269-292` 全部改用 `backend.exec/stop/remove`。**这是产品 `evals/` 近年来唯一有明确缺陷记录与修复的工程改动**，且修复后有 `tests/evals/test_docker_backend.py`。

---

## 5. `scenarios/collaboration*.jsonl`：唯一的多 Agent 资产

### 5.1 现状

| 文件 | 题数 | `category` | fixture | 关键判分字段 | 题面要求 |
|---|---:|---|---|---|---|
| `collaboration.jsonl` | 1 | `collaboration_diagnostic` | `holdout-parcels` | `min_child_tasks=2`、`required_child_roles=[planner,reviewer]`、`max_failed_child_tasks=0`、`timeout=600` | **显式命令**「先派发两个不同的只读子 Agent」 |
| `collaboration-autonomous.jsonl` | 1 | `collaboration_autonomous_diagnostic` | 同上 | **无** `min_child_tasks`、**无** `required_child_roles`；仅 `max_failed_child_tasks=0` | 「如何组织工作由你决定」 |
| `context.jsonl` | 2 | `context_summary` | `dev-notes` / `dev-metrics` | 5 轮固定输入，`read_only_until_turn=4` | 先给契约 → 3 段合成日志 → 要求实施 |

`collaboration.md` 自我定位（`:5`）：「**这是用户明确要求协作时的功能诊断，不是比较 Agent 是否自主派发的无偏 benchmark**」。

### 5.2 上次跑是什么时候、结论是什么（实读产物）

本机存在 **4 个产物目录、6 个 trial**：

| 目录 | 场景 × 变体 | `task_count` | `child_roles` | `failed_child` | 耗时 | `summary_count` | model_calls |
|---|---|---:|---|---:|---:|---:|---:|
| `collab-check-explicit` | combined × **single** | **0** | [] | 0 | 91.2s | 0 | 20 |
| `collab-check-explicit` | combined × **team** | **2** | `[reviewer, planner]` | 0 | 126.7s | 0 | 24 |
| `collab-check-manual` | autonomous × single | **0** | [] | 0 | 62.9s | 0 | 8 |
| `collab-check-manual` | autonomous × **team** | **0** | [] | 0 | 34.1s | 0 | 7 |
| `collab-verify-explicit` | combined × **team** | **2** | `[reviewer, planner]` | 0 | 116.3s | 0 | 26 |
| `collab-verify-single` | autonomous × single | **0** | [] | 0 | 41.4s | 0 | 11 |

`input.json` 核实：`single → team_enabled=false`、`team → team_enabled=true`（6/6 一致），profile 均为 64K / 8192 输出 / ratio=0.8。

**结论（4 条，全部有产物支撑）**：

1. **显式要求 + 团队工具可用 → `task_count=2`，且稳定复现 2 次**（126.7s / 116.3s，`child_roles` 均为 `[reviewer, planner]`，0 失败）。
2. **显式要求 + 团队工具关闭 → `task_count=0`**（结构性，因为 `single` 不注册团队工具；`min_child_tasks=2` 必然失败）。
3. **不要求 + 团队工具可用 → `task_count=0`**（`autonomous × team = 0`，与 `autonomous × single = 0` 相同）。
4. **6 次 trial 的 `summary_count` 全为 0**——这些场景输入量远未达 64K×0.8 = 52.4k 阈值，**不能用于验证摘要**。

### 5.3 「bench 说 0，产品说 2」是否兼容：**完全兼容，且已被 bench 明确桥接**

| 结论 | 出处 | 评价对象 | 条件 |
|---|---|---|---|
| `task_count=0` | bench | **SWE-bench Pro 40 题**（真实 upstream issue） | 题面**不要求**派发；团队工具可用 |
| `task_count=0` | 产品 `collaboration-autonomous.jsonl` | 1 道合成题 | 题面**不要求**派发；团队工具可用（team 组） |
| `task_count=2` | 产品 `collaboration.jsonl` | 1 道合成题 | 题面**显式命令**派发 planner + reviewer |

三者是**同一条因果链的三个点**，不是矛盾：

- bench 的结论有明确边界——`TASKCOUNT-ATTRIBUTION.md:21` 原文：「产品侧 team 工具链是好的（可见、可调、能跑通）；`task_count=0` 是因为**评测题没有给模型"值得派发"的理由**」；
- 且 bench 的 `TASKCOUNT-ATTRIBUTION.md:168` **直接引用了** `evals/scenarios/collaboration.jsonl` 作为验证资产，并记录了验证 A（team，2）与验证 B（single，0）的产物路径；
- 产品 `2026-10-28-multi-agent-diagnosis.md` 的三段式结论（显式→2；自主→0；加规则后仍 0）与上表逐项吻合。

**唯一需要澄清的措辞**：bench 说「这批题不触发协作」中的「这批题」**只能**指 SWE-bench Pro 40 题，**不能**推广成「协作机制不可用」或「多 Agent 无收益」；反之产品侧「显式分工能 2」也**不能**推广成「真实任务上会自动派发」。两侧文档目前都守住了这个边界（bench `RETROSPECTIVE` §2.2 红线第 3 条明确禁止「用 `task_count=0` 说多 agent 协作没用」）。

**遗留风险**：`collaboration.jsonl` 的 `min_child_tasks=2` 检查若被误用在 `single` 变体上，会得到**结构性必败**结果（`combined × single` 实测 `task_count=0`）。`README` 与 `collaboration.md` 均未警告这一点——只有 `evals/README.md:13` 说「`single` 不注册团队工具」，间接提示但未直接禁止。

---

## 6. 建议：保留、合并、还是退役

### 6.1 分层处置（不是一刀切）

| 资产 | 处置 | 理由 | 成本 |
|---|---|---|---|
| **`cases/` + `fixtures/`（32 题）** | **退役**（保留文件，标注「已饱和，仅历史」） | 10-28 已 100% 饱和；3.2.5 之后产品改动全由 bench 验证；无产物可复核 | 低（改 README 一句） |
| **`profiles/`（5 个）** | **保留但标注失效边界** | 除 collaboration 外无使用；`max_output_tokens=8192` 已证伪；缺 2 个新字段 | 低（加注释 + 补字段） |
| **`scenarios/collaboration*.jsonl`** | **合并进 bench**（作为独立的「协作能力切片」catalog，不进 sample-40） | 唯一能稳定触发 `task_count=2` 的资产；bench 已引用它但未纳入自己的跑批体系；放进 bench 才能与 5 组基线共用统计与报告 | 中（bench 需支持非 SWE-bench 题型的 grader，或写成 variant 专用脚本） |
| **`scenarios/context.jsonl`** | **合并进 bench**（优先度高于 collaboration） | **这是唯一能控制摘要触发与否的资产**，而 DEEP-ANALYSIS §10 证明 bench 现有题集**永远测不到摘要路径**（峰值最大 102k < 150.4k 触发线）。要验证 `c5d2973` 摘要降级，必须用它或等价物 | 中 |
| **`graders.py` / `run.py` / `report.py` / `docker_backend.py`** | **退役** | 与 Harbor 重复；判分模型（protected_paths 拒绝式）与官方（重置式）不同源；`report.py` 527 行无 partial、无缺失分类 | 低（不进 bench） |
| **`worker.py`** | **保留为参考实现**，把 3 个独有能力搬进 bench 适配器 | `summary_count`、`context_history`（逐轮 messages/token/workspace_changed）、`recover_context()`（直读 checkpoints 数摘要版本）——bench 适配器都没有，DEEP-ANALYSIS §10 是事后手工算的 | 中（改 bench 适配器 +30 行） |
| **`diagnose.py`** | **合并**（保留 `protected_file_constraint` 与 `model_connection` 细分） | bench 的 7 类缺「受保护文件被改」与「连接类」细分，而后者在 2026-10-21 占 53/144（37%） | 低 |
| **`docs/evaluation/` 19 份** | **归档 + 在 bench 建一条指针**（不是复制内容） | 唯一仍有价值的是 `2026-10-29-evaluation-methodology.md`（过程指标 + Goodhart 自省）与 `2026-10-21.md`/`results-*.json`（144 trial 的原始计数）；其余数字已被 bench 取代 | 低（bench `docs/archive/README.md` 加 3 行） |

### 6.2 必须立刻修的三处口径冲突（零成本）

| # | 动作 | 位置 |
|---|---|---|
| 1 | `evals/README.md` 顶部加一句：「本目录 32 题已于 2026-10-28 饱和并停止用于能力测量，仅 `scenarios/` 仍在使用」 | `evals/README.md:1-5` |
| 2 | 修正台账行的日期与引用：`10-21` → `10-28`；`2026-10-21.md` → `2026-10-28-iteration-01.md`；并补注「65% → 100% 的原因是从连接故障恢复」 | `docs/evaluation/README.md:70` |
| 3 | 在 `docs/evaluation/README.md` §2「当前权威基线」顶部加指向：「本表的 v3.2.4 / holdout-24 数字已被 bench `RESULTS-LEDGER.md` 的 3.2.5/3.2.7 取代，两者题集不同（holdout-24 vs sample-40），不可比」 | `docs/evaluation/README.md:50` |

### 6.3 反向建议（不做的）

- **不建议**把产品 `evals/` 整体迁进 bench。两边判分模型（受保护文件拒绝 vs 测试面重置）不同源，强行合并会产生第三套口径。只搬 **3 个场景清单 + 3 个观测能力**。
- **不建议**为产品 `evals/` 补 partial credit。它的题是「28 道编程题 = 每题 1 个 `python` 断言 + 1 个 `command` + 2 个 `protected_file`」的粗粒度检查，**没有逐测试粒度**，加 partial 也只能到「4 项检查里过几项」，信息量不如 bench 的 `output.json`。
- **不建议**再跑 32 题。若需 L1 快速回归，用 bench 的 `regression-set.json`（5–10 题真实题）比自造 32 题更有代表性。

---

## 7. 对第一轮复盘 R5 的核对

R5 称「`docs/evaluation/` 19 份是跨仓孤儿，未被 bench 任何文档索引」。**核实结果：基本成立，但需修正两处**。

| R5 说法 | 核实 |
|---|---|
| 19 份未被我 benc 索引 | ✅ 成立（bench 全文只有 `R4`/`R5` 自己提到 `docs/evaluation/README.md`；`TASKCOUNT-ATTRIBUTION` 引的是 `evals/scenarios/` 而非 `docs/evaluation/`） |
| 「跨仓孤儿」 | ✅ 成立，且**比 R5 说的更严重**：这 19 份文档**依赖 bench 的代码**（`docs/evaluation/README.md:27`：「Harness：Harbor 0.24.0；入口 `sayacode_bench.execution.run_official_trial`」），即**产品仓文档反向依赖 bench 模块**。bench 若改 `execution.py` 签名，这 19 份的实验无法复现，且不会有任何测试报警 |
| 建议「在 bench `docs/archive/README.md` 加指针」 | ✅ 可采纳，但应加**3 条**而非 1 条（见 §6.1） |

---

## 8. 结论（一页）

1. **两套评测不是重复建设，而是接力关系**：产品 `evals/` 是 2026-10-21～10-28 的探索期工具，32 题在 10-28 饱和后退役；bench 是 10-28 之后的正式评测仓。重叠的是 Docker/判分/报告基建（应退役产品侧），互补的是**场景切片**（应迁入 bench）。
2. **grader 一致性：pass 判定兼容，但 partial、超时、缺失分类、改测试判定四处不同源**；产品 `evals/` 内部还有两套失败分类（`run.py` 4 类进报告 / `diagnose.py` 11 类仅诊断），bench 是第三套（7 类）。
3. **19 份 docs 中 4 份仍有效且不可替代**（`2026-10-29-evaluation-methodology.md`、`2026-10-21.md` + `results-*.json`、`2026-10-29-c-stage-musl-assessment.md`、`WORKFLOW.md`），其余数字已被 bench 取代。**存在 4 处与 bench 的实质冲突**，其中 C1（两套 SAYACODE 成绩）与 C3（台账引用错位）必须修。
4. **产品评测的可信度分层明显**：只有 collaboration 的 6 个 trial 产物可核；144 trial 主批次只剩脱敏汇总；10-28 饱和批与摘要专题**不可复核**。无硬编码作弊，但 `hard-v1.jsonl` 6 题**不在冻结身份内**。
5. **`profiles/` 语法有效、语义部分失效**：4 个 summary 配置的触发阈值仍算得对（16,384 / 4,096 / 关闭 / 52,428），但 `max_output_tokens=8192` 已被实测证伪，且全部缺 `context_edit_keep` 与 `completion_guard` 两个新字段。
6. **collaboration 的两侧结论完全兼容**：bench 的 `task_count=0`（真实题、不要求派发）与产品的 `task_count=2`（合成题、显式命令派发）是同一条因果链的两端，且 bench `TASKCOUNT-ATTRIBUTION` 已引用该资产并做了桥接。**唯一风险**是 `min_child_tasks=2` 用在 `single` 变体会结构性必败。
7. **明确建议：退役 32 题与基建、把 3 个场景清单迁进 bench、19 份文档归档并在 bench 建指针。** 三处零成本口径修正应立刻做。

---

## 9. 引用索引

### 产品仓 `evals/`

| 内容 | 位置 |
|---|---|
| 定位与任务集 | `evals/README.md:1-27`（`:17` 32 题、`:5` 「样本不足」措辞） |
| 跑批命令 | `evals/README.md:70-98` |
| 冻结校验 | `evals/catalog.py:19-61`（`:21-25` sha256 校验、`:26` 只 glob `cases/*.jsonl`） |
| 源码身份 | `evals/catalog.py:64-74` |
| 试验执行 | `evals/run.py:215-408`（`:294-336` 判分、`:356-359` pass 判定、`:377-379` 失败分类） |
| 容器 | `evals/run.py:170-212`；`evals/docker_backend.py` |
| 判分 | `evals/graders.py:31-82`（`:73-81` protected_paths） |
| 报告口径 | `evals/report.py:33-55`（`_verdict`、`_outcomes`）、`:58-71`（摘要指标） |
| 诊断分类 | `evals/diagnose.py:13-48`（11 类） |
| worker 调用产品 | `evals/worker.py:148-276`（`:162-173` `SayacodeApp`、`:200-213` summary_count、`:222-255` task_count） |
| 冻结清单 | `evals/cases/freeze.json`（`dataset_version 0.2`、60 个 sha256、**不含 hard-v1**） |
| 任务集说明 | `evals/cases/catalog.md:18`（8+24 题、13 家族）、`:56-79`（20 自动 + 4 人工） |
| 协作场景 | `evals/scenarios/collaboration.jsonl`、`collaboration-autonomous.jsonl`、`collaboration.md`（`:5` 定位、`:26-38` 观察与结论边界） |
| 摘要专题 | `evals/scenarios/context.jsonl`、`scenarios/README.md`（`:57-77` 配对约定、`:71` 4096 失败、`:73` 配额耗尽） |
| profiles | `evals/profiles/*.json`（5 个，全部缺 `context_edit_keep`/`completion_guard`） |

### 产品仓 `docs/evaluation/`

| 内容 | 位置 |
|---|---|
| 主台账 | `docs/evaluation/README.md`（`:23` 自造集已弃用、`:50-58` v3.2.4 14/20、`:70` 10-21 台账行） |
| 首轮 144 trial | `docs/evaluation/2026-10-21.md`（`:58-63` 65.0%/63.3%、`:82` subtasks=0、`:107-111` 摘要专题） |
| 批次汇总数据 | `docs/evaluation/results-2026-10-21.json`（`groups`、`diagnostic_counts`、`interpretation_limits`） |
| 饱和出处 | `docs/evaluation/2026-10-28-iteration-01.md:23-24`、`2026-10-28-authoritative-iteration-01.md:14` |
| 多 Agent 诊断 | `docs/evaluation/2026-10-28-multi-agent-diagnosis.md`（全文 42 行） |
| holdout 基线 | `docs/evaluation/2026-10-29-holdout-baseline.md` |
| 方法论 | `docs/evaluation/2026-10-29-evaluation-methodology.md`（`:12-34` 三层指标、`:98-110` Goodhart） |
| 统计功效 | `docs/evaluation/2026-10-29-task-count-power.md` |
| 台账一致性 | `docs/evaluation/WORKFLOW.md`（`:60-69` Go/No-Go、`:108-115` 工具缺口） |

### 评测仓 `sayacode-bench`

| 内容 | 位置 |
|---|---|
| 权威口径 | `docs/RESULTS-LEDGER.md` §1（planned/observed/partial/task_macro；strict 已废除） |
| 四组主表 | `docs/RESULTS-LEDGER.md` §2 |
| 协作归因 | `docs/TASKCOUNT-ATTRIBUTION.md:21`（结论）、`:168`（引用 `collaboration.jsonl` 与产物路径） |
| evals 被拦 | `docs/LESSONS-20261102-v2.md` §1.9（Docker named pipe） |
| 孤儿记录 | `docs/review/2026-11-07/R5-doc-debt.md:14,16,88,232` |
| 摘要未触发 | `docs/DEEP-ANALYSIS-20261106.md` §10 |
| 产品修复分级 | `docs/review/2026-11-07/R4-product-fixes.md` |

### 产物

| 内容 | 路径 |
|---|---|
| collaboration 6 trial | `C:\sb\hard\collab-{check-explicit,check-manual,verify-explicit,verify-single}\trials\` |
| 逐 trial 结果 | 各 `trials\<id>--<variant>--<repeat>\state\worker-result.json` |
| 运行配置 | 各 `trials\...\state\input.json`（`team_enabled`、profile） |
| 自造 32 题原始目录 | **不存在**（`C:\develop\sayacode-evaluations`、`C:\sb\eval-results` 均无） |

---

*本文所有行号基于产品仓 `HEAD = 5c84486`（工作树干净）与 bench 仓当前工作树；产物结论均来自实读 `worker-result.json` / `input.json`，未引用文档转述的数字。*
