# EXPERIMENT DESIGN：SAYACODE 评测实验设计（2026-10-30）

> 从顶层研究问题到执行细节的完整梳理。**所有数字均标注来源；未经核实的标注「待测」，不做反推。**
> 配套：[EVALUATION-PLAN](EVALUATION-PLAN-20261030.md)（总纲）、[ITERATION-WORKFLOW](ITERATION-WORKFLOW.md)（流程）、[AGENTS](../AGENTS.md)（维护须知）。

## 1. 研究问题

**主问题**：在**同一模型（hy3）、同一基准（SWE-bench Pro V2）、同一批题**下，SAYACODE 的完整 agent 设计（工具集/规划/子 agent/上下文管理）相对标准 harness，在**任务完成率**与**成本**上各是多少？

**子问题**：
1. SAYACODE vs mini-swe-agent（最小 scaffold，仅 bash）——**复杂度的净收益**
2. SAYACODE vs Codex CLI（商业级 scaffold，含规划+协作模式）——**与头部产品的差距**
3. 三者的**成本**（token/成功）与**过程质量**（改测试率、空转、patch 膨胀）差异

**不回答**：谁"更强"的通用结论（只限本模型、本基准、本子集）。

## 2. 假设（可被否定）

| 编号 | 假设 | 否定条件 |
|---|---|---|
| H1 | 同模型下 SAYACODE 完成率高于 mini-swe-agent | 配对 McNemar p>0.05 或方向相反 |
| H2 | SAYACODE 在长任务（多文件/大 patch）上优势更大 | 子集上无差异 |
| H3 | 复杂度带来更高成本（token/成功） | 成本无差异或更低 |
| H4 | SAYACODE 的改测试率低于基线 | 改测试率更高 |

## 3. 选型

### 3.1 基准：SWE-bench Pro V2 public set
- 642 题 / 11 仓库（`v2/tasks` 实测 642 个目录）。
- **排除 123 题 musl**（gravitational 68 + protonmail 55，产品栈无 musllinux wheel）→ **519 可评测**。
- 难度/类别单一：**100% medium / 100% debugging**（642 个 task.toml 实测）。
- 权威性与风险见 [EVALUATION-METHOD-REVIEW](EVALUATION-METHOD-REVIEW.md)（Epoch AI 判 "Flawed"，约 30% 坏题 → 必须 gold patch 筛）。
- **不用 Terminal-Bench**（已弃用）。

### 3.2 模型：hy3（暂定唯一）
- Magpie `auto-hy3`，实际 context **192,000** / max_output 64,000（`/v1/models` 实测）。
- 三来源同模型不同额度池（workbuddy / workbuddy-ai / hy3-x），权重已调；**每 trial 记录 served**。
- 上下文窗口**必须显式对齐**（见 §5.3）。

### 3.3 题集：`studies/sample-40.json`
- 40 题 = 复用已缓存 29 + 按仓库比例新抽 11（seed `saya-eval-20261030`，sha256 排序）。
- 覆盖 9 个可评测仓库，按题数比例分配。
- 统计力：40 题配对、每版 2 重复 → 可检测 **约 20pp**（95% CI 半宽 ±14pp 独立）。

### 3.4 三个 agent（同模型）
| | SAYACODE | mini-swe-agent | Codex CLI |
|---|---|---|---|
| 实现 | 产品本体（`adapter:SayacodeAgent`）| `locked_mini_swe_fixed`（补 mcp）| `locked_codex` |
| 工具 | 11 种 | 仅 bash | shell/apply_patch/exec_command/update_plan |
| 规划 | write_todos | 无 | update_plan |
| 子 agent | 有 | 无 | collaboration 模式 |
| 协议 | Anthropic messages | OpenAI chat | OpenAI responses |

## 4. 实验设计

### 4.1 变量
- **自变量**：agent（3 水平）
- **控制变量**：模型（hy3）、题集（40 题）、环境（官方容器）、验证器（官方）、重复次数（2）、权限（三者均完全权限）、上下文窗口（均对齐 192k）
- **因变量**：见 §5

### 4.2 对照与盲法
- **配对**：同一题、同一重复序号跑三个 agent（消除题目难度方差）。
- **无盲法**（无法对 agent 隐藏）。

### 4.3 重复
- 每 (agent, 题) 跑 **2 次**，用于：① 抵消同题方差 ② 计算 pass^k（一致率）③ 估计重复方差。

### 4.4 样本量与多重比较
- 3 agent 两两比较 = 3 个假设 → **Bonferroni α/3 = 0.0167**。
- 40 题配对的 McNemar 在 α=0.0167 下，可检测效应约为 **18–20pp**（待按实际不一致对数校准）。

## 5. 配置对齐（已核实项）

### 5.1 权限（全部完全权限，不会阻塞等用户）
| agent | 依据 |
|---|---|
| SAYACODE | `default_trust="full"`、`trust_level="full"`、`trust_explicit=True`（worker.py:860-877）|
| mini-swe | yolo 模式（`mini_toolcall.yaml`）|
| Codex | `--dangerously-bypass-approvals-and-sandbox`（codex.py:1767，无条件）|

