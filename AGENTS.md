# AGENTS.md — 仓库维护须知

给在本仓库工作的 AI 与人。**动态维护：发现信息过时或失效，立即更新或删除，不要留着误导后来者。**

## 必须遵守

1. **维护文档**：每次实验或方案变更后，更新 [STATUS](docs/STATUS.md)、[HANDOFF](docs/HANDOFF.md)、[RETROSPECTIVE](docs/RETROSPECTIVE-20261105.md)，必要时更新 [EVALUATION-PLAN](docs/EVALUATION-PLAN-20261030.md)、[ITERATION-WORKFLOW](docs/ITERATION-WORKFLOW.md)。被推翻的结论要显式标「已作废」及原因，并移到 `docs/archive/`；不要静默删改，也不要在 `docs/` 根继续摆着作废文档。**真实踩坑写进 [LESSONS](docs/LESSONS-20261102-v2.md)**（现象/根因/处置/预防），不要只留在聊天记录里。**新坑同时补进本文件「常见坑」**——两份都要写，缺一份就会丢。
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
  - **题集深度必须随结论声明**：40 题组里 patch 中位 **2 个文件 / 64 行**（SAYACODE 62% 的 trial 只碰 1–2 文件）。对照 SWE-EVO 平均 21 文件、SWE-Bench ProMax 平均 11.4 文件/261.6 行。**四组压在 67.5–80.0% 很可能是题太浅，不是"模型都一样强"。**
- **开发迭代集**：`studies/sample-40-final.json`（40 题，按仓库分层 + seed 可复现）。**gold-check 实际是 36 good / 1 bad / 3 null**，不是「40 题全绿」；bad 题不在 40 题内，3 个 null 需补齐或替换。
  - ⚠️ 它是**开发集，不是 holdout**。`protocol.md` 要求最终成绩来自冻结的 holdout/validation，而**独立 holdout 从未执行**；SAYACODE 的提示词规则（R1–R5）正是从这 40 题的失败个案调出来的（`C:\develop\sayacode\docs\PROMPT-OVERFIT-RISK.md`）。引用任何分数时必须声明这一点。
- **评测制品身份（最容易搞错）**：所有 SAYACODE 正式数字跑的是**本地构建的 `sayacode-3.2.5-py3-none-any.whl`**（`scripts/locked_agents.py:48`）。**PyPI 上从未发布 3.2.5 / 3.2.6**，序列是 `… 3.2.4 → 3.2.7`。产品 HEAD 已含 3 个版本的产品修复（`summary.py` / `graph.py` / `prompts.py`），**都没进被测制品** → 不能说「78.8% 是 PyPI 版本的分数」，也不能说「修复带来提升」（无评测证据，只有单题对照）。
- **基线（v4 现状）**：mini-swe / Claude Code / OpenCode 三组可用；**Codex 整组作废**（`apply_patch` 不可用 373 次、`/v1/responses` websocket 405 960 次），不参与任何排名。各脚手架与 hy3 的原生适配度未被统一，组间比较只统一了模型变量。
- **容器内存实测**（50 trial 采样）：空载 3–5MB；agent 执行阶段 140–500MB；**验证器阶段峰值可达 2.26GB**（vuls）；任务差异远大于 agent 差异。
- **阶段耗时实测**（50 trial）：environment_setup 8s（1%）、agent_setup 172s（22.5%）、**agent_execution 540s（70.5%，低内存）**、verifier 46s（6%，高内存）。单 trial 均值 12.8 分钟。
- **并发策略（2026-11 实测）**：轻题 **2–4** + 验证器限流 1；**重题（vuls 3.3GB）并发 1，必须先 `split_sample.py` 分片**。历史上限 12 是旧环境调优值；WSL 上限 7GB，超了就静默 OOM（日志只剩心跳）。
- **Docker 崩溃根因**（实测 2026-10-30）：主机物理内存 15.6GB 被 Docker VM（提交 6.9GB）+ 桌面应用 + 系统吃满，提交内存冲到 53.6GB、页面文件峰值 13.8GB → WSL 后端被压垮。**关掉 ChatGPT/WorkBuddy/codex 桌面应用可释放约 2.4GB**。崩溃后 `wsl --shutdown` + 重启 Docker + `--skip-existing` 续跑。
- **Docker 磁盘**：构建缓存与旧镜像可回收约 **142GB**（`docker system prune -a` 前先确认没有要保留的镜像；这是实测可回收量，不是当前占用）。
- **网络**：Clash Verge 已开 TUN + fake-ip；规则模板 `profiles/rNSaXJaGi0rv.yaml` 已加国内镜像（tuna/aliyun/ustc/tencent/huawei）**DIRECT** 规则——否则国内源被代理拖到 30KB/s。改规则后需重启 Clash Verge 生效。
- **每个 trial 占 2 个 Docker 网络**（`instance_*__env_default` + `saya-isolated-*`），默认地址池约 17 个；跑批前后必须 `docker network prune -f`，否则「all predefined address pools have been fully subnetted」。
- 结果目录：v1 在 `C:\sb\hard\formal-240`；**v2/v3/v4 同在 `C:\sb\hard\v2-325`**（按产物文件区分：`FINAL-SUMMARY.json` 是三组历史，`FINAL-SUMMARY-V4.json` + `STRICT-COMPARE.json` + `TRAJ-AUDIT-*.json` 是四组当前权威；旧 `v2` 是 3.2.4 预览批次，已归档）。

