# STATUS：当前真实状态

更新：**2026-11-07（P0 修正）**。本文件只写**当前有效**的事实。历史演进与作废清单一处看：[RETROSPECTIVE-20261105](RETROSPECTIVE-20261105.md)；协议见 [PROTOCOL-V2](PROTOCOL-V2.md)；踩坑见 [LESSONS-20261102-v2](LESSONS-20261102-v2.md)；作废文档见 [docs/archive/](archive/README.md)。

> ⚠️ **本文件已按 2026-11-07 复盘修正：`strict` 口径废除**（其前提「verifier 不重置 `.snap`」被 642/642 个 `tests/test.sh:97-105` 证伪），改用 **planned / observed / partial** 三口径。证据见 [review/RETROSPECTIVE-20261107.md](review/2026-11-07/RETROSPECTIVE-20261107.md)。

## 1. 一句话状态

40 题 × 2 重复的四组对照，**SAYACODE 已换成 PyPI 可获取的 3.2.7**（运行根 `C:\sb\hard\v4-327`，2026-11-06），三个基线仍是 v2-325 批次（跨批次，见 §2 脚注）。planned **76.2% / 85.0% / 77.5% / 75.0%**（SAYACODE 3.2.7 / mini-swe / Claude Code / OpenCode），**四组落在 75.0–85.0% 窄带，跨批次不可排名**；题级 McNemar **全部不显著**（旧四组配对 p ≥ 0.070；327 跨批次配对不复算，见 §2.1）。Codex 组整组作废；v1 结论继续作废。`strict` 口径已废除（前提被证伪），不再给出 strict 数字与名次。

## 2. 终版数字（以 `FINAL-SUMMARY-V4.json` / `FINAL-SUMMARY-327.json` 为准）

| agent | planned | observed | **partial** | 缺失 | 题级 task-macro | bootstrap95 | 题级全通过 |
|---|---|---|---|---|---|---|---|
| **SAYACODE 3.2.7** | **76.2%** (61/80) | 77.2% | 97.6% | 1 | **76.9%** | [66.7, 85.9] | 24/39 = 61.5% |
| **mini-swe** | 85.0% (68/80) | 86.1% | 98.5% | 1 | 87.2% | [79.5, 94.9] | 30/39 = 76.9% |
| **Claude Code** | 77.5% (62/80) | 78.5% | 97.9% | 1 | 78.2% | [67.9, 88.5] | 25/39 = 64.1% |
| **OpenCode** | 75.0% (60/80) | 75.0% | 94.4% | **0** | 75.0% | [65.0, 83.8] | 23/40 = 57.5% |
| ~~Codex CLI~~ | 68.8% | 69.6% | — | 1 | — | — | **不可比** |

口径：
- **planned = 80 分母**（缺失按失败，主报）。
- **observed**（只含有 reward/终态的子集，单独报会高估；mini-swe 的 observed 86.1% 只覆盖 79/80，存在幸存者偏差）。
- **partial** = `verifier/test-stdout.txt` 的 `Required tests that passed / Required tests`，**按 trial 平均**；分母 = **有该文件的 trial**（缺失/空 patch 无 test-stdout，不计入）。覆盖：SAYACODE 3.2.7 72/80、mini-swe 77/80、Claude Code 76/80、OpenCode 77/80。**题级均值**（先按题归约重复再平均）分别为 97.8% / 98.6% / 98.0% / 94.6%。数据源：`C:\sb\analysis\dataset.json`（其 `required/passed` 即 test-stdout 的 N/M）。`FINAL-SUMMARY-V4.json` / `FINAL-SUMMARY-327.json` 的 `partial` 字段覆盖更全（79–80/80），但其中 11–12 条分母比 test-stdout 多 1（如 `flipt-8bd3604` 0.857=6/7 vs test-stdout 6/6），因此未作为主口径。
- **strict 已废除**：其前提「verifier 不重置 `__snapshots__/*.snap`」被 642/642 个 `tests/test.sh:97-105` 证伪（判分前对 `.snap` 执行 `git checkout HEAD`）。如仍需保留 snap 信息，只能报 `touches_snap_pass`（patch 触碰 snap 且 reward=1 的 trial 数：0/4/3/6/3），并注明**不影响结果、不参与排名**。
- **跨批次警告（强化）**：SAYACODE 行来自 2026-11-06 的 `v4-327`（PyPI 3.2.7、served 全 hy3）；三个基线来自 2026-11-02 的 `v2-325`（served 约 14.3% hy3-x）。题集、模型族、evaluator 相同，但**不是同批次同跑**，组间差异与批次效应完全混淆，**只可做描述性对照，不能当作严格的同条件实验，也不能据此排名**。

