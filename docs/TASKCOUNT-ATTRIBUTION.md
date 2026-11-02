# team 变体 task_count=0 归因报告

> 范围：只读代码 + 已有产物核对 + 2 次少量验证（复用 `collab_manual.ps1` 流程，镜像 `sayacode-eval:local`，网关 `127.0.0.1:3425`）。
> 结论标注了**直接证据**与**推断**；未修改产品逻辑，未 commit。

---

## 一、结论（先看这个）

**task_count=0 不是"工具不可见"，也不是"调用失败"，而是"任务规模小 + 触发条件未满足 + 模型遵循系统提示选择单干"。**

四象限判定：

| 候选原因 | 判定 | 关键证据 |
|---|---|---|
| **工具不可见**（注册失败/被过滤） | **排除**（team 变体下） | 同一镜像/同一 profile/同一 team_enabled=true，在题面明确要求派发的题上，`delegate_to_subagent` 实际被调用 2 次，`task_count=2`、`child_roles=["reviewer","planner"]`、`failed_child_tasks=0`（验证 A） |
| **调用失败**（派发报错/子任务未登记） | **排除** | 验证 A 的两个子线程 `task-8878e8564938`、`task-2ea9e711ef09` 在 audit 中各有 29/39 条事件、13/9 次工具调用，主线程用 `task_status`×2 + `task_wait`×2 收齐；`failed_child_tasks=0` |
| **触发条件未满足** | **成立（主因之一）** | 原 trial 的题是 `collaboration-autonomous`（"如何组织工作由你决定"，`followups=[]`）；而明确要求协作的 `collaboration-parcel-combined` 在 team 下 2/2 派发 |
| **任务规模不值得派发 / 模型偏好单干** | **成立（主因之一）** | 原 trial 只改 3 个文件（store/models/service 各数十行），7–8 次模型调用、34–63 秒完成；且**连 `write_todos` 都没调用**（team autonomous trial 的工具序列只有 read_file×5 / write_file×4 / execute×3 / list_directory×1）——模型判定为"一处即可完成的小修复"，符合 `prompts.py:22` 的"不要派发单个小修复" |

**一句话**：产品侧 team 工具链是好的（可见、可调、能跑通）；`task_count=0` 是因为**评测题没有给模型"值得派发"的理由**，模型按提示做了单干。

---

## 二、代码事实（注册链路，逐行）

### 2.1 `evals/worker.py`：team_enabled 如何传给产品、task_count 从哪来

- `worker.py:172`：`team_enabled=spec["team_enabled"]` 直接传给 `SayacodeApp(...)`。
- `worker.py:222-224`：
  ```python
  records = [record for record in await app.tasks.list() if record.parent_thread_id == app.session_id]
  ```
- `worker.py:250-251`：`"task_count": len(records)`、`"child_roles": [record.role for record in records]`。
- `worker.py:262`：**异常兜底**也写 `task_count: 0`（注意：若 worker 抛异常，看起来同样是 0，需与"正常完成但没派发"区分——本次已有产物 `status=completed`，故不是这一支）。

**含义**：task_count 只统计 `parent_thread_id == "eval-main"` 的直接子任务。模型不调用派发工具 → 0；派发后子任务正常登记 → >0。

### 2.2 `src/sayacode/application.py`：工具注册

- `application.py:97`：`team_enabled: bool = True`（默认开启）。
- `application.py:118`：`self.team_enabled = team_enabled`。
- `application.py:511-536` `_tools_for_context()`：
  ```python
  if include_team_tools and self.team_enabled:      # :527
      items.extend(parent_tools(self))              # :528  ← 5 个团队工具
  elif context.task_id is not None:                 # :529
      items.extend(child_tools(self))               # :530  ← 子 Agent 只有 report_to_parent
  if context.agent_role in READ_ONLY_ROLES:         # :531
      items = [item for item in items if item.name in READ_ONLY_ALLOWED_TOOLS]
  elif context.trust_level == "read_only":          # :533
      allowed = READ_ONLY_ALLOWED_TOOLS | {"delegate_to_subagent"}   # :534
  ```
