# SWE-bench Pro V2 多方对照最终结果（2026-11-05）

> 题集：冻结 `studies/sample-40-final.json` 40 题 × 2 重复 = 80 trial/组
> 模型：统一 `auto-hy3`（**hy3**，WorkBuddy 网关；context 192k / max_output 64k，profile 配 32k）；同题集、同预算、同口径
> 验证器：官方 Harbor + SWE-bench Pro V2 verifier（`tests/test.sh` 重置测试代码表面）
> 口径：**planned**（缺失计失败）/ **observed**（排除缺失）/ **strict**（再扣「改 `__snapshots__/*.snap` 通过」的 pass）

> ⚠️ **2026-11-05 更正**：本文初版把 `auto-hy3` 标成「DeepSeek-V4.1-Flash」，**这是错的**。网关 `/v1/models` 显示 `auto/hy3`（owned_by `workbuddy`，192k/64k）与 `auto/deepseek-v4.1-flash`（owned_by `opencode-zen`，1M/200k）是**两个不同模型**；评测窗口内 42681 条 usage 记录里，四个基线的 `served` **全部是 `hy3` / `hy3-x`，没有任何 `deepseek-v4.1-flash`**（后者只出现在本机 DSH 会话）。详见 §五.6。

## 一、最终数字

| agent | planned | observed | **strict** | 缺失 | 题级 task-macro | bootstrap95 | 题级全通过 |
|---|---|---|---|---|---|---|---|
| **SAYACODE** | **78.8%** (63/80) | 79.7% | **78.8%** (63) | 1 | **80.8%** | [69.2, 91.0] | 29/39 = 74.4% |
| **mini-swe-agent** | 85.0% (68/80) | 86.1% | **80.0%** (64) | 1 | 87.2% | [79.5, 94.9] | 30/39 = 76.9% |
| **Claude Code** | 77.5% (62/80) | 78.5% | **73.8%** (59) | 1 | 78.2% | [67.9, 88.5] | 25/39 = 64.1% |
| **OpenCode** | 75.0% (60/80) | 75.0% | **67.5%** (54) | **0** | 75.0% | [65.0, 83.8] | 23/40 = 57.5% |
| ~~Codex CLI~~ | 68.8% | 68.8% | 65.0% | 0 | — | — | **不可比**（见下） |

### 两两配对（题级全通过，McNemar exact）

| 对比 | 共同题 | delta | a 独过 / b 独过 | p |
|---|---|---|---|---|
| Claude Code vs mini-swe | 38 | −7.9% | 3 / 7 | 0.344 |
| Claude Code vs SAYACODE | 38 | **0.0%** | 4 / 7 | 0.549 |
| Claude Code vs OpenCode | 39 | +3.8% | 9 / 6 | 0.607 |
| mini-swe vs SAYACODE | 38 | +7.9% | 6 / 5 | 1.000 |
| mini-swe vs OpenCode | 39 | +11.5% | 11 / 4 | 0.118 |
| **OpenCode vs SAYACODE** | 39 | **−3.8%** | 1 / 7 | **0.070** |

**四组两两差异全部不显著（p ≥ 0.070）**。四组共 **6 对**比较，Bonferroni 校正后 α/6 ≈ **0.0083**（即使按更宽松的 α/3 ≈ 0.017 也远未达到）；最接近显著的是 OpenCode vs SAYACODE（p=0.070）。bootstrap95 区间大幅重叠。

### 补跑前后同表（协议 §6 要求，缺此项即为选择性报告）

| agent | 补跑前 planned | 补跑后 planned | 增量 | 补跑条目的根因 |
|---|---|---|---|---|
| SAYACODE | 67.5% | **78.8%** | +11.3pp | TLS/apt/网络 |
| mini-swe | **70.0%**（56/80） | **85.0%**（68/80） | **+15.0pp** | **全部是安装期网络失败**（`apt-get exit 100` 撞 Clash fake-ip `198.18.0.17`、`NetworkConnectError`），agent 从未执行 |
| Claude Code | — | 77.5% | — | 单批跑完（首跑即含修复后的网络配置）|
| OpenCode | — | 75.0% | — | 单批跑完，零缺失 |

