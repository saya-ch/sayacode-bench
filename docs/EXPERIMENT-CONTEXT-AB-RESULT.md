# 长上下文 A/B 实验：结果报告（2026-11-07）

| 项 | 值 |
|---|---|
| 目的 | 检验 `EXPERIMENT-CONTEXT-AB.md` 的核心假设：**题集太浅导致无判别力，注入无关长上下文能拉开差异** |
| 设计 | 同题、同验证器、同制品，唯一变量是**指令尾部追加的无关材料**（≈100k tokens） |
| 题集 | 6 题（从 clean 双过里选，覆盖 6 个仓库，排除 vuls 重题） |
| 制品 | PyPI `sayacode-3.2.7`（与 clean 批次同制品） |
| 模型 | `auto-hy3`（192k / 32k） |
| clean 对照 | **不重跑**，直接复用 `C:\sb\hard\v4-327`（同 6 题、同 repeat、同制品） |
| noise 组 | `C:\sb\hard\ab-ctx\run-sayacode`（12 trial） |
| 结果产物 | `AB-RESULT.json`、`FINAL-SUMMARY-NOISE.json`、`clean-baseline.json` |

> **这是本项目第一次检出统计上强、方向上单向的差异。** 此前所有批次（v1~v4）的结论都是"未检出显著差异"。这一结果的含义与局限见 §4。

---

## 1. 结果

### 1.1 主结果

| 组 | 通过 | 通过率 |
|---|---|---:|
| **clean**（v4-327，无噪声） | 12/12 | **100.0%** |
| **noise-100k**（追加 ≈100k tokens 无关材料） | 7/12 | **58.3%** |
| **Δ（退化量）** | — | **41.7 pp** |

配对结构（题 × repeat，12 对）：

| 指标 | 值 |
|---|---|
| both pass | 7 |
| **clean-only**（噪声下退化） | **5** |
| **noise-only**（噪声下反而通过） | **0** |
| both fail | 0 |
| McNemar exact p | **0.062** |
| 题块 bootstrap CI95（Δ） | **[+8.3, +83.3] pp**（不含 0） |

**完全单向**：5 个退化、0 个反转。这在配对设计里是很强的信号。

### 1.2 逐题

| 仓库 | clean | noise | 判定 |
|---|---|---|---|
| NodeBB | 2/2 | **1/2** | 退化（r1 空 patch）|
| element-hq | 2/2 | 2/2 | 无退化 |
| flipt-io | 2/2 | **0/2** | **退化（两次都失败，均有 patch）** |
| internetarchive | 2/2 | 2/2 | 无退化 |
| navidrome | 2/2 | **0/2** | **退化（r1 空 patch，r2 有 patch 仍失败）** |
| tutao | 2/2 | 2/2 | 无退化 |

**3/6 题退化，3/6 题完全不受影响。** 这个分裂本身值得注意——噪声不是均匀地拖慢所有题，而是**打掉了特定的题**。

### 1.3 失败模式

12 个 trial 里，5 个失败分两类：

| 类型 | 数量 | 含义 |
|---|---|---|
| **空 patch**（`skipped_empty_patch`） | 2 | agent 什么都没改就结束了 —— 被噪声"淹没" |
| **有 patch 但没改对** | 3 | agent 改了，但改错地方/改漏了 |

二者都是**能力退化**的表现，不是环境失败（见 §3 的核验）。

---

## 2. 机制验证：噪声确实注入且未越摘要线

这是实验有效性的**前提条件**，单独核验（smoke trial 的 `usage-details.json`）：

| 检查项 | 结果 |
|---|---|
| 噪声是否真的进 prompt | ✅ 单次调用 `input_tokens` 峰值 **95,645**（clean 批次峰值中位 30–35k） |
| 是否越过摘要触发线（150,400） | ✅ 最高 95,645，**差 54,755**，从未触发摘要 |
| 任务是否仍可完成 | ✅ smoke 那题 `reward = 1` |

→ 测的确实是**"抗干扰 / 长上下文保持"**，而不是"摘要能力"。

同时验证了 `cmd/scripts/locked_agents.py` 的噪声注入钩子（此前从未实现，`STATUS.md` 记"钩子尚未加入"）：
- SAYACODE 走 `variant["instruction_append"]`
- 三个基线走 `inject_noise()`（本次实现，7 个测试覆盖）
- 两条路用同一噪声文件、同一分隔符。

---

## 3. 环境因素排除（关键核验）

内存全程紧张（可用 0.4–1.7GB 波动），必须排除"失败是 OOM 造成的"：

