# AGENTS.md — 仓库维护须知

给在本仓库工作的 AI 与人。**动态维护：发现信息过时或失效，立即更新或删除，不要留着误导后来者。**

## 必须遵守

1. **维护文档**：每次实验或方案变更后，更新 [STATUS](docs/STATUS.md)、[HANDOFF](docs/HANDOFF.md)，必要时更新 [EVALUATION-PLAN](docs/EVALUATION-PLAN-20261030.md)、[ITERATION-WORKFLOW](docs/ITERATION-WORKFLOW.md)。被推翻的结论要显式标「已作废」及原因，并移到 `docs/archive/`；不要静默删改，也不要在 `docs/` 根继续摆着作废文档。
2. **时常推送**：完成一批改动就 `git commit` + `git push origin main`，不要在本地长期累积未推送的提交。
3. **跑前汇报配置**：每次评测启动前用 `python scripts/profile_summary.py <profile>` 汇报模型 / 上下文 / 摘要触发点 / max_output，并取得确认（见 ITERATION-WORKFLOW §8）。
4. **诚实边界**：开发期数字不当正式成绩；作废数字不引用；过程指标（步数/token/改测试）只作诊断，不作「模型更强」的证据；分母不一致不得并列比较。
5. **失败先自己查根因，不要等用户问**。依次查：`job.log` / `exception.txt` / 容器内**实测**（`docker run` 测网络与下载速度）/ 对比 host 与容器行为，定位到具体环节（安装、网络、配置、模型）再汇报；汇报必须带实测证据与已排除项。

## 环境事实（确认无疑）

- **模型网关**：Magpie，host `127.0.0.1:3425/v1`，容器内经 `saya-model-gateway:8080`（支持 `/v1/messages`、`/v1/chat/completions`、`/v1/responses`）。
- **模型**：只用 **hy3**（`auto-hy3` 组，同模型多额度池）。`/v1/models` 实测 context **192,000**、**max_output 64,000**。
  - **hy3 不支持 `temperature`**：传 temperature 无意义（不接受该参数）。可复现性靠**固定来源 + 固定 seed + 重复次数**保证，不要写「temperature=0 已固定」。
  - profile 的 `max_output_tokens` v2 起配 **32,000**（模型上限 64,000，留余量给重试与长回答；v1 配 16,000 导致长任务收尾过早）。
- **基准**：只用 **SWE-bench Pro V2**（642 题，排除 123 musl → **519 可评测**）；暂不使用 Terminal-Bench。
- **开发迭代集**：`studies/sample-40-final.json`（40 题，按仓库分层 + seed 可复现）。**gold-check 实际是 36 good / 1 bad / 3 null**，不是「40 题全绿」；bad 题不在 40 题内，3 个 null 需补齐或替换。
- **容器内存实测**（50 trial 采样）：空载 3–5MB；agent 执行阶段 140–500MB；**验证器阶段峰值可达 2.26GB**（vuls）；任务差异远大于 agent 差异。
- **阶段耗时实测**（50 trial）：environment_setup 8s（1%）、agent_setup 172s（22.5%）、**agent_execution 540s（70.5%，低内存）**、verifier 46s（6%，高内存）。单 trial 均值 12.8 分钟。
- **并发策略**：v2 重建期 **trial 并发 4–6 + 验证器限流 1**（`run_formal_240.py --concurrency 4 --verifier-limit 1`），内存自适应降级（>5GB 降到 2，>3.5GB 降到 4）。历史上限 12 是旧环境调优值，当前保守用 4–6。
- **Docker 崩溃根因**（实测 2026-10-30）：主机物理内存 15.6GB 被 Docker VM（提交 6.9GB）+ 桌面应用 + 系统吃满，提交内存冲到 53.6GB、页面文件峰值 13.8GB → WSL 后端被压垮。**关掉 ChatGPT/WorkBuddy/codex 桌面应用可释放约 2.4GB**。崩溃后 `wsl --shutdown` + 重启 Docker + `--skip-existing` 续跑。
- **Docker 磁盘**：构建缓存与旧镜像可回收约 **142GB**（`docker system prune -a` 前先确认没有要保留的镜像；这是实测可回收量，不是当前占用）。
- **网络**：Clash Verge 已开 TUN + fake-ip；规则模板 `profiles/rNSaXJaGi0rv.yaml` 已加国内镜像（tuna/aliyun/ustc/tencent/huawei）**DIRECT** 规则——否则国内源被代理拖到 30KB/s。改规则后需重启 Clash Verge 生效。
- **每个 trial 占 2 个 Docker 网络**（`instance_*__env_default` + `saya-isolated-*`），默认地址池约 17 个；跑批前后必须 `docker network prune -f`，否则「all predefined address pools have been fully subnetted」。
- 结果目录：v1 在 `C:\sb\hard\formal-240`；v2 在 `C:\sb\hard\v2`。

