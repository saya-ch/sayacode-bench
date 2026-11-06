# M4：测试质量审计（第二轮复盘）

| 项 | 值 |
|---|---|
| 日期 | 2026-11-07 |
| 范围 | `C:\develop\sayacode-bench\tests`（1524 collected）、`C:\develop\sayacode\tests`（546 collected） |
| 方法 | AST 静态分级 + 全量/抽样运行 + **变异测试**（沙箱副本改回旧行为，看哪些测试会红）+ 静态引用分析 |
| 硬约束 | 只读；未修改任何仓库代码与测试（变异只在 `C:\sb\tmp\mut` 副本上做，跑完已恢复） |
| 一句话结论 | **P1 修的三个 P0 全部有能抓住回退的测试**（变异测试 5/5 被抓）；真正的问题不在"测试不够"，而在**约 5% 的测试断言实现细节（源码文本/mock）**、**scripts 层 29 个文件零测试**、以及**产品侧 4 个长期失败全部是环境缺陷伪装成测试失败**。 |

---

## 一、测试有效性分级

### 1.1 口径

- **A 类（真断言行为）**：有至少一个非弱断言（或 `pytest.raises`），且检测不到"源码文本/mock 调用"断言。
- **B 类（断言内部实现）**：断言 mock 被调用（`assert_called*`/`call_args`/`call_count`）、`caplog`/`capsys` 日志文案、或**读取源码文件后断言字符串存在**（源码文本断言）。
- **C 类（自娱自乐）**：所有断言均弱——`is not None`、`assert x`、`isinstance`、`len(x)>0`、常量自比、`assert True/False`——且无 `raises`。
- **D 类（空壳/跳过）**：无条件 `@pytest.mark.skip`/`xfail`、函数体只有 `pass`、运行时 `pytest.skip`、或无断言也无被测调用。
- 计数单位：**collected 测试数**（参数化展开后，即 pytest 报的 1515/546 口径）；同时给函数数供参考。
- 说明：`assert x is None` **不算弱**（它是"不得猜测出值"的有效负断言）；`assert x is not None` 算弱。
- 局限：静态规则不能识别"断言了错误的期望值"或"断言了没人消费的字段"；C 类初判结果全部做了人工复核（见 1.3）。

### 1.2 结果

**sayacode-bench（1524 collected / 836 个测试函数）**

| 类别 | 函数数 | 占比 | collected | 占比 |
|---|---:|---:|---:|---:|
| A 真断言行为 | 783 | 93.7% | 1447 | 94.95% |
| B 断言实现细节 | 53 | 6.3% | 77 | 5.05% |
| C 自娱自乐 | 0 | 0.0% | 0 | 0.00% |
| D 空壳/跳过 | 0 | 0.0% | 9（运行时 skip） | 0.59% |
| **C+D** | — | — | **9** | **0.59%** |

**sayacode 产品（546 collected / 450 个测试函数）**

| 类别 | 函数数 | 占比 | collected | 占比 |
|---|---:|---:|---:|---:|
| A 真断言行为 | 427 | 94.9% | 517 | 94.7% |
| B 断言实现细节 | 21 | 4.7% | 27 | 4.9% |
| C 自娱自乐 | 2 | 0.4% | 2 | 0.37% |
| D 空壳/跳过 | 0 | 0.0% | 0 | 0.00% |
| **C+D** | — | — | **2** | **0.37%** |

**结论：C+D 均远低于 10%，不需要按数量点名。** 这一结果与"测试数量很多但抓不住回退"的担忧不符——数量之外，**回退保护本身是有效的**（见第三节变异测试）。真正需要点名的是 B 类（5%）与覆盖盲区（第四节）。

### 1.3 C 类人工复核（为什么 bench 是 0）

静态初判出 6 个"只有弱断言"的测试，逐一复核后**全部属于有效的负断言**，不构成自娱自乐：

| 位置 | 断言 | 复核结论 |
|---|---|---|
| `test_analysis.py:246` | 单题不生成置信区间 → 断言 `interval_95 is None` | A：否定式行为断言 |
| `test_artifacts.py:56` | 失败间隔超过 5 次不再触发止损 | A |
| `test_execution.py:122` | 非 0/1 reward 不得被猜成 pass → `success is None` | A（参数化 ×4） |
| `test_installation.py:230` | 摘要不符时安装探针必须拒绝 | A |
| `test_resources.py:38,97` | 证据缺失必须保持"未知"而不是伪造一致 | A（×8/×2） |

