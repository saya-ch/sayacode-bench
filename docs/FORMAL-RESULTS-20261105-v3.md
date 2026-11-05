# SWE-bench Pro V2 三方对照最终结果（2026-11-05）

> 题集：冻结 `studies/sample-40-final.json` 40 题 × 2 重复 = 80 trial/组
> 模型：统一 `auto-hy3`（DeepSeek-V4.1-Flash）；同题集、同预算、同口径
> 验证器：官方 Harbor + SWE-bench Pro V2 verifier（`tests/test.sh` 重置测试代码表面）
> 口径：**planned**（缺失计失败）/ **observed**（排除缺失）/ **strict**（再扣「改 `__snapshots__/*.snap` 通过」的 pass）

## 一、最终数字

| agent | planned | observed | **strict** | 缺失 | 题级 task-macro | bootstrap95 | 题级全通过 |
|---|---|---|---|---|---|---|---|
| **SAYACODE** | **78.8%** (63/80) | 79.7% | **78.8%** (63) | 1 | **80.8%** | [69.2, 91.0] | 29/39 = 74.4% |
| **mini-swe-agent** | 85.0% (68/80) | 87.2% | **80.0%** (64) | 2 | 87.2% | [79.5, 94.9] | 30/39 = 76.9% |
| **Claude Code** | 77.5% (62/80) | 78.5% | **73.8%** (59) | 1 | 78.2% | [67.9, 88.5] | 25/39 = 64.1% |
| ~~Codex CLI~~ | 68.8% | 69.6% | 65.0% | 1 | — | — | **不可比**（见下） |

### 两两配对（题级全通过，McNemar exact）

| 对比 | 共同题 | delta | a 独过 / b 独过 | p |
|---|---|---|---|---|
| Claude Code vs mini-swe | 38 | −7.9% | 3 / 7 | 0.344 |
| Claude Code vs SAYACODE | 38 | **0.0%** | 4 / 7 | 0.549 |
| mini-swe vs SAYACODE | 38 | +7.9% | 6 / 5 | 1.000 |

**三组两两差异全部不显著（p ≥ 0.34）**。bootstrap95 区间大幅重叠。

### 口径为什么重要（同一份数据，三种排名）

| 口径 | 排名 |
|---|---|
| planned | mini-swe 85.0% > SAYACODE 78.8% > Claude Code 77.5% > Codex 68.8% |
| observed | mini-swe 87.2% > SAYACODE 79.7% > Claude Code 78.5% > Codex 69.6% |
| **strict** | mini-swe 80.0% > **SAYACODE 78.8%** > Claude Code 73.8% > Codex 65.0% |

- mini-swe 的 planned 85.0% 里有 **4 个 pass 是改 `.snap` 快照换来的**（verifier 的 DATA_DIRS 包含 `__snapshots__`，不重置）；strict 口径扣掉后降到 80.0%。
- SAYACODE **0 个改快照**（strict = planned）。
- 因此「谁最强」完全取决于口径——**报告必须同时给三个口径，不给单一排名**。

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

1. **模型错配仍在**：Claude Code / mini-swe / SAYACODE 的 prompt 与工具契约都非为 hy3 调优。但这是**三组共同承受**（不像 Codex 是单向伤害），故组间比较仍有意义；**不能据此评价任一产品的真实能力**。
2. **40 题样本功效不足**：检测 10pp 需约 330 题（`docs/MULTI-MODEL-PLAN.md` 口径）。当前 CI 宽 ±12pp，任何「更强」都谈不上。
3. **strict 口径下 Claude Code 最低（73.8%）**，planned 口径下却与 SAYACODE 几乎相同（77.5% vs 78.8%），差异全在噪声内。
4. **v2 的 Codex 组与 v3 三组不同口径**：Codex 组因适配缺陷整体作废，不参与排名。
5. **未做的对照**：Claude Code + 原生 Claude 模型（付费 API，超 ¥50 预算）；同题集上的 holdout 提示词检验。

## 六、可写进简历的口径（保守版）

> 「独立开发 SAYACODE（LangGraph/LangChain 1.x，PyPI 发布）。在 SWE-bench Pro V2（40 题 × 2 重复，官方 Harbor 验证）上 pass@1 **78.8%**（strict 口径同为 78.8%，0 个改快照通过），与 mini-swe-agent（80.0% strict）、Claude Code（73.8% strict）**同量级，题级 McNemar 均不显著**（p ≥ 0.34）。单任务成本 1.43M tokens。建设可复现评测体系（三口径分母、缺失分类、题级统计、结果对账、指标 lint、轨迹级适配审计），并通过轨迹归因定位修复 5 个产品缺陷与 8 个评测基建缺陷。」

**不能写**：「优于 Codex / 优于 Claude Code / SOTA」。

## 七、产物

- 汇总：`C:\sb\hard\v2-325\FINAL-SUMMARY-V4.json`、`STRICT-COMPARE.json`、`TRAJ-AUDIT-claude-code.json`
- 工具：`scripts/strict_compare.py`、`scripts/audit_agent_traj.py`、`scripts/split_sample.py`
- 文档：`docs/CODEX-BASELINE-INVALID.md`、`docs/CLAUDE-CODE-BASELINE.md`
- 日志：`C:\sb\hard\v2-325\logs\{claude-light,claude-heavy,verify-final5}.log`
