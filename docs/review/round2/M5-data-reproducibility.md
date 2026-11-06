# M5：数据资产清点与可复现性演练（round 2）

> 通道：M5。日期：2026-11-06。范围：`C:\sb\hard\v2-325`、`C:\sb\hard\v4-327`、`C:\sb\newset\runs\pilot1`、`C:\sb\analysis`、`C:\sb\archive`、`C:\develop\sayacode-bench\docs\RESULTS-LEDGER.md`、`C:\develop\sayacode-bench\studies`。
> 方法：只读。`docker images` / `docker image inspect` 只读查询；用 python 从 trial 产物重算；未跑模型、未删除/移动任何文件。
> 演练脚本：`C:\sb\tmp\explore\m5\drill.py`（只读）。

## 一、结论摘要

**如果换一台机器，只靠仓库和文档，不能重建全部已发表数字。** 分三层：

1. **可完整重算**（产物在、条件在）：v2-325 四组的 planned / pass / partial / task_macro / 六对 McNemar；v4-327 的 planned / partial；327 vs 3.2.5 配对；`touches_snap_pass`。演练已逐项复现（见 §四）。
2. **只能读缓存**（产物在、无法原样重跑）：v2-325 的 **SAYACODE 3.2.5**——trial 产物完整，但其 config 依赖的 `requirements_path` / `variant_path` 指向的 `C:\sb\r\formal-study-v1` **整个目录已不存在**。
3. **不可复现**（产物和条件都缺）：**SWE-EVO pilot 的 5/10**——10 个 trial 的 `verifier/` 全空、无 `reward.txt`，10 个 `image_id` 在本地 `docker image inspect` 全部返回 1（镜像已丢）。5/10 只能读 `FINAL-SUMMARY-PILOT.json`，既不能重算也不能重跑。

**最危险的三个断点**：pilot 镜像与 reward 全丢；3.2.5 SAYACODE 的 study 输入目录被移走/删除；`327 vs 3.2.5` 配对脚本只存在于 `C:\sb\tmp`（临时目录），且不能独立运行。

## 二、产物血缘图

以 RESULTS-LEDGER 的数字为终点，自下而上：