**产品侧 2 个 C 类**（建议补强）：

| 位置 | 问题 |
|---|---|
| `agent/test_runtime_additional.py:155` | 只断言 `is None` 类弱条件，未验证触发的摘要调用参数 |
| `agent/test_truncation_continuation.py:169` | 只断言弱条件，未验证 nudge 文本与调用计数 |

### 1.4 D 类实况：9 个全部是**环境/平台条件跳过**，不是空壳

| 位置 | 跳过原因 | 性质 |
|---|---|---|
| `test_native_usage_observer.py:162/173` | 缺 `langchain_core` / `langchain` | 环境（依赖未装） |
| `test_network.py:466` | 真实 Docker 探针需显式开关 | 设计（显式启用） |
| `test_prepare_final_study.py:195` | 非 POSIX 平台 | 平台 |
| `test_prepare_primary_study.py:174` | 无权限创建符号链接 | 环境（Windows 权限） |
| `test_shards_docker.py:237` | Docker smoke 需显式开关 | 设计 |
| `test_shards_docker.py:587` | 缺 `langchain_anthropic` | 环境 |
| `test_worker_artifacts.py:93` | 无法创建符号链接 | 环境 |
| `test_worker_artifacts.py:151` | Windows 无 POSIX 命名管道 | 平台 |

无一个"无条件 skip/pass 的空壳"（静态扫描 0 个）。但**这也意味着 9 个高价值路径在本机从未执行**（Docker 网络隔离、分片 smoke、符号链接、命名管道），属环境性覆盖缺口。

---

## 二、B 类（实现细节断言）明细：这是真正需要治理的 5%

### 2.1 源码文本断言（bench 38 个函数 / product 10 个）——最脆的一类

做法是 `read_text()` 读被测脚本源码，再断言某个字符串存在于源码中。它**不执行代码**，只检查文本：

| 文件 | 数量 | 风险示例 |
|---|---:|---|
| `test_locked_agents.py` | 2 | 断言 `run_formal_240.py` 源码包含 `"verifier/terminal.json"`、`canonical_model=CANONICAL_MODEL` —— 改注释/换行/重命名即红 |
| `test_publish.py` | 4 | 断言发布脚本源码含特定字段名 |
| `test_adapter.py` | 3 | 断言安装命令文本（`pip install --require-hashes` 等） |
| `test_cloud_qualification.py` / `test_cloud_calibration.py` / `test_preflight_installation_workflow.py` | 3/2/3 | 断言 workflow YAML 文本 |
| `test_study.py` / `test_sharded_workflow.py` / `test_sensitivity.py` / 其余 | 各 1–3 | 断言脚本里存在某个 guard 调用 |

**风险**：这类测试对"重构"过度敏感（改名、换行、等价改写都会红），却对"逻辑写错"不敏感（文本还在、行为已坏）。`test_locked_agents.py` 的两个例子正是 2026-11-06 那次 P0 的同款：断言实现细节而不是行为，**第一轮复盘教训的变体仍在**。

### 2.2 mock/caplog 断言（bench 15 个函数 / product 11 个）

集中在 `test_fixture_qualification.py`（6）、`cli/test_headless_contracts.py`（7）等，多为"断言某个内部函数被调用一次"。它们能防"忘了调用"，但抓不到"调用参数错/返回值错"。

**建议**：B 类不是都要删——对"必须调用外部副作用（上传、写文件）"的场景，mock 断言是合理的。但**源码文本断言应逐步替换为行为断言**（例：`test_locked_agents.py` 改断言 `archive_incomplete_jobs()` 的返回值与目录状态，而非源码字符串）。

---

## 三、回归保护缺口：变异测试（本轮核心证据）

### 3.1 实验设计

在沙箱副本 `C:\sb\tmp\mut`（src/tests/scripts/studies 完整复制，`PYTHONPATH` 指向副本 src）上，把 **P1 修的每个 P0 逐条改回旧行为**，跑 6 个相关测试文件（`test_formal` / `test_execution` / `test_artifact_replay` / `test_trialdir` / `test_strict_compare` / `test_verify_patches`），记录哪些测试变红。基线：**135 passed，0 红**。