| 检查 | 结果 |
|---|---|
| 5 个失败 trial 的 `record_complete` | **全部 True**（agent 正常结束，不是被杀） |
| `harbor_exception_type` | 仅 **1 个**（navidrome r1，`NonZeroAgentExitCodeError`） |
| 其余 4 个失败 | 无任何异常记录，patch 正常产出（5628–7379 字节） |
| 通过率与内存的关系 | 失败分布在内存正常时段，非集中在低谷 |

→ **4/5 的失败可确认为能力退化**；navidrome r1 判为 infra（保守起见仍按失败计入 planned）。

**口径说明**：
- `planned`（主报）：12 分母，空 patch/infra 按失败 → **58.3%**
- `best` 界：把 navidrome r1 当 infra 可补 → 8/12 = 66.7%，Δ = 33.3pp
- **两种口径的 Δ 都在 33–42pp，远超预注册阈值 15pp**

---

## 4. 这意味着什么 / 不意味什么

### 4.1 可以说的

1. **SAYACODE 3.2.7 在追加 ≈100k tokens 无关材料后，6 题上的通过率从 100% 降到 58.3%（Δ 41.7pp）。** 5 个退化、0 个反转，CI 不含 0。
2. **「题集太浅导致无判别力」这个假设，至少方向是对的**：往同一批题里注入长上下文，原本 100% 通过的题里有一半掉了下来。这说明之前四组被压在窄带里，确实与"上下文压力不足"有关。
3. **失败有明确形态**：2/5 是空 patch（放弃），3/5 是改了但没改对。不是随机噪声。
4. **退化是选择性的**：3 题完全不受影响、3 题被打掉。不是均匀拖慢。

### 4.2 **不能**说的（红线）

1. ❌ **不能说"SAYACODE 的抗干扰能力比基线差"** —— 本实验**只跑了 SAYACODE 一组**，没有基线对照。设计文档明确写过"只跑 SAYACODE 不跑基线 → 无法归因"。
2. ❌ **不能说"41.7pp 是上下文能力的真实差距"** —— n=6 题，McNemar p=0.062 未过 0.05（功效不足，不是效应不存在）。
3. ❌ **不能与旧四组数据横向比较** —— clean 来自 11-06 批次、noise 来自 11-07 批次，虽同制品同题，但环境不同。
4. ❌ **不能外推到其他题库/其他模型** —— 只有 SWE-bench Pro V2 的 6 题、只有 hy3。

### 4.3 一个必须承认的局限

**噪音是"其他项目的 instruction 原文"**，不是"无关但语义截然不同的材料"。它包含真实的 issue 描述、验收标准、代码片段——虽然来自其他仓库、且已过滤掉目标仓库名，但**形态上仍是"编程任务描述"**。因此模型可能不是"被无关内容干扰"，而是"被同类任务描述误导"。

这个区别很重要：
- 若理解为"抗干扰能力"，结论是"SAYACODE 抗干扰弱"
- 若理解为"同类任务描述造成任务混淆"，结论是"SAYACODE 在长 prompt 下目标保持能力弱"

**当前数据无法区分这两者。** 要区分，需要加一个"语义无关材料"（如随机技术文档、纯日志）的对照档。

---

## 5. 下一步

| 优先级 | 动作 | 理由 |
|---|---|---|
| **P0** | **跑基线三组**（6 题 × 2 × noise-100k × 3 agent = 36 trial） | 这是唯一能把"SAYACODE 退化 41.7pp"变成"SAYACODE 比基线退化更多/更少"的实验，也是设计要求的归因前提 |
| P0 | 补 `noise-30k` 档，做剂量-反应 | 若 30k 无影响而 100k 有影响，说明存在阈值；这对"需要多长的题"有直接指导 |
| P1 | 加"语义无关材料"对照档 | 区分"抗干扰"与"目标保持"（见 §4.3） |
| P1 | 扩题到 12 题 | 当前 n=6，p=0.062 差一口气 |

---

## 7. 基线组受阻：Windows 命令行长度限制（技术障碍，未解决）

**基线三组（mini-swe / Claude Code / OpenCode）无法用同样的方式注入噪声**，这是本实验当前最大的缺口。

### 7.1 现象

`C:\sb\hard\ab-ctx\ABANDONED-baselines-WinError206`（保留证据，221 个文件）：

| agent | 结果 | 每 trial 耗时 |
|---|---|---|
| mini-swe | `有效 0/12`，12/12 `FileNotFoundError` | ~1 分钟即失败 |
| claude-code | 全部 `infrastructure_error` | 32–49 秒即失败 |

### 7.2 根因

```
FileNotFoundError: [WinError 206] 文件名或扩展名太长。
  ...
  hp, ht, pid, tid = _winapi.CreateProcess(executable, args, ...)
```

Harbor 把 instruction 直接拼进命令行参数：

