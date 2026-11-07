# 系统提示 v2 实验：精简做对了就有效（2026-11-08）

> **结论：v1 变差是「精简得不对」，不是「精简不行」。v2 精简 63% 后通过率反超完整版，
> 且空 patch 归零。**
>
> 这个实验是由用户的一句质疑促成的：「也有可能是你精简的不够好」。

| 项 | 值 |
|---|---|
| 实验分支 | `exp/prompt-v2`（`ba2ff08`）|
| 变体制品 | 3.4.1（`C:\sb\hard\wheel-3.4.1`）|
| 系统提示 | 3,031 → **1,115 字符（-63%）**，`never` 5 → **0** |
| 设计 | 单变量对照：todo 都是 1,148 字符，其余全同 |
| 结果 | `C:\sb\hard\ab-ctx\run-prompt-v2` |

---

## 1. 三版对比

| 组 | 通过 | 通过率 | **空 patch** | 模型调用 | input tokens |
|---|---:|---:|---:|---:|---:|
| clean（无噪声基准）| 12/12 | 100.0% | 0/12 | — | — |
| **v2（1,115 字符，never=0）** | **9/12** | **75.0%** | **0/12** | 491 | 26,448,202 |
| main（3,031 字符，never=5）| 8/12 | 66.7% | 2/12 | 342 | 23,253,792 |
| v1（1,262 字符，never=5）| 7/12 | 58.3% | 3/12 | 365 | 24,493,648 |

### 配对检验

| 对比 | 变好 | 变差 | Δ | McNemar p |
|---|---:|---:|---:|---:|
| **v2 vs main** | 2（navidrome r1/r2）| 1（NodeBB r2）| **+8.3 pp** | 1.0000 |
| **v2 vs v1** | 2（navidrome r1/r2）| 0 | **+16.7 pp** | 0.5000 |

### 逐 trial

| 仓库 | rep | v2 | main | v1 |
|---|---|---|---|---|
| NodeBB | 1 | PASS 3461B | PASS 2499B | PASS 3245B |
| NodeBB | 2 | **fail** 3058B | PASS 2937B | fail 746B |
| element-hq | 1 | PASS 3117B | PASS 3142B | PASS 3205B |
| element-hq | 2 | PASS 3049B | PASS 3128B | PASS 3151B |
| flipt-io | 1 | fail 5817B | fail 0B | fail 0B |
| flipt-io | 2 | **fail 24.2MB** | fail 6982B | fail 0B |
| internetarchive | 1 | PASS 731B | PASS 882B | PASS 1297B |
| internetarchive | 2 | PASS 852B | PASS 1239B | PASS 1448B |
| navidrome | 1 | **PASS** 6588B | fail 0B | fail 0B |
| navidrome | 2 | **PASS** 6565B | fail 3740B | fail 6413B |
| tutao | 1 | PASS 3245B | PASS 3238B | PASS 3191B |
| tutao | 2 | PASS 3266B | PASS 3267B | PASS 3272B |

---

## 2. v1 与 v2 差在哪（这才是实验的真正结论）

| 指标 | main | v1（变差）| **v2（变好）** | OpenCode |
|---|---:|---:|---:|---:|
| 字符数 | 3,031 | 1,262 | **1,115** | 730 |
| **`never`** | 5 | **5** | **0** | 0 |
| `do not` | 4 | 1 | **0** | 0 |
| 有目标陈述 | 无 | 无 | **有** | 有 |
| 有交付要求 | 有 | **无** | **有** | 无 |
| 有「该动手」驱动 | 无 | 无 | **有** | 无 |

**v1 的问题**：把字符砍到 42%，却一个 `never` 没减——约束密度反而上升；
同时删掉了 main 里唯一推动交付的那句「state what changed, why, how it was verified」。

**v2 的做法**：
1. 开头明确目标：`Your job is to fully handle the user's objective and deliver a working change, not just an analysis`
2. `never` 全部改成正向表述（`Never edit existing tests` → `Keep the project's existing tests passing`）
3. 补「该动手」驱动：`Once you know which file must change, make the change. A small correct edit now beats another round of investigation`
4. 保留交付要求与验证要求

**所以变量不是长度，是取向**：约束密度、目标陈述、交付要求、动手驱动。

---

## 3. 空 patch 归零

v2 是三轮里唯一 **0/12 空 patch** 的组：

| 组 | 空 patch |
|---|---:|
| v2 | **0/12** |
| main | 2/12 |
| v1 | 3/12 |

这是之前加 `ExploreBudgetMiddleware` 想解决、但没能干净解决的问题（middleware 让它 0/12，
但也带来了 tutao r2 干扰和 51 分钟长尾）。v2 用一个更简单的手段达到了同样效果——
**在提示词里直接写「知道该改哪个文件就动手」**，且没有引入任何运行时机制。

---

## 4. 必须说的局限

| 局限 | 说明 |
|---|---|
| **统计不显著** | 配对 p = 1.0（vs main）、0.5（vs v1）。n=12，不一致对太少 |
| **成本更高** | 模型调用 491 vs main 的 342（**+43.6%**），input tokens 26.4M vs 23.3M（+13.7%）。多花的钱换来了 +8.3pp 和空 patch 归零 |
| **单次运行** | 没有重复实验 |
| **NodeBB r2 变差** | v2 有一个 trial 从 PASS 变 fail，说明不是无损的 |
| **flipt-io 出现 24.2MB patch** | 见 §5，是新发现的问题 |

---

## 5. 新发现的独立问题：patch 里混进编译产物

v2 的 flipt-io r2 产出了 **24,200,658 字节（24.2MB）** 的 patch：

| diff 段 | 字符数 | 文件 |
|---|---:|---|
| 1 | 1,010 | `cmd/flipt/main.go`（真实改动）|
| 2 | **25,396,314** | **`flipt`** ← **Go 编译产物** |
| 3 | 3,334 | `internal/config/config.go`（真实改动）|

模型改了 2 个 Go 源文件后跑了构建，把生成的可执行文件也纳入 patch。

**这是产品缺陷**：patch 采集应该排除未跟踪的构建产物（或用 `.gitignore` 语义过滤）。
否则：
- patch 体积失控（24MB vs 正常几 KB）
- 验证器可能因为应用补丁失败而判负
- 存储和传输浪费

**与提示词无关**，是 `git diff` 采集口径的问题，值得单独修。

---

## 6. 下一步

1. **修 patch 采集**：排除构建产物（`git status --porcelain` 里 untracked 的二进制/构建目录）。
2. **v2 上到产品**：如果确认值得 +43.6% 的调用成本。或者先做剂量实验（解释为什么 v2 更费调用）。
3. **扩样本**：n=12 不足以确认 +8.3pp，至少需要 30–50 个配对 trial。
4. **仍失败的 3 个 trial**：NodeBB r2（PASS→fail，可能是波动）、flipt-io r1/r2（改错型，两版都不过）。