### 3.2 结果

| 变异 | 改回旧行为的位置 | 抓红测试数 | 具体测试（代表性） |
|---|---|---:|---|
| **M1** `instance_` 前缀（P0） | `execution.replay_official_trial` 改回 `glob("instance_*/result.json")` | **19** | `test_execution.py::test_pristine_replay_uses_official_agent_and_records_apply_evidence[sweevo-demo__only]`、`test_empty_patch_is_regraded_...`、`test_replay_needs_confirmation_...`、`test_replay_resources_...` 等（**全部是 `sweevo-demo__only` 参数化分支**） |
| **M2** timeout 无分支（P0） | `formal.classify_missing` 删除 timeout 分支 | **1** | `test_formal.py::test_timeout_is_classified_before_empty_patch_and_unverified` |
| **M3** strict 方向（P0） | `strict_compare` 找不到 patch 时改回 `strict += 1` | **1** | `test_strict_compare.py::test_pass_without_patch_is_not_counted_as_strict` |
| **M4** `instance_`（S4） | `artifact_replay._find_patch` 改回 `glob("instance_*/source.json")` | **2** | `test_artifact_replay.py::test_sweevo_named_portable_trial_is_located`、`test_flat_portable_layout_is_located` |
| **M5** 身份哈希（S2） | `_request_identity` 的 source_job 输入改回 `instance_*` glob | **1** | `test_execution.py::test_source_patch_change_cannot_reuse_old_replay_identity[sweevo-demo__only]` |

**结论：5 个变异 5 个被抓，无一漏网。**

### 3.3 关键细节：为什么这次抓得住

1. **M1 只对 `sweevo-demo__only` 分支变红，`instance_demo__only` 分支仍绿**——这恰好证明测试是**按行为而非按文本**判定的：旧行为对 SWE-bench 命名本来就能工作，只有非 `instance_` 命名能暴露缺陷。`replay_source` fixture 的参数化（P1 的改动）是这一保护的直接来源。
2. **M2 的红点精确落在新增的 timeout 测试上**，且该测试同时覆盖"有 patch/无 patch/已成功"三种输入——它锁住了"timeout 必须早于 empty_patch/unverified"这一**方向性**语义，而不只是"timeout 类存在"。
3. **M3 的红点来自 P1 新增的 `test_pass_without_patch_is_not_counted_as_strict`**，注释里明确写了"方向性 bug 回归：旧实现会高估"。

### 3.4 仍存在的回归保护缺口（变异测试之外）

| 缺口 | 说明 | 风险 |
|---|---|---|
| `MISSING_CLASSES` 的 7 vs 协议 6 类 | 全仓测试中**没有任何断言** `MISSING_CLASSES` 的类集合或长度；只在 `test_formal.py:229` 的 docstring 提到。若有人加/删类，只有 timeout 行为测试会间接报警 | 中 |
| `unattributed` 行为 | 只在注释出现（`test_formal.py:309`），**无测试**断言"unattributed 不进分母/报告" | 中 |
| `run_formal_240` 主流程 | 只有 `archive_incomplete_jobs` 有测试；`main_async`/`container_mem_mb`/`AdaptiveSemaphore`/`install_verifier_throttle`/`prune_networks`/`mem_supervisor` **均未被测试引用**（静态符号检查） | **高**（历史事故最多的一段） |
| `verify_patches` 主流程 | `collect_pending`/`record_empty_patch` 有测试；`main_async`/`_inner_dir`/`_task_of` 无测试 | 中 |
| `locked_agents.env_cfg` | 无测试（`build_agent`/`PatchReplayAgent` 等有） | 低 |

---

## 四、测试与文档/口径的一致性

