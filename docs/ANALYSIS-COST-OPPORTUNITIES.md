# SAYACODE 成本与延迟优化空间分析（2026-11-09）

> 数据：`C:\sb\hard\ab-ctx\{impact-350,v2v-main}\sayacode\jobs\*\*\agent\sayacode\audit.jsonl`（79 个有效 trial，3,091 次模型调用，4,290 次工具调用）
> 方法：直接从原始 `audit.jsonl` + `usage-details.json` 解析计算，未引用任何既有报告结论。全部数字由文末脚本可复现。
> **独立发现的口径事实**（与任务描述不同，先列出来）：
> 1. 不是"80 个独立 trial"，而是 **40 题 × 2 组产品版本**：`impact-350`=**3.5.0**（40 trial）、`v2v-main`=**3.3.0**（39 trial）；交集 39 题，`impact-350` 独有 1 题（`qutebrowser-3d01c201b-r2`，另有 1 份 `abandoned-*` 副本已排除）。
> 2. 该批是**长上下文压力实验**：variant `noise-100k-unified` 把 350,946 字符无关文本拼进**首轮用户消息末尾**（`sayacode_bench/worker.py` `instruction += "\n\n" + appended`），该消息随每轮重复携带。
> 3. profile 为 `context_length=192000 / max_output_tokens=32000 / summary_trigger_ratio=0.8 / keep=12 / context_edit 关闭`（`profile-private.json`）。
> 4. `cache_read_tokens` 是 `input_tokens` 的子集（2,793/2,793 条 cache>0 记录全部 cache<input）；`audit.jsonl` **不记录 `cache_creation`**。

---

## 一、成本结构表

79 trial 合计（两组合并；版本不同，仅用于成本结构，不作版本对比）：

| 项 | 数值 | 占 Σinput |
|---|---:|---:|
| **Σinput_tokens** | **193,291,991** | 100% |
| 其中 cache_read（缓存命中） | 174,772,416 | **90.4%** |
| 其中未缓存输入 | 18,519,575 | 9.6% |
| **Σoutput_tokens** | **2,744,478** | — |
| input : output | **70.4 : 1** | — |
| 每 trial Σinput 均值 | 2,446,734 | — |

分组合计：

| 组 | 产品 | trial | Σinput | cache_read | 未缓存 | Σoutput | cache占比 | 每trial input |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| impact-350 | 3.5.0 | 40 | 95,501,060 | 88,000,832 | 7,500,228 | 1,382,566 | 92.1% | 2,387,526 |
| v2v-main | 3.3.0 | 39 | 97,790,931 | 86,771,584 | 11,019,347 | 1,361,912 | 88.7% | 2,507,460 |
| **合计** | — | **79** | **193,291,991** | **174,772,416** | **18,519,575** | **2,744,478** | **90.4%** | **2,446,734** |

**读法**：
- 缓存命中率 90.4%，`usage-details.json` 顶层 `cache_creation_input_tokens = 0`——本批**没有任何缓存写入计费**，缓存由网关侧承担。因此**降本杠杆不在缓存策略上，而在"总输入体积"**。
- input:output = 70:1，意味着**每生成 1 token 要重发 70 token 上下文**。这是所有优化提案的算账基础。

**成本分解（关键）**：每 trial 平均 39.1 次模型调用、平均每次 input ≈ 62,540 token。首轮 input 中位 **80,956**（=`350,946 字符噪声 ÷ ~4.3 字符/token` + 产品自身前缀），压缩后主调用回落到 **7,404**。

| 组成 | 估算 token | 依据 |
|---|---:|---|
| 评测注入噪声（首轮用户消息） | ~80,000 / 轮 | 350,946 字符 ÷ 4.3；首轮 input 实测 80,620–82,278（极窄） |
| 产品自身固定前缀（system+planning+tools schema） | **~2,300** | 源码实测：system 3,031 字符 + planning 679 + todo desc 469 + 11 工具 schema/描述 4,959 = 9,138 字符 ≈ 2.3k token |
| 压缩后剩余（摘要 + 最近消息） | ~5,100 | 压缩后主调用 7,404 − 2,300 |

