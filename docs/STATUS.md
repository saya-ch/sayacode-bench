# STATUS：当前真实状态

更新：2026-11-02。**v2 开发期 240 trial 已完成，基建已重建，产品 SAYACODE 3.2.5 已发布；v1 结论仍作废。**

本文件只写**当前有效**的事实。v2 报告见 [FORMAL-RESULTS-20261102-v2.md](FORMAL-RESULTS-20261102-v2.md)，协议见 [PROTOCOL-V2.md](PROTOCOL-V2.md)，踩坑见 [LESSONS-20261102-v2.md](LESSONS-20261102-v2.md)；历史与作废文档见 [docs/archive/](archive/README.md)。

## 1. 一句话状态

v2（40 题 × 2 重复 × 3 agent = 240 trial，运行根 `C:\sb\hard\v2-325`）已完成：planned **78.8% / 70.0% / 68.8%**，补跑后**缺失 15 条已分类**。三 agent 经 Bonferroni 校正后差异**均不显著**，不能下「谁更强」的结论。v1 结论继续作废。

## 2. v2 终版数字（以 `FINAL-SUMMARY.json` 2026-11-02 23:04 版为准）

| agent | planned | observed | task_macro | 缺失 | CI95 | 题级 complete | pass@2 |
|---|---|---|---|---|---|---|---|
| **SAYACODE** | **78.8%** | 79.7% | **80.8%** | 1 | [69.2, 91.0] | 39/40 | 87.2% |
| **mini-swe** | **70.0%** | 84.8% | **84.8%** | 14 | [75.8, 92.4] | 33/40 | 97.0% |
| **Codex** | **68.8%** | 68.8% | **68.8%** | 0 | [57.5, 80.0] | 40/40 | 85.0% |

口径：**planned = 80 分母（缺失按失败，主报）**；observed = 有 reward/终态的子集；task_macro = 题级宏平均；题级 complete = 有终态的题数。只报 observed 会高估（mini-swe 84.8% 只覆盖 66/80），任何表格必须带 planned。

### 2.1 缺失 15 条（已分类）

| agent | 缺失 | 分类 |
|---|---|---|
| SAYACODE | 1 | `empty_patch`（tutanota-5181821-r1）|
| mini-swe | 14 | `empty_patch` 8 + `no_job` 6（qutebrowser setup_timeout）|
| Codex | 0 | — |

分类与补跑规则见 [PROTOCOL-V2 §3–§6](PROTOCOL-V2.md)：环境类（infra/no_job/unverified）可补，timeout / empty_patch 不补。

### 2.2 补跑效应

| agent | 初始 planned% | 终版 planned% | 增量 |
|---|---|---|---|
| SAYACODE | 67.5% | 78.8% | **+11.3pp** |
| mini-swe | 47.5% | 70.0% | **+22.5pp** |
| Codex | 68.8% | 68.8% | 0 |

补跑收益不能归因于产品修复；环境失败会系统性惩罚某些 agent，补跑前数字不能当能力。

### 2.3 题级 McNemar（任务块）

| 对比 | 共同题 | delta | p | 结论 |
|---|---|---|---|---|
| mini-swe vs SAYACODE | 32 | +1.6% | 0.727 | 不显著 |
| Codex vs SAYACODE | 39 | −10.3% | 0.021 | **未过** Bonferroni α/3 = 0.0167 |
| Codex vs mini-swe | 33 | −15.2% | 0.065 | 不显著 |

### 2.4 `task_count` 全 0

240 trial 的 `task_count` 全为 0：本批是单点/单文件调试，**不能用它评价多 agent 协作**；协作能力须另用 `evals/scenarios/collaboration-autonomous.jsonl`。

## 3. v1 结论仍作废（不得引用）

| 曾声称 | 作废原因 |
|---|---|
| SAYACODE 68.8% 低于 mini-swe/Codex 86.2%（17.4pp）| 三套分母并列；Codex 实为 56/65，统一 80 分母 70.0% |
| 「改测试率 49% / 73% / 42%」| 49%≈48.8% 是**产品侧检测率**（39/80），patch 含测试比例是 SAYACODE 0% / mini-swe 70.9% / Codex 54.2%，两口径不可混；v2 尚未采集改测试指标 |
| 「3 条模型故障，剔除后 71.4%」| v1 只有 1 条真 API 故障（vuls-f6cc8c-r1 ECONNRESET）；严格剔除后 55/79 = 69.6% |
| 「40 题 gold patch 全绿」| 实际 36 good / 1 bad / 3 null；bad 不在 40 题内，null 不能算绿 |

