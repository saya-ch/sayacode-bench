# pro-v2 四 agent 对比：执行记录与已知缺陷（2026-11-10 启动 → 2026-11-11 完成）

> 状态：**已完成**（160 trial 全部跑完）；结果与结论见 [RESULT-PROV2-4AGENTS-FINAL.md](RESULT-PROV2-4AGENTS-FINAL.md)。
> 本文记录运行配置、判分口径，以及**已知缺陷与修复状态**——引用结果前必须先读 §6。

## 1. 冒烟结果（pro-v2 navidrome 单题，2026-11-10 01:20~02:02）

| agent | reward | 耗时 |
|---|---:|---:|
| sayacode 3.3.0 | **0** | 21:05 |
| mini-swe | 1 | 15:28 |
| claude-code | 1 | 16:01 |
| opencode | 1 | **5:48** |

**流程全部跑通。但 1 题不能说明任何问题**——这题上 sayacode 输给三个基线，而 mini-swe / claude-code / opencode 需要对照的历史数据也还没有。

## 2. 正式运行配置

| 项 | 值 |
|---|---|
| 题集 | `studies/large-sample-v1-pro-v2.json`（40 题，与旧开发集零重叠）|
| agent | sayacode 3.3.0 / mini-swe / claude-code / opencode |
| 重复 | 1（40×2 是伪重复，会把独立样本数虚报一倍）|
| 总 trial | 160 |
| 并发 | 1（提交内存 84%，只能跑 1 个 2GB 容器）|
| 分批 | 5 批 × 8 题，每批跑完删镜像 |
| 实际耗时 | 约 17 小时（含 4 次环境事故，见 §7）|

### 为什么是这 40 题

从 642 题题库里排除已污染的 40 题（`sample-40-final` 及其子集）后，按来源分层抽出的 pro-v2 分片，与旧实验题集**零重叠**。

### 为什么 repeats=1

`sample-40-final` 的 40 题 × 2 repeat 被当作 80 个观测用过，但同题两跑不是独立样本——80 trial 实际只有 40 个独立配对。这正是此前「mini-swe 高 6.2pp」却 p=0.189 测不出来的原因。

单次重复 + 更多题量，独立样本数才等于 trial 数。**代价是丢掉题内方差估计**：单跑无法直接测 flaky，只能从历史 `v2-325` 迁移估计（见结果文档 §3）。

## 3. 环境约束

| 资源 | 值 | 影响 |
|---|---:|---|
| 磁盘 | 89.9GB | 够（每批 8 题约 24GB）|
| 提交内存 | 84% | **并发只能 1** |
| ComfyUI（PID 15176）| 预留 8.92GB 提交 | 关掉可并发 3~4，时间降到 12 小时 |

## 4. 判分口径（必须分开报，不能合并）

| 题库 | 判分 | 测试级明细 |
|---|---|---|
| swe-bench-pro-v2 | `parser.py` 解析 F2P/P2P | `verifier/output.json` |
| terminal-bench-2.1 | `test.sh` 写 reward.txt | `ctrf.json` |

本次只跑 pro-v2，口径统一。将来加 tb21 时**不能混在一起算总通过率**。

### 4.1 本批采用的分类规则（`C:\sb\tmp\run100\analyze.py` 文件头注释）

1. **`reward` 优先**：`verifier/reward.txt` 是 ground truth，不是 `normalized.json.status`。Harbor 会在 job 收尾时用 `infrastructure_error` 覆盖已通过的 trial，只看 status 会造成假阴性。
2. **只有「verifier 完全没有产出 reward 且异常来自 harness」才算 `infrastructure`**。有 reward=0 的 trial（哪怕 status 写着 infrastructure_error）一律算 `model`。
3. **超时留在分母**：用完时间预算是 agent 的失败，不是 harness 的失败。
4. **空 patch 留在分母**：模型跑完但没产出属于 `empty_patch`（能力/行为类，协议规定不补）。

> 这四条是 2026-11-11 更正后的规则。旧版把「有 reward=0 但 status=infrastructure_error」也算基建失败，导致分母被压小、通过率虚高（详见结果文档 §0）。

### 4.2 三口径

| 口径 | 分母 | 回答的问题 |
|---|---|---|
| `all` | 40（infra/timeout 算失败）| 实际完成率 |
| `effective` | 40 − infra（**timeout 不排除**）| 排除「我们跑不起来」后的能力对照 |
| `complete-case` | 四家都无 infra/timeout 的 29 题 | 排除「题目本身坏掉」的影响 |