| 数字（ledger 节） | 汇总/生成文件 | trial 产物（目录与字段） | 题集 | 镜像 | 链路状态 |
|---|---|---|---|---|---|
| v2-325 四组 planned / 缺失 / task_macro /逐题 | `v2-325\FINAL-SUMMARY-V4.json`（`agents[].trials`、`stats.agents`） | `v2-325\<agent>\jobs\` 与 `verify\jobs\`：`verifier\reward.txt`、`verifier\output.json`、`verifier\terminal.json`、`normalized.json` | `studies\sample-40-final.json`（sha256 `b2f1643…` 与 summary 记录一致） | `ghcr.io/scaleapi/swe-bench_pro-v2:<task_id>` × 40，本地 **40/40 在** | ✅ 可重算 |
| v2-325 四组 partial | `C:\sb\analysis\dataset.json`（`required/passed/partial`） | 同上 `verifier\output.json` 的 `tests[].status`（**不是** `test-stdout.txt`，见 §三.6） | 同上 | 同上（partial 不依赖镜像重跑） | ✅ 可重算 |
| v2-325 六对 McNemar | `FINAL-SUMMARY-V4.json` 的 `stats.pairwise` 或从 trials 复算 | 四组 `reward`/`terminal`（complete 题交集） | 同上 | 同上 | ✅ 可重算 |
| v2-325 `touches_snap_pass` | `dataset.json` 的 `touches_snap` | `agent/model.patch` 的 `+++ b/` 文件集 | 同上 | 同上 | ⚠️ 字段只覆盖 claude/opencode，其余为 null（见 §三.6） |
| v4-327 planned / partial / task_macro / pass@2 | `v4-327\FINAL-SUMMARY-327.json` | `v4-327\sayacode\jobs\`（无 reward，只有 patch/terminal）+ `verify\jobs\`（`reward.txt`、`output.json`） | 同上 | 同上 40 题（本地在）+ **PyPI 3.2.7 wheel**（`C:\sb\tmp\hard\wheel-release-3.2.7\out\…whl`，sha256 `49db58d1…`） | ✅ 可重算 + 可重跑（config 依赖齐全） |
| 327 vs 3.2.5 配对（78 trial、Δ−2.6pp、p=0.8145、CI[−12.5,+6.2]） | `C:\sb\tmp\paired_325_327.py`（**不在仓库**） | 两批 `FINAL-SUMMARY` 的 `trials[].effective_reward` | 同上 | 不依赖镜像 | ⚠️ 可重算，但脚本在 tmp、需手动 `PYTHONPATH`（见 §三.3） |
| SWE-EVO pilot 5/10、逐题 | `pilot1\FINAL-SUMMARY-PILOT.json`、`PREDICT-VS-ACTUAL.json`、`VERSION-HYPOTHESIS.json` | `pilot1\sayacode\jobs\<job>\sweevo-…__XXXX\`：`verifier\` **空**、无 `reward.txt`、`normalized.reward=null` | `C:\sb\newset\swe-evo\sample-pilot.json`（sha256 `a31fa82…` 一致） | pilot 的 10 个 `image_reference` / `image_id` **全部缺失**（`docker image inspect` rc=1） | ❌ 不可复现（只能读缓存） |
| SWE-EVO 48 题状态 | `C:\sb\analysis\swe-evo-baseline.json`（仅 4 条 usable） | `C:\sb\newset\swe-evo\tasks\`（48 个任务目录在） | `large-sample-v1-swe-evo.json` | 本地 `docker images` 中 sweevo/sweb.eval 仅 **8 个**（含 5 个 xingyaoww 基线、2 个旧 sweevo env-main），远少于 48 | ⚠️ 未跑全，镜像需重拉/重建 |

## 三、断链清单（按严重度）

| # | 断在哪 | 证据 | 影响 | 能否修复 |
|---|---|---|---|---|
| 1 | **pilot 的 reward 与镜像双缺** | 10 个 trial 的 `verifier/` 为空、无 `reward.txt`、`normalized.reward=null`；10 个 `image_id` 的 `docker image inspect` 全 rc=1 | SWE-EVO pilot 的 **5/10、逐题、预测矩阵** 全部只能读 `FINAL-SUMMARY-PILOT.json`；换机器后无法重算/重跑 | **只能重跑**：重建 5 题 `env-main` 镜像并重跑；或接受「历史缓存」。无法从现有产物恢复 |
| 2 | **v2-325 SAYACODE 3.2.5 的 study 输入目录消失** | `v2-325\sayacode\jobs\*\config.json` 的 `requirements_path=C:\sb\r\formal-study-v1\prepared-original\mapped-bundle\inputs\product-requirements.txt`、`variant_path=…\inputs\baseline.json`；`C:\sb\r\formal-study-v1` **已不存在** | 3.2.5 批次 SAYACODE **无法原样重跑**（缺 requirements + variant）；trial 产物在，仍可重算 | **部分可修**：从 archive/其他副本找回这两个文件；找不到则只能以「等价配置」重跑，并标注条件不等价 |
| 3 | **327 配对脚本不在仓库、不能独立运行** | 脚本位于 `C:\sb\tmp\paired_325_327.py`；首次运行 `ModuleNotFoundError: No module named 'sayacode_bench'`，需手动 `PYTHONPATH=C:\develop\sayacode-bench\src` 才能跑出 78/63/61/−2.6/p=0.8145 | ledger §3.2 的配对数字在 tmp 清理后不可复算；临时目录不受版本控制 | **可修**：把脚本迁入 `scripts/`、在脚本内 `sys.path.insert(0, ROOT/"src")`、加 `--old/--new` 参数 |
| 4 | **汇总脚本默认参数过期** | `scripts\final_summary.py:31` 默认 `root=C:\sb\hard\formal-240`（v1）；`:141` 默认 `--agents sayacode mini-swe codex`（无 claude-code/opencode，且 codex 已作废） | 直接运行无法重建 ledger 四组；需人工改参数 | **可修**：更新默认值或加 `scripts/rebuild_ledger.py` wrapper，固定 `--root v2-325 --agents sayacode mini-swe claude-code opencode` |
| 5 | **trial 布局四套不一致，无统一读取器** | ① v2 sayacode/mini：`verify\jobs` 有 `output.json`+`reward.txt`，`jobs` 只有 reward/patch；② v2 claude/opencode：**无 verify/jobs**，`jobs` 内联全套 verifier；③ v4：`jobs` 无 reward，`verify\jobs` 有；④ pilot：trial 目录名 `sweevo-…__XXXX`（**不以 `instance_` 开头**），通用脚本按前缀会找不到 | 用仓库现有脚本无法一次重算全部数字；按 `instance_` 前缀写的脚本对 pilot 静默失效（R1/R3 已记录同类缺陷） | **可修**：写统一读取器（按内容识别 `result.json` + 兼容 jobs/verify 两种布局），见 §七 |
| 6 | **partial 的数据源是 `output.json`，不是 `test-stdout.txt`** | `flipt-8bd3604-r1`：`test-stdout.txt` 显示 `Required tests: 7 / passed: 6`（0.857），而 `verifier/output.json` 的 `tests` 是 6 个全 PASSED（1.0）；`dataset.json` 记 `required=6, passed=6` | 若用 test-stdout 重算 partial，五组分别得到 **0.924/0.962/0.913/0.877/0.911**，比 ledger 的 **99.2/98.5/97.9/94.4/97.6** 低 4–7pp；用 output.json 则精确一致 | **口径可修**：脚本强制只读 output.json；或在 ledger 旁注明「禁止用 test-stdout 算 partial」 |
| 7 | **SWE-EVO 48 题镜像未拉全** | `docker images` 中 sweevo/sweb.eval 共 8 个；`C:\sb\newset\swe-evo\tasks` 有 48 个任务目录；`swe-evo-baseline.json` 仅 4 条 usable | 48 题目前无法整体重跑；pilot 的 5 题镜像也已丢 | **可修但成本高**：按 48 题清单重拉/重建镜像；需记录每题的 image digest |
| 8 | **归档不完整** | `C:\sb\archive` 只有 `formal-240-v1-20261031.zip` 与 `scripts-20261029/`；v2-325/v4-327/analysis/studies/wheels 均未打包；wheels 在 `C:\sb\tmp\hard\wheel-release-*`（tmp 目录） | 换机器时无法整体恢复；tmp 清理会丢 wheel | **可修**：立即打包并写 manifest/sha256（§七） |

## 四、演练实录（只读，从 trial 产物重算）

演练脚本 `C:\sb\tmp\explore\m5\drill.py`，结果：

### 4.1 四组 planned/pass（从 `verifier/reward.txt`）

| agent | 磁盘可读 reward 的 unique job | 重算 pass | ledger pass | 判定 |
|---|---:|---:|---:|---|
| SAYACODE 3.2.5 | 79 | **63** | 63/80 | ✅ 一致 |
| mini-swe | 78 | **68** | 68/80 | ✅ 一致 |
| Claude Code | 79 | **62** | 62/80 | ✅ 一致 |
| OpenCode | 80 | **60** | 60/80 | ✅ 一致 |

- unique job 少于 80，是因为 `terminal=skipped_empty_patch` 的 trial 没有 `reward.txt`（v2 mini 1 个、v4 2 个）；这些 trial 的 `verifier/terminal.json` 存在（`{"status":"skipped_empty_patch","reward":0.0,...}`），可据其把 missing 分类补全。
- 结论：**pass 数可从磁盘精确重算**；missing 分类需同时读 `terminal.json`。

### 4.2 partial（从 `verifier/output.json`）

| 组 | 磁盘重算（output.json） | ledger | 判定 |
|---|---:|---:|---|
| SAYACODE 3.2.5 | 99.2%（n=73） | 99.2% | ✅ |
| mini-swe | 98.5%（n=77） | 98.5% | ✅ |
| Claude Code | 97.9%（n=76） | 97.9% | ✅ |
| OpenCode | 94.4%（n=77） | 94.4% | ✅ |
| SAYACODE 3.2.7 | 97.6%（n=72） | 97.6% | ✅ |

反例（错误源）：从 `test-stdout.txt` 重算得到 0.924 / 0.962 / 0.913 / 0.877 / 0.911，**与 ledger 不符**（见 §三.6）。

### 4.3 v4-327 planned

从 `v4-327\sayacode\verify\jobs` 的 `reward.txt` 重算：77 个可读 reward、**pass=61**，与 ledger 61/80 一致；另 2 条 `terminal=skipped_empty_patch`（`vuls-dc496468b9e r1`、`qutebrowser-3e21c8214a r1`）与 1 条空 patch（`vuls-4b680b99606 r1`）需从 `terminal.json` 与 `jobs` 补。

### 4.4 327 vs 3.2.5 配对

- 直接用「磁盘 reward 按短名对齐」的临时实现得到 common=40 / 3.2.5=30 / 3.2.7=33（**错**），原因是没按 `(task, repeat)` 对齐、且漏了 `terminal` trial。
- 使用 `C:\sb\tmp\paired_325_327.py`（需先 `set PYTHONPATH=C:\develop\sayacode-bench\src`）得到：
  `3.2.5 trials=79, 3.2.7 trials=79, 配对=78`；`both=53, 3.2.5_only=10, 3.2.7_only=8`；`80.8% → 78.2%`；`Δ=−2.6pp`；`p=0.8145`；`bootstrap CI95=[−12.5,+6.2]pp`；翻转 18（10/8）——**与 ledger §3.2 完全一致**。
- 缺陷：脚本不在仓库；首次运行因缺 `sys.path` 报 `ModuleNotFoundError`；不修路径则演练失败。

### 4.5 SWE-EVO pilot

- 10 个 trial 的 `verifier/` 全空、无 `reward.txt`、`normalized.reward=null`；10 个镜像 `docker image inspect` 全 rc=1。
- 只能读 `FINAL-SUMMARY-PILOT.json`：10 trial、pass=5，与 ledger 5/10 一致——但这是**读缓存**，不是重算。
- 结论：pilot 的 5/10 属于「不可复现」。

### 4.6 演练中需要人工干预的步骤（均为缺陷）

1. pilot 无法重算（必须改读 FINAL-SUMMARY）。
2. 配对脚本需手动设 `PYTHONPATH`，且不在仓库。
3. `final_summary.py` 需手动指定 `--root` 与 `--agents`，否则根目录指向 v1、agent 列表缺 claude/opencode。
4. partial 需知道「用 output.json 而非 test-stdout」，无脚本强制。
5. 四种 trial 布局需要人工判断用 jobs 还是 verify/jobs。

## 五、题集与镜像可用性

| 项 | 状态 | 证据 |
|---|---|---|
| `studies\sample-40-final.json` | ✅ 存在，sha256 `b2f1643567f55abe04a054c7fc88e946315c47cb39dfa284445f5e483f35fe96`，与 V4/327 summary 记录一致 | `FINAL-SUMMARY-V4.json.sample.sha256` |
| 40 题 SWE-bench Pro V2 镜像 | ✅ **40/40 在本地**（`docker images` 共 68 个） | 从 v2/v4 trial 的 `runtime.json.docker_image` 收集 40 个唯一名，逐一比对命中 |
| 3.2.5 wheel | ✅ 存在 `C:\sb\tmp\hard\wheel-release-3.2.5\out\sayacode-3.2.5-py3-none-any.whl`，sha256 `f26930e8fab5b615edd80ab97253df068440aa8a7db674cd70b2fe92ed15f102` | 文件系统实测 |
| 3.2.7 wheel | ✅ 存在且 sha256 `49db58d12bba065c0f7038b3a9339bc1f2a2097952d178d7d26bbd6a4970d04b`，与 327 报告一致 | 文件系统实测 |
| v2-325 SAYACODE 的 requirements/variant | ❌ **MISSING**（`C:\sb\r\formal-study-v1` 整个目录不存在） | config.json 的 `requirements_path`/`variant_path` |
| pilot 5 题镜像 | ❌ 0/10（`image_reference` 不在本地；`image_id` inspect 全 rc=1） | runtime.json + docker inspect |
| SWE-EVO 48 题镜像 | ⚠️ 本地仅 8 个 sweevo/sweb.eval；`C:\sb\newset\swe-evo\tasks` 有 48 个任务目录 | `docker images` + 目录计数 |
| SWE-EVO 题集 | ✅ `sample-pilot.json` sha256 `a31fa827…` 一致；48 题任务目录在 | 文件系统实测 |

## 六、可复现性分级

| 数字 | 分级 | 说明 |
|---|---|---|
| v2-325 四组 planned / pass / missing / task_macro / 六对 McNemar | **可完整重算** | reward.txt + terminal.json + output.json + complete 题交集；已演练 |
| v2-325 四组 partial | **可完整重算** | 必须用 `output.json`；test-stdout 会错 |
| v2-325 `touches_snap_pass` | **可完整重算（覆盖不全）** | `dataset.json.touches_snap` 仅 claude/opencode 有值 |
| v4-327 planned / partial / task_macro / pass@2 | **可完整重算 + 可重跑** | 镜像 40/40、wheel/requirements/variant 齐全 |
| 327 vs 3.2.5 配对 | **可完整重算（脚本需修）** | 数字可复现，但脚本在 tmp 且路径缺陷 |
| v2-325 SAYACODE 3.2.5 | **只能读缓存** | trial 产物在，可重算；但缺 requirements/variant，无法原样重跑 |
| v2-325 mini/claude/opencode | **可完整重算 + 可重跑** | 镜像在、config 无缺失 refs |
| SWE-EVO pilot 5/10、逐题、预测矩阵 | **不可复现（只能读缓存）** | trial 无 reward、镜像全丢 |
| SWE-EVO 48 题 | **不可复现（条件缺）** | 未跑全，镜像未拉全 |
| v1（68.8/86.2/86.2 等） | **不在本 ledger** | `C:\sb\archive\formal-240-v1-20261031.zip` 有打包，但不在本轮数据根 |

## 七、建议（立刻固化）

1. **打包一份完整可复现归档**（只读复制，不删源）：`v2-325`、`v4-327`、`pilot1`、`C:\sb\analysis`、`C:\develop\sayacode-bench\studies`、3.2.5/3.2.7 wheels、`FINAL-SUMMARY*`、`RESULTS-LEDGER.md`。写 `manifest.json`（路径 + sha256 + 文件数 + 生成时间）。
2. **写一个 `scripts/rebuild_ledger.py`**：统一读取四种 trial 布局（jobs / verify/jobs / 内联 verifier / pilot 非 `instance_` 前缀），用 `output.json` 算 partial、用 `terminal.json` 补 missing，产出与 ledger 逐项对账。这是把本次演练固化成可重复资产的最小成本。
3. **把 `C:\sb\tmp\paired_325_327.py` 迁入 `scripts/paired_325_327.py`**：脚本内加 `sys.path.insert(0, ROOT/"src")`，加 `--old/--new` 参数，并在 ledger §6 登记。
4. **修 `final_summary.py` 默认值**：`--root` 默认改 `C:\sb\hard\v2-325`、`--agents` 改为四组（去 codex）；或加 wrapper。
5. **补 3.2.5 的 study 输入**：找回 `product-requirements.txt` 与 `baseline.json` 并归档；找不到就明确写「3.2.5 批次不可原样重跑」。
6. **记录所有制品与题集 sha256**（已可写）：sample-40-final `b2f1643…`、sample-pilot `a31fa82…`、3.2.5 wheel `f26930e8…`、3.2.7 wheel `49db58d1…`；镜像 digest 从 `runtime.json.image_id` 汇总成清单。
7. **pilot / SWE-EVO 单独标注为「历史缓存」**：不写入任何可复现声明；若未来要用，需重建 `env-main` 镜像并重新跑。
8. **禁止再写 tmp 脚本作为唯一实现**：`paired_325_327.py`、`run_formal_240.py` 等若只在 tmp，迁移入仓库。

## 八、复现命令

```powershell
# 1) 演练（只读）：四组 planned/partial、327、配对、pilot
cd C:\sb\tmp\explore\m5
python drill.py

# 2) 327 vs 3.2.5 配对（需补 src 路径）
$env:PYTHONPATH = 'C:\develop\sayacode-bench\src'
python C:\sb\tmp\paired_325_327.py

# 3) 镜像统计（只读）
docker images --format '{{.Repository}}:{{.Tag}}' | Measure-Object

# 4) 题集 sha256
python -c "import hashlib;print(hashlib.sha256(open(r'C:\develop\sayacode-bench\studies\sample-40-final.json','rb').read()).hexdigest())"
```

**一句话**：v2-325 四组与 v4-327 的数字仍可从 trial 产物重算（partial 必须用 `output.json`）；**SWE-EVO pilot 的 5/10 已经死了**（reward 与镜像双缺）；3.2.5 SAYACODE 只能读缓存、不能原样重跑。换机器前必须打包 `C:\sb\hard\{v2-325,v4-327}` + `analysis` + `studies` + wheels，并把 tmp 里的配对脚本迁入仓库。