完整 v1 记录见 [archive/FORMAL-RESULTS-20261031.md](archive/FORMAL-RESULTS-20261031.md) 与 [archive/README](archive/README.md)。

## 4. 基建与产品状态

- **产品**：SAYACODE **3.2.5**（`13df615` / `v3.2.5`）已发布；评测实现 `dfe2fd8`。
- **模型**：hy3（`auto-hy3`），context 192,000 / `max_output_tokens=32000`；每个 trial 记录 served/provider。
- **跑批**：stage1 与 verify **串行**；并发 4–6，验证器限流 1；跑前 `docker network prune -f`。
- **已修 bug**：安装证据目录重跑幂等（`5c59126`）、产品版本从 wheel 文件名推断（`a1e51d3`）、阶段1 续跑认 `normalized.json`（`5f8b138`）。
- **环境**：`.wslconfig` 设 `memory=7GB`/`swap=2GB`（合并写入，勿覆盖 mirrored/dnsTunneling）；Clash profile `prepend` 已加 debian/ubuntu DIRECT（修 apt 502）；容器直连、不走代理（修 gaierror）。
- **磁盘**：`docker_data.vhdx` 稀疏，删镜像不会立即回收；约 53GB 需 `diskpart` 的 `compact vdisk` 才释放。
- **结果根**：v2 在 `C:\sb\hard\v2-325`；v1 在 `C:\sb\hard\formal-240`（历史）。

## 5. 已知局限（必须随任何结论声明）

1. **统计不显著**：三 agent 校正后均不显著（Codex vs SAYACODE p=0.021 未过 α/3=0.0167）。
2. **mini-swe 幸存者偏差**：observed 84.8% 只覆盖 66/80，task_macro 仅 33/40。
3. **Codex 零缺失但 task_macro 最低**（68.8%）：40/40 完整，数字最可信，不代表更强。
4. **`task_count` 全 0**：不能评价多 agent 协作。
5. **仅 hy3**：结论不外推到其他模型。
6. **样本小**：40 题 × 2 重复，CI 约 ±11–15pp，不足以区分 <10pp 差异；显著性检验需 ≥100 题。
7. **补跑效应大**：+11.3pp / +22.5pp，补跑前数字不能当能力。
8. **v2 未采集**：partial、轨迹、改测试两口径（下一步）。

## 6. 下一步（按优先级）

1. **TLS 预置 installer**：`astral.sh` 间歇 `curl exit=35` 是最大环境噪声源；把 uv installer 预置进评测镜像或换国内镜像，从根上消除。
2. **partial / 轨迹采集**：v2 只有 pass/fail；补 partial credit、轨迹与「改测试」两口径（检测率 / patch 含测试）。
3. **扩样 100 题**：从 519 可评测题分层抽 100，CI 收窄到约 ±9pp，才谈显著性。
4. **多 agent 场景**：SWE-bench Pro 本批不触发协作，改用 `evals/scenarios/collaboration-autonomous.jsonl`。
5. **compact vhdx**：回收约 53GB 未释放空间（`diskpart` → `select vdisk` → `compact vdisk`），跑批前保留 ≥40GB。
6. **第二模型**：按 [MULTI-MODEL-PLAN.md](MULTI-MODEL-PLAN.md) 执行，先 pilot 再全矩阵。

## 7. 证据与文档

| 内容 | 位置 |
|---|---|
| v2 逐 trial 明细 | `C:\sb\hard\v2-325\FINAL-SUMMARY.json`（含 task/task_id/repo/repeat）|
| v2 统计 | `C:\sb\hard\v2-325\logs\final\`（final-summary.txt / final-stats.txt / stats-four.txt / final-classify.json）|
| v2 报告 | [FORMAL-RESULTS-20261102-v2.md](FORMAL-RESULTS-20261102-v2.md) |
| 现行协议 | [PROTOCOL-V2.md](PROTOCOL-V2.md) |
| 踩坑记录 | [LESSONS-20261102-v2.md](LESSONS-20261102-v2.md) |
| 交接 | [HANDOFF.md](HANDOFF.md) |
| 历史/作废 | [docs/archive/](archive/README.md) |
