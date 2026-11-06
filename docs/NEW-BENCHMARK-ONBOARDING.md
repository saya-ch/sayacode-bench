# 新题库接入指南（2026-11-06，基于 SWE-EVO 实战）

> 背景：现有 40 题（SWE-bench Pro V2 子集）已被证明**饱和**——65% 的题所有 agent
> 部分得分满分、只有 8 题有区分度、2 题环境性不可过。详见
> [DEEP-ANALYSIS-20261106](DEEP-ANALYSIS-20261106.md)。因此必须换更难的题库。
>
> 本文记录接入 SWE-EVO 时踩到的全部坑与可复用流程。

## 1. 接入流程（四步）

```
1) 转换   scripts/convert_swe_evo.py       数据集 → Harbor task 目录
2) 基线验证 scripts/verify_task_baseline.py  不打 patch 跑官方判定，剔假题 + 过滤 p2p
3) 组题   scripts/compose_swe_evo_sample.py  usable 题 → sample json
4) 跑批   scripts/run_formal_240.py + verify_patches.py（用 SAYACODE_BENCH_TASKS_ROOT 指向新题库）
```

## 2. SWE-EVO 数据集本身的问题（必须先筛）

| 问题 | 表现 | 后果 |
|---|---|---|
| **假题** | `test_patch` 为空的题，FAIL_TO_PASS 在基线就全过 | 对任何 agent 都白送分 |
| **p2p 大面积基线失败** | dask 那题 2861 个 p2p 只有 1222 个基线通过（57% 失败） | 要求 p2p 全过则任何 agent 都不可能通过 |
| **test_patch 混入 CI 配置** | dask 的补丁含 `.github/workflows/tests.yml`，上下文对不上 | 整个 `git apply` 失败 |
| **镜像版本不匹配** | `ghcr.io/epoch-research/swe-bench.eval.*` 是 SWE-bench 原始镜像（如 `psf__requests-2931`），而 SWE-EVO 的题是版本演进（`v2.9.0→v2.9.1`） | 6 题直接不可用 |

**结论**：任何新题库接入，**基线验证是硬门槛**，不能跳。

### 2.1 基线验证判定表

| verdict | 条件 | 处置 |
|---|---|---|
| `fake` | f2p 在基线**全部**通过 | 剔除 |
| `usable` | f2p 至少一个基线失败 | 保留，并把基线失败的 p2p 从 config 删除 |
| `broken` | 镜像拉不到 / test_patch 完全应用不上 | 剔除 |

## 3. 六个工程坑（都已修在转换器里）

1. **CRLF**：Windows 上 `Path.write_text` 默认写 `\r\n`，bash 脚本报 `syntax error: unexpected end of file`。
   必须 `newline="\n"`。
2. **Python 3.8**：镜像内是 3.8，`dict[str, str]` 这类 PEP 585 注解会在定义时抛
   `TypeError: 'type' object is not subscriptable`。parser 里不能用现代泛型注解。
3. **`/logs/verifier` 不存在**：test.sh 把测试输出重定向到 `/logs/verifier/test.log`，
   但手工 `docker run` 没有 Harbor 的目录 → 写入失败 → parser 读到空文件 → 全 0。
   test.sh 开头必须 `mkdir -p /logs/verifier`。
4. **test_patch 的 CI 文件**：只保留测试相关文件的补丁块（`filter_test_patch`），
   并用 `git apply --reject` 容忍个别 hunk 失败。
5. **pytest 两种输出格式**：`-rA` 是 `PASSED path::test`（行首），
   `-vv -o console_output_style=classic` 是 `path::test PASSED [12%]`（行尾）。
   parser 必须两种都认，否则会出现「明明 4920 passed，parser 却报 0」。
6. **task 目录名必须短且合法**：`sweevo-iterative__dvc_1.11.12_1.11.13` 被 Harbor
   slug 化后可能以 `-` 结尾，与 `__<random>__env-main` 拼成 `-__`，
   Docker 报 `invalid reference format`。用 `scripts/rename_tasks_short.py` 改成纯小写短横线名。

## 4. 网络：Docker Hub 需要 daemon 级代理

Docker Desktop 的 VPNKit 代理（`http.docker.internal:3128`）会转发系统代理，
但 Clash 端口变动后（7890 → 7897）转发链路会断，表现为拉取 `EOF`。

**修复**：在 `C:\ProgramData\Docker\config\daemon.json` 直接配代理后重启 Docker Desktop：

```json
{
  "proxies": {
    "http-proxy": "http://127.0.0.1:7897",
    "https-proxy": "http://127.0.0.1:7897",
    "no-proxy": "localhost,127.0.0.1,host.docker.internal,*.local"
  }
}
```

## 5. 新题库准入清单（建议写进流程）

- [ ] 镜像可拉取（Docker Hub / ghcr 至少一个通道通）
- [ ] `base_commit` 与镜像 HEAD 一致（或镜像里含该 commit）
- [ ] 跑基线：**f2p 至少一个失败**（否则是假题）
- [ ] 跑基线：记录基线失败的 p2p 并剔除
- [ ] 每镜像体量 × 并发数 ≤ 磁盘余量（当前 C: 约 30GB，需滚动执行）
- [ ] 单题耗时估得出（决定并发与 ETA）

## 6. 当前状态（2026-11-06）

- 48 题已转换并改成短名；4 个 dvc 题 + 1 个 dask 题通过基线验证（usable）；
  `pydantic v2.7.1` 确认是假题；`ghcr.io/epoch-research` 6 题不可用。
- pilot 正在跑：5 题 × 2 重复 = 10 trial，结果根 `C:\sb\newset\runs\pilot1`。