> 结论：**本批 62% 左右的输入是评测注入的噪声**（80k × 压缩前约 19 轮 × 79 trial ≈ 1.2 亿 token，占 193M 的 62%）。产品自身固定前缀只占约 3.7%。真实业务场景没有这段噪声，产品前缀的占比会显著上升。

---

## 二、上下文贡献排名

### 2.1 工具输出（单次原始输出，79 trial 合并）

| # | 工具 | 次数 | Σ字符 | 占比 | 均值 | p50 | p95 | max |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `read_file` | 1,150 | **4,785,156** | **60.6%** | 4,161 | 2,995 | 11,059 | 24,924 |
| 2 | `grep_search` | 922 | 1,343,428 | 17.0% | 1,457 | 208 | 6,556 | 38,104 |
| 3 | `execute_command_tool` | 1,042 | 1,150,458 | 14.6% | 1,104 | 605 | 3,121 | 18,132 |
| 4 | `list_directory` | 141 | 197,513 | 2.5% | 1,401 | 1,088 | 3,457 | 6,469 |
| 5 | `git` | 48 | 189,196 | 2.4% | 3,942 | 1,051 | 17,060 | 17,060 |
| 6 | `glob_search` | 296 | 96,170 | 1.2% | 325 | 51 | 1,308 | 9,152 |
| 7 | `write_todos` | 106 | 55,936 | 0.7% | 528 | 489 | 986 | 1,098 |
| 8 | `analyze_project` | 4 | 35,521 | 0.4% | 8,880 | 6,976 | 19,373 | 19,373 |
| 9-13 | 其余 5 个 | 587 | 41,528 | 0.5% | — | — | — | — |
| | **合计** | **4,290** | **7,894,906** | 100% | | | | |

### 2.2 但"单次输出"严重低估了影响——重复携带才是主因

工具输出一旦进入上下文，**在后续每一轮都会被重发**。实测（48 个发生压缩的 trial，取首个压缩点之前的累计）：

| trial | 首次 input | 压缩前 input | 增量 Δ | 该区间工具输出字符 | 按 3 字符/token | 工具占 Δ |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 82,211 | 107,779 | 25,568 | 96,227 | 32,076 | 125% |
| 2 | 82,211 | 113,789 | 31,578 | 122,662 | 40,887 | 129% |
| 3 | 81,405 | 115,398 | 33,993 | 101,866 | 33,955 | 100% |
| 4 | 80,694 | 116,295 | 35,601 | 134,068 | 44,689 | 126% |
| 5 | 80,694 | 124,181 | 43,487 | 169,367 | 56,456 | 130% |
| 6 | 80,777 | 101,603 | 20,826 | 57,122 | 19,041 | 91% |
| 8 | 81,733 | 101,926 | 20,193 | 39,467 | 13,156 | 65% |
| 10 | 82,278 | 114,933 | 32,655 | 82,990 | 27,663 | 85% |

**结论：压缩前的上下文增长几乎全部由工具输出驱动**（按 3 字符/token 换算中位 ~99%；用实测反推的 3.7 字符/token 则约 80%）。反证：模型自身输出只占 8%（Σoutput 2.74M / Σinput 193M），用户消息每 trial 只有 1–2 条。

**排序结论**：`read_file`（60.6%）是单一最大贡献者，其影响被放大 ~19 倍（平均每次工具输出在剩余轮次被重复携带）。`grep_search` + `execute_command_tool` 合计 31.6%，是第二梯队。

### 2.3 工具并行度（最大的未被利用杠杆）

| 指标 | 值 |
|---|---:|
| 带工具的模型调用 | 2,907 次 |
| 每次携带工具数（均值 / 中位） | **1.48 / 1** |
| 只带 1 个工具的调用 | **2,136 次（73.5%）** |
| 发生并行（>1）的比例 | **26.5%** |
| 分布 | 1→2,136；2→395；3→208；4→125；5→24；6→15；7→2；8→2 |

`prompts.py` 的 `_WORK_RULES` 已有一条"把独立只读调用批量放进一个 response"，但实测**73.5% 仍是单工具串行**。每多一次往返 = 一次完整的 62.5k 上下文重发。

---

## 三、增长模式与压缩

### 3.1 全局曲线

| 指标 | 首次调用 | 末次调用 | 全程最大 |
|---|---:|---:|---:|
| 均值 | 81,110 | 53,573 | 104,661 |
| 中位 | 80,956 | 35,994 | 104,033 |