| 检查 | 结果 | 证据 |
|---|---|---|
| 是否还把 **strict 口径**当权威 | **否**。`strict_compare` 仍存在，但测试 `test_strict_compare.py:180 test_cli_warns_that_strict_is_deprecated` 明确断言 CLI 会警告"不得引用"；`test_formal_stats.py:90` 的 `strict` 只是局部变量名（McNemar 的 all_repeats_pass），非旧口径 | 见 `tests/test_strict_compare.py:180-190` |
| 是否断言"缺失 7 类" | **否**（无任何类集合断言）→ 若把协议对齐为 6 类或恢复其它类，**没有测试会报警** | grep `MISSING_CLASSES` 仅命中 docstring |
| 是否固化已废除字段 | **否**：`snap_pass`/`snapshot_pass` 等旧字段无断言；`DeepSeek-V4.1-Flash` 硬编码已在 P1 全部改为常量（本轮 grep 仅剩 2 处负例与 1 处"断言旧模式不存在"的反向断言） | grep 结果 |
| 是否有测试断言 `unattributed` 的处理 | **否**（缺口） | 同 §3.4 |
| 测试与 `PROTOCOL-V2 §3` 的类清单一致性 | **无测试锁定**；代码 7 类 vs 协议 6 类仍存在（P1 未处理，见 R3 S8 遗留） | — |

**结论**：没有发现"把已废除口径固化成断言"的测试；相反，`strict` 的废除被测试显式锁住了。真正的不一致是**协议与代码的 7/6 类偏差没有测试守护**。

---

## 五、产品侧 4 个长期失败：逐条定性

### 5.1 复现与共同根因

命令（产品仓库）：

```
uv run --no-sync pytest tests/evals/test_execution.py tests/memory/test_repository.py \
  tests/tasks/test_task_safety.py tests/tools/test_security_boundaries.py -q
→ 4 failed, 68 passed
```

四个失败分别为：

1. `tests/evals/test_execution.py::test_driver_saves_abort_and_report_even_when_stop_command_times_out`
2. `tests/memory/test_repository.py::test_same_scope_survives_new_store_and_project_scopes_stay_separate`
3. `tests/tasks/test_task_safety.py::test_non_git_builder_uses_shared_workspace_and_keeps_profile_private`
4. `tests/tools/test_security_boundaries.py::test_official_search_has_no_sensitive_path_exceptions[True]`

**共同根因（环境，非产品 bug、非测试写错）**：产品 venv 的 Python **找不到可用临时目录**，导致 pytest 的 `tmp_path` 退化到**仓库根目录内**（`C:\develop\sayacode\pytest-of-20655\...`），而 4 个测试的前提都是"临时目录位于非 git 仓库、且不在 .gitignore 覆盖范围内"。

直接证据：

| 证据 | 内容 |
|---|---|
| 仓库内出现 pytest 临时目录 | `C:\develop\sayacode\pytest-of-20655\pytest-13..17`（时间戳为 11-06 23:49） |
| `tempfile.gettempdir()` 退化 | 产品 venv：`gettempdir= C:\develop\sayacode`；bench venv：`C:\Users\20655\AppData\Local\Temp` |
| 非 git 副本中直接抛错 | 在 `C:\sb\tmp\prod-copy`（无 `.git`）运行同一测试：`FileNotFoundError: No usable temporary directory found in ['C:\Users\20655\AppData\Local\Temp', ..., 'C:\WINDOWS\Temp', 'c:\temp', 'c:\tmp', '\temp', '\tmp', 'C:\sb\tmp\prod-copy']` |
| pwsh 自身可写 TEMP | `Set-Content $env:TEMP\probe-*.txt` 成功 → 说明是**该 venv Python 进程**的临时目录可用性问题（非机器全局权限） |

### 5.2 逐个判定

| # | 失败 | 失败原因（代码级） | 定性 |
|---|---|---|---|
| 1 | `test_execution` | `argparse` 拒绝：`evals.run: error: 原始轨迹与工作区必须存放在仓库外`。测试用 `tmp_path` 作输出目录，tmp_path 落在仓库内 → 被"仓库外"守卫拒绝（`SystemExit: 2`） | **环境**（tmp_path 位置） |
| 2 | `test_repository` | `scopes_for()` 用 `_git_common_dir(project_path)`：两个 fixture 目录都在同一 git 仓库内 → 返回同一 git-common-dir → 两个"不同项目"的 scope identity 相同 → `assert project_scope_a != project_scope_b` 失败 | **环境**（tmp_path 在 git 仓库内；正常环境两个目录在系统 temp，非 git） |
| 3 | `test_task_safety` | `is_git_workspace(plain)` 向上找到仓库 `.git` → 返回 True，而测试断言"非 git 目录"应为 False | **环境**（同上） |
| 4 | `test_security_boundaries` | 用上游 `FilesystemFileSearchMiddleware(use_ripgrep=True)` 搜 `MATCH_`，只命中 `/source.txt`；`credentials.json`、`.env`、`.ssh/id_rsa` 未命中。原因：tmp_path 在仓库内 → ripgrep 遵守仓库 `.gitignore` 且默认跳过隐藏文件（`.env`/`.ssh`）；产品代码 `tools/search.py` 只是包装上游、不改变忽略规则 | **环境**（tmp_path 在仓库内 → rg 的忽略规则生效）；若在系统 temp 下应命中 |