### 2.0 补跑前后必须同报（协议 §6）

| agent | 补跑前 | 补跑后 | 增量 | 根因 |
|---|---|---|---|---|
| SAYACODE | 67.5% | **78.8%** | +11.3pp | TLS / apt / 网络 |
| mini-swe | **70.0%**（56/80）| **85.0%**（68/80）| **+15.0pp** | **全部是安装期网络失败**（`apt-get exit 100` 撞 Clash fake-ip；`NetworkConnectError`），agent 从未执行 |
| Claude Code / OpenCode | — | 77.5% / 75.0% | — | 首跑即含修好的网络配置，无补跑 |

**mini-swe 的 85.0% planned 建立在补跑 12 条之后**；那 12 条按语义是 `infra`（可补），但旧分类把它们记成 `empty_patch`（不补），造成「违反协议」的假象。证据与修复见 [RETROSPECTIVE §5.6](RETROSPECTIVE-20261105.md)。

### 2.1 两两配对（题级全通过，McNemar exact）

| 对比 | 共同题 | delta | a 独过 / b 独过 | p |
|---|---|---|---|---|
| Claude Code vs mini-swe | 38 | −7.9% | 3 / 7 | 0.344 |
| Claude Code vs SAYACODE | 38 | 0.0% | 4 / 7 | 0.549 |
| Claude Code vs OpenCode | 39 | +3.8% | 9 / 6 | 0.607 |
| mini-swe vs SAYACODE | 38 | +7.9% | 6 / 5 | 1.000 |
| mini-swe vs OpenCode | 39 | +11.5% | 11 / 4 | 0.118 |
| **OpenCode vs SAYACODE** | 39 | −3.8% | 1 / 7 | **0.070** |
| SAYACODE 3.2.7 vs mini-swe | 40 | −12.5% | 3 / 8 | 0.227 |
| SAYACODE 3.2.7 vs Claude Code | 40 | −2.5% | 5 / 6 | 1.000 |
| SAYACODE 3.2.7 vs OpenCode | 40 | +5.0% | 8 / 6 | 0.791 |

后三行是 11-06 新批次对 11-02 旧批次的跨批次配对（40 题全交集）；口径与上表一致（题级全通过）。

⚠️ **后三行不作为证据**：R2 复算（[review/2026-11-07/R2-data-verification.md](review/2026-11-07/R2-data-verification.md) §2.3）显示其数字无法重现——common 写 40，实测 complete 交集为 38/39；Claude 一行 b 独过文档 6、实测 5，OpenCode 一行 a 独过文档 8、实测 7，OpenCode 一行 p=0.791、实测 1.0。且跨批次配对本身受批次效应污染，**不得引用这三行的 p 值与独过数**。

Bonferroni α/3 ≈ 0.0167（三组两两为上限口径）。**全部未过。**

### 2.2 Codex 组为何不可比

`docs/CODEX-BASELINE-INVALID.md`：`unsupported call: apply_patch` 373 次（78/80 trial）、`/v1/responses` websocket 405 960 次（80/80 trial）、模型统一 hy3 而 Codex 是 OpenAI 自家调优。**其 68.8% planned 不参与任何排名**（strict 已废除，65.0% 不再引用）。已被 Claude Code 替换。

### 2.3 适配健康度（`scripts/audit_agent_traj.py` 全量轨迹）

| agent | API Error | unsupported call | websocket 405 | tool_use |
|---|---|---|---|---|
| SAYACODE | 0 | 0 | 0 | — |
| mini-swe | 0 | 0 | 0 | — |
| Claude Code | **0** | **0** | **0** | 3468 / 80 trial（tool_result 3467）|
| OpenCode | **0** | **0** | **0** | 2480 / 80 trial |
| ~~Codex~~ | 960 | 373 | 960 | apply_patch 全组不可用 |

## 3. 制品身份（必须随任何结论声明）

