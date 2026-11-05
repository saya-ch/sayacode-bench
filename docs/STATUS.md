# STATUS：当前真实状态

更新：**2026-11-05（v4：四组基线定稿）**。本文件只写**当前有效**的事实。历史演进与作废清单一处看：[RETROSPECTIVE-20261105](RETROSPECTIVE-20261105.md)；协议见 [PROTOCOL-V2](PROTOCOL-V2.md)；踩坑见 [LESSONS-20261102-v2](LESSONS-20261102-v2.md)；作废文档见 [docs/archive/](archive/README.md)。

## 1. 一句话状态

40 题 × 2 重复 × **4 个可用基线**的正式对照已完成（运行根 `C:\sb\hard\v2-325`）：planned **78.8% / 85.0% / 77.5% / 75.0%**，strict **78.8% / 80.0% / 73.8% / 67.5%**（SAYACODE / mini-swe / Claude Code / OpenCode）。**两两 McNemar 全部不显著（p ≥ 0.070）**，不能说谁更强。Codex 组整组作废。v1 结论继续作废。

## 2. 终版数字（以 `FINAL-SUMMARY-V4.json` + `STRICT-COMPARE.json` 为准）

| agent | planned | observed | **strict** | 缺失 | 题级 task-macro | bootstrap95 | 题级全通过 | snap pass |
|---|---|---|---|---|---|---|---|---|
| **SAYACODE** | **78.8%** (63/80) | 79.7% | **78.8%** | 1 | **80.8%** | [69.2, 91.0] | 29/39 = 74.4% | **0** |
| **mini-swe** | 85.0% (68/80) | 87.2% | **80.0%** | 2 | 87.2% | [79.5, 94.9] | 30/39 = 76.9% | 4 |
| **Claude Code** | 77.5% (62/80) | 78.5% | **73.8%** | 1 | 78.2% | [67.9, 88.5] | 25/39 = 64.1% | 3 |
| **OpenCode** | 75.0% (60/80) | 75.0% | **67.5%** | **0** | 75.0% | [65.0, 83.8] | 23/40 = 57.5% | **6** |
| ~~Codex CLI~~ | 68.8% | 69.6% | 65.0% | 1 | — | — | — | 3 | **不可比** |

口径：
- **planned = 80 分母**（缺失按失败，主报）；
- **observed**（只含有 reward/终态的子集，单独报会高估）；
- **strict** = planned 再扣掉「改 `__snapshots__/*.snap` 换来的 pass」（`tests/test.sh` 只重置测试**代码**，`.snap` 不重置）。
- 三种口径给出**三种排名**（planned 上 mini-swe 领先 6.2pp；strict 上缩到 1.2pp）→ **报告必须三口径并列，不给单一排名**。

### 2.1 两两配对（题级全通过，McNemar exact）

| 对比 | 共同题 | delta | a 独过 / b 独过 | p |
|---|---|---|---|---|
| Claude Code vs mini-swe | 38 | −7.9% | 3 / 7 | 0.344 |
| Claude Code vs SAYACODE | 38 | 0.0% | 4 / 7 | 0.549 |
| Claude Code vs OpenCode | 39 | +3.8% | 9 / 6 | 0.607 |
| mini-swe vs SAYACODE | 38 | +7.9% | 6 / 5 | 1.000 |
| mini-swe vs OpenCode | 39 | +11.5% | 11 / 4 | 0.118 |
| **OpenCode vs SAYACODE** | 39 | −3.8% | 1 / 7 | **0.070** |

Bonferroni α/3 ≈ 0.0167（三组两两为上限口径）。**全部未过。**

### 2.2 Codex 组为何不可比

`docs/CODEX-BASELINE-INVALID.md`：`unsupported call: apply_patch` 373 次（78/80 trial）、`/v1/responses` websocket 405 960 次（80/80 trial）、模型统一 hy3 而 Codex 是 OpenAI 自家调优。**其 68.8% / 65.0% 不参与任何排名。** 已被 Claude Code 替换。

### 2.3 适配健康度（`scripts/audit_agent_traj.py` 全量轨迹）

| agent | API Error | unsupported call | websocket 405 | tool_use |
|---|---|---|---|---|
| SAYACODE | 0 | 0 | 0 | — |
| mini-swe | 0 | 0 | 0 | — |
| Claude Code | **0** | **0** | **0** | 3468 / 80 trial（tool_result 3467）|
| OpenCode | **0** | **0** | **0** | 2480 / 80 trial |
| ~~Codex~~ | 960 | 373 | 960 | apply_patch 全组不可用 |

## 3. 制品身份（必须随任何结论声明）

- 所有 SAYACODE 数字跑的是**本地构建的 `sayacode-3.2.5-py3-none-any.whl`**（`scripts/locked_agents.py:48`），**不是 PyPI 制品**。
- PyPI 上 `sayacode` 的版本是 `… 3.2.3, 3.2.4, **3.2.7**`——**3.2.5 / 3.2.6 从未发布**。
- 产品 HEAD（`41b1e38`）相对 `v3.2.5` 又有实质改动（`summary.py` +116、`graph.py` +35、`prompts.py` +26），即**阶段 3 修的产品缺陷没进被测制品**。
- 因此：**不能说「78.8% 是 PyPI 版本的分数」**；「修复带来提升」目前**无评测证据**（只有单题/小样本对照）。

## 4. v1 结论仍作废（不得引用）