**重要结论**：这 4 个不是"4 个孤立隐患"，而是**同一个环境缺陷的 4 个投影**。在正常机器（临时目录可写且不在 git 仓库内）上，它们应当全部通过；本机把它们挂成"长期失败"，会掩盖真实回归。**处置建议：修复 venv 的临时目录可用性（或设置 `--basetemp` 指向仓库外目录），然后把这 4 个测试纳入"必须绿"基线**——而不是继续挂着。

---

## 六、覆盖盲区

### 6.1 src 模块（静态引用）

`src/sayacode_bench/` 的 **25 个模块全部**在 tests 中被引用（0 个完全未提及）。但"被 import"不等于"被行为覆盖"；按功能看，`shards.py`/`study.py` 的冻结链路覆盖较好（对应测试体量大），`formal.py` 的 `unattributed` 分支无测试（§3.4）。

### 6.2 scripts 层（57 个文件，29 个零测试）

| 状态 | 文件 |
|---|---|
| 有测试（28） | `formal`/`strict_compare`/`locked_agents`/`verify_patches`/`run_formal_240.archive_incomplete_jobs`/`benchmark_health`（新增）/`reconcile_results`/`lint_metrics`/`calibrate_cloud`/`qualify_*`/`prepare_*`/`ci_smoke`/`auto_resume`/`split_sample`/`generate_sharded_workflow`/`build_sqlite_vec_musl` 等 |
| **零测试（29）** | `analyze_behavior`、`analyze_behavior_result`、`analyze_context_ab`、`analyze_new_benchmark`、`analyze_partial_scores`、`analyze_pilot_trial`、`analyze_repeat_consistency`、`analyze_trials`、`annotate_served`、`audit_agent_traj`、`build_analysis_dataset`、`check_summary_trigger`、`check_version_hypothesis`、`compare_predictions`、`compare_trials`、`compose_large_sample`、`compose_swe_evo_sample`、`convert_swe_evo`、`final_stats`、`make_context_noise`、`pick_pilot`、`predict_pilot`、`profile_summary`、`rename_tasks_short`、`run_holdout`、`run_regression`、`split_sample`、`summarize_large_set`、`verify_task_baseline` |

其中**高危零测试**：

1. `convert_swe_evo.py` —— SWE-EVO 接入的转换器（CRLF/Py3.8/CI-patch/pytest 两种输出格式全在它里面；R3 复盘记录的 6 个坑都修在它里面，**无任何回归测试**）。
2. `verify_task_baseline.py` —— 新题库准入的唯一硬门槛（假题筛除 + p2p 过滤），无测试。
3. `compose_swe_evo_sample.py` / `compose_large_sample.py` —— 组题逻辑（分层/配额），无测试。
4. `run_holdout.py` / `run_regression.py` —— 跑批入口（与 `run_formal_240` 同级的另一条链路），无测试。
5. `audit_agent_traj.py` / `benchmark_health.py` 的**判定逻辑**（后者已有测试，前者没有）—— 这是"发现整组基线失效"的工具，本身没有回归测试。

### 6.3 `run_formal_240.py` 分支覆盖

| 分支 | 覆盖 |
|---|---|
| `archive_incomplete_jobs`（P0 修复点） | ✅ `tests/test_run_formal_240_archive.py`（SWE-EVO 命名，行为断言） |
| `--skip-existing` 判据 | ✅ 同上（另一用例） |
| `main_async` 编排（agent 循环、并发、错误汇总） | ❌ |
| `container_mem_mb` / `mem_supervisor` / `AdaptiveSemaphore` | ❌ |
| `install_verifier_throttle`（monkey-patch Harbor） | ❌ |
| `prune_networks` | ❌ |

即：**历史上出事故最多的"编排层"仍无测试**，只有"归档判据"这一处有。这与第一轮 `46f57f0` 的教训同构——修了 bug 的位置补了测试，主流程照旧无保护。

