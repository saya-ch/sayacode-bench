# SAYACODE 3.2.7 正式结果（2026-11-06）

> 目的：把评测数字从「本地未发布的 3.2.5 wheel」换成**第三方可获取的 PyPI 制品**，并给出「3.2.6/3.2.7 的产品修复是否有效」的第一份评测证据。
> 题集：冻结 `studies/sample-40-final.json` 40 题 × 2 重复 = 80 trial；模型 `auto-hy3`；官方 Harbor + SWE-bench Pro V2 verifier。
> 结果根：`C:\sb\hard\v4-327`。运行日期 2026-11-05 22:55 → 2026-11-06 06:35。

## 1. 输入身份（全部可核）

| 项 | 值 | 证据 |
|---|---|---|
| 制品 | `sayacode-3.2.7-py3-none-any.whl`（PyPI，sha256 `49db58d1…`）| Harbor `config.json` 的 `agent.kwargs.product_wheel` |
| 依赖 | `product-requirements-3.2.6.txt` | 3.2.7 METADATA 与 3.2.6 运行时依赖逐项相同，仅多 `evals` extra |
| 模型 | `auto-hy3`（多池分摊）| worker `result.json` 的 `model_id` |
| served | 按已有记录 `hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572 | `scripts/annotate_served.py` 逐 trial；记录为零 `hy3-x`、零 deepseek。⚠️ **2026-11-07 降级：该记录不可复核**——本机 Magpie routing 日志只到 10-29，见 [RESULTS-LEDGER](RESULTS-LEDGER.md) §5.6 |
| agent 版本 | `SAYACODE 3.2.7` | Harbor `result.json` 的 `agent_info.version` |

## 2. 三口径结果

| 口径 | 值 | 分子/分母 |
|---|---|---|
| planned | **76.2%** | 61 / 80（缺失按失败，主报）|
| observed | 77.2% | 61 / 79（辅助；幸存者偏差：只覆盖 79/80）|
| **partial** | **97.6%** | `verifier/output.json` 的 `tests[].status` 中 PASSED 占比，按 trial 平均（n=72/80；题级 97.8%，39 题）|
| worst / best（planned 界） | **76.25% / 77.5%** | `FINAL-SUMMARY-327.json` 的 `rates.worst_bound=0.7625`、`best_bound=0.775` |

- 缺失 1 条：`vuls-4b680b996061044e93ef5977a0816616 r1`，类别 `empty_patch`（`model.patch` 缺失）。
- 另有 2 条显式终态（`vuls-dc496468b9e r1`、`qutebrowser-3e21c8214a r1`）按 0 分计入 observed。
- 题级：完整题 39/40，task-macro **76.9%**，题块 bootstrap95 [66.7%, 85.9%]，题级全通过 24/39 = 61.5%，pass@2 36/39 = 92.3%。
- **题级分母口径**：`task_macro` 与 `pass@2` 的分母是 `complete_tasks=39`（只算两次都有 reward 的题），而 `planned` 的分母是 80（40 题）。`vuls-4b680b99606` 的 r2 通过、r1 空 patch，因此按 39 题算 `pass@2 36/39`，按 40 题全量算则是 `37/40`；两个数**不是同一口径**，引用时必须注明。
- **partial 口径**：`verifier/output.json` 的 `tests[].status` 中 PASSED 占比，按 trial 平均，分母 = 有该文件的 trial（缺失/空 patch 不计入）。主表用 `C:\sb\analysis\dataset.json` 复算值（97.6%，72 trial）。**不要用 `test-stdout.txt` 的 `Required tests` 口径**：实测同一批 trial 会低 2.4–6.8pp，两者不可混用（第二轮复盘实测，见 [STATUS.md](STATUS.md) §2）。

## 3. 与 3.2.5（本地未发布制品）的配对对比

配对 78 个 trial（两侧都有 reward 的题 × 重复）：

| | 3.2.5 | 3.2.7 |
|---|---|---|
| 通过 | 63/78 = **80.8%** | 61/78 = **78.2%** |
| planned 全量 | 63/80 = 78.8% | 61/80 = 76.2% |

- **Δ = −2.6pp**
- **McNemar exact p = 0.8145**（完全不显著）
- 题块 bootstrap（40 题）：estimate −2.5pp，**CI95 = [−12.5, +6.2]pp**（跨 0）
- 翻转 18 个 trial：3.2.5 独过 10、3.2.7 独过 8

**结论：3.2.7 与 3.2.5 在统计上没有差异**（Δ −2.6pp，p=0.8145，CI 跨 0）。

**但必须纠正一处硬性事实：3.2.7 制品内只有两项产品修复，不是三项。** `git diff --stat v3.2.5 ba43e04 -- src/` 只涉及 4 个文件（`graph.py` 4 行、`summary.py` +116、`application.py` +1、`prompts.py` +26），精确对应摘要失败降级 `c5d2973` 与提示/工具集一致性 `60ca2f0`；`41b1e38`（11-04 13:22）**晚于**发布提交 `ba43e04`（11-04 03:46），**不在 3.2.7 制品内**。另：PyPI 3.2.7 **没有对应 git tag**（最后 tag 是 `v3.2.6`），HEAD 另有 4 个提交不在制品内。

## 4. 为什么不能解读成「修复无效」：三重作用面错配

翻转的 18 个 trial 里有明显的**镜像反转**：

| 题 | r1 | r2 |
|---|---|---|
| `element-web-772df302` | PASS → FAIL | FAIL → PASS |
| `element-web-d405160080` | PASS → FAIL | FAIL → PASS |
| `qutebrowser-c09e1439f` | PASS → FAIL | FAIL → PASS |

同一题的两个重复在同一次运行内**方向相反**，说明这些题的通过与否主要由运行间随机性决定
（与 `DEEP-DIVE-20261102` 的「5 题一过一败里 3 题系统性」结论一致）。

更根本的问题是**三重作用面错配**（详见 `docs/review/2026-11-07/RETROSPECTIVE-20261107.md` §四.4、R4）：

1. **摘要失败降级 `c5d2973`**：40 题的单次调用 input 峰值仅 102k–127k，**从未达到摘要触发线（约 150,400）**——摘要路径从未触发，修复没有作用对象。
2. **提示/工具集一致性 `60ca2f0`**：本批配置 `team_enabled=true`，修复前后系统提示**逐字节不变**，作用面为零。
3. **CompletionGuard 判据收紧 `41b1e38`**：该提交不在 3.2.7 制品内，且 `completion_guard` 默认 False、从未装配。

因此：**这套题 × 这套配置对该修复的作用面为零，Δ 的信息量为零。** 既不能解读成「修复无效」，也不能解读成「有效」；在 40 题 × 2 重复的规模下，±2.6pp 本就远小于运行间噪声。要检验修复效果，需要构造走到对应路径的场景（长上下文触发摘要、`team_enabled=false`、开启 CompletionGuard），而不是继续在这套题上加重复。

## 5. 本轮与历史批次的差异（必须声明）

| 项 | 3.2.5 批次（v2-325）| 3.2.7 批次（v4-327）|
|---|---|---|
| 制品可获取性 | ❌ 本地 wheel，PyPI 从未发布 3.2.5/3.2.6 | ✅ PyPI 3.2.7 |
| served 分布 | 约 14.3% `hy3-x` + 其余 `hy3` | 0% `hy3-x`，`workbuddy` / `workbuddy-ai` 两池 |
| 并发 | 2–4 | 4（轻题）/ 1（vuls）|
| 缺失 | 1（`tutao-tutanota-51818218 r1`）| 1（`vuls-4b680b99606 r1`）|

`hy3` 与 `hy3-x` 是同一模型的不同额度池（用户确认），不构成混杂；但 served 分布不同这件事本身要随数字一起报。

## 6. 本轮踩到并记录的问题

完整清单见 `C:\sb\hard\v4-327-CHECKS.md` 与 `v4-327-interventions.log`，其中两个值得留档：

1. **`workbuddy/hy3` 单池 429**：为「固定 provider」把请求全 pin 到一个池，被该池频率限制
   （`WorkBuddy: 使用量已超出频率限制，将在 … 重置`），4 个 trial 挂起 15 分钟。
   改为 `auto-hy3` 多池分摊后恢复。**结论：pin provider 会放大单池配额风险。**
2. **Docker 引擎 API 500 挂起**：容器全掉但 runner 仍打印 `active=4` 心跳，watchdog 原逻辑
   （只看进程与日志）抓不到。已加「模型流量停滞」检测（阶段 1）与「阶段 2 放宽陈旧阈值」两处修补。

## 7. 产物

| 内容 | 路径 |
|---|---|
| 三口径（strict 已废除） | `C:\sb\hard\v4-327\STRICT-COMPARE-327.json`；仅作历史，**不作证据** |
| 逐 trial 汇总 | `C:\sb\hard\v4-327\FINAL-SUMMARY-327.json` |
| served 分布 | 各 trial 目录下 `served-distribution.json`；汇总 `hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572 |
| 跑批日志 | `C:\sb\hard\v4-327-run3.log` |
| 核验记录 | `C:\sb\hard\v4-327-CHECKS.md`（§1–§14）|
| 干预记录 | `C:\sb\hard\v4-327-interventions.log` |
| 配对分析 | `C:\sb\tmp\paired_325_327.py` |