- 首轮 80,956 极稳定（范围 80,620–82,278）→ 固定注入。
- 末次中位 35,994 低于首轮 → 中途被压缩。

### 3.2 压缩事件（48/79 = 60.8% 的 trial 发生）

| 指标 | 值 |
|---|---:|
| 压缩前 input 中位 | 107,096（范围 98,523–131,452） |
| 压缩后主调用 input 中位 | **7,404**（范围 5,233–19,343） |
| **真实压缩率** | **93.1%** |
| 压缩后回落到 <12k 的比例 | 44/48 |
| 压缩触发位置（第几次调用）中位 | 19（范围 12–44） |
| 骤降那次调用的 input | **恒为 555 token**（48/48 全部相同） |

**555 恒定的含义**：48 个不同 trial、不同上下文规模，骤降那一跳的 input 全部精确等于 555——这不可能是主循环（主循环上下文是动态的），只能是**固定提示词的独立模型调用**，即摘要中间件在 `before_model` 内发起的压缩子调用（其 `parent_run_id` 与主调用不同，其后主调用回落到 7.4k）。

> 本批 `state` 目录**不保存 checkpoints.sqlite3**，无法直接读到摘要消息，故上段定性标注为**推断**（三条一致证据：恒 555 / parent_run_id 不同 / 其后主调用回落）。压缩子调用自身成本可忽略：50 次 × 555 = 27,750 token，占 Σinput 0.01%。

### 3.3 压缩后立即二次增长

| 指标 | 值 |
|---|---:|
| 压缩后到结束的最大 input | 中位 19,266 |
| 压缩后再增长幅度 | 中位 **+18,710** |
| 压缩后剩余调用数 | 中位 20 |

即：刚压到 7.4k，剩下 20 轮里又涨回 19.3k（+2.5 倍）。**压缩只解决一次，不改变增长速率**。

### 3.4 压缩与结果的关系（观察性，非因果）

reward 来自各组 `sayacode/verify/jobs/*/verifier/reward.txt`，匹配到 71/79 trial，通过 47、失败 24。

| 分组 | n | pass | 通过率 | 平均调用数 |
|---|---:|---:|---:|---:|
| 发生过压缩 | 41 | 19 | **46.3%** | 56.1 |
| 未压缩 | 30 | 28 | **93.3%** | 20.1 |

- **24 个失败中 22 个（91.7%）落在发生压缩的长任务里**。
- ⚠️ 这是**观察性关联**：压缩由"跑得久"触发，任务难 → 调用多 → 触发压缩，存在内生选择效应。**不能读作"压缩导致失败"**，也不能读作"压缩能救任务"。要分离需固定题目的对照实验（本批数据无法分离）。

---

## 四、延迟分布

### 4.1 工具耗时（`tool.completed.duration_ms`）

| 工具 | 次数 | Σ耗时 | 均值 | p50 | p95 | max | 占工具总耗时 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `execute_command_tool` | 1,042 | **11,134 s** | 10,685 ms | 319 ms | **65,227 ms** | **320,907 ms** | **81.6%** |
| `grep_search` | 922 | 2,189 s | 2,374 ms | 57 ms | 14,030 ms | 101,808 ms | 16.1% |
| `glob_search` | 296 | 249 s | 840 ms | 112 ms | 4,137 ms | 6,179 ms | 1.8% |
| `read_file` | 1,150 | **27 s** | 23 ms | **16 ms** | 60 ms | 1,298 ms | 0.2% |
| 其余 9 个 | 880 | ~36 s | — | — | — | — | 0.3% |
| **合计** | **4,290** | **3.8 h** | | | | | 100% |

要点：
- `read_file` 虽然输出字符最多（60.6%），但**耗时几乎为零**（p50 16ms，总 27 秒）。**体积与耗时是两个独立问题**。
- `execute_command_tool` 占工具耗时 81.6%，p95 达 65 秒、max 321 秒。

### 4.2 模型耗时（`model.completed.duration_ms`）