- `include_team_tools` 的取值：`sessions.py:200` `include_team_tools=not bool(metadata.get("is_background"))`（主会话为 True）；`application.py:724` `include_team_tools=thread.get("task_id") is None`（主线程为 True）；`tasks/manager.py:551` 子任务显式 `include_team_tools=False`（子 Agent 不能再派发）。

**结论**：`team_enabled=True` + 主线程 → 必然注册 5 个父工具；`team_enabled=False` → **一个都不注册**（这是设计）。

### 2.3 `src/sayacode/tasks/tools.py`：工具本体

`parent_tools()`（`tools.py:16-129`）返回 5 个工具：

| 工具 | 行号 | 作用 |
|---|---|---|
| `delegate_to_subagent(task, role, use_worktree, title)` | `:19-69` | 派发独立后台子 Agent；role ∈ {builder, planner, reviewer}；调 `app._spawn_task(...)`（`:45`） |
| `send_message_to_subagent` | `:71-88` | 向直接子 Agent 追加要求 |
| `task_status` | `:90-97` | 读子 Agent 状态与交付元数据 |
| `task_delivery` | `:99-105` | 查看 builder 工作树交付差异 |
| `task_wait` | `:107-121` | 限时等待子 Agent 当前轮结束 |

`_spawn_task`（`application.py:981-1047`）→ `self.tasks.spawn(...)`（`:1031`）登记 record（`parent_thread_id` 由 `delegate_to_subagent` 传入 `context.session_id`，`tools.py:48`）。

### 2.4 系统提示：**无论 team_enabled 与否，都告知模型"可以派发"**

- `prompts.py:22`（`_ROLE_RULES["main"]`）：
  > "**Dispatch trigger: when the request spans two or more areas you could investigate independently** (separate modules or layers, a plan plus an independent review, or unrelated files), dispatch bounded read-only subagents for those areas and keep working on your own part while they run. **Do not delegate a single small fix you can do directly.**"
- `prompts.py:99-137` `build_system_prompt(...)`：只按 `role` 选 `_ROLE_RULES[role]`，**不接收、也不判断 `team_enabled`**；`application.py:649-654` 调用时也只传 `role=context.agent_role`。
- `graph.py:40-56` `_SAYACODE_PLANNING_PROMPT`（挂到 `TodoListMiddleware`，`graph.py:333-338` **无条件加载**）同样写着 "Background tasks are asynchronous. After delegation, continue any independent work…"、"When delegating, give the child a bounded objective…"。

**由此产生一个已实测的不一致（风险 R1）**：`team_enabled=False`（single）时，模型仍被系统提示告知"可以派发、应该派发"，但工具集里没有任何派发工具。验证 B 中模型明确写道："本会话可用工具集中没有任何子 Agent 或任务派发工具……`list_skills` 两次查询都返回 total:0……在 Shell 里探测 sayacode / agent / task / claude / codex / aider 全部为 missing"——即模型**按提示去找派发能力，浪费了 1–2 次探测调用**，最后诚实声明"未能完成协作"。

### 2.5 只读角色的额外约束

`approvals/policy.py:21` `READ_ONLY_ROLES={planner, reviewer}`；`:43` `READ_ONLY_ALLOWED_TOOLS` 不含 `delegate_to_subagent`；`:71-74` 只在 `role∈{planner,reviewer}` 时把 `delegate_to_subagent` 视为只读可放行。主 Agent（role=main）不受影响，可正常派发 builder/planner/reviewer。

---

## 三、已有产物核对（`C:\sb\hard\collab-check-manual`）

| 字段 | team trial | single trial |
|---|---|---|
| 题目 | `collaboration-parcel-autonomous`（"如何组织工作由你决定"） | 同 |
| input.json `team_enabled` | **true** | **false** |
| `status` | completed | completed |
| **`task_count`** | **0** | **0** |
| `child_roles` | `[]` | `[]` |
| `turns[].tasks` | `[]` | `[]` |
| `failed_child_tasks` | 0 | 0 |
| `duration_seconds` | 34.1 | 62.9 |
| `model_calls` | 7 | 8 |
| 实际工具序列（events.jsonl） | read_file×5, write_file×4, execute×3, list_directory×1 | read_file×5, write_file×4, execute×3, list_directory×1, analyze_project×1, git×1 |
| 团队工具调用次数 | **0** | 0（工具不存在） |
| `write_todos` | **0** | 0 |

