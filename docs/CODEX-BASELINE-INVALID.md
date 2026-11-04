# Codex 基线适配缺陷（2026-11-04 复核发现）

> 结论：v2 对照评测里的「Codex CLI」**不是可用状态的 Codex**。它被换成非原生模型、砍掉主编辑工具、跑在不支持的协议上。
> 因此 **68.75%（55/80）不能代表 Codex 产品能力**，三组对照中该基线不可比。

## 一、证据（全部来自 `C:\sb\hard\v2-325` 落盘轨迹）

| 缺陷 | 影响面 | 总次数 |
|---|---|---|
| `codex_core::tools::router: error=unsupported call: apply_patch` | **78 / 80 trial** | **373 次** |
| `responses_websocket ... 405 Method Not Allowed, url: ws://saya-model-gateway:8080/v1/responses` | **80 / 80 trial** | **960 次** |
| `Falling back from WebSockets to HTTPS transport` | **80 / 80 trial** | — |

按 reward 分组（通过组也中招，说明是系统性缺陷而非个别失败）：

| reward | trial 数 | 含 apply_patch 错误 | 平均错误次数 |
|---|---|---|---|
| 1（通过） | 55 | 53 | 4.5 |
| 0（失败） | 24 | 24 | 4.8 |
| 无 reward | 1 | 1 | 13.0 |

### 模型身份（`config.json` 实测）

```json
{
  "import_path": "locked_agents:LockedCodex",
  "model_name": "auto-hy3",
  "kwargs": {
    "reasoning_effort": "high",
    "web_search": "disabled",
    "config": {"model_context_window": 192000, "model_max_output_tokens": 32000}
  },
  "env": {
    "OPENAI_BASE_URL": "http://saya-model-gateway:8080/v1",
    "OPENAI_API_BASE": "http://saya-model-gateway:8080/v1"
  }
}
```

`auto-hy3` 是 Magpie 网关上的 **DeepSeek-V4.1-Flash** 别名（`locked_agents.py: CANONICAL_MODEL = "auto-hy3"`）。
三个 agent 统一用它，是「控制变量」设计；但 Codex CLI 的 system prompt、工具契约与推理格式是围绕 OpenAI 模型写死的。

### 轨迹原文（`agent/codex.txt`）

- Codex 的 system prompt 明确要求：「Use the `apply_patch` tool to edit files (NEVER try `applypatch` or `apply-patch`, only `apply_patch`)」。
- 实际下发给模型的函数列表只有：`exec_command`, `write_stdin`, `request_user_input`, `view_image`, `multi_agent_v1__*`, `get_goal`, `create_goal`, `update_goal` —— **没有 `apply_patch`**。
- 模型每轮都要重新推理这件事，然后改走 shell heredoc / python 脚本编辑文件：

> "Looking at the tools, I see: exec_command, write_stdin, ... There's no `apply_patch` tool! The instructions say to use `apply_patch` but it's not in my available functions."
> "The `apply_patch` tool isn't available in this environment, so I'll edit files via shell. Let me apply the proxy changes with a Python script."

## 二、归因：三重错配

1. **模型错配**：为 OpenAI 模型调优的 prompt / 工具 schema / reasoning 格式，套在 hy3 上。
2. **工具契约错配**：prompt 强制 `apply_patch`，运行时却不提供该工具 —— 主编辑路径从头到尾不可用，78/80 trial 共 373 次报错，模型被迫绕路。
3. **协议错配**：Codex 优先走 `/v1/responses` websocket，网关 nginx 返回 405，每次 5 次重连后回退 HTTPS；80/80 trial 都付出这部分延迟与重试预算。

**这解释了「为什么 24 个失败都有正常大小 patch」（中位 5551B、零空 patch）**：Codex 跑完了、改了文件，但主武器不可用 + 模型不认识契约，改错/改不全的概率被系统性抬高。

**也解释了用户更早的质疑**「一个只会 bash 的基线怎么会比 Codex 强」：mini-swe 的裸 bash 是模型无关的最短路径，SAYACODE 的 prompt 是围绕 hy3 磨过的；只有 Codex 是「外来户」，统一模型这个看似公平的设计恰恰把最依赖自家模型的 agent 打残。

## 三、影响与口径

- **v2 主表里的 Codex 68.75%（严格 65.0%）作废为「能力结论」**，只能作为「本次适配条件下的观测值」。
- 三组对照（SAYACODE / mini-swe / Codex）**不构成对 Codex 产品的公平比较**；任何「优于 Codex」「不输 Codex」的表述都不可用。
- 之前写进 `docs/FORMAL-RESULTS-20261102-v2.md` / `DEEP-DIVE-20261102.md` 的 Codex 相关推论需加本注记。

### 不能说的

- 不能推断「修好适配后 Codex 会到 X%」——没有数据。
- 不能说「Codex 产品弱」，也不能说「Codex 其实很强」——本次实验测不到。
- 不能用「补跑 3 个超时 trial」来修：缺陷是 **78/80 + 80/80 的全组系统性**问题，且其中 2 个已有 `reward=0`（有效失败），只补这几个等于 retry-until-pass。

## 四、处置选项

1. **报告口径（零成本，当前采用）**：把 Codex 组标为「适配缺陷、不可比」，只报 SAYACODE 与 mini-swe 的同口径对比，并给 Codex 观测区间（55/80 = 68.75%，3 个基建缺陷项不计则 55/77 = 71.4%，上界 58/80 = 72.5%）。
2. **修适配后整组重跑（¥0，几小时）**：关 websocket 强制（或让网关支持 upgrade）、把 `apply_patch` 工具映射补进 Codex 运行时；因这会改变 `request_sha256` 输入身份，**必须整组重跑 80 trial**，不能只补失败项。
3. **换原生模型（需付费 API）**：让 Codex 用它调优的 OpenAI 模型，另两组也换 —— 但会破坏「同模型」控制变量，且超出 ¥50 预算。

## 五、复现

- 缺陷统计：`C:\sb\tmp\explore\audit_codex3.py`（扫 `agent/codex.txt`）。
- 失败 patch 分布：`C:\sb\tmp\explore\audit_codex2.py`。
- verifier 合法性反查：`C:\sb\tmp\explore\audit_mini2.py`（确认 mini 补跑回放的是 agent patch、verifier 重置测试表面）。

## 六、方法论教训

- **「统一模型」不等于公平**：对「为特定模型深度调优的商业 agent」，统一到第三方模型会引入方向性偏差；控制变量必须同时报告每个 agent 的原生适配前提。
- **必须校验工具契约**：agent 的 system prompt 要求什么工具，运行时就得真的下发什么工具；否则测的是「缺胳膊的 agent」。
- **必须扫全量轨迹**：只看 `exception.txt` 会以为只有 3 个 trial 出问题；扫 `agent/codex.txt` 才发现 78/80 + 80/80 的系统性缺陷。
