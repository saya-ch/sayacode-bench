# OpenCode 基线接入（2026-11-05）

## 为什么加

v2 的第三基线 Codex 因适配缺陷整组作废（`docs/CODEX-BASELINE-INVALID.md`），已由 Claude Code 替换。
OpenCode 作为第四个基线加入，用于和另外三个可用基线做同模型下的脚手架对比。

## 与 Claude Code 的对称性

| 维度 | Claude Code | OpenCode |
|---|---|---|
| 协议 | `/v1/messages`（Magpie 原生 Anthropic） | `/v1/chat/completions`（Magpie 原生 OpenAI 兼容） |
| 模型 | `auto-hy3` | `openai/auto-hy3` |
| 安装 | 宿主预置 2.1.311 linux 二进制（126.7MB） | 宿主预置 1.19.5 linux 二进制（79.1MB） |
| 工具契约 | Edit/Write/Bash 由 CLI 自带 | 由 CLI 自带（tool part 直接落在 stdout JSON） |
| 容器依赖 | 无 node/npm | 无 node/npm |

## 安装细节

```powershell
# 一次性：宿主下载 linux-x64 原生包（npmmirror 可达）
npm pack opencode-linux-x64@1.19.5 --registry=https://registry.npmmirror.com --pack-destination C:\sb\tmp\hard
# => C:\sb\tmp\hard\opencode-linux-x64-1.19.5.tgz（79,136,190 B，内含 package/bin/opencode）
```

每 trial 的 `install()` 只做「上传 → 解压 → install -m 755 → `opencode --version`」，不访问网络。

## 注册（`scripts/locked_agents.py`）

- `AGENTS = ("sayacode", "mini-swe", "claude-code", "opencode")`
- `LockedOpenCode(OpenCode)`：覆盖 `install`（预置二进制）与 `run`（收尾抓 `model.patch`），
  `exec_as_agent` 给 `opencode` 调用套沙箱内 timeout。
- `build_agent("opencode")`：`model_name="openai/auto-hy3"`，
  `env={"OPENAI_API_KEY": "magpie", "OPENAI_BASE_URL": IN_SANDBOX_GATEWAY + "/v1", ...}`。
- 二进制路径可用 `SAYACODE_OPENCODE_TARBALL` 覆盖。

## 实测结果（80 trial，与另外三组同题集/同模型/同口径）

| 口径 | OpenCode |
|---|---|
| planned | 75.0%（60/80） |
| observed | 75.0% |
| **strict**（扣改 `.snap` 的 pass） | **67.5%**（54/80） |
| 缺失 | 0 |
| 题级 task-macro | 75.0%，bootstrap95 [65.0, 83.8] |
| 题级全通过 | 23/40 = 57.5% |

- **OpenCode 的 snap pass 是四组里最多的（6 个）**，planned→strict 掉 7.5pp；说明它更倾向改快照而不是改产品代码。
- 轨迹健康：80/80 trial 有 `tool_use`（共 2480 次），**0 API Error / 0 unsupported call / 0 websocket 405 / 0 unrecognized_model**。
- 配对：vs SAYACODE delta −3.8%、McNemar p=0.070（未过 Bonferroni，是四组里最接近显著的一对）；vs mini-swe p=0.118；vs Claude Code p=0.607。

## 诚实限制

- **OpenCode 没有「原生模型」**：它是开源、provider-agnostic 的脚手架，接入任意 provider 都是其常规用法，
  所以这里接 `auto-hy3` **不构成模型错配**（这点和 Claude Code / Codex 本质不同）。
  它的低分更可能来自脚手架自身的重量（默认工具 / skills / slash-commands 更多、system prompt 更长、
  agent loop 探索轮次更多）以及 6 个 snap pass 所反映的「改快照而非改产品代码」倾向。
- 单题内存峰值约 3.9GB（vuls），必须走高内存分片（`split_sample.py` + 并发 1），否则会打爆 WSL 7GB。
