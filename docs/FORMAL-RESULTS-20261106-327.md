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
| served | `hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572 | `scripts/annotate_served.py` 逐 trial；**零 `hy3-x`、零 deepseek** |
| agent 版本 | `SAYACODE 3.2.7` | Harbor `result.json` 的 `agent_info.version` |

## 2. 三口径结果

| 口径 | 值 | 分子/分母 |
|---|---|---|
| planned | **76.2%** | 61 / 80（缺失按失败）|
| observed | 77.2% | 61 / 79 |
| **strict** | **76.2%** | 61 / 80，**snap pass = 0** |

- 缺失 1 条：`vuls-4b680b996061044e93ef5977a0816616 r1`，类别 `empty_patch`（`model.patch` 缺失）。
- 另有 2 条显式终态（`vuls-dc496468b9e r1`、`qutebrowser-3e21c8214a r1`）按 0 分计入 observed。
- 题级：完整题 39/40，task-macro **76.9%**，题块 bootstrap95 [66.7%, 85.9%]，题级全通过 24/39 = 61.5%，pass@2 36/39 = 92.3%。

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

**结论：3.2.7 与 3.2.5 在统计上没有差异。** 3.2.6/3.2.7 的三项产品修复
（摘要失败降级 `c5d2973`、提示与工具集一致性 `60ca2f0`、CompletionGuard 判据收紧 `41b1e38`）
**没有带来可测的提升，也没有造成退化**——效果落在运行间噪声内。

## 4. 为什么不能解读成「修复无效」

翻转的 18 个 trial 里有明显的**镜像反转**：

| 题 | r1 | r2 |
|---|---|---|
| `element-web-772df302` | PASS → FAIL | FAIL → PASS |
| `element-web-d405160080` | PASS → FAIL | FAIL → PASS |
| `qutebrowser-c09e1439f` | PASS → FAIL | FAIL → PASS |

同一题的两个重复在同一次运行内**方向相反**，说明这些题的通过与否主要由运行间随机性决定
（与 `DEEP-DIVE-20261102` 的「5 题一过一败里 3 题系统性」结论一致）。
在 40 题 × 2 重复的规模下，±2.6pp 远小于这种噪声，**既证不了有效，也证不了无效**。
要检验修复效果需要：更大题量（≥100 题）或对每题更多重复。

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
| 三口径 | `C:\sb\hard\v4-327\STRICT-COMPARE-327.json` |
| 逐 trial 汇总 | `C:\sb\hard\v4-327\FINAL-SUMMARY-327.json` |
| served 分布 | 各 trial 目录下 `served-distribution.json`；汇总 `hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572 |
| 跑批日志 | `C:\sb\hard\v4-327-run3.log` |
| 核验记录 | `C:\sb\hard\v4-327-CHECKS.md`（§1–§14）|
| 干预记录 | `C:\sb\hard\v4-327-interventions.log` |
| 配对分析 | `C:\sb\tmp\paired_325_327.py` |