- **3.2.5 批次**（`v2-325`，本地构建 `sayacode-3.2.5-py3-none-any.whl`，`scripts/locked_agents.py:48`；PyPI 从未发布 3.2.5/3.2.6）：planned **78.8%（63/80）**，该数字**第三方不可复现**。
- **3.2.7 批次**（`v4-327`，PyPI `sayacode-3.2.7-py3-none-any.whl`，sha256 `49db58d1…`）：planned **76.2%（61/80）**，制品可获取；但 PyPI 3.2.7 **没有对应 git tag**（最后 tag 是 `v3.2.6`），HEAD 另有 4 个提交不在制品内。
- PyPI 上 `sayacode` 的版本是 `… 3.2.3, 3.2.4, **3.2.7**`——**3.2.5 / 3.2.6 从未发布**。
- 因此：**不能说「78.8% 是 PyPI 版本的分数」**；「修复带来提升」目前**无评测证据**（3.2.6/3.2.7 的修复存在三重作用面错配，见 [FORMAL-RESULTS-20261106-327.md](FORMAL-RESULTS-20261106-327.md) §3–§4）。

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
- **模型**：**hy3**（`auto-hy3`，网关 `owned_by=workbuddy`），context 192,000 / `max_output_tokens=32000`（模型上限 64k）。hy3 **不接受 temperature**，可复现性靠固定来源 + 固定 seed + 重复次数。

### 5.1 模型身份与 served 分布（2026-11-05 更正）