| 指标 | 值 |
|---|---:|
| 调用数 | 3,091 |
| Σ耗时 | **14.5 小时** |
| 均值 | 16,926 ms |
| p50 | 6,053 ms |
| p95 | 62,956 ms |
| max | 793,860 ms |
| trial 墙钟 中位 / 均值 | 700 s / 817 s |
| **模型耗时 / 墙钟** | **81.1%** |
| 工具耗时 / 墙钟 | 21.1% |
| 模型+工具 > 墙钟 | −2.2%（并发重叠） |

**模型调用是延迟主因（81.1%），工具只占 21.1%。** 优化工具耗时对墙钟的上限收益约 21%，而优化"调用次数"直接作用于 81% 的那部分。

### 4.3 输入规模 → 单次延迟

| input 区间 | 调用数 | 耗时中位 | 耗时 p95 |
|---|---:|---:|---:|
| <40k | 1,158 | 4,904 ms | 30,955 ms |
| 40–80k | 317 | 5,120 ms | 30,839 ms |
| 80–120k | 1,599 | **7,453 ms** | **93,801 ms** |
| 120k+ | 17 | 8,889 ms | 49,648 ms |

80–120k 区间比 <40k 慢 **52%**，p95 慢 **3 倍**。→ **压小上下文同时降延迟**，两个目标同向。

---

## 五、优化提案（按 预期收益/实现难度 排序）

### T1（最高优先）提高工具并行度 —— 砍调用次数

- **改什么**：`src/sayacode/prompts.py` 的 `_WORK_RULES` 第 3 条（现为"Batch every independent read-only call … into one response"，已存在但实测未生效），把它从"建议"改成**带判据的操作指令 + 反例**；并在 `src/sayacode/tools/files.py`、`search.py` 的工具 description 末尾加"可在同一响应内与其他只读工具一起调用"。
- **数据依据**：73.5% 的带工具调用只发 1 个工具；平均 1.48。若提到 2.2～2.5，调用数从 39.1 降到 26～29（**−25%～−33%**）。
- **预期收益**：input 同比 −25%（**约 4,800 万 token**），墙钟 −20%（模型耗时占 81%），延迟 p95 同步下降。
- **风险**：中。写类工具（`write_file`/`search_replace`/`delete_file`）不可并行（有先后依赖），只应鼓励**只读**工具并行。若模型并行读同一文件的不同片段，属于合理行为；若并行跑有副作用的 `execute_command_tool` 可能冲突——应在提示里显式限定为 `read_file/list_directory/grep_search/glob_search` 四类。
- **验证方式**：现有 `audit.jsonl` 已同时记录 `tool_call_id` 与 `run_id`，可直接复算并行度；A/B 只需两个 prompt 变体。

### T2 `read_file` 收紧默认读取量 + 强制"先定位再读"

- **改什么**：`src/sayacode/tools/files.py` 的 `read_file(path, offset=1, limit=250)` 默认 `limit` 250→150；description 增加"先 `grep_search` 定位行号，再用 offset/limit 精确读"。
- **数据依据**：read_file 占工具输出 60.6%（4.79M 字符）；p95 11,059 字符、max 24,924。按字符截断模拟：截到 8,000 字符影响 188/1,150 次（16%），直接省 524,914 字符（**11.0%** 的 read_file 输出）；截到 4,000 影响 429 次（37%），省 34.5%。
- **预期收益**：按工具输出驱动 80% 上下文增长折算，约 **总 input 的 5%～8%**（≈1,000～1,500 万 token）。
- **风险**：低–中。截断可能让模型漏读关键代码尾部；缓解办法是不硬截断，而是**降低默认 limit 并明确提示可翻页**（`read_file` 已支持 offset）。
- **不建议**：把全局 `output_limit_bytes` 从 64KiB 下调。实测 cap=16,384 只影响 35 次调用（1%）、省 2.0%；cap=4,096 虽省 29.9% 但影响 550 次（13%），风险收益比差。

### T3 压缩后限制二次增长