## 5. 已知的判断题集坑

| 题库 | 状态 |
|---|---|
| pro-v2 | ✅ 一等公民 |
| tb21 | ✅ 一等公民（需本地构建镜像，内存不足时失败）|
| swe-evo | ⚠️ 不在 `study.py` 白名单，只有目录命名兼容；15 题名字可转换（已验证 15/15）|
| promax | ❌ 缺 `run_script`/`parsing_script`/F2P/P2P，**无法判分**，已排除 |

多题库题集的 `task_id` 带 `source/` 前缀，而题目录名是不带前缀的 native_id。`run_formal_240` 已修（`a37233a`）。

## 6. 已知缺陷与口径（引用结果前必读）

> 本节是 2026-11-11 重写版：把本批暴露的缺陷按「已修 / 未修」分开，并给出对结论的影响方向。修复提交 `c8dba0e`。

### 6.1 已修（`c8dba0e`，2026-11-11）

| # | 缺陷 | 现象与根因 | 修复 | 对结论的影响 |
|---|---|---|---|---|
| 1 | **网关配置缺 `/v1` 无人拦** | `SAYACODE_BENCH_GATEWAY` 少 `/v1` 时，`require_inputs` 只查文件存在；隔离层要求上游路径恰好以 `/v1/messages` 结尾，于是每个 trial 在 10 秒内以 `ExceptionGroup → ValueError` 失败，异常正文不含实际配置值。**本轮实测白跑 32 个 trial** | `network.validate_upstreams` 复用 `_endpoint` 的同一份规则，在 `env_cfg` 构造环境时就校验，报错带实际地址与期望后缀 | 已修；这批 32 条已按 `infra` 处理，不进入能力比较 |
| 2 | **job 收尾 OSError 吞掉已通过的 trial** | Harbor 在 Windows 上 job 收尾抛 `OSError [Errno 22]`，而 trial 已跑完、验证器已给 `reward=1.0`；旧实现无条件写 `infrastructure_error` | `_recover_finished_trial` 在 `except` 分支按 Harbor 的 `TrialResult` 反序列化抢救现场；trial 自身报错或没有验证器结果时仍保留 `infrastructure_error`（不把真失败洗成成功） | 实测挽回 **2 条 mini-swe 假阴性**（`qutebrowser-ff1c025ad`、`teleport-db89206db6`）。旧版把 mini-swe 记为 26/40 的算法就是被这条缺陷咬到；正确是 **28/40** |
| 3 | **内部 timeout 被记成 infrastructure** | `budget = timeout_sec - 60` 导致内部 timeout 永远先触发，退出码 124 被 Harbor 归成 `NonZeroAgentExitCodeError`；按旧规则会算基建失败 | 保留 timeout 包裹，把退出码 124 映射成 Harbor 原生的 `AgentTimeoutError`，`execution.py` 据此判 `status=timeout` | 3 条；修正后 timeout 留在分母（符合「timeout 不补」） |
| 4 | **长跑零产出被当成基建失败** | `openlibrary-427f1`（2476 s）、`teleport-b5d8169`（1332 s）的 verifier 正常跑完、`exception` 为空、只 patch 为 0 字节；旧规则把它们算成 infra 并从分母删除 | 分析侧改为「只有 verifier 完全没产出 reward 且异常来自基建才算 infra」；`empty_patch` 留在分母 | **直接改变排名**：sayacode 有效通过率从虚高的 75.9% 回到 **64.71%**，「与 opencode 持平」的结论作废（详见结果文档 §0） |

### 6.2 未修：musl/Alpine 镜像的系统性偏差（**最需要警惕的一条**）

**事实**：protonmail 的两个 task（`09fcf0dbdb8…`、`e7f3f20c8ad…`）在 40 题集里共 **3 题**（webclients 仓库）；其中 **2 题**上 claude-code / opencode / sayacode **三家全部 infrastructure**，只有 mini-swe 通过（2/2）。根因是这两个镜像基于 **musl（Alpine）**：

- claude-code / opencode 用 glibc 预编译二进制：`rc=127` + `cannot execute: required file not found`，`/lib64/ld-linux-x86-64.so.2` 在 musl 镜像不存在；
- sayacode 的 `requirements` 含 `sqlite-vec==0.1.9`，**没有 musllinux wheel**，`uv pip install --require-hashes` 无解。

