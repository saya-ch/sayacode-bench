# scripts/ 工具索引

本目录混着**现行跑批工具**与**历史一次性工具**。历史工具之所以还在根目录、没有移进 `archive/`，是因为 `src/`、`tests/` 或 `.github/workflows/` 以模块导入或文件 SHA256 身份绑定了它们——**移动会直接破坏测试与身份校验**。归档前请先确认引用。

## 现行（v2 开发期使用）

| 脚本 | 用途 |
|---|---|
| `run_formal_240.py` | 阶段1：40 题 × 2 重复 × 3 agent 解题（`--skip-verifier`，默认读 `studies/sample-40-final.json`）|
| `verify_patches.py` | 阶段2：PatchReplay 统一验证（`--agents`、`--concurrency`）|
| `final_summary.py` | 汇总逐 trial 明细、按统一口径出记分卡 |
| `analyze_trials.py` | 指标记分卡：pass@1 / partial / cost-per-success / reward hacking / bloat / 方差 |
| `compare_trials.py` | 配对统计（McNemar + risk difference）|
| `profile_summary.py` | 跑前配置汇报（模型 / 上下文 / max_output / 摘要触发点）——**硬性** |
| `annotate_served.py` | 从 Magpie usage 关联每个 trial 的实际 `served` / `provider` |
| `run_holdout.py` | holdout 跑批（默认 `studies/primary-selection-v1.json`，可用 `--sample-file`）|
| `run_regression.py` | L2 回归集（`studies/regression-set.json`）|
| `gold_patch_check.py` | gold patch 筛坏题（默认读 `studies/sample-40.json`）|

## 历史工具（保留原位：被代码/测试/工作流绑定）

| 脚本 | 绑定方 | 说明 |
|---|---|---|
| `analyze_sensitivity.py` | `src/sayacode_bench/artifacts.py`、`tests/test_sensitivity.py` | 正式协议的离线敏感性分析 CLI；当前无正式试验可分析 |
| `qualify_fixtures.py` | `tests/test_fixture_qualification.py`、`docs/fixture-gates.md` | 三加一环境资格门禁（开发期不用）|
| `diagnose_fixtures.py` | `tests/test_fixture_diagnostic.py`、`.github/workflows/fixture-diagnostic.yml` | 固定八次诊断 |
| `diagnose_wheel.py` | `tests/test_diagnose_wheel.py`、`calibrate_cloud.py` | wheel 逐字节比较 |
| `calibrate_cloud.py` | `tests/test_cloud_calibration.py`、`.github/workflows/cloud-calibration.yml` | 两题云端校准 |
| `qualify_cloud.py` | `tests/test_cloud_qualification.py`、`tests/test_terminal_supplement.py` | 公开资格链 |
| `generate_sharded_workflow.py` | `tests/test_sharded_workflow.py`、`analyze_sensitivity.py` | 分片 DAG 生成 |
| `study_resume.py` | `tests/test_phase_resume.py`、`generate_sharded_workflow.py` | 物理批次恢复 helper |
| `prepare_primary_study.py` | `tests/test_prepare_primary_study.py`、`.github/workflows/prepare-primary-study.yml` | 主开发准备 |
| `prepare_final_study.py` | `tests/test_prepare_final_study.py`、`.github/workflows/prepare-final-study.yml` | 最终验收准备 |
| `prepare_cloud_runner.py` | `src/sayacode_bench/installation.py`、8 个 workflow | 云端 runner 预检 |
| `preflight_installations.py`、`preflight_installation_storage.py` | `src/sayacode_bench/installation.py` | 安装预检 |
| `regrade_calibration_patches.py` | `tests/test_calibration_regrade.py` | 校准补丁重判 |
| `reproduce_hypothesis_seed.py` | `tests/test_hypothesis_seed.py`、`.github/workflows/hypothesis-seed-diagnostic.yml` | 固定种子对照 |
| `verify_calibration_stability.py` | `tests/test_calibration_stability.py` | 校准稳定性复核 |
| `build_sqlite_vec_musl.py` | `tests/test_build_sqlite_vec_musl.py` | musl wheel 构建（早期探针）|

> 这些脚本**不是现行流程**。引用它们前先读对应归档文档，并确认 `tests/` 仍在用。

## 已归档

| 脚本 | 归档原因 |
|---|---|
| `archive/summarize_formal.py` | v1 的一次性汇总脚本，已被 `final_summary.py` 取代；无代码/测试依赖，安全归档 |

## 使用约定

- 跑批前必须 `docker network prune -f`，并发 ≤ 6，验证器限流 1。
- 任何汇总必须统一分母（缺 trial 写 79/80，不换分母）；改测试分「检测率」与「patch 含测试」两列。
- 复杂 `python -c` 写成 .py 文件再执行（PowerShell 引号地狱）。