**判读**：两者都正常完成、都没报错；team trial 的 `tasks=[]` 不是"调用失败留下的空"，而是**根本没有 tool.started(delegate_to_subagent) 事件**——是"没调用"，不是"调用失败"。且模型连 todo 计划都没写，说明它判定任务简单（系统提示允许"Skip the todo list for a simple answer or one obvious action"，`graph.py:44`）。

---

## 四、两次少量验证（≤2 次，均用 `sayacode-eval:local` + 3425 网关）

为避免破坏已有产物，副本脚本 `C:\sb\hard\collab_manual_explicit.ps1`（与 `collab_manual.ps1` 流程相同，仅改读 `evals/scenarios/collaboration.jsonl` 第 1 题、输出到 `C:\sb\hard\collab-check-explicit`）。该题 `collaboration-parcel-combined` 的题面**明确要求**"先派发两个不同的只读子 Agent：planner 调查 store.py、reviewer 调查 service.py，两个子任务运行时主 Agent 先做自己的调查"。

| 验证 | 变体 | task_count | child_roles | failed_child_tasks | 耗时 | 关键工具调用 |
|---|---|---|---|---|---|---|
| **A**（明确要求派发） | team | **2** | `["reviewer","planner"]` | 0 | 126.7s | `delegate_to_subagent`×2（planner/reviewer）、`task_status`×2、`task_wait`×2、`write_todos`×2；子线程 `task-2ea9e711ef09`(13 次工具)、`task-8878e8564938`(9 次工具) |
| **B**（同题对照） | single | **0** | `[]` | 0 | 91.2s | 无派发工具；模型明确声明"没有任何子 Agent 或任务派发工具"，并实际探测 `list_skills`×3 与 shell 里的 `sayacode/agent/task/...` |

**A 是决定性证据**：同样的代码、同样的 team_enabled=true、同样的模型，只把"任务是否值得派发"这一变量从"自主判断的小改动"换成"明确要求两条独立调查线"，task_count 就从 0 变 2。→ 排除"工具不可见/调用失败"，锁定"触发条件+任务规模"。

**B 是反向对照**：team_enabled=false 时工具确实不存在（设计如此），且模型会因系统提示的"可派发"描述而去探测，最终诚实降级为单干。→ 证明注册分支按 `team_enabled` 生效，同时暴露 R1 的提示不一致。

审计侧交叉核对（验证 A）：`audit.jsonl` 出现 3 个 thread_id（`eval-main` 145 条、`task-8878e8564938` 29 条、`task-2ea9e711ef09` 39 条），33 次 model 调用；`tool.failed` 仅 2 次，均为 `read_file` 读目录（`[Errno 21] Is a directory: '/workspace/tests'`），**与派发无关**。

---

## 五、为什么原 trial 是 0：逐条排除

1. **不是异常兜底**：`worker-result.json` 的 `status=completed`，非 `failed`；`worker.py:262` 的 `task_count:0` 只在异常分支写。
2. **不是登记失败**：验证 A 证明 `_spawn_task`→`tasks.spawn` 正常，`parent_thread_id` 过滤正确（`worker.py:222-224`）。
3. **不是工具被角色过滤**：主 Agent role=main，不在 `READ_ONLY_ROLES`；trust=full，`_tools_for_context` 不会过滤 `delegate_to_subagent`。
4. **不是团队工具被 feature flag 关闭**：input.json `team_enabled=true`，且 `parent_tools` 注册路径确认（`application.py:527-528`）。
5. **就是"没调用"**：events.jsonl 无任何 `tool.started(delegate_to_subagent|task_*)`；模型 7 次调用即完成，未写 todo，符合"单个小修复直接做"的提示。
6. **题目本身的触发强度不足**：`collaboration-autonomous` 只有一句"如何组织工作由你决定"，没有"跨两个以上可独立调查区域"的显式信号（对照 `prompts.py:22` 的 Dispatch trigger 条件）。

