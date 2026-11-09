# 验证行为不是瓶颈：模型很努力地在自证，但证错了方向（2026-11-09）

> 起因：`bench-method` 的行级分析发现 33 条失败里 12 条是「编译/收集失败」，
> 建议「用 `go build` 或 `pytest --collect-only` 在提交前拦住」。
> 本文验证这个建议是否成立。**结论：不成立。**

---

## 1. 先确认 bench-method 的分类是对的

它把 33 条失败分成：

| 类型 | 数量 | 占比 |
|---|---:|---:|
| 空 patch | 9 | 27% |
| 编译/收集失败 | 12 | 36% |
| f2p 断言失败 | 11 | 33% |
| 仅 p2p 回归 | 1 | 3% |

这一分类比我此前做的「改错 10 / 空 patch 4」细致得多——我漏掉了「编译失败」
这一整类，因为它看起来像「改错」。

---

## 2. 但「强制跑 build」不能解决问题

`events.jsonl` 里有 `tool_input`，可以还原模型实际执行过的命令。
解析 79 个 trial 的命令后发现：

| 组 | 跑过 build/collect 类命令 | 跑过 test 类命令 | 命令数中位 |
|---|---:|---:|---:|
| 通过（47 个）| 33/47 = **70%** | 35/47 = 74% | 16 |
| 失败（32 个）| 22/32 = **69%** | 23/32 = 72% | **26** |

**两组跑 build 的比例完全一样（70% vs 69%），失败的 trial 命令数还更多（26 vs 16）。**

如果「不跑 build」是失败原因，这里应该出现显著差异。没有。

---

## 3. 逐案看：模型确实在验证，但验证的点不对

以 `ansible-415e08`（失败，30 次命令，既跑了 build 也跑了 test）为例，
还原它的命令序列：

```
1. grep "module_utils.common" basic.py                  exit 0
2. python -c "from ...locale import get_best_parsable_locale..."  exit 0
3. python <<EOF  # 检查 ansible.cli 可导入                 exit 1  Traceback
4. python <<EOF  # 检查 basic 能否解析 locale import        exit 0  "basic parses with locale import present"
5. grep "def recursive_finder" module_common.py             exit 0
6. python <<EOF  # 检查 basic.py AST 里有 locale import      exit 0  "locale import present in basic.py AST"
7. grep "def recursive_finder|_find_module_utils" ...       exit 0
8. python <<EOF  # 检查 zipfile payload 里有 locale.py       exit 0  "common/locale entries in payload: [...] OK"
```

**它跑了 8 个自定义验证脚本，全部围绕「locale import 有没有被正确打进 payload」，
并且每次都自己确认 OK。** 但最终测试仍然失败。

这说明问题不在「没验证」，而在**它验证的是自己认为重要的点，不是测试实际要求的点**。

---

## 4. 合并其他证据，同一个结论

| 证据 | 数字 |
|---|---|
| 通过的 trial 改完后跑过命令 | 26/26 = 100% |
| 失败的 trial 改完后跑过命令 | 11/14 = 79% |
| 通过的 trial 跑过 build | 70% |
| 失败的 trial 跑过 build | 69% |
| 失败 trial 的命令数中位 vs 通过 | 26 vs 16 |

**模型在失败的 trial 里往往更努力（命令更多），但仍失败。**

这解释了为什么三轮干预全部无效：

| 轮次 | 干预 | 行为层生效？ | 通过率 |
|---|---|---|---|
| 1 | ExploreBudgetMiddleware（催动手）| 是，空 patch 归零 | 不动 |
| 2 | 系统提示精简 63% | 是，调用次数变多 | 扩样本后归零 |
| 3 | 影响面检查清单 | 是，覆盖率 +6.7pp | +2.5pp，p=1.0 |
| 4 | （本次验证）强制 build | **不需要**——本来就在跑 | — |

**每一次都在改变「模型做什么动作」，但动作变了，正确率没变。**

---

## 5. 结论

**失败的主因不是行为缺失，是理解偏差。** 具体表现：

| 案例 | 模型理解 | 测试要求 |
|---|---|---|
| qutebrowser-52708 | 自定义 `__init__` 不接受 `valid_values` | 测试显式调用 `klass(valid_values=...)` |
| flipt-8bd3604 | 输出 `{"level": "DEBUG"}` | 期望 `{"level": 10}`（slog 数值） |
| navidrome-0130c / vuls-4b680b | 没写 `getImageFiles` / `parsePkgInfo` | 测试直接调用这两个方法 |
| ansible-415e08 | 反复验证 locale 是否进 payload | 要求的是别的行为 |

这些都不是「多做一步检查」能修好的——**模型必须更准确地读懂需求**。

而「更准确地读懂需求」恰好是提示词层面最难撬动的部分。三轮实验已经证明，
把要求写得更清楚（v2 的目标陈述、影响面清单）不改变结果。

---

## 6. 所以该做什么

**建议停止在「通过率」上继续投入。** 理由：

1. 四轮干预全部在行为层有效、在正确率上无效
2. 失败集中在「理解偏差」，这是当前模型能力边界
3. 继续投入的最可能结果是第五次「行为变了、分数不变」

**转向已经证明有收益的地方：成本侧。**

已有一个成功先例：TodoList 提示压缩 82%（6,502 → 1,148 字符），
结果是墙钟 -40%、input tokens -15.6%、调用次数 -30%，通过率持平。
成本是连续量，抗噪声，小改动能穿透。

---

## 7. 数据来源

| 项 | 路径 |
|---|---|
| 失败分类（33 条，行级） | `docs/ANALYSIS-LINE-LEVEL-DIFF.md`（bench-method）|
| 命令还原脚本 | `C:\sb\tmp\check_build_commands.py` |
| 覆盖率复核 | `docs/AUDIT-RECOMPUTE.md`（sandbox-amadeus）|
| 原始命令记录 | `C:\sb\hard\ab-ctx\{impact-350,v2v-main}\sayacode\jobs\*\*\agent\sayacode\events.jsonl` |