---

## 七、建议

### 7.1 应立即处理（P0，半天内）

1. **修复产品 venv 的临时目录**：设置 `TMPDIR`/`--basetemp` 指向可写且不在 git 仓库内的目录，使 4 个长期失败测试回到"能区分真伪失败"的状态。**这 4 个不应继续作为"已知失败"挂着**——它们现在掩盖任何真实回归。
2. **把 `MISSING_CLASSES` 与协议 §3 的偏差（7 vs 6）用一条测试锁住**：断言类集合等于协议列出的集合（或断言 `unattributed` 的处置语义），防止再次"代码与文档各说一套"。

### 7.2 应补的测试（P1）

| 优先级 | 补什么 | 理由 |
|---|---|---|
| 高 | `run_formal_240.main_async` 的**编排行为**（用假 job 分钟级、断言归档/skip/汇总调用顺序），以及 `mem_supervisor` 的降并发决策 | 历史事故最多；当前 0 覆盖 |
| 高 | `convert_swe_evo.py` 的转换黄金样本（CRLF 输出、Py3.8 parser、CI patch 过滤、两种 pytest 输出） | 新题库准入的全部坑都在这里，0 测试 |
| 高 | `verify_task_baseline.py` 的假题/usable/broken 判定 | 新题库准入硬门槛，0 测试 |
| 中 | `formal.unattributed` 分支（无 task_id / repeat<1 的行不进分母） | 当前仅注释提及 |
| 中 | `verify_patches._inner_dir/_task_of`（非 instance_ 命名已有 `collect_pending` 覆盖，但这两个函数没有独立用例） | P0 修复点的旁支 |
| 中 | 产品 2 个 C 类（`test_runtime_additional:155`、`test_truncation_continuation:169`）补成参数断言 | 现有断言过弱 |

### 7.3 可删/可替换（P2）

- **不删**任何 A 类；D 类 9 个是环境 skip，保留并在 CI 或本机显式开启。
- **替换而非删除** B 类的"源码文本断言"：把 `test_locked_agents.py` 等对 `run_formal_240.py` 源码字符串的断言，换成对 `archive_incomplete_jobs()` 返回值/目录状态的断言（`test_run_formal_240_archive.py` 已是正确范式，值得推广）。
- **保留**合理的 mock 断言（外部副作用类）。

### 7.4 流程建议

1. **每次 P0 修复必须附"变异可抓"证明**：本轮 5/5 全抓说明 P1 做对了；把"把代码改回旧行为，测试必须红"写进复盘检查清单。
2. **scripts 层测试纳入同一条门槛**：`run_formal_240`/`verify_patches`/`locked_agents` 是正式跑批三件套，不应只有"某个 bug 的补丁测试"。
3. **测试运行环境纳入健康检查**：`pytest --basetemp` 与 `tempfile.gettempdir()` 应在 `ci_smoke` 或 `--collect-only` 前断言"不在 git 仓库内"，否则 4 个失败会再次被误读为产品缺陷。

---

## 八、附：方法与可复现命令

```powershell
# 1) 分级统计（AST + collect 解析）
python C:\sb\tmp\explore\quality_audit.py C:\develop\sayacode-bench\tests `
  C:\sb\tmp\explore\bench-collect.txt bench C:\sb\tmp\explore\bench-quality.json
python C:\sb\tmp\explore\quality_audit.py C:\develop\sayacode\tests `
  C:\sb\tmp\explore\product-collect.txt product C:\sb\tmp\explore\product-quality.json

# 2) 变异测试（沙箱副本 C:\sb\tmp\mut，跑完自动恢复；基线 135 passed）
python C:\sb\tmp\explore\mutate_test.py

# 3) 覆盖盲区（静态引用）
python C:\sb\tmp\explore\coverage_gaps.py

# 4) 产品 4 个失败复现
cd C:\develop\sayacode
uv run --no-sync pytest tests/evals/test_execution.py tests/memory/test_repository.py `
  tests/tasks/test_task_safety.py tests/tools/test_security_boundaries.py -q
```

原始数据：`bench-quality.json`、`product-quality.json`、`mutation-results.json`（均在 `C:\sb\tmp\explore`）。全仓仅写入本报告一个文件。
