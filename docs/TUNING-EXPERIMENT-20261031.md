# TUNING EXPERIMENT：SAYACODE 提示词调优（v2-tuned）

> 目的：基于 baseline（68.8% pass@1）的失败证据，用**提示词约束**提升 SAYACODE 表现。
> 不改产品代码，只改 variant 的 `instruction_append`，成本低、可回滚。

## 1. Baseline 的失败证据（来自 80 trial）

| 失败类型 | 数量 | 证据 |
|---|---|---|
| 空 patch（agent 放弃）| 9 | `model.patch` 0 字节，无异常 |
| 有补丁但失败 | 6 | 含 `ansible-fb144c` **11/12 测试通过**（差 1 个）|
| 改测试 + 有补丁 | 10 | 被验证器恢复（`restored-test-files.json`）|
| **改测试总率** | **49%（36/80）** | 修改 `test/`、`*-test.tsx`、`*.snap` |
| 补丁异常膨胀 | 1 | `flipt-9d25c18` patch **185KB** |
| bloat 中位 | 0.73× | 补丁普遍偏小（改不完整）|

## 2. v2-tuned 的 5 条规则

文件：`C:\sb\hard\variant-v2-tuned.json`

| # | 规则 | 针对证据 |
|---|---|---|
| 1 | 禁止修改测试文件（`test/`、`tests/`、`__tests__/`、`spec/`、`*-test.*`、`*_test.*`、`*.snap`）| 49% 改测试率 |
| 2 | 改完必须运行失败的测试确认通过，否则继续修 | `ansible-fb144c` 11/12 |
| 3 | 只改源码，不碰 `node_modules/`、`vendor/`、`dist/`、`build/`、锁文件 | 185KB 膨胀补丁 |
| 4 | 必须产出补丁（部分解决也要写源码，空补丁零分）| 9 个空 patch |
| 5 | 最小 diff，不重写仓库、不格式化无关文件 | bloat 0.73× |

## 3. A/B 设计

| 项 | baseline | v2-tuned |
|---|---|---|
| variant | `baseline.json`（instruction_append 空）| `variant-v2-tuned.json` |
| 题集 | `sample-40-final.json`（40 题）| 同 |
| 重复 | 2 | 2 |
| 结果目录 | `formal-240/sayacode` | `formal-tuned/sayacode` |
| 环境变量 | 无 | `SAYA_VARIANT=...variant-v2-tuned.json` |

**对比方式**：配对（同题），指标 = pass@1、改测试率、空 patch 数、partial。

## 4. 执行记录

- 启动：2026-10-31 14:36（续跑），6 并发，阶段1 跳过验证器
- 阶段2 统一验证：待阶段1 完成后执行 `verify_patches.py`

## 5. 预期与判据

**成功判据**（三条同时满足才算调优有效）：
1. pass@1 提升 ≥ 10pp（相对 baseline 68.8%）
2. 改测试率从 49% 降到 <10%
3. 空 patch 从 9 降到 ≤3

**若只有 pass@1 升、改测试率没降** → 说明规则未被遵守，需要更强约束（如工具层禁止）。
