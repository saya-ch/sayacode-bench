# Claude Code 基线替换（2026-11-04）

> 结论：v2 对照评测的第三个基线由 **Codex CLI 换为 Claude Code**。理由、可行性验证、
> 剩余限制与复现步骤全部记录在此。

## 一、为什么换

`docs/CODEX-BASELINE-INVALID.md` 已证明 Codex 组**不可比**：

- `unsupported call: apply_patch` 影响 **78/80 trial**（373 次）——system prompt 要求用
  `apply_patch`，运行时却未下发该工具；
- `/v1/responses` websocket **405** 影响 **80/80 trial**（960 次重连）；
- 模型统一为 `auto-hy3`（DeepSeek-V4.1-Flash），不是 Codex 调优的 OpenAI 模型。

因此 68.75%（严格 65.0%）只能作为「本次适配条件下的观测值」。

## 二、为什么 Claude Code 能修掉这些问题

| 维度 | Codex（坏） | Claude Code（本次） |
|---|---|---|
| 协议 | `/v1/responses` websocket → nginx 405 → 回退 HTTPS | `/v1/messages` **Magpie 原生协议**，已实测带 tools 返回规范 `tool_use` |
| 工具契约 | `apply_patch` 未下发，78/80 trial 报错 | `init` 事件里 **Edit / Write / Bash / Read / Task 等全部下发**并由 CLI 自带实现 |
| 安装 | 容器内下载 tar.gz / apt，受网络影响 | **宿主预下载 linux-x64 原生二进制 tarball**，每 trial 上传解压；容器内零网络依赖 |
| 模型 | `auto-hy3` | `auto-hy3`（同模型，控制变量） |

### 实测证据（2026-11-04）

- 宿主 `ANTHROPIC_BASE_URL=http://127.0.0.1:3425` + `ANTHROPIC_MODEL=auto-hy3`：
  `claude -p` 返回 `PROBE_OK`（`unrecognized_model` 只是遥测警告，非错误）。
- 容器内单题 smoke（`instance_ansible__ansible-415e08c...`）：
  `claude-code install: rc=0 2.1.311` → `model.patch bytes: 2680` → **reward=1.0**（2分34秒）。
- `init` 快照：`"model":"auto-hy3"`，`apiKeySource=ANTHROPIC_API_KEY`，
  `permissionMode=bypassPermissions`，tools 列表完整。

## 三、踩到并修掉的一个真缺陷（nginx `$args` 拦截）

第一次 smoke 返回 `API Error: 400 Bad Request`（`patch=0B`），但宿主直连 Magpie 的
probe 是成功的 → 定位到 `src/sayacode_bench/network.py` 的网关规则：

```nginx
if ($args != "") { return 400; }
```

Claude Code SDK 会在 `/v1/messages` 上携带 beta query（如 `?beta=true`），被这条规则
一律 400。**已移除该拦截**；`location = /v1/messages` 仍是精确路径白名单，端点约束不变。
移除后 smoke 立即通过（reward=1.0）。`tests/test_network.py` 28 passed。

## 四、剩余限制（必须诚实标注）

1. **模型错配仍在**：Claude Code 的 system prompt / 工具契约围绕 Claude 模型调优，这里
   统一跑 `auto-hy3`。但这是**三组共同承受的控制变量**（SAYACODE / mini-swe /
   Claude Code 同模型、同题集、同预算），不像 Codex 那次是单向伤害。
2. **不能据此评价 Claude Code 产品能力**：测的是「Claude Code 脚手架 + hy3」，不是
   「Claude Code + Claude」。要评价产品需换原生模型（付费 API，超 ¥50 预算）。
3. **版本锁定**：二进制固定 `2.1.311`，由 `SAYACODE_CLAUDE_TARBALL` 指向宿主
   `C:\sb\tmp\hard\claude-linux.tgz`（126.7MB，来自 npmmirror 的
   `@anthropic-ai/claude-code-linux-x64@2.1.311`）。换版本需重新下载并改 tarball。
4. **`codex` 分支保留**在 `build_agent` 中，仅供 v2 历史结果复现；`AGENTS` 已改为
   `("sayacode", "mini-swe", "claude-code")`。

## 五、复现

```powershell
# 1) 宿主预下载二进制（一次性）
curl.exe -L -o C:\sb\tmp\hard\claude-linux.tgz `
  https://registry.npmmirror.com/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-2.1.311.tgz

# 2) 单题 smoke
uv run --no-sync python scripts/run_formal_240.py `
  --out C:\sb\tmp\explore\claude-smoke-out --repeats 1 --concurrency 1 `
  --agents claude-code --sample C:\sb\tmp\explore\claude-smoke-1.json

# 3) 正式 80 trial（20/40 题 × 2 重复）
uv run --no-sync python scripts/run_formal_240.py `
  --out C:\sb\hard\v2-325 --repeats 2 --concurrency 2 `
  --agents claude-code --skip-existing
```

环境变量：`ANTHROPIC_API_KEY=magpie`、`ANTHROPIC_BASE_URL=http://saya-model-gateway:8080`
（容器内网关；Harbor 会把 `ANTHROPIC_MODEL` 及 sonnet/opus/haiku/subagent alias
统一设为 `auto-hy3`）。

## 六、文件改动

- `scripts/locked_agents.py`：`AGENTS`、`LockedClaudeCode`、`build_agent("claude-code")`、
  `_CLAUDE_TARBALL`、`_CAPTURE_CLAUDE`。
- `src/sayacode_bench/network.py`：移除 `$args` 400 拦截。
- `tests/test_locked_agents.py`、`tests/test_adapter.py`：同步断言。
