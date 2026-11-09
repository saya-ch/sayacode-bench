# pro-v2 四 agent 对比：执行中（2026-11-10 启动）

> 状态：**运行中**，2026-11-10 02:05 启动，预计 41 小时。
> 本文只记录启动时的已知事实与冒烟结果，正式结果另文。

## 1. 冒烟结果（pro-v2 navidrome 单题，2026-11-10 01:20~02:02）

| agent | reward | 耗时 |
|---|---:|---:|
| sayacode 3.3.0 | **0** | 21:05 |
| mini-swe | 1 | 15:28 |
| claude-code | 1 | 16:01 |
| opencode | 1 | **5:48** |

**流程全部跑通。但 1 题不能说明任何问题**——这题上 sayacode 输给三个基线，
而 mini-swe / claude-code / opencode 需要对照的历史数据也还没有。

## 2. 正式运行配置

| 项 | 值 |
|---|---|
| 题集 | `studies/large-sample-v1-pro-v2.json`（40 题，**未污染的 holdout**）|
| agent | sayacode 3.3.0 / mini-swe / claude-code / opencode |
| 重复 | 1（不是 2——40×2 是伪重复，会把独立样本数虚报一倍）|
| 总 trial | 160 |
| 并发 | 1（提交内存 84%，只能跑 1 个 2GB 容器）|
| 分批 | 5 批 × 8 题，每批跑完删镜像 |
| 预计 | 约 41 小时 |

### 为什么是这 40 题

从 642 题题库里排除已污染的 40 题（`sample-40-final` 及其子集）后，
按来源分层抽出的 pro-v2 分片。与旧实验题集**零重叠**。

### 为什么 repeats=1

`sample-40-final` 的 40 题 × 2 repeat 被当作 80 个观测用过，但同题两跑
不是独立样本——80 trial 实际只有 40 个独立配对。这正是此前
「mini-swe 高 6.2pp」却 p=0.189 测不出来的原因。

单次重复 + 更多题量，独立样本数才等于 trial 数。

## 3. 环境约束（重要，会限制解读）

| 资源 | 值 | 影响 |
|---|---:|---|
| 磁盘 | 89.9GB | 够（每批 8 题约 24GB）|
| 提交内存 | 84% | **并发只能 1** |
| ComfyUI（PID 15176）| 预留 8.92GB 提交 | 关掉可并发 3~4，时间降到 12 小时 |

## 4. 判分口径差异（必须分开报，不能合并）

| 题库 | 判分 | 测试级明细 |
|---|---|---|
| swe-bench-pro-v2 | `parser.py` 解析 F2P/P2P | `verifier/output.json` |
| terminal-bench-2.1 | `test.sh` 写 reward.txt | `ctrf.json` |

本次只跑 pro-v2，口径统一。将来加 tb21 时**不能混在一起算总通过率**。

## 5. 已知的判断题集坑

| 题库 | 状态 |
|---|---|
| pro-v2 | ✅ 一等公民 |
| tb21 | ✅ 一等公民（需本地构建镜像，内存不足时失败）|
| swe-evo | ⚠️ 不在 `study.py` 白名单，只有目录命名兼容；15 题名字可转换（已验证 15/15）|
| promax | ❌ 缺 `run_script`/`parsing_script`/F2P/P2P，**无法判分**，已排除 |

多题库题集的 `task_id` 带 `source/` 前缀，而题目录名是不带前缀的 native_id。
`run_formal_240` 已修（`a37233a`）。

## 6. 本轮修掉的缺陷

| commit | 内容 |
|---|---|
| `a37233a` | task_id 带题库前缀时，路径和 job 名都要剥掉 |
| `1356faf` | 缺失运行输入在启动前报错；exception 记录 message 与 ExceptionGroup 子异常 |

第二个缺陷是这次卡住最久的：`require_inputs` 写了但从未调用，
异常又只记 `type(exc).__name__`，导致 sayacode 每次都 10 秒失败、
只留一个 `ExceptionGroup` 类型名。补上 message 记录后才看到根因是
`SAYACODE_BENCH_VARIANT` 未设置、默认值指向已不存在的
`C:\sb\r\formal-study-v1\...`。