⚠️ **mini-swe 的 +15.0pp 必须一直带着看**：它的 85.0% / 80.0% strict 都是在补跑 12 条之后得到的；补的那 12 条按语义是 `infra`，不是能力。原始 `exception.txt` 证据在 `C:\sb\hard\v2-325\mini-swe\abandoned-retry-20261102-165011\`，分析见 [RETROSPECTIVE §5.6](RETROSPECTIVE-20261105.md)。

### 口径为什么重要（同一份数据，三种排名）

| 口径 | 排名 |
|---|---|
| planned | mini-swe 85.0% > SAYACODE 78.8% > Claude Code 77.5% > OpenCode 75.0% > Codex 68.8% |
| observed | mini-swe 86.1% > SAYACODE 79.7% > Claude Code 78.5% > OpenCode 75.0% > Codex 68.8% |
| **strict** | mini-swe 80.0% > **SAYACODE 78.8%** > Claude Code 73.8% > OpenCode 67.5% > Codex 65.0% |

- mini-swe 的 planned 85.0% 里有 **4 个 pass 是改 `.snap` 快照换来的**；strict 扣掉后 80.0%。
- **OpenCode 的 snap pass 最多（6 个）**，planned 75.0% → strict 67.5%（−7.5pp），是四组里被快照口径影响最大的。
- SAYACODE **0 个改快照**（strict = planned）。
- 因此「谁最强」完全取决于口径——**报告必须同时给三个口径，不给单一排名**。

### 四组的适配健康度（`scripts/audit_agent_traj.py`）

| agent | API Error | unsupported call | websocket 405 | tool_use |
|---|---|---|---|---|
| SAYACODE | 0 | 0 | 0 | — |
| mini-swe | 0 | 0 | 0 | — |
| Claude Code | **0** | **0** | **0** | 3468 tool_use / 3467 tool_result（**80/80 trial 完整覆盖**）|
| OpenCode | **0** | **0** | **0** | 2480 tool_use / 80 trial（其日志**不含** `tool_result` 事件，格式差异，配平检查对它不适用）|
| ~~Codex~~ | 960 | **373（78/80 trial）** | 960（80/80 trial） | apply_patch 不可用 |

四个可用基线的轨迹全部健康；只有 Codex 是整组失效。

## 二、Codex 组为何不可比

`docs/CODEX-BASELINE-INVALID.md` 有完整证据：

| 缺陷 | 影响面 | 次数 |
|---|---|---|
| `unsupported call: apply_patch`（system prompt 要求用，运行时未下发） | 78/80 trial | 373 |
| `/v1/responses` websocket 405 | 80/80 trial | 960 |
| 模型统一为 hy3（非 Codex 调优的 OpenAI 模型） | 全部 | — |

→ 其 68.8% / 65.0% 只能作为「本次适配条件下的观测值」，**不能用来宣称任何排名**。已由 Claude Code 替换为第三基线。

## 三、Claude Code 组的适配健康度（对照组：Codex）

| 信号 | Codex | Claude Code |
|---|---|---|
| API Error | 960 次 405 + 373 次 unsupported | **0** |
| unsupported call | 373 | **0** |
| tool_use / tool_result | apply_patch 全组不可用 | **3468 / 3467**（80/80 trial，完美配平） |
| unrecognized_model | — | 80（遥测警告，无害） |

**Claude Code 这组数据可安全用于同口径比较。**

## 四、本轮修复的真实缺陷（全部有证据）

| # | 缺陷 | 影响 | 修复 |
|---|---|---|---|
| 1 | nginx `if ($args != "") { return 400; }` 拦掉 Claude Code 的 `?beta=true` | Claude Code 首个请求即 400，0 通过 | `network.py` 移除该拦截（精确路径白名单保留） |
| 2 | Clash fake-ip 的 CNAME 陷阱：`deb.debian.org` → `debian.map.fastlydns.net` | 容器内 DNS 返回 198.18.x 死 IP，apt 全失败 | fake-ip-filter 加 `+.fastlydns.net`（`*.` 只匹配一级子域） |
| 3 | mini 镜像的 apt 源是 `us-west-2.ec2.archive.ubuntu.com` | sed 未匹配 → 换清华源失败 | 改通用正则换清华 HTTPS 镜像 |
| 4 | Debian 12 PEP 668 保护系统 Python | `pip3 install uv` 被拒 | `pip3 install --break-system-packages` |
| 5 | uv 下载 CPython 3.12 走 GitHub 超时 | mini 全组安装失败 | 宿主预下载 tarball 上传解压到 `/opt/uv-python` |
| 6 | vuls 单题 3.3GB × 并发 2 打爆 WSL 7GB | 跑批被宿主 OOM 静默杀死（日志只剩心跳行） | `split_sample.py` 分片 + 重题并发 1 |
| 7 | 缺镜像被误删（ghcr.io 拉取 EOF） | 2 trial 无法起容器 | 重试拉取（第 4 次成功） |
| 8 | `test_adapter.py` 断言 `"curl " not in` 过宽 | 全量测试红 | 改为精确检测 curl 下载调用 |

## 五、必须诚实标注的限制

1. **各组的模型适配前提不同，必须分开说清**（不能用一句「都非为 hy3 调优」糊过去）：
   - **Claude Code**：Anthropic 自家产品，system prompt / 工具契约围绕 Claude 模型深度调优 → 跑 hy3 有**方向性适配损耗**。
   - **Codex CLI**：OpenAI 自家产品，同理（且还叠加了工具契约与协议缺陷，整组作废）。
   - **OpenCode**：**开源、provider-agnostic**，设计上就接入任意模型（Anthropic/OpenAI/Google/OpenRouter 等），**接 hy3 是它的常规用法，不存在「对自家模型的偏好」**。它的低分不能归因于模型错配，更可能来自脚手架自身的重量（默认工具/skills/slash-commands 更多、system prompt 更长、agent loop 探索轮次更多）以及 **6 个 snap pass（四组最多）**所反映的行为倾向。
   - **mini-swe-agent**：模型无关的最简脚手架，短任务上几乎无额外故障面。
   - **SAYACODE**：prompt / 摘要降级 / 输出预算等围绕 hy3 所在网关打磨过（这是它的现实优势），但同时自带相应复杂度。
   因此「四组同模型」只统一了**模型变量**，没有统一**脚手架-模型适配度**；组间比较有意义，但**不能据此评价任一产品的真实能力**。
2. **40 题样本功效不足**：检测 10pp 需约 330 题（`docs/MULTI-MODEL-PLAN.md` 口径）。当前 CI 宽 ±12pp，任何「更强」都谈不上。
3. **strict 口径下 OpenCode 最低（67.5%）、Claude Code 次低（73.8%）**，但 planned 口径下差距都缩到 2–5 个 pass；四组配对 McNemar 全不显著（最接近的 p=0.070）。
4. **v2 的 Codex 组与 v3/v4 四组不同口径**：Codex 组因适配缺陷整体作废，不参与排名。
5. **未做的对照**：任一 agent + 其原生模型（付费 API，超 ¥50 预算）；同题集上的 holdout 提示词检验。
6. **模型身份与 served 分布（2026-11-05 更正 + 新披露）**：
   - 实跑模型是 **hy3**（`auto-hy3` 组，网关 `owned_by=workbuddy`，192k/64k），**不是 DeepSeek-V4.1-Flash**。
   - 评测窗口（2026-10-31 ~ 11-05）内 Magpie `usage.jsonl` 共 42681 条请求，按 agent 分组的 served 分布：

     | agent（usage 里的 agent 名） | hy3 | hy3-x | 其他 | hy3-x 占比 |
     |---|---|---|---|---|
     | `langchain-anthropic`（SAYACODE）| 6879 | 1144 | 3 | **14.3%** |
     | `litellm`（mini-swe）| 3947 | 2145 | 0 | **35.2%** |
     | `claude`（Claude Code）| 3082 | 326 | 13 | **9.6%** |
     | `opencode`（OpenCode）| 2333 | 130 | 84 | **5.3%** |
     | ~~`codex`~~ | 6157 | 2566 | 1 | 29.4% |

   - 历史记录称 `workbuddy/hy3`、`workbuddy-ai/hy3`、`workbuddy/hy3-x` 是**同一个 hy3 模型**的不同额度来源/地区版本（`ROUTING-DRIFT-20261029.md:60`，用户确认；非网关元数据证明）。
   - **但 hy3-x 占比在四组间差 6 倍（5.3% ~ 35.2%）**，这是一个未被控制的组间混杂因素：若 hy3-x 在能力或配额策略上与 hy3 有差异，会混进组间差。目前没有证据说它不同，也没有证据说相同——**必须在结论里披露**。
   - 网关元数据未标注 hy3 的厂商；`ROUTING-DRIFT` 记作「腾讯 hy3」，非独立验证，引用需注明来源。

## 六、可写进简历的口径（保守版）

> 「独立开发 SAYACODE（LangGraph/LangChain 1.x，PyPI 发布）。在 SWE-bench Pro V2（40 题 × 2 重复，官方 Harbor 验证，模型 hy3）上 pass@1 **78.8%**（strict 口径同为 78.8%，0 个改快照通过），与 mini-swe-agent（80.0% strict）、Claude Code（73.8% strict）、OpenCode（67.5% strict）**同量级，题级 McNemar 均不显著**（p ≥ 0.070）。单任务成本 1.43M tokens。建设可复现评测体系（三口径分母、缺失分类、题级统计、结果对账、指标 lint、轨迹级适配审计），并通过轨迹归因定位修复 5 个产品缺陷与 8 个评测基建缺陷。」

**不能写**：「优于 Codex / 优于 Claude Code / 优于 OpenCode / SOTA」。

## 七、产物

- 汇总：`C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json`、`STRICT-COMPARE.json`、`TRAJ-AUDIT-claude-code.json`、`TRAJ-AUDIT-opencode.json`
- 工具：`scripts/strict_compare.py`、`scripts/audit_agent_traj.py`、`scripts/split_sample.py`
- 文档：`docs/CODEX-BASELINE-INVALID.md`、`docs/CLAUDE-CODE-BASELINE.md`、`docs/OPENCODE-BASELINE.md`
- 日志：`C:\sb\hard\v2-325\logs\{claude-light,claude-heavy,opencode-light,opencode-heavy,verify-final5}.log`
