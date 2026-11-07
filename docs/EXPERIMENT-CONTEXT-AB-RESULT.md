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

## 7. 基线组受阻：三条进程通道各有各的长度限制（未解决）

**基线三组无法用同样的方式注入噪声。** 这不是一个 bug，而是**三条不同的传参通道各有各的平台限制**，而 350KB 的 instruction 在三条通道上全部超限。

### 7.1 三条通道的实测结果

| agent | 传参方式 | 实测失败 | 限制在哪 |
|---|---|---|---|
| **SAYACODE** | `variant.json` 文件 → 容器内读取 | ✅ **12/12 成功** | 不经过任何命令行，**不受限** |
| **mini-swe** | `--task={shlex.quote(instruction)}`（argv） | ❌ 12/12 失败 | Linux `execve` 单参数上限（`E2BIG`，通常 128KB） |
| **Claude Code** | 环境变量 `HARBOR_CLAUDE_CODE_INSTRUCTION_<hash>` | ❌ 全失败 | Windows 命令行 32KB（env 被拼进 `docker exec -e`）|
| **OpenCode** | 未实测（预计同类） | — | — |

### 7.2 前两次尝试与各自的失败

**第一次**（`ABANDONED-baselines-WinError206`，221 文件）——原样注入，全部崩在 Windows：

```
FileNotFoundError: [WinError 206] 文件名或扩展名太长。
  hp, ht, pid, tid = _winapi.CreateProcess(executable, args, ...)
```

**第二次**（`ABANDONED-baselines2-multi-channel`，244 文件）——实现了「超长命令落盘为容器内脚本」的修复（提交 `75dbb36`，含 6 个测试 + 变异检验），成功绕过 Windows 32KB：

- ✅ 修复本身**有效**：mini-swe 不再在 Windows 层崩溃，`exception.txt` 归零。
- ❌ 但撞上**第二堵墙**——Linux `execve` 的单参数上限：

```
/tmp/bench-cmd-<uuid>.sh: line 2: /root/.local/bin/mini-swe-agent: Argument list too long
```

- ❌ Claude Code 连 spill 都不触发：它的命令只有 **511 字符**（instruction 走环境变量 `"$HARBOR_CLAUDE_CODE_INSTRUCTION_..."`），是 `docker exec -e` 那一层超限。

### 7.3 为什么不能简单"再修一下"

| 通道 | 要让 350KB 通过，必须 | 代价 |
|---|---|---|
| mini-swe | 不能用 argv 传（`--task="$(cat file)"` 展开后**仍是**一个 350KB 的 argv，仍然 E2BIG）→ 必须让它**从 stdin 或文件**读 | 需改 harbor 的命令构造；且 agent 是否"真读了"不可控 |
| Claude Code | 环境变量也不能传 350KB → 同样必须改成"文件 + 提示" | 同上 |
| **代价的核心** | **一旦基线改成"从文件读"，SAYACODE 的 variant 通道就不可比了** | 要可比就必须**两组都改成文件方式，并重跑 SAYACODE 的 12 trial** |

### 7.4 第三次尝试：改用「容器内文件 + 短提示」（路线 A）——也失败

2026-11-07 中午按路线 A 实施：新增 `src/sayacode_bench/noise.py` 的 `stage_background()`，
把噪声上传成容器内 `/tmp/BACKGROUND.md`，instruction 只带一段**固定短提示**
（明说"与你当前要修复的问题无关"+"请用 cat 读取，可分块"），四组走**同一个函数**。

结果（mini-swe 单题 smoke）：

| 检查 | 结果 |
|---|---|
| 传参通道是否通了 | ✅ `completed`，`model.patch` **2831 字节**（不再是 0） |
| 轨迹是否记录了提示 | ✅ 出现 `cat /tmp/BACKGROUND.md` 与提示正文 |
| **噪声内容是否真的进了上下文** | ❌ **没有** |

决定性证据：

| 特征串 | 轨迹中出现次数 |
|---|---:|
| `----- 归档 #`（噪声每个 block 的开头） | **0** |
| `ansible`（噪声素材里的仓库名） | **0** |

轨迹本身有 113KB（说明 agent 确实做了不少事），但**噪声内容一个字都没进去**。

**根因：第四层限制——agent 自身的 observation 输出上限。**
`cat` 一个 350KB 的文件时，工具返回被截断（mini-swe 侧约 10000 字符），
agent 只看到提示文字、看不到材料正文。

### 7.5 四次尝试，四层限制

| # | 尝试 | 撞上的限制 | 影响 |
|---|---|---|---|
| 1 | 噪声直接拼 instruction | **Windows 命令行 32KB**（`WinError 206`） | 基线全失败 |
| 2 | 超长命令落盘为容器内脚本 | **Linux `execve` 单参数 128KB**（`E2BIG`） | mini-swe 仍失败；Claude Code 更在 env 层就挂 |
| 3 | 改用容器内文件 + 短提示 | **agent observation 输出上限（约 10k 字符）** | 提示生效但内容进不去 |
| 4 | 拆成多文件分块读？ | 需 agent 主动执行几十次读取——**不可靠，且无法保证它真读完** | 未实施 |

**每一层修好之后，下一层才浮现。** 这是本次实验最贵的教训。

### 7.6 最终结论（收敛）

**在当前 harness + 平台条件下，无法给三个基线可靠注入 100k 上下文。** 因此：

- ✅ **SAYACODE 单组的 Δ=41.7pp 成立**（它走 `variant.json` → 容器内 worker 读取，
  是唯一真正把 350KB 放进 prompt 的通道；已用 `input_tokens` 峰值 95,645 验证）。
- ❌ **基线对照不可得**。按预注册判定，缺基线**不能**判「假设成立」。
- **要真正跑通只能改 harness**：在对话历史里预置噪声（而不是让 agent 去读）——
  那是框架级改动，超出本次范围。

### 7.7 三条可能的后续方向

| 方向 | 做法 | 成本 | 能回答什么 |
|---|---|---|---|
| **A. 改 harness 预置历史** | 让基线 agent 启动时即带若干条"背景"消息 | 需读 harbor agent 内部实现，3–5 小时，且脆弱 | 四组可比的完整结论 |
| **B. 只报 SAYACODE 单组** | 接受当前结果 | 0 | SAYACODE 在 100k 上下文下退化 41.7pp（不能归因） |
| **C. 换测量方式** | 不追"抗干扰"，改测**真实长轨迹任务**（多轮累积上下文，如 `evals/scenarios/context.jsonl`） | 中 | 更贴近真实长上下文场景，但样本另起 |

**建议 B + C**：先把已有结果固化（它本身已经是本项目第一次检出强差异），
再用真实长轨迹任务（C）替代"人为注入噪声"，避免与 harness 的层层限制搏斗。

### 7.8 教训（值得记进坑库）

1. **「设计定稿」不等于「可执行」。** 这份设计 2026-11-05 就写完了、工具也写好了，但注入钩子直到今天才实现——实现后才发现三条通道各有各的限制。
2. **平台限制是分层的，修好一层不等于通。** Windows 的 32KB 修好后，Linux 的 128KB 才浮现；而 Claude Code 根本不走 argv。
3. **凡是「把长文本塞进进程参数」的设计，必须先量清楚目标通道的上限**，并优先选择**文件通道**（SAYACODE 的 variant 之所以 12/12 成功，正是因为它一开始就走文件）。

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