---

## 六、风险与建议

**R1（真实存在，已实测）提示与工具不一致**：`team_enabled=False` 时系统提示仍包含"Dispatch trigger / 派发子 Agent / After delegation…"（`prompts.py:22`、`graph.py:40-56`），但工具为空。后果：模型浪费探测调用、可能"谎称已派发"（本次模型诚实，但不能依赖）。建议：`build_system_prompt` 增加 `team_enabled` 参数（或在 `application.py:649` 按 `self.team_enabled` 选 `_ROLE_RULES["main"]` 的无派发变体），TodoList 的协作段也按开关裁剪。

**R2（评测口径）**：`task_count` 无法区分"没派发"与"派发但子任务 0 秒空转"。建议 `worker-result.json` 增记 `delegate_calls`（events 里 `tool.started(delegate_to_subagent)` 计数）与每子任务 `status/role/turns`，作为 task_count 的旁证。

**R3（题目设计）**：若研究目标是"验证协作能力"，用 `collaboration-autonomous` 这类"自主决定"题会得到 task_count=0 的**正常但无信息量**的结果；应改用 `collaboration-parcel-combined` 这类**显式分工**题，或把任务规模做大到确实跨 2 个以上独立区域（例如多模块重构 + 独立 review）。当前的"autonomous"题实际上是**测"模型是否会不必要地派发"**，而提示明确鼓励"不要派发小修复"，所以 0 是设计上可预期的。

**R4（不要误读历史结论）**：此前把 `task_count=0` 当作"协作能力差/机制不通"的证据是**不成立的**；机制在 team 下 2/2 成功。真正需要评估的是"模型在值得派发时是否派发"以及"派发带来的收益"，这需要专门设计的题面与更大的任务。

---

## 七、证据索引

**代码**
- `evals/worker.py:172`（team_enabled 透传）、`:222-224`（records 过滤）、`:250-251`（task_count/child_roles）、`:262`（异常兜底 0）
- `src/sayacode/application.py:97,118`（team_enabled）、`:511-536`（工具装配，关键 `:527-528`）、`:626-628`（传 include_team_tools）、`:649-654`（build_system_prompt 只传 role）、`:724`（主线程 include_team_tools）、`:981-1047`（_spawn_task）
- `src/sayacode/tasks/tools.py:16-129`（parent_tools 5 工具，`:19-69` delegate_to_subagent）
- `src/sayacode/prompts.py:18-24`（main 角色规则，`:22` Dispatch trigger）、`:99-137`（build_system_prompt 不看 team_enabled）
- `src/sayacode/agent/graph.py:40-56`（规划/协作提示）、`:333-338`（TodoListMiddleware 无条件）
- `src/sayacode/approvals/policy.py:21,43,67-74`（只读角色与 delegate 放行）
- `src/sayacode/sessions.py:200`、`src/sayacode/tasks/manager.py:551`（include_team_tools 之来源）

**已有产物（`C:\sb\hard\collab-check-manual\trials`）**
- `collaboration-parcel-autonomous--team--1\state\input.json`（team_enabled=true）、`state\worker-result.json`（task_count=0, child_roles=[], duration 34.1, model_calls 7）
- `collaboration-parcel-autonomous--single--1\state\input.json`（team_enabled=false）、`state\worker-result.json`（task_count=0, duration 62.9, model_calls 8）
- 两 trial 的 `state\events.jsonl`：均无 `delegate_to_subagent`/`task_*` 的 `tool.started`

**本次验证产物（不 commit）**
- 脚本：`C:\sb\hard\collab_manual_explicit.ps1`
- 验证 A（team，task_count=2）：`C:\sb\hard\collab-check-explicit\trials\collaboration-parcel-combined--team--1\`（`state\worker-result.json`、`state\events.jsonl`、`state\agent\audit.jsonl`）
- 验证 B（single，task_count=0）：`C:\sb\hard\collab-check-explicit\trials\collaboration-parcel-combined--single--1\`
- 题面：`C:\develop\sayacode\evals\scenarios\collaboration.jsonl`（第 1 行 `collaboration-parcel-combined`，显式要求派发 planner+reviewer）
