# studies/ 配置索引

本目录保存**机器可读的配置、题集、协议与价格快照**。现行开发期（v2 重建）实际使用的只有下面标「现行」的几项；其余保留是因为被 `src/` 或 `scripts/` 以文件身份绑定，**不可移动**。

## 现行（v2 开发期使用）

| 文件 | 用途 | 状态 |
|---|---|---|
| `sample-40-final.json` | **开发迭代集 40 题**（按仓库分层，seed 可复现）| 现行；gold-check 为 36 good / 1 bad / 3 null |
| `sensitivity-protocol-v12.json` | 现行统计协议（任务块主分析、仓库簇敏感性、10,000 次抽样、seed）| 现行；被 `src/sayacode_bench/study.py` 绑定 |
| `execution-protocol-v13.json` | 现行执行合同（restart-v2 轮次），绑定 v12 统计协议 SHA256 | 现行；被 `src/sayacode_bench/study.py` 绑定 |
| `regression-set.json` | L2 快速回归集（历史失败题 + 稳定通过题）| 现行（`scripts/run_regression.py`）|
| `sample-40.json` | 初版 40 题清单（final 的前身）| 参考；`scripts/gold_patch_check.py` 默认读它 |
| `design-20261022-v1.json` | 固定设计（样本规模、seed、排除规则）| 参考；`protocol.md` 引用 |
| `baseline.json` / `diagnostic.json` / `focused.json` | 三个候选配置（只改追加执行指导）| **未验证**，当前不做 A/B |

## 保留但非现行（被代码绑定，不可移动）

| 文件 | 为何保留 |
|---|---|
| `primary-selection-v1.json` | `scripts/run_holdout.py` 的默认 holdout 清单、`scripts/qualify_cloud.py` 的 `INITIAL_SELECTION`；移动会破坏现行工具 |
| `terminal-selection-v1.json` | `scripts/qualify_cloud.py` 与 `tests/test_terminal_supplement.py` 的身份绑定（Terminal-Bench 已弃用，文件仍被校验）|
| `terminal-selection-v2.json` | `scripts/analyze_sensitivity.py` 的 `terminal_selection_sha256` 身份绑定 |
| `calibration.json` / `calibration-run-v1.json` / `calibration-ansible-v3.json` | 资源校准题与校准运行记录；校准题不进正式 40 题 |
| `prices/*.json` | 历史价格快照（2026-10-22/23 的 SiliconFlow 价格），供历史费用核对；现行开发期成本另记 |

## 已归档（历史协议修订）

`sensitivity-protocol-v2` … `sensitivity-protocol-v11` 已移到 [archive/](archive/)，逐份说明见 [archive/README](archive/README.md)。它们是正式模型运行之前的协议修订历史，**没有对应的正式效果试验**，不能从中挑选更有利的结果。

## 冻结与选择原则

- 三个初始配置使用相同模型、图、工具、摘要、权限和团队能力，只改变追加的执行指导；它们是**假设性候选，不是已证明有效的调优**。
- 真实开发错误、候选比较和选择结果必须另行保存；不得使用最终验收结果倒推候选指令。
- 追加指导仍走现有生产应用，官方原始题面不改写；最终候选通过 `lock-candidate` 签收。
- 基线胜出时最终使用单组 validation，不构造基线与自身的伪对照。
- 资格检查使用的源码版本与未来模型运行的源码版本分别记录；冻结模型阶段时不能覆盖这些历史字段。
- 当前开发期重建**不使用** `qualify_fixtures` 资格链与分片流程，它们保留给将来的正式研究。
