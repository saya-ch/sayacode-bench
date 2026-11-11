# pro-v2 四 agent 对比：最终结果（2026-11-11 完成）

> 40 题 × 1 repeat × 4 agent = **160 trial 全部完成**。
> 题集从未参与过任何调优，四次重复已剔除，**40 个独立配对**。

---

## 1. 最终数字

| agent | trial | 通过 | 原始通过率 | 基础设施失败 | 超时 | 模型失败 | 有效分母 | **有效通过率** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **claude-code** | 40 | 30 | **75.0%** | 4 | 0 | 6 | 36 | **83.3%** |
| **mini-swe** | 40 | 28 | 70.0% | 6 | 0 | 6 | 34 | **82.4%** |
| **opencode** | 40 | 28 | 70.0% | 3 | 0 | 9 | 37 | **75.7%** |
| **sayacode 3.3.0** | 40 | 22 | **55.0%** | **11** | 1 | 6 | 29 | **75.9%** |

### 配对检验（40 个独立配对，McNemar 精确检验）

| 对比 | A 独赢 | B 独赢 | Δ | p |
|---|---:|---:|---:|---:|
| **sayacode vs claude-code** | **3** | **11** | **-20.0pp** | **0.0574** |
| sayacode vs mini-swe | 6 | 12 | -15.0pp | 0.2379 |
| sayacode vs opencode | 3 | 9 | -15.0pp | 0.1460 |
| mini-swe vs claude-code | 4 | 6 | -5.0pp | 0.7539 |
| mini-swe vs opencode | 7 | 7 | 0.0pp | 1.0000 |
| claude-code vs opencode | 6 | 5 | +5.0pp | 0.7744 |

**多重比较**：6 个对比，Bonferroni 阈值 0.05/6 = 0.0083。
**最小 p=0.0574 未过校正阈值，因此不能宣布任何两组存在统计显著差异。**

### F2P 测试级（比整体 0/1 更细）

| agent | 可算题数 | F2P 均值 |
|---|---:|---:|
| claude-code | 34 | **86.83%** |
| opencode | 36 | 84.35% |
| mini-swe | 34 | 83.82% |
| sayacode | 31 | **81.34%** |

排序与整体一致：sayacode 最低，claude-code 最高。

---

## 2. 三个可靠结论

### 2.1 sayacode 的基础设施失败率是别人的 2-3 倍

| agent | 基础设施失败 | 占比 |
|---|---:|---:|
| **sayacode** | **11** | **27.5%** |
| mini-swe | 6 | 15.0% |
| claude-code | 4 | 10.0% |
| opencode | 3 | 7.5% |

根因明确：**只有 sayacode 需要 `pip install` 完整产品 wheel**，其他三个 agent 用内置运行时。
安装链路每一环都可能失败（本轮修了 4 个独立缺陷，见 §4）。

**原始通过率 55.0% vs 有效通过率 75.9%，差 20.9pp 全部来自安装失败。**

### 2.2 有效通过率上 sayacode 与 opencode 持平

- sayacode 75.9%
- opencode 75.7%
- 差 0.2pp，配对 3-9 但 p=0.1460

**落后 claude-code 7.4pp、mini-swe 6.5pp，但均不显著。**

### 2.3 接近显著的那一组

sayacode vs claude-code：40 题里 **3 胜 11 负**，p=0.0574。
这是整个项目（含此前所有实验）**唯一接近 0.05 的结果**。

但按多重比较校正，仍不能宣布显著。要坐实这个差距需要更多题量：
- 40 题检出 20pp 需要 p<0.0083，当前 p=0.0574
- 若真实差距是 20pp，约需 **60-70 题** 才能过校正阈值
- 若真实差距是 10pp，约需 **150+ 题**

---

## 3. 与历史数据的对照

此前 `v2-325` 批次（40 题 × 2 repeat，伪重复）曾得出：

| agent | 历史 planned | 本次有效通过率 | 差异 |
|---|---:|---:|---:|
| mini-swe | 85.0% | 82.4% | -2.6pp |
| sayacode 3.2.5 | 78.8% | 75.9%（3.3.0） | -2.9pp |
| claude-code | 77.5% | **83.3%** | **+5.8pp** |
| opencode | 75.0% | 75.7% | +0.7pp |

**claude-code 提升了 5.8pp**——它是唯一在两次批次间变化较大的。
可能是模型/端点变化，也可能是伪重复 vs 独立配对的统计效应。
**不做因果解释，只记录事实。**

历史结论「mini-swe 85% 最高、sayacode 78.8% 第二」在独立配对下**不再成立**：
- mini-swe 仍是第一梯队（82.4%），但 claude-code（83.3%）已追平甚至略高
- sayacode 掉到最后（75.9%）

---

## 4. 本轮修掉的 5 个缺陷

| commit | 缺陷 | 影响 |
|---|---|---|
| `a37233a` | 题集 task_id 带题库前缀时路径/job名不剥离 | 多题库题集完全跑不起来 |
| `1356faf` | `require_inputs` 从不调用；异常只记类型名 | 缺输入时跑到一半才炸，无法诊断 |
| `7927546` | pyc 损坏 + 异常详情要落旁路文件 | 假失败，被记 reward=0 |
| `0ecf99f` | `uv venv` 没 `--clear` | 残留 venv 时整链失败 |
| `0ca7eec` | pip3 装不上 uv 时无回退 | pip 21 的镜像永远装不上 |

**五个都是「安装链某环节失败后没有正确回退或报错」。**
共同后果：sayacode 白丢 trial、被记 reward=0，系统性压低其分数。

---

## 5. 实验过程中的环境事故

| 时间 | 事件 | 影响 |
|---|---|---|
| 20:01 | 外层 ps1 静默死亡 | 第 3 批中断，改用 takeover 脚本 |
| 20:58 | 同上 | 第 4 批重启 |
| 22:17 | Docker daemon 500 崩溃 | 第 4 批中断 |
| 09:00 | Docker 反复 500 | 第 5 批三次失败 |
| 10:22 | vhdx 从 55GB 涨回 108.7GB，磁盘剩 18.9GB | 阻塞 |
| 10:30 | 清理 uv/Temp/npm/pnpm 缓存释放 36GB | 恢复 |

**根因**：vhdx 膨胀 + Windows 磁盘被挤到 19GB，Docker 在低磁盘下不稳定。

---

## 6. 判分数据质量

| 项 | 值 |
|---|---|
| reward.txt 权威性 | 已确认优先于 Harbor 的 normalized status（见 `6790432`）|
| 被误判的 trial | 4 个（mini-swe，reward.txt 写 "1" 但 normalized 记 infrastructure_error）|
| F2P 可算比例 | sayacode 31/40、mini-swe 34/40、claude-code 34/40、opencode 36/40 |
| 超时 | 仅 sayacode 1 个（ansible-40ade1f，51.7 分钟）|

---

## 7. 产物

| 项 | 路径 |
|---|---|
| 结果数据 | `C:\sb\hard\ab-ctx\prov2-40x4` |
| 分析脚本 | `scripts/analyze_prov2_v2.py` |
| 批次切分 | `C:\sb\hard\ab-ctx\prov2-40x4-batches` |
| 运行日志 | `C:\sb\hard\ab-ctx\prov2-40x4-takeover.log` |
| 缺陷收集 | `C:\sb\tmp\collect_failure_causes.py` |
| 误判扫描 | `C:\sb\tmp\scan_false_negatives.py` |
