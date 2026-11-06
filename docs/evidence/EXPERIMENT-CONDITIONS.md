# EXPERIMENT-CONDITIONS：每次实验的确切条件

> 用途：**任何跨实验引用前，先查这张表确认条件是否可比。** 只登记有证据的条件；没有证据就写「未记录」，不推测。
> 生成方式：读各 `FINAL-SUMMARY*.json`、`C:\sb\hard\*\config.json`、`profile-private.json`、`studies/*.json`、`C:\sb\archive\formal-240-v1-20261031.zip` 的元数据。
> 相关：[DATASET-CARD](../DATASET-CARD.md)（题集口径）、[served-distribution-20261107.json](served-distribution-20261107.json)（served 审计）、[RESULTS-LEDGER](../RESULTS-LEDGER.md)（数字）。

## 1. 条件登记表

| 实验 | 时间 | 模型 | context | max_output | 制品 | 题集 | 并发 | 结果落盘 |
|---|---|---|---:|---:|---|---|---|---|
| **v1 formal-240** | 2026-10-29 ~ 10-31（归档 `formal-240-v1-20261031.zip`） | `auto-hy3`（profile `C:\sb\hard\agent-verify\profile-private.json` 的 `model_id`） | 192,000 | **16,000**（同 profile） | `sayacode-3.2.4-py3-none-any.whl`（`C:\sb\tmp\hard\wheel-release\out\`） | `studies/sample-40-final.json`（sha `b2f1643…`） | **未记录** | `C:\sb\archive\formal-240-v1-20261031.zip`（原目录已不在 `C:\sb\hard`） |
| **v2-325 三基线**（mini-swe / Claude Code / OpenCode 首跑） | 2026-11-01 ~ 11-02（补跑至 11-05） | mini-swe `openai/auto-hy3`；Claude Code `auto-hy3`；OpenCode `openai/auto-hy3` | 192,000（`profile-private.json` 与 codex config 均记 192000；Claude/OpenCode 未显式配置，按模型默认） | 32,000（mini 的 `litellm_model_registry` 记 `max_tokens: 32000`；codex config 记 `model_max_output_tokens: 32000`） | 无（基线不用 product wheel） | `sample-40-final` | 2–4（轻题）/ 1（vuls） | `C:\sb\hard\v2-325` |
| **v3 Claude Code**（换第三基线） | 2026-11-04 | `auto-hy3` | 同上（未显式） | 同上 | 无 | `sample-40-final` | 2–4 / 1 | `C:\sb\hard\v2-325\claude-code` |
| **v4 OpenCode** | 2026-11-05 | `openai/auto-hy3` | 同上（未显式） | 同上 | 无 | `sample-40-final` | 2–4 / 1 | `C:\sb\hard\v2-325\opencode` |
| **v4-327（SAYACODE 3.2.7）** | 2026-11-05 22:55 → 11-06 06:35 | `auto-hy3` | 192,000 | 32,000 | **PyPI 3.2.7**（`sayacode-3.2.7-py3-none-any.whl`，sha256 `49db58d1…`） | `sample-40-final` | 4（轻题）/ 1（vuls） | `C:\sb\hard\v4-327` |
| **SWE-EVO pilot** | 2026-11-06 | `auto-hy3` | 192,000 | 32,000 | PyPI 3.2.7 | `C:\sb\newset\swe-evo\sample-pilot.json`（5 题，sha `a31fa82…`） | **未记录** | `C:\sb\newset\runs\pilot1` |
| **协作验证（explicit / explicit-check）** | **未记录**（无独立日期记录） | `auto/deepseek-v4.1-flash`（`input.json.profile.model_id`） | **65,536** | **8,192** | 无（产品侧适配调用，非 bench 制品） | `collaboration-parcel-combined`（team / single） | 1（单 trial） | `C:\sb\hard\collab-verify-explicit`、`collab-check-explicit` |
| **协作验证（single / manual）** | **未记录** | `auto/deepseek-v4.1-flash`（同 input.json 结构；manual 的 image 未核） | 65,536（同结构） | 8,192 | 无 | `collaboration-parcel-autonomous`（single） | 1 | `C:\sb\hard\collab-verify-single`、`collab-check-manual` |
| **摘要专题（summary on/off/pressure）** | — | — | — | — | — | — | — | **未记录**：无独立实验目录；仅 `studies/calibration-ansible-v3.json` 出现 `summary` 字段，不足以构成对照 |
| **CompletionGuard A/B** | — | — | — | — | — | — | — | **未记录**：无独立实验目录；产品证据只在 `evals/` 代码层，未形成 bench 对照 |

## 2. 关键不可比之处（F7）

1. **bench 侧 vs 产品侧不是同一条件**：bench（v1~v4）是 `auto-hy3` / 192k / 32k；协作验证是 `auto/deepseek-v4.1-flash` / **64k / 8k**。任何把「task_count=2」「协作行为」的 bench 结论与产品侧验证互相引用，都必须先说明这一点。
2. **v1 与 v2~v4 的 max_output 不同**：v1 配 16k，v2 起 32k（AGENTS 明确「v1 配 16,000 导致长任务收尾过早」）；v1 与 v2 单轮输出上限不可比。
3. **两份制品不可混**：3.2.5（本地 wheel，未发布）与 3.2.7（PyPI，sha `49db58d1…`）；v2-325 的 SAYACODE 是 3.2.5，v4-327 是 3.2.7。
4. **served 数据不可复核**：文档「42681 条、零 deepseek」在当前机器上**无法复现**——本地 `C:\sb\magpie-export\config\routing` 只到 2026-10-29 18:40（13,332 条；排除 DSH 后 7,327 条），且 10-26~10-29 的 SAYACODE 记录 served 为 `deepseek`/`glm`（见 [served-distribution-20261107.json](served-distribution-20261107.json) 的 `comparison`）。该窗口早于 hy3 评测（10-31 起），**不能直接推翻「10-31~11-05 零 deepseek」，但也不能用它证明**。
5. **协作验证缺日期与镜像证据**：`collab-*` 只有 `trials/<name>/state`（input/worker-result/snapshots），没有 config 侧的时间戳与镜像版本；「未记录」就是未记录，不要补猜。
6. **摘要/CompletionGuard 没有独立实验**：文档里的「摘要专题」「CompletionGuard A/B」没有对应的实验目录和结果根；引用相关结论时必须标注「仅有代码/单题证据，无 bench 对照」。

## 3. 证据指针

| 条件 | 证据位置 |
|---|---|
| v1 模型/制品/题集 | `C:\sb\archive\formal-240-v1-20261031.zip` 内 `formal-240/sayacode/jobs/…/config.json`、`formal-240/FINAL-SUMMARY.json`（sample.sha256） |
| v1 profile（16k） | `C:\sb\hard\agent-verify\profile-private.json`：`model_id=auto-hy3`、`context_length=192000`、`max_output_tokens=16000` |
| v2 四组 config | `C:\sb\hard\v2-325\<agent>\jobs\…\config.json`（model_name、litellm registry、codex `model_context_window/max_output`） |
| v2 SAYACODE profile | `C:\sb\hard\v2-325\sayacode\profile-private.json`：192000 / 32000 / ratio 0.8 |
| v4-327 config | `C:\sb\hard\v4-327\sayacode\jobs\…\config.json`：`product_wheel=…3.2.7…whl`、`requirements_path=product-requirements-3.2.6.txt`、`variant_path=variant-baseline.json` |
| pilot config | `C:\sb\newset\runs\pilot1\sayacode\jobs\…\config.json`、`profile-private.json`（192000 / 32000） |
| 协作验证 | `C:\sb\hard\collab-verify-explicit\trials\collaboration-parcel-combined--team--1\state\input.json`：`profile.model_id=auto/deepseek-v4.1-flash`、`context_length=65536`、`max_output_tokens=8192`、`team_enabled` |
| served | `docs/evidence/served-distribution-20261107.json`（由 `scripts/audit_served.py` 生成） |

## 4. 复算命令

```powershell
# served 分布审计（本表 §2.4 的数据）
python scripts\audit_served.py --source C:\sb\magpie-export\config\routing `
  --json-out docs\evidence\served-distribution-20261107.json
# 测试
python -m pytest tests\test_audit_served.py -q
```
