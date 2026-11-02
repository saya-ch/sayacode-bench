# Collaboration 场景小样本验证（2026-11-02）

> 目的：验证「开放团队工具」的 `team` 变体在**适合协作的任务**上是否真的派发子 agent（`task_count > 0`）。
> 背景：v2 的 240 trial（SWE-bench Pro）`task_count` 全 0，但那批是单点修复题，不能据此评价协作机制。本验证用产品自带场景补上。
> 结论先行：**`task_count = 0`——team 变体没有派发子 agent；两种变体都靠单 agent 完成，质量都通过。**

## 一、方法

- 场景：`evals/scenarios/collaboration-autonomous.jsonl`（1 题 `collaboration-parcel-autonomous`，fixture `holdout-parcels`）。
- 运行器：`evals/run.py` 的 trial 逻辑在沙箱内无法运行（Python 子进程访问 Docker named pipe 被拒，见 LESSONS 1.9），因此**手动复刻**：
  - `docker build -f evals/Dockerfile -t sayacode-eval:local .`
  - 复制 fixture → `workspace`，创建 `state`；
  - `docker run --read-only --cpus 2 --memory 2g --add-host host.docker.internal:host-gateway`；
  - 写 `state/input.json`（prompt / profile / variant / team_enabled）；
  - `docker exec python -B /opt/evals/worker.py`。
- 模型：`evals/profiles/magpie-deepseek.json`（`auto/deepseek-v4.1-flash`，65536 ctx / 8192 output，Magpie `:3425`）。
  - 注：默认 `commandcode.json`（`:8787` 反代）返回 `insufficient credits`，不可用。
- 判分：宿主 `python -m unittest discover -s tests` + 保护文件 SHA256 对比。

## 二、结果

| 指标 | team | single |
|---|---|---|
| status | completed | completed |
| **task_count** | **0** | **0** |
| child_roles | `[]` | `[]` |
| unittest | **14/14 OK** | **14/14 OK** |
| 保护文件（README / test_public.py） | 未修改（哈希一致） | 未修改（哈希一致） |
| model_calls | 7 | 8 |
| input_tokens | 53,756 | 59,354 |
| output_tokens | 3,872 | 5,514 |
| total_tokens | 57,628 | 64,868 |
| duration | 34.1s | 62.9s |
| messages | 21 | 24 |

- 两种变体都完整实现了三项需求（store.find/all、Parcel.cancel、service.register 幂等/list_by_status/cancel），并自建 13 个测试。
- **`team` 变体没有派发任何子任务**：`tasks=[]`、`child_roles=[]`、`task_count=0`，即使 `team_enabled=true`。
- 单次样本下 team 的 token/耗时略低（57.6K/34s vs 64.9K/63s），但 n=1，**不能当效率结论**。

## 三、解读（能说与不能说）

**能说**：
- 在 collaboration-autonomous 场景、`deepseek-v4.1-flash` 下，**模型选择单干，未使用团队工具**。
- 两种变体都能完成任务且不破坏保护文件；该题对两者都不构成区分。

**不能说**：
- 不能推断「团队机制无效」——`task_count=0` 只说明**本模型在本任务上没派发**，可能是模型偏好、任务规模（3 个需求、34–63 秒）不值得派发、或派发触发条件未被满足。
- 不能推断 team 更省——n=1，且 token/时长受随机性影响。
- 不能替代 evals 的完整 32 题集；本验证只覆盖 1 题 1 次。

## 四、限制与未闭环

1. **沙箱限制**：`evals/run.py` 用 `subprocess` 调 docker CLI，被 named pipe 拦截；本验证用手动脚本绕过，未改产品代码。
2. **镜像问题**：首次 build 因 `uv.lock` 未随 3.2.6 更新而失败（已修）；容器内 `.pyc` 损坏（Dockerfile 已加 `find ... -delete`）；`host.docker.internal` 解析 IPv6（已用 `--add-host host-gateway`）。
3. **模型额度**：`:8787` 反代 `insufficient credits`，改用 `:3425` Magpie。
4. **样本量**：1 题 × 2 变体 × 1 次；要判断协作收益需按 `MULTI-MODEL-PLAN.md` 的 A 阶段跑 20 题 × 2 × 2。
5. **未跑判分器**：用 unittest + 哈希代替 `evals/graders.py`，未覆盖全部 checks（Python 检查片段已由 14 测试间接覆盖）。

## 五、复现

```powershell
cd C:\develop\sayacode
docker build -f evals/Dockerfile -t sayacode-eval:local .
powershell -NoProfile -File C:\sb\hard\collab_manual.ps1 -Variant team
powershell -NoProfile -File C:\sb\hard\collab_manual.ps1 -Variant single
```

产物：`C:\sb\hard\collab-check-manual\trials\<case>--<variant>--1\`（`state/worker-result.json`、`workspace/`、`worker.log`）。

## 六、下一步

1. 用 `evals/run.py` 在**非沙箱**终端跑完整 `collaboration-autonomous` + `collaboration` 两个场景（各 2 变体 × 2 重复）。
2. 若 `task_count` 仍为 0，检查 `worker.py` 的 `team_enabled` 是否真正注册工具（日志/工具列表），并试更强的模型（hy3）或更长任务。
3. 把「team 是否派发」做成 `worker-result.json` 的显式字段（已有 `task_count`/`child_roles`），纳入报告模板。