- ⚠️ **`auto-hy3` ≠ `auto/deepseek-v4.1-flash`**。网关 `/v1/models` 是两条独立记录：`auto/hy3`（`workbuddy`，192k/64k）与 `auto/deepseek-v4.1-flash`（`opencode-zen`，1M/200k）。本仓库早期文档（v3 报告初版、Codex/Claude Code 基线文档）把两者混为一谈，**已更正**。
- 评测窗口（10-31 ~ 11-05）内 42681 条 Magpie usage 记录，四组基线的 `served` **全是 `hy3` / `hy3-x`，零 `deepseek-v4.1-flash`**（后者只出现在本机 DSH 会话）。
- `hy3` 与 `hy3-x` 是同一个模型（用户确认，`ROUTING-DRIFT-20261029.md:60`）；占比差异只是额度池分摊，不影响组间可比性。
- 逐 trial 记录里 `canonical_model` 字段值是 `auto-hy3`（正确，没有被 src 的旧常量污染）。
- 遗留隐患：`src/sayacode_bench/{connections,execution}.py` 的 `CANONICAL_MODEL = "DeepSeek-V4.1-Flash"` 是 v1 SiliconFlow 时代遗留（`study.py` 的 freeze 路径会用它校验 profile）；本批跑批走 `scripts/locked_agents.py` 的 `auto-hy3`，**两条路径的常量不一致，未统一**。
- **基线**：mini-swe / Claude Code / OpenCode（Codex 作废）。协议全部走本地网关三路（`/v1/chat/completions`、`/v1/messages`、`/v1/responses`）。
- **跑批**：stage1 与 verify **串行**；轻题并发 2–4，vuls 等重题并发 1（单题 3.3GB，WSL 7GB 上限）；验证器限流 1；跑前 `docker network prune -f`。
- **行为测试**：`uv run --no-sync pytest -q` → **1430 passed / 9 skipped**（2026-11-05 实测，190s）。
- **环境**：`.wslconfig` `memory=7GB`/`swap=2GB`（合并写入，勿覆盖 mirrored/dnsTunneling）；Clash profile `prepend` 需含 `debian.org`/`ubuntu.com`/**`+.fastlydns.net`** DIRECT；容器直连、不走代理。
- **磁盘**：`docker_data.vhdx` 稀疏，删镜像不回收；需管理员 `diskpart compact vdisk`。
- **结果根**：`C:\sb\hard\v2-325`（v2/v3/v4 同一根，按产物文件区分）。

## 6. 已知局限（必须随任何结论声明）

1. **统计不显著**：四组两两 p ≥ 0.070，最小可检测效应远大于组间差。
2. **题集无判别力**：题面中位 **2 文件 / 64 行**（SAYACODE 62% 的 trial 只碰 1–2 文件）；四组被压在 planned 75.0–85.0% 窄带（strict 已废除，不再引用 67.5–80.0）。
3. **开发集当正式成绩**：40 题是**开发迭代集**，且 SAYACODE 的提示词规则 R1–R5 正是从这套题的失败个案调出来的 → 对 SAYACODE 有偏置（方向有利，结论仍不显著）。**独立 holdout 从未执行**。
4. **制品断链**：78.8% 对应本地 3.2.5 wheel，第三方不可获取（§3）。
5. **重复 2 次不足**：一过一败的 5 题里 3 题是系统性差异（patch 规模 3.3× / 7.3× / 59×）。
6. **`task_count` 全 0**：这批题不触发多 agent，不能用它评价协作（协作另用 `evals/scenarios/collaboration-autonomous.jsonl`，已单题验证 `task_count=2`）。
7. **仅 hy3**：结论不外推其他模型；各脚手架与模型的原生适配度未被统一（Claude Code / Codex 是厂商调优产品，OpenCode / mini-swe 是模型无关脚手架，SAYACODE 围绕该网关打磨过）。
8. **样本小**：40 题 CI 宽 ±12pp；检测 10pp 差异需约 330 题。
9. **补跑效应大**：SAYACODE +11.3pp、mini-swe +22.5pp 都发生过；补跑前数字不能当能力。

## 7. 下一步（按优先级）

1. **还文档债**：见 [RETROSPECTIVE](RETROSPECTIVE-20261105.md) §6（本文件已重写；README / HANDOFF / AGENTS / LESSONS 已同步）。
2. ~~用 3.2.7（或 HEAD 构建的 3.2.8）重跑 SAYACODE 单组 80 trial~~：**已完成**（`v4-327`，planned 76.2%，见 §9）；但基于该批的「修复有效性」结论因作用面错配不成立，见 327 报告 §3–§4。
3. **注入长上下文/多文件压力做受控 A/B**（干净 vs 加压，同题同验证器）：直接检验"题太浅导致无判别力"这一假设。
4. **holdout 提示词配对**（R1/R3 去留）：关掉开发集偏置洞；受硬件与题量限制。
5. **扩样 ≥100 题**：CI 收到约 ±9pp 才谈得上显著性（`SCALE-WITHOUT-UPGRADE.md`）。
6. **多模型 / 原生模型对照**：超 ¥50 预算，暂不做。

## 8. 证据与文档

| 内容 | 位置 |
|---|---|
| 四组逐 trial 汇总 | `C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json` |
| strict 口径（已废除） | `C:\sb\hard\v2-325\STRICT-COMPARE.json`；仅在重新定义前保留，**不作证据** |
| 轨迹审计 | `C:\sb\hard\v2-325\TRAJ-AUDIT-{claude-code,opencode}.json` |
| 四组报告 | [FORMAL-RESULTS-20261105-v3.md](FORMAL-RESULTS-20261105-v3.md) |
| **历史演进 + 文档债** | [RETROSPECTIVE-20261105.md](RETROSPECTIVE-20261105.md) |
| 现行协议 | [PROTOCOL-V2.md](PROTOCOL-V2.md) |
| 踩坑记录 | [LESSONS-20261102-v2.md](LESSONS-20261102-v2.md) |
| 交接 | [HANDOFF.md](HANDOFF.md) |
| 历史/作废 | [docs/archive/](archive/README.md) |

## 9. 已完成批次（P0）：SAYACODE 3.2.7（可获取制品）

**2026-11-06 06:35 完成。** 目的达成：数字现在对应 PyPI 上第三方可安装的制品。

| 项 | 值 |
|---|---|
| 制品 | `sayacode-3.2.7-py3-none-any.whl`（PyPI，sha256 `49db58d1…`）|
| 结果根 | `C:\sb\hard\v4-327`（80 trial）|
| **planned / observed / partial** | **76.2% (61/80) / 77.2% / 97.6%**，snap 信息仅作 `touches_snap_pass`（0）参考 |
| 缺失 | 1（`vuls-4b680b99606 r1`，`empty_patch`）|
| 题级 | 完整题 39/40，task-macro 76.9%，CI95 [66.7, 85.9]|
| served | `hy3/workbuddy` 6206 + `hy3/workbuddy-ai` 3572，**零 hy3-x、零 deepseek** |

**与 3.2.5 的配对对比（78 个 trial）**：80.8% → 78.2%，Δ −2.6pp，
**McNemar p = 0.8145**，题块 bootstrap CI95 [−12.5, +6.2]pp（跨 0）。

→ **3.2.7 制品内实际只有两项产品修复**（摘要失败降级 `c5d2973`、提示/工具集一致性 `60ca2f0`；`41b1e38` 晚于发布提交 `ba43e04`、不在制品内），且两者在**这套题 × 这套配置**下作用面为零（摘要路径从未触发；`team_enabled=true` 时提示逐字节不变）。因此 Δ 的信息量为零，**不能解读为「修复无效」**。
翻转的 18 个 trial 里有多组「同题 r1/r2 镜像反转」，说明题目级随机性是主要噪声来源。

完整报告：[FORMAL-RESULTS-20261106-327.md](FORMAL-RESULTS-20261106-327.md)。

## 10. P1（下一步）

设计见 [EXPERIMENT-CONTEXT-AB.md](EXPERIMENT-CONTEXT-AB.md)；工具已就绪：`scripts/make_context_noise.py`（确定性噪声生成，已 smoke）、`scripts/analyze_context_ab.py`（配对退化分析）。**噪声注入钩子尚未加入 `locked_agents.py`**——P0 跑批进程依赖该文件，改它会污染 P0 结果。