### 5.2 上下文策略（各自固有，非缺陷）
| agent | 窗口 | 策略 |
|---|---|---|
| SAYACODE | 192,000（有效输入 176,000）| 摘要触发 153,600、保留 12 条 |
| mini-swe | 176,000 输入 + 16,000 输出（registry 注册）| 观察输出截断 >10k 字符裁头尾 |
| Codex | 182,400 | `history_mode: paginated` + 输出截断 |

### 5.3 窗口对齐记录
- hy3 真实 context：192,000（`/v1/models`）。
- SAYACODE：profile `context_length=192000, max_output_tokens=16000` → 摘要触发 153,600（`profile_summary.py` 实测）。
- mini-swe：litellm 不认识 `openai/auto-hy3`（`ModelNotMappedError` 实测）→ 用 `litellm_model_registry` 注册 `max_input_tokens=176000, max_output_tokens=16000`（容器内 `/tmp/mswea-config/registry.json` 实测）。
- Codex：`config.model_context_window=192000` → 会话实际 `model_context_window=182400`（codex 自扣，实测）。
- **三者有效输入：176,000 / 176,000 / 182,400**（差异来自各 harness 的 output 预算策略）。

## 6. 指标体系

| 类别 | 指标 | 定义/来源 |
|---|---|---|
| 结果 | pass@1（±Wilson CI）| 官方 reward |
| 结果 | partial credit | 必需测试通过数/必需数（验证器 stdout）|
| 结果 | pass^k（一致率）| 2 次全过 |
| 结果 | 回归破坏率 | PASS_TO_PASS 变化（partial=100% 但 reward=0 等）|
| 效率 | **cost-per-success** | 总 token ÷ 通过数 |
| 效率 | step-per-success | 总步数 ÷ 通过数 |
| 护栏 | **reward hacking rate** | 改/删测试的 trial 比例 |
| 护栏 | 空转率 | model.patch=0 |
| 护栏 | bloat ratio | patch 字节 ÷ gold patch 字节（中位）|
| 噪声 | 重复方差 | 同题两次 reward 的标准差 |

报告格式：`成功率(±CI) | partial | pass^k | cost/成功 | step/成功 | 改测试率 | bloat | 空转 | 方差`

## 7. 评价与统计

1. 逐题记录 reward、partial、token、步数、改测试、patch、重复结果。
2. **配对 McNemar**（`compare_trials.py`）比较两 agent；报风险差与 95%CI。
3. 3 组比较用 **Bonferroni 校正**。
4. 不宣称"显著优于"除非：护栏不恶化 + 效应量 ≥ 可检测阈值 + p 通过校正。
5. 单题结果一律标注"n=1，不可结论"。

## 8. 执行协议

1. 跑前：`docker network prune -f`（每 trial 占 2 网络，池约 17）+ `profile_summary.py` 汇报配置（硬性，见 ITERATION-WORKFLOW §8）。
2. 并发：**8**（实测单容器峰值约 507MB；Docker VM 8GB；网络池需 prune）。
3. 每次跑批：`--repeats 2 --concurrency 8`，secrets/镜像均已就绪。
4. 跑后：`analyze_trials.py` 出记分卡 + `annotate_served.py` 确认 served 分布。

## 9. 数据与可复现

- 题集：`studies/sample-40.json`（含 seed、抽样规则、仓库分配）。
- 每个 trial 保存：`result.json`、`verifier/`、`agent/model.patch`、`agent/*trajectory*`、`restored/stripped-test-files.json`。
- 镜像持久化（40 题已缓存，不再重拉）。
- 配置：`magpie-hy3.json`（profile）+ `test_agent.py`（三 agent 构造，当前为验证脚本，正式跑需固化为 variant）。

## 10. 已知局限与风险

| 风险 | 说明 | 缓解 |
|---|---|---|
| 坏题 | Epoch AI 称 Pro 约 30% 坏题 | gold patch 筛题（待执行）|
| 单题方差 | 实测同题 0→1 | 2 重复 + pass^k + 配对 |
| 8 并发稳定性 | 未实测 | 首轮监控内存/网络，异常降至 4 |
| JS/TS 内存峰值 | 未实测（仅测 Python 507MB）| 首轮监控 |
| 协议不同 | messages/chat/responses | 记录，不归因 |
| 上下文策略不同 | 各自固有 | 记录 |
| 仅 hy3 | 结论不外推到其他模型 | 报告标注 |
| 40 题样本 | ±14pp | 不外宣称更小差异 |

## 11. 当前状态

- ✅ 三 agent 单题链路跑通（SAYACODE 0/1、mini-swe 1.0、Codex 1.0）
- ✅ 40 题镜像就绪
- ✅ 窗口/权限/网络/依赖全部对齐
- ⏳ 待执行：gold patch 筛坏题 → SAYACODE 40×2 → mini-swe 40×2 → Codex 40×2
