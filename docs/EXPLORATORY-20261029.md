# 2026-10 探索性调优记录（非正式成绩）

日期：2026-10-29。状态：**开发期探索诊断，不构成正式成绩，不改变 protocol 冻结清单，不进入正式分母。**

本文件记录在 [protocol](protocol.md)/[WORK_PLAN](WORK_PLAN.md) 正式流程之外、为准备候选而做的探索性运行，用于提炼假设与工具，不是公开子集分数。

## 1. 数据与边界

- 数据集：SWE-bench Pro V2，本地 `primary-selection-v1` 的 holdout 24 题；其中 musl 镜像 4 题（teleport×2、protonmail×2）无法安装产品，标为结构性不可评测。
- 模型：本地 Magpie 网关 `auto/deepseek-v4.1-flash`（DeepSeek-V4.1-Flash）。
- 判分：官方 Harbor 验证器 reward。
- **边界**：单次为主，样本小、方差大；**任何数字不得作为正式成绩引用**。

## 2. 观察到的结果（探索，非成绩）

- 可评测 20 题，基线通过 14（探索性点估计，95%CI 半宽约 ±10pp，样本不足以对外声明）。
- 6 个失败探索性分类：**5/5 原始失败与「改既有测试」相关**（element×2、navidrome、qutebrowser、tutao）。

## 3. 三个机制性发现（可复现、写进工具）

1. **token 增长主要来自历史上下文**：工具输出仅占输入约 5%，其余是每轮重复携带的历史。压缩提示词（-30%）对 token 无感。
2. **测试保护有效但非万能**：`restore_existing_test_files` 在 tutao 真实触发一次并正确恢复既有测试，但该题仍失败（源码修复错误）；`strip_new_test_files` 处理「新建测试绕过」。
3. **同题方差极大**：同一配置同题可一过一败；token 在 0.9M–3.7M 间波动。→ 开发期必须用 pass^k / 重复，而非单次 pass@1。

## 4. 对正式流程的建议（交 protocol 决策，不在本文件生效）

- 主指标补充 **partial credit** 与 **pass^k 一致率**（0/1 会掩盖「差 1 个测试」）。
- 结果指标必须与**过程护栏**（改既有测试、回归破坏、空转）同报，防止指标被刷。
- 用**配对 McNemar** 做候选比较，减少所需样本量。

## 5. 工具（本仓库 scripts/）

- `scripts/analyze_trials.py`：从工件算 partial credit、过程指标、pass@1+CI。
- `scripts/compare_trials.py`：配对 McNemar + risk difference。
- `scripts/run_regression.py` + `studies/regression-set.json`：L2 快速回归。

全部只读已完成工件，不调用模型，不建立新评分器。
