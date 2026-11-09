# 评价方法改进：建立 F2P/P2P 测试级指标（2026-11-09）

> 主线是「评价与调优」。此前所有实验的主指标都是**整体通过率（0/1）**，
> 这是二值量，小改动穿不透噪声。本文把评价从二值升级到测试级，
> 并用它复核了此前 5 轮干预的结论。

---

## 1. 此前评价的缺陷

| 问题 | 后果 |
|---|---|
| 只保留 `reward: 0.0/1.0` | 一个题 15 个测试里过了 14 个，和过了 0 个同样记 0 分 |
| 验证过程零日志 | `trial.log` 只有 1 行 "Collecting main service artifacts" |
| 无法区分「没修好」和「修好了但改坏别的」 | 都表现为 reward=0 |

---

## 2. 测试级数据其实一直在，只是没被用

任务定义里本来就有两个列表（`tests/config.json`）：

- **FAIL_TO_PASS（F2P）**：原本失败、修好后应该通过的测试 → 衡量「有没有修好」
- **PASS_TO_PASS（P2P）**：原本通过、不应被破坏的测试 → 衡量「有没有改坏」

而 `tests/test.sh` 第 156-157 行本来就把解析结果复制到日志目录：

```bash
# Copy output.json and raw logs to /logs/verifier for debugging
cp /tmp/output.json /logs/verifier/output.json 2>/dev/null || true
```

这个文件被 Harbor 保留在：

```
<实验>/sayacode/verify/jobs/verify-<job>/<inner>/verifier/output.json
```

结构（由任务的 `tests/parser.py` 生成）：

```json
{"tests": [{"name": "...", "status": "PASSED|FAILED|SKIPPED|ERROR"}]}
```

**覆盖情况（实测）**：

| 实验 | verify job | output.json | 累计测试条目 |
|---|---:|---:|---:|
| impact-350 | 36 | 36 | 6,146 |
| v2v-main | 35 | 35 | 3,934 |
| run-todo-compact | 10 | 10 | 2,906 |

---

## 3. 用测试级指标复核「影响面清单」实验

数据：40 对配对（20 题 × 2 repeat），3.5.0 vs 3.3.0。

| 指标 | impact(3.5.0) | control(3.3.0) | 差值 |
|---|---:|---:|---:|
| **F2P 平均通过率** | **79.36%** | 76.75% | +2.61pp |
| **F2P 配对（40 对）** | **67.45%** | **65.24%** | **+2.21pp** |
| F2P 全通过 | 20/40 | 22/40 | **-2** |
| P2P 保持率 | 100% | 100% | 0 |
| 整体 reward=1 | 24/40 | 23/40 | +1 |

**F2P 逐对：提升 4 / 下降 2 / 持平 34。**

明细（只有 3 个题有差异）：

| 题目 | control → impact | 方向 |
|---|---|---|
| openlibrary-03095（两个 repeat）| F2P 0% → 50% | ↑ |
| flipt-8bd36（两个 repeat）| F2P 71.4% → 85.7% | ↑ |
| ansible-7e1a3（两个 repeat）| F2P 100% → 80% | ↓ |

### 结论

**换成敏感得多的测试级指标，结论完全一样**（+2.2pp vs 整体 +2.5pp，p=1.0）。

这坐实了一件事：**五轮干预不是「效果被粗指标掩盖」，是真的没有效果。**

---

## 4. 顺带发现的一个评价缺陷

P2P 指标在部分项目上**不可信**：element-web 的 `pass_to_pass` 列了 44 个测试，
但 `output.json` 里一个都匹配不上（0/44）——JS 项目的测试命名格式和
Python 项目不同，`parser.py` 输出的名字和 `config.json` 里写的名字对不上。

处理方式：P2P 只在「能匹配上 ≥80%」时才计入统计。
本轮 40 个 trial 里只有 **10 个**满足条件，这 10 个的 P2P 保持率都是 100%。

**这是个待修的评价缺陷**：JS 类项目的 P2P 目前无法评估。

---

## 5. 这次改进的价值

| 项 | 之前 | 现在 |
|---|---|---|
| 指标粒度 | 整体 0/1 | F2P / P2P 测试级 |
| 敏感度 | 15 个测试过 14 个 = 0 分 | 93.3% |
| 能否诊断「改坏」 | 不能 | 能（P2P） |
| 覆盖 | 全部实验 | 已有 45 个 verify job 可回溯 |

**局限**：
- F2P 在多数题上已经饱和（中位 100%），对「更精细的改进」仍不敏感
- P2P 在 JS 项目上不可用（见 §4）
- 这是诊断指标，不能替代整体通过率作为对外口径

---

## 6. 产物

| 项 | 路径 |
|---|---|
| 测试级指标脚本 | `C:\sb\tmp\test_level_metrics.py` |
| P2P 匹配调试 | `C:\sb\tmp\debug_p2p.py` |
| 覆盖检查 | `C:\sb\tmp\check_verify_coverage.py` |
| 测试级原始数据 | `<实验>/sayacode/verify/jobs/*/*/verifier/output.json` |
| 任务定义 | `C:\sb\tmp\hard\cache\swe-bench-pro-v2-*\v2\tasks\<id>\tests\config.json` |
