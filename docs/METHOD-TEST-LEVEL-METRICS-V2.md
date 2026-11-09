# 测试级指标：方法、我自己的 bug、以及被排除的样本（2026-11-09）

> 主线的「评价」部分。建立 F2P/P2P 测试级指标 → 复核五轮干预 → 顺带发现并修正
> **我自己**的一个匹配 bug。结论：五轮干预确实无效，测试级指标也证实了。

---

## 1. 为什么需要测试级指标

此前所有实验主指标都是整体通过率（0/1）。一个题 15 个测试过了 14 个，
和过了 0 个记同样的 0 分。这掩盖了细粒度差异。

SWE-bench 任务定义里本来就有两个列表（`tests/config.json`）：

| 列表 | 含义 | 用途 |
|---|---|---|
| `fail_to_pass`（F2P）| 原本失败、修好后应通过 | 衡量「有没有修好」|
| `pass_to_pass`（P2P）| 原本通过、不应被破坏 | 衡量「有没有改坏」|

而测试级结果一直在，只是没人用：

```
<实验>/sayacode/verify/jobs/verify-<job>-r<N>/<inner>/verifier/output.json
{"tests": [{"name": "...", "status": "PASSED|FAILED|..."}]}
```

来源：任务的 `tests/test.sh` 第 156-157 行本来就会
`cp /tmp/output.json /logs/verifier/output.json`。

覆盖（实测）：impact-350 36 个、v2v-main 35 个、run-todo-compact 10 个。

---

## 2. 我自己的 bug：verify job 匹配没带 repeat

### 症状

第一版脚本算出「F2P 全过但 reward=0」的有 9 个 trial，看起来像评测误判。
其中 `ansible-a02e2 r1` 显示 `F2P 24/24 全过、P2P 39/39 全保持，却 reward=0`。

### 根因

`find_verify` 只用「5 位 commit 前缀」做子串匹配，**没带 repeat**：

```python
# 错误写法
for vk, tests in verify.items():
    if key in vk:          # vk 是完整 key，不含 repeat 区分
        return tests       # r1 的 trial 会拿到 r2 的结果
```

而 verify 目录里同一个题有 `verify-...-r1` 和 `verify-...-r2` 两套，
子串匹配会命中先遍历到的那一个。

### 修正

行距改为按 `(key, repeat)` 双键：

```python
m = re.search(r"-r(\d+)$", body)      # 从 job 名提取 repeat
out[(key, repeat)] = tests            # 双键

def find_verify(verify, task_id, repeat):
    for (vk, rep), tests in verify.items():
        if rep == repeat and key in vk:
            return tests
```

### 修正前后的数字对比

| | 修正前（错） | 修正后（对） |
|---|---:|---:|
| F2P 配对 impact | 67.45% | 59.98% |
| F2P 配对 control | 65.24% | 52.62% |
| **Δ** | **+2.21pp** | **+7.36pp** |

修正后 Δ 反而变大了——但这还不是最终数，因为下面还有一层排除。

---

## 3. 被排除的样本：parser 空输出

### 现象

11 个 trial 的 `output.json` 是空文件（0 个测试），且**它们的 reward 全是 0**：

| 组 | parser 正常 | parser 空 |
|---|---|---|
| impact | 24/36 = 66.7% 通过 | **0/4 = 0%** |
| control | 23/33 = 69.7% 通过 | **0/7 = 0%** |

### 一开始以为是评测缺陷

`output.json` 空 + reward=0，看起来像「测试跑对了但 parser 没解析出来，导致误判」。
但原始日志推翻了这一点。

### 真相：测试根本没跑起来，是模型改坏了代码

`ansible-a02e2 r1` 的 `test-stdout.txt` 结尾：

```
Required tests: 63
Passed tests: 0
Required tests that passed: 0
RESULT: FAILED
```

`test-stdout.txt` 更早的部分：

```
=========================== short test summary info ===========================
ERROR test/units/galaxy/test_collection_install.py - ValueError: error parsing...
ERROR gw0
ERROR gw1
ERROR gw3
============================== 4 errors in 4.45s ===============================
```

**pytest 启动了**（有 xdist workers `gw0/gw1/gw3`），但测试文件导入时抛
`ValueError: error parsing` —— 是模型改动引入的解析错误。

**所以 parser 空输出 = 测试无法收集 = 模型确实做错了，判负合理。**
这 11 个样本从测试级统计里排除，但不算误判。

---

## 4. 最终结果（严格版）

只统计「两边都解析成功」的 33 对配对：

| 指标 | impact(3.5.0) | control(3.3.0) | 差值 |
|---|---:|---:|---:|
| **F2P 平均通过率** | **63.61%** | **63.78%** | **-0.17pp** |
| F2P 逐对 | 提升 3 / 下降 3 / 持平 27 | — | — |
| 整体通过（同一批）| 22/33 | 23/33 | -1 |

差异明细（只有 6 个题有变化，且方向互相抵消）：

| 题目 | control → impact | 方向 |
|---|---|---|
| ansible-7e1a3 r1 | F2P 100% → 0% | ↓ |
| ansible-7e1a3 r2 | F2P 0% → 80% | ↑ |
| flipt-8bd36 r2 | 71.4% → 85.7% | ↑ |
| openlibrary-03095 r1 | F2P 100% → 50% | ↓ |
| qutebrowser-3d01c r2 | 0% → 100% | ↑ |
| qutebrowser-52708 r1 | 100% → 50% | ↓ |

**同一题的两个 repeat 出现相反方向**（ansible-7e1a3：r1 变差、r2 变好），
这是随机波动的典型特征。

### 结论

**换成测试级指标，Δ = -0.17pp。和整体通过率（+2.5pp，p=1.0）一样，没有差异。**

这坐实了：五轮干预不是「被粗指标掩盖」，是真没效果。

---

## 5. 这次评价改进的真实价值

| 项 | 之前 | 现在 |
|---|---|---|
| 指标粒度 | 整体 0/1 | F2P / P2P 测试级 |
| 敏感度 | 15 个过 14 个 = 0 分 | 93.3% |
| 能否诊断「改坏」| 不能 | 能（P2P，但 JS 项目有缺陷）|
| 能否区分「测试没跑起来」和「跑了没过」| 不能 | 能（看 output.json 是否为空 + stderr）|

**知道的东西变多了，但结论没变。** 这本身是有价值的信息：说明「找不到改进方向」
不是测量精度问题。

---

## 6. 遗留缺陷

| 缺陷 | 影响 | 状态 |
|---|---|---|
| P2P 在 JS 项目上不可用 | element-web 的 `pass_to_pass` 44 个测试，`output.json` 里 0 个匹配得上（命名格式不同）| 未修 |
| F2P 在多数题上饱和 | 中位 100%，对更精细的改进仍不敏感 | 无解（题目本身 F2P 少）|
| 11/80 个 trial 测试无法收集 | 只能判负，无法知道是「改错了」还是「改出了语法错误」| 可从 stderr 逐个人工判断 |

---

## 7. 产物

| 项 | 路径 |
|---|---|
| 测试级指标（含 repeat 修正）| `C:\sb\tmp\test_level_metrics.py` |
| 严格版（排除 parser 空）| `C:\sb\tmp\test_level_strict.py` |
| parser 影响分析 | `C:\sb\tmp\parser_impact.py` |
| 矛盾追查 | `C:\sb\tmp\why_failed.py` |
| 覆盖检查 | `C:\sb\tmp\check_verify_coverage.py` |