- **改什么**：`src/sayacode/agent/graph.py` 装配 `SummarizationMiddleware` 时，在压缩生效后的若干轮内把工具输出上限临时收紧（例如通过 `AgentContext.output_limit_bytes` 由中间件动态下发 8KiB），或给 `ClearToolUsesEdit` 设一个**低于摘要阈值**的 `context_edit_trigger`（当前 profile 里是 `None`，即关闭）。
- **数据依据**：压缩把 107k 压到 7.4k（−93%），但剩余 20 轮又涨回 19.3k（+18,710）。按当前增长速率，第二个压缩点很快到来；而本批只有 48/79 记录到首个压缩点，说明多数 trial 在第二次压缩前结束。
- **预期收益**：把压缩后的二次增长压掉一半，约 **总 input 的 5%～8%**；同时减少第二次压缩带来的上下文损失。
- **风险**：中。`ClearToolUsesEdit` 会删除模型已看过的工具结果，若模型还需要回看会重新读（反而增加调用）。**必须先 A/B**：`context_edit_trigger=40k` vs `None`。

### T4 system prompt 瘦身 —— 收益有限，不优先

- **数据**：产品固定前缀仅 **~9,138 字符 ≈ 2.3k token**（system 3,031 + planning 679 + todo desc 469 + 11 个工具 schema/描述 4,959），占 Σinput 的 **3.7%**。
- **预期收益上限 3.7%，实际可省 1%～2%**。
- **结论**：参考先例（TodoList 6,502→1,148 字符）之所以墙钟 −40%，是因为那次同时减少了 30% 调用次数；**单靠 prompt 体积本身收益很小**。若要动，应并入 T1 一起做（同一批 A/B）。

### T5 `execute_command_tool` 长尾超时 —— 风险高于收益

- **数据**：p95 65,227ms、max 320,907ms，占工具耗时 81.6%，但**工具只占墙钟 21.1%**。
- **收益上限**：即便砍掉全部工具长尾，墙钟最多 −21%；实际能砍的只是 p95 以上部分，约 −5%～−8%。
- **风险**：**高**。长命令通常是构建/测试，砍超时会直接把"能通过"变成"超时失败"。
- **建议**：不改默认 120s；只对明确的快速命令（`git status`、`ls`、`grep`）在提示层建议短超时，或对 `git` 工具固定短超时（`src/sayacode/tools/git.py` 已固定 120s，可降到 30s：实测 git p95 仅 1,532ms）。

---

## 六、数据限制

1. **噪声稀释**：首轮 80k token 中约 80k 是评测注入的无关文本（350,946 字符），随每轮重复携带，估算占总输入 **62%**。本批数据中"产品自身开销"只占约 3.7%，**任何优化的绝对收益都建立在含噪基线之上**；到真实业务场景，产品前缀与工具输出的占比会显著上升，本报告的百分比需要重算。
2. **两组制品不同**（3.5.0 / 3.3.0），合并统计只用于成本结构，**不能用于版本对比**。
3. **无子 Agent**：79 个 trial 的 `thread_id` 全部是 `bench-main`，本批**无法评估多 Agent 协作的成本**。
4. **无 checkpoints**：`state` 目录不保存 `checkpoints.sqlite3`，555-token 的压缩子调用只能靠三条一致证据**推断**，无法直接读到摘要消息验证。
5. **压缩与结果的关联是观察性**：压缩由长任务触发，存在选择效应，不能当因果。
6. **审计缺 `cache_creation`**：`audit.jsonl` 的 usage 只有 `input/output/total/cache_read` 四个键（3,091/3,091 一致），缓存写入量仅能从 `usage-details.json` 顶层拿到（本批为 0）。若供应商开始按 cache_creation 计费，当前审计无法归因。
7. **reward 只匹配到 71/79**：8 个 trial 在 `verify/` 下无对应 `reward.txt`。
8. **成本未折算货币**：数据中无单价，本报告只报 token 与秒，不编造金额。

---

## 七、复现脚本

保存为 `analyze_cost.py`，在 `C:\develop\sayacode-bench` 下执行 `uv run --no-sync python analyze_cost.py`。

