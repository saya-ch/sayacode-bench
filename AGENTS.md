# AGENTS.md — 仓库维护须知

给在本仓库工作的 AI 与人。**动态维护：发现信息过时或失效，立即更新或删除，不要留着误导后来者。**

## 必须遵守

1. **维护文档**：每次实验或方案变更后，更新 `docs/`（尤其 [EVALUATION-PLAN](docs/EVALUATION-PLAN-20261030.md)、[ITERATION-WORKFLOW](docs/ITERATION-WORKFLOW.md)、[STATUS](docs/STATUS.md)），并把数字/结论写进台账。被推翻的结论要显式标「已作废」及原因，不要静默删改。
2. **时常推送**：完成一批改动就 `git commit` + `git push origin main`，不要在本地长期累积未推送的提交。
3. **跑前汇报配置**：每次评测启动前用 `python scripts/profile_summary.py <profile>` 汇报模型 / 上下文 / 摘要触发点并取得确认（见 ITERATION-WORKFLOW §8）。
4. **诚实边界**：开发期数字不当正式成绩；作废数字不引用；过程指标（步数/token/改测试）只作诊断，不作「模型更强」的证据。

## 环境事实（确认无疑）

- 模型网关：Magpie，host `127.0.0.1:3425/v1`，容器内经 `saya-model-gateway:8080`（支持 `/v1/messages`、`/v1/chat/completions`、`/v1/responses`）。
- 暂定只用 **hy3**（`auto-hy3`），上下文 **192,000** / 输出 16,000。
- 只用 **SWE-bench Pro V2**（642 题，排除 123 musl → **519 可评测**）；暂不使用 Terminal-Bench。
- Docker 内存 8GB，单容器约 1.5GB → 并发建议 ≤4。
- 迭代题集：`studies/sample-40.json`（seed `saya-eval-20261030`，可复现）。

## 常见坑

- 别用会漂移的 `auto/...` 泛指别名——实测 40% 请求落到 glm（见 [ROUTING-DRIFT](docs/ROUTING-DRIFT-20261029.md)）。
- 别把 `context_length` 配小（hy3 实际 192k；曾误配 65536 导致长任务早摘要）。
- 跑批用唯一 job 名，避免 Harbor「身份不符」拒绝；中断后用 `--skip-existing` 续跑，旧未完成 job 会被归档。
- Docker / 网络偶发 TLS 失败（`uv` 下载 `curl exit=18`、`git push` SSL 握手），重试或重启 Docker Desktop。
- 报告 `pass@1` 必须带 Wilson CI 与样本量；只说「通过率 52%」会误导。

## 目录速览

`docs/` 方案与协议 · `scripts/` 迭代工具 · `studies/` 题集清单 · `src/sayacode_bench/` 核心库 · `tests/` 行为测试。