## 常见坑

1. **分母三套（最严重的坑）**：v1 的 SAYACODE 55/80、mini-swe 69/80、Codex **56/65** 被并列成 68.8%/86.2%/86.2%，制造 17.4pp 假差距；Codex 统一 80 分母是 **70.0%**。任何对比表分母必须一致，缺 trial 就写 79/80，不换分母。
2. **改测试 / 改快照的口径**：verifier 会重置**测试代码**（`tests/`、`*_test.go` 等），所以「patch 含测试文件」绝大部分对分数无效，**不能当作弊指标**；只有 `__snapshots__/*.snap` 不被重置、改它才有效（见坑 24）。历史上把「产品侧检测率 48.8%（39/80）」与「patch 含测试 0% / 70.9% / 54.2%」并列是两个不同的量，旧数字 49%/73%/42% 全部作废。
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
14. **apt 502 是 Clash TUN/fake-ip 问题**：`deb.debian.org` / `archive.ubuntu.com` 返回 502 `[IP: 198.18.x.x]`。修法是改 **Clash Verge profile 的 `prepend`**（`profiles/rNSaXJaGi0rv.yaml`）加 `DOMAIN-SUFFIX,debian.org,DIRECT` 等；**Merge.yaml 的 prepend-rules 不生效**。改完重启 Clash。
15. **给容器注入代理必须补 NO_PROXY**：Docker CLI 的 `proxies` 会把 `HTTP(S)_PROXY` 注入所有容器；`NO_PROXY` 必须含 `saya-model-gateway`、`saya-gateway` 与私网段，否则 agent 调内部网关报 `gaierror`、patch=0。更稳的是**无代理直连**（实测 astral.sh 直连可用）。
16. **astral.sh `curl exit=35` 是间歇性 TLS 失败**（不是被墙，宿主实测 301）；补跑成功率高，下一批应把 uv installer 预置进镜像。
17. **阶段1 续跑判据**：`--skip-verifier` 完成时只有 `normalized.json`（无 reward/terminal），skip 判据必须认 `record_complete=True`，否则重复进入 `run_official_trial` 撞 `ValueError`。
18. **`verify_patches.collect_pending` 只认 stage1 的 reward**（不看 `verify/jobs/`），重跑 verify 会报「已 verified 冲突」；临时办法是把 verify 的 `reward.txt` 同步回 stage1 jobs，长期应在代码里修。
19. **stage1 与 verify 不要并行**：验证器峰值 2.26GB，并行会把宿主压到 <0.6GB，kill 后留下「未收尾 Harbor job」，后续 verify 连锁 ValueError。
20. **归档与 retry sample 必须同源**：先列要补的 job，再由同一清单生成 `--sample`，最后归档；否则会出现「归档 28 个、sample 只覆盖 8 题」的 22 条 `no_job`。
21. **`.wslconfig` 只能合并、不能覆盖**：原文件有 `networkingMode=mirrored`、`dnsTunneling`、`firewall`、`autoProxy`，覆盖会让容器网络失效；改前备份，改后用 `docker info` 的 MemTotal 验证。
22. **Docker vhdx 删镜像不缩容**：`docker_data.vhdx` 是稀疏文件，删镜像后 C: 不会自动涨；需管理员 `diskpart compact vdisk`（脚本 `C:\sb\hard\v2\logs\compact-docker-vhdx.ps1`）。
23. **补跑后数字会变**：v2 中 SAYACODE 67.5%→78.8%、mini-swe 47.5%→70.0%；任何 >1pp 变化都要更新报告，不能拿补跑前快照当终版。
24. **`.snap` 快照不被 verifier 重置**：`tests/test.sh` 只 reset 测试**代码**目录（`tests`/`spec`/`__tests__` 等，`git checkout HEAD`），`__snapshots__` 属 data 目录被**排除、不重置**。真正「靠改快照通过」的 v4 计数是 mini-swe 4、Claude Code 3、OpenCode 6、**SAYACODE 0**。**主表必须同时给 planned 与 strict**（strict = planned 扣掉 snap pass），因为三种口径给三种排名；**不要只报 planned**。详见 [TEST-EDIT-ANALYSIS](docs/TEST-EDIT-ANALYSIS-20261102.md) 与 [STRICT-COMPARE 脚本](scripts/strict_compare.py)。
25. **`team_enabled=False` 时必须裁剪系统提示的 Dispatch 段**：否则模型会反复探测团队工具、甚至谎称已派发（浪费 token、污染轨迹）。已修 `prompts.py` 并新增测试；改提示模板时务必保持该裁剪。
26. **`evals.run` 用 CLI subprocess 调 docker，在「Python 子进程无法访问 npipe」的环境不可用**：`python -m evals.run` 会报 `permission denied ... npipe:////./pipe/dockerDesktopLinuxEngine`（DSH 沙箱限制子进程访问 named pipe）。已加 `evals/docker_backend.py`（SDK + CLI 回退）；仍失败时按 [COLLABORATION-CHECK](docs/COLLABORATION-CHECK-20261102.md) 手动复刻流程。
27. **网关曾拦掉带 query 的请求**：`network.py` 里 `if ($args != "") { return 400; }` 让 Claude Code 的 `?beta=true` 首个请求即 400（该组 0 通过）。现只保留精确路径白名单，**不要再加全局 query 拦截**。
28. **Clash fake-ip 的 CNAME 陷阱**：`deb.debian.org` 实际 CNAME 到 `debian.map.fastlydns.net`（二级子域），`DOMAIN-SUFFIX,fastlydns.net` **不匹配**，必须写 `+.fastlydns.net`。同理 `*.x` 只匹配一级子域。
29. **Debian 12 PEP 668**：`pip3 install` 被系统 Python 拒绝，需 `--break-system-packages`；容器内安装链必须先探测再选路径。
30. **uv 下 CPython 走 GitHub 会超时**：预下载 tarball 上传到 `/opt/uv-python` 再让 uv 指向本地，不要依赖容器内 `uv python install`。
31. **重题会静默打爆 WSL**：vuls 单题 3.3GB，并发 2 × WSL 7GB → 进程被宿主 OOM 杀死，日志只剩心跳行（看起来像"卡住"）。用 `scripts/split_sample.py` 按重仓库分片，重题并发 1。
32. **只看 `exception.txt` 会系统性低估适配缺陷**：必须跑 `scripts/audit_agent_traj.py` 做全量轨迹审计（unsupported call / API error / websocket 405 / tool_use 配平）。Codex 组（78/80 trial 的 `apply_patch` 不可用）就是这样判出整组作废的；只看 reward 会误判成"能力差"。

## 目录速览

`docs/` 现行方案、协议与状态（作废文档在 `docs/archive/`，索引见 [archive/README](docs/archive/README.md)）· `scripts/` 现行跑批/统计工具与历史工具（见 [scripts/README](scripts/README.md)）· `studies/` 现行配置与题集（见 [studies/README](studies/README.md)）· `src/sayacode_bench/` 核心库 · `tests/` 行为测试。