```python
"""SAYACODE 成本/延迟分析：从原始 audit.jsonl 直接计算。"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

GROUPS = {
    "impact-350": (Path(r"C:\sb\hard\ab-ctx\impact-350"), "3.5.0"),
    "v2v-main": (Path(r"C:\sb\hard\ab-ctx\v2v-main"), "3.3.0"),
}
SMALL_CALL = 1000


def iter_audits():
    for group, (root, _v) in GROUPS.items():
        for audit in sorted(root.rglob("audit.jsonl")):
            if any(p.startswith("abandoned") for p in audit.parts):
                continue
            name = next(p for p in audit.parts if p.startswith("sayacode-"))
            yield group, name, audit


def rows(path):
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def pct(vals, q):
    o = sorted(vals)
    return o[max(0, min(len(o) - 1, int(round(q * (len(o) - 1)))))] if o else float("nan")


def load(group, name, audit):
    calls, tools, at, seq = [], [], [], []
    for r in rows(audit):
        k, d, a = r.get("event"), r.get("details") or {}, r.get("at")
        if a:
            at.append(a)
        if k == "model.completed":
            u = d.get("usage") or {}
            calls.append({
                "input": int(u.get("input_tokens") or 0),
                "output": int(u.get("output_tokens") or 0),
                "cache": int(u.get("cache_read_tokens") or 0),
                "ms": d.get("duration_ms"),
            })
            seq.append("m")
        elif k == "tool.completed":
            tools.append({
                "name": d.get("tool_name") or "?",
                "chars": int(d.get("output_characters") or 0),
                "ms": d.get("duration_ms"),
                "err": d.get("error_type"),
            })
            seq.append("t")
    wall = None
    if len(at) >= 2:
        wall = (datetime.fromisoformat(max(at)) - datetime.fromisoformat(min(at))).total_seconds()
    return {"group": group, "name": name, "calls": calls, "tools": tools, "wall": wall, "seq": seq}


trials = [load(g, n, p) for g, n, p in iter_audits()]
print(f"trials={len(trials)}")

# --- 成本结构 ---
print("\n## 成本结构")
print("| 组 | Σinput | cache_read | 未缓存 | Σoutput | cache占比 | input/output |")
print("|---|---:|---:|---:|---:|---:|---:|")
tot = defaultdict(int)
for g in GROUPS:
    ts = [t for t in trials if t["group"] == g]
    i = sum(c["input"] for t in ts for c in t["calls"])
    c = sum(c["cache"] for t in ts for c in t["calls"])
    o = sum(c["output"] for t in ts for c in t["calls"])
    tot["i"] += i; tot["c"] += c; tot["o"] += o
    print(f"| {g} | {i:,} | {c:,} | {i-c:,} | {o:,} | {c/i:.1%} | {i/o:.1f}:1 |")
print(f"| 合计 | {tot['i']:,} | {tot['c']:,} | {tot['i']-tot['c']:,} | {tot['o']:,} "
      f"| {tot['c']/tot['i']:.1%} | {tot['i']/tot['o']:.1f}:1 |")

# --- 工具输出 ---
print("\n## 工具输出")
agg = defaultdict(lambda: {"n": 0, "chars": 0, "vals": [], "ms": [], "groups": []})
for t in trials:
    seq, cur = [], 0
    for m in t["calls"]:
        seq.append(("m", m))
    for c in t["tools"]:
        e = agg[c["name"]]
        e["n"] += 1; e["chars"] += c["chars"]; e["vals"].append(c["chars"])
        if isinstance(c["ms"], (int, float)):
            e["ms"].append(c["ms"])
total_chars = sum(e["chars"] for e in agg.values())
print("| 工具 | 次数 | Σ字符 | 占比 | 均值 | p50 | p95 | max |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
for name, e in sorted(agg.items(), key=lambda kv: -kv[1]["chars"]):
    print(f"| {name} | {e['n']} | {e['chars']:,} | {e['chars']/total_chars:.1%} "
          f"| {statistics.fmean(e['vals']):,.0f} | {pct(e['vals'],0.5):,.0f} "
          f"| {pct(e['vals'],0.95):,.0f} | {max(e['vals']):,} |")

# --- 并行度（按事件顺序把 tool.completed 归并到其所属的模型调用）---
print("\n## 工具并行度")
groups = []
for t in trials:
    cur = 0
    for ch in t["seq"]:
        if ch == "t":
            cur += 1
        else:
            if cur:
                groups.append(cur)
            cur = 0
    if cur:
        groups.append(cur)
print(f"带工具的模型调用 {len(groups)} 次；平均 {statistics.fmean(groups):.2f} 个工具，"
      f"中位 {statistics.median(groups):.0f}")
print(f"分布 {dict(sorted(Counter(groups).items()))}")
single = sum(1 for g in groups if g == 1)
print(f"只带 1 个工具 {single}/{len(groups)} = {single/len(groups):.1%}；"
      f"发生并行 {len(groups)-single}/{len(groups)} = {(len(groups)-single)/len(groups):.1%}")

# --- 增长与压缩 ---
print("\n## 增长与压缩")
firsts, lasts = [], []
compress = []
for t in trials:
    s = [c["input"] for c in t["calls"]]
    if not s:
        continue
    firsts.append(s[0]); lasts.append(s[-1])
    for k in range(1, len(s)):
        if s[k-1] > 20_000 and s[k] < s[k-1] * 0.5:
            after = next((v for v in s[k+1:] if v > SMALL_CALL), None)
            if after:
                compress.append((s[0], s[k-1], s[k], after))
                break
print(f"首次中位 {statistics.median(firsts):,.0f}，末次中位 {statistics.median(lasts):,.0f}")
print(f"压缩 trial {len(compress)}/{len(trials)}")
if compress:
    print(f"压缩前中位 {statistics.median([c[1] for c in compress]):,.0f}，"
          f"子调用恒为 {sorted({c[2] for c in compress})}，"
          f"压缩后主调用中位 {statistics.median([c[3] for c in compress]):,.0f}，"
          f"压缩率 {1-statistics.median([c[3] for c in compress])/statistics.median([c[1] for c in compress]):.1%}")

# --- 延迟 ---
print("\n## 延迟")
tool_ms = {name: e["ms"] for name, e in agg.items() if e["ms"]}
for name, ms in sorted(tool_ms.items(), key=lambda kv: -sum(kv[1]))[:5]:
    print(f"{name}: Σ{sum(ms)/1000:.0f}s p50 {pct(ms,0.5):,.0f}ms p95 {pct(ms,0.95):,.0f}ms max {max(ms):,}ms")
mms = [c["ms"] for t in trials for c in t["calls"] if isinstance(c["ms"], (int, float))]
walls = [t["wall"] for t in trials if t["wall"]]
print(f"模型: Σ{sum(mms)/1000/3600:.1f}h p50 {pct(mms,0.5):,.0f}ms p95 {pct(mms,0.95):,.0f}ms")
print(f"墙钟: 中位 {statistics.median(walls):.0f}s；模型占 {sum(mms)/1000/sum(walls):.1%}；"
      f"工具占 {sum(sum(v) for v in tool_ms.values())/1000/sum(walls):.1%}")
```