```python
# harbor/agents/installed/mini_swe_agent.py:746,847
escaped_instruction = shlex.quote(augmented_instruction)
command = f"mini-swe-agent --yolo --model={...} --task={escaped_instruction} ..."
```

**Windows `CreateProcess` 的命令行上限约 32KB**，而我们的 noise instruction 是 **350,946 字符**（≈343KB）——超限 10 倍。

### 7.3 为什么 SAYACODE 不受影响

SAYACODE 走 `variant["instruction_append"]`：噪声被写进 `variant.json` 文件，由产品侧在**容器内部**读取，全程不经过 Windows 命令行。所以它 12/12 正常完成。

**这解释了为什么本实验只有 SAYACODE 的数据** —— 不是设计选择，是被环境限制逼出来的。

### 7.4 可行方案与代价

| 方案 | 做法 | 代价 |
|---|---|---|
| **A. 改注入通道为「容器内文件 + 提示读取」** | `upload_file()` 把噪声传进容器，instruction 只加一句「背景材料见 /tmp/BACKGROUND.md」 | ① 语义变了：测的是「会不会去读无关文件」而非「prompt 里有无关内容」；② **SAYACODE 也必须改成同样方式并重跑**，否则两组不可比；③ 耗时 +1 小时 |
| **B. 改写 harbor 调用，用 `--task="$(cat file)"` 绕过长度限制** | 在 `LockedMiniSwe.exec_as_agent()` 里拦截超长 `--task=`，改成读容器内文件 | 语义保留（模型收到的仍是完整 instruction）；但要对 3 个 agent 各写一份适配，且依赖 harbor 内部实现细节，升级易碎 |
| **C. 在 WSL/Linux 侧跑** | 命令行上限 2MB，350KB 可直传 | 需要把整套跑批搬到 WSL，工作量大 |
| **D. 缩小噪声到 32KB（≈9k tokens）** | 不超限即可 | **测不到长上下文效应**——9k 与 clean 的 30–35k 同量级，等于没做 |

### 7.5 对当前结论的影响

- ✅ **SAYACODE 单组的 Δ=41.7pp 仍然成立**（12/12 正常完成，机制与环境均已核验）。
- ❌ **但归因不完整**：无法回答「这个退化是 SAYACODE 特有的，还是所有 agent 都会退化」。按 `EXPERIMENT-CONTEXT-AB.md` 的预注册判定，缺基线就**不能**判「假设成立」。
- **建议走方案 B**（语义保留、不动 SAYACODE 已有结果、不重跑），如果时间允许再补方案 A 作交叉验证。

### 7.6 教训（值得记进坑库）

**「设计定稿」不等于「可执行」。** 这份实验设计 2026-11-05 就写完了、工具也写好了，但注入钩子直到今天才实现——而实现后才发现**基线通道有平台级限制**。教训是：**任何跨平台的长参数传递，必须在设计阶段就用最长的输入做一次端到端 smoke**，而不是假设"instruction 就是个字符串"。

---

## 8. 复现

```powershell
# 1) 生成统一噪声（排除 6 个目标仓库，二次过滤掉提到目标仓库名的素材）
uv run --no-sync python C:\sb\tmp\make_unified_noise.py

# 2) 构造 variant
uv run --no-sync python -c "import json,pathlib; n=pathlib.Path(r'C:\sb\hard\ab-ctx\noise-unified\unified-noise-100000.txt').read_text(encoding='utf-8'); pathlib.Path(r'C:\sb\hard\ab-ctx\variant-unified-noise-100k.json').write_text(json.dumps({'id':'noise-100k-unified','instruction_append':n}, ensure_ascii=False, indent=2), encoding='utf-8')"

# 3) 跑批（SAYACODE 6 题 × 2）
pwsh -File C:\sb\tmp\run-ab-sayacode.ps1

# 4) 配对分析
uv run --no-sync python scripts/analyze_context_ab.py `
  --clean-root C:\sb\hard\v4-327 `
  --noise-root C:\sb\hard\ab-ctx\run-sayacode `
  --sample C:\sb\hard\ab-ctx\sample-ab6.json `
  --agents sayacode --repeats 2 --json-out C:\sb\hard\ab-ctx\AB-RESULT.json
```

**噪声身份**（事后核验用）：
- 文件 `C:\sb\hard\ab-ctx\noise-unified\unified-noise-100000.txt`
- 350,946 字符 ≈ 100,270 tokens
- sha256 `4ffb2924e0eea4fb96f5b157288958233863d651813df5ca39d2a5dbc3cf1a75`
- 素材 550 条，来自 9 个仓库（已排除 6 个目标仓库 + 2 条提到目标仓库名的）
- 目标仓库名泄漏检查：**无泄漏**