## 常见坑

1. **分母三套（最严重的坑）**：v1 的 SAYACODE 55/80、mini-swe 69/80、Codex **56/65** 被并列成 68.8%/86.2%/86.2%，制造 17.4pp 假差距；Codex 统一 80 分母是 **70.0%**。任何对比表分母必须一致，缺 trial 就写 79/80，不换分母。
2. **改测试两个口径混用**：产品侧检测率 SAYACODE **39/80 = 48.8%**（被验证器恢复）与 patch 含测试文件比例（SAYACODE **0%** / mini-swe **70.9%** / Codex **54.2%**）是不同量，**不可跨 agent 比**。旧数字 49%/73%/42% 全部作废。
3. **空 patch 死循环**：阶段1 跳过验证器时没有 `reward.txt`，旧的归档/`--skip-existing` 逻辑会把有 patch 的 job 反复归档或全量重跑。现行规则是「**有 reward 或 有 patch 都不归档、都跳过**」。判断「空 patch」必须看 `agent/model.patch` 是否 0 字节，不能只看 reward。
4. **tutanota 超配**：`tutao-51818218` r1/r2 在 v1 出现 `completed + verified + reward=0` 的**空 patch**，曾被误报为模型故障并算进「3 条故障」。重跑时注意该题的资源与上下文预算；**空 patch 不等于 API 故障**，只有 ECONNRESET 这类才是真故障（v1 仅 `vuls-f6cc8c-r1` 一条）。
5. **Docker 网络池耗尽**：并发 14 时 28 个网络必爆。跑前 `docker network prune -f`，并发 ≤ 6。
6. **PatchReplayAgent `source_job`**：必须传单个 trial 目录（`jobs/<job_name>`），不是整个 jobs 目录，否则「no source patch」、全 0 分。
7. **对比脚本读错目录**：Codex 的 patch 在 `jobs/`，`verify/jobs/` 只有 `replay.json`；比 patch 大小必须读 `jobs/`。
8. **PowerShell 引号地狱**：复杂 `python -c` 一律写成 .py 文件再执行。
9. **进程自杀**：`Where-Object { $_.CommandLine -match 'watchdog' }` 会匹配到自己（命令行含该字符串），导致 exit 4294967295。用 `-like '*watchdog.ps1*' -and $_.ProcessId -ne $PID`。
10. **别用会漂移的 `auto/...` 泛指别名**：实测 40% 请求落到 glm（见 [ROUTING-DRIFT](docs/ROUTING-DRIFT-20261029.md)）。
11. **别把 `context_length` 配小**：hy3 实际 192k；曾误配 65536 导致长任务早摘要。
12. **报告 `pass@1` 必须带 Wilson CI 与样本量**；只说「通过率 52%」会误导。
13. **Docker / 网络偶发 TLS 失败**（`uv` 下载 `curl exit=18`、`git push` SSL 握手），重试或重启 Docker Desktop。

## 目录速览

`docs/` 现行方案、协议与状态（作废文档在 `docs/archive/`，索引见 [archive/README](docs/archive/README.md)）· `scripts/` 现行跑批/统计工具与历史工具（见 [scripts/README](scripts/README.md)）· `studies/` 现行配置与题集（见 [studies/README](studies/README.md)）· `src/sayacode_bench/` 核心库 · `tests/` 行为测试。