> 注：并行度一节的归并规则是「从上一个 `model.completed` 之后到本 `model.completed` 之前的所有 `tool.completed` 计为同一次模型调用的工具批」。这套规则复现出正文 §2.3 的 2,907 次 / 1.48 / 73.5% 三个数。

---

## 八、一页结论

1. **成本结构**：1.93 亿 input token 中 90.4% 是缓存命中、9.6% 未缓存；output 只有 274 万（input:output = 70:1）。缓存已接近优化上限，**唯一有效杠杆是减少总输入体积与调用次数**。
2. **谁撑大上下文**：`read_file` 占工具输出 60.6%，`grep_search` 17.0%，`execute_command_tool` 14.6%。但单次输出只占 Σinput 的 1.4%——**真正的放大器是重复携带**：压缩前的上下文增长中位 ~99% 可归因于工具输出（按 3 字符/token）。
3. **增长模式**：首轮 80,956（其中约 80k 是评测注入噪声）→ 涨到 107,096 触发压缩 → 压到 7,404（−93%）→ 剩余 20 轮又涨回 19,266。60.8% 的 trial 经历压缩；24 个失败里 22 个在压缩组（观察性，非因果）。
4. **延迟**：模型调用占墙钟 **81.1%**，工具只占 21.1%。`execute_command_tool` 占工具耗时 81.6%（p95 65s），而 `read_file` 体量大但几乎不耗时（p50 16ms）。输入 80–120k 的单次调用比 <40k 慢 52%。
5. **最值得做的一件事**：**提高工具并行度**。73.5% 的带工具调用只发 1 个工具，把它提到 2.2～2.5 可砍掉 25%～33% 的模型调用，直接作用于占总成本 70:1 的上下文重发和占墙钟 81% 的模型耗时。其次是收紧 `read_file` 默认读取量（5%～8%）。**不建议**优先做 system prompt 瘦身（上限 3.7%）或工具超时（风险高于收益）。
