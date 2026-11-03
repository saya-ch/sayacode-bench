# CompletionGuard 本地 A/B 结果（2026-11-04）

> 目的：验证 `completion_guard`（纯文本收尾保护）是否值得默认开启。
> 设计：20 题（sample-40 分层抽样）× 2 重复 × 2 变体（guard-off / guard-on）= **80 trial**；产品 SAYACODE 3.2.6；模型 hy3；本地并发 2；¥0（Magpie 免费额度）。
> 结论先行：**guard 确实触发（on 36/40 = 90%，off 0%，以 `checkpoints.sqlite3` 实测为准），pass@1 方向为正（+10pp）但统计不显著（p≈0.29，n=20），而 token 成本 +53%（远超 <15% 护栏）→ 仍不建议默认开启。**

## 一、结果（trial 级，两组均 40/40 完整）

| 变体 | trial | pass(1.0) | fail(0.0) | pass@1 | 题级 both_pass |
|---|---|---|---|---|---|
| **guard-off** | 40 | 31 | 9 | **77.5%** | 13/20 |
| **guard-on** | 40 | 35 | 5 | **87.5%** | 16/20 |

- 差 **+10.0pp**（35 vs 31）。
- 配对（同题同 repeat，40 对）：**off败→on过 = 6，off过→on败 = 2**。
- **McNemar 精确检验：双侧 p ≈ 0.289，不显著**（一侧 P(X≥6|8)=0.1445）。
- 20 题功效不足：检测 10pp 需 ~330 题（见 `evaluation/2026-10-29-task-count-power.md`）。

## 二、成本（这是关键）

| 指标 | guard-off | guard-on | 变化 |
|---|---|---|---|
| mean model_calls / trial | 37.5 | 51.8 | **+38%** |
| mean total_tokens / trial | 1.40M | 2.15M | **+53%** |
| mean output_tokens / trial | 29.6K | 42.8K | **+44%** |

- **A/B 设计文档的成本护栏是「token 增幅 < 15%」——实际 +53%，严重超护栏**。
- **guard 触发率（正确口径）= on 36/40 = 90%，off 0/40 = 0%**：用 `agent/sayacode/checkpoints.sqlite3`（LangGraph 持久化 messages）实测——on 的 checkpoints 含 55 处 `continue_nudge` 明文，off 为 0 处。
- **不能用 `events.jsonl` 算触发率**：它只记 `assistant.delta/tool.started/model.completed` 等，不含 message 内容，搜 `sayacode_continue_nudge` 会**假阴性 0%**（最初 `analyze_ab.py` 就踩了这个坑，已用 `analyze_ab_fixed.py` / `verify_nudge.py` 更正）。
- model_calls/tokens 的上升（+38% / +53%）与 90% 触发一致：每轮最多 1 次 nudge，触发后模型继续执行多步。

## 三、解读

**能说**：
- guard 在这批题上**触发了**（成本证据），但**没有带来统计显著的通过率提升**（+10pp，p≈0.29）。
- guard 让模型「多做」，token 成本 +53%，但多数多做没转化为通过。
- 按设计文档护栏：**H1 不成立 + 成本超护栏 → 不进入默认开启**（保持 `completion_guard=False`）。

**不能说**：
- 不能说 guard「无效」——n=20 功效不足，+10pp 可能是真效应但测不出；需要 ~330 题才能判定 10pp。
- 不能宣称 guard 有收益——当前证据不支持。

## 四、建议

1. **保持默认关闭**（`completion_guard=False`）；本轮未发现默认开启的理由。
2. 若要正式验证：扩到 ≥120 题（检测 18pp）或 ≥330 题（检测 10pp），并监控 token 增幅护栏。
3. 修 `worker`/`events`：**记录 nudge 注入次数**，否则无法直接算触发率（当前只能从 usage 间接推断）。
4. 本次顺带修复的**三个 3.2.6 安装真 bug**（否则 3.2.6 在 Debian12 镜像全失败）：
   - `run_holdout.py` 未从 wheel 推断 `PRODUCT_VERSION`（locked_agents 有、run_holdout 没有）；
   - `adapter.py` uv 兜底顺序：pip3 应最前（有 curl 的镜像走 install-uv.sh 会因 astral.sh 403 失败）；
   - `adapter.py` PEP 668：Debian12 `pip3 install` 需 `--break-system-packages`。
   修后 6 个原本 15 秒 infra 的 trial 全部补回 reward（SAYACODE 3.2.6 校验 rc=0）。

## 五、产物

- 数据：`C:\sb\tmp\completion-guard\{off,on}\jobs\`（各 40 trial，`result.json` 含 usage）。
- 分析：`C:\sb\tmp\completion-guard\analyze_ab.py`、`usage_cmp.py`。
- 变体：`guard-off.json` / `guard-on.json`；样本：`sample-20.json`。
