# 评测方案（对齐版，2026-10-30）

> 本文件是 SAYACODE 评测调优的**总纲**，取代此前分散、部分作废的探索记录。与 [protocol](protocol.md) 的关系：protocol 管正式对外研究的预注册；本方案管**开发期内部调优**的执行。

## 1. 目标

**内部调优：找改进方向，快速迭代。** 允许复用已跑过基线的缓存题；不追求对外可比成绩（对外另设干净集）。

## 2. 基准：只用 SWE-bench Pro V2

- **弃用 Terminal-Bench 2.1**（题池小、与产品主战场偏离）。
- 用 SWE-bench Pro V2 **public set 642 题**（11 仓库），排除 123 题 musl（gravitational/protonmail）→ **519 可评测**。
- 全部 medium/debugging、4 语言（python/go/ts/js）。数据本身同质，靠**仓库分层**保证覆盖。
- 权威性与局限见 [EVALUATION-METHOD-REVIEW](EVALUATION-METHOD-REVIEW.md)；Epoch AI 判其 "Flawed"（约 30% 坏题），故**必须 gold patch 筛题**（见 §6）。

## 3. 模型：暂定只用 hy3（固定来源，正确上下文）

| 角色 | 模型 | 固定来源 | 上下文配置 |
|---|---|---|---|
| 主模型（开发 + 确认）| **hy3** | `auto-hy3`（同模型多额度池）| 192,000 / 输出 **32,000**（v2 起）|

- **暂定只用 hy3**；deepseek-v4.1-flash 作为「可选」最终确认，**尚未确认使用**，不纳入当前流程。
- **禁止用会漂移的 `auto/...` 别名**（见 [ROUTING-DRIFT](ROUTING-DRIFT-20261029.md)）。
- 每个 trial 记录实际 `served`/`provider`（`scripts/annotate_served.py`）。

## 4. 题集：40 题（开发迭代集）

- **40 题 = 复用已缓存 29 + 新抽 11**，按仓库分层（`studies/sample-40.json`，seed=`saya-eval-20261030`，可复现）。
- 统计力：40 题配对、每版 2 重复 → **可检测约 20pp** 的改进（95% CI ±14pp 独立）。
- 干净集（对外里程碑用）另建：从 492 干净题分层抽 60，逐题拉→跑→删（不持久化）。

## 5. 指标：成功率与成本并重

| 类别 | 指标 |
|---|---|
| 结果（主） | pass@1（±Wilson CI）、**cost-per-success**（token/成功）、partial credit、pass^k、回归破坏率 |
| 过程（诊断/护栏） | 步数、重复读、**reward hacking rate（改测试率）**、空转、bloat ratio、step-per-success、重复方差 |
| 效率 | token/时长 per 成功 |

详见 [ITERATION-WORKFLOW](ITERATION-WORKFLOW.md) 第 2、9 节。**partial 必须与 reward hacking 同报**（防刷）。

## 6. 执行方法（防噪声 + 防坏题）

1. **gold patch 筛坏题**：候选题的 `solution/gold_patch.diff` 跑验证器必须通过，失败即视为坏题剔除替换。
2. **配对设计**：基线版与候选版跑**同一批题**；用 McNemar 检验（`scripts/compare_trials.py`）。
3. **每版 2 重复**：抵消同题方差；报 pass^k 与重复方差。
4. **跑前汇报配置**：每次跑批前用 `scripts/profile_summary.py` 汇报模型/上下文/触发点并取得确认（硬性）。

## 7. 横向对比：SAYACODE vs mini-swe-agent vs Codex CLI（同 hy3）

- 目的是量化"SAYACODE 的脚手架比标准 harness 多拿多少分"，同模型隔离 harness 差异。
- 三组两两比较需 **Bonferroni 校正**（α/3），有效检测门槛升到 ~18–20pp。
- mini-swe 与 Codex 需先做**单题可行性验证**（网络/协议/端点）再正式跑。

## 8. 工具链

| 用途 | 命令 |
|---|---|
| 题集清单 | `studies/sample-40.json` |
| 跑批（holdout）| `scripts/run_holdout.py --profile ... --skip-existing --concurrency 4` |
| 跑批（回归集）| `scripts/run_regression.py --model-label hy3` |
| 指标记分卡 | `scripts/analyze_trials.py <jobs>` |
| 配对统计 | `scripts/compare_trials.py <A_jobs> <B_jobs>` |
| 配置汇报 | `scripts/profile_summary.py <profile>` |
| served 记录 | `scripts/annotate_served.py <jobs>` |

## 9. 当前状态与下一步（2026-10-31 更新）

- 网络环境已支持 chat/messages/**responses** 三种上游（`network.py`）。
- ✅ 三 agent 单题可行性验证完成；窗口/权限/依赖已对齐。
- ⚠️ gold patch 筛 40 题：实际 **36 good / 1 bad / 3 null**，bad 不在 40 题内；「40 题全绿」不成立，3 个 null 需补齐或替换。
- ⛔ v1 240 次跑批已收尾但**结论作废**：221/240 完整，分母三套（SAYACODE 55/80、mini-swe 69/80、Codex 56/65），17.4pp 差距是分母假象（Codex 统一 80 分母 70.0%）。
- 🔄 下一步：**v2 重跑**（40 题 × 2 重复 × 3 agent，输出 `C:\sb\hard\v2`，`max_output_tokens=32000`），汇总必须统一 80 分母、改测试分两口径、模型故障逐条列明。
- 当前真实状态见 [STATUS](STATUS.md)，交接见 [HANDOFF](HANDOFF.md)。