**影响方向**：这是**对 mini-swe 单方面有利**的系统性偏差。按 2 题 / 40 的上界估算，相当于给 mini-swe 白送约 **5pp**（2/40）；若把同一偏差在更大题集上的比例外推（webclients 类题若占更高比例），偏差会更大。**尚未修**，修复路径见 `C:\sb\tmp\audit\infra\ROOTCAUSE.md` §组 1：

1. install 前检测 musl（`test -f /etc/alpine-release` 或 `ldd --version | grep -q musl`），对 musl 镜像使用 musl 版 tarball；无 musl 版时明确报错并带镜像名，禁止静默 127；
2. 对 `sqlite-vec` 走源码构建或显式记录 `sqlite_vec_unavailable`，避免每 trial 白耗约 45 s × 3 次重试；
3. 失败信息必须带 `rc` 与 stdout（旧实现 `result.stderr=None`，真正的 `rc=127` 只进了 `logger.info`）。

> 口径核对：任务简报写「webclients 8 题」，与 40 题集的实测（webclients 仓库 3 题，其中 2 题受影响）不符；本文以实测为准。若「8 题」指更大评测集里的比例，需要另做统计，本文未做。

### 6.3 未修 / 未复核的其他缺陷

| 项 | 状态 | 说明 |
|---|---|---|
| 2 条「启动后异常退出」的分类 | **口径边界，未裁定** | `flipt-6fe76d024ee0`（172 s）、`teleport-78b0d8c726`（138 s）有 verifier 输出 reward=0，但异常是 `NonZeroAgentExitCodeError`；本文按 `analyze.py` 归 `model`，若归 `infra`，sayacode 分母 34→32、通过率 64.71%→68.75% |
| `audit.jsonl` schema 不匹配 | **未复核** | 无法确认两条空 patch 是「写了又撤销」还是「采集失败」；只能确认无异常、verifier 跑完、patch 为空 |
| 旧版「4 个误判」 | **只确认 3 个** | 第 4 个在现有产物中找不到证据 |
| F2P/partial | **不进主结论** | `partial` 有两个数据源、差 2.4–6.8pp（[RESULTS-LEDGER §5.5](RESULTS-LEDGER.md)）；旧版 F2P 表未复核，不应引用 |
| 题集作用域 | **已标注** | `tutao` 仅 1 题、`protonmail` 仅 3 题且 infra 率高，这两个 repo 的结论不可用 |

### 6.4 历史缺陷（本批之前修掉，保留备查）

| commit | 内容 |
|---|---|
| `a37233a` | task_id 带题库前缀时，路径和 job 名都要剥掉 |
| `1356faf` | 缺失运行输入在启动前报错；exception 记录 message 与 ExceptionGroup 子异常 |

第二个缺陷是当时卡住最久的：`require_inputs` 写了但从未调用，异常又只记 `type(exc).__name__`，导致 sayacode 每次都 10 秒失败、只留一个 `ExceptionGroup` 类型名。补上 message 记录后才看到根因是 `SAYACODE_BENCH_VARIANT` 未设置、默认值指向已不存在的 `C:\sb\r\formal-study-v1\...`。

## 7. 实验过程中的环境事故

| 时间 | 事件 | 影响 |
|---|---|---|
| 20:01 | 外层 ps1 静默死亡 | 第 3 批中断，改用 takeover 脚本 |
| 20:58 | 同上 | 第 4 批重启 |
| 22:17 | Docker daemon 500 崩溃 | 第 4 批中断 |
| 09:00 | Docker 反复 500 | 第 5 批三次失败 |
| 10:22 | vhdx 从 55GB 涨回 108.7GB，磁盘剩 18.9GB | 阻塞 |
| 10:30 | 清理 uv/Temp/npm/pnpm 缓存释放 36GB | 恢复 |

**根因**：vhdx 膨胀 + Windows 磁盘被挤到 19GB，Docker 在低磁盘下不稳定。

## 8. 缺陷收集与复算产物

| 项 | 路径 |
|---|---|
| 结果数据 | `C:\sb\hard\ab-ctx\prov2-40x4` |
| 顶部汇总（本文对应） | `C:\sb\tmp\collect_failure_causes.py` |
| 误判扫描 | `C:\sb\tmp\scan_false_negatives.py` |
| 复算脚本（结果文档用） | `C:\sb\tmp\run100\analyze.py` |
| 基建取证 | `C:\sb\tmp\audit\infra\ROOTCAUSE.md`、`evidence.txt` |
| 对抗复核 | `C:\sb\tmp\audit\challenge\CHALLENGE.md` |
| 数字独立重算 | `C:\sb\tmp\audit\numbers\NUMBERS.md` |