| 曾声称 | 作废原因 |
|---|---|
| SAYACODE 68.8% 低于 mini-swe/Codex 86.2%（17.4pp）| 三套分母并列；Codex 实为 56/65，统一 80 分母 70.0% |
| 「改测试率 49% / 73% / 42%」| 49%≈48.8% 是**产品侧检测率**（39/80），patch 含测试比例是另一量（SAYACODE 0% / mini-swe 70.9% / Codex 54.2%）|
| 「3 条模型故障，剔除后 71.4%」| 只有 1 条真 API 故障（`vuls-f6cc8c-r1` ECONNRESET）|
| 「40 题 gold patch 全绿」| 实际 36 good / 1 bad / 3 null |

完整记录见 [archive/FORMAL-RESULTS-20261031.md](archive/FORMAL-RESULTS-20261031.md) 与 [RETROSPECTIVE](RETROSPECTIVE-20261105.md) §2.3。

## 5. 基建与产品状态

- **产品**：HEAD `41b1e38`（3.2.7 已发布到 PyPI；3.2.5/3.2.6 未发布）。评测制品固定 3.2.5。
- **模型**：hy3（`auto-hy3`），context 192,000 / `max_output_tokens=32000`（模型上限 64k）。hy3 **不接受 temperature**，可复现性靠固定来源 + 固定 seed + 重复次数。
- **基线**：mini-swe / Claude Code / OpenCode（Codex 作废）。协议全部走本地网关三路（`/v1/chat/completions`、`/v1/messages`、`/v1/responses`）。
- **跑批**：stage1 与 verify **串行**；轻题并发 2–4，vuls 等重题并发 1（单题 3.3GB，WSL 7GB 上限）；验证器限流 1；跑前 `docker network prune -f`。
- **行为测试**：`uv run --no-sync pytest -q` → **1430 passed / 9 skipped**（2026-11-05 实测，190s）。
- **环境**：`.wslconfig` `memory=7GB`/`swap=2GB`（合并写入，勿覆盖 mirrored/dnsTunneling）；Clash profile `prepend` 需含 `debian.org`/`ubuntu.com`/**`+.fastlydns.net`** DIRECT；容器直连、不走代理。
- **磁盘**：`docker_data.vhdx` 稀疏，删镜像不回收；需管理员 `diskpart compact vdisk`。
- **结果根**：`C:\sb\hard\v2-325`（v2/v3/v4 同一根，按产物文件区分）。

## 6. 已知局限（必须随任何结论声明）

1. **统计不显著**：四组两两 p ≥ 0.070，最小可检测效应远大于组间差。
2. **题集无判别力**：题面中位 **2 文件 / 64 行**（SAYACODE 62% 的 trial 只碰 1–2 文件）；四组被压在 67.5–80.0% 窄带。
3. **开发集当正式成绩**：40 题是**开发迭代集**，且 SAYACODE 的提示词规则 R1–R5 正是从这套题的失败个案调出来的 → 对 SAYACODE 有偏置（方向有利，结论仍不显著）。**独立 holdout 从未执行**。
4. **制品断链**：78.8% 对应本地 3.2.5 wheel，第三方不可获取（§3）。
5. **重复 2 次不足**：一过一败的 5 题里 3 题是系统性差异（patch 规模 3.3× / 7.3× / 59×）。
6. **`task_count` 全 0**：这批题不触发多 agent，不能用它评价协作（协作另用 `evals/scenarios/collaboration-autonomous.jsonl`，已单题验证 `task_count=2`）。
7. **仅 hy3**：结论不外推其他模型；各脚手架与模型的原生适配度未被统一（Claude Code / Codex 是厂商调优产品，OpenCode / mini-swe 是模型无关脚手架，SAYACODE 围绕该网关打磨过）。
8. **样本小**：40 题 CI 宽 ±12pp；检测 10pp 差异需约 330 题。
9. **补跑效应大**：SAYACODE +11.3pp、mini-swe +22.5pp 都发生过；补跑前数字不能当能力。

## 7. 下一步（按优先级）

1. **还文档债**：见 [RETROSPECTIVE](RETROSPECTIVE-20261105.md) §6（本文件已重写；README / HANDOFF / AGENTS / LESSONS 已同步）。
2. **用 3.2.7（或 HEAD 构建的 3.2.8）重跑 SAYACODE 单组 80 trial**：让数字对应可获取制品，并首次为"修复有效性"提供评测证据。本地 ¥0。
3. **注入长上下文/多文件压力做受控 A/B**（干净 vs 加压，同题同验证器）：直接检验"题太浅导致无判别力"这一假设。
4. **holdout 提示词配对**（R1/R3 去留）：关掉开发集偏置洞；受硬件与题量限制。
5. **扩样 ≥100 题**：CI 收到约 ±9pp 才谈得上显著性（`SCALE-WITHOUT-UPGRADE.md`）。
6. **多模型 / 原生模型对照**：超 ¥50 预算，暂不做。

## 8. 证据与文档

| 内容 | 位置 |
|---|---|
| 四组逐 trial 汇总 | `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json` |
| 严格口径对比 | `C:\sb\hard\v2-325\STRICT-COMPARE.json` |
| 轨迹审计 | `C:\sb\hard\v2-325\TRAJ-AUDIT-{claude-code,opencode}.json` |
| 四组报告 | [FORMAL-RESULTS-20261105-v3.md](FORMAL-RESULTS-20261105-v3.md) |
| **历史演进 + 文档债** | [RETROSPECTIVE-20261105.md](RETROSPECTIVE-20261105.md) |
| 现行协议 | [PROTOCOL-V2.md](PROTOCOL-V2.md) |
| 踩坑记录 | [LESSONS-20261102-v2.md](LESSONS-20261102-v2.md) |
| 交接 | [HANDOFF.md](HANDOFF.md) |
| 历史/作废 | [docs/archive/](archive/README.md) |
