# 大评测集 v1：不重复、走量、分层、分组统计

> 状态：题集已冻结（`studies/large-sample-v1.json`），工具就绪，**未开跑**。
> 决策来源：用户「不重复了，走量怎么样，各题组抽样，组成大评测集」「当然也要单独统计每套题」，后续定稿「太多了，要跑好多天，100 道差不多了」。
> 规模：**100 题**（从 312 题缩下来；312 题 × 4 组需两天多，跑不动）。

## 1. 为什么这么改

| | 旧设计 | 大评测集 |
|---|---|---|
| 样本 | 40 题 × 2 重复 = 80 trial/组 | **100 题 × 1 重复 = 100 trial/组** |
| 题级 n | 40 | **100** |
| 95% CI | ±12pp | 约 ±9pp |
| 检测 10pp 差异 | 需约 330 题 | 100 题仍不足，但 CI 比 40 题收窄一半以上 |
| 重复 | 2 次（DEEP-DIVE 已证「不足以消除系统性方差」） | 1 次 |

**核心理由**：统计不显著的根因是题量，不是重复次数。把重复的资源换成题量，题级 Wilson CI 收窄，且四组跑同一批题 → **题级配对 McNemar 仍然成立**。代价是丢掉 pass@2 / pass^2（这两个本来就只是诊断指标，不是主结论）。

## 2. 题组与配额

| source | 池 | 抽中 | 分层维度 | 数据源 |
|---|---:|---:|---|---|
| `pro-v2` | 642 | **40** | 11 个仓库 | 本地任务缓存（`C:\sb\tmp\hard\cache\...`）|
| `promax` | 170 | **35** | 7 语言 × 3 文件档（21 层）| [HF `swe-bench-promax/SWE-Bench-ProMax`](https://huggingface.co/datasets/swe-bench-promax/SWE-Bench-ProMax) |
| `swe-evo` | 48 | **15** | 7 个项目（单层上限 10 保多样性）| [HF `Anonymous-123456/SWE-EVO`](https://huggingface.co/datasets/Anonymous-123456/SWE-EVO) |
| `tb21` | 81（排除 >4GB）| **10** | 16 个 category | 本地快照 `C:\sb\s\terminal-bench-2.1-...` |
| **合计** | | **100** | | |

- 固定 seed `20261105-large-eval`；层内按 `sha256(seed:task_id)` 排序取样，**完全可复现**。
- ProMax 的 gold patch 中位 7 文件、最大 184 文件，是当前题集（中位 2 文件）的深度天花板。
- TB 2.1 已饱和（最佳 92.8%），只留 10 题作 CLI 形态补充，不让它主导结论。
- 每个 task 带 `source` / `stratum` / `repo` / `difficulty` / `memory_mb`，供分组与诊断。

## 3. 单独统计（硬性要求）

**每套题必须单独出一组完整统计**，合并数字只作总体口径，不能替代分组结论：

| 指标 | 按 source 出 | 合并总体 |
|---|---|---|
| planned / observed / **partial** / 缺失 / `touches_snap_pass` | ✅ | ✅ |
| 题级 Wilson CI | ✅ | ✅ |
| 分层诊断（哪个仓库/语言/项目拖后腿）| ✅ | — |
| 题级配对 McNemar（组间）| ✅ | ✅ |

工具：`scripts/summarize_large_set.py`，输出「每套题单独统计」表 + 「合并总体」表 + 分层明细 + 配对检验，落 `JSON`。分片结果目录约定 `<root>/<source>/<agent>/{jobs,verify/jobs}`，与 `run_formal_240.py --sample <分片>` 一一对应。

## 4. 产物

| 文件 | 内容 |
|---|---|
| `studies/large-sample-v1.json` | 总集 100 题（带 source）|
| `studies/large-sample-v1-{pro-v2,promax,swe-evo,tb21}.json` | 4 个分片，可直接跑批 |
| `studies/large-sample-v1-strata.json` | 分层配额报告 |
| `scripts/compose_large_sample.py` | 确定性分层抽样生成器 |
| `scripts/summarize_large_set.py` | 分组汇总 + 配对检验 |

## 5. 执行成本（本地 ¥0）

单题约 8–13 分钟，并发 4、重题并发 1：

| 范围 | trial 数 | 估计 |
|---|---:|---|
| SAYACODE 单组跑完 100 题 | 100 | 约 4–5 小时（过夜）|
| 四组全跑 | **400** | 约 18 小时，按 source 分 4 批滚动 |

建议顺序：先 SAYACODE 单组（验证四个题组在本机都能跑通、拿到各 source 的真实基线），再按 source 分批跑三个基线；每批结束就出一次分组统计，不等全部跑完。

**风险**：ProMax 含 7 种语言工具链，镜像体积不可忽略；C: 当前约 28GB 可用，按 `SCALE-WITHOUT-UPGRADE.md` 的每片 20 题滚动，跑完一片删一片（保留 40 题 Pro V2 已有镜像）。SWE-EVO 7 个纯 Python 项目可共享镜像层，最省。

## 6. 与在跑的批次的关系

`C:\sb\hard\v4-327`（P0，3.2.7 制品对齐，40 题 × 2）继续跑完，它是**制品身份验证**，与大评测集目的不同，不合并、不互相替代。大评测集用 1 重复，从这里开始。
